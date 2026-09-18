"""MCP facade server: five tools over stdio — governed + ad-hoc metrics.

Exactly five tools (spec §4):

    list_metrics()                     -> served governed metrics with descriptions
    list_datasets()                    -> [{name, columns: [{name, type}]}] from the attach
    search_context(query)              -> ranked matches over context_layer/**/*.md
    get_metric(name, dimensions, range)-> rows PLUS the compiled SQL (provenance), governed: true
    define_metric(definition)          -> the ad-hoc path (spec rev 3): ephemeral OSI model ->
                                          render -> read-only execution -> rows + SQL +
                                          governed: false + auto-staged proposal

Mechanism per ADR-0008 (spec rev 7): our own sqlglot compiler
(:mod:`ariadne.render`) renders the OSI envelope model to SQL and the
facade-owned DuckDB connection — built by the shared source-registry builder
(:mod:`ariadne.sources`, ADR-0010: a ``ariadne.yaml`` registry, or the legacy
``--db`` SQLite file attached read-only as catalog ``demo``) — executes it.
``range`` is an optional ``{start, end}`` applied by the compiler to the
model's primary date dimension (the is_time field).
``list_metrics``/``list_datasets`` read the envelope metadata and the attach
directly — no datus anywhere in the runtime.

Ad-hoc (ADR-0005, spec §6): ``define_metric`` params are expanded into an
ephemeral OSI-core model (version 0.2.0.dev0 shape, dialects-expression fields,
is_time dimension), rendered by :mod:`ariadne.render` (no files touched — the
served semantic dir is never written). Compile failure returns the compiler's
error verbatim; nothing is staged, nothing executed. On success the compiled SQL
is executed read-only and the definition is auto-staged as a proposal: the OSI
model under ``staging/semantic_layer/models/adhoc/`` plus a minimal OKF draft
under ``staging/context_layer/metrics/`` so ``search_context`` can discover it
(numeric suffix on name collision, never overwrite); promotion stays human
(ADR-0003).

Routing contract (spec rev 4 §8.12): fresh consuming agents discover the ad-hoc
path through the facade itself — ``list_metrics`` ends with the routing hint,
the unknown-metric error names ``list_datasets()`` + ``define_metric``, and the
tool descriptions carry the same language (the MCP registry is the agent's map).

No-unvalidated-execution invariant (spec §6): the DuckDB executor only ever
receives SQL returned by the render compile step — there is no code path from
tool arguments to ``duckdb.execute`` that bypasses the compiler.

Invariants and failure behavior (spec §6/§7): ``get_metric`` accepts only named
governed metrics — never raw SQL; unknown metric -> error listing the available
metrics and naming the ad-hoc path (``list_datasets()`` + ``define_metric``);
unrenderable served models -> fail fast at startup; an environment that
actively blocks the retired datus packages -> fail fast with the historical
install hint.

Usage::

    python -m ariadne.serve --db examples/retail-demo/data/demo.db \\
        --semantic semantic_layer --context context_layer
"""

import argparse
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

# The grain guard lives in ariadne.grain (shared with the validate audit — mvp-5
# round 2 convergence); GRAIN_GUIDANCE is re-exported for backward compatibility
# (tests and the tool text import it from this module).
from ariadne.grain import GRAIN_GUIDANCE, check_grain_preserving  # noqa: F401 — re-export

# (the pyright ignore below: the analyzer may bind `ariadne` to a copy predating
# this lane's render module — see ADR-0008; runtime and uvx pyright resolve it)
from ariadne.render import render  # pyright: ignore[reportMissingImports]

# ADR-0010: the facade's DuckDB session comes from the shared registry builder
# (ariadne.yaml --sources, or the legacy --db single-sqlite shorthand).
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    build_connection,
    default_registry_path,
    implicit_registry,
    load_registry,
)

# ADR-0008: the compile path is ariadne.render (own sqlglot compiler) — datus is
# no longer imported at all. The historical spec §7 fail-fast contract stays
# testable: an environment that ACTIVELY BLOCKS datus (the ``sys.modules[name] =
# None`` sentinel the offline tests install) still surfaces the original install
# hint at Facade init, while a plain datus-free install serves through render().
_DATUS_IMPORT_ERROR: ImportError | None = (
    ImportError("import of datus_semantic_osi halted; None in sys.modules")
    if sys.modules.get("datus_semantic_osi", 1) is None
    else None
)

INSTALL_HINT = (
    "datus-semantic-osi is required to serve governed metrics "
    "(uv pip install 'datus-semantic-osi[metricflow]' on Python 3.12)"
)

# Spec rev 4 §8.12: the explicit route for questions no governed metric answers.
# Shared by list_metrics' trailing hint and the unknown-metric error so both
# name the same two tools.
ROUTING_HINT = (
    "If no governed metric above answers your question, route it to the ad-hoc path: "
    "call list_datasets() to see the queryable tables, then define_metric(definition) "
    "to compute the answer (compiled, executed read-only, auto-staged for human promotion)."
)

# MetricFlow's metric-name schema, enforced again at lowering time — reject up
# front with an actionable message (lowercase snake_case, no double underscore).
_SLUG_RE = re.compile(r"[a-z][a-z0-9_]*[a-z0-9]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def assert_single_statement(sql: str) -> None:
    """Spec §6 no-unvalidated-execution invariant: the executor receives exactly
    one statement. Uses duckdb's own parser (extract_statements), so semicolons
    inside string literals cannot false-positive; an unparseable compiled SQL is
    likewise rejected — nothing reaches a duckdb call un-parsed. Runs on the
    compiled SQL after the Datus gate and BEFORE any duckdb call (EXPLAIN or
    execution): both paths share this choke point, so no future code path can
    reintroduce multi-statement SQL. Rejection: nothing staged, nothing executed."""
    try:
        count = len(duckdb.extract_statements(sql))
    except Exception as exc:  # parse error — the SQL can never be one valid statement
        raise ValueError(f"{type(exc).__name__}: {exc}") from exc
    if count != 1:
        raise ValueError(
            f"compiled SQL must be exactly one statement, got {count} "
            "(no-unvalidated-execution invariant, spec §6); nothing staged, nothing executed"
        )


class Facade:
    """Governed + ad-hoc metric facade: render-gate compile + facade-owned DuckDB execution."""

    def __init__(
        self,
        semantic_dir: str | Path,
        context_dir: str | Path,
        db_path: str | Path,
        staging_dir: str | Path = "staging",
        sources: str | Path | None = None,
    ):
        if _DATUS_IMPORT_ERROR is not None:  # spec §7: fail fast with the hint
            raise RuntimeError(f"{INSTALL_HINT}: {_DATUS_IMPORT_ERROR}")

        self.context_dir = Path(context_dir)
        models = Path(semantic_dir) / "models"
        if not models.is_dir():
            raise RuntimeError(
                f"no semantic models under {models} — promote staging/semantic_layer/ first"
            )
        # Envelope metadata read directly (no datus): per metric, its description,
        # available dimensions (fields carrying a dimension flag — spec rev 4 §8.12)
        # and the single-entry envelope render() compiles.
        self._metrics: dict[str, Any] = {}
        for path in sorted(models.glob("*.yml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for model in doc.get("semantic_model") or []:
                dimension_names = {
                    field.get("name")
                    for dataset in model.get("datasets") or []
                    for field in dataset.get("fields") or []
                    if isinstance(field.get("dimension"), dict) and field.get("name")
                }
                for metric in model.get("metrics") or []:
                    name = metric.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    self._metrics[name] = {
                        "description": metric.get("description") or "",
                        "dimensions": sorted(dimension_names),
                        "model": {"version": doc.get("version"), "semantic_model": [model]},
                    }
        if not self._metrics:  # spec §7: nothing servable -> fail fast, not at query time
            raise RuntimeError(f"no governed metrics found under {models}")
        seen: list[dict] = []
        for entry in self._metrics.values():
            if not any(entry["model"] is candidate for candidate in seen):
                seen.append(entry["model"])
        try:
            for model in seen:
                render(model)
        except Exception as exc:
            raise RuntimeError(f"served OSI models under {models} do not compile: {exc}") from exc

        # ADR-0010: one shared builder produces the facade's long-lived DuckDB
        # session over the registry sources (addressable as <source>.<table>);
        # non-DuckDB attaches are connection-local, so this happens exactly
        # once. Compiled SQL references <catalog>.<schema>.<table> — the legacy
        # shorthand keeps the authoring contract's catalog name demo.
        registry = load_registry(sources) if sources is not None else implicit_registry(db_path)
        self.con, self.catalog = build_connection(registry)
        self._qualified = sources is not None
        if not self._qualified:
            # Bare table names in agent-authored ad-hoc sources resolve against the attach.
            self.con.execute("USE demo.main")
        self.staging_dir = Path(staging_dir)
        # Governed-path grain-guard memo: the served envelopes are loaded once here
        # and never re-read, so one passing check per metric holds for the facade's
        # lifetime (ponytail: one COUNT scan per join key, paid once per process;
        # re-key by model file mtime if served models ever hot-reload).
        self._grain_checked: set[str] = set()

    async def list_metrics(self) -> list[dict | str]:
        """Governed metrics with descriptions and available dimensions; the list
        ends with the explicit routing hint to the ad-hoc path (spec rev 4 §8.12)."""
        entries: list[dict | str] = [
            {
                "name": name,
                "description": meta["description"],
                "dimensions": meta["dimensions"],
            }
            for name, meta in self._metrics.items()
        ]
        entries.append(ROUTING_HINT)
        return entries

    async def list_datasets(self) -> list[dict]:
        """Every queryable table across all registry sources with its columns
        (the agent's map, spec rev 9 §8.20). The legacy --db shorthand keeps
        plain table names; a registry qualifies each entry as
        ``<source>.<table>`` so both sources stay distinguishable."""
        datasets: list[dict] = []
        for source in self.catalog:
            for table in source["tables"]:
                datasets.append(
                    {
                        "name": (
                            f"{source['name']}.{table['name']}"
                            if self._qualified
                            else table["name"]
                        ),
                        "columns": table["columns"],
                    }
                )
        return datasets

    async def get_metric(
        self,
        name: str,
        dimensions: list[str] | None = None,
        range: dict | None = None,  # noqa: A002 — spec §4 names the parameter
    ) -> dict:
        if name not in self._metrics:  # spec §7/rev 4: discovery before failure
            available = ", ".join(sorted(self._metrics))
            raise ValueError(
                f"unknown metric {name!r}; available metrics: {available}. {ROUTING_HINT}"
            )
        # Compiled by our sqlglot renderer (ADR-0008) from the served OSI models —
        # never tool input (spec §6): the executor only ever receives SQL returned
        # by the compile step. The statement guard is defense in depth on this
        # governed path too.
        sql = render(self._metrics[name]["model"], dimensions or [], range or {}, metric=name)
        # Choke point shared with the EXPLAIN bind-check below (spec §6): exactly
        # one statement at parse level before any duckdb call.
        assert_single_statement(sql)
        # Same gauntlet as the ad-hoc path (spec §8.9): the renderer compiles
        # structurally, so a column missing from the source only surfaces at bind
        # time. EXPLAIN binds the plan without executing it — while still only
        # ever feeding compiler output to duckdb.
        try:
            self.con.execute(f"EXPLAIN {sql}")  # nosemgrep — sql is render() output (spec §6)
        except Exception as exc:  # spec §7: the binder's text, verbatim (§8.9 holds:
            # the guard above guarantees nothing executed before this check).
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc
        # Grain guard on the model's dataset source (spec rev 5 §13): a fan-out
        # baked into a served model would aggregate at joined-row grain
        # (Datus-ai/Datus-agent#1426) — identical rejection contract to
        # define_metric. Memoized per metric (see __init__).
        if name not in self._grain_checked:
            (dataset,) = self._metrics[name]["model"]["semantic_model"][0].get("datasets") or []
            check_grain_preserving(self.con, dataset["source"])
            self._grain_checked.add(name)
        # sql is the render compile step's output and nothing else (spec §6).
        relation = self.con.sql(sql)
        columns = list(relation.columns)
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return {
            "metric": name,
            "dimensions": dimensions or [],
            "columns": columns,
            "rows": rows,
            "sql": sql,
            "governed": True,  # spec rev 3 §8.10: symmetry with define_metric
        }

    async def define_metric(self, definition: dict) -> dict:
        """Ad-hoc path (spec rev 3 §4/§5): draft -> compile gate -> execute -> stage.

        The definition is expanded into an ephemeral OSI model and rendered by
        ariadne.render; failure returns the compiler's error verbatim (nothing
        staged, nothing executed). On success the compiled SQL is executed
        read-only and the definition is auto-staged as a proposal (never
        auto-promoted).
        """
        params = _normalize_definition(definition)
        # Grain guard BEFORE envelope expansion/compile (spec rev 5 §13): a source
        # that fans out the fact grain is rejected outright — the compiler would
        # aggregate at joined-row grain (Datus-ai/Datus-agent#1426). Nothing staged,
        # nothing executed; same contract as the single-statement guard below.
        check_grain_preserving(self.con, params["source"])
        envelope = _expand_adhoc_model(params)
        sql = await self._compile_adhoc(envelope, params["name"], params["dimensions"])
        # Choke point shared by the EXPLAIN bind-check below and the execution
        # above it: exactly one statement, checked at parse level before any
        # duckdb call (a crafted source can otherwise smuggle DDL past EXPLAIN).
        assert_single_statement(sql)
        # The renderer compiles structurally without schema introspection, so a
        # column missing from the source only surfaces at bind time. EXPLAIN binds
        # the plan without executing it, keeping §8.9's "no execution" honest for
        # that shape — while still only ever feeding compiler output to duckdb.
        try:
            self.con.execute(f"EXPLAIN {sql}")  # nosemgrep — sql is render() output (spec §6)
        except Exception as exc:  # spec §7: the binder's text, verbatim (§8.9 holds:
            # the guard above guarantees nothing executed before this check).
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc
        # sql is the render compile step's output and nothing else (spec §6): the
        # definition reached execution exclusively through the compiler above.
        relation = self.con.sql(sql)
        columns = list(relation.columns)
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        staged_as = self._stage_atomic(
            self.staging_dir / "semantic_layer" / "models" / "adhoc",
            params["name"],
            ".yml",
            yaml.safe_dump(envelope, sort_keys=False).encode("utf-8"),
        )
        staged_page = self._stage_atomic(
            self.staging_dir / "context_layer" / "metrics",
            params["name"],
            ".md",
            _build_adhoc_page(params),
        )
        return {
            "metric": params["name"],
            "columns": columns,
            "rows": rows,
            "sql": sql,
            "governed": False,
            "definition": params,  # echoed definition
            "staged_as": str(staged_as),
            "staged_context_as": str(staged_page),
        }

    async def _compile_adhoc(self, envelope: dict, name: str, dimensions: list[str]) -> str:
        """Render-gate compile (ADR-0008) of the ephemeral model — the only gate
        between tool args and execution. Returns the compiled SQL; raises
        ValueError carrying the compiler's verbatim reason (spec §7). No files
        are touched: the envelope is compiled in memory; the served semantic dir
        and everything outside staging is never written."""
        try:
            return render(envelope, dimensions)
        except ValueError:
            raise  # RenderError already carries the verbatim reason (spec §7)
        except Exception as exc:  # defense in depth — surface it verbatim
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc

    def _stage_atomic(self, directory: Path, stem: str, ext: str, payload: bytes) -> Path:
        """Auto-stage one proposal artifact after successful execution (ADR-0003:
        promotion stays human). Numeric suffix on collision — never overwrites
        (spec §8.11): the O_CREAT|O_EXCL claim is atomic, so racing facade
        processes suffix off each other instead of overwriting (no
        exists()-then-write TOCTOU). Same discipline for the model (.yml) and
        the context page (.md) — spec rev 4 §4."""
        directory.mkdir(parents=True, exist_ok=True)
        candidate = directory / f"{stem}{ext}"
        suffix = 2
        while True:
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                candidate = directory / f"{stem}-{suffix}{ext}"
                suffix += 1
                continue
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
            return candidate

    async def search_context(self, query: str, limit: int = 10) -> list[dict]:
        """Rank OKF pages by query-term frequency (name-anchored ties by path).

        Scans the served context dir AND the staged context drafts
        (``staging/context_layer/**/*.md``) — spec rev 4 §4: define_metric
        drafts must be discoverable before promotion. Staged hits carry
        ``draft: true`` and served hits ``draft: false`` — a draft never
        masquerades as verified context (ADR-0003: promotion stays human)."""
        terms = query.lower().split()
        hits: list[dict] = []
        roots = [(self.context_dir, False), (self.staging_dir / "context_layer", True)]
        for root, draft in roots:
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                score = sum(text.lower().count(term) for term in terms)
                if not score:
                    continue
                hits.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "score": score,
                        "draft": draft,  # staged proposals stay distinguishable
                        "content": text,  # full OKF page: the rules are the payload
                    }
                )
        hits.sort(key=lambda hit: (-hit["score"], hit["path"]))
        return hits[:limit]


def _normalize_definition(definition: dict) -> dict:
    """Validate define_metric params and return the canonical echoed form."""
    if not isinstance(definition, dict):
        raise ValueError("define_metric expects a definition object")
    name = definition.get("name")
    if not isinstance(name, str) or "__" in name or not _SLUG_RE.fullmatch(name):
        raise ValueError(
            f"invalid metric name {name!r}: use a lowercase snake_case slug "
            "(letters, digits, single underscores, starting and ending alphanumeric)"
        )
    params: dict[str, Any] = {"name": name}
    for key in ("description", "source", "expression"):
        value = definition.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"define_metric requires a non-empty string {key!r}")
        params[key] = value
    dimensions = definition.get("dimensions") or []
    if not isinstance(dimensions, list) or not all(
        isinstance(d, str) and _IDENTIFIER_RE.fullmatch(d) for d in dimensions
    ):
        raise ValueError("'dimensions' must be a list of column-name identifiers")
    params["dimensions"] = dimensions
    time_field = definition.get("time_field")
    if time_field is not None:
        if not isinstance(time_field, str) or not _IDENTIFIER_RE.fullmatch(time_field):
            raise ValueError("'time_field' must be a column-name identifier")
        params["time_field"] = time_field
    return params


def _expand_adhoc_model(params: dict) -> dict:
    """Expand define_metric params into an ephemeral OSI-core model — the dialect
    per project/research/datus-spike.md §3.1 (version 0.2.0.dev0, dialects-expression
    fields, is_time dimension). ``source`` is a table name or SELECT (query
    sources pass through untouched); ``expression`` is the aggregate SQL. The
    definition alone carries any business filter — the facade adds nothing."""

    def field(name: str, is_time: bool = False) -> dict:
        spec: dict[str, Any] = {
            "name": name,
            "expression": {"dialects": [{"dialect": "ANSI_SQL", "expression": name}]},
        }
        spec["dimension"] = {"is_time": True} if is_time else {}
        return spec

    fields = [field(d) for d in params["dimensions"]]
    if "time_field" in params:
        fields.append(field(params["time_field"], is_time=True))
    return {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {
                "name": f"adhoc_{params['name']}",
                "description": params["description"],
                "datasets": [
                    {
                        "name": "adhoc_source",
                        "source": params["source"],
                        "fields": fields,
                    }
                ],
                "metrics": [
                    {
                        "name": params["name"],
                        "description": params["description"],
                        "expression": {
                            "dialects": [
                                {"dialect": "ANSI_SQL", "expression": params["expression"]}
                            ]
                        },
                    }
                ],
            }
        ],
    }


# Best-effort table refs in an agent-authored SELECT ("FROM demo.main.orders",
# "JOIN customers") for the draft page's provenance frontmatter.
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)


def _source_tables(source: str) -> list[str]:
    """Table names from the definition's source (a table name or SELECT). Best
    effort for exotic SQL — the staged OSI model stays the authoritative proposal."""
    if _IDENTIFIER_RE.fullmatch(source):
        return [source]
    return list(dict.fromkeys(t.rsplit(".", 1)[-1] for t in _TABLE_RE.findall(source)))


def _build_adhoc_page(params: dict) -> bytes:
    """Minimal OKF draft for the auto-staged proposal (spec rev 4 §4): frontmatter
    + name + description + dimensions + proposal marker, so ``search_context``
    can discover ad-hoc proposals and the human gate sees them in context."""
    frontmatter = yaml.safe_dump(
        {
            "type": "metric",
            "status": "draft",
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "sources": _source_tables(params["source"]),
        },
        sort_keys=False,
    )
    dimensions = "\n".join(f"- {d}" for d in (params["dimensions"] or ["(none)"]))
    return (
        f"---\n{frontmatter}---\n\n"
        f"# {params['name']}\n\n"
        f"{params['description']}\n\n"
        f"Dimensions:\n{dimensions}\n\n"
        "Auto-staged ad-hoc proposal awaiting promotion.\n"
    ).encode()


def build_app(facade: Facade):
    """Wire the facade onto an MCP stdio server: exactly five tools (spec §4)."""
    from mcp.server.fastmcp import (  # pyright: ignore[reportMissingImports, reportAttributeAccessIssue]
        FastMCP,  # mcp<2 (pinned) exports FastMCP; the 2.x shim renames it
    )

    app: FastMCP = FastMCP("ariadne")

    @app.tool()
    async def list_metrics() -> list[dict | str]:
        """List served governed metrics with descriptions and available dimensions.

        The response ends with a routing hint: questions no listed metric answers
        go to list_datasets() + define_metric (the ad-hoc path).
        """
        return await facade.list_metrics()

    @app.tool()
    async def search_context(query: str) -> list[dict]:
        """Search the Context Layer (OKF pages) for business rules; ranked matches.

        Includes auto-staged ad-hoc proposals awaiting promotion; those hits are
        marked draft: true (served pages are draft: false).
        """
        return await facade.search_context(query)

    @app.tool()
    async def get_metric(
        name: str, dimensions: list[str] | None = None, range: dict | None = None
    ) -> dict:
        """Rows plus compiled SQL for a named governed metric — never raw SQL.

        Args:
            name: governed metric name (see list_metrics).
            dimensions: dimensions to group by (e.g. ["region"]).
            range: optional {"start", "end"} dates on the primary date dimension.
        """
        return await facade.get_metric(name, dimensions, range)

    @app.tool()
    async def list_datasets() -> list[dict]:
        """List every table in the attached database with its columns and types.

        Pairs with define_metric: pick tables here, then define an ad-hoc metric
        for any question no governed metric answers.
        """
        return await facade.list_datasets()

    @app.tool()
    async def define_metric(definition: dict) -> dict:
        """Define an ad-hoc metric for a question no governed metric answers:
        compiled, executed read-only, auto-staged for human promotion.

        Args:
            definition: {name, description, source, expression, dimensions?, time_field?}
                where name is a lowercase snake_case slug, source is a table name or a
                SELECT (joins allowed), expression is an aggregate SQL expression
                (any business filter belongs in it), and dimensions/time_field are
                column names of the source. Joins must be grain-preserving: every
                join key must be unique on the joined side — resolve one-to-many
                relationships per the ADR-0006 rubric (upstream conditional pivot,
                child-grain fact model, or fact weight allocation), i.e. pre-aggregate
                the many side to the fact grain inside source, or the definition is
                rejected. Invalid definitions return the compiler
                errors verbatim; nothing is staged or executed. Success returns rows,
                the compiled SQL (provenance), governed: false, the echoed definition,
                and the staging paths of the auto-staged proposal (OSI model under
                semantic_layer/models/adhoc/ plus an OKF draft under
                context_layer/metrics/ that search_context can find).
        """
        return await facade.define_metric(definition)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.serve",
        description="MCP stdio facade over the served context and semantic layers.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite database to attach read-only (default: examples/retail-demo/data/demo.db when "
        "no --sources/ariadne.yaml applies)",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="source registry YAML (ADR-0010; default: ./ariadne.yaml only when "
        "neither --sources nor --db is given)",
    )
    parser.add_argument("--semantic", default="semantic_layer", help="served OSI layer directory")
    parser.add_argument("--context", default="context_layer", help="served OKF layer directory")
    parser.add_argument(
        "--staging", default="staging", help="staging root for auto-staged ad-hoc proposals"
    )
    args = parser.parse_args(argv)

    # Explicit --db/--sources always win over the ambient ./ariadne.yaml
    # (shared resolution, ADR-0010); the legacy default fills in only when
    # --db is not given (unused by the Facade whenever a registry applies).
    sources_path = default_registry_path(args.sources, args.db)
    db = args.db or "examples/retail-demo/data/demo.db"
    try:
        facade = Facade(
            args.semantic,
            args.context,
            db,
            staging_dir=args.staging,
            sources=sources_path,
        )
    except Exception as exc:  # fail fast before any MCP traffic
        print(f"error: {exc}", file=sys.stderr)
        return 1
    build_app(facade).run()  # stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MCP facade server: five tools over stdio — governed + ad-hoc metrics.

Exactly five tools (spec §4):

    list_metrics()                     -> served governed metrics with descriptions
    list_datasets()                    -> [{name, columns: [{name, type}]}] from the attach
    search_context(query)              -> ranked matches over context_layer/**/*.md
    get_metric(name, dimensions, range)-> rows PLUS the compiled SQL (provenance), governed: true
    define_metric(definition)          -> the ad-hoc path (spec rev 3): ephemeral OSI model ->
                                          Datus compile -> read-only execution -> rows + SQL +
                                          governed: false + auto-staged proposal

Mechanism per docs/research/datus-spike.md §5: Datus compiles the OSI metric to
SQL (``query_metrics(dry_run=True)`` -> ``metadata["sql"]``) and the
facade-owned DuckDB connection — with the SQLite database ATTACHed read-only as
catalog ``demo`` — executes it. ``range`` is an optional ``{start, end}`` applied
by the compiler to the metric's primary date dimension.

Ad-hoc (ADR-0005, spec §6): ``define_metric`` params are expanded into an
ephemeral OSI-core model (dialect per docs/research/datus-spike.md §3.1),
compiled by a dedicated DatusOSIAdapter over a temp directory (discarded after
each call — the served semantic dir is never touched). Compile failure returns
the compiler errors verbatim; nothing is staged, nothing executed. On success
the compiled SQL is executed read-only and the definition is auto-staged as a
proposal: the OSI model under ``staging/semantic_layer/models/adhoc/`` plus a
minimal OKF draft under ``staging/context_layer/metrics/`` so ``search_context``
can discover it (numeric suffix on name collision, never overwrite); promotion
stays human (ADR-0003).

Routing contract (spec rev 4 §8.12): fresh consuming agents discover the ad-hoc
path through the facade itself — ``list_metrics`` ends with the routing hint,
the unknown-metric error names ``list_datasets()`` + ``define_metric``, and the
tool descriptions carry the same language (the MCP registry is the agent's map).

No-unvalidated-execution invariant (spec §6): the DuckDB executor only ever
receives SQL returned by the Datus compile step — there is no code path from
tool arguments to ``duckdb.execute`` that bypasses the compiler.

Invariants and failure behavior (spec §6/§7): ``get_metric`` accepts only named
governed metrics — never raw SQL; unknown metric -> error listing the available
metrics and naming the ad-hoc path (``list_datasets()`` + ``define_metric``);
Datus absent/broken or no served models -> fail fast at startup with an
install hint.

Usage::

    python -m ariadne.serve --db data/demo.db \\
        --semantic semantic_layer --context context_layer
"""

import argparse
import asyncio
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

# Captured when datus is missing so startup can fail fast with a hint (spec §7).
# The imports live inside the try: a missing datus must not abort the module import
# itself — the CLI fails fast with INSTALL_HINT instead of a raw ImportError.
# Tests exercise the branch offline via monkeypatching / blocked imports.
try:
    from datus_semantic_osi.adapter import DatusOSIAdapter  # pyright: ignore[reportMissingImports]
    from datus_semantic_osi.config import DatusOSIConfig  # pyright: ignore[reportMissingImports]

    _DATUS_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:
    DatusOSIAdapter = None  # type: ignore[assignment, misc]
    DatusOSIConfig = None  # type: ignore[assignment, misc]
    _DATUS_IMPORT_ERROR = exc

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
    """Governed + ad-hoc metric facade: Datus compile + facade-owned DuckDB execution."""

    def __init__(
        self,
        semantic_dir: str | Path,
        context_dir: str | Path,
        db_path: str | Path,
        staging_dir: str | Path = "staging",
    ):
        if _DATUS_IMPORT_ERROR is not None:  # spec §7: fail fast with the hint
            raise RuntimeError(f"{INSTALL_HINT}: {_DATUS_IMPORT_ERROR}")
        assert DatusOSIAdapter is not None and DatusOSIConfig is not None

        self.context_dir = Path(context_dir)
        models = Path(semantic_dir) / "models"
        if not models.is_dir():
            raise RuntimeError(
                f"no semantic models under {models} — promote staging/semantic_layer/ first"
            )
        self.adapter = DatusOSIAdapter(DatusOSIConfig(semantic_models_path=str(models)))
        try:
            metrics = asyncio.run(self.adapter.list_metrics())
        except Exception as exc:
            raise RuntimeError(f"served OSI models under {models} do not compile: {exc}") from exc
        if not metrics:  # spec §7: nothing servable -> fail fast, not at query time
            raise RuntimeError(f"no governed metrics found under {models}")
        self._metrics: dict[str, Any] = {metric.name: metric for metric in metrics}
        # Spec rev 4 §8.12: per-metric available dimensions for list_metrics.
        # The models compiled two lines above, so discovery on them is safe.
        self._dimensions: dict[str, list[str]] = {
            name: sorted(dim.name for dim in asyncio.run(self.adapter.get_dimensions(name)))
            for name in self._metrics
        }

        # Spike §6.2: non-DuckDB attaches are connection-local, so the facade
        # attaches once on its long-lived connection; compiled SQL references
        # demo.main.<table> (the authoring contract's catalog name).
        self.con = duckdb.connect()
        self.con.execute(f"ATTACH '{Path(db_path)}' AS demo (TYPE SQLITE, READ_ONLY)")
        # Bare table names in agent-authored ad-hoc sources resolve against the attach.
        self.con.execute("USE demo.main")
        self.staging_dir = Path(staging_dir)

    async def list_metrics(self) -> list[dict | str]:
        """Governed metrics with descriptions and available dimensions; the list
        ends with the explicit routing hint to the ad-hoc path (spec rev 4 §8.12)."""
        entries = [
            {
                "name": metric.name,
                "description": metric.description or "",
                "dimensions": self._dimensions.get(metric.name, []),
            }
            for metric in self._metrics.values()
        ]
        entries.append(ROUTING_HINT)
        return entries

    async def list_datasets(self) -> list[dict]:
        """Every table in the attached database with its columns (the agent's map)."""
        rows = self.con.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_catalog = 'demo' AND table_schema = 'main' "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        datasets: dict[str, dict] = {}
        for table, column, data_type in rows:
            entry = datasets.setdefault(table, {"name": table, "columns": []})
            entry["columns"].append({"name": column, "type": data_type})
        return list(datasets.values())

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
        time_start = range.get("start") if range else None
        time_end = range.get("end") if range else None
        result = await self.adapter.query_metrics(
            metrics=[name],
            dimensions=dimensions or [],
            time_start=time_start,
            time_end=time_end,
            dry_run=True,
        )
        sql = (result.metadata or {}).get("sql")
        if not sql:
            raise RuntimeError(f"Datus returned no compiled SQL for metric {name!r}")
        # Compiled by Datus from the served OSI models — never tool input (spec §6):
        # the executor only ever receives SQL returned by the compile step. The
        # statement guard is defense in depth on this governed path too.
        assert_single_statement(sql)
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

        The definition is expanded into an ephemeral OSI model and compiled by
        Datus; failure returns compiler errors verbatim (nothing staged, nothing
        executed). On success the compiled SQL is executed read-only and the
        definition is auto-staged as a proposal (never auto-promoted).
        """
        params = _normalize_definition(definition)
        envelope = _expand_adhoc_model(params)
        sql = await self._compile_adhoc(envelope, params["name"], params["dimensions"])
        # Choke point shared by the EXPLAIN bind-check below and the execution
        # above it: exactly one statement, checked at parse level before any
        # duckdb call (a crafted source can otherwise smuggle DDL past EXPLAIN).
        assert_single_statement(sql)
        # Datus compiles structurally without schema introspection, so a column
        # missing from the source only surfaces at bind time. EXPLAIN binds the
        # plan without executing it, keeping §8.9's "no execution" honest for
        # that shape — while still only ever feeding compiler output to duckdb.
        try:
            self.con.execute(f"EXPLAIN {sql}")
        except Exception as exc:  # spec §7: the binder's text, verbatim (§8.9 holds:
            # the guard above guarantees nothing executed before this check).
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc
        # sql is the Datus compile step's output and nothing else (spec §6): the
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
        """Datus compile of the ephemeral model — the only gate between tool args
        and execution. Returns the compiled SQL; raises ValueError carrying the
        compiler errors verbatim (spec §7). The ephemeral model lives in a system
        temp dir that is discarded after the call; the served semantic dir and
        everything outside it is never written."""
        with tempfile.TemporaryDirectory(prefix="ariadne-adhoc-") as tmp:
            try:
                model = Path(tmp) / "adhoc.yml"
                model.write_text(yaml.safe_dump(envelope, sort_keys=False), encoding="utf-8")
                adapter = DatusOSIAdapter(DatusOSIConfig(semantic_models_path=tmp))  # pyright: ignore[reportOptionalCall]
                validation = await adapter.validate_semantic()
                errors = [
                    issue.message
                    for issue in validation.issues
                    if getattr(issue, "severity", "error") == "error"
                ]
                if errors:
                    raise ValueError("\n".join(errors))
                result = await adapter.query_metrics(
                    metrics=[name], dimensions=dimensions, dry_run=True
                )
                sql = (result.metadata or {}).get("sql")
                if not sql:
                    raise ValueError("Datus returned no compiled SQL for the ad-hoc definition")
                return sql
            except ValueError:
                raise
            except Exception as exc:  # lowering/load failure — surface it verbatim
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
        """Rank OKF pages by query-term frequency (name-anchored ties by path)."""
        terms = query.lower().split()
        hits: list[dict] = []
        for path in sorted(self.context_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            score = sum(text.lower().count(term) for term in terms)
            if not score:
                continue
            hits.append(
                {
                    "path": path.relative_to(self.context_dir).as_posix(),
                    "score": score,
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
    per docs/research/datus-spike.md §3.1 (version 0.2.0.dev0, dialects-expression
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
    from mcp.server.fastmcp import FastMCP  # pyright: ignore[reportMissingImports]

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
        """Search the Context Layer (OKF pages) for business rules; ranked matches."""
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
                column names of the source. Invalid definitions return the compiler
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
    parser.add_argument("--db", default="data/demo.db", help="SQLite database to attach read-only")
    parser.add_argument("--semantic", default="semantic_layer", help="served OSI layer directory")
    parser.add_argument("--context", default="context_layer", help="served OKF layer directory")
    parser.add_argument(
        "--staging", default="staging", help="staging root for auto-staged ad-hoc proposals"
    )
    args = parser.parse_args(argv)

    try:
        facade = Facade(args.semantic, args.context, args.db, staging_dir=args.staging)
    except Exception as exc:  # fail fast before any MCP traffic
        print(f"error: {exc}", file=sys.stderr)
        return 1
    build_app(facade).run()  # stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

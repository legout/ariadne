"""Transport-neutral Ariadne runtime: the five governed + ad-hoc operations.

AriadneRuntime owns everything the served tree offers to consuming agents
(spec 2026-09-23-0001 §3, ADR-0012) — the MCP adapter (:mod:`ariadne.serve`)
registers these operations as tools; it never duplicates compilation,
execution, context, grain, or proposal-staging logic:

    list_metrics()                     -> served governed metrics with descriptions
    list_datasets()                    -> [{name, columns: [{name, type}]}] from the attach
    search_context(query)              -> ranked matches over context_layer/**/*.md
    get_metric(name, dimensions, range)-> rows PLUS the compiled SQL (provenance),
                                          governed: true + context (rev 10): the full
                                          served OKF metric page plus the full bodies
                                          of every policy its frontmatter cites
    define_metric(definition)          -> the ad-hoc path (spec rev 3): ephemeral OSI model ->
                                          render -> read-only execution -> rows + SQL +
                                          governed: false + auto-staged proposal

Mechanism per ADR-0008 (spec rev 7): our own sqlglot compiler
(:mod:`ariadne.render`) renders the OSI envelope model to SQL and the
runtime-owned DuckDB connection — built by the shared source-registry builder
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
path through the runtime itself — ``list_metrics`` ends with the routing hint
and the unknown-metric error names ``list_datasets()`` + ``define_metric``.

No-unvalidated-execution invariant (spec §6): the DuckDB executor only ever
receives SQL returned by the render compile step — there is no code path from
tool arguments to ``duckdb.execute`` that bypasses the compiler.

Invariants and failure behavior (spec §6/§7): ``get_metric`` accepts only named
governed metrics — never raw SQL; unknown metric -> error listing the available
metrics and naming the ad-hoc path (``list_datasets()`` + ``define_metric``);
unrenderable served models -> fail fast at startup; an environment that
actively blocks the retired datus packages -> fail fast with the historical
install hint.
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

# Issue #19 (ADR-0015, spec 2026-09-29-0007): the answer-example store is a
# separate transport-neutral module — the runtime only contributes its selected
# roots; examples never touch compilation, execution or governed context.
from ariadne import (
    answer_examples,  # pyright: ignore[reportMissingImports] — new-module resolver drift
)

# The grain guard lives in ariadne.grain (shared with the validate audit — mvp-5
# round 2 convergence); check_grain_preserving is the runtime's entry into it.
from ariadne.grain import check_grain_preserving

# Issue #30: the multi-fact query path rides the validated private planner
# (issues #27-#29) and the normalized graph (issue #26) — both internal seams;
# the transport-neutral query_metrics/query_detail below are their only public
# surface, and no call reaches execution without admission, planning, binding,
# and the per-request live audits.
from ariadne.planner import (  # pyright: ignore[reportMissingImports] — drift
    PlannerError,
    plan_detail,
    plan_query,
)

# (the pyright ignore below: the analyzer may bind `ariadne` to a copy predating
# this lane's render module — see ADR-0008; runtime and uvx pyright resolve it)
from ariadne.render import render  # pyright: ignore[reportMissingImports]

# ADR-0010: the runtime's DuckDB session comes from the shared registry builder
# (ariadne.yaml --sources, or the legacy --db single-sqlite shorthand).
from ariadne.semantic_graph import (  # pyright: ignore[reportMissingImports] — drift
    SemanticGraph,
    load_graph,
)
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    build_connection,
    implicit_registry,
    load_registry,
)
from ariadne.validate import (  # pyright: ignore[reportMissingImports] — drift
    _registry_identity,
    served_tree_digest,
)

# ADR-0008: the compile path is ariadne.render (own sqlglot compiler) — datus is
# no longer imported at all. The historical spec §7 fail-fast contract stays
# testable: an environment that ACTIVELY BLOCKS datus (the ``sys.modules[name] =
# None`` sentinel the offline tests install) still surfaces the original install
# hint at AriadneRuntime init, while a plain datus-free install serves through
# render().
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
# name the same two operations.
ROUTING_HINT = (
    "If no governed metric above answers your question, route it to the ad-hoc path: "
    "call list_datasets() to see the queryable tables, then define_metric(definition) "
    "to compute the answer (compiled, executed read-only, auto-staged for human promotion)."
)

# MetricFlow's metric-name schema, enforced again at lowering time — reject up
# front with an actionable message (lowercase snake_case, no double underscore).
_SLUG_RE = re.compile(r"[a-z][a-z0-9_]*[a-z0-9]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# OKF page frontmatter (same shape as author/promote): sources[] resolution for
# the rev 10 context field reads it.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# Spec 2026-09-23-0002: search matching is token-aware, not substring — a query
# token is a lowercase [a-z0-9]+ run, so "order" no longer counts inside
# "orders" and incidental substring repetition cannot crowd out real matches.
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")

# ATX headings (spec: the section is the containing Markdown heading; a line
# like "#hashtag" without the required space is not one).
_HEADING_RE = re.compile(r"#{1,6}\s+(.+?)\s*$")

# Excerpt bound: chars of context kept on each side of the matched token before
# snapping outward to whole words (spec: bounded, verbatim).
_EXCERPT_RADIUS = 60


def _fence_mask(lines: list[str]) -> list[bool]:
    """True for lines that delimit or sit inside a fenced code block — ``` or
    ~~~. A fence closes only on the same marker with a run at least as long as
    the opener and nothing else on the line (CommonMark: a ~~~ line inside a
    ~~~~ fence stays literal). Fenced text is generated/machine content (SQL,
    code) whose identifiers merely echo page names — the spec's "incidental
    occurrences" — so it scores at half weight and its headings never
    establish a section (spec: every Markdown category stays searchable;
    fenced-only occurrences still hit)."""
    mask: list[bool] = []
    marker = ""  # active fence marker char; "" when not fenced
    needed = 0  # closing run length the active fence requires
    for line in lines:
        stripped = line.lstrip()
        char = stripped[:1]
        run = len(stripped) - len(stripped.lstrip(char))
        if char in ("`", "~") and run >= 3:
            if not marker:
                marker, needed = char, run  # opener: an info string may follow
                mask.append(True)
            elif char == marker and run >= needed and not stripped[run:].strip():
                marker, needed = "", 0  # closer: same marker, long enough, bare
                mask.append(True)
            else:
                mask.append(True)  # fence-ish line stays literal inside the fence
        else:
            mask.append(bool(marker))
    return mask


def _locate_passage(
    lines: list[str], mask: list[bool], body_start: int, terms: set[str]
) -> tuple[str, int, int, str | None]:
    """Deterministically pick the passage a hit points at (spec rev 1): scan the
    body lines first — a body match is preferred over a frontmatter-only match —
    then the frontmatter, in file order; the leftmost token match on the first
    matching line wins (fenced lines may carry the passage). Returns (excerpt,
    line_start, line_end, section) with inclusive 1-based line coordinates; the
    section is the nearest ATX heading at or before the passage, outside fenced
    code, or None for frontmatter/heading-less matches (no body evidence is
    fabricated)."""
    for index in [*range(body_start, len(lines)), *range(body_start)]:
        line = lines[index]
        token = next(
            (m for m in _QUERY_TOKEN_RE.finditer(line.lower()) if m.group() in terms), None
        )
        if token is None:
            continue
        start, end = token.span()
        lo = max(0, start - _EXCERPT_RADIUS)
        hi = min(len(line), end + _EXCERPT_RADIUS)
        while lo > 0 and start - lo < _EXCERPT_RADIUS and not line[lo - 1].isspace():
            lo -= 1  # keep whole words at the left clip
        while hi < len(line) and hi - end < _EXCERPT_RADIUS and not line[hi].isspace():
            hi += 1  # keep whole words at the right clip
        if index >= body_start:
            section = _enclosing_heading(lines, mask, body_start, index)
        else:
            section = None
        return line[lo:hi], index + 1, index + 1, section
    raise AssertionError("a positive score implies a matched line")  # pragma: no cover


def _enclosing_heading(
    lines: list[str], mask: list[bool], body_start: int, index: int
) -> str | None:
    """The nearest ATX heading at or above line `index` that is not inside a
    fenced code block (spec: headings inside fences never establish a section,
    and a passage on a heading line names that heading)."""
    section = None
    for position, line in enumerate(lines[body_start : index + 1], start=body_start):
        if not mask[position] and (heading := _HEADING_RE.match(line)):
            section = heading.group(1)
    return section


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


class AriadneRuntime:
    """Governed + ad-hoc metric runtime: render-gate compile + runtime-owned
    DuckDB execution."""

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

        # ADR-0010: one shared builder produces the runtime's long-lived DuckDB
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
        # and never re-read, so one passing check per metric holds for the runtime's
        # lifetime (ponytail: one COUNT scan per join key, paid once per process;
        # re-key by model file mtime if served models ever hot-reload).
        self._grain_checked: set[str] = set()
        # Issue #30: the admitted multi-fact graph. Admission is the human local
        # Promotion of a validated bundle — the promotion-written admission record
        # under the served semantic layer binds the post-Promotion served-tree
        # digest; a graph without it (hand-placed, or plain staging promotion) is
        # never governed. Production Git-review admission is a separate blocked
        # workstream: this runtime has no code path that could label an unreviewed
        # commit governed, and reports only the route it actually served. The
        # bound identity (db/sources) is kept for the per-query staleness recheck.
        self._graph: SemanticGraph | None = None
        self._admission: dict | None = None
        self._admission_reason: str | None = None
        self._admission_db = db_path
        self._admission_sources = sources
        self._semantic_dir = Path(semantic_dir)
        self._load_admission(Path(semantic_dir), db_path, sources)

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
            "context": self._metric_context(name),  # spec rev 10 §8.21 (ADR-0011)
        }

    def _load_admission(
        self, semantic_dir: Path, db_path: str | Path, sources: str | Path | None
    ) -> None:
        """Resolve the served tree's multi-fact admission (issue #30). The
        promotion-written ``semantic_layer/admission.json`` maps the exact
        staged review digest to the POST-Promotion served-tree digest together
        with the persisted technical validation scope; the graph serves only
        while the CURRENT served bytes still match it. No record, a corrupt
        record, changed served bytes, or a changed approved registry each leave
        the runtime unadmitted — ``query_metrics``/``query_detail`` refuse with
        that reason while the legacy single-metric path keeps its behavior
        (spec rev 1 AC7)."""
        record_path = semantic_dir / "admission.json"
        if not record_path.is_file():
            self._admission_reason = (
                "the served tree carries no multi-fact admission record — admit the "
                "graph by submitting the bundle, having a human review it, and running "
                "the exact-digest ariadne-promote --digest (local route); an unadmitted "
                "graph is never governed"
            )
            return
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not record.get("served_digest"):
                raise ValueError("not an admission record")
        except ValueError as exc:
            self._admission_reason = (
                f"{record_path}: unreadable admission record ({exc}) — the multi-fact "
                "query interface stays refused until a human re-promotes a validated "
                "bundle"
            )
            return
        current = served_tree_digest(semantic_dir, self.context_dir)
        if current != record["served_digest"]:
            self._admission_reason = (
                "the served layers changed after admission "
                f"(served digest {current[:12]}… != recorded {record['served_digest'][:12]}…) "
                "— revalidate and re-promote before serving the graph as governed"
            )
            return
        bound = (record.get("validation") or {}).get("registry_digest")
        registry_digest, _label = _registry_identity(db_path, sources)
        if bound is not None and registry_digest != bound:
            self._admission_reason = (
                "the approved source registry changed after admission — revalidate and "
                "re-promote before serving the graph as governed"
            )
            return
        try:
            self._graph = load_graph(semantic_dir)
        except Exception as exc:  # fail fast: an admitted tree that cannot load
            raise RuntimeError(f"admitted graph under {semantic_dir} does not load: {exc}") from exc
        self._admission = record

    def _admitted(self) -> tuple[SemanticGraph, dict]:
        """The admitted graph + record, or the structured refusal (spec rev 1
        "Failure and compatibility behavior": a stable error code, before any
        SELECT executes). The served-tree digest is RE-CHECKED here, not just at
        construction: a long-lived server must see a hand-edited model, graph,
        or cited Policy as a stale admission, exactly like one constructed after
        the edit (the digest re-hash is a handful of small files; the loaded
        graph itself stays the admitted bytes)."""
        if self._admission is None or self._graph is None:
            raise PlannerError(
                "not_admitted",
                self._admission_reason or "the served tree carries no admitted multi-fact graph",
            )
        current = served_tree_digest(self._semantic_dir, self.context_dir)
        if current != self._admission["served_digest"]:
            raise PlannerError(
                "admission_stale",
                "the served layers changed after admission "
                f"(served digest {current[:12]}… != recorded "
                f"{self._admission['served_digest'][:12]}…) — revalidate and re-promote "
                "before serving the graph as governed",
            )
        bound = (self._admission.get("validation") or {}).get("registry_digest")
        registry_digest, _label = _registry_identity(self._admission_db, self._admission_sources)
        if bound is not None and registry_digest != bound:
            raise PlannerError(
                "admission_stale",
                "the approved source registry changed after admission — revalidate and "
                "re-promote before serving the graph as governed",
            )
        return self._graph, self._admission

    def _admission_view(self, record: dict) -> dict:
        """The response's local admission provenance: route, the exact reviewed
        digest, the served-tree digest it is bound to, the persisted technical
        validation scope, and the human promotion identity."""
        return {
            "route": record.get("route"),
            "reviewed_digest": record.get("reviewed_digest"),
            "served_digest": record.get("served_digest"),
            "revision": record.get("revision"),
            "validation": record.get("validation"),
            "promoted": record.get("promoted"),
        }

    async def query_metrics(self, request: dict) -> dict:
        """Governed multi-fact query (issue #30, spec rev 1 "Query and result
        contract"): a nonempty list of PREDEFINED metric names over the ADMITTED
        served graph — never agent-authored SQL. The request carries declared
        dimensions, optional typed parameters, named segments, row/result
        filters, an optional conformed time range/grain, order and limit. Every
        call passes admission, planning (fact-local aggregation, safe
        many-to-one paths, aligned aggregate merge), the per-request live
        relationship audits, the single-statement guard, and an EXPLAIN bind
        before the one guarded SELECT executes. The response carries the rows,
        the compiled SQL, a bounded lineage plan, per-metric OKF metric + Policy
        context with the independent attestation state, and the local admission
        provenance — ``governed: true`` only because a human Promoted the exact
        validated bytes."""
        graph, admission = self._admitted()
        plan = plan_query(graph, request, self.con)
        assert_single_statement(plan.sql)
        try:
            self.con.execute(f"EXPLAIN {plan.sql}")  # nosemgrep — planner output (spec §6)
        except Exception as exc:  # spec §7: the binder's text, verbatim
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc
        relation = self.con.sql(plan.sql)
        columns = list(relation.columns)
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return {
            "metrics": list(plan.metrics),
            "dimensions": list(plan.dimensions),
            "columns": columns,
            "rows": rows,
            "sql": plan.sql,
            "plan": {
                "branches": [
                    {
                        "dataset": branch.dataset,
                        "metrics": list(branch.metrics),
                        "joins": list(branch.joins),
                        "keys": [[key, column] for key, column in branch.keys],
                        "filters": list(branch.filters),
                    }
                    for branch in plan.branches
                ],
                "conformed_keys": list(plan.conformed_keys),
                "segments": list(plan.segments),
                "time_dimension": plan.time_dimension,
                "time_grain": plan.time_grain,
                "windows": list(plan.windows),
                "audits": [
                    {"name": audit.name, "outcome": audit.outcome, "detail": audit.detail}
                    for audit in plan.audits
                ],
                "relationship_audit": plan.relationship_audit,
            },
            "governed": True,
            "context": {name: self._metric_context(name) for name in plan.metrics},
            "admission": self._admission_view(admission),
        }

    async def query_detail(self, request: dict) -> dict:
        """Governed detail projection (issue #30 over issue #28): one declared
        root dataset's fields — its own directly, others only through proven
        many_to_one/one_to_one lookup paths — with no aggregates and no
        fan-out, over the ADMITTED served graph, behind the same admission,
        single-statement, and EXPLAIN bind gauntlet."""
        graph, admission = self._admitted()
        plan = plan_detail(graph, request, self.con)
        assert_single_statement(plan.sql)
        try:
            self.con.execute(f"EXPLAIN {plan.sql}")  # nosemgrep — planner output (spec §6)
        except Exception as exc:  # spec §7: the binder's text, verbatim
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc
        relation = self.con.sql(plan.sql)
        columns = list(relation.columns)
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return {
            "dataset": plan.dataset,
            "fields": [field.name for field in plan.fields],
            "columns": columns,
            "rows": rows,
            "sql": plan.sql,
            "plan": {
                "fields": [
                    {"name": field.name, "dataset": field.dataset, "path": list(field.path)}
                    for field in plan.fields
                ],
                "joins": list(plan.joins),
                "audits": [
                    {"name": audit.name, "outcome": audit.outcome, "detail": audit.detail}
                    for audit in plan.audits
                ],
                "relationship_audit": plan.relationship_audit,
            },
            "governed": True,
            "admission": self._admission_view(admission),
        }

    async def save_example(self, submission: dict) -> dict:
        """Issue #19 (spec 2026-09-29-0007, ADR-0015): stage one explicitly
        submitted answer example as a labeled ``status: draft`` OKF record
        under ``staging/answer_examples/`` — transport-neutral, so the local
        CLI and the optional MCP adapter share exactly this path. Validated
        before any write: malformed submissions, oversized excerpts/records,
        citations that do not resolve inside the selected served root, and
        claimed (rather than self-declared) identity or verification all store
        nothing. The served roots are never touched."""
        return answer_examples.save_example(submission, self.context_dir.parent, self.staging_dir)

    async def search_examples(
        self, query: str, limit: int = 10, include_history: bool = False
    ) -> list[dict]:
        """Issue #19: ranked labeled example records (draft/stable identity,
        staleness, question/interpretation, method summary, provenance, path)
        from the current served and staging example roots — re-read on each
        request, no query execution, no saved rows. ``search_context`` and
        governed ``get_metric.context`` are unaffected: examples live outside
        ``context_layer/`` and never enter them."""
        return answer_examples.search_examples(
            self.context_dir.parent,
            self.staging_dir,
            query,
            limit=limit,
            include_history=include_history,
        )

    def _metric_context(self, name: str) -> dict:
        """Rev 10 (ADR-0011): the governed number ships with its caveats — the full
        served OKF metric page (``context_layer/metrics/<name>.md``) plus the full
        bodies of every policy page its frontmatter ``sources[]`` cites
        (``policies/`` paths, resolved against the served context dir). When the
        metric's computation page declares ``attestation: pending`` (ADR-0013:
        promoted is not independently value-attested), the context carries that
        caveat explicitly. Context problems NEVER fail the query — the number is
        still governed: a missing metric page or an unresolvable policy reference
        collapses to ``{metric_page: null, policies: []}`` and is logged nowhere.
        Containment (defense in depth — served YAML names are not fully trusted):
        the metric page must resolve inside the context root and every cited policy
        under ``policies/``; a ``../..``-style traversal is just another
        unresolvable reference — the context collapses to the null form and
        nothing outside the context dir is ever read."""
        try:
            root = self.context_dir.resolve()
            page = root / "metrics" / f"{name}.md"
            if not page.resolve().is_relative_to(root):
                raise ValueError("metric page path escapes the context root")
            text = page.read_text(encoding="utf-8")
            match = _FRONTMATTER_RE.match(text)
            meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
            refs = (
                source.get("resource") if isinstance(source, dict) else source
                for source in meta.get("sources") or []
            )
            policies_root = root / "policies"
            policies = []
            for ref in refs:
                if not (isinstance(ref, str) and ref.startswith("policies/")):
                    continue
                body = (root / ref).resolve()
                if not body.is_relative_to(policies_root):
                    raise ValueError(f"policy reference escapes policies/: {ref}")
                policies.append(body.read_text(encoding="utf-8"))
            context = {"metric_page": text, "policies": policies}
            if self._computation_attestation(root, name) == "pending":
                # ADR-0013/spec acceptance 5, and ONLY the pending case (the new
                # harness-led bundles): governed:true means Promoted, never an
                # independent numeric attestation — say so on every such answer.
                # Existing attested bundles keep the established context shape.
                context["attestation"] = "pending"
                context["governed_note"] = (
                    "governed: true means Promoted, not independently value-attested"
                )
            return context
        except Exception:  # missing page, unresolvable ref, traversal, unparsable frontmatter
            return {"metric_page": None, "policies": []}

    def _computation_attestation(self, root: Path, name: str) -> str | None:
        """The computation page's attestation caveat for ``name``: ``"pending"``
        when the served computation declares it (ADR-0007 scoped extension),
        the cited attester when one is present, None when there is no such
        page. Read problems are just another missing caveat — never a failure."""
        try:
            page = root / "computations" / f"{name}.md"
            if not page.resolve().is_relative_to(root) or not page.is_file():
                return None
            match = _FRONTMATTER_RE.match(page.read_text(encoding="utf-8"))
            meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
            if meta.get("attestation") == "pending":
                return "pending"
            return str(meta["attester"]) if meta.get("attester") else None
        except Exception:
            return None

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
            "context": None,  # spec rev 10: no served page exists for ad-hoc metrics
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
        """Rank OKF pages by query-token frequency; each hit points at its passage.

        Scans the served context dir AND the staged context drafts
        (``staging/context_layer/**/*.md``) — spec rev 4 §4: define_metric
        drafts must be discoverable before promotion. Staged hits carry
        ``draft: true`` and served hits ``draft: false`` — a draft never
        masquerades as verified context (ADR-0003: promotion stays human).

        Spec 2026-09-23-0002: ranking is deterministic and token-aware (whole
        ``[a-z0-9]+`` tokens, so incidental substrings like "order" inside
        "orders" no longer crowd out real matches; fenced code tokens count at
        half weight so generated SQL echoes rank below prose without hiding a
        fenced-only match; ties break by path, served before staged). Every hit
        additionally carries ``excerpt`` (a bounded
        verbatim substring of ``content`` around the first matched token),
        inclusive 1-based ``line_start``/``line_end`` covering that excerpt,
        and ``section`` (the containing ATX heading outside fenced code, else
        ``None`` — a frontmatter-only match never fabricates a body section;
        a body match is preferred over a frontmatter match). Nonpositive
        limits and queries with no matching token return ``[]``."""
        if limit <= 0:
            return []
        terms = _QUERY_TOKEN_RE.findall(query.lower())
        hits: list[dict] = []
        roots = [(self.context_dir, False), (self.staging_dir / "context_layer", True)]
        for root, draft in roots:
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                lines = text.split("\n")
                mask = _fence_mask(lines)
                prose: Counter[str] = Counter()
                code: Counter[str] = Counter()
                for line, fenced in zip(lines, mask):
                    (code if fenced else prose).update(_QUERY_TOKEN_RE.findall(line.lower()))
                score = 2 * sum(prose[term] for term in terms) + sum(code[term] for term in terms)
                if not score:
                    continue
                frontmatter = _FRONTMATTER_RE.match(text)
                body_start = text[: frontmatter.start(2)].count("\n") if frontmatter else 0
                excerpt, line_start, line_end, section = _locate_passage(
                    lines, mask, body_start, set(terms)
                )
                hits.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "score": score,  # relative ranking value, not a frequency contract
                        "draft": draft,  # staged proposals stay distinguishable
                        "content": text,  # full OKF page: the rules are the payload
                        "excerpt": excerpt,
                        "line_start": line_start,
                        "line_end": line_end,
                        "section": section,
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
    definition alone carries any business filter — the runtime adds nothing."""

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

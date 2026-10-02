"""Query workflow: the five governed + ad-hoc operations (QueryRuntime).

:class:`QueryRuntime` owns everything the served tree offers to consuming
agents (spec 2026-09-23-0001 §3, ADR-0012; moved here from
``ariadne.runtime`` in the modular-core extraction, spec 2026-10-02-0009 §2 /
ADR-0016) — the MCP adapter (:mod:`ariadne.serve`) and the local CLI
(:mod:`ariadne.cli`) register these operations; they never duplicate
compilation, execution, context, grain, or proposal-staging logic:

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
    query_metrics/query_detail         -> the admitted multi-fact graph (issue #30)

Mechanism per ADR-0008 (spec rev 7): our own sqlglot compiler
(:mod:`ariadne.render`) renders the OSI envelope model to SQL and the
execution-owned DuckDB connection (:class:`ariadne.execution.DuckDBExecution`,
built by the shared source-registry builder :mod:`ariadne.sources`, ADR-0010:
a ``ariadne.yaml`` registry, or the legacy ``--db`` SQLite file attached
read-only as catalog ``demo``) executes it. ``range`` is an optional
``{start, end}`` applied by the compiler to the model's primary date dimension
(the is_time field). ``list_metrics``/``list_datasets`` read the envelope
metadata and the attach directly — no datus anywhere in the query path.

Ad-hoc (ADR-0005, spec §6): ``define_metric`` params are expanded into an
ephemeral OSI-core model (version 0.2.0.dev0 shape, dialects-expression fields,
is_time dimension), rendered by :mod:`ariadne.render` (no files touched — the
served semantic dir is never written). Compile failure returns the compiler's
error verbatim; nothing is staged, nothing executed. On success the compiled SQL
is executed read-only and the definition is auto-staged as a proposal: the OSI
model under ``staging/semantic_layer/models/adhoc/`` plus a minimal OKF draft
under ``staging/context_layer/metrics/`` so ``search_context`` can discover it
(numeric suffix on name collision, never overwrite); promotion stays human
(ADR-0003). Query stages ad-hoc definitions through the shared
:func:`ariadne.proposals.stage_ad_hoc` operation without importing the Authoring
workflow (spec 2026-10-02-0009 §2).

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
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Issue #19 (ADR-0015, spec 2026-09-29-0007): the answer-example store is a
# separate transport-neutral module — the runtime only contributes its selected
# roots; examples never touch compilation, execution or governed context.
#
# Shared Proposals (issue #34, ADR-0016): the compiled ad-hoc staging/label
# operation — Query stages ad-hoc definitions through it WITHOUT importing the
# Authoring workflow or touching any Git proposal store (spec 2026-10-02-0009 §2).
from ariadne import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    answer_examples,
    proposals,  # pyright: ignore[reportMissingImports] — drift
)

# Shared Context Layer (issue #33, ADR-0016): retrieval, citation attachment and
# deterministic OKF generation live in ariadne.context.
from ariadne.context import (  # pyright: ignore[reportMissingImports] — drift
    metric_context,
    search_pages,
)

# Shared Execution (issue #33, ADR-0016): the DuckDB session, catalog, bind
# operation, statement guard and result collection are execution-owned.
from ariadne.execution import (  # pyright: ignore[reportMissingImports] — drift
    DuckDBExecution,
    assert_single_statement,
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
from ariadne.semantic_graph import (  # pyright: ignore[reportMissingImports] — drift
    SemanticGraph,
    load_graph,
)
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
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
# hint at runtime init, while a plain datus-free install serves through
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


class QueryRuntime:
    """Governed + ad-hoc metric runtime: render-gate compile + execution-owned
    DuckDB execution. ``ariadne.runtime.AriadneRuntime`` and ``ariadne.serve.Facade``
    are aliases of exactly this class (spec 2026-10-02-0009 §2) — never a second
    implementation."""

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

        # ADR-0010/0016: one shared owner produces the runtime's long-lived DuckDB
        # session over the registry sources (addressable as <source>.<table>);
        # non-DuckDB attaches are connection-local, so this happens exactly
        # once. Compiled SQL references <catalog>.<schema>.<table> — the legacy
        # shorthand keeps the authoring contract's catalog name demo.
        registry = load_registry(sources) if sources is not None else implicit_registry(db_path)
        self._execution = DuckDBExecution(registry)
        # The connection/catalog aliases preserve the historical runtime surface
        # (consumers close via con; list_datasets reads the catalog).
        self.con, self.catalog = self._execution.con, self._execution.catalog
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
        self._execution.bind(sql)
        # Grain guard on the model's dataset source (spec rev 5 §13): a fan-out
        # baked into a served model would aggregate at joined-row grain
        # (Datus-ai/Datus-agent#1426) — identical rejection contract to
        # define_metric. Memoized per metric (see __init__).
        if name not in self._grain_checked:
            (dataset,) = self._metrics[name]["model"]["semantic_model"][0].get("datasets") or []
            check_grain_preserving(self.con, dataset["source"])
            self._grain_checked.add(name)
        # sql is the render compile step's output and nothing else (spec §6).
        columns, rows = self._execution.fetch(sql)
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
        self._execution.bind(plan.sql)
        columns, rows = self._execution.fetch(plan.sql)
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
        self._execution.bind(plan.sql)
        columns, rows = self._execution.fetch(plan.sql)
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
        """The shared context implementation over this runtime's served context
        dir (spec rev 10 §8.21; contract and containment in
        :func:`ariadne.context.metric_context`)."""
        return metric_context(self.context_dir, name)

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
        self._execution.bind(sql)
        # sql is the render compile step's output and nothing else (spec §6): the
        # definition reached execution exclusively through the compiler above.
        columns, rows = self._execution.fetch(sql)
        # The SHARED compiled ad-hoc staging operation (moved intact into
        # ariadne.proposals, issue #34): the OSI model + draft OKF page land in
        # the legacy staging store — ungoverned, discoverable, never a Git
        # proposal, never admitted.
        staged_as, staged_page = proposals.stage_ad_hoc(
            self.staging_dir, params["name"], envelope, params
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

    async def search_context(self, query: str, limit: int = 10) -> list[dict]:
        """Search the served Context Layer and staged drafts for business rules
        (spec 2026-09-23-0002; the shared ranking implementation and its
        contract live in :func:`ariadne.context.search_pages`): deterministic
        token-aware ranking over the served context dir plus the staged context
        drafts, served hits ``draft: false`` and staged hits ``draft: true``."""
        return search_pages(
            query, limit, [(self.context_dir, False), (self.staging_dir / "context_layer", True)]
        )


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

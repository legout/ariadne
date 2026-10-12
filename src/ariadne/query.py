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
    resolve_term(request)              -> shared terminology resolution (spec
                                          0010 §6): bounded concept/representation
                                          matches with exact bindings, scope,
                                          ambiguity and unconfirmed claims
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
``ariadne.proposals.reserve_ad_hoc``/``stage_reserved_ad_hoc`` operations without
importing the Authoring
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
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import expressions as exp
from sqlglot.optimizer.scope import Scope, build_scope  # pyright: ignore[reportMissingImports]

# Issue #19 (ADR-0015, spec 2026-09-29-0007): the answer-example store is a
# separate transport-neutral module — the runtime only contributes its selected
# roots; examples never touch compilation, execution or governed context.
#
# Shared Proposals (issue #34, ADR-0016): the compiled ad-hoc staging/label
# operation — Query stages ad-hoc definitions through it WITHOUT importing the
# Authoring workflow or touching any Git proposal store (spec 2026-10-02-0009 §2).
from ariadne import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    admission,  # issue #37/G5: pinned-snapshot resolution for open_project
    answer_examples,
    authoring_inputs,  # K4 fix pass: the operator evidence age budget (host config)
    context,  # issue #48 fix: the assessment clock/assembly seams stay internal
    proposals,  # pyright: ignore[reportMissingImports] — drift
    query_results,  # pyright: ignore[reportAttributeAccessIssue] — drift: the analyzer binds `ariadne` to the venv's editable main checkout, which lacks this lane's new module; runtime/uvx resolve the worktree
)

# Shared Context Layer (issue #33, ADR-0016): retrieval, citation attachment and
# deterministic OKF generation live in ariadne.context.
from ariadne.context import (  # pyright: ignore[reportMissingImports] — drift
    data_signals,
    list_pages,
    read_page,
    resolve_term,
    search_pages,
)

# Shared Execution (issue #33, ADR-0016): the DuckDB session, catalog, bind
# operation, statement guard and result collection are execution-owned.
from ariadne.execution import (  # pyright: ignore[reportMissingImports] — drift
    DeadlineBudget,
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
    TIMESTAMP_MARKER,
    TIMESTAMP_REFUSAL_CODE,
    PlannerError,
    QueryPlan,
    _closure,
    plan_detail,
    plan_query,
    plan_records,
)

# (the pyright ignore below: the analyzer may bind `ariadne` to a copy predating
# this lane's render module — see ADR-0008; runtime and uvx pyright resolve it)
from ariadne.query_results import QueryResultError  # pyright: ignore[reportMissingImports] — drift
from ariadne.render import render  # pyright: ignore[reportMissingImports]
from ariadne.semantic_graph import (  # pyright: ignore[reportMissingImports] — drift
    SemanticGraph,
    load_graph,
)
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    Registry,
    implicit_registry,
    load_registry,
)

# Issue #59 (spec 0014 §9): the static ad-hoc IO-authority boundary — one
# transport-neutral core check the CLI, the Facade and the Analyst toolset all
# inherit because they all call this runtime's define_metric.
from ariadne.sql_authority import (  # pyright: ignore[reportMissingImports] — new-module drift
    AdHocAuthority,
    assert_ad_hoc_authority,
)
from ariadne.validate import (  # pyright: ignore[reportMissingImports] — drift
    _registry_identity,
    candidate_scope_digest,
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
    "to compute the answer (compiled, executed read-only, auto-staged for human promotion). "
    "For bounded record selection over one known table (no aggregation, no staging), "
    "call query_records(request) with {dataset, fields, order, limit?} — never raw SQL."
)

# K4 (issue #44, spec 0010 §6/§9): the SPECIFIC missing-catalog error every
# metric operation keeps on a human-admitted CONTEXT-ONLY snapshot (schemas/
# References, no metrics): discovery and terminology resolution serve the
# admitted context, the metric surface refuses explicitly, and no absent
# model ever triggers a fallback raw-SQL route. The legacy explicit-root
# constructors keep their historical fail-fast startup errors instead.
MISSING_CATALOG = (
    "no governed metric catalog: the pinned admitted snapshot carries no semantic "
    "models — metric operations are refused; discovery (search_context) and term "
    "resolution (resolve_term) still serve the admitted context, and no absent "
    "model ever triggers a raw-SQL fallback"
)

# MetricFlow's metric-name schema, enforced again at lowering time — reject up
# front with an actionable message (lowercase snake_case, no double underscore).
_SLUG_RE = re.compile(r"[a-z][a-z0-9_]*[a-z0-9]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A fully qualified physical-table reference ("demo.main.orders",
# "events.events") — the identity form the catalog match below requires.
_IDENTIFIER_PATH_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class QueryRuntime:
    """Governed + ad-hoc metric runtime: render-gate compile + execution-owned
    DuckDB execution. ``ariadne.runtime.AriadneRuntime`` and ``ariadne.serve.Facade``
    are aliases of exactly this class (spec 2026-10-02-0009 §2) — never a second
    implementation."""

    def __init__(
        self,
        semantic_dir: str | Path,
        context_dir: str | Path,
        db_path: str | Path | None,
        staging_dir: str | Path = "staging",
        sources: str | Path | None = None,
        *,
        registry: Registry | None = None,
        admission_record: dict | None = None,
        project_root: str | Path | None = None,
        query_limits: dict | None = None,
        response_measure=None,
        deadline_budget: DeadlineBudget | None = None,
    ):
        """``db_path``/``sources`` select the LEGACY explicit source identity
        (the ``--db`` shorthand or an ADR-0010 registry file). The keyword-only
        parameters carry the MANAGED Git route (issue #37/G5):
        ``registry`` is an already-resolved approved identity (never a file),
        ``admission_record`` the pinned Git-review admission
        (:meth:`open_project` resolves both), and ``project_root`` the logical
        project root that anchors the staging/ad-hoc/Answer Example stores —
        separate from the pinned artifact root, which is derived from
        ``context_dir``. An explicit legacy construction (no ``registry``/
        ``admission_record``) keeps its legacy behavior exactly.

        Issue #56/S1 (spec 0014 §4–§6): ``query_limits`` is the HOST-owned
        complete-output ceilings (validated tightening-only; built-ins when
        omitted — never a tool/request field), ``response_measure`` the
        selected transport's actual-representation preflight (a callable the
        ADAPTER supplies; the core only calls it — it never imports MCP), and
        ``deadline_budget`` the ONE remaining-seconds budget a REQUEST-LIFETIME
        construction (CLI invocation / lazy MCP factory) shares between source
        setup and its first operation (fix pass 1, finding 1) — long-lived
        eager runtimes omit it and every operation starts a fresh budget."""
        if _DATUS_IMPORT_ERROR is not None:  # spec §7: fail fast with the hint
            raise RuntimeError(f"{INSTALL_HINT}: {_DATUS_IMPORT_ERROR}")

        self.context_dir = Path(context_dir)
        models = Path(semantic_dir) / "models"
        # K4 (issue #44, spec 0010 §6): a MANAGED context-only admitted snapshot
        # (no semantic models — schemas/References only) constructs for
        # discovery and term resolution; every metric operation then refuses
        # with the SPECIFIC missing-catalog error. The legacy explicit-root
        # constructors keep the historical fail-fast startup errors exactly.
        self._context_only = False
        if not models.is_dir():
            if admission_record is None:
                raise RuntimeError(
                    f"no semantic models under {models} — promote staging/semantic_layer/ first"
                )
            self._context_only = True
        # Envelope metadata read directly (no datus): per metric, its description,
        # available dimensions (fields carrying a dimension flag — spec rev 4 §8.12)
        # and the single-entry envelope render() compiles.
        self._metrics: dict[str, Any] = {}
        for path in sorted(models.glob("*.yml")) if models.is_dir() else []:
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
            if admission_record is None:
                raise RuntimeError(f"no governed metrics found under {models}")
            self._context_only = True  # a managed catalog-less admission serves discovery
        try:
            for entry in self._metrics.values():
                render(entry["model"])
        except Exception as exc:
            raise RuntimeError(f"served OSI models under {models} do not compile: {exc}") from exc

        # ADR-0010/0016: one shared owner produces the runtime's long-lived DuckDB
        # session over the registry sources (addressable as <source>.<table>);
        # non-DuckDB attaches are connection-local, so this happens exactly
        # once. Compiled SQL references <catalog>.<schema>.<table> — the legacy
        # shorthand keeps the authoring contract's catalog name demo.
        if registry is not None:
            source_registry = registry
        elif sources is not None:
            source_registry = load_registry(sources)
        else:
            if db_path is None:
                # unreachable via the public factories (the managed route always
                # resolves an approved registry; the legacy roots always carry a
                # --db) — kept type-honest for direct construction
                raise ValueError("legacy construction requires db_path or sources")
            source_registry = implicit_registry(db_path)
        # Issue #56/S1 (spec 0014 §4/§6): the host-owned ceilings are loaded and
        # validated BEFORE source construction, and the eager setup runs under
        # one bounded setup budget (the existing K3 mechanism) — construction
        # never opens an unbounded source before the guard starts. A
        # request-time construction passes its OWN budget: setup and the
        # request's first operation then share ONE remaining-seconds allowance.
        self._limits = query_results.effective_limits(query_limits)
        self._measure = response_measure
        self._request_budget = deadline_budget
        self._execution = DuckDBExecution(
            source_registry,
            budget=deadline_budget
            if deadline_budget is not None
            else DeadlineBudget(self._limits["execution_seconds"]),
        )
        # The connection/catalog aliases preserve the historical runtime surface
        # (consumers close via con; list_datasets reads the catalog).
        self.con, self.catalog = self._execution.con, self._execution.catalog
        self._qualified = sources is not None or registry is not None
        if not self._qualified:
            # Bare table names in agent-authored ad-hoc sources resolve against the attach.
            self.con.execute("USE demo.main")
        # Issue #59 (spec 0014 §9): the ad-hoc IO-authority boundary's approved
        # physical-relation set — the ALREADY-BUILT execution catalog plus
        # DuckDB's own current catalog/schema (the legacy --db route's
        # USE demo.main is what makes bare table names resolve; a registry
        # route keeps its <source>.<table> form). Read once here, from trusted
        # internal reads only, so an ad-hoc refusal never needs a DuckDB call.
        self._ad_hoc_authority = AdHocAuthority.build(self.catalog, self.con)
        self.staging_dir = Path(staging_dir)
        # Issue #53 (spec 0013 §4): the exact-identity map of the ALREADY-BUILT
        # execution catalog — qualified table name → canonical resource — built
        # lazily once and reused by every data_signals attachment. No new catalog
        # or source query ever runs for quality evidence.
        self._catalog_resources: dict[str, str] | None = None
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
        # The managed Git route (issue #37/G5): the session pins ONE coherent
        # admitted revision — snapshot bytes, approved source identity and the
        # logical project root that anchors the ORIGINAL project-owned staging
        # and Answer Example stores (never the pinned artifact root).
        self._managed = admission_record
        self._project = Path(project_root).resolve() if project_root is not None else None
        # Issue #37 fix pass: the Answer Example store stays anchored at the
        # LOGICAL project root on the managed route (operator-reviewed stable
        # examples under <project>/answer_examples stay discoverable), while
        # citations and staleness keep resolving against the PINNED artifact
        # root (context_dir.parent) — the legacy route keeps its single shared
        # root (examples_root=None).
        self._examples_root = self._project
        if admission_record is not None:
            self._load_managed_graph(self._semantic_dir)
            if self._context_only and self._graph is None:
                # the managed multi-fact refusal names the missing CATALOG on a
                # context-only snapshot, not a broken admission
                self._admission_reason = MISSING_CATALOG
        else:
            self._load_admission(Path(semantic_dir), db_path, sources)

    @classmethod
    def open_project(
        cls,
        project: str | Path,
        *,
        staging_dir: str | Path | None = None,
        deadline_budget: DeadlineBudget | None = None,
    ) -> "QueryRuntime":
        """The managed-project factory (issue #37/G5, plan §2): resolve the
        pinned snapshot and its approved source configuration of a Git-managed
        data project and construct the runtime over them. EVERY query method
        of the returned runtime therefore requires admission by construction —
        a Git-managed project with no valid admission is refused here, never a
        silent fallback to proposal worktrees or mutable project files, while
        the explicit legacy artifact-root constructors keep legacy behavior for
        fixtures/operators. Source locations resolve through the
        operator-approved identity (never snapshot-relative paths); the
        staging/ad-hoc/Answer Example stores stay at their ORIGINAL
        project-owned locations (default ``<project>/staging``), separate from
        the pinned artifact root. Each session pins one coherent admitted
        revision; a later session picks up a later admission."""
        root = Path(project).resolve()
        record, snapshot = admission.resolve_admission(root)
        return cls(
            snapshot / "semantic_layer",
            snapshot / "context_layer",
            None,
            staging_dir=(root / "staging") if staging_dir is None else staging_dir,
            registry=admission.approved_registry(record),
            admission_record=record,
            project_root=root,
            # issue #56/S1: the LOGICAL host project's operator ceilings — never
            # the pinned snapshot's inert ``query:`` copy (plan 0014 §2)
            query_limits=query_results.load_host_query_limits(root),
            deadline_budget=deadline_budget,
        )

    async def list_metrics(self) -> list[dict | str]:
        """Governed metrics with descriptions and available dimensions; the list
        ends with the explicit routing hint to the ad-hoc path (spec rev 4 §8.12).
        Serves pinned snapshot bytes (the envelope metadata), so the managed
        route re-checks them first — mid-session tampering refuses here too
        (issue #37 fix pass). A context-only admitted snapshot keeps the
        SPECIFIC missing-catalog error (K4): an empty list would pose as a
        served catalog over an admitted revision that carries none."""
        self._discard_request_budget()  # fix pass 2, finding 1b (list_metrics)
        if self._managed is not None:
            self._recheck_pinned()
        if self._context_only:
            raise ValueError(MISSING_CATALOG)
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
        ``<source>.<table>`` so both sources stay distinguishable. K1 (issue
        #41): every entry additionally carries the EXPLICIT identity fields
        (source/catalog/schema/table plus the canonical credential-free
        ``resource``) — same-named tables in distinct schemas/collections stay
        distinct assets, and consumers use these fields rather than parsing
        display names."""
        self._discard_request_budget()  # fix pass 2, finding 1b (list_datasets)
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
                        "source": source["name"],
                        "catalog": table.get("catalog"),
                        "schema": table.get("schema"),
                        "table": table["name"],
                        "resource": table.get("resource"),
                    }
                )
        return datasets

    def _claim_operation_budget(self) -> DeadlineBudget:
        """One remaining-seconds budget per operation (spec 0014 §6, fix pass
        1 finding 1): a runtime constructed INSIDE a request (CLI invocation /
        lazy MCP factory) draws its FIRST operation from the very budget that
        bounded construction — setup + bind + audits + collection + preflight
        share ONE allowance — while every later operation on the reused
        session starts a fresh budget."""
        if self._request_budget is not None:
            budget, self._request_budget = self._request_budget, None
            return budget
        return DeadlineBudget(self._limits["execution_seconds"])

    def _discard_request_budget(self) -> None:
        """Request-budget hygiene (fix pass 2, finding 1b). Invariant: a
        request-lifetime budget belongs to exactly ONE request — the one whose
        construction it bounded. Non-result operations discard any stored
        request budget at entry, so the request that lazily constructed this
        runtime through e.g. ``list_metrics`` can never strand its (possibly
        expired) allowance where a LATER result request would inherit it:
        every result operation either claims the current request's budget or
        starts a fresh one."""
        self._request_budget = None

    @contextmanager
    def _phase(self, budget: DeadlineBudget):
        """One guarded operation phase (spec 0014 §6): the shared budget arms
        the owned connection's interrupt for bind, live audits and bounded
        collection, and a budget spent at the phase boundary — including an
        interrupt the planner wrapped into its own error — becomes the
        structured ``execution_deadline`` refusal, never a complete answer
        after expiry."""
        try:
            with budget.guard(self.con):
                yield
        except QueryResultError:
            raise  # a refusal is a refusal; never relabeled by the clock
        except Exception as exc:
            if budget.expired():
                raise query_results.deadline_refusal(budget.seconds) from exc
            raise

    def _collect(self, sql: str, budget: DeadlineBudget):
        """Bounded collection of one compiled statement under the operation's
        budget (spec 0014 §4): all-or-nothing on the overflow facts — a row
        or cell overflow is the structured refusal, with observed lower
        bounds only (counting stopped at the indicator row)."""
        bounded = self._execution.fetch_bounded(sql, self._limits, budget)
        if bounded.row_overflow:
            raise query_results.row_limit_refusal(
                self._limits["max_rows"], self._limits["max_rows"] + 1
            )
        if bounded.cell_overflow:
            raise query_results.cell_limit_refusal(
                self._limits["cell_bytes"], bounded.cell_overflow
            )
        return bounded

    async def get_metric(
        self,
        name: str,
        dimensions: list[str] | None = None,
        range: dict | None = None,  # noqa: A002 — spec §4 names the parameter
    ) -> dict:
        if self._context_only:  # K4: the specific missing-catalog refusal
            if self._managed is not None:
                self._recheck_pinned()
            raise ValueError(MISSING_CATALOG)
        if name not in self._metrics:  # spec §7/rev 4: discovery before failure
            available = ", ".join(sorted(self._metrics))
            raise ValueError(
                f"unknown metric {name!r}; available metrics: {available}. {ROUTING_HINT}"
            )
        if self._managed is not None:
            # Issue #37/G5: a governed answer on the managed route re-checks the
            # session's pinned snapshot bytes and source identity first — a
            # hand-edited snapshot or a withdrawn approval is a staleness refusal.
            self._recheck_pinned()
        # Compiled by our sqlglot renderer (ADR-0008) from the served OSI models —
        # never tool input (spec §6): the executor only ever receives SQL returned
        # by the compile step. The statement guard is defense in depth on this
        # governed path too.
        sql = render(self._metrics[name]["model"], dimensions or [], range or {}, metric=name)
        # Choke point shared with the EXPLAIN bind-check below (spec §6): exactly
        # one statement at parse level before any duckdb call.
        assert_single_statement(sql)
        # Issue #56/S1 (spec 0014 §6): one fresh remaining-seconds budget covers
        # bind, the live grain audit and bounded execution/collection; a reused
        # session never inherits a previous operation's allowance.
        budget = self._claim_operation_budget()
        with self._phase(budget):
            # Same gauntlet as the ad-hoc path (spec §8.9): the renderer compiles
            # structurally, so a column missing from the source only surfaces at
            # bind time. EXPLAIN binds the plan without executing it — while still
            # only ever feeding compiler output to duckdb.
            self._execution.bind(sql)
            # Grain guard on the model's dataset source (spec rev 5 §13): a fan-out
            # baked into a served model would aggregate at joined-row grain
            # (Datus-ai/Datus-agent#1426) — identical rejection contract to
            # define_metric. Runs against LIVE data on every call: an ETL reload
            # can introduce fan-out under a long-lived session, so no per-process
            # memo — a few COUNT scans per query are cheap at this scale.
            (dataset,) = self._metrics[name]["model"]["semantic_model"][0].get("datasets") or []
            check_grain_preserving(self.con, dataset["source"])
            # sql is the render compile step's output and nothing else (spec §6).
            bounded = self._collect(sql, budget)
        if budget.expired():  # no complete answer after expiry (spec 0014 §6)
            raise query_results.deadline_refusal(budget.seconds)
        result = {
            "metric": name,
            "dimensions": dimensions or [],
            "columns": bounded.columns,
            "rows": bounded.rows,
            "sql": sql,
            "governed": True,  # spec rev 3 §8.10: symmetry with define_metric
            "context": self._metric_context(name),  # spec rev 10 §8.21 (ADR-0011)
        }
        if self._managed is not None:
            # Issue #37/G5: revision/route provenance alongside the existing
            # caveats (spec §5: governed answers identify the admitted revision
            # and route) — legacy responses keep their exact shape.
            result["admission"] = self._admission_view(self._managed)
        # Issue #53/#54 (spec 0013 §4): the additive advisory source-quality
        # view. Identity comes from the executed query's direct dataset
        # dependencies matched EXACTLY against the built catalog; the shared
        # reader is pure and never fails or changes the governed result above.
        # The requested range is the runtime's own mechanical period fact
        # (issue #54 W1 fix3): an inclusive [start, end] render range becomes
        # the exclusive instant span — render predicates the inner aggregate,
        # so consumed == requested here — and period correspondence is only
        # assessed for a report whose period field IS the model's ``is_time``
        # field, the one field the range predicates.
        result["data_signals"] = data_signals(
            self.context_dir,
            {name: self._direct_table_dependencies(name)},
            requested_period=_requested_period(range, inclusive_end=True),
            period_fields=self._model_time_fields(name),
        )
        # Issue #56/S1 (spec 0014 §5): additive completeness metadata for the
        # fitting answer, then the full-envelope accounting and the selected
        # transport's actual-representation preflight before it is returned.
        result["result"] = query_results.completeness(len(bounded.rows))
        query_results.account_rows(self._limits, result, bounded.rows)
        query_results.finalize_response(self._limits, result, response_measure=self._measure)
        if budget.expired():  # the last check before return (fix pass 1, finding 1)
            raise query_results.deadline_refusal(budget.seconds)
        return result

    def _model_time_fields(self, name: str) -> set[str]:
        """The ``is_time`` dimension names of the metric's model (issue #54 W1
        fix3): the exact fields a get_metric range predicates, so a report's
        declared evidence-period FIELD can be matched mechanically — a period
        on any other field never proves correspondence with the range."""
        fields: set[str] = set()
        for dataset in self._metrics[name]["model"]["semantic_model"][0].get("datasets") or []:
            for field in (dataset.get("fields") if isinstance(dataset, dict) else None) or []:
                flag = field.get("dimension") if isinstance(field, dict) else None
                if (
                    isinstance(flag, dict)
                    and flag.get("is_time")
                    and isinstance(field.get("name"), str)
                ):
                    fields.add(field["name"])
        return fields

    def _catalog_resource_map(self) -> dict[str, str]:
        """The exact-identity map of the ALREADY-BUILT execution catalog —
        fully qualified table name (attach: ``<catalog>.<schema>.<table>``;
        file view: ``<schema>.<table>`` with the catalog-null convention) →
        canonical resource. Built lazily once and reused by every
        data_signals attachment; no new catalog or source query ever runs
        for quality evidence."""
        if self._catalog_resources is None:
            self._catalog_resources = {
                f"{table['ref']}.{table['name']}": table["resource"]
                for source in self.catalog
                for table in source["tables"]
            }
        return self._catalog_resources

    def _dataset_resources(self, source: object) -> list[str | None]:
        """The canonical resources of ONE dataset source's physical table
        references, matched against the built catalog by exact qualified
        identity (spec 0013 §4). An unmatched reference stays ``None`` —
        unknown dependency identity, never a stripped-name guess."""
        catalog = self._catalog_resource_map()
        return [None if ref is None else catalog.get(ref) for ref in _qualified_source_refs(source)]

    def _direct_table_dependencies(self, name: str) -> list[str | None]:
        """The canonical table resources of the metric's DIRECT dataset
        dependencies (spec 0013 §4, issues #53/#54): every dataset source — a
        qualified table name or a SELECT — is matched against the ALREADY-BUILT
        execution catalog by exact qualified identity, never an unqualified
        display-name match (same-named tables in distinct sources stay distinct
        assets, which is why :func:`ariadne.context._source_tables` — it
        deliberately strips qualification — is never used as an identity
        resolver here). An unmatched or unresolvable dependency is ``None``:
        unknown coverage, never a guess."""
        dependencies: list[str | None] = []
        for dataset in self._metrics[name]["model"]["semantic_model"][0].get("datasets") or []:
            source = dataset.get("source") if isinstance(dataset, dict) else None
            dependencies.extend(self._dataset_resources(source))
        return dependencies

    def _plan_table_dependencies(
        self, graph: SemanticGraph, plan: QueryPlan
    ) -> dict[str, list[str | None]]:
        """Per-metric direct table dependencies of an EXECUTED multi-fact plan
        (issue #54, spec 0013 §4, plan 0013 §2): each retained metric is
        associated with the physical tables of exactly the fact branches its
        metric closure aggregates in, plus the lookup datasets those branches
        traverse — the plan's own bounded lineage, never the whole query's
        asset union presented as a proven per-metric match. A metric whose
        correspondence no branch proves, and a dataset source that does not
        resolve to the exact catalog identity, stay ``None``: unknown
        coverage."""
        edge_targets = {edge.name: edge.to_dataset for edge in graph.relationships}
        dependencies: dict[str, list[str | None]] = {}
        for name in plan.metrics:
            members = set(_closure(graph, name))
            datasets: list[str] = []
            for branch in plan.branches:
                if any(member in branch.metrics for member in members):
                    if branch.dataset not in datasets:
                        datasets.append(branch.dataset)
                    for join in branch.joins:
                        target = edge_targets.get(join)
                        if target is not None and target not in datasets:
                            datasets.append(target)
            if not datasets:
                dependencies[name] = [None]  # no provable branch correspondence
                continue
            resolved: list[str | None] = []
            for dataset in datasets:
                for resource in self._dataset_resources(graph.datasets[dataset].source):
                    if resource not in resolved:
                        resolved.append(resource)
            dependencies[name] = resolved
        return dependencies

    def _load_managed_graph(self, semantic_dir: Path) -> None:
        """The managed route's multi-fact gate (issue #37/G5): the pinned
        Git-review admission IS the graph's admission — the legacy
        promotion-written ``admission.json`` never exists inside a snapshot
        (it is not admitted artifact scope), so ``query_metrics``/
        ``query_detail`` serve only when the pinned snapshot itself carries a
        loadable graph."""
        if (semantic_dir / "graph.yml").is_file():
            try:
                self._graph = load_graph(semantic_dir)
            except Exception as exc:  # fail fast: an admitted graph that cannot load
                raise RuntimeError(
                    f"the admitted graph under {semantic_dir} does not load: {exc}"
                ) from exc
            return
        self._admission_reason = (
            "the pinned snapshot carries no multi-fact graph (semantic_layer/graph.yml) "
            "— query_metrics/query_detail stay refused; governed single-metric answers "
            "serve from the pinned admitted revision"
        )

    def _recheck_pinned(self) -> None:
        """Issue #37/G5: re-verify the session's bound snapshot bytes and
        source identity on every governed answer — a hand-edited snapshot file
        or a withdrawn source approval is a staleness refusal (the runtime
        never serves mutated pinned bytes), exactly like the legacy admission
        digest recheck."""
        record = self._managed
        assert record is not None  # only the managed route calls this
        digest = candidate_scope_digest(self.context_dir.parent)
        if digest != record["artifact_digest"]:
            raise PlannerError(
                "admission_stale",
                "the pinned snapshot changed after admission "
                f"(snapshot digest {digest[:12]}… != admitted "
                f"{record['artifact_digest'][:12]}…) — the runtime never serves "
                "hand-edited snapshot bytes; re-admit a reviewed/validated revision",
            )
        if self._project is not None and not admission.approval_present(
            self._project, record["source_digest"]
        ):
            raise PlannerError(
                "admission_stale",
                "the admitted source identity no longer carries the operator's "
                "approval — re-approve the exact resolved identity before serving",
            )

    def _load_admission(
        self, semantic_dir: Path, db_path: str | Path | None, sources: str | Path | None
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
        graph itself stays the admitted bytes). The MANAGED Git route (issue
        #37/G5) pins the admission the same way over its snapshot bytes and
        approved source identity."""
        if self._managed is not None:
            if self._graph is None:
                raise PlannerError(
                    # K4 (issue #44): a context-only admitted snapshot names the
                    # missing CATALOG (a specific refusal), never a broken
                    # admission — the snapshot is validly admitted, it carries
                    # no semantic models.
                    "missing_catalog" if self._context_only else "not_admitted",
                    self._admission_reason
                    or "the pinned snapshot carries no admitted multi-fact graph",
                )
            self._recheck_pinned()
            return self._graph, self._managed
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
        """The response's local admission provenance. The managed Git route
        (issue #37/G5) reports the pinned revision/route evidence: route,
        pinned commit, proposal, the human-confirmed review digest, the bound
        artifact digest and the recorded validation scope."""
        if record is self._managed:
            return {
                "route": record.get("route"),
                "revision": record.get("commit"),
                "proposal": record.get("proposal"),
                "review_digest": record.get("review_digest"),
                "artifact_digest": record.get("artifact_digest"),
                "confirmed": record.get("confirmed"),
                "validation": record.get("validation"),
            }
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
        # Issue #56/S1 (spec 0014 §6): the shared budget covers the planner's
        # live relationship/grain audits, the EXPLAIN bind and the bounded
        # collection — one allowance for the whole operation.
        budget = self._claim_operation_budget()
        with self._phase(budget):
            plan = plan_query(graph, request, self.con)
            assert_single_statement(plan.sql)
            self._execution.bind(plan.sql)
            bounded = self._collect(plan.sql, budget)
        if budget.expired():  # no complete answer after expiry (spec 0014 §6)
            raise query_results.deadline_refusal(budget.seconds)
        now = context._assessment_now()  # one clock value for every metric's context (spec 0011 §2)
        result = {
            "metrics": list(plan.metrics),
            "dimensions": list(plan.dimensions),
            "columns": bounded.columns,
            "rows": bounded.rows,
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
            "context": {name: self._metric_context(name, _now=now) for name in plan.metrics},
            "admission": self._admission_view(admission),
        }
        # Issue #54 (spec 0013 §4): the additive advisory source-quality view
        # for MULTI-METRIC work — every retained metric associated with its own
        # identified fact/lookup dependencies through the executed plan and the
        # admitted graph (shared asset/report entries, one budget, one
        # assessment instant — plan 0013 §2). The shared reader is pure and
        # never fails or changes the governed result above. W1 fix3: the
        # period fact is the plan's mechanically CONSUMED fetch range (window
        # lookback precedes the display trim, so the display range would
        # mislabel material lookback evidence as inapplicable), and period
        # correspondence is only assessed for a report whose period field is
        # one of the conformed time dimension's native member fields.
        result["data_signals"] = data_signals(
            self.context_dir,
            self._plan_table_dependencies(graph, plan),
            requested_period=_plan_requested_period(plan.fetch_bounds),
            period_fields=self._conformed_time_fields(graph, plan.time_dimension),
        )
        # Issue #56/S1 (spec 0014 §5): completeness metadata + full-envelope
        # accounting + the selected transport's actual-representation preflight.
        result["result"] = query_results.completeness(len(bounded.rows))
        query_results.account_rows(self._limits, result, bounded.rows)
        query_results.finalize_response(self._limits, result, response_measure=self._measure)
        if budget.expired():  # the last check before return (fix pass 1, finding 1)
            raise query_results.deadline_refusal(budget.seconds)
        return result

    @staticmethod
    def _conformed_time_fields(graph: SemanticGraph, time_dimension: str | None) -> set[str]:
        """The native member field names of the request's conformed primary
        business time (issue #54 W1 fix3): the fields the time range
        predicates on each fact — the cheap mechanical correspondence for a
        report's declared evidence-period field. No time request (or no such
        edge) yields an empty set: period correspondence stays unknown, never
        an unproven inapplicable."""
        if time_dimension is None:
            return set()
        return {
            field
            for edge in graph.conformed_dimensions
            if edge.name == time_dimension
            for _dataset, field in edge.members
        }

    async def query_detail(self, request: dict) -> dict:
        """Governed detail projection (issue #30 over issue #28): one declared
        root dataset's fields — its own directly, others only through proven
        many_to_one/one_to_one lookup paths — with no aggregates and no
        fan-out, over the ADMITTED served graph, behind the same admission,
        single-statement, and EXPLAIN bind gauntlet."""
        graph, admission = self._admitted()
        budget = self._claim_operation_budget()
        with self._phase(budget):
            plan = plan_detail(graph, request, self.con)
            assert_single_statement(plan.sql)
            self._execution.bind(plan.sql)
            bounded = self._collect(plan.sql, budget)
        if budget.expired():  # no complete answer after expiry (spec 0014 §6)
            raise query_results.deadline_refusal(budget.seconds)
        result = {
            "dataset": plan.dataset,
            "fields": [field.name for field in plan.fields],
            "columns": bounded.columns,
            "rows": bounded.rows,
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
        # Issue #56/S1 (spec 0014 §5): completeness metadata + full-envelope
        # accounting + the selected transport's actual-representation preflight.
        result["result"] = query_results.completeness(len(bounded.rows))
        query_results.account_rows(self._limits, result, bounded.rows)
        query_results.finalize_response(self._limits, result, response_measure=self._measure)
        if budget.expired():  # the last check before return (fix pass 1, finding 1)
            raise query_results.deadline_refusal(budget.seconds)
        return result

    async def query_records(self, request: dict) -> dict:
        """Bounded Ad-hoc Record Query (spec 0014 §3, issue #57/S2): a
        requested top-N selection of records from ONE already-known catalog
        dataset — strict known fields/request keys, AND-combined typed
        predicates, one optional declared timestamp interpretation (the only
        way the documented VARCHAR sorts as time), explicit NULLS LAST and the
        selected-value tie tuple, and a same-execution lookahead indicator —
        never a metric, never an admitted graph traversal, never caller SQL.
        Every answer reports ``governed: false`` and truthful bounded
        provenance; nothing is ever staged. The managed route keeps its
        pinned-admission and approved-source rechecks (admission is a
        provenance fact, not admission of this request); the legacy route
        needs no graph admission. Compiled through the existing planner
        ownership, the single-statement guard and the EXPLAIN bind, then the
        shared S1 output safeguards bound the answer."""
        if self._managed is not None:
            # spec 0014 §3: managed projects retain pinned admission +
            # approved-source rechecks; a stale pin or withdrawn approval
            # refuses here, never a legacy fallback.
            self._recheck_pinned()
        budget = self._claim_operation_budget()
        with self._phase(budget):
            plan = plan_records(
                self.catalog, request, self.con, row_ceiling=self._limits["max_rows"]
            )
            # Choke point shared with the EXPLAIN bind (spec §6): the planner's
            # compiled output only, exactly one statement before any duckdb call.
            assert_single_statement(plan.executed_sql)
            self._execution.bind(plan.executed_sql)
            try:
                # the executed statement is the planner's compiled output and
                # nothing else (spec §6)
                bounded = self._collect(plan.executed_sql, budget)
            except Exception as exc:
                # the row-level timestamp interpretation refusal (spec 0014
                # §3/§5): its fixed marker converts into the stable code —
                # identifying field and interpretation, never a source value.
                refusal = _timestamp_refusal(exc)
                if refusal is not None:
                    raise refusal from exc
                raise
        if budget.expired():  # no complete answer after expiry (spec 0014 §6)
            raise query_results.deadline_refusal(budget.seconds)
        # the TRAILING execution-only columns of the executed statement — the
        # same-execution lookahead indicator and, when declared, the
        # normalized timestamp instant that keeps the interpretation
        # evaluated on every eligible row — are stripped POSITIONALLY from
        # the collected dict rows (they keep the executed column order): the
        # plan names its execution-only columns, so a physical column named
        # like a helper is still an ordinary value column (fix pass 1,
        # findings 2 and 3)
        execution_only = plan.execution_only_columns
        rows: list[dict] = []
        tail: dict = {}
        for raw in bounded.rows:
            items = list(dict(raw).items())
            tail = dict(items[-len(execution_only) :]) if execution_only else {}
            rows.append(dict(items[: len(items) - len(execution_only)]))
        # the lookahead indicator: one boolean on the last returned row of
        # the SAME execution (the extra row's payload never transfers)
        has_more = bool(tail.get(plan.has_more_column)) if rows else False
        columns = bounded.columns[: len(bounded.columns) - len(execution_only)]
        result = {
            "dataset": plan.dataset,
            "resource": plan.resource,
            "fields": list(plan.fields),
            "columns": columns,
            "rows": rows,
            "sql": plan.sql,  # the logical top-N selection (provenance)
            # the ACTUAL compiled execution statement: the same selection
            # wrapped in the execution-only lookahead guard
            "executed_sql": plan.executed_sql,
            "plan": {
                "dataset": plan.dataset,
                "resource": plan.resource,
                "fields": list(plan.fields),
                "filters": list(plan.filters),
                "order": list(plan.order),
                "tie_order": list(plan.tie_order),
                "timestamp": plan.timestamp,
                "limit": plan.limit,
                "lookahead": (
                    "has_more_matching comes from one LEAD existence indicator "
                    "in the same execution; no lookahead payload cells, no "
                    "second query, no COUNT"
                ),
                "guards": (
                    "execution-only row/cell/byte/deadline guards bound the "
                    "executed statement (spec 0014 §4); the logical sql is "
                    "provenance, executed_sql is what actually ran"
                ),
            },
            "governed": False,  # every Ad-hoc Record Query, even on admitted sources
            "provenance": self._record_provenance(),
            "result": {
                "status": "complete",
                "complete": True,
                "scope": "requested_top_n",
                "requested_limit": plan.limit,
                "returned_rows": len(rows),
                "has_more_matching": has_more,
            },
        }
        query_results.account_rows(self._limits, result, rows)
        query_results.finalize_response(self._limits, result, response_measure=self._measure)
        if budget.expired():  # the last check before return
            raise query_results.deadline_refusal(budget.seconds)
        return result

    def _record_provenance(self) -> dict:
        """The record answer's truthful provenance (spec 0014 §3): the actual
        route and artifact identity when established — the managed route's
        pinned admission view — otherwise the unversioned/as-of disclosure;
        legacy host configuration is never called Git Review Admission."""
        if self._managed is not None:
            return {
                "route": "managed-pinned-admission",
                "admission": self._admission_view(self._managed),
                "disclosure": (
                    "source admission is a provenance fact, not admission of "
                    "this requested record definition; the admission revision "
                    "and artifact digest identify the admitted registry/models/"
                    "context artifacts, not the live source data — source data "
                    "is unversioned/as-of unless an independent source snapshot "
                    "identity is established"
                ),
            }
        return {
            "route": "legacy-local-sources" if self._qualified else "legacy-local-attach",
            "admission": None,
            "disclosure": (
                "unversioned, as-of source data — legacy host configuration is "
                "not Git Review Admission; no snapshot identity is established"
            ),
        }

    async def save_example(self, submission: dict) -> dict:
        """Issue #19 (spec 2026-09-29-0007, ADR-0015): stage one explicitly
        submitted answer example as a labeled ``status: draft`` OKF record
        under ``staging/answer_examples/`` — transport-neutral, so the local
        CLI and the optional MCP adapter share exactly this path. Validated
        before any write: malformed submissions, oversized excerpts/records,
        citations that do not resolve inside the selected served root, and
        claimed (rather than self-declared) identity or verification all store
        nothing. The served roots are never touched. Citations resolve against
        the PINNED artifact root on the managed route; the staging store stays
        at its original project-owned location (issue #37 fix pass)."""
        self._discard_request_budget()  # fix pass 2, finding 1b (save_example)
        return answer_examples.save_example(
            submission,
            self.context_dir.parent,
            self.staging_dir,
            examples_root=self._examples_root,
        )

    async def search_examples(
        self, query: str, limit: int = 10, include_history: bool = False
    ) -> list[dict]:
        """Issue #19: ranked labeled example records (draft/stable identity,
        staleness, question/interpretation, method summary, provenance, path)
        from the current served and staging example roots — re-read on each
        request, no query execution, no saved rows. On the managed route the
        served example store is anchored at the LOGICAL project root (issue
        #37 fix pass), while citation staleness checks the pinned artifact
        root. ``search_context`` and governed ``get_metric.context`` are
        unaffected: examples live outside ``context_layer/`` and never enter
        them."""
        self._discard_request_budget()  # fix pass 2, finding 1b (search_examples)
        return answer_examples.search_examples(
            self.context_dir.parent,
            self.staging_dir,
            query,
            limit=limit,
            include_history=include_history,
            examples_root=self._examples_root,
        )

    def _metric_context(self, name: str, *, _now: datetime | None = None) -> dict:
        """The shared context implementation over this runtime's served context
        dir (spec rev 10 §8.21; contract and containment in
        :func:`ariadne.context.metric_context`). ``_now`` propagates one
        operation-wide assessment instant (spec 0011 §2) through the internal
        seam only — the public ``metric_context`` signature stays unchanged
        (issue #48 fix)."""
        return context._metric_context(self.context_dir, name, now=_now)

    async def define_metric(self, definition: dict) -> dict:
        """Ad-hoc path (spec rev 3 §4/§5, amended by spec 0014 §5): draft ->
        compile gate -> bounded execute -> FULL core + selected-transport
        success preflight -> stage -> return.

        The definition is expanded into an ephemeral OSI model and rendered by
        ariadne.render; failure returns the compiler's error verbatim (nothing
        staged, nothing executed). On success the compiled SQL executes
        read-only under the shared complete-output safeguards; the complete
        bounded staging receipt is reserved and preflighted BEFORE the write,
        so an output refusal after successful computation — including an
        MCP-envelope refusal — stages NOTHING and the definition is never
        auto-promoted (issue #56/S1).

        Issue #59 (spec 0014 §9): the static IO-authority boundary runs FIRST,
        on the whole nested ``source`` and ``expression`` trees, so an ad-hoc
        definition can only read the registered catalog relations with the
        reviewed analytics functions — no file/network/table-function read,
        metadata catalog or indirect SQL function ever reaches the grain
        guard, the compile gate, bind or execution.
        """
        params = _normalize_definition(definition)
        budget = self._claim_operation_budget()
        with self._phase(budget):
            # Issue #59 (spec 0014 §9): the IO-authority boundary BEFORE the
            # grain guard, compile, bind or any execution — the entire nested
            # source AND expression trees may read only the registered catalog
            # relations and call only the reviewed built-in analytics functions.
            # A refusal is static (no DuckDB call at all): nothing staged,
            # nothing executed.
            assert_ad_hoc_authority(
                params["source"], kind="source", authority=self._ad_hoc_authority
            )
            assert_ad_hoc_authority(
                params["expression"], kind="expression", authority=self._ad_hoc_authority
            )
            # Grain guard BEFORE envelope expansion/compile (spec rev 5 §13): a
            # source that fans out the fact grain is rejected outright — the
            # compiler would aggregate at joined-row grain
            # (Datus-ai/Datus-agent#1426). Nothing staged, nothing executed;
            # same contract as the single-statement guard below.
            check_grain_preserving(self.con, params["source"])
            envelope = _expand_adhoc_model(params)
            sql = await self._compile_adhoc(envelope, params["name"], params["dimensions"])
            # Choke point shared by the EXPLAIN bind-check below and the execution
            # above it: exactly one statement, checked at parse level before any
            # duckdb call (a crafted source can otherwise smuggle DDL past EXPLAIN).
            assert_single_statement(sql)
            # The renderer compiles structurally without schema introspection, so
            # a column missing from the source only surfaces at bind time. EXPLAIN
            # binds the plan without executing it, keeping §8.9's "no execution"
            # honest for that shape — while still only ever feeding compiler
            # output to duckdb.
            self._execution.bind(sql)
            # sql is the render compile step's output and nothing else (spec §6):
            # the definition reached execution exclusively through the compiler
            # above.
            bounded = self._collect(sql, budget)
        if budget.expired():  # exhaustion is checked before preflight/staging
            raise query_results.deadline_refusal(budget.seconds)
        # The complete bounded staging receipt is RESERVED (atomically claimed,
        # collision-suffixed exactly as the write would be) so the preflight
        # measures the actual receipt paths — then the payloads are written only
        # after every preflight passed; a refusal releases the reservation and
        # leaves no model or draft page behind (spec 0014 §5).
        reserved = proposals.reserve_ad_hoc(self.staging_dir, params["name"])
        try:
            result = {
                "metric": params["name"],
                "columns": bounded.columns,
                "rows": bounded.rows,
                "sql": sql,
                "governed": False,
                "context": None,  # spec rev 10: no served page exists for ad-hoc metrics
                "definition": params,  # echoed definition
                "staged_as": str(reserved[0]),
                "staged_context_as": str(reserved[1]),
                "result": query_results.completeness(len(bounded.rows)),
            }
            query_results.account_rows(self._limits, result, bounded.rows)
            query_results.finalize_response(self._limits, result, response_measure=self._measure)
            if budget.expired():  # no staging after expiry (spec 0014 §6)
                raise query_results.deadline_refusal(budget.seconds)
            # The SHARED compiled ad-hoc staging operation (moved intact into
            # ariadne.proposals, issue #34): the OSI model + draft OKF page land
            # in the legacy staging store — ungoverned, discoverable, never a
            # Git proposal, never admitted.
            proposals.stage_reserved_ad_hoc(reserved, envelope, params)
        except BaseException:
            proposals.release_reserved(reserved)  # an output refusal stages nothing
            raise
        if budget.expired():
            # Fix pass 2, finding 1a (spec 0014 §6): staging completed but the
            # budget is spent — no successful complete result is returned after
            # exhaustion. The fulfilled reservation is NOT released (the write
            # happened); the refusal reports the staging honestly instead of
            # claiming nothing occurred, mirroring the spec's
            # network-failure-after-staging stance (§5).
            raise query_results.deadline_refusal(budget.seconds, staging_status="staged")
        return result

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
        drafts, served hits ``draft: false`` and staged hits ``draft: true``.
        Serves pinned snapshot bytes on the managed route, so the pinned digest
        is re-checked first — mid-session tampering refuses here exactly like
        ``get_metric`` (issue #37 fix pass)."""
        self._discard_request_budget()  # fix pass 2, finding 1b (search_context)
        if self._managed is not None:
            self._recheck_pinned()
        return search_pages(
            query, limit, [(self.context_dir, False), (self.staging_dir / "context_layer", True)]
        )

    async def resolve_term(self, request: str | dict, *, part: int = 1) -> dict:
        """Resolve one shared business term or exact ``{resource, column}``
        field lookup against the served context (spec 0010 §6, plan §2; the
        shared read-only resolver lives in
        :func:`ariadne.context.resolve_term`): bounded matching
        concept/representation identities with their exact bindings, required
        scope, ambiguity, unconfirmed claim status, freshness and actual
        page/source citations. Resolves the PINNED admitted context only
        (never staging drafts); the managed route re-checks the pinned bytes
        first and carries the admission provenance alongside the matches. The
        resolver applies no transform, rewrites no SQL and authorizes no join;
        ``search_context`` keeps its lexical ranking and passage pointers
        unchanged."""
        self._discard_request_budget()  # fix pass 2, finding 1b (resolve_term)
        if self._managed is not None:
            self._recheck_pinned()
        result = resolve_term(
            [(self.context_dir, False)],
            request,
            part=part,
            # K4 (issue #44): the admitted human mapping confirmations of the
            # pinned revision ride the resolver — a mapping reports confirmed
            # only while the recorded selection binds its exact effective
            # assertion identity and unchanged verified evidence. K4 fix pass
            # (finding 3): the operator's evidence age budget (the same
            # inspection.receipt_max_age_hours host config the receipt gate
            # uses) drives the explicit as_of/stale freshness states, and a
            # matching confirmation over EXPIRED evidence is withheld as
            # current guidance (needs-revalidation, history disclosed).
            confirmations=(self._managed or {}).get("confirmed_mappings"),
            evidence_max_age_hours=(
                authoring_inputs.project_inspection_limits(self._project)["receipt_max_age_hours"]
                if self._project is not None
                else None
            ),
        )
        if self._managed is not None:
            # the resolved terms identify the admitted revision they came from
            result["admission"] = self._admission_view(self._managed)
        return result

    async def list_context_pages(self) -> list[dict]:
        """Enumerate every served and staged Context Layer page (spec 0015,
        ADR-0020): metadata only — ``path``, ``draft``, ``title`` and the
        advisory ``context_signals`` envelope — served before staged, then
        path, deterministically. No bodies and no query tokens: the
        token-free directory view for discovery and onboarding. Serves
        pinned snapshot bytes on the managed route, so the pinned digest is
        re-checked first exactly like ``search_context``."""
        self._discard_request_budget()
        if self._managed is not None:
            self._recheck_pinned()
        return list_pages([(self.context_dir, False), (self.staging_dir / "context_layer", True)])

    async def read_context_page(self, path: str, draft: bool = False) -> dict:
        """Read one exact Context Layer page by bundle-relative POSIX path
        (spec 0015, ADR-0020): full ``content`` plus ``draft``, ``title``-free
        metadata, and the advisory ``context_signals`` envelope. ``draft=false``
        (the default) reads the served root and re-checks the pinned digest
        on the managed route exactly like ``search_context``; ``draft=true``
        reads the staged root's live bytes (a draft is by definition not
        pinned). An absolute, root-escaping, non-markdown or unknown path
        raises ``ValueError`` naming the rejected path — never a search
        fallback, never an empty success."""
        self._discard_request_budget()
        if not draft and self._managed is not None:
            self._recheck_pinned()
        root = self.staging_dir / "context_layer" if draft else self.context_dir
        return read_page(path, root, draft=draft)


def _timestamp_refusal(exc: BaseException) -> QueryResultError | None:
    """Convert the record plan's row-level timestamp interpretation marker
    into the stable structured refusal (spec 0014 §5): the guarded SQL raises
    the FIXED marker through DuckDB's ``error()`` — the refusal message
    identifies the field and the declared interpretation, never the source
    value. ``None`` for any other exception (those keep their established
    behavior)."""
    text = str(exc)
    index = text.find(TIMESTAMP_MARKER)
    if index < 0:
        return None
    return QueryResultError(TIMESTAMP_REFUSAL_CODE, text[index:])


def _qualified_source_refs(source: object) -> list[str | None]:
    """The QUALIFIED PHYSICAL table references of one dataset source (spec
    0013 §4, issues #53/#54): a bare dotted identifier path is itself; a
    SELECT is resolved with the installed SQLGlot's scope-aware parsing — a
    CTE or derived-table alias is resolved THROUGH its own subquery scope to
    the physical tables it reads, never reported as a table itself, and a
    same-named CTE never shadows or borrows a physical table's identity.
    Predicate/scalar subqueries (EXISTS/IN/comparisons) are physical reads
    too — their scopes are reached and collected recursively (W1 fix1: the
    Q1 base caught these; dropping them silently lost a real dependency's
    evidence). A reference with no resolvable physical table at all (an
    unqualified name, a tableless expression) and an absent or unparseable
    source yield ``None`` — unknown dependency identity, never a
    stripped-name guess; the compile gate owns the real error for anything
    the renderer rejects."""
    if not isinstance(source, str) or not source.strip():
        return [None]
    text = source.strip()
    if _IDENTIFIER_PATH_RE.fullmatch(text):
        return [text]

    def collect(node: Scope) -> list[str | None]:
        refs: list[str | None] = []
        for _alias, entry in node.selected_sources.items():
            table, origin = entry
            if isinstance(origin, Scope):  # a CTE/derived alias: resolve through
                refs.extend(collect(origin))
            else:
                assert isinstance(table, exp.Table)
                refs.append(".".join(part.name for part in table.parts))
        for subquery in node.subqueries:  # predicate/scalar subquery reads
            subquery_scope = build_scope(subquery)
            if subquery_scope is not None:
                refs.extend(collect(subquery_scope))
        return refs

    try:
        root = build_scope(sqlglot.parse_one(text))
        refs = collect(root) if root is not None else []
    except Exception:  # unparseable/unscopable: unknown identity, never a guess
        return [None]
    return refs or [None]


def _requested_period(
    raw: object, *, inclusive_end: bool
) -> tuple[datetime | None, datetime | None] | None:
    """The requested query period as aware instants — the runtime's own
    mechanical fact for the period-correspondence assessment of issue #54
    (spec 0013 §3/§4). Date bounds anchor at UTC midnight (the request's own
    dates carry no timezone); an inclusive end (get_metric's render contract:
    ``>= start AND <= end``) becomes the following day's exclusive bound,
    while query_metrics' half-open ``[start, end)`` time range maps directly.
    A missing or unparseable bound stays ``None`` (unbounded — no
    contradiction can be established on that side), and a request with no
    bounds at all yields ``None`` so the assessment cannot invent one."""
    if not isinstance(raw, dict):
        return None

    def bound(key: str, *, day_after: bool = False) -> datetime | None:
        value = raw.get(key)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return None  # naive: no unambiguous mechanical instant
            return value + timedelta(days=1) if day_after else value
        if isinstance(value, date):
            day = value + timedelta(days=1) if day_after else value
            return datetime(day.year, day.month, day.day, tzinfo=UTC)
        if isinstance(value, str):
            try:
                day = date.fromisoformat(value)
            except ValueError:
                return None
            day = day + timedelta(days=1) if day_after else day
            return datetime(day.year, day.month, day.day, tzinfo=UTC)
        return None

    start = bound("start")
    end = bound("end", day_after=inclusive_end)
    return None if start is None and end is None else (start, end)


def _plan_requested_period(
    fetch_bounds: tuple[date | None, date | None] | None,
) -> tuple[datetime | None, datetime | None] | None:
    """The CONSUMED query period of an executed multi-fact plan as aware
    instants (issue #54 W1 fix3): the planner's fetch bounds — the half-open
    NATIVE fetch range that already includes any window lookback extension
    and precedes the display trim — mapped at UTC midnight like every other
    runtime period fact. ``None`` (no time request) or fully unbounded
    bounds yield ``None``; one-sided bounds keep their ``None`` side."""
    if fetch_bounds is None:
        return None
    start_day, end_day = fetch_bounds

    def instant(day: date | None) -> datetime | None:
        if day is None:
            return None
        return datetime(day.year, day.month, day.day, tzinfo=UTC)

    start, end = instant(start_day), instant(end_day)
    return None if start is None and end is None else (start, end)


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

"""Query workflow: the five governed + ad-hoc operations (QueryRuntime).

:class:`QueryRuntime` owns everything the served tree offers to consuming
agents (spec 2026-09-23-0001 §3, ADR-0012; moved here from
``ariadne.runtime`` in the modular-core extraction, spec 2026-10-02-0009 §2 /
ADR-0016) — the MCP adapter (:mod:`ariadne.serve`) and the local CLI
(:mod:`ariadne.cli`) register these operations; they never duplicate
compilation, execution, context, or grain logic:

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
    define_metric(definition)          -> ephemeral OSI model -> render -> read-only
                                          execution -> rows + SQL + governed: false +
                                          persistence: not_saved
    query_metrics/query_detail         -> the admitted multi-fact graph (issue #30)

Mechanism per ADR-0008 (spec rev 7): our own sqlglot compiler
(:mod:`ariadne.render`) renders the OSI envelope model to SQL and the
execution-owned DuckDB connection (:class:`ariadne.execution.DuckDBExecution`,
built from the operator-approved registry identity resolved by the Git project
factory) executes it. ``range`` is an optional
``{start, end}`` applied by the compiler to the model's primary date dimension
(the is_time field). ``list_metrics``/``list_datasets`` read the envelope
metadata and the attach directly — no datus anywhere in the query path.

Ad-hoc (ADR-0005, spec §6): ``define_metric`` params are expanded into an
ephemeral OSI-core model (version 0.2.0.dev0 shape, dialects-expression fields,
is_time dimension), rendered by :mod:`ariadne.render`, compiled and executed
read-only. Success returns the complete bounded result, SQL provenance, echoed
definition, ``governed: false`` and ``persistence: {status: not_saved}``; it writes
no candidate or artifact. Failures likewise leave no authored state. If a user
explicitly requests retention, the existing Authoring ``start`` and
revision-checked typed edits retain the definition in a Git candidate; there is
no persistence flag or new save operation.

Routing contract (spec rev 4 §8.12): fresh consuming agents discover the ad-hoc
path through the runtime itself — ``list_metrics`` ends with the routing hint
and the unknown-metric error names ``list_datasets()`` + ``define_metric``.

No-unvalidated-execution invariant (spec §6): the DuckDB executor only ever
receives SQL returned by the render compile step — there is no code path from
tool arguments to ``duckdb.execute`` that bypasses the compiler.

Invariants and failure behavior (spec §6/§7): ``get_metric`` accepts only named
governed metrics — never raw SQL; unknown metric -> error listing the available
metrics and naming the ad-hoc path (``list_datasets()`` + ``define_metric``);
unrenderable served models -> fail fast at query runtime initialization.
"""

import re
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import (  # pyright: ignore[reportMissingImports] — same
    expressions as exp,
)
from sqlglot.optimizer.scope import Scope, build_scope  # pyright: ignore[reportMissingImports]

# Issue #19 (ADR-0015, spec 2026-09-29-0007): the answer-example store is a
# separate transport-neutral module — the runtime only contributes its selected
# roots; examples never touch compilation, execution or governed context.
from ariadne import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    admission,  # issue #37/G5: pinned-snapshot resolution for open_project
    answer_examples,
    context,  # issue #48 fix: the assessment clock/assembly seams stay internal
    query_results,  # pyright: ignore[reportAttributeAccessIssue] — drift: the analyzer binds `ariadne` to the venv's editable main checkout, which lacks this lane's new module; runtime/uvx resolve the worktree
)
from ariadne.context import (  # pyright: ignore[reportMissingImports] — drift
    data_signals,
)

# Shared Context Layer (issue #33, ADR-0016): retrieval, citation attachment and
# deterministic OKF generation live in ariadne.context.
from ariadne.discovery import MISSING_CATALOG, ROUTING_HINT, _DiscoverySession

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
    served_tree_digest,
)

# MetricFlow's metric-name schema, enforced again at lowering time — reject up
# front with an actionable message (lowercase snake_case, no double underscore).
_SLUG_RE = re.compile(r"[a-z][a-z0-9_]*[a-z0-9]")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A fully qualified physical-table reference ("demo.main.orders",
# "events.events") — the identity form the catalog match below requires.
_IDENTIFIER_PATH_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


class _QueryRuntimeSession(_DiscoverySession):
    """Internal query session created by the project-bound ``QueryRuntime`` factory."""

    def __init__(
        self,
        semantic_dir: str | Path,
        context_dir: str | Path,
        db_path: str | Path | None,
        sources: str | Path | None = None,
        *,
        registry: Registry | None = None,
        admission_record: dict | None = None,
        project_root: str | Path | None = None,
        query_limits: dict | None = None,
        response_measure=None,
        deadline_budget: DeadlineBudget | None = None,
    ):
        """The public ``QueryRuntime.open_project`` factory supplies the
        already-resolved approved ``registry``, pinned Git-review
        ``admission_record``, and logical ``project_root``. ``db_path`` and
        ``sources`` remain private lower-level inputs for synthetic numerical
        tests only; no public route constructs a runtime from an artifact root.

        Issue #56/S1 (spec 0014 §4–§6): ``query_limits`` is the HOST-owned
        complete-output ceilings (validated tightening-only; built-ins when
        omitted — never a tool/request field), ``response_measure`` the
        selected transport's actual-representation preflight (a callable the
        ADAPTER supplies; the core only calls it — it never imports MCP), and
        ``deadline_budget`` the ONE remaining-seconds budget a REQUEST-LIFETIME
        construction (CLI invocation / lazy MCP factory) shares between source
        setup and its first operation (fix pass 1, finding 1) — long-lived
        eager runtimes omit it and every operation starts a fresh budget."""
        self._load_catalog(semantic_dir, context_dir, admission_record)
        models = Path(semantic_dir) / "models"
        try:
            for entry in self._metrics.values():
                render(entry["model"])
        except Exception as exc:
            raise RuntimeError(f"served OSI models under {models} do not compile: {exc}") from exc

        # ADR-0010/0016: one shared owner produces the runtime's long-lived DuckDB
        # session over the registry sources (addressable as <source>.<table>);
        # non-DuckDB attaches are connection-local, so this happens exactly
        # once. Compiled SQL references <catalog>.<schema>.<table>.
        if registry is not None:
            source_registry = registry
        elif sources is not None:
            source_registry = load_registry(sources)
        else:
            if db_path is None:
                raise ValueError("an internal query session requires an approved registry")
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
        # DuckDB's own current catalog/schema (the private single-database
        # test seam's USE demo.main is what makes bare table names resolve; a
        # registry route keeps its <source>.<table> form). Read once here, from trusted
        # internal reads only, so an ad-hoc refusal never needs a DuckDB call.
        self._ad_hoc_authority = AdHocAuthority.build(self.catalog, self.con)
        # Issue #53 (spec 0013 §4): the exact-identity map of the ALREADY-BUILT
        # execution catalog — qualified table name → canonical resource — built
        # lazily once and reused by every data_signals attachment. No new catalog
        # or source query ever runs for quality evidence.
        self._catalog_resources: dict[str, str] | None = None
        self._source_free = False
        self._init_artifacts(semantic_dir, db_path, sources, admission_record, project_root)

    async def list_metrics(self) -> list[dict | str]:
        self._discard_request_budget()
        return await super().list_metrics()

    async def list_datasets(self) -> list[dict]:
        """Every queryable table across the approved registry with its columns
        (the agent's map, spec rev 9 §8.20). Qualified names keep entries from
        distinct sources distinguishable. K1 (issue
        #41): every entry additionally carries the EXPLICIT identity fields
        (source/catalog/schema/table plus the canonical credential-free
        ``resource``) — same-named tables in distinct schemas/collections stay
        distinct assets, and consumers use these fields rather than parsing
        display names. C1 (issue #77, spec 0028 §7): entries whose exact asset
        tuple matches a bound contract of the PINNED admitted snapshot carry a
        bounded snapshot-based contract annotation (producer id/version,
        binding, as-of observation) — computed once from the admission
        descriptor, with NO extra source reads and no second inspection."""
        self._refuse_unsupported("list_datasets")
        if self._managed is not None:
            self._recheck_pinned()
        self._discard_request_budget()  # fix pass 2, finding 1b (list_datasets)
        annotations = self._contract_annotations()
        datasets: list[dict] = []
        for source in self.catalog:
            for table in source["tables"]:
                entry = {
                    "name": (
                        f"{source['name']}.{table['name']}" if self._qualified else table["name"]
                    ),
                    "columns": table["columns"],
                    "source": source["name"],
                    "catalog": table.get("catalog"),
                    "schema": table.get("schema"),
                    "table": table["name"],
                    "resource": table.get("resource"),
                }
                contract = annotations.get(
                    (source["name"], table.get("catalog"), table.get("schema"), table["name"])
                )
                if contract is not None:
                    entry["contract"] = contract
                datasets.append(entry)
        return datasets

    def _contract_annotations(self) -> dict[tuple, dict]:
        """The pinned snapshot's contract annotations keyed by exact asset
        tuple (spec 0028 §7): built lazily ONCE from the admission descriptor
        only — the live catalog construction itself is untouched, and no
        additional source read ever runs for the annotation."""
        from ariadne import authoring_inputs, contract_inspection

        cache: dict[tuple, dict] = {}
        record = self._managed
        view = (record or {}).get("contracts") or {}
        observations = {
            observation.get("binding"): observation
            for observation in view.get("observations") or []
            if isinstance(observation, dict)
        }
        for binding in view.get("bindings") or []:
            if not isinstance(binding, dict):
                continue
            asset = binding.get("asset") or {}
            if not isinstance(asset, dict):
                continue
            observation = observations.get(binding.get("id"))
            eligibility = "unknown"
            if observation is not None and record is not None and self._project is not None:
                eligibility = contract_inspection.snapshot_observation_eligibility(
                    self.context_dir.parent,
                    record,
                    binding,
                    observation,
                    authoring_inputs.project_inspection_limits(self._project)[
                        "receipt_max_age_hours"
                    ],
                )
            cache[
                (asset.get("source"), asset.get("catalog"), asset.get("schema"), asset.get("table"))
            ] = {
                "id": binding.get("contract_id"),
                "version": binding.get("contract_version"),
                "binding": binding.get("id"),
                "object_id": binding.get("object_id"),
                "observation": None
                if observation is None
                else {
                    "observed_at": observation.get("observed_at"),
                    "outcome": observation.get("outcome"),
                    "scope": observation.get("scope"),
                    "eligibility": eligibility,
                },
            }
        return cache

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
        budget = None
        if self._context_snapshot is not None:
            budget = self._claim_operation_budget()
            self._recheck_pinned()
        if self._context_only:  # K4: the specific missing-catalog refusal
            if self._managed is not None:
                self._recheck_pinned()
            if self._context_snapshot is not None:
                raise ValueError("no admitted metric catalog; integrated MVP has no fallback")
            raise ValueError(MISSING_CATALOG)
        if name not in self._metrics:  # spec §7/rev 4: discovery before failure
            available = ", ".join(sorted(self._metrics))
            hint = (
                ROUTING_HINT
                if self._context_snapshot is None
                else ("Local integrated MVP: get_metric and query_metrics; no Ad-hoc fallback.")
            )
            raise ValueError(f"unknown metric {name!r}; available metrics: {available}. {hint}")
        if self._managed is not None and self._context_snapshot is None:
            # Issue #37/G5: a governed answer on the managed route re-checks the
            # session's pinned snapshot bytes and source identity first — a
            # hand-edited snapshot or a withdrawn approval is a staleness refusal.
            self._recheck_pinned()
        required_context = None
        if self._context_snapshot is not None:
            assert self._managed is not None
            from ariadne import lumio_context  # pyright: ignore[reportAttributeAccessIssue]

            required_context = lumio_context.metric_context(
                self._context_snapshot,
                self._managed["bound_release"],
                self.context_dir,
                self._metrics[name]["model"]["semantic_model"][0]["name"],
                name,
            )
            query_results.account_rows(self._limits, {"context": required_context}, [])
            query_results.finalize_response(
                self._limits, {"context": required_context}, response_measure=self._measure
            )
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
        if budget is None:
            budget = self._claim_operation_budget()
        if budget.expired():
            raise query_results.deadline_refusal(budget.seconds)
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
            "context": (
                required_context if required_context is not None else self._metric_context(name)
            ),
        }
        if self._managed is not None:
            # Issue #37/G5: revision/route provenance alongside the existing
            # caveats (spec §5: governed answers identify the admitted revision
            # and route).
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
        assets). An unmatched or unresolvable dependency is ``None``:
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
                f"{self._admission['served_digest'][:12]}…) — revalidate and re-admit "
                "before serving the graph as governed",
            )
        bound = (self._admission.get("validation") or {}).get("registry_digest")
        registry_digest, _label = _registry_identity(self._admission_db, self._admission_sources)
        if bound is not None and registry_digest != bound:
            raise PlannerError(
                "admission_stale",
                "the approved source registry changed after admission — revalidate and "
                "re-admit before serving the graph as governed",
            )
        return self._graph, self._admission

    def _sdk_metric_contexts(self, request: dict) -> dict[str, dict] | None:
        """Q2 (spec0029 §1.2): on an integrated Bound Release, resolve every
        requested metric's exact SDK Context Binding and complete required
        Policy Closure from the one pinned published version, then prove the
        COMBINED mandatory context fits the complete-response budget — all
        before any planner/live-audit/bind/SELECT work. An unbound, hidden or
        incomplete binding refuses here; an answer that cannot carry its
        required context never executes. Returns ``None`` on the standalone
        route (the unchanged OKF context path applies) and an empty mapping
        for a malformed request (the planner's structured request validation
        still owns that refusal, before its own live audits)."""
        if self._context_snapshot is None:
            return None
        assert self._managed is not None
        from ariadne import lumio_context  # pyright: ignore[reportAttributeAccessIssue]

        names = request.get("metrics") if isinstance(request, dict) else None
        if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
            return {}
        unknown = [name for name in names if name not in self._metrics]
        if unknown:
            # the planner's exact unknown-metric refusal contract, kept ahead
            # of the live operations the SDK preflight must precede
            raise PlannerError(
                "unknown_metric",
                f"unknown metric(s) {unknown}",
                candidates=tuple(sorted(self._metrics)),
            )
        now = context._assessment_now()  # one clock value for every metric (spec 0011 §2)
        resolved: dict[str, dict] = {}
        for name in dict.fromkeys(names):
            meta = self._metrics[name]
            resolved[name] = lumio_context.metric_context(
                self._context_snapshot,
                self._managed["bound_release"],
                self.context_dir,
                meta["model"]["semantic_model"][0]["name"],
                name,
                _now=now,
            )
        envelope = {"context": resolved}
        query_results.account_rows(self._limits, envelope, [])
        query_results.finalize_response(self._limits, envelope, response_measure=self._measure)
        return resolved

    def _attest_bound_checks(self, plan) -> None:
        """#83 (spec0032 §10.2): an executable policy binding of this admission
        is satisfied only by the ACTUAL executed check for the consumed
        subject — a plan audit reporting not-run establishes nothing, and
        authored generated/verified stamps on pages are never proof. The
        obligation must be established before any result SQL executes;
        get_metric bindings stay explanatory in this revision (their gates
        are invariants only)."""
        if self._context_snapshot is None or self._managed is None:
            return
        manifest = self._managed.get("bound_release") or {}
        bindings = (manifest.get("policy_bindings") or {}).get("bindings") or []
        if not bindings:
            return
        consumed = set()
        for name in plan.metrics:
            meta = self._metrics.get(name)
            if meta is None:
                continue
            consumed.add(f"{meta['model']['semantic_model'][0]['name']}::{name}")
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            enforcement = binding.get("enforcement")
            if not isinstance(enforcement, dict):
                continue  # explanatory disclosure claims no executed check
            if enforcement.get("check") != "graph.relationship_audit":
                continue  # the one catalog check that executes for query_metrics
            if "query_metrics" not in (binding.get("operations") or []):
                continue
            subject = binding.get("subject") or {}
            identity = subject.get("identity")
            if subject.get("kind") not in ("metric", "computation") or identity not in consumed:
                continue
            if plan.relationship_audit != "passed":
                raise PlannerError(
                    "binding_not_attested",
                    "executable policy binding declares check 'graph.relationship_audit' "
                    f"for subject {identity!r}, but the executed plan reports relationship "
                    f"audit '{plan.relationship_audit}' — authored evidence stamps are "
                    "not proof; the operation refuses instead of labeling the narrative "
                    "enforced",
                )

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
        provenance — ``governed: true`` only because a human admitted the exact
        validated revision."""
        self._refuse_unsupported("query_metrics")
        graph, admission = self._admitted()
        # Q2 (spec0029 §1.2): on an integrated Bound Release, every requested
        # metric's exact SDK binding and complete Policy Closure resolve as ONE
        # unit, and the COMBINED mandatory context must fit the complete-response
        # budget — BEFORE planning, the live relationship audits, bind or SELECT.
        # An answer that cannot carry its required context never executes; the
        # standalone route keeps the unchanged OKF context path below.
        sdk_contexts = self._sdk_metric_contexts(request)
        # Issue #56/S1 (spec 0014 §6): the shared budget covers the planner's
        # live relationship/grain audits, the EXPLAIN bind and the bounded
        # collection — one allowance for the whole operation.
        budget = self._claim_operation_budget()
        with self._phase(budget):
            plan = plan_query(graph, request, self.con)
            self._attest_bound_checks(plan)  # §10.2: real executed-check proof, before result SQL
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
            "context": (
                {name: sdk_contexts[name] for name in plan.metrics}
                if sdk_contexts is not None
                else {name: self._metric_context(name, _now=now) for name in plan.metrics}
            ),
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
        self._refuse_unsupported("query_detail")
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
        provenance; nothing is ever staged. The public project route keeps its
        pinned-admission and approved-source rechecks (admission is a
        provenance fact, not admission of this request). Private synthetic
        sessions do not represent public serving. Compiled through the existing planner
        ownership, the single-statement guard and the EXPLAIN bind, then the
        shared S1 output safeguards bound the answer."""
        self._refuse_unsupported("query_records")
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
        pinned admission view — otherwise an internal synthetic-session
        disclosure; no public route establishes provenance without Git Admission."""
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
            "route": "internal-synthetic-session",
            "admission": None,
            "disclosure": "unversioned, as-of source data; no Git snapshot identity is established",
        }

    async def save_example(
        self,
        submission: dict,
        *,
        proposal: str | None = None,
        expected_revision: str | None = None,
    ) -> dict:
        """Save one explicit Example as an unadmitted Git proposal candidate."""
        self._refuse_unsupported("save_example")
        self._discard_request_budget()
        if self._managed is not None:
            if self._project is None:
                raise ValueError("Git Example authoring requires a managed --project")
            return answer_examples.save_candidate_example(
                submission,
                self._project,
                self.context_dir.parent,
                self._managed["commit"],
                proposal=proposal,
                expected_revision=expected_revision,
            )
        raise ValueError("a Git admission is required for Example authoring")

    async def search_examples(
        self,
        query: str,
        limit: int = 10,
        include_history: bool = False,
        include_sql: bool = False,
        *,
        proposal: str | None = None,
        revision: str | None = None,
    ) -> list[dict]:
        self._discard_request_budget()
        return await super().search_examples(
            query,
            limit=limit,
            include_history=include_history,
            include_sql=include_sql,
            proposal=proposal,
            revision=revision,
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
        """Ad-hoc path: normalize -> compile gate -> bounded read-only execution
        -> complete-output preflight -> return an explicitly unsaved result.

        Failure returns the compiler's error verbatim or a bounded refusal;
        neither failure nor success writes a candidate or artifact. The existing
        complete-output safeguards still refuse any incomplete result, including
        an MCP-envelope overflow (issue #56/S1).

        Issue #59 (spec 0014 §9): the static IO-authority boundary runs FIRST,
        on the whole nested ``source`` and ``expression`` trees, so an ad-hoc
        definition can only read the registered catalog relations with the
        reviewed analytics functions — no file/network/table-function read,
        metadata catalog or indirect SQL function ever reaches the grain
        guard, the compile gate, bind or execution.
        """
        self._refuse_unsupported("define_metric")
        if self._managed is not None:
            self._recheck_pinned()
        params = _normalize_definition(definition)
        budget = self._claim_operation_budget()
        with self._phase(budget):
            # Issue #59 (spec 0014 §9): the IO-authority boundary BEFORE the
            # grain guard, compile, bind or any execution — the entire nested
            # source AND expression trees may read only the registered catalog
            # relations and call only the reviewed built-in analytics functions.
            # A refusal is static (no DuckDB call at all): no artifact written,
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
            # (Datus-ai/Datus-agent#1426). No authored state is written and
            # nothing executes; same contract as the single-statement guard.
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
        if budget.expired():  # no complete answer after expiry (spec 0014 §6)
            raise query_results.deadline_refusal(budget.seconds)
        result = {
            "metric": params["name"],
            "columns": bounded.columns,
            "rows": bounded.rows,
            "sql": sql,
            "governed": False,
            "context": None,  # spec rev 10: no served page exists for ad-hoc metrics
            "definition": params,
            "persistence": {"status": "not_saved"},
            "result": query_results.completeness(len(bounded.rows)),
        }
        query_results.account_rows(self._limits, result, bounded.rows)
        query_results.finalize_response(self._limits, result, response_measure=self._measure)
        if budget.expired():
            raise query_results.deadline_refusal(budget.seconds)
        return result

    async def _compile_adhoc(self, envelope: dict, name: str, dimensions: list[str]) -> str:
        """Render-gate compile (ADR-0008) of the ephemeral model — the only gate
        between tool args and execution. Returns the compiled SQL; raises
        ValueError carrying the compiler's verbatim reason (spec §7). No files
        are touched: the envelope is compiled in memory."""
        try:
            return render(envelope, dimensions)
        except ValueError:
            raise  # RenderError already carries the verbatim reason (spec §7)
        except Exception as exc:  # defense in depth — surface it verbatim
            raise ValueError(f"{type(exc).__name__}: {exc}") from exc

    async def search_context(self, query: str, limit: int = 10) -> list[dict]:
        self._discard_request_budget()
        return await super().search_context(query, limit=limit)

    async def resolve_term(self, request: str | dict, *, part: int = 1) -> dict:
        self._discard_request_budget()
        return await super().resolve_term(request, part=part)

    async def list_context_pages(self) -> list[dict]:
        self._discard_request_budget()
        return await super().list_context_pages()

    async def read_context_page(self, path: str) -> dict:
        self._discard_request_budget()
        return await super().read_context_page(path)


class QueryRuntime:
    """Public query factory; governed runtimes can only come from Git admission."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("QueryRuntime is a project factory; use QueryRuntime.open_project(project)")

    @classmethod
    def open_project(
        cls,
        project: str | Path,
        *,
        deadline_budget: DeadlineBudget | None = None,
        discovery: _DiscoverySession | None = None,
    ) -> _QueryRuntimeSession:
        root = Path(project).resolve()
        if discovery is None:
            record, snapshot = admission.resolve_admission(root)
        else:
            if discovery._project != root or discovery._managed is None:
                raise ValueError("discovery does not pin an admission for this project")
            discovery._recheck_pinned()
            record, snapshot = discovery._managed, discovery.context_dir.parent
        return _QueryRuntimeSession(
            snapshot / "semantic_layer",
            snapshot / "context_layer",
            None,
            registry=admission.approved_registry(record),
            admission_record=record,
            project_root=root,
            query_limits=query_results.load_host_query_limits(root),
            deadline_budget=deadline_budget,
        )


class DeferredQueryRuntime:
    """Adapter session: discovery is artifact-only; other tools open execution on demand."""

    def __init__(
        self,
        factory: Callable[[], _QueryRuntimeSession],
        discovery: _DiscoverySession | Callable[[], _DiscoverySession],
    ):
        self._factory = factory
        self._discovery = discovery
        self._runtime: _QueryRuntimeSession | None = None

    def runtime(self) -> _QueryRuntimeSession:
        if self._runtime is None:
            self._runtime = self._factory()
        return self._runtime

    @property
    def discovery(self) -> _DiscoverySession:
        if callable(self._discovery):
            discovery = self._discovery()
            if discovery._managed is not None:
                self._discovery = discovery
            return discovery
        return self._discovery

    @property
    def _qualified(self) -> bool:
        return self.discovery._qualified

    async def discover(self, query: str, limit: int = 5) -> dict:
        return await self.discovery.discover(query, limit=limit)

    async def list_metrics(self):
        if self.discovery._context_snapshot is not None:
            return await self.discovery.list_metrics()
        return await self.runtime().list_metrics()

    def __getattr__(self, name):
        if self.discovery._context_snapshot is not None and name in {
            "search_context",
            "resolve_term",
            "list_context_pages",
            "read_context_page",
            "search_examples",
        }:
            return getattr(self.discovery, name)
        self.discovery._refuse_unsupported(name)
        return getattr(self.runtime(), name)

    def close(self) -> None:
        if self._runtime is not None:
            self._runtime.con.close()


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

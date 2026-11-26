"""``ariadne preview`` / MCP ``preview`` (spec 0040 §3.6): compile and run a metric from the
ACTIVE DRAFT over exactly the granted source identities, ``governed: false``. The served
release, its snapshot and the governed query path are never touched."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ariadne import authoring, authoring_sources, draft, proposals, query_results
from ariadne.discovery import _DiscoverySession
from ariadne.execution import DeadlineBudget, DuckDBExecution, assert_single_statement
from ariadne.grain import check_grain_preserving
from ariadne.planner import plan_query
from ariadne.render import render
from ariadne.semantic_graph import load_graph


def preview(
    project: str | Path,
    metric: str,
    dimensions: list[str] | None = None,
    filters: list[dict] | None = None,
    response_measure=None,
) -> dict:
    project = Path(project).resolve()
    view = draft.status(project)
    if view is None:
        raise ValueError("there is no active draft to preview — make an edit to open one")
    pin = (view["generation"], view["candidate_revision"])
    proposal, revision = draft.proposal_of(project, pin), view["candidate_revision"]
    if view["stale"]:
        raise ValueError(
            "stale draft: the served state advanced past the draft's base — run "
            "'ariadne draft rebase'; nothing was opened"
        )
    resolved, digest = authoring_sources.candidate_sources(project, revision)
    if resolved is None:
        raise ValueError("the draft declares no sources — nothing to preview over")
    # refuses naming any source without a grant for its exact identity, before anything opens
    grant = authoring_sources._effective_grant(project, resolved, digest, proposal, revision)
    if view["validation"] != "validated":
        reasons = (proposals.load_validation(project, proposal, revision) or {}).get("errors")
        raise ValueError(
            f"the draft is {view['validation']} — run 'ariadne validate' and fix: "
            f"{'; '.join(map(str, reasons)) if reasons else 'it has not been validated'}; "
            "nothing was opened"
        )
    approved = {entry["name"] for entry in grant["sources"]}
    registry = authoring_sources.identity_registry(grant["sources"], grant["storage_bindings"])
    limits = query_results.effective_limits(query_results.load_host_query_limits(project))

    with tempfile.TemporaryDirectory(prefix="ariadne-preview-") as tmp:
        tree = Path(tmp) / "bundle"
        tree.mkdir()
        authoring._materialize(project, proposal, revision, tree)
        session = _DiscoverySession(
            tree / "semantic_layer",
            tree / "context_layer",
            None,
            registry=registry,
            project_root=project,
        )
        if session._catalog_error:
            raise ValueError(f"the draft's models do not load: {session._catalog_error}")
        name = session._resolve(metric)
        request = {"metrics": [name], "dimensions": dimensions or [], "filters": filters or []}

        planned = bool(filters) or len(session._metric_datasets(name)) > 1

        def compile_(con=None) -> str:
            if planned:
                return plan_query(load_graph(tree / "semantic_layer"), request, con).sql
            spec, output = session._metric_slice(name)
            return render(spec, dimensions or [], {}, metric=output)

        sql = compile_()
        authoring._authorize_statement(name, sql, approved)  # pre-bind, spec 0039
        budget = DeadlineBudget(limits["execution_seconds"])
        execution = DuckDBExecution(registry, budget=budget, locked=True)
        try:
            with budget.guard(execution.con):
                if planned:
                    sql = compile_(execution.con)  # per-request live audits
                    authoring._authorize_statement(name, sql, approved)
                else:
                    check_grain_preserving(execution.con, session._metric_datasets(name)[0].source)
                assert_single_statement(sql)
                execution.bind(sql)
                bounded = execution.fetch_bounded(sql, limits, budget)
        finally:
            execution.close()
    if bounded.row_overflow:
        raise query_results.row_limit_refusal(limits["max_rows"], limits["max_rows"] + 1)
    if bounded.cell_overflow:
        raise query_results.cell_limit_refusal(limits["cell_bytes"], bounded.cell_overflow)
    result = {
        "metric": name,
        "dimensions": dimensions or [],
        "columns": bounded.columns,
        "rows": bounded.rows,
        "sql": sql,
        "governed": False,
        "draft_generation": view["generation"],
        "draft_revision": revision,
        "served_revision": view["served_revision"],
    }
    query_results.account_rows(limits, result, bounded.rows)
    query_results.finalize_response(limits, result, response_measure=response_measure)
    if budget.expired():  # no complete answer after expiry, as in governed get_metric
        raise query_results.deadline_refusal(budget.seconds)
    return result

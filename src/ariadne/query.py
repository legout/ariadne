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
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports]

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
)

# Shared Context Layer (issue #33, ADR-0016): retrieval, citation attachment and
# deterministic OKF generation live in ariadne.context.
from ariadne.context import (  # pyright: ignore[reportMissingImports] — drift
    data_signals,
    resolve_term,
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
    Registry,
    implicit_registry,
    load_registry,
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
    "to compute the answer (compiled, executed read-only, auto-staged for human promotion)."
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
        db_path: str | Path,
        staging_dir: str | Path = "staging",
        sources: str | Path | None = None,
        *,
        registry: Registry | None = None,
        admission_record: dict | None = None,
        project_root: str | Path | None = None,
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
        ``admission_record``) keeps its legacy behavior exactly."""
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
        source_registry = (
            registry
            if registry is not None
            else (load_registry(sources) if sources is not None else implicit_registry(db_path))
        )
        self._execution = DuckDBExecution(source_registry)
        # The connection/catalog aliases preserve the historical runtime surface
        # (consumers close via con; list_datasets reads the catalog).
        self.con, self.catalog = self._execution.con, self._execution.catalog
        self._qualified = sources is not None or registry is not None
        if not self._qualified:
            # Bare table names in agent-authored ad-hoc sources resolve against the attach.
            self.con.execute("USE demo.main")
        self.staging_dir = Path(staging_dir)
        # Governed-path grain-guard memo: the served envelopes are loaded once here
        # and never re-read, so one passing check per metric holds for the runtime's
        # lifetime (ponytail: one COUNT scan per join key, paid once per process;
        # re-key by model file mtime if served models ever hot-reload).
        self._grain_checked: set[str] = set()
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
        cls, project: str | Path, *, staging_dir: str | Path | None = None
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
        )

    async def list_metrics(self) -> list[dict | str]:
        """Governed metrics with descriptions and available dimensions; the list
        ends with the explicit routing hint to the ad-hoc path (spec rev 4 §8.12).
        Serves pinned snapshot bytes (the envelope metadata), so the managed
        route re-checks them first — mid-session tampering refuses here too
        (issue #37 fix pass). A context-only admitted snapshot keeps the
        SPECIFIC missing-catalog error (K4): an empty list would pose as a
        served catalog over an admitted revision that carries none."""
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
        result = {
            "metric": name,
            "dimensions": dimensions or [],
            "columns": columns,
            "rows": rows,
            "sql": sql,
            "governed": True,  # spec rev 3 §8.10: symmetry with define_metric
            "context": self._metric_context(name),  # spec rev 10 §8.21 (ADR-0011)
        }
        if self._managed is not None:
            # Issue #37/G5: revision/route provenance alongside the existing
            # caveats (spec §5: governed answers identify the admitted revision
            # and route) — legacy responses keep their exact shape.
            result["admission"] = self._admission_view(self._managed)
        # Issue #53 (spec 0013 §4): the additive advisory source-quality view.
        # Identity comes from the executed query's direct dataset dependencies
        # matched EXACTLY against the built catalog; the shared reader is pure
        # and never fails or changes the governed result above.
        result["data_signals"] = data_signals(
            self.context_dir, {name: self._direct_table_dependencies(name)}
        )
        return result

    def _direct_table_dependencies(self, name: str) -> list[str | None]:
        """The canonical table resources of the metric's DIRECT dataset
        dependencies (spec 0013 §4, issue #53): every dataset source — a
        qualified table name or a SELECT — is matched against the ALREADY-BUILT
        execution catalog by exact qualified identity, never an unqualified
        display-name match (same-named tables in distinct sources stay distinct
        assets, which is why :func:`ariadne.context._source_tables` — it
        deliberately strips qualification — is never used as an identity
        resolver here). An unmatched or unresolvable dependency is ``None``:
        unknown coverage, never a guess."""
        if self._catalog_resources is None:
            self._catalog_resources = {
                f"{table['ref']}.{table['name']}": table["resource"]
                for source in self.catalog
                for table in source["tables"]
            }
        dependencies: list[str | None] = []
        for dataset in self._metrics[name]["model"]["semantic_model"][0].get("datasets") or []:
            dependencies.extend(
                None if ref is None else self._catalog_resources.get(ref)
                for ref in _qualified_source_refs(
                    dataset.get("source") if isinstance(dataset, dict) else None
                )
            )
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
        plan = plan_query(graph, request, self.con)
        assert_single_statement(plan.sql)
        self._execution.bind(plan.sql)
        columns, rows = self._execution.fetch(plan.sql)
        now = context._assessment_now()  # one clock value for every metric's context (spec 0011 §2)
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
            "context": {name: self._metric_context(name, _now=now) for name in plan.metrics},
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
        nothing. The served roots are never touched. Citations resolve against
        the PINNED artifact root on the managed route; the staging store stays
        at its original project-owned location (issue #37 fix pass)."""
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
        drafts, served hits ``draft: false`` and staged hits ``draft: true``.
        Serves pinned snapshot bytes on the managed route, so the pinned digest
        is re-checked first — mid-session tampering refuses here exactly like
        ``get_metric`` (issue #37 fix pass)."""
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


def _qualified_source_refs(source: object) -> list[str | None]:
    """The QUALIFIED table references of one dataset source (spec 0013 §4,
    issue #53): a bare dotted identifier path is itself; a SELECT keeps every
    FROM/JOIN target WITH its qualification (a CTE or otherwise unresolvable
    name stays what it is and fails the exact catalog match — unknown
    dependency identity, never a stripped-name guess). An absent or
    unparseable source yields ``None``."""
    if not isinstance(source, str) or not source.strip():
        return [None]
    text = source.strip()
    if _IDENTIFIER_PATH_RE.fullmatch(text):
        return [text]
    try:
        tree = sqlglot.parse_one(text)
    except Exception:  # unparseable: the compile gate owns the real error
        return [None]
    refs: list[str | None] = [
        ".".join(part.name for part in table.parts) for table in tree.find_all(exp.Table)
    ]
    return refs or [None]


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

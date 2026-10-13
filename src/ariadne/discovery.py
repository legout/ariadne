"""Shared artifact-only discovery: metadata, admission and native read seams.

QueryRuntime reuses this path; only its execution construction renders models
and opens sources (spec 0018 / ADR-0021).
"""

import json
import shlex
from pathlib import Path
from typing import Any

import yaml

from ariadne import admission, answer_examples, authoring_inputs, context
from ariadne.context import list_pages, read_page, resolve_term, search_pages
from ariadne.planner import PlannerError
from ariadne.semantic_graph import SemanticGraph, load_graph
from ariadne.sources import Registry, implicit_registry, load_registry
from ariadne.validate import _registry_identity, candidate_scope_digest, served_tree_digest

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


class DiscoveryRuntime:
    """Source-free artifact reads for legacy roots or one pinned admission."""

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
    ):
        self._load_catalog(semantic_dir, context_dir, admission_record, report_read_errors=True)
        self._qualified = sources is not None or registry is not None
        # Parse source identity only; never open the registered location.
        if registry is None:
            if sources is not None:
                load_registry(sources)
            elif db_path is not None:
                implicit_registry(db_path)
            else:
                raise ValueError("legacy construction requires db_path or sources")
        self._init_artifacts(
            semantic_dir, db_path, sources, staging_dir, admission_record, project_root
        )

    def _load_catalog(
        self, semantic_dir, context_dir, admission_record, *, report_read_errors=False
    ):
        self._catalog_error: str | None = None
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
            try:
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
            except (OSError, yaml.YAMLError, ValueError, TypeError, AttributeError) as exc:
                if not report_read_errors:
                    raise  # QueryRuntime retains the native construction failure.
                self._catalog_error = f"{path}: {type(exc).__name__}: {exc}"
                break  # never return a partially read catalog as available
        if not self._metrics and self._catalog_error is None:
            if admission_record is None:
                raise RuntimeError(f"no governed metrics found under {models}")
            self._context_only = True  # a managed catalog-less admission serves discovery

    def _init_artifacts(
        self, semantic_dir, db_path, sources, staging_dir, admission_record, project_root
    ):
        self.staging_dir = Path(staging_dir)
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
        if self._catalog_error is not None:
            # Avoid rereading broken models for graph metadata; managed consistency
            # checks still run at admission resolution and before serving any group.
            return
        if admission_record is not None:
            self._load_managed_graph(self._semantic_dir)
            if self._context_only and self._graph is None:
                # the managed multi-fact refusal names the missing CATALOG on a
                # context-only snapshot, not a broken admission
                self._admission_reason = MISSING_CATALOG
        else:
            self._load_admission(Path(semantic_dir), db_path, sources)

    @classmethod
    def open_project(cls, project: str | Path, *, staging_dir=None):
        root = Path(project).resolve()
        record, snapshot = admission.resolve_admission(root)
        return cls(
            snapshot / "semantic_layer",
            snapshot / "context_layer",
            None,
            staging_dir=root / "staging" if staging_dir is None else staging_dir,
            registry=admission.approved_registry(record),
            admission_record=record,
            project_root=root,
        )

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

    async def discover(self, query: str, limit: int = 5) -> dict:
        """Compose native reads without execution or cross-kind ranking (spec 0018)."""
        if self._managed is not None:
            self._recheck_pinned()  # global refusal, never a group availability label
        groups = {}
        for kind in ("metrics", "pages", "terms", "examples"):
            try:
                if kind == "metrics":
                    catalog = await self.list_metrics()
                    tokens = context._QUERY_TOKEN_RE.findall(query.lower())
                    matches = [
                        entry
                        for entry in catalog
                        if isinstance(entry, dict)
                        and tokens
                        and set(tokens).issubset(
                            context._QUERY_TOKEN_RE.findall(
                                f"{entry['name']} {entry['description']}".lower()
                            )
                        )
                    ]
                    items = matches[: max(0, limit)]
                    group = {
                        "items": items,
                        "routing_hint": catalog[-1],
                        "total_matches": len(matches),
                        "complete": len(items) == len(matches),
                        "follow_up": [
                            f"ariadne get-metric {shlex.quote(entry['name'])}" for entry in items
                        ],
                    }
                elif kind == "terms":
                    result = await self.resolve_term(query)
                    group = {
                        "result": result,
                        "follow_up": (
                            f"ariadne resolve-term {shlex.quote(query)} --part {result['part'] + 1}"
                            if not result["complete"]
                            else None
                        ),
                        "reminder": "Term discovery never authorizes a join or transform.",
                    }
                else:
                    items = (
                        await self.search_context(query, limit=limit)
                        if kind == "pages"
                        else await self.search_examples(query, limit=limit)
                    )
                    group = {"items": items, "completeness": "unknown"}
                groups[kind] = {"status": "available", **group}
            except PlannerError:
                raise  # admission/identity failures always refuse the whole operation
            except (OSError, ValueError, RuntimeError) as exc:
                groups[kind] = {"status": "unavailable", "reason": str(exc)}
        return {"query": query, "groups": groups}

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
        if self._catalog_error is not None:
            raise ValueError(self._catalog_error)
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

    async def list_context_pages(self) -> list[dict]:
        """Enumerate every served and staged Context Layer page (spec 0015,
        ADR-0020): metadata only — ``path``, ``draft``, ``title`` and the
        advisory ``context_signals`` envelope — served before staged, then
        path, deterministically. No bodies and no query tokens: the
        token-free directory view for discovery and onboarding. Serves
        pinned snapshot bytes on the managed route, so the pinned digest is
        re-checked first exactly like ``search_context``."""
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
        if not draft and self._managed is not None:
            self._recheck_pinned()
        root = self.staging_dir / "context_layer" if draft else self.context_dir
        return read_page(path, root, draft=draft)

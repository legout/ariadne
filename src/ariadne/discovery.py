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
from ariadne.contracts import (  # pyright: ignore[reportMissingImports] — new module, stale analysis index; resolves in the qualified env
    CONSUMER_PROFILE,
)
from ariadne.planner import PlannerError
from ariadne.semantic_graph import SemanticGraph, load_graph
from ariadne.sources import Registry, implicit_registry, load_registry
from ariadne.validate import candidate_scope_digest

# Spec rev 4 §8.12: the explicit route for questions no governed metric answers.
# Shared by list_metrics' trailing hint and the unknown-metric error so both
# name the same two operations.
ROUTING_HINT = (
    "If no governed metric above answers your question, route it to the ad-hoc path: "
    "call list_datasets() to see the queryable tables, then define_metric(definition) "
    "to compute the answer (compiled and executed read-only; not saved). "
    "For bounded record selection over one known table (no aggregation or persistence), "
    "call query_records(request) with {dataset, fields, order, limit?} — never raw SQL."
)

# K4 (issue #44, spec 0010 §6/§9): the SPECIFIC missing-catalog error every
# metric operation keeps on a human-admitted CONTEXT-ONLY snapshot (schemas/
# References, no metrics): discovery and terminology resolution serve the
# admitted context, the metric surface refuses explicitly, and no absent
# model ever triggers a fallback raw-SQL route.
MISSING_CATALOG = (
    "no governed metric catalog: the pinned admitted snapshot carries no semantic "
    "models — metric operations are refused; discovery (search_context) and term "
    "resolution (resolve_term) still serve the admitted context, and no absent "
    "model ever triggers a raw-SQL fallback"
)


# The supported-consumer-profile scope note every contracts entry carries
# (spec 0028 §§4–5): the honest limitation line, not a conformance claim.
CONTRACT_PROFILE_LIMITS = (
    "pinned ODCS v3.2.0 consumer profile: flat scalar field checks (presence, "
    "logical/physical type, required-NULL) and single-dataset DuckDB SQL "
    "quality; enum/unique/primaryKey/transform/nested assertions and other "
    "dialects are preserved but unsupported; observations are as-of, never a "
    "current-compliance claim"
)


class _DiscoverySession:
    """Internal artifact view; public construction is through DiscoveryRuntime."""

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
        source_free: bool = False,
    ):
        self._source_free = source_free
        if source_free:
            self._catalog_error = None
            self.context_dir = Path(context_dir)
            self._metrics = {}
            self._context_only = True
        else:
            self._load_catalog(semantic_dir, context_dir, admission_record, report_read_errors=True)
        self._qualified = sources is not None or registry is not None
        # Parse source identity only; never open the registered location.
        if registry is None and not source_free:
            if sources is not None:
                load_registry(sources)
            elif db_path is not None:
                implicit_registry(db_path)
            else:
                raise ValueError("internal artifact sessions require a source identity")
        self._init_artifacts(semantic_dir, db_path, sources, admission_record, project_root)

    def _load_catalog(
        self, semantic_dir, context_dir, admission_record, *, report_read_errors=False
    ):
        self._catalog_error: str | None = None
        self.context_dir = Path(context_dir)
        models = Path(semantic_dir) / "models"
        # K4 (issue #44, spec 0010 §6): a MANAGED context-only admitted snapshot
        # (no semantic models — schemas/References only) constructs for
        # discovery and term resolution; every metric operation then refuses
        # with the SPECIFIC missing-catalog error.
        self._context_only = False
        if not models.is_dir():
            if admission_record is None:
                raise RuntimeError(
                    f"no semantic models under {models} — author a Git project proposal first"
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

    def _init_artifacts(self, semantic_dir, db_path, sources, admission_record, project_root):
        self._graph: SemanticGraph | None = None
        self._admission: dict | None = None
        self._admission_reason: str | None = None
        self._admission_db = db_path
        self._admission_sources = sources
        self._semantic_dir = Path(semantic_dir)
        self._managed = admission_record
        self._project = Path(project_root).resolve() if project_root is not None else None
        self._examples_root = self._project
        if self._source_free:
            self._admission_reason = "the project has no admitted snapshot"
            return
        if self._catalog_error is not None:
            return
        if admission_record is not None:
            self._load_managed_graph(self._semantic_dir)
            if self._context_only and self._graph is None:
                self._admission_reason = MISSING_CATALOG
        else:
            self._admission_reason = "a valid Git admission is required for public discovery"

    def _load_managed_graph(self, semantic_dir: Path) -> None:
        """The Git-review admission is the multi-fact graph's admission:
        ``query_metrics``/``query_detail`` serve only when the pinned snapshot
        itself carries a loadable graph."""
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
        or a withdrawn source approval is a staleness refusal; the runtime
        never serves mutated pinned bytes."""
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
            "revision": record.get("commit"),
            "proposal": record.get("proposal"),
            "review_digest": record.get("review_digest"),
            "artifact_digest": record.get("artifact_digest"),
            "confirmed": record.get("confirmed"),
            "validation": record.get("validation"),
        }

    def _contracts_group(self, query: str, limit: int) -> dict:
        """The bounded contracts group of ``discover`` (spec 2028 §7, issue
        #77/C1): ONLY the pinned admitted snapshot's contracts — producer
        ID/version, native binding and model/dataset identity, the
        supported-profile limitations and the matching stored observation's
        as-of/eligibility. Never candidate/worktree content, never a source
        read, and absent/expired evidence is reported honestly, never
        regenerated."""
        if self._source_free:
            raise ValueError(
                "no admitted snapshot is available — contract discovery serves "
                "only a pinned admitted revision"
            )
        if self._managed is None:
            raise ValueError("contracts serve only a Git admission")
        record = self._managed
        view = record.get("contracts") or {}
        bindings = view.get("bindings") or []
        observations = {
            observation.get("binding"): observation
            for observation in view.get("observations") or []
            if isinstance(observation, dict)
        }
        max_age_hours = (
            authoring_inputs.project_inspection_limits(self._project)["receipt_max_age_hours"]
            if self._project is not None
            else None
        )
        items = []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            observation = observations.get(binding.get("id"))
            eligibility = "unknown"
            if max_age_hours is not None and observation is not None:
                from ariadne import (  # pyright: ignore[reportMissingImports,reportAttributeAccessIssue] — stale analysis index; resolves in the qualified env
                    contract_inspection,
                )

                eligibility = contract_inspection.snapshot_observation_eligibility(
                    self.context_dir.parent, record, binding, observation, max_age_hours
                )
            items.append(
                {
                    "contract": {
                        "id": binding.get("contract_id"),
                        "version": binding.get("contract_version"),
                    },
                    "binding": binding.get("id"),
                    "object_id": binding.get("object_id"),
                    "asset": binding.get("asset"),
                    "model": binding.get("model"),
                    "dataset": binding.get("dataset"),
                    "profile": CONSUMER_PROFILE,
                    "limitations": CONTRACT_PROFILE_LIMITS,
                    "revision": record.get("commit"),
                    "observation": None
                    if observation is None
                    else {
                        "observed_at": observation.get("observed_at"),
                        "outcome": observation.get("outcome"),
                        "scope": observation.get("scope"),
                        "eligibility": eligibility,
                    },
                }
            )
        bound_pairs = {
            (binding.get("contract_id"), binding.get("contract_version")) for binding in bindings
        }
        for document in view.get("documents", []):
            if (document.get("id"), document.get("version")) not in bound_pairs:
                items.append(
                    {
                        "contract": {"id": document.get("id"), "version": document.get("version")},
                        "binding": None,
                        "observation": None,
                        "revision": record.get("commit"),
                        "profile": CONSUMER_PROFILE,
                        "limitations": CONTRACT_PROFILE_LIMITS,
                    }
                )
        tokens = set(context._QUERY_TOKEN_RE.findall(query.lower()))
        matches = [
            item
            for item in items
            if tokens.issubset(
                context._QUERY_TOKEN_RE.findall(json.dumps(item, default=str).lower())
            )
        ]
        selected = matches[: max(0, limit)]
        group = {
            "items": selected,
            "total_matches": len(matches),
            "complete": len(selected) == len(matches),
            "reminder": "scoped as-of evidence, never current compliance or human approval",
        }
        if self._project is not None:
            from ariadne.contract_inspection import contract_content_bytes

            ceiling = authoring_inputs.project_inspection_limits(self._project)["response_bytes"]
            while selected and contract_content_bytes(group) > ceiling:
                selected.pop()
                group["complete"] = False
            if contract_content_bytes(group) > ceiling:
                raise ValueError("contract response ceiling cannot carry the summary")
        return group

    async def discover(self, query: str, limit: int = 5) -> dict:
        """Compose native reads without execution or cross-kind ranking (spec 0018)."""
        if self._managed is not None:
            self._recheck_pinned()  # global refusal, never a group availability label
        groups = {}
        for kind in ("metrics", "pages", "terms", "examples", "contracts"):
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
                elif kind == "contracts":
                    group = self._contracts_group(query, limit)
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
        if self._source_free:
            raise ValueError("no admitted snapshot is available")
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
        self,
        query: str,
        limit: int = 10,
        include_history: bool = False,
        include_sql: bool = False,
        *,
        proposal: str | None = None,
        revision: str | None = None,
    ) -> list[dict]:
        """Search admitted Examples by default, or one explicitly selected candidate."""
        if (proposal is None) != (revision is None):
            raise ValueError("--proposal and --revision are required together")
        if proposal is not None:
            assert revision is not None
            if self._project is None:
                raise ValueError("candidate Example search requires a managed --project")
            return answer_examples.search_candidate(
                self._project,
                query,
                proposal=proposal,
                revision=revision,
                limit=limit,
                include_history=include_history,
                include_sql=include_sql,
            )
        if self._managed is not None:
            self._recheck_pinned()
            return answer_examples.search_admitted(
                self.context_dir.parent,
                query,
                limit=limit,
                include_history=include_history,
                include_sql=include_sql,
            )
        if self._source_free:
            return []
        raise ValueError("Examples are available only from a Git admission or explicit candidate")

    async def search_context(self, query: str, limit: int = 10) -> list[dict]:
        """Search only the admitted Context snapshot."""
        if self._source_free:
            return []
        if self._managed is not None:
            self._recheck_pinned()
        return search_pages(query, limit, [(self.context_dir, False)])

    async def resolve_term(self, request: str | dict, *, part: int = 1) -> dict:
        """Resolve one shared business term or exact ``{resource, column}``
        field lookup against the served context (spec 0010 §6, plan §2; the
        shared read-only resolver lives in
        :func:`ariadne.context.resolve_term`): bounded matching
        concept/representation identities with their exact bindings, required
        scope, ambiguity, unconfirmed claim status, freshness and actual
        page/source citations. Resolves the PINNED admitted context only
        (never proposal drafts); the managed route re-checks the pinned bytes
        first and carries the admission provenance alongside the matches. The
        resolver applies no transform, rewrites no SQL and authorizes no join;
        ``search_context`` keeps its lexical ranking and passage pointers
        unchanged."""
        if self._source_free:
            return resolve_term([], request, part=part)
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
        """List admitted Context metadata without opening a source."""
        if self._source_free:
            return []
        if self._managed is not None:
            self._recheck_pinned()
        return list_pages([(self.context_dir, False)])

    async def read_context_page(self, path: str) -> dict:
        """Read one exact page from the admitted Context snapshot."""
        if self._source_free:
            raise ValueError("no admitted Context snapshot; use Authoring for a candidate")
        if self._managed is not None:
            self._recheck_pinned()
        return read_page(path, self.context_dir, draft=False)


class DiscoveryRuntime:
    """Public source-free factory for admitted-project discovery."""

    def __new__(cls, *args, **kwargs):
        raise TypeError(
            "DiscoveryRuntime is a project factory; use DiscoveryRuntime.open_project(project)"
        )

    @classmethod
    def open_project(cls, project: str | Path) -> _DiscoverySession:
        root = Path(project).resolve()
        if admission.load_current(root) is None:
            return _DiscoverySession(
                root / "semantic_layer",
                root / "context_layer",
                None,
                project_root=root,
                source_free=True,
            )
        record, snapshot = admission.resolve_admission(root)
        return _DiscoverySession(
            snapshot / "semantic_layer",
            snapshot / "context_layer",
            None,
            registry=admission.approved_registry(record),
            admission_record=record,
            project_root=root,
        )

"""Git-backed harness-led authoring for new data projects.

``AuthoringProject`` exposes revision-checked proposal edits, source approval,
measured external document inputs, whole-candidate validation and review.
Durable authored bytes live only in Git candidates/admitted snapshots; approval
and validation evidence stays in operator-owned ``.ariadne/`` state.

Original documents remain under operator-controlled input roots or exact
approved object URIs; reads derive digest and conversion from one byte snapshot.
Human source approval and Git Review Admission remain distinct.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages; the guarded statement seam's error type
import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import exp  # pyright: ignore[reportMissingImports] — same

from ariadne import (
    answer_examples,
    authoring_context,
    authoring_contracts,  # pyright: ignore[reportMissingImports,reportAttributeAccessIssue] — new module, stale analysis index; resolves in the qualified env
    authoring_inputs,  # noqa: F401 — re-export: the historical seam
    authoring_semantic,
    authoring_sources,
    context,
    contract_inspection,  # pyright: ignore[reportMissingImports,reportAttributeAccessIssue] — same
    execution,
    profiler,
    proposals,
)
from ariadne.author import MAX_ROUNDS, _bundle_errors, _load_frontmatter_meta
from ariadne.authoring_inputs import (  # noqa: F401 — re-export: the historical seam
    EVIDENCE_PART_CHARS,
    MAX_DOCUMENTS_PER_CALL,
    MAX_RAW_EXAMPLES,
    SEED_NOTES_REL,
    _convert_snapshot,
    _document_bytes,
    _evidence_record,
    _fetch_object_bytes,
    _input_root,
    _lstat,
    _project_documents_config,
    _sha256_hex,
    bytes_evidence,
    document_evidence,
    effective_inspection_limits,
    project_inspection_limits,
)
from ariadne.context import (  # noqa: F401 — the K1 generated-page seam (issue #41)
    _EVIDENCE_SUMMARY_KEYS,
    _canonical_digest,
    build_dataset_page,
    build_native_dataset_page,
    build_native_table_page,
    build_table_page,
    candidate_digest,
    confirmation_binding_digest,  # K4 fix pass: the effective identity a confirmation binds
    evidence_counterevidence,  # K4 fix pass: counterevidence named at validation/review
    generated_page_filename,
    mapping_assertion_digest,  # K4 (issue #44): the declaration identity of a mapping
    resolve_term,  # K2 (issue #42): the shared read-only term resolver
    validate_inspection_candidate,
)
from ariadne.render import render
from ariadne.semantic_graph import load_graph
from ariadne.sources import _URI_SCHEME_RE, collection_resource, parse_resource, table_resource
from ariadne.validate import (
    VALIDATOR_VERSION,
    CheckOutcome,
    _model_entries,
    candidate_scope_digest,
    validate,
    validator_identity,
)

_GENERATED_FILES = frozenset({"index.md", "log.md"})


def _fsync_tree(root: Path) -> None:
    """Durably sync a copied admission snapshot before its final rename."""
    entries = sorted(root.rglob("*"))
    for path in entries:
        if path.is_file():
            proposals._fsync_path(path)
    for path in sorted(
        (path for path in entries if path.is_dir()), key=lambda path: len(path.parts), reverse=True
    ):
        proposals._fsync_path(path)
    proposals._fsync_path(root)


_LAYER_EDITORS = {
    "model": authoring_semantic,
    "graph": authoring_semantic,
    "page": authoring_context,
    "seed_notes": authoring_context,
    # spec 0028 §3 (issue #77/C1): producer contract documents and the fixed
    # native binding document are typed authored artifacts — the same
    # revision-checked read/edit seam, no arbitrary file paths
    "contract": authoring_contracts,
    "contract_bindings": authoring_contracts,
}
EDIT_KINDS = tuple(sorted(_LAYER_EDITORS))


def _citation_record(
    reference: str, project: Path, source_id: str | None = None
) -> tuple[dict, str | None]:
    """Observe one permitted document and check any native digest-prefix binding."""
    resource, title, data = _document_bytes(reference, project)
    _convert_snapshot(data, Path(title).suffix, display=title)
    digest = _sha256_hex(data)
    binding_error = None
    if isinstance(source_id, str) and re.fullmatch(r"[0-9a-f]{12}", source_id):
        if not digest.startswith(source_id):
            binding_error = (
                f"recorded document digest binding {source_id} does not match "
                f"permitted original bytes (current sha256 prefix {digest[:12]})"
            )
    return {"resource": resource, "title": title, "digest": digest}, binding_error


def _authorize_dataset_sources(tree: Path, approved: set[str]) -> None:
    """Refuse candidate sources outside the approved registry before bind/audit.

    Every table in rendered model SQL is walked through SQLGlot; table
    functions, direct file/URI scans, unqualified tables and identities outside
    the approved set never reach validation's source connection.
    """
    for name, envelope in _model_entries(tree):
        model = envelope["semantic_model"][0]
        if isinstance(model, dict) and len(model.get("datasets") or []) > 1:
            raise ValueError(
                f"model '{name}': multi-dataset (domain-layout) models are refused "
                "at the source-access boundary until authorization understands the "
                "normalized graph — submit one dataset per model"
            )
        try:
            rendered = render(envelope)
        except Exception:  # RenderError et al.: the compile gate owns the error
            continue
        try:
            parsed = sqlglot.parse_one(rendered, dialect="duckdb")
        except Exception:
            continue  # render() re-parses its output; unreachable in practice
        ctes = {cte.alias_or_name for cte in parsed.find_all(exp.CTE)}
        names = ", ".join(sorted(approved)) or "none approved yet"
        for table in parsed.find_all(exp.Table):
            this = table.this
            if not isinstance(this, exp.Identifier):
                raise ValueError(
                    f"model '{name}': the dataset source uses the table function "
                    f"{this.name or type(this).__name__}(...) — only SELECT/joins over "
                    f"approved registry tables ({names}) enter validation; raw scans "
                    "of server files or object URIs are refused before any execution"
                )
            ref = table.sql(dialect="duckdb")
            if table.catalog or table.db:
                if (table.catalog or table.db) not in approved:
                    raise ValueError(
                        f"model '{name}': {ref} is not an approved source registry "
                        f"identity (approved: {names}) — validation never opens "
                        "locations outside the approved registry"
                    )
            elif table.name in ctes:
                continue
            elif "/" in table.name or _URI_SCHEME_RE.match(table.name):
                raise ValueError(
                    f"model '{name}': the dataset source scans {table.name!r} directly "
                    "— only SELECT/joins over approved registry tables enter validation; "
                    "direct file/URI scans are refused before any execution"
                )
            else:
                raise ValueError(
                    f"model '{name}': table '{table.name}' is unqualified — qualify "
                    f"tables with an approved source name ({names})"
                )


def _graph_citation_errors(tree: Path) -> list[str]:
    """Require each multi-fact metric to cite an admitted, contained Policy."""
    if not (tree / "semantic_layer" / "graph.yml").is_file():
        return []
    try:
        graph = load_graph(tree / "semantic_layer")
    except Exception:
        return []  # the validator's graph diagnostics already failed the candidate
    context_root = tree / "context_layer"
    errors: list[str] = []
    for name in sorted(graph.metrics):
        page = context_root / "metrics" / f"{name}.md"
        rel = f"context_layer/metrics/{name}.md"
        if not page.is_file():
            errors.append(
                f"{rel}: multi-fact admission requires a cited metric page for every "
                f"graph metric — '{name}' has none (issue #30); an uncited definition "
                "cannot become a governed multi-fact answer"
            )
            continue
        try:
            meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"{rel}: frontmatter is not valid YAML: {exc}")
            continue
        refs = [
            str(source.get("resource") if isinstance(source, dict) else source or "")
            for source in meta.get("sources") or []
        ]
        cited = [ref for ref in refs if ref.startswith("policies/")]
        if not cited:
            errors.append(
                f"{rel}: multi-fact admission must cite at least one governing policies/... page"
            )
        for ref in cited:
            target = (context_root / ref).resolve()
            policy_root = (context_root / "policies").resolve()
            if not target.is_relative_to(policy_root) or not target.is_file():
                errors.append(
                    f"{rel}: cited policy '{ref}' does not resolve inside "
                    "context_layer/policies/ — a citation outside the Policy "
                    "directory fails multi-fact admission"
                )
    return errors


class AuthoringProject:
    """One host-configured data project and its Git-backed authoring proposals
    (spec 2026-10-02-0009 §3–4, plan §2). Callers address system-generated
    proposal IDs and typed artifact identities within this fixed project —
    never repository/worktree roots, operational state files or arbitrary
    filesystem paths. Every method returns a JSON-shaped envelope reusable by
    the CLI, MCP and Agent adapters; every failure is an explicit, actionable
    error that preserves the worktree, history and evidence.

    This slice (G2) owns proposal lifecycle and complete artifact edits;
    ``validate_proposal``/``review_proposal`` are G4. Source proposals,
    operator approval and measured inputs are G3 (issue #35), routed through
    :mod:`ariadne.authoring_sources` (``propose_sources``/``approve_sources``/
    ``inputs``) and :mod:`ariadne.authoring_inputs` (``document_evidence``).
    """

    def __init__(self, project: str | Path = "."):
        self.project = Path(project)

    def start_proposal(self, base_revision: str | None = None) -> dict:
        """Start one isolated proposal: a system-generated ID, its branch and
        worktree (derived, never caller-supplied), from the optional known base
        revision or the current one; a repository with no commits yet gets its
        human-created initial artifact revision first. Returns
        ``{proposal, base_revision, candidate_revision}``."""
        return proposals.start_proposal(self.project, base_revision=base_revision)

    def read_artifact(self, proposal: str, identity: dict, *, part: int = 1) -> dict:
        """Read one artifact of the proposal's current candidate revision —
        inherited from the base when never edited — addressed by a typed
        identity (``{kind: model, name}``, ``{kind: graph}``,
        ``{kind: page, section, name}``, ``{kind: seed_notes}``), in bounded
        parts. Returns ``{proposal, revision, path, content, part, parts,
        chars, complete}`` or a specific missing-artifact error."""
        if not isinstance(identity, dict) or identity.get("kind") not in _LAYER_EDITORS:
            got = identity.get("kind") if isinstance(identity, dict) else identity
            raise ValueError(
                f"an artifact identity is a typed object with kind one of {EDIT_KINDS}, got {got!r}"
            )
        editor = _LAYER_EDITORS[identity["kind"]]
        kwargs = (
            {"project": self.project, "proposal": proposal}
            if identity["kind"] == "contract"
            else {}
        )
        rel = editor.resolve_identity(identity, **kwargs)
        return proposals.read_artifact(self.project, proposal, rel, part=part)

    def edit_proposal(self, proposal: str, expected_revision: str, edit: dict) -> dict:
        """Apply one complete artifact edit — a discriminated JSON object
        (``{kind: model, name, content}``, ``{kind: graph, content}``,
        ``{kind: page, section, name, content}``, ``{kind: seed_notes,
        content}``) — to the proposal, requiring the expected candidate
        revision (stale or competing writers are refused before any write; an
        identical edit at the current revision is a no-op). Returns
        ``{proposal, revision, changed, path}``."""
        if not isinstance(edit, dict) or edit.get("kind") not in _LAYER_EDITORS:
            got = edit.get("kind") if isinstance(edit, dict) else edit
            raise ValueError(
                "an edit is a discriminated JSON object with kind one of "
                f"{EDIT_KINDS} (typed source proposals arrive through the "
                f"propose_sources operation), got kind {got!r}"
            )
        editor = _LAYER_EDITORS[edit["kind"]]
        kwargs = (
            {"project": self.project, "proposal": proposal} if edit["kind"] == "contract" else {}
        )
        rel, content = editor.resolve_edit(edit, **kwargs)
        return proposals.edit_proposal(self.project, proposal, expected_revision, rel, content)

    # ------------------- G3 (issue #35): sources, approval, measured inputs

    def propose_sources(
        self,
        proposal: str,
        expected_revision: str,
        sources: list[dict] | tuple[dict, ...],
        storages: dict | None = None,
    ) -> dict:
        """Append validated typed source entries — plus optional named storage
        profile definitions (spec 0025 §5) — to the candidate's registry
        (``ariadne.yaml``) through the revision-checked edit seam and return
        ``{proposal, revision, changed, source_digest, sources}`` — the digest
        of the candidate's full RESOLVED identity (paths resolved against the
        host project root) plus the precise resolved locations. Inert data:
        nothing is opened, and the candidate cannot grant itself approval."""
        return authoring_sources.propose_sources(
            self.project, proposal, expected_revision, sources, storages
        )

    def approve_sources(self, proposal: str, revision: str, source_digest: str) -> dict:
        """HUMAN-ONLY (the CLI command; never an MCP/Agent tool): record the
        operator's permission for the EXACT resolved source identity of the
        proposal's current candidate revision, outside Git artifacts under
        ``.ariadne/source-approvals.json`` — without editing the
        already-committed candidate."""
        return authoring_sources.approve_sources(self.project, proposal, revision, source_digest)

    def inputs(
        self,
        proposal: str,
        *,
        documents: Sequence[str] = (),
        part: int = 1,
        sample_rows: int | None = None,
    ) -> dict:
        """The proposal's measured inputs: the profile of the APPROVED
        resolved registry identity (an unapproved or changed entry is an
        explicit error and never opens anything), converted evidence for the
        referenced documents inside the operator's host-root document
        boundary, and the candidate's Seed Notes evidence — bounded, with
        stable digests, from the recorded candidate revision."""
        return authoring_sources.inputs(
            self.project, proposal, documents=list(documents), part=part, sample_rows=sample_rows
        )

    # ----------------------- G4 (issue #36): validate and review the candidate

    def validate_proposal(self, proposal: str, expected_revision: str) -> dict:
        """Validate the proposal's effective candidate at its EXACT final
        revision: finalize the deterministic generated artifacts, commit any
        generated changes, then run the complete check stack — existing
        schema/compile/bind/grain/relationship audits over the approved source
        identity plus the page-contract and citation gates — against the
        materialized final commit (never the earlier input commit). Returns
        that revision with the report/errors; the evidence is stored separately
        under ``.ariadne/validation/``. Validation is not admission (G5)."""
        return validate_proposal(self.project, proposal, expected_revision)

    def review_proposal(self, proposal: str, *, part: int = 1) -> dict:
        """Read the proposal's candidate (read-only; reading is never
        sign-off): current/base revisions, change inventory, bounded effective
        bodies, citations, the validation report with its full check scope and
        a review digest binding the exact reviewed identity."""
        return review_proposal(self.project, proposal, part=part)

    # ------------- K1 (issue #41): explicit physical schema refresh

    def refresh_schema(
        self, proposal: str, expected_revision: str, assets: list[dict] | tuple[dict, ...]
    ) -> dict:
        """Regenerate the core-owned physical schema facts of an EXPLICIT
        catalog asset list inside the selected proposal (plan §2
        ``refresh_schema``, spec 0010 §4): reads go through the
        operator-APPROVED resolved source identity only, writes are
        revision-checked complete page edits, authored summary/column meaning
        is preserved for identical column identity/type (removed or
        type-changed columns keep their old meaning as reviewable history,
        never a rename guess), and an identical refresh against identical
        inputs is a no-op (the candidate revision does not move). Returns the
        resulting revision, the generated page identities and the schema-change
        flags. Refresh is never admission (K4 owns that)."""
        return refresh_schema(self.project, proposal, expected_revision, assets)

    def resolve_term(self, proposal: str, request: str | dict, *, part: int = 1) -> dict:
        """Resolve one shared business term or exact ``{resource, column}``
        field lookup against an EXPLICITLY selected proposal's current
        candidate revision (plan §2 ``resolve_term`` row, spec 0010 §6):
        read-only — the candidate is materialized from the exact commit, never
        a mutable worktree, and the response keeps the candidate identity
        (proposal + revision + ``candidate: true``) visible beside the shared
        resolver envelope (:func:`ariadne.context.resolve_term`). Authoring
        gains no query, approval or admission authority here."""
        project = self.project.resolve()
        proposals._load_record(project, proposal)  # identity errors early
        with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
            record = proposals._load_record(project, proposal)  # authoritative
            proposals._check_coherent(project, record)
            with tempfile.TemporaryDirectory(prefix="ariadne-resolve-") as tmp:
                tree = Path(tmp) / "bundle"
                tree.mkdir()
                _materialize(project, proposal, record["candidate_revision"], tree)
                result = resolve_term(
                    [(tree / "context_layer", False)],
                    request,
                    part=part,
                    # the operator's evidence age budget drives the candidate
                    # side's explicit as_of/stale freshness states too (K4 fix
                    # pass, finding 3); no confirmations exist on a candidate
                    evidence_max_age_hours=project_inspection_limits(project)[
                        "receipt_max_age_hours"
                    ],
                )
        result.update(
            {
                "proposal": proposal,
                "revision": record["candidate_revision"],
                "candidate": True,
            }
        )
        return result

    # --------------- K3 (issue #43): bounded mapping inspection + receipts

    def inspect_mapping(
        self, proposal: str, expected_revision: str, candidate: object, limits: object = None
    ) -> dict:
        """Measure one structured mapping-inspection candidate (plan §2
        ``inspect_mapping``, spec 0010 §7): a discriminated JSON object of
        exactly the approved families — equality/composite, string prefix
        with an optional scoped prefix lookup, explicit scoped lookup — over
        the operator-APPROVED resolved source identity, through guarded
        core-generated read-only statements with parameterized scope, under
        the operator-owned finite ceilings (a request may only LOWER them).
        Returns the core receipt (eligible/tested denominators, actual scope,
        null/missing/unknown-lookup counts, coverage, mismatches, collisions,
        multiplicity, containment-versus-pairing basis, sampled/full
        designation, ``complete|inconclusive`` outcome with limitations)
        retained atomically in the ``.ariadne/`` evidence area — never a page
        edit, approval or admission. Aggregate counts are the default; raw
        identifier examples need the operator's explicit sample permission.
        """
        return inspect_mapping(self.project, proposal, expected_revision, candidate, limits=limits)


# ------------------------------------- slice 5 (issue #36/G4): validation/review

# The finalize commit's fixed message (the only commits validation itself
# creates): deterministic generated artifacts only, never a review decoration.
FINALIZE_COMMIT_MESSAGE = "ariadne: finalize generated artifacts"


def _cited_resources(meta: dict) -> list[tuple[str, str | None]]:
    """Distinct citation resources and their existing ``sources[].id`` bindings."""
    resources: list[tuple[str, str | None]] = []
    for source in meta.get("sources") or []:
        resource = (
            source.get("resource") if isinstance(source, dict) and "resource" in source else source
        )
        if isinstance(resource, str) and resource:
            source_id = source.get("id") if isinstance(source, dict) else None
            citation = (resource, source_id if isinstance(source_id, str) else None)
            if citation not in resources:
                resources.append(citation)
    extension = meta.get("ariadne") if isinstance(meta.get("ariadne"), dict) else None
    for representation in (extension or {}).get("representations") or []:
        if not isinstance(representation, dict):
            continue
        bindings = [*(representation.get("fields") or []), *(representation.get("scope") or [])]
        for binding in bindings:
            if isinstance(binding, dict) and isinstance(binding.get("resource"), str):
                citation = (binding["resource"], None)
                if citation not in resources:
                    resources.append(citation)
    return resources


def _tree_citation(tree: Path, page: Path, resource: str) -> str | None:
    """The tree-relative path of a citation that resolves INSIDE the effective
    bundle — context-root-relative first (``policies/x.md`` — the runtime's
    citation contract), then the citing page's own directory (the generated
    computations cite ``../../semantic_layer/...``), then bundle-root-relative
    (``data/seed_notes.md``); None when it resolves nowhere. Containment is
    checked against the materialized TREE (the whole candidate is the citation
    universe): an escaping traversal is just another unresolvable reference."""
    root = tree.resolve()
    context = tree / "context_layer"
    for base in (context, page.parent, tree):
        try:
            resolved = (base / resource).resolve()
        except OSError:  # pragma: no cover - pathological resource spellings
            return None
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved.relative_to(root).as_posix()
    return None


def _verified_citations(
    tree: Path, project: Path, source_names: set[str]
) -> tuple[list[dict], list[str]]:
    """Verify every citation of the effective bundle's OKF pages (spec §3–4):
    a citation resolves as a CANDIDATE page (inside the effective tree), an
    APPROVED source-table identity, or a DOCUMENT inside the operator's input
    boundary — verified through the shared boundary seam with its sha256
    (:func:`_citation_record`), matching the revision-bound proposal review
    contract. Returns (verified citations, errors): a citation resolving
    nowhere is broken, and broken INHERITED citations block even when only one
    file changed (AC2)."""
    citations: dict[tuple[str, str], dict] = {}
    errors: list[str] = []
    context_dir = tree / "context_layer"
    pages = sorted(context_dir.rglob("*.md")) if context_dir.is_dir() else []
    for page in pages:
        rel = f"context_layer/{page.relative_to(context_dir)}"
        try:
            meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            # a malformed draft page is a validation FAILURE the page gate
            # already names structurally; here it becomes a citation
            # diagnostic in the report — never an exception that escapes
            # validate_proposal with the whole report (spec §4)
            errors.append(
                f"{rel}: frontmatter is not valid YAML — its citations cannot be verified: {exc}"
            )
            continue
        for resource, source_id in _cited_resources(meta):
            if (bundle_rel := _tree_citation(tree, page, resource)) is not None:
                citations[("bundle", resource)] = {
                    "resource": resource,
                    "kind": "bundle",
                    "path": bundle_rel,
                }
            elif resource.startswith("ariadne://"):
                # K1 (issue #41): a canonical catalog asset resource — the
                # identified catalog/profile citation for physical facts. The
                # source it names must be one of the approved registry
                # identities (the approval separately binds the resolved
                # location; a navigation resource can never confer access).
                try:
                    _kind, parts = parse_resource(resource)
                except ValueError as exc:
                    errors.append(
                        f"{rel}: cited catalog resource {resource!r} is not canonical: {exc}"
                    )
                    continue
                if parts[0] not in source_names:
                    errors.append(
                        f"{rel}: cited catalog resource {resource!r} names source "
                        f"{parts[0]!r} which is not an approved registry identity "
                        f"(approved: {', '.join(sorted(source_names)) or 'none'})"
                    )
                    continue
                citations[("asset", resource)] = {
                    "resource": resource,
                    "kind": "catalog_asset",
                    "source": parts[0],
                }
            elif resource in source_names or resource.split(".", 1)[0] in source_names:
                citations[("source", resource)] = {"resource": resource, "kind": "source"}
            else:
                try:  # the operator's document boundary (verified, digest-bound)
                    citation, binding_error = _citation_record(resource, project, source_id)
                except ValueError as exc:
                    errors.append(
                        f"{rel}: cited resource {resource!r} does not resolve as a "
                        "bundle page, approved source identity or operator-bound "
                        f"document — broken citation: {exc}"
                    )
                    continue
                citations[("document", resource)] = {
                    "resource": resource,
                    "kind": "document",
                    "title": citation["title"],
                    "digest": citation["digest"],
                    "location": citation["resource"],
                }
                if binding_error:
                    errors.append(f"{rel}: cited document {resource!r}: {binding_error}")
    knowledge = tree / "knowledge"
    if (tree / "context_integration.yaml").is_file() and knowledge.is_dir():
        # F2 (fix pass, spec0029 §1.5): EVERY captured KB Reference — hidden
        # or unreferenced, with or without mappings — enters the same
        # citation gate. The producer's public parse feeds the lossless
        # view; Core never re-parses KB bytes, a legacy context_layer copy
        # is never a fallback source, and a missing knowledge dependency
        # stays missing.
        for page in sorted(knowledge.rglob("*.md")):
            if page.name in ("index.md", "log.md"):
                continue
            rel_kb = page.relative_to(knowledge).as_posix()
            page_text = page.read_text(encoding="utf-8")
            parsed = _kb_reference_from_text(page_text, rel_kb)
            if parsed is None:
                # #83 (spec0032 §3/§5): EVERY captured technical profile —
                # hidden or unreferenced — enters the same citation gate for
                # its identity-bearing catalog resources: the whole captured
                # KB is validated at admission, and a technical page binding
                # an unapproved source is refused naming page and source.
                for resource in _kb_technical_resources(page_text, rel_kb):
                    rel = f"knowledge/{rel_kb}"
                    try:
                        _kind, parts = parse_resource(resource)
                    except ValueError as exc:
                        errors.append(
                            f"{rel}: technical profile resource {resource!r} is not "
                            f"canonical: {exc}"
                        )
                        continue
                    if parts[0] not in source_names:
                        errors.append(
                            f"{rel}: technical profile resource {resource!r} names "
                            f"source {parts[0]!r} which is not an approved registry "
                            f"identity (approved: {', '.join(sorted(source_names)) or 'none'})"
                        )
                        continue
                    citations[("asset", resource)] = {
                        "resource": resource,
                        "kind": "catalog_asset",
                        "source": parts[0],
                    }
                # #83 review fix F2: the RELATIVE native provenance citations
                # (bundle paths) resolve inside the integrated candidate's
                # knowledge subtree or refuse — a same-path legacy
                # context_layer page is never a fallback, and containment is
                # never papered over with string filtering.
                for resource in _kb_relative_provenance(page_text, rel_kb):
                    rel = f"knowledge/{rel_kb}"
                    resolved = (tree / "knowledge" / resource).resolve()
                    if (
                        resolved.is_relative_to((tree / "knowledge").resolve())
                        and resolved.is_file()
                    ):
                        citations[("bundle", resource)] = {
                            "resource": resource,
                            "kind": "bundle",
                            "path": f"knowledge/{resource}",
                        }
                    else:
                        errors.append(
                            f"{rel}: native provenance citation {resource!r} does not "
                            "resolve inside the integrated candidate's knowledge "
                            "subtree — a same-path legacy context_layer page is "
                            "never a fallback"
                        )
                continue  # ordinary/legacy KB pages carry no structured citations
            view, _full = parsed
            rel = f"knowledge/{rel_kb}"
            for resource, source_id in _cited_resources(view):
                if resource.startswith("ariadne://"):
                    try:
                        _kind, parts = parse_resource(resource)
                    except ValueError as exc:
                        errors.append(
                            f"{rel}: cited catalog resource {resource!r} is not canonical: {exc}"
                        )
                        continue
                    if parts[0] not in source_names:
                        errors.append(
                            f"{rel}: cited catalog resource {resource!r} names source "
                            f"{parts[0]!r} which is not an approved registry identity "
                            f"(approved: {', '.join(sorted(source_names)) or 'none'})"
                        )
                        continue
                    citations[("asset", resource)] = {
                        "resource": resource,
                        "kind": "catalog_asset",
                        "source": parts[0],
                    }
                elif (resolved := (knowledge / resource).resolve()).is_relative_to(
                    knowledge.resolve()
                ) and resolved.is_file():
                    # a KB citation resolves INSIDE the knowledge subtree only
                    citations[("bundle", resource)] = {
                        "resource": resource,
                        "kind": "bundle",
                        "path": f"knowledge/{resource}",
                    }
                else:
                    errors.append(
                        f"{rel}: cited resource {resource!r} does not resolve inside "
                        "the integrated candidate's knowledge subtree — a same-path "
                        "legacy context_layer page is never a fallback"
                    )
    return [citations[key] for key in sorted(citations)], errors


def _document_digests_current(project: Path, citations: list[dict]) -> bool:
    """True when every recorded DOCUMENT citation still resolves to the exact
    verified bytes — changed document evidence must never be presented as the
    unchanged validated candidate's linkage."""
    for citation in citations or []:
        if citation.get("kind") != "document":
            continue
        try:
            _resource, _title, data = _document_bytes(citation["resource"], project)
        except ValueError:
            return False
        if _sha256_hex(data) != citation.get("digest"):
            return False
    return True


def _materialize(project: Path, proposal: str, revision: str, target: Path) -> list[str]:
    """Materialize the EXACT candidate-scope bytes of ``revision`` into
    ``target`` (read from the commit, never a mutable worktree) and return the
    sorted scope paths — the validated/reviewed effective project. An
    empty-project onboarding candidate (no models yet) materializes fine:
    review stays readable and ``validate`` reports the missing models itself."""
    rels: list[str] = []
    for rel, blob in proposals.scope_blobs(project, revision):
        path = target.joinpath(*PurePosixPath(rel).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        rels.append(rel)
    return rels


def _report_view(report) -> dict:
    """The JSON view of one digest-bound ValidationReport."""
    return {
        "scope": report.scope,
        "digest": report.digest,
        "validator_version": report.validator_version,
        "registry_digest": report.registry_digest,
        "registry_label": report.registry_label,
        "files": list(report.files),
        "checks": [
            {"name": check.name, "outcome": check.outcome, "detail": check.detail}
            for check in report.checks
        ],
    }


def _validate_view(
    evidence: dict, evidence_path: Path, *, idempotent: bool, contract_limits: dict
) -> dict:
    """The validate_proposal response envelope (reused verbatim by the
    idempotent no-op retry)."""
    view = {
        "proposal": evidence["proposal"],
        "revision": evidence["commit"],
        "input_revision": evidence["input_revision"],
        "finalized": evidence["commit"] != evidence["input_revision"],
        "ok": evidence["ok"],
        "status": evidence["status"],
        "errors": list(evidence["errors"]),
        "attempts": evidence["repair"]["attempts"],
        "repair_status": evidence["repair"]["status"],
        "artifact_digest": evidence["artifact_digest"],
        "artifact_files": list(evidence["artifact_files"]),
        "source_digest": evidence["source_digest"],
        "approval_digest": evidence.get("approval_digest"),
        "storage_bindings": dict(evidence.get("storage_bindings") or {}),
        "citations": list(evidence["citations"]),
        "report": evidence["report"],
        "performed_checks": list(evidence["performed_checks"]),
        "validator_identity": evidence["validator_identity"],
        **(
            {"execution_identity": evidence["execution_identity"]}
            if evidence.get("execution_identity") is not None
            else {}
        ),
        "contracts": evidence.get("contracts"),
        "evidence": str(evidence_path),
    }
    contract_view = view.get("contracts")
    contract_checks = [check for check in view["report"]["checks"] if check["name"] == "contracts"]
    contract_errors = []
    for check in contract_checks:
        # Contract errors are appended last; match that exact suffix, including
        # diagnostics containing semicolons, without classifying unrelated errors.
        remaining = check["detail"]
        for error in reversed(view["errors"]):
            if remaining == error:
                contract_errors.append(error)
                break
            suffix = f"; {error}"
            if not remaining.endswith(suffix):
                break
            contract_errors.append(error)
            remaining = remaining[: -len(suffix)]
    omitted = set(contract_errors)
    contract_content = {
        "contracts": contract_view,
        "errors": [error for error in view["errors"] if error in omitted],
        "details": [check["detail"] for check in contract_checks],
    }
    if (
        contract_view
        and contract_inspection.contract_content_bytes(contract_content)
        > contract_limits["response_bytes"]
    ):
        marker = "contract response incomplete/refused: truncated; see evidence reference"
        replacement = {
            "errors": [marker],
            "details": [marker],
            "contracts": {"complete": False, "outcome": "refused", "reason": "response_bytes"},
        }
        if (
            contract_inspection.contract_content_bytes(replacement)
            > contract_limits["response_bytes"]
        ):
            replacement = {"errors": ["refused; see evidence"]}
        if (
            contract_inspection.contract_content_bytes(replacement)
            > contract_limits["response_bytes"]
        ):
            replacement = {}
            # The fixed failure envelope/evidence reference is outside the contract budget.
            view["configuration_error"] = (
                "inspection.response_bytes cannot fit a contract refusal; see evidence reference"
            )
        view.update(ok=False, status="invalid")
        # Static contract errors can also occur earlier in the base validator's errors.
        view["errors"] = [
            error for error in view["errors"] if error not in omitted
        ] + replacement.get("errors", [])
        view["report"] = {
            **view["report"],
            "checks": [
                {
                    "name": "contracts",
                    "outcome": "failed",
                    **({"detail": replacement["details"][0]} if "details" in replacement else {}),
                }
                if check["name"] == "contracts"
                else check
                for check in view["report"]["checks"]
            ],
        }
        if "contracts" in replacement:
            view["contracts"] = replacement["contracts"]
        else:
            view.pop("contracts")
    if idempotent:
        view["idempotent"] = True
    return view


def _contract_evidence_eligible(
    project: Path, tree: Path, stored: dict, approval: dict | None
) -> bool:
    """Whether the stored validation's contract evidence is still ELIGIBLE as
    the unchanged candidate's reusable passing validation (spec 0028 §6): an
    expired observation must not return as a reusable pass — the full
    validation re-observes it under the current age budget instead."""
    contracts = stored.get("contracts") or {}
    if not contracts.get("present") or not contracts.get("bindings"):
        return True
    limits = project_inspection_limits(project)
    return (
        approval is not None
        and contract_inspection.contract_content_bytes(contracts) <= limits["response_bytes"]
        and contract_inspection.evidence_eligible(tree, contracts, approval, limits)
    )


def _stale_schema_binding_errors(tree: Path, approval_digest: str | None) -> list[str]:
    """spec 0025 §4 (measurement invalidation): every generated table page —
    the classic context_layer route AND the integrated producer-native
    knowledge/ route (#83 review fix F2, read through the producer's public
    frontmatter parse) — whose measured observations carry a
    ``source_binding`` must carry the CURRENT effective approval digest:
    schema and selected-value evidence measured under a different endpoint
    is stale provenance and refuses validation until the schema is refreshed
    under the current binding. Pages without a measured binding make no
    endpoint claim; a missing optional stamp proves nothing."""
    errors: list[str] = []
    tables_dir = tree / "context_layer" / "tables"
    if tables_dir.is_dir() and approval_digest is not None:
        for page in sorted(tables_dir.rglob("*.md")):
            rel = f"context_layer/tables/{page.relative_to(tables_dir)}"
            try:
                meta = context._load_frontmatter_meta(page.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue  # the page-contract gate owns malformed pages
            ariadne_meta = meta.get("ariadne") if isinstance(meta, dict) else None
            observations = (
                ariadne_meta.get("observations") if isinstance(ariadne_meta, dict) else None
            )
            bound = observations.get("source_binding") if isinstance(observations, dict) else None
            if isinstance(bound, str) and bound and bound != approval_digest:
                errors.append(
                    f"{rel}: its measured schema/value observations are bound to a "
                    f"different effective storage identity ({bound[:12]}, the candidate "
                    f"now validates under {approval_digest[:12]}) — refresh_schema under "
                    "the current endpoint before validation (spec 0025 §4)"
                )
    knowledge_tables = tree / "knowledge" / "tables"
    if knowledge_tables.is_dir() and approval_digest is not None:
        from lumio_wiki import (  # pyright: ignore[reportMissingImports] — optional SDK
            parse_frontmatter,
        )

        for page in sorted(knowledge_tables.rglob("*.md")):
            rel = f"knowledge/tables/{page.relative_to(knowledge_tables)}"
            try:
                full, _body, _start = parse_frontmatter(page.read_text(encoding="utf-8"), rel)
            except Exception:  # noqa: BLE001 — the producer/page gate owns malformed errors
                continue
            profile = full.get("ariadne_profile") if isinstance(full, dict) else None
            native = profile.get("native") if isinstance(profile, dict) else None
            extension = native.get("ariadne") if isinstance(native, dict) else None
            observations = extension.get("observations") if isinstance(extension, dict) else None
            bound = observations.get("source_binding") if isinstance(observations, dict) else None
            if isinstance(bound, str) and bound and bound != approval_digest:
                errors.append(
                    f"{rel}: its measured schema/value observations are bound to a "
                    f"different effective storage identity ({bound[:12]}, the candidate "
                    f"now validates under {approval_digest[:12]}) — refresh_schema under "
                    "the current endpoint before validation (spec 0025 §4)"
                )
    return errors


def validate_proposal(project: str | Path, proposal: str, expected_revision: str) -> dict:
    """Validate the proposal's effective candidate at its EXACT final revision
    (plan §2 ``validate_proposal``, spec §4): finalize the deterministic
    generated artifacts, commit any generated changes, materialize the final
    commit's candidate scope, and run the complete existing check stack over
    it — :func:`ariadne.validate` schema/compile/bind/grain/relationship
    audits against the operator-APPROVED resolved source identity (the G3
    seam; a declared-but-unapproved identity is an explicit error before
    anything opens), the ADR-0007 per-type page contract, the graph-citation
    gate and the verified-citation check. Returns the FINAL revision with the
    report and errors — never the earlier input commit when bytes changed.

    Evidence is stored separately (``.ariadne/validation/<proposal>/<
    commit>.json``, never a committed artifact) binding the commit, the
    COMPLETE artifact digest (generated/bookkeeping/Seed Notes bytes included,
    unlike a served-content-only digest), the resolved source identity, the
    verified citations, the performed check set and the validator identity.
    The bounded repair state is per-proposal and persistent: an unchanged
    retry is idempotent (no attempt consumed, no reset), a changed candidate
    consumes one of the authoring rounds, and exhausting them stays
    ``review_needed`` for the human — creating another commit never resets it."""
    project = Path(project).resolve()
    proposals._load_record(project, proposal)  # identity/belonging errors early
    worktree_root = project / proposals.WORKTREES_REL / proposal
    with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
        record = proposals._load_record(project, proposal)  # authoritative under the lock
        proposals._check_coherent(project, record)
        current = record["candidate_revision"]
        if expected_revision != current:
            raise ValueError(
                f"stale revision: proposal {proposal} is at candidate {current}, the "
                f"validation expected {expected_revision} — re-read the candidate and "
                "retry with the current revision; nothing was written"
            )
        from ariadne import lumio_context  # pyright: ignore[reportAttributeAccessIssue]

        validation_build = lumio_context.validation_build_identity(worktree_root)
        build_context = (
            {"execution_identity": validation_build} if validation_build is not None else {}
        )
        # The G3 seam BEFORE any finalize commit: the candidate's resolved
        # source identity must carry the operator's approval — for its CURRENT
        # effective storage binding (spec 0025 §4: endpoint changes need their
        # own grant; a declaration digest with only a historical grant never
        # authorizes). The finalize pass touches only context_layer bytes, so
        # the input revision's registry identity IS the final revision's.
        resolved_sources, source_digest = authoring_sources.candidate_sources(project, current)
        approval = None
        if resolved_sources is not None:
            assert source_digest is not None
            approval = authoring_sources._effective_grant(
                project, resolved_sources, source_digest, proposal, current
            )
        approval_digest_value = approval.get("approval_digest") if approval else None
        # Idempotent no-op retry: stored evidence for the EXACT current commit
        # with unchanged binding context returns as-is — nothing re-runs and
        # the bounded repair state is neither reset nor advanced.
        stored = proposals.load_validation(project, proposal, current)
        if (
            stored is not None
            and stored.get("execution_identity") == validation_build
            and stored.get("source_digest") == source_digest
            and stored.get("approval_digest") == (approval_digest_value or source_digest)
            and stored.get("validator_identity")
            == validator_identity(stored.get("performed_checks") or [])
            and _document_digests_current(project, stored.get("citations") or [])
            and _contract_evidence_eligible(project, worktree_root, stored, approval)
        ):
            lumio_context.require_validation_build(
                stored, lumio_context.validation_build_identity(worktree_root)
            )
            return _validate_view(
                stored,
                proposals._validation_path(project, proposal, current),
                idempotent=True,
                contract_limits=project_inspection_limits(project),
            )
        repair: dict = dict(record.get("repair") or {"attempts": 0, "status": "open"})
        if repair["attempts"] >= MAX_ROUNDS or repair["status"] == "review_needed":
            raise ValueError(
                f"proposal {proposal} exhausted its {MAX_ROUNDS} bounded validation "
                f"rounds ({repair['attempts']} attempts) and remains review_needed — "
                "this needs human resolution; no agent validation resets the repair "
                "state (spec §4); nothing was written"
            )
        # Finalize BEFORE validation (spec §4): deterministic generated content
        # (no wall-clock restamp), committed as the exact final candidate.
        proposals.refuse_untracked_scope(project, record)
        # K3 (issue #43): verify every structured mapping's cited receipts
        # against the project's evidence records and the current dependency
        # identities, and attach the bounded verified summaries to the
        # Reference pages (deterministic core-authored page edits, committed
        # BEFORE the finalize pass so the regenerated index trees include
        # them; the validated bytes carry the verified evidence).
        current, receipt_errors = _finalize_mapping_evidence(
            project,
            proposal,
            record,
            current,
            source_digest=source_digest,
            approval=approval,
        )
        context.finalize_candidate(worktree_root)
        final = (
            proposals.commit_generated(project, record, message=FINALIZE_COMMIT_MESSAGE) or current
        )
        with tempfile.TemporaryDirectory(prefix="ariadne-candidate-") as tmp:
            root = Path(tmp)
            tree = root / "bundle"
            tree.mkdir()
            rels = _materialize(project, proposal, final, tree)
            # The audit connection opens ONLY the operator-approved resolved
            # identity (the G3 seam) with the grant's FROZEN effective binding
            # (spec 0025 §4): one registry object carrying exactly those
            # resolved entries and pinned endpoints — never a re-resolved
            # environment value after the check.
            approved_registry = (
                authoring_sources.identity_registry(
                    approval["sources"], approval.get("storage_bindings")
                )
                if approval is not None
                else None
            )
            names = {entry["name"] for entry in (approval["sources"] if approval else [])}
            try:  # the source-access boundary BEFORE any bind/audit execution
                _authorize_dataset_sources(tree, names)
                auth_error = None
            except (ValueError, yaml.YAMLError) as exc:
                # an unauthorizable or unparseable model set never reaches the
                # audit connection; the structural gate reports the parse error
                auth_error = str(exc)
            if auth_error is None:
                result = validate(tree, registry=approved_registry)
                errors = list(result.errors)
            else:  # never open the audit connection for an unauthorized source
                result = validate(tree)  # compile-only: the boundary error blocks
                errors = [auth_error, *result.errors]
            page_errors = (
                _bundle_errors(tree)
                + _graph_citation_errors(tree)
                + _stale_schema_binding_errors(
                    tree, approval.get("approval_digest") if approval else None
                )
            )
            # K4 (issue #44): conflicting asserted claims refuse validation
            # alongside the receipt-verification gate
            claim_errors = _asserted_claim_errors(tree)
            example_errors = answer_examples.validate_candidate_records(project, record, tree)
            citations, citation_errors = _verified_citations(tree, project, names)
            errors.extend(page_errors)
            errors.extend(example_errors)
            errors.extend(citation_errors)
            errors.extend(receipt_errors)
            errors.extend(claim_errors)
            # C1 (issue #77, spec 0028 §§4–6): the contract leg — the static
            # document/binding checks plus, for resolved bindings under the
            # operator-approved source identity, the live observation of every
            # bound dataset under the operator's existing inspection ceilings
            # (execution seconds, response bytes, evidence age — the shared
            # K3 ceilings, explicitly extended to contract inspection).
            # Still-applicable retained observations are reused with their
            # ORIGINAL observation time; expired or dependency-mismatched
            # evidence is re-observed, never restamped (spec 0028 §6).
            contract_limits = project_inspection_limits(project)
            contract_evidence, contract_errors = contract_inspection.observe_contracts(
                project,
                tree,
                approval=approval,
                prior_observations=(record.get("contract_observations") or {})
                if validation_build is None
                or record.get("contract_observation_build") == validation_build
                else {},
                limits=contract_limits,
            )
            if contract_evidence.get("present"):
                serialized = contract_inspection.contract_content_bytes(contract_evidence)
                if serialized > contract_limits["response_bytes"]:
                    contract_errors.append(
                        f"the serialized contract evidence is {serialized} bytes, over "
                        f"the {contract_limits['response_bytes']}-byte response ceiling "
                        "— narrow the bound contract profile; nothing was admitted"
                    )
            errors.extend(contract_errors)
            _captured = None
            try:
                _captured, context_errors = lumio_context.candidate(
                    tree, worktree_root / "knowledge", final
                )
            except Exception as exc:
                context_errors = [f"context integration: {type(exc).__name__}: {exc}"]
            errors.extend(context_errors)
            # validate() carries no report at all only when a graph is declared
            # without models (the load owns that failure): the structural
            # outcome owns it explicitly. A context-only candidate (K4, issue
            # #44) arrives WITH a report — its semantic checks are explicitly
            # not_applicable with reasons.
            base_checks = (
                result.report.checks
                if result.report is not None
                else (CheckOutcome("structural", "failed", "; ".join(result.errors)),)
            )
            # the static validate() contracts check is superseded here by the
            # DEFINITIVE Git-Authoring outcome (static + live observation):
            # compile-only static success never attests the admission gate.
            base_checks = tuple(check for check in base_checks if check.name != "contracts")
            if contract_evidence.get("present"):
                contract_check = CheckOutcome(
                    "contracts",
                    "failed" if contract_errors else "passed",
                    "; ".join(contract_errors)
                    or (
                        "document, binding and live approved-source observations "
                        f"complete ({len(contract_evidence.get('observations') or [])} "
                        "bound dataset(s) observed)"
                    ),
                )
            else:
                contract_check = CheckOutcome(
                    "contracts",
                    "not_applicable",
                    "no contract artifacts (contracts/, contract_bindings.yaml) — the "
                    "candidate carries no data contracts",
                )
            checks = (
                CheckOutcome(
                    "source_boundary", "failed" if auth_error else "passed", auth_error or ""
                ),
                *base_checks,
                CheckOutcome(
                    "page_contract",
                    "failed" if page_errors else "passed",
                    "; ".join(page_errors),
                ),
                CheckOutcome(
                    "answer_examples",
                    "failed" if example_errors else "passed",
                    "; ".join(example_errors),
                ),
                CheckOutcome(
                    "citations",
                    "failed" if citation_errors else "passed",
                    "; ".join(citation_errors),
                ),
                CheckOutcome(
                    "mapping_evidence",
                    "failed" if (receipt_errors or claim_errors) else "passed",
                    "; ".join([*receipt_errors, *claim_errors]),
                ),
                contract_check,
                CheckOutcome(
                    "context_integration",
                    "failed"
                    if context_errors
                    else ("not_applicable" if _captured is None else "passed"),
                    "; ".join(context_errors)
                    or ("standalone project; no integrated selector" if _captured is None else ""),
                ),
            )
            # K4 (issue #44): an explicitly not_applicable check was NOT
            # performed — the applicability decision rides the report (each
            # not_applicable outcome carries its reason), never the performed
            # set a current validator identity binds.
            performed = [
                check.name for check in checks if check.outcome not in ("not-run", "not_applicable")
            ]
            artifact_digest = candidate_scope_digest(tree)
            report_view = (
                _report_view(result.report)
                if result.report is not None
                else {
                    "scope": "none (no semantic models)",
                    "digest": None,
                    "validator_version": VALIDATOR_VERSION,
                    "registry_digest": None,
                    "registry_label": None,
                    "files": [],
                    "checks": [],
                }
            )
            # the report the evidence binds carries the FULL check scope: the
            # compiler/audit outcomes plus the wrapper-level gates
            report_view["checks"] = [
                {"name": check.name, "outcome": check.outcome, "detail": check.detail}
                for check in checks
            ]
        lumio_context.require_validation_build(
            build_context, lumio_context.validation_build_identity(worktree_root)
        )
        ok = not errors
        status = "validated" if ok else "invalid"
        # Bounded repair accounting: one round per CHANGED validation (a
        # different commit or a changed binding context — the effective
        # storage binding rides the key, so identical candidate bytes cannot
        # reuse an old-endpoint validation, spec 0025 §4); an identical retry
        # of the same key consumes nothing.
        key = {
            "commit": final,
            **build_context,
            "source_digest": source_digest,
            "approval_digest": approval_digest_value or source_digest,
            "documents": sorted(
                f"{c['resource']}:{c['digest']}" for c in citations if c["kind"] == "document"
            ),
        }
        previous = record.get("validation") or {}
        attempts = repair["attempts"] + (1 if previous.get("key") != key else 0)
        repair = {
            "attempts": attempts,
            "status": "review_needed" if (errors and attempts >= MAX_ROUNDS) else "open",
        }
        evidence = {
            "proposal": proposal,
            "project": str(project),
            "commit": final,
            "input_revision": expected_revision,
            "ok": ok,
            "status": status,
            "errors": errors,
            "artifact_digest": artifact_digest,
            "artifact_files": rels,
            "source_digest": source_digest,
            "source_identity": resolved_sources,
            "source_approval": (
                {"digest": source_digest, "approved_at": approval["approved_at"]}
                if approval is not None
                else None
            ),
            "approval_digest": approval_digest_value or source_digest,
            "storage_bindings": (approval.get("storage_bindings") or {}) if approval else {},
            "citations": citations,
            "report": report_view,
            "performed_checks": performed,
            "validator_identity": validator_identity(performed),
            **build_context,
            # C1 (issue #77, spec 0028 §6): the contract observations bound to
            # this validation — producer identity/version, bindings, live
            # outcomes with their dependency digests and observation times.
            # Bound into the evidence so pre-contract or weaker proof can
            # never attest the contracted-model admission gate.
            **({"contracts": contract_evidence} if contract_evidence.get("present") else {}),
            "repair": repair,
            "validated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        # The proposal record's persistent repair/validation state and the
        # verified citation identities (plan §2) — never reset by a new commit.
        # C1: the retained per-binding contract observations (for reuse with
        # their ORIGINAL time while dependencies and age allow, spec 0028 §6).
        record["repair"] = repair
        record["validation"] = {"commit": final, "ok": ok, "key": key, "attempts": attempts}
        record["citations"] = citations
        record["contract_observations"] = {
            observation["binding"]: observation
            for observation in contract_evidence.get("observations") or []
        }
        record["contract_observation_build"] = validation_build
        proposals._store_record(project, record)
        evidence_path = proposals.store_validation(project, evidence)
        return _validate_view(
            evidence, evidence_path, idempotent=False, contract_limits=contract_limits
        )


def _review_body(rel: str, data: bytes, *, part: int) -> dict:
    """One bounded body entry of the review inventory: part ``part`` of the
    artifact when it has one, and an honestly EMPTY ``exhausted`` entry when
    the artifact has no such part. The part bound applies PER-ARTIFACT (plan
    §2 bounded-part review contract), so a short artifact (e.g.
    ``ariadne.yaml``) never makes the later parts of a longer one
    unreachable — every part of every artifact stays retrievable through
    successive review calls, and no truncated part is ever claimed complete."""
    text = data.decode("utf-8", errors="replace")
    parts = max(1, -(-len(text) // EVIDENCE_PART_CHARS))
    if part > parts:
        return {
            "resource": rel,
            "title": PurePosixPath(rel).name,
            "digest": _sha256_hex(data),
            "chars": len(text),
            "part": part,
            "parts": parts,
            "text": "",
            "complete": False,
            "exhausted": True,  # no part N exists — earlier parts hold the whole body
        }
    record = _evidence_record(
        rel,
        PurePosixPath(rel).name,
        _sha256_hex(data),
        text,
        part=part,
        part_chars=EVIDENCE_PART_CHARS,
    )
    record["exhausted"] = False
    return record


def _change_inventory(project: Path, record: dict) -> list[dict]:
    """The candidate's change inventory versus its base revision, bounded to
    the candidate artifact scope (an unrelated tracked file never leaks into a
    review)."""
    scope = [
        proposals._literal(prefix)
        for prefix in (
            "ariadne.yaml",
            "data/seed_notes.md",
            "semantic_layer",
            "context_layer",
            "answer_examples",
            "contracts",
            "contract_bindings.yaml",
            "context_integration.yaml",
            "knowledge",
        )
    ]
    diff = proposals._git(
        [
            "diff",
            "--name-status",
            "--no-renames",
            record["base_revision"],
            record["candidate_revision"],
            "--",
            *scope,
        ],
        project,
    ).stdout
    inventory = []
    for line in diff.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        inventory.append({"change": status[0], "path": path})
    return inventory


def review_proposal(project: str | Path, proposal: str, *, part: int = 1) -> dict:
    """Read the proposal's effective candidate (plan §2 ``review_proposal``;
    spec §4 — reading a review response is NOT sign-off, and admission is a
    separate human decision in G5): current/base revisions, the change
    inventory, bounded effective bodies with stable digests (the requested
    part applies PER-ARTIFACT; artifacts without that many parts keep their
    inventory entry as an honestly empty ``exhausted`` record), the CURRENT
    source identity and approval state, the verified citations (re-verified
    now: changed document evidence or a moved candidate is reported stale,
    never as an unchanged validated candidate), the stored validation report
    with its full check scope, the expected admitted baseline the record
    binds, and a review digest binding exactly what was reviewed (baseline
    included — a review made against a different served baseline is a
    different review identity). Read-only: nothing is written, moved or reset.
    """
    project = Path(project).resolve()
    proposals._load_record(project, proposal)
    with proposals._file_lock(project / proposals.LOCKS_REL / f"{proposal}.lock"):
        record = proposals._load_record(project, proposal)  # authoritative under the lock
        return _review_candidate(project, proposal, part=part, record=record)


# ------------------------------------ K4 (issue #44): asserted mappings surface


def _kb_reference_view(full_meta: object) -> dict | None:
    """Adapt one integrated KB Reference page (spec0029 §1.5) to the shared
    structured Reference input: the COMPLETE producer-validated native
    mapping rides through — title, description, aliases, sources, status,
    stale_after and every authored advisory field keep their native
    semantics (F3 fix pass: a lossy projection that turns authored metadata
    into unknown is a defect); only ``type`` is added by the view. The
    curated KB stays the one maintained source: this is an in-memory view,
    never a context_layer mirror or a KB write. Returns None for pages
    without a structured reference profile."""
    if not isinstance(full_meta, dict):
        return None
    profile = full_meta.get("ariadne_profile")
    if not isinstance(profile, dict) or profile.get("kind") != "reference":
        return None
    native = profile.get("native")
    if not isinstance(native, dict):
        return None
    extension = native.get("ariadne")
    if not isinstance(extension, dict) or not isinstance(extension.get("mappings"), list):
        return None
    return {"type": "reference", **native}


def _kb_technical_resources(text: str, path: str) -> list[str]:
    """The canonical resource identities one technical profile page binds,
    parsed through the producer's PUBLIC frontmatter parse (#83, spec0032
    §§3/§5 — Core never re-parses KB bytes with its own YAML loader): the
    core_ref resource, the native resource field, the dataset tables links,
    the supported observation citations and the CANONICAL native source
    entries — exactly the identity-bearing fields the citation gate checks
    against the approved registry (#83 review fix F2: full native
    provenance). Malformed pages stay the producer page gate's own error."""
    from lumio_wiki import parse_frontmatter  # pyright: ignore[reportMissingImports] — optional SDK

    try:
        full, _body, _start = parse_frontmatter(text, path)
    except Exception:  # noqa: BLE001 — the producer/page gate owns malformed errors
        return []
    profile = full.get("ariadne_profile") if isinstance(full, dict) else None
    if not isinstance(profile, dict) or profile.get("kind") not in (
        "table",
        "dataset",
        "computation",
    ):
        return []
    resources: list[str] = []
    core_ref = profile.get("core_ref")
    if isinstance(core_ref, dict) and isinstance(core_ref.get("id"), str):
        resources.append(core_ref["id"])
    native = profile.get("native")
    native = native if isinstance(native, dict) else {}
    if isinstance(native.get("resource"), str):
        resources.append(native["resource"])
    extension = native.get("ariadne")
    if isinstance(extension, dict):
        for table in extension.get("tables") or []:
            if isinstance(table, str):
                resources.append(table)
        observations = extension.get("observations")
        citation = observations.get("citation") if isinstance(observations, dict) else None
        if isinstance(citation, str):
            resources.append(citation)
    for entry in native.get("sources") or []:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if isinstance(resource, str) and resource.startswith("ariadne://"):
            resources.append(resource)
    return [resource for resource in dict.fromkeys(resources) if resource.startswith("ariadne://")]


def _kb_relative_provenance(text: str, path: str) -> list[str]:
    """The RELATIVE native provenance citations of one technical profile page
    (native ``sources[].resource`` bundle paths), parsed through the
    producer's PUBLIC frontmatter parse (#83 review fix F2, spec0032 §§5–6):
    these must resolve inside the integrated candidate's knowledge subtree
    through the existing containment gate — an operator-owned document
    outside the captured KB never becomes frozen bundle evidence, and a
    same-path legacy context_layer page is never a fallback."""
    from lumio_wiki import parse_frontmatter  # pyright: ignore[reportMissingImports] — optional SDK

    try:
        full, _body, _start = parse_frontmatter(text, path)
    except Exception:  # noqa: BLE001 — the producer/page gate owns malformed errors
        return []
    profile = full.get("ariadne_profile") if isinstance(full, dict) else None
    if not isinstance(profile, dict) or profile.get("kind") not in (
        "table",
        "dataset",
        "computation",
    ):
        return []
    native = profile.get("native")
    native = native if isinstance(native, dict) else {}
    relative: list[str] = []
    for entry in native.get("sources") or []:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if isinstance(resource, str) and resource and not resource.startswith("ariadne://"):
            relative.append(resource)
    return relative


def _kb_reference_from_text(text: str, path: str) -> tuple[dict, dict] | None:
    """One KB page's (lossless structured-Reference view, full frontmatter)
    parsed through the producer's PUBLIC frontmatter parse (F1 fix pass,
    spec0029 §1.5): Core never re-parses KB bytes with its own YAML loader,
    directly or indirectly. Returns None for pages without a structured
    reference profile; malformed pages stay the page gate's own error."""
    from lumio_wiki import parse_frontmatter  # pyright: ignore[reportMissingImports] — optional SDK

    try:
        full, _body, _start = parse_frontmatter(text, path)
    except Exception:  # noqa: BLE001 — the producer/page gate owns malformed errors
        return None
    view = _kb_reference_view(full)
    return None if view is None else (view, full)


def _reference_mapping_pages(tree: Path) -> list[tuple[str, dict, dict]]:
    """Every structured Reference page of one materialized candidate tree:
    (context-relative page path, frontmatter meta, the ariadne extension).
    Legacy References without the extension stay out; malformed draft pages
    stay out too — the page gate owns their structural errors. Integrated
    candidates (spec0029 §1.5) carry their ONE maintained curated source in
    the knowledge/ subtree: those KB Reference pages are consumed through the
    shared in-memory view above, and a legacy context_layer copy — if any —
    is never a fallback source."""
    if (tree / "context_integration.yaml").is_file():
        pages: list[tuple[str, dict, dict]] = []
        knowledge = tree / "knowledge"
        for page in sorted(knowledge.rglob("*.md")) if knowledge.is_dir() else []:
            if page.name in ("index.md", "log.md"):
                continue
            rel = page.relative_to(knowledge).as_posix()
            parsed = _kb_reference_from_text(page.read_text(encoding="utf-8"), rel)
            if parsed is not None:
                view, _full = parsed
                pages.append((rel, view, view["ariadne"]))
        return pages
    context_dir = tree / "context_layer"
    legacy: list[tuple[str, dict, dict]] = []
    for page in sorted(context_dir.rglob("*.md")) if context_dir.is_dir() else []:
        if page.name in _GENERATED_FILES:
            continue
        rel = page.relative_to(context_dir).as_posix()
        if not rel.startswith("references/"):
            continue
        try:
            meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue  # the page gate owns the malformed-draft error
        extension = meta.get("ariadne") if isinstance(meta, dict) else None
        if isinstance(extension, dict) and isinstance(extension.get("mappings"), list):
            legacy.append((rel, meta, extension))
    return legacy


def _asserted_claim_errors(tree: Path) -> list[str]:
    """Conflicting asserted claims refuse validation (spec 0010 §5/§9, K4):
    two ASSERTED mappings of one Reference over the same relationship — the
    same endpoints and family — with different assertion digests are two
    disagreeing confirmed-usage candidates, not alternatives a human confirms
    one by one. Different or conflicting declarations stay separate labeled
    HYPOTHESES (plan §2); only an unambiguous asserted claim reaches human
    confirmation."""
    errors: list[str] = []
    for rel, _meta, extension in _reference_mapping_pages(tree):
        claimed: dict[tuple, dict] = {}
        for mapping in extension["mappings"]:
            if not isinstance(mapping, dict) or mapping.get("claim") != "asserted":
                continue
            key = (mapping.get("from"), mapping.get("to"), mapping.get("family"))
            digest = mapping_assertion_digest(mapping)
            if key in claimed and claimed[key]["digest"] != digest:
                errors.append(
                    f"context_layer/{rel}: asserted mappings "
                    f"{claimed[key]['id']!r} and {mapping.get('id')!r} claim the same "
                    f"relationship ({mapping.get('from')!r} -> {mapping.get('to')!r}, "
                    f"family {mapping.get('family')!r}) with different declarations — "
                    "conflicting asserted claims refuse validation; keep the "
                    "alternatives as separate labeled hypotheses"
                )
            elif key not in claimed:
                claimed[key] = {"id": mapping.get("id"), "digest": digest}
    return errors


def _mapping_assertions(tree: Path) -> list[dict]:
    """The reviewed candidate's structured mapping assertions (K4, plan §2
    "Admission and automatic capture"): each mapping's page resource,
    reference slug, mapping ID, family, endpoints, claim, verbatim
    declaration, assertion digest, dependencies/evidence and confirmation
    eligibility — the exact surface a human selects from with
    ``--confirm-mapping <reference-slug>:<mapping-id>``. Reading this list is
    NEVER confirmation (spec 0010 §5): a hypothesis is listed for the review
    but never selectable, and only an asserted mapping is confirmable — never
    one whose verified receipts show counterevidence (K4 fix pass, finding 1:
    an asserted claim contradicted by its own cited evidence is
    unsupported)."""
    assertions: list[dict] = []
    for rel, meta, extension in _reference_mapping_pages(tree):
        evidence = meta.get("ariadne_evidence")
        summaries = evidence if isinstance(evidence, dict) else {}
        for mapping in extension["mappings"]:
            if not isinstance(mapping, dict):
                continue
            claim = mapping.get("claim")
            receipts = [
                {
                    "id": summary.get("id"),
                    "digest": summary.get("digest"),
                    "observed_at": summary.get("observed_at"),
                    "designation": summary.get("designation"),
                    "outcome": summary.get("outcome"),
                    "mismatch_count": summary.get("mismatch_count"),
                    "comparison_basis": summary.get("comparison_basis"),
                }
                for summary in summaries.get(mapping.get("id")) or []
                if isinstance(summary, dict)
            ]
            # K4 fix pass (finding 1, spec 0010 §§8–9): an asserted mapping
            # contradicted by its own verified receipts (honest mismatches, an
            # ambiguous pairing basis or an inconclusive outcome) is
            # UNSUPPORTED — it is never selectable for confirmation. A
            # hypothesis carrying the same receipt stays listed (openly
            # labeled, never confirmable).
            counterevidence = [
                named
                for named in (evidence_counterevidence(summary) for summary in receipts)
                if named
            ]
            confirmable = claim == "asserted" and not counterevidence
            if claim == "asserted" and counterevidence:
                note = (
                    "the asserted mapping's verified receipts show counterevidence "
                    f"({'; '.join(counterevidence)}) — an asserted claim contradicted by "
                    "its own cited evidence is unsupported; carry it as a labeled "
                    "hypothesis instead"
                )
            elif confirmable:
                note = (
                    "an asserted mapping is eligible for explicit human confirmation "
                    "(--confirm-mapping)"
                )
            else:
                note = (
                    "a hypothesis is investigative knowledge only — it is never "
                    "selectable as a confirmed assertion"
                )
            assertions.append(
                {
                    "page": rel,
                    "reference": PurePosixPath(rel).stem,
                    "mapping": mapping.get("id"),
                    "family": mapping.get("family"),
                    "from": mapping.get("from"),
                    "to": mapping.get("to"),
                    "claim": claim,
                    "declaration": mapping,
                    # the EFFECTIVE identity a confirmation binds (K4 fix pass,
                    # finding 2): the declaration plus its endpoint
                    # representations' normalized correspondence — review,
                    # admission and retention all compare THIS digest
                    "assertion_digest": (
                        confirmation_binding_digest(meta, mapping)
                        if isinstance(mapping.get("id"), str)
                        else None
                    ),
                    "source_ids": list(mapping.get("source_ids") or []),
                    "receipts": receipts,
                    "confirmable": confirmable,
                    "confirmation_note": note,
                }
            )
    return assertions


def _review_candidate(
    project: Path, proposal: str, *, part: int = 1, record: dict | None = None
) -> dict:
    """The lock-free review core (issue #37/G5): exactly the envelope
    :func:`review_proposal` returns, computed for one loaded record — the
    caller holds the proposal lock (the public review takes it; admission
    already holds the project+proposal locks when it re-derives the review
    digest, and a nested lock acquisition would self-deadlock). K4 (issue
    #44): the envelope carries the candidate's structured mapping assertions
    — each mapping's page/ID/digest/dependencies and confirmation eligibility
    — bound into the review digest, so an admission's mapping selections are
    bound to the exact reviewed identity."""
    if record is None:
        record = proposals._load_record(project, proposal)
    proposals._check_coherent(project, record)
    base = record["base_revision"]
    current = record["candidate_revision"]
    with tempfile.TemporaryDirectory(prefix="ariadne-review-") as tmp:
        tree = Path(tmp) / "bundle"
        tree.mkdir()
        rels = _materialize(project, proposal, current, tree)
        resolved_sources, source_digest = authoring_sources.candidate_sources(project, current)
        bodies = []
        for rel in rels:
            data = (tree / Path(*PurePosixPath(rel).parts)).read_bytes()
            bodies.append(_review_body(rel, data, part=part))
        source_names = {entry["name"] for entry in resolved_sources or []}
        citations, _citation_errors = _verified_citations(tree, project, source_names)
        approval = authoring_sources.approval_state(project, resolved_sources, source_digest)
        approved = approval["approved"]
        artifact_digest = candidate_scope_digest(tree)
        # The stored report binds the exact candidate commit or is absent:
        # a candidate that moved past its validation, a changed source
        # identity, changed document evidence or changed artifact bytes can
        # never be presented as an unchanged validated candidate.
        report = proposals.load_validation(project, proposal, current)
        stale_reasons: list[str] = []
        if report is not None:
            from ariadne import lumio_context  # pyright: ignore[reportAttributeAccessIssue]

            try:
                lumio_context.require_validation_build(
                    report, lumio_context.validation_build_identity(tree)
                )
            except ValueError as exc:
                stale_reasons.append(str(exc))
            if report.get("source_digest") != source_digest:
                stale_reasons.append("the resolved source identity changed since validation")
            if approval["state"] == "unresolved":
                # spec 0025 §4: a required endpoint/region value is unset — the
                # effective binding cannot be resolved offline, so prior
                # validation is never presented as current (and review never
                # crashes on the missing digest key)
                stale_reasons.append(
                    "the effective storage binding is unresolved (a required "
                    "endpoint/region variable is unset, spec 0025 §4) — prior "
                    "validation is not current; resolve the prerequisite and "
                    "revalidate before admission"
                )
            elif approval.get("approval_digest") is not None and report.get(
                "approval_digest"
            ) not in (None, approval["approval_digest"]):
                stale_reasons.append(
                    "the effective storage binding changed since validation "
                    "(spec 0025 §4) — revalidate against the current endpoint grant"
                )
            if not _document_digests_current(project, report.get("citations") or []):
                stale_reasons.append("cited document evidence changed since validation")
            if report.get("artifact_digest") != artifact_digest:
                stale_reasons.append(
                    "the candidate's artifact bytes differ from the validated digest"
                )
        inventory = _change_inventory(project, record)
        # K4 (issue #44): the candidate's structured mapping assertions — the
        # exact identity/digest/dependencies/eligibility surface a human
        # selects from at admission. Reading it is never confirmation.
        mapping_assertions = _mapping_assertions(tree)
        review_digest = hashlib.sha256(
            json.dumps(
                {
                    "proposal": proposal,
                    "base_revision": base,
                    "revision": current,
                    "expected_baseline": record.get("expected_baseline"),
                    "changes": inventory,
                    "artifact_digest": artifact_digest,
                    "citations": citations,
                    # spec 0025 §4 (exact human authority): the review digest
                    # binds the candidate's EFFECTIVE source identity — the
                    # declaration digest, the effective approval digest and
                    # the complete storage bindings — so a reviewed digest
                    # validated under endpoint A can never admit endpoint B
                    # from identical candidate bytes.
                    "source_digest": source_digest,
                    "approval_digest": approval.get("approval_digest"),
                    "storage_bindings": approval.get("storage_bindings") or {},
                    "mapping_assertions": [
                        {
                            "page": entry["page"],
                            "mapping": entry["mapping"],
                            "assertion_digest": entry["assertion_digest"],
                            "receipts": [receipt["digest"] for receipt in entry["receipts"]],
                        }
                        for entry in mapping_assertions
                    ],
                    "validation": None
                    if report is None
                    else {
                        "commit": report["commit"],
                        "ok": report["ok"],
                        "artifact_digest": report["artifact_digest"],
                        **(
                            {"execution_identity": report["execution_identity"]}
                            if report.get("execution_identity") is not None
                            else {}
                        ),
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            "proposal": proposal,
            "project": str(project),
            "base_revision": base,
            "revision": current,
            "expected_baseline": record.get("expected_baseline"),
            "part": part,
            "changes": inventory,
            "files": bodies,
            "sources": resolved_sources or [],
            "sources_digest": source_digest,
            "source_approved": approved,
            "source_approval_state": approval["state"],
            "storage_bindings": approval.get("storage_bindings") or {},
            "citations": citations,
            "report": None
            if report is None
            else _validate_view(
                report,
                proposals._validation_path(project, proposal, current),
                idempotent=False,
                contract_limits=project_inspection_limits(project),
            ),
            "validation_stale": bool(stale_reasons),
            "stale_reasons": stale_reasons,
            "mapping_assertions": mapping_assertions,
            "review_digest": review_digest,
        }


# ------------------------ K1 (issue #41): the explicit schema refresh seam

# One catalog asset of a refresh request: the COMPLETE identity tuple
# {source, catalog, schema, table} with exact case-sensitive identifiers
# (plan §2). ``catalog`` is null for file views.
_ASSET_KEYS = frozenset({"source", "catalog", "schema", "table"})


def _catalog_asset(asset: object) -> dict:
    """Validate one explicit catalog asset request: exactly the identity-tuple
    keys, plain non-empty identifiers (catalog may be null). Consumers use
    these explicit fields, never display names."""
    if not isinstance(asset, dict) or set(asset) != _ASSET_KEYS:
        raise ValueError(
            "a catalog asset is exactly {source, catalog, schema, table} with exact "
            "case-sensitive identifiers (catalog null for file views), got "
            f"{asset!r}"
        )
    for key in ("source", "schema", "table"):
        if not isinstance(asset[key], str) or not asset[key]:
            raise ValueError(f"catalog asset field {key!r} must be a non-empty string")
    catalog = asset["catalog"]
    if catalog is not None and (not isinstance(catalog, str) or not catalog):
        raise ValueError(
            "catalog asset field 'catalog' must be the stable attached catalog name "
            "or null (file views carry no catalog)"
        )
    return dict(asset)


def _declared_columns(con, catalog: list[dict]) -> dict[tuple[str, str, str], dict[str, dict]]:
    """Declared column metadata (is_nullable/column_default) for ATTACHED
    sources only, read from information_schema: file views carry no declared
    constraints, so their metadata stays unknown (spec 0010 §4 — expose
    declared metadata only where the source provides it)."""
    declared: dict[tuple[str, str, str], dict[str, dict]] = {}
    for entry in catalog:
        if not any(table.get("catalog") for table in entry["tables"]):
            continue  # file views: no declared metadata to read
        rows = con.execute(
            "SELECT table_catalog, table_schema, table_name, column_name, "
            "is_nullable, column_default FROM information_schema.columns "
            "WHERE table_catalog = ? ORDER BY table_schema, table_name, ordinal_position",
            [entry["name"]],
        ).fetchall()
        for catalog_name, schema, table, column, is_nullable, default in rows:
            declared.setdefault((catalog_name, schema, table), {})[column] = {
                # the DECLARED nullability, verbatim: YES -> nullable, NO ->
                # NOT NULL; anything else the source does not declare stays
                # unknown (None), never a manufactured constraint (spec 0010 §4)
                "nullable": (
                    True if is_nullable == "YES" else False if is_nullable == "NO" else None
                ),
                "default": default,
            }
    return declared


def _native_resource_pages(project: Path, revision: str) -> tuple[dict[str, dict], set[str]]:
    """The candidate's producer-native technical profile pages at
    ``revision`` (read from the commit, never a worktree; parsed through the
    producer's PUBLIC frontmatter parse — Core never re-parses KB bytes with
    its own YAML loader): ``(core_ref resource -> {path, meta, body, text},
    tracked technical-page paths)`` over knowledge/tables and
    knowledge/datasets. Two pages binding the same resource is a collision
    needing human resolution; non-technical or unprofiled pages are not
    touched by refresh."""
    from lumio_wiki import parse_frontmatter  # pyright: ignore[reportMissingImports] — optional SDK

    tracked = proposals._git(["ls-tree", "-r", "--name-only", revision], project).stdout
    pages: dict[str, dict] = {}
    paths: set[str] = set()
    for rel in tracked.split("\n"):
        if not (rel.startswith("knowledge/tables/") or rel.startswith("knowledge/datasets/")):
            continue
        blob = proposals._read_blob(project, revision, rel)
        if blob is None:  # pragma: no cover - ls-tree paths always resolve
            continue
        paths.add(rel)
        text = blob.decode("utf-8", "replace")
        try:
            meta, body, _start = parse_frontmatter(text, rel)
        except Exception:  # noqa: BLE001 — the producer/page gate owns malformed errors
            continue
        profile = meta.get("ariadne_profile") if isinstance(meta, dict) else None
        core_ref = profile.get("core_ref") if isinstance(profile, dict) else None
        resource = core_ref.get("id") if isinstance(core_ref, dict) else None
        if (
            isinstance(profile, dict)
            and profile.get("kind") in ("table", "dataset")
            and isinstance(resource, str)
            and resource.startswith("ariadne://")
        ):
            if resource in pages:
                raise ValueError(
                    f"the candidate carries two technical profile pages for {resource!r} "
                    f"({pages[resource]['path']} and {rel}) — a resource collision "
                    "needs human resolution; refresh refuses rather than overwriting"
                )
            pages[resource] = {"path": rel, "meta": meta, "body": body, "text": text}
    return pages, paths


def _resource_pages(project: Path, revision: str) -> tuple[dict[str, dict], set[str]]:
    """The candidate's resource-bound schema pages at ``revision`` (read from
    the commit, never a worktree): ``(resource -> {path, meta, text}, tracked
    schema-page paths)``. Two pages carrying the same resource is a collision
    needing human resolution; pages without a canonical resource (legacy
    authored names) are not touched by refresh."""
    tracked = proposals._git(["ls-tree", "-r", "--name-only", revision], project).stdout
    pages: dict[str, dict] = {}
    paths: set[str] = set()
    for rel in tracked.split("\n"):
        if (
            not (
                rel.startswith("context_layer/tables/") or rel.startswith("context_layer/datasets/")
            )
            or PurePosixPath(rel).name in proposals._GENERATED_FILES
        ):
            continue
        blob = proposals._read_blob(project, revision, rel)
        if blob is None:  # pragma: no cover - ls-tree paths always resolve
            continue
        paths.add(rel)
        text = blob.decode("utf-8", "replace")
        try:
            meta = _load_frontmatter_meta(text)
        except yaml.YAMLError:
            continue  # a malformed draft page: the validation gate owns the error
        resource = meta.get("resource") if isinstance(meta, dict) else None
        if isinstance(resource, str) and resource.startswith("ariadne://"):
            if resource in pages:
                raise ValueError(
                    f"the candidate carries two schema pages for {resource!r} "
                    f"({pages[resource]['path']} and {rel}) — a resource collision "
                    "needs human resolution; refresh refuses rather than overwriting"
                )
            pages[resource] = {"path": rel, "meta": meta, "text": text}
    return pages, paths


def _schema_columns(catalog_table: dict, declared: dict) -> list[dict]:
    """The core-owned schema facts of one table: exact column identity/type in
    ordinal order plus only supported declared metadata (unknown stays
    unknown; no manufactured NOT NULL, default or comment)."""
    facts = declared.get(
        (catalog_table.get("catalog"), catalog_table.get("schema"), catalog_table["name"]), {}
    )
    columns: list[dict] = []
    for column in catalog_table["columns"]:
        meta = facts.get(column["name"])
        columns.append(
            {
                "column": column["name"],
                "type": column["type"],
                "nullable": meta["nullable"] if meta is not None else "unknown",
                "default": meta["default"] if meta is not None else "unknown",
                "comment": "unknown",  # no comment source is read in K1
            }
        )
    return columns


def _refresh_native_profiles(
    project: Path,
    proposal: str,
    current: str,
    requested: list[dict],
    matched: dict[tuple, dict],
    profiles: dict[str, dict],
    declared: dict[tuple, dict],
    binding_digest: str | None,
    source_digest: str,
) -> dict:
    """The revision-2 refresh route (spec0032 SS5-6): regenerate the
    core-owned schema facts as PRODUCER-NATIVE Table/Dataset profile pages of
    the candidate's knowledge/ subtree through revision-checked complete
    page edits - no maintained context_layer mirror, no second producer
    schema. Existing pages are read through the producer's public frontmatter
    parse; authored base metadata, native extras and the curated body are
    preserved verbatim; identical inputs are a no-op. Returns the same shape
    as :func:`refresh_schema`."""
    existing, tracked_paths = _native_resource_pages(project, current)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    specs: list[dict] = []
    claimed: dict[str, str] = {}
    collections: dict[tuple, dict] = {}
    for asset in requested:
        key = (asset["source"], asset["catalog"], asset["schema"], asset["table"])
        table = matched[key]
        resource = table_resource(
            asset["source"], asset["catalog"], asset["schema"], asset["table"]
        )
        columns = _schema_columns(table, declared)
        page = existing.get(resource)
        path = (
            page["path"]
            if page
            else (f"knowledge/tables/{generated_page_filename(resource, asset['source'])}")
        )
        text, flags = build_native_table_page(
            asset={**asset, "resource": resource},
            columns=columns,
            profile=profiles[resource],
            existing_meta=page["meta"] if page else None,
            existing_body=page["body"] if page else "",
            now=now,
            source_binding=binding_digest,
        )
        specs.append(
            {"resource": resource, "path": path, "text": text, "kind": "table", "flags": flags}
        )
        collections.setdefault(
            (asset["source"], asset["catalog"], asset["schema"]),
            {"source": asset["source"], "catalog": asset["catalog"], "schema": asset["schema"]},
        )
    for collection_key, collection in collections.items():
        resource = collection_resource(
            collection["source"], collection["catalog"], collection["schema"]
        )
        page = existing.get(resource)
        path = (
            page["path"]
            if page
            else (f"knowledge/datasets/{generated_page_filename(resource, collection['source'])}")
        )
        # Overview membership: the collection's EXISTING native table pages
        # PLUS the requested updates (the issue #41 rule carried to the
        # native route) - a narrower refresh never drops a still-present
        # table's link, and an undocumented asset is never silently asserted.
        members: list[dict] = []
        requested_here: set[str] = set()
        for spec in specs:
            if spec["kind"] != "table":
                continue
            parts = parse_resource(spec["resource"])[1]
            if parts[:3] != list(collection_key):
                continue
            members.append(
                {
                    "resource": spec["resource"],
                    "table": parts[3],
                    "column_count": len(profiles[spec["resource"]]["columns"]),
                }
            )
            requested_here.add(spec["resource"])
        carried: list[tuple[str, dict]] = []
        for res, carried_page in existing.items():
            if res in requested_here:
                continue
            try:
                kind, parts = parse_resource(res)
            except ValueError:
                continue
            if kind != "table" or parts[:3] != list(collection_key):
                continue
            carried_profile = (
                carried_page["meta"].get("ariadne_profile")
                if isinstance(carried_page["meta"], dict)
                else None
            )
            carried_native = (
                carried_profile.get("native") if isinstance(carried_profile, dict) else None
            )
            carried_ariadne = (
                carried_native.get("ariadne") if isinstance(carried_native, dict) else None
            )
            carried_schema = (
                carried_ariadne.get("schema") if isinstance(carried_ariadne, dict) else None
            )
            carried.append(
                (
                    parts[3],
                    {
                        "resource": res,
                        "table": parts[3],
                        "column_count": (
                            len(carried_schema) if isinstance(carried_schema, list) else 0
                        ),
                    },
                )
            )
        members.extend(member for _table, member in sorted(carried, key=lambda item: item[0]))
        text, flags = build_native_dataset_page(
            collection={**collection, "resource": resource},
            tables=members,
            existing_meta=page["meta"] if page else None,
            existing_body=page["body"] if page else "",
        )
        specs.append(
            {"resource": resource, "path": path, "text": text, "kind": "dataset", "flags": flags}
        )
    # collision checks BEFORE any write (the plan section 2
    # refuse-never-overwrite rule carried to the native route)
    for spec in specs:
        other = claimed.get(spec["path"])
        if other is not None and other != spec["resource"]:
            raise ValueError(
                f"generated filename collision: {spec['path']} would serve both "
                f"{other!r} and {spec['resource']!r} - refresh refuses rather "
                "than overwriting another asset"
            )
        claimed[spec["path"]] = spec["resource"]
        page = existing.get(spec["resource"])
        if page is None and spec["path"] in tracked_paths:
            raise ValueError(
                f"{spec['path']}: the generated page for {spec['resource']!r} collides "
                "with a different existing candidate page - a filename/resource "
                "collision refuses rather than overwriting; resolve it by hand"
            )
    for spec in specs:
        proposals.check_artifact_content(f"generated page {spec['resource']!r}", spec["text"])
    revision = current
    pages: list[dict] = []
    changed_any = False
    for spec in specs:  # revision-checked complete page edits, core-generated
        out = proposals.edit_proposal(
            project, proposal, revision, spec["path"], spec["text"], core_generated=True
        )
        revision = out["revision"]
        changed_any = changed_any or out["changed"]
        pages.append(
            {
                "resource": spec["resource"],
                "path": spec["path"],
                "kind": spec["kind"],
                "changed": out["changed"],
                "changes": spec["flags"],
            }
        )
    return {
        "proposal": proposal,
        "revision": revision,
        "changed": changed_any,
        "pages": pages,
        "assets": requested,
        "source_digest": source_digest,
    }


def refresh_schema(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    assets: list[dict] | tuple[dict, ...],
) -> dict:
    """The explicit physical schema refresh (plan §2 ``refresh_schema``, spec
    0010 §4; issue #41/K1): regenerate the core-owned schema facts and Dataset
    Overviews of an EXPLICIT catalog asset list inside the selected proposal.

    Reads run ONLY through the operator-approved resolved source identity (the
    G3 seam — an unapproved or changed registry is an explicit error and the
    connection builder is never called); every write is a revision-checked
    complete page edit (an identical refresh is a no-op and the candidate
    revision does not move); authored summary/column meaning is preserved for
    identical column identity/type while removed/type-changed columns keep
    their prior meaning as reviewable history; filename/resource collisions
    refuse instead of overwriting. Returns the resulting revision, the
    generated page identities (resource + path + kind) and per-page
    schema-change flags. Refresh edits a candidate — it is never validation or
    admission (K4 owns context-only admission)."""
    project = Path(project).resolve()
    if not isinstance(assets, (list, tuple)) or not assets:
        raise ValueError(
            "refresh_schema takes an explicit non-empty list of catalog assets "
            "{source, catalog, schema, table}"
        )
    requested = [_catalog_asset(asset) for asset in assets]
    seen: set[tuple] = set()
    for asset in requested:
        key = (asset["source"], asset["catalog"], asset["schema"], asset["table"])
        if key in seen:
            raise ValueError(f"duplicate catalog asset in the refresh request: {asset}")
        seen.add(key)
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if expected_revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the "
            f"refresh expected {expected_revision} — re-read the candidate and retry "
            "with the current revision; nothing was written"
        )
    resolved, digest = authoring_sources.candidate_sources(project, current)
    if resolved is None:
        raise ValueError(
            f"proposal {proposal} declares no source entries in its candidate "
            f"registry at {current[:12]} — there is nothing to refresh"
        )
    assert digest is not None
    approval = authoring_sources._effective_grant(project, resolved, digest, proposal, current)
    storage_bindings = approval.get("storage_bindings") or {}
    binding_digest = approval.get("approval_digest") if storage_bindings else None
    owned = execution.DuckDBExecution(
        authoring_sources.identity_registry(approval["sources"], storage_bindings)
    )
    try:
        con, catalog = owned.con, owned.catalog
        declared = _declared_columns(con, catalog)
        # profile ONLY the requested tables (bounded, explicit refresh work)
        profiles: dict[str, dict] = {}
        matched: dict[tuple, dict] = {}
        for entry in catalog:
            matching = [
                t
                for t in entry["tables"]
                if (t["source"], t.get("catalog"), t.get("schema"), t["name"]) in seen
            ]
            if not matching:
                continue
            for table in matching:
                matched[
                    (table["source"], table.get("catalog"), table.get("schema"), table["name"])
                ] = table
            source_profile = profiler._profile_source(con, {**entry, "tables": matching})
            for table in source_profile["tables"].values():
                profiles[table["resource"]] = table
    finally:
        owned.close()
    missing = [
        asset
        for asset in requested
        if (asset["source"], asset["catalog"], asset["schema"], asset["table"]) not in matched
    ]
    if missing:
        available = sorted(
            f"{t['source']}.{t.get('schema')}.{t['name']}"
            for entry in catalog
            for t in entry["tables"]
        )
        raise ValueError(
            f"catalog asset(s) not present in the approved resolved source identity: "
            f"{missing[0]} — available assets: {', '.join(available) or 'none'}; "
            "nothing was written"
        )
    existing, tracked_paths = _resource_pages(project, current)
    # #83 (spec0032 §§5–6): a candidate whose selector opted into support
    # revision 2 refreshes into the PRODUCER-NATIVE technical profile pages
    # of its knowledge/ subtree (revision-checked complete page edits through
    # the public producer parse for existing pages — no Core YAML parse of
    # KB bytes, no maintained context_layer mirror); every other candidate,
    # including standalone and legacy integrated ones, keeps the unchanged
    # context_layer route below.
    selector_blob = proposals._read_blob(project, current, "context_integration.yaml")
    if selector_blob is not None:
        from ariadne import lumio_context  # pyright: ignore[reportAttributeAccessIssue]

        selected_route = lumio_context.validated_selector(
            yaml.safe_load(selector_blob.decode("utf-8"))
        )
        if selected_route is not None and selected_route.get("support_revision", 1) >= 2:
            return _refresh_native_profiles(
                project,
                proposal,
                current,
                requested,
                matched,
                profiles,
                declared,
                binding_digest,
                digest,
            )
    now = datetime.now(UTC).isoformat(timespec="seconds")
    specs: list[dict] = []
    claimed: dict[str, str] = {}
    collections: dict[tuple, dict] = {}
    for asset in requested:
        key = (asset["source"], asset["catalog"], asset["schema"], asset["table"])
        table = matched[key]
        resource = table_resource(
            asset["source"], asset["catalog"], asset["schema"], asset["table"]
        )
        columns = _schema_columns(table, declared)
        page = existing.get(resource)
        path = (
            page["path"]
            if page
            else (f"context_layer/tables/{generated_page_filename(resource, asset['source'])}")
        )
        text, flags = build_table_page(
            asset={
                **asset,
                "resource": resource,
            },
            columns=columns,
            profile=profiles[resource],
            existing_text=page["text"] if page else None,
            now=now,
            source_binding=binding_digest,
        )
        specs.append(
            {
                "resource": resource,
                "path": path,
                "text": text,
                "kind": "table",
                "flags": flags,
            }
        )
        collections.setdefault(
            (asset["source"], asset["catalog"], asset["schema"]),
            {"source": asset["source"], "catalog": asset["catalog"], "schema": asset["schema"]},
        )
    for collection_key, collection in collections.items():
        resource = collection_resource(
            collection["source"], collection["catalog"], collection["schema"]
        )
        page = existing.get(resource)
        path = (
            page["path"]
            if page
            else (
                f"context_layer/datasets/{generated_page_filename(resource, collection['source'])}"
            )
        )
        # Overview membership is the collection's EXISTING represented pages
        # PLUS the requested updates (issue #41): a narrower refresh never
        # drops a still-present table's link — and an approved asset nothing
        # ever documented is never silently asserted (no unrelated additions)
        members: list[dict] = []
        requested_here: set[str] = set()
        for spec in specs:
            if spec["kind"] != "table":
                continue
            parts = parse_resource(spec["resource"])[1]
            if parts[:3] != list(collection_key):
                continue  # the tables of OTHER collections
            members.append(
                {
                    "resource": spec["resource"],
                    "table": parts[3],
                    "link": f"../tables/{PurePosixPath(spec['path']).name}",
                    "column_count": len(profiles[spec["resource"]]["columns"]),
                }
            )
            requested_here.add(spec["resource"])
        carried: list[tuple[str, dict]] = []
        for res, carried_page in existing.items():
            if res in requested_here or not carried_page["path"].startswith(
                "context_layer/tables/"
            ):
                continue
            try:
                kind, parts = parse_resource(res)
            except ValueError:
                continue  # not a canonical resource: nothing it can represent
            if kind != "table" or parts[:3] != list(collection_key):
                continue
            carried_meta = (
                carried_page["meta"].get("ariadne")
                if isinstance(carried_page["meta"], dict)
                else None
            )
            carried_schema = carried_meta.get("schema") if isinstance(carried_meta, dict) else None
            carried.append(
                (
                    parts[3],
                    {
                        "resource": res,
                        "table": parts[3],
                        "link": f"../tables/{PurePosixPath(carried_page['path']).name}",
                        "column_count": (
                            len(carried_schema) if isinstance(carried_schema, list) else 0
                        ),
                    },
                )
            )
        members.extend(member for _table, member in sorted(carried, key=lambda c: c[0]))
        text, flags = build_dataset_page(
            collection={
                **collection,
                "resource": resource,
            },
            tables=members,
            existing_text=page["text"] if page else None,
        )
        specs.append(
            {"resource": resource, "path": path, "text": text, "kind": "dataset", "flags": flags}
        )
    # collision checks BEFORE any write (plan §2: a collision refuses, never
    # overwrites; filename/resource consistency is checked against the
    # candidate's tracked schema pages)
    for spec in specs:
        other = claimed.get(spec["path"])
        if other is not None and other != spec["resource"]:
            raise ValueError(
                f"generated filename collision: {spec['path']} would serve both "
                f"{other!r} and {spec['resource']!r} — refresh refuses rather than "
                "overwriting another asset"
            )
        claimed[spec["path"]] = spec["resource"]
        page = existing.get(spec["resource"])
        if page is None and spec["path"] in tracked_paths:
            raise ValueError(
                f"{spec['path']}: the generated page for {spec['resource']!r} collides "
                "with a different existing candidate page — a filename/resource "
                "collision refuses rather than overwriting; resolve it by hand"
            )
    # Fix F1 (parent-authorized, spec 0024 §3/§6 AC5): pre-flight EVERY
    # generated page against the shared artifact bound BEFORE the first edit.
    # The sequential edit seam checks one page at a time, so an over-limit
    # later page would otherwise refuse only after earlier pages already
    # advanced the candidate — a half-updated refresh. The check is the same
    # one the edit seam itself runs, moved ahead of all writes; no partial
    # state can remain.
    for spec in specs:
        proposals.check_artifact_content(f"generated page {spec['resource']!r}", spec["text"])
    revision = current
    pages: list[dict] = []
    changed_any = False
    for spec in specs:  # revision-checked complete page edits, core-generated
        out = proposals.edit_proposal(
            project, proposal, revision, spec["path"], spec["text"], core_generated=True
        )
        revision = out["revision"]
        changed_any = changed_any or out["changed"]
        pages.append(
            {
                "resource": spec["resource"],
                "path": spec["path"],
                "kind": spec["kind"],
                "changed": out["changed"],
                "changes": spec["flags"],
            }
        )
    return {
        "proposal": proposal,
        "revision": revision,
        "changed": changed_any,
        "pages": pages,
        "assets": requested,
        "source_digest": digest,
    }


# ------------------- K3 (issue #43): bounded mapping inspection + receipts

# The core-controlled measured-evidence area (plan §2: receipts are retained
# in the project's evidence area with atomic persistence — operator-owned
# ignored state beside the validation evidence, never a Git artifact).
EVIDENCE_REL = proposals.ARIADNE_STATE_DIR / "evidence"
_RECEIPT_ID_RE = re.compile(r"mr-[0-9a-f]{16}")


def _receipt_path(project: Path, proposal: str, receipt_id: str) -> Path:
    """Where one mapping-evidence receipt lives (``.ariadne/evidence/<id>/``)."""
    if not isinstance(receipt_id, str) or not _RECEIPT_ID_RE.fullmatch(receipt_id):
        raise ValueError(f"{receipt_id!r} is not a mapping-evidence receipt id (mr-<16 hex>)")
    return project / EVIDENCE_REL / proposal / f"{receipt_id}.json"


def store_receipt(project: Path, proposal: str, receipt: dict) -> Path:
    """Persist one receipt ATOMICALLY and durably (the proposal-record
    discipline: data synced, tmp+os.replace, directory entry synced) under the
    operator-owned ``.ariadne/evidence/<proposal>/`` — separate from committed
    artifacts, so evidence never changes the revision it measures."""
    path = _receipt_path(project, proposal, receipt["receipt_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(receipt, fh, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    proposals._fsync_path(path.parent)
    return path


def load_receipt(project: Path, proposal: str, receipt_id: str) -> dict:
    """Load and INTEGRITY-CHECK one retained receipt: a missing, unreadable,
    tampered or malformed record is an explicit error — never a silent pass
    (an allowlisted id or count proves nothing, spec 0010 §7)."""
    path = _receipt_path(project, proposal, receipt_id)
    entry = proposals._lstat(path)
    if entry is None:
        raise ValueError(
            f"receipt {receipt_id!r} does not resolve in the project's evidence "
            f"records ({path} is absent) — allowlisting an id is not proof"
        )
    if not stat.S_ISREG(entry.st_mode):
        raise ValueError(f"{path}: refusing a non-regular receipt — inspect it by hand")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: unreadable receipt ({exc})") from None
    if not isinstance(receipt, dict) or receipt.get("receipt_id") != receipt_id:
        raise ValueError(f"{path}: malformed receipt — it does not carry its own identity")
    recorded = receipt.pop("integrity_digest", None)
    if not isinstance(recorded, str) or _canonical_digest(receipt) != recorded:
        raise ValueError(
            f"{path}: receipt integrity check failed — the recorded measurements do "
            "not match their integrity digest (tampered or truncated evidence)"
        )
    receipt["integrity_digest"] = recorded
    return receipt


def _quote(identifier: str) -> str:
    """Quote one SQL identifier (the profiler discipline: catalog-validated
    names, doubled inner quotes — no identifier is ever interpolated raw)."""
    return '"' + identifier.replace('"', '""') + '"'


def _sql_ref(ref: str) -> str:
    """The catalog entry's plain dotted ``ref`` as a SQL-qualified prefix.
    The builder emits ``<alias>.<schema>`` for attaches (schema-only for
    file views); the alias is everything before the FIRST dot — a schema may
    itself contain dots and is quoted as ONE identifier with the same
    discipline as the table name (``warehouse.sales.west`` renders
    ``"warehouse"."sales.west"``; the table is quoted by the caller)."""
    alias, dot, schema = ref.partition(".")
    return f"{_quote(alias)}.{_quote(schema)}" if dot else _quote(ref)


def _scope_for(resource: str, scope: list[dict]) -> list[dict]:
    return [predicate for predicate in scope if predicate["resource"] == resource]


def _scope_clause(scope: list[dict]) -> tuple[str, list]:
    """The parameterized WHERE conjunct of one asset's scope predicates
    (plan §2: scope values are bound as parameters, never interpolated)."""
    clauses: list[str] = []
    params: list = []
    for predicate in scope:
        column = _quote(predicate["column"])
        if predicate["op"] == "in":
            marks = ", ".join("?" for _ in predicate["value"])
            clauses.append(f"{column} IN ({marks})")
            params.extend(predicate["value"])
        else:
            operator = {"eq": "=", "gte": ">=", "lt": "<"}[predicate["op"]]
            clauses.append(f"{column} {operator} ?")
            params.append(predicate["value"])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def inspection_sample_statement(
    table: dict, columns: list[str], scope: list[dict], limit: int
) -> tuple[str, list]:
    """The bounded, deterministic materialized-sample statement of one
    participating asset (plan §2): exactly the candidate's bound columns are
    projected (no all-column scan), identifiers are quoted catalog-validated
    names, scope values ride as parameters, and the sample is ordered by the
    bound columns so repeated inspections of unchanged inputs measure the
    same rows. The LIMIT bound is itself a parameter."""
    projection = ", ".join(_quote(column) for column in columns)
    ordering = ", ".join(_quote(column) for column in columns)
    where, params = _scope_clause(scope)
    sql = (
        f"SELECT {projection} FROM {_sql_ref(table['ref'])}.{_quote(table['name'])}{where} "
        f"ORDER BY {ordering} LIMIT ?"
    )
    return sql, [*params, int(limit)]


def inspection_count_statement(
    table: dict, columns: list[str], scope: list[dict]
) -> tuple[str, list]:
    """The full-data eligible/null aggregate of one side's measured columns:
    ``eligible`` counts scoped rows whose measured tuple is complete,
    ``nulls`` scoped rows with any null component — the honest denominators a
    sampled coverage ratio reports against (the scan itself stays bounded by
    the shared deadline, never by a cheap LIMIT)."""
    non_null = " AND ".join(f"{_quote(column)} IS NOT NULL" for column in columns)
    any_null = " OR ".join(f"{_quote(column)} IS NULL" for column in columns)
    where, params = _scope_clause(scope)
    sql = (
        f"SELECT COUNT(*) FILTER (WHERE {non_null}) AS eligible, "
        f"COUNT(*) FILTER (WHERE {any_null}) AS nulls "
        f"FROM {_sql_ref(table['ref'])}.{_quote(table['name'])}{where}"
    )
    return sql, params


def _guarded(con, budget, sql: str, params: list):
    """Execute one core-generated guarded statement: single-statement guard,
    read-only by construction, parameters bound, and the shared deadline's
    interrupt armed — an over-budget read STOPS here."""
    execution.assert_single_statement(sql)
    with budget.guard(con):
        return con.execute(sql, params).fetchall()


def _participant(resource: str, catalog: list[dict]) -> dict:
    """The approved catalog table of one canonical resource, with the
    cross-source participation refusal (an unapproved source never
    participates) and the unknown-asset refusal distinct."""
    for entry in catalog:
        for table in entry["tables"]:
            if table.get("resource") == resource:
                return table
    _kind, parts = parse_resource(resource)
    names = {entry["name"] for entry in catalog}
    if parts[0] not in names:
        raise ValueError(
            f"the candidate names source {parts[0]!r} which is not an approved "
            f"registry identity (approved: {', '.join(sorted(names)) or 'none'}) — a "
            "cross-source candidate participates only when EVERY participating "
            "source is approved; nothing was measured"
        )
    raise ValueError(
        f"catalog asset {resource!r} is not present in the approved resolved source "
        "identity — nothing was measured"
    )


def _column_type(table: dict, column: str) -> str:
    for entry in table["columns"]:
        if entry["name"] == column:
            return entry["type"]
    raise ValueError(
        f"column {column!r} is not present in the catalog asset "
        f"{table.get('resource')!r} — the candidate binds exact approved columns only"
    )


def _check_family_types(candidate: dict, tables: dict) -> None:
    """The lossy-coercion refusal (plan §2): equality compares compatible
    types position-by-position; prefix components and the target are
    string-typed; lookup keys/values compare compatibly with the fact side.
    A string beside a numeric column is NEVER silently coerced."""
    family = candidate["family"]
    if family == "equality":
        for left, right in zip(candidate["left"], candidate["right"], strict=True):
            left_type = _column_type(tables[candidate["left"][0]["resource"]], left["column"])
            right_type = _column_type(tables[candidate["right"][0]["resource"]], right["column"])
            if not profiler.types_compatible(left_type, right_type):
                raise ValueError(
                    f"incompatible types for an equality candidate: "
                    f"{left['column']} is {left_type} and {right['column']} is "
                    f"{right_type} — no lossy coercion is applied (string identifier "
                    "equivalence is never inferred from a numeric cast); nothing was "
                    "measured"
                )
    elif family == "prefix":
        components = [*candidate["left"], *candidate["right"]]
        if candidate.get("prefix_lookup"):
            components.append(candidate["prefix_lookup"]["prefix_field"])
        for binding in components:
            the_type = _column_type(tables[binding["resource"]], binding["column"])
            if the_type.split("(")[0].upper() != "VARCHAR":
                raise ValueError(
                    f"a prefix candidate's string components must be VARCHAR: "
                    f"{binding['column']} is {the_type} — no trim/pad/case-fold or "
                    "cast participates; nothing was measured"
                )
    else:  # lookup
        lookup = candidate["lookup"]
        for fact, remote in (
            *zip(candidate["left"], lookup["key_fields"], strict=True),
            *zip(candidate["right"], lookup["value_fields"], strict=True),
        ):
            fact_type = _column_type(tables[candidate["left"][0]["resource"]], fact["column"])
            remote_type = _column_type(tables[lookup["asset"]], remote["column"])
            if not profiler.types_compatible(fact_type, remote_type):
                raise ValueError(
                    f"incompatible types for a lookup candidate: {fact['column']} is "
                    f"{fact_type} and {remote['column']} is {remote_type} — no lossy "
                    "coercion is applied; nothing was measured"
                )


def _collision_view(values: list[tuple]) -> dict:
    """Duplicate tuple values among the tested rows: how many values repeat
    and the highest multiplicity — the fan-out evidence that a bare join on
    the compared value would multiply rows (AC5)."""
    counts = Counter(values)
    repeated = [count for count in counts.values() if count > 1]
    return {
        "values": len(repeated),
        "max_multiplicity": max(repeated, default=1),
    }


def _jsonable(value):
    return profiler._jsonable(value)


def _shape_summary(rows: list[dict], column: str) -> dict:
    """The bounded AGGREGATE identifier-shape summary of one requested binding
    (K3 fix pass, finding 7, spec 0010 §7 "identifier-shape summaries"): nulls,
    distinct-within-sample, string length min/max/avg and disjoint charset
    classes over the asset's EXISTING permitted sample — aggregates only,
    never a raw value (raw examples stay behind the operator's explicit sample
    permission)."""
    values = [row[column] for row in rows]
    present = [value for value in values if value is not None]
    summary: dict = {
        "sampled": len(values),
        "nulls": len(values) - len(present),
        "distinct": len({str(value) for value in present}),
    }
    strings = [value for value in present if isinstance(value, str)]
    if strings:
        lengths = [len(value) for value in strings]
        summary["length"] = {
            "min": min(lengths),
            "max": max(lengths),
            "avg": round(sum(lengths) / len(lengths), 2),
        }
        summary["charset"] = {
            "digits_only": sum(1 for value in strings if value.isdigit()),
            "letters_only": sum(1 for value in strings if value.isalpha()),
            "mixed_alphanumeric": sum(
                1
                for value in strings
                if value.isalnum() and not value.isalpha() and not value.isdigit()
            ),
            "other_characters": sum(1 for value in strings if not value.isalnum()),
        }
    return summary


def _measure(
    con,
    budget,
    candidate: dict,
    tables: dict,
    limits: dict,
) -> dict:
    """Run the guarded statements of one normalized candidate and assemble the
    measured evidence (counts only by default — raw examples ride separately
    under the operator's sample permission). Every statement draws the SAME
    deadline; each participating asset materializes at most ``sample_rows``
    rows (K3 fix pass, finding 2: ONE bounded union-column sample PER ASSET,
    reused by every side/lookup that reads that asset), ordered by the bound
    columns so repeated inspections of unchanged inputs measure the same
    rows."""
    family = candidate["family"]
    left_table = tables[candidate["left"][0]["resource"]]
    right_table = tables[candidate["right"][0]["resource"]]
    left_columns = [binding["column"] for binding in candidate["left"]]
    right_columns = [binding["column"] for binding in candidate["right"]]
    pairing = candidate.get("pairing") or []
    pairing_left = [pair["left"]["column"] for pair in pairing]
    pairing_right = [pair["right"]["column"] for pair in pairing]
    scope = candidate.get("scope") or []
    sample_rows = int(limits["sample_rows"])
    example_budget = int(limits["examples"])

    unavailable: list[str] = []

    # K3 fix pass (finding 2): the union of measured columns per participating
    # asset — exactly one bounded sample is taken per asset, in this
    # deterministic binding order, and every side/lookup reads that sample.
    asset_columns: dict[str, list[str]] = {}

    def _union(resource: str, columns: list[str]) -> None:
        merged = asset_columns.setdefault(resource, [])
        for column in columns:
            if column not in merged:
                merged.append(column)

    lookup = candidate.get("lookup")
    prefix_lookup = candidate.get("prefix_lookup")
    _union(left_table["resource"], left_columns)
    _union(right_table["resource"], right_columns)
    _union(left_table["resource"], pairing_left)
    _union(right_table["resource"], pairing_right)
    if prefix_lookup:
        _union(
            prefix_lookup["asset"],
            [binding["column"] for binding in prefix_lookup["key_fields"]]
            + [prefix_lookup["prefix_field"]["column"]],
        )
    if lookup:
        _union(
            lookup["asset"],
            [binding["column"] for binding in lookup["key_fields"]]
            + [binding["column"] for binding in lookup["value_fields"]],
        )

    def sample(table: dict) -> list[dict]:
        """One asset's bounded materialized sample; a source read that fails
        (an absent location, an unreadable backend) is DISCLOSED as an
        unavailable measurement — an honest empty sample, never a passing
        check and never an invented count."""
        columns = asset_columns[table["resource"]]
        sql, params = inspection_sample_statement(
            table, columns, _scope_for(table["resource"], scope), sample_rows
        )
        try:
            rows = _guarded(con, budget, sql, params)
        except ValueError:
            raise  # the deadline refusal propagates: nothing partial persists
        except duckdb.Error as exc:
            unavailable.append(
                f"the materialized sample of {table['resource']} could not be read "
                f"({type(exc).__name__}) — no rows of this asset were tested"
            )
            return []
        return [dict(zip(columns, row)) for row in rows]

    samples: dict[str, list[dict]] = {
        resource: sample(tables[resource]) for resource in asset_columns
    }
    left_sample = samples[left_table["resource"]]
    right_sample = samples[right_table["resource"]]

    # full-data denominators per side: the deadline bounds the scan itself,
    # and any unavailable count is disclosed, never guessed. For the lookup
    # family the fact side's keys AND values are one complete measured tuple
    # on the SAME asset (K3 fix pass, finding 4: the right side never inherits
    # a keys-only denominator).
    eligible: dict[str, object] = {}
    nulls: dict[str, object] = {}
    fact_tuple = [*left_columns, *right_columns]
    measured_columns = {
        "left": left_columns if family != "lookup" else fact_tuple,
        "right": right_columns if family != "lookup" else fact_tuple,
    }
    for side, table in (("left", left_table), ("right", right_table)):
        if family == "lookup" and table is left_table and "left" in eligible:
            eligible["right"], nulls["right"] = eligible["left"], nulls["left"]
            continue  # keys and values live on the same measured asset/tuple
        sql, params = inspection_count_statement(
            table, measured_columns[side], _scope_for(table["resource"], scope)
        )
        try:
            row = _guarded(con, budget, sql, params)[0]
        except ValueError:
            raise  # the deadline refusal propagates: nothing partial persists
        except duckdb.Error as exc:
            eligible[side], nulls[side] = None, None
            unavailable.append(
                f"counts.{side}: the eligible/null denominator could not be read "
                f"({type(exc).__name__}) — coverage ratios over this side are "
                "not asserted"
            )
            continue
        eligible[side], nulls[side] = int(row[0]), int(row[1])

    # a tested row carries a complete measured tuple: the left components (and,
    # for the lookup family, the mapped fact values too — a null value is not a
    # comparable measurement)
    left_complete = left_columns if family != "lookup" else fact_tuple
    tested_left = [row for row in left_sample if all(row[c] is not None for c in left_complete)]
    tested_right = [row for row in right_sample if all(row[c] is not None for c in right_columns)]
    left_tuples = [tuple(row[c] for c in left_columns) for row in tested_left]
    right_tuples = [tuple(row[c] for c in right_columns) for row in tested_right]

    def lookup_side_measurement(table: dict, columns: list[str]) -> dict:
        """The lookup asset's own honest denominators (K3 fix pass, finding 4):
        complete-tuple eligible/null counts, the sampled tested count and the
        sampled null rows — a truncated lookup sample can never masquerade as
        a fully measured lookup."""
        sql, params = inspection_count_statement(
            table, columns, _scope_for(table["resource"], scope)
        )
        try:
            row = _guarded(con, budget, sql, params)[0]
            count_eligible, count_nulls = int(row[0]), int(row[1])
        except ValueError:
            raise
        except duckdb.Error as exc:
            count_eligible = count_nulls = None
            unavailable.append(
                f"counts of the lookup asset {table['resource']} could not be read "
                f"({type(exc).__name__}) — its sampled/full designation is not "
                "asserted"
            )
        rows = samples[table["resource"]]
        complete = [r for r in rows if all(r[c] is not None for c in columns)]
        return {
            "asset": table["resource"],
            "eligible": count_eligible,
            "nulls": count_nulls,
            "tested": len(complete),
            "null_rows_sampled": len(rows) - len(complete),
            "rows_sampled": len(rows),
        }

    measurement: dict = {
        "counts": {
            "eligible_left": eligible["left"],
            "eligible_right": eligible["right"],
            "tested_left": len(tested_left),
            "tested_right": len(tested_right) if family != "lookup" else len(tested_left),
            "unavailable": unavailable,
        },
        "null_counts": {"left": nulls["left"], "right": nulls["right"]},
        "unknown_lookup_count": 0,
        "missing_key_count": 0,
        "ambiguous_key_count": 0,
        "multiplicity": {"lookup_duplicate_keys": 0, "lookup_max_rows_per_key": 1},
        "collisions": {
            "left": {"values": 0, "max_multiplicity": 1},
            "right": {"values": 0, "max_multiplicity": 1},
        },
        # K3 fix pass (finding 7): every REQUESTED binding's bounded aggregate
        # shape summary, from the existing per-asset samples
        "shapes": [
            {"resource": resource, "column": column, **_shape_summary(samples[resource], column)}
            for resource, columns in asset_columns.items()
            for column in columns
        ],
    }
    limitations: list[str] = []
    examples: list[dict] = []

    if family == "lookup":
        assert lookup is not None  # validate_inspection_candidate requires this family's asset.
        # the explicit approved lookup: missing keys, duplicates, ambiguity and
        # multiplicity are REPORTED — a many-valued lookup never collapses
        key_columns = [b["column"] for b in lookup["key_fields"]]
        value_columns = [b["column"] for b in lookup["value_fields"]]
        lookup_counts = lookup_side_measurement(
            tables[lookup["asset"]], key_columns + value_columns
        )
        measurement["lookup_counts"] = lookup_counts
        fully_measured = (
            lookup_counts["eligible"] is not None
            and lookup_counts["tested"] >= lookup_counts["eligible"]
        )
        lookup_index: dict[tuple, list[tuple]] = {}
        for row in samples[lookup["asset"]]:
            if any(row[c] is None for c in key_columns + value_columns):
                continue  # the null row is counted above, never silently dropped
            lookup_index.setdefault(tuple(row[c] for c in key_columns), []).append(
                tuple(row[c] for c in value_columns)
            )
        repeated = [len(values) for values in lookup_index.values() if len(values) > 1]
        measurement["multiplicity"] = {
            "lookup_duplicate_keys": len(repeated),
            "lookup_max_rows_per_key": max(repeated, default=1),
        }
        matched = mismatched = 0
        for row, keys in zip(tested_left, left_tuples, strict=True):
            values = lookup_index.get(keys)
            fact_values = tuple(row[c] for c in right_columns)
            if values is None:
                # a fact key beyond the SAMPLED lookup rows is an unknown
                # lookup, not a missing key — unless the lookup was fully
                # measured (finding 4)
                if fully_measured:
                    measurement["missing_key_count"] += 1
                    outcome = "missing"
                else:
                    measurement["unknown_lookup_count"] += 1
                    outcome = "unknown-lookup"
            elif len(set(values)) > 1:
                measurement["ambiguous_key_count"] += 1
                outcome = "ambiguous"
            elif values[0] == fact_values:
                matched += 1
                outcome = "matched"
            else:
                mismatched += 1
                outcome = "mismatch"
            if example_budget and len(examples) < example_budget:
                examples.append(
                    {
                        "keys": {column: _jsonable(row[column]) for column in left_columns},
                        "fact_values": {column: _jsonable(row[column]) for column in right_columns},
                        "lookup_values": [list(map(_jsonable, value)) for value in (values or [])],
                        "outcome": outcome,
                    }
                )
        measurement["coverage"] = {
            "left_in_right": {"matched": matched, "tested": len(tested_left)},
            "right_in_left": {"matched": matched, "tested": len(tested_left)},
        }
        measurement["distinct_matched"] = matched
        measurement["mismatch_count"] = mismatched
        measurement["collisions"] = {
            "left": _collision_view(left_tuples),
            "right": _collision_view(right_tuples),
        }
        measurement["pairing"] = {
            "keys": [],
            "status": "absent",
            "paired": 0,
            "ambiguous_keys": 0,
            "max_rows_per_key": 1,
        }
        measurement["comparison_basis"] = "key-paired"
        limitations.append(
            "the lookup's scoped keys pair the sampled fact rows with the lookup "
            "asset's sampled rows"
        )
    else:
        # the compared value of each tested row: the tuple itself (equality)
        # or the constructed prefix value (prefix family)
        lookup_counts = None
        if family == "prefix":
            separator = candidate["separator"]
            key_arity = 0
            prefix_index: dict[tuple, list] = {}
            if prefix_lookup:
                key_arity = len(prefix_lookup["key_fields"])
                key_columns = [b["column"] for b in prefix_lookup["key_fields"]]
                prefix_column = prefix_lookup["prefix_field"]["column"]
                lookup_counts = lookup_side_measurement(
                    tables[prefix_lookup["asset"]], key_columns + [prefix_column]
                )
                measurement["lookup_counts"] = lookup_counts
                for row in samples[prefix_lookup["asset"]]:
                    if any(row[c] is None for c in key_columns) or row[prefix_column] is None:
                        continue
                    prefix_index.setdefault(tuple(row[c] for c in key_columns), []).append(
                        row[prefix_column]
                    )
                repeated = [len(v) for v in prefix_index.values() if len(v) > 1]
                measurement["multiplicity"] = {
                    "lookup_duplicate_keys": len(repeated),
                    "lookup_max_rows_per_key": max(repeated, default=1),
                }
            left_pairs: list[tuple[dict, tuple]] = []
            for row, components in zip(tested_left, left_tuples, strict=True):
                if prefix_lookup:
                    values = prefix_index.get(tuple(components[:key_arity]))
                    if not values:
                        measurement["unknown_lookup_count"] += 1
                        continue
                    if len(set(values)) > 1:
                        measurement["ambiguous_key_count"] += 1
                        continue  # an ambiguous prefix lookup is disclosed, not collapsed
                    prefix_value = values[0]
                    value = separator.join(
                        str(part) for part in (prefix_value, *components[key_arity:])
                    )
                else:
                    value = separator.join(str(part) for part in components)
                row["__constructed"] = value
                left_pairs.append((row, (value,)))
        else:
            left_pairs = list(zip(tested_left, left_tuples, strict=True))
        right_pairs = list(zip(tested_right, right_tuples, strict=True))
        left_compare = [value for _row, value in left_pairs]
        right_compare = [value for _row, value in right_pairs]
        right_values, left_values = set(right_compare), set(left_compare)
        matched_left = [value for value in left_compare if value in right_values]
        matched_right = [value for value in right_compare if value in left_values]
        measurement["coverage"] = {
            # the denominator is every sampled eligible row — an unresolvable
            # row (unknown/ambiguous lookup key) stays in it, unmatched
            "left_in_right": {"matched": len(matched_left), "tested": len(tested_left)},
            "right_in_left": {"matched": len(matched_right), "tested": len(tested_right)},
        }
        measurement["distinct_matched"] = len(set(matched_left))
        measurement["collisions"] = {
            "left": _collision_view(left_compare),
            "right": _collision_view(right_compare),
        }
        measurement["mismatch_count"] = len(left_compare) - len(matched_left)
        # independently paired comparison when pairing keys are supplied and
        # actually pair sampled records. K3 fix pass (finding 3): EVERY right
        # row is retained per pairing key — a key carrying multiple right rows
        # is disclosed as an ambiguous pairing and never silently collapsed to
        # the last row's value, so the basis never claims unique independent
        # pairing.
        paired = mismatches = ambiguous_keys = 0
        by_key: dict[tuple, list[tuple]] = {}
        if pairing:
            for row, value in right_pairs:
                if all(row[c] is not None for c in pairing_right):
                    by_key.setdefault(tuple(row[c] for c in pairing_right), []).append(value)
            ambiguous_keys = sum(1 for values in by_key.values() if len(values) > 1)
        max_rows_per_key = max((len(values) for values in by_key.values()), default=1)
        for row, value in left_pairs:
            if not pairing or not all(row[c] is not None for c in pairing_left):
                continue
            values = by_key.get(tuple(row[c] for c in pairing_left))
            if not values or len(values) > 1:
                continue  # unpaired or ambiguous: disclosed, never collapsed
            paired += 1
            if values[0] != value:
                mismatches += 1
        status = "absent"
        if pairing:
            if ambiguous_keys:
                status = "ambiguous"
            elif paired:
                status = "usable"
            else:
                status = "unusable"
        measurement["pairing"] = {
            "keys": [{"left": pair["left"], "right": pair["right"]} for pair in pairing],
            "status": status,
            "paired": paired,
            "ambiguous_keys": ambiguous_keys,
            "max_rows_per_key": max_rows_per_key,
        }
        if pairing and (paired or ambiguous_keys):
            if ambiguous_keys:
                measurement["comparison_basis"] = "ambiguous-pairing"
                measurement["mismatch_count"] = mismatches
                limitations.append(
                    f"{ambiguous_keys} sampled pairing key(s) carry multiple right "
                    f"rows (up to {max_rows_per_key} per key) — the paired comparison "
                    "cannot claim unique independent pairing"
                )
                if paired:
                    limitations.append(
                        f"paired comparison over {paired} unambiguously keyed sampled record(s)"
                    )
                else:
                    limitations.append("no sampled record pair could be compared unambiguously")
            else:
                measurement["comparison_basis"] = "independently-paired"
                measurement["mismatch_count"] = mismatches
                limitations.append(
                    f"paired comparison over {paired} independently keyed sampled record(s)"
                )
        else:
            measurement["comparison_basis"] = "containment-only"
            if pairing:
                limitations.append(
                    "the supplied pairing keys matched no sampled record pair — only "
                    "value containment was measured"
                )
        if example_budget:
            for row, value in left_pairs:
                if len(examples) >= example_budget:
                    break
                entry: dict = {"matched": value in right_values}
                if family == "prefix":
                    entry["components"] = {
                        column: _jsonable(row[column]) for column in left_columns
                    }
                    entry["constructed"] = value[0]
                    targets = [
                        r[right_columns[0]] for r in tested_right if (r[right_columns[0]],) == value
                    ]
                    entry["target"] = _jsonable(targets[0]) if targets else None
                else:
                    entry["left"] = {column: _jsonable(row[column]) for column in left_columns}
                examples.append(entry)

    complete_counts = (
        measurement["counts"]["eligible_left"] is not None
        and measurement["counts"]["eligible_right"] is not None
    )
    fact_full = complete_counts and (
        measurement["counts"]["tested_left"] >= measurement["counts"]["eligible_left"]
        and measurement["counts"]["tested_right"] >= measurement["counts"]["eligible_right"]
    )
    # K3 fix pass (finding 4): a truncated lookup sample forbids the 'full'
    # designation even when every fact row was tested — and the truncation is
    # disclosed, because keys beyond the sample are unknown lookups.
    lookup_full = lookup_counts is None or (
        lookup_counts["eligible"] is not None
        and lookup_counts["tested"] >= lookup_counts["eligible"]
    )
    measurement["designation"] = designation = "full" if (fact_full and lookup_full) else "sampled"
    if designation == "sampled":
        limitations.append(
            f"sampled completion: {measurement['counts']['tested_left']} of "
            f"{measurement['counts']['eligible_left']} eligible left rows and "
            f"{measurement['counts']['tested_right']} of "
            f"{measurement['counts']['eligible_right']} eligible right rows were "
            "tested — completion of the stated sample, never full-data proof"
        )
    if lookup_counts is not None and not lookup_full:
        limitations.append(
            f"the lookup asset {lookup_counts['asset']} was sampled at "
            f"{lookup_counts['tested']} of {lookup_counts['eligible']} eligible rows — "
            "a fact key beyond the sampled lookup rows is an unknown lookup, not a "
            "missing key"
        )
    if lookup_counts is not None and lookup_counts["null_rows_sampled"]:
        limitations.append(
            f"{lookup_counts['null_rows_sampled']} sampled lookup row(s) carried a "
            "null key or value and were not indexed"
        )
    limitations.append(
        "containment and pairing were measured over the materialized samples of "
        f"each participating asset (at most {sample_rows} rows per asset)"
    )
    limitations.extend(unavailable)
    measurement["outcome"] = "inconclusive" if unavailable else "complete"
    measurement["limitations"] = limitations
    if example_budget:
        measurement["examples"] = examples
    return measurement


def _asset_schema_digest(table: dict | None) -> str | None:
    """The digest of one dependency asset's FULL schema identity (K3 fix
    pass, finding 6): every catalog column's (name, type) at measurement
    time — beside the per-column identity ``dependencies.assets`` already
    carries, this binds the lookup asset's complete schema so ANY schema
    change on it invalidates the receipt immediately."""
    if not table:
        return None
    return _canonical_digest([(column["name"], column["type"]) for column in table["columns"]])


def _cited_policy_digest(worktree: Path, resource: str) -> str | None:
    """The sha256 of one cited dependency page inside the proposal's
    worktree — None (an honestly UNKNOWN dependency identity) when the
    resource is unreadable or escapes the worktree."""
    try:
        resolved = (worktree / resource).resolve()
        if not resolved.is_relative_to(worktree.resolve()):
            return None
        return _sha256_hex(resolved.read_bytes())
    except OSError:
        return None


def _cited_policy_dependencies(
    project: Path, proposal: str, revision: str, measured_digest: str
) -> list[dict]:
    """The cited Policy/OSI dependency identities of every Reference page in
    the proposal's CURRENT candidate that declares THIS exact candidate (K3
    fix pass, finding 6, spec 0010 §8): each such mapping's cited
    ``source_ids`` resolve to the page's ``sources[]`` resources, whose
    current content digests the receipt binds — a changed cited Policy page
    then invalidates the dependent evidence at verification. Resources are
    read from the proposal worktree (the candidate's own tracked pages and
    documents); an unreadable dependency is recorded with a null digest and
    can never verify as unchanged."""
    worktree = project / proposals.WORKTREES_REL / proposal
    entries: dict[str, dict] = {}
    for page in _reference_pages_at(project, revision).values():
        for mapping in page["meta"]["ariadne"].get("mappings") or []:
            if not isinstance(mapping, dict):
                continue
            try:
                if candidate_digest(mapping.get("candidate")) != measured_digest:
                    continue
            except ValueError:
                continue
            sources = {
                source.get("id"): source.get("resource")
                for source in page["meta"].get("sources") or []
                if isinstance(source, dict)
            }
            for source_id in mapping.get("source_ids") or []:
                resource = sources.get(source_id)
                if not isinstance(resource, str) or not resource or resource in entries:
                    continue
                # F2 (fix pass, spec0029 §1.5): an integrated Reference's
                # cited knowledge Policy binds to THAT KB page — the digest
                # resolves inside the knowledge subtree, never a same-path
                # legacy context_layer page; a missing dependency stays an
                # honest unknown
                worktree_resource = (
                    f"knowledge/{resource}" if page.get("kb_path") is not None else resource
                )
                entries[resource] = {
                    "resource": worktree_resource,
                    "digest": _cited_policy_digest(worktree, worktree_resource),
                }
    return [entries[resource] for resource in sorted(entries)]


def inspect_mapping(
    project: str | Path,
    proposal: str,
    expected_revision: str,
    candidate: object,
    limits: object = None,
) -> dict:
    """The ONE typed mapping-inspection operation (plan §2 ``inspect_mapping``,
    spec 0010 §7; issue #43/K3): measure a structured candidate from exactly
    the approved families — equality/composite, string prefix with an optional
    scoped prefix lookup, explicit scoped lookup — against the
    operator-APPROVED resolved source identity, through guarded core-generated
    read-only statements with parameterized scope, under the operator-owned
    finite ceilings (a request may only LOWER them), and retain the receipt
    atomically in the core-controlled ``.ariadne/`` evidence area. Never a
    page edit, never approval, never admission; aggregate counts are the
    default output and raw identifier examples need the operator's explicit
    sample permission."""
    project = Path(project).resolve()
    normalized = validate_inspection_candidate(candidate)
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if expected_revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the "
            f"inspection expected {expected_revision} — re-read the candidate and "
            "retry with the current revision; nothing was measured"
        )
    resolved, digest = authoring_sources.candidate_sources(project, current)
    if resolved is None:
        raise ValueError(
            f"proposal {proposal} declares no source entries in its candidate "
            f"registry at {current[:12]} — there is nothing to inspect"
        )
    assert digest is not None
    approval = authoring_sources._effective_grant(project, resolved, digest, proposal, current)
    effective = effective_inspection_limits(project_inspection_limits(project), limits)
    budget = execution.DeadlineBudget(effective["execution_seconds"])
    owned = execution.DuckDBExecution(
        authoring_sources.identity_registry(approval["sources"], approval.get("storage_bindings")),
        budget=budget,
    )
    try:
        con, catalog = owned.con, owned.catalog
        tables: dict[str, dict] = {}
        for binding in [
            *normalized["left"],
            *normalized["right"],
            *(normalized.get("scope") or []),
            *(
                pair[pairing_side]
                for pair in (normalized.get("pairing") or [])
                for pairing_side in ("left", "right")
            ),
            *(
                [
                    *normalized["prefix_lookup"]["key_fields"],
                    normalized["prefix_lookup"]["prefix_field"],
                ]
                if normalized.get("prefix_lookup")
                else []
            ),
            *(
                [
                    *normalized["lookup"]["key_fields"],
                    *normalized["lookup"]["value_fields"],
                ]
                if normalized.get("lookup")
                else []
            ),
        ]:
            if binding["resource"] not in tables:
                tables[binding["resource"]] = _participant(binding["resource"], catalog)
            # K3 fix pass (finding 1): EVERY bound column (sides, scope,
            # pairing, lookup fields) exists on its catalog asset BEFORE any
            # statement runs — a missing column is an up-front refusal, never
            # a mid-measurement "unavailable" disclosure.
            _column_type(tables[binding["resource"]], binding["column"])
        _check_family_types(normalized, tables)
        measurement = _measure(con, budget, normalized, tables, effective)
    finally:
        owned.close()
    observed_at = datetime.now(UTC).isoformat(timespec="seconds")
    assets = []
    for resource, table in tables.items():
        bound = {
            binding["column"]
            for binding in [
                *normalized["left"],
                *normalized["right"],
                *(normalized.get("scope") or []),
                *(
                    pair[pairing_side]
                    for pair in (normalized.get("pairing") or [])
                    for pairing_side in ("left", "right")
                ),
                *(
                    [
                        *normalized["prefix_lookup"]["key_fields"],
                        normalized["prefix_lookup"]["prefix_field"],
                    ]
                    if normalized.get("prefix_lookup")
                    else []
                ),
                *(
                    [
                        *normalized["lookup"]["key_fields"],
                        *normalized["lookup"]["value_fields"],
                    ]
                    if normalized.get("lookup")
                    else []
                ),
            ]
            if binding["resource"] == resource
        }
        ordered = [column for column in table["columns"] if column["name"] in bound]
        assets.append(
            {
                "resource": resource,
                "source": table.get("source"),
                "catalog": table.get("catalog"),
                "schema": table.get("schema"),
                "table": table["name"],
                "columns": [{"name": c["name"], "type": c["type"]} for c in ordered],
            }
        )
    receipt = {
        "receipt_id": f"mr-{uuid.uuid4().hex[:16]}",
        "family": normalized["family"],
        "candidate": normalized,
        "candidate_digest": _canonical_digest(normalized),
        "proposal": proposal,
        "inspection_revision": current,
        "source_digest": digest,
        "source_identity": resolved,
        "approval_digest": approval.get("approval_digest") or digest,
        "storage_bindings": approval.get("storage_bindings") or {},
        "dependencies": {
            "assets": sorted(assets, key=lambda asset: asset["resource"]),
            "lookup": normalized.get("prefix_lookup") or normalized.get("lookup"),
            # K3 fix pass (finding 6, spec 0010 §8): the cited Policy/OSI
            # dependencies of the Reference pages that declare THIS candidate
            # in the current proposal candidate — the receipt binds their
            # content digests so a changed cited Policy page invalidates it.
            "policy_osi": _cited_policy_dependencies(
                project, proposal, current, _canonical_digest(normalized)
            ),
            # the lookup asset's FULL schema identity (its measured columns
            # ride dependencies.assets; any schema change on the lookup asset
            # invalidates immediately)
            "lookup_schema_digest": _asset_schema_digest(
                tables.get(
                    (normalized.get("prefix_lookup") or normalized.get("lookup") or {})["asset"]
                    if normalized.get("prefix_lookup") or normalized.get("lookup")
                    else ""
                )
            ),
        },
        "observed_at": observed_at,
        "version_signal": {"state": "as_of", "observed_at": observed_at},
        "scope": normalized.get("scope") or [],
        "pairing": measurement.pop("pairing"),
        "comparison_basis": measurement.pop("comparison_basis"),
        "sample_rows": effective["sample_rows"],
        **measurement,
    }
    receipt["integrity_digest"] = _canonical_digest(receipt)
    envelope = {
        "proposal": proposal,
        "revision": current,
        "receipt_id": receipt["receipt_id"],
        "receipt": receipt,
        # K3 fix pass (finding 8): the COMPLETE final envelope (evidence path
        # included) is what the response ceiling measures — and the receipt is
        # retained only after the complete envelope fits.
        "evidence": str(_receipt_path(project, proposal, receipt["receipt_id"])),
    }
    size = len(json.dumps(envelope, ensure_ascii=False).encode("utf-8"))
    if size > effective["response_bytes"]:
        raise ValueError(
            f"the serialized inspection response is {size} bytes, over the "
            f"{effective['response_bytes']}-byte ceiling — lower the raw-example "
            "count or narrow the candidate; no receipt was retained"
        )
    store_receipt(project, proposal, receipt)
    return envelope


def _receipt_summary(receipt: dict) -> dict:
    """The bounded, credential-free verified summary of one retained receipt —
    exactly the fields a finalized Reference page may cite (plan §2: bounded
    summaries only, never raw examples, never model-authored counts)."""
    counts = receipt["counts"]
    return {
        "id": receipt["receipt_id"],
        "digest": receipt["integrity_digest"],
        "family": receipt["family"],
        "outcome": receipt["outcome"],
        "designation": receipt["designation"],
        "comparison_basis": receipt["comparison_basis"],
        "tested_left": counts["tested_left"],
        "tested_right": counts["tested_right"],
        "eligible_left": counts["eligible_left"],
        "eligible_right": counts["eligible_right"],
        "matched_left_in_right": receipt["coverage"]["left_in_right"]["matched"],
        "matched_right_in_left": receipt["coverage"]["right_in_left"]["matched"],
        "mismatch_count": receipt["mismatch_count"],
        "observed_at": receipt["observed_at"],
    }


def _current_asset_columns(catalog: list[dict]) -> dict[str, list[dict]]:
    """resource -> [{name, type}] of every asset the approved identity holds."""
    columns: dict[str, list[dict]] = {}
    for entry in catalog:
        for table in entry["tables"]:
            columns[table["resource"]] = [
                {"name": column["name"], "type": column["type"]} for column in table["columns"]
            ]
    return columns


def _verify_receipt(
    receipt_id: str,
    project: Path,
    proposal: str,
    *,
    declaration_digest: str,
    source_digest: str | None,
    asset_columns: dict[str, list[dict]],
    endpoints: dict | None = None,
    worktree: Path | None = None,
    max_age_hours: float | None = None,
    storage_bindings: dict | None = None,
) -> tuple[dict | None, str | None]:
    """Verify ONE cited receipt against the project's evidence records and the
    current dependency identities (spec 0010 §§7–8): existence, integrity, the
    normalized DECLARATION the receipt measured, the ENDPOINT correspondence
    of the mapping's representations (K3 fix pass, finding 5: the measured
    left/right bindings and scope must correspond to the declared endpoints —
    a retargeted representation never keeps a verified summary), the resolved
    SOURCE identity it read, the measured ASSET/LOOKUP columns, the lookup
    asset's full schema digest, the bound cited Policy/OSI dependency digests
    (finding 6) and the operator's evidence age budget (finding 6: age bounds
    the RECEIPT's validity for attachment; unversioned data stays as_of).
    Returns (summary, None) or (None, error) — an allowlisted id or an
    author-authored count is never proof. Receipt validity is
    dependency-matched, not candidate-revision matched: an unrelated save
    commit keeps a receipt valid, a changed declaration/input does not
    (plan §2)."""
    try:
        receipt = load_receipt(project, proposal, receipt_id)
    except ValueError as exc:
        return None, str(exc)
    if receipt.get("candidate_digest") != declaration_digest:
        return None, (
            f"receipt {receipt_id!r} measures a different declaration (its normalized "
            f"candidate digest is {str(receipt.get('candidate_digest'))[:12]}, the "
            f"declared candidate's is {declaration_digest[:12]}) — changed mapping "
            "parameters invalidate dependent evidence; re-inspect the changed candidate"
        )
    if endpoints is not None:
        measured = receipt.get("candidate") or {}
        for key, side in (("from", "left"), ("to", "right")):
            declared = [
                (binding.get("resource"), binding.get("column"))
                for binding in endpoints[key]["fields"]
                if isinstance(binding, dict)
            ]
            measured_side = [
                (binding.get("resource"), binding.get("column"))
                for binding in measured.get(side) or []
                if isinstance(binding, dict)
            ]
            if declared != measured_side:
                return None, (
                    f"receipt {receipt_id!r} measured {side} bindings {measured_side} "
                    f"but the mapping's {key!r} representation declares {declared} — "
                    "retargeted endpoint representations invalidate dependent "
                    "evidence; re-inspect against the declared representation"
                )
        scope_columns = {
            (predicate.get("resource"), predicate.get("column"))
            for predicate in measured.get("scope") or []
            if isinstance(predicate, dict)
        }
        for key in ("from", "to"):
            for binding in endpoints[key]["scope"]:
                required = (binding.get("resource"), binding.get("column"))
                if required not in scope_columns:
                    return None, (
                        f"receipt {receipt_id!r} was not measured under the required "
                        f"scope {required} of the mapping's {key!r} representation — "
                        "evidence must correspond to the declared scope"
                    )
    if receipt.get("source_digest") != source_digest:
        return None, (
            f"receipt {receipt_id!r} was measured against a different resolved source "
            f"identity ({str(receipt.get('source_digest'))[:12]}, the candidate now "
            f"resolves to {str(source_digest)[:12]}) — changed inputs invalidate "
            "dependent evidence"
        )
    if storage_bindings is not None and (receipt.get("storage_bindings") or {}) != (
        storage_bindings or {}
    ):
        return None, (
            f"receipt {receipt_id!r} was measured against a different effective "
            "storage binding (spec 0025 §4) — an endpoint change invalidates "
            "dependent evidence; re-inspect against the current binding"
        )
    dependencies = receipt.get("dependencies") or {}
    lookup_asset = (dependencies.get("lookup") or {}).get("asset")
    schema_digest = dependencies.get("lookup_schema_digest")
    if schema_digest is not None and isinstance(lookup_asset, str):
        current = asset_columns.get(lookup_asset)
        if (
            current is None
            or _canonical_digest([(c["name"], c["type"]) for c in current]) != schema_digest
        ):
            return None, (
                f"receipt {receipt_id!r} depends on the lookup asset {lookup_asset!r} "
                "whose schema changed since the measurement — schema changes "
                "invalidate dependent evidence immediately"
            )
    for asset in dependencies.get("assets") or []:
        current = asset_columns.get(asset["resource"])
        if current is None:
            return None, (
                f"receipt {receipt_id!r} depends on asset {asset['resource']!r} which "
                "is no longer present in the approved resolved source identity"
            )
        recorded = [(column["name"], column["type"]) for column in asset["columns"]]
        wanted = {name for name, _type in recorded}
        now = [(column["name"], column["type"]) for column in current if column["name"] in wanted]
        if recorded != now:
            return None, (
                f"receipt {receipt_id!r} depends on asset {asset['resource']!r} whose "
                "measured columns changed since the measurement — schema changes "
                "invalidate dependent evidence immediately"
            )
    for dependency in dependencies.get("policy_osi") or []:
        resource = dependency.get("resource")
        current_digest = (
            _cited_policy_digest(worktree, resource)
            if isinstance(resource, str) and worktree is not None
            else None
        )
        if dependency.get("digest") is None or current_digest != dependency.get("digest"):
            return None, (
                f"receipt {receipt_id!r} depends on the cited Policy/OSI page "
                f"{resource!r} whose content changed since the measurement (or can "
                "no longer be read) — referenced Policy/OSI content changes "
                "invalidate dependent evidence immediately"
            )
    if max_age_hours is not None:
        observed = receipt.get("observed_at")
        try:
            observed_at = datetime.fromisoformat(observed) if isinstance(observed, str) else None
            if observed_at is None:
                raise ValueError(observed)
            age = datetime.now(UTC) - observed_at
        except ValueError, TypeError, OverflowError:
            return None, (
                f"receipt {receipt_id!r} carries no parseable measurement time — "
                "its freshness is unknown and can never be verified as current"
            )
        if age > timedelta(hours=max_age_hours):
            return None, (
                f"receipt {receipt_id!r} was measured at {observed} ({age} ago), "
                f"beyond the operator's {max_age_hours}h evidence age budget — age "
                "bounds the receipt's validity for attachment (unversioned data "
                "stays as-of); re-inspect to attach fresh evidence"
            )
    return _receipt_summary(receipt), None


def _reference_pages_at(project: Path, revision: str) -> dict[str, dict]:
    """The tracked structured Reference pages at one revision: path ->
    {meta, text}. Pages without the ``ariadne`` extension stay out (legacy
    References never carry mapping evidence). Integrated candidates carry
    their structured References in the knowledge/ subtree (spec0029 §1.5):
    each record also keeps the KB-relative path and the FULL page frontmatter
    for the Core-owned evidence attach, which rewrites the page through the
    producer's public parse and checked worktree write — never a
    context_layer mirror."""
    tracked = proposals._git(["ls-tree", "-r", "--name-only", revision], project).stdout
    pages: dict[str, dict] = {}
    integrated = "context_integration.yaml" in tracked.split("\n")
    for rel in tracked.split("\n"):
        kb_path: str | None = None
        if integrated:
            if not rel.startswith("knowledge/") or not rel.endswith(".md"):
                continue
            kb_path = PurePosixPath(rel).relative_to("knowledge").as_posix()
            if PurePosixPath(rel).name in proposals._GENERATED_FILES or kb_path in (
                "index.md",
                "log.md",
            ):
                continue
        elif not rel.startswith("context_layer/references/") or not rel.endswith(".md"):
            continue
        else:
            if PurePosixPath(rel).name in proposals._GENERATED_FILES:
                continue
        blob = proposals._read_blob(project, revision, rel)
        if blob is None:  # pragma: no cover - ls-tree paths always resolve
            continue
        text = blob.decode("utf-8", "replace")
        if kb_path is not None:
            parsed = _kb_reference_from_text(text, kb_path)
            if parsed is None:
                continue
            view, full = parsed
            if not view["ariadne"].get("mappings"):
                continue
            pages[rel] = {"meta": view, "text": text, "full": full, "kb_path": kb_path}
        else:
            try:
                meta = _load_frontmatter_meta(text)
            except yaml.YAMLError:
                continue  # the native page gate owns malformed legacy pages
            extension = meta.get("ariadne") if isinstance(meta, dict) else None
            if isinstance(extension, dict) and extension.get("mappings"):
                pages[rel] = {"meta": meta, "text": text}
    return pages


EVIDENCE_COMMIT_MESSAGE = "ariadne: attach verified mapping evidence"


def _kb_evidence_page(page: dict, desired: dict | None) -> str:
    """Rewrite one integrated KB Reference page's Core-attached evidence slot
    through the producer's public frontmatter parse (spec0029 §1.5): the
    curated body bytes and every other frontmatter key are preserved, only
    ``ariadne_profile.native.ariadne_evidence`` changes. The resulting page
    is applied by the caller through the producer's checked worktree write —
    never a Core YAML write of the KB."""
    from lumio_wiki import parse_frontmatter  # pyright: ignore[reportMissingImports] — optional SDK

    meta, body, _body_start = parse_frontmatter(page["text"], page["kb_path"])
    native = meta["ariadne_profile"]["native"]
    if desired:
        native["ariadne_evidence"] = desired
    else:
        native.pop("ariadne_evidence", None)
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---" + body


def _commit_core_pages(project: Path, record: dict, rels: list[str], message: str) -> str | None:
    """Commit EXACTLY the named core-authored page changes in the proposal
    worktree (the caller holds the proposal lock): any other change is the
    interrupted-transition refusal, exactly like the finalize commit's
    discipline. Returns the new candidate revision or None when nothing
    changed."""
    proposal = record["id"]
    worktree = project / proposals.WORKTREES_REL / proposal
    changed: list[str] = []
    for line in proposals._git(
        ["status", "--porcelain", "--untracked-files=all"], worktree
    ).stdout.splitlines():
        if not line.strip():
            continue
        rel = line[3:].rsplit(" -> ", 1)[-1]
        if rel in rels:
            changed.append(rel)
        else:
            raise ValueError(
                f"the worktree of proposal {proposal} carries the change {rel!r} "
                "outside the core-authored evidence pages" + proposals._HUMAN_RESOLUTION
            )
    if not changed:
        return None
    proposals._require_git_identity(project)
    literal = [proposals._literal(rel) for rel in changed]
    proposals._git(["add", "-f", "--", *literal], worktree)
    proposals._git(["commit", "-m", message, "--", *literal], worktree)
    record["candidate_revision"] = proposals._git(["rev-parse", "HEAD"], worktree).stdout.strip()
    proposals._store_record(project, record)
    return record["candidate_revision"]


def _finalize_mapping_evidence(
    project: Path,
    proposal: str,
    record: dict,
    revision: str,
    *,
    source_digest: str | None,
    approval: dict | None,
) -> tuple[str, list[str]]:
    """The K3 finalization step (plan §2): verify every structured mapping's
    cited receipts against the project's evidence records and the current
    dependency identities, attach the bounded verified summaries to the
    Reference pages as the core-owned ``ariadne_evidence`` frontmatter block,
    and REMOVE a block whose receipts no longer verify. Returns (the final
    revision, errors) — an unverifiable receipt is a validation error naming
    the mapping, never a silently inherited summary."""
    pages = _reference_pages_at(project, revision)
    cited = any(
        mapping.get("receipt_ids")
        for page in pages.values()
        for mapping in (page["meta"]["ariadne"].get("mappings") or [])
        if isinstance(mapping, dict)
    )
    carried = any("ariadne_evidence" in page["meta"] for page in pages.values())
    if not pages or not (cited or carried):
        return revision, []
    asset_columns: dict[str, list[dict]] = {}
    if approval is not None:
        owned = execution.DuckDBExecution(authoring_sources.identity_registry(approval["sources"]))
        try:
            asset_columns = _current_asset_columns(owned.catalog)
        finally:
            owned.close()
    errors: list[str] = []
    rewrites: dict[str, str] = {}
    # K3 fix pass (finding 6): the operator's evidence age budget (host
    # config only) bounds how old a receipt may be and still attach; the
    # cited Policy/OSI digests re-verify against the proposal worktree.
    max_age_hours = project_inspection_limits(project)["receipt_max_age_hours"]
    worktree = project / proposals.WORKTREES_REL / proposal
    for rel, page in pages.items():
        representations = {
            representation.get("id"): representation
            for representation in (page["meta"]["ariadne"].get("representations") or [])
            if isinstance(representation, dict) and isinstance(representation.get("id"), str)
        }
        desired: dict[str, list[dict]] = {}
        for mapping in page["meta"]["ariadne"].get("mappings") or []:
            if not isinstance(mapping, dict):
                continue
            receipt_ids = mapping.get("receipt_ids") or []
            if not receipt_ids:
                continue
            declaration = mapping.get("candidate")
            try:
                declaration_digest = candidate_digest(declaration)
            except ValueError as exc:
                errors.append(
                    f"{rel}: mapping {mapping.get('id')!r} cites receipts but its "
                    f"candidate declaration is not measurable: {exc}"
                )
                continue
            # K3 fix pass (finding 5): the measured candidate must correspond
            # to the mapping's ENDPOINT representations (fields and required
            # scope) BEFORE any evidence attaches — an endpoint that fails to
            # resolve is the page contract's own error, not a correspondence
            # check (verification then runs without endpoints).
            endpoints: dict | None = {}
            for key in ("from", "to"):
                representation = representations.get(mapping.get(key))
                if not isinstance(representation, dict) or not isinstance(
                    representation.get("fields"), list
                ):
                    endpoints = None
                    break
                endpoints[key] = {
                    "fields": representation.get("fields") or [],
                    "scope": representation.get("scope") or [],
                }
            summaries = []
            for receipt_id in receipt_ids:
                summary, error = _verify_receipt(
                    receipt_id,
                    project,
                    proposal,
                    declaration_digest=declaration_digest,
                    source_digest=source_digest,
                    asset_columns=asset_columns,
                    endpoints=endpoints,
                    worktree=worktree,
                    max_age_hours=max_age_hours,
                    storage_bindings=(approval or {}).get("storage_bindings"),
                )
                if error is not None:
                    errors.append(f"{rel}: mapping {mapping.get('id')!r} — {error}")
                    continue
                assert summary is not None
                summaries.append(summary)
                # K4 fix pass (finding 1, spec 0010 §§8–9): an ASSERTED claim
                # contradicted by its own verified receipts (honest mismatches,
                # an ambiguous pairing basis or an inconclusive outcome) is
                # unsupported and fails the mapping-evidence gate — the same
                # receipt under a hypothesis claim stays admissible as openly
                # labeled investigative knowledge.
                if mapping.get("claim") == "asserted":
                    named = evidence_counterevidence(summary)
                    if named:
                        errors.append(
                            f"{rel}: mapping {mapping.get('id')!r} is asserted but its "
                            f"verified receipt {summary.get('id')!r} shows "
                            f"counterevidence ({named}) — an asserted claim "
                            "contradicted by its own cited evidence is unsupported; "
                            "carry it as a labeled hypothesis instead"
                        )
            if summaries:
                desired[str(mapping.get("id"))] = summaries
        current = page["meta"].get("ariadne_evidence")
        if current != (desired or None):
            if page.get("kb_path") is not None:
                rewrites[rel] = _kb_evidence_page(page, desired)
            else:
                rewrites[rel] = context._set_frontmatter_key(
                    page["text"], "ariadne_evidence", desired or None
                )
    final = revision
    if rewrites:
        core_rels: list[str] = []
        kb_revisions: list[tuple[str, str]] = []
        for rel, text in rewrites.items():
            if pages[rel].get("kb_path") is not None:
                kb_revisions.append((pages[rel]["kb_path"], text))
            else:
                proposals._safe_write(worktree, rel, text)
                core_rels.append(rel)
        if kb_revisions:
            # the KB evidence attach goes through the producer's public parse
            # and checked worktree write contract: the curated body, profile
            # and Entity are preserved, only the Core-attached
            # ariadne_evidence slot changes (spec0029 §1.5)
            from lumio_wiki.git_authoring import (  # pyright: ignore[reportMissingImports] — optional SDK
                revise_pages_in_worktree,
            )

            revise_pages_in_worktree(
                worktree / "knowledge",
                kb_revisions,
                operation="attach verified mapping evidence",
            )
            core_rels.extend(f"knowledge/{kb_path}" for kb_path, _text in kb_revisions)
        final = (
            _commit_core_pages(project, record, sorted(core_rels), EVIDENCE_COMMIT_MESSAGE)
            or revision
        )
    return final, errors

"""Explicit legacy-artifact import into the Git authoring workflow (issue #39
/ G7; spec 2026-10-02-0009 §7 + AC5/8/9, plan §2's ``migration.py`` row, ADR
0003/0009/0016's scoped amendments: the legacy staging/Promotion route,
standalone ingestion and the Answer Example store keep their own contracts).

:func:`import_legacy` is the HUMAN-ONLY migration step — exposed ONLY through
the local command adapter (``ariadne-authoring import-legacy --project DIR
--from-root ROOT``), never an MCP registration or a native Agent tool. It
copies a legacy project's SELECTED artifacts — the source registry
(``ariadne.yaml``), Seed Notes, OSI models, the multi-fact graph and the OKF
content pages — into a FRESH UNADMITTED Git authoring proposal, or into the
human-created initial artifact revision when the project has none yet:

- A project with no artifact revision yet (no commits, or history that carries
  no candidate-scope path) gets the legacy bytes as its INITIAL ARTIFACT
  REVISION base content: the files are copied into the project tree (never
  overwriting a conflicting file) and committed through the same explicit
  allowlisted literal-pathspec seam ``start_proposal`` uses — tracked even
  under an old ignore rule that excludes the served layers. Imported as BASE
  CONTENT, the promotion-stamped trust claims of served pages (``verified``
  history, ``status: stable``) are preserved byte-for-byte as content, never
  as model edits claiming new authority: the G2 forged-claims gate compares
  edits against this base, so the imported claims neither grant nor lose
  meaning (spec §4/§7).
- A project that already carries an artifact revision gets a fresh unadmitted
  PROPOSAL whose edits go through the SAME layer edit interfaces the agent
  surface uses (:mod:`ariadne.authoring_semantic` /
  :mod:`ariadne.authoring_context` resolvers + ``edit_proposal``):
  revision-checked, one complete artifact per edit, registry entries appended
  through the typed ``propose_sources`` seam (never overwriting an existing
  name). Trust claims the base does not carry are refused by the shared
  forged-claims gate — the import grants no special authority.

Generated bookkeeping (``index.md``/``log.md`` trees, computation pages) is
NEVER imported: the finalize pass owns and regenerates it before validation.
Pending legacy work is preserved byte-for-byte OUTSIDE the proposal — the
legacy ``staging/`` tree (an outstanding harness-led bundle, a standalone
ingest proposal, an ad-hoc proposal, an Answer Example) is never read or
written here, and page citations ride along as content, unchanged.

Import is NEVER admission (AC9): a Git commit of existing files is not human
review, a legacy ``bundle-state.json`` validation marker is not Git validation
evidence, and imported frontmatter claims are not sign-off. The first admitted
snapshot is established only through the normal steps — operator source
approval (``approve-sources``), ``validate`` (finalize + the full check stack
bound to the exact final commit), ``review`` and the human
``ariadne-admit --confirm`` (spec §5).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import proposals, sources
from ariadne.authoring import AuthoringProject

# The human steps every import needs before anything is served (spec §5/§7):
# rendered into the import envelope with the concrete proposal identity.
_ADMISSION_STEPS = (
    "operator source approval: ariadne-authoring approve-sources --project {project} "
    "--proposal {proposal} --revision <candidate-revision> --source-digest <digest>",
    "finalize and validate the exact final revision: ariadne-authoring validate "
    "--project {project} --proposal {proposal} --expected-revision <candidate-revision>",
    "human review of the exact candidate: ariadne-authoring review --project {project} "
    "--proposal {proposal}",
    "human Git Review Admission of the reviewed digest: ariadne-admit --project "
    "{project} --proposal {proposal} --revision <final-revision> "
    "--reviewed-digest <digest> --confirm",
)


def _legacy_selection(from_root: Path) -> list[tuple[str, bytes]]:
    """The SELECTED legacy artifacts of ``from_root``: exactly the
    user-editable candidate scope (registry, Seed Notes, models, graph, OKF
    content pages — generated bookkeeping excluded), each with its exact
    bytes. The shared credential boundary runs BEFORE anything is copied or
    committed."""
    selection: list[tuple[str, bytes]] = []
    for rel in proposals._scope_files(from_root):
        if not proposals._in_user_scope(rel):  # defense behind the grammar
            continue
        data = (from_root / rel).read_bytes()
        text = data.decode("utf-8", "replace")
        proposals.check_artifact_content(f"legacy artifact {rel!r}", text)
        selection.append((rel, data))
    return selection


def _legacy_registry_entries(from_root: Path) -> list[dict]:
    """The legacy ``ariadne.yaml`` source entries, validated through the
    shared registry rules against the LEGACY root (the identity spelling the
    Git route re-resolves against the host project). [] when the legacy
    project declares no registry."""
    path = from_root / "ariadne.yaml"
    if not path.is_file():
        return []
    sources.load_registry(path)  # the shared ADR-0010 validation, verbatim
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = doc.get("sources") if isinstance(doc, dict) else None
    return [dict(entry) for entry in entries] if isinstance(entries, list) else []


def _typed_edit(rel: str, content: str) -> dict:
    """One legacy artifact as the discriminated edit object of the layer edit
    interfaces (plan §2's Authoring call contract): the SAME typed shape an
    agent edit carries, resolved by the same layer resolvers."""
    parts = PurePosixPath(rel).parts
    if rel == "data/seed_notes.md":
        return {"kind": "seed_notes", "content": content}
    if rel == "semantic_layer/graph.yml":
        return {"kind": "graph", "content": content}
    if parts[:2] == ("semantic_layer", "models"):
        return {"kind": "model", "name": PurePosixPath(rel).stem, "content": content}
    section = "references" if parts[1] == "references" else parts[1]
    return {
        "kind": "page",
        "section": section,
        "name": PurePosixPath(rel).stem,
        "content": content,
    }


def _tracked_artifacts(project: Path, revision: str) -> bool:
    """True when ``revision`` already carries a candidate-scope artifact path
    — the project HAS an artifact revision (a proposal can build on it)."""
    tracked = proposals._git(["ls-tree", "-r", "--name-only", revision], project).stdout
    return any(proposals._in_snapshot(rel) for rel in tracked.split())


def _copy_into_project(
    project: Path, from_root: Path, selection: list[tuple[str, bytes]]
) -> list[str]:
    """Copy the selected legacy artifacts into the project tree so the
    human-created initial artifact revision commits exactly these bytes (the
    base-content import). Never overwrites: a conflicting existing file is an
    actionable error, an identical one is already in place, and a symlinked
    target component is refused before any write."""
    copied: list[str] = []
    for rel, data in selection:
        source = from_root.joinpath(*PurePosixPath(rel).parts)
        target = project.joinpath(*PurePosixPath(rel).parts)
        if target.resolve() == source.resolve():
            continue  # same tree: the artifact is already where it belongs
        proposals._refuse_symlinked_component(project, PurePosixPath(rel))
        if target.exists():
            if target.read_bytes() == data:
                continue
            raise ValueError(
                f"{target} already exists with different content than {source} — "
                "resolve the conflict by hand and re-run; the import never "
                "overwrites an existing project file"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        copied.append(rel)
    return copied


def import_legacy(*, project: str | Path, from_root: str | Path) -> dict:
    """HUMAN-ONLY (the ``ariadne-authoring import-legacy`` adapter): copy the
    selected legacy artifacts into a fresh UNADMITTED Git authoring proposal
    — or into the human-created initial artifact revision when the project
    has none yet — through the same layer edit interfaces the agent surface
    uses. Pending legacy staging/state is never touched, citations are
    preserved as content, and NOTHING is admitted, validated or reviewed: the
    envelope names the human steps that alone establish the first snapshot."""
    project = Path(project).resolve()
    from_root = Path(from_root).resolve()
    if not from_root.is_dir():
        raise ValueError(
            f"{from_root} is not a directory — name the legacy project root to import from"
        )
    proposals._require_repo(project)  # the actionable git-init error, early
    selection = _legacy_selection(from_root)
    if not selection:
        raise ValueError(
            f"no legacy artifacts found under {from_root} — the import copies "
            "ariadne.yaml, data/seed_notes.md, semantic_layer/models/*.yml, "
            "semantic_layer/graph.yml and OKF pages under context_layer/"
            "{tables,references/joins,policies,metrics,skills}/"
        )
    entries = _legacy_registry_entries(from_root)

    head = proposals._current_head(project)
    if head is None or not _tracked_artifacts(project, head):
        # No artifact revision yet: the legacy bytes become the BASE CONTENT
        # (byte-for-byte, claims included — never model edits), committed by
        # the human-created initial artifact revision seam.
        _copy_into_project(project, from_root, selection)
        if head is not None:
            proposals.create_initial_revision(project)
        started = proposals.start_proposal(project)
        mode = "initial-artifact-revision"
        registry: dict = {"entries": len(entries), "base_content": True}
    else:
        started = proposals.start_proposal(project)
        mode = "proposal-edits"
        registry = {"entries": len(entries)}

    api = AuthoringProject(project)
    proposal = started["proposal"]
    revision = started["candidate_revision"]
    imported: list[dict] = []
    for rel, data in selection:
        if rel == "ariadne.yaml":
            continue  # the registry is handled through its own typed seam below
        if proposals._read_blob(project, revision, rel) == data:
            # already the base content, byte-for-byte: no edit churn, no
            # normalization pass, claims preserved exactly
            imported.append({"path": rel, "changed": False})
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"legacy artifact {rel!r} is not UTF-8 text ({exc}) — artifacts are "
                "text files; resolve the encoding by hand and re-run"
            ) from None
        edit = _typed_edit(rel, content)
        result = api.edit_proposal(proposal, revision, edit)
        revision = result["revision"]
        imported.append({"path": rel, "changed": result["changed"]})

    if mode == "proposal-edits" and entries:
        # The registry arrives through the typed source-proposal seam: entries
        # identical to the candidate's stay untouched, a name clash with
        # different content is an actionable error, new names are appended
        # (never overwriting) and stay INERT until the operator approves the
        # resolved identity (spec §5).
        blob = proposals._read_blob(project, revision, "ariadne.yaml")
        current = yaml.safe_load(blob.decode("utf-8")) or {} if blob else {}
        existing = {
            entry.get("name"): entry
            for entry in (current.get("sources") or [])
            if isinstance(entry, dict)
        }
        fresh: list[dict] = []
        for entry in entries:
            name = entry.get("name")
            if name not in existing:
                fresh.append(entry)
            elif existing[name] != entry:
                raise ValueError(
                    f"legacy source {name!r} differs from the candidate registry entry "
                    "of the same name — the import appends, it never overwrites; "
                    "resolve the conflict by hand"
                )
        if fresh:
            result = api.propose_sources(proposal, revision, fresh)
            revision = result["revision"]
            registry["proposed"] = len(fresh)
            registry["source_digest"] = result["source_digest"]
        else:
            registry["identical"] = True

    return {
        "project": str(project),
        "from_root": str(from_root),
        "mode": mode,
        "proposal": proposal,
        "base_revision": started["base_revision"],
        "revision": revision,
        "imported": imported,
        "registry": registry,
        "staging_untouched": True,
        "admitted": False,
        "admission_required": [
            step.format(project=project, proposal=proposal) for step in _ADMISSION_STEPS
        ],
        "note": (
            "import is not admission: a Git commit of existing files is never human "
            "review (spec §7/AC9) — the imported proposal is unadmitted until the "
            "named human steps establish the first admitted snapshot"
        ),
    }

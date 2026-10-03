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

K6 (issue #46, spec 0010 §4/§9): :func:`enrich_legacy` is the SECOND
human-only seam of this module — the explicit binding of ONE imported legacy
physical-table page (its unqualified spelling, e.g. a ``source.table``
citation) to the canonical resource of an EXPLICITLY identified approved
catalog asset, as one complete page edit through the core-owned regeneration
seam. It never guesses: an ambiguous spelling (same-named tables of distinct
sources/schemas) and an asset outside the approved identity are explicit
refusals. The old filename, links, citations and promotion-stamped history are
preserved; authored legacy explanations under the refresh-owned
Schema/Observations headings are re-homed into the authored sections (Column
meanings / Authored notes), never silently discarded; nothing is renamed,
deleted, reclassified, refreshed or admitted — the explicit
``refresh-schema`` and the normal admission steps stay separate.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne import authoring, authoring_sources, execution, proposals, sources
from ariadne.authoring import AuthoringProject
from ariadne.authoring_sources import candidate_sources
from ariadne.context import (
    _FRONTMATTER_RE,
    MEANINGS_SECTION,
    OBSERVATIONS_SECTION,
    SCHEMA_SECTION,
    _assemble_body,
    _body_sections,
    _load_frontmatter_meta,
    _meaning_blocks,
    _set_frontmatter_key,
)
from ariadne.sources import parse_resource

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
    if parts[1] == "references":
        # K2 (issue #42): general References are the ``references`` section;
        # the legacy join References under references/joins/ are ``joins``.
        section = "joins" if len(parts) > 3 else "references"
    else:
        section = parts[1]
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


# ------------------------- K6 (issue #46): the explicit legacy enrichment


def _asset_of(table: dict) -> dict:
    """One approved catalog table's explicit identity tuple."""
    return {
        "source": table["source"],
        "catalog": table.get("catalog"),
        "schema": table.get("schema"),
        "table": table["name"],
    }


def _spelling_matches(spelling: str, catalog: list[dict]) -> list[dict]:
    """The approved catalog tables ONE legacy spelling names: ``<table>``
    (any source), ``<source>.<table>`` (any schema of that source) or
    ``<source>.<schema>.<table>`` — exact case-sensitive identifiers, never a
    fuzzy or suffix match. An identifier cannot contain a dot, so the split is
    unambiguous."""
    pieces = spelling.split(".")
    if not 1 <= len(pieces) <= 3 or not all(pieces):
        return []  # a non-identifier citation (a document path, a URI): not a binding spelling
    tables = [table for entry in catalog for table in entry["tables"]]
    if len(pieces) == 1:
        return [table for table in tables if table["name"] == pieces[0]]
    if len(pieces) == 2:
        return [
            table
            for table in tables
            if table["source"] == pieces[0] and table["name"] == pieces[1]
        ]
    return [
        table
        for table in tables
        if (
            table["source"],
            table.get("schema"),
            table["name"],
        )
        == (pieces[0], pieces[1], pieces[2])
    ]


# The clearly labeled authored-notes section of an enriched legacy page
# (issue #46/K6): the enrichment re-homes the remaining authored prose/links
# found under the refresh-owned Schema/Observations headings (everything that
# is not a column-explanation bullet) here — outside the core-owned sections,
# so the explicit refresh carries it forward verbatim, honestly labeled as
# authored, never measured (spec 0010 §4/§9).
AUTHORED_NOTES_SECTION = "Authored notes"


def _rehome_legacy_authored(text: str) -> str:
    """Re-home the authored content a legacy page carries under the headings
    the bound page's refresh will OWN and regenerate (``Schema`` /
    ``Observations``, spec 0010 §4) BEFORE the binding edit: every
    column-explanation bullet — with its continuation lines — moves into the
    authored ``Column meanings`` section, where the K1 meaning-preservation
    path keeps it for identical column identity/type (so refresh never
    re-seeds ``unknown`` for a documented column), and every remaining
    authored line moves into the clearly labeled ``Authored notes`` section
    that regeneration carries forward verbatim. The core-owned headings
    themselves belong to refresh (regenerated, never carried); a page with
    no authored content under them returns unchanged."""
    match = _FRONTMATTER_RE.match(text)
    body = match.group(2) if match else text
    meanings: list[str] = []
    notes: list[str] = []
    kept: list[tuple[str | None, list[str]]] = []
    for heading, lines in _body_sections(body):
        if heading not in (SCHEMA_SECTION, OBSERVATIONS_SECTION):
            kept.append((heading, lines))  # authored sections stay where they sit
            continue
        for column, _meaning, block in _meaning_blocks(lines[1:]):
            target = meanings if column is not None else notes
            target.extend(line for line in block if line.strip())
    if not meanings and not notes:
        return text  # nothing authored under refresh-owned headings
    for section, lines in ((MEANINGS_SECTION, meanings), (AUTHORED_NOTES_SECTION, notes)):
        if not lines:
            continue
        index = next((i for i, (h, _l) in enumerate(kept) if h == section), None)
        if index is None:  # a new authored section, adjacent to the future facts
            kept.append((section, [f"## {section}", "", *lines, ""]))
        else:  # the page already authored this section: extend it in place
            heading, existing = kept[index]
            kept[index] = (heading, [*existing, *lines])
    front = f"---\n{match.group(1)}\n---\n\n" if match else ""
    return f"{front}{_assemble_body(kept)}\n"


def enrich_legacy(
    *,
    project: str | Path,
    proposal: str,
    revision: str,
    page: str,
    asset: dict | None = None,
) -> dict:
    """HUMAN-ONLY (the ``ariadne-authoring enrich-legacy`` adapter, issue #46
    / K6; spec 0010 §4/§9 + §10 AC2/AC10): bind ONE imported legacy
    physical-table page to its EXPLICITLY identified canonical resource
    through a complete page edit, so the explicit :func:`refresh_schema` can
    regenerate the core-owned schema facts in it (plan §2: "explicit
    enrichment can bind an existing page to an unambiguous asset while
    retaining its filename and links").

    The binding resolves ONLY against the operator-approved resolved source
    identity (the G3 seam): with ``asset`` the request names the exact tuple;
    without it the page's own legacy spelling (its non-canonical top-level
    ``resource`` or its ``sources`` citation resources) must resolve to
    EXACTLY ONE approved asset — zero matches and, above all, SEVERAL matches
    (same-named tables of distinct sources/schemas) are explicit refusals,
    never guesses. The old filename, links, citations, authored meaning and
    promotion-stamped history are preserved byte-for-byte in their parsed
    meaning; nothing is renamed, deleted or reclassified; the page keeps its
    legacy date-only freshness fields. Authored text the page carries under the
    headings its bound refresh will own (``Schema``/``Observations``) is
    re-homed, never discarded: column-explanation bullets into ``Column
    meanings`` (the K1 preservation path) and the remaining prose into the
    clearly labeled ``Authored notes`` block. The enrichment never refreshes,
    validates, reviews or admits anything — those stay their own explicit
    steps."""
    project = Path(project).resolve()
    parts = PurePosixPath(page).parts if isinstance(page, str) else ()
    if (
        len(parts) != 3
        or parts[:2] != ("context_layer", "tables")
        or PurePosixPath(page).suffix != ".md"
    ):
        raise ValueError(
            f"{page!r}: only a legacy physical-table page under context_layer/tables/ "
            "can be enriched — enriching any other page would silently reclassify it; "
            "bind a Dataset Overview or a Reference through its own page edit instead"
        )
    proposals.refuse_generated(page)
    proposals.check_artifact_name(PurePosixPath(page).stem, what="the legacy table page")
    record = proposals._load_record(project, proposal)
    current = record["candidate_revision"]
    if revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the "
            f"enrichment expected {revision} — re-read the candidate and retry with "
            "the current revision; nothing was written"
        )
    blob = proposals._read_blob(project, current, page)
    if blob is None:
        raise ValueError(
            f"{page} is not part of the candidate revision {current[:12]} of proposal "
            f"{proposal} — name a page the imported candidate actually carries"
        )
    text = blob.decode("utf-8")
    try:
        meta = _load_frontmatter_meta(text)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"{page}: the frontmatter is not valid YAML ({exc}) — this needs human "
            "resolution before any enrichment"
        ) from None
    meta = meta if isinstance(meta, dict) else {}
    existing_resource = meta.get("resource")
    if isinstance(existing_resource, str) and existing_resource.startswith("ariadne://"):
        try:
            _kind, _payload = parse_resource(existing_resource)
        except ValueError:
            pass  # a malformed claim: still bound-shaped, still not this seam's to rewrite
        else:
            raise ValueError(
                f"{page} is already bound to the canonical resource "
                f"{existing_resource!r} — the enrichment binds legacy pages once; "
                "a rebind is a reviewed human page edit, never this seam, and "
                "refresh_schema owns the generated facts of a bound page"
            )

    resolved, digest = candidate_sources(project, current)
    if resolved is None:
        raise ValueError(
            f"proposal {proposal} declares no source entries in its candidate "
            f"registry at {current[:12]} — there is no approved identity to bind to"
        )
    approval = authoring_sources._approved_identity(project, digest, proposal, current)
    owned = execution.DuckDBExecution(
        authoring_sources.identity_registry(approval["sources"])
    )
    try:
        catalog = owned.catalog
    finally:
        owned.close()
    tables = [table for entry in catalog for table in entry["tables"]]
    available = ", ".join(
        sorted(f"{t['source']}.{t.get('schema')}.{t['name']}" for t in tables)
    )

    if asset is not None:
        requested = authoring._catalog_asset(asset)
        matching = [
            table
            for table in tables
            if _asset_of(table)
            == {
                "source": requested["source"],
                "catalog": requested["catalog"],
                "schema": requested["schema"],
                "table": requested["table"],
            }
        ]
        if not matching:
            raise ValueError(
                f"catalog asset {requested} is not present in the approved resolved "
                f"source identity — available assets: {available or 'none'}; nothing "
                "was written"
            )
        target = matching[0]
        bound_from = None
    else:
        spellings: list[str] = []
        if isinstance(existing_resource, str) and existing_resource:
            spellings.append(existing_resource)
        for citation in meta.get("sources") or []:
            if isinstance(citation, dict) and isinstance(citation.get("resource"), str):
                spellings.append(citation["resource"])
        matched: dict[tuple, dict] = {}
        for spelling in spellings:
            hits = _spelling_matches(spelling, catalog)
            if len(hits) > 1:
                names = ", ".join(
                    f"{hit['source']}.{hit.get('schema')}.{hit['name']}" for hit in hits
                )
                raise ValueError(
                    f"the legacy resource spelling {spelling!r} of {page} is ambiguous: "
                    f"it matches {len(hits)} approved catalog assets ({names}) — the "
                    "enrichment never guesses a source/table binding; name the exact "
                    'asset with --file {"source": ..., "catalog": ..., "schema": ..., '
                    '"table": ...} and retry'
                )
            if hits:
                hit = hits[0]
                matched[(hit["source"], hit.get("catalog"), hit.get("schema"), hit["name"])] = hit
        if not matched:
            raise ValueError(
                f"no approved catalog asset matches the legacy spelling(s) of {page} "
                f"({', '.join(repr(s) for s in spellings) or 'none'}) — available "
                f"assets: {available or 'none'}; name the exact asset with --file "
                '{"source": ..., "catalog": ..., "schema": ..., "table": ...}'
                "and retry; nothing was written"
            )
        if len(matched) > 1:
            names = ", ".join(
                f"{t['source']}.{t.get('schema')}.{t['name']}" for t in matched.values()
            )
            raise ValueError(
                f"{page} names {len(matched)} distinct approved catalog assets ({names}) "
                "— the enrichment never guesses a source/table binding; name the exact "
                'asset with --file {"source": ..., "catalog": ..., "schema": ..., '
                '"table": ...} and retry'
            )
        target = next(iter(matched.values()))
        bound_from = next(
            spelling
            for spelling in spellings
            if any(
                (hit["source"], hit.get("catalog"), hit.get("schema"), hit["name"])
                == (
                    target["source"],
                    target.get("catalog"),
                    target.get("schema"),
                    target["name"],
                )
                for hit in _spelling_matches(spelling, catalog)
            )
        )

    resource = target["resource"]
    existing_pages, _tracked = authoring._resource_pages(project, current)
    other = existing_pages.get(resource)
    if other is not None:
        raise ValueError(
            f"the candidate already carries {other['path']} bound to {resource!r} — "
            "two pages for one asset need human resolution; the enrichment never "
            "overwrites another page's binding"
        )
    new_text = _set_frontmatter_key(_rehome_legacy_authored(text), "resource", resource)
    try:
        new_meta = _load_frontmatter_meta(new_text)
    except yaml.YAMLError as exc:  # pragma: no cover - a parseable page round-trips
        raise ValueError(
            f"{page}: the enriched frontmatter is not valid YAML ({exc}) — refusing "
            "to write anything"
        ) from None
    new_meta = new_meta if isinstance(new_meta, dict) else {}
    if {k: v for k, v in meta.items() if k != "resource"} != {
        k: v for k, v in new_meta.items() if k != "resource"
    }:
        raise ValueError(  # pragma: no cover - the seam changes exactly one key
            f"{page}: the enrichment may only bind the canonical resource — any "
            "other change is refused; nothing was written"
        )
    out = proposals.edit_proposal(
        project, proposal, current, page, new_text, core_generated=True
    )
    return {
        "project": str(project),
        "proposal": proposal,
        "page": page,
        "revision": out["revision"],
        "changed": out["changed"],
        "resource": resource,
        "asset": _asset_of(target),
        "bound_from": bound_from,
        "staging_untouched": True,
        "admitted": False,
        "next_steps": [
            "ariadne-authoring refresh-schema --project "
            f"{project} --proposal {proposal} --expected-revision {out['revision']} "
            '--file <asset list json> to generate the schema facts of the bound asset',
            "ariadne-authoring validate, review and ariadne-admit --confirm remain the "
            "normal human admission steps",
        ],
        "note": (
            "the enrichment binds one legacy page to its canonical resource — it is "
            "never refresh, validation, review or admission (spec 0010 §9): the old "
            "filename, links and history are preserved, authored explanations under "
            "the refresh-owned Schema/Observations headings are re-homed into Column "
            "meanings and Authored notes (never discarded), and the page stays "
            "unadmitted"
        ),
    }

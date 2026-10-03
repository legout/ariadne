"""Context-layer and Seed Notes artifact edits for Git authoring proposals
(issue #34/G2; spec 2026-10-02-0009 §3, plan §2 "Authoring call contract").

The layer-specific half of the discriminated edit contract for OKF pages and
the Seed Notes: one complete ``page`` addressed by its documented section and
name, or the complete ``seed_notes`` document. Sections and names are validated
and converted into allowed artifact paths HERE — one central resolver, no
arbitrary path field, no generated-page edit (``index.md``/``log.md``/
computations are system-owned, ADR-0007/ADR-0013), no deletion or rename, no
per-metric mutation (spec §3). Content may be an incomplete or invalid draft:
the per-type frontmatter gate belongs to a later validation slice, not to the
edit seam.
"""

from __future__ import annotations

from ariadne.proposals import (
    check_artifact_content,
    check_artifact_name,
    check_edit_keys,
    refuse_generated,
)

_EDIT_KEYS = {
    "page": frozenset({"kind", "section", "name", "content"}),
    "seed_notes": frozenset({"kind", "content"}),
}
_IDENTITY_KEYS = {
    "page": frozenset({"kind", "section", "name"}),
    "seed_notes": frozenset({"kind"}),
}


def _check_section(section: object) -> str:
    if section == "computations":
        raise ValueError(
            "context_layer/computations/ pages are system-generated (attestation is "
            "service-owned, ADR-0007/ADR-0013) — they are never user-editable in a "
            "proposal"
        )
    if section not in ("datasets", "tables", "references", "policies", "metrics", "skills"):
        raise ValueError(
            f"unknown page section {section!r}: OKF pages live under context_layer/"
            "{datasets,tables,references,policies,metrics,skills}/ — computations, "
            "index.md and log.md are system-owned"
        )
    return str(section)


def _relpath(identity: dict) -> str:
    """The allowed artifact path of one page/seed-notes edit/identity."""
    kind = identity.get("kind")
    if kind == "page":
        section = _check_section(identity.get("section"))
        name = check_artifact_name(identity.get("name"), what="page name")
        folder = "references/joins" if section == "references" else section
        return f"context_layer/{folder}/{name}.md"
    if kind == "seed_notes":
        return "data/seed_notes.md"
    raise ValueError(
        f"unknown context-layer edit kind {kind!r}: use "
        "{{kind: 'page', section, name, content}} or {{kind: 'seed_notes', content}}"
    )


def resolve_edit(edit: dict) -> tuple[str, str]:
    """Validate one discriminated page/seed-notes edit and return its allowed
    artifact path plus the content to commit."""
    if not isinstance(edit, dict) or edit.get("kind") not in _EDIT_KEYS:
        got = edit.get("kind") if isinstance(edit, dict) else edit
        raise ValueError(
            "a context-layer edit is a discriminated object with kind 'page' or "
            f"'seed_notes', got kind {got!r}"
        )
    check_edit_keys(edit, _EDIT_KEYS[edit["kind"]])
    rel = _relpath(edit)
    refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    return rel, edit["content"]


def resolve_identity(identity: dict) -> str:
    """The allowed artifact path of one typed page/seed-notes read identity."""
    if not isinstance(identity, dict) or identity.get("kind") not in _IDENTITY_KEYS:
        got = identity.get("kind") if isinstance(identity, dict) else identity
        raise ValueError(
            "a context-layer artifact identity is a typed object with kind 'page' or "
            f"'seed_notes', got kind {got!r}"
        )
    check_edit_keys(identity, _IDENTITY_KEYS[identity["kind"]])
    return _relpath(identity)

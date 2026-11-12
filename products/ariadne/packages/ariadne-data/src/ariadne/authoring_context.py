"""Seed Notes artifact edits for Git authoring proposals (issue #34/G2).

C6 (spec0035 §6): the context-layer ``page`` edit kind is retired — Context
pages are native ``knowledge/`` Lumio pages authored as complete
``{path, content}`` objects through the public native page batch
(``edit_pages_batch``), never through the retired ``context_layer/...``
artifact resolver. This module keeps ONLY the live Seed Notes resolution:
one complete ``seed_notes`` document addressed as ``data/seed_notes.md``,
validated and converted into its allowed artifact path HERE — one central
resolver, no arbitrary path field, no deletion or rename. Content may be an
incomplete or invalid draft: the per-type gate belongs to validation, not to
the edit seam.
"""

from __future__ import annotations

from ariadne.proposals import (
    check_artifact_content,
    check_edit_keys,
    refuse_generated,
)

_PAGES_GUIDANCE = (
    "the context-layer page edit kind is retired (spec0035 §6): Context pages "
    "are native knowledge/ Lumio pages — author them as complete {path, "
    "content} objects through the native page batch (edit_pages_batch), not "
    "as {kind: 'page', section, name} artifact edits; nothing was written"
)

_EDIT_KEYS = {
    "page": frozenset({"kind", "section", "name", "content"}),
    "seed_notes": frozenset({"kind", "content"}),
}
_IDENTITY_KEYS = {
    "page": frozenset({"kind", "section", "name"}),
    "seed_notes": frozenset({"kind"}),
}

SEED_NOTES_REL = "data/seed_notes.md"


def _relpath(identity: dict) -> str:
    """The allowed artifact path of one seed-notes edit/identity, or the
    retired-kind guidance refusal for a context-layer ``page``."""
    kind = identity.get("kind")
    if kind == "page":
        raise ValueError(_PAGES_GUIDANCE)
    if kind == "seed_notes":
        return SEED_NOTES_REL
    raise ValueError(
        f"unknown context-layer edit kind {kind!r}: use "
        "{{kind: 'page', section, name, content}} or {{kind: 'seed_notes', content}}"
    )


def resolve_edit(edit: dict) -> tuple[str, str]:
    """Validate one discriminated seed-notes edit and return its allowed
    artifact path plus the content to commit; a retired context-layer
    ``page`` edit refuses with the supported-native-page guidance."""
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
    """The allowed artifact path of one typed seed-notes read identity; a
    retired context-layer ``page`` identity refuses with the guidance."""
    if not isinstance(identity, dict) or identity.get("kind") not in _IDENTITY_KEYS:
        got = identity.get("kind") if isinstance(identity, dict) else identity
        raise ValueError(
            "a context-layer artifact identity is a typed object with kind 'page' or "
            f"'seed_notes', got kind {got!r}"
        )
    check_edit_keys(identity, _IDENTITY_KEYS[identity["kind"]])
    return _relpath(identity)

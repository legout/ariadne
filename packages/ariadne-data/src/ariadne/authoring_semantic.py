"""Semantic-layer artifact edits for Git authoring proposals (issue #34/G2;
spec 2026-10-02-0009 §3, plan §2 "Authoring call contract").

The layer-specific half of the discriminated edit contract for
``semantic_layer`` artifacts: a complete OSI ``model`` (named, so one model can
be replaced without resending the bundle) or the cross-file ``graph``. Names
are validated and converted into allowed artifact paths HERE — one central
resolver, no arbitrary path field, no per-metric mutation, no deletion or
rename (spec §3). Content may be an incomplete or invalid draft: artifact
validation is a later gate; only identity, payload bounds, credentials and the
system-owned-artifact boundary apply now. Model/graph YAML is normalized to
readable block scalars by the shared authoring normalizer
(:func:`ariadne.author.normalize_layer_yaml`, issue #31) so the human reviews
the same readable form at the Git gate.
"""

from __future__ import annotations

from ariadne.author import normalize_layer_yaml
from ariadne.proposals import (
    check_artifact_content,
    check_artifact_name,
    check_edit_keys,
    refuse_generated,
)

_EDIT_KEYS = {
    "model": frozenset({"kind", "name", "content"}),
    "graph": frozenset({"kind", "content"}),
}
_IDENTITY_KEYS = {"model": frozenset({"kind", "name"}), "graph": frozenset({"kind"})}


def _relpath(edit: dict) -> str:
    """The allowed artifact path of one semantic-layer edit/identity."""
    kind = edit.get("kind")
    if kind == "model":
        name = check_artifact_name(edit.get("name"), what="model name")
        return f"semantic_layer/models/{name}.yml"
    if kind == "graph":
        return "semantic_layer/graph.yml"
    raise ValueError(
        f"unknown semantic-layer edit kind {kind!r}: use "
        "{{kind: 'model', name, content}} or {{kind: 'graph', content}}"
    )


def resolve_edit(edit: dict) -> tuple[str, str]:
    """Validate one discriminated semantic-layer edit and return its allowed
    artifact path plus the (normalized) content to commit."""
    if not isinstance(edit, dict) or edit.get("kind") not in _EDIT_KEYS:
        got = edit.get("kind") if isinstance(edit, dict) else edit
        raise ValueError(
            "a semantic-layer edit is a discriminated object with kind 'model' or "
            f"'graph', got kind {got!r}"
        )
    check_edit_keys(edit, _EDIT_KEYS[edit["kind"]])
    rel = _relpath(edit)
    refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    # Readable block scalars for multi-line sources; non-YAML drafts pass
    # through unchanged.
    return rel, normalize_layer_yaml(edit["content"])


def resolve_identity(identity: dict) -> str:
    """The allowed artifact path of one typed semantic-layer read identity."""
    if not isinstance(identity, dict) or identity.get("kind") not in _IDENTITY_KEYS:
        got = identity.get("kind") if isinstance(identity, dict) else identity
        raise ValueError(
            "a semantic-layer artifact identity is a typed object with kind 'model' "
            f"or 'graph', got kind {got!r}"
        )
    check_edit_keys(identity, _IDENTITY_KEYS[identity["kind"]])
    return _relpath(identity)

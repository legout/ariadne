"""Typed artifact resolvers for Git authoring proposals: the semantic layer
(``model``/``graph``), Seed Notes, and contract documents with the fixed native
binding file. Each discriminated identity or edit is validated BEFORE any Git
dispatch and mapped to one allowed candidate path; there is no arbitrary path
field, no deletion or rename. Content may be an incomplete draft: only identity,
payload bounds, credentials and the system-owned-artifact boundary apply here.
"""

from __future__ import annotations

import yaml

from ariadne import proposals
from ariadne.proposals import (
    check_artifact_content,
    check_artifact_name,
    check_edit_keys,
    refuse_generated,
)

_SEMANTIC_EDIT_KEYS = {
    "model": frozenset({"kind", "name", "content"}),
    "graph": frozenset({"kind", "content"}),
}
_SEMANTIC_IDENTITY_KEYS = {"model": frozenset({"kind", "name"}), "graph": frozenset({"kind"})}


def _semantic_relpath(edit: dict) -> str:
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


def _resolve_semantic_edit(edit: dict) -> tuple[str, str]:
    """Validate one discriminated semantic-layer edit and return its allowed
    artifact path plus the (normalized) content to commit."""
    if not isinstance(edit, dict) or edit.get("kind") not in _SEMANTIC_EDIT_KEYS:
        got = edit.get("kind") if isinstance(edit, dict) else edit
        raise ValueError(
            "a semantic-layer edit is a discriminated object with kind 'model' or "
            f"'graph', got kind {got!r}"
        )
    check_edit_keys(edit, _SEMANTIC_EDIT_KEYS[edit["kind"]])
    rel = _semantic_relpath(edit)
    refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    # Readable block scalars for multi-line sources; non-YAML drafts pass
    # through unchanged.
    return rel, normalize_layer_yaml(edit["content"])


def _resolve_semantic_identity(identity: dict) -> str:
    """The allowed artifact path of one typed semantic-layer read identity."""
    if not isinstance(identity, dict) or identity.get("kind") not in _SEMANTIC_IDENTITY_KEYS:
        got = identity.get("kind") if isinstance(identity, dict) else identity
        raise ValueError(
            "a semantic-layer artifact identity is a typed object with kind 'model' "
            f"or 'graph', got kind {got!r}"
        )
    check_edit_keys(identity, _SEMANTIC_IDENTITY_KEYS[identity["kind"]])
    return _semantic_relpath(identity)


_PAGES_GUIDANCE = (
    "the context-layer page edit kind is retired (spec0035 §6): Context pages "
    "are native knowledge/ Lumio pages — author them as complete {path, "
    "content} objects through the native page batch (edit_pages_batch), not "
    "as {kind: 'page', section, name} artifact edits; nothing was written"
)

_SEED_EDIT_KEYS = {
    "page": frozenset({"kind", "section", "name", "content"}),
    "seed_notes": frozenset({"kind", "content"}),
}
_SEED_IDENTITY_KEYS = {
    "page": frozenset({"kind", "section", "name"}),
    "seed_notes": frozenset({"kind"}),
}

SEED_NOTES_REL = "data/seed_notes.md"


def _seed_relpath(identity: dict) -> str:
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


def _resolve_seed_edit(edit: dict) -> tuple[str, str]:
    """Validate one discriminated seed-notes edit and return its allowed
    artifact path plus the content to commit; a retired context-layer
    ``page`` edit refuses with the supported-native-page guidance."""
    if not isinstance(edit, dict) or edit.get("kind") not in _SEED_EDIT_KEYS:
        got = edit.get("kind") if isinstance(edit, dict) else edit
        raise ValueError(
            "a context-layer edit is a discriminated object with kind 'page' or "
            f"'seed_notes', got kind {got!r}"
        )
    check_edit_keys(edit, _SEED_EDIT_KEYS[edit["kind"]])
    rel = _seed_relpath(edit)
    refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    return rel, edit["content"]


def _resolve_seed_identity(identity: dict) -> str:
    """The allowed artifact path of one typed seed-notes read identity; a
    retired context-layer ``page`` identity refuses with the guidance."""
    if not isinstance(identity, dict) or identity.get("kind") not in _SEED_IDENTITY_KEYS:
        got = identity.get("kind") if isinstance(identity, dict) else identity
        raise ValueError(
            "a context-layer artifact identity is a typed object with kind 'page' or "
            f"'seed_notes', got kind {got!r}"
        )
    check_edit_keys(identity, _SEED_IDENTITY_KEYS[identity["kind"]])
    return _seed_relpath(identity)


CONTRACTS_REL = "contracts"
CONTRACT_BINDINGS_REL = "contract_bindings.yaml"

CONTRACT_KIND = "contract"
CONTRACT_BINDINGS_KIND = "contract_bindings"

_CONTRACT_IDENTITY_KEYS = {
    CONTRACT_KIND: frozenset({"kind", "name"}),
    CONTRACT_BINDINGS_KIND: frozenset({"kind"}),
}
_CONTRACT_EDIT_KEYS = {
    CONTRACT_KIND: frozenset({"kind", "name", "content"}),
    CONTRACT_BINDINGS_KIND: frozenset({"kind", "content"}),
}


def _contract_kind(payload: object) -> str | None:
    if not isinstance(payload, dict) or payload.get("kind") not in _CONTRACT_IDENTITY_KEYS:
        got = payload.get("kind") if isinstance(payload, dict) else payload
        raise ValueError(
            "a contract artifact identity is a typed object with kind 'contract' or "
            f"'contract_bindings', got {got!r}"
        )
    return payload["kind"]


def _contract_relpath(payload: dict, *, project=None, proposal=None) -> str:
    kind = _contract_kind(payload)
    if kind == CONTRACT_BINDINGS_KIND:
        return CONTRACT_BINDINGS_REL
    name = check_artifact_name(payload["name"], what="contract document name")
    explicit = name.endswith((".yaml", ".yml"))
    stem = name.rsplit(".", 1)[0] if explicit else name
    check_artifact_name(stem, what="contract document stem")
    candidates = [f"{CONTRACTS_REL}/{stem}{suffix}" for suffix in (".yaml", ".yml")]
    existing = set()
    if project is not None and proposal is not None:
        record = proposals._load_record(project, proposal)
        existing = {
            rel for rel, _blob in proposals.scope_blobs(project, record["candidate_revision"])
        }
    matches = [rel for rel in candidates if rel in existing]
    if not explicit and len(matches) > 1:
        raise ValueError("ambiguous contract name: select the exact .yaml or .yml filename")
    selected = f"{CONTRACTS_REL}/{name}" if explicit else (matches[0] if matches else candidates[0])
    if selected not in existing and matches:
        raise ValueError("contract extension collision: edit the existing exact filename")
    return selected


def _resolve_contract_identity(identity: dict, *, project=None, proposal=None) -> str:
    """The allowed artifact path of one typed contract read identity."""
    _contract_kind(identity)
    check_edit_keys(identity, _CONTRACT_IDENTITY_KEYS[identity["kind"]])
    return _contract_relpath(identity, project=project, proposal=proposal)


def _resolve_contract_edit(edit: dict, *, project=None, proposal=None) -> tuple[str, str]:
    """Validate one discriminated contract/bindings edit and return its
    allowed artifact path plus the content to commit. The producer's exact
    submitted text is preserved — no normalization is applied here."""
    _contract_kind(edit)
    check_edit_keys(edit, _CONTRACT_EDIT_KEYS[edit["kind"]])
    rel = _contract_relpath(edit, project=project, proposal=proposal)
    proposals.refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    return rel, edit["content"]


class _LayerDumper(yaml.SafeDumper):  # type: ignore[no-any-unimported]
    """Use readable literal blocks for multiline strings."""


def _block_str_representer(dumper: _LayerDumper, data: str):  # type: ignore[no-any-unimported]
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LayerDumper.add_representer(str, _block_str_representer)


def normalize_layer_yaml(content: str) -> str:
    """Re-emit mapping YAML with multiline SQL as reviewable literal blocks."""
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(doc, dict):
        return content
    return yaml.dump(
        doc,
        Dumper=_LayerDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )


_FAMILIES = {
    "model": (_resolve_semantic_identity, _resolve_semantic_edit),
    "graph": (_resolve_semantic_identity, _resolve_semantic_edit),
    "page": (_resolve_seed_identity, _resolve_seed_edit),
    "seed_notes": (_resolve_seed_identity, _resolve_seed_edit),
    "contract": (_resolve_contract_identity, _resolve_contract_edit),
    "contract_bindings": (_resolve_contract_identity, _resolve_contract_edit),
}
EDIT_KINDS = tuple(sorted(_FAMILIES))


def resolve_identity(identity: dict, *, project, proposal) -> str:
    """The allowed artifact path of one typed read identity (kind in ``EDIT_KINDS``)."""
    resolve = _FAMILIES[identity["kind"]][0]
    if identity["kind"] == "contract":
        return resolve(identity, project=project, proposal=proposal)
    return resolve(identity)


def resolve_edit(edit: dict, *, project, proposal) -> tuple[str, str]:
    """The allowed artifact path plus the content to commit for one discriminated edit."""
    resolve = _FAMILIES[edit["kind"]][1]
    if edit["kind"] == "contract":
        return resolve(edit, project=project, proposal=proposal)
    return resolve(edit)

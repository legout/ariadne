"""The narrow typed artifact resolver for contract documents and the fixed
native binding file (spec 2028 §3, issue #77/C1).

Contract artifacts enter the existing revision-checked mutation seam exactly
like the other authored kinds: a discriminated identity/edit validated BEFORE
any Git dispatch, mapped to one allowed candidate path. There is no arbitrary
path editor here — names are plain artifact filenames under ``contracts/``,
the binding document is one fixed file, and the shared content boundary
(payload bounds, credential classes) applies unchanged.
"""

from __future__ import annotations

from ariadne import proposals
from ariadne.proposals import check_artifact_content, check_artifact_name, check_edit_keys

CONTRACTS_REL = "contracts"
CONTRACT_SUFFIX = ".yaml"
CONTRACT_BINDINGS_REL = "contract_bindings.yaml"

CONTRACT_KIND = "contract"
CONTRACT_BINDINGS_KIND = "contract_bindings"

_IDENTITY_KEYS = {
    CONTRACT_KIND: frozenset({"kind", "name"}),
    CONTRACT_BINDINGS_KIND: frozenset({"kind"}),
}
_EDIT_KEYS = {
    CONTRACT_KIND: frozenset({"kind", "name", "content"}),
    CONTRACT_BINDINGS_KIND: frozenset({"kind", "content"}),
}


def _kind(payload: object) -> str | None:
    if not isinstance(payload, dict) or payload.get("kind") not in _IDENTITY_KEYS:
        got = payload.get("kind") if isinstance(payload, dict) else payload
        raise ValueError(
            "a contract artifact identity is a typed object with kind 'contract' or "
            f"'contract_bindings', got {got!r}"
        )
    return payload["kind"]


def _relpath(payload: dict) -> str:
    kind = _kind(payload)
    if kind == CONTRACT_BINDINGS_KIND:
        return CONTRACT_BINDINGS_REL
    name = check_artifact_name(payload["name"], what="contract document name")
    return f"{CONTRACTS_REL}/{name}{CONTRACT_SUFFIX}"


def resolve_identity(identity: dict) -> str:
    """The allowed artifact path of one typed contract read identity."""
    _kind(identity)
    check_edit_keys(identity, _IDENTITY_KEYS[identity["kind"]])
    return _relpath(identity)


def resolve_edit(edit: dict) -> tuple[str, str]:
    """Validate one discriminated contract/bindings edit and return its
    allowed artifact path plus the content to commit. The producer's exact
    submitted text is preserved — no normalization is applied here."""
    _kind(edit)
    check_edit_keys(edit, _EDIT_KEYS[edit["kind"]])
    rel = _relpath(edit)
    proposals.refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    return rel, edit["content"]

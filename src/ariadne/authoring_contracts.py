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


def _relpath(payload: dict, *, project=None, proposal=None) -> str:
    kind = _kind(payload)
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


def resolve_identity(identity: dict, *, project=None, proposal=None) -> str:
    """The allowed artifact path of one typed contract read identity."""
    _kind(identity)
    check_edit_keys(identity, _IDENTITY_KEYS[identity["kind"]])
    return _relpath(identity, project=project, proposal=proposal)


def resolve_edit(edit: dict, *, project=None, proposal=None) -> tuple[str, str]:
    """Validate one discriminated contract/bindings edit and return its
    allowed artifact path plus the content to commit. The producer's exact
    submitted text is preserved — no normalization is applied here."""
    _kind(edit)
    check_edit_keys(edit, _EDIT_KEYS[edit["kind"]])
    rel = _relpath(edit, project=project, proposal=proposal)
    proposals.refuse_generated(rel)
    check_artifact_content(f"edit {rel!r}", edit["content"])
    return rel, edit["content"]

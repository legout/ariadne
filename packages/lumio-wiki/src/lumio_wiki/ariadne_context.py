"""The Ariadne Context Profile and immutable scoped SDK view (spec 0009).

An explicitly versioned ``ariadne-context/1`` application profile over native
Lumio content, plus the additive producer SDK for it. The envelope lives in
Compiled Page frontmatter under ``ariadne_profile``; its ``native`` slot
retains the supported Ariadne OKF metadata families losslessly. This module
is model-free, adds no dependency, and never imports Ariadne: the supported
schema below is frozen from the approved Ariadne source contracts
(specs 0010/0011/0024 at the pinned source commit recorded in spec 0009).

Support boundary (v1, frozen with this module's first committed result):

- Envelope: exact integer ``version: 1``, one of the seven native kinds,
  ``native`` metadata, typed ``required_policies`` edges (mandatory — even
  when empty — on metric and policy pages), ``metric_ref`` (required on
  metric pages), ``core_ref`` (required on dataset/table/computation pages)
  and ``ontology_refs``. Unknown envelope fields refuse.
- Native families: page/resource identity (``type``, ``title``,
  ``description``, ``tags``, ``aliases``, ``resource``), structured
  provenance (``sources``, ``verified``, ``generated``), lifecycle and
  freshness (``status``, ``stale_after``), Computation attestation
  (``attestation``, ``attester``, ``runtime``, ``governed_by``,
  ``dimensions``, ``grain``) and the versioned Reference/identifier
  extension (``ariadne``) with its core-attached ``ariadne_evidence``
  receipt summaries. Unknown native fields refuse by name. Binding
  resources are validated as exact non-empty catalog identity strings;
  deep Ariadne URI canonicalization stays consumer-side.
- Temporal values keep their YAML-native published source (date, datetime or
  the exact original string); SDK disclosure uses the native ISO-8601 JSON
  representation contract and never invents freshness.

The SDK surfaces are additive: candidate inspection of one exact captured
(unadmitted) Authoring Revision, and opening of one exact immutable
Published Version with its full expected Context Identity and effective
Visibility Scope. Nothing here executes payload content, reads a latest
pointer as fallback, or grants source/publication/database permission.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import date
from typing import Any

import msgspec

from lumio_wiki.records import (
    AriadneCoreReference,
    AriadneMetricReference,
    AriadneOntologyReference,
    AriadnePolicyReference,
    AriadneProfile,
    CompiledPage,
    Source,
)

#: The one supported envelope version (no coercion, no latest dispatch).
ARIADNE_PROFILE_VERSION = 1

#: The one supported version of the native ``ariadne`` Reference extension
#: (frozen from the Ariadne source contract; distinct from the envelope).
ARIADNE_EXTENSION_VERSION = 1

#: The supported profile kinds (native OKF page types; application metadata,
#: not a Lumio ontology type).
ARIADNE_PROFILE_KINDS = frozenset(
    {"dataset", "table", "reference", "policy", "metric", "computation", "skill"}
)

#: Kinds whose pages MUST declare ``required_policies`` (even when empty).
KINDS_REQUIRING_REQUIRED_POLICIES = frozenset({"metric", "policy"})
#: Kinds whose pages MUST declare ``metric_ref``.
KINDS_REQUIRING_METRIC_REF = frozenset({"metric"})
#: Kinds whose pages MUST declare ``core_ref``.
KINDS_REQUIRING_CORE_REF = frozenset({"dataset", "table", "computation"})

_ENVELOPE_KEYS = frozenset(
    {
        "version",
        "kind",
        "native",
        "required_policies",
        "metric_ref",
        "core_ref",
        "ontology_refs",
    }
)

# -- The frozen supported native families (Ariadne specs 0010/0011/0024). ---

NATIVE_TYPES = frozenset(
    {"dataset", "table", "reference", "policy", "metric", "computation", "skill"}
)
REFERENCE_ROLES = ("term", "identifier", "enum", "join")
MAPPING_FAMILIES = ("equality", "prefix", "lookup")
MAPPING_CLAIMS = ("hypothesis", "asserted")

NATIVE_KEYS = frozenset(
    {
        "type",
        "title",
        "description",
        "tags",
        "sources",
        "aliases",
        "resource",
        "status",
        "stale_after",
        "generated",
        "verified",
        "attestation",
        "attester",
        "runtime",
        "governed_by",
        "dimensions",
        "grain",
        "ariadne",
        "ariadne_evidence",
    }
)
NATIVE_SOURCE_KEYS = frozenset({"id", "title", "url", "resource"})
_EXTENSION_KEYS = frozenset({"version", "reference_role", "representations", "mappings"})
_REPRESENTATION_KEYS = frozenset({"id", "aliases", "fields", "scope", "description"})
_MAPPING_KEYS = frozenset(
    {"id", "family", "from", "to", "claim", "source_ids", "receipt_ids", "candidate"}
)
_EVIDENCE_SUMMARY_KEYS = frozenset(
    {
        "id",
        "digest",
        "family",
        "outcome",
        "designation",
        "comparison_basis",
        "tested_left",
        "tested_right",
        "eligible_left",
        "eligible_right",
        "matched_left_in_right",
        "matched_right_in_left",
        "mismatch_count",
        "observed_at",
    }
)
_EVIDENCE_STRING_KEYS = frozenset(
    {"id", "digest", "family", "outcome", "designation", "comparison_basis", "observed_at"}
)

_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

#: The default operator-authorized Visibility Scope (spec 0009 §4).
PUBLIC_VISIBILITY_SCOPE = ("public",)


# ---------------------------------------------------------------------------
# Refusals. Reader-safe diagnostics distinguish the contract's refusal
# classes; none of them ever discloses hidden titles, text or topology.
# ---------------------------------------------------------------------------


class AriadneContextError(Exception):
    """Base class of every Ariadne Context Profile refusal."""


class UnsupportedProfileError(AriadneContextError):
    """An unsupported profile version or native variant was requested."""


class MalformedProfileError(AriadneContextError):
    """A supported structure is malformed, or the candidate is invalid."""


class UnresolvedReferenceError(AriadneContextError):
    """A typed reference does not resolve in the selected scope."""


class SnapshotUnavailableError(AriadneContextError):
    """The pinned Published Version is absent, corrupt or unreadable."""


class IdentityMismatchError(AriadneContextError):
    """The opened version does not match the expected Context Identity."""


class OutOfScopeDependencyError(AriadneContextError):
    """A required Policy Closure dependency is outside the effective scope."""


class UnadmittedInputError(AriadneContextError):
    """The input is not an admitted, exact, immutable-pinned publication."""


class AriadneProfileDiagnostic(msgspec.Struct, frozen=True):
    """One structural/dependency diagnostic with a safe category label."""

    category: str
    """``unsupported``, ``malformed``, ``duplicate-binding``,
    ``unresolved-reference`` or ``out-of-scope``."""

    message: str


# ---------------------------------------------------------------------------
# Envelope parsing and the frozen native-schema validation (pure).
# ---------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list_errors(where: str, value: object) -> list[str]:
    if not isinstance(value, list) or not all(_non_empty_str(item) for item in value):
        return [f"{where} must be a list of non-empty strings"]
    return []


def _json_shaped(value: object) -> bool:
    """Whether a native value stays representable in the native JSON contract."""
    if value is None or isinstance(value, (str, int, float, date)):  # bool ⊂ int
        return True
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_shaped(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_json_shaped(item) for item in value)
    return False


def _binding_list_errors(where: str, bindings: object) -> list[str]:
    """Ordered ``{resource, column}`` bindings with exact identities."""
    if not isinstance(bindings, list):
        return [f"{where} must be an ordered list of {{resource, column}} bindings"]
    errors: list[str] = []
    for index, binding in enumerate(bindings):
        spot = f"{where}[{index}]"
        if not isinstance(binding, dict) or set(binding) != {"resource", "column"}:
            errors.append(f"{spot} must be exactly {{resource, column}}")
            continue
        if not _non_empty_str(binding["resource"]):
            errors.append(f"{spot} resource must be an exact non-empty catalog identity")
        if not _non_empty_str(binding["column"]):
            errors.append(f"{spot} column must be a non-empty exact identifier")
    return errors


def _extension_errors(where: str, extension: object, footnote_ids: frozenset[str]) -> list[str]:
    """The version-1 ``ariadne`` Reference extension contract (spec 0010 §5)."""
    if extension is None:
        return [f"{where} is null — null is not a supported extension form"]
    if not isinstance(extension, dict):
        return [f"{where} must be a mapping, got {type(extension).__name__}"]
    errors: list[str] = []
    version = extension.get("version")
    if not _is_int(version):
        return [f"{where} version must be the integer {ARIADNE_PROFILE_VERSION}"]
    if version != ARIADNE_EXTENSION_VERSION:
        return [f"{where} has unsupported extension version {version}"]
    unknown = sorted(set(extension) - _EXTENSION_KEYS)
    if unknown:
        errors.append(f"{where} carries unsupported field(s) {unknown}")
    role = extension.get("reference_role")
    if role not in REFERENCE_ROLES:
        errors.append(
            f"{where} reference_role must be one of {list(REFERENCE_ROLES)}, got {role!r}"
        )
    representations = extension.get("representations")
    if not isinstance(representations, list):
        representations = []
        errors.append(f"{where} representations must be an ordered list")
    representation_ids: set[str] = set()
    for position, representation in enumerate(representations):
        spot = f"{where} representations[{position}]"
        if not isinstance(representation, dict):
            errors.append(f"{spot} must be a mapping")
            continue
        unknown = sorted(set(representation) - _REPRESENTATION_KEYS)
        if unknown:
            errors.append(f"{spot} carries unsupported field(s) {unknown}")
        identifier = representation.get("id")
        if not isinstance(identifier, str) or not _SLUG_RE.fullmatch(identifier):
            errors.append(f"{spot} id must be a stable lowercase slug")
        elif identifier in representation_ids:
            errors.append(f"{spot} duplicates representation id {identifier!r}")
        else:
            representation_ids.add(identifier)
        errors.extend(_string_list_errors(f"{spot} aliases", representation.get("aliases")))
        fields = representation.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(f"{spot} requires a non-empty ordered fields list")
        else:
            errors.extend(_binding_list_errors(f"{spot} fields", fields))
        if "scope" not in representation:
            errors.append(f"{spot} requires its scope list (possibly empty)")
        else:
            errors.extend(_binding_list_errors(f"{spot} scope", representation["scope"]))
        description = representation.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"{spot} description must be a string")
    mappings = extension.get("mappings")
    if not isinstance(mappings, list):
        mappings = []
        errors.append(f"{where} mappings must be a list (possibly empty)")
    mapping_ids: set[str] = set()
    for position, mapping in enumerate(mappings):
        spot = f"{where} mappings[{position}]"
        if not isinstance(mapping, dict):
            errors.append(f"{spot} must be a mapping")
            continue
        unknown = sorted(set(mapping) - _MAPPING_KEYS)
        if unknown:
            errors.append(
                f"{spot} carries unsupported field(s) {unknown} — approval, "
                "confirmation and measured counts/digests are never authored in a mapping"
            )
        identifier = mapping.get("id")
        if not isinstance(identifier, str) or not _SLUG_RE.fullmatch(identifier):
            errors.append(f"{spot} id must be a stable lowercase slug")
        elif identifier in mapping_ids:
            errors.append(f"{spot} duplicates mapping id {identifier!r}")
        else:
            mapping_ids.add(identifier)
        if mapping.get("family") not in MAPPING_FAMILIES:
            errors.append(
                f"{spot} family must be one of {list(MAPPING_FAMILIES)}, "
                f"got {mapping.get('family')!r}"
            )
        for key in ("from", "to"):
            endpoint = mapping.get(key)
            if not _non_empty_str(endpoint):
                errors.append(f"{spot} {key} endpoint must be a representation id")
            elif endpoint not in representation_ids:
                errors.append(
                    f"{spot} {key} endpoint {endpoint!r} does not resolve to a "
                    "representation of this reference"
                )
        claim = mapping.get("claim")
        if claim not in MAPPING_CLAIMS:
            errors.append(f"{spot} claim must be one of {list(MAPPING_CLAIMS)}, got {claim!r}")
        source_ids = mapping.get("source_ids")
        if not isinstance(source_ids, list) or not all(
            isinstance(source_id, str) and source_id for source_id in source_ids
        ):
            errors.append(f"{spot} source_ids must be a list of footnote ids")
        else:
            unresolved = sorted(set(source_ids) - footnote_ids)
            if unresolved:
                errors.append(f"{spot} source_ids {unresolved} resolve to no native footnote")
            if claim == "asserted" and not source_ids:
                errors.append(f"{spot} is an asserted mapping without evidence")
        receipt_ids = mapping.get("receipt_ids")
        if receipt_ids is not None and not (
            isinstance(receipt_ids, list)
            and all(isinstance(receipt, str) and receipt for receipt in receipt_ids)
        ):
            errors.append(f"{spot} receipt_ids must be a list of evidence ids")
        candidate = mapping.get("candidate")
        if candidate is not None:
            if not isinstance(candidate, dict):
                errors.append(f"{spot} candidate must be a structured mapping object")
            elif candidate.get("family") not in MAPPING_FAMILIES:
                errors.append(f"{spot} candidate must declare its mapping family")
            elif candidate.get("family") != mapping.get("family"):
                errors.append(
                    f"{spot} declares family {mapping.get('family')!r} but its candidate "
                    f"measures the {candidate.get('family')!r} family"
                )
    return errors


def _evidence_errors(where: str, evidence: object) -> list[str]:
    """Core-attached verified receipt summaries (exact key set, counts int)."""
    if not isinstance(evidence, dict):
        return [f"{where} must be a mapping of mapping ids"]
    errors: list[str] = []
    for mapping_id, summaries in evidence.items():
        spot = f"{where}[{mapping_id!r}]"
        if not isinstance(summaries, list) or not summaries:
            errors.append(f"{spot} must be a non-empty list of verified receipt summaries")
            continue
        for position, summary in enumerate(summaries):
            entry = f"{spot}[{position}]"
            if not isinstance(summary, dict) or set(summary) != _EVIDENCE_SUMMARY_KEYS:
                errors.append(f"{entry} must be exactly a core-attached verified receipt summary")
                continue
            for key in _EVIDENCE_STRING_KEYS:
                if not _non_empty_str(summary[key]):
                    errors.append(f"{entry} {key} must be a non-empty string")
            for key in (
                "tested_left",
                "tested_right",
                "eligible_left",
                "eligible_right",
                "matched_left_in_right",
                "matched_right_in_left",
                "mismatch_count",
            ):
                if not _is_int(summary[key]):
                    errors.append(f"{entry} {key} must be an integer count")
    return errors


def native_metadata_errors(where: str, native: object) -> list[str]:
    """Validate the supported native metadata families of one profile.

    ``where`` is the named safe path of the ``native`` slot (the page's
    relative path). Pure: no I/O, no payload interpretation.
    """
    if native is None:
        return [f"{where} is null — a profiled page retains its native metadata"]
    if not isinstance(native, dict):
        return [f"{where} must be a mapping, got {type(native).__name__}"]
    errors: list[str] = []
    unknown = sorted(set(native) - NATIVE_KEYS)
    if unknown:
        errors.append(f"{where} carries unsupported native field(s) {unknown}")
    if "type" in native and native["type"] not in NATIVE_TYPES:
        errors.append(f"{where} type must be one of {sorted(NATIVE_TYPES)}")
    for key in ("title", "description"):
        if key in native and not isinstance(native[key], str):
            errors.append(f"{where} {key} must be a string")
    errors.extend(_string_list_errors(f"{where} tags", native.get("tags")))
    errors.extend(_string_list_errors(f"{where} aliases", native.get("aliases")))
    if "sources" in native:
        sources = native["sources"]
        if not isinstance(sources, list):
            errors.append(f"{where} sources must be a list")
        else:
            for index, entry in enumerate(sources):
                if isinstance(entry, str):
                    if not entry.strip():
                        errors.append(f"{where} sources[{index}] must be a non-empty identity")
                    continue
                if not isinstance(entry, dict):
                    errors.append(f"{where} sources[{index}] must be a mapping or string")
                elif set(entry) - NATIVE_SOURCE_KEYS:
                    errors.append(
                        f"{where} sources[{index}] carries unsupported field(s) "
                        f"{sorted(set(entry) - NATIVE_SOURCE_KEYS)}"
                    )
    footnote_ids = frozenset(
        entry["id"]
        for entry in native.get("sources") or []
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    )
    for key in ("resource", "status", "attestation", "attester", "runtime", "governed_by"):
        if key in native and not _non_empty_str(native[key]):
            errors.append(f"{where} {key} must be a non-empty string")
    errors.extend(_string_list_errors(f"{where} dimensions", native.get("dimensions")))
    if "grain" in native:
        grain = native["grain"]
        if not isinstance(grain, dict):
            errors.append(f"{where} grain must be a mapping")
        else:
            errors.extend(
                _string_list_errors(f"{where} grain primary_key", grain.get("primary_key"))
            )
            if not _non_empty_str(grain.get("cardinality_enforcement")):
                errors.append(f"{where} grain requires cardinality_enforcement")
    if "stale_after" in native and not isinstance(native["stale_after"], (str, date)):
        errors.append(
            f"{where} stale_after must keep its published source (a date, datetime or string)"
        )
    if "generated" in native:
        generated = native["generated"]
        if not isinstance(generated, dict) or not _json_shaped(generated):
            errors.append(f"{where} generated must be a JSON-shaped mapping")
    if "verified" in native:
        verified = native["verified"]
        if not isinstance(verified, list) or not all(
            isinstance(entry, dict) and _non_empty_str(entry.get("by")) for entry in verified
        ):
            errors.append(f"{where} verified must be a list of mappings with a non-empty 'by'")
    if "ariadne" in native:
        errors.extend(_extension_errors(f"{where} ariadne", native["ariadne"], footnote_ids))
    if "ariadne_evidence" in native:
        errors.extend(_evidence_errors(f"{where} ariadne_evidence", native["ariadne_evidence"]))
    return errors


def _policy_reference(where: str, raw: object) -> tuple[AriadnePolicyReference | None, list[str]]:
    if not isinstance(raw, dict) or set(raw) != {"namespace", "entity_id"}:
        return None, [f"{where} must be exactly {{namespace, entity_id}}"]
    if not _non_empty_str(raw["namespace"]) or not _non_empty_str(raw["entity_id"]):
        return None, [f"{where} namespace and entity_id must be non-empty strings"]
    return AriadnePolicyReference(
        namespace=str(raw["namespace"]), entity_id=str(raw["entity_id"])
    ), []


def parse_ariadne_profile(raw: object, *, where: str) -> tuple[AriadneProfile | None, list[str]]:
    """Parse and structurally validate one ``ariadne_profile`` envelope.

    ``where`` is the page's named safe path used in diagnostics. Returns the
    parsed envelope (``None`` when any diagnostic fires) and named-path
    diagnostics. Pure: no I/O, no payload interpretation, no coercion of
    versions or temporal scalars.
    """
    if raw is None:
        return None, []
    spot = f"{where}::ariadne_profile"
    if not isinstance(raw, dict):
        return None, [f"{spot} must be a mapping, got {type(raw).__name__}"]
    errors: list[str] = []
    unknown = sorted(set(raw) - _ENVELOPE_KEYS)
    if unknown:
        errors.append(f"{spot} carries unsupported field(s) {unknown}")
    version = raw.get("version")
    if not _is_int(version):
        errors.append(f"{spot} version must be the integer {ARIADNE_PROFILE_VERSION}")
    elif version != ARIADNE_PROFILE_VERSION:
        errors.append(f"{spot} has unsupported profile version {version}")
    kind = raw.get("kind")
    if kind not in ARIADNE_PROFILE_KINDS:
        errors.append(f"{spot} kind must be one of {sorted(ARIADNE_PROFILE_KINDS)}, got {kind!r}")
    if kind in KINDS_REQUIRING_REQUIRED_POLICIES and "required_policies" not in raw:
        errors.append(
            f"{spot} kind {kind!r} requires an explicit required_policies list (even when empty)"
        )
    if kind in KINDS_REQUIRING_METRIC_REF and "metric_ref" not in raw:
        errors.append(f"{spot} kind {kind!r} requires metric_ref")
    if kind in KINDS_REQUIRING_CORE_REF and "core_ref" not in raw:
        errors.append(f"{spot} kind {kind!r} requires core_ref")
    native = raw.get("native")
    if "native" not in raw:
        errors.append(f"{spot} requires its native metadata slot")
    errors.extend(native_metadata_errors(f"{spot}.native", native))
    required_policies: list[AriadnePolicyReference] = []
    if "required_policies" in raw:
        entries = raw["required_policies"]
        if not isinstance(entries, list):
            errors.append(f"{spot} required_policies must be a list")
        else:
            for index, entry in enumerate(entries):
                reference, entry_errors = _policy_reference(
                    f"{spot} required_policies[{index}]", entry
                )
                errors.extend(entry_errors)
                if reference is not None:
                    required_policies.append(reference)
    metric_ref = None
    if "metric_ref" in raw:
        entry = raw["metric_ref"]
        if not isinstance(entry, dict) or set(entry) != {"model", "metric"}:
            errors.append(f"{spot} metric_ref must be exactly {{model, metric}}")
        elif not _non_empty_str(entry["model"]) or not _non_empty_str(entry["metric"]):
            errors.append(f"{spot} metric_ref model and metric must be non-empty strings")
        else:
            metric_ref = AriadneMetricReference(
                model=str(entry["model"]), metric=str(entry["metric"])
            )
    core_ref = None
    if "core_ref" in raw:
        entry = raw["core_ref"]
        if not isinstance(entry, dict) or set(entry) != {"kind", "id"}:
            errors.append(f"{spot} core_ref must be exactly {{kind, id}}")
        elif entry["kind"] not in ("resource", "semantic"):
            errors.append(f"{spot} core_ref kind must be 'resource' or 'semantic'")
        elif not _non_empty_str(entry["id"]):
            errors.append(f"{spot} core_ref id must be a non-empty identity string")
        else:
            core_ref = AriadneCoreReference(kind=str(entry["kind"]), id=str(entry["id"]))
    ontology_refs: list[AriadneOntologyReference] = []
    if "ontology_refs" in raw:
        entries = raw["ontology_refs"]
        if not isinstance(entries, list):
            errors.append(f"{spot} ontology_refs must be a list")
        else:
            for index, entry in enumerate(entries):
                place = f"{spot} ontology_refs[{index}]"
                if not isinstance(entry, dict) or set(entry) != {
                    "namespace",
                    "identifier",
                    "revision",
                }:
                    errors.append(f"{place} must be exactly {{namespace, identifier, revision}}")
                elif not all(_non_empty_str(entry[key]) for key in entry):
                    errors.append(
                        f"{place} namespace, identifier and revision must be non-empty strings"
                    )
                else:
                    ontology_refs.append(
                        AriadneOntologyReference(
                            namespace=str(entry["namespace"]),
                            identifier=str(entry["identifier"]),
                            revision=str(entry["revision"]),
                        )
                    )
    if errors:
        return None, errors
    native = native if isinstance(native, dict) else {}
    return (
        AriadneProfile(
            version=ARIADNE_PROFILE_VERSION,
            kind=str(kind),
            native=dict(native),
            required_policies=required_policies,
            metric_ref=metric_ref,
            core_ref=core_ref,
            ontology_refs=ontology_refs,
        ),
        [],
    )


# ---------------------------------------------------------------------------
# Policy Closure and candidate validation (typed edges only).
# ---------------------------------------------------------------------------


def policy_closure(
    pages: Sequence[CompiledPage],
    profile: AriadneProfile,
    *,
    namespace: str,
    scope: Sequence[str] | None = None,
) -> tuple[tuple[AriadnePolicyReference, ...], tuple[AriadneProfileDiagnostic, ...]]:
    """The finite transitive closure over typed ``required_policies`` edges.

    Deterministic breadth-first expansion with sorted edges, deduplicated by
    exact ``(namespace, entity_id)`` identity and safe against cycles. Edges
    are ONLY the typed envelope edges — Markdown links, Claims, paths and
    Source references never contribute. ``scope`` (reader mode) additionally
    refuses an out-of-scope dependency WITHOUT naming the hidden page.
    """
    by_entity = {page.id: page for page in pages if page.id}
    diagnostics: list[AriadneProfileDiagnostic] = []
    seen: set[tuple[str, str]] = set()
    ordered: list[AriadnePolicyReference] = []
    queue = sorted(profile.required_policies, key=lambda ref: (ref.namespace, ref.entity_id))
    while queue:
        reference = queue.pop(0)
        identity = (reference.namespace, reference.entity_id)
        if identity in seen:
            continue
        seen.add(identity)
        if reference.namespace != namespace:
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    "a required policy names namespace "
                    f"{reference.namespace!r}, which is not the selected KB namespace "
                    f"{namespace!r} (v1 never traverses another namespace)",
                )
            )
            continue
        target = by_entity.get(reference.entity_id)
        if target is None:
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    f"a required policy entity {reference.entity_id!r} does not exist in "
                    "the selected Knowledge Base",
                )
            )
            continue
        target_profile = target.ariadne_profile
        if target_profile is None or target_profile.kind != "policy":
            kind = target_profile.kind if target_profile is not None else "(no profile)"
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    f"a required policy entity {reference.entity_id!r} is not a Policy "
                    f"page (kind {kind})",
                )
            )
            continue
        if scope is not None and (target.visibility or "") not in set(scope):
            # Reader-safe: the hidden page's title, text and position are
            # never disclosed — only that the closure cannot be served.
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "out-of-scope",
                    "the required Policy Closure contains a dependency outside the "
                    "authorized visibility scope",
                )
            )
            continue
        ordered.append(reference)
        queue.extend(target_profile.required_policies)
        queue.sort(key=lambda ref: (ref.namespace, ref.entity_id))
    return tuple(ordered), tuple(diagnostics)


def validate_ariadne_profiles(
    pages: Sequence[CompiledPage],
    *,
    namespace: str,
    scope: Sequence[str] | None = None,
) -> tuple[AriadneProfileDiagnostic, ...]:
    """Validate the complete profile set of one captured candidate.

    Envelope structure is validated at parse time (loader ValidationReport);
    this pass owns the cross-page contract: unique Entity/metric bindings and
    the complete, kind-correct, scope-aware required Policy Closure of every
    metric page. No database access, no payload execution.
    """
    diagnostics: list[AriadneProfileDiagnostic] = []
    profiled = [page for page in pages if page.ariadne_profile is not None]
    metric_binding_owner: dict[tuple[str, str], str] = {}
    for page in profiled:
        profile = page.ariadne_profile
        assert profile is not None
        if profile.metric_ref is not None:
            binding = (profile.metric_ref.model, profile.metric_ref.metric)
            owner = metric_binding_owner.get(binding)
            if owner is not None and owner != page.id:
                diagnostics.append(
                    AriadneProfileDiagnostic(
                        "duplicate-binding",
                        f"{page.path} binds metric {binding[0]}.{binding[1]} already "
                        f"bound by {owner}: each integrated metric has exactly one "
                        "Context Binding",
                    )
                )
            else:
                metric_binding_owner[binding] = page.id
    for page in profiled:
        profile = page.ariadne_profile
        assert profile is not None
        _, closure_diagnostics = policy_closure(pages, profile, namespace=namespace, scope=scope)
        for diagnostic in closure_diagnostics:
            diagnostics.append(
                AriadneProfileDiagnostic(
                    diagnostic.category,
                    f"{page.path}: {diagnostic.message}",
                )
            )
    return tuple(diagnostics)


# ---------------------------------------------------------------------------
# The immutable SDK view.
# ---------------------------------------------------------------------------


class ContextIdentity(msgspec.Struct, frozen=True):
    """The full expected identity of one published Context.

    Fingerprint alone is insufficient: the publication manifest digest and
    the Source Reference Manifest digest bind the exact source/reference
    state separately (spec 0009 §5).
    """

    namespace: str
    profile_version: int
    published_version: str
    fingerprint: str
    publication_manifest_digest: str
    source_reference_digest: str
    scope: tuple[str, ...] = PUBLIC_VISIBILITY_SCOPE


class ContextPageView(msgspec.Struct, frozen=True):
    """One scope-filtered full page view with its exact citation."""

    namespace: str
    entity_id: str
    kind: str
    path: str
    content: str
    body: str
    body_start_line: int
    native: dict
    sources: list[Source]
    published_version: str
    citation: str


class ContextBinding(msgspec.Struct, frozen=True):
    """One typed Context Binding: a metric Entity and its complete closure."""

    metric_entity_id: str
    metric_ref: AriadneMetricReference
    required_policies: tuple[ContextPageView, ...]


class ContextSnapshot(msgspec.Struct, frozen=True):
    """The immutable, scope-filtered view of one published Context."""

    identity: ContextIdentity
    pages: tuple[ContextPageView, ...]
    bindings: tuple[ContextBinding, ...]


class AriadneCandidateInspection(msgspec.Struct, frozen=True):
    """Structural/dependency diagnostics of one exact captured revision.

    Always unadmitted: inspection is never a served Context Snapshot and
    never grants publication authority (spec 0009 §5).
    """

    namespace: str
    revision: str
    subtree: str
    admitted: bool
    fingerprint: str
    source_reference_manifest_digest: str
    diagnostics: tuple[AriadneProfileDiagnostic, ...]


def inspect_ariadne_candidate(
    kb_root: str, revision: str, *, namespace: str
) -> AriadneCandidateInspection:
    """Inspect one exact captured Authoring Revision (explicitly unadmitted).

    Reads only the exact Git blobs of the selected revision. The candidate's
    declared namespace must match ``namespace``. Operator review may inspect
    its own candidate normally, so no visibility filtering is applied here.
    """
    from lumio_wiki.git_authoring import capture_revision

    if not _non_empty_str(namespace):
        raise AriadneContextError("candidate inspection requires the expected KB namespace")
    captured = capture_revision(kb_root, revision)
    if captured.manifest.namespace != namespace:
        raise IdentityMismatchError(
            "the captured revision declares Source Reference namespace "
            f"{captured.manifest.namespace!r}, not the expected {namespace!r}"
        )
    diagnostics: list[AriadneProfileDiagnostic] = [
        AriadneProfileDiagnostic(
            "malformed",
            f"{issue.file}: {issue.field}: {issue.message}",
        )
        for issue in captured.report.issues
        if issue.severity == "error"
    ]
    diagnostics.extend(validate_ariadne_profiles(captured.kb.pages, namespace=namespace))
    return AriadneCandidateInspection(
        namespace=namespace,
        revision=captured.revision,
        subtree=captured.subtree,
        admitted=False,
        fingerprint=captured.fingerprint.digest,
        source_reference_manifest_digest=captured.manifest_digest,
        diagnostics=tuple(diagnostics),
    )


def _page_view(
    page: CompiledPage,
    *,
    namespace: str,
    published_version: str,
    canonical_content: dict[str, bytes],
) -> ContextPageView:
    raw = canonical_content.get(page.path, b"")
    return ContextPageView(
        namespace=namespace,
        entity_id=page.id,
        kind=page.ariadne_profile.kind if page.ariadne_profile else "",
        path=page.path,
        content=raw.decode("utf-8", errors="replace"),
        body=page.body,
        body_start_line=page.body_start_line,
        native=dict(page.ariadne_profile.native) if page.ariadne_profile else {},
        sources=list(page.sources),
        published_version=published_version,
        citation=f"{namespace} {page.id} v{published_version} {page.path}",
    )


def _raise_for_diagnostics(diagnostics: Sequence[AriadneProfileDiagnostic]) -> None:
    for diagnostic in diagnostics:
        if diagnostic.category == "unsupported":
            raise UnsupportedProfileError(diagnostic.message)
        if diagnostic.category == "unresolved-reference":
            raise UnresolvedReferenceError(diagnostic.message)
        if diagnostic.category == "out-of-scope":
            raise OutOfScopeDependencyError(diagnostic.message)
        raise MalformedProfileError(diagnostic.message)
    if diagnostics:
        raise MalformedProfileError(diagnostics[0].message)


def open_published_context(
    location: Any,
    expected: ContextIdentity,
) -> ContextSnapshot:
    """Open one exact immutable Published Version as a Context Snapshot.

    Requires a version-pinned published Location (never a plain directory,
    never a floating current pointer), verifies every expected Context
    Identity component against the publication's own manifest and bytes, and
    applies the expected identity's effective Visibility Scope before any
    lookup, expansion or view construction. A changed or wrong version
    refuses; there is no fallback to latest.
    """
    from lumio_wiki.location import PublishedFilesystemLocation, published_version_path

    if not isinstance(location, PublishedFilesystemLocation):
        raise UnadmittedInputError(
            "opening a published Context requires an immutable-version-pinned "
            "published Location; plain directories and unadmitted inputs are refused"
        )
    pinned = location.version
    if pinned is None:
        raise UnadmittedInputError(
            "the published Location carries no exact version pin; the current "
            "pointer is never read as a fallback for Context opening"
        )
    manifest_file = published_version_path(location.path, pinned) / "manifest.json"
    try:
        manifest_raw = manifest_file.read_bytes()
    except OSError as exc:
        raise SnapshotUnavailableError(
            f"Published Version {pinned!r} has no readable manifest at {location.path}: {exc}"
        ) from exc
    manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
    try:
        snapshot = location.resolve()
        manifest = location.read_manifest(pinned)
    except Exception as exc:  # KnowledgeBaseError family: corruption, absence.
        raise SnapshotUnavailableError(
            f"Published Version {pinned!r} could not be resolved and verified: {exc}"
        ) from exc
    if not _non_empty_str(manifest.namespace):
        raise UnadmittedInputError(
            "the publication carries no Source Reference namespace disclosure; its "
            "Context Identity cannot be verified"
        )
    mismatches = []
    if expected.published_version != pinned:
        mismatches.append("published_version")
    if expected.fingerprint != manifest.fingerprint:
        mismatches.append("fingerprint")
    if expected.publication_manifest_digest != manifest_digest:
        mismatches.append("publication_manifest_digest")
    if expected.source_reference_digest != manifest.source_reference_digest:
        mismatches.append("source_reference_digest")
    if expected.namespace != manifest.namespace:
        mismatches.append("namespace")
    if mismatches:
        raise IdentityMismatchError(
            "the opened Published Version does not match the expected Context "
            f"Identity (mismatched: {', '.join(sorted(mismatches))}); an exact "
            "identity is required and latest is never substituted"
        )
    if expected.profile_version != ARIADNE_PROFILE_VERSION:
        raise UnsupportedProfileError(
            f"unsupported profile version {expected.profile_version} "
            f"(supported: {ARIADNE_PROFILE_VERSION})"
        )
    if not expected.scope:
        raise AriadneContextError("the effective Visibility Scope must not be empty")
    if not snapshot.validation_report.is_valid():
        issues = "; ".join(
            f"{issue.file}: {issue.field}: {issue.message}"
            for issue in snapshot.validation_report.issues
            if issue.severity == "error"
        )
        raise MalformedProfileError(f"the published content fails native validation: {issues}")
    _raise_for_diagnostics(
        validate_ariadne_profiles(
            snapshot.pages, namespace=manifest.namespace, scope=expected.scope
        )
    )
    in_scope = [
        page
        for page in snapshot.pages
        if page.ariadne_profile is not None and (page.visibility or "") in set(expected.scope)
    ]
    content = snapshot.knowledge_base.canonical_pages
    views = {
        page.id: _page_view(
            page,
            namespace=manifest.namespace,
            published_version=pinned,
            canonical_content=content,
        )
        for page in in_scope
    }
    bindings: list[ContextBinding] = []
    for page in in_scope:
        profile = page.ariadne_profile
        assert profile is not None
        if profile.kind != "metric" or profile.metric_ref is None:
            continue
        closure, _ = policy_closure(
            snapshot.pages, profile, namespace=manifest.namespace, scope=expected.scope
        )
        bindings.append(
            ContextBinding(
                metric_entity_id=page.id,
                metric_ref=profile.metric_ref,
                required_policies=tuple(
                    views[reference.entity_id]
                    for reference in closure
                    if reference.entity_id in views
                ),
            )
        )
    return ContextSnapshot(
        identity=expected,
        pages=tuple(views.values()),
        bindings=tuple(bindings),
    )


def disclose_native(value: Any) -> Any:
    """Disclose a native value under the native JSON representation contract.

    YAML-native date/datetime scalars become ISO-8601 strings; everything
    else passes through untouched. No freshness, currency or receipt is
    invented by disclosure.
    """
    if isinstance(value, dict):
        return {str(key): disclose_native(item) for key, item in value.items()}
    if isinstance(value, list):
        return [disclose_native(item) for item in value]
    if isinstance(value, date):  # datetime included
        return value.isoformat()
    return value

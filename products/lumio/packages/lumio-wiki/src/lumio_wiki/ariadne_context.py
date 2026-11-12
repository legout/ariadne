"""The Ariadne Context Profile and immutable scoped SDK view (spec 0009).

An explicitly versioned ``ariadne-context/1`` application profile over native
Lumio content, plus the additive producer SDK for it. The envelope lives in
Compiled Page frontmatter under ``ariadne_profile``; its ``native`` slot
retains the supported Ariadne OKF metadata families losslessly. This module
is model-free, adds no dependency, and never imports Ariadne: the supported
schema below is frozen from the approved Ariadne source contracts (specs
0010/0011/0024 and the native context/sources parsers at the pinned source
commit recorded in spec 0009).

Support boundary (v1, frozen with this module's committed result):

- Envelope: exact integer ``version: 1``, one of the eight native kinds,
  ``native`` metadata, typed ``required_policies`` edges (mandatory — even
  when empty — on metric and policy pages), ``metric_ref`` (required on
  metric pages), ``core_ref`` (required on dataset/table/computation pages)
  and ``ontology_refs``. Unknown envelope fields refuse.
- Native families (validated per the page's native ``type``): the shared
  page identity/provenance/lifecycle fields (``title``, ``description``,
  ``tags``, ``sources``, ``status``, ``aliases``, ``stale_after``,
  ``generated``, ``verified``, ``observed_value_columns``, ``resource``),
  metric governance (``governed_by``, ``dimensions``, ``grain``),
  computation attestation (``attestation``, ``attester``, ``runtime``,
  ``dataset_sources``), the Reference ``ariadne`` extension with
  ``ariadne_evidence`` receipt summaries, the table ``ariadne``
  schema/observations block, and the dataset ``ariadne.tables`` links.
  Required-versus-optional follows the native per-kind contract; canonical
  binding Resources are ``ariadne://table/<payload>`` (or ``collection``)
  URIs; native ``sources[].resource`` entries are relative OKF-bundle paths
  (Policy/semantic-layer provenance), a distinct concept from table binding
  Resources. Unknown native fields refuse by name. YAML-native date/datetime
  temporal values keep their published source; SDK disclosure follows the
  native ISO-8601 JSON representation contract.
- Typed ``required_policies`` edges drive the Policy Closure; retained native
  Policy path references must resolve to an existing Policy page and agree
  with the typed closure (provenance is preserved, never promoted to edges).
  ``ontology_refs`` resolve only against a caller-pinned declared catalog;
  floating/unknown/ambiguous targets refuse.

The SDK surfaces are additive: candidate inspection of one exact captured
(unadmitted) Authoring Revision, opening of one exact admitted immutable
Published Version (local or S3 object store) with its full expected Context
Identity and effective Visibility Scope, and scoped local navigation
(list/read/search of the visible ordinary and profiled pages) through the
same one-shot verified snapshot. Nothing here executes payload
content, reads a latest pointer as fallback, or grants source/publication/
database permission.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, TypeGuard

import msgspec

from lumio_wiki.records import (
    AriadneContextControl,
    AriadneCoreReference,
    AriadneMetricReference,
    AriadneOntologyReference,
    AriadnePolicyReference,
    AriadneProfile,
    CompiledPage,
    KnowledgeBaseControlFile,
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
    {
        "dataset",
        "table",
        "reference",
        "policy",
        "metric",
        "computation",
        "skill",
        "answer_example",
    }
)

#: Kinds whose pages MUST declare ``required_policies`` (even when empty).
KINDS_REQUIRING_REQUIRED_POLICIES = frozenset({"metric", "policy"})
#: Kinds whose pages MUST declare ``metric_ref``.
KINDS_REQUIRING_METRIC_REF = frozenset({"metric"})
#: Kinds whose pages MUST declare ``core_ref``.
KINDS_REQUIRING_CORE_REF = frozenset({"dataset", "table", "computation"})

#: Native per-kind required metadata families beyond the envelope itself
#: (mirrors the native bundle contract: shared base plus per-kind additions).
_NATIVE_BASE_REQUIRED = ("title", "description", "tags", "sources")
NATIVE_REQUIRED_FIELDS = {
    "dataset": _NATIVE_BASE_REQUIRED,
    "table": _NATIVE_BASE_REQUIRED,
    "reference": _NATIVE_BASE_REQUIRED,
    "skill": _NATIVE_BASE_REQUIRED,
    "policy": _NATIVE_BASE_REQUIRED + ("status",),
    "metric": _NATIVE_BASE_REQUIRED + ("status", "governed_by", "dimensions", "grain"),
    "computation": _NATIVE_BASE_REQUIRED + ("status",),
    # spec0035 C4: the retained spec0007 required families; optional
    # parameters/project/sql_provenance validate exactly when supplied.
    "answer_example": _NATIVE_BASE_REQUIRED
    + ("question", "interpretation", "method", "submitter", "answer"),
}

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
    {
        "dataset",
        "table",
        "reference",
        "policy",
        "metric",
        "computation",
        "skill",
        "answer_example",
    }
)
REFERENCE_ROLES = ("term", "identifier", "enum", "join")
MAPPING_FAMILIES = ("equality", "prefix", "lookup")
MAPPING_CLAIMS = ("hypothesis", "asserted")
CANDIDATE_FAMILIES = ("equality", "prefix", "lookup")
CANDIDATE_SCOPE_OPS = ("eq", "in", "gte", "lt")
MAX_PARTICIPATING_ASSETS = 4
MAX_CANDIDATE_BINDINGS = 16
MAX_SCOPE_PREDICATES = 8
MAX_IN_LIST_VALUES = 100
#: Revision labels that are explicitly floating and never valid immutable
#: ontology revisions (spec 0009 §4).
FLOATING_REVISIONS = frozenset({"main", "latest", "head", "current", "tip"})

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
        "observed_value_columns",
        "dataset_sources",
        # spec0035 C4: the producer-owned Answer Example families (structural
        # only; Ariadne specs 0007/0023 keep their meanings, Core keeps the
        # analytical meaning/consent/provenance authority).
        "question",
        "interpretation",
        "method",
        "parameters",
        "project",
        "submitter",
        "citations",
        "sql_provenance",
        "answer",
    }
)
NATIVE_SOURCE_KEYS = frozenset({"id", "title", "url", "resource"})

# -- The producer-owned Answer Example families (spec0035 C4; retained field
# -- meanings live in Ariadne specs 0007/0023 — validated structurally only). --

#: The only structured methods an Example may record (never standalone SQL).
_ANSWER_EXAMPLE_OPERATIONS = frozenset({"get_metric", "define_metric"})
#: spec0023 §2: the fixed provenance descriptor — the submitted result
#: envelope's sql field, never a verified execution origin.
_ANSWER_EXAMPLE_SQL_SOURCE = "submitted_result.sql"
#: spec0007: the timestamped answer excerpt bound (UTF-8 bytes).
_ANSWER_EXAMPLE_EXCERPT_BYTES = 8 * 1024
_ANSWER_EXAMPLE_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ANSWER_EXAMPLE_KEYS = frozenset(
    {"question", "interpretation", "method", "submitter", "answer"}
)
_ANSWER_EXAMPLE_OPTIONAL_KEYS = frozenset({"parameters", "project", "citations", "sql_provenance"})
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
_EVIDENCE_COUNT_KEYS = frozenset(
    {
        "tested_left",
        "tested_right",
        "eligible_left",
        "eligible_right",
        "matched_left_in_right",
        "matched_right_in_left",
        "mismatch_count",
    }
)
#: The table ``ariadne`` block (core-generated schema/observations).
_TABLE_ARIADNE_KEYS = frozenset({"schema", "observations"})
_TABLE_ARIADDE_KEYS = frozenset({"schema", "observations"})
_TABLE_OBSERVATION_KEYS = frozenset(
    {
        "observed_at",
        "scope",
        "row_count",
        "candidate_keys",
        "columns",
        "citation",
        "value_evidence",
        "source_binding",
    }
)
#: The dataset ``ariadne`` block links exactly the documented tables.
_DATASET_ARIADNE_KEYS = frozenset({"tables"})
#: The dataset ``ariadne`` block links exactly the documented tables.
_DATASET_ARIADDE_KEYS = frozenset({"tables"})
_COMMON_CANDIDATE_KEYS = frozenset({"family", "left", "right", "scope", "pairing"})
_FAMILY_CANDIDATE_KEYS = {
    "equality": frozenset(),
    "prefix": frozenset({"separator", "prefix_lookup"}),
    "lookup": frozenset({"lookup"}),
}
_SCOPE_PREDICATE_KEYS = frozenset({"resource", "column", "op", "value"})
_PAIRING_KEYS = frozenset({"left", "right"})
_PREFIX_LOOKUP_KEYS = frozenset({"asset", "key_fields", "prefix_field"})
_LOOKUP_KEYS = frozenset({"asset", "key_fields", "value_fields"})

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

    path: str = ""
    """The named safe path of the page this diagnostic is scoped to (empty for
    non-page diagnostics). Used by native gates to file the issue; never a
    hidden out-of-scope page."""


# ---------------------------------------------------------------------------
# Canonical resource identity (ported structurally from the native contract:
# ariadne sources.py ``table_resource``/``parse_resource`` — stdlib only).
# ---------------------------------------------------------------------------


def parse_ariadne_resource(uri: object) -> tuple[str, list]:
    """Decode one canonical ``ariadne://table|collection/<payload>`` URI.

    Returns ``(kind, parts)`` where parts is the identifier array
    ``[source, catalog (or null), schema(, table)]``. Malformed URIs,
    absolute operational paths and credential-bearing resource strings raise
    ``ValueError`` — the exact structural rules of the native contract.
    """
    if not isinstance(uri, str):
        raise ValueError(f"resource must be a string, got {uri!r}")
    prefix = "ariadne://"
    if not uri.startswith(prefix):
        raise ValueError(f"resource {uri!r} is not a canonical ariadne:// URI")
    kind, _, payload = uri[len(prefix) :].partition("/")
    if kind not in ("table", "collection") or not payload:
        raise ValueError(
            f"resource {uri!r} must be ariadne://table/<payload> or ariadne://collection/<payload>"
        )
    padded = payload + "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        parts = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(
            f"resource {uri!r} does not decode to a canonical payload: {exc}"
        ) from None
    expected = 4 if kind == "table" else 3
    if (
        not isinstance(parts, list)
        or len(parts) != expected
        or not all(part is None or isinstance(part, str) for part in parts)
        or not isinstance(parts[0], str)
        or not parts[0]
        or parts[2] is None
    ):
        raise ValueError(
            f"resource {uri!r} payload must be [{expected} identifiers: source, "
            "catalog (or null), schema(, table)]"
        )
    return kind, parts


def _resource_uri_errors(where: str, uri: object, *, kinds: tuple[str, ...]) -> list[str]:
    try:
        kind, _parts = parse_ariadne_resource(uri)
    except ValueError as exc:
        return [f"{where} is not canonical: {exc}"]
    if kind not in kinds:
        return [f"{where} names a {kind} resource — expected {' or '.join(kinds)}"]
    return []


# ---------------------------------------------------------------------------
# Envelope parsing and the frozen native-schema validation (pure).
# ---------------------------------------------------------------------------


def _is_int(value: object) -> TypeGuard[int]:
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
    """Ordered ``{resource, column}`` bindings with canonical table resources."""
    if not isinstance(bindings, list):
        return [f"{where} must be an ordered list of {{resource, column}} bindings"]
    errors: list[str] = []
    for index, binding in enumerate(bindings):
        spot = f"{where}[{index}]"
        if not isinstance(binding, dict) or set(binding) != {"resource", "column"}:
            errors.append(f"{spot} must be exactly {{resource, column}}")
            continue
        errors.extend(
            _resource_uri_errors(f"{spot} resource", binding["resource"], kinds=("table",))
        )
        if not _non_empty_str(binding["column"]):
            errors.append(f"{spot} column must be a non-empty exact identifier")
    return errors


def _one_resource(where: str, bindings: object) -> tuple[str | None, list[str]]:
    """The single canonical resource a binding side names, or an error."""
    if not isinstance(bindings, list) or not bindings:
        return None, [f"{where} requires an ordered non-empty binding list"]
    resources = {binding["resource"] for binding in bindings if isinstance(binding, dict)}
    if len(resources) != 1:
        return None, [f"{where} must name exactly one canonical resource"]
    return resources.pop(), []


def _scope_scalar(value: object) -> bool:
    """A typed scope scalar (bool is not a number here; null is untyped)."""
    return isinstance(value, (str, int, float, bool))


def _lookup_asset_errors(where: str, lookup: object) -> tuple[dict | None, int, list[str]]:
    """Validate one lookup/prefix-lookup asset declaration (native contract)."""
    if not isinstance(lookup, dict):
        return None, 0, [f"{where} must be a mapping"]
    errors: list[str] = []
    asset = lookup.get("asset")
    try:
        kind, _parts = parse_ariadne_resource(asset)
        if kind != "table":
            errors.append(f"{where} names a {kind} resource — a lookup asset is a table")
    except ValueError as exc:
        errors.append(f"{where} asset is not canonical: {exc}")
    count = 0
    saw_key_fields = False
    for key in ("key_fields", "value_fields", "prefix_field"):
        if key not in lookup:
            continue
        bindings = lookup[key]
        bindings = [bindings] if key == "prefix_field" else bindings
        if not isinstance(bindings, list) or not bindings:
            errors.append(f"{where} {key} must be an ordered non-empty binding list")
            continue
        spot = f"{where} {key}"
        errors.extend(_binding_list_errors(spot, bindings))
        for binding in bindings:
            if isinstance(binding, dict) and binding.get("resource") != asset:
                errors.append(
                    f"{spot} must bind the lookup asset itself — a binding names "
                    f"{binding.get('resource')!r}"
                )
        count += len(bindings)
        if key == "key_fields":
            saw_key_fields = True
    if not saw_key_fields:
        errors.append(f"{where} requires its ordered key_fields")
    return (lookup if not errors else None), count, errors


def _candidate_errors(where: str, candidate: object) -> list[str]:
    """The structural inspection-candidate contract (native spec 0010 §7,
    ported without execution): discriminated JSON object, canonical bindings,
    typed scope/pairing/lookup shapes, family arity and structural ceilings.
    There is no SQL, function, path or freely interpreted expression field."""
    if not isinstance(candidate, dict):
        return [f"{where} must be a discriminated JSON object"]
    errors: list[str] = []
    family = candidate.get("family")
    if family not in CANDIDATE_FAMILIES:
        return [f"{where} family must be one of {list(CANDIDATE_FAMILIES)}, got {family!r}"]
    allowed = _COMMON_CANDIDATE_KEYS | _FAMILY_CANDIDATE_KEYS[family]
    unknown = sorted(set(candidate) - allowed)
    if unknown:
        errors.append(
            f"{where} carries unsupported field(s) {unknown} — there is no SQL, "
            "function or path field"
        )
    sides: dict[str, list] = {}
    for side in ("left", "right"):
        bindings = candidate.get(side)
        if not isinstance(bindings, list) or not bindings:
            errors.append(f"{where} requires an ordered non-empty '{side}' binding list")
            continue
        spot_errors = _binding_list_errors(f"{where} {side}", bindings)
        errors.extend(spot_errors)
        if spot_errors:
            continue
        sides[side] = bindings
    left_resource = right_resource = None
    if "left" in sides:
        left_resource, one_errors = _one_resource(f"{where} left", sides["left"])
        errors.extend(one_errors)
    if "right" in sides:
        right_resource, one_errors = _one_resource(f"{where} right", sides["right"])
        errors.extend(one_errors)
    assets: set[str] = set()
    if left_resource is not None:
        assets.add(left_resource)
    if right_resource is not None:
        assets.add(right_resource)
    binding_count = sum(len(side) for side in sides.values())
    scope = candidate.get("scope", [])
    if scope is None:
        scope = []
    if not isinstance(scope, list):
        errors.append(f"{where} scope must be an ordered list of predicates")
        scope = []
    if len(scope) > MAX_SCOPE_PREDICATES:
        errors.append(
            f"{where} carries {len(scope)} scope predicates — at most "
            f"{MAX_SCOPE_PREDICATES} are measurable per request"
        )
    for index, predicate in enumerate(scope):
        spot = f"{where} scope[{index}]"
        if not isinstance(predicate, dict) or set(predicate) != _SCOPE_PREDICATE_KEYS:
            errors.append(f"{spot} must be exactly {{resource, column, op, value}}")
            continue
        errors.extend(
            _binding_list_errors(
                spot, [{"resource": predicate["resource"], "column": predicate["column"]}]
            )
        )
        if predicate["op"] not in CANDIDATE_SCOPE_OPS:
            errors.append(f"{spot} operator must be one of {list(CANDIDATE_SCOPE_OPS)}")
        value = predicate["value"]
        if predicate["op"] == "in":
            if (
                not isinstance(value, list)
                or not value
                or len(value) > MAX_IN_LIST_VALUES
                or not all(_scope_scalar(item) for item in value)
            ):
                errors.append(
                    f"{spot} 'in' value must be a non-empty list of at most "
                    f"{MAX_IN_LIST_VALUES} typed scalar values"
                )
        elif not _scope_scalar(value):
            errors.append(f"{spot} value must be a typed scalar")
    binding_count += len(scope)
    pairing = candidate.get("pairing", [])
    if pairing is None:
        pairing = []
    if not isinstance(pairing, list):
        errors.append(f"{where} pairing must be a list of field pairs")
        pairing = []
    for index, pair in enumerate(pairing):
        spot = f"{where} pairing[{index}]"
        if not isinstance(pair, dict) or set(pair) != _PAIRING_KEYS:
            errors.append(f"{spot} must be exactly {{left, right}}")
            continue
        for side, side_resource in (("left", left_resource), ("right", right_resource)):
            binding = pair.get(side)
            if not isinstance(binding, dict):
                errors.append(f"{spot} {side} must be a {{resource, column}} binding")
                continue
            errors.extend(_binding_list_errors(f"{spot} {side}", [binding]))
            if (
                isinstance(binding, dict)
                and side_resource is not None
                and binding.get("resource") != side_resource
            ):
                errors.append(
                    f"{spot} {side} binding must name the candidate's {side} asset "
                    f"{side_resource!r}"
                )
        binding_count += 2
    if family == "equality":
        if "left" in sides and "right" in sides and len(sides["left"]) != len(sides["right"]):
            errors.append(
                f"{where} an equality candidate compares equally sized tuples — "
                f"left has {len(sides['left'])} field(s), right {len(sides['right'])}"
            )
    elif family == "prefix":
        if "right" in sides and len(sides["right"]) != 1:
            errors.append(f"{where} a prefix candidate compares one target field binding")
        separator = candidate.get("separator")
        if not isinstance(separator, str):
            errors.append(
                f"{where} a prefix candidate carries an explicit literal 'separator' "
                "string (the empty string is explicit)"
            )
        prefix_lookup = candidate.get("prefix_lookup")
        if prefix_lookup is not None:
            if not isinstance(prefix_lookup, dict) or set(prefix_lookup) != _PREFIX_LOOKUP_KEYS:
                errors.append(
                    f"{where} prefix_lookup must be exactly {{asset, key_fields, prefix_field}}"
                )
            else:
                _lookup, count, lookup_errors = _lookup_asset_errors(
                    f"{where} prefix_lookup", prefix_lookup
                )
                errors.extend(lookup_errors)
                binding_count += count
                if _lookup is not None and isinstance(_lookup.get("key_fields"), list):
                    if len(_lookup["key_fields"]) > len(sides.get("left") or []):
                        errors.append(
                            f"{where} prefix_lookup key_fields outnumber the left "
                            "components they identify"
                        )
                if _lookup is not None and _lookup.get("asset"):
                    assets.add(_lookup["asset"])
    else:  # lookup
        lookup = candidate.get("lookup")
        if not isinstance(lookup, dict) or set(lookup) != _LOOKUP_KEYS:
            errors.append(f"{where} lookup must be exactly {{asset, key_fields, value_fields}}")
        else:
            _lookup, count, lookup_errors = _lookup_asset_errors(f"{where} lookup", lookup)
            errors.extend(lookup_errors)
            binding_count += count
            if _lookup is not None:
                key_fields = _lookup.get("key_fields") or []
                value_fields = _lookup.get("value_fields") or []
                if len(sides.get("left") or []) != len(key_fields):
                    errors.append(
                        f"{where} a lookup candidate's left bindings match the lookup "
                        "key_fields one-for-one"
                    )
                if len(sides.get("right") or []) != len(value_fields):
                    errors.append(
                        f"{where} a lookup candidate's right bindings match the lookup "
                        "value_fields one-for-one"
                    )
                if left_resource is not None and left_resource != right_resource:
                    errors.append(
                        f"{where} a lookup candidate's left and right bindings name "
                        "the same measured asset (its keys and mapped values)"
                    )
                if _lookup.get("asset"):
                    assets.add(_lookup["asset"])
    if scope and not errors:
        unattached = sorted(
            {predicate["resource"] for predicate in scope if isinstance(predicate, dict)} - assets
        )
        if unattached:
            errors.append(
                f"{where} scope names {unattached}, which is not a participating "
                "measured asset — scope narrows a participating measured asset only"
            )
    if binding_count > MAX_CANDIDATE_BINDINGS:
        errors.append(
            f"{where} binds {binding_count} fields — at most "
            f"{MAX_CANDIDATE_BINDINGS} candidate field bindings are measurable "
            "per request"
        )
    if len(assets) > MAX_PARTICIPATING_ASSETS:
        errors.append(
            f"{where} names {len(assets)} participating assets ({sorted(assets)}) — "
            f"at most {MAX_PARTICIPATING_ASSETS} participate"
        )
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
        return [f"{where} version must be the integer {ARIADNE_EXTENSION_VERSION}"]
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
        if "aliases" in representation:
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
            candidate_diagnostics = _candidate_errors(f"{spot} candidate", candidate)
            errors.extend(candidate_diagnostics)
            if not candidate_diagnostics:
                if candidate.get("family") != mapping.get("family"):
                    errors.append(
                        f"{spot} declares family {mapping.get('family')!r} but its "
                        f"candidate measures the {candidate.get('family')!r} family"
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
                value = summary[key]
                if key == "observed_at":
                    # YAML-native temporal values keep their published source.
                    if not isinstance(value, (str, date)):
                        errors.append(
                            f"{entry} observed_at must keep its published source "
                            "(a date, datetime or string)"
                        )
                elif not _non_empty_str(value):
                    errors.append(f"{entry} {key} must be a non-empty string")
            for key in _EVIDENCE_COUNT_KEYS:
                if not _is_int(summary[key]):
                    errors.append(f"{entry} {key} must be an integer count")
    return errors


def _value_evidence_errors(where: str, evidence: object) -> list[str]:
    """Spec0024's saved observation structure, never measurement authentication."""
    if not isinstance(evidence, dict):
        return [f"{where} must map selected columns to evidence entries"]
    errors: list[str] = []
    reasons = {
        "not_in_profile", "column_missing", "type_changed", "unsupported_representation",
        "permission_denied", "too_large",
    }
    for column, entry in evidence.items():
        spot = f"{where}[{column!r}]"
        if not _non_empty_str(column) or not isinstance(entry, dict):
            errors.append(f"{spot} requires a column name and a state-specific mapping")
            continue
        state = entry.get("state")
        if state == "unavailable":
            reason = entry.get("reason")
            if (set(entry) != {"state", "reason"}
                    or not isinstance(reason, str) or reason not in reasons):
                errors.append(f"{spot} unavailable requires a supported reason and no top_values")
        elif state == "observed":
            top = entry.get("top_values")
            if set(entry) != {"state", "top_values"} or not isinstance(top, list) or not top:
                errors.append(f"{spot} observed requires measured top_values")
                continue
            if len(top) > 10:
                errors.append(f"{spot} top_values exceeds the native ten-value bound")
            for index, value in enumerate(top):
                item = f"{spot}.top_values[{index}]"
                if not isinstance(value, dict) or set(value) != {"value", "count"}:
                    errors.append(f"{item} must contain exactly value and count")
                    continue
                literal = value["value"]
                if not (
                    literal is None or isinstance(literal, (str, bool, int))
                    or (isinstance(literal, float) and math.isfinite(literal))
                ):
                    errors.append(f"{item}.value must retain a supported finite native scalar")
                if not _is_int(value["count"]) or value["count"] < 0:
                    errors.append(f"{item}.count must be a non-negative integer")
        else:
            errors.append(f"{spot}.state must be observed or unavailable")
    if not errors:
        try:
            size = len(json.dumps(evidence, ensure_ascii=False, allow_nan=False,
                                  separators=(",", ":")).encode("utf-8"))
        except UnicodeError:
            errors.append(f"{where} must contain UTF-8 representable values")
        else:
            if size > 8 * 1024:
                errors.append(f"{where} exceeds the native 8-KiB compact-JSON bound")
    return errors


def _table_ariadne_errors(where: str, block: object) -> list[str]:
    """The pinned native schema rows and saved observations, without reinterpretation."""
    if not isinstance(block, dict):
        return [f"{where} must be a mapping"]
    errors: list[str] = []
    unknown = sorted(set(block) - _TABLE_ARIADDE_KEYS)
    if unknown:
        errors.append(f"{where} carries unsupported field(s) {unknown}")
    schema = block.get("schema")
    if not isinstance(schema, list) or not schema:
        errors.append(f"{where} schema must be an ordered non-empty column inventory")
    else:
        for index, entry in enumerate(schema):
            spot = f"{where} schema[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"{spot} must be a column metadata mapping")
                continue
            if set(entry) != {"column", "type", "nullable", "default", "comment"}:
                errors.append(f"{spot} requires native column/type/nullable/default/comment fields")
            for key in ("column", "type"):
                if not _non_empty_str(entry.get(key)):
                    errors.append(f"{spot} requires a non-empty '{key}'")
            nullable = entry.get("nullable")
            if nullable is not None and not isinstance(nullable, bool) and nullable != "unknown":
                errors.append(f"{spot}.nullable must retain a boolean, null or unknown")
            for key in ("default", "comment"):
                if entry.get(key) is not None and not isinstance(entry[key], str):
                    errors.append(f"{spot}.{key} must retain a string or null")
    observations = block.get("observations")
    if not isinstance(observations, dict):
        return [*errors, f"{where} observations must be a mapping of measured facts"]
    unknown = sorted(set(observations) - _TABLE_OBSERVATION_KEYS)
    if unknown:
        errors.append(f"{where} observations carries unsupported field(s) {unknown}")
    observed_at = observations.get("observed_at")
    try:
        timestamp = (
            datetime.fromisoformat(observed_at) if isinstance(observed_at, str) else observed_at
        )
        if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
            raise ValueError
    except (ValueError, OverflowError):
        errors.append(f"{where} observations requires an explicit-offset 'observed_at' timestamp")
    if observations.get("scope") not in ("full", "sampled"):
        errors.append(f"{where} observations scope must be full or sampled")
    count = observations.get("row_count")
    if not _is_int(count) or count < 0:
        errors.append(f"{where} observations row_count must be a non-negative integer")
    errors.extend(_string_list_errors(
        f"{where} observations candidate_keys", observations.get("candidate_keys")))
    columns = observations.get("columns")
    if not isinstance(columns, dict):
        errors.append(f"{where} observations columns must be a mapping")
    else:
        for name, stats in columns.items():
            spot = f"{where} observations columns[{name!r}]"
            if (
                not _non_empty_str(name) or not isinstance(stats, dict)
                or set(stats) != {"null_count", "distinct_count"}
                or any(not _is_int(stats.get(key)) or stats[key] < 0
                       for key in ("null_count", "distinct_count"))
            ):
                errors.append(f"{spot} must carry non-negative integer null_count/distinct_count")
    errors.extend(_resource_uri_errors(
        f"{where} observations citation", observations.get("citation"), kinds=("table",)))
    if "value_evidence" in observations:
        errors.extend(_value_evidence_errors(
            f"{where} observations value_evidence", observations["value_evidence"]))
    if "source_binding" in observations and not _non_empty_str(observations["source_binding"]):
        errors.append(f"{where} observations source_binding must be a non-empty string")
    return errors


def _dataset_ariadne_errors(where: str, block: object) -> list[str]:
    """The dataset ``ariadne.tables`` links to exactly the documented tables."""
    if not isinstance(block, dict):
        return [f"{where} must be a mapping"]
    errors: list[str] = []
    unknown = sorted(set(block) - _DATASET_ARIADDE_KEYS)
    if unknown:
        errors.append(f"{where} carries unsupported field(s) {unknown}")
    tables = block.get("tables")
    if not isinstance(tables, list):
        errors.append(f"{where} tables must be an ordered list of table resources")
    else:
        for index, table in enumerate(tables):
            errors.extend(_resource_uri_errors(f"{where} tables[{index}]", table, kinds=("table",)))
    return errors


def _native_source_entry_errors(where: str, index: int, entry: object) -> list[str]:
    spot = f"{where} sources[{index}]"
    if isinstance(entry, str):
        if not entry.strip():
            return [f"{spot} must be a non-empty identity"]
        return []
    if not isinstance(entry, dict):
        return [f"{spot} must be a mapping or string"]
    unknown = sorted(set(entry) - NATIVE_SOURCE_KEYS)
    if unknown:
        return [f"{spot} carries unsupported field(s) {unknown}"]
    if "resource" in entry:
        resource = entry["resource"]
        if isinstance(resource, str) and resource.startswith("ariadne://"):
            return _resource_uri_errors(f"{spot} resource", resource, kinds=("table", "collection"))
        if not _non_empty_str(resource) or resource.startswith("/") or "://" in resource:
            return [f"{spot} resource must be a relative bundle path or canonical Ariadne Resource"]
    return []


def native_metadata_errors(where: str, native: object, *, kind: str | None = None) -> list[str]:
    """Validate the supported native metadata families of one profile.

    ``where`` is the named safe path of the ``native`` slot; ``kind`` is the
    envelope kind, used for per-kind required fields, the envelope/native
    kind agreement, and per-kind ``ariadne`` block validation. Optional
    families are validated exactly when supplied. Pure: no I/O, no payload
    interpretation.
    """
    if native is None:
        return [f"{where} is null — a profiled page retains its native metadata"]
    if not isinstance(native, dict):
        return [f"{where} must be a mapping, got {type(native).__name__}"]
    errors: list[str] = []
    native_type = native.get("type")
    # C6 quality-profile amendment (spec0009 §9): `ariadne_quality` is a
    # kind-scoped OPTIONAL native field of TABLE profile pages only; every
    # other kind still refuses it as an unsupported field.
    allowed_keys = set(NATIVE_KEYS)
    if kind == "table" or native_type == "table":
        allowed_keys.add("ariadne_quality")
    unknown = sorted(set(native) - allowed_keys)
    if unknown:
        errors.append(f"{where} carries unsupported native field(s) {unknown}")
    if "type" in native:
        if not isinstance(native_type, str) or native_type not in NATIVE_TYPES:
            errors.append(f"{where} type must be one of {sorted(NATIVE_TYPES)}")
    if (
        kind is not None
        and isinstance(native_type, str)
        and native_type in NATIVE_TYPES
        and native_type != kind
    ):
        errors.append(f"{where} type {native_type!r} contradicts the envelope kind {kind!r}")
    # Per-kind required native fields (validated when the kind is known and
    # the type is not itself malformed).
    if (
        kind is not None
        and kind in NATIVE_REQUIRED_FIELDS
        and (native_type is None or native_type == kind)
    ):
        for key in NATIVE_REQUIRED_FIELDS[kind]:
            if key not in native:
                errors.append(f"{where} {kind} pages require native '{key}'")
    for key in ("title", "description"):
        if key in native and not isinstance(native[key], str):
            errors.append(f"{where} {key} must be a string")
    # Optional list families: validated exactly when supplied (F1).
    if "tags" in native:
        errors.extend(_string_list_errors(f"{where} tags", native["tags"]))
    if "aliases" in native:
        errors.extend(_string_list_errors(f"{where} aliases", native["aliases"]))
    if "dimensions" in native:
        errors.extend(_string_list_errors(f"{where} dimensions", native["dimensions"]))
    if "sources" in native:
        sources = native["sources"]
        if not isinstance(sources, list):
            errors.append(f"{where} sources must be a list")
        else:
            for index, entry in enumerate(sources):
                errors.extend(_native_source_entry_errors(where, index, entry))
    footnote_ids = (
        frozenset(
            entry["id"]
            for entry in native["sources"]
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        )
        if isinstance(native.get("sources"), list)
        else frozenset()
    )
    if "resource" in native:
        expected_kinds = ("collection",) if kind == "dataset" else ("table",)
        errors.extend(
            _resource_uri_errors(f"{where} resource", native["resource"], kinds=expected_kinds)
        )
    for key in ("status", "attestation", "attester", "runtime", "governed_by"):
        if key in native and not _non_empty_str(native[key]):
            errors.append(f"{where} {key} must be a non-empty string")
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
    if "observed_value_columns" in native:
        selection = native["observed_value_columns"]
        if selection is not None:
            if not isinstance(selection, dict) or not all(
                _non_empty_str(column) and _non_empty_str(type_name)
                for column, type_name in selection.items()
            ):
                errors.append(
                    f"{where} observed_value_columns must map column names to "
                    "selected catalog types (both non-empty strings)"
                )
    if "dataset_sources" in native:
        errors.extend(_string_list_errors(f"{where} dataset_sources", native["dataset_sources"]))
    if kind == "computation" or native_type == "computation":
        attester = native.get("attester")
        if not _non_empty_str(attester) and native.get("attestation") != "pending":
            errors.append(
                f"{where} computation pages require 'attester' or the honest "
                "'attestation: pending' state"
            )
    if kind == "answer_example" or native_type == "answer_example":
        errors.extend(_answer_example_native_errors(where, native))
    if "ariadne" in native:
        block = native["ariadne"]
        if kind == "reference" or native_type == "reference":
            errors.extend(_extension_errors(f"{where} ariadne", block, footnote_ids))
        elif kind == "table" or native_type == "table":
            errors.extend(_table_ariadne_errors(f"{where} ariadne", block))
        elif kind == "dataset" or native_type == "dataset":
            errors.extend(_dataset_ariadne_errors(f"{where} ariadne", block))
        else:
            errors.append(
                f"{where} ariadne carries a reference/table/dataset metadata block — "
                "unsupported for this kind"
            )
    if (kind == "table" or native_type == "table") and "ariadne_quality" in native:
        errors.extend(
            _table_quality_native_errors(
                f"{where} ariadne_quality",
                native["ariadne_quality"],
                resource=native.get("resource"),
                sources=native.get("sources"),
            )
        )
    if "ariadne_evidence" in native:
        errors.extend(_evidence_errors(f"{where} ariadne_evidence", native["ariadne_evidence"]))
    return errors


def _answer_example_native_errors(where: str, native: dict) -> list[str]:
    """Structural validation of the producer-owned Answer Example families
    (spec0035 C4). The retained field meanings are Ariadne specs 0007/0023;
    this gate checks shapes, string types and the published size bound only —
    never meaning, consent, citation resolution or execution authority, which
    stay Core-side. Pure: no I/O."""
    errors: list[str] = []
    unknown = sorted(
        set(native)
        - _ANSWER_EXAMPLE_KEYS
        - _ANSWER_EXAMPLE_OPTIONAL_KEYS
        - set(NATIVE_REQUIRED_FIELDS["answer_example"])
        - {"type"}
    )
    if unknown:
        errors.append(f"{where} carries unsupported answer_example field(s) {unknown}")
    for key in ("question", "interpretation"):
        if not _non_empty_str(native.get(key)):
            errors.append(f"{where} {key} must be a non-empty string")
    method = native.get("method")
    if not isinstance(method, dict) or set(method) != {"operation", "arguments"}:
        errors.append(
            f"{where} method must be a mapping with exactly {{operation, arguments}}"
        )
    else:
        if not isinstance(method["operation"], str) or (
            method["operation"] not in _ANSWER_EXAMPLE_OPERATIONS
        ):
            errors.append(
                f"{where} method.operation must be one of "
                f"{sorted(_ANSWER_EXAMPLE_OPERATIONS)} (never standalone SQL)"
            )
        arguments = method["arguments"]
        if (
            not isinstance(arguments, dict)
            or not arguments
            or not all(_json_shaped(value) for value in arguments.values())
        ):
            errors.append(
                f"{where} method.arguments must be a non-empty mapping of "
                "JSON-shaped structured values (the arguments the named operation takes)"
            )
    if "parameters" in native and not _json_shaped(native["parameters"]):
        errors.append(f"{where} parameters must be a JSON-shaped mapping")
    if "project" in native and not _non_empty_str(native["project"]):
        errors.append(f"{where} project must be a non-empty string")
    submitter = native.get("submitter")
    if not isinstance(submitter, dict) or set(submitter) != {"identity", "attestation"}:
        errors.append(
            f"{where} submitter must be a mapping with exactly {{identity, attestation}}"
        )
    elif not _non_empty_str(submitter["identity"]) or not _non_empty_str(
        submitter["attestation"]
    ):
        errors.append(
            f"{where} submitter identity and attestation must be non-empty strings"
        )
    citations = native.get("citations")
    if not isinstance(citations, list):
        errors.append(f"{where} citations must be a list of {{path, sha256}} mappings")
    else:
        for index, entry in enumerate(citations):
            if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
                errors.append(
                    f"{where} citations[{index}] must be exactly {{path, sha256}}"
                )
                continue
            if not _non_empty_str(entry["path"]):
                errors.append(f"{where} citations[{index}].path must be a non-empty string")
            if not isinstance(entry["sha256"], str) or not _ANSWER_EXAMPLE_SHA256_RE.fullmatch(
                entry["sha256"]
            ):
                errors.append(
                    f"{where} citations[{index}].sha256 must be a 64-hex digest"
                )
    if "sql_provenance" in native:
        provenance = native["sql_provenance"]
        if not isinstance(provenance, dict) or set(provenance) != {"source", "text"}:
            errors.append(
                f"{where} sql_provenance must be a mapping with exactly {{source, text}}"
            )
        else:
            if provenance["source"] != _ANSWER_EXAMPLE_SQL_SOURCE:
                errors.append(
                    f"{where} sql_provenance.source must be the fixed descriptor "
                    f"{_ANSWER_EXAMPLE_SQL_SOURCE!r} (never a verified execution origin)"
                )
            if not isinstance(provenance["text"], str) or not provenance["text"].strip():
                errors.append(
                    f"{where} sql_provenance.text must be a non-whitespace string"
                )
    answer = native.get("answer")
    if not isinstance(answer, dict) or set(answer) != {"captured", "excerpt", "result_digest"}:
        errors.append(
            f"{where} answer must be a mapping with exactly "
            "{captured, excerpt, result_digest}"
        )
    else:
        if not _non_empty_str(answer["captured"]):
            errors.append(f"{where} answer.captured must be a non-empty string")
        excerpt = answer["excerpt"]
        if not isinstance(excerpt, str):
            errors.append(f"{where} answer.excerpt must be a string")
        elif len(excerpt.encode("utf-8")) > _ANSWER_EXAMPLE_EXCERPT_BYTES:
            errors.append(
                f"{where} answer.excerpt exceeds the "
                f"{_ANSWER_EXAMPLE_EXCERPT_BYTES}-byte bound"
            )
        if not isinstance(answer["result_digest"], str) or not _ANSWER_EXAMPLE_SHA256_RE.fullmatch(
            answer["result_digest"]
        ):
            errors.append(f"{where} answer.result_digest must be a 64-hex digest")
    return errors


# --- C6 quality-profile amendment (spec0009 §9, owner-approved 2026-11-12):
# the OPTIONAL `ariadne_quality` native field of TABLE profile pages, with
# structural validation ONLY. The closed v1 grammar is retained 1:1 from the
# approved Ariadne source-quality contract (spec0013 r2 + the Core validator's
# closed constants); K checks shape, types, bounds, vocabularies and the
# binding-local asset/citation rules — never meaning, freshness interpretation,
# applicability, execution authority or query refusal, which stay Core-side
# advisory meaning. Reports are SUPPLIED CLAIMS, never authenticated execution
# or current healthy state. Pure: no I/O, no dependency, never imports Ariadne.
ARIADNE_QUALITY_VERSION = 1
QUALITY_MAX_REPORTS = 8
QUALITY_MAX_CHECKS = 8
QUALITY_MAX_SOURCE_IDS = 8
QUALITY_MAX_ID_CHARS = 128  # id/source-version value/field/actor strings
QUALITY_MAX_TEXT_CHARS = 1024  # description/criterion/population/meaning/provenance
QUALITY_MAX_CADENCE_CHARS = 256
QUALITY_MAX_UNITS_CHARS = 64  # units/timezone
QUALITY_MAX_BYTES = 8192  # the normalized (disclosed compact JSON) profile bound
_QUALITY_ROOT_KEYS = frozenset({"version", "reports"})
_QUALITY_REPORT_KEYS = frozenset(
    {
        "id",
        "asset",
        "source_ids",
        "scope",
        "reported_at",
        "observed_at",
        "source_version",
        "provenance",
        "reported_by",
        "cadence",
        "valid_until",
        "checks",
        "watermark",
    }
)
_QUALITY_REPORT_OPTIONAL_KEYS = frozenset(
    {
        "observed_at",
        "source_version",
        "provenance",
        "reported_by",
        "cadence",
        "valid_until",
        "watermark",
    }
)
_QUALITY_SCOPE_KEYS = frozenset({"kind", "description", "population", "period"})
_QUALITY_PERIOD_KEYS = frozenset({"field", "start", "end"})
_QUALITY_SOURCE_VERSION_KEYS = frozenset({"kind", "value"})
_QUALITY_CHECK_KEYS = frozenset(
    {"id", "kind", "outcome", "criterion", "tested_population", "tested_period"}
)
_QUALITY_WATERMARK_KEYS = frozenset(
    {"kind", "value", "field", "meaning", "units", "timezone", "observed_at"}
)
_QUALITY_SCOPE_KINDS = ("asset", "subset")
_QUALITY_SOURCE_VERSION_KINDS = ("snapshot", "version")
_QUALITY_CHECK_OUTCOMES = ("pass", "fail", "unknown")
_QUALITY_WATERMARK_KINDS = ("event_time", "ingestion_time", "snapshot_as_of", "other")


def _quality_aware_instant(value: object, where: str) -> tuple[datetime | None, list[str]]:
    """Parse one OPTIONAL aware ISO-8601 instant. Naive datetimes, plain dates
    and non-temporal values reject with a NAMED field diagnostic — never an
    invented timezone and never a crash."""
    if value is None:
        return None, []
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None, [f"{where} is not a valid ISO-8601 instant"]
    else:
        return None, [
            f"{where} must be an ISO-8601 instant string with an explicit UTC "
            "offset (a plain date is not an instant)"
        ]
    if not isinstance(parsed, datetime) or parsed.utcoffset() is None:
        return None, [
            f"{where} must carry an explicit UTC offset (naive datetimes and "
            "plain dates are rejected)"
        ]
    return parsed, []


def _quality_period_errors(period: object, where: str) -> list[str]:
    """The closed `{field, start, end}` declared-evidence period with aware
    instants ordered ``start < end`` (the retained spec0013 §2 authoring rule:
    the period is interpreted ``[start, end)``); an explicit null is the
    declared non-time-bounded form (omission is not a declaration — the
    requiring caller owns that rule). Pure structural chronology between the
    two declared bounds — no Core import, no dynamic freshness."""
    if period is None:
        return []
    if not isinstance(period, dict):
        return [f"{where} must be {{field, start, end}} or an explicit null"]
    errors: list[str] = []
    unknown = sorted(set(period) - _QUALITY_PERIOD_KEYS)
    if unknown:
        errors.append(f"{where} carries unsupported field(s) {unknown}")
    field = period.get("field")
    if not isinstance(field, str) or not field.strip():
        errors.append(f"{where} field must be a non-empty string")
    elif len(field) > QUALITY_MAX_ID_CHARS:
        errors.append(f"{where} field exceeds its {QUALITY_MAX_ID_CHARS}-character bound")
    start, start_errors = _quality_aware_instant(period.get("start"), f"{where} start")
    errors.extend(start_errors)
    end, end_errors = _quality_aware_instant(period.get("end"), f"{where} end")
    errors.extend(end_errors)
    if start is not None and end is not None and not start < end:
        errors.append(f"{where} must satisfy start < end (interpreted [start, end))")
    return errors


def _table_quality_native_errors(
    where: str, profile: object, *, resource: object, sources: object
) -> list[str]:
    """Structural validation of the OPTIONAL `ariadne_quality` native field of
    one TABLE profile page (spec0009 §9 quality-profile amendment, owner-
    approved 2026-11-12). The closed v1 grammar is retained 1:1 from the
    approved Ariadne source-quality contract: closed keys, exact version,
    count/length/byte bounds, closed vocabularies, duplicate-ID detection and
    the binding-local rules — each report's `asset` must equal the containing
    page's canonical `native.resource`, and `source_ids` must resolve to the
    page's actual `sources[].id` entries, every selected source declaring a
    nonempty `resource`. Reports are SUPPLIED CLAIMS: no meaning, freshness
    interpretation, applicability, execution authority or query refusal is
    evaluated here (Core-side advisory meaning). Pure: no I/O."""
    if not isinstance(profile, dict):
        return [f"{where} must be a mapping"]
    errors: list[str] = []
    normalized = json.dumps(
        disclose_native(profile), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    normalized_bytes = len(normalized.encode("utf-8"))
    if normalized_bytes > QUALITY_MAX_BYTES:
        errors.append(
            f"{where} exceeds its {QUALITY_MAX_BYTES}-UTF-8-byte normalized bound "
            f"(disclosed compact form is {normalized_bytes} bytes)"
        )
    unknown = sorted(set(profile) - _QUALITY_ROOT_KEYS)
    if unknown:
        errors.append(
            f"{where} carries unsupported field(s) {unknown} — the profile is a "
            "closed declaration with no sql/script/command or other executable "
            "payload field; descriptions are inert text"
        )
    version = profile.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != ARIADNE_QUALITY_VERSION
    ):
        errors.append(
            f"{where} version must be the exact integer {ARIADNE_QUALITY_VERSION}, "
            f"got {version!r}"
        )
    reports = profile.get("reports")
    if not isinstance(reports, list):
        return errors + [f"{where} reports must be a list"]
    if len(reports) > QUALITY_MAX_REPORTS:
        errors.append(
            f"{where} carries {len(reports)} reports — at most {QUALITY_MAX_REPORTS} "
            "are declared per page"
        )
    binding = resource if isinstance(resource, str) else None
    citation_resources: dict[str, str | None] = {}
    if isinstance(sources, list):
        for source in sources:
            if isinstance(source, dict) and isinstance(source.get("id"), str):
                entry_resource = source.get("resource")
                citation_resources[source["id"]] = (
                    entry_resource if isinstance(entry_resource, str) else None
                )
    report_ids: set[str] = set()
    for position, report in enumerate(reports):
        spot = f"{where} reports[{position}]"
        if not isinstance(report, dict):
            errors.append(f"{spot} must be a mapping")
            continue
        unknown = sorted(set(report) - _QUALITY_REPORT_KEYS)
        if unknown:
            errors.append(
                f"{spot} carries unsupported field(s) {unknown} — the profile is a "
                "closed declaration with no sql/script/command or other executable "
                "payload field; descriptions are inert text"
            )
        missing = sorted(_QUALITY_REPORT_KEYS - _QUALITY_REPORT_OPTIONAL_KEYS - set(report))
        if missing:
            errors.append(f"{spot} requires field(s) {missing}")
        identifier = report.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{spot} id must be a nonempty stable string")
        elif len(identifier) > QUALITY_MAX_ID_CHARS:
            errors.append(f"{spot} id exceeds its {QUALITY_MAX_ID_CHARS}-character bound")
        elif identifier in report_ids:
            errors.append(
                f"{spot} duplicates report id {identifier!r} — report IDs are "
                "stable: repeated findings update the same declaration"
            )
        else:
            report_ids.add(identifier)
        if isinstance(binding, str) and binding and report.get("asset") != binding:
            errors.append(
                f"{spot} asset must equal the containing page's canonical resource "
                f"binding {binding!r} — a report is tied to its page's exact asset, "
                "never a display-name match"
            )
        source_ids = report.get("source_ids")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or len(source_ids) > QUALITY_MAX_SOURCE_IDS
            or not all(isinstance(source_id, str) and source_id for source_id in source_ids)
        ):
            errors.append(
                f"{spot} source_ids must be a nonempty list of at most "
                f"{QUALITY_MAX_SOURCE_IDS} citation ids"
            )
        else:
            unresolved = [s for s in source_ids if s not in citation_resources]
            if unresolved:
                errors.append(
                    f"{spot} source_ids {unresolved} resolves to no page sources[] "
                    "citation — supplied evidence cites the page's actual sources"
                )
            resourceless = [s for s in source_ids if not citation_resources.get(s)]
            if resourceless:
                errors.append(
                    f"{spot} source_ids {resourceless} cite a source without a "
                    "resource — a citation is an identity, and needs one"
                )
        scope = report.get("scope")
        if not isinstance(scope, dict):
            errors.append(f"{spot} scope must be {{kind, description, population, period}}")
        else:
            unknown = sorted(set(scope) - _QUALITY_SCOPE_KEYS)
            if unknown:
                errors.append(f"{spot} scope carries unsupported field(s) {unknown}")
            if scope.get("kind") not in _QUALITY_SCOPE_KINDS:
                errors.append(
                    f"{spot} scope kind must be one of {list(_QUALITY_SCOPE_KINDS)}, "
                    f"got {scope.get('kind')!r}"
                )
            for key in ("description", "population"):
                value = scope.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{spot} scope {key} must be a non-empty string")
                elif len(value) > QUALITY_MAX_TEXT_CHARS:
                    errors.append(
                        f"{spot} scope {key} exceeds its {QUALITY_MAX_TEXT_CHARS}-character bound"
                    )
            missing = sorted(_QUALITY_SCOPE_KEYS - set(scope))
            if missing:
                errors.append(
                    f"{spot} scope requires field(s) {missing} — period is null only "
                    "when non-time-bounded evidence is EXPLICITLY declared; "
                    "omission is not a declaration"
                )
            errors.extend(_quality_period_errors(scope.get("period"), f"{spot} scope period"))
        reported_at, reported_errors = _quality_aware_instant(
            report.get("reported_at"), f"{spot} reported_at"
        )
        errors.extend(reported_errors)
        if "observed_at" in report:
            _, observed_errors = _quality_aware_instant(
                report.get("observed_at"), f"{spot} observed_at"
            )
            errors.extend(observed_errors)
        if "valid_until" in report:
            valid_until, valid_errors = _quality_aware_instant(
                report.get("valid_until"), f"{spot} valid_until"
            )
            errors.extend(valid_errors)
            if (
                not valid_errors
                and reported_at is not None
                and valid_until is not None
                and valid_until < reported_at
            ):
                errors.append(f"{spot} valid_until must not precede reported_at")
        if "source_version" in report:
            source_version = report.get("source_version")
            if not isinstance(source_version, dict):
                errors.append(f"{spot} source_version must be {{kind, value}}")
            else:
                unknown = sorted(set(source_version) - _QUALITY_SOURCE_VERSION_KEYS)
                if unknown:
                    errors.append(f"{spot} source_version carries unsupported field(s) {unknown}")
                if source_version.get("kind") not in _QUALITY_SOURCE_VERSION_KINDS:
                    errors.append(
                        f"{spot} source_version kind must be one of "
                        f"{list(_QUALITY_SOURCE_VERSION_KINDS)}, got {source_version.get('kind')!r}"
                    )
                value = source_version.get("value")
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{spot} source_version value must be a non-empty string")
                elif len(value) > QUALITY_MAX_ID_CHARS:
                    errors.append(
                        f"{spot} source_version value exceeds its "
                        f"{QUALITY_MAX_ID_CHARS}-character bound"
                    )
        for key, cap in (
            ("provenance", QUALITY_MAX_TEXT_CHARS),
            ("reported_by", QUALITY_MAX_ID_CHARS),
            ("cadence", QUALITY_MAX_CADENCE_CHARS),
        ):
            if key in report:
                value = report.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{spot} {key} must be a non-empty string")
                elif len(value) > cap:
                    errors.append(f"{spot} {key} exceeds its {cap}-character bound")
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"{spot} requires a nonempty checks list")
        elif len(checks) > QUALITY_MAX_CHECKS:
            errors.append(
                f"{spot} carries {len(checks)} checks — at most {QUALITY_MAX_CHECKS} "
                "are declared per report"
            )
        else:
            for index, check in enumerate(checks):
                check_spot = f"{spot} checks[{index}]"
                if not isinstance(check, dict):
                    errors.append(f"{check_spot} must be a mapping")
                    continue
                unknown = sorted(set(check) - _QUALITY_CHECK_KEYS)
                if unknown:
                    errors.append(f"{check_spot} carries unsupported field(s) {unknown}")
                missing = sorted(_QUALITY_CHECK_KEYS - set(check))
                if missing:
                    errors.append(f"{check_spot} requires field(s) {missing}")
                identifier = check.get("id")
                if not isinstance(identifier, str) or not identifier.strip():
                    errors.append(f"{check_spot} id must be a non-empty string")
                elif len(identifier) > QUALITY_MAX_ID_CHARS:
                    errors.append(
                        f"{check_spot} id exceeds its {QUALITY_MAX_ID_CHARS}-character bound"
                    )
                check_kind = check.get("kind")
                if not isinstance(check_kind, str) or not check_kind.strip():
                    errors.append(f"{check_spot} kind must be a non-empty string")
                elif len(check_kind) > QUALITY_MAX_ID_CHARS:
                    errors.append(
                        f"{check_spot} kind exceeds its {QUALITY_MAX_ID_CHARS}-character bound"
                    )
                if check.get("outcome") not in _QUALITY_CHECK_OUTCOMES:
                    errors.append(
                        f"{check_spot} outcome must be one of "
                        f"{list(_QUALITY_CHECK_OUTCOMES)}, got {check.get('outcome')!r}"
                    )
                criterion = check.get("criterion")
                if not isinstance(criterion, str) or not criterion.strip():
                    errors.append(f"{check_spot} criterion must be a non-empty string")
                elif len(criterion) > QUALITY_MAX_TEXT_CHARS:
                    errors.append(
                        f"{check_spot} criterion exceeds its "
                        f"{QUALITY_MAX_TEXT_CHARS}-character bound"
                    )
                tested_population = check.get("tested_population")
                if tested_population is not None:
                    if not isinstance(tested_population, str) or not tested_population.strip():
                        errors.append(
                            f"{check_spot} tested_population must be a non-empty string or null"
                        )
                    elif len(tested_population) > QUALITY_MAX_TEXT_CHARS:
                        errors.append(
                            f"{check_spot} tested_population exceeds its "
                            f"{QUALITY_MAX_TEXT_CHARS}-character bound"
                        )
                errors.extend(
                    _quality_period_errors(
                        check.get("tested_period"), f"{check_spot} tested_period"
                    )
                )
        if "watermark" in report:
            watermark = report.get("watermark")
            if not isinstance(watermark, dict):
                errors.append(f"{spot} watermark must be a mapping")
            else:
                unknown = sorted(set(watermark) - _QUALITY_WATERMARK_KEYS)
                if unknown:
                    errors.append(f"{spot} watermark carries unsupported field(s) {unknown}")
                if watermark.get("kind") not in _QUALITY_WATERMARK_KINDS:
                    errors.append(
                        f"{spot} watermark kind must be one of "
                        f"{list(_QUALITY_WATERMARK_KINDS)}, got {watermark.get('kind')!r}"
                    )
                watermark_value = watermark.get("value")
                if watermark.get("kind") in ("event_time", "ingestion_time", "snapshot_as_of"):
                    _, value_errors = _quality_aware_instant(
                        watermark_value, f"{spot} watermark value"
                    )
                    errors.extend(value_errors)
                elif watermark_value is not None and (
                    isinstance(watermark_value, bool)
                    or not isinstance(watermark_value, (int, float, str))
                    or (isinstance(watermark_value, float) and not math.isfinite(watermark_value))
                ):
                    errors.append(
                        f"{spot} watermark value must be a finite scalar with its stated meaning"
                    )
                for key, cap in (
                    ("field", QUALITY_MAX_ID_CHARS),
                    ("meaning", QUALITY_MAX_TEXT_CHARS),
                    ("units", QUALITY_MAX_UNITS_CHARS),
                    ("timezone", QUALITY_MAX_UNITS_CHARS),
                ):
                    if key in watermark and watermark.get(key) is not None:
                        wm_value = watermark.get(key)
                        if not isinstance(wm_value, str) or not wm_value.strip():
                            errors.append(
                                f"{spot} watermark {key} must be a non-empty string or null"
                            )
                        elif len(wm_value) > cap:
                            errors.append(
                                f"{spot} watermark {key} exceeds its {cap}-character bound"
                            )
                if "observed_at" in watermark:
                    _, wm_errors = _quality_aware_instant(
                        watermark.get("observed_at"), f"{spot} watermark observed_at"
                    )
                    errors.extend(wm_errors)
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
    if not isinstance(kind, str) or kind not in ARIADNE_PROFILE_KINDS:
        errors.append(f"{spot} kind must be one of {sorted(ARIADNE_PROFILE_KINDS)}, got {kind!r}")
        kind = None  # per-kind requirements are not decidable; do not cascade
    else:
        if kind in KINDS_REQUIRING_REQUIRED_POLICIES and "required_policies" not in raw:
            errors.append(
                f"{spot} kind {kind!r} requires an explicit required_policies list "
                "(even when empty)"
            )
        if kind in KINDS_REQUIRING_METRIC_REF and "metric_ref" not in raw:
            errors.append(f"{spot} kind {kind!r} requires metric_ref")
        if kind in KINDS_REQUIRING_CORE_REF and "core_ref" not in raw:
            errors.append(f"{spot} kind {kind!r} requires core_ref")
    native = raw.get("native")
    if "native" not in raw:
        errors.append(f"{spot} requires its native metadata slot")
    errors.extend(native_metadata_errors(f"{spot}.native", native, kind=kind))
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
        else:
            if entry["kind"] == "resource":
                id_errors = _resource_uri_errors(
                    f"{spot} core_ref id", entry["id"], kinds=("table", "collection")
                )
                errors.extend(id_errors)
                if not id_errors:
                    core_ref = AriadneCoreReference(kind="resource", id=str(entry["id"]))
            elif not _non_empty_str(entry["id"]):
                errors.append(f"{spot} core_ref id must be a non-empty identity string")
            else:
                core_ref = AriadneCoreReference(kind="semantic", id=str(entry["id"]))
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
                elif str(entry["revision"]).strip().lower() in FLOATING_REVISIONS:
                    errors.append(
                        f"{place} names floating revision {entry['revision']!r} — an "
                        "ontology reference pins an immutable revision"
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
# Policy Closure and candidate validation (typed edges only, scope first).
# ---------------------------------------------------------------------------


def _native_policy_paths(page: CompiledPage) -> list[str]:
    """Retained native Policy path references of one page (provenance)."""
    profile = page.ariadne_profile
    if profile is None:
        return []
    paths: list[str] = []
    sources = profile.native.get("sources")
    if isinstance(sources, list):
        for entry in sources:
            resource = entry.get("resource") if isinstance(entry, dict) else entry
            if isinstance(resource, str) and resource.startswith("policies/"):
                paths.append(resource)
    governed_by = profile.native.get("governed_by")
    if isinstance(governed_by, str) and governed_by.startswith("policies/"):
        paths.append(governed_by)
    return sorted(set(paths))


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
    Source references never contribute. In reader mode (``scope`` given) the
    visibility gate runs BEFORE any existence/kind lookup of a target: an
    out-of-scope dependency refuses GENERICALLY, never disclosing the hidden
    page's existence, kind, path or position.
    """
    by_entity = {page.id: page for page in pages if page.id}
    allowed = set(scope) if scope is not None else None
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
        if allowed is not None and (target.visibility or "") not in allowed:
            # Reader-safe: the hidden page's title, text, kind and position
            # are never disclosed — only that the closure cannot be served.
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "out-of-scope",
                    "the required Policy Closure contains a dependency outside the "
                    "authorized visibility scope",
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
        ordered.append(reference)
        queue.extend(target_profile.required_policies)
        queue.sort(key=lambda ref: (ref.namespace, ref.entity_id))
    return tuple(ordered), tuple(diagnostics)


def _parse_ariadne_context_control(
    raw: object, control_bytes: bytes,
) -> tuple[AriadneContextControl | None, list[str]]:
    """Parse the optional canonical application block; no external authority or I/O."""
    import yaml

    errors: list[str] = []
    # The normal safe YAML decoder collapses duplicate keys. Inspect only this
    # block's fixed-depth maps so ambiguous declarations cannot become last-wins.
    root = yaml.compose(control_bytes, Loader=yaml.SafeLoader)
    if isinstance(root, yaml.MappingNode):
        blocks = [value for key, value in root.value
                  if isinstance(key, yaml.ScalarNode) and key.value == "ariadne_context"]
        if len(blocks) != 1:
            errors.append("ariadne_context is declared more than once")
        maps = [(node, "ariadne_context", 0) for node in blocks]
        while maps:
            node, path, depth = maps.pop()
            if not isinstance(node, yaml.MappingNode):
                continue
            seen: set[str] = set()
            for key, value in node.value:
                if not isinstance(key, yaml.ScalarNode):
                    continue
                if key.value in seen:
                    errors.append(f"{path} has duplicate declaration {key.value!r}")
                seen.add(key.value)
                if (depth == 0 and key.value == "ontology_catalog") or depth == 1:
                    maps.append((value, f"{path}.{key.value}", depth + 1))
    if not isinstance(raw, dict) or set(raw) != {"version", "ontology_catalog"}:
        return None, [*errors, "ariadne_context requires exactly version and ontology_catalog"]
    if type(raw["version"]) is not int or raw["version"] != 1:
        errors.append("ariadne_context.version must be the exact integer 1")
    catalog = raw["ontology_catalog"]
    if not isinstance(catalog, dict):
        return None, [*errors, "ariadne_context.ontology_catalog must be a mapping"]
    for namespace, identifiers in catalog.items():
        spot = f"ariadne_context.ontology_catalog[{namespace!r}]"
        if not _non_empty_str(namespace) or not isinstance(identifiers, dict):
            errors.append(f"{spot} requires a non-empty namespace and an identifier mapping")
            continue
        for identifier, revision in identifiers.items():
            if not _non_empty_str(identifier) or not _non_empty_str(revision):
                errors.append(
                    f"{spot}[{identifier!r}] requires one exact non-empty revision string"
                )
            elif revision.strip().casefold() in FLOATING_REVISIONS:
                errors.append(f"{spot}[{identifier!r}] refuses floating revision {revision!r}")
    return (None, errors) if errors else (AriadneContextControl(1, catalog), [])


def _control_catalog(control: KnowledgeBaseControlFile | None) -> dict[str, dict[str, str]] | None:
    return control.ariadne_context.ontology_catalog if control and control.ariadne_context else None


def _ontology_errors(
    pages: Sequence[CompiledPage],
    catalog: Mapping[str, Mapping[str, str | Sequence[str]]] | None,
) -> list[AriadneProfileDiagnostic]:
    """Resolve declared ontology references against the pinned catalog scope.

    The catalog is structural data extracted from the candidate Control File
    (spec 0009 §4); floating revisions already refused at parse time;
    conflicting duplicate declarations are ambiguous and refuse.
    """
    diagnostics: list[AriadneProfileDiagnostic] = []
    declared: dict[tuple[str, str], set[str]] = {}
    for page in pages:
        profile = page.ariadne_profile
        if profile is None:
            continue
        for ref in profile.ontology_refs:
            declared.setdefault((ref.namespace, ref.identifier), set()).add(ref.revision)
    for (namespace, identifier), revisions in sorted(declared.items()):
        if len(revisions) > 1:
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    f"ontology target {namespace}::{identifier} is declared with "
                    f"conflicting revisions {sorted(revisions)} — an ambiguous "
                    "reference refuses",
                )
            )
    if catalog is None:
        for namespace, identifier in sorted(declared):
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    f"ontology reference {namespace}::{identifier} has no pinned "
                    "declared catalog to resolve against; supply the reviewed "
                    "catalog scope or remove the reference",
                )
            )
        return diagnostics
    for (namespace, identifier), revisions in sorted(declared.items()):
        allowed_ids = catalog.get(namespace)
        if not isinstance(allowed_ids, Mapping):
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    f"ontology reference {namespace}::{identifier} names an "
                    "undeclared target namespace in the pinned catalog",
                )
            )
            continue
        allowed_revisions = allowed_ids.get(identifier)
        if allowed_revisions is None:
            diagnostics.append(
                AriadneProfileDiagnostic(
                    "unresolved-reference",
                    f"ontology reference {namespace}::{identifier} is an unknown "
                    "target in the pinned declared catalog",
                )
            )
            continue
        for revision in sorted(revisions):
            if not isinstance(allowed_revisions, str) or revision != allowed_revisions:
                diagnostics.append(
                    AriadneProfileDiagnostic(
                        "unresolved-reference",
                        f"ontology reference {namespace}::{identifier} pins revision "
                        f"{revision!r}, which the declared catalog does not allow",
                    )
                )
    return diagnostics


def validate_ariadne_profiles(
    pages: Sequence[CompiledPage],
    *,
    namespace: str,
    scope: Sequence[str] | None = None,
    ontology_catalog: Mapping[str, Mapping[str, str | Sequence[str]]] | None = None,
) -> tuple[AriadneProfileDiagnostic, ...]:
    """Validate the complete profile set of one captured candidate.

    Envelope structure is validated at parse time (loader ValidationReport);
    this pass owns the cross-page contract: unique metric bindings, the
    complete kind-correct scope-aware required Policy Closure, retained
    native Policy path agreement and pinned ontology declarations. In reader
    mode (``scope``) authorization selects the visible roots BEFORE any
    lookup, expansion or diagnostic. ``ontology_catalog`` is extracted
    structural data, not publication authority. Hidden pages never produce or shape
    diagnostics, and unrelated hidden graphs never block a public reader.
    No database access, no payload execution.
    """
    diagnostics: list[AriadneProfileDiagnostic] = []
    profiled = [page for page in pages if page.ariadne_profile is not None]
    allowed = set(scope) if scope is not None else None
    visible = (
        profiled
        if allowed is None
        else [page for page in profiled if (page.visibility or "") in allowed]
    )
    by_path = {page.path: page for page in pages if page.path}
    metric_binding_owner: dict[tuple[str, str], str] = {}
    for page in visible:
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
                        path=page.path,
                    )
                )
            else:
                metric_binding_owner[binding] = page.id
    for page in visible:
        profile = page.ariadne_profile
        assert profile is not None
        closure, closure_diagnostics = policy_closure(
            pages, profile, namespace=namespace, scope=scope
        )
        closure_ids = {reference.entity_id for reference in closure}
        for diagnostic in closure_diagnostics:
            diagnostics.append(
                AriadneProfileDiagnostic(
                    diagnostic.category,
                    f"{page.path}: {diagnostic.message}",
                    path=page.path,
                )
            )
        # Only metrics' retained native Policy references govern their typed
        # closure; other pages' sources remain provenance (spec 0009 §4).
        if profile.kind != "metric":
            continue
        for path in _native_policy_paths(page):
            target = by_path.get(path)
            if target is None:
                diagnostics.append(
                    AriadneProfileDiagnostic(
                        "unresolved-reference",
                        f"{page.path}: retained native policy reference {path!r} "
                        "resolves to no page in the selected Knowledge Base",
                        path=page.path,
                    )
                )
                continue
            if allowed is not None and (target.visibility or "") not in allowed:
                diagnostics.append(
                    AriadneProfileDiagnostic(
                        "out-of-scope",
                        f"{page.path}: a retained native policy reference is outside "
                        "the authorized visibility scope",
                        path=page.path,
                    )
                )
                continue
            if target.id not in closure_ids:
                diagnostics.append(
                    AriadneProfileDiagnostic(
                        "unresolved-reference",
                        f"{page.path}: retained native policy reference {path!r} "
                        f"(entity {target.id!r}) contradicts the typed "
                        "required_policies closure — declare the typed edge or "
                        "repair the retained reference",
                        path=page.path,
                    )
                )
    diagnostics.extend(_ontology_errors(visible, ontology_catalog))
    return tuple(diagnostics)


# ---------------------------------------------------------------------------
# The immutable SDK view.
# ---------------------------------------------------------------------------


class ContextIdentity(msgspec.Struct, frozen=True):
    """The full expected identity of one published Context.

    Fingerprint alone is insufficient: the selected subtree, publication
    manifest digest and Source Reference Manifest digest bind the exact
    source/reference state separately (spec 0009 §5).
    """

    namespace: str
    profile_version: int
    published_version: str
    fingerprint: str
    publication_manifest_digest: str
    source_reference_digest: str
    subtree: str = ""
    scope: tuple[str, ...] = PUBLIC_VISIBILITY_SCOPE


def _freeze(value: Any) -> Any:
    """Recursively immutable view containers (dict → MappingProxyType,
    list → tuple). Scalars and ordering pass through unchanged."""
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def disclose_native(value: Any) -> Any:
    """Disclose a native value under the native JSON representation contract.

    Reverses the immutable view containers (proxy → dict, tuple → list) and
    converts YAML-native date/datetime scalars to ISO-8601 strings. No
    freshness, currency or receipt is invented by disclosure.
    """
    if isinstance(value, (MappingProxyType, dict)):
        return {str(key): disclose_native(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [disclose_native(item) for item in value]
    if isinstance(value, date):  # datetime included
        return value.isoformat()
    return value


class ContextPageView(msgspec.Struct, frozen=True):
    """One scope-filtered full page view with its exact citation.

    ``native`` and ``sources`` are deep-immutable view containers: compare
    through :func:`disclose_native` for JSON-shaped equality; direct mutation
    raises ``TypeError``.
    """

    namespace: str
    entity_id: str
    kind: str
    path: str
    content: str
    body: str
    body_start_line: int
    native: Any
    sources: tuple[Source, ...]
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


class PublishedContextPageMetadata(msgspec.Struct, frozen=True):
    """Immutable scoped navigation metadata for one visible page; no body.

    ``kind`` is the profile kind, or the explicit ``unprofiled`` label of an
    ordinary documentation page (never a technical validation claim). An
    absent advisory fact stays ``None`` (spec0009 navigation r3).
    """

    namespace: str
    entity_id: str
    path: str
    title: str
    kind: str
    published_version: str
    citation: str
    lifecycle: str | None
    review_after: str | None


class PublishedContextPage(PublishedContextPageMetadata):
    """One complete visible canonical page with immutable body and views.

    ``native`` is empty when the page is unprofiled; ``native`` and
    ``sources`` are deep-immutable view containers (compare through
    :func:`disclose_native`; direct mutation raises ``TypeError``).
    """

    content: str
    body: str
    body_start_line: int
    native: Any
    sources: tuple[Source, ...]


class PublishedContextSearchHit(msgspec.Struct, frozen=True):
    """One native lexical hit over the scope-filtered visible page set.

    ``snippet`` is the native compacted snippet; ``excerpt`` is the
    separately labeled verbatim canonical passage with inclusive 1-based
    canonical line numbers and the actual fence-aware section when the
    passage lies in the body (``None`` for a frontmatter passage). The
    completeness counters describe visible-only candidates.
    """

    page: PublishedContextPage
    score: float
    matched_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]
    snippet: str
    candidates_seen: int
    results_dropped: int
    excerpt: str
    line_start: int | None
    line_end: int | None
    section: str | None


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
    kb_root: str,
    revision: str,
    *,
    namespace: str,
    ontology_catalog: Mapping[str, Mapping[str, str | Sequence[str]]] | None = None,
) -> AriadneCandidateInspection:
    """Inspect one exact captured Authoring Revision (explicitly unadmitted).

    Reads only the exact Git blobs of the selected revision. The candidate's
    declared namespace must match ``namespace``. Inspection covers the
    complete captured candidate: page validation, cross-page profile
    validation and the structural Source Reference Manifest consistency
    available without private registry access. Operator review may inspect
    its own candidate normally, so no visibility filtering is applied here.
    The compatibility ``ontology_catalog`` argument may only agree with the
    declaration already captured from lumio.yaml; it cannot supply authority.
    """
    from lumio_wiki.git_authoring import capture_revision
    from lumio_wiki.source_references import validate_source_references

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
            _issue_category(issue),
            f"{issue.file}: {issue.field}: {issue.message}",
        )
        for issue in captured.report.issues
        if issue.severity == "error"
    ]
    diagnostics.extend(
        AriadneProfileDiagnostic("malformed", message)
        for message in validate_source_references(captured.manifest, captured.kb)
    )
    if ontology_catalog is not None and ontology_catalog != _control_catalog(captured.kb.control):
        diagnostics.append(AriadneProfileDiagnostic(
            "unresolved-reference",
            "caller ontology_catalog does not agree with the captured Control File declaration",
        ))
    return AriadneCandidateInspection(
        namespace=namespace,
        revision=captured.revision,
        subtree=captured.subtree,
        admitted=False,
        fingerprint=captured.fingerprint.digest,
        source_reference_manifest_digest=captured.manifest_digest,
        diagnostics=tuple(diagnostics),
    )


def _issue_category(issue: Any) -> str:
    """Map a loader ValidationIssue to its typed diagnostic category."""
    message = issue.message
    if "unsupported profile version" in message or "unsupported extension version" in message:
        return "unsupported"
    if "unsupported native field" in message or "unsupported field(s)" in message:
        return "unsupported"
    return "malformed"


def _page_view(
    page: CompiledPage,
    *,
    namespace: str,
    published_version: str,
    canonical_content: dict[str, bytes],
) -> ContextPageView:
    raw = canonical_content.get(page.path, b"")
    profile = page.ariadne_profile
    return ContextPageView(
        namespace=namespace,
        entity_id=page.id,
        kind=profile.kind if profile else "",
        path=page.path,
        content=raw.decode("utf-8", errors="replace"),
        body=page.body,
        body_start_line=page.body_start_line,
        native=_freeze(profile.native) if profile else MappingProxyType({}),
        sources=tuple(page.sources),
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


def _verify_local_admission(destination: Any, pinned: str, manifest: Any) -> None:
    """Reuse native exact manifest/receipt/sealed verification, without Git or current."""
    from pathlib import Path

    from lumio_wiki.git_authoring import _verify_version_complete

    try:
        checked, receipt, _sealed = _verify_version_complete(
            Path(destination).resolve(), pinned, manifest.fingerprint
        )
    except Exception as exc:
        # Private records and storage details are not reader diagnostics.
        raise UnadmittedInputError(
            f"Published Version {pinned!r} has no completed matching native admission"
        ) from exc
    if checked != manifest or not receipt.activated:
        raise UnadmittedInputError(
            f"Published Version {pinned!r} has inconsistent admission or incomplete activation"
        )


def _verify_s3_admission(metadata_store: Any, pinned: str, manifest: Any, location: Any) -> None:
    """Native Source/subtree/binding integrity plus the separate activation receipt."""
    from lumio_wiki.git_authoring import S3ActivationReceipt, _load_s3_publication_record

    try:
        record = _load_s3_publication_record(metadata_store, pinned, manifest)
        if record is None:
            raise ValueError("missing native admission record")
        activation = msgspec.json.decode(
            metadata_store.get_activation_receipt(pinned), type=S3ActivationReceipt
        )
    except Exception as exc:
        raise UnadmittedInputError(
            f"S3 Published Version {pinned!r} has no completed private admission "
            "matching its exact native identity and binding integrity"
        ) from exc
    receipt = record.receipt
    if (
        activation.version != receipt.version
        or activation.review_digest != receipt.review_digest
        or activation.expected_current != receipt.expected_current
        or (location.destination_uri is not None
            and receipt.destination.rstrip("/") != location.destination_uri.rstrip("/"))
        or (location.effective_target_identity is not None
            and receipt.destination_identity != location.effective_target_identity)
    ):
        raise UnadmittedInputError(
            f"S3 Published Version {pinned!r} has inconsistent activation or destination identity"
        )


def _resolve_verified_published_context(
    location: Any,
    expected: ContextIdentity,
    *,
    ontology_catalog: Mapping[str, Mapping[str, str | Sequence[str]]] | None = None,
    metadata_store: Any = None,
) -> tuple[Any, Any, str]:
    """Resolve and fully verify one exact admitted Published Version, once.

    The shared verification front-half of :func:`open_published_context`;
    its gate order, keyword arguments, exception categories and diagnostics
    are unchanged: location and exact version-pin admission, publication
    manifest and identity digests, profile version, non-empty effective
    Visibility Scope, native admission receipts and profile validation.
    Returns the verified resolved snapshot, its publication manifest and the
    pinned version; callers disclose only this one verified snapshot.
    """
    from lumio_wiki.location import PublishedFilesystemLocation, published_version_path
    from lumio_wiki.s3_location import MANIFEST_OBJECT, S3Location, _get_bytes

    if isinstance(location, PublishedFilesystemLocation):
        pinned = location.version
        if pinned is None:
            raise UnadmittedInputError(
                "the published Location carries no exact version pin; the current "
                "pointer is never read as a fallback for Context opening"
            )
        manifest_file = published_version_path(location.path, pinned) / MANIFEST_OBJECT
        try:
            manifest_raw = manifest_file.read_bytes()
        except OSError as exc:
            raise SnapshotUnavailableError(
                f"Published Version {pinned!r} has no readable manifest at {location.path}: {exc}"
            ) from exc
    elif isinstance(location, S3Location):
        pinned = location.version
        if pinned is None:
            raise UnadmittedInputError(
                "the S3 Location carries no exact version pin; the current pointer "
                "is never read as a fallback for Context opening"
            )
        if metadata_store is None:
            raise UnadmittedInputError(
                "opening an S3 Published Context requires the producer-side "
                "metadata store that holds the private admission records; "
                "there is no local fallback"
            )
        key = "/".join(part for part in (location.prefix, pinned, MANIFEST_OBJECT) if part)
        try:
            manifest_raw = _get_bytes(location.store, key)
        except Exception as exc:
            raise SnapshotUnavailableError(
                f"S3 Published Version {pinned!r} has no readable manifest at "
                f"{location.prefix or '/'}: {exc}"
            ) from exc
    else:
        raise UnadmittedInputError(
            "opening a published Context requires an immutable-version-pinned "
            "published Location; plain directories and unadmitted inputs are refused"
        )
    manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
    try:
        snapshot = location.resolve()
        manifest = (
            location.read_manifest(pinned)
            if isinstance(location, PublishedFilesystemLocation)
            else _manifest_from_bytes(manifest_raw)
        )
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
    if expected.subtree != manifest.subtree:
        mismatches.append("subtree")
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
    # Exact native admission facts (producer-owned; never consumer-rebuilt).
    if isinstance(location, PublishedFilesystemLocation):
        _verify_local_admission(location.path, pinned, manifest)
    else:
        _verify_s3_admission(metadata_store, pinned, manifest, location)
    if not snapshot.validation_report.is_valid:
        _refuse_invalid_report(snapshot, expected.scope)
    _raise_for_diagnostics(
        validate_ariadne_profiles(
            snapshot.pages,
            namespace=manifest.namespace,
            scope=expected.scope,
            ontology_catalog=_control_catalog(snapshot.knowledge_base.control),
        )
    )
    if ontology_catalog is not None and ontology_catalog != _control_catalog(
        snapshot.knowledge_base.control
    ):
        raise UnresolvedReferenceError(
            "caller ontology_catalog does not agree with the published Control File declaration"
        )
    return snapshot, manifest, pinned


def open_published_context(
    location: Any,
    expected: ContextIdentity,
    *,
    ontology_catalog: Mapping[str, Mapping[str, str | Sequence[str]]] | None = None,
    metadata_store: Any = None,
) -> ContextSnapshot:
    """Open one exact admitted immutable Published Version as a Context Snapshot.

    Requires a version-pinned published Location — local or S3 object store —
    never a plain directory and never a floating current pointer. S3 input
    additionally requires the producer-side ``metadata_store`` used at
    publication so the exact native admission facts can be verified; there is
    no local-path fallback. Every expected Context Identity component
    (including the selected subtree) is compared before a usable view, and
    the expected identity's effective Visibility Scope is applied before any
    lookup, expansion or view construction. A changed or wrong version
    refuses; there is no fallback to latest. ``ontology_catalog`` is a
    compatibility assertion only: it must agree with the published Control File.
    """
    snapshot, manifest, pinned = _resolve_verified_published_context(
        location, expected, ontology_catalog=ontology_catalog, metadata_store=metadata_store
    )
    allowed = set(expected.scope)
    in_scope = [
        page
        for page in snapshot.pages
        if page.ariadne_profile is not None and (page.visibility or "") in allowed
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


def _scoped_visible_pages(snapshot: Any, scope: Sequence[str]) -> list[CompiledPage]:
    """Authorized-scope pages only, filtered before selection or ranking."""
    allowed = set(scope)
    return [page for page in snapshot.pages if (page.visibility or "") in allowed]


def _published_page_metadata(
    page: CompiledPage, *, namespace: str, published_version: str
) -> PublishedContextPageMetadata:
    """The immutable advisory metadata of one visible page; no page body."""
    profile = page.ariadne_profile
    return PublishedContextPageMetadata(
        namespace=namespace,
        entity_id=page.id,
        path=page.path,
        title=page.title,
        kind=profile.kind if profile else "unprofiled",
        published_version=published_version,
        citation=f"{namespace} {page.id} v{published_version} {page.path}",
        lifecycle=page.lifecycle,
        review_after=page.review_after,
    )


def _published_page_record(
    page: CompiledPage,
    *,
    namespace: str,
    published_version: str,
    canonical_content: Mapping[str, bytes],
) -> PublishedContextPage:
    """One complete visible canonical page as an immutable navigation record."""
    profile = page.ariadne_profile
    raw = canonical_content.get(page.path, b"")
    metadata = _published_page_metadata(
        page, namespace=namespace, published_version=published_version
    )
    return PublishedContextPage(
        **msgspec.to_builtins(metadata),
        content=raw.decode("utf-8", errors="replace"),
        body=page.body,
        body_start_line=page.body_start_line,
        native=_freeze(profile.native) if profile else MappingProxyType({}),
        sources=tuple(page.sources),
    )


#: Native page-search field -> canonical frontmatter key carrying the decoded
#: value a metadata-only match must cite.
_METADATA_FIELD_KEYS = MappingProxyType(
    {"title": "title", "alias": "aliases", "tag": "tags", "summary": "summary"}
)


def _mark_offset(mark: Any, line_starts: Sequence[int], bound: int) -> int:
    """Character offset of one composed YAML mark inside its frontmatter text."""
    base = line_starts[mark.line] if mark.line < len(line_starts) else bound
    return min(base + mark.column, bound)


def _metadata_match_passage(
    page: CompiledPage,
    matched_fields: Sequence[str],
    terms: Sequence[str],
    raw: str,
) -> tuple[str, int, int, None]:
    """The verbatim canonical raw span of the actually matched metadata value.

    Composed YAML node marks map the decoded native search value back to its
    canonical source characters: an escaped scalar (``"\\u0068alcyon"``) cites
    its authored raw line, a multiline scalar truthfully cites its whole raw
    span, and a comment on an unrelated key never stands in for the passage.
    The span is composed from and sliced out of the original canonical text,
    so its real line separators (CRLF included) stay verbatim. Metadata sits
    above the body, so no section exists. An unavailable mapping refuses; a
    body passage is never fabricated.
    """
    import yaml

    keys = {
        _METADATA_FIELD_KEYS[field]
        for field in matched_fields
        if field in _METADATA_FIELD_KEYS
    }
    if not keys:
        raise MalformedProfileError(
            f"no citable frontmatter key for matched fields of {page.path!r}"
        )
    lines = raw.splitlines()
    frontmatter_lines = lines[: max(page.body_start_line - 1, 0)]
    # Start offset of every frontmatter line in the original raw text, each
    # line's real separator kept (CRLF, LF or bare CR), so both the compose
    # input and the excerpt slice stay byte-verbatim; composed marks are
    # 0-based lines of exactly this text, so canonical line == mark + 1.
    raw_starts = []
    pos = 0
    for line in frontmatter_lines:
        raw_starts.append(pos)
        pos += len(line)
        if raw[pos : pos + 2] == "\r\n":
            pos += 2
        elif raw[pos : pos + 1] in ("\r", "\n"):
            pos += 1
    frontmatter = raw[:pos]
    root = yaml.compose(frontmatter, Loader=yaml.SafeLoader)
    if not isinstance(root, yaml.MappingNode):
        raise MalformedProfileError(
            f"no citable YAML frontmatter mapping at {page.path!r}"
        )
    for key, value in root.value:
        if not (isinstance(key, yaml.ScalarNode) and key.value in keys):
            continue
        # A searched field holds one scalar or a sequence of scalars; no
        # deeper structure is interpreted.
        values = value.value if isinstance(value, yaml.SequenceNode) else (value,)
        for node in values:
            if not isinstance(node, yaml.ScalarNode):
                continue
            folded = node.value.casefold()
            if not any(term in folded for term in terms):
                continue
            # The raw token span minus its consuming trailing line breaks is
            # the verbatim passage; original-text character offsets keep the
            # span and its separators exact down to whole original lines.
            start = _mark_offset(node.start_mark, raw_starts, len(frontmatter))
            end = _mark_offset(node.end_mark, raw_starts, len(frontmatter))
            span = frontmatter[start:end].rstrip()
            first = node.start_mark.line
            last = first + len(span.splitlines()) - 1
            return (
                raw[raw_starts[first] : raw_starts[last] + len(lines[last])],
                first + 1,
                last + 1,
                None,
            )
    raise MalformedProfileError(
        f"no canonical source span for the matched metadata value of {page.path!r}"
    )


def _canonical_match_passage(
    page: CompiledPage,
    matched_fields: Sequence[str],
    matched_terms: Sequence[str],
    canonical_content: Mapping[str, bytes],
) -> tuple[str, int | None, int | None, str | None]:
    """The verbatim canonical line passage for one kept visible hit.

    A body match cites its matching canonical line (verbatim, indentation
    kept) with the innermost fence-aware section containing it; a
    metadata-only match cites the real canonical frontmatter span carrying
    the matched value, with no section — never a fabricated body passage.
    """
    from lumio_wiki.evidence import body_sections

    raw = canonical_content.get(page.path, b"").decode("utf-8", errors="replace")
    lines = raw.splitlines()
    terms = [term.casefold() for term in matched_terms]
    if "body" not in matched_fields:
        return _metadata_match_passage(page, matched_fields, terms, raw)
    # Canonical line ``body_start_line`` begins the body: its first character
    # is that line's terminating newline.
    first = page.body_start_line - 1
    last = len(lines)
    sections = body_sections(page.body, page.body_start_line)
    for index in range(first, min(last, len(lines))):
        folded = lines[index].casefold()
        if any(term in folded for term in terms):
            line_number = index + 1
            section = None
            for title, start, end, _text in sections:
                if start <= line_number <= end:
                    section = title  # innermost (latest) containing section
            return lines[index], line_number, line_number, section
    # Defensive tail (a genuine native match always finds its line): the
    # whole stripped body passage with its page coordinates.
    body_lines = page.body.splitlines()
    return (
        page.body.strip(),
        page.body_start_line,
        page.body_start_line + len(body_lines) - 1,
        None,
    )


def _navigation_snapshot(
    location: Any, expected: ContextIdentity, *, metadata_store: Any = None
) -> tuple[Any, Any, str]:
    """One fully verified pinned snapshot for a navigation operation.

    The shared reader gate is reused unchanged, so plain directories and
    unpinned locations refuse with the reader's categories and message
    idioms before any store access; an S3 location additionally requires
    the explicitly supplied producer-side ``metadata_store`` whose private
    native admission records are verified (spec0009 navigation r4). Each
    operation then discloses only this one verified snapshot.
    """
    return _resolve_verified_published_context(
        location, expected, ontology_catalog=None, metadata_store=metadata_store
    )


def list_published_context_pages(
    location: Any, expected: ContextIdentity, *, metadata_store: Any = None
) -> tuple[PublishedContextPageMetadata, ...]:
    """List the immutable metadata of every visible published context page.

    Ordinary documentation pages appear alongside profiled pages with the
    explicit ``unprofiled`` kind; results carry no page body and are sorted
    by exact relative path. Requires an immutable-version-pinned published
    Location — local ``PublishedFilesystemLocation`` or S3 ``S3Location``
    with its explicitly supplied producer-side ``metadata_store`` so the
    shared exact-admission verifier can verify the private native records
    (spec0009 navigation r4; S3 without it still refuses) — and the complete
    expected :class:`ContextIdentity`; the effective Visibility Scope is
    applied before path selection.
    """
    snapshot, manifest, pinned = _navigation_snapshot(
        location, expected, metadata_store=metadata_store
    )
    visible = sorted(_scoped_visible_pages(snapshot, expected.scope), key=lambda page: page.path)
    return tuple(
        _published_page_metadata(page, namespace=manifest.namespace, published_version=pinned)
        for page in visible
    )


def read_published_context_page(
    location: Any, expected: ContextIdentity, path: str, *, metadata_store: Any = None
) -> PublishedContextPage:
    """Read one complete visible canonical page by its exact relative path.

    Accepts the same pinned local Location or pinned S3 Location with
    explicit producer-side ``metadata_store`` as
    :func:`list_published_context_pages`. The result carries the exact
    canonical UTF-8 content, the parsed body with its body-start line,
    immutable native metadata (empty when unprofiled) and the public Source
    provenance. Missing and out-of-scope paths refuse with the same
    scope-safe unavailability, disclosing no hidden title, Entity identity
    or text.
    """
    snapshot, manifest, pinned = _navigation_snapshot(
        location, expected, metadata_store=metadata_store
    )
    canonical_content = snapshot.knowledge_base.canonical_pages
    for page in _scoped_visible_pages(snapshot, expected.scope):
        if page.path == path:
            return _published_page_record(
                page,
                namespace=manifest.namespace,
                published_version=pinned,
                canonical_content=canonical_content,
            )
    raise UnadmittedInputError(
        f"no visible context page at path {path!r} in Published Version {pinned!r}"
    )


def search_published_context_pages(
    location: Any,
    expected: ContextIdentity,
    query: str,
    *,
    limit: int = 10,
    metadata_store: Any = None,
    kinds: Sequence[str] | None = None,
) -> tuple[PublishedContextSearchHit, ...]:
    """Search exactly the visible pages of one verified immutable version.

    Accepts the same pinned local Location or pinned S3 Location with
    explicit producer-side ``metadata_store`` as
    :func:`list_published_context_pages`. Normalization, ranking,
    deterministic ties, query limits and completeness accounting are the
    native page search over the scope-filtered page set — no second ranking
    engine. ``kinds`` optionally restricts the ranked set to the named
    producer profile kinds (``unprofiled`` included) BEFORE matching,
    ranking and limiting — a producer view filter over the same typed scoped
    view, never a separate index. Each kept hit adds a separately labeled
    verbatim canonical excerpt with inclusive 1-based line numbers and the
    actual fence-aware section when available; metadata-only matches cite
    the real canonical metadata passage.
    """
    from lumio_wiki.page_search import search_pages

    snapshot, manifest, pinned = _navigation_snapshot(
        location, expected, metadata_store=metadata_store
    )
    visible = _scoped_visible_pages(snapshot, expected.scope)
    if kinds is not None:
        requested = frozenset(kinds)
        if not requested or not all(isinstance(kind, str) and kind for kind in requested):
            raise ValueError("kinds must be a non-empty sequence of producer kind strings")
        visible = [
            page
            for page in visible
            if (page.ariadne_profile.kind if page.ariadne_profile else "unprofiled")
            in requested
        ]
    canonical_content = snapshot.knowledge_base.canonical_pages
    hits: list[PublishedContextSearchHit] = []
    for result in search_pages(visible, query, limit=limit):
        excerpt, line_start, line_end, section = _canonical_match_passage(
            result.page, result.matched_fields, result.matched_terms, canonical_content
        )
        hits.append(
            PublishedContextSearchHit(
                page=_published_page_record(
                    result.page,
                    namespace=manifest.namespace,
                    published_version=pinned,
                    canonical_content=canonical_content,
                ),
                score=result.score,
                matched_fields=tuple(result.matched_fields),
                matched_terms=tuple(result.matched_terms),
                snippet=result.snippet,
                candidates_seen=result.candidates_seen,
                results_dropped=result.results_dropped,
                excerpt=excerpt,
                line_start=line_start,
                line_end=line_end,
                section=section,
            )
        )
    return tuple(hits)


def _manifest_from_bytes(manifest_raw: bytes) -> Any:
    from lumio_wiki.s3_location import S3Manifest

    return msgspec.json.decode(manifest_raw, type=S3Manifest)


def _refuse_invalid_report(snapshot: Any, scope: Sequence[str]) -> None:
    """Refuse invalid published content without disclosing hidden metadata.

    Validation errors on pages inside the effective scope are named; errors
    that exist only on out-of-scope pages are summarized by count, never by
    file, title or path.
    """
    allowed = set(scope)
    visible_files = {page.path for page in snapshot.pages if (page.visibility or "") in allowed}
    errors = [issue for issue in snapshot.validation_report.issues if issue.severity == "error"]
    visible_errors = [issue for issue in errors if issue.file in visible_files]
    hidden_errors = [issue for issue in errors if issue.file not in visible_files]
    if visible_errors:
        detail = "; ".join(
            f"{issue.file}: {issue.field}: {issue.message}" for issue in visible_errors
        )
        raise MalformedProfileError(f"the published content fails native validation: {detail}")
    raise MalformedProfileError(
        "the published content fails native validation with "
        f"{len(hidden_errors)} error(s) on content outside the authorized "
        "visibility scope"
    )

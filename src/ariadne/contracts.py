"""Source-free ODCS contract document, profile and binding validation (spec
2026-10-17-0028 §§2–6, issue #77/C1).

This module owns the OFFLINE half of the contract consumer profile: the
immutable official-schema pin, strict document validation with explicit
version dispatch, the scoped-ID/internal-reference semantics beyond JSON
Schema, the native binding-document grammar, the supported field/SQL profile
declaration and the pinned comparison semantics. It opens no connection,
reads no environment variable and resolves nothing remote — the approved
source observation seam lives in :mod:`ariadne.contract_inspection`.

Document validity, binding validity, supported evaluation and observed
conformance are separate facts (ADR-0025): a valid four-field document is
never source-compliant evidence, and a schema-valid feature outside this
evaluator stays valid ODCS while being explicitly unsupported here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import jsonschema
import yaml

# The immutable official pin (spec 0028 §2): the unmodified upstream
# ``schema/odcs-json-schema-v3.2.0.json`` from commit f0bdad9, Git blob
# f934075, exactly the recorded bytes. A drifted package refuses validation
# rather than validating against unknown schema bytes; schema updates are
# explicit reviewed changes, never downloads at validation time.
SCHEMA_RESOURCE = "odcs-json-schema-v3.2.0.json"
SCHEMA_SHA256 = "edb41f33ec46e84780e99872ab2bd67f074959d2bf3e9c9fc54e61f8982b0d93"
SCHEMA_SIZE = 110505
SUPPORTED_API_VERSION = "v3.2.0"
ODCS_KIND = "DataContract"

# The consumer profile's own identity, bound into validation evidence (spec
# 0028 §6): bump when the checks performed below change.
CONSUMER_PROFILE = "ariadne-odcs-consumer/1"

# The exact logical-type → observed-scalar-family mapping of the supported
# field profile (spec 0028 §4). NOT profiler.types_compatible (which owns
# identifier comparability): unknown or unavailable type metadata is never
# proof of compatibility.
_LOGICAL_FAMILIES: dict[str, frozenset[str]] = {
    "string": frozenset({"varchar", "char"}),
    "integer": frozenset(
        {
            "tinyint",
            "smallint",
            "integer",
            "bigint",
            "hugeint",
            "utinyint",
            "usmallint",
            "uinteger",
            "ubigint",
            "uhugeint",
        }
    ),
    "number": frozenset(
        {
            "tinyint",
            "smallint",
            "integer",
            "bigint",
            "hugeint",
            "utinyint",
            "usmallint",
            "uinteger",
            "ubigint",
            "uhugeint",
            "decimal",
            "float",
            "double",
        }
    ),
    "boolean": frozenset({"boolean"}),
    "date": frozenset({"date"}),
    "time": frozenset({"time"}),
    "timestamp": frozenset({"timestamp"}),
}

# Recognized source-dialect aliases normalized before a declared
# ``physicalType`` comparison (width/precision/scale/time-zone distinctions
# are retained, never dropped — spec 0028 §4).
_PHYSICAL_ALIASES = {
    "int": "integer",
    "int1": "tinyint",
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "signed": "integer",
    "string": "varchar",
    "text": "varchar",
    "character varying": "varchar",
    "float4": "float",
    "float8": "double",
    "real": "float",
    "numeric": "decimal",
    "bool": "boolean",
    "logical": "boolean",
}

# Unsupported declared constraints of the field profile (spec 0028 §4):
# preserved and displayed per property, never silently ignored or inferred
# fulfilled from a different SQL rule.
_UNSUPPORTED_PROPERTY_FLAGS = ("unique", "primaryKey")


class ContractError(ValueError):
    """A contract document/binding validation failure with its location."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """A YAML loader that refuses ambiguous duplicate mapping keys instead of
    silently choosing the last interpretation (spec 0028 §2)."""


def _construct_mapping(loader: yaml.Loader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise ContractError(
                f"mapping key {key!r} is not a string — JSON-compatible objects only"
            )
        if key in mapping:
            raise ContractError(f"duplicate mapping key {key!r} — ambiguous documents are refused")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


_schema_cache: dict | None = None


def load_pinned_schema() -> dict:
    """The packaged official v3.2.0 schema bytes, hash-verified at first load.

    Vendored from bitol-io/open-data-contract-standard commit f0bdad9 (Git
    blob f934075); the Apache-2.0 LICENSE rides beside it in the package.
    Loading is offline and fail-closed: packaged bytes that do not match the
    recorded pin refuse validation instead of guessing the dialect.
    """
    global _schema_cache
    cached = _schema_cache
    if cached is not None:
        return cached
    data = (
        resources.files("ariadne")
        .joinpath("schemas")
        .joinpath("odcs")
        .joinpath(SCHEMA_RESOURCE)
        .read_bytes()
    )
    if len(data) != SCHEMA_SIZE or hashlib.sha256(data).hexdigest() != SCHEMA_SHA256:
        raise ContractError(
            f"the packaged ODCS schema pin is not the recorded official v3.2.0 "
            f"bytes (sha256 {SCHEMA_SHA256}) — refusing validation against "
            "unknown schema bytes; schema updates are explicit reviewed changes"
        )
    schema: dict = json.loads(data)
    _schema_cache = schema
    return schema


def _json_compatible(value: object, where: str) -> None:
    """A contract document carries one JSON-compatible object: non-JSON YAML
    values (dates, sets, bytes, non-string keys, NaN) are refused rather than
    silently coerced (spec 0028 §2)."""

    def check(node: object, path: str) -> None:
        if node is None or isinstance(node, (bool, int, str)):
            return
        if isinstance(node, float):
            if node != node or node in (float("inf"), float("-inf")):
                raise ContractError(f"{where}: {path} is a non-finite float — not a JSON value")
            return
        if isinstance(node, list):
            for index, item in enumerate(node):
                check(item, f"{path}[{index}]")
            return
        if isinstance(node, dict):
            for key, item in node.items():
                if not isinstance(key, str):
                    raise ContractError(
                        f"{where}: {path} has the non-string mapping key {key!r} — "
                        "JSON-compatible objects only"
                    )
                check(item, f"{path}.{key}")
            return
        raise ContractError(
            f"{where}: {path} is a {type(node).__name__} — not a JSON-compatible value"
        )

    check(value, "$")


def parse_contract_document(text: str, where: str) -> dict:
    """Parse ONE UTF-8 YAML document representing a JSON-compatible object,
    refusing duplicate mapping keys and non-JSON values. A multi-document
    stream is an explicit error (one contract per file)."""
    if not isinstance(text, str):
        raise ContractError(f"{where}: contract bytes must decode to UTF-8 text")
    try:
        loader = _UniqueKeyLoader(text)
        try:
            documents = [loader.get_single_data()]
        finally:
            loader.dispose()
    except ContractError as exc:
        raise ContractError(f"{where}: {exc}") from None
    except yaml.YAMLError as exc:
        raise ContractError(f"{where}: not valid YAML: {exc}") from None
    [document] = documents if isinstance(documents, list) and len(documents) == 1 else [None]
    if not isinstance(document, dict):
        raise ContractError(
            f"{where}: a contract document is exactly one YAML mapping — one contract per file"
        )
    _json_compatible(document, where)
    return document


def _schema_errors(document: dict) -> list[str]:
    """The pinned official schema's structural Draft 2019-09 assertions.
    ``format`` stays an annotation: no environment-dependent format checker
    may silently change document validity (spec 0028 §2)."""
    schema = load_pinned_schema()
    validator_class = jsonschema.validators.validator_for(schema)  # pyright: ignore[reportAttributeAccessIssue,reportCallIssue] — jsonschema's Draft 2019-09 selection (untyped upstream)
    validator = validator_class(schema)
    errors = []
    for error in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        pointer = "/".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{pointer}: {error.message}")
    return errors


def _walk_id_arrays(node: object, path: str, errors: list[str]) -> None:
    """The standard's scoped-ID uniqueness beyond JSON Schema: ids are unique
    within their containing array (StableId's own rule), checked for every
    array of identified elements (schema objects, properties, servers,
    quality rules, custom properties, relationships)."""
    if isinstance(node, list):
        seen: dict[str, str] = {}
        identified = [
            item for item in node if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        for item in identified:
            identifier = item["id"]
            if identifier in seen:
                errors.append(
                    f"{path}: duplicate scoped id {identifier!r} within its containing "
                    "array — stable ids are unique per array"
                )
            else:
                seen[identifier] = identifier
        for index, item in enumerate(node):
            _walk_id_arrays(item, f"{path}[{index}]", errors)
    elif isinstance(node, dict):
        for key, item in node.items():
            _walk_id_arrays(item, f"{path}.{key}", errors)


def _reference_targets(document: dict) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Object/property NAMES and ids available for internal reference
    resolution: (names: object name -> property names, ids: object id ->
    property ids)."""
    names: dict[str, set[str]] = {}
    ids: dict[str, set[str]] = {}
    for obj in document.get("schema") or []:
        if not isinstance(obj, dict):
            continue
        if isinstance(obj.get("name"), str):
            names.setdefault(obj["name"], set())
        if isinstance(obj.get("id"), str):
            ids.setdefault(obj["id"], set())
        for prop in obj.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            if isinstance(obj.get("name"), str) and isinstance(prop.get("name"), str):
                names[obj["name"]].add(prop["name"])
            if isinstance(obj.get("id"), str) and isinstance(prop.get("id"), str):
                ids[obj["id"]].add(prop["id"])
    return names, ids


def _resolve_internal_reference(reference: str, names: dict, ids: dict) -> str | None:
    """Resolve one relationship endpoint reference inside THIS contract:
    fully qualified ``schema/<id>[/properties/<id>]`` by id, shorthand
    ``object.property`` by name. Returns None for external references (a
    ``...yaml#`` prefix — retained metadata, never fetched). Raises
    ContractError for a dangling internal reference."""
    if "#" in reference:  # an external file/URL prefix: metadata, not fetched
        return None
    if "/" in reference:
        parts = [part for part in reference.strip("/").split("/")]
        if len(parts) >= 2 and parts[0] == "schema" and parts[1] in ids:
            if len(parts) == 2:
                return reference
            if len(parts) == 4 and parts[2] == "properties":
                if parts[3] in ids[parts[1]]:
                    return reference
                raise ContractError(
                    f"reference {reference!r} names property id {parts[3]!r} which does "
                    "not exist in that schema object — dangling internal reference"
                )
        raise ContractError(
            f"reference {reference!r} does not resolve inside this contract — dangling "
            "internal reference"
        )
    table, _, column = reference.partition(".")
    if not column:
        raise ContractError(
            f"reference {reference!r} does not resolve inside this contract — dangling "
            "internal reference"
        )
    if table in names and column in names[table]:
        return reference
    raise ContractError(
        f"reference {reference!r} does not resolve inside this contract — dangling "
        "internal reference"
    )


def _check_references(document: dict, where: str, errors: list[str]) -> None:
    """Every internal relationship endpoint must resolve inside the contract
    (spec 0028 §3: dangling internal references fail visibly, beyond JSON
    Schema). External references are retained without fetching."""
    names, ids = _reference_targets(document)
    for index, obj in enumerate(document.get("schema") or []):
        if not isinstance(obj, dict):
            continue
        base = f"schema[{index}]"
        for position, relationship in enumerate(obj.get("relationships") or []):
            if not isinstance(relationship, dict):
                continue
            for side in ("from", "to"):
                endpoints = relationship.get(side)
                if not isinstance(endpoints, list):
                    endpoints = [endpoints]
                for endpoint in endpoints:
                    if isinstance(endpoint, str):
                        try:
                            _resolve_internal_reference(endpoint, names, ids)
                        except ContractError as exc:
                            errors.append(f"{where}: {base}.relationships[{position}]: {exc}")
        for position, prop in enumerate(obj.get("properties") or []):
            if not isinstance(prop, dict):
                continue
            for position_r, relationship in enumerate(prop.get("relationships") or []):
                if not isinstance(relationship, dict):
                    continue
                endpoints = relationship.get("to")
                if not isinstance(endpoints, list):
                    endpoints = [endpoints]
                for endpoint in endpoints:
                    if isinstance(endpoint, str):
                        try:
                            _resolve_internal_reference(endpoint, names, ids)
                        except ContractError as exc:
                            errors.append(
                                f"{where}: {base}.properties[{position}]"
                                f".relationships[{position_r}]: {exc}"
                            )


@dataclass
class DocumentResult:
    """The separate document-level facts of one contract file (spec 0028 §6):
    structural validity under the pinned schema, the explicit version
    dispatch, and the producer identity — never a data-conformance claim."""

    path: str
    digest: str
    valid: bool
    supported_version: bool
    contract_id: str | None = None
    contract_version: Any = None
    api_version: Any = None
    team: Any = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "path": self.path,
            "digest": self.digest,
            "valid": self.valid,
            "supported_version": self.supported_version,
            "id": self.contract_id,
            "version": self.contract_version,
            "api_version": self.api_version,
            # ownership is PRESERVED as declared and honestly undeclared when
            # absent — never inferred from a source alias, Git author or
            # filename (spec 0028 §2)
            "team": self.team,
            "ownership": "declared" if self.team is not None else "undeclared",
        }


def validate_document(text: str, where: str) -> tuple[dict | None, DocumentResult]:
    """Validate one producer contract document OFFLINE under the pinned
    official schema plus the native semantic rules. Returns (document,
    result); ``document`` is None when the text does not parse. A different
    ``apiVersion`` label fails the explicit version dispatch even though the
    pinned schema accepts some older labels (spec 0028 §2)."""
    result = DocumentResult(
        path=where,
        digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        valid=False,
        supported_version=False,
    )
    try:
        document = parse_contract_document(text, where)
    except ContractError as exc:
        result.errors = [str(exc)]
        return None, result
    result.contract_id = document.get("id") if isinstance(document.get("id"), str) else None
    result.contract_version = document.get("version")
    result.api_version = document.get("apiVersion")
    result.team = document.get("team")
    errors = _schema_errors(document)
    semantic: list[str] = []
    _walk_id_arrays(document.get("schema") or [], "$.schema", semantic)
    for index, server in enumerate(document.get("servers") or []):
        if isinstance(server, dict):
            _walk_id_arrays(server.get("roles") or [], f"$.servers[{index}].roles", semantic)
    _check_references(document, where, semantic)
    # The explicit consumer version dispatch: only v3.2.0 is supported, even
    # though the pinned schema's enum accepts older labels.
    version_error = None
    if document.get("apiVersion") != SUPPORTED_API_VERSION:
        version_error = (
            f"{where}: apiVersion {document.get('apiVersion')!r} is outside the supported "
            f"profile — only {SUPPORTED_API_VERSION} is evaluated here (the pinned "
            "official schema accepts some older labels; explicit version dispatch "
            "refuses them)"
        )
    if document.get("kind") != ODCS_KIND:
        errors.append(
            f"{where}: kind {document.get('kind')!r} is not {ODCS_KIND!r} — only "
            "DataContract documents are consumed"
        )
    if not errors and not semantic and version_error is None:
        result.valid = True
        result.supported_version = True
        return document, result
    result.errors = [
        *(["schema: " + error for error in errors]),
        *(["semantic: " + error.removeprefix(f"{where}: ") for error in semantic]),
        *([version_error] if version_error else []),
    ]
    return document, result


# --------------------------------------------------------------- field profile


def observed_type_family(observed: str) -> tuple[str | None, dict]:
    """The supported observed scalar family of one catalog type string plus
    its retained variant distinctions (width/precision/scale/time-zone) —
    ``None`` when the type is unknown or unavailable, which is never proof of
    compatibility (spec 0028 §4)."""
    text = (observed or "").strip().lower()
    variant: dict[str, Any] = {}
    if text.startswith(("timestamp with time zone", "timetz")):
        variant["time_zone"] = True
        family = "timestamp" if text.startswith("timestamp") else "time"
        return family, variant
    if text.startswith(("time with time zone",)):
        return "time", {"time_zone": True}
    base = text.split("(")[0].strip()
    for suffix in (" with time zone",):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            variant["time_zone"] = True
    normalized = _PHYSICAL_ALIASES.get(base, base)
    if "(" in text:
        arguments = text[text.index("(") + 1 :].rstrip(")").strip()
        parts = [part.strip() for part in arguments.split(",")]
        if normalized == "decimal" and 1 <= len(parts) <= 2 and all(p.isdigit() for p in parts):
            variant["precision"] = int(parts[0])
            if len(parts) == 2:
                variant["scale"] = int(parts[1])
        elif len(parts) == 1 and parts[0].isdigit():
            variant["width"] = int(parts[0])
    return normalized, variant


def logical_type_matches(logical_type: Any, observed: str) -> tuple[str, str]:
    """Compare one declared ODCS logical type with an observed scalar type
    using the explicit supported mapping. Returns (outcome, detail) with
    outcome ``passed`` / ``drift`` / ``unsupported``; an ABSENT type
    declaration imposes no invented type constraint (caller checks)."""
    if logical_type is None:
        return "passed", "no declared logical type — no invented type constraint"
    if not isinstance(logical_type, str) or logical_type not in _LOGICAL_FAMILIES:
        return (
            "unsupported",
            f"logical type {logical_type!r} is outside the supported field profile "
            "(nested collection/object types and unknown logical types are not evaluated)",
        )
    family, _variant = observed_type_family(observed)
    if family is None:
        return (
            "unsupported",
            f"the observed type {observed!r} has no reliable supported family — "
            "unknown metadata is not proof of compatibility",
        )
    if family in _LOGICAL_FAMILIES[logical_type]:
        return "passed", f"observed {observed!r} is in the supported family of {logical_type!r}"
    return (
        "drift",
        f"declared logical type {logical_type!r} does not cover the observed type "
        f"{observed!r} ({family!r}) — no coercion bridges them",
    )


def compare_physical_type(declared: Any, observed: str) -> tuple[str, str]:
    """Compare a declared ``physicalType`` with the observed catalog type:
    recognized aliases are normalized without dropping width, precision,
    scale or time-zone distinctions; a known mismatch is drift, an
    unverifiable distinction is unsupported, never a coerced pass (spec 0028
    §4)."""
    if not isinstance(declared, str) or not declared.strip():
        return (
            "unsupported",
            "the declared physicalType is not a comparable string — unverifiable, never a pass",
        )
    declared_family, declared_variant = observed_type_family(declared)
    observed_family, observed_variant = observed_type_family(observed)
    if declared_family is None or observed_family is None:
        return (
            "unsupported",
            f"declared physicalType {declared!r} or observed type {observed!r} has no "
            "recognized supported spelling — the original physical type is not reliably "
            "observable here, never a coerced pass",
        )
    if declared_family != observed_family:
        return (
            "drift",
            f"declared physicalType {declared!r} ({declared_family!r}) mismatches the "
            f"observed type {observed!r} ({observed_family!r})",
        )
    for distinction in ("width", "precision", "scale", "time_zone"):
        declared_value = declared_variant.get(distinction)
        observed_value = observed_variant.get(distinction)
        if declared_value is None and observed_value is None:
            continue
        if declared_value != observed_value:
            if declared_value is None or observed_value is None:
                return (
                    "unsupported",
                    f"declared physicalType {declared!r} and observed type {observed!r} "
                    f"disagree on {distinction} with one side unavailable — unverifiable, "
                    "never a coerced pass",
                )
            return (
                "drift",
                f"declared physicalType {declared!r} mismatches the observed type "
                f"{observed!r} on {distinction} ({declared_value} vs {observed_value})",
            )
    return "passed", f"declared physicalType {declared!r} matches the observed {observed!r}"


# ------------------------------------------------------- SQL-quality semantics

# The pinned quality documentation (commit f0bdad9, docs/data-quality.md)
# equates ``mustBeBetween: [a, b]`` with ``mustBeGreaterThan a`` plus
# ``mustBeLessThan b``: this profile uses OPEN interval endpoints, and the
# complement for ``mustNotBeBetween``. Bounds must be increasing; they are
# never sorted or repaired (spec 0028 §5).
QUALITY_OPERATORS = (
    "mustBe",
    "mustNotBe",
    "mustBeGreaterThan",
    "mustBeGreaterOrEqualTo",
    "mustBeLessThan",
    "mustBeLessOrEqualTo",
    "mustBeBetween",
    "mustNotBeBetween",
)


def compare_quality_rule(rule: dict, value: object) -> tuple[str, str]:
    """Apply one declared SQL-quality comparison to an observed scalar
    result. Numeric comparisons preserve precision with no bool/integer
    conflation, string-to-number coercion or invented tolerance; boolean
    results support same-type equality/inequality only. NULL, non-finite
    values and wrong shapes are evaluation errors, not false comparisons."""
    operator = next(op for op in QUALITY_OPERATORS if op in rule)
    operand = rule[operator]
    if value is None:
        return "error", "the rule's query returned NULL — an evaluation error, not a comparison"
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    is_boolean = isinstance(value, bool)
    if isinstance(value, float) and not math.isfinite(value):
        return "error", "the rule's query returned a non-finite value — an evaluation error"
    if not (is_number or is_boolean):
        return "error", f"the rule's query returned {type(value).__name__} — not a scalar"
    if operator in ("mustBeBetween", "mustNotBeBetween"):
        if (
            not isinstance(operand, list)
            or len(operand) != 2
            or not all(
                isinstance(bound, (int, float)) and not isinstance(bound, bool) for bound in operand
            )
        ):
            return (
                "unsupported",
                f"{operator} needs an increasing two-number array, got {operand!r}",
            )
        low, high = operand
        if not low < high:
            return "error", f"{operator} bounds [{low}, {high}] are not increasing — refusing"
        if not is_number:
            return (
                "unsupported",
                f"{operator} compares numbers; a boolean result is not orderable here",
            )
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        inside = low < value < high  # the pinned documentation's open endpoints
        passed = inside if operator == "mustBeBetween" else not inside
        return (
            "passed" if passed else "drift",
            f"{operator} {operand}: observed {value!r} "
            f"({'inside' if inside else 'outside'} the open interval)",
        )
    if isinstance(operand, bool):
        if not is_boolean:
            return (
                "unsupported",
                f"{operator} {operand!r} is boolean; a numeric result is not same-type comparable",
            )
        if operator == "mustBe":
            return ("passed" if value == operand else "drift", f"mustBe {operand}: {value!r}")
        if operator == "mustNotBe":
            return ("passed" if value != operand else "drift", f"mustNotBe {operand}: {value!r}")
        return "unsupported", f"{operator} does not order booleans"
    if isinstance(operand, (int, float)) and not isinstance(operand, bool):
        if not is_number:
            return (
                "unsupported",
                f"{operator} {operand!r} is numeric; a boolean result is not same-type comparable",
            )
        if isinstance(operand, float) and not math.isfinite(operand):
            return "error", f"{operator} operand {operand!r} is non-finite"
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        comparisons = {
            "mustBe": value == operand,
            "mustNotBe": value != operand,
            "mustBeGreaterThan": value > operand,
            "mustBeGreaterOrEqualTo": value >= operand,
            "mustBeLessThan": value < operand,
            "mustBeLessOrEqualTo": value <= operand,
        }
        passed = comparisons[operator]
        return ("passed" if passed else "drift", f"{operator} {operand!r}: observed {value!r}")
    return "unsupported", f"{operator} operand {operand!r} is not a supported scalar shape"


# ------------------------------------------------------------- binding grammar

# The native binding document (spec 0028 §3): repository-local consumer
# configuration, SEPARATE from the producer contract. ``server_id`` is
# required when SQL-quality rules apply to the binding's object.
BINDING_VERSION = 1
_ASSET_KEYS = frozenset({"source", "catalog", "schema", "table"})
_BINDING_KEYS = frozenset(
    {
        "id",
        "contract_id",
        "contract_version",
        "object_id",
        "asset",
        "model",
        "dataset",
        "properties",
        "server_id",
    }
)


@dataclass
class Binding:
    """One parsed native contract binding."""

    id: str
    contract_id: str
    contract_version: str
    object_id: str
    asset: dict
    model: str
    dataset: str
    properties: dict[str, str]
    server_id: str | None

    def digest_payload(self) -> dict:
        return {
            "id": self.id,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "object_id": self.object_id,
            "asset": self.asset,
            "model": self.model,
            "dataset": self.dataset,
            "properties": self.properties,
            "server_id": self.server_id,
        }


def validate_bindings_document(text: str, where: str) -> tuple[list[Binding], list[str]]:
    """Parse and validate the fixed native binding document. Unknown binding
    fields, duplicate binding IDs and conflicting bindings for one OSI
    dataset are errors; exact producer identifiers are kept as strings (the
    producer version is not re-interpreted). Returns (bindings, errors)."""
    errors: list[str] = []
    try:
        document = parse_contract_document(text, where)
    except ContractError as exc:
        return [], [str(exc)]
    if document.get("version") != BINDING_VERSION:
        errors.append(
            f"{where}: the native binding document declares version "
            f"{document.get('version')!r}, not {BINDING_VERSION}"
        )
    unknown = sorted(set(document) - {"version", "bindings"})
    if unknown:
        errors.append(f"{where}: unsupported binding-document field(s) {unknown}")
    bindings: list[Binding] = []
    seen_ids: set[str] = set()
    seen_datasets: dict[tuple[str, str], Binding] = {}
    for index, entry in enumerate(document.get("bindings") or []):
        position = f"{where}: bindings[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{position}: a binding is a mapping")
            continue
        extra = sorted(set(entry) - _BINDING_KEYS)
        missing = sorted(_BINDING_KEYS - {"server_id"} - set(entry))
        if extra:
            errors.append(
                f"{position}: unsupported binding field(s) {extra} — the fixed grammar "
                "carries exactly the documented fields"
            )
        if missing:
            errors.append(f"{position}: missing required binding field(s) {missing}")
            continue
        asset = entry["asset"]
        if not isinstance(asset, dict) or set(asset) != _ASSET_KEYS:
            errors.append(
                f"{position}: asset is exactly {{source, catalog, schema, table}} with "
                "exact case-sensitive identifiers (catalog null for file views)"
            )
            continue
        for key in ("source", "schema", "table"):
            if not isinstance(asset[key], str) or not asset[key]:
                errors.append(f"{position}: asset.{key} must be a non-empty string")
        catalog = asset["catalog"]
        if catalog is not None and (not isinstance(catalog, str) or not catalog):
            errors.append(f"{position}: asset.catalog must be a stable name or null")
        properties = entry["properties"]
        if not isinstance(properties, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and key and value
            for key, value in properties.items()
        ):
            errors.append(
                f"{position}: properties maps producer property IDs to exact physical column names"
            )
            continue
        for key in ("id", "contract_id", "contract_version", "object_id", "model", "dataset"):
            if not isinstance(entry[key], str) or not entry[key]:
                errors.append(f"{position}: {key} must be a non-empty string")
        server_id = entry.get("server_id")
        if server_id is not None and (not isinstance(server_id, str) or not server_id):
            errors.append(f"{position}: server_id must be a producer server ID string or null")
        if errors and any(position in error for error in errors):
            continue
        binding = Binding(
            id=entry["id"],
            contract_id=entry["contract_id"],
            contract_version=entry["contract_version"],
            object_id=entry["object_id"],
            asset=dict(asset),
            model=entry["model"],
            dataset=entry["dataset"],
            properties=dict(properties),
            server_id=server_id,
        )
        if binding.id in seen_ids:
            errors.append(f"{position}: duplicate binding id {binding.id!r}")
        else:
            seen_ids.add(binding.id)
        dataset_key = (binding.model, binding.dataset)
        if dataset_key in seen_datasets:
            errors.append(
                f"{position}: binding {binding.id!r} conflicts with "
                f"{seen_datasets[dataset_key].id!r} for OSI dataset "
                f"{binding.model}.{binding.dataset} — one binding per dataset"
            )
        else:
            seen_datasets[dataset_key] = binding
        bindings.append(binding)
    return bindings, errors


def resolve_contract(
    documents: list[tuple[str, dict | None, DocumentResult]],
    contract_id: str,
    contract_version: str,
) -> tuple[dict | None, str | None]:
    """Resolve a contract by its exact ``(id, version)`` pair: duplicate
    documents for one pair are ambiguous, a miss is explicit (different
    producer versions coexist with explicit selection)."""
    matches = [
        (path, document)
        for path, document, result in documents
        if result.contract_id == contract_id
        and isinstance(result.contract_version, str)
        and result.contract_version == contract_version
        and result.valid
    ]
    if not matches:
        return None, (
            f"no valid contract document resolves the exact pair (id {contract_id!r}, "
            f"version {contract_version!r}) — bindings select exact producer versions"
        )
    if len(matches) > 1:
        return None, (
            f"the exact contract pair (id {contract_id!r}, version {contract_version!r}) "
            f"is ambiguous between {', '.join(path for path, _ in matches)}"
        )
    return matches[0][1], None

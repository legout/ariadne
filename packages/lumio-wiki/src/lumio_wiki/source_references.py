"""Strict v1 Source Reference Manifest for Git-native authoring (spec 0008 §3.1).

A versioned ``.lumio-authoring.yaml`` beside ``lumio.yaml`` carries authored
provenance input for Git-native Knowledge Base authoring: a stable KB
namespace, source lifecycle intent, and per-Entity exact SHA-256 bindings. It
is authoring input, never Reader content: it stays out of canonical
fingerprints, public exports, and retrieval, and its digest is bound
separately to the Published Version provenance.

Strictness is the contract: YAML here is parsed by a dedicated block-mapping
parser for the fixed v1 grammar because generic YAML decoders silently accept
duplicate keys (last-wins), while the specification requires rejecting
duplicate keys at every level, unknown fields at every level, malformed
digests, and unsupported versions with a diagnostic instead of silently
ignoring them. Flow styles, anchors, aliases, and block scalars are outside
the normative grammar and are rejected rather than guessed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import msgspec

from lumio_wiki.source_registry import _validate_source_id

#: The manifest's fixed basename beside ``lumio.yaml``.
SOURCE_REFERENCE_MANIFEST_BASENAME = ".lumio-authoring.yaml"

#: The single supported manifest version (spec 0008 §3.1).
SOURCE_REFERENCE_MANIFEST_VERSION = 1

#: A binding digest: exactly 64 lowercase hex characters (SHA-256).
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")

#: A YAML scalar that never needs quoting in the serialized manifest.
_PLAIN_SCALAR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_SOURCE_STATUS_VALUES = ("active", "retired")

_MANIFEST_KEYS = ("version", "namespace", "sources", "bindings")


class SourceReferenceError(ValueError):
    """A Source Reference Manifest is malformed or violates the v1 contract."""


class SourceReferenceManifest(msgspec.Struct, frozen=True):
    """The parsed v1 Source Reference Manifest.

    ``sources`` maps a Source ID to its reviewed lifecycle intent
    (``active``/``retired``); ``bindings`` maps an Entity ID to a mapping of
    declared active Source IDs to the exact SHA-256 digest of the Source
    Version that supports the Entity. Maps serialize in lexicographic key
    order; the reviewed file bytes are what publications digest.
    """

    version: int
    namespace: str
    sources: dict[str, str] = msgspec.field(default_factory=dict)
    bindings: dict[str, dict[str, str]] = msgspec.field(default_factory=dict)


def manifest_digest(raw: bytes) -> str:
    """Return the SHA-256 of the exact reviewed manifest bytes."""
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Strict block-mapping parser for the fixed v1 grammar.
# ---------------------------------------------------------------------------

_DOUBLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
}


def _strip_comment(line: str) -> str:
    """Drop a trailing `` #`` comment (never inside a quoted scalar start)."""
    in_single = in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single and (index == 0 or line[index - 1] != "\\"):
            in_double = not in_double
        elif (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1] in " \t")
        ):
            return line[:index]
    return line


def _scan_quoted(text: str, lineno: int) -> tuple[str, int]:
    """Scan a quoted scalar at the start of ``text``; return (value, end)."""
    quote = text[0]
    out: list[str] = []
    index = 1
    while index < len(text):
        char = text[index]
        if quote == "'":
            if char == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    out.append("'")
                    index += 2
                    continue
                return "".join(out), index + 1
            out.append(char)
            index += 1
            continue
        # Double-quoted.
        if char == "\\":
            if index + 1 >= len(text):
                raise SourceReferenceError(f"line {lineno}: unfinished escape")
            escape = text[index + 1]
            if escape not in _DOUBLE_ESCAPES:
                raise SourceReferenceError(f"line {lineno}: unsupported escape \\{escape}")
            out.append(_DOUBLE_ESCAPES[escape])
            index += 2
            continue
        if char == '"':
            return "".join(out), index + 1
        out.append(char)
        index += 1
    raise SourceReferenceError(f"line {lineno}: unterminated quoted scalar")


def _parse_scalar(text: str, lineno: int) -> Any:
    """Parse one value scalar; ``{}`` denotes an explicitly empty mapping."""
    value = text.strip()
    if not value:
        raise SourceReferenceError(f"line {lineno}: empty scalar")
    if value == "{}":
        return {}
    if value[0] in "'\"":
        scanned, end = _scan_quoted(value, lineno)
        if value[end:].strip():
            raise SourceReferenceError(f"line {lineno}: trailing content after quoted scalar")
        return scanned
    if value[0] in "[{&*|>!%@`":
        raise SourceReferenceError(
            f"line {lineno}: flow styles, anchors, aliases, and block scalars are "
            "not part of the manifest grammar; use block mappings"
        )
    return value


def _parse_line(raw_line: str, lineno: int) -> tuple[int, str, Any, bool]:
    """Parse one manifest line into (indent, key, value, has_value)."""
    line = _strip_comment(raw_line).rstrip()
    if not line.strip():
        return 0, "", None, False
    stripped = line.lstrip(" ")
    if "\t" in line[: len(line) - len(stripped)]:
        raise SourceReferenceError(f"line {lineno}: tabs are not valid indentation")
    indent = len(line) - len(stripped)
    if stripped.startswith("- "):
        raise SourceReferenceError(f"line {lineno}: sequences are not part of the manifest grammar")
    if stripped.startswith("---") or stripped.startswith("..."):
        raise SourceReferenceError(f"line {lineno}: document markers are not allowed")
    if stripped[0] in "'\"":
        key, end = _scan_quoted(stripped, lineno)
        rest = stripped[end:]
        if not rest.startswith(":"):
            raise SourceReferenceError(f"line {lineno}: expected ':' after quoted key")
        rest = rest[1:]
    else:
        split = stripped.find(": ")
        colon_end = split == -1 and stripped.endswith(":")
        if split == -1 and not colon_end:
            raise SourceReferenceError(f"line {lineno}: expected 'key:' mapping entry")
        if colon_end:
            key, rest = stripped[:-1], ""
        else:
            key, rest = stripped[:split], stripped[split + 1 :]
        if not key or key != key.strip():
            raise SourceReferenceError(f"line {lineno}: invalid mapping key")
        if any(char in key for char in "{}[],&*|>!%@`"):
            raise SourceReferenceError(
                f"line {lineno}: plain keys with special characters must be quoted"
            )
    rest_stripped = rest.strip()
    if not rest_stripped:
        return indent, key, None, False
    return indent, key, _parse_scalar(rest_stripped, lineno), True


def _parse_manifest_tree(text: str) -> dict:
    """Parse block mappings into nested dicts, rejecting duplicate keys."""
    entries: list[tuple[int, str, Any, bool, int]] = []
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        indent, key, value, has_value = _parse_line(raw_line, lineno)
        if key == "" and not has_value:
            continue  # blank or comment-only line
        entries.append((indent, key, value, has_value, lineno))
    if not entries:
        raise SourceReferenceError("manifest is empty")

    def build(start: int, indent: int) -> tuple[dict, int]:
        node: dict = {}
        index = start
        while index < len(entries):
            entry_indent, key, value, has_value, lineno = entries[index]
            if entry_indent < indent:
                break
            if entry_indent > indent:
                raise SourceReferenceError(f"line {lineno}: unexpected indentation under '{key}'")
            if key in node:
                raise SourceReferenceError(f"line {lineno}: duplicate key '{key}'")
            if has_value:
                node[key] = value
                index += 1
                continue
            # Nested block: the next entry must be deeper, else an empty map.
            if index + 1 < len(entries) and entries[index + 1][0] > entry_indent:
                child, index = build(index + 1, entries[index + 1][0])
                node[key] = child
            else:
                node[key] = {}
                index += 1
        return node, index

    tree, consumed = build(0, entries[0][0])
    if consumed != len(entries):
        raise SourceReferenceError("inconsistent indentation in manifest")
    return tree


def parse_source_reference_manifest(raw: bytes) -> SourceReferenceManifest:
    """Parse and structurally validate the exact reviewed manifest bytes.

    Rejects unsupported versions, unknown or missing fields, duplicate keys at
    every level, malformed digests, invalid Source IDs, and lifecycle statuses
    other than ``active``/``retired`` — each with a specific diagnostic rather
    than silent tolerance (spec 0008 §3.1).
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceReferenceError(f"manifest is not valid UTF-8: {exc}") from exc
    tree = _parse_manifest_tree(text)

    unknown = sorted(set(tree) - set(_MANIFEST_KEYS))
    if unknown:
        raise SourceReferenceError(f"unknown manifest field(s): {', '.join(unknown)}")
    missing = [key for key in _MANIFEST_KEYS if key not in tree]
    if missing:
        raise SourceReferenceError(f"missing required manifest field(s): {', '.join(missing)}")

    version = tree["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+", version):
        raise SourceReferenceError("manifest version must be the integer 1")
    if int(version) != SOURCE_REFERENCE_MANIFEST_VERSION:
        raise SourceReferenceError(
            f"unsupported manifest version {version!r}: this Lumio supports "
            f"version {SOURCE_REFERENCE_MANIFEST_VERSION} only"
        )

    namespace = tree["namespace"]
    if not isinstance(namespace, str) or not namespace.strip():
        raise SourceReferenceError("manifest namespace must be a non-empty string")

    sources_raw = tree["sources"]
    if not isinstance(sources_raw, dict):
        raise SourceReferenceError("manifest 'sources' must be a mapping")
    sources: dict[str, str] = {}
    for source_id, entry in sorted(sources_raw.items()):
        if not isinstance(source_id, str) or not source_id:
            raise SourceReferenceError("source id keys must be non-empty strings")
        try:
            _validate_source_id(source_id)
        except ValueError as exc:
            raise SourceReferenceError(f"invalid source id in manifest: {exc}") from exc
        if not isinstance(entry, dict):
            raise SourceReferenceError(f"source '{source_id}' entry must be a mapping")
        unknown_entry = sorted(set(entry) - {"status"})
        if unknown_entry:
            raise SourceReferenceError(
                f"source '{source_id}' has unknown field(s): {', '.join(unknown_entry)}"
            )
        status = entry.get("status")
        if status not in _SOURCE_STATUS_VALUES:
            raise SourceReferenceError(
                f"source '{source_id}' status must be 'active' or 'retired', got {status!r}"
            )
        sources[source_id] = status

    bindings_raw = tree["bindings"]
    if not isinstance(bindings_raw, dict):
        raise SourceReferenceError("manifest 'bindings' must be a mapping")
    bindings: dict[str, dict[str, str]] = {}
    for entity_id, entry in sorted(bindings_raw.items()):
        if not isinstance(entity_id, str) or not entity_id.strip():
            raise SourceReferenceError("binding keys must be non-empty Entity IDs")
        if not isinstance(entry, dict):
            raise SourceReferenceError(f"binding '{entity_id}' must be a mapping")
        entity_bindings: dict[str, str] = {}
        for source_id, digest in sorted(entry.items()):
            if not isinstance(source_id, str) or not source_id:
                raise SourceReferenceError(
                    f"binding '{entity_id}' has a non-empty source id requirement"
                )
            if source_id not in sources:
                raise SourceReferenceError(
                    f"binding '{entity_id}' references undeclared source '{source_id}'"
                )
            if sources[source_id] != "active":
                raise SourceReferenceError(
                    f"binding '{entity_id}' -> '{source_id}' is not allowed: retired "
                    "sources cannot have supporting bindings"
                )
            if not isinstance(digest, str) or not _DIGEST_PATTERN.match(digest):
                raise SourceReferenceError(
                    f"binding '{entity_id}' -> '{source_id}' must be a 64-character "
                    "lowercase SHA-256 digest"
                )
            entity_bindings[source_id] = digest
        bindings[entity_id] = entity_bindings

    return SourceReferenceManifest(
        version=SOURCE_REFERENCE_MANIFEST_VERSION,
        namespace=namespace,
        sources=sources,
        bindings=bindings,
    )


def load_source_reference_manifest(kb_root: str | Path) -> SourceReferenceManifest | None:
    """Load and parse the manifest beside ``lumio.yaml``; ``None`` when absent.

    A present-but-malformed manifest raises :class:`SourceReferenceError` — a
    Git authoring operation never falls back to the legacy proposal route over
    an invalid manifest.
    """
    path = Path(kb_root) / SOURCE_REFERENCE_MANIFEST_BASENAME
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    return parse_source_reference_manifest(raw)


def _quote(value: str) -> str:
    if _PLAIN_SCALAR_PATTERN.match(value):
        return value
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    )
    return f'"{escaped}"'


def serialize_source_reference_manifest(manifest: SourceReferenceManifest) -> bytes:
    """Serialize the manifest as canonical block YAML with sorted map keys."""
    if manifest.version != SOURCE_REFERENCE_MANIFEST_VERSION:
        raise SourceReferenceError("cannot serialize an unsupported manifest version")
    lines = [
        f"version: {manifest.version}",
        f"namespace: {_quote(manifest.namespace)}",
    ]
    if manifest.sources:
        lines.append("sources:")
        for source_id in sorted(manifest.sources):
            lines.append(f"  {_quote(source_id)}:")
            lines.append(f"    status: {manifest.sources[source_id]}")
    else:
        lines.append("sources: {}")
    if manifest.bindings:
        lines.append("bindings:")
        for entity_id in sorted(manifest.bindings):
            entity_bindings = manifest.bindings[entity_id]
            if not entity_bindings:
                lines.append(f"  {_quote(entity_id)}: {{}}")
                continue
            lines.append(f"  {_quote(entity_id)}:")
            for source_id in sorted(entity_bindings):
                lines.append(f"    {_quote(source_id)}: {entity_bindings[source_id]}")
    else:
        lines.append("bindings: {}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def upsert_binding(
    manifest: SourceReferenceManifest,
    entity_id: str,
    source_id: str,
    digest: str,
) -> SourceReferenceManifest:
    """Return a new manifest with one exact binding recorded as active support.

    The deterministic ingest helper: it declares the source active when it is
    new and sets the Entity's binding to the exact digest, replacing a prior
    binding for the same source on that Entity. Structural validity is
    re-checked so a helper can never persist a malformed manifest.
    """
    sources = dict(manifest.sources)
    sources[source_id] = "active"
    entity_bindings = dict(manifest.bindings.get(entity_id, {}))
    entity_bindings[source_id] = digest
    bindings = dict(manifest.bindings)
    bindings[entity_id] = entity_bindings
    updated = SourceReferenceManifest(
        version=manifest.version,
        namespace=manifest.namespace,
        sources=sources,
        bindings=bindings,
    )
    # Round-trip through the strict parser: the helper's output must satisfy
    # the same contract as a hand-authored manifest.
    parse_source_reference_manifest(serialize_source_reference_manifest(updated))
    return updated


def validate_source_references(
    manifest: SourceReferenceManifest,
    kb: Any,
    *,
    registry: Any = None,
) -> list[str]:
    """Cross-check the manifest against the selected Knowledge Base.

    Returns collected findings (empty list = valid): dangling Entity IDs,
    bindings whose Source ID the page does not declare, missing bindings for
    declared active managed sources, managed non-synthetic pages without
    eligible support, and — when a private registry is selected — bindings
    that resolve to no exact registered Source Version (fail closed, never
    registry-latest). Page Source IDs absent from the manifest are public-only
    provenance and stay supported; they are disclosed by the review, not
    rejected here.
    """
    issues: list[str] = []
    page_by_entity = {page.id: page for page in kb.pages if getattr(page, "id", None)}
    for entity_id, entity_bindings in sorted(manifest.bindings.items()):
        page = page_by_entity.get(entity_id)
        if page is None:
            issues.append(
                f"binding key '{entity_id}' does not resolve to an Entity in the "
                "selected Knowledge Base"
            )
            continue
        declared_source_ids = {source.id for source in page.sources if source.id}
        for source_id in sorted(entity_bindings):
            if source_id not in declared_source_ids:
                issues.append(
                    f"binding '{entity_id}' -> '{source_id}' is not declared in that "
                    f"page's sources[].id ({page.path})"
                )
            if registry is not None:
                found = registry.find_version(source_id, entity_bindings[source_id])
                if found is None:
                    issues.append(
                        f"binding '{entity_id}' -> '{source_id}' does not resolve to "
                        "an exact registered Source Version"
                    )
    for page in kb.pages:
        entity_id = getattr(page, "id", None)
        source_ids = [source.id for source in page.sources if source.id]
        managed = [source_id for source_id in source_ids if source_id in manifest.sources]
        if not managed:
            continue
        if not entity_id:
            issues.append(
                f"page '{page.title}' cites managed source(s) {', '.join(sorted(managed))} "
                "but carries no Entity ID; managed authoring requires the v2 Entity contract"
            )
            continue
        entity_bindings = manifest.bindings.get(entity_id, {})
        active_managed = [
            source_id for source_id in managed if manifest.sources[source_id] == "active"
        ]
        missing = [
            source_id for source_id in active_managed if entity_bindings.get(source_id) is None
        ]
        if missing:
            issues.append(
                f"page '{page.title}' ({entity_id}) requires an exact binding for "
                f"active managed source(s): {', '.join(sorted(missing))}"
            )
        if not page.synthetic and not any(
            manifest.sources.get(source_id) == "active" for source_id in entity_bindings
        ):
            issues.append(
                f"managed non-synthetic page '{page.title}' ({entity_id}) has no "
                "eligible supporting binding; an explicit reviewed reclassification "
                "or Page Removal is required"
            )
    return issues

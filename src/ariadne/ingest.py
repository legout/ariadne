"""Revision-bound document ingestion for native Git authoring candidates.

``ariadne-ingest`` reads references only from the operator's configured local
roots or exact approved object-store URIs, captures each source digest and
converted text from one byte snapshot, and writes generated OKF pages through
the existing revision-checked proposal edit seam. It never writes a staging
catalog, retains original bytes, or admits the candidate. Verbatim mode skips
the model and preserves the converter's text exactly; ordinary reconciliation
compares against the immutable admitted snapshot and keeps Policy egress
opt-in.

Converter dispatch remains optional via ``[documents]``::

    .md .txt                                  native read (no dependencies)
    .pdf                                      liteparse
    .docx .pptx .xlsx .html                   markitdown[docx]
    .doc .rtf .epub .csv .odt .ods .odp .xls  firecrawl-anydoc (imports as ``anydoc``)

The LLM call reuses the author's OpenAI-compatible wiring (``OPENAI_*`` loaded
from ``ARIADNE_ENV``). Core assembles provenance/lifecycle metadata, validates
each page and scans credentials before writing. Each successful artifact edit
uses the current candidate revision; collisions create a new suffixed page,
not an overwrite. Partial batches report actual writes and the resulting
candidate revision.

Interfaces::

    ingest(docs, *, project, proposal, expected_revision, complete=None, verbatim=False)
        -> {proposal, base_revision, candidate_revision, written, unchanged, errors}
    reconcile_ingest(docs, *, project, proposal, expected_revision, complete=None)
        -> (ingest result, comparisons)   # opt-in, spec 2026-09-23-0004
    ariadne-ingest DOC... --project DIR --proposal ID --expected-revision REV
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from ariadne.author import _default_complete
from ariadne.context import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    _FRONTMATTER_RE,
    _page_contract_errors,
)

MAX_RETRIES = 2  # ≤2 retry rounds on contract violations (rev 8 brief; author allows 3 total)
CONTEXT_SUBDIR = "context_layer"

# Bundle taxonomy ingest may classify into (ADR-0009): folder -> frontmatter type.
# metrics/computations/skills stay author-owned (metric pages need OSI-model
# enrichment ingest cannot compute), so proposing them is a contract violation.
_ALLOWED_FOLDERS = {
    "tables": "table",
    "policies": "policy",
    "references": "reference",
    "references/joins": "reference",
}

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")  # slug; no slashes/dots: no path tricks

# Credential classes rejected before a candidate edit: LLM output is untrusted,
# so a secret from the source document must never enter an authored artifact.
# Violations name the CLASS only — the matched text is never reproduced.
# (sk- allows -/_ so real sk-proj-... keys match; assignments are same-line so
# prose ending in the word "token" cannot false-positive across newlines.)
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("api_token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("credential_assignment", re.compile(r"\b(password|secret|token|api_key)[ \t]*[=:][ \t]*\S+")),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}")),
)

_NATIVE_SUFFIXES = (".md", ".txt")


def _convert_native(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _convert_pdf(path: Path) -> str:
    # Lazy import: the [documents] extra is optional (ADR-0009); a missing
    # converter must surface as the actionable install hint, not a crash.
    # liteparse's package __init__ exposes LiteParse through a runtime
    # __getattr__ mapping pyright cannot follow — import the real submodule.
    from liteparse.parser import LiteParse  # pyright: ignore[reportMissingImports]

    # liteparse's shipped type hints lag its runtime API (total_pages/get_page
    # exist and return Optional[ParsedPage]) — an Any annotation sidesteps the stub.
    parser: Any = LiteParse()
    result = parser.parse(str(path))
    chunks: list[str] = []
    for number in range(1, int(result.total_pages) + 1):
        page = result.get_page(number)
        if page is not None:
            chunks.append(page.markdown or page.text or "")
    return "\n\n".join(chunks).strip()


def _convert_markitdown(path: Path) -> str:
    from markitdown import MarkItDown  # pyright: ignore[reportMissingImports]

    return MarkItDown().convert(str(path)).text_content or ""


def _convert_anydoc(path: Path) -> str:
    import anydoc  # pyright: ignore[reportMissingImports] — optional [documents] extra

    return anydoc.to_markdown(str(path))


# suffix -> (converter, pip requirement to name in the missing-extra error)
_CONVERTERS: dict[str, tuple] = {
    ".pdf": (_convert_pdf, "liteparse"),
    ".docx": (_convert_markitdown, "markitdown[docx]"),
    ".pptx": (_convert_markitdown, "markitdown[docx]"),
    ".xlsx": (_convert_markitdown, "markitdown[docx]"),
    ".html": (_convert_markitdown, "markitdown[docx]"),
    ".doc": (_convert_anydoc, "firecrawl-anydoc"),
    ".rtf": (_convert_anydoc, "firecrawl-anydoc"),
    ".epub": (_convert_anydoc, "firecrawl-anydoc"),
    ".csv": (_convert_anydoc, "firecrawl-anydoc"),
    ".odt": (_convert_anydoc, "firecrawl-anydoc"),
    ".ods": (_convert_anydoc, "firecrawl-anydoc"),
    ".odp": (_convert_anydoc, "firecrawl-anydoc"),
    ".xls": (_convert_anydoc, "firecrawl-anydoc"),
}

_INSTALL_HINT = 'install the [documents] extra: uv pip install -e ".[documents]"'


class _ConversionError(Exception):
    """One document could not be converted; message is user-facing and actionable."""


def _convert(path: Path) -> str:
    """Dispatch one document to Markdown by extension (see module docstring)."""
    suffix = path.suffix.lower()
    if suffix in _NATIVE_SUFFIXES:
        return _convert_native(path)
    entry = _CONVERTERS.get(suffix)
    if entry is None:
        supported = ", ".join((*_NATIVE_SUFFIXES, *sorted(_CONVERTERS)))
        raise _ConversionError(
            f"{path}: unsupported document type '{suffix or '(no extension)'}'. "
            f"Supported: {supported}. For the converter formats, {_INSTALL_HINT}. "
            "Nothing was written."
        )
    convert, requirement = entry
    try:
        return convert(path)
    except ImportError:
        raise _ConversionError(
            f"{path}: converting '{suffix}' needs the optional '{requirement}' package — "
            f"{_INSTALL_HINT}. Nothing was written."
        ) from None
    except _ConversionError:
        raise
    except Exception as exc:  # converter present but choked on this document
        raise _ConversionError(f"{path}: conversion failed: {type(exc).__name__}: {exc}") from exc


_SYSTEM_PROMPT = """\
You are the Ariadne ingestion agent (ADR-0009). From one converted source \
document you distill typed Context Layer (OKF) pages classified into the \
existing bundle taxonomy.

Return ONE JSON object and nothing else — no markdown fences, no commentary:
{"pages": [{"folder": "...", "name": "...", "type": "...", "title": "...",
            "description": "...", "tags": ["..."], "grain": {...}, "body": "..."}]}
("grain" only on table pages.)

Classification:
- A rule the data owner applies when computing (status semantics, exclusions, \
currency or timing cutovers) -> folder "policies", type "policy". Policies are \
the owner's words: transcribe VERBATIM, never reinterpret. One page per \
independent rule.
- A fact about what one row of a table means, its columns, or its declared \
grain -> folder "tables", type "table". Add "grain": {"primary_key": [...], \
"cardinality_enforcement": "STRICT_1_TO_1"} only when the document STATES \
the row identity (that cited statement is the declared authority); otherwise \
name the real cardinality or omit the grain block — a physical table's \
Grain may stay unknown. Observed or plausible uniqueness alone is never a \
declared business key.
- A relationship between tables (join keys, cardinality) -> folder \
"references/joins", type "reference".
- A shared business term or identifier meaning with its documented aliases \
and field bindings -> folder "references", type "reference". You may \
include "aliases": [...] and the structured declaration \
"ariadne": {"version": 1, "reference_role": "term"|"identifier"|"enum", \
"representations": [{"id": ..., "aliases": [...], \
"fields": [{"resource": ..., "column": ...}], "scope": []}], \
"mappings": [...]} — transcribe ONLY what the document states. Bindings name \
canonical table resources (ariadne://table/...); NEVER add measured counts, \
receipts, approval or confirmation states. A mapping citing the document \
itself uses "source_ids": ["@document"] — ingestion binds that token to the \
document's citation id mechanically. The ariadne declaration belongs \
to references ONLY: never attach it to a table or policy page.
- Any other knowledge worth keeping (glossary, background, meeting notes) -> \
folder "references", type "reference", and include the tag "ingest".
- Distill only what the document supports: never invent columns, keys, \
numbers, or rules. One or many pages; return an empty pages list only when \
nothing in the document is worth keeping.

Page contract (violations are fed back to you for repair, at most 2 retries):
- name: a short lowercase slug (becomes <name>.md). Never "index" or "log".
- Allowed folder/type pairs: tables/table, policies/policy, \
references/reference, references/joins/reference. metrics/computations/skills \
are author-owned: never propose them.
- title and description: single-line plain text; description is one sentence.
- tags: a JSON list of lowercase keywords.
- body: the full markdown page body WITHOUT frontmatter — provenance and \
lifecycle fields are attached mechanically; never write YAML yourself.
"""


def _user_prompt(text: str, filename: str, citation_id: str) -> str:
    return (
        f"Source document: {filename} (already converted to markdown)\n"
        f"Document citation id: {citation_id} — this id identifies the document "
        "in the candidate; a mapping citing the document itself uses the token "
        '"@document" in source_ids and ingestion binds it to this id.\n\n'
        f"<document>\n{text.strip()}\n</document>\n\n"
        "Distill it into typed OKF pages now. Return only the JSON object."
    )


# The explicit input-document citation token (K2, spec 0010 §4: domain
# claims cite the ACTUAL input document): the digest footnote id is
# core-owned, never guessed by the model — a mapping cites the document
# itself with this token and _assemble binds the real citation id
# mechanically, like every other mechanical provenance field.
_DOCUMENT_CITATION_TOKEN = "@document"


def _bind_document_citations(extension: dict, citation_id: str) -> dict:
    """Bind every ``@document`` mapping-citation token to the input document's
    ACTUAL citation id: validation then resolves it like any authored
    source_id, so a mapping citing the actual input document survives
    ingestion instead of failing the footnote-resolution gate."""
    for mapping in extension.get("mappings") or []:
        if not isinstance(mapping, dict):
            continue
        source_ids = mapping.get("source_ids")
        if isinstance(source_ids, list):
            mapping["source_ids"] = [
                citation_id if source_id == _DOCUMENT_CITATION_TOKEN else source_id
                for source_id in source_ids
            ]
    return extension


def _parse_pages(raw: str) -> list[dict]:
    """Parse the LLM response into page entries (tolerates <think> and fences)."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = re.sub(r"\A```[a-zA-Z0-9_-]*\n|\n```\Z", "", text)
    data = json.loads(text)
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        raise ValueError("response must be a JSON object with a 'pages' list")
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("every entry in 'pages' must be an object")
    return pages


def _assemble(
    entries: list[dict], source: dict, model: str, now: str
) -> tuple[list[tuple], list[str]]:
    """Build (folder, name, full page text) triples plus contract violations.

    Frontmatter the pipeline knows mechanically (type/status/sources/generated)
    is attached here, never asked of the LLM (author discipline)."""
    pages: list[tuple[str, str, str]] = []
    errors: list[str] = []
    for position, entry in enumerate(entries):
        rel = f"pages[{position}]"
        folder = str(entry.get("folder") or "")
        expected = _ALLOWED_FOLDERS.get(folder)
        if expected is None:
            errors.append(
                f"{rel}: folder must be one of {sorted(_ALLOWED_FOLDERS)} (got "
                f"{folder!r}); metrics/computations/skills are author-owned"
            )
            continue
        if str(entry.get("type") or "") != expected:
            errors.append(
                f"{rel}: folder {folder!r} requires type '{expected}' (got {entry.get('type')!r})"
            )
            continue
        name = str(entry.get("name") or "")
        if not _NAME_RE.fullmatch(name):
            errors.append(f"{rel}: name must be a lowercase slug (got {name!r})")
            continue
        if name in ("index", "log"):
            errors.append(f"{rel}: name '{name}' is bundle bookkeeping (promote-owned)")
            continue
        title = str(entry.get("title") or "").strip()
        description = str(entry.get("description") or "").strip()
        tags = entry.get("tags")
        body = str(entry.get("body") or "").strip()
        if not title:
            errors.append(f"{rel}: title must be a non-empty single line")
        if not description:
            errors.append(f"{rel}: description must be a non-empty one-sentence summary")
        if not body:
            errors.append(f"{rel}: body must be non-empty markdown")
        if (
            not isinstance(tags, list)
            or not tags
            or not all(isinstance(tag, str) and tag.strip() for tag in tags)
        ):
            errors.append(f"{rel}: tags must be a non-empty JSON list of strings")
            tags = []
        front: dict = {
            "type": expected,
            "status": "draft",
            "title": title,
            "description": description,
            "tags": cast("list[str]", tags),
            "sources": [source],
            "generated": {"by": f"ariadne-ingest:{model}", "at": now},
        }
        if expected == "table" and isinstance(entry.get("grain"), dict):
            front["grain"] = entry["grain"]  # per-type gate validates the block
        # K2 (issue #42, spec 0010 §3/§5): the ALLOWLISTED structured Reference
        # declarations survive ordinary candidate edits — page aliases and the
        # versioned ``ariadne`` extension — with the document's own provenance
        # (sources above); everything else the entry carries stays ignored.
        # The extension belongs to References ONLY (spec 0010 §3): a table or
        # policy entry carrying one — fabricated authority/measurements
        # included, since table/dataset ariadne facts are core-owned, never
        # distilled — is refused outright, never laundered by silently
        # preserving or dropping the block. The shared per-type gate below
        # then validates the preserved declaration (it rejects fabricated
        # approval/measurement claims wherever they hide).
        aliases = entry.get("aliases")
        if aliases is not None:
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias.strip() for alias in aliases
            ):
                errors.append(
                    f"{rel}: aliases must be a list of non-empty strings naming the concept"
                )
            else:
                front["aliases"] = aliases
        extension = entry.get("ariadne")
        if extension is not None and expected != "reference":
            errors.append(
                f"{rel}: the ariadne extension belongs to References (spec 0010 §3) "
                f"— a {expected} page carries no structured declaration, and "
                "authority/measurement claims are never added to candidate content; remove it"
            )
        elif extension is not None:
            if not isinstance(extension, dict):
                errors.append(
                    f"{rel}: ariadne must be the structured Reference declaration "
                    "(a mapping with version/reference_role/representations/mappings)"
                )
            else:
                front["ariadne"] = _bind_document_citations(extension, source["id"])
        front_yaml = yaml.safe_dump(front, default_flow_style=False, sort_keys=False).strip()
        pages.append((folder, name, f"---\n{front_yaml}\n---\n\n{body}\n"))
    return pages, errors


def _secret_violations(pages: list[tuple]) -> list[str]:
    """Reject pages whose fully-rendered text (frontmatter values + body)
    matches a credential pattern. The violation names the pattern CLASS,
    never the secret itself, so the retry loop can continue without it."""
    violations: list[str] = []
    for position, (_folder, _name, text) in enumerate(pages):
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                violations.append(
                    f"pages[{position}]: appears to contain a {label} credential — "
                    "remove it and re-send; secrets are never written to the candidate"
                )
                break  # one class names the rejection; drop the page
    return violations


def _contract_errors(pages: list[tuple]) -> list[str]:
    """Run the per-type gate in temporary scratch before any candidate edit."""
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths: list[tuple[Path, str]] = []
        for folder, name, text in pages:
            page = root / CONTEXT_SUBDIR / folder / f"{name}.md"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(text, encoding="utf-8")
            paths.append((page, _ALLOWED_FOLDERS[folder]))
        for page, expected_type in paths:
            errors.extend(_page_contract_errors(root, page, expected_type))
    return errors


def _distill(
    text: str, *, filename: str, source: dict, complete, now: str
) -> tuple[list[tuple], list[str], str]:
    """Distill one already-snapshotted document and return gate-clean pages."""
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(text, filename, source["id"])},
    ]
    violations: list[str] = []
    for attempt in range(1 + MAX_RETRIES):
        raw = complete(messages)
        model = os.environ.get("OPENAI_MODEL") or "unknown"
        try:
            entries = _parse_pages(raw)
        except Exception as exc:  # unparseable response: feed the parse error back
            violations = [f"response violated the JSON page contract: {exc}"]
        else:
            pages, violations = _assemble(entries, source, model, now)
            if not violations:
                violations = _secret_violations(pages)
            if not violations:
                violations = _contract_errors(pages)
            if not violations:
                return pages, [], text
        print(
            f"ariadne-ingest: {filename}: attempt {attempt + 1}: "
            f"{len(violations)} contract violation(s), feeding back",
            flush=True,
        )
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": "Contract violations:\n- "
                + "\n- ".join(violations)
                + "\nFix them and return the full JSON object again.",
            }
        )
    print(
        f"ariadne-ingest: {filename}: still violating after 1 + {MAX_RETRIES} "
        "attempts — nothing was written",
        flush=True,
    )
    return [], violations, text


# --- opt-in verbatim mode (spec 2026-10-13-0021, issue #66): preserve, never distill ---

_VERBATIM_BY = "ariadne-ingest:verbatim"  # generated.by stamp of the no-model mode
_VERBATIM_FOLDER = "references"  # every verbatim document is one draft Reference
# The retry comparison masks ONLY the ``generated`` timestamp VALUE, and only
# in the exact serialized line _verbatim_page writes it: two-space indent,
# single-quoted UTC ISO-8601 seconds stamp (PyYAML always quotes that value —
# verified deterministic). Any OTHER byte on that line — an appended comment,
# a changed key/indentation, a corrupted or non-timestamp value — stays
# unmasked and counts as changed (spec §4), as does every other byte of the
# candidate; if the renderer ever changed form, retries fail SAFE toward
# writing a new candidate draft, never toward a false 'unchanged'.
_AT_LINE_RE = re.compile(r"(?m)^  at: '\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00'$")


def _verbatim_name(doc: Path) -> str | None:
    """Safe page name derived mechanically from the filename (spec §2), or None
    when the stem yields no slug or collides with promote-owned bookkeeping —
    the same name discipline as distilled pages."""
    slug = re.sub(r"[^a-z0-9_-]+", "-", doc.stem.lower()).strip("-_")
    if _NAME_RE.fullmatch(slug) and slug not in ("index", "log"):
        return slug
    return None


def _verbatim_page(filename: str, text: str, source: dict, now: str) -> tuple[str, str, str]:
    """Render one draft Reference without changing the converter's text."""
    name = _verbatim_name(Path(filename))
    if name is None:
        raise ValueError(
            f"{filename}: filename yields no safe page name (empty slugs and "
            "the promote-owned 'index'/'log' are refused)"
        )
    front: dict = {
        "type": "reference",
        "status": "draft",
        "title": Path(filename).stem,
        "description": f"Verbatim preservation of {filename} (unmodified converter output).",
        "tags": ["ingest", "verbatim"],
        "sources": [source],
        "generated": {"by": _VERBATIM_BY, "at": now},
    }
    front_yaml = yaml.safe_dump(front, default_flow_style=False, sort_keys=False).strip()
    return _VERBATIM_FOLDER, name, f"---\n{front_yaml}\n---\n\n{text}"


def _mask_generation_time(text: str) -> str | None:
    """The page text with ONLY the generation timestamp's exact serialized
    line replaced by a constant — every other byte (the rest of an edited
    ``  at: `` line included, delimiters, blank lines, body) preserved — or
    None when the text has no frontmatter block."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    start, end = match.span(1)
    return text[:start] + _AT_LINE_RE.sub("  at: @", text[start:end]) + text[end:]


def _candidate_page_unchanged(existing_text: str, page_text: str) -> bool:
    """True only when candidate bytes match, modulo the generated timestamp."""
    masked = _mask_generation_time(existing_text)
    return masked is not None and masked == _mask_generation_time(page_text)


def _source_snapshot(reference: str | Path, project: Path) -> tuple[str, str, dict]:
    """Read one operator-authorized source once; digest and text share bytes."""
    from ariadne.authoring_inputs import _convert_snapshot, _document_bytes

    resource, filename, data = _document_bytes(str(reference), project)
    text = _convert_snapshot(data, Path(filename).suffix, display=filename)
    source = {
        "id": hashlib.sha256(data).hexdigest()[:12],
        "resource": resource,
        "title": filename,
    }
    return filename, text, source


def _document_pages(
    reference: str | Path, project: Path, *, complete, now: str, verbatim: bool
) -> tuple[list[tuple], list[str], str]:
    try:
        filename, text, source = _source_snapshot(reference, project)
    except (OSError, ValueError, _ConversionError) as exc:
        shown = _redact_credential_matches(str(reference))
        return [], [f"{shown}: {_redact_credential_matches(str(exc))}"], ""
    if verbatim:
        if not text.strip():
            return [], [f"{filename}: converted text is empty (whitespace only)"], text
        try:
            page = _verbatim_page(filename, text, source, now)
        except ValueError as exc:
            return [], [str(exc)], text
        errors = _contract_errors([page])
        if not errors:
            errors = _secret_violations([page])
        return ([], errors, text) if errors else ([page], [], text)
    return _distill(text, filename=filename, source=source, complete=complete, now=now)


def _proposal_state(project: Path, proposal: str, expected_revision: str):
    from ariadne import proposals

    record = proposals._load_record(project, proposal)
    proposals._check_coherent(project, record)
    current = record["candidate_revision"]
    if expected_revision != current:
        raise ValueError(
            f"stale revision: proposal {proposal} is at candidate {current}, the ingest "
            f"expected {expected_revision} — re-read the candidate and retry; nothing was written"
        )
    return record, current


def _context_pages(project: Path, revision: str) -> dict[str, str]:
    from ariadne import proposals

    return {
        rel: blob.decode("utf-8", errors="replace")
        for rel, blob in proposals.scope_blobs(project, revision)
        if rel.startswith(f"{CONTEXT_SUBDIR}/") and rel.endswith(".md")
    }


def _candidate_page_target(
    pages: dict[str, str], folder: str, name: str, page_text: str
) -> tuple[str, str | None]:
    """Find an unchanged source/page in the complete suffix family, else the
    first free Git artifact path. Existing candidate bytes are never replaced."""
    directory = f"{CONTEXT_SUBDIR}/{folder}/"
    family = re.compile(rf"^{re.escape(directory + name)}(?:-(\d+))?\.md$")
    matches = [(rel, match) for rel in pages if (match := family.fullmatch(rel)) is not None]
    matches.sort(
        key=lambda item: (
            (0,) if item[1].group(1) is None else (len(item[1].group(1)), item[1].group(1))
        )
    )
    for rel, _match in matches:
        existing = pages[rel]
        if _candidate_page_unchanged(existing, page_text):
            return rel, existing
    suffix = 1
    while True:
        rel = f"{directory}{name if suffix == 1 else f'{name}-{suffix}'}.md"
        if rel not in pages:
            return rel, None
        suffix += 1


def ingest(
    docs: list[str | Path],
    *,
    project: str | Path,
    proposal: str,
    expected_revision: str,
    complete=None,
    verbatim: bool = False,
) -> dict:
    """Write derived pages to one revision-checked Git candidate.

    Sources are resolved only through the host project's operator-managed
    document boundary. Each durable edit is its own Git commit; partial batches
    report the paths and revision that actually remain in the candidate."""
    from ariadne import proposals

    root = Path(project).resolve()
    record, current_revision = _proposal_state(root, proposal, expected_revision)
    base_revision = record["base_revision"]
    candidate_pages = _context_pages(root, current_revision)
    complete = complete or _default_complete
    now = datetime.now(UTC).isoformat(timespec="seconds")
    written: list[str] = []
    unchanged: list[str] = []
    errors: list[str] = []
    mutation_failed = False

    for reference in docs:
        pages, doc_errors, _converted = _document_pages(
            reference, root, complete=complete, now=now, verbatim=verbatim
        )
        if doc_errors:
            errors.extend(doc_errors)
            continue
        for folder, name, page_text in pages:
            rel, existing_text = _candidate_page_target(candidate_pages, folder, name, page_text)
            content = existing_text if existing_text is not None else page_text
            try:
                result = proposals.edit_proposal(
                    root, proposal, current_revision, rel, content, core_generated=True
                )
            except Exception as exc:
                errors.append(
                    f"{reference}: candidate edit failed: {_redact_credential_matches(str(exc))}"
                )
                mutation_failed = True
                break
            current_revision = result["revision"]
            candidate_pages[rel] = content
            target = written if result["changed"] else unchanged
            if rel not in target:
                target.append(rel)
        if mutation_failed:
            break

    try:
        current_revision = proposals._load_record(root, proposal)["candidate_revision"]
    except Exception as exc:
        if not errors:
            errors.append(f"candidate revision is unavailable after ingest: {type(exc).__name__}")
    return {
        "proposal": proposal,
        "base_revision": base_revision,
        "candidate_revision": current_revision,
        "written": written,
        "unchanged": unchanged,
        "errors": errors,
    }


# --- opt-in evidence reconciliation (spec 2026-09-23-0004 rev 1, ADR-0003/0009) ---
# Deterministic identity + candidate comparison (issue #12 validation unit A) plus the
# explicitly opt-in conflict advisory (unit B): only a same-path matched
# APPROVED Policy with changed body text is ever sent to the configured
# ingestion model, after the existing credential-pattern refusal — never any
# other approved page, never `verified` identities.

_DIFF_LINE_CAP = 60  # bounded human-readable diff: review output stays readable
# Frontmatter excluded from owner-content comparison: promotion bookkeeping
# (status/verified/generated, promote.py's no-op key) and source provenance,
# which is compared separately as digest identity (provenance_only class).
_BOOKKEEPING_KEYS = ("status", "verified", "generated", "sources")


@dataclass
class Advisory:
    """Fallible conflict advice for the human reviewer (spec 2026-09-23-0004):
    it never promotes, blocks, rewrites, or sets review_needed — a suggestion
    with no verbatim-verified quote is not evidence."""

    status: str  # "supported" | "unverified" | "none" | "unavailable" | "not_applicable"
    reason: str = ""  # e.g. credential-pattern class or provider-failure cause
    note: str = ""  # the model's one-line conflict note, when it suggested one
    quotes: list[dict] | None = None  # [{text, verified}] — only verified ones are evidence


@dataclass
class Reconciliation:
    """One proposed page compared against the approved Context Layer."""

    proposal: str  # context-layer-relative proposed path, e.g. policies/x.md
    match: str  # "same-path" (matched an approved page) | "new" (unmatched)
    change: str  # "changed" | "provenance_only" | "unchanged" | "new"
    new_source: dict  # proposal's {resource, digest}
    old_source: dict | None = None  # matched approved page's {resource, digest}
    diff: str = ""  # bounded unified diff of owner content (changed only)
    warning: str | None = None  # e.g. possible-duplicate on path drift
    candidate_path: str | None = None  # artifact-relative path in the candidate
    advisory: Advisory = field(  # not_applicable unless eligible (unit B)
        default_factory=lambda: Advisory("not_applicable")
    )


_ADVISORY_ABSENT_NOTE = "model offered no conflict suggestion — absence is not proof of consistency"

_ADVISORY_SYSTEM_PROMPT = """\
You are the Ariadne reconciliation advisor (spec 2026-09-23-0004). You see \
ONE converted source document and ONE approved Policy that a new proposal \
would replace. Determine whether the revised document possibly CONFLICTS \
with the approved Policy (contradiction, dropped constraint, changed \
obligation).

Return ONE JSON object and nothing else — no markdown fences, no commentary:
{"possible_conflict": true|false, "note": "<one line>", "quotes": ["<passage>", ...]}
Each quote MUST be copied VERBATIM from the document or the approved Policy \
and must support the note. If there is no possible conflict, return \
{"possible_conflict": false} with no quotes. Never invent quotations.
"""


def _advisory_user_prompt(
    document: str, filename: str, title: str, body: str, identity: dict
) -> str:
    """The minimal disclosure payload (ADR-0009 clarification): the converted
    input plus ONLY the matched approved Policy's title, body and source
    identity — never its verified identities or unrelated pages."""
    return (
        f"Source document: {filename} (already converted to markdown)\n\n"
        f"<document>\n{document.strip()}\n</document>\n\n"
        f'<approved_policy resource="{identity["resource"]}" '
        f'digest="{identity["digest"]}" title="{title}">\n{body.strip()}\n</approved_policy>\n\n'
        "Is there a possible conflict? Return only the JSON object."
    )


def _parse_advisory(raw: str) -> dict:
    """Parse the advisory JSON (tolerates <think> blocks and fences like the
    distillation response)."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if text.startswith("```"):
        text = re.sub(r"\A```[a-zA-Z0-9_-]*\n|\n```\Z", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("advisory response must be a JSON object")
    return data


# A recognized PEM private key must redact as ONE BLOCK — the header-only
# pattern above would leave the base64 payload and END marker in review output
# (owner-authorized unit-B delta finding). The optional END alternation also
# swallows a dangling BEGIN whose END marker never arrived.
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN[A-Z ]*PRIVATE KEY-----.*?(?:-----END[A-Z ]*PRIVATE KEY-----|$)", re.DOTALL
)


def _redact_credential_matches(text: str) -> str:
    """Replace credential-pattern matches with their class name in ONE pass
    (markers are immune to later patterns): every returned/printed diff stays
    a useful bounded comparison without echoing a suspected secret (spec
    2026-09-23-0004). A recognized PEM private key is removed as the ENTIRE
    block — BEGIN header, payload lines and END marker. Applied where a diff
    is built — never to an authored page or the admitted state."""
    text = _PEM_BLOCK_RE.sub("[redacted private_key]", text)
    combined = re.compile(
        "|".join(
            f"(?P<c{index}>{pattern.pattern})"
            for index, (_label, pattern) in enumerate(_SECRET_PATTERNS)
        )
    )

    def _redact(match: re.Match) -> str:
        for index, (label, _pattern) in enumerate(_SECRET_PATTERNS):
            if match.group(f"c{index}") is not None:
                return f"[redacted {label}]"
        return match.group(0)  # pragma: no cover — one alternative always matched

    return combined.sub(_redact, text)


def _run_advisory(
    record: Reconciliation,
    ameta: dict,
    abody: str,
    *,
    identity: dict,
    converted: str,
    filename: str,
    complete,
) -> None:
    """Attach one opt-in advisory result to ``record``. Credential-pattern
    refusal over the approved Policy's substantive metadata AND body comes
    BEFORE any egress (the diff is already credential-redacted where it is
    built); provider failure, unparseable answers and a missing boolean
    possible_conflict flag leave the deterministic comparison intact as
    `unavailable`; every quote is verified verbatim against the same converted
    text the distillation saw before counting as evidence — anything else
    stays `unverified`, and no answer is ever proof of consistency."""
    title = str(ameta.get("title", ""))
    description = str(ameta.get("description", ""))
    tags = ", ".join(str(tag) for tag in (ameta.get("tags") or []))
    # The refusal scans ALL approved text that can echo into review output —
    # substantive metadata (title/description/tags) plus body — while the model
    # payload below still sends only title/body/source identity (never that
    # metadata): a metadata credential refuses the call without being sent.
    outgoing = f"{title}\n{description}\n{tags}\n{abody}"
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(outgoing):
            record.advisory = Advisory(
                "unavailable",
                reason=(
                    f"approved Policy text matches the {label} credential pattern — "
                    "not sent; deterministic diff above stands"
                ),
            )
            return
    messages: list[dict] = [
        {"role": "system", "content": _ADVISORY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _advisory_user_prompt(converted, filename, title, abody, identity),
        },
    ]
    try:
        data = _parse_advisory(complete(messages))
    except Exception as exc:  # provider failure/unparseable: the deterministic edit remains
        cause = type(exc).__name__
        record.advisory = Advisory("unavailable", reason=f"advisory call failed ({cause})")
        return
    flag = data.get("possible_conflict")
    if not isinstance(flag, bool):
        record.advisory = Advisory(
            "unavailable", reason="advisory response lacks a boolean possible_conflict"
        )
        return
    if not flag:
        record.advisory = Advisory("none", reason=_ADVISORY_ABSENT_NOTE)
        return
    note = str(data.get("note") or "").strip()
    quotes: list[dict] = []
    raw_quotes = data.get("quotes")
    for quote in raw_quotes if isinstance(raw_quotes, list) else []:
        passage = str(quote)
        if not passage.strip():
            continue
        verified = passage in converted or passage in abody or (bool(title) and passage in title)
        quotes.append({"text": passage, "verified": verified})
    if not quotes:
        record.advisory = Advisory(
            "unverified", note=note, reason="suggestion carried no verifiable quotes"
        )
        return
    status = "supported" if any(q["verified"] for q in quotes) else "unverified"
    record.advisory = Advisory(status, note=note, quotes=quotes)


def _split_page(text: str) -> tuple[dict, str]:
    """Frontmatter meta (empty dict when absent) and body of one OKF page."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    return (yaml.safe_load(match.group(1)) or {}), match.group(2)


def _owner_text(meta: dict, body: str) -> str:
    """Canonical owner content: every frontmatter field except promotion
    bookkeeping (status, verified, generated) and source provenance (compared
    separately as digest identity) — substantive per-type metadata such as a
    table's grain participates in change detection — plus the body."""
    owner_meta = {key: value for key, value in meta.items() if key not in _BOOKKEEPING_KEYS}
    front = yaml.safe_dump(owner_meta, sort_keys=True, default_flow_style=False).strip()
    return f"{front}\n{body}"


def _source_identity(meta: dict) -> dict | None:
    """{resource, digest} of a page's first sources[] entry, or None.
    Resource values are identity STRINGS — never opened as paths."""
    sources = meta.get("sources") or []
    if not sources or not isinstance(sources[0], dict):
        return None
    return {
        "resource": str(sources[0].get("resource", "")),
        "digest": str(sources[0].get("id", "")),
    }


def _matching_source(meta: dict, resource: str) -> dict | None:
    """{resource, digest} of the sources[] entry identifying ``resource`` — the
    entry that made the page a match — or None when no citation identifies it."""
    for entry in meta.get("sources") or []:
        if isinstance(entry, dict) and str(entry.get("resource", "")) == resource:
            return {
                "resource": str(entry.get("resource", "")),
                "digest": str(entry.get("id", "")),
            }
    return None


def _approved_page(pages: dict[str, str], rel: str) -> str | None:
    """Read an exact-path page from the proposal's immutable base revision."""
    return pages.get(f"{CONTEXT_SUBDIR}/{rel}")


def _duplicate_suspect(pages: dict[str, str], meta: dict) -> str | None:
    """Find a different base-snapshot page sharing source identity or title."""
    resource = ""
    sources = meta.get("sources") or []
    if sources and isinstance(sources[0], dict):
        resource = str(sources[0].get("resource", ""))
    title = str(meta.get("title", ""))
    prefix = f"{CONTEXT_SUBDIR}/"
    for artifact, text in sorted(pages.items()):
        if not artifact.startswith(prefix) or not artifact.endswith(".md"):
            continue
        rel = artifact.removeprefix(prefix)
        if Path(rel).name == "index.md":
            continue
        suspect_meta, _ = _split_page(text)
        if not suspect_meta:
            continue
        for entry in suspect_meta.get("sources") or []:
            if isinstance(entry, dict) and str(entry.get("resource", "")) == resource != "":
                return rel
        if title and suspect_meta.get("title") == title:
            return rel
    return None


def _bounded_diff(old: str, new: str) -> str:
    """Bounded unified diff of owner content (approved -> proposed)."""
    lines = list(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile="approved", tofile="proposed", lineterm=""
        )
    )
    if len(lines) > _DIFF_LINE_CAP:
        lines = [*lines[:_DIFF_LINE_CAP], "… (diff truncated)"]
    return "\n".join(lines)


def _reconcile_one(
    reference: str | Path,
    *,
    project: Path,
    proposal: str,
    current_revision: str,
    base_pages: dict[str, str],
    candidate_pages: dict[str, str],
    complete,
    now: str,
) -> tuple[str, list[str], list[str], list[str], list[Reconciliation], bool]:
    """Compare one source with the admitted base, preflight its paths, then edit Git."""
    pages, errors, converted = _document_pages(
        reference, project, complete=complete, now=now, verbatim=False
    )
    if errors:
        return current_revision, [], [], errors, [], False

    shown = _redact_credential_matches(str(reference))
    doc_errors: list[str] = []
    comparisons: list[Reconciliation] = []
    plans: list[tuple[Reconciliation, str, str]] = []
    advisory_jobs: list[tuple[Reconciliation, dict, str]] = []
    preflight_unchanged: list[str] = []
    planned_pages = candidate_pages.copy()
    seen: set[str] = set()

    for folder, name, page_text in pages:
        rel = f"{folder}/{name}.md"
        if rel in seen:
            doc_errors.append(
                f"{shown}: duplicate proposal path {rel} within this document — "
                "nothing was written for this document"
            )
            break
        seen.add(rel)
        artifact_path = f"{CONTEXT_SUBDIR}/{rel}"
        pmeta, pbody = _split_page(page_text)
        new_source = _source_identity(pmeta) or {"resource": "", "digest": ""}
        approved = _approved_page(base_pages, rel)
        current = planned_pages.get(artifact_path)

        if approved is not None:
            ameta, abody = _split_page(approved)
            old_source = _matching_source(ameta, new_source["resource"])
            if old_source is None:
                doc_errors.append(
                    f"{shown}: identity conflict at {rel}: the base page's sources do not "
                    f"reference {new_source['resource']} — resolve the mismatch manually; "
                    "nothing was written for this document"
                )
                break
            same_owner = _owner_text(ameta, abody) == _owner_text(pmeta, pbody)
            if same_owner and old_source == new_source:
                record = Reconciliation(rel, "same-path", "unchanged", new_source, old_source)
                record.candidate_path = artifact_path if current is not None else None
                comparisons.append(record)
                if current is not None:
                    preflight_unchanged.append(artifact_path)
                    planned_pages[artifact_path] = current
                continue

            change = "provenance_only" if same_owner else "changed"
            diff = ""
            if not same_owner:
                diff = _redact_credential_matches(
                    _bounded_diff(_owner_text(ameta, abody), _owner_text(pmeta, pbody))
                )
            record = Reconciliation(rel, "same-path", change, new_source, old_source, diff=diff)
            comparisons.append(record)
            if current != approved:
                if current is not None and _candidate_page_unchanged(current, page_text):
                    record.candidate_path = artifact_path
                    preflight_unchanged.append(artifact_path)
                    planned_pages[artifact_path] = current
                else:
                    doc_errors.append(
                        f"{shown}: candidate replacement target {artifact_path} differs from "
                        "its admitted base — re-read the candidate and resolve the edit; "
                        "nothing was written for this document"
                    )
                    break
            else:
                plans.append((record, artifact_path, page_text))
                planned_pages[artifact_path] = page_text
            if ameta.get("type") == "policy" and abody.strip() != pbody.strip():
                advisory_jobs.append((record, ameta, abody))
            continue

        suspect = _duplicate_suspect(base_pages, pmeta)
        warning = None
        if suspect is not None:
            warning = (
                f"possible duplicate: no admitted page at {rel}, but {suspect} matches "
                "this proposal's source/title — written as a new candidate page, not retargeted"
            )
        path, existing = _candidate_page_target(planned_pages, folder, name, page_text)
        record = Reconciliation(rel, "new", "new", new_source, warning=warning)
        record.candidate_path = path if existing is not None else None
        comparisons.append(record)
        if existing is None:
            plans.append((record, path, page_text))
            planned_pages[path] = page_text
        else:
            preflight_unchanged.append(path)
            planned_pages[path] = existing

    if doc_errors:
        return current_revision, [], [], doc_errors, [], False

    from ariadne import proposals

    written: list[str] = []
    unchanged = preflight_unchanged
    mutation_failed = False
    for record, artifact_path, page_text in plans:
        try:
            result = proposals.edit_proposal(
                project, proposal, current_revision, artifact_path, page_text, core_generated=True
            )
        except Exception as exc:
            doc_errors.append(
                f"{shown}: candidate edit failed: {_redact_credential_matches(str(exc))}"
            )
            mutation_failed = True
            break
        current_revision = result["revision"]
        candidate_pages[artifact_path] = page_text
        record.candidate_path = artifact_path
        target = written if result["changed"] else unchanged
        if artifact_path not in target:
            target.append(artifact_path)

    for record, ameta, abody in advisory_jobs:
        _run_advisory(
            record,
            ameta,
            abody,
            identity=record.old_source or {"resource": "", "digest": ""},
            converted=converted,
            filename=Path(str(reference)).name,
            complete=complete,
        )
    return current_revision, written, unchanged, doc_errors, comparisons, mutation_failed


def reconcile_ingest(
    docs: list[str | Path],
    *,
    project: str | Path,
    proposal: str,
    expected_revision: str,
    complete=None,
) -> tuple[dict, list[Reconciliation]]:
    """Compare source-derived pages with the admitted base and edit one candidate.

    Advisory egress remains opt-in. The base and candidate are read by exact Git
    revision; no mutable served tree or separate staging catalog participates.
    """
    from ariadne import proposals

    root = Path(project).resolve()
    record, current_revision = _proposal_state(root, proposal, expected_revision)
    base_revision = record["base_revision"]
    base_pages = _context_pages(root, base_revision)
    candidate_pages = _context_pages(root, current_revision)
    complete = complete or _default_complete
    now = datetime.now(UTC).isoformat(timespec="seconds")
    written: list[str] = []
    unchanged: list[str] = []
    errors: list[str] = []
    comparisons: list[Reconciliation] = []

    for reference in docs:
        (
            current_revision,
            doc_written,
            doc_unchanged,
            doc_errors,
            doc_comparisons,
            mutation_failed,
        ) = _reconcile_one(
            reference,
            project=root,
            proposal=proposal,
            current_revision=current_revision,
            base_pages=base_pages,
            candidate_pages=candidate_pages,
            complete=complete,
            now=now,
        )
        written.extend(doc_written)
        unchanged.extend(doc_unchanged)
        errors.extend(doc_errors)
        comparisons.extend(doc_comparisons)
        if mutation_failed:
            break

    try:
        current_revision = proposals._load_record(root, proposal)["candidate_revision"]
    except Exception as exc:
        if not errors:
            errors.append(
                f"candidate revision is unavailable after reconciliation: {type(exc).__name__}"
            )
    result = {
        "proposal": proposal,
        "base_revision": base_revision,
        "candidate_revision": current_revision,
        "written": written,
        "unchanged": unchanged,
        "errors": errors,
    }
    return result, comparisons


def _print_reconciliation(record: Reconciliation) -> None:
    """One comparison for the opt-in command's review output (never a served page)."""
    print(f"reconcile: {record.proposal} — {record.match}, {record.change}")
    if record.warning is not None:
        print(f"  warning: {record.warning}")
    if record.old_source is not None:
        old = record.old_source
        print(f"  old source: {old['resource']} (digest {old['digest']})")
    print(f"  new source: {record.new_source['resource']} (digest {record.new_source['digest']})")
    if record.diff:
        print("  diff:")
        for line in record.diff.splitlines():
            print(f"    {line}")
    if record.candidate_path is not None:
        print(f"  candidate: {record.candidate_path}")
    advisory = record.advisory
    line = f"  advisory: {advisory.status}"
    if advisory.reason:
        line += f" — {advisory.reason}"
    print(line)
    if advisory.note:
        print(f"    note: {advisory.note}")
    for quote in advisory.quotes or []:
        flag = "supported" if quote["verified"] else "UNVERIFIED, not evidence"
        print(f"    quote ({flag}): {quote['text']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ariadne-ingest",
        description="Ingest documents into a revision-checked Git Authoring candidate.",
    )
    parser.add_argument(
        "docs",
        nargs="+",
        help="operator-authorized document references; supported formats may require [documents]",
    )
    parser.add_argument("--project", required=True, help="the local Git data project")
    parser.add_argument("--proposal", required=True, help="existing Authoring proposal ID")
    parser.add_argument("--expected-revision", required=True, help="current candidate revision")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="compare with the proposal's immutable admitted base; Policy text egress stays opt-in",
    )
    parser.add_argument(
        "--verbatim",
        action="store_true",
        help="preserve converted text in one draft Reference per document without a model call",
    )
    args = parser.parse_args(argv)
    if args.verbatim and args.reconcile:
        parser.error("--verbatim does not support --reconcile (spec 0021 §2)")

    if args.reconcile:
        result, comparisons = reconcile_ingest(
            args.docs,
            project=args.project,
            proposal=args.proposal,
            expected_revision=args.expected_revision,
        )
        for record in comparisons:
            _print_reconciliation(record)
    else:
        result = ingest(
            args.docs,
            project=args.project,
            proposal=args.proposal,
            expected_revision=args.expected_revision,
            verbatim=args.verbatim,
        )
    for path in result["written"]:
        print(f"written: {path}")
    for path in result["unchanged"]:
        print(f"unchanged: {path}")
    print(f"candidate: {result['candidate_revision']}")
    for error in result["errors"]:
        print(f"error: {error}", file=sys.stderr)
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

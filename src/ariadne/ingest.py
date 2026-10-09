"""Standalone proposal-first document ingestion (spec rev 8 §8.19, ADR-0009).

``ariadne-ingest <doc>...`` turns documents into typed OKF proposals WITHOUT the
authoring loop: convert to Markdown, LLM-distill into pages classified into the
existing bundle taxonomy, enforce the per-type frontmatter contract, and stage
under ``staging/context_layer/`` only — the human promotion gate
(``ariadne-promote``) stays the only path to served state; served dirs,
``index.md`` and ``log.md`` are never written (promote owns bundle bookkeeping).

Converter dispatch — the lumio-wiki-researched stack, installed via the optional
``[documents]`` extra so the base install stays lightweight::

    .md .txt                                  native read (no dependencies)
    .pdf                                      liteparse
    .docx .pptx .xlsx .html                   markitdown[docx]
    .doc .rtf .epub .csv .odt .ods .odp .xls  firecrawl-anydoc (imports as ``anydoc``)

(.html routes to markitdown: firecrawl-anydoc 0.1.3 ships no HTML reader —
owner decision, rev 8 implementation round.) A missing converter or an
unsupported extension fails that document with the exact install hint and
stages nothing for it.

The LLM call reuses the author's OpenAI-compatible wiring (``OPENAI_*`` loaded
from ``ARIADNE_ENV``). What the pipeline already knows mechanically is never
trusted to LLM recall: every assembled page carries
``sources: [{id: <sha256-12 of the file>, resource: <absolute path>, title:
<filename>}]``, ``generated: {by: ariadne-ingest:<model>, at: <iso>}`` and
``status: draft``; the LLM supplies only the classification, title,
description, tags and body. Pages are gated with the author's per-type contract
(:func:`ariadne.context._page_contract_errors`) BEFORE anything touches staging,
with at most 2 retry rounds feeding violations back; a document that never
passes stages nothing.

Two further untrusted-input refusals: staging refuses to write through any
symlinked component under staging/ (init.py's component-walk discipline — an
attacker-planted link, e.g. ``staging/context_layer`` -> the served dir,
receives nothing), and every fully-rendered page is scanned for credential
patterns before staging, rejected naming the pattern CLASS, never the secret.

Staging writes use the facade's atomic ``O_CREAT|O_EXCL`` claim — name
collisions suffix ``-2``/``-3``/… instead of overwriting (spec §8.11 discipline).

Interfaces::

    ingest(docs, staging_dir="staging", complete=None) -> (staged paths, errors)
    reconcile_ingest(docs, *, served_root, staging_dir="staging", complete=None)
        -> (staged paths, errors, comparisons)   # opt-in, spec 2026-09-23-0004
    ariadne-ingest <doc>... [--db DB]          # --db reserved: unwired for now
    ariadne-ingest --reconcile --served ROOT <doc>...
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

from ariadne.author import _default_complete, _validate_staging
from ariadne.context import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    _FRONTMATTER_RE,
    _page_contract_errors,
)
from ariadne.init import _symlink_under

MAX_RETRIES = 2  # ≤2 retry rounds on contract violations (rev 8 brief; author allows 3 total)
STAGING_SUBDIR = "context_layer"  # the only place ingest ever writes under staging/

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

# Credential classes rejected before staging: LLM output is untrusted, so a
# secret from the source document must never be echoed into a staged page.
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
    import anydoc  # firecrawl-anydoc installs as firecrawl-anydoc, imports as anydoc

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
            "Nothing was staged."
        )
    convert, requirement = entry
    try:
        return convert(path)
    except ImportError:
        raise _ConversionError(
            f"{path}: converting '{suffix}' needs the optional '{requirement}' package — "
            f"{_INSTALL_HINT}. Nothing was staged."
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
document's staged footnote id mechanically. The ariadne declaration belongs \
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
        f"Document citation id: {citation_id} — this document stages as that "
        "footnote id; a mapping citing the document itself uses the token "
        '"@document" in source_ids and ingestion binds it to this id.\n\n'
        f"<document>\n{text.strip()}\n</document>\n\n"
        "Distill it into typed OKF pages now. Return only the JSON object."
    )


# The explicit input-document citation token (K2, spec 0010 §4: domain
# claims cite the ACTUAL input document): the digest footnote id is
# core-owned, never guessed by the model — a mapping cites the document
# itself with this token and _assemble binds the real staged id
# mechanically, like every other mechanical provenance field.
_DOCUMENT_CITATION_TOKEN = "@document"


def _bind_document_citations(extension: dict, citation_id: str) -> dict:
    """Bind every ``@document`` mapping-citation token to the input document's
    ACTUAL staged footnote id: validation then resolves it like any authored
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
        # declarations survive ordinary staging — page aliases and the
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
                "authority/measurement claims are never staged; remove it"
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


def _symlink_offender(staging: Path, pages: list[tuple]) -> str | None:
    """First symlinked component of any page's staging path (from staging/
    down to the target file), or None — the same component-walk refusal as
    ariadne.init's scaffolder: an attacker-planted link (e.g.
    ``staging/context_layer`` -> the served context_layer/) must never receive
    staged pages directly, bypassing the promotion gate."""
    for folder, name, _text in pages:
        offender = _symlink_under(staging, f"{STAGING_SUBDIR}/{folder}/{name}.md")
        if offender is not None:
            return offender
    return None


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
                    "remove it and re-send; secrets are never staged"
                )
                break  # one class names the rejection; drop the page
    return violations


def _contract_errors(pages: list[tuple]) -> list[str]:
    """Run the author's per-type gate over assembled pages WITHOUT staging them:
    pages are mirrored into a throwaway tree so a violating round never leaves
    anything under staging/ (rev 8: nothing partially staged)."""
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        paths: list[tuple[Path, str]] = []
        for folder, name, text in pages:
            page = root / STAGING_SUBDIR / folder / f"{name}.md"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(text, encoding="utf-8")
            paths.append((page, _ALLOWED_FOLDERS[folder]))
        for page, expected_type in paths:
            errors.extend(_page_contract_errors(root, page, expected_type))
    return errors


def _claim_exclusive(candidate: Path, text: str) -> Path:
    """Atomic O_CREAT|O_EXCL write: claims the path or raises FileExistsError."""
    fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return candidate


def _stage_atomic(directory: Path, name: str, text: str) -> Path:
    """Mirror of the facade's O_CREAT|O_EXCL claim (ariadne.serve): the suffix
    race resolves atomically, collisions get -2/-3/…, never an overwrite."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{name}.md"
    suffix = 2
    while True:
        try:
            return _claim_exclusive(candidate, text)
        except FileExistsError:
            candidate = directory / f"{name}-{suffix}.md"
            suffix += 1


def _distill(doc: Path, *, complete, now: str) -> tuple[list[tuple], list[str], str]:
    """Convert + LLM-distill + gate one document WITHOUT touching staging;
    returns (gate-clean page triples, errors, converted text). The SAME
    converted text is returned so callers that quote-check against the document
    (the reconcile advisory) never re-read a file that may have changed mid-run.
    Shared by ordinary ingest and the opt-in reconcile mode."""
    if not doc.is_file():
        return [], [f"{doc}: no such document"], ""
    try:
        text = _convert(doc)
    except _ConversionError as exc:
        return [], [str(exc)], ""
    source = {
        "id": hashlib.sha256(doc.read_bytes()).hexdigest()[:12],
        "resource": str(doc.resolve()),
        "title": doc.name,
    }
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        # The document's ACTUAL staged footnote id rides in the prompt material
        # (K2): the model never guesses the core-owned digest, it cites the
        # "@document" token and _assemble binds this id mechanically.
        {"role": "user", "content": _user_prompt(text, doc.name, source["id"])},
    ]
    violations: list[str] = []
    for attempt in range(1 + MAX_RETRIES):
        raw = complete(messages)
        # Read AFTER the first call: the default endpoint loads ARIADNE_ENV inside
        # _default_complete, so OPENAI_MODEL is only guaranteed present by now.
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
            if not violations:  # gate-clean: the caller decides what gets staged
                return pages, [], text
        print(
            f"ariadne-ingest: {doc.name}: attempt {attempt + 1}: "
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
        f"ariadne-ingest: {doc.name}: still violating after 1 + {MAX_RETRIES} "
        "attempts — nothing staged",
        flush=True,
    )
    return [], violations, text


def _ingest_one(doc: Path, *, staging: Path, complete, now: str) -> tuple[list[Path], list[str]]:
    """Convert + distill + gate + stage one document. Returns (staged, errors)."""
    pages, errors, _converted = _distill(doc, complete=complete, now=now)
    if errors:
        return [], errors
    offender = _symlink_offender(staging, pages)
    if offender is not None:  # refuse BEFORE any write: stage nothing
        return [], [
            f"{doc.name}: refusing to stage through a symlink: {offender} "
            f"is a symlink under {staging}; remove it and re-run"
        ]
    return [
        _stage_atomic(staging / STAGING_SUBDIR / folder, name, page_text)
        for folder, name, page_text in pages
    ], []


def ingest(
    docs: list[str | Path],
    *,
    staging_dir: str | Path = "staging",
    complete=None,
) -> tuple[list[Path], list[str]]:
    """Ingest documents into staged OKF proposals; returns (staged paths, errors).

    ``complete(messages) -> str`` is the LLM call boundary (default: the same
    OpenAI-compatible endpoint the author uses)."""
    staging = Path(staging_dir)
    _validate_staging(staging)  # spec §6: never the repo root or a served layer
    complete = complete or _default_complete
    now = datetime.now(UTC).isoformat(timespec="seconds")
    staged: list[Path] = []
    errors: list[str] = []
    for doc in docs:
        paths, doc_errors = _ingest_one(Path(doc), staging=staging, complete=complete, now=now)
        staged.extend(paths)
        errors.extend(doc_errors)
    return staged, errors


# --- opt-in evidence reconciliation (spec 2026-09-23-0004 rev 1, ADR-0003/0009) ---
# Deterministic identity + staging (issue #12 validation unit A) plus the
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
    staged: Path | None = None  # final staged path (suffixed path for new pages)
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
    is built — never to a staged page or the served state."""
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
    except Exception as exc:  # provider failure/unparseable: advice is unavailable, staging stands
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


def _approved_page(served_root: Path, rel: str) -> tuple[Path | None, str | None]:
    """Contained, symlink-free approved page at exactly ``rel`` under
    served_root/context_layer/, or (None, error). A proposed or symlinked path
    must never read outside the selected approved Context Layer."""
    offender = _symlink_under(served_root, f"{STAGING_SUBDIR}/{rel}")
    if offender is not None:
        return None, f"approved path {rel} traverses a symlink ({offender})"
    served_context = served_root / STAGING_SUBDIR
    page = served_context / rel
    if not page.resolve().is_relative_to(served_context.resolve()):
        return None, f"approved path {rel} escapes the served Context Layer"
    if page.is_file():
        return page, None
    return None, None  # no approved page at that exact path: an unmatched new page


def _duplicate_suspect(served_root: Path, meta: dict) -> str | None:
    """Approved page at a DIFFERENT path sharing the proposal's source resource
    or title (path-drift hint); warning-only — it never retargets a proposal.
    Symlinked candidates are skipped unread: discovery must never read outside
    the selected approved Context Layer."""
    served_context = served_root / STAGING_SUBDIR
    resource = ""
    sources = meta.get("sources") or []
    if sources and isinstance(sources[0], dict):
        resource = str(sources[0].get("resource", ""))
    title = str(meta.get("title", ""))
    for page in sorted(served_context.rglob("*.md")):
        if page.name == "index.md":
            continue
        rel = page.relative_to(served_context).as_posix()
        if _symlink_under(served_root, f"{STAGING_SUBDIR}/{rel}") is not None:
            continue  # symlinked candidate: never read through it
        suspect_meta, _ = _split_page(page.read_text(encoding="utf-8", errors="replace"))
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
    doc: Path, *, staging: Path, served_root: Path, complete, now: str
) -> tuple[list[Path], list[str], list[Reconciliation]]:
    """Reconcile one document: distill, resolve EVERY candidate's identity and
    collisions first, then stage. Any preflight failure stages nothing for this
    document; other documents stay independently processable."""
    pages, errors, converted = _distill(doc, complete=complete, now=now)
    if errors:
        return [], errors, []
    doc_errors: list[str] = []
    comparisons: list[Reconciliation] = []
    plans: list[tuple[str, str, str]] = []  # (rel, mode, page_text); mode: replacement|new
    seen: set[str] = set()  # every proposed path, unchanged ones included
    advisory_jobs: list[tuple[Reconciliation, dict, str]] = []  # (record, ameta, abody)
    # -- preflight: resolve all candidates before any per-document write ------
    for folder, name, page_text in pages:
        rel = f"{folder}/{name}.md"
        if rel in seen:
            doc_errors.append(
                f"{doc.name}: duplicate proposal path {rel} within this document — "
                "nothing staged for this document"
            )
            break
        seen.add(rel)
        pmeta, pbody = _split_page(page_text)
        new_source = _source_identity(pmeta) or {"resource": "", "digest": ""}
        approved, containment_error = _approved_page(served_root, rel)
        if containment_error is not None:
            doc_errors.append(
                f"{doc.name}: refusing to reconcile {rel}: {containment_error}; "
                "nothing staged for this document"
            )
            break
        if approved is not None:
            ameta, abody = _split_page(approved.read_text(encoding="utf-8"))
            old_source = _matching_source(ameta, new_source["resource"])
            if old_source is None:
                doc_errors.append(
                    f"{doc.name}: identity conflict at {rel}: the approved page's sources "
                    f"do not reference {new_source['resource']} — resolve the mismatch "
                    "manually; nothing staged for this document"
                )
                break
            same_owner = _owner_text(ameta, abody) == _owner_text(pmeta, pbody)
            if same_owner and old_source == new_source:
                comparisons.append(  # identical page and digest: stages nothing
                    Reconciliation(rel, "same-path", "unchanged", new_source, old_source)
                )
                continue
            change = "provenance_only" if same_owner else "changed"
            diff = ""
            if not same_owner:
                # EVERY returned/printed diff is credential-redacted where it is
                # built (spec 2026-09-23-0004: no suspected secret in review
                # output) — independent of advisory eligibility, so a metadata
                # credential echoes nowhere. The proposal side is already
                # secret-free by the distillation gate; only approved-side
                # echoes are masked.
                diff = _redact_credential_matches(
                    _bounded_diff(_owner_text(ameta, abody), _owner_text(pmeta, pbody))
                )
            if (staging / STAGING_SUBDIR / rel).exists():
                doc_errors.append(
                    f"{doc.name}: replacement staging target {rel} is already occupied "
                    f"under {staging} — nothing staged for this document"
                )
                break
            record = Reconciliation(rel, "same-path", change, new_source, old_source, diff=diff)
            comparisons.append(record)
            plans.append((rel, "replacement", page_text))
            if ameta.get("type") == "policy" and abody.strip() != pbody.strip():
                # unit B eligibility: only a matched approved POLICY with changed
                # BODY text is ever disclosed to the advisory model
                advisory_jobs.append((record, ameta, abody))
        else:
            suspect = _duplicate_suspect(served_root, pmeta)
            warning = None
            if suspect is not None:
                warning = (
                    f"possible duplicate: no approved page at {rel}, but approved "
                    f"{suspect} matches this proposal's source/title — staged as a new "
                    "page, not retargeted"
                )
            comparisons.append(Reconciliation(rel, "new", "new", new_source, warning=warning))
            plans.append((rel, "new", page_text))
    if doc_errors:
        return [], doc_errors, []
    for _rel, _mode, _text in plans:  # staging containment refusal, unchanged walk
        offender = _symlink_under(staging, f"{STAGING_SUBDIR}/{_rel}")
        if offender is not None:
            return (
                [],
                [
                    f"{doc.name}: refusing to stage through a symlink: {offender} is a "
                    f"symlink under {staging}; remove it and re-run"
                ],
                [],
            )
    # -- all candidates resolved: only now does anything touch staging --------
    staged: list[Path] = []
    for rel, mode, page_text in plans:
        directory = staging / STAGING_SUBDIR / Path(rel).parent
        directory.mkdir(parents=True, exist_ok=True)
        if mode == "replacement":  # exact approved path: suffixing would change identity
            staged.append(_claim_exclusive(directory / f"{Path(rel).stem}.md", page_text))
        else:
            staged.append(_stage_atomic(directory, Path(rel).stem, page_text))
    final_by_rel = {rel: path for (rel, _mode, _text), path in zip(plans, staged)}
    for record in comparisons:
        record.staged = final_by_rel.get(record.proposal)
    # -- opt-in advisory (unit B): only eligible changed approved Policies, and
    # only AFTER the deterministic comparison and staging are complete — advice
    # can never gate, rewrite or undo them (spec 2026-09-23-0004). The advisory
    # quote-checks against the SAME converted text the distillation saw: no
    # re-read of a document that may have changed or vanished mid-run.
    for record, ameta, abody in advisory_jobs:
        _run_advisory(
            record,
            ameta,
            abody,
            identity=record.old_source or {"resource": "", "digest": ""},
            converted=converted,
            filename=doc.name,
            complete=complete,
        )
    return staged, [], comparisons


def reconcile_ingest(
    docs: list[str | Path],
    *,
    served_root: str | Path,
    staging_dir: str | Path = "staging",
    complete=None,
) -> tuple[list[Path], list[str], list[Reconciliation]]:
    """Opt-in re-ingestion with evidence reconciliation (spec 2026-09-23-0004):
    compares document-derived proposals against same-path approved pages,
    stages replacements at their exact approved relative path, and returns
    (staged_paths, errors, comparisons). The served tree is never written;
    human promotion stays the only path to served state."""
    staging = Path(staging_dir)
    _validate_staging(staging)  # same spec §6 discipline as ordinary ingest
    served = Path(served_root)
    if not (served / STAGING_SUBDIR).is_dir():
        raise ValueError(
            f"served root {served} has no {STAGING_SUBDIR}/ — nothing to "
            "reconcile against; pass the served root that promotion writes"
        )
    staging_resolved = staging.resolve()
    served_resolved = served.resolve()
    if staging_resolved == served_resolved or staging_resolved.is_relative_to(served_resolved):
        # _validate_staging only knows the repo's fixed served paths; the
        # caller-selected served root needs the same promotion-gate discipline
        # (ADR-0003), or an unmatched new page would land directly in served state.
        raise ValueError(
            f"staging directory {staging} is inside the served root {served}: staged "
            "pages reach served state only through human promotion — spec §6"
        )
    complete = complete or _default_complete
    now = datetime.now(UTC).isoformat(timespec="seconds")
    staged: list[Path] = []
    errors: list[str] = []
    comparisons: list[Reconciliation] = []
    for doc in docs:  # documents stay independently processable
        paths, doc_errors, doc_comparisons = _reconcile_one(
            Path(doc), staging=staging, served_root=served, complete=complete, now=now
        )
        staged.extend(paths)
        errors.extend(doc_errors)
        comparisons.extend(doc_comparisons)
    return staged, errors, comparisons


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
    if record.staged is not None:
        print(f"  staged: {record.staged}")
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
        description="Ingest documents as typed OKF proposals into staging/ "
        "(ADR-0009): convert -> LLM distill -> per-type gate -> stage; the human "
        "promotion gate stays the only path to served state.",
    )
    parser.add_argument(
        "docs",
        nargs="+",
        help="documents to ingest: .md/.txt natively; .pdf/.docx/.pptx/.xlsx/.html "
        "and more via the optional [documents] extra",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="ignored for now (reserved for a future author-loop widening, ADR-0009)",
    )
    parser.add_argument("--staging", default="staging", help="staging directory (default: staging)")
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="opt-in (spec 2026-09-23-0004): compare proposals against same-path "
        "approved pages under --served before staging; replacements claim their "
        "exact approved path, nothing is ever served automatically",
    )
    parser.add_argument(
        "--served",
        default=None,
        help="served root holding context_layer/ (required with --reconcile)",
    )
    args = parser.parse_args(argv)
    if args.reconcile and not args.served:
        parser.error("--reconcile requires --served ROOT (a served root containing context_layer/)")

    if args.reconcile:
        staged, errors, comparisons = reconcile_ingest(
            args.docs, served_root=Path(args.served), staging_dir=Path(args.staging)
        )
        for record in comparisons:
            _print_reconciliation(record)
    else:
        staged, errors = ingest(args.docs, staging_dir=Path(args.staging))
    for path in staged:
        meta = yaml.safe_load(path.read_text(encoding="utf-8").split("---")[1]) or {}
        print(f"staged: {path} [{meta.get('type')}] {meta.get('description', '')}")
    if not staged and not errors:
        print("ingest: documents yielded no pages worth keeping; nothing staged")
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

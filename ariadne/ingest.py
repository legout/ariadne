"""Standalone proposal-first document ingestion (spec rev 8 §8.19, ADR-0009).

``ariadne-ingest <doc>...`` turns documents into typed OKF proposals WITHOUT the
authoring loop: convert to Markdown, LLM-distill into pages classified into the
existing bundle taxonomy, enforce the per-type frontmatter contract, and stage
under ``staging/context_layer/`` only — the human promotion gate
(``scripts/promote.py``) stays the only path to served state; served dirs,
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
(:func:`ariadne.author._page_contract_errors`) BEFORE anything touches staging,
with at most 2 retry rounds feeding violations back; a document that never
passes stages nothing.

Staging writes use the facade's atomic ``O_CREAT|O_EXCL`` claim — name
collisions suffix ``-2``/``-3``/… instead of overwriting (spec §8.11 discipline).

Interfaces::

    ingest(docs, staging_dir="staging", complete=None) -> (staged paths, errors)
    ariadne-ingest <doc>... [--db DB]   # --db reserved: unwired for now
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from ariadne.author import _default_complete, _page_contract_errors, _validate_staging

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
"cardinality_enforcement": "STRICT_1_TO_1"} — STRICT_1_TO_1 only when the \
document proves the key unique, otherwise name the real cardinality.
- A relationship between tables (join keys, cardinality) -> folder \
"references/joins", type "reference".
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


def _user_prompt(text: str, filename: str) -> str:
    return (
        f"Source document: {filename} (already converted to markdown)\n\n"
        f"<document>\n{text.strip()}\n</document>\n\n"
        "Distill it into typed OKF pages now. Return only the JSON object."
    )


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
                f"{rel}: folder {folder!r} requires type '{expected}' "
                f"(got {entry.get('type')!r})"
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
        if not isinstance(tags, list) or not tags or not all(
            isinstance(tag, str) and tag.strip() for tag in tags
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
        front_yaml = yaml.safe_dump(front, default_flow_style=False, sort_keys=False).strip()
        pages.append((folder, name, f"---\n{front_yaml}\n---\n\n{body}\n"))
    return pages, errors


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


def _stage_atomic(directory: Path, name: str, text: str) -> Path:
    """Mirror of the facade's O_CREAT|O_EXCL claim (ariadne.serve): the suffix
    race resolves atomically, collisions get -2/-3/…, never an overwrite."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{name}.md"
    suffix = 2
    while True:
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            candidate = directory / f"{name}-{suffix}.md"
            suffix += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        return candidate


def _ingest_one(
    doc: Path, *, staging: Path, complete, now: str
) -> tuple[list[Path], list[str]]:
    """Convert + distill + gate + stage one document. Returns (staged, errors)."""
    if not doc.is_file():
        return [], [f"{doc}: no such document"]
    try:
        text = _convert(doc)
    except _ConversionError as exc:
        return [], [str(exc)]
    source = {
        "id": hashlib.sha256(doc.read_bytes()).hexdigest()[:12],
        "resource": str(doc.resolve()),
        "title": doc.name,
    }
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(text, doc.name)},
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
                violations = _contract_errors(pages)
            if not violations:  # gate-clean: only now does anything touch staging
                return [
                    _stage_atomic(staging / STAGING_SUBDIR / folder, name, page_text)
                    for folder, name, page_text in pages
                ], []
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
    return [], violations


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
    args = parser.parse_args(argv)

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

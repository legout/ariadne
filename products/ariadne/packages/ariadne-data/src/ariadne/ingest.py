"""Shared document conversion and credential-pattern helpers.

Document onboarding itself is Lumio-native: ``extract_source``
plus ``CandidateRequest``/``ingest_candidate`` own source binding, authored
pages and original retention, and the retired ``ariadne-ingest`` orchestration
(distillation, reconciliation, proposal writes, CLI) is gone. This module keeps
ONLY the two live internal helpers with retained callers: the extension-routed
converter seam for the bounded Seed-Notes document parts
(``ariadne.authoring_inputs``) and the credential classes reused verbatim by
``ariadne.proposals``. Converter dispatch remains optional via ``[documents]``::

    .md .txt                                  native read (no dependencies)
    .pdf                                      liteparse
    .docx .pptx .xlsx .html                   markitdown[docx]
    .doc .rtf .epub .csv .odt .ods .odp .xls  firecrawl-anydoc (imports as ``anydoc``)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_NATIVE_SUFFIXES = (".md", ".txt")

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


def _convert_native(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _convert_pdf(path: Path) -> str:
    # Lazy import: the [documents] extra is optional; a missing
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

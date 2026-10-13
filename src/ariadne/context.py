"""Shared Context Layer (OKF) module (spec 2026-10-02-0009 §2 "Module
ownership", ADR-0016).

Everything deterministic about OKF pages lives here so Query
(:mod:`ariadne.query`), the Authoring workflows (:mod:`ariadne.author`,
:mod:`ariadne.ingest`) and the legacy promotion gate (:mod:`ariadne.promote`)
call one implementation — moved intact out of the workflow files (issue #33),
never reimplemented:

- context retrieval: the token-aware ranked search over served and staged OKF
  pages (:func:`search_pages`) and the governed citation attachment
  (:func:`metric_context`: the full served metric page plus the full bodies of
  every policy its frontmatter cites, collapsing to the null form — never
  failing a query);
- deterministic OKF checks and generation: the per-type frontmatter contract
  (:func:`_page_contract_errors`, :func:`_bundle_errors`), the post-validation
  enrichment/computation/stamping passes (:func:`_finalize_bundle`) and the
  auto-staged ad-hoc draft page (:func:`_build_adhoc_page`); the WALL-CLOCK-FREE
  Git-candidate variant (:func:`finalize_candidate`, issue #36/G4) finalizes
  enrichment/computations/indexes before the candidate commit is validated;
- deterministic promotion bookkeeping: the promoted page form (verified append,
  status flip), the regenerated ``index.md`` trees and the ``log.md`` append
  (:func:`_promoted_text`, :func:`_regenerate_indexes`, :func:`_append_log`);
- K2 structured References and terminology resolution (spec 0010 §§5–6, issue
  #42): the versioned ``ariadne`` extension of a Reference page is validated by
  the shared per-type gate (:func:`_reference_extension_errors` — malformed
  supported declarations and author-fabricated approval/measurement claims are
  rejected; legacy References stay readable), and the shared read-only
  :func:`resolve_term` resolves terms and exact field bindings with bounded
  alternatives, unconfirmed claims and actual citations.

Ranking, full Policy bodies, draft labels and attestation semantics are the
historical ones. This module guides interpretation and never computes metrics
(spec §2); it imports no workflow module.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import cast

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

# K2 (issue #42): the canonical catalog-resource parser behind exact field
# bindings (the shared source registry owns resource identity; this module
# imports no workflow module — sources is the shared registry layer).
from ariadne.sources import parse_resource

# OKF page frontmatter (same shape across author/ingest/promote/query):
# sources[] resolution (rev 10 context field) and lifecycle bookkeeping read it.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# Spec 2026-09-23-0002: search matching is token-aware, not substring — a query
# token is a lowercase [a-z0-9]+ run, so "order" no longer counts inside
# "orders" and incidental substring repetition cannot crowd out real matches.
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")

# ATX headings (spec: the section is the containing Markdown heading; a line
# like "#hashtag" without the required space is not one).
_HEADING_RE = re.compile(r"#{1,6}\s+(.+?)\s*$")

# Excerpt bound: chars of context kept on each side of the matched token before
# snapping outward to whole words (spec: bounded, verbatim).
_EXCERPT_RADIUS = 60


# ------------------------------------------------------------- context search


def _fence_mask(lines: list[str]) -> list[bool]:
    """True for lines that delimit or sit inside a fenced code block — ``` or
    ~~~. A fence closes only on the same marker with a run at least as long as
    the opener and nothing else on the line (CommonMark: a ~~~ line inside a
    ~~~~ fence stays literal). Fenced text is generated/machine content (SQL,
    code) whose identifiers merely echo page names — the spec's "incidental
    occurrences" — so it scores at half weight and its headings never
    establish a section (spec: every Markdown category stays searchable;
    fenced-only occurrences still hit)."""
    mask: list[bool] = []
    marker = ""  # active fence marker char; "" when not fenced
    needed = 0  # closing run length the active fence requires
    for line in lines:
        stripped = line.lstrip()
        char = stripped[:1]
        run = len(stripped) - len(stripped.lstrip(char))
        if char in ("`", "~") and run >= 3:
            if not marker:
                marker, needed = char, run  # opener: an info string may follow
                mask.append(True)
            elif char == marker and run >= needed and not stripped[run:].strip():
                marker, needed = "", 0  # closer: same marker, long enough, bare
                mask.append(True)
            else:
                mask.append(True)  # fence-ish line stays literal inside the fence
        else:
            mask.append(bool(marker))
    return mask


def _locate_passage(
    lines: list[str], mask: list[bool], body_start: int, terms: set[str]
) -> tuple[str, int, int, str | None]:
    """Deterministically pick the passage a hit points at (spec rev 1): scan the
    body lines first — a body match is preferred over a frontmatter-only match —
    then the frontmatter, in file order; the leftmost token match on the first
    matching line wins (fenced lines may carry the passage). Returns (excerpt,
    line_start, line_end, section) with inclusive 1-based line coordinates; the
    section is the nearest ATX heading at or before the passage, outside fenced
    code, or None for frontmatter/heading-less matches (no body evidence is
    fabricated)."""
    for index in [*range(body_start, len(lines)), *range(body_start)]:
        line = lines[index]
        token = next(
            (m for m in _QUERY_TOKEN_RE.finditer(line.lower()) if m.group() in terms), None
        )
        if token is None:
            continue
        start, end = token.span()
        lo = max(0, start - _EXCERPT_RADIUS)
        hi = min(len(line), end + _EXCERPT_RADIUS)
        while lo > 0 and start - lo < _EXCERPT_RADIUS and not line[lo - 1].isspace():
            lo -= 1  # keep whole words at the left clip
        while hi < len(line) and hi - end < _EXCERPT_RADIUS and not line[hi].isspace():
            hi += 1  # keep whole words at the right clip
        if index >= body_start:
            section = _enclosing_heading(lines, mask, body_start, index)
        else:
            section = None
        return line[lo:hi], index + 1, index + 1, section
    raise AssertionError("a positive score implies a matched line")  # pragma: no cover


def _enclosing_heading(
    lines: list[str], mask: list[bool], body_start: int, index: int
) -> str | None:
    """The nearest ATX heading at or above line `index` that is not inside a
    fenced code block (spec: headings inside fences never establish a section,
    and a passage on a heading line names that heading)."""
    section = None
    for position, line in enumerate(lines[body_start : index + 1], start=body_start):
        if not mask[position] and (heading := _HEADING_RE.match(line)):
            section = heading.group(1)
    return section


def search_pages(query: str, limit: int, roots: list[tuple[Path, bool]]) -> list[dict]:
    """Rank OKF pages by query-token frequency; each hit points at its passage
    (moved intact from the query runtime; the Query surface passes the served
    context dir and the staged context drafts).

    Scans the served context dir AND the staged context drafts
    (``staging/context_layer/**/*.md``) — spec rev 4 §4: define_metric
    drafts must be discoverable before promotion. Staged hits carry
    ``draft: true`` and served hits ``draft: false`` — a draft never
    masquerades as verified context (ADR-0003: promotion stays human).

    Spec 2026-09-23-0002: ranking is deterministic and token-aware (whole
    ``[a-z0-9]+`` tokens, so incidental substrings like "order" inside
    "orders" no longer crowd out real matches; fenced code tokens count at
    half weight so generated SQL echoes rank below prose without hiding a
    fenced-only match; ties break by path, served before staged). Every hit
    additionally carries ``excerpt`` (a bounded
    verbatim substring of ``content`` around the first matched token),
    inclusive 1-based ``line_start``/``line_end`` covering that excerpt,
    and ``section`` (the containing ATX heading outside fenced code, else
    ``None`` — a frontmatter-only match never fabricates a body section;
    a body match is preferred over a frontmatter match). Nonpositive
    limits and queries with no matching token return ``[]``."""
    if limit <= 0:
        return []
    now = _assessment_now()  # one observational instant for the whole search (spec 0011 §2)
    terms = _QUERY_TOKEN_RE.findall(query.lower())
    hits: list[dict] = []
    for root, draft in roots:
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            lines = text.split("\n")
            mask = _fence_mask(lines)
            prose: Counter[str] = Counter()
            code: Counter[str] = Counter()
            for line, fenced in zip(lines, mask):
                (code if fenced else prose).update(_QUERY_TOKEN_RE.findall(line.lower()))
            score = 2 * sum(prose[term] for term in terms) + sum(code[term] for term in terms)
            if not score:
                continue
            frontmatter = _FRONTMATTER_RE.match(text)
            body_start = text[: frontmatter.start(2)].count("\n") if frontmatter else 0
            excerpt, line_start, line_end, section = _locate_passage(
                lines, mask, body_start, set(terms)
            )
            rel = path.relative_to(root).as_posix()
            hits.append(
                {
                    "path": rel,
                    "score": score,  # relative ranking value, not a frequency contract
                    "draft": draft,  # staged proposals stay distinguishable
                    "content": text,  # full OKF page: the rules are the payload
                    "excerpt": excerpt,
                    "line_start": line_start,
                    "line_end": line_end,
                    "section": section,
                    # spec 0011 §4: every hit carries the advisory envelope of ITS
                    # returned page, built from the already-read text — no second
                    # read, no ranking or eligibility authority
                    "context_signals": _context_signals([_page_view(rel, _page_meta(text), now)]),
                }
            )
    hits.sort(key=lambda hit: (-hit["score"], hit["path"]))
    return hits[:limit]


def _page_title(meta: dict, text: str) -> str | None:
    """A page's display title (spec 0015): declared frontmatter ``title``, else
    the first ATX heading outside fenced code, else ``None`` — never invented."""
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    lines = text.split("\n")
    for line, fenced in zip(lines, _fence_mask(lines)):
        if not fenced and line.startswith("# "):
            return line[2:].strip()
    return None


def list_pages(roots: list[tuple[Path, bool]]) -> list[dict]:
    """Enumerate every OKF page under the roots (spec 0015): the token-free
    directory view over the same roots :func:`search_pages` ranks — metadata
    only (``path``, ``draft``, ``title`` and the advisory ``context_signals``
    envelope), never page bodies. Roots are walked in the caller's order
    (the Query surface passes served before staged), sorted by path within
    each, so the listing is deterministic."""
    now = _assessment_now()
    pages: list[dict] = []
    for root, draft in roots:
        root = root.resolve()
        for path in sorted(root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            rel = path.relative_to(root).as_posix()
            meta = _page_meta(text)
            pages.append(
                {
                    "path": rel,
                    "draft": draft,
                    "title": _page_title(meta, text),
                    "context_signals": _context_signals([_page_view(rel, meta, now)]),
                }
            )
    return pages


def read_page(path: str, root: Path, *, draft: bool) -> dict:
    """Read one exact OKF page by bundle-relative POSIX path (spec 0015):
    full ``content`` plus ``draft``, ``context_signals`` and the resolved
    ``path``. Only an exact ``.md`` file directly under ``root`` reads — an
    absolute, backslashed, root-escaping (``..`` or symlink), non-markdown
    or unknown path raises ``ValueError`` naming the rejected path: never a
    search fallback, never an empty success."""
    if not isinstance(path, str) or not path or "\\" in path:
        raise ValueError(f"unknown context page: {path!r}")
    rel = PurePosixPath(path)
    if (
        rel.is_absolute()
        or not path.endswith(".md")
        or any(part in ("", ".", "..") for part in rel.parts)
    ):
        raise ValueError(f"unknown context page: {path!r}")
    root = root.resolve()
    candidate = (root.joinpath(*rel.parts)).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(f"unknown context page: {path!r}")
    text = candidate.read_text(encoding="utf-8")
    rel_str = candidate.relative_to(root).as_posix()
    meta = _page_meta(text)
    return {
        "path": rel_str,
        "draft": draft,
        "content": text,
        "context_signals": _context_signals([_page_view(rel_str, meta, _assessment_now())]),
    }


# --------------------------------------------------------- citation attachment


class _RequiredContextUnavailable(Exception):
    """Internal marker: the existing metric-context assembly path failed at
    this bundle-relative path (spec 0011 §5: missing/unreadable required
    metric/Policy context — advisory disclosure, never a query failure)."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


def _collapsed_context(path: str) -> dict:
    """The one required-context fallback shape (spec rev 10 §8.21 + spec 0011
    §5): the exact null/empty payload plus the path-specific
    ``context_unavailable`` warning — nothing was successfully assembled, so
    no page (and no undiscoverable dependency) is claimed assessed."""
    return {
        "metric_page": None,
        "policies": [],
        "context_signals": {
            "pages": [],
            "warnings": [{"code": "context_unavailable", "path": path}],
        },
    }


def metric_context(context_dir: Path, name: str) -> dict:
    """Rev 10 (ADR-0011): the governed number ships with its caveats — the full
    served OKF metric page (``context_layer/metrics/<name>.md``) plus the full
    bodies of every policy page its frontmatter ``sources[]`` cites
    (``policies/`` paths, resolved against the served context dir). When the
    metric's computation page declares ``attestation: pending`` (ADR-0013:
    promoted is not independently value-attested), the context carries that
    caveat explicitly. Context problems NEVER fail the query — the number is
    still governed: a missing metric page or an unresolvable policy reference
    collapses to ``{metric_page: null, policies: []}`` and is logged nowhere.
    Containment (defense in depth — served YAML names are not fully trusted):
    the metric page must resolve inside the context root and every cited policy
    under ``policies/``; a ``../..``-style traversal is just another
    unresolvable reference — the context collapses to the null form and
    nothing outside the context dir is ever read.

    Spec 0011 §§4–5: the context additionally carries the additive
    ``context_signals`` advisory envelope over exactly the consumed set — the
    metric page, its directly cited Policy pages, and the computation page when
    the existing computation-caveat path reads one. The required-context
    fallback keeps its exact null/empty payload and adds the path-specific
    ``context_unavailable`` warning. The assessment instant is the shared
    internal clock seam (spec 0011 §2) — never a public argument (issue #48
    fix: public signatures stay at their base contract)."""
    return _metric_context(context_dir, name)


def _metric_context(context_dir: Path, name: str, *, now: datetime | None = None) -> dict:
    """``metric_context``'s implementation seam: identical contract, plus the
    internal-only ``now`` that pins the single assessment instant of one
    multi-metric operation (spec 0011 §2) — ``None`` means the shared internal
    clock seam supplies it. Never part of the public API."""
    assess = _assessment_now() if now is None else now
    try:
        root = context_dir.resolve()
        page = root / "metrics" / f"{name}.md"
        if not page.resolve().is_relative_to(root):
            raise _RequiredContextUnavailable(f"metrics/{name}.md")
        text = page.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(text)
        try:
            meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
        except yaml.YAMLError:
            raise _RequiredContextUnavailable(f"metrics/{name}.md") from None
        if not isinstance(meta, dict):
            raise _RequiredContextUnavailable(f"metrics/{name}.md")
        refs = (
            source.get("resource") if isinstance(source, dict) else source
            for source in meta.get("sources") or []
        )
        policies_root = root / "policies"
        policies = []
        policy_views: dict[str, dict] = {}
        for ref in refs:
            if not (isinstance(ref, str) and ref.startswith("policies/")):
                continue
            body = (root / ref).resolve()
            if not body.is_relative_to(policies_root):
                raise _RequiredContextUnavailable(ref)
            try:
                policy_text = body.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                raise _RequiredContextUnavailable(ref) from None
            policies.append(policy_text)
            policy_views.setdefault(ref, _page_view(ref, _page_meta(policy_text), assess))
        computation = _computation_meta(root, name)
        pages = [_page_view(f"metrics/{name}.md", meta, assess), *policy_views.values()]
        if computation is not None:  # consumed by the existing caveat path
            pages.append(_page_view(f"computations/{name}.md", computation, assess))
        context = {
            "metric_page": text,
            "policies": policies,
            "context_signals": _context_signals(pages),
        }
        if computation is not None and computation.get("attestation") == "pending":
            # ADR-0013/spec acceptance 5, and ONLY the pending case (the new
            # harness-led bundles): governed:true means Promoted, never an
            # independent numeric attestation — say so on every such answer.
            # Existing attested bundles keep the established context shape.
            context["attestation"] = "pending"
            context["governed_note"] = (
                "governed: true means Promoted, not independently value-attested"
            )
        return context
    except _RequiredContextUnavailable as miss:
        return _collapsed_context(miss.path)
    except Exception:  # missing page, unresolvable ref, traversal, unparsable frontmatter
        return _collapsed_context(f"metrics/{name}.md")


def _computation_meta(root: Path, name: str) -> dict | None:
    """The computation page's frontmatter meta, or None when no such page is
    readable (read problems are just another missing caveat — never a
    failure). The page enters spec 0011 §5's consumed set exactly when this
    existing caveat path reads it; its attestation semantics live in
    ``metric_context`` (``attestation: pending``, ADR-0007 scoped extension)."""
    try:
        page = root / "computations" / f"{name}.md"
        if not page.resolve().is_relative_to(root) or not page.is_file():
            return None
        match = _FRONTMATTER_RE.match(page.read_text(encoding="utf-8"))
        meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
    except Exception:
        return None
    return meta if isinstance(meta, dict) else {}


# ------------------------------------------------- deterministic OKF generation

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # a bare column/table name

# Best-effort table refs in an agent-authored SELECT ("FROM demo.main.orders",
# "JOIN customers") for the draft page's provenance frontmatter.
_TABLE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_.]*)", re.IGNORECASE)


def _source_tables(source: str) -> list[str]:
    """Table names from the definition's source (a table name or SELECT). Best
    effort for exotic SQL — the staged OSI model stays the authoritative proposal."""
    if _IDENTIFIER_RE.fullmatch(source):
        return [source]
    return list(dict.fromkeys(t.rsplit(".", 1)[-1] for t in _TABLE_RE.findall(source)))


def _build_adhoc_page(params: dict) -> bytes:
    """Minimal OKF draft for the auto-staged proposal (spec rev 4 §4): frontmatter
    + name + description + dimensions + proposal marker, so ``search_context``
    can discover ad-hoc proposals and the human gate sees them in context."""
    frontmatter = yaml.safe_dump(
        {
            "type": "metric",
            "status": "draft",
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "sources": _source_tables(params["source"]),
        },
        sort_keys=False,
    )
    dimensions = "\n".join(f"- {d}" for d in (params["dimensions"] or ["(none)"]))
    return (
        f"---\n{frontmatter}---\n\n"
        f"# {params['name']}\n\n"
        f"{params['description']}\n\n"
        f"Dimensions:\n{dimensions}\n\n"
        "Auto-staged ad-hoc proposal awaiting promotion.\n"
    ).encode()


# ------------------------------------------------------- frontmatter primitives


def _load_frontmatter_meta(text: str) -> dict:
    """Frontmatter meta of an OKF page (empty dict when absent)."""
    match = _FRONTMATTER_RE.match(text)
    return (yaml.safe_load(match.group(1)) or {}) if match else {}


def _set_frontmatter(text: str, updates: dict) -> str:
    """Update (or add) YAML frontmatter on an OKF page, preserving the body."""
    match = _FRONTMATTER_RE.match(text)
    meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
    meta.update(updates)
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = match.group(2) if match else text
    return f"---\n{front}\n---\n\n{body}"


def _set_frontmatter_key(text: str, key: str, value) -> str:
    """Set — or REMOVE, with ``value=None`` — ONE frontmatter key, preserving
    every other key's order and the body (the K3 evidence-attachment seam:
    deterministic round-trip of a core-attached system claim)."""
    match = _FRONTMATTER_RE.match(text)
    meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
    if value is None:
        meta.pop(key, None)
    else:
        meta[key] = value
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = match.group(2) if match else text
    return f"---\n{front}\n---\n\n{body}"


def _load(text: str) -> tuple[dict | None, str]:
    """Split a file into (frontmatter meta or None, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    return (yaml.safe_load(match.group(1)) or {}), match.group(2)


# ------------------------------------------------------- the OKF page contract

# ADR-0007 bundle contract, as amended by spec 0010 §3/§9 (issue #41):
# every content type is CHECKED by its context_layer section and frontmatter
# ``type``; presence is APPLICABLE (a section with pages must satisfy its
# contract; absent sections are not invented categories), not the mandatory
# six-category presence — callers with their own complete-bundle scope (the
# legacy author loop) pass ``required_sections``.
_BUNDLE_TYPES = {
    "datasets": "dataset",
    "tables": "table",
    "references": "reference",
    "references/joins": "reference",
    "policies": "policy",
    "metrics": "metric",
    "computations": "computation",
    "skills": "skill",
}

# Per-type required frontmatter beyond ``type`` itself (ADR-0007 bundle
# contract, as documented in the authoring prompt and asserted per type in
# tests/test_author.py). Fields attached mechanically after validation (metric
# governed_by/dimensions/grain, computation runtime/attester) carry their own
# targeted errors below, not this shared list.
_BUNDLE_REQUIRED_FIELDS = {
    "dataset": ("title", "description", "tags", "sources"),
    "table": ("title", "description", "tags", "sources"),
    "reference": ("title", "description", "tags", "sources"),
    "policy": ("status", "title", "description", "tags", "sources"),
    "metric": ("status", "title", "description", "tags", "sources"),
    "computation": ("status", "title", "description", "tags", "sources"),
    "skill": ("title", "description", "tags", "sources"),
}


def _page_contract_errors(staging: Path, page: Path, expected_type: str) -> list[str]:
    """Contract violations of one staged page (ADR-0007 required frontmatter per
    type: every field the bundle contract documents and the per-type bundle
    tests assert — an omission anywhere fails the gate with the field named)."""
    rel = page.relative_to(staging).as_posix()
    try:
        text = page.read_text(encoding="utf-8")
        meta = _load_frontmatter_meta(text)
    except yaml.YAMLError as exc:
        return [f"{rel}: frontmatter is not valid YAML: {exc}"]
    if not meta:
        return [f"{rel}: no frontmatter (needs type: {expected_type})"]
    errors: list[str] = []
    if str(meta.get("type") or "") != expected_type:
        errors.append(f"{rel}: frontmatter type must be '{expected_type}'")
    for key in _BUNDLE_REQUIRED_FIELDS[expected_type]:
        if not meta.get(key):
            errors.append(f"{rel}: {expected_type} page requires '{key}' frontmatter")
    if expected_type == "table":
        # Spec 0010 §3 (issue #41): a physical table may have UNKNOWN Grain —
        # core-generated schema pages carry none, and a declared one must
        # still be the well-formed ADR-0007 block (semantic Grain requirements
        # on metric pages are unchanged below).
        grain = meta.get("grain")
        if grain is not None and (
            not isinstance(grain, dict)
            or not grain.get("primary_key")
            or not grain.get("cardinality_enforcement")
        ):
            errors.append(
                f"{rel}: a declared table grain block requires primary_key and "
                "cardinality_enforcement (an undeclared physical Grain stays unknown)"
            )
        # C1 (issue #69, spec 0024 §3): the optional authored selection of
        # observed filter values — validated here so a malformed mapping or a
        # duplicate declaration fails AUTHORING validation before human
        # admission, never first as a refresh refusal. Absent/empty is the
        # valid legacy form (no published values).
        errors.extend(
            f"{rel}: authored {OBSERVED_VALUE_COLUMNS_KEY} {error}"
            for error in _selection_shape_errors(meta.get(OBSERVED_VALUE_COLUMNS_KEY))
        )
        front = _FRONTMATTER_RE.match(text)
        if front:
            errors.extend(
                f"{rel}: authored {OBSERVED_VALUE_COLUMNS_KEY} {error}"
                for error in _duplicate_selection_declarations(front.group(1))
            )
        # Spec 0013 §2 (issue #53): the optional authored ``ariadne_quality``
        # profile — validated here so malformed/unsupported declarations fail
        # AUTHORING validation before human admission, never as a query
        # refusal. A table page without the key is the plain legacy form.
        errors.extend(_quality_profile_errors(rel, meta))
    elif expected_type == "metric":
        for key in ("governed_by", "dimensions", "grain"):  # attached mechanically
            if not meta.get(key):
                errors.append(
                    f"{rel}: metric page lacks governed '{key}' frontmatter (no "
                    "matching staged OSI model metric?)"
                )
        resources = [
            str(s.get("resource") if isinstance(s, dict) else s or "")
            for s in meta.get("sources") or []
        ]
        if not any(r.startswith("policies/") for r in resources):
            errors.append(
                f"{rel}: metric page must cite at least one governing policy "
                "(a policies/... source)"
            )
    elif expected_type == "computation":
        for key in ("governed_by", "runtime"):
            if not meta.get(key):
                errors.append(f"{rel}: computation page requires '{key}' frontmatter")
        # ADR-0007 scoped extension (ADR-0013): the honest ``attestation: pending``
        # state stands in for an attester a new metric does not have; a real
        # attester may be cited instead. Neither present = contract violation.
        if not meta.get("attester") and meta.get("attestation") != "pending":
            errors.append(
                f"{rel}: computation page requires 'attester' frontmatter or the honest "
                "'attestation: pending' state (ADR-0007 scoped extension)"
            )
    elif expected_type == "reference":
        # K2 (issue #42, spec 0010 §5): a Reference page MAY carry the versioned
        # ``ariadne`` extension; when present it is validated — malformed
        # supported declarations and author-fabricated approval/measurement
        # claims never pass the gate. A Reference WITHOUT the extension is the
        # legacy form and stays readable unchanged.
        errors.extend(_reference_extension_errors(rel, meta))
    return errors


# System-generated promotion bookkeeping (index trees, log): never authored
# content pages, so the per-type bundle gate does not check them (issue #36:
# the Git candidate's finalize pass generates the index trees BEFORE
# validation; legacy staging still has none at gate time — no behavior change
# for the legacy route).
_BOOKKEEPING_NAMES = frozenset({"index.md", "log.md"})


def _bundle_errors(
    staging: Path, *, required_sections: tuple[str, ...] | set[str] | None = None
) -> list[str]:
    """The hard ADR-0007 page-contract gate as amended by spec 0010 §3/§9
    (issue #41): applicable pages, not artificial presence of every category.
    Every section that carries pages satisfies its per-type contract — the
    inherited page→OSI/cited-Policy dependencies of the per-type checks stay
    binding; nothing is invented for absent categories. ``required_sections``
    restores a caller's own complete-bundle scope (the legacy author loop
    drafts the whole demo bundle): an absent required section is the
    historical "incomplete bundle" error."""
    context = staging / "context_layer"
    errors: list[str] = []
    present: set[str] = set()
    for section, expected_type in _BUNDLE_TYPES.items():
        section_dir = context / section
        pages = (
            sorted(p for p in section_dir.glob("*.md") if p.name not in _BOOKKEEPING_NAMES)
            if section_dir.is_dir()
            else []
        )
        if not pages:
            continue
        present.add(section)
        for page in pages:
            errors.extend(_page_contract_errors(staging, page, expected_type))
    if required_sections is not None:
        for section in required_sections:
            if section not in present:
                # the historical message text (it rides into the staged pages'
                # review_errors and the measured-retrieval corpus over the
                # demo tree depends on those bytes)
                errors.append(
                    f"authored bundle is incomplete: no pages under context_layer/{section}/ "
                    "(ADR-0007 requires all six content types: tables, references/joins, "
                    "policies, metrics, computations, skills)"
                )
    return errors


# ---------------------------------------------- post-validation OKF enrichment


def _model_index(staging: Path) -> tuple[dict[str, dict], bool]:
    """``(metric name -> {model, primary_key, dimensions, dataset_sources,
    expression}, all_parsed)`` from the staged OSI models — the mechanical
    source of truth for enrichment and computations. A model file whose YAML
    does not parse — or whose structures are malformed (a non-list
    ``semantic_model``, a non-mapping model/dataset/metric entry) — is SKIPPED
    and reported through ``all_parsed=False`` (its failure belongs to the
    validation gate, which reports it structurally); the legacy finalize runs
    only after validation passed, so nothing changes for the legacy route —
    the Git candidate's finalize (issue #36/G4) runs BEFORE validation and
    must leave invalid drafts to the gate, never crash on them (and never
    treat an unparseable draft's metrics as removed)."""
    index: dict[str, dict] = {}
    all_parsed = True
    models_dir = staging / "semantic_layer" / "models"
    for path in sorted(models_dir.glob("*.yml")) if models_dir.is_dir() else []:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            all_parsed = False  # unparseable draft: the validation gate owns the error
            continue
        if not isinstance(doc, dict):
            all_parsed = False
            continue
        models = doc.get("semantic_model")
        if not isinstance(models, list):
            all_parsed = False  # malformed draft: the gate owns the error
            continue
        for model in models:
            if not isinstance(model, dict):
                all_parsed = False
                continue
            pk: list[str] = []
            dimensions: list[str] = []
            dataset_sources: list[str] = []
            for dataset in model.get("datasets") or []:
                if not isinstance(dataset, dict):
                    all_parsed = False
                    continue
                pk = pk or [str(key) for key in dataset.get("primary_key") or []]
                source = dataset.get("source")
                if (
                    isinstance(source, str)
                    and source.strip()
                    and source.strip() not in dataset_sources
                ):
                    dataset_sources.append(source.strip())
                for field in dataset.get("fields") or []:
                    if isinstance(field, dict) and field.get("name") and "dimension" in field:
                        dimensions.append(str(field["name"]))
            for metric in model.get("metrics") or []:
                if not isinstance(metric, dict):
                    all_parsed = False
                    continue
                name = metric.get("name")
                if not name:
                    continue
                block = metric.get("expression")
                dialects = (block.get("dialects") if isinstance(block, dict) else None) or [{}]
                lead = dialects[0]
                if not isinstance(lead, dict):
                    all_parsed = False
                    lead = {}
                index[str(name)] = {
                    "model": str(model.get("name") or path.stem),
                    "primary_key": pk,
                    "dimensions": dimensions,
                    "dataset_sources": dataset_sources,
                    "expression": str(lead.get("expression") or ""),
                }
    return index, all_parsed


def _enrich_metric_pages(staging: Path, models: dict[str, dict]) -> None:
    """Attach governed_by/dimensions/grain to staged metric pages (spec §8.15) —
    derived from the staged OSI models, never trusted to LLM recall. A missing
    description defaults to the metric name: index links carry it, and the
    metric's own page must answer its name best in term-frequency search."""
    metrics_dir = staging / "context_layer" / "metrics"
    for path in sorted(metrics_dir.glob("*.md")) if metrics_dir.is_dir() else []:
        info = models.get(path.stem)
        if not info:
            continue
        existing = path.read_text(encoding="utf-8")
        try:
            description_missing = not _load_frontmatter_meta(existing).get("description")
        except yaml.YAMLError:
            continue  # unparseable draft frontmatter: the gate owns the error
        updates = {
            "governed_by": f"semantic_layer {info['model']}::{path.stem}",
            "dimensions": info["dimensions"],
            "grain": {
                "primary_key": info["primary_key"],
                "cardinality_enforcement": "STRICT_1_TO_1",
            },
        }
        if description_missing:
            updates["description"] = f"{path.stem.replace('_', ' ')} — governed metric"
        path.write_text(_set_frontmatter(existing, updates), encoding="utf-8")


def _write_computations(
    staging: Path, models: dict[str, dict], *, attester: str | None = "tests/test_evals.py"
) -> None:
    """One computation page per governed metric (spec §8.15): the sanctioned
    expression straight from the gate-checked model, runtime + attestation
    status. Deterministic: the LLM is never asked to reproduce SQL the compile
    gate already sanctions.

    ``attester=None`` is the harness-led mode (ADR-0013 / ADR-0007 scoped
    extension): a metric with no independent expected-value oracle carries an
    honest ``attestation: pending`` — never an invented attester such as the
    demo's ``tests/test_evals.py``.

    ponytail: pages are deliberately term-sparse (generic h1, no name repetition,
    no filler prose) — the query surface ranks context hits by term frequency
    (search_pages), so generated boilerplate must never outrank the metric's
    narrative page (spec §8.4)."""
    comp_dir = staging / "context_layer" / "computations"
    comp_dir.mkdir(parents=True, exist_ok=True)
    for name, info in sorted(models.items()):
        meta = {
            "type": "computation",
            "title": f"sanctioned SQL — {info['model']}::{name}",
            "description": "Sanctioned computation: SQL, runtime, attester.",
            "tags": ["computation"],
            "status": "draft",
            "governed_by": f"semantic_layer {info['model']}::{name}",
            "runtime": "duckdb",
            # the computation's recorded dataset sources — the semantic inputs
            # attestation preservation is bound to (issue #36 criterion 2): a
            # page that cannot prove its inputs unchanged conservatively
            # regenerates instead of inheriting an attester
            "dataset_sources": list(info["dataset_sources"]),
            "sources": [
                {
                    "id": f"model-{info['model']}",
                    "resource": f"../../semantic_layer/models/{info['model']}.yml",
                    "title": f"{info['model']} OSI model",
                }
            ],
        }
        if attester is None:
            meta["attestation"] = "pending"
        else:
            meta["attester"] = attester
        front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
        oracle = (
            "independent attestation pending — no expected-value oracle is cited "
            "(compile and grain checks are not independent numeric attestation)"
            if attester is None
            else f"attestation `{attester}` golden values"
        )
        body = (
            "# Sanctioned computation\n\n"
            f"Sanctioned SQL (ANSI_SQL, `semantic_layer/models/{info['model']}.yml`); "
            "compile gate `ariadne.validate`; execution DuckDB via the local `ariadne` "
            f"command (`ariadne get-metric`); {oracle}. "
            "Business rules: cited metric page.\n\n"
            "```sql\n" + info["expression"].strip() + "\n```\n"
        )
        (comp_dir / f"{name}.md").write_text(f"---\n{front}\n---\n\n{body}", encoding="utf-8")


def _stamp_pages(staging: Path, now: datetime, *, by: str = "ariadne-author") -> None:
    """Stamp the trust/lifecycle frontmatter the LLM must never invent (ADR-0007):
    generated/verified/stale_after on every staged OKF page."""
    stale_after = (now + timedelta(days=90)).date().isoformat()
    context_dir = staging / "context_layer"
    for path in sorted(context_dir.rglob("*.md")) if context_dir.is_dir() else []:
        path.write_text(
            _set_frontmatter(
                path.read_text(encoding="utf-8"),
                {
                    "generated": {
                        "by": by,
                        "at": now.isoformat(timespec="seconds"),
                    },
                    "verified": [],
                    "stale_after": stale_after,
                },
            ),
            encoding="utf-8",
        )


def _finalize_bundle(
    staging: Path,
    *,
    generated_by: str = "ariadne-author",
    attester: str | None = "tests/test_evals.py",
    stamp_lifecycle: bool = True,
) -> None:
    """Post-validation deterministic passes (ADR-0007): enrich metric pages from the
    staged models, generate the computation pages, stamp lifecycle frontmatter.
    Harness-led submission (spec 2026-09-24-0005) passes its own provenance and
    ``attester=None`` (pending attestation, ADR-0013). ``stamp_lifecycle=False``
    (the Git-authoring mode, issue #39/G7 fix) skips the WALL-CLOCK
    generated/verified/stale_after stamping: lifecycle claims belong to the
    deterministic finalize/promotion passes of the route the drafts enter, and
    fresh stamps would be refused as forged claims the moment the drafts are
    imported into a project that already carries an artifact revision."""
    now = datetime.now(UTC)
    models, _all_parsed = _model_index(staging)  # post-validation: always parsed
    _enrich_metric_pages(staging, models)
    _write_computations(staging, models, attester=attester)
    if stamp_lifecycle:
        _stamp_pages(staging, now, by=generated_by)


# ------------------------------------------- the Git-candidate finalize pass

_SQL_FENCE_RE = re.compile(r"```sql\n(.*?)\n```", re.DOTALL)


def _computation_matches(page: Path, name: str, info: dict) -> bool:
    """True when the existing computation page is the SAME computation: same
    governed_by identity, same sanctioned SQL expression AND the same dataset
    sources — the computation's full semantic dependencies. A model edit that
    keeps the expression text but changes what it reads (``events.events`` →
    a filtered SELECT) is a CHANGED computation: identical SQL over different
    inputs does not preserve an expected-value attestation (issue #36
    criterion 2). Only a full match may keep its bytes — an unchanged
    computation preserves its provenance and any independent expected-value
    attestation it carries; a CHANGED computation cannot inherit its
    predecessor's attestation and is regenerated with the honest
    ``attestation: pending`` state (ADR-0013). A page recording no dataset
    sources (a form the finalize never generated) proves nothing about its
    inputs and conservatively regenerates."""
    if not page.is_file():
        return False
    text = page.read_text(encoding="utf-8")
    try:
        meta = _load_frontmatter_meta(text)
    except yaml.YAMLError:
        return False  # malformed draft frontmatter: the gate owns the error
    fence = _SQL_FENCE_RE.search(text)
    return (
        meta.get("governed_by") == f"semantic_layer {info['model']}::{name}"
        and meta.get("dataset_sources") == info["dataset_sources"]
        and fence is not None
        and fence.group(1).strip() == info["expression"].strip()
    )


def finalize_candidate(staging: Path) -> None:
    """The deterministic finalize pass for Git-backed proposals (issue #36/G4,
    spec §4: generated artifact content is finalized BEFORE the candidate
    commit is validated): metric-page enrichment, computation pages and the
    index trees — with NO wall-clock lifecycle stamping and no review
    decoration. Existing page lifecycle frontmatter is not Git admission
    authority: reviewed/governed state is supplied by the external admission
    record (G5), so the committed pages are never restamped, and unchanged
    inherited pages keep their bytes verbatim (deterministic output ⇒ an
    unchanged retry is byte-identical and no-op revisions stay no-ops).

    Unchanged computations are preserved byte-for-byte — their independent
    attestation stays earned (unchanged is the FULL semantic dependency match:
    governed identity, sanctioned SQL and dataset sources); changed or new
    ones carry ``attestation:
    pending`` — and computations of metrics that no longer exist are removed
    (the generated set is always exactly the governed metric set). A model
    file that does not parse — or whose structures are malformed — is an
    invalid DRAFT (allowed at the edit seam):
    the computation set cannot be derived, so nothing is generated or removed
    and the validation gate reports the structural failure."""
    models, all_parsed = _model_index(staging)
    _enrich_metric_pages(staging, models)
    comp_dir = staging / "context_layer" / "computations"
    if all_parsed:
        changed = {
            name: info
            for name, info in sorted(models.items())
            if not _computation_matches(comp_dir / f"{name}.md", name, info)
        }
        if changed:
            _write_computations(staging, changed, attester=None)
        if comp_dir.is_dir():
            for page in sorted(comp_dir.glob("*.md")):
                if page.stem not in models:
                    page.unlink()
    _regenerate_indexes(staging / "context_layer")


# -------------------------- K1 (issue #41): core-owned physical schema pages

# The core-owned sections of a generated table page (spec 0010 §4): the
# physical schema block, the separately labeled observations and the schema
# change history. Authored content — the summary and the per-column meanings
# — lives OUTSIDE these sections and is preserved by refresh for identical
# column identity/type.
SCHEMA_SECTION = "Schema"
OBSERVATIONS_SECTION = "Observations"
HISTORY_SECTION = "Schema history"
MEANINGS_SECTION = "Column meanings"
_CORE_SECTIONS = frozenset({SCHEMA_SECTION, OBSERVATIONS_SECTION, HISTORY_SECTION})

# An authored column-meaning bullet: ``- `column` — meaning`` (any of the
# three separators). A bullet opens ONE meaning block that also owns its
# continuation lines (indented or lazy — a multiline Markdown explanation is
# ONE block, issue #41: it moves into history complete, never leaving an
# orphaned remainder in the active section); only parseable bullets name a
# column, everything else stays verbatim wherever it sits.
_MEANING_LINE_RE = re.compile(r"^[-*]\s+`([^`]+)`\s*[—:-]\s*(.+)$")
_LIST_ITEM_RE = re.compile(r"^[-*]\s+")


def _source_slug(source: str) -> str:
    """The filename slug of one source name: underscores to hyphens, capped
    at 48 characters (plan §2 — the digest preserves distinction)."""
    return source.replace("_", "-")[:48]


def generated_page_filename(resource: str, source: str) -> str:
    """The source-qualified filename of one generated page:
    ``<source-slug>-<sha256(resource)>.md`` — the full lowercase digest keeps
    same-named assets in long-named sources distinct after slug capping."""
    digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()
    return f"{_source_slug(source)}-{digest}.md"


def _body_sections(body: str) -> list[tuple[str | None, list[str]]]:
    """Split a page body into ``(heading text or None, lines)`` chunks at ATX
    headings of any level; each heading line stays with its chunk and the
    preamble (no heading) is the first chunk."""
    chunks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in body.split("\n"):
        if match := _HEADING_RE.match(line):
            chunks.append((match.group(1), [line]))
        else:
            chunks[-1][1].append(line)
    return chunks


def _assemble_body(chunks: list[tuple[str | None, list[str]]]) -> str:
    return "\n".join(line for _heading, lines in chunks for line in lines).strip()


def core_body_sections(text: str) -> dict[str, str]:
    """The core-owned BODY sections of one page (``Schema``, ``Observations``,
    ``Schema history``) keyed by section heading: the section chunk from its
    heading line to the next heading, trailing blank lines aside. This is the
    generated-facts map the proposal edit seam compares (issue #41): the
    core-owned rendered facts an inherited generated page carries may be
    carried unchanged, never changed, dropped or extended — frontmatter or
    not. Unparseable frontmatter yields no sections (the claim seam owns that
    refusal)."""
    try:
        _meta, body = _load(text)
    except yaml.YAMLError:
        return {}
    return {
        heading: "\n".join(lines).strip()
        for heading, lines in _body_sections(body or "")
        if heading in _CORE_SECTIONS
    }


def _schema_entry_text(value) -> str:
    """One schema fact's honest text: unknown metadata stays the explicit
    string ``unknown``; booleans render true/false."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "unknown"
    return str(value).replace("|", "\\|")


def _schema_flags(old_schema: list[dict] | None, new_schema: list[dict]) -> dict:
    """Column-level change flags of one refresh (plan §2): added/removed
    columns and type changes — detected by exact column identity, never
    paired into a rename guess."""
    old = {entry["column"]: entry["type"] for entry in old_schema or []}
    new = {entry["column"]: entry["type"] for entry in new_schema}
    return {
        "added": sorted(set(new) - set(old)),
        "removed": sorted(set(old) - set(new)),
        "type_changed": [
            {"column": column, "from": old[column], "to": new[column]}
            for column in sorted(set(old) & set(new))
            if old[column] != new[column]
        ],
    }


# ----------------- C1 (issue #69): selected observed filter values (spec
# 0024 §3). The human owns the optional ``observed_value_columns`` selection
# on a table page — an exact column -> catalog-type mapping that binds the
# publication to one known field representation; the core owns the measured
# ``value_evidence`` inside ``ariadne.observations`` and its rendering in the
# core-owned Observations section. Selection alone is never Source Approval
# or a sample grant, and it introduces no new permission, tool or engine.

OBSERVED_VALUE_COLUMNS_KEY = "observed_value_columns"

# The whole-value-evidence bound (spec 0024 §3): at most 8 KiB UTF-8 for the
# COMPLETE successful ``value_evidence`` mapping, measured as compact JSON
# with non-ASCII preserved — never a clipped literal or a partially retained
# histogram.
VALUE_EVIDENCE_MAX_BYTES = 8 * 1024

# The supported EXACT filter-value representations (spec 0024 §3): native
# text/enum labels, booleans, integers and FINITE native floating-point
# values, exactly as the profile measured them — never trimmed, case-folded,
# stringified nulls or numericated strings. Decimal, binary, temporal and
# complex normalizations are not an exact typed filter-value contract and
# stay unavailable (``unsupported_representation``), however the profiler
# stringified them for its own statistics.
_VALUE_EVIDENCE_TYPES = frozenset(
    {
        "VARCHAR",
        "ENUM",
        "BOOLEAN",
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
        "FLOAT",
        "REAL",
        "DOUBLE",
    }
)


def _duplicate_selection_declarations(front: str) -> list[str]:
    """Duplicate ``observed_value_columns`` declarations in RAW frontmatter
    YAML (spec 0024 §3): PyYAML collapses duplicate mapping keys last-wins, so
    the node tree is inspected directly — a duplicated top-level key or a
    duplicated column inside the selection is a validation error, never an
    implicit last-wins selection. Duplicate declarations of unrelated keys
    keep the existing safe_load behavior (not this contract)."""
    try:
        root = yaml.compose(front, Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return []  # unparseable frontmatter: the existing gates own that error
    if not isinstance(root, yaml.MappingNode):
        return []
    errors: list[str] = []
    declarations = 0
    for key_node, value_node in root.value:
        if not (
            isinstance(key_node, yaml.ScalarNode) and key_node.value == OBSERVED_VALUE_COLUMNS_KEY
        ):
            continue
        declarations += 1
        if not isinstance(value_node, yaml.MappingNode):
            continue  # a non-mapping selection: the shape check owns that error
        seen: set[str] = set()
        for column_node, _value in value_node.value:
            if not isinstance(column_node, yaml.ScalarNode):
                continue
            column = str(column_node.value)
            if column in seen:
                errors.append(f"duplicate declaration of column {column!r}")
            seen.add(column)
    if declarations > 1:
        errors.append("the top-level key is declared more than once")
    return errors


def _selection_shape_errors(selection: object) -> list[str]:
    """Shape errors of the optional authored ``observed_value_columns``
    mapping (spec 0024 §3): exact physical column name -> selected catalog
    type, both non-empty strings. An absent or EMPTY mapping is the valid
    legacy form (no published values); a malformed declaration is a
    validation error, never an implicit selection of all columns."""
    if selection is None:
        return []
    if not isinstance(selection, dict):
        return [
            f"{OBSERVED_VALUE_COLUMNS_KEY} must be a mapping of column name to "
            "selected catalog type"
        ]
    errors: list[str] = []
    for column, type_name in selection.items():
        if not isinstance(column, str) or not column:
            errors.append(f"column name {column!r} must be a non-empty string")
        if not isinstance(type_name, str) or not type_name:
            errors.append(
                f"column {column!r}: the selected catalog type must be a non-empty string"
            )
    return errors


def _authored_selection(existing_text: str | None, where: str) -> dict | None:
    """The VALIDATED authored selection of one existing table page (spec 0024
    §3) — the only input of measured value evidence. Absent/empty mapping
    means no published values; a malformed or duplicate declaration refuses
    the refresh BEFORE any page is built. A page without parseable frontmatter
    regenerates as before: there is no selection to honor."""
    if not existing_text:
        return None
    match = _FRONTMATTER_RE.match(existing_text)
    if not match:
        return None
    errors = _duplicate_selection_declarations(match.group(1))
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    selection = meta.get(OBSERVED_VALUE_COLUMNS_KEY) if isinstance(meta, dict) else None
    errors.extend(_selection_shape_errors(selection))
    if errors:
        raise ValueError(
            f"{where}: authored {OBSERVED_VALUE_COLUMNS_KEY} is not a valid selection "
            f"({'; '.join(errors) or 'malformed declaration'}) — fix the page metadata; "
            "nothing was written"
        )
    return selection or None


def _value_sort_key(entry: dict) -> tuple:
    """The deterministic evidence order (count descending, then the value
    ascending with null first): a canonical presentation of the SAME measured
    top values that keeps identical inputs byte-identical even when the
    engine's equal-count ordering differs between runs."""
    value = entry["value"]
    if value is None:
        return (-entry["count"], 0, "")
    if isinstance(value, (bool, int, float)):
        return (-entry["count"], 1, value)
    return (-entry["count"], 2, value)


def _compact_json_bytes(mapping: dict) -> int:
    """The whole-value-evidence bound measure (spec 0024 §3): compact JSON,
    UTF-8, non-ASCII preserved, non-finite numbers refused."""
    return len(
        json.dumps(mapping, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _value_evidence(*, selection: dict, columns: list[dict], profile: dict, where: str) -> dict:
    """Measured value evidence for the SELECTED columns only (spec 0024 §3):
    values/counts come from the profile's existing top_values — no new lookup,
    widened sampling, changed cardinality rule or histogram reconstruction; a
    missing histogram is ``not_in_profile``, never an empty-domain claim, and
    an invalid supplied measurement is an error, never a valid histogram.
    ``permission_denied`` is part of the contract's reason vocabulary but has
    no applicable permission gate on this V1 refresh path. The complete
    mapping must fit :data:`VALUE_EVIDENCE_MAX_BYTES` compact-JSON UTF-8
    bytes: over the bound EVERY selected column falls back to an unavailable/
    ``too_large`` outcome (never a clipped or arbitrarily reduced histogram),
    and a status-only mapping that still exceeds it refuses atomically."""
    schema_types = {entry["column"]: entry["type"] for entry in columns}
    profiled = profile.get("columns") or {}
    evidence: dict = {}
    for column, expected_type in selection.items():
        current = schema_types.get(column)
        if current is None:
            evidence[column] = {"state": "unavailable", "reason": "column_missing"}
            continue
        if current != expected_type:  # the authored type binds the representation
            evidence[column] = {"state": "unavailable", "reason": "type_changed"}
            continue
        if current.split("(", 1)[0].strip().upper() not in _VALUE_EVIDENCE_TYPES:
            evidence[column] = {"state": "unavailable", "reason": "unsupported_representation"}
            continue
        top = (profiled.get(column) or {}).get("top_values")
        if not isinstance(top, list) or not top:
            evidence[column] = {"state": "unavailable", "reason": "not_in_profile"}
            continue
        if not all(
            isinstance(entry, dict) and isinstance(entry.get("count"), int) and "value" in entry
            for entry in top
        ):
            raise ValueError(
                f"{where}: the profiled top_values of column {column!r} are a malformed "
                "measurement — an invalid measurement is an error, never a valid "
                "histogram; nothing was written"
            )
        if any(
            isinstance(entry["value"], float) and not math.isfinite(entry["value"]) for entry in top
        ):
            # finite native floats only (spec 0024 §3): a non-finite value is
            # not an exactly representable filter literal, and never a clipped one
            evidence[column] = {"state": "unavailable", "reason": "unsupported_representation"}
            continue
        evidence[column] = {
            "state": "observed",
            "top_values": sorted(top, key=_value_sort_key),
        }
    if _compact_json_bytes(evidence) > VALUE_EVIDENCE_MAX_BYTES:
        evidence = {column: {"state": "unavailable", "reason": "too_large"} for column in evidence}
    if _compact_json_bytes(evidence) > VALUE_EVIDENCE_MAX_BYTES:
        raise ValueError(
            f"{where}: even the status-only value evidence of the current selection "
            f"exceeds the {VALUE_EVIDENCE_MAX_BYTES}-byte compact-JSON bound — refresh "
            "refuses rather than writing partial evidence; reduce the selection"
        )
    return evidence


def _observation_facts(*, resource: str, profile: dict, value_evidence: dict | None = None) -> dict:
    """The core-generated observation facts WITHOUT the timestamp (the part
    compared for timestamp reuse): scope, counts, measured candidate keys and
    citation identity — measurements, never declared constraints. C1 (issue
    #69, spec 0024 §3): the selected value evidence rides the same facts and
    the same timestamp-reuse comparison; it is present ONLY when a nonempty
    validated selection exists, so selection-free refreshes keep the exact
    legacy facts, bytes and no-op behavior."""
    columns = {
        name: {"null_count": stats["null_count"], "distinct_count": stats["distinct_count"]}
        for name, stats in (profile.get("columns") or {}).items()
    }
    facts = {
        "scope": "sampled" if profile.get("sampled") else "full",
        "row_count": profile.get("row_count"),
        "candidate_keys": sorted(profile.get("primary_key_candidates") or []),
        "columns": columns,
        "citation": resource,
    }
    if value_evidence:
        facts["value_evidence"] = value_evidence
    return facts


def _ensure_citation(existing_sources: list | None, citation: dict) -> list:
    """The page's frontmatter sources with the core's catalog/profile citation
    guaranteed (authored entries preserved verbatim, no duplicates by
    resource)."""
    sources = list(existing_sources or [])
    resource = citation["resource"]
    if not any(
        (entry.get("resource") if isinstance(entry, dict) else entry) == resource
        for entry in sources
    ):
        sources.append(citation)
    return sources


def _meaning_blocks(lines: list[str]) -> list[tuple[str | None, str, list[str]]]:
    """The authored meanings section as ``(column or None, complete meaning
    text, block lines)`` blocks: one block per list item — an authored meaning
    bullet plus its continuation lines up to the next list item — with a
    column of ``None`` for preamble lines and non-meaning bullets, which stay
    verbatim wherever they sit. The complete text joins the bullet's meaning
    with its continuation lines, so a removed/type-changed column's multiline
    explanation moves into history as one block (issue #41)."""
    blocks: list[tuple[str | None, str, list[str]]] = []
    for line in lines:
        if _LIST_ITEM_RE.match(line) or not blocks:
            match = _MEANING_LINE_RE.match(line.strip())
            blocks.append(
                (
                    match.group(1) if match else None,
                    match.group(2).strip() if match else "",
                    [line],
                )
            )
        else:  # a continuation line belongs to the block above it
            _column, text, block = blocks[-1]
            parts = (text, line.strip())
            blocks[-1] = (_column, " ".join(part for part in parts if part), [*block, line])
    return blocks


def _table_body(
    *,
    asset: dict,
    columns: list[dict],
    observations: dict,
    flags: dict,
    observed_at: str,
    authored: str,
) -> str:
    """Assemble one table page's body from the authored content plus the
    three core-owned sections."""
    source, schema, table = asset["source"], asset["schema"], asset["table"]
    chunks = _body_sections(authored)
    # prior history ENTRIES survive verbatim (bullet lines only); the intro
    # and the empty placeholder are regenerated — the section is core-owned
    prior_history = [
        line
        for heading, lines in chunks
        if heading == HISTORY_SECTION
        for line in lines
        if line.startswith("- ")
    ]
    authored_chunks: list[tuple[str | None, list[str]]] = [
        (heading, lines) for heading, lines in chunks if heading not in _CORE_SECTIONS
    ]
    has_authored = any(line.strip() for _heading, lines in authored_chunks for line in lines)
    if not has_authored:  # a page refresh never saw: seed the authored scaffold
        authored_chunks = [
            (
                None,
                [
                    f"# {source}.{schema}.{table}",
                    "",
                    f"Physical table `{table}` of source `{source}` (schema `{schema}`).",
                    "Summary: unknown — not yet authored.",
                    "",
                ],
            )
        ]
    # meanings surgery: preserve blocks of identical columns verbatim, move
    # removed/type-changed columns' COMPLETE meaning blocks (continuation
    # lines included) into history, seed new columns
    changed_columns = set(flags["removed"]) | {c["column"] for c in flags["type_changed"]}
    retained: dict[str, str] = {}
    meanings_index = next(
        (i for i, (h, _l) in enumerate(authored_chunks) if h == MEANINGS_SECTION), None
    )
    if meanings_index is None:
        meanings_lines: list[str] = []
        authored_chunks.append((MEANINGS_SECTION, []))
        meanings_index = len(authored_chunks) - 1
    else:
        # the chunk's first line IS the heading — it is re-emitted exactly once
        _heading, lines = authored_chunks[meanings_index]
        meanings_lines = lines[1:]
        authored_chunks[meanings_index] = (_heading, [])  # rebuilt below
    kept: list[str] = []
    seen: set[str] = set()
    for column, text, block in _meaning_blocks(meanings_lines):
        if column is not None and column in changed_columns:
            retained[column] = text  # the complete block moves to history
            continue
        if column is not None and column in seen:
            kept.extend(block)  # a duplicate meaning stays verbatim
            continue
        if column is not None:
            seen.add(column)
        kept.extend(block)
    known = {entry["column"] for entry in columns}
    for column in sorted(known - seen):
        kept.append(f"- `{column}` — unknown (not yet authored)")
    heading, _ = authored_chunks[meanings_index]
    stripped = [line for line in kept if line.strip()]
    authored_chunks[meanings_index] = (
        heading,
        [f"## {MEANINGS_SECTION}", *stripped, ""],
    )
    history = prior_history + _history_entries(flags, observed_at, retained)
    schema_rows = [
        "| Column | Type | Nullable | Default | Comment |",
        "| --- | --- | --- | --- | --- |",
        *[
            "| `{}` | {} | {} | {} | {} |".format(
                entry["column"],
                _schema_entry_text(entry["type"]),
                _schema_entry_text(entry["nullable"]),
                _schema_entry_text(entry["default"]),
                _schema_entry_text(entry["comment"]),
            )
            for entry in columns
        ],
    ]
    observation_lines = [
        f"- observed_at: {observations['observed_at']}",
        f"- scope: {observations['scope']}",
        f"- row_count: {observations['row_count']}",
        "- candidate keys (measured, not business-key declarations): "
        + (", ".join(observations["candidate_keys"]) or "none observed"),
        f"- citation: {observations['citation']}",
        *[
            f"- `{name}`: nulls {stats['null_count']}, distinct {stats['distinct_count']}"
            for name, stats in observations["columns"].items()
        ],
    ]
    value_evidence = observations.get("value_evidence")
    if value_evidence:
        # C1 (issue #69, spec 0024 §3): the SAME selected measured facts,
        # rendered as data inside the core-owned observation section — never
        # an independently authored list or usage instructions. A measured
        # null renders as the JSON literal null, never the string "NULL".
        observation_lines.append(
            "- value evidence (selected observed filter values — measured top "
            "values, not a complete allowed-value domain):"
        )
        for name, entry in value_evidence.items():
            if entry.get("state") == "observed":
                rendered = ", ".join(
                    f"{json.dumps(item['value'], ensure_ascii=False)} ({item['count']})"
                    for item in entry["top_values"]
                )
                observation_lines.append(f"  - `{name}`: observed — {rendered}")
            else:
                observation_lines.append(f"  - `{name}`: unavailable ({entry['reason']})")
    core: list[tuple[str | None, list[str]]] = [
        (
            SCHEMA_SECTION,
            [
                f"# {SCHEMA_SECTION}",
                "",
                "Core-generated physical schema (regenerated by refresh_schema; "
                "authored meaning lives above). Declared metadata appears only "
                "where the source provides it; unavailable metadata is unknown.",
                "",
                *schema_rows,
                "",
            ],
        ),
        (
            OBSERVATIONS_SECTION,
            [
                f"## {OBSERVATIONS_SECTION}",
                "",
                "Core-generated observations of the stated scope — measurements, "
                "not declared constraints: observed uniqueness or zero nulls is "
                "never a NOT NULL or business-key declaration.",
                "",
                *observation_lines,
                "",
            ],
        ),
        (
            HISTORY_SECTION,
            [
                f"## {HISTORY_SECTION}",
                "",
                "Core-generated record of detected schema changes: removed or "
                "changed columns keep their prior authored meaning here for "
                "review — a rename is never guessed.",
                "",
                *(history or ["(none — no schema changes recorded)"]),
                "",
            ],
        ),
    ]
    return _assemble_body(authored_chunks + core)


def _history_entries(flags: dict, observed_at: str, retained: dict[str, str]) -> list[str]:
    """Deterministic history entries for one refresh's detected changes,
    sorted by column, quoting the retained authored meaning when one exists."""
    entries: list[str] = []
    for column in sorted(flags["removed"]):
        was = next((c["type"] for c in flags.get("_old_schema", []) if c["column"] == column), None)
        note = f"`{column}` removed" + (f" (was {was})" if was else "")
        if column in retained:
            note += f"; retained meaning: {retained[column]}"
        entries.append(f"- {observed_at} — {note}")
    for change in flags["type_changed"]:
        note = f"`{change['column']}` type changed {change['from']} -> {change['to']}"
        if change["column"] in retained:
            note += f"; retained meaning: {retained[change['column']]}"
        entries.append(f"- {observed_at} — {note}")
    return entries


def build_table_page(
    *,
    asset: dict,
    columns: list[dict],
    profile: dict,
    existing_text: str | None,
    now: str,
) -> tuple[str, dict]:
    """Generate one physical table page's complete bytes from the approved
    catalog/profile facts (spec 0010 §4, plan §2): frontmatter with the exact
    resource and the core-owned ``ariadne.schema``/``ariadne.observations``
    metadata, authored summary/meanings preserved outside the core-owned
    sections, removed/type-changed columns' meanings retained as history, and
    the observation timestamp REUSED when the schema and the measurements are
    unchanged (identical inputs produce identical bytes — a no-op refresh).
    Returns ``(page text, change flags)``.
    """
    resource = asset["resource"]
    try:
        existing_meta = _load_frontmatter_meta(existing_text) if existing_text else {}
    except yaml.YAMLError:
        existing_meta = {}
    existing_ariadne = existing_meta.get("ariadne") if isinstance(existing_meta, dict) else None
    old_schema = existing_ariadne.get("schema") if isinstance(existing_ariadne, dict) else None
    old_schema = old_schema if isinstance(old_schema, list) else None
    old_observations = (
        existing_ariadne.get("observations") if isinstance(existing_ariadne, dict) else None
    )
    old_observations = old_observations if isinstance(old_observations, dict) else {}
    old_observed_at = (
        old_observations.get("observed_at")
        if isinstance(old_observations.get("observed_at"), str)
        else None
    )
    flags = _schema_flags(old_schema, columns)
    selection = _authored_selection(existing_text, resource)
    value_evidence = (
        _value_evidence(selection=selection, columns=columns, profile=profile, where=resource)
        if selection
        else None
    )
    facts = _observation_facts(resource=resource, profile=profile, value_evidence=value_evidence)
    reuse_timestamp = (
        old_observed_at is not None
        and old_schema is not None
        and old_schema == columns
        and {k: v for k, v in old_observations.items() if k != "observed_at"} == facts
    )
    observed_at = old_observed_at if reuse_timestamp and old_observed_at is not None else now
    observations = {"observed_at": observed_at, **facts}
    citation = {
        "id": f"catalog-{asset['source']}-{asset['schema']}-{asset['table']}",
        "resource": resource,
        "title": f"catalog and profile of {asset['source']}.{asset['schema']}.{asset['table']}",
    }
    meta: dict = {
        "type": "table",
        "title": f"{asset['source']}.{asset['schema']}.{asset['table']}",
        "description": (
            f"Physical table {asset['table']} of source {asset['source']} "
            f"(schema {asset['schema']}). Row meaning: unknown — not yet authored."
        ),
        "tags": ["table", "schema"],
    }
    if isinstance(existing_meta, dict):
        for key in ("title", "description", "tags"):
            if existing_meta.get(key):
                meta[key] = existing_meta[key]
    meta["sources"] = _ensure_citation(
        existing_meta.get("sources") if isinstance(existing_meta, dict) else None, citation
    )
    if isinstance(existing_meta, dict):
        if existing_meta.get("grain") is not None:  # authored declared Grain preserved
            meta["grain"] = existing_meta["grain"]
        for key in sorted(set(existing_meta) - set(meta) - {"type", "ariadne", "resource"}):
            meta[key] = existing_meta[key]  # authored extras preserved verbatim
    meta["resource"] = resource
    meta["ariadne"] = {"schema": columns, "observations": observations}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    authored = ""
    if existing_text:
        _fm, authored = _load(existing_text)
        if authored is None:
            authored = ""
    flags_with_old = {**flags, "_old_schema": old_schema or []}
    body = _table_body(
        asset=asset,
        columns=columns,
        observations=observations,
        flags=flags_with_old,
        observed_at=observed_at,
        authored=authored,
    )
    return f"---\n{front}---\n\n{body}\n", flags


# ------------- K2 (issue #42): structured References and term resolution

# The supported ``ariadne`` extension version of a Reference page (plan §2:
# integer 1; an unsupported or malformed version is a contract violation,
# never a guess).
ARIADNE_EXTENSION_VERSION = 1
# The reference-role discriminator of the extension (spec 0010 §5): Term
# References and Identifier Mappings are roles within References, not new
# standalone page types; ``join``/``enum`` pages carry the same structures
# without gaining an interpreter.
REFERENCE_ROLES = ("term", "identifier", "enum", "join")
MAPPING_FAMILIES = ("equality", "prefix", "lookup")
MAPPING_CLAIMS = ("hypothesis", "asserted")
# Concept/representation/mapping slugs follow the safe page-name discipline:
# a plain lowercase slug — never a path, hidden, option-shaped or wildcard.
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
# The bounded resolution contract (plan §2): at most 20 matches per part in
# stable page/representation order, explicit truncation, part continuation.
RESOLVE_TERM_LIMIT = 20
# …and the SAME 64 KiB serialized-response ceiling the operator's bounded
# inspection defaults set (plan §2): every response PART stays under this
# many serialized UTF-8 bytes on top of the count limit.
RESOLVE_TERM_MAX_BYTES = 64 * 1024
# Disclosure caps of one oversized match entry (the never-silent-drop path):
# an entry whose serialized form alone cannot fit a whole response part is
# still disclosed — identity fields intact, every over-cap string/list cut
# with an explicit marker naming what was elided.
_RESOLVE_TEXT_CAP = 512  # characters one disclosed string field may carry
_RESOLVE_LIST_CAP = 8  # items one disclosed list may carry
# Serialized bytes reserved for the envelope's own fields (request, counters,
# truncation/continuation flags) when budgeting a part's matches.
_RESOLVE_ENVELOPE_RESERVE = 1024

_EXTENSION_KEYS = frozenset({"version", "reference_role", "representations", "mappings"})
_REPRESENTATION_KEYS = frozenset({"id", "aliases", "fields", "scope", "description"})
# K3 (issue #43, spec 0010 §7): the structured inspection candidate IS part of
# a mapping declaration now — validated by the shared candidate schema below
# (``validate_inspection_candidate``), still alongside the refusal of every
# author-fabricated approval/measurement claim.
_MAPPING_KEYS = frozenset(
    {"id", "family", "from", "to", "claim", "source_ids", "receipt_ids", "candidate"}
)


# --------------------- K3 (issue #43): the inspection candidate schema

# The candidate is a discriminated JSON object, never an executable string
# (spec 0010 §7, plan §2 "Inspection candidate and finite limits"): the
# allowlists below are exhaustive — there is no SQL, function, path or freely
# interpreted expression field, and an unknown key is refused by name.
CANDIDATE_FAMILIES = ("equality", "prefix", "lookup")
CANDIDATE_SCOPE_OPS = ("eq", "in", "gte", "lt")
# Operator-owned structural ceilings of one candidate (plan §2): four
# participating assets, sixteen candidate field bindings, eight scope
# predicates, one hundred values per in-list. Requests never raise these.
MAX_PARTICIPATING_ASSETS = 4
MAX_CANDIDATE_BINDINGS = 16
MAX_SCOPE_PREDICATES = 8
MAX_IN_LIST_VALUES = 100

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
# The bounded verified receipt summary the core attaches to a Reference page
# at finalization (K3, plan §2): credential-free counts only, never raw
# examples — and never authorable (the edit seam owns the claim key).
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


def _canonical_digest(payload: object) -> str:
    """sha256 over the canonical UTF-8 JSON form (sorted keys, compact)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _one_resource(where: str, bindings: list[dict]) -> str:
    """The single resource every binding of one side names (left/right sides
    each address ONE catalog asset — a composite tuple or paired record of one
    table, never a mixture of two assets' rows)."""
    resources = {binding["resource"] for binding in bindings}
    if len(resources) != 1:
        raise ValueError(
            f"{where} must name exactly ONE catalog asset (got {len(resources)} — a "
            "composite tuple pairs columns of one asset)"
        )
    return resources.pop()


def validate_inspection_candidate(candidate: object) -> dict:
    """Validate the structured inspection candidate (spec 0010 §7, plan §2)
    and return its normalized deep copy — the identity a receipt's
    ``candidate_digest`` binds and a re-declared mapping must reproduce.
    Raises ``ValueError`` naming the offending field for every malformed
    shape: unknown keys (there is no SQL/function/path field anywhere),
    non-canonical bindings, unsupported operators, untyped scope values,
    arity violations and the structural ceilings."""
    if not isinstance(candidate, dict):
        raise ValueError(
            f"the inspection candidate must be a discriminated JSON object, got "
            f"{type(candidate).__name__}"
        )
    family = candidate.get("family")
    if family not in CANDIDATE_FAMILIES:
        raise ValueError(
            f"the inspection candidate family must be one of "
            f"{list(CANDIDATE_FAMILIES)}, got {family!r}"
        )
    allowed = _COMMON_CANDIDATE_KEYS | _FAMILY_CANDIDATE_KEYS[family]
    unknown = sorted(set(candidate) - allowed)
    if unknown:
        raise ValueError(
            f"the inspection candidate carries unsupported field(s) {unknown} — a "
            "candidate is a discriminated object of {family!r} with at most "
            f"{sorted(allowed)}; there is no SQL, function or path field"
        )
    for side in ("left", "right"):
        bindings = candidate.get(side)
        if not isinstance(bindings, list) or not bindings:
            raise ValueError(
                f"the inspection candidate requires an ordered non-empty '{side}' "
                "field binding list"
            )
        errors = _binding_errors(f"candidate {side}", bindings)
        if errors:
            raise ValueError("; ".join(errors))
    left, right = candidate["left"], candidate["right"]
    left_resource = _one_resource("candidate left", left)
    right_resource = _one_resource("candidate right", right)
    assets = {left_resource, right_resource}
    binding_count = len(left) + len(right)
    scope = candidate.get("scope", [])
    if scope is None:
        scope = []
    if not isinstance(scope, list):
        raise ValueError("candidate scope must be an ordered list of predicates")
    if len(scope) > MAX_SCOPE_PREDICATES:
        raise ValueError(
            f"the inspection candidate carries {len(scope)} scope predicates — at "
            f"most {MAX_SCOPE_PREDICATES} are measurable per request"
        )
    for index, predicate in enumerate(scope):
        where = f"candidate scope[{index}]"
        if not isinstance(predicate, dict) or set(predicate) != _SCOPE_PREDICATE_KEYS:
            raise ValueError(
                f"{where} must be exactly {{resource, column, op, value}} — scope "
                "operators are eq/in/gte/lt over typed scalar values"
            )
        binding = {"resource": predicate["resource"], "column": predicate["column"]}
        errors = _binding_errors(where, [binding])
        if errors:
            raise ValueError("; ".join(errors))
        # K3 fix pass (finding 1): a scope predicate narrows a PARTICIPATING
        # measured asset — attachment is checked below, after the family
        # branch resolved every participating (side/lookup) asset.
        if predicate["op"] not in CANDIDATE_SCOPE_OPS:
            raise ValueError(
                f"{where} operator must be one of {list(CANDIDATE_SCOPE_OPS)}, got "
                f"{predicate['op']!r}"
            )
        value = predicate["value"]
        if predicate["op"] == "in":
            if (
                not isinstance(value, list)
                or not value
                or len(value) > MAX_IN_LIST_VALUES
                or not all(_scope_scalar(item) for item in value)
            ):
                raise ValueError(
                    f"{where} 'in' value must be a non-empty list of at most "
                    f"{MAX_IN_LIST_VALUES} typed scalar values"
                )
        elif not _scope_scalar(value):
            raise ValueError(
                f"{where} value must be a typed scalar (string, number or boolean) "
                "bound as a parameter"
            )
    binding_count += len(scope)
    pairing = candidate.get("pairing", [])
    if pairing is None:
        pairing = []
    if not isinstance(pairing, list):
        raise ValueError("candidate pairing must be a list of field pairs")
    for index, pair in enumerate(pairing):
        where = f"candidate pairing[{index}]"
        if not isinstance(pair, dict) or set(pair) != _PAIRING_KEYS:
            raise ValueError(
                f"{where} must be exactly {{left, right}} — pairing names "
                "independently supplied record keys, not a guessed row order"
            )
        for side, side_resource in (("left", left_resource), ("right", right_resource)):
            errors = _binding_errors(f"{where} {side}", [pair[side]])
            if errors:
                raise ValueError("; ".join(errors))
            # K3 fix pass (finding 1): a pairing binding names a column of ITS
            # side's measured asset — a pairing identity naming another asset
            # while the measurement reads the side's columns is a refusal, so a
            # receipt never carries a pairing identity for columns it did not
            # read from that asset.
            if pair[side]["resource"] != side_resource:
                raise ValueError(
                    f"{where} {side} binding must name the candidate's {side} asset "
                    f"{side_resource!r} — a pairing key binds a column of ITS side's "
                    f"measured asset, got {pair[side]['resource']!r}"
                )
        binding_count += 2
    prefix_lookup = lookup = None
    if family == "equality":
        if len(left) != len(right):
            raise ValueError(
                f"an equality candidate compares equally sized tuples — left has "
                f"{len(left)} field(s), right {len(right)}"
            )
    elif family == "prefix":
        if len(right) != 1:
            raise ValueError("a prefix candidate compares one target field binding")
        separator = candidate.get("separator")
        if not isinstance(separator, str):
            raise ValueError(
                "a prefix candidate carries an explicit literal 'separator' string "
                "(the empty string is explicit)"
            )
        prefix_lookup = candidate.get("prefix_lookup")
        if prefix_lookup is not None:
            if not isinstance(prefix_lookup, dict) or set(prefix_lookup) != _PREFIX_LOOKUP_KEYS:
                raise ValueError(
                    "candidate prefix_lookup must be exactly {asset, key_fields, prefix_field}"
                )
            prefix_lookup, lookup_bindings = _lookup_asset(prefix_lookup, "candidate prefix_lookup")
            if len(lookup_bindings["key_fields"]) > len(left):
                raise ValueError(
                    "candidate prefix_lookup key_fields outnumber the left components they identify"
                )
            binding_count += lookup_bindings["count"]
            assets.add(prefix_lookup["asset"])
    else:  # lookup
        lookup = candidate.get("lookup")
        if not isinstance(lookup, dict) or set(lookup) != _LOOKUP_KEYS:
            raise ValueError("candidate lookup must be exactly {asset, key_fields, value_fields}")
        lookup, lookup_bindings = _lookup_asset(lookup, "candidate lookup")
        if len(left) != len(lookup["key_fields"]):
            raise ValueError(
                f"a lookup candidate's left bindings match the lookup key_fields "
                f"one-for-one — left has {len(left)}, key_fields "
                f"{len(lookup['key_fields'])}"
            )
        if len(right) != len(lookup["value_fields"]):
            raise ValueError(
                f"a lookup candidate's right bindings match the lookup "
                f"value_fields one-for-one — right has {len(right)}, value_fields "
                f"{len(lookup['value_fields'])}"
            )
        if left_resource != right_resource:
            raise ValueError(
                "a lookup candidate's left and right bindings name the same "
                "measured asset (its keys and mapped values)"
            )
        binding_count += lookup_bindings["count"]
        assets.add(lookup["asset"])
    # K3 fix pass (finding 1): scope predicates attach to PARTICIPATING
    # measured assets only — scope on an otherwise unmeasured asset would be
    # retained in the receipt's declaration while never narrowing any read.
    unattached = sorted({predicate["resource"] for predicate in scope} - assets)
    if unattached:
        raise ValueError(
            f"candidate scope names {unattached}, which is not a participating "
            f"measured asset (measured participants: {sorted(assets)}) — scope "
            "narrows a participating measured asset only"
        )
    if binding_count > MAX_CANDIDATE_BINDINGS:
        raise ValueError(
            f"the inspection candidate binds {binding_count} fields — at most "
            f"{MAX_CANDIDATE_BINDINGS} candidate field bindings are measurable per "
            "request"
        )
    if len(assets) > MAX_PARTICIPATING_ASSETS:
        raise ValueError(
            f"the inspection candidate names {len(assets)} participating assets "
            f"({sorted(assets)}) — at most {MAX_PARTICIPATING_ASSETS} participate"
        )
    normalized = json.loads(json.dumps(candidate, ensure_ascii=False))  # deep copy
    normalized["scope"] = scope
    normalized["pairing"] = pairing
    return normalized


def _scope_scalar(value: object) -> bool:
    """A typed scope scalar (bool is not a number here; null is untyped)."""
    return isinstance(value, (str, int, float, bool)) and not isinstance(value, type(None))


def _lookup_asset(lookup: dict, where: str) -> tuple[dict, dict]:
    """Validate one lookup/prefix-lookup asset declaration: a canonical table
    resource with its ordered key/value (or prefix) field bindings all naming
    THAT asset. Returns (the declaration, {key_fields, value_fields, count})."""
    asset = lookup.get("asset")
    try:
        kind, _parts = parse_resource(asset)
    except ValueError as exc:
        raise ValueError(f"{where} asset is not canonical: {exc}") from None
    if kind != "table":
        raise ValueError(f"{where} names a {kind} resource — a lookup asset is a table")
    fields: dict[str, list[dict]] = {}
    count = 0
    for key in ("key_fields", "value_fields", "prefix_field"):
        if key not in lookup:
            continue
        bindings = lookup[key]
        bindings = [bindings] if key == "prefix_field" else bindings
        if not isinstance(bindings, list) or not bindings:
            raise ValueError(f"{where} {key} must be an ordered non-empty binding list")
        errors = _binding_errors(f"{where} {key}", bindings)
        if errors:
            raise ValueError("; ".join(errors))
        for binding in bindings:
            if binding["resource"] != asset:
                raise ValueError(
                    f"{where} {key} must bind the lookup asset itself — a binding "
                    f"names {binding['resource']!r}"
                )
        fields[key] = bindings
        count += len(bindings)
    if "key_fields" not in fields:
        raise ValueError(f"{where} requires its ordered key_fields")
    return lookup, {
        "key_fields": fields["key_fields"],
        "value_fields": fields.get("value_fields", []),
        "count": count,
    }


def candidate_digest(candidate: object) -> str:
    """The normalized candidate identity digest (plan §2): family, ordered
    fields/components, scope and pairing/lookup parameters — never observed
    results or measurement time."""
    return _canonical_digest(validate_inspection_candidate(candidate))


def _aliases_errors(where: str, aliases: object) -> list[str]:
    """Aliases are a list of non-empty strings (natural-language names)."""
    if not isinstance(aliases, list) or not all(
        isinstance(alias, str) and alias.strip() for alias in aliases
    ):
        return [f"{where} aliases must be a list of non-empty strings"]
    return []


def _binding_errors(where: str, bindings: object) -> list[str]:
    """Field/scope bindings are ordered ``{resource, column}`` entries with a
    CANONICAL table resource and an exact column identity (spec 0010 §4/§5:
    bindings use the actual catalog identity, never an ambiguous name)."""
    if not isinstance(bindings, list):
        return [f"{where} must be an ordered list of {{resource, column}} bindings"]
    errors: list[str] = []
    for index, binding in enumerate(bindings):
        spot = f"{where}[{index}]"
        if not isinstance(binding, dict) or set(binding) != {"resource", "column"}:
            errors.append(f"{spot} must be exactly {{resource, column}}")
            continue
        try:
            kind, _parts = parse_resource(binding["resource"])
        except ValueError as exc:
            errors.append(f"{spot} resource is not canonical: {exc}")
            continue
        if kind != "table":
            errors.append(f"{spot} names a {kind} resource — a field binding names a table")
        if not isinstance(binding["column"], str) or not binding["column"]:
            errors.append(f"{spot} column must be a non-empty exact identifier")
    return errors


def _reference_extension_errors(rel: str, meta: dict) -> list[str]:
    """The version-1 ``ariadne`` extension contract of one Reference page
    (spec 0010 §5, plan §2 "Structured References, authority and freshness"):
    integer version 1, a valid reference role, ordered representations with
    stable slug IDs/aliases/exact bindings/required scope, and mappings whose
    endpoints resolve within the Reference, whose claim is classified and
    whose evidence dependencies resolve to ACTUAL page footnotes. The strict
    field allowlist rejects author-fabricated system authority and measured
    claims (``approved``/``confirmed``/counts/digests) wherever they appear; a
    page WITHOUT the extension is the legacy form and reports no errors."""
    if "ariadne" not in meta:
        return []  # legacy Reference: the extension is ABSENT, never required
    extension = meta["ariadne"]
    if extension is None:
        # A PRESENT-but-null extension is the MALFORMED form of a supported
        # extension, not the legacy absent one — the resolver must refuse the
        # page explicitly instead of crashing on ``None``.
        return [
            f"{rel}: the ariadne extension is null — null is not the legacy "
            "(absent) form; declare the structured extension or remove the key"
        ]
    if not isinstance(extension, dict):
        return [f"{rel}: the ariadne extension must be a mapping, got {type(extension).__name__}"]
    errors: list[str] = []
    version = extension.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return [
            f"{rel}: ariadne extension version must be the integer "
            f"{ARIADNE_EXTENSION_VERSION}, got {version!r}"
        ]
    if version != ARIADNE_EXTENSION_VERSION:
        return [
            f"{rel}: unsupported ariadne extension version {version} "
            f"(supported: {ARIADNE_EXTENSION_VERSION})"
        ]
    unknown = sorted(set(extension) - _EXTENSION_KEYS)
    if unknown:
        errors.append(f"{rel}: the ariadne extension carries unsupported field(s) {unknown}")
    role = extension.get("reference_role")
    if role not in REFERENCE_ROLES:
        errors.append(f"{rel}: reference_role must be one of {list(REFERENCE_ROLES)}, got {role!r}")
    if meta.get("aliases") is not None:  # page aliases are optional (the
        # concept may have none — only their FORM is validated)
        errors.extend(_aliases_errors(f"{rel}: page", meta.get("aliases")))
    representations = extension.get("representations")
    if not isinstance(representations, list):
        representations = []
        errors.append(
            f"{rel}: representations must be an ordered list "
            "(a role with no representations declares an empty list)"
        )
    representation_ids: set[str] = set()
    for position, representation in enumerate(representations):
        where = f"{rel}: representations[{position}]"
        if not isinstance(representation, dict):
            errors.append(f"{where} must be a mapping")
            continue
        unknown = sorted(set(representation) - _REPRESENTATION_KEYS)
        if unknown:
            errors.append(f"{where} carries unsupported field(s) {unknown}")
        identifier = representation.get("id")
        if not isinstance(identifier, str) or not _SLUG_RE.fullmatch(identifier):
            errors.append(f"{where} id must be a stable lowercase slug")
        elif identifier in representation_ids:
            errors.append(
                f"{where} duplicates representation id {identifier!r} — representation "
                "IDs are stable: reuse the existing declaration instead"
            )
        else:
            representation_ids.add(identifier)
        errors.extend(_aliases_errors(where, representation.get("aliases")))
        fields = representation.get("fields")
        if not isinstance(fields, list) or not fields:
            errors.append(
                f"{where} requires a non-empty ordered fields list of "
                "{{resource, column}} bindings"
            )
        else:
            errors.extend(_binding_errors(f"{where} fields", fields))
        if "scope" not in representation:
            errors.append(
                f"{where} requires its scope list (possibly empty — the required "
                "store/tenant/time scope of the representation)"
            )
        else:
            errors.extend(_binding_errors(f"{where} scope", representation["scope"]))
        description = representation.get("description")
        if description is not None and not isinstance(description, str):
            errors.append(f"{where} description must be a cited string")
    footnote_ids = {
        source.get("id")
        for source in meta.get("sources") or []
        if isinstance(source, dict) and source.get("id")
    }
    mappings = extension.get("mappings")
    if not isinstance(mappings, list):
        mappings = []
        errors.append(f"{rel}: mappings must be a list (possibly empty)")
    mapping_ids: set[str] = set()
    for position, mapping in enumerate(mappings):
        where = f"{rel}: mappings[{position}]"
        if not isinstance(mapping, dict):
            errors.append(f"{where} must be a mapping")
            continue
        unknown = sorted(set(mapping) - _MAPPING_KEYS)
        if unknown:
            errors.append(
                f"{where} carries unsupported field(s) {unknown} — approval, "
                "confirmation and measured counts/digests are system-owned and "
                "never authored in a mapping"
            )
        identifier = mapping.get("id")
        if not isinstance(identifier, str) or not _SLUG_RE.fullmatch(identifier):
            errors.append(f"{where} id must be a stable lowercase slug")
        elif identifier in mapping_ids:
            errors.append(
                f"{where} duplicates mapping id {identifier!r} — mapping IDs are "
                "stable: repeated findings update the same declaration"
            )
        else:
            mapping_ids.add(identifier)
        if mapping.get("family") not in MAPPING_FAMILIES:
            errors.append(
                f"{where} family must be one of {list(MAPPING_FAMILIES)}, "
                f"got {mapping.get('family')!r}"
            )
        for key in ("from", "to"):
            endpoint = mapping.get(key)
            # Endpoint TYPE is validated before any membership operation: an
            # unhashable endpoint (list/dict) must be a page-contract
            # diagnostic, never a TypeError inside the gate.
            if not isinstance(endpoint, str) or not endpoint:
                errors.append(
                    f"{where} {key} endpoint must be a representation id "
                    f"(a non-empty string), got {type(endpoint).__name__}"
                )
                continue
            if endpoint not in representation_ids:
                errors.append(
                    f"{where} {key} endpoint {endpoint!r} does not resolve to a "
                    "representation of this reference — endpoint representation IDs "
                    "resolve within the Reference; related concepts use ordinary "
                    "page links"
                )
        claim = mapping.get("claim")
        if claim not in MAPPING_CLAIMS:
            errors.append(f"{where} claim must be one of {list(MAPPING_CLAIMS)}, got {claim!r}")
        source_ids = mapping.get("source_ids")
        if not isinstance(source_ids, list) or not all(
            isinstance(source_id, str) and source_id for source_id in source_ids
        ):
            errors.append(f"{where} source_ids must be a list of footnote ids")
        else:
            unresolved = [s for s in source_ids if s not in footnote_ids]
            if unresolved:
                errors.append(
                    f"{where} source_ids {unresolved} resolves to no page footnote "
                    "— evidence dependencies cite the page's actual sources[]"
                )
            if claim == "asserted" and not source_ids:
                errors.append(
                    f"{where} is an asserted mapping without evidence: an asserted "
                    "mapping cites at least one source_id"
                )
        receipt_ids = mapping.get("receipt_ids")
        if receipt_ids is not None and (
            not isinstance(receipt_ids, list)
            or not all(isinstance(receipt, str) and receipt for receipt in receipt_ids)
        ):
            errors.append(
                f"{where} receipt_ids must be a list of evidence ids (verification "
                "is core-owned; allowlisting an id is not proof)"
            )
        # K3 (issue #43): the structured candidate is part of the declaration —
        # validated by the shared candidate schema; its family must agree with
        # the mapping's declared family.
        if "candidate" in mapping:
            try:
                normalized = validate_inspection_candidate(mapping["candidate"])
            except ValueError as exc:
                errors.append(f"{where} candidate: {exc}")
            else:
                if normalized["family"] != mapping.get("family"):
                    errors.append(
                        f"{where} declares family {mapping.get('family')!r} but its "
                        f"candidate measures the {normalized['family']!r} family"
                    )
    # K3 (issue #43): the core-attached verified receipt summaries. The key
    # is system-owned (the edit seam refuses an authored change); this shape
    # check keeps a legacy/ingested page honest — authenticity is verified by
    # the project-bound validation against the evidence records, never here.
    evidence = meta.get("ariadne_evidence")
    if evidence is not None:
        if not isinstance(evidence, dict):
            errors.append(f"{rel}: ariadne_evidence must be a mapping of mapping ids")
        else:
            for mapping_id, summaries in evidence.items():
                if not isinstance(summaries, list) or not summaries:
                    errors.append(
                        f"{rel}: ariadne_evidence[{mapping_id!r}] must be a non-empty "
                        "list of verified receipt summaries"
                    )
                    continue
                for position, summary in enumerate(summaries):
                    if not isinstance(summary, dict) or set(summary) != _EVIDENCE_SUMMARY_KEYS:
                        errors.append(
                            f"{rel}: ariadne_evidence[{mapping_id!r}][{position}] must "
                            "be exactly a core-attached verified receipt summary — "
                            "measured counts are never authored"
                        )
    return errors


def mapping_assertion_digest(mapping: dict) -> str:
    """The stable identity digest of ONE authored mapping declaration (K4,
    plan §2): the complete structured assertion — id, family, endpoints,
    claim, cited source_ids/receipt_ids and the structured candidate — in the
    canonical JSON form. Human confirmation binds THIS digest (a changed
    declaration is a different assertion and can never inherit a prior
    confirmation); observed results and measurement times live in the core's
    receipts, never in the declaration."""
    return _canonical_digest(mapping)


def _endpoint_correspondence(representation: object) -> dict | None:
    """One mapping endpoint representation's normalized correspondence — the
    K3 receipt-verification form: the ORDERED (resource, column) field list
    and the required scope bindings as a canonical set (K4 fix pass, finding
    2). None when the endpoint resolves to no representation (the page
    contract owns that error; the binding digest stays honest about the
    absence)."""
    if not isinstance(representation, dict):
        return None
    fields = [
        {"resource": binding.get("resource"), "column": binding.get("column")}
        for binding in representation.get("fields") or []
        if isinstance(binding, dict)
    ]
    scope = sorted(
        {
            (str(binding.get("resource")), str(binding.get("column")))
            for binding in representation.get("scope") or []
            if isinstance(binding, dict)
        }
    )
    return {
        "fields": fields,
        "scope": [{"resource": resource, "column": column} for resource, column in scope],
    }


def confirmation_binding_digest(meta: dict, mapping: dict) -> str:
    """The EFFECTIVE identity a human confirmation binds (K4 fix pass,
    finding 2, plan §2): the complete mapping declaration PLUS the normalized
    endpoint correspondence of both endpoint representations (ordered
    resource+column fields and required scope bindings — the same normalized
    correspondence K3 receipt verification enforces). Retargeting an endpoint
    representation changes THIS digest even when the mapping bytes stay
    identical, so a changed representation meaning can never inherit a prior
    confirmation."""
    extension = meta.get("ariadne") or {}
    representations = {
        representation.get("id"): representation
        for representation in extension.get("representations") or []
        if isinstance(representation, dict)
    }
    return _canonical_digest(
        {
            "mapping": mapping,
            "endpoints": {
                key: _endpoint_correspondence(representations.get(mapping.get(key)))
                for key in ("from", "to")
            },
        }
    )


def evidence_counterevidence(summary: dict) -> str | None:
    """The named counterevidence ONE verified receipt summary carries against
    its mapping's claim (K4 fix pass, finding 1, spec 0010 §§8–9): honest
    mismatches, an ambiguous pairing basis or an inconclusive outcome — None
    when the summary supports the claim. A hypothesis may carry it openly; an
    ASSERTED claim contradicted by its own cited evidence is unsupported."""
    if not isinstance(summary, dict):
        return None
    if isinstance(summary.get("mismatch_count"), int) and summary["mismatch_count"] > 0:
        return f"{summary['mismatch_count']} mismatching sampled value(s)"
    if summary.get("comparison_basis") == "ambiguous-pairing":
        return "an ambiguous pairing basis that cannot claim unique independent pairing"
    if summary.get("outcome") == "inconclusive":
        return "an inconclusive measurement (a budget or unavailable evidence prevented the check)"
    return None


def evidence_freshness(observed_at: object, max_age_hours: float | None) -> dict:
    """The explicit freshness state of ONE measured evidence view (K4 fix
    pass, finding 3, spec 0010 §§6/§8): ``as_of`` while the observation sits
    within the operator's evidence age budget, ``stale`` once ``observed_at``
    is past it — ``unknown`` without a budget or a parseable observation
    time. An unversioned measurement is an observation at a time (never
    permanent proof) and an absent freshness fact is never proof of currency.
    Read-only: freshness is computed, never written back."""
    if max_age_hours is None:
        return {"state": "unknown", "observed_at": observed_at, "max_age_hours": None}
    try:
        observed = datetime.fromisoformat(observed_at) if isinstance(observed_at, str) else None
        if observed is None:
            raise ValueError(observed_at)
        age = datetime.now(UTC) - observed
    except (ValueError, TypeError, OverflowError):
        return {
            "state": "unknown",
            "observed_at": observed_at,
            "max_age_hours": max_age_hours,
        }
    state = "stale" if age > timedelta(hours=max_age_hours) else "as_of"
    return {"state": state, "observed_at": observed_at, "max_age_hours": max_age_hours}


def _evidence_views(
    meta: dict, mapping_id: object, max_age_hours: float | None = None
) -> list[dict]:
    """The bounded AS-OF evidence view of one mapping's core-attached verified
    summaries (spec 0010 §6 "evidence freshness"): measurement time,
    sampled/full designation, outcome and mismatch count — an unversioned
    measurement is explicitly an observation AT a time, never permanent
    proof — plus each view's explicit freshness state against the operator's
    evidence age budget (K4 fix pass, finding 3: ``as_of`` within the budget,
    ``stale`` past it, ``unknown`` without a budget). Empty for a mapping with
    no verified receipts attached."""
    evidence = meta.get("ariadne_evidence")
    summaries = evidence.get(mapping_id) if isinstance(evidence, dict) else None
    views: list[dict] = []
    for summary in summaries or []:
        if not isinstance(summary, dict):
            continue
        views.append(
            {
                "id": summary.get("id"),
                "digest": summary.get("digest"),
                "observed_at": summary.get("observed_at"),
                "designation": summary.get("designation"),
                "outcome": summary.get("outcome"),
                "mismatch_count": summary.get("mismatch_count"),
                "freshness": evidence_freshness(summary.get("observed_at"), max_age_hours),
            }
        )
    return views


def confirmation_lookup(confirmations: list[dict] | None) -> dict[tuple[str, object], dict]:
    """The admitted confirmation records indexed for the resolver: page path
    (context-layer relative, the resolver's own citation form) + mapping id →
    the recorded human confirmation entry."""
    return {
        (cast(str, entry.get("page")), entry.get("mapping")): entry
        for entry in confirmations or []
        if isinstance(entry, dict)
    }


def _confirmation_matches(
    entry: dict | None, meta: dict, mapping: dict, evidence: list[dict]
) -> bool:
    """True when ONE recorded human confirmation still binds the mapping it
    confirmed (plan §2 "Admission and automatic capture"): the EXACT effective
    identity digest — the mapping declaration PLUS its endpoint
    representations' normalized field/scope correspondence (K4 fix pass,
    finding 2: a retargeted representation is a changed meaning and can never
    inherit confirmation) — AND the unchanged verified evidence dependencies
    (the receipts' integrity digests). A changed, stale or conflicting
    assertion cannot inherit confirmation — it reports unconfirmed."""
    if not isinstance(entry, dict):
        return False
    if entry.get("assertion_digest") != confirmation_binding_digest(meta, mapping):
        return False
    recorded = sorted(
        str(receipt.get("digest"))
        for receipt in entry.get("receipts") or []
        if isinstance(receipt, dict) and receipt.get("digest") is not None
    )
    current = sorted(str(view["digest"]) for view in evidence if view.get("digest") is not None)
    return recorded == current


def _mapping_views(
    meta: dict,
    representation_id: str | None,
    page: str,
    confirmations: dict[tuple[str, object], dict] | None = None,
    max_age_hours: float | None = None,
) -> list[dict]:
    """The mapping view(s) of one match: every mapping of the Reference for a
    concept-level match, the mappings touching ``representation_id`` for a
    representation match. Every mapping reports its claim classification and
    its confirmation status: ``confirmed`` ONLY when a recorded human
    confirmation of the exact reviewed assertion (unchanged effective
    identity digest — declaration plus endpoint correspondence — and
    unchanged verified evidence dependencies) exists — admission of the page
    alone confirms nothing, a hypothesis is never confirmable, and a page
    flag is never authority (spec 0010 §5, K4/issue #44). Expired evidence
    withholds stale confirmed GUIDANCE (K4 fix pass, finding 3, spec §§6/§8):
    a matching confirmation whose verified evidence aged past the operator
    budget surfaces as ``needs-revalidation`` with the human confirmation
    disclosed as history — never silently as current confirmed guidance. The
    bounded AS-OF evidence view (each with its explicit freshness state) and
    a mapping-level evidence-freshness summary ride along: unversioned
    measurements are observations at a time, never permanent proof."""
    views: list[dict] = []
    extension = meta.get("ariadne") or {}
    for mapping in extension.get("mappings") or []:
        if not isinstance(mapping, dict):
            continue
        if representation_id is not None and representation_id not in (
            mapping.get("from"),
            mapping.get("to"),
        ):
            continue
        evidence = _evidence_views(meta, mapping.get("id"), max_age_hours)
        confirmation = "unconfirmed"
        history: list[dict] | None = None
        entry = confirmations.get((page, mapping.get("id"))) if confirmations else None
        if _confirmation_matches(entry, meta, mapping, evidence):
            assert entry is not None
            if any(view["freshness"]["state"] == "stale" for view in evidence):
                # a stale mapping cannot supply confirmed guidance without
                # revalidation: the human confirmation is disclosed as history
                confirmation = "needs-revalidation"
                history = [{"by": entry.get("by"), "at": entry.get("at")}]
            else:
                confirmation = "confirmed"
        view = {
            "id": mapping.get("id"),
            "family": mapping.get("family"),
            "from": mapping.get("from"),
            "to": mapping.get("to"),
            "claim": mapping.get("claim"),
            "confirmation": confirmation,
            "source_ids": list(mapping.get("source_ids") or []),
            # allowlisted evidence IDs ride along verbatim — they are NOT
            # proof (receipt verification is core-owned; nothing is
            # fabricated here)
            "receipt_ids": list(mapping.get("receipt_ids") or []),
            # the bounded AS-OF verified evidence summaries the core
            # attached at finalization (K3), honestly reporting observation
            # time, scope designation, counterevidence and freshness state
            "evidence": evidence,
            "evidence_freshness": {
                "state": (
                    "stale"
                    if any(item["freshness"]["state"] == "stale" for item in evidence)
                    else "as_of"
                    if evidence and all(item["freshness"]["state"] == "as_of" for item in evidence)
                    else "unknown"
                )
            },
        }
        if history is not None:
            view["confirmation_history"] = history
        views.append(view)
    return views


def _assessment_now() -> datetime:
    """The internal freshness assessment clock (aware UTC now); tests patch
    this seam, it is not a public argument (spec 0011, issue #47)."""
    return datetime.now(UTC)


def _freshness_view(meta: dict, now: datetime) -> dict:
    """Interpret page expiry timestamps as instants and legacy dates as UTC days."""
    value = meta.get("stale_after")
    if isinstance(value, datetime):
        disclosed = value.isoformat()
        if value.utcoffset() is None:
            return {"stale_after": disclosed, "state": "unknown"}
        expiry = value
    elif isinstance(value, date):
        disclosed = value.isoformat()
        expiry = value
    elif isinstance(value, str):
        disclosed = value
        try:
            expiry = date.fromisoformat(value)
        except ValueError:
            try:
                expiry = datetime.fromisoformat(value)
            except ValueError:
                return {"stale_after": disclosed, "state": "unknown"}
            if expiry.utcoffset() is None:
                return {"stale_after": disclosed, "state": "unknown"}
    else:
        return {"stale_after": None, "state": "unknown"}

    if isinstance(expiry, datetime):
        state = "stale" if now >= expiry else "current"
    else:
        state = "stale" if now.date() > expiry else "current"
    return {"stale_after": disclosed, "state": state}


def _page_meta(text: str) -> dict:
    """Best-effort frontmatter of an arbitrary readable page for advisory
    assessment (spec 0011 §4): unparseable frontmatter yields no metadata —
    never a raise, never an invented claim."""
    try:
        meta = _load_frontmatter_meta(text)
    except yaml.YAMLError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _jsonable(value: object) -> object:
    """Keep disclosed evidence JSON-shaped: YAML-native date/datetime values
    become ISO strings (spec 0011 §3), other values pass through untouched —
    no response adapter has to learn a new type."""
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):  # datetime is a date subclass: both -> ISO
        return value.isoformat()
    return value


def _json_shaped(value: object) -> bool:
    """Whether an optional-evidence tree is fully representable in the existing
    JSON contract (bools/ints/floats/strings/nulls, string-keyed dicts, lists,
    dates). YAML-native objects outside it — sets, binaries, anchors to custom
    tags — make the evidence unsupported (issue #48 fix: the whole optional
    field then degrades to its absent form instead of reaching an adapter as a
    non-serializable object; pages carrying them serialized fine before the
    signals view existed)."""
    if value is None or isinstance(value, (str, int, float, date)):
        return True  # bool is an int subclass; datetime is a date subclass
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_shaped(item) for key, item in value.items())
    if isinstance(value, list):
        return all(_json_shaped(item) for item in value)
    return False


def _optional_evidence(value: object, kind: type, absent: object) -> object:
    """One optional-evidence field of the page view (issue #48 fix): disclosed
    only when the declared shape holds AND every value inside stays
    JSON-contract representable; otherwise the field degrades to its absent
    form (``None`` for generated/verified, ``[]`` for sources) — never a
    fabricated claim, never a non-serializable object."""
    if isinstance(value, kind) and _json_shaped(value):
        return _jsonable(value)
    return absent


def _lifecycle_status(meta: dict) -> str:
    """Conservative lifecycle disclosure (spec 0011 §4): a declared status is
    preserved verbatim (Ariadne draft/review states included); an absent
    status on a readable concept page uses OKF's ``stable`` default;
    malformed lifecycle metadata and pages without concept frontmatter
    (reserved navigation/history files) stay ``unknown``, never implicitly
    stable."""
    if "status" not in meta:
        return "stable" if meta else "unknown"
    declared = meta["status"]
    return declared if isinstance(declared, str) and declared else "unknown"


def _verification_tier(meta: dict) -> str:
    """Advisory document-verification tier (spec 0011 §4) — a claim declared
    in the page, never admission: no usable confirmation (including an empty
    list) is ``unverified``; non-human confirmations only are
    ``machine-confirmed``; a declared ``human:`` actor yields
    ``human-reviewed``."""
    verified = meta.get("verified")
    if not isinstance(verified, list):
        return "unverified"
    tier = "unverified"
    for entry in verified:
        by = entry.get("by") if isinstance(entry, dict) else None
        if not (isinstance(by, str) and by):
            continue
        if by.startswith("human:"):
            return "human-reviewed"
        tier = "machine-confirmed"
    return tier


def _page_view(rel: str, meta: dict, now: datetime) -> dict:
    """One assessed page's advisory view (spec 0011 §4): bundle-relative
    identity, lifecycle, freshness, document-verification tier and the
    AVAILABLE evidence. Optional evidence stays nullable/empty and is never
    fabricated; evidence the JSON contract cannot represent degrades to its
    field's absent form (issue #48 fix) rather than reaching an adapter as a
    non-serializable object; no field here establishes admission."""
    return {
        "path": rel,
        "status": _lifecycle_status(meta),
        "freshness": _freshness_view(meta, now),
        "verification_tier": _verification_tier(meta),
        "generated": _optional_evidence(meta.get("generated"), dict, None),
        "verified": _optional_evidence(meta.get("verified"), list, None),
        "sources": _optional_evidence(meta.get("sources"), list, []),
    }


def _context_signals(pages: list[dict]) -> dict:
    """The additive advisory envelope (spec 0011 §§4–5): the assessed pages
    plus one warning per concrete §5 problem — a supported expiry reached,
    an explicitly deprecated page. Absent/unknown optional expiry, generation
    or verification metadata never warns; a draft stays labeled through the
    existing draft/claim rules and does not warn either."""
    warnings: list[dict] = []
    for page in pages:
        if page["freshness"]["state"] == "stale":
            warnings.append({"code": "context_stale", "path": page["path"]})
        if page["status"] == "deprecated":
            warnings.append({"code": "context_deprecated", "path": page["path"]})
    return {"pages": pages, "warnings": warnings}


def _match_entry(
    rel: str,
    meta: dict,
    draft: bool,
    *,
    level: str,
    representation: str | None,
    aliases: list,
    fields: list,
    scope: list,
    mappings: list[dict],
    now: datetime,
    representations: list[dict] | None = None,
) -> dict:
    """One bounded match entry: the concept/representation identity, its exact
    bindings and required scope, the claim/confirmation status and the ACTUAL
    page/source citations (spec 0010 §6). No transform, SQL or join authority
    exists anywhere in the entry."""
    entry = {
        "page": rel,
        "draft": draft,
        "title": meta.get("title"),
        "description": meta.get("description"),
        "reference_role": (meta.get("ariadne") or {}).get("reference_role"),
        "level": level,
        "representation": representation,
        "aliases": list(aliases),
        "fields": [dict(binding) for binding in fields],
        "scope": [dict(binding) for binding in scope],
        "mappings": mappings,
        "sources": [dict(source) for source in meta.get("sources") or []],
        "freshness": _freshness_view(meta, now),
        "context_signals": _context_signals([_page_view(rel, meta, now)]),
    }
    if representations is not None:
        entry["representations"] = representations
    return entry


def _representation_entries(
    rel: str,
    meta: dict,
    draft: bool,
    representations: list[dict],
    query: dict,
    needle: str | None,
    now: datetime,
    confirmations: dict[tuple[str, object], dict] | None = None,
    max_age_hours: float | None = None,
) -> list[dict]:
    """The eligible representation-level matches of one page (term form:
    casefolded whole-alias equality; field form: exact binding identity)."""
    entries: list[dict] = []
    for representation in representations:
        aliases = list(representation.get("aliases") or [])
        if query["kind"] == "term":
            if needle not in [alias.casefold() for alias in aliases]:
                continue
        elif not any(
            binding == {"resource": query["resource"], "column": query["column"]}
            for binding in representation.get("fields") or []
        ):
            continue
        entries.append(
            _match_entry(
                rel,
                meta,
                draft,
                level="representation",
                representation=representation.get("id"),
                aliases=aliases,
                fields=list(representation.get("fields") or []),
                scope=list(representation.get("scope") or []),
                mappings=_mapping_views(
                    meta, representation.get("id"), rel, confirmations, max_age_hours
                ),
                now=now,
            )
        )
    return entries


def _page_matches(
    rel: str,
    meta: dict,
    draft: bool,
    query: dict,
    needle: str | None,
    now: datetime,
    confirmations: dict[tuple[str, object], dict] | None = None,
    max_age_hours: float | None = None,
) -> list[dict]:
    """The eligible matches of ONE structured Reference page, in stable order
    (concept before representations, representations in declared order).
    Natural-language matching is deterministic casefolded whole-alias/phrase
    equality — a substring is never a match; a field lookup compares the EXACT
    ``{resource, column}`` identity, never a case-folded one (spec 0010 §6)."""
    extension = meta["ariadne"]
    representations = [
        representation
        for representation in extension.get("representations") or []
        if isinstance(representation, dict)
    ]
    if query["kind"] == "field":
        return _representation_entries(
            rel, meta, draft, representations, query, needle, now, confirmations, max_age_hours
        )
    entries: list[dict] = []
    page_aliases = list(meta.get("aliases") or [])
    if needle in [alias.casefold() for alias in page_aliases]:
        entries.append(
            _match_entry(
                rel,
                meta,
                draft,
                level="concept",
                representation=None,
                aliases=page_aliases,
                fields=[],
                scope=[],
                mappings=_mapping_views(meta, None, rel, confirmations, max_age_hours),
                now=now,
                representations=[
                    {
                        "id": representation.get("id"),
                        "aliases": list(representation.get("aliases") or []),
                        "fields": [dict(binding) for binding in representation.get("fields") or []],
                        "scope": [dict(binding) for binding in representation.get("scope") or []],
                    }
                    for representation in representations
                ],
            )
        )
    entries.extend(
        _representation_entries(
            rel, meta, draft, representations, query, needle, now, confirmations, max_age_hours
        )
    )
    return entries


def _entry_bytes(entry: dict) -> int:
    """Serialized size of one match entry in UTF-8 bytes (the response's own
    wire measure — a part's budget is counted in these bytes, plan §2)."""
    return len(json.dumps(entry, ensure_ascii=False).encode("utf-8"))


def _disclosed_entry(entry: dict, budget: int) -> dict:
    """One bounded disclosure of a match whose serialized form alone exceeds a
    whole part's byte budget: every over-cap string/list is cut with an inline
    marker and named in the entry's explicit ``elided`` list (identity fields
    — page/level/representation/role — are short slugs and survive intact).
    Should the capped form STILL not fit (pathological nesting), only the
    identity fields remain with a marker naming the elision — an oversized
    entry is disclosed, never silently dropped nor overflowed."""
    elided: list[str] = []

    def cap(node: object, path: str) -> object:
        if isinstance(node, str):
            if len(node) > _RESOLVE_TEXT_CAP:
                omitted = len(node) - _RESOLVE_TEXT_CAP
                elided.append(f"{path} ({omitted} characters elided)")
                return f"{node[:_RESOLVE_TEXT_CAP]}… [elided {omitted} characters]"
            return node
        if isinstance(node, list):
            if len(node) > _RESOLVE_LIST_CAP:
                omitted = len(node) - _RESOLVE_LIST_CAP
                elided.append(f"{path} ({omitted} of {len(node)} items elided)")
                node = node[:_RESOLVE_LIST_CAP]
            return [cap(item, f"{path}[{index}]") for index, item in enumerate(node)]
        if isinstance(node, dict):
            return {
                key: cap(value, f"{path}.{key}" if path else key) for key, value in node.items()
            }
        return node

    bounded = {key: cap(value, key) for key, value in entry.items()}
    markers = elided[:_RESOLVE_LIST_CAP]
    if len(elided) > _RESOLVE_LIST_CAP:
        markers.append(f"elided ({len(elided) - _RESOLVE_LIST_CAP} more elisions)")
    bounded["elided"] = markers
    if _entry_bytes(bounded) > budget:  # pathological nesting: identity only
        return {
            key: bounded[key]  # already capped: this form is bounded by construction
            for key in ("page", "draft", "level", "representation", "reference_role")
            if key in bounded
        } | {
            "elided": [
                "entry: too large for one response part — everything but the "
                "identity was elided; read the cited page for the full match"
            ]
        }
    return bounded


def _resolve_response_parts(matches: list[dict], *, limit: int, max_bytes: int) -> list[list[dict]]:
    """Deterministic response parts honoring BOTH bounds: at most ``limit``
    matches per part AND at most ``max_bytes`` serialized bytes per part (plan
    §2's 64 KiB ceiling). A part stops before exceeding the byte budget; an
    entry too large for a whole part enters as its bounded disclosure."""
    budget = max_bytes - _RESOLVE_ENVELOPE_RESERVE
    parts: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for entry in matches:
        size = _entry_bytes(entry)
        if size > budget:  # cannot fit a whole part alone: disclose it bounded
            entry = _disclosed_entry(entry, budget)
            size = _entry_bytes(entry)
        if current and used + size + 1 > budget:  # +1: the list comma
            parts.append(current)
            current, used = [], 0
        current.append(entry)
        used += size + 1
        if len(current) >= limit:
            parts.append(current)
            current, used = [], 0
    if current or not parts:
        parts.append(current)
    return parts


def resolve_term(
    roots: list[tuple[Path, bool]],
    request: str | dict,
    *,
    part: int = 1,
    limit: int = RESOLVE_TERM_LIMIT,
    confirmations: list[dict] | None = None,
    evidence_max_age_hours: float | None = None,
) -> dict:
    """The shared read-only terminology resolver (spec 0010 §6, plan §2):
    bounded matching concept/representation identities, exact field bindings,
    required scope, ambiguity, claim/confirmation/freshness status and actual
    page/source citations over the given context roots — Query passes its
    pinned admitted context dir, Authoring its explicitly selected candidate
    revision.

    Matching is deterministic: casefolded whole-alias/phrase equality for
    natural language (never substring fuzzy inference) and exact qualified
    field identity for bindings (never case-folded). All eligible matches are
    counted before the bound, so ambiguity is never declared from a truncated
    result; at most ``limit`` matches return per part in stable
    page/representation order with explicit truncation and part continuation
    (the existing bounded-read convention), every part staying under the
    shared 64 KiB serialized-response ceiling (plan §2): a part stops before
    exceeding it, and an entry too large for a whole part is disclosed with
    bounded fields and an explicit elision marker — never silently dropped
    nor overflowed. No match yields an empty match list; a malformed supported
    Reference or request fails explicitly. The resolver applies no transform,
    rewrites no SQL and authorizes no join.

    ``confirmations`` (K4, issue #44) are the ADMITTED human confirmation
    records of the served revision's admission evidence — a mapping reports
    ``confirmed`` only while the recorded selection still binds its exact
    effective identity (declaration plus endpoint correspondence) and
    unchanged verified evidence. ``evidence_max_age_hours`` (K4 fix pass,
    finding 3) is the operator's evidence age budget (the same
    ``inspection.receipt_max_age_hours`` config): each evidence view reports
    its explicit ``as_of``/``stale`` freshness state against it, and a
    matching confirmation over EXPIRED evidence is withheld as current
    guidance (``needs-revalidation``, the human confirmation disclosed as
    history). Without a budget the freshness state stays honestly
    ``unknown``. The candidate side passes no confirmations, so every mapping
    stays unconfirmed there."""
    if isinstance(request, str):
        term = request.strip()
        if not term:
            raise ValueError(
                "a resolve_term request must be a non-empty term string or a "
                "{resource, column} object"
            )
        query: dict = {"kind": "term", "term": term}
        needle = term.casefold()
    elif isinstance(request, dict):
        if set(request) != {"resource", "column"}:
            raise ValueError(
                "a field resolve_term request is exactly {resource, column} (a term "
                "request is a plain string)"
            )
        column = request["column"]
        if not isinstance(column, str) or not column:
            raise ValueError("a field resolve_term request needs a non-empty exact column")
        try:
            kind, _parts = parse_resource(request["resource"])
        except ValueError as exc:
            raise ValueError(
                f"a field resolve_term request names a canonical resource: {exc}"
            ) from None
        if kind != "table":
            raise ValueError("a field resolve_term request names a table resource")
        query = {"kind": "field", "resource": request["resource"], "column": column}
        needle = None
    else:
        raise ValueError(
            "a resolve_term request is a term string or a {resource, column} object, "
            f"got {type(request).__name__}"
        )
    if isinstance(part, bool) or not isinstance(part, int) or part < 1:
        raise ValueError("the resolve_term part must be a positive integer (part 1 of N)")
    matches: list[dict] = []
    now = _assessment_now()
    admitted = confirmation_lookup(confirmations)
    for root, draft in roots:
        references = Path(root) / "references"
        if not references.is_dir():
            continue
        for path in sorted(references.rglob("*.md")):
            if path.name in ("index.md", "log.md"):
                continue  # system bookkeeping, never a Reference
            rel = path.relative_to(Path(root)).as_posix()
            try:
                meta = _load_frontmatter_meta(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise ValueError(f"malformed reference page {rel}: {exc}") from None
            if meta.get("type") != "reference" or "ariadne" not in meta:
                continue  # legacy/non-reference pages stay readable, unstructured
            errors = _reference_extension_errors(rel, meta)
            if errors:
                raise ValueError(
                    f"malformed reference page — {'; '.join(errors)} — the resolver "
                    "resolves only well-formed supported declarations"
                )
            matches.extend(
                _page_matches(
                    rel, meta, draft, query, needle, now, admitted or None, evidence_max_age_hours
                )
            )
    total = len(matches)
    response_parts = _resolve_response_parts(matches, limit=limit, max_bytes=RESOLVE_TERM_MAX_BYTES)
    parts = len(response_parts)
    exhausted = part > parts
    returned = [] if exhausted else response_parts[part - 1]
    return {
        "request": query,
        "matches": returned,
        "total_matches": total,
        "ambiguous": total > 1,
        "truncated": total > len(returned),
        "part": part,
        "parts": parts,
        "complete": part >= parts and not exhausted,
        "exhausted": exhausted,
        "limit": limit,
    }


def build_dataset_page(
    *, collection: dict, tables: list[dict], existing_text: str | None
) -> tuple[str, dict]:
    """Generate one Dataset Overview page (``type: dataset``): the physical
    collection's canonical resource and the links to EXACTLY the tables this
    refresh documents — never every approved source (spec 0010 §3/§4).
    Deterministic derivation, no timestamps. Returns ``(page text, flags)``
    with the linked-table additions/removals versus the existing overview."""
    resource = collection["resource"]
    try:
        existing_meta = _load_frontmatter_meta(existing_text) if existing_text else {}
    except yaml.YAMLError:
        existing_meta = {}
    existing_ariadne = existing_meta.get("ariadne") if isinstance(existing_meta, dict) else None
    old_tables = existing_ariadne.get("tables") if isinstance(existing_ariadne, dict) else None
    old_tables = old_tables if isinstance(old_tables, list) else []
    linked = [table["resource"] for table in tables]
    flags = {
        "added": sorted(set(linked) - set(old_tables)),
        "removed": sorted(set(old_tables) - set(linked)),
    }
    source, schema = collection["source"], collection["schema"]
    citation = {
        "id": f"catalog-{source}-{schema}",
        "resource": resource,
        "title": f"catalog of {source}.{schema}",
    }
    meta: dict = {
        "type": "dataset",
        "title": f"{source}.{schema}",
        "description": (
            f"Dataset Overview of the physical collection {source}.{schema} of "
            f"source {source} — {len(tables)} documented table"
            + ("s" if len(tables) != 1 else "")
            + "."
        ),
        "tags": ["dataset"],
        "sources": _ensure_citation(
            existing_meta.get("sources") if isinstance(existing_meta, dict) else None,
            citation,
        ),
        "resource": resource,
        "ariadne": {"tables": linked},
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    links = [
        f"- [{table['table']}]({table['link']}) — `{table['table']}` "
        f"({table['column_count']} columns)"
        for table in tables
    ]
    body = (
        f"# {source}.{schema}\n\n"
        f"Dataset Overview of the physical collection `{source}.{schema}` (source "
        f"`{source}`). The tables listed below are the ones this project "
        "documents — an unrelated approved source is not silently asserted to "
        "have been documented.\n\n"
        f"## Tables\n\n" + "\n".join(links) + "\n"
    )
    return f"---\n{front}---\n\n{body}", flags


# -------------------------------------------- deterministic promotion bookkeeping

# Section heading for a folder's index.md (SPEC §8 example form: "# Metric").
_SECTION_TITLES = {
    "datasets": "Dataset",
    "tables": "Table",
    "references": "Reference",
    "joins": "Join",
    "policies": "Policy",
    "metrics": "Metric",
    "computations": "Computation",
    "skills": "Skill",
}
# One-line blurb used when an index links a subdirectory (directories carry no
# frontmatter to take a description from).
_FOLDER_BLURBS = {
    "datasets": "Physical collections: Dataset Overviews linking their tables.",
    "tables": "Physical tables: row meaning, schema, join hints.",
    "references": "Cross-table reference notes.",
    "joins": "Join catalog: keys, cardinality evidence, grain safety.",
    "policies": "Human-owned business rules the metrics cite.",
    "metrics": "Governed metrics and the rules that make them right.",
    "computations": "Sanctioned computations: SQL, runtime, attester.",
    "skills": "Operational guides: run, promote, query.",
}


def _content_key(text: str) -> str:
    """Canonical form for change detection: everything EXCEPT verified/status.
    Equal keys mean the promotion bookkeeping would be byte-identical — no-op."""
    meta, body = _load(text)
    if meta is None:
        return body
    meta = {k: v for k, v in meta.items() if k not in ("verified", "status")}
    return yaml.safe_dump(meta, sort_keys=True) + body


def _promoted_text(text: str, by: str, at: str, prior_verified: list | None = None) -> str:
    """The served form of a staged OKF page: status flipped, verified appended.
    ``prior_verified`` (the served page's existing list) is preserved, so a
    re-promoted update APPENDS to the verification history."""
    meta, body = _load(text)
    if meta is None:  # callers route non-OKF files to the raw merge
        return text
    meta["status"] = "stable"
    verified = list(prior_verified or [])
    verified.append({"by": by, "at": at})
    meta["verified"] = verified
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n{body}"


def _index_for(directory: Path, served_context: Path) -> str:
    """One index.md body: subdirectory links, then page links with the target's
    frontmatter description (SPEC §8 progressive disclosure). Pages carrying a
    canonical ``resource`` (spec 0010 §4: ``resource`` authoritative, filenames
    navigational) append it as a trailing marker — the regenerated index is
    the reader's resource->page resolution source (owner-approved fix4)."""
    if directory == served_context:
        heading = "Context Layer"
    else:
        heading = _SECTION_TITLES.get(directory.name, directory.name.capitalize())
    lines = [f"# {heading}", ""]
    for sub in sorted(p for p in directory.iterdir() if p.is_dir()):
        if not any(sub.rglob("*.md")):
            continue
        rel = sub.relative_to(served_context)
        blurb = _FOLDER_BLURBS.get(sub.name, "")
        lines.append(f"* [{sub.name.capitalize()}]({rel.as_posix()}/) - {blurb}".rstrip(" -"))
    for page in sorted(p for p in directory.glob("*.md") if p.name != "index.md"):
        try:
            meta, _ = _load(page.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            meta = None  # unparseable frontmatter: fall back to the file stem
        title = str((meta or {}).get("title") or page.stem.replace("_", " "))
        desc = str((meta or {}).get("description") or "")
        line = f"* [{title}]({page.name}) - {desc}".rstrip(" -")
        resource = str((meta or {}).get("resource") or "")
        if resource:
            line += f" - resource: `{resource}`"
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def _has_pages(directory: Path) -> bool:
    """True when the directory or any descendant holds .md pages."""
    return any(directory.rglob("*.md"))


def _regenerate_indexes(served_context: Path) -> None:
    """Regenerate index.md at the bundle root and in every folder that holds
    pages (directly or below — the root links its section subdirs), from the
    CURRENT served contents, so merge-surviving pages are indexed too."""
    if not served_context.is_dir():
        return
    dirs = [served_context, *sorted(p for p in served_context.rglob("*") if p.is_dir())]
    for directory in dirs:
        if _has_pages(directory):
            text = _index_for(directory, served_context)
            (directory / "index.md").write_text(text, encoding="utf-8")


def _append_log(served_context: Path, changes: list, by: str, date: str) -> None:
    """Append Creation/Update entries under today's heading (newest-first).
    ``changes`` are the promoter's Change records (``action``/``rel`` duck-typed:
    importing the promotion workflow for the annotation would invert the
    shared-module dependency)."""
    if not changes:
        return
    path = served_context / "log.md"
    if path.is_file():
        lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    else:
        lines = ["# Directory Update Log"]
    heading = f"## {date}"
    entries = [
        f"**{'Update' if c.action == 'updated' else 'Creation'}**: {c.rel} — verified {by}"
        for c in changes
    ]
    if heading in lines:
        pos = lines.index(heading) + 1
        while pos < len(lines) and lines[pos].startswith("**"):
            pos += 1
    else:
        pos = 1 if lines and lines[0].startswith("# ") else 0
        lines[pos:pos] = ["", heading]
        pos += 2
    lines[pos:pos] = entries
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------ advisory supplied source-quality evidence (spec 0013, #53)

# The optional authored ``ariadne_quality`` profile of a physical-table page
# (spec 0013 §§2–3, plan 0013 §2 "Authored metadata"): one bounded,
# closed-shape declaration of SUPPLIED reports — a domain owner's/upstream
# producer's reported claims with citations, never a core-produced
# measurement or a new registry. The shared per-type gate validates it before
# human admission; the shared :func:`data_signals` consumer reads it. Every
# bound below is an approved public-contract limit (plan §2), not an
# adjustable mechanical budget.
ARIADNE_QUALITY_VERSION = 1
QUALITY_MAX_REPORTS = 8
QUALITY_MAX_CHECKS = 8
QUALITY_MAX_SOURCE_IDS = 8
QUALITY_MAX_ID_CHARS = 128  # id/version/field/actor strings
QUALITY_MAX_TEXT_CHARS = 1024  # description/criterion/population/meaning/provenance
QUALITY_MAX_CADENCE_CHARS = 256
QUALITY_MAX_UNITS_CHARS = 64  # units/timezone
QUALITY_PROFILE_MAX_BYTES = 8 * 1024

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
_QUALITY_OPTIONAL_REPORT_KEYS = frozenset(
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
_QUALITY_VERSION_KEYS = frozenset({"kind", "value"})
_QUALITY_CHECK_KEYS = frozenset(
    {"id", "kind", "outcome", "criterion", "tested_population", "tested_period"}
)
_QUALITY_WATERMARK_KEYS = frozenset(
    {"kind", "value", "field", "meaning", "units", "timezone", "observed_at"}
)
QUALITY_SCOPE_KINDS = ("asset", "subset")
QUALITY_VERSION_KINDS = ("snapshot", "version")
QUALITY_CHECK_OUTCOMES = ("pass", "fail", "unknown")
QUALITY_WATERMARK_KINDS = ("event_time", "ingestion_time", "snapshot_as_of", "other")


def _aware_instant(value: object, where: str) -> tuple[datetime | None, str | None]:
    """``(instant, error)`` of one required structured timestamp (spec 0013
    §3): an aware ``datetime`` (YAML-native) or an ISO-8601 string carrying an
    explicit offset. Naive datetimes, plain dates and non-temporal values are
    rejected — new structured temporal evidence never silently inherits
    UTC."""
    if isinstance(value, bool) or not isinstance(value, (datetime, str)):
        return None, (
            f"{where} must be an aware instant (an ISO-8601 string or YAML datetime "
            "with explicit offset) — a naive datetime, plain date or non-temporal "
            "value is rejected, never silently assigned UTC"
        )
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None, f"{where} must be a parseable ISO-8601 instant, got {value!r}"
    if not isinstance(value, datetime) or value.utcoffset() is None:
        return None, (
            f"{where} carries no timezone/offset — a naive timestamp is rejected, "
            "never silently assigned UTC"
        )
    return value, None


def _quality_text_error(value: object, where: str, cap: int) -> str | None:
    """The error string of one supplied bounded text field, or None."""
    if not isinstance(value, str) or not value:
        return f"{where} must be supplied non-empty text"
    if len(value) > cap:
        return f"{where} exceeds its {cap}-character bound ({len(value)})"
    return None


def _quality_period_errors(period: object, where: str) -> list[str]:
    """A period is ``None`` for explicitly non-time-bounded evidence,
    otherwise ``{field, start, end}`` with an exact physical-field identity,
    aware instants and ``start < end`` (interpreted ``[start, end)``)."""
    if period is None:
        return []
    if not isinstance(period, dict):
        return [f"{where} must be a period mapping or null (explicitly non-time-bounded)"]
    errors: list[str] = []
    unknown = sorted(set(period) - _QUALITY_PERIOD_KEYS)
    if unknown:
        errors.append(f"{where} carries unsupported field(s) {unknown}")
    error = _quality_text_error(period.get("field"), f"{where} field", QUALITY_MAX_ID_CHARS)
    if error:
        errors.append(error)
    start, start_error = _aware_instant(period.get("start"), f"{where} start")
    if start_error:
        errors.append(start_error)
    end, end_error = _aware_instant(period.get("end"), f"{where} end")
    if end_error:
        errors.append(end_error)
    if start is not None and end is not None and not start < end:
        errors.append(f"{where} must satisfy start < end (interpreted [start, end))")
    return errors


def _finite_scalar(value: object) -> bool:
    """A finite JSON scalar (string, number or boolean — never null,
    non-finite floats or containers)."""
    if value is None or isinstance(value, (dict, list)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return isinstance(value, (str, int, float, bool))


def _normalize_quality_value(value: object):
    """The JSON-normalized form of supplied profile content: aware datetimes
    (and plain dates, should a legacy value slip through) become ISO-8601
    strings; containers are rebuilt in order."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _normalize_quality_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_quality_value(item) for item in value]
    return value


def _quality_profile_errors(rel: str, meta: dict) -> list[str]:
    """The optional ``ariadne_quality`` profile of one table page (spec 0013
    §2, plan 0013 §2): version 1, at most :data:`QUALITY_MAX_REPORTS`
    closed-shape reports whose ``asset`` equals the containing page's exact
    core ``resource`` binding, citations resolving to the page's actual
    ``sources`` entries, aware structured instants, checks stating their
    tested population/criterion and outcome, watermarks declaring
    kind/value/meaning, and the normalized profile within its byte ceiling.
    Unsupported versions, unexpected keys (there is no sql/script/command or
    other executable payload field anywhere), malformed values, duplicate
    IDs and mismatched asset/citation identity fail this AUTHORING gate
    before human admission. A table page WITHOUT the key is the plain legacy
    form and reports no errors; validation establishes shape and binding,
    never real quality or business truth (admission authorizes the exact
    artifact, not the report's current truth)."""
    if "ariadne_quality" not in meta:
        return []  # the profile is optional: ordinary pages keep their behavior
    profile = meta["ariadne_quality"]
    if profile is None:
        return [
            f"{rel}: ariadne_quality is null — null is not the (absent) legacy "
            "form; declare the versioned profile or remove the key"
        ]
    if not isinstance(profile, dict):
        return [f"{rel}: ariadne_quality must be a mapping, got {type(profile).__name__}"]
    version = profile.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != ARIADNE_QUALITY_VERSION
    ):
        return [
            f"{rel}: ariadne_quality version must be the integer "
            f"{ARIADNE_QUALITY_VERSION}, got {version!r}"
        ]
    errors: list[str] = []
    unknown = sorted(set(profile) - _QUALITY_ROOT_KEYS)
    if unknown:
        errors.append(f"{rel}: ariadne_quality carries unsupported field(s) {unknown}")
    binding = meta.get("resource")
    if not isinstance(binding, str) or not binding:
        errors.append(
            f"{rel}: ariadne_quality requires the page's canonical resource binding "
            "— a page without an established table binding cannot carry a quality "
            "report (an asset is never guessed from a display name)"
        )
    citation_resources = {
        source["id"]: source.get("resource")
        for source in meta.get("sources") or []
        # a citation id must be a string: a later-edited non-string id (e.g.
        # ``id: [owner-report]``) simply resolves to nothing — malformed, but
        # never an unhashable-key crash out of the advisory reader
        if isinstance(source, dict) and isinstance(source.get("id"), str) and source["id"]
    }
    reports = profile.get("reports")
    if not isinstance(reports, list):
        return errors + [f"{rel}: ariadne_quality reports must be a list"]
    if len(reports) > QUALITY_MAX_REPORTS:
        errors.append(
            f"{rel}: ariadne_quality carries {len(reports)} reports — at most "
            f"{QUALITY_MAX_REPORTS} are declared per page (plan 0013 §2)"
        )
    report_ids: set[str] = set()
    for position, report in enumerate(reports):
        where = f"{rel}: ariadne_quality.reports[{position}]"
        if not isinstance(report, dict):
            errors.append(f"{where} must be a mapping")
            continue
        unknown = sorted(set(report) - _QUALITY_REPORT_KEYS)
        if unknown:
            errors.append(
                f"{where} carries unsupported field(s) {unknown} — the profile is a "
                "closed declaration with no sql/script/command or other executable "
                "payload field; descriptions are inert text"
            )
        missing = sorted(_QUALITY_REPORT_KEYS - _QUALITY_OPTIONAL_REPORT_KEYS - set(report))
        if missing:
            errors.append(f"{where} requires field(s) {missing}")
        identifier = report.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{where} id must be a nonempty stable string")
        elif len(identifier) > QUALITY_MAX_ID_CHARS:
            errors.append(f"{where} id exceeds its {QUALITY_MAX_ID_CHARS}-character bound")
        elif identifier in report_ids:
            errors.append(
                f"{where} duplicates report id {identifier!r} — report IDs are "
                "stable: repeated findings update the same declaration"
            )
        else:
            report_ids.add(identifier)
        if isinstance(binding, str) and binding and report.get("asset") != binding:
            errors.append(
                f"{where} asset must equal the containing page's canonical resource "
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
                f"{where} source_ids must be a nonempty list of at most "
                f"{QUALITY_MAX_SOURCE_IDS} citation ids"
            )
        else:
            unresolved = [s for s in source_ids if s not in citation_resources]
            if unresolved:
                errors.append(
                    f"{where} source_ids {unresolved} resolves to no page sources[] "
                    "citation — supplied evidence cites the page's actual sources"
                )
            resourceless = [s for s in source_ids if not citation_resources.get(s)]
            if resourceless:
                errors.append(
                    f"{where} source_ids {resourceless} cite a source without a "
                    "resource — a citation is an identity, and needs one"
                )
        scope = report.get("scope")
        if not isinstance(scope, dict):
            errors.append(f"{where} scope must be {{kind, description, population, period}}")
        else:
            unknown = sorted(set(scope) - _QUALITY_SCOPE_KEYS)
            if unknown:
                errors.append(f"{where} scope carries unsupported field(s) {unknown}")
            if scope.get("kind") not in QUALITY_SCOPE_KINDS:
                errors.append(
                    f"{where} scope kind must be one of {list(QUALITY_SCOPE_KINDS)}, "
                    f"got {scope.get('kind')!r}"
                )
            for key in ("description", "population"):
                error = _quality_text_error(
                    scope.get(key), f"{where} scope {key}", QUALITY_MAX_TEXT_CHARS
                )
                if error:
                    errors.append(error)
            missing = sorted(_QUALITY_SCOPE_KEYS - set(scope))
            if missing:
                errors.append(
                    f"{where} scope requires field(s) {missing} — period is null only "
                    "when non-time-bounded evidence is EXPLICITLY declared; "
                    "omission is not a declaration"
                )
            errors.extend(_quality_period_errors(scope.get("period"), f"{where} scope period"))
        reported_at, reported_error = _aware_instant(
            report.get("reported_at"), f"{where} reported_at"
        )
        if reported_error:
            errors.append(reported_error)
        if "observed_at" in report:
            _observed, observed_error = _aware_instant(
                report.get("observed_at"), f"{where} observed_at"
            )
            if observed_error:
                errors.append(observed_error)
        if "valid_until" in report:
            valid_until, valid_error = _aware_instant(
                report.get("valid_until"), f"{where} valid_until"
            )
            if valid_error:
                errors.append(valid_error)
            elif reported_at is not None and valid_until is not None and valid_until < reported_at:
                errors.append(f"{where} valid_until must not precede reported_at")
        if "source_version" in report:
            source_version = report.get("source_version")
            if not isinstance(source_version, dict):
                errors.append(f"{where} source_version must be {{kind, value}}")
            else:
                unknown = sorted(set(source_version) - _QUALITY_VERSION_KEYS)
                if unknown:
                    errors.append(f"{where} source_version carries unsupported field(s) {unknown}")
                if source_version.get("kind") not in QUALITY_VERSION_KINDS:
                    errors.append(
                        f"{where} source_version kind must be one of "
                        f"{list(QUALITY_VERSION_KINDS)}, got "
                        f"{source_version.get('kind')!r}"
                    )
                error = _quality_text_error(
                    source_version.get("value"),
                    f"{where} source_version value",
                    QUALITY_MAX_ID_CHARS,
                )
                if error:
                    errors.append(error)
        for key, cap in (
            ("provenance", QUALITY_MAX_TEXT_CHARS),
            ("reported_by", QUALITY_MAX_ID_CHARS),
            ("cadence", QUALITY_MAX_CADENCE_CHARS),
        ):
            if key in report:
                error = _quality_text_error(report.get(key), f"{where} {key}", cap)
                if error:
                    errors.append(error)
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"{where} requires a nonempty checks list")
        elif len(checks) > QUALITY_MAX_CHECKS:
            errors.append(
                f"{where} carries {len(checks)} checks — at most "
                f"{QUALITY_MAX_CHECKS} per report (plan 0013 §2)"
            )
        else:
            check_ids: set[str] = set()
            for index, check in enumerate(checks):
                spot = f"{where} checks[{index}]"
                if not isinstance(check, dict):
                    errors.append(f"{spot} must be a mapping")
                    continue
                unknown = sorted(set(check) - _QUALITY_CHECK_KEYS)
                if unknown:
                    errors.append(f"{spot} carries unsupported field(s) {unknown}")
                missing = sorted(_QUALITY_CHECK_KEYS - set(check))
                if missing:
                    errors.append(f"{spot} requires field(s) {missing}")
                check_id = check.get("id")
                if not isinstance(check_id, str) or not check_id:
                    errors.append(f"{spot} id must be a nonempty stable string")
                elif len(check_id) > QUALITY_MAX_ID_CHARS:
                    errors.append(f"{spot} id exceeds its {QUALITY_MAX_ID_CHARS}-character bound")
                elif check_id in check_ids:
                    errors.append(f"{spot} duplicates check id {check_id!r} within the report")
                else:
                    check_ids.add(check_id)
                error = _quality_text_error(check.get("kind"), f"{spot} kind", QUALITY_MAX_ID_CHARS)
                if error:
                    errors.append(error)
                if check.get("outcome") not in QUALITY_CHECK_OUTCOMES:
                    errors.append(
                        f"{spot} outcome must be exactly one of "
                        f"{list(QUALITY_CHECK_OUTCOMES)}, got {check.get('outcome')!r}"
                    )
                for key in ("criterion", "tested_population"):
                    error = _quality_text_error(
                        check.get(key), f"{spot} {key}", QUALITY_MAX_TEXT_CHARS
                    )
                    if error:
                        errors.append(error)
                errors.extend(
                    _quality_period_errors(check.get("tested_period"), f"{spot} tested_period")
                )
        if "watermark" in report:
            watermark = report.get("watermark")
            if not isinstance(watermark, dict):
                errors.append(
                    f"{where} watermark must be "
                    "{kind, value, field, meaning, units, timezone, observed_at}"
                )
            else:
                unknown = sorted(set(watermark) - _QUALITY_WATERMARK_KEYS)
                if unknown:
                    errors.append(f"{where} watermark carries unsupported field(s) {unknown}")
                kind = watermark.get("kind")
                if kind not in QUALITY_WATERMARK_KINDS:
                    errors.append(
                        f"{where} watermark kind must be one of "
                        f"{list(QUALITY_WATERMARK_KINDS)}, got {kind!r}"
                    )
                value = watermark.get("value")
                if kind in ("event_time", "ingestion_time", "snapshot_as_of"):
                    _instant, value_error = _aware_instant(value, f"{where} watermark value")
                    if value_error:
                        errors.append(
                            f"{where} watermark value: a temporal watermark carries an "
                            "aware instant as its value"
                        )
                elif not _finite_scalar(value):
                    errors.append(
                        f"{where} watermark value must be a finite scalar with its stated meaning"
                    )
                for key, cap in (
                    ("field", QUALITY_MAX_ID_CHARS),
                    ("meaning", QUALITY_MAX_TEXT_CHARS),
                    ("units", QUALITY_MAX_UNITS_CHARS),
                    ("timezone", QUALITY_MAX_UNITS_CHARS),
                ):
                    error = _quality_text_error(watermark.get(key), f"{where} watermark {key}", cap)
                    if error:
                        errors.append(error)
                _observed, observed_error = _aware_instant(
                    watermark.get("observed_at"), f"{where} watermark observed_at"
                )
                if observed_error:
                    errors.append(observed_error)
    if not errors:
        payload = _normalize_quality_value(profile)
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if size > QUALITY_PROFILE_MAX_BYTES:
            errors.append(
                f"{rel}: the normalized ariadne_quality profile is {size} UTF-8 "
                f"bytes — at most {QUALITY_PROFILE_MAX_BYTES} are declared per page "
                "(plan 0013 §2)"
            )
    return errors


# The shared advisory ``data_signals`` view (spec 0013 §4, plan 0013 §2
# "data_signals view"). Approved public-contract bounds, not adjustable
# mechanical budgets: finite metric/asset/page/report counts, the bounded
# per-page frontmatter read and the total view byte ceiling.
DATA_SIGNALS_VERSION = 1
DATA_SIGNALS_MAX_METRICS = 64
DATA_SIGNALS_MAX_ASSETS = 64
DATA_SIGNALS_MAX_PAGES = 32
DATA_SIGNALS_MAX_REPORTS = 128
DATA_SIGNALS_MAX_BYTES = 64 * 1024
_PAGE_FRONTMATTER_READ_BYTES = 64 * 1024


def _read_page_meta_bounded(path: Path) -> dict | None:
    """Frontmatter meta of one OKF page from a BOUNDED read — at most 64 KiB
    of the file, never the body or external citations. ``None`` when the page
    is unreadable or carries no parseable frontmatter: unknown evidence,
    never a query failure."""
    try:
        with path.open("rb") as handle:
            prefix = handle.read(_PAGE_FRONTMATTER_READ_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    match = _FRONTMATTER_RE.match(prefix)
    if not match:
        return None
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) else None


def _coerce_validated_instant(value: object) -> datetime:
    """The instant of a VALIDATED profile timestamp (aware datetime or aware
    ISO string — the authoring gate rejected everything else)."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# One enriched index line: the page link plus the trailing core-appended
# resource marker ``resource: `ariadne://…` ``. The label may itself contain
# ``]`` (authored titles are preserved verbatim), so the link ends at the
# FIRST ``](`` — first-link-target semantics. Greedy prefix matching keeps
# the LAST marker on a line — the one the generator appends — ahead of any
# identical text authored into a description.
_INDEX_RESOURCE_RE = re.compile(r"^\s*\*\s+\[(?:.*?)\]\(([^)\s]+)\).*\bresource:\s*`([^`]+)`")


def _table_index_bindings(context_dir: Path) -> dict[str, str]:
    """The resource->page resolution map of the system-generated
    ``tables/index.md`` (spec 0010 §4: ``resource`` authoritative, page
    filenames navigational; the owner-approved fix4 design makes the
    regenerated index the reader's resolution source). ONE bounded metadata
    read — at most 64 KiB — explicitly NOT charged against the 32-page
    evidence budget. A missing or unreadable index, or one written by an
    older core without resource markers, resolves nothing: every canonical
    citation then degrades to a ``binding_unknown`` disclosure, never to a
    scan. ponytail: duplicate-resource lines (an authoring anomaly — pages
    bound to resources keep protected single resources) resolve to the
    first line, matching the index's sorted page order."""
    try:
        with (context_dir / "tables" / "index.md").open("rb") as handle:
            text = handle.read(_PAGE_FRONTMATTER_READ_BYTES).decode("utf-8", "replace")
    except OSError:
        return {}
    bindings: dict[str, str] = {}
    for line in text.splitlines():
        match = _INDEX_RESOURCE_RE.match(line)
        if match and match.group(2) not in bindings:
            name = match.group(1)
            if name == Path(name).name and name.endswith(".md"):  # one served page file
                bindings[match.group(2)] = f"tables/{name}"
    return bindings


def _direct_table_citations(
    context_dir: Path, metric_names: list[str]
) -> tuple[set[str], set[str]]:
    """The DIRECTLY-cited table identities recorded on the CONSUMING metric
    pages (``metrics/<name>.md`` frontmatter ``sources[]``): cited table page
    paths (``tables/<plain-name>.md``) and cited canonical table resources
    (``ariadne://table/…``). This is the consuming side of spec 0013 §4's
    contract — a table page citing its own source is a self-citation, never a
    citation by the metric — and it is resolved BEFORE any ``tables/*.md``
    read, so only directly-cited pages ever enter evidence consideration. A
    missing or unparseable metric page, a ``sources[]`` that is not a list,
    bare display names, ``policies/...`` refs, non-plain page paths
    (subdirectories, traversal — the citation names one served page file) and
    malformed resources cite nothing: unknown coverage, never a guess."""
    root = context_dir.resolve()
    cited_pages: set[str] = set()
    cited_resources: set[str] = set()
    for name in metric_names:
        page = root / "metrics" / f"{name}.md"
        try:
            if not page.resolve().is_relative_to(root):
                continue  # containment: a crafted name is just another missing page
        except OSError:
            continue
        meta = _read_page_meta_bounded(page)
        sources = meta.get("sources") if meta else None
        if not isinstance(sources, list):
            continue
        for source in sources:
            resource = source.get("resource") if isinstance(source, dict) else None
            if not (isinstance(resource, str) and resource):
                continue
            if resource.startswith("tables/"):
                name_part = resource[len("tables/") :]
                if name_part == Path(name_part).name and name_part.endswith(".md"):
                    cited_pages.add(f"tables/{name_part}")
                continue
            try:
                kind, _parts = parse_resource(resource)
            except ValueError:
                continue
            if kind == "table":
                cited_resources.add(resource)
    return cited_pages, cited_resources


def _period_disjoint(period: dict, requested: tuple[datetime | None, datetime | None]) -> bool:
    """True when the report's ``[start, end)`` evidence period and the
    requested query period PROVABLY do not overlap (spec 0013 §3/§4, issue
    #54): each comparison needs the pair of bounds that establishes it — an
    unbounded side establishes nothing and leaves correspondence unknown.
    Overlap proves nothing either: applicability stays a per-axis question
    and only a mechanical contradiction makes a report inapplicable."""
    evidence_start = _coerce_validated_instant(period["start"])
    evidence_end = _coerce_validated_instant(period["end"])
    requested_start, requested_end = requested
    if requested_start is not None and evidence_end <= requested_start:
        return True
    if requested_end is not None and requested_end <= evidence_start:
        return True
    return False


def _report_view(
    report: dict,
    now: datetime,
    requested_period: tuple[datetime | None, datetime | None] | None,
    period_fields: set[str] | frozenset[str] | None,
) -> dict:
    """The normalized advisory view of one VALIDATED report: every supplied
    field (instants as ISO-8601 strings) plus ``evidence_kind: supplied`` and
    the honest ``age``/``applicability`` axes with closed ``limitations``
    codes. Age is expiry of the SUPPLIED validity only — an unexpired report
    never establishes live health, and a report OR observation time later
    than the assessment instant leaves age unknown (plan §2). Applicability
    is mechanical correspondence, never a guess: a KNOWN period contradiction
    — the report's own evidence period provably disjoint from the requested
    query period, and only when the report's declared period FIELD is one the
    request's range actually predicates (issue #54 W1 fix3) — makes the
    report inapplicable to the requested use; a subset scope without
    established correspondence and a source version the runtime cannot
    cross-check (absent, or supplied with no runtime dataset-version fact to
    match against — an admission digest is not a dataset version) are
    explicit unknowns; ``as_of`` means available unexpired as-of evidence,
    nothing more."""
    limitations: list[str] = []
    applicability = "unknown"
    scope = report.get("scope") or {}
    if scope.get("kind") == "subset":
        limitations.append("scope_unknown")  # subset text alone proves no correspondence
    if (
        requested_period is not None
        and period_fields  # the range's own field(s): correspondence is provable
        and isinstance(scope.get("period"), dict)
        and scope["period"].get("field") in period_fields
        and _period_disjoint(scope["period"], requested_period)
    ):
        # mechanically established contradiction (spec §3/§4, issue #54 W1
        # fix3): the report's own declared evidence period — on the very
        # field the request's range predicates — provably does not overlap
        # the requested query period, so the report cannot apply to this
        # request: never a matching pass and never a failed/passing check of
        # the data
        limitations.append("scope_mismatch")
        applicability = "inapplicable"
    # Version correspondence needs mechanically established matching from
    # existing source/query facts (spec §3): this runtime holds no
    # dataset-version fact, so a supplied source_version is an upstream CLAIM
    # — unknown correspondence whether absent or merely supplied, never a
    # matching assessment.
    limitations.append("source_version_unknown")
    reported_at = _coerce_validated_instant(report["reported_at"])
    observed_at = report.get("observed_at")
    age = "unknown"
    if reported_at > now or (
        observed_at is not None and _coerce_validated_instant(observed_at) > now
    ):
        # plan §2 (W1 fix4): a report/observation later than the assessment
        # instant has unknown age — the supplied timestamps stay visible,
        # never an as-of disclosure
        limitations.append("report_time_in_future")
    elif "valid_until" not in report:
        limitations.append("validity_not_supplied")  # as-of timestamps stay visible
    else:
        age = "expired" if now >= _coerce_validated_instant(report["valid_until"]) else "as_of"
    view: dict = {key: _normalize_quality_value(item) for key, item in report.items()}
    view["evidence_kind"] = "supplied"
    view["age"] = age
    view["applicability"] = applicability
    view["limitations"] = limitations
    return view


def data_signals(
    context_dir: str | Path,
    dependencies: dict[str, list[str | None]],
    *,
    requested_period: tuple[datetime | None, datetime | None] | None = None,
    period_fields: set[str] | frozenset[str] | None = None,
) -> dict:
    """The shared read-only advisory quality-evidence view of spec 0013 §4
    (plan 0013 §2): for every metric's DIRECT table dependencies — already
    resolved to canonical table resources by the caller against the built
    execution catalog — the directly cited physical-table pages under the
    served ``tables/`` section are read (bounded: at most 64 KiB of
    frontmatter per page, at most 32 pages physically read), and each page's
    optional validated ``ariadne_quality`` reports are disclosed with their
    age, applicability, limitations, checks and watermarks.

    A page is DIRECTLY CITED only when the CONSUMING metric page
    (``metrics/<name>.md``) records the citation in its own ``sources[]`` —
    a ``tables/...`` page path or a canonical table resource (spec §4's
    "admitted table citations"). Every citation is resolved to an EXACT
    page path BEFORE any table-page read: a path citation names its page
    directly, and a canonical-resource citation resolves through the
    regenerated ``tables/index.md`` — the reader's resource->page resolution
    source (spec 0010 §4: ``resource`` is authoritative, filenames
    navigational; existing pages bound to resources keep their names) — via
    ONE bounded index read that is explicitly NOT charged against the
    page-read budget, with each resolved page's OWN frontmatter — its
    declared ``resource`` — confirming the resolution as it is read.
    Resolution is INDEX-ONLY: an index without resource markers (a
    pre-existing served context), a missing/unreadable index or a citation
    the index does not resolve degrades to a ``binding_unknown`` disclosure
    for that citation — the query still succeeds, nothing is scanned. A
    table page citing its own source is a self-citation and establishes
    nothing. The resolved pages are the ONLY pages ever read: unrelated
    pages are never read, never sorted against and never consume the
    page-read budget, and each resolved page's declared binding is
    cross-checked against the catalog-resolved direct dependencies
    (same-named tables in distinct sources stay distinct assets). Citing
    more pages than the budget reads is the one truncation scenario: a
    cited page beyond it is disclosed under ``omitted``/``truncated``, never
    silently assessed.

    Coverage is honesty about EVIDENCE, not about data: ``complete`` means
    every direct dependency is identified and covered by applicable parseable
    report evidence (an expired or reported-failed report still covers an
    identified dependency); ``partial`` means identified coverage is
    incomplete; ``unknown`` means correspondence/evidence is unavailable. A
    missing binding, a missing table citation, an absent optional profile or
    a later-unreadable declared profile is explicit unknown coverage — the
    last additionally warns ``data_evidence_unavailable``; a wholly absent
    optional profile never warns merely for its absence. No pass outcome,
    watermark recency or admission is ever presented as live health.

    The optional ``requested_period`` (issue #54) is the runtime's own
    requested query period as aware instants (either side may be ``None`` —
    unbounded): it NEVER widens evidence, it only lets a mechanically
    established period CONTRADICTION — the report's own declared evidence
    period provably disjoint from the requested period — disclose that report
    as ``inapplicable`` with the ``scope_mismatch`` limitation. The
    contradiction additionally requires ``period_fields`` (W1 fix3): the
    runtime-supplied set of fields the request's range actually predicates,
    so a period declared on any other field stays unknown correspondence.
    Overlap establishes nothing: applicability stays unknown on every
    unproven axis.

    The read is PURE (no restamp, no write, no fetch, no probe — retries
    return another assessment of the same pinned bytes) and never fails a
    numerically valid query: bounded counts and the total view size elide
    trailing entries deterministically, count them under ``omitted`` and mark
    ``truncated`` (elided evidence never leaves a complete/warning-free
    claim). No recursive lineage traversal, directory-wide report discovery
    or external read happens here — only the directly cited table pages of
    the named dependencies."""
    now = _assessment_now()
    metric_names = list(dependencies)[:DATA_SIGNALS_MAX_METRICS]
    omitted_metrics = len(dependencies) - len(metric_names)
    asset_order: list[str] = []
    for name in metric_names:
        for resource in dependencies[name]:
            if isinstance(resource, str) and resource and resource not in asset_order:
                asset_order.append(resource)
    omitted_assets = max(0, len(asset_order) - DATA_SIGNALS_MAX_ASSETS)
    asset_order = asset_order[:DATA_SIGNALS_MAX_ASSETS]
    wanted = set(asset_order)
    # The directly-cited set resolved from the CONSUMING side before any
    # table-page read (spec 0013 §4, issue #53's "exactly bound directly
    # cited table"): the metric pages' recorded table citations name the
    # pages (``tables/...`` paths) or canonical resources that may supply
    # evidence. A table page citing its own source is a self-citation and
    # establishes nothing; an uncited page — same resource or not — never
    # enters evidence consideration.
    cited_pages, cited_resources = _direct_table_citations(Path(context_dir), metric_names)
    # The citation resolution, built BEFORE any table-page read (spec 0010
    # §4 + the owner-approved fix4 design): a path citation names its page
    # directly, and a canonical-resource citation resolves through the
    # regenerated ``tables/index.md`` — ONE bounded metadata read, explicitly
    # NOT charged against the 32-page evidence budget — to the exact page
    # the index binds that resource to, each resolved page's OWN frontmatter
    # (its declared ``resource``) confirming the resolution as it is read.
    # Resolution is INDEX-ONLY: no ``tables/*.md`` walk, no generated-name
    # convention, no scan loop — unrelated pages are never candidates, never
    # read and never charged to the page-read budget. An index without
    # resource markers (a pre-existing served context), a missing/unreadable
    # index or a citation the index does not resolve degrades to a
    # ``binding_unknown`` disclosure — the query still succeeds, nothing is
    # scanned.
    cited_wanted = cited_resources & wanted
    resolved: dict[str, str] = {}
    if cited_wanted:
        for resource, page in _table_index_bindings(Path(context_dir)).items():
            if resource in cited_wanted:
                resolved[resource] = page
    candidates: set[str] = set(cited_pages) | set(resolved.values())
    bindings: dict[str, tuple[str, dict]] = {}
    omitted_pages = 0
    pages_read = 0
    read_pages: set[str] = set()
    tables_dir = Path(context_dir) / "tables"
    if tables_dir.is_dir():
        for rel in sorted(candidates):
            if pages_read >= DATA_SIGNALS_MAX_PAGES:
                # direct citations the read budget never reached — disclosed
                # as omitted: citing more pages than the budget reads is the
                # one truncation scenario, never silently assessed
                omitted_pages = len(candidates) - pages_read
                break  # the budget bounds pages physically read (plan §2)
            pages_read += 1
            read_pages.add(rel)
            meta = _read_page_meta_bounded(tables_dir / Path(rel).name)
            if not meta:
                continue
            resource = meta.get("resource")
            # the identity cross-check of the cited pages against the runtime
            # catalog: a directly-cited page still binds only when its declared
            # resource is one of the catalog-resolved direct dependencies
            if not (isinstance(resource, str) and resource in wanted):
                continue
            if (rel in cited_pages or resource in cited_resources) and resource not in bindings:
                bindings[resource] = (rel, meta)  # the first cited page in sorted order binds
    # honest degradation (owner-approved fix4 design): a canonical citation
    # the index did not resolve at all, or whose resolved page was read but
    # did not confirm the binding, is disclosed binding_unknown — never a
    # guess and never a scan (a page the budget never reached stays covered
    # by the omitted/truncated disclosure alone)
    unresolved: list[str] = []
    for resource in sorted(cited_wanted):
        if resource in bindings:
            continue
        page = resolved.get(resource)
        if page is None or page in read_pages:
            unresolved.append(resource)
    state: dict[str, dict] = {}
    omitted_reports = 0
    reports_emitted = 0
    for resource in asset_order:
        page, meta = bindings.get(resource, (None, None))
        entry = {"resource": resource, "page": page, "coverage": "unknown", "reports": []}
        info: dict = {"entry": entry, "elided": False, "invalid": False}
        state[resource] = info
        profile = meta.get("ariadne_quality") if meta else None
        if profile is not None:
            try:
                invalid = bool(_quality_profile_errors(page or resource, meta or {}))
                if not invalid:
                    applicable = False
                    for report in profile.get("reports") or []:
                        if reports_emitted >= DATA_SIGNALS_MAX_REPORTS:
                            omitted_reports += 1
                            info["elided"] = True
                            continue
                        reports_emitted += 1
                        view = _report_view(report, now, requested_period, period_fields)
                        entry["reports"].append(view)
                        if view["applicability"] == "applicable":
                            applicable = True
                    entry["coverage"] = (
                        "partial" if info["elided"] else ("complete" if applicable else "unknown")
                    )
            except Exception:
                # Advisory interpretation NEVER fails the query (spec §5): a
                # later-edited unreadable declaration (e.g. a citation with a
                # non-string id) degrades to unknown evidence with the
                # unavailability warning — the computed result is already safe.
                invalid = True
                entry["reports"] = []
                entry["coverage"] = "unknown"
                info["elided"] = False
            if invalid:
                info["invalid"] = True  # later-unreadable declared evidence
    while True:  # deterministic convergence to the 64 KiB ceiling (W1 fix2)
        metrics: list[dict] = []
        warnings: list[dict] = []
        for name in metric_names:
            contributions: list[str] = []
            asset_refs: list[str | None] = []
            for resource in dependencies[name]:
                if resource is None:
                    asset_refs.append(None)
                    contributions.append("unknown")
                elif resource not in state:  # identified but omitted by the asset bound
                    asset_refs.append(None)
                    contributions.append("partial")
                else:
                    asset_refs.append(resource)
                    contributions.append(state[resource]["entry"]["coverage"])
            if contributions and all(coverage == "complete" for coverage in contributions):
                coverage = "complete"
            elif any(coverage in ("complete", "partial") for coverage in contributions):
                coverage = "partial"
            else:
                coverage = "unknown"
            metrics.append({"name": name, "assets": asset_refs, "coverage": coverage})
            if coverage == "partial":
                warnings.append(
                    {
                        "code": "data_coverage_partial",
                        "metric": name,
                        "asset": None,
                        "page": None,
                        "report": None,
                    }
                )
        truncated = bool(omitted_metrics or omitted_assets or omitted_pages or omitted_reports)
        for resource in asset_order:
            if resource not in state:  # elided by the byte ceiling (W1 fix2)
                continue
            info = state[resource]
            entry = info["entry"]
            if info["invalid"]:
                warnings.append(
                    {
                        "code": "data_evidence_unavailable",
                        "metric": None,
                        "asset": resource,
                        "page": entry["page"],
                        "report": None,
                    }
                )
                continue
            for report_view_entry in entry["reports"]:
                base = {
                    "metric": None,
                    "asset": resource,
                    "page": entry["page"],
                    "report": report_view_entry.get("id"),
                }
                if report_view_entry["applicability"] == "inapplicable":
                    warnings.append({**base, "code": "data_report_inapplicable"})
                    continue  # disclosed as inapplicable, never as the requested data's check
                if report_view_entry["applicability"] == "unknown":
                    warnings.append({**base, "code": "data_applicability_unknown"})
                if report_view_entry["age"] == "expired":
                    warnings.append({**base, "code": "data_report_expired"})
                if any(
                    check.get("outcome") == "fail"
                    for check in report_view_entry.get("checks") or []
                ):
                    warnings.append({**base, "code": "data_report_failed"})
        for resource in unresolved:  # citations the index never resolved to a
            # confirmed page binding — the honest-degradation disclosure of the
            # owner-approved fix4 design (spec 0013 §4: unresolved dependency is
            # unknown coverage, never a guess, never a scan)
            warnings.append(
                {
                    "code": "data_binding_unknown",
                    "metric": None,
                    "asset": resource,
                    "page": None,
                    "report": None,
                }
            )
        if truncated and not any(
            warning["code"] == "data_signals_truncated" for warning in warnings
        ):
            warnings.append(
                {
                    "code": "data_signals_truncated",
                    "metric": None,
                    "asset": None,
                    "page": None,
                    "report": None,
                }
            )
        view = {
            "version": DATA_SIGNALS_VERSION,
            "assessed_at": now.isoformat(),
            "metrics": metrics,
            "assets": [state[resource]["entry"] for resource in asset_order if resource in state],
            "warnings": warnings,
            "truncated": truncated,
            "omitted": {
                "metrics": omitted_metrics,
                "assets": omitted_assets,
                "pages": omitted_pages,
                "reports": omitted_reports,
            },
        }
        size = len(json.dumps(view, ensure_ascii=False).encode("utf-8"))
        if size <= DATA_SIGNALS_MAX_BYTES:
            return view
        # deterministic convergence to the ceiling (W1 fix2): elide ONE
        # trailing disclosure unit per pass — the last remaining report first,
        # then trailing metric entries, then trailing asset entries — and
        # re-measure. Every elision increments an ``omitted`` counter, so
        # ``truncated`` can never be false while a bound prevented disclosure,
        # and the loop provably terminates (each pass removes one unit; the
        # final empty view is the terminal return — report-less over-budget
        # views can no longer escape the ceiling unflagged).
        for info in reversed(list(state.values())):
            if info["entry"]["reports"]:
                info["entry"]["reports"].pop()
                omitted_reports += 1
                info["elided"] = True
                info["entry"]["coverage"] = "partial"
                break
        else:
            if metric_names:
                metric_names.pop()  # the trailing metric entry, elided
                omitted_metrics += 1
            elif state:
                del state[next(reversed(state))]  # the trailing asset entry, elided
                omitted_assets += 1
            else:
                return view  # nothing left to elide: the terminal valid view

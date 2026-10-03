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
import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
            hits.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "score": score,  # relative ranking value, not a frequency contract
                    "draft": draft,  # staged proposals stay distinguishable
                    "content": text,  # full OKF page: the rules are the payload
                    "excerpt": excerpt,
                    "line_start": line_start,
                    "line_end": line_end,
                    "section": section,
                }
            )
    hits.sort(key=lambda hit: (-hit["score"], hit["path"]))
    return hits[:limit]


# --------------------------------------------------------- citation attachment


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
    nothing outside the context dir is ever read."""
    try:
        root = context_dir.resolve()
        page = root / "metrics" / f"{name}.md"
        if not page.resolve().is_relative_to(root):
            raise ValueError("metric page path escapes the context root")
        text = page.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(text)
        meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
        refs = (
            source.get("resource") if isinstance(source, dict) else source
            for source in meta.get("sources") or []
        )
        policies_root = root / "policies"
        policies = []
        for ref in refs:
            if not (isinstance(ref, str) and ref.startswith("policies/")):
                continue
            body = (root / ref).resolve()
            if not body.is_relative_to(policies_root):
                raise ValueError(f"policy reference escapes policies/: {ref}")
            policies.append(body.read_text(encoding="utf-8"))
        context = {"metric_page": text, "policies": policies}
        if _computation_attestation(root, name) == "pending":
            # ADR-0013/spec acceptance 5, and ONLY the pending case (the new
            # harness-led bundles): governed:true means Promoted, never an
            # independent numeric attestation — say so on every such answer.
            # Existing attested bundles keep the established context shape.
            context["attestation"] = "pending"
            context["governed_note"] = (
                "governed: true means Promoted, not independently value-attested"
            )
        return context
    except Exception:  # missing page, unresolvable ref, traversal, unparsable frontmatter
        return {"metric_page": None, "policies": []}


def _computation_attestation(root: Path, name: str) -> str | None:
    """The computation page's attestation caveat for ``name``: ``"pending"``
    when the served computation declares it (ADR-0007 scoped extension),
    the cited attester when one is present, None when there is no such
    page. Read problems are just another missing caveat — never a failure."""
    try:
        page = root / "computations" / f"{name}.md"
        if not page.resolve().is_relative_to(root) or not page.is_file():
            return None
        match = _FRONTMATTER_RE.match(page.read_text(encoding="utf-8"))
        meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
        if meta.get("attestation") == "pending":
            return "pending"
        return str(meta["attester"]) if meta.get("attester") else None
    except Exception:
        return None


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
        meta = _load_frontmatter_meta(page.read_text(encoding="utf-8"))
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
                dialects = (block.get("dialects") if isinstance(block, dict) else None) or [
                    {}
                ]
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


def _observation_facts(*, resource: str, profile: dict) -> dict:
    """The core-generated observation facts WITHOUT the timestamp (the part
    compared for timestamp reuse): scope, counts, measured candidate keys and
    citation identity — measurements, never declared constraints."""
    columns = {
        name: {"null_count": stats["null_count"], "distinct_count": stats["distinct_count"]}
        for name, stats in (profile.get("columns") or {}).items()
    }
    return {
        "scope": "sampled" if profile.get("sampled") else "full",
        "row_count": profile.get("row_count"),
        "candidate_keys": sorted(profile.get("primary_key_candidates") or []),
        "columns": columns,
        "citation": resource,
    }


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
    authored_chunks = [
        (heading, lines) for heading, lines in chunks if heading not in _CORE_SECTIONS
    ]
    has_authored = any(
        line.strip() for _heading, lines in authored_chunks for line in lines
    )
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
    core = [
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
        was = next(
            (c["type"] for c in flags.get("_old_schema", []) if c["column"] == column), None
        )
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
    facts = _observation_facts(resource=resource, profile=profile)
    reuse_timestamp = (
        old_observed_at is not None
        and old_schema is not None
        and old_schema == columns
        and {k: v for k, v in old_observations.items() if k != "observed_at"} == facts
    )
    observed_at = old_observed_at if reuse_timestamp else now
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
                    "candidate prefix_lookup must be exactly "
                    "{asset, key_fields, prefix_field}"
                )
            prefix_lookup, lookup_bindings = _lookup_asset(
                prefix_lookup, "candidate prefix_lookup"
            )
            if len(lookup_bindings["key_fields"]) > len(left):
                raise ValueError(
                    "candidate prefix_lookup key_fields outnumber the left "
                    "components they identify"
                )
            binding_count += lookup_bindings["count"]
            assets.add(prefix_lookup["asset"])
    else:  # lookup
        lookup = candidate.get("lookup")
        if not isinstance(lookup, dict) or set(lookup) != _LOOKUP_KEYS:
            raise ValueError(
                "candidate lookup must be exactly {asset, key_fields, value_fields}"
            )
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
        errors.append(
            f"{rel}: reference_role must be one of {list(REFERENCE_ROLES)}, got {role!r}"
        )
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
            errors.append(
                f"{where} claim must be one of {list(MAPPING_CLAIMS)}, got {claim!r}"
            )
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


def _mapping_views(extension: dict, representation_id: str | None) -> list[dict]:
    """The mapping view(s) of one match: every mapping of the Reference for a
    concept-level match, the mappings touching ``representation_id`` for a
    representation match. Every mapping reports its claim classification with
    ``confirmation: unconfirmed`` — until K4's exact-assertion human
    confirmation exists, no mapping (hypothesis or asserted) is confirmed, and
    an admitted page confirms nothing by itself (spec 0010 §5)."""
    views: list[dict] = []
    for mapping in extension.get("mappings") or []:
        if not isinstance(mapping, dict):
            continue
        if representation_id is not None and representation_id not in (
            mapping.get("from"),
            mapping.get("to"),
        ):
            continue
        views.append(
            {
                "id": mapping.get("id"),
                "family": mapping.get("family"),
                "from": mapping.get("from"),
                "to": mapping.get("to"),
                "claim": mapping.get("claim"),
                "confirmation": "unconfirmed",
                "source_ids": list(mapping.get("source_ids") or []),
                # allowlisted evidence IDs ride along verbatim — they are NOT
                # proof (receipt verification is K3; nothing is fabricated here)
                "receipt_ids": list(mapping.get("receipt_ids") or []),
            }
        )
    return views


def _freshness_view(meta: dict) -> dict:
    """The honest evidence-freshness view of one page: its declared
    ``stale_after`` date (the ADR-0007 lifecycle field) compared to today, or
    ``unknown`` when the page declares nothing — an absent freshness fact is
    never proof of currency (spec 0010 §4)."""
    value = meta.get("stale_after")
    if not isinstance(value, str):
        return {"stale_after": None, "state": "unknown"}
    try:
        stale_after = date.fromisoformat(value)
    except ValueError:
        return {"stale_after": value, "state": "unknown"}
    state = "stale" if datetime.now(UTC).date() > stale_after else "current"
    return {"stale_after": value, "state": state}


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
        "freshness": _freshness_view(meta),
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
                mappings=_mapping_views(meta["ariadne"], representation.get("id")),
            )
        )
    return entries


def _page_matches(rel: str, meta: dict, draft: bool, query: dict, needle: str | None) -> list[dict]:
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
        return _representation_entries(rel, meta, draft, representations, query, needle)
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
                mappings=_mapping_views(extension, None),
                representations=[
                    {
                        "id": representation.get("id"),
                        "aliases": list(representation.get("aliases") or []),
                        "fields": [
                            dict(binding) for binding in representation.get("fields") or []
                        ],
                        "scope": [
                            dict(binding) for binding in representation.get("scope") or []
                        ],
                    }
                    for representation in representations
                ],
            )
        )
    entries.extend(_representation_entries(rel, meta, draft, representations, query, needle))
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
                key: cap(value, f"{path}.{key}" if path else key)
                for key, value in node.items()
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


def _resolve_response_parts(
    matches: list[dict], *, limit: int, max_bytes: int
) -> list[list[dict]]:
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
    rewrites no SQL and authorizes no join."""
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
            matches.extend(_page_matches(rel, meta, draft, query, needle))
    total = len(matches)
    response_parts = _resolve_response_parts(
        matches, limit=limit, max_bytes=RESOLVE_TERM_MAX_BYTES
    )
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
    old_tables = (
        existing_ariadne.get("tables") if isinstance(existing_ariadne, dict) else None
    )
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
    frontmatter description (SPEC §8 progressive disclosure)."""
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
        lines.append(f"* [{title}]({page.name}) - {desc}".rstrip(" -"))
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

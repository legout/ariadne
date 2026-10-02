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
  (:func:`_promoted_text`, :func:`_regenerate_indexes`, :func:`_append_log`).

Ranking, full Policy bodies, draft labels and attestation semantics are the
historical ones. This module guides interpretation and never computes metrics
(spec §2); it imports no workflow module.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

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


def _load(text: str) -> tuple[dict | None, str]:
    """Split a file into (frontmatter meta or None, body)."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None, text
    return (yaml.safe_load(match.group(1)) or {}), match.group(2)


# ------------------------------------------------------- the OKF page contract

# ADR-0007 bundle contract: every content type must be present, keyed by its
# context_layer section and the frontmatter ``type`` its pages must carry.
_BUNDLE_TYPES = {
    "tables": "table",
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
        grain = meta.get("grain")
        if (
            not isinstance(grain, dict)
            or not grain.get("primary_key")
            or not grain.get("cardinality_enforcement")
        ):
            errors.append(
                f"{rel}: table page requires a grain block with primary_key and "
                "cardinality_enforcement"
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
    return errors


# System-generated promotion bookkeeping (index trees, log): never authored
# content pages, so the per-type bundle gate does not check them (issue #36:
# the Git candidate's finalize pass generates the index trees BEFORE
# validation; legacy staging still has none at gate time — no behavior change
# for the legacy route).
_BOOKKEEPING_NAMES = frozenset({"index.md", "log.md"})


def _bundle_errors(staging: Path) -> list[str]:
    """The hard ADR-0007 bundle contract gate (spec §5: no silent success): all six
    content types present under context_layer/, per-type required frontmatter, and
    every metric page citing at least one governing policy. System-generated
    bookkeeping (index.md/log.md) is not an authored page and is skipped."""
    context = staging / "context_layer"
    errors: list[str] = []
    for section, expected_type in _BUNDLE_TYPES.items():
        section_dir = context / section
        pages = (
            sorted(p for p in section_dir.glob("*.md") if p.name not in _BOOKKEEPING_NAMES)
            if section_dir.is_dir()
            else []
        )
        if not pages:
            errors.append(
                f"authored bundle is incomplete: no pages under context_layer/{section}/ "
                "(ADR-0007 requires all six content types: tables, references/joins, "
                "policies, metrics, computations, skills)"
            )
            continue
        for page in pages:
            errors.extend(_page_contract_errors(staging, page, expected_type))
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
) -> None:
    """Post-validation deterministic passes (ADR-0007): enrich metric pages from the
    staged models, generate the computation pages, stamp lifecycle frontmatter.
    Harness-led submission (spec 2026-09-24-0005) passes its own provenance and
    ``attester=None`` (pending attestation, ADR-0013)."""
    now = datetime.now(UTC)
    models, _all_parsed = _model_index(staging)  # post-validation: always parsed
    _enrich_metric_pages(staging, models)
    _write_computations(staging, models, attester=attester)
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


# -------------------------------------------- deterministic promotion bookkeeping

# Section heading for a folder's index.md (SPEC §8 example form: "# Metric").
_SECTION_TITLES = {
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

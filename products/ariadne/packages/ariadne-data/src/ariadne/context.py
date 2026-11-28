"""Shared Context Layer (OKF) technical-facts module (spec 2026-10-02-0009 §2
"Module ownership", ADR-0016, C6 cutover per spec0035 §6).

Core's deterministic technical evidence lives here: the shared technical
machinery consumed by the native Context path (:mod:`ariadne.lumio_context`),
the advisory quality view and the authoring workflows. This module has no
authoring, serving or admission workflow (the classic bundle search,
envelope context, per-type OKF page gates, classic finalization, index
generation and classic page builders were removed with their retired routes;
computation-page reads for historical revision-1 native releases remain):

- K2 structured References and terminology resolution (spec 0010 §§5–6, issue
  #42): the versioned ``ariadne`` extension of a Reference page is validated by
  the shared per-type gate (:func:`_reference_extension_errors` — malformed
  supported declarations and author-fabricated approval/measurement claims are
  rejected; legacy References stay readable), and the shared read-only
  :func:`resolve_term` resolves terms and exact field bindings with bounded
  alternatives, unconfirmed claims and actual citations;
- the advisory quality view through the pinned typed-SDK
  entry (:func:`data_signals_pinned`) over ONE shared disclosure assembly;
- native technical page builders (:func:`build_native_table_page`,
  :func:`build_native_dataset_page`, the native finalize derivation) and the
  measurement/mapping evidence machinery (digests, evidence views,
  confirmation bindings, quality profiles).

Ranking, full Policy bodies, candidate labels and attestation semantics remain
unchanged. This module guides interpretation and never computes metrics or
admits artifacts; it imports no workflow module.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

# the canonical catalog-resource parser behind exact field
# bindings (the shared source registry owns resource identity; this module
# imports no workflow module — sources is the shared registry layer).
from ariadne.sources import parse_resource

# OKF page frontmatter shared by Authoring, Ingest and Query:
# sources[] resolution (rev 10 context field) and lifecycle bookkeeping read it.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# search matching is token-aware, not substring — a query
# token is a lowercase [a-z0-9]+ run, so "order" no longer counts inside
# "orders" and incidental substring repetition cannot crowd out real matches.
_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")

# ATX headings (spec: the section is the containing Markdown heading; a line
# like "#hashtag" without the required space is not one).
_HEADING_RE = re.compile(r"#{1,6}\s+(.+?)\s*$")

# Excerpt bound: chars of context kept on each side of the matched token before
# snapping outward to whole words (spec: bounded, verbatim).


# ------------------------------------------------- deterministic OKF generation

# ------------------------------------------------------- frontmatter primitives


def _load_frontmatter_meta(text: str) -> dict:
    """Frontmatter meta of an OKF page (empty dict when absent)."""
    match = _FRONTMATTER_RE.match(text)
    return (yaml.safe_load(match.group(1)) or {}) if match else {}


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


# ADR-0007 bundle contract, as amended by spec 0010 §3/§9:
# every content type is CHECKED by its context_layer section and frontmatter
# ``type``; presence is APPLICABLE (a section with pages must satisfy its
# contract; absent sections are not invented categories).
# Per-type required frontmatter beyond ``type`` itself (ADR-0007 bundle
# contract, as documented in the authoring prompt and asserted per type in
# tests/test_author.py). Fields attached mechanically after validation (metric
# governed_by/dimensions/grain, computation runtime/attester) carry their own
# targeted errors below, not this shared list.


# System-generated candidate bookkeeping (index trees, log) is not authored
# content, so the per-type bundle gate does not check it.


# ---------------------------------------------- post-validation OKF enrichment


def _model_index(staging: Path) -> tuple[dict[str, dict], bool]:
    """``(full identity -> {model, primary_key, dimensions, dataset_sources,
    expression}, all_parsed)`` from the candidate Ossie models — the mechanical
    source of truth for enrichment and computations. The identity is
    ``<model>::<key>`` with key ``<metric>`` or ``<dataset>.<metric>``, so two
    models sharing a metric key stay distinct. A model file that does not parse
    or validate is SKIPPED and reported through ``all_parsed=False`` so the
    validation gate can report the structural failure without a finalize crash
    or treating an unparseable draft's metrics as removed."""
    from ariadne import ossie

    index: dict[str, dict] = {}
    all_parsed = True
    models_dir = staging / "semantic_layer" / "models"
    paths = (
        sorted((*models_dir.glob("*.yml"), *models_dir.glob("*.yaml")))
        if models_dir.is_dir()
        else []
    )
    for path in paths:
        try:
            model = ossie.parse_model(ossie.read_document(path), path.name)
        except ValueError:
            all_parsed = False  # unparseable/invalid draft: the validation gate owns the error
            continue
        for key, metric in model.metrics.items():
            owner = model.datasets.get(metric.owner) if metric.owner else None
            scope = [owner] if owner is not None else list(model.datasets.values())
            sources: list[str] = []
            for dataset in scope:
                if dataset.source not in sources:
                    sources.append(dataset.source)
            index[f"{model.name}::{key}"] = {
                "model": model.name,
                "primary_key": list(scope[0].primary_key) if scope else [],
                "dimensions": [n for d in scope for n, f in d.fields.items() if f.dimension],
                "dataset_sources": sources,
                "expression": metric.expression,
            }
    return index, all_parsed


# ------------------------------------------- the Git-candidate finalize pass

_SQL_FENCE_RE = re.compile(r"```sql\n(.*?)\n```", re.DOTALL)


def sanctioned_sql(staging: Path, models: dict[str, dict]) -> dict[str, str]:
    """The CURRENT resolved sanctioned SQL of every single-dataset governed
    metric of the tree (``models`` is :func:`_model_index`'s index, keyed by full
    identity), from the existing compiler; cross-fact and unresolvable metrics
    are absent."""
    from ariadne.render import render
    from ariadne.semantic_graph import load_graph

    try:
        graph = load_graph(staging / "semantic_layer")
    except Exception:
        graph = None  # the structural gate owns the loader failure
    rendered: dict[str, str] = {}
    if graph is not None:
        for identity, info in models.items():
            name = identity.partition("::")[2]
            if identity not in graph.metrics:
                continue
            try:
                from ariadne.render import build_slice

                model = graph.models[info["model"]]
                node = graph.metrics[identity]
                datasets = {graph.metrics[d].owner for d in node.deps} or {node.owner}
                dataset = next(iter(datasets))
                if len(datasets) != 1 or dataset is None:
                    continue  # cross-fact: the planner compiles it, not the single renderer
                keys = [k for k, m in model.metrics.items() if m.owner == dataset]
                keys += [
                    k
                    for k, m in model.metrics.items()
                    if m.owner is None and all(d in keys for d in m.deps)
                ]
                spec = build_slice(model, dataset, keys, aliases={k: k for k in keys})
                rendered[identity] = render(spec, metric=name).strip()
            except Exception:
                continue  # the compile gate owns the structural failure
    return rendered


def finalize_native_candidate(staging: Path) -> tuple[list[dict], list[str]]:
    """The revision-2 native finalize derivation (spec0035 §6 C2 cutover): the
    deterministic generated Computation content of the governed metric set as
    producer-native ``knowledge/computations`` page specs for the ONE native
    batch writer — no classic ``context_layer`` finalization, no classic index
    generation. Evidence binding is DEFINITION- AND DEPENDENCY-COMPLETE for
    authored and generated pages alike (owner-approved bounded completion of
    the preserved classic ``_computation_matches``/source-only-attestation
    principles): the CURRENT resolved sanctioned definition of every governed
    metric comes from the EXISTING compiler (``render`` embeds the full
    dependency closure, so a base-metric or field-mapping change reaches
    derived metrics whose own expression string and dataset sources never
    moved) — no new SQL/KB parser, no whole-tree digest, no data/source
    access. A core-generated page still recording that exact resolved SQL and
    dataset sources keeps its bytes verbatim, earned attestation included; a
    generated page whose recorded definition no longer matches refreshes the
    derived facts and clears the predecessor's obsolete attester/check down
    to honest ``attestation: pending`` through the same atomic native batch,
    preserving unrelated authored frontmatter and curated narrative. An
    AUTHORED page is never rewritten by the finalize: one WITHOUT an
    evidence claim (no attester, ``attestation`` absent/pending) claims
    nothing and stays untouched, while one CARRYING an earned check that no
    longer matches — or that never recorded — the current resolved definition
    REFUSES validation with a named diagnostic for human resolution (an
    unbound historical check is never quietly trusted). Unparseable model
    drafts derive nothing — the validation gate owns the structural failure,
    exactly like the classic pass. Returns ``(specs, errors)``; empty specs
    is the no-op."""
    models, all_parsed = _model_index(staging)
    if not models or not all_parsed:
        return [], []
    rendered = sanctioned_sql(staging, models)
    comps_dir = staging / "knowledge" / "computations"
    existing: dict[str, tuple[str, str]] = {}
    occupied: dict[str, str] = {}  # page file -> whose it is, anchored or authored
    if comps_dir.is_dir():
        from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
            parse_frontmatter,
        )

        for page in sorted(comps_dir.glob("*.md")):
            raw = page.read_text(encoding="utf-8")
            occupied[page.name] = f"an authored page ({page.name})"
            try:
                full, _body, _start = parse_frontmatter(raw, page.name)
            except Exception:  # noqa: BLE001 — the producer/page gate owns malformed pages
                continue
            profile = full.get("ariadne_profile") if isinstance(full, dict) else None
            core_ref = profile.get("core_ref") if isinstance(profile, dict) else None
            if isinstance(core_ref, dict) and core_ref.get("kind") == "semantic":
                existing[str(core_ref.get("id"))] = (page.name, raw)
                occupied[page.name] = str(core_ref.get("id"))
    specs: list[dict] = []
    errors: list[str] = []
    for identity, info in sorted(models.items()):
        name = identity.partition("::")[2]
        sanctioned = rendered.get(identity)
        page = existing.get(identity)
        if page is None:
            if sanctioned is not None:
                file = _page_file(identity, info["model"], name)
                if file in occupied:
                    errors.append(
                        f"knowledge/computations/{file}: the page for {identity} would take"
                        f" the path already held by {occupied[file]}; resolve it by hand"
                    )
                    continue
                occupied[file] = identity
                specs.append(
                    {
                        "path": f"knowledge/computations/{file}",
                        "content": _build_native_computation_page(name, info, sanctioned),
                    }
                )
            continue  # no resolvable definition: the compile gate owns the failure
        rel_name, raw = page
        state, refusal = _native_computation_state(raw, name, info, sanctioned)
        if refusal is not None:
            errors.append(refusal)
        if state == "stale" and sanctioned is not None:
            specs.append(
                {
                    "path": f"knowledge/computations/{rel_name}",
                    "content": _refresh_native_computation_page(raw, name, info, sanctioned),
                }
            )
    return specs, errors


def _page_file(identity: str, model: str, key: str) -> str:
    """Page file name ``<model>--<key>.md``; past 200 bytes (filesystem limit) it
    is the first 120 bytes of that encoded name + ``--h`` + 16 hex of sha256(identity)."""
    file = f"{_path_part(model)}--{_path_part(key)}.md"
    if len(file) <= 200:  # the encoding is pure ASCII: characters are bytes
        return file
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{file[:120]}--h{digest}.md"


def _path_part(text: str) -> str:
    """Injective, filesystem-safe encoding of a model or key: ``[A-Za-z0-9_]``
    stay; every other UTF-8 byte (``-`` and ``.`` included) becomes ``-<hex>``,
    so the ``--`` that joins model and key never occurs inside either part."""
    return "".join(
        chr(b) if chr(b).isascii() and (chr(b).isalnum() or b == 0x5F) else f"-{b:02x}"
        for b in text.encode("utf-8")
    )


def _native_computation_state(
    text: str, name: str, info: dict, sanctioned: str | None
) -> tuple[str, str | None]:
    """``authored`` (skip: no evidence claim, an eligible claim, or bytes the
    finalize never touches), ``stale`` (core-generated and no longer matching
    the resolved definition: refresh) or ``refuse`` (an authored evidence
    claim that cannot apply). ``sanctioned`` is the CURRENT resolved
    sanctioned SQL of the metric from the existing compiler — the same
    dependency-closure identity the compile gate sanctions; identity, marker
    or raw own-expression strings alone are never definition proof."""
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        parse_frontmatter,
    )

    try:
        full, body, _start = parse_frontmatter(text, name)
    except Exception:  # noqa: BLE001 — the producer/page gate owns malformed pages
        return "authored", None
    profile = full.get("ariadne_profile") if isinstance(full, dict) else None
    native = profile.get("native") if isinstance(profile, dict) else None
    native = native if isinstance(native, dict) else {}
    generated = any(
        isinstance(source, dict) and source.get("id") == f"model-{info['model']}"
        for source in native.get("sources") or []
    )
    claims_evidence = "attester" in native or native.get("attestation") not in (
        None,
        "pending",
    )
    fence = _SQL_FENCE_RE.search(body or "")
    recorded_sources = native.get("dataset_sources")
    recorded_definition = fence is not None or isinstance(recorded_sources, list)
    if generated:
        if sanctioned is None:
            return "authored", None  # the compile gate owns the definition failure
        matches = (
            fence is not None
            and fence.group(1).strip() == sanctioned
            and recorded_sources == list(info["dataset_sources"])
        )
        return ("current", None) if matches else ("stale", None)
    if not claims_evidence:
        return "authored", None  # pending/absent attestation claims nothing
    if sanctioned is None:
        return "authored", None  # the compile gate owns the definition failure
    if not recorded_definition:
        return "authored", (
            f"knowledge/computations/{name}.md (its core_ref names"
            f" {info['model']}::{name}): the page carries an independent"
            " attestation bound to no recorded sanctioned definition (no"
            " attested SQL fence or dataset sources) — an unbound historical"
            " check is never trusted for the current executable bytes; record"
            " the attested definition or withdraw the claim"
        )
    matches = (
        fence is not None
        and fence.group(1).strip() == sanctioned
        and (
            not isinstance(recorded_sources, list)
            or recorded_sources == list(info["dataset_sources"])
        )
    )
    if matches:
        return "authored", None  # eligible: the earned check binds the current definition
    return "authored", (
        f"knowledge/computations/{name}.md (its core_ref names"
        f" {info['model']}::{name}): the recorded independent attestation was"
        " earned for a DIFFERENT sanctioned definition — the predecessor check"
        " cannot apply to the current executable bytes; re-attest against the"
        " current definition or withdraw the claim (the finalize never"
        " rewrites authored content)"
    )


def _refresh_native_computation_page(text: str, name: str, info: dict, sanctioned: str) -> str:
    """The surgical refresh of one STALE core-generated Computation page: the
    derived facts (resolved sanctioned SQL fence, runtime, dataset sources)
    update to the current definition and the predecessor's obsolete
    attester/check is cleared down to the honest ``attestation: pending`` — a
    prior numerical check is never carried onto executable bytes it did not
    check. Every other byte of the page (identity, authored envelope,
    lifecycle, sources, unrelated curated narrative) is preserved verbatim."""
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        parse_frontmatter,
    )

    full, body, _start = parse_frontmatter(text, name)
    profile = full.get("ariadne_profile")
    native = profile.get("native") if isinstance(profile, dict) else None
    if not isinstance(native, dict):  # pragma: no cover — state() parsed it before
        return text
    native.pop("attester", None)
    native["attestation"] = "pending"
    native["runtime"] = "duckdb"
    native["dataset_sources"] = list(info["dataset_sources"])
    new_fence = "```sql\n" + sanctioned + "\n```"
    match = _SQL_FENCE_RE.search(body or "")
    if match is not None:
        body = body[: match.start()] + new_fence + body[match.end() :]
    else:
        body = (body or "").rstrip() + "\n\n" + new_fence + "\n"
    front = yaml.safe_dump(full, default_flow_style=False, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{body}"


def _build_native_computation_page(name: str, info: dict, sanctioned: str) -> str:
    """One honest generated native Computation page: the same
    sanctioned-SQL provenance the classic finalize pass produced, as a
    producer-native Computation profile anchored by its exact core_ref
    semantic identity. The recorded SQL fence is the metric's CURRENT
    RESOLVED sanctioned definition from the existing compiler (full
    dependency closure — never the raw own-expression string), so evidence
    binds the exact executable bytes. Deterministic from the gate-checked
    model — no wall-clock stamp, an unchanged retry is byte-identical. The
    page claims no independent attestation (``attestation: pending``), no
    governing Policy edge and no curated meaning: the authored metric page
    owns the narrative; this page exists so the governed answer still
    discloses the sanctioned computation and its honest attestation state."""
    semantic_id = f"{info['model']}::{name}"
    model_source = {"id": f"model-{info['model']}", "title": f"{info['model']} OSI model"}
    meta = {
        "id": "entity:"
        + semantic_id.replace("::", "-").replace(".", "-").replace("_", "-").lower()
        + "-computation",
        "entity_types": ["computation"],
        "tags": ["computation"],
        "title": f"sanctioned SQL — {semantic_id}",
        "summary": "Sanctioned computation: SQL, runtime, attester.",
        "lifecycle": "draft",
        "visibility": "public",
        "sources": [model_source],
        "ariadne_profile": {
            "version": 1,
            "kind": "computation",
            "core_ref": {"kind": "semantic", "id": semantic_id},
            "required_policies": [],
            "native": {
                "type": "computation",
                "status": "draft",
                "title": f"sanctioned SQL — {semantic_id}",
                "description": "Sanctioned computation: SQL, runtime, attester.",
                "tags": ["computation"],
                "attestation": "pending",
                "sources": [model_source],
                "runtime": "duckdb",
                "dataset_sources": list(info["dataset_sources"]),
            },
        },
    }
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = (
        "# Sanctioned computation\n\n"
        f"Sanctioned SQL (OSSIE_SQL_2026, `semantic_layer/models/{info['model']}.yml`); "
        "compile gate `ariadne.validate`; execution DuckDB via the local `ariadne` "
        "command (`ariadne get-metric`); independent attestation pending — no "
        "expected-value oracle is cited (compile and grain checks are not "
        "independent numeric attestation). "
        "Business rules: cited metric page.\n\n"
        "```sql\n" + sanctioned + "\n```\n"
    )
    return f"---\n{front}\n---\n\n{body}"


# -------------------------- K1: core-owned physical schema pages

# The core-owned sections of a generated table page: the
# physical schema block, the separately labeled observations and the schema
# change history. Authored content — the summary and the per-column meanings
# — lives OUTSIDE these sections and is preserved by refresh for identical
# column identity/type.
SCHEMA_SECTION = "Schema"
OBSERVATIONS_SECTION = "Observations"
HISTORY_SECTION = "Schema history"
_CORE_SECTIONS = frozenset({SCHEMA_SECTION, OBSERVATIONS_SECTION, HISTORY_SECTION})


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


def core_body_sections(text: str) -> dict[str, str]:
    """The core-owned BODY sections of one page (``Schema``, ``Observations``,
    ``Schema history``) keyed by section heading: the section chunk from its
    heading line to the next heading, trailing blank lines aside. This is the
    generated-facts map the proposal edit seam compares: the
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


def _schema_flags(old_schema: list[dict] | None, new_schema: list[dict]) -> dict:
    """Column-level change flags of one refresh: added/removed
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


# ----------------- C1: selected observed filter values (spec
# 0024 §3). The human owns the optional ``observed_value_columns`` selection
# on a table page — an exact column -> catalog-type mapping that binds the
# publication to one known field representation; the core owns the measured
# ``value_evidence`` inside ``ariadne.observations`` and its rendering in the
# core-owned Observations section. Selection alone is never Source Approval
# or a sample grant, and it introduces no new permission, tool or engine.

OBSERVED_VALUE_COLUMNS_KEY = "observed_value_columns"

# The whole-value-evidence bound: at most 8 KiB UTF-8 for the
# COMPLETE successful ``value_evidence`` mapping, measured as compact JSON
# with non-ASCII preserved — never a clipped literal or a partially retained
# histogram.
VALUE_EVIDENCE_MAX_BYTES = 8 * 1024

# The supported EXACT filter-value representations: native
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
    YAML: PyYAML collapses duplicate mapping keys last-wins, so
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
    mapping: exact physical column name -> selected catalog
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
    """The whole-value-evidence bound measure: compact JSON,
    UTF-8, non-ASCII preserved, non-finite numbers refused."""
    return len(
        json.dumps(mapping, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _value_evidence(*, selection: dict, columns: list[dict], profile: dict, where: str) -> dict:
    """Measured value evidence for the SELECTED columns only:
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
            # finite native floats only: a non-finite value is
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


def _observation_facts(
    *,
    resource: str,
    profile: dict,
    value_evidence: dict | None = None,
    source_binding: str | None = None,
) -> dict:
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
    if source_binding:
        # the effective storage approval the measurements were
        # taken under — endpoint provenance for profile-backed sources only,
        # so profile-free pages keep their exact legacy facts/bytes.
        facts["source_binding"] = source_binding
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


def build_native_table_page(
    *,
    asset: dict,
    columns: list[dict],
    profile: dict,
    existing_meta: dict | None,
    existing_body: str,
    now: str,
    source_binding: str | None = None,
) -> tuple[str, dict]:
    """Generate one producer-native Table profile page (spec0032 §5/§6,
    producer spec 0009 §2) for a revision-2 candidate: the complete
    ``ariadne_profile`` envelope — ``core_ref`` resource identity, the native
    base metadata and the core-owned ``native.ariadne`` schema/observations
    facts — with authored summary/base metadata and the curated body
    preserved verbatim outside the core-owned sections. The physical row
    fields (column/type/nullable/default/comment) regenerate from the
    INSPECTED source columns on every refresh (#83 review fix F5, spec0010
    §4): a prior same-name/type row never launders stale declared DDL facts,
    and curated meaning lives in the authored description/body and preserved
    native extras. The producer-parsed native ``observed_value_columns``
    selection is fulfilled by the real measured profile through the existing
    selection/value-evidence validators —
    preserve-or-refuse, never a silent evidence drop. The observation
    timestamp is REUSED when the schema and the measurements are unchanged
    (identical inputs produce identical bytes). The caller parses any
    existing KB page through the producer's public frontmatter parse; this
    builder never parses KB bytes itself.
    Returns ``(page text, change flags)``."""
    resource = asset["resource"]
    existing_profile = (
        existing_meta.get("ariadne_profile") if isinstance(existing_meta, dict) else None
    )
    existing_profile = existing_profile if isinstance(existing_profile, dict) else None
    existing_native = existing_profile.get("native") if existing_profile is not None else None
    existing_native = existing_native if isinstance(existing_native, dict) else {}
    existing_ariadne = existing_native.get("ariadne")
    existing_ariadne = existing_ariadne if isinstance(existing_ariadne, dict) else {}
    old_schema = existing_ariadne.get("schema")
    old_schema = old_schema if isinstance(old_schema, list) else None
    # the physical row fields regenerate from the INSPECTED
    # columns on every refresh — a prior same-name/type row never launders
    # stale declared nullability/default/comment; curated meaning lives in the
    # authored description/body and the preserved native extras.
    authored: list[dict] = [dict(column) for column in columns]
    flags = _schema_flags(old_schema, authored)
    # the producer-parsed native selection (existing_meta is
    # the producer's public frontmatter view — never a Core YAML parse of KB
    # bytes, never _authored_selection over raw page text) is fulfilled by the
    # REAL measured profile through the existing validators; a malformed
    # selection refuses the whole refresh and unsupported states stay honest.
    selection = existing_native.get("observed_value_columns")
    selection_errors = _selection_shape_errors(selection)
    if selection_errors:
        raise ValueError(
            f"{resource}: authored observed_value_columns is not a valid selection "
            f"({'; '.join(selection_errors)}) — fix the page metadata; nothing "
            "was written"
        )
    value_evidence = (
        _value_evidence(selection=selection, columns=authored, profile=profile, where=resource)
        if selection
        else None
    )
    facts = _observation_facts(
        resource=resource,
        profile=profile,
        value_evidence=value_evidence,
        source_binding=source_binding,
    )
    old_observations = existing_ariadne.get("observations")
    old_observations = old_observations if isinstance(old_observations, dict) else {}
    old_observed_at = (
        old_observations.get("observed_at")
        if isinstance(old_observations.get("observed_at"), str)
        else None
    )
    reuse_timestamp = (
        old_observed_at is not None
        and old_schema is not None
        and old_schema == authored
        and {key: value for key, value in old_observations.items() if key != "observed_at"} == facts
    )
    observed_at = old_observed_at if reuse_timestamp and old_observed_at is not None else now
    observations = {"observed_at": observed_at, **facts}
    citation = {
        "id": f"catalog-{asset['source']}-{asset['schema']}-{asset['table']}",
        "resource": resource,
        "title": f"catalog and profile of {asset['source']}.{asset['schema']}.{asset['table']}",
    }
    title = f"{asset['source']}.{asset['schema']}.{asset['table']}"
    description = (
        f"Physical table {asset['table']} of source {asset['source']} "
        f"(schema {asset['schema']}). Row meaning: unknown — not yet authored."
    )
    if existing_meta is None:
        meta: dict = {
            "id": f"entity:table-{hashlib.sha256(resource.encode('utf-8')).hexdigest()}",
            "entity_types": ["table"],
            "tags": ["table", "schema"],  # canonical contract: nonempty tags list
            "title": title,
            "summary": description.split(". ")[0] + ".",
            "lifecycle": "approved",
            "visibility": "public",
            "sources": [citation],
        }
    else:
        meta = dict(existing_meta)
    native = {
        "type": "table",
        "title": existing_native.get("title") or title,
        "description": existing_native.get("description") or description,
        "tags": existing_native.get("tags") or ["table", "schema"],
        "sources": _ensure_citation(existing_native.get("sources"), citation),
        "resource": resource,
        "ariadne": {"schema": authored, "observations": observations},
    }
    for key, value in existing_native.items():
        if key not in native and key != "ariadne":
            native[key] = value  # authored native extras preserved verbatim
    meta["ariadne_profile"] = {
        "version": 1,
        "kind": "table",
        "core_ref": {"kind": "resource", "id": resource},
        **{
            key: value
            for key, value in (existing_profile or {}).items()
            if key not in ("version", "kind", "core_ref", "native")
        },
        "native": native,
    }
    body = existing_body
    if not body.strip():
        body = (
            # the producer parse keeps the boundary newline IN the body, so
            # the seeded placeholder carries it too and the emitted page —
            # fence + body reassembled without an extra separator — is
            # byte-stable across refreshes (an identical refresh is a no-op)
            f"\n# {title}\n\nGenerated physical table profile of the approved "
            "catalog asset; the schema and observation facts live in the "
            "technical envelope. This body is curated operator space.\n"
        )
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{front}---{body}", flags


def build_native_dataset_page(
    *,
    collection: dict,
    tables: list[dict],
    existing_meta: dict | None,
    existing_body: str,
) -> tuple[str, dict]:
    """Generate one producer-native Dataset Overview profile page
    (spec0032 §3/§5): ``core_ref`` collection identity and the
    ``native.ariadne.tables`` links to EXACTLY the tables this refresh
    documents — never every approved source. Authored base metadata and the
    curated body are preserved verbatim; links are regenerated. Returns
    ``(page text, flags)`` with the linked-table additions/removals."""
    resource = collection["resource"]
    existing_profile = (
        existing_meta.get("ariadne_profile") if isinstance(existing_meta, dict) else None
    )
    existing_profile = existing_profile if isinstance(existing_profile, dict) else None
    existing_native = existing_profile.get("native") if existing_profile is not None else None
    existing_native = existing_native if isinstance(existing_native, dict) else {}
    existing_ariadne = existing_native.get("ariadne")
    existing_ariadne = existing_ariadne if isinstance(existing_ariadne, dict) else {}
    old_tables = existing_ariadne.get("tables")
    old_tables = old_tables if isinstance(old_tables, list) else []
    linked = [table["resource"] for table in tables]
    flags = {
        "added": sorted(set(linked) - set(old_tables)),
        "removed": sorted(set(old_tables) - set(linked)),
    }
    citation = {
        "id": f"catalog-{collection['source']}-{collection['schema']}",
        "resource": resource,
        "title": f"catalog of {collection['source']}.{collection['schema']}",
    }
    title = f"{collection['source']}.{collection['schema']}"
    description = (
        f"Physical collection {collection['schema']} of source "
        f"{collection['source']}. Collection meaning: unknown — not yet authored."
    )
    if existing_meta is None:
        meta: dict = {
            "id": f"entity:dataset-{hashlib.sha256(resource.encode('utf-8')).hexdigest()}",
            "entity_types": ["dataset"],
            "tags": ["dataset", "schema"],  # canonical contract: nonempty tags list
            "title": title,
            "summary": description.split(". ")[0] + ".",
            "lifecycle": "approved",
            "visibility": "public",
            "sources": [citation],
        }
    else:
        meta = dict(existing_meta)
    native = {
        "type": "dataset",
        "title": existing_native.get("title") or title,
        "description": existing_native.get("description") or description,
        "tags": existing_native.get("tags") or ["dataset", "schema"],
        "sources": _ensure_citation(existing_native.get("sources"), citation),
        "ariadne": {"tables": linked},
    }
    for key, value in existing_native.items():
        if key not in native and key != "ariadne":
            native[key] = value  # authored native extras preserved verbatim
    meta["ariadne_profile"] = {
        "version": 1,
        "kind": "dataset",
        "core_ref": {"kind": "resource", "id": resource},
        **{
            key: value
            for key, value in (existing_profile or {}).items()
            if key not in ("version", "kind", "core_ref", "native")
        },
        "native": native,
    }
    body = existing_body
    if not body.strip():
        body = (
            # same boundary-newline contract as the table builder above: the
            # reassembled page is byte-stable across refreshes
            f"\n# {title}\n\nGenerated Dataset Overview of the approved "
            "collection; the table links live in the technical envelope. This "
            "body is curated operator space.\n"
        )
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{front}---{body}", flags


# ------------- K2: structured References and term resolution

# The supported ``ariadne`` extension version of a Reference page (plan §2:
# integer 1; an unsupported or malformed version is a contract violation,
# never a guess).
ARIADNE_EXTENSION_VERSION = 1
# The reference-role discriminator of the extension: Term
# References and Identifier Mappings are roles within References, not new
# standalone page types; ``join``/``enum`` pages carry the same structures
# without gaining an interpreter.
REFERENCE_ROLES = ("term", "identifier", "enum", "join")
MAPPING_FAMILIES = ("equality", "prefix", "lookup")
MAPPING_CLAIMS = ("hypothesis", "asserted")
# Concept/representation/mapping slugs follow the safe page-name discipline:
# a plain lowercase slug — never a path, hidden, option-shaped or wildcard.
_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
# The bounded resolution contract: at most 20 matches per part in
# stable page/representation order, explicit truncation, part continuation.
RESOLVE_TERM_LIMIT = 20
# …and the SAME 64 KiB serialized-response ceiling the operator's bounded
# inspection defaults set: every response PART stays under this
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
# the structured inspection candidate IS part of
# a mapping declaration now — validated by the shared candidate schema below
# (``validate_inspection_candidate``), still alongside the refusal of every
# author-fabricated approval/measurement claim.
_MAPPING_KEYS = frozenset(
    {"id", "family", "from", "to", "claim", "source_ids", "receipt_ids", "candidate"}
)


# --------------------- K3: the inspection candidate schema

# The candidate is a discriminated JSON object, never an executable string
# (plan §2 "Inspection candidate and finite limits"): the
# allowlists below are exhaustive — there is no SQL, function, path or freely
# interpreted expression field, and an unknown key is refused by name.
CANDIDATE_FAMILIES = ("equality", "prefix", "lookup")
CANDIDATE_SCOPE_OPS = ("eq", "in", "gte", "lt")
# Operator-owned structural ceilings of one candidate: four
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
# at finalization: credential-free counts only, never raw
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
    """Validate the structured inspection candidate
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
        # a scope predicate narrows a PARTICIPATING
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
            # a pairing binding names a column of ITS
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
    # scope predicates attach to PARTICIPATING
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
    try:
        normalized = json.loads(json.dumps(candidate, ensure_ascii=False))  # deep copy
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"the inspection candidate is not serializable data ({exc}) — "
            "an invalid candidate is an error, never a partial normalization"
        ) from None
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
    """The normalized candidate identity digest: family, ordered
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
    (plan §2 "Structured References, authority and freshness"):
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
        # the structured candidate is part of the declaration —
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
    # the core-attached verified receipt summaries. The key
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
    its mapping's claim: honest
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
    flag is never authority. Expired evidence
    withholds stale confirmed GUIDANCE:
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
    this seam, it is not a public argument."""
    return datetime.now(UTC)


def _parse_timestamp(value: object) -> date | datetime | None:
    """OKF §5 timestamp: an offset-bearing date-time or a date-only day (YAML-native
    or quoted); anything else, including a naive date-time, is ``None``."""
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def _freshness_view(meta: dict, now: datetime) -> dict:
    """Interpret page expiry timestamps as instants and legacy dates as UTC days."""
    value = meta.get("stale_after")
    if not isinstance(value, (str, date)):
        return {"stale_after": None, "state": "unknown"}
    disclosed = value if isinstance(value, str) else value.isoformat()
    expiry = _parse_timestamp(value)
    if expiry is None:
        return {"stale_after": disclosed, "state": "unknown"}
    if isinstance(expiry, datetime):
        state = "stale" if now >= expiry else "current"
    else:
        state = "stale" if now.date() > expiry else "current"
    return {"stale_after": disclosed, "state": state}


def _jsonable(value: object) -> object:
    """Keep disclosed evidence JSON-shaped: YAML-native date/datetime values
    become ISO strings, other values pass through untouched —
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
    """Conservative lifecycle disclosure: a declared status is
    preserved verbatim (Ariadne draft/review states included); an absent
    status on a readable concept page uses OKF's ``stable`` default;
    malformed lifecycle metadata and pages without concept frontmatter
    (reserved navigation/history files) stay ``unknown``, never implicitly
    stable."""
    if "status" not in meta:
        return "stable" if meta else "unknown"
    declared = meta["status"]
    return declared if isinstance(declared, str) and declared else "unknown"


def _utc_instant(value: object) -> datetime | None:
    parsed = _parse_timestamp(value)
    if parsed is None or isinstance(parsed, datetime):
        return parsed
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def _verification_tier(meta: dict) -> str:
    """Advisory document-verification tier — a claim declared in the page, never
    admission. Only CURRENT events count (OKF v0.3 §5.3): ``at`` >= the page's
    ``generated.at``, or any event when ``generated`` is absent; an event without
    ``by``/``at`` is ignored and an unparsable ``at`` is never current. None
    current (including an empty list) is ``unverified``; current non-human only
    is ``machine-confirmed``; a current ``human:`` actor is ``human-reviewed``."""
    verified = meta.get("verified")
    if not isinstance(verified, list):
        return "unverified"
    generated = meta.get("generated")
    floor = _utc_instant(generated.get("at")) if isinstance(generated, dict) else None
    tier = "unverified"
    for entry in verified:
        if not isinstance(entry, dict):
            continue
        by = entry.get("by")
        at = _utc_instant(entry.get("at"))
        if not (isinstance(by, str) and by) or at is None:
            continue
        if floor is not None and at < floor:
            continue
        if by.startswith("human:"):
            return "human-reviewed"
        tier = "machine-confirmed"
    return tier


def _page_view(rel: str, meta: dict, now: datetime) -> dict:
    """One assessed page's advisory view: bundle-relative
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
    """The additive advisory envelope: the assessed pages
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
    page/source citations. No transform, SQL or join authority
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
    ``{resource, column}`` identity, never a case-folded one."""
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
    """The shared read-only terminology resolver over
    the given context ROOTS: Query passes its pinned admitted context dir,
    Authoring its explicitly selected candidate revision. Semantics, bounds
    and confirmation handling are exactly the shared core in
    :func:`resolve_term_entries` — this is only the filesystem collector for
    context-layer roots (the integrated pinned-SDK route feeds the same core
    through structured entries, spec0029 §1.5; there is no second matcher)."""
    entries: list[tuple[str, dict, bool]] = []
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
            entries.append((rel, meta, draft))
    return resolve_term_entries(
        entries,
        request,
        part=part,
        limit=limit,
        confirmations=confirmations,
        evidence_max_age_hours=evidence_max_age_hours,
    )


def resolve_term_entries(
    entries: list[tuple[str, dict, bool]],
    request: str | dict,
    *,
    part: int = 1,
    limit: int = RESOLVE_TERM_LIMIT,
    confirmations: list[dict] | None = None,
    evidence_max_age_hours: float | None = None,
    enrich=None,
) -> dict:
    """The ONE shared resolver core over explicit structured Reference entries
    (spec 0010 §6, plan §2): ``(page path, frontmatter-shaped meta, draft)``
    triples — bounded matching concept/representation identities, exact field
    bindings, required scope, ambiguity, claim/confirmation/freshness status
    and actual page/source citations.

    Matching is deterministic: casefolded whole-alias/phrase equality for
    natural language (never substring fuzzy inference) and exact qualified
    field identity for bindings (never case-folded). All eligible matches are
    counted before the bound, so ambiguity is never declared from a truncated
    result; at most ``limit`` matches return per part in stable
    page/representation order with explicit truncation and part continuation
    (the existing bounded-read convention), every part staying under the
    shared 64 KiB serialized-response ceiling: a part stops before
    exceeding it, and an entry too large for a whole part is disclosed with
    bounded fields and an explicit elision marker — never silently dropped
    nor overflowed. No match yields an empty match list; a malformed supported
    Reference or request fails explicitly. The resolver applies no transform,
    rewrites no SQL and authorizes no join. ``enrich``
    optionally decorates each match — the integrated route's version-qualified
    SDK/Bound-Release provenance — BEFORE the bounded parts are computed, so
    the whole-output ceilings always bind the enriched form.

    ``confirmations`` are the ADMITTED human confirmation
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
    for rel, meta, draft in entries:
        errors = _reference_extension_errors(rel, meta)
        if errors:
            raise ValueError(
                f"malformed reference page — {'; '.join(errors)} — the resolver "
                "resolves only well-formed supported declarations"
            )
        page_matches = _page_matches(
            rel, meta, draft, query, needle, now, admitted or None, evidence_max_age_hours
        )
        if enrich is not None:
            page_matches = [enrich(match) for match in page_matches]
        matches.extend(page_matches)
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


# ---------------------------------------------- deterministic index generation


# ------------------ advisory supplied source-quality evidence

# The optional authored ``ariadne_quality`` profile of a physical-table page
# (plan 0013 §2 "Authored metadata"): one bounded,
# closed-shape declaration of SUPPLIED reports — a domain owner's/upstream
# producer's reported claims with citations, never a core-produced
# measurement or a new registry. The shared per-type gate validates it before
# human admission; the pinned advisory consumer reads it. Every
# bound below is an approved public-contract limit, not an
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
    unknown = sorted(set(period) - _QUALITY_PERIOD_KEYS, key=repr)
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
    unknown = sorted(set(profile) - _QUALITY_ROOT_KEYS, key=repr)
    if unknown:
        errors.append(f"{rel}: ariadne_quality carries unsupported field(s) {unknown}")
    binding = meta.get("resource")
    if not isinstance(binding, str) or not binding:
        errors.append(
            f"{rel}: ariadne_quality requires the page's canonical resource binding "
            "— a page without an established table binding cannot carry a quality "
            "report (an asset is never guessed from a display name)"
        )
    sources = meta.get("sources")
    if not isinstance(sources, list):
        # a non-list native sources shape is a NAMED
        # pre-interpretation refusal — never a TypeError iteration crash on
        # the producer-parsed scalar and never a misleading citation error
        return errors + [
            f"{rel}: native sources must be a list to carry ariadne_quality — "
            "source_ids resolve against the page's declared source records"
        ]
    citation_resources = {
        source["id"]: source.get("resource")
        for source in sources
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
        unknown = sorted(set(report) - _QUALITY_REPORT_KEYS, key=repr)
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
            unknown = sorted(set(scope) - _QUALITY_SCOPE_KEYS, key=repr)
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
                unknown = sorted(set(source_version) - _QUALITY_VERSION_KEYS, key=repr)
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
                unknown = sorted(set(check) - _QUALITY_CHECK_KEYS, key=repr)
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
                unknown = sorted(set(watermark) - _QUALITY_WATERMARK_KEYS, key=repr)
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
DATA_SIGNALS_MAX_REPORTS = 128
DATA_SIGNALS_MAX_BYTES = 64 * 1024


def _coerce_validated_instant(value: object) -> datetime:
    """The instant of a VALIDATED profile timestamp (aware datetime or aware
    ISO string — the producer authoring gate rejected everything else)."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


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
    than the assessment instant leaves age unknown. Applicability
    is mechanical correspondence, never a guess: a KNOWN period contradiction
    — the report's own evidence period provably disjoint from the requested
    query period, and only when the report's declared period FIELD is one the
    request's range actually predicates — makes the
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
    # existing source/query facts: this runtime holds no
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
        # a report/observation later than the assessment
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


def _data_signals_state(
    metric_names: list[str],
    asset_order: list[str],
    omitted_metrics: int,
    omitted_assets: int,
    omitted_pages: int,
    dependencies: dict[str, list[str | None]],
    bindings: dict[str, tuple[str, dict]],
    unresolved: list[str],
    now: datetime,
    requested_period: tuple[datetime | None, datetime | None] | None,
    period_fields: set[str] | frozenset[str] | None,
) -> dict:
    """The shared spec0013 §4 disclosure assembly behind the pinned advisory
    entry :func:`data_signals_pinned` (pinned typed SDK metadata): coverage,
    warnings, bounded elision and the deterministic 64 KiB convergence —
    ONE semantic calculation, never a second advisory dialect."""

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
                # Advisory interpretation NEVER fails the query: a
                # later-edited unreadable declaration (e.g. a citation with a
                # non-string id) degrades to unknown evidence with the
                # unavailability warning — the computed result is already safe.
                invalid = True
                entry["reports"] = []
                entry["coverage"] = "unknown"
                info["elided"] = False
            if invalid:
                info["invalid"] = True  # later-unreadable declared evidence
    while True:  # deterministic convergence to the 64 KiB ceiling
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
            if resource not in state:  # elided by the byte ceiling
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
        # deterministic convergence to the ceiling: elide ONE
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


def data_signals_pinned(
    snapshot,
    dependencies: dict[str, list[str | None]],
    *,
    requested_period: tuple[datetime | None, datetime | None] | None = None,
    period_fields: set[str] | frozenset[str] | None = None,
) -> dict:
    """The spec0013 §4 advisory quality view over the PINNED scoped
    ContextSnapshot (C6 native route, owner-approved quality contract):
    the SAME semantic calculation and disclosure shape as the classic entry
    (via the shared `_data_signals_state`), with the consuming metric pages
    and the directly-cited table pages resolved from the REAL producer view —
    metric identity ONLY through `snapshot.bindings` (`metric_entity_id` /
    `metric_ref`, qualified model::metric — a bare name mapping to several
    models stays honestly unknown, never a cross-match) and table identity
    through the exact FLAT `native.resource`. Citations resolve SCOPE-FIRST
    over the visible pinned pages: an exact visible KB-relative page path
    resolves that page and reads its canonical resource; a canonical resource
    URI matches the visible page whose resource equals it exactly; unknown or
    hidden stays honestly unknown. No filesystem read, no second index, no
    raw KB parse, no SQL/source probe on the advisory read; the view never
    fails a numerically valid query and never invents evidence — a dependency
    without a pinned technical page, or a page without an authored accepted
    `ariadne_quality` profile, stays honestly unknown coverage."""
    from lumio_wiki.ariadne_context import disclose_native

    now = _assessment_now()
    pages = tuple(snapshot.pages) if snapshot is not None else ()
    bindings = tuple(snapshot.bindings) if snapshot is not None else ()
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
    # qualified metric identity through the REAL producer bindings (never a
    # bare-name cross-match), then the metric page by its exact producer identity
    bindings_by_metric: dict[str, list] = {}
    for binding in bindings:
        metric_ref = getattr(binding, "metric_ref", None)
        key = getattr(metric_ref, "metric", None)
        model = getattr(metric_ref, "model", None)
        if isinstance(key, str) and key and isinstance(model, str) and model:
            bindings_by_metric.setdefault(f"{model}::{key}", []).append(binding)
    page_by_entity = {page.entity_id: page for page in pages}
    # typed index over the VISIBLE pinned pages (deterministic order; the
    # disclosed FLAT native metadata is the only metadata read)
    metric_citations: dict[str, set[str]] = {}
    tables: dict[str, tuple[str, dict]] = {}
    resource_by_visible_path: dict[str, str] = {}
    for page in sorted(pages, key=lambda item: item.path):
        native_meta = disclose_native(page.native)
        if not isinstance(native_meta, dict):
            continue
        if page.kind != "table":
            continue
        resource = native_meta.get("resource")
        if not (isinstance(resource, str) and resource.startswith("ariadne://")):
            continue
        meta: dict = {"resource": resource}
        # the Core advisory gate resolves the reports' source_ids against the
        # page's own declared citations — carry them with the profile
        sources_meta = native_meta.get("sources")
        if isinstance(sources_meta, list):
            meta["sources"] = sources_meta
        quality = native_meta.get("ariadne_quality")
        if quality is not None:
            meta["ariadne_quality"] = quality
        tables.setdefault(resource, (f"knowledge/{page.path}", meta))
        resource_by_visible_path[page.path] = resource
    for name in dict.fromkeys(metric_names):
        candidates = bindings_by_metric.get(name) or []
        if len(candidates) != 1:
            continue  # absent/ambiguous qualified identity: honest unknown
        binding = candidates[0]
        metric_page = page_by_entity.get(getattr(binding, "metric_entity_id", None))
        if metric_page is None:
            continue
        native_meta = disclose_native(metric_page.native)
        sources = native_meta.get("sources") if isinstance(native_meta, dict) else None
        if not isinstance(sources, list):
            continue
        cited = metric_citations.setdefault(name, set())
        for source in sources:
            resource = source.get("resource") if isinstance(source, dict) else None
            if not (isinstance(resource, str) and resource):
                continue
            if not resource.startswith("ariadne://"):
                # an exact visible KB-relative table page path resolves THAT
                # page, then its canonical resource — never a URI comparison
                resolved = resource_by_visible_path.get(resource)
                if resolved is not None:
                    cited.add(resolved)
                continue
            try:
                citation_kind, _parts = parse_resource(resource)
            except ValueError:
                continue
            if citation_kind == "table":
                cited.add(resource)  # canonical URI: exact resource match below
    bindings_resolved: dict[str, tuple[str, dict]] = {}
    for resource in asset_order:
        entry = tables.get(resource)
        if entry is None:
            continue  # no pinned technical page: the asset entry stays unknown
        path, meta = entry
        if any(resource in metric_citations.get(name, ()) for name in metric_names):
            bindings_resolved[resource] = (path, meta)
    cited_wanted: set[str] = set()
    for name in metric_names:
        cited_wanted |= {r for r in metric_citations.get(name, ()) if r in wanted}
    unresolved = sorted(cited_wanted - set(bindings_resolved))
    return _data_signals_state(
        metric_names,
        asset_order,
        omitted_metrics,
        omitted_assets,
        0,  # the pinned set is already complete: no page-read budget exists
        dependencies,
        bindings_resolved,
        unresolved,
        now,
        requested_period,
        period_fields,
    )

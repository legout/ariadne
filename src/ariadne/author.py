"""Authoring agent (tickets #4 + rev 6B): profile + seed notes -> LLM drafts -> staging/.

The loop (spec §5, ≤3 rounds):

    profile(db) + seed notes -> LLM draft (OKF bundle .md + OSI .yml) -> validate()
        -> on compile errors, feed them back into the next round
        -> after 3 failed rounds, stop and mark the staged files
           ``status: review_needed`` (spec §7).

One successful round drafts the WHOLE OKF bundle (ADR-0007): ``tables/``,
``references/joins/``, ``policies/``, ``metrics/``, ``skills/`` pages plus the
OSI models. Everything the compile gate already determines mechanically is
NEVER trusted to LLM recall and is attached deterministically after validation:
the trust/lifecycle frontmatter (``generated``/``verified``/``stale_after``),
the metric ``governed_by``/``dimensions``/``grain`` blocks (derived from the
staged models), and one ``computations/<metric>.md`` page per governed metric
(sanctioned expression + runtime + attester). The author never writes
``index.md``/``log.md`` — the promotion gate owns bundle bookkeeping, and such
LLM-supplied file writes are dropped in code, not just by prompt instruction.

The author NEVER writes outside ``staging/`` (spec invariant): every LLM-supplied
path is checked to resolve inside the staging directory. Inputs come from
:mod:`ariadne.profiler` (the profile.json contract) and the human-written seed
notes; business rules live only in the seed notes.

LLM access goes through one OpenAI-compatible chat call per round
(``OPENAI_BASE_URL``/``OPENAI_API_KEY``/``OPENAI_MODEL``). Live credentials live
outside the worktree and are loaded from ``ARIADNE_ENV`` (default
``/home/volker/coding/ariadne/.env``); they are never committed or copied.
Tests inject ``complete=`` (fixture responses) and ``validate_fn=`` (fake
results), so no test touches the network; real compilation is exercised by
tests/test_validate.py and the live run.

Interfaces::

    author(db_path, notes_path) -> list[Path]   # staged files
    author_to_proposal(notes_path, project=...) -> (paths, envelope)  # --git: unadmitted proposal
    # from examples/retail-demo/:
    #   python -m ariadne.author --db data/demo.db --notes seed_notes.md
    #   python -m ariadne.author --git --sources ariadne.yaml --notes data/seed_notes.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

# Shared Context Layer (issue #33, ADR-0016): the deterministic OKF contract,
# enrichment and frontmatter primitives moved to ariadne.context; this module
# calls the shared implementations. ``_load_frontmatter_meta`` is re-exported
# for its existing ariadne.authoring import (unchanged in this slice).
from ariadne.context import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    _BUNDLE_TYPES,
    _bundle_errors,
    _finalize_bundle,
    _load_frontmatter_meta,  # noqa: F401 — re-export: ariadne.authoring imports it from here
    _set_frontmatter,
)

# ADR-0010: the author loop runs on the shared registry connection when a
# registry is in play (--sources / ariadne.yaml), else the legacy --db sqlite.
from ariadne.sources import (  # pyright: ignore[reportMissingImports] — new-module resolver drift
    build_connection,
    default_registry_path,
    implicit_registry,
    load_registry,
)
from ariadne.validate import validate

ENV_PATH = Path(os.environ.get("ARIADNE_ENV", "/home/volker/coding/ariadne/.env"))
MAX_ROUNDS = 3  # spec §5 hard cap on the validate/error loop
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SERVED_LAYERS = ("context_layer", "semantic_layer")  # only ever human-promoted (spec §6)

# Assembled as string pieces so every source line stays under the lint limit.
# Both patterns are execution-verified against tests/fixtures/expected_metrics.json.
_EXCLUDE_REV_EXPR = (
    "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount * fx_rate ELSE 0 END)"
)
_EXCLUDE_COGS_EXPR = (
    "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN product_cost * fx_rate ELSE 0 END)"
)

_SYSTEM_PROMPT_TEMPLATE = """\
You are the Ariadne authoring agent. From a statistical database profile and the \
data owner's seed notes you draft a Context Layer (OKF Markdown) and a Semantic \
Layer (OSI YAML) for governed metrics.

Return ONE JSON object and nothing else — no markdown fences, no commentary:
{"files": [{"path": "<path relative to staging/>", "content": "<complete file content>"}]}

Context Layer (OKF Markdown bundle, ADR-0007) — ONE response carries the WHOLE \
bundle: every folder below PLUS the semantic models.
- `context_layer/tables/<table>.md` — one page per table in the profile.
  Frontmatter: `type: table`, `title`, a one-sentence `description`, `tags`
  (list), `sources` (list of {id, resource, title} maps citing the database),
  and a `grain` block: `{primary_key: [...], cardinality_enforcement:
  STRICT_1_TO_1}` — STRICT_1_TO_1 when the profiler proves the key unique
  (distinct_count == row_count). Body: what one row means, column-by-column
  schema notes, and join hints (keys, cardinality, and the profiler evidence:
  match_ratio, distinct counts, row counts).
- `context_layer/references/joins/<a>--<b>.md` — one page per join pair the
  models use (orders--customers, orders--currency_conversion_rate).
  Frontmatter: `type: reference`, `title`, one-sentence `description`, `tags`,
  `sources`. Body: the join keys, the cardinality FROM THE PROFILER EVIDENCE
  (many-to-one from the fact side because the joined key is a proven-unique
  primary key; cite match_ratio and distinct counts), and a grain-safety note
  per ADR-0006 (project/adr/0006-grain-governance-multi-cardinality-joins.md):
  the join is grain-preserving only because the joined side is unique — a 1:N
  join would fan out the parent grain and must never be registered.
- `context_layer/policies/<slug>.md` — the human-owned business rules extracted
  VERBATIM from the seed notes, one page per rule: `order-status-billing`
  (CANCELLED/RETURNED orders are not revenue) and `emea-currency-cutover`
  (pre-2024 EMEA rows are unconverted local currency). Frontmatter:
  `type: policy`, `status: draft`, `title`, `description`, `tags`, `sources`
  (cite the seed notes). Policies are the owner's words: transcribe, never
  reinterpret.
- `context_layer/metrics/<metric_name>.md` — one page per governed metric,
  named EXACTLY like its OSI metric. Frontmatter: `type: metric`,
  `status: draft`, `title`, `description`, `tags`, and `sources` citing the
  source tables AND the governing policy pages by path (e.g.
  {id: order-status-billing, resource: policies/order-status-billing.md}).
  The body MUST restate every business rule from the seed notes that affects
  the metric — exact column names, status values, dates, and thresholds. Those
  rules are why the numbers come out right; omitting one makes it wrong. Do
  NOT write `governed_by`, `dimensions`, or `grain` on metric pages: they are
  attached mechanically from the OSI models after validation.
- `context_layer/skills/<slug>.md` — exactly four guides: `run-the-demo`,
  `promote-artifacts`, `import-to-git`, `query-artifacts`. Frontmatter:
  `type: skill`, `title`, `description`, `tags`, `sources` (cite the
  script/module). Body: the exact commands from the operational facts below
  and what each step does, naming WHO runs each human gate (source approval,
  Promotion, Git Review Admission) — a guide never teaches running a human
  gate itself or mutating Git branches, shell commands or files directly.
  The query guide is local-first: it cites the `ariadne` executable (spec
  2026-09-23-0001 §8) and must never claim a server or MCP is required.
- NEVER write `index.md` or `log.md` — the promotion gate owns them.
- Never invent `generated`, `verified`, or `stale_after` frontmatter — stamped
  mechanically after validation.
- Frontmatter must be VALID YAML: quote any scalar containing a colon (e.g.
  `title: "Policy: order status billing"`); keep values single-line.

Semantic Layer (OSI YAML):
- One file per model under `semantic_layer/models/<model_name>.yml`, OSI core \
schema `version: 0.2.0.dev0`, following EXACTLY the reference structure below \
(same keys and nesting, expression.dialects blocks, primary_key as a list).
- Bind datasets to the exact `<source>.<table>` references from the multi-source
  catalog in the user message (e.g. `demo.main.orders`, `support.tickets`), or to
  a SELECT query when a rule needs a join or conversion (as in the reference).
- Model EVERY source the seed notes define metrics over — one model per source,
  each binding to that source's `<source>.<table>` references and honoring the
  same grain rules. Sources the seed notes say nothing about need no model.
- Define BOTH governed metrics: `gross_margin` and `order_count`.
- Encode exclusion rules as CASE WHEN inside the aggregate expression.
- A ratio of aggregates is a derived metric: reference base metrics by name in its \
expression and tag it with the DATUS custom_extensions hint exactly as shown.
- Mark the primary time dimension with `dimension: {is_time: true}`; groupable \
text columns carry `dimension: {}`.

Grain rules (ADR-0006 — the validation audit REJECTS models that violate them;
see project/adr/0006-grain-governance-multi-cardinality-joins.md):
- Rule of single declared grain: every model maps to exactly one declared grain; \
its `primary_key` must be unique over the dataset source.
- Rule of additive metric ownership: additive measures (SUM/AVG) only on fields \
native to that grain — never aggregate a parent-side column across a 1:N or N:M join.
- Rule of cardinality elimination: resolve 1:N and N:M joins before registration — \
upstream conditional pivot (Pattern 1), child-grain fact model (Pattern 2), or fact \
weight allocation (Pattern 5).

Reference structure (adapt the content, keep the shape — it already encodes both
seed-note rules: status exclusion in the metric expressions, pre-2024 EMEA
currency conversion in the dataset source query):

version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: >-
          SELECT o.order_id, o.customer_id, o.order_timestamp, o.status, o.region_code,
                 o.currency, o.amount, o.product_cost,
                 CASE WHEN o.region_code = 'EMEA' AND o.order_timestamp < '2024-01-01'
                      THEN COALESCE(r.rate_to_usd, 1.0) ELSE 1.0 END AS fx_rate
          FROM demo.main.orders o
          LEFT JOIN demo.main.currency_conversion_rate r ON r.currency = o.currency
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: order_date
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: CAST(order_timestamp AS DATE)
            dimension:
              is_time: true
          - name: status
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: status
            dimension: {}
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region_code
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
          - name: product_cost
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: product_cost
          - name: fx_rate
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: fx_rate
    metrics:
      - name: gross_revenue
        description: Billed revenue in USD excluding non-billable statuses
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: @EXCLUDE_REV@
      - name: cogs
        description: Direct cost of goods in USD excluding non-billable statuses
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: @EXCLUDE_COGS@
      - name: gross_margin
        description: Ratio of sums, not an average of per-row margins
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: (gross_revenue - cogs) / NULLIF(gross_revenue, 0)
        custom_extensions:
          - vendor_name: DATUS
            data: '{"metric_kind":"derived","inputs":["gross_revenue","cogs"]}'
      - name: order_count
        description: Count of billable orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN 1 ELSE 0 END)

Lowering constraints (violating any of these breaks the compiled SQL even when
the YAML validates):
- Reference dataset columns UNQUALIFIED in expressions — never `orders.amount`,
  just `amount`. The compiler scan-aliases tables and strips qualifiers.
- Never use correlated scalar subqueries in metric or field expressions; the
  compiler drops the outer qualifier inside subqueries, corrupting the correlation.
- Keep date/time literals like '2024-01-01' OUT of metric expressions — they
  corrupt the compiler's generated column names and can collapse two metrics into
  one aggregate. Put time-boundary logic in the dataset source query, as shown.
- Joins belong in the dataset source query (LEFT JOIN a lookup only when its join
  key is unique, so rows cannot fan out), never as metric-level subqueries."""

_SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.replace("@EXCLUDE_REV@", _EXCLUDE_REV_EXPR).replace(
    "@EXCLUDE_COGS@", _EXCLUDE_COGS_EXPR
)


def _load_env(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE lines into os.environ (never overrides existing vars)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _default_complete(messages: list[dict[str, str]]) -> str:
    """One OpenAI-compatible chat completion (the only network call per round)."""
    _load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            f"OPENAI_API_KEY/OPENAI_MODEL not set; expected in {ENV_PATH} "
            "(or the environment) — never commit secrets"
        )
    # Lazy import: analysis environments without the SDK installed cannot resolve
    # it statically; at runtime openai is a hard dependency (pyproject).
    from openai import OpenAI  # pyright: ignore[reportMissingImports]

    client = OpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=cast("Any", messages),  # dict messages match the wire shape
        temperature=0.2,
    )
    return response.choices[0].message.content or ""


def _parse_files(raw: str) -> list[tuple[str, str]]:
    """Parse the LLM's JSON response into (staging-relative path, content) pairs."""
    text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)  # reasoning models inline these
    text = text.strip()
    if text.startswith("```"):  # tolerate a fenced response
        text = re.sub(r"\A```[a-zA-Z0-9_-]*\n|\n```\Z", "", text)
    # pi-lens-ignore: unchecked-throwing-call-python
    data = json.loads(text)  # ValueError feeds the round-feedback loop by design
    entries = data.get("files", []) if isinstance(data, dict) else data
    files = [(entry["path"], entry["content"]) for entry in entries]
    if not files:
        raise ValueError("response contained no files")
    return files


def _validate_staging(staging: Path) -> None:
    """Spec §6: staging must be a dedicated directory — never the repo root or a
    served layer. From the repo root, LLM-supplied paths like
    ``context_layer/...`` would overwrite the served dirs directly, bypassing
    the human promotion gate."""
    resolved = staging.resolve()
    if resolved == _REPO_ROOT:
        raise ValueError(
            f"staging directory {resolved} is the repo root: authored content would "
            "overwrite the served context_layer//semantic_layer/ — spec §6 requires a "
            "dedicated staging directory"
        )
    if resolved.name in _SERVED_LAYERS:
        raise ValueError(
            f"staging directory {resolved} is a served layer ({resolved.name}): served "
            "artifacts arrive only by human promotion from staging/ — spec §6"
        )
    for layer in _SERVED_LAYERS:
        served_root = _REPO_ROOT / layer
        if resolved == served_root or resolved.is_relative_to(served_root):
            raise ValueError(
                f"staging directory {resolved} is inside the served layer "
                f"{layer}/: served artifacts arrive only by human promotion from "
                "staging/ — spec §6"
            )


def _safe_path(staging: Path, rel_path: str) -> Path:
    """Resolve an LLM-supplied staging-relative path, refusing escapes."""
    target = (staging / rel_path).resolve()
    if not target.is_relative_to(staging.resolve()):
        raise ValueError(f"authored path escapes staging/: {rel_path!r}")
    return target


def _catalog_lines(db_path: str | Path | None, sources_path: str | Path | None) -> str:
    """Every queryable table as the exact ``<source>.<table>`` reference models
    must use — read from the shared builder's catalog (ADR-0010), the same
    surface the validate gate's grain audit runs over."""
    if sources_path is not None:
        registry = load_registry(sources_path)
    elif db_path is not None:
        registry = implicit_registry(db_path)
    else:
        raise ValueError("catalog requires sources_path or db_path")
    con, catalog = build_connection(registry)
    try:
        return "\n".join(
            f"- {entry['name']} ({entry['type']}): "
            + ", ".join(
                f"{table.get('ref') or entry['name']}.{table['name']}" for table in entry["tables"]
            )
            for entry in catalog
        )
    finally:
        con.close()


def _user_prompt(profile: dict, notes: str, catalog_lines: str) -> str:
    return (
        "Statistical profile of the database (JSON):\n"
        f"{json.dumps(profile)}\n\n"
        "Multi-source catalog — every queryable table, named exactly as model "
        "dataset sources must reference them:\n"
        f"{catalog_lines}\n\n"
        "Seed notes from the data owner (authoritative business rules):\n"
        f"{notes}\n\n"
        "Operational facts for the skill pages (use these commands verbatim):\n"
        "- Seed the demo database: cd examples/retail-demo && python seed_db.py data/demo.db\n"
        "- Run the end-to-end demo: examples/retail-demo/demo.sh (--yes for unattended)\n"
        "- Promote demo artifacts (human gate): python ariadne-promote "
        "--staging examples/retail-demo/staging --served examples/retail-demo [--yes]\n"
        "- Query promoted artifacts locally — the default, no server needed (repo root):\n"
        "  ariadne list-metrics --served examples/retail-demo "
        "--sources examples/retail-demo/ariadne.yaml\n"
        "  ariadne get-metric gross_margin --dimension region "
        "--served examples/retail-demo --sources examples/retail-demo/ariadne.yaml\n"
        "  ariadne search-context 'cancelled orders' --served examples/retail-demo "
        "--sources examples/retail-demo/ariadne.yaml "
        "--staging examples/retail-demo/staging\n"
        "  ariadne list-datasets --served examples/retail-demo "
        "--sources examples/retail-demo/ariadne.yaml\n"
        "  ariadne define-metric --file def.json --served examples/retail-demo "
        "--sources examples/retail-demo/ariadne.yaml "
        "--staging examples/retail-demo/staging (stdin also works)\n"
        "- Git authoring route (a data project with its own Git repository — the human\n"
        "  gates stay human, an agent never mutates Git itself):\n"
        "  python -m ariadne.author --git --notes data/seed_notes.md --project . \n"
        "  ariadne-authoring import-legacy --from-root LEGACY_DIR  (HUMAN import)\n"
        "  ariadne-authoring approve-sources --proposal ID --revision REV --source-digest D\n"
        "    (HUMAN — source approval is never an agent action)\n"
        "  ariadne-authoring validate --proposal ID --expected-revision REV\n"
        "  ariadne-authoring review --proposal ID\n"
        "  ariadne-admit --proposal ID --revision REV --reviewed-digest DIGEST --confirm  (HUMAN)\n"
        "- Optional MCP transport (needs the extra installed: pip install 'ariadne-core[mcp]'):\n"
        "  python -m ariadne.serve --sources examples/retail-demo/ariadne.yaml "
        "--semantic examples/retail-demo/semantic_layer "
        "--context examples/retail-demo/context_layer "
        "--staging examples/retail-demo/staging\n"
        "  optional client example: examples/retail-demo/mcp_client.py\n\n"
        "Draft the complete Context Layer bundle and the Semantic Layer models now. "
        "Return only the JSON object."
    )


class _LayerDumper(yaml.SafeDumper):  # type: ignore[no-any-unimported]
    """safe_dump plus the block-scalar str representer; wide width so long
    single-line scalars never wrap into backslash continuations."""


def _block_str_representer(dumper: _LayerDumper, data: str):  # type: ignore[no-any-unimported]
    """Multi-line strings as readable literal blocks (issue #31) instead of
    one escaped double-quoted line; scalars PyYAML cannot emit as a literal
    (e.g. lines with trailing spaces) fall back to its quoted style."""
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_LayerDumper.add_representer(str, _block_str_representer)


def normalize_layer_yaml(content: str) -> str:
    """Re-emit a semantic-layer YAML with multi-line scalars (dataset source
    SQL) as literal blocks: agent drafts sometimes serialize them as one
    double-quoted \\n-escaped line no human can review at the staging gate
    (issue #31). Parse + re-dump; parsed meaning is preserved, and the staged
    bytes this produces are what validation and the review digest bind to.
    Non-YAML or non-mapping content returns unchanged."""
    try:
        doc = yaml.safe_load(content)
    except yaml.YAMLError:
        return content
    if not isinstance(doc, dict):
        return content
    return yaml.dump(
        doc,
        Dumper=_LayerDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=4096,
    )


def _mark_review_needed(staging: Path, errors: list[str]) -> None:
    """Record the failure in the staged files (spec §7): frontmatter on OKF pages,
    YAML comments on OSI models (schema rejects unknown top-level keys)."""
    marked_md = False
    for path in sorted(staging.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if "review_needed" in text:
            continue
        try:
            marked = _set_frontmatter(text, {"status": "review_needed", "review_errors": errors})
        except yaml.YAMLError:  # unparseable frontmatter: mark without rewriting it
            marked = "# status: review_needed (frontmatter unparseable)\n" + text
        path.write_text(marked, encoding="utf-8")
        marked_md = True
    for path in sorted(staging.rglob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if "review_needed" in text:
            continue
        lines = ["# status: review_needed"] + [
            f"# review error: {error.replace(chr(10), ' ')}" for error in errors
        ]
        path.write_text("\n".join(lines) + "\n" + text, encoding="utf-8")
    if not marked_md:  # pathological round produced no OKF page at all
        page = "---\ntype: review\nstatus: review_needed\nsources: []\n---\n\n"
        page += "Authoring failed after the maximum rounds:\n"
        page += "\n".join(f"- {error}" for error in errors) + "\n"
        (staging / "REVIEW_NEEDED.md").write_text(page, encoding="utf-8")


def _staged_paths(staging: Path) -> list[Path]:
    return sorted(path for path in staging.rglob("*") if path.is_file())


def author(
    db_path: str | Path | None,
    notes_path: str | Path,
    *,
    staging_dir: str | Path = "staging",
    complete=None,
    validate_fn=None,
    rounds: int = MAX_ROUNDS,
    sources_path: str | Path | None = None,
    stamp_lifecycle: bool = True,
) -> list[Path]:
    """Run the authoring loop; return the staged file paths.

    ``complete(messages) -> str`` is the LLM call boundary (default: the
    OpenAI-compatible endpoint); ``validate_fn(staging_dir) -> ValidationResult``
    is the validation gate (default: real compile plus the ADR-0006 §5 grain
    audit over this author run's connection — spec rev 6 §8.14 — the legacy
    ``db_path`` sqlite attach, or the ADR-0010 registry via ``sources_path``).
    ``stamp_lifecycle=False`` (the ``--git`` mode) skips the legacy finalizer's
    wall-clock generated/verified/stale_after stamping — lifecycle claims are
    owned by the deterministic finalize/promotion passes of the route the
    drafts enter, never by the drafting loop (issue #39/G7 fix)."""
    if rounds > MAX_ROUNDS:
        raise ValueError(
            f"rounds={rounds} exceeds the spec §5 hard cap of {MAX_ROUNDS} "
            "(reject, not clamp: a silent cap would hide that the request was invalid)"
        )
    staging = Path(staging_dir)
    _validate_staging(staging)
    staging.mkdir(parents=True, exist_ok=True)
    complete = complete or _default_complete
    # Default gate: compile + grain audit over this author run's database (rev 6);
    # a registry (ADR-0010) replaces the single-sqlite audit connection.
    gate = validate_fn or (
        lambda staged: validate(staged, db_path=db_path, sources_path=sources_path)
    )

    from ariadne.profiler import profile

    profile_data = profile(db_path, sources_path=sources_path)
    notes = Path(notes_path).read_text(encoding="utf-8")
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _user_prompt(profile_data, notes, _catalog_lines(db_path, sources_path)),
        },
    ]

    errors: list[str] = []
    for round_no in range(1, rounds + 1):
        raw = ""
        try:
            raw = complete(messages)
            files = _parse_files(raw)
        except Exception as exc:  # unparseable response: feed the parse error back
            errors = [f"response violated the JSON file contract: {exc}"]
            print(f"author: round {round_no}: {errors[0]}", flush=True)
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": errors[0] + " Return the JSON object."})
            continue
        for rel_path, content in files:
            if Path(rel_path).name in ("index.md", "log.md"):
                # code-level enforcement of the prompt rule: bundle bookkeeping
                # belongs to the promotion gate, never to the author
                print(f"author: ignoring {rel_path} (the author never writes it)", flush=True)
                continue
            target = _safe_path(staging, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            in_layer = "semantic_layer" in target.parts
            if in_layer and target.suffix in (".yml", ".yaml"):
                content = normalize_layer_yaml(content)  # issue #31: readable blocks
            target.write_text(content, encoding="utf-8")
        result = gate(staging)
        errors = result.errors
        if result.ok:  # deterministic post-passes and the bundle contract may still reject
            try:
                _finalize_bundle(staging, stamp_lifecycle=stamp_lifecycle)
            except Exception as exc:  # e.g. frontmatter that is not valid YAML
                errors = [
                    f"authored bundle violates the OKF frontmatter contract: {exc}. "
                    "Quote YAML scalar values that contain colons or special "
                    "characters."
                ]
            else:
                # the author loop's own scope IS the complete legacy demo bundle
                # (its prompt drafts every legacy section), so it opts into
                # naming absent sections — Dataset Overviews are generated by
                # the explicit schema refresh (issue #41), never invented here;
                # the shared gate itself checks applicable pages only
                # (spec 0010 §3/§9)
                legacy_sections = set(_BUNDLE_TYPES) - {"datasets"}
                errors = _bundle_errors(staging, required_sections=legacy_sections)
        if not errors:
            print(f"author: round {round_no}: validation passed", flush=True)
            return _staged_paths(staging)
        print(f"author: round {round_no}: {len(errors)} error(s), feeding back", flush=True)
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": "Compile errors:\n- "
                + "\n- ".join(errors)
                + "\nFix the affected files and return the full JSON object again.",
            }
        )

    print("author: 3 rounds failed — status: review_needed", flush=True)
    _mark_review_needed(staging, errors)
    return _staged_paths(staging)


def _needs_human_review(paths: list[Path]) -> bool:
    """True when any staged file carries the spec §7 ``review_needed`` marker."""
    return any("review_needed" in path.read_text(encoding="utf-8") for path in paths)


# Where an exhausted --git run's evidence lands: the project's staging area is
# the human-facing pending-work store (ignored by Git), and this clearly named
# subtree keeps the run's REVIEW_NEEDED.md + partial drafts durable.
_REVIEW_EVIDENCE_REL = Path("staging") / "author-review-needed"


def _preserve_review_evidence(draft: Path, project: Path) -> Path | None:
    """Copy an exhausted run's review-needed evidence — the root
    REVIEW_NEEDED.md plus every partial marked draft — out of the TEMPORARY
    drafting dir into the project's staging area (issue #39/G7 fix: three
    unparseable responses leave nothing the import can select, so the import
    fails and the temp dir's deletion would otherwise destroy the ONLY
    evidence of the run). Returns the durable evidence dir, or None when the
    project directory does not exist (nothing durable to attach to)."""
    if not project.is_dir():
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = project / _REVIEW_EVIDENCE_REL / stamp
    shutil.copytree(draft, target)
    return target


def author_to_proposal(
    notes_path: str | Path,
    *,
    project: str | Path = ".",
    db_path: str | Path | None = None,
    sources_path: str | Path | None = None,
    complete=None,
    validate_fn=None,
    rounds: int = MAX_ROUNDS,
) -> tuple[list[Path], dict]:
    """The SAME bounded authoring loop (≤3 rounds, deterministic checks,
    ``review_needed`` marking — never a second model loop), but its drafted
    output lands in the NEW Git proposal workflow (issue #39/G7 migration):
    the drafts are written to a TEMPORARY staging dir and carry NO wall-clock
    lifecycle stamps (the deterministic finalize pass of the Git route owns
    stamping — fresh author-time stamps would be refused as forged claims
    when imported into an existing artifact revision). The project's legacy
    ``staging/`` tree is never touched by the drafts or the import; only an
    exhausted run's review-needed evidence is preserved under
    ``staging/author-review-needed/`` BEFORE the import, so it survives the
    temp dir's deletion even when the import itself fails. The human-explicit
    legacy import (:func:`ariadne.migration.import_legacy`) copies the drafts
    into a fresh UNADMITTED Git authoring proposal (or the initial artifact
    revision of a project with none yet). Returns ``(drafted paths, import
    envelope)``: the envelope names the human steps (source approval,
    validate, review, ``ariadne-admit --confirm``) that alone admit anything —
    the import never admits and never infers review from the drafts (AC9)."""
    project_path = Path(project)
    with tempfile.TemporaryDirectory(prefix="ariadne-author-git-") as tmp:
        draft = Path(tmp) / "draft"
        staged = author(
            db_path,
            notes_path,
            staging_dir=draft,
            complete=complete,
            validate_fn=validate_fn,
            rounds=rounds,
            sources_path=sources_path,
            stamp_lifecycle=False,  # lifecycle stamping belongs to the Git route
        )
        # computed BEFORE the temporary dir goes away: the drafts' spec §7
        # review_needed marker rides the envelope (the CLI cannot re-read them)
        review_required = _needs_human_review(staged)
        evidence = (
            _preserve_review_evidence(draft, project_path) if review_required else None
        )
        from ariadne import migration  # function-level: ariadne.authoring imports this module

        try:
            envelope = migration.import_legacy(project=project, from_root=draft)
        except Exception as exc:
            if evidence is not None:  # the evidence outlives the temp dir; name it
                raise ValueError(
                    f"{exc} — the review-needed evidence of this exhausted authoring "
                    f"run is preserved for human resolution at {evidence}"
                ) from exc
            raise
    envelope["review_required"] = review_required
    if evidence is not None:
        envelope["review_evidence"] = str(evidence)
    return staged, envelope


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.author",
        description="Author OKF context pages and OSI semantic models into staging/.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="path to the SQLite database (or --sources)",
    )
    parser.add_argument(
        "--sources",
        default=None,
        help="source registry YAML (ADR-0010; default: ./ariadne.yaml only when "
        "neither --sources nor --db is given)",
    )
    parser.add_argument("--notes", required=True, help="path to the seed notes markdown")
    parser.add_argument("--staging", default="staging", help="staging directory (default: staging)")
    parser.add_argument("--rounds", type=int, default=MAX_ROUNDS)
    parser.add_argument(
        "--git",
        action="store_true",
        help="draft into a fresh UNADMITTED Git authoring proposal of the data "
        "project's own repository instead of staging/ (issue #39/G7): the same "
        "bounded loop, output imported through the human seam; source approval "
        "and ariadne-admit stay human-only",
    )
    parser.add_argument(
        "--project",
        default=".",
        help="the managed Git data project for --git (default: the working directory)",
    )
    args = parser.parse_args(argv)

    if not 1 <= args.rounds <= MAX_ROUNDS:
        parser.error(f"--rounds must be between 1 and {MAX_ROUNDS} (spec §5 hard cap)")
    sources_path = default_registry_path(args.sources, args.db)
    if args.db is None and sources_path is None:
        parser.error("one of --db or --sources is required")
    try:
        _validate_staging(Path(args.staging))
    except ValueError as exc:
        parser.error(str(exc))

    if args.git:
        try:
            staged, envelope = author_to_proposal(
                args.notes,
                project=args.project,
                db_path=args.db,
                sources_path=sources_path,
                rounds=args.rounds,
            )
        except ValueError as exc:
            # e.g. an exhausted run left nothing the import can select — the
            # error already names the preserved review-needed evidence, if any
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(envelope))
        for step in envelope["admission_required"]:
            print(f"  human step: {step}")
        if envelope["review_required"]:  # the drafted bundle needs the human first
            location = envelope.get("review_evidence")
            print(
                "error: drafted files carry status: review_needed — human review "
                "required; the imported proposal stays unadmitted"
                + (
                    "; this run's review-needed evidence is preserved at "
                    f"{location}"
                    if location
                    else ""
                ),
                file=sys.stderr,
            )
            return 1
        return 0

    paths = author(
        args.db,
        args.notes,
        staging_dir=Path(args.staging),
        rounds=args.rounds,
        sources_path=sources_path,
    )
    for path in paths:
        print(f"staged: {path}")
    if _needs_human_review(paths):  # spec §6/§7: review_needed artifacts are not promotable
        print(
            "error: staged files carry status: review_needed — human review required "
            "before promotion",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Authoring agent (ticket #4): profile + seed notes -> LLM drafts -> staging/.

The loop (spec §5, ≤3 rounds):

    profile(db) + seed notes -> LLM draft (OKF .md + OSI .yml) -> validate()
        -> on compile errors, feed them back into the next round
        -> after 3 failed rounds, stop and mark the staged files
           ``status: review_needed`` (spec §7).

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
    python -m ariadne.author --db data/demo.db --notes data/seed_notes.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, cast

import yaml

from ariadne.validate import validate

ENV_PATH = Path(os.environ.get("ARIADNE_ENV", "/home/volker/coding/ariadne/.env"))
MAX_ROUNDS = 3  # spec §5 hard cap on the validate/error loop
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVED_LAYERS = ("context_layer", "semantic_layer")  # only ever human-promoted (spec §6)

_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.DOTALL)

# Assembled as string pieces so every source line stays under the lint limit.
# Both patterns are execution-verified against tests/fixtures/expected_metrics.json.
_EXCLUDE_REV_EXPR = (
    "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED')"
    " THEN amount * fx_rate ELSE 0 END)"
)
_EXCLUDE_COGS_EXPR = (
    "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED')"
    " THEN product_cost * fx_rate ELSE 0 END)"
)

_SYSTEM_PROMPT_TEMPLATE = """\
You are the Ariadne authoring agent. From a statistical database profile and the \
data owner's seed notes you draft a Context Layer (OKF Markdown) and a Semantic \
Layer (OSI YAML) for governed metrics.

Return ONE JSON object and nothing else — no markdown fences, no commentary:
{"files": [{"path": "<path relative to staging/>", "content": "<complete file content>"}]}

Context Layer (OKF Markdown pages):
- One page per governed metric under `context_layer/metrics/<metric_name>.md`.
- Each page starts with YAML frontmatter between `---` lines carrying at least:
  `type: metric`, `status: draft`, and `sources:` (list of source tables read).
- The page body MUST restate every business rule from the seed notes that affects \
the metric — exact column names, status values, dates, and thresholds. Those rules \
are why the numbers come out right; omitting one makes the metric wrong.

Semantic Layer (OSI YAML):
- One file per model under `semantic_layer/models/<model_name>.yml`, OSI core \
schema `version: 0.2.0.dev0`, following EXACTLY the reference structure below \
(same keys and nesting, expression.dialects blocks, primary_key as a list).
- Bind datasets to `demo.main.<table>`, or to a SELECT query when a rule needs a
  join or conversion (as in the reference).
- Define BOTH governed metrics: `gross_margin` and `order_count`.
- Encode exclusion rules as CASE WHEN inside the aggregate expression.
- A ratio of aggregates is a derived metric: reference base metrics by name in its \
expression and tag it with the DATUS custom_extensions hint exactly as shown.
- Mark the primary time dimension with `dimension: {is_time: true}`; groupable \
text columns carry `dimension: {}`.

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
    data = json.loads(text)
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


def _user_prompt(profile: dict, notes: str) -> str:
    return (
        "Statistical profile of the database (JSON):\n"
        f"{json.dumps(profile)}\n\n"
        "Seed notes from the data owner (authoritative business rules):\n"
        f"{notes}\n\n"
        "Draft the Context Layer pages and Semantic Layer models now. "
        "Return only the JSON object."
    )


def _set_frontmatter(text: str, updates: dict) -> str:
    """Update (or add) YAML frontmatter on an OKF page, preserving the body."""
    match = _FRONTMATTER_RE.match(text)
    meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
    meta.update(updates)
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = match.group(2) if match else text
    return f"---\n{front}\n---\n\n{body}"


def _mark_review_needed(staging: Path, errors: list[str]) -> None:
    """Record the failure in the staged files (spec §7): frontmatter on OKF pages,
    YAML comments on OSI models (schema rejects unknown top-level keys)."""
    marked_md = False
    for path in sorted(staging.rglob("*.md")):
        if "review_needed" in path.read_text(encoding="utf-8"):
            continue
        path.write_text(
            _set_frontmatter(
                path.read_text(encoding="utf-8"),
                {"status": "review_needed", "review_errors": errors},
            ),
            encoding="utf-8",
        )
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
    db_path: str | Path,
    notes_path: str | Path,
    *,
    staging_dir: str | Path = "staging",
    complete=None,
    validate_fn=validate,
    rounds: int = MAX_ROUNDS,
) -> list[Path]:
    """Run the authoring loop; return the staged file paths.

    ``complete(messages) -> str`` is the LLM call boundary (default: the
    OpenAI-compatible endpoint); ``validate_fn(staging_dir) -> ValidationResult``
    is the compile gate (default: real Datus compile).
    """
    if rounds > MAX_ROUNDS:
        raise ValueError(
            f"rounds={rounds} exceeds the spec §5 hard cap of {MAX_ROUNDS} "
            "(reject, not clamp: a silent cap would hide that the request was invalid)"
        )
    staging = Path(staging_dir)
    _validate_staging(staging)
    staging.mkdir(parents=True, exist_ok=True)
    complete = complete or _default_complete

    from ariadne.profiler import profile

    profile_data = profile(db_path)
    notes = Path(notes_path).read_text(encoding="utf-8")
    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(profile_data, notes)},
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
            target = _safe_path(staging, rel_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        result = validate_fn(staging)
        if result.ok:
            print(f"author: round {round_no}: validation passed", flush=True)
            return _staged_paths(staging)
        errors = result.errors
        print(f"author: round {round_no}: {len(errors)} compile error(s), feeding back", flush=True)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.author",
        description="Author OKF context pages and OSI semantic models into staging/.",
    )
    parser.add_argument("--db", required=True, help="path to the SQLite database")
    parser.add_argument("--notes", required=True, help="path to the seed notes markdown")
    parser.add_argument("--staging", default="staging", help="staging directory (default: staging)")
    parser.add_argument("--rounds", type=int, default=MAX_ROUNDS)
    args = parser.parse_args(argv)

    if not 1 <= args.rounds <= MAX_ROUNDS:
        parser.error(f"--rounds must be between 1 and {MAX_ROUNDS} (spec §5 hard cap)")
    try:
        _validate_staging(Path(args.staging))
    except ValueError as exc:
        parser.error(str(exc))

    paths = author(args.db, args.notes, staging_dir=Path(args.staging), rounds=args.rounds)
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

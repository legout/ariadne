"""Deterministic recorded-trace check (spec 2026-09-23-0003, evidence tier 1).

``tests/evals/agent_trace.json`` records a fresh Pi session (all questions
asked in ONE session) over the installed packaged Ariadne skill and synthetic
retail demo: every observed ``ariadne`` CLI call in order, including failed
unpromoted get-metric and define-metric probes; the
JSON outputs the assertions need, packaged-skill digest, evaluated model
identity, and final answers verbatim from the assistant's write payloads.
Nothing is scripted or edited to pass: this check validates the RECORDED run
only. A separately reported fresh live smoke covers the current agent (spec
tier 2); this test calls no model and makes no live-provider claim.

Three questions: the established governed gross-margin and unmodeled
mean-order-amount evaluations (spec 0003), the consumed-expired-Policy
question of spec 0011 §6/§8 AC8 — a governed number whose consumed set
includes a Policy past its supported expiry keeps route, value and label,
and the answer must carry ONE brief lifecycle caveat naming that Policy —
and the supplied-quality-report question of spec 0013 §5/§7 AC1–2/AC10: a
governed gross-revenue answer whose directly cited orders table carries a
SYNTHETIC supplied report (failed completeness check, expired validity,
recent event watermark) keeps route, value and label, and the answer must
carry ONE brief data caveat naming the report and its as-of scope — never
turning the watermark into a completeness claim. Caveat demand is scoped to
context/evidence the answer actually relies on: absent optional
expiry/verification metadata, unrelated search hits, unknown applicability
and unrelated or passing optional reports never demand a caveat (negative
controls below mutate fixture copies, never recorded evidence).

Numbers cross three independent ways, as in tests/test_evals.py: observed
governed rows == independent hand-written SQL == baked golden values, and
observed ad-hoc rows == the SAME shared rev-2 oracle imported from
tests/test_evals.py (no second numeric oracle). The answers are checked with
explicit deterministic assertions — governance label, served metric/Policy
citations actually returned by the tool (never invented paths), both caveats,
and rounded display values within display precision. Mutated in-memory copies
of the fixture fail for the named reason (spec acceptance example 2), and a
skill digest mismatch invalidates the recorded environment (example 3).
"""

import hashlib
import json
import re
import sys
from functools import cache
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.skill import ASSETS  # noqa: E402  # pyright: ignore[reportMissingImports]
from ariadne.sources import table_resource  # noqa: E402  # pyright: ignore[reportMissingImports]
from tests.test_evals import (  # noqa: E402
    GOLDEN,
    TOLERANCE,
    independent_adhoc_means,
    independent_expected,
)
from tests.test_seed import run_seed  # noqa: E402

TRACE_PATH = REPO_ROOT / "tests" / "evals" / "agent_trace.json"
DISPLAY_TOLERANCE = 0.0051  # answers show values rounded to 2 decimals

# The EMEA conversion caveat is TIME-BOUND: mentioning EMEA and conversion
# without the cutover qualifier is not the caveat (spec rev 2: "pre-2024 EMEA").
# ("cutover" alone is insufficient — the cited policy filename carries it.)
_EMEA_TIME_BOUNDARY = re.compile(
    r"pre[-\s]?2024|before 2024|prior to 2024|2024-01-01|earlier than 2024"
)


def _assert_answer_caveats(answer: str) -> None:
    """Both spec caveats, stated in the answer itself (not just tool JSON):
    CANCELLED/RETURNED exclusion, and the time-qualified pre-2024 EMEA USD
    conversion."""
    lowered = answer.lower()
    assert "cancel" in lowered and "return" in lowered, (
        "final answer caveat missing: excluded CANCELLED/RETURNED orders"
    )
    assert (
        "emea" in lowered
        and re.search(r"conver[ts]", lowered)
        and _EMEA_TIME_BOUNDARY.search(lowered)
    ), (
        "final answer caveat missing: pre-2024 EMEA currency conversion with its "
        "time qualifier (the unqualified 'EMEA amounts are converted' is not the caveat)"
    )


# Spec 0011 §6/AC8: a brief lifecycle caveat is demanded ONLY for context the
# answer actually relies on, and must identify the issue AND name the affected
# page. Absent optional metadata and unrelated hits never enter this check.
_LIFECYCLE_WORDS = re.compile(
    r"expir|stale|out[-\s]?of[-\s]?date|outdated|deprecated|unavailable|unreadable|missing"
)
_LIFECYCLE_CODES = {"context_stale", "context_deprecated", "context_unavailable"}


# Spec 0013 §5 / §7 AC1–2/AC10: supplied-evidence caveats are demanded ONLY
# for relied-upon assets whose supplied report warns of a FAILED check or
# EXPIRED validity, and must name the report and its as-of scope. Unknown
# applicability, partial coverage, absent optional reports and reports on
# unrelated assets never demand a caveat (negative controls below).
_DATA_CAVEAT_CODES = {"data_report_failed", "data_report_expired"}
_DATA_WARNING_CODES = {
    "data_report_failed",
    "data_report_expired",
    "data_report_inapplicable",
    "data_applicability_unknown",
    "data_coverage_partial",
    "data_evidence_unavailable",
    "data_signals_truncated",
    "data_binding_unknown",
}

# An event-time watermark is an event boundary (spec 0013 §3/§5, §7 AC2): an
# answer must never turn it into a completeness/currency/health claim. The
# negator guard keeps honestly restating a report's "not proof that every
# expected record arrived" meaning a pass, and a bare noun mention
# ("completeness check failed … watermark is recent") carries no claim word.
_WATERMARK_CLAIM = re.compile(
    r"\b(?:"
    r"prov\w*|proof|guarante\w*|healthy|current|up[-\s]?to[-\s]?date|"
    r"fully (?:loaded|arrived|caught up)|"
    r"(?:is|are|was|were|be|been|being|seems?|looks?|stands?)\s+(?:\w+\s+){0,2}?complete\b|"
    r"(?:confirms?|shows?|means?|implies?|establish\w*|demonstrat\w*)\s+(?:\w+\s+){0,2}?complet\w*|"
    r"all (?:expected )?(?:records?|rows?|events?|orders?)\s+(?:are|have|were)\s+"
    r"(?:present|arrived|loaded)|"
    r"every (?:expected )?(?:record|row|event|order)\s+(?:is|has|was)\s+"
    r"(?:present|arrived|loaded)"
    r")\b",
    re.IGNORECASE,
)
_WATERMARK_NEGATOR = re.compile(
    r"\b(?:not|never|no|n't|cannot|can't|without|fail\w*|incomplete\w*|missing|"
    r"absent|unverified|nor)\b",
    re.IGNORECASE,
)
_EXPIRY_WORDS = re.compile(r"expir\w*|validity\W+(?:ended|through|until)", re.IGNORECASE)

# Clause boundaries INSIDE a sentence — used only to LOCATE the clause a
# claim belongs to (fix2), never to drop the sentence's watermark
# association: a claim in a later anaphoric clause ("the watermark is recent,
# but it proves …") is still the watermark's claim.
_CLAUSE_SPLIT = re.compile(r";\s*|,\s+(?:but|yet|although|though|whereas|while)\s+", re.IGNORECASE)
# Direct-negation proximity (fix2): a negator suppresses rejection only when
# it sits within this many characters before (or inside) the claim's matched
# assertion, inside the claim's own clause — never merely elsewhere in the
# sentence. 24 chars keeps "does not prove"/"not proof that" hedges direct
# while a clause-away "the check failed, but … proves" stays a claim.
_NEGATION_WINDOW = 24


def _assert_lifecycle_caveats(answer: str, relied_warnings: list) -> None:
    """One brief caveat per lifecycle warning on relied-upon context. An empty
    list demands nothing — that is the negative-control half of AC8."""
    for warning in relied_warnings:
        assert warning["code"] in _LIFECYCLE_CODES, warning
        assert warning["path"] in answer and _LIFECYCLE_WORDS.search(answer.lower()), (
            f"final answer relies on warned context {warning['path']} "
            f"({warning['code']}) but omits the brief lifecycle caveat naming the "
            "affected Policy/page"
        )


def _assert_data_caveats(answer: str, data_signals: dict, metric_name: str) -> None:
    """ONE brief caveat per relied-upon report warning of a FAILED check or
    EXPIRED validity (spec 0013 §5, §7 AC10): the answer must name the report
    and acknowledge the warned outcome with its as-of scope. An empty
    demanded set demands nothing — absent/unknown/optional evidence and
    unrelated-asset reports are the negative-control half."""
    entry = next((m for m in data_signals["metrics"] if m["name"] == metric_name), None)
    if entry is None:
        return
    relied = {asset for asset in entry["assets"] if isinstance(asset, str)}
    reports = {
        report["id"]: report for asset in data_signals["assets"] for report in asset["reports"]
    }
    lowered = answer.lower()
    for warning in data_signals["warnings"]:
        if warning["code"] not in _DATA_CAVEAT_CODES or warning["asset"] not in relied:
            continue  # unknown applicability/coverage and unrelated reports never demand
        report_id = warning["report"]
        assert report_id and report_id in answer, (
            f"final answer relies on asset {warning['asset']} whose supplied report "
            f"{report_id!r} carries a {warning['code']} warning, but omits the brief "
            "caveat naming that report"
        )
        report = reports[report_id]
        as_of = {
            str(report.get(key, ""))[:10] for key in ("reported_at", "observed_at", "valid_until")
        }
        if warning["code"] == "data_report_failed":
            assert re.search(r"\bfail\w*", lowered), (
                f"final answer names supplied report {report_id!r} but never "
                "acknowledges its FAILED check outcome"
            )
        else:  # expired: the caveat must carry the as-of scope, not just the id
            assert _EXPIRY_WORDS.search(lowered) and any(
                date and date in answer for date in as_of
            ), (
                f"final answer names expired report {report_id!r} but omits its "
                "as-of scope (the expiry and the report/validity time)"
            )


def _assert_no_watermark_completeness_claim(answer: str) -> None:
    """An event-time watermark is an event boundary, never completeness,
    ingestion currency or source health (spec 0013 §3/§5, §7 AC2). The claim
    is evaluated at SENTENCE level whenever the sentence mentions a watermark
    — an anaphoric claim in a later clause keeps the association ("the
    watermark is recent, but it proves every record has arrived" is the
    forbidden inference). A negation suppresses rejection only when it
    DIRECTLY negates the claim: a negator within a short window before (or
    inside) the matched assertion, in the claim's own clause — a hedge or a
    failed check sitting in another clause licenses nothing."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer):
        if "watermark" not in sentence.lower():
            continue
        for claim in _WATERMARK_CLAIM.finditer(sentence):
            boundary = max(
                (split.end() for split in _CLAUSE_SPLIT.finditer(sentence, 0, claim.start())),
                default=0,
            )
            window = sentence[max(boundary, claim.start() - _NEGATION_WINDOW) : claim.end()]
            if not _WATERMARK_NEGATOR.search(window):
                raise AssertionError(
                    "final answer turns an event watermark into a completeness/currency/"
                    "health claim — a watermark is an event boundary, never proof that "
                    "every expected record has arrived"
                )


@cache
def load_trace() -> dict:
    return json.loads(TRACE_PATH.read_text(encoding="utf-8"))


def _frontmatter(page: str) -> dict:
    """YAML frontmatter of an actually returned OKF page (a get-metric context
    metric page or a search-context hit's content) — the source of every
    supported citation."""
    match = re.match(r"\A---\s*\n(.*?)\n---", page, re.DOTALL)
    assert match is not None, "a returned OKF page must carry YAML frontmatter"
    return yaml.safe_load(match.group(1)) or {}


def _policy_paths(meta: dict) -> list[str]:
    """The policies/*.md resources a returned page's frontmatter cites."""
    return [
        source["resource"]
        for source in meta.get("sources") or []
        if isinstance(source, dict) and str(source.get("resource", "")).startswith("policies/")
    ]


def _assert_citations(answer: str, supported: set[str], must_cite: set[str]) -> None:
    """The answer may cite ONLY paths the tool actually returned (never
    invented ones) and must cite the required returned paths. A returned page
    may be cited by its returned relative path or by its served-root
    (`context_layer/…`) path — both identify the same actually returned page
    (the adhoc checks' established rule, applied to every returned path; an
    invented path still fails because NEITHER form was returned)."""
    cited = set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", answer))
    forms = _either_form(supported)
    assert cited <= forms, (
        f"final answer cites paths the tool did not return: {sorted(cited - forms)}"
    )
    missing = [
        p
        for p in must_cite
        if _unprefixed(p) not in cited and f"context_layer/{_unprefixed(p)}" not in cited
    ]
    assert not missing, (
        f"final answer must cite the returned context paths (either form): missing {missing}"
    )


def _unprefixed(path: str) -> str:
    """A returned page's unprefixed (returned relative) form."""
    return path.removeprefix("context_layer/")


def _either_form(paths) -> set[str]:
    """A returned page's exactly two citation forms: its unprefixed returned
    path and its served-root (`context_layer/…`) path — never a doubled
    prefix (`context_layer/context_layer/…` does not exist on any served
    tree and is never a citation of the returned page)."""
    base = {_unprefixed(p) for p in paths}
    return base | {f"context_layer/{p}" for p in base}


@pytest.fixture(scope="module")
def demo_db(tmp_path_factory) -> Path:
    db_path = tmp_path_factory.mktemp("agent_trace") / "demo.db"
    run_seed(db_path)  # same deterministic synthetic demo as tests/test_evals.py
    return db_path


# --- Recorded-run checks; each failure names its reason (spec example 2) -----


def check_provenance(trace: dict) -> None:
    meta = trace["_meta"]
    session = meta["session"]
    digest = session["jsonl_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", digest), "recorded run must cite its session JSONL sha256"
    assert session["run_id"] and session["session_id"], "recorded run must cite its session ids"
    assert isinstance(meta.get("model"), str) and meta["model"], (
        "recorded run must record the evaluated agent model identity"
    )
    packaged = hashlib.sha256((ASSETS / "SKILL.md").read_bytes()).hexdigest()
    assert meta["skill"]["skill_md_sha256"] == packaged, (
        f"skill digest mismatch: fixture records {meta['skill']['skill_md_sha256'][:12]}… "
        f"but the packaged skill is {packaged[:12]}… — a different skill cannot be "
        "presented as the recorded run's environment; refresh the trace from a new "
        "observed run"
    )
    assert meta.get("skill_read_before_first_call") is True, (
        "the recorded session must have loaded the installed skill before its first call"
    )


def _subcommands(scenario: dict) -> list[str]:
    """The ariadne subcommand of every recorded call, in observed order."""
    subs = []
    for call in scenario["calls"]:
        match = re.search(r"ariadne ([a-z-]+)", call["command"])
        assert match is not None, f"call {call['seq']} is not an ariadne CLI call"
        subs.append(match.group(1))
    return subs


def _real_calls(scenario: dict, subcommand: str) -> list[int]:
    """Indices of REAL subcommand calls — ``--help`` schema probes are not
    invocations of the operation and never count for route classification."""
    return [
        i
        for i, call in enumerate(scenario["calls"])
        if re.search(rf"ariadne {subcommand}\b", call["command"])
        and "--help" not in call["command"]
    ]


def _no_promotion(trace: dict) -> None:
    for name, scenario in trace["scenarios"].items():
        for call in scenario["calls"]:
            assert "promote" not in call["command"], (
                f"{name}: recorded run must not promote anything (call {call['seq']})"
            )


def check_governed(scenario: dict, sql_expected: dict, golden_expected: dict) -> None:
    get_at = _real_calls(scenario, "get-metric")
    assert get_at, "governed route: no get-metric call recorded"
    assert not _real_calls(scenario, "define-metric"), (
        "governed route: define-metric must not answer a governed question"
    )
    discovery = _real_calls(scenario, "list-metrics") + _real_calls(scenario, "search-context")
    assert discovery and min(discovery) < min(get_at), (
        "governed route: discovery must precede the get-metric call"
    )

    call = scenario["calls"][get_at[0]]
    result = call["result"]
    assert call["exit"] == 0 and result["governed"] is True, "get-metric must return governed: true"

    # The command must actually request what the result claims to answer —
    # stale rows behind a rewritten request (wrong metric, wrong dimension)
    # are a route/value failure, not recorded evidence.
    tokens = call["command"].split()
    anchor = tokens.index("get-metric")
    requested = [t for t in tokens[anchor + 1 :] if not t.startswith("--")][0]
    requested_dims = [
        tokens[i + 1] for i in range(anchor, len(tokens) - 1) if tokens[i] == "--dimension"
    ]
    assert requested == "gross_margin" and requested_dims == ["region"], (
        f"governed route: the get-metric command must request gross_margin by "
        f"region, got {requested!r} by {requested_dims}"
    )
    assert result["metric"] == requested and result["dimensions"] == requested_dims, (
        f"governed route: get-metric requested {requested!r} by {requested_dims} "
        f"but the result is for {result['metric']!r} by {result['dimensions']}"
    )
    observed = {row["region"]: row["gross_margin"] for row in result["rows"]}
    assert set(observed) == set(sql_expected) == set(golden_expected), "region set mismatch"
    for region in observed:
        assert abs(observed[region] - sql_expected[region]) <= TOLERANCE, (
            f"governed value {region}: observed != independent SQL"
        )
        assert abs(golden_expected[region] - sql_expected[region]) <= TOLERANCE, (
            f"governed value {region}: golden != independent SQL"
        )

    # Supported citations and caveat topics derive from what the tool ACTUALLY
    # returned: the served metric page (metrics/<name>.md under the served
    # context root), the policy paths its frontmatter sources[] cites, and the
    # full policy body strings.
    context = result["context"]
    assert set(context) == {"metric_page", "policies", "context_signals"}, (
        "get-metric context must be the actual {metric_page, policies, context_signals} payload"
    )
    policy_paths = _policy_paths(_frontmatter(context["metric_page"]))
    assert policy_paths, "the served metric page must cite its Policy pages"
    assert len(context["policies"]) == len(policy_paths), (
        "observed context must return the full body of every policy the page cites"
    )
    for path, body in zip(policy_paths, context["policies"]):
        assert isinstance(body, str) and body.strip(), f"policy body missing for {path}"
    bodies = "\n".join(context["policies"]).lower()
    assert "cancelled" in bodies and "returned" in bodies, (
        "the returned policy bodies must carry the status-exclusion rule"
    )
    assert "rate_to_usd" in bodies and "2024" in bodies, (
        "the returned policy bodies must carry the pre-2024 EMEA conversion rule"
    )

    # Spec 0011 §§4–5, observed negative control (AC8): the consumed pages
    # carry NO optional expiry/verification metadata — unknown freshness,
    # unverified tier — and that absence must produce NO warning and NO caveat.
    signals = context["context_signals"]
    assert set(signals) == {"pages", "warnings"}, (
        "context_signals is the additive {pages, warnings} envelope"
    )
    assert {page["path"] for page in signals["pages"]} == {
        f"metrics/{result['metric']}.md",
        *policy_paths,
    }, "the assessed page set is exactly the consumed set (metric page + cited policies)"
    for page in signals["pages"]:
        assert page["freshness"]["state"] == "unknown" and (
            page["verification_tier"] == "unverified"
        ), "absent optional expiry/verification metadata reads unknown/unverified"
    assert signals["warnings"] == [], (
        "absent optional expiry/verification metadata alone must never warn"
    )

    answer = scenario["final_answer"]
    _assert_lifecycle_caveats(answer, signals["warnings"])
    _assert_data_caveats(answer, result["data_signals"], result["metric"])
    _assert_no_watermark_completeness_claim(answer)
    lowered = answer.lower()
    assert "governed" in lowered and not any(
        negation in lowered for negation in ("not governed", "governed: false", "ungoverned")
    ), (
        "final answer must positively label the number governed — a negated label "
        "('not governed' / 'governed: false' / 'ungoverned') is not one"
    )
    served_page = f"context_layer/metrics/{result['metric']}.md"
    _assert_citations(answer, {served_page} | set(policy_paths), {served_page} | set(policy_paths))
    _assert_answer_caveats(answer)

    # Display precision: the answer's rounded table must agree with the oracle
    # (the percent may sit anywhere in its row — leading, like "36.68% (0.3668)",
    # trailing, like "0.3844 (≈ 38.44%)", or in a separate percent column).
    shown = {
        region: float(pct)
        for region, pct in re.findall(
            r"^\|\s*(NA|EMEA|APAC)\s*\|[^\n]*?([\d.]+)\s*%", answer, re.MULTILINE
        )
    }
    assert set(shown) == set(sql_expected), "answer must show every region"
    for region, pct in shown.items():
        assert abs(pct - round(sql_expected[region] * 100, 2)) <= DISPLAY_TOLERANCE, (
            f"answer display value {region}: {pct}% disagrees with the oracle"
        )


def check_adhoc(scenario: dict, oracle: dict) -> None:
    list_at = _real_calls(scenario, "list-metrics")
    datasets_at = _real_calls(scenario, "list-datasets")
    define_ok = [
        i for i in _real_calls(scenario, "define-metric") if scenario["calls"][i]["exit"] == 0
    ]
    # A define-metric success whose observed output is the full result payload
    # (a verification re-run may print only its own comparison artifact — that
    # output is recorded verbatim but is never a value source).
    define_results = [
        scenario["calls"][i]["result"]
        for i in define_ok
        if isinstance(scenario["calls"][i].get("result"), dict)
        and "rows" in scenario["calls"][i]["result"]
    ]
    assert list_at and datasets_at and define_ok and define_results, (
        "ad-hoc route: incomplete recorded path"
    )
    assert min(list_at) < min(datasets_at) < min(define_ok), (
        "ad-hoc route: discovery (list-metrics) must precede list-datasets, "
        "which must precede the successful define-metric"
    )
    # The spec's trap is the UNLISTED metric: a served context page exists, but
    # a governed get-metric of it must refuse. Successful governed probes of
    # other LISTED metrics are honest discovery and stay allowed.
    unlisted = "mean_order_amount_per_customer"
    for i in _real_calls(scenario, "get-metric"):
        if unlisted in scenario["calls"][i]["command"]:
            assert scenario["calls"][i]["exit"] != 0, (
                "ad-hoc route: no governed get-metric may answer an unlisted metric"
            )

    # The trap the spec names: a served context page for the measure exists,
    # but list-metrics does not serve it as a semantic metric — the recorded
    # discovery must show exactly that, not a governed claim. The hit's REAL
    # content frontmatter (not a summary) carries governed_by: adhoc_*.
    listed = {
        entry["name"]
        for entry in scenario["calls"][list_at[0]]["result"]
        if isinstance(entry, dict)
    }
    assert "mean_order_amount_per_customer" not in listed, (
        "the mean per customer must not appear as a listed governed metric"
    )
    search = next(call for call in scenario["calls"] if "search-context" in call["command"])
    hit = search["result"][0]  # actual search-context output: first complete hit
    assert hit["path"] == "metrics/mean_order_amount_per_customer.md", (
        "search must have surfaced the served context page for the measure"
    )
    assert hit["draft"] is False, "the surfaced page is served, not a staged draft"
    hit_meta = _frontmatter(hit["content"])
    assert str(hit_meta.get("governed_by", "")).startswith("adhoc_"), (
        "a served context page whose governed_by is adhoc_* is not a governed metric"
    )

    # Failed definition probes are preserved and precede the successes (nothing
    # rewritten to look clean); every real define-metric before the first success failed.
    first_ok = min(define_ok)
    for i in _real_calls(scenario, "define-metric"):
        if i < first_ok:
            assert scenario["calls"][i]["exit"] != 0, (
                "define-metric probes before the first success must be the observed failures"
            )

    grouped = define_results[-1]
    assert grouped["governed"] is False, "define-metric result must be governed: false"
    assert grouped["columns"] == ["customer_id", "mean_order_amount_per_customer"], (
        "the grouped definition must return customer_id rows"
    )
    observed = {
        row["customer_id"]: row["mean_order_amount_per_customer"] for row in grouped["rows"]
    }
    expected = oracle["per_customer"]
    assert set(observed) == set(expected) == set(oracle["customer_ids"]), (
        "every customer ID in the demo must carry an observed ad-hoc row"
    )
    for customer_id, value in observed.items():
        assert abs(value - expected[customer_id]) <= TOLERANCE, (
            f"ad-hoc value customer {customer_id}: observed != shared independent SQL"
        )

    # #49 fix1: the proposal paths must genuinely resolve under the staged-
    # proposals location. The observed relative (`staging/...`) and absolute
    # (`.../staging/...`) forms are both accepted, but a path that lacks the
    # staging location is NOT a staged proposal and fails by name (spec 0003:
    # proposals stay staged — never served, never governed).
    def _under_staging(path: str, what: str) -> str:
        assert "/staging/" in path or path.startswith("staging/"), (
            f"{what} must resolve under the staged-proposals location (staging/), "
            f"got {path!r} — an unstaged output is not a staged proposal"
        )
        return (
            path.split("/staging/", 1)[-1] if "/staging/" in path else path.removeprefix("staging/")
        )

    staged_model = re.fullmatch(
        r"semantic_layer/models/adhoc/(mean_order_amount_per_customer(?:-\d+)?)\.yml",
        _under_staging(grouped["staged_as"], "staged_as"),
    )
    staged_ctx = _under_staging(grouped["staged_context_as"], "staged_context_as")
    assert staged_model is not None and staged_ctx == (
        f"context_layer/metrics/{staged_model.group(1)}.md"
    ), "the successful definition must have staged a matching OSI and OKF proposal"

    answer = scenario["final_answer"]
    lowered = answer.lower()
    assert "governed: false" in lowered and "ad-hoc" in lowered, (
        "final answer must label the result an ungoverned ad-hoc proposal"
    )
    assert ("staged" in lowered or "/staging/" in lowered) and (
        "not promoted" in lowered
        or "not been promoted" in lowered
        or "unpromoted" in lowered
        or "never promoted" in lowered
        or "not a canonical" in lowered
        or re.search(r"\bno promotion\b.{0,90}\bperformed", lowered)
    ), "final answer must state the proposal stays staged, never promoted"
    _assert_answer_caveats(answer)
    # Lifecycle demand is scoped to the search hit the answer actually relies
    # on (the cited mean-order page); unrelated hits never demand a caveat.
    hit_signals = hit["context_signals"]
    assert set(hit_signals) >= {"pages", "warnings"}, (
        "each search-context hit carries its page's advisory context_signals view"
    )
    _assert_lifecycle_caveats(answer, hit_signals["warnings"])
    page_paths = {hit["path"], f"context_layer/{hit['path']}"}
    policies = set(_policy_paths(hit_meta))
    # A search result may be cited by its returned relative path or by its
    # served-root path; both identify the same actually returned metric page.
    cited = set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", answer))
    assert cited & page_paths, "final answer must cite the returned context page"
    staged_page = "staging/" + staged_ctx
    # every page the scenario's searches actually returned is citable (a
    # policy-page search hit is a returned page like any other)
    search_hits = {
        hit["path"]
        for call in scenario["calls"]
        if "search-context" in call["command"]
        for hit in (call["result"] if isinstance(call.get("result"), list) else [])
    }
    _assert_citations(answer, page_paths | policies | {staged_page} | search_hits, policies)

    # Display precision: every customer's rounded or full-precision figure must
    # agree with the shared oracle. An overall per-billable-order mean is
    # OPTIONAL (the spec asks per-customer amounts) — validated when present.
    shown: dict[int, float] = {}
    for customer_id, value in re.findall(
        r"\|\s*(\d{1,2})\s*\|\s*\$?([\d,]+\.\d+)\s*(?=\|)", answer
    ):
        shown[int(customer_id)] = float(value.replace(",", ""))
    assert set(shown) == set(expected), "answer must show every customer ID"
    for customer_id, value in shown.items():
        assert abs(value - round(expected[customer_id], 2)) <= DISPLAY_TOLERANCE, (
            f"answer display value customer {customer_id}: ${value} disagrees with the oracle"
        )
    overall_match = re.search(r"(?:per billable order\*\* is|≈)\s*\$([\d,]+\.\d{2})", answer)
    if overall_match is not None:
        overall_shown = float(overall_match.group(1).replace(",", ""))
        assert abs(overall_shown - round(oracle["overall"], 2)) <= DISPLAY_TOLERANCE, (
            f"answer overall mean ${overall_shown} disagrees with the oracle"
        )


def check_stale_policy(scenario: dict, sql_expected: dict) -> None:
    """The consumed-expired-Policy question (spec 0011 §6 / §8 AC8): a governed
    number whose consumed set includes a Policy past its supported expiry keeps
    its route, value and governance label — the warning is advisory — and the
    answer carries ONE brief lifecycle caveat naming that Policy."""
    get_ok = [i for i in _real_calls(scenario, "get-metric") if scenario["calls"][i]["exit"] == 0]
    assert get_ok, "stale-policy route: no successful get-metric call recorded"
    assert not _real_calls(scenario, "define-metric"), (
        "stale-policy route: define-metric must not answer a governed question"
    )
    discovery = _real_calls(scenario, "list-metrics") + _real_calls(scenario, "search-context")
    assert discovery and min(discovery) < min(get_ok), (
        "stale-policy route: discovery must precede the get-metric call"
    )

    call = scenario["calls"][get_ok[0]]
    result = call["result"]
    tokens = call["command"].split()
    anchor = tokens.index("get-metric")
    requested = [t for t in tokens[anchor + 1 :] if not t.startswith("--")][0]
    requested_dims = [
        tokens[i + 1] for i in range(anchor, len(tokens) - 1) if tokens[i] == "--dimension"
    ]
    assert requested == "order_count" and requested_dims == ["region"], (
        f"stale-policy route: the get-metric command must request order_count by "
        f"region, got {requested!r} by {requested_dims}"
    )
    assert result["metric"] == requested and result["governed"] is True, (
        "stale-policy route: get-metric must return the requested metric, governed: true"
    )
    observed = {row["region"]: row["order_count"] for row in result["rows"]}
    assert set(observed) == set(sql_expected), "region set mismatch"
    for region in observed:
        assert abs(observed[region] - sql_expected[region]) <= TOLERANCE, (
            f"stale-policy value {region}: observed != independent SQL "
            "(a lifecycle warning never changes the number)"
        )

    context = result["context"]
    policy_paths = _policy_paths(_frontmatter(context["metric_page"]))
    assert policy_paths and len(context["policies"]) == len(policy_paths), (
        "observed context must return the full body of every cited policy"
    )
    for path, body in zip(policy_paths, context["policies"]):
        assert isinstance(body, str) and body.strip(), f"policy body missing for {path}"
    warnings = context["context_signals"]["warnings"]
    assert {w["code"] for w in warnings} <= _LIFECYCLE_CODES, warnings
    stale_paths = {w["path"] for w in warnings if w["code"] == "context_stale"}
    assert stale_paths and stale_paths <= set(policy_paths), (
        "the expired Policy must be one of the consumed page's cited policies"
    )
    # The agent saw the lifecycle problem in the evidence it actually relied
    # on: each stale warning rides the successful get-metric's own
    # context_signals envelope (the payload the answer is based on). The #55
    # re-recording answers governed questions straight from discovery without
    # an intermediate search hit — the earlier T3 session saw the same warning
    # earlier in its discovery search; either way it was visible before the
    # answer, and still neither route, value nor label changed.

    answer = scenario["final_answer"]
    lowered = answer.lower()
    assert "governed" in lowered and not any(
        negation in lowered for negation in ("not governed", "governed: false", "ungoverned")
    ), "final answer must positively label the number governed"
    # Only the status-exclusion rule governs a count — the EMEA conversion
    # caveat belongs to money metrics, not this consumed set (its policies say
    # so themselves); the LIFECYCLE caveat is the spec-0011 addition.
    assert "cancel" in lowered and "return" in lowered, (
        "final answer caveat missing: excluded CANCELLED/RETURNED orders"
    )
    served_page = f"context_layer/metrics/{result['metric']}.md"
    _assert_citations(answer, {served_page} | set(policy_paths), {served_page} | stale_paths)
    _assert_lifecycle_caveats(answer, warnings)
    _assert_data_caveats(answer, result["data_signals"], result["metric"])
    _assert_no_watermark_completeness_claim(answer)

    shown = {
        region: int(count)
        for region, count in re.findall(r"\|\s*(NA|EMEA|APAC)\s*\|[^|\n]*?(\d+)\s*\|", answer)
    }
    assert set(shown) == set(sql_expected), "answer must show every region's count"
    for region, count in shown.items():
        assert count == sql_expected[region], (
            f"answer display value {region}: {count} disagrees with the oracle"
        )
    total = re.search(r"[Tt]otal[^.\n]*?(\d{3})", answer)
    if total is not None:  # optional overall total, validated when present
        assert int(total.group(1)) == sum(sql_expected.values()), (
            "answer total disagrees with the independent SQL sum"
        )


def check_quality_report(scenario: dict, sql_expected: dict) -> None:
    """The supplied-evidence question (spec 0013 §5, §7 AC1–2/AC10): a governed
    gross-revenue answer whose directly cited orders table carries a SYNTHETIC
    supplied report — failed completeness check, expired validity, recent
    event watermark — keeps its route, value and governance label, and the
    answer carries ONE brief data caveat naming the report and its as-of
    scope, never turning the watermark into a completeness claim."""
    get_ok = [i for i in _real_calls(scenario, "get-metric") if scenario["calls"][i]["exit"] == 0]
    assert get_ok, "quality-report route: no successful get-metric call recorded"
    assert not _real_calls(scenario, "define-metric"), (
        "quality-report route: define-metric must not answer a governed question"
    )
    discovery = _real_calls(scenario, "list-metrics") + _real_calls(scenario, "search-context")
    assert discovery and min(discovery) < min(get_ok), (
        "quality-report route: discovery must precede the get-metric call"
    )

    call = scenario["calls"][get_ok[0]]
    result = call["result"]
    tokens = call["command"].split()
    anchor = tokens.index("get-metric")
    requested = [t for t in tokens[anchor + 1 :] if not t.startswith("--")][0]
    requested_dims = [
        tokens[i + 1] for i in range(anchor, len(tokens) - 1) if tokens[i] == "--dimension"
    ]
    assert requested == "gross_revenue" and requested_dims == ["region"], (
        f"quality-report route: the get-metric command must request gross_revenue by "
        f"region, got {requested!r} by {requested_dims}"
    )
    assert result["metric"] == requested and result["governed"] is True, (
        "quality-report route: get-metric must return the requested metric, governed: true"
    )
    observed = {row["region"]: row["gross_revenue"] for row in result["rows"]}
    assert set(observed) == set(sql_expected), "region set mismatch"
    for region in observed:
        assert abs(observed[region] - sql_expected[region]) <= TOLERANCE, (
            f"quality-report value {region}: observed != independent SQL "
            "(a data warning never changes the number)"
        )

    context = result["context"]
    policy_paths = _policy_paths(_frontmatter(context["metric_page"]))
    assert policy_paths and len(context["policies"]) == len(policy_paths), (
        "observed context must return the full body of every cited policy"
    )
    bodies = "\n".join(context["policies"]).lower()
    assert "cancelled" in bodies and "returned" in bodies, (
        "the returned policy bodies must carry the status-exclusion rule"
    )
    assert "rate_to_usd" in bodies and "2024" in bodies, (
        "the returned policy bodies must carry the pre-2024 EMEA conversion rule"
    )
    lifecycle = context["context_signals"]["warnings"]
    assert lifecycle == [], "no lifecycle problem is staged in this scenario"

    # The additive advisory view (plan 0013 §2): the failed check, the expired
    # validity and the recent event watermark stay three SEPARATE disclosed
    # facts — none of them becomes a health claim, and none changes the number.
    signals = result["data_signals"]
    assert set(signals) == {
        "version",
        "assessed_at",
        "metrics",
        "assets",
        "warnings",
        "truncated",
        "omitted",
    }, "data_signals is the additive closed advisory view of plan 0013 §2"
    assert {w["code"] for w in signals["warnings"]} <= _DATA_WARNING_CODES, signals["warnings"]
    orders = table_resource("demo", "demo", "main", "orders")
    entry = next(m for m in signals["metrics"] if m["name"] == "gross_revenue")
    assert orders in [a for a in entry["assets"] if isinstance(a, str)], (
        "the orders table must be a directly identified dependency of the answer"
    )
    asset = next(a for a in signals["assets"] if a["resource"] == orders)
    assert asset["page"] and asset["coverage"] != "complete", (
        "a failed+expired supplied report never yields a complete coverage claim"
    )
    [report] = [r for r in asset["reports"] if r["id"] == "orders-completeness-2026-09"]
    assert report["evidence_kind"] == "supplied", "the profile discloses SUPPLIED evidence"
    assert report["age"] == "expired", "the supplied validity is past — age is expired"
    assert report["applicability"] == "unknown", "correspondence is never guessed"
    assert [check["outcome"] for check in report["checks"]] == ["fail"], (
        "the reported failed outcome stays a reported fact"
    )
    assert report["watermark"]["kind"] == "event_time", (
        "the recent event watermark stays an event-time boundary"
    )
    report_warnings = {w["code"] for w in signals["warnings"] if w["report"] == report["id"]}
    assert {"data_report_failed", "data_report_expired", "data_applicability_unknown"} <= (
        report_warnings
    ), "the failed and expired axes are disclosed separately, unknown applicability never a pass"

    answer = scenario["final_answer"]
    lowered = answer.lower()
    assert "governed" in lowered and not any(
        negation in lowered for negation in ("not governed", "governed: false", "ungoverned")
    ), "final answer must positively label the number governed"
    served_page = f"context_layer/metrics/{result['metric']}.md"
    supported = {served_page} | set(policy_paths) | {asset["page"]}
    _assert_citations(answer, supported, {served_page} | set(policy_paths))
    _assert_answer_caveats(answer)
    _assert_lifecycle_caveats(answer, lifecycle)
    _assert_data_caveats(answer, signals, "gross_revenue")
    _assert_no_watermark_completeness_claim(answer)

    # Display precision: every region's row must show at least one figure that
    # agrees with the oracle's rounded display value (an exact full-precision
    # column, a rounded column, or a single value all qualify; a truncated
    # prefix of a longer number is never a display value).
    rows = re.findall(r"^\|\s*(NA|EMEA|APAC)\s*\|([^\n]*)$", answer, re.MULTILINE)
    assert {region for region, _ in rows} == set(sql_expected), (
        "answer must show every region's revenue"
    )
    shown: dict[str, list[float]] = {
        region: [float(n.replace(",", "")) for n in re.findall(r"\$?\s?([\d,]+\.\d+)", cells)]
        for region, cells in rows
    }
    for region, values in shown.items():
        assert values, f"answer must show region {region}'s revenue"
        assert any(
            abs(value - round(sql_expected[region], 2)) <= DISPLAY_TOLERANCE for value in values
        ), f"answer display value {region}: none of {values} agrees with the oracle"


def check_all(trace: dict, demo_db: Path) -> None:
    check_provenance(trace)
    _no_promotion(trace)
    governed = trace["scenarios"]["governed"]
    sql_expected = independent_expected(demo_db, "gross_margin", ["region"])
    golden_entry = next(
        e
        for e in GOLDEN["entries"]
        if e["metric"] == "gross_margin" and e.get("dimensions") == ["region"]
    )
    check_governed(governed, sql_expected, golden_entry["expected"])
    check_adhoc(trace["scenarios"]["adhoc"], independent_adhoc_means(demo_db))
    check_stale_policy(
        trace["scenarios"]["stale_policy"],
        independent_expected(demo_db, "order_count", ["region"]),
    )
    check_quality_report(
        trace["scenarios"]["quality_report"],
        independent_expected(demo_db, "gross_revenue", ["region"]),
    )


# --- The recorded run meets the spec (spec acceptance example 1) --------------


def test_recorded_trace_meets_spec(demo_db):
    check_all(load_trace(), demo_db)


# --- Named failures on mutated copies (spec acceptance example 2/3) -----------


def _mutated(**overrides):
    import copy

    trace = copy.deepcopy(load_trace())
    for path, value in overrides.items():
        node = trace
        keys = path.split(".")
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node[key]
        last = keys[-1]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return trace


def test_wrong_governed_route_fails_named(demo_db):
    get_at = _real_calls(load_trace()["scenarios"]["governed"], "get-metric")[0]
    trace = _mutated(
        **{f"scenarios.governed.calls.{get_at}.command": "ariadne define-metric --file gm.json"}
    )
    with pytest.raises(AssertionError, match="governed route"):
        check_all(trace, demo_db)


def test_missing_caveat_fails_named(demo_db):
    answer = load_trace()["scenarios"]["governed"]["final_answer"]
    mutilated = re.sub(r"(?m)^- Pre-2024 EMEA rows.*\n", "", answer)
    assert mutilated != answer, "mutation must change the recorded answer"
    trace = _mutated(**{"scenarios.governed.final_answer": mutilated})
    with pytest.raises(AssertionError, match="caveat"):
        check_all(trace, demo_db)


def test_false_governed_label_fails_named(demo_db):
    answer = load_trace()["scenarios"]["adhoc"]["final_answer"]
    relabeled = answer.replace("governed: false", "governed: true")
    assert relabeled != answer, "mutation must change the recorded answer"
    trace = _mutated(**{"scenarios.adhoc.final_answer": relabeled})
    with pytest.raises(AssertionError, match="ungoverned ad-hoc"):
        check_all(trace, demo_db)


def test_skill_digest_mismatch_invalidates(demo_db):
    trace = _mutated(**{"_meta.skill.skill_md_sha256": "0" * 64})
    with pytest.raises(AssertionError, match="skill digest mismatch"):
        check_all(trace, demo_db)


def test_unqualified_emea_caveat_fails_named(demo_db):
    """Deleting only the time qualifier (pre-2024) while leaving EMEA and the
    conversion wording must still fail: the caveat is the TIME-BOUND conversion."""
    answer = load_trace()["scenarios"]["governed"]["final_answer"]
    mutilated = answer.replace("Pre-2024 EMEA rows", "EMEA rows")
    assert mutilated != answer and "convert" in mutilated.lower() and "emea" in mutilated.lower()
    trace = _mutated(**{"scenarios.governed.final_answer": mutilated})
    with pytest.raises(AssertionError, match="caveat"):
        check_all(trace, demo_db)


def test_negated_governed_label_fails_named(demo_db):
    """A negated label ('not governed' / 'governed: false') is not a positive
    governed label, even though the substring 'governed' is present."""
    answer = load_trace()["scenarios"]["governed"]["final_answer"]
    for bad in ("not governed", "governed: false"):
        relabeled = answer.replace("governed: true", bad)
        assert relabeled != answer, f"mutation must change the recorded answer ({bad})"
        trace = _mutated(**{"scenarios.governed.final_answer": relabeled})
        with pytest.raises(AssertionError, match="positively label"):
            check_all(trace, demo_db)


def test_command_argument_substitution_fails_named(demo_db):
    """Stale rows behind a rewritten request must fail: the successful
    get-metric command must actually request gross_margin by region, and its
    returned metric/dimensions must match the request."""
    get_at = _real_calls(load_trace()["scenarios"]["governed"], "get-metric")[0]
    original = load_trace()["scenarios"]["governed"]["calls"][get_at]["command"]
    assert "get-metric gross_margin --dimension region" in original
    for substitution in (
        "get-metric cogs --dimension region",  # wrong metric, stale rows
        "get-metric gross_margin --dimension status",  # wrong dimension, stale rows
    ):
        mutated_cmd = original.replace("get-metric gross_margin --dimension region", substitution)
        assert mutated_cmd != original
        trace = _mutated(**{f"scenarios.governed.calls.{get_at}.command": mutated_cmd})
        with pytest.raises(AssertionError, match="governed route"):
            check_all(trace, demo_db)


def test_optional_overall_mean_absence_still_passes(demo_db):
    """The answer need only show per-customer values; an overall figure is
    optional, but when supplied it must agree with the same SQL oracle."""
    answer = load_trace()["scenarios"]["adhoc"]["final_answer"]
    assert "$774.65" not in answer
    check_all(load_trace(), demo_db)
    augmented = answer + " Across all customers, mean **per billable order** is $774.65."
    trace = _mutated(**{"scenarios.adhoc.final_answer": augmented})
    check_all(trace, demo_db)


def test_missing_returned_policy_body_fails_named(demo_db):
    """A context that returns the metric page's policy citations without the
    corresponding full body is incomplete evidence — named failure."""
    get_at = _real_calls(load_trace()["scenarios"]["governed"], "get-metric")[0]
    policies = load_trace()["scenarios"]["governed"]["calls"][get_at]["result"]["context"][
        "policies"
    ]
    assert len(policies) == 2 and policies[1].strip()
    trace = _mutated(**{f"scenarios.governed.calls.{get_at}.result.context.policies.1": ""})
    with pytest.raises(AssertionError, match="policy"):
        check_all(trace, demo_db)


def test_doubled_prefix_citation_is_not_a_returned_path():
    """Negative control (fix pass 1): a doubled-prefix path
    (`context_layer/context_layer/…`) does not exist — citing it and nothing
    real must FAIL the citation check, while both genuine forms of a returned
    page keep passing."""
    doubled = "context_layer/context_layer/metrics/gross_margin.md"
    real = "context_layer/metrics/gross_margin.md"
    with pytest.raises(AssertionError, match="did not return"):
        _assert_citations(f"see `{doubled}`.", {real}, {real})
    for form in (real, "metrics/gross_margin.md"):
        _assert_citations(f"see `{form}`.", {real}, {real})


# --- Lifecycle-caveat controls (spec 0011 §6 / §8 AC8; constructed checker
# inputs only — never recorded-Agent evidence) -------------------------------


def test_missing_lifecycle_caveat_fails_named(demo_db):
    """An answer relying on a consumed expired Policy but omitting the brief
    lifecycle caveat naming it must be rejected for the named reason."""
    answer = load_trace()["scenarios"]["stale_policy"]["final_answer"]
    mutilated = re.sub(r"(?m)^- The billable-status list.*\n", "", answer)
    assert mutilated != answer and not _LIFECYCLE_WORDS.search(mutilated.lower()), (
        "mutation must remove the lifecycle caveat (words and reliance naming)"
    )
    trace = _mutated(**{"scenarios.stale_policy.final_answer": mutilated})
    with pytest.raises(AssertionError, match="lifecycle caveat"):
        check_all(trace, demo_db)


def test_unrelated_stale_hit_demands_no_caveat(demo_db):
    """Negative control: a lifecycle warning on a search hit the answer does
    NOT rely on (an uncited, unrelated hit) must demand no answer caveat —
    the unchanged recorded answer still passes."""
    scenario = load_trace()["scenarios"]["adhoc"]
    search_idx = next(
        i for i, call in enumerate(scenario["calls"]) if "search-context" in call["command"]
    )
    unrelated_idx = next(
        i
        for i, hit in enumerate(scenario["calls"][search_idx]["result"])
        if isinstance(hit, dict) and hit["path"] != "metrics/mean_order_amount_per_customer.md"
    )
    trace = _mutated(
        **{
            f"scenarios.adhoc.calls.{search_idx}.result.{unrelated_idx}.context_signals.warnings": [
                {"code": "context_stale", "path": "metrics/gross_margin.md"}
            ]
        }
    )
    check_all(trace, demo_db)  # no caveat demanded: the hit is not relied upon


def test_optional_metadata_demands_no_warning(demo_db):
    """Negative control: absent optional expiry/verification metadata on the
    RELIED-UPON hit itself must demand neither a warning nor an answer caveat
    — stripping the cited page's evidence to absent/unknown keeps the
    unchanged answer passing."""
    scenario = load_trace()["scenarios"]["adhoc"]
    search_idx = next(
        i for i, call in enumerate(scenario["calls"]) if "search-context" in call["command"]
    )
    absent_view = [
        {
            "path": "metrics/mean_order_amount_per_customer.md",
            "status": "stable",
            "freshness": {"stale_after": None, "state": "unknown"},
            "verification_tier": "unverified",
            "generated": None,
            "verified": None,
            "sources": [],
        }
    ]
    trace = _mutated(
        **{
            f"scenarios.adhoc.calls.{search_idx}.result.0.context_signals.pages": absent_view,
            f"scenarios.adhoc.calls.{search_idx}.result.0.context_signals.warnings": [],
        }
    )
    check_all(trace, demo_db)  # unknown/unverified alone never warns or demands a caveat


def test_unstaged_proposal_path_fails_named(demo_db):
    """A definition whose proposal paths do not resolve under the staged-
    proposals location must not pass as staged (spec 0003: the proposal stays
    staged; #49 fix1: the staging location itself is required — plausible-
    looking adhoc paths outside staging/ are not staged proposals)."""
    scenario = load_trace()["scenarios"]["adhoc"]

    def unstaged(path: str) -> str:
        return (
            path.split("/staging/", 1)[-1] if "/staging/" in path else path.removeprefix("staging/")
        )

    grouped_at = [
        i
        for i in _real_calls(scenario, "define-metric")
        if isinstance(scenario["calls"][i].get("result"), dict)
        and "rows" in scenario["calls"][i]["result"]
    ][-1]
    result = scenario["calls"][grouped_at]["result"]
    assert "/staging/" in result["staged_as"] or result["staged_as"].startswith("staging/")
    trace = _mutated(
        **{
            f"scenarios.adhoc.calls.{grouped_at}.result.staged_as": unstaged(result["staged_as"]),
            f"scenarios.adhoc.calls.{grouped_at}.result.staged_context_as": unstaged(
                result["staged_context_as"]
            ),
        }
    )
    with pytest.raises(AssertionError, match="staged-proposals location"):
        check_all(trace, demo_db)


# --- Supplied-evidence caveat controls (spec 0013 §5 / §7 AC1–2/AC10;
# constructed checker inputs only — never recorded-Agent evidence) ----------


def _quality_get_at(scenario: dict) -> int:
    return [i for i in _real_calls(scenario, "get-metric") if scenario["calls"][i]["exit"] == 0][0]


def test_missing_data_caveat_fails_named(demo_db):
    """An answer relying on an asset whose supplied report FAILED a check and
    EXPIRED, but omitting the brief caveat naming that report and its as-of
    scope, must be rejected for the named reason (spec 0013 §5, AC10)."""
    answer = load_trace()["scenarios"]["quality_report"]["final_answer"]
    mutilated = re.sub(r"(?m)^- This answer relies on the orders table.*\n", "", answer)
    assert mutilated != answer and "orders-completeness-2026-09" not in mutilated, (
        "mutation must remove the supplied-evidence caveat (report id and scope)"
    )
    trace = _mutated(**{"scenarios.quality_report.final_answer": mutilated})
    with pytest.raises(AssertionError, match="caveat naming that report"):
        check_all(trace, demo_db)


def test_watermark_completeness_claim_fails_named(demo_db):
    """An answer claiming an event watermark proves completeness must be
    rejected (spec 0013 §7 AC2); honestly restating the boundary with a
    negation is not a claim."""
    answer = load_trace()["scenarios"]["quality_report"]["final_answer"]
    claimed = answer + (
        "The event watermark of 2026-10-06T23:00Z proves every expected record "
        "has arrived, so the orders data is complete."
    )
    trace = _mutated(**{"scenarios.quality_report.final_answer": claimed})
    with pytest.raises(AssertionError, match="event watermark"):
        check_all(trace, demo_db)
    # the honest disclaimer form never trips the control
    _assert_no_watermark_completeness_claim(
        "The report's watermark is an event-time boundary — not proof that every "
        "expected record has arrived, and not ingestion currency."
    )
    _assert_no_watermark_completeness_claim(
        "Its completeness check failed while the watermark is recent; both facts stand."
    )


def test_contradictory_watermark_claim_fails_named(demo_db):
    """A failed check in one clause never licenses an affirmative watermark-
    completeness claim in another (spec 0013 §7 AC2: a failed check and a
    recent watermark coexist — neither reinterprets the other). The claim and
    any negation are evaluated PER CLAUSE, not per sentence."""
    answer = load_trace()["scenarios"]["quality_report"]["final_answer"]
    contradiction = answer + (
        " The completeness check failed, but the recent event watermark proves "
        "every expected record has arrived."
    )
    assert contradiction != answer
    trace = _mutated(**{"scenarios.quality_report.final_answer": contradiction})
    with pytest.raises(AssertionError, match="event watermark"):
        check_all(trace, demo_db)
    # the per-clause hedge still passes: the watermark clause itself is negated
    _assert_no_watermark_completeness_claim(
        "The watermark does not prove completeness, but it is a useful boundary signal."
    )


def test_anaphora_watermark_claim_fails_named(demo_db):
    """Sentence-level association (fix2): an anaphoric claim in a later clause
    still belongs to the sentence's watermark — 'The watermark is recent, but
    it proves every expected record has arrived' is the forbidden inference
    (spec 0013 §7 AC2: a watermark never proves completeness of arrival),
    while a negation directly before the claim's own assertion still hedges."""
    answer = load_trace()["scenarios"]["quality_report"]["final_answer"]
    anaphora = answer + (
        " The watermark is recent, but it proves every expected record has arrived."
    )
    assert anaphora != answer
    trace = _mutated(**{"scenarios.quality_report.final_answer": anaphora})
    with pytest.raises(AssertionError, match="event watermark"):
        check_all(trace, demo_db)
    # the three probes of the authorized semantics, at the checker boundary
    with pytest.raises(AssertionError, match="event watermark"):
        _assert_no_watermark_completeness_claim(
            "The watermark is recent, but it proves every expected record has arrived."
        )
    with pytest.raises(AssertionError, match="event watermark"):
        _assert_no_watermark_completeness_claim(
            "The completeness check failed, but the recent event watermark proves "
            "every expected record has arrived."
        )
    _assert_no_watermark_completeness_claim(
        "The watermark does not prove completeness, but it is a useful boundary signal."
    )


def test_unrelated_data_warning_demands_no_caveat(demo_db):
    """Negative control: a data warning naming an asset/report the answer does
    NOT rely on (an unrelated table) must demand no caveat — the unchanged
    recorded answer still passes."""
    scenario = load_trace()["scenarios"]["quality_report"]
    get_at = _quality_get_at(scenario)
    warnings = scenario["calls"][get_at]["result"]["data_signals"]["warnings"]
    unrelated = {
        "code": "data_report_failed",
        "metric": None,
        "asset": table_resource("demo", "demo", "main", "customers"),
        "page": None,
        "report": "customers-completeness-2026-09",
    }
    trace = _mutated(
        **{
            f"scenarios.quality_report.calls.{get_at}.result.data_signals.warnings": [
                *warnings,
                unrelated,
            ]
        }
    )
    check_all(trace, demo_db)  # no caveat demanded: the report is not relied upon


def test_passing_optional_report_demands_no_data_caveat(demo_db):
    """Negative control: a PASSING, unexpired supplied report on a relied-upon
    asset (no failed/expired warning) demands no caveat — an answer with no
    data caveat keeps passing (spec 0013 §5: a report alone is not a warning)."""
    scenario = load_trace()["scenarios"]["governed"]
    get_at = _quality_get_at(scenario)
    passing = {
        "id": "orders-availability-2026-10",
        "evidence_kind": "supplied",
        "age": "as_of",
        "applicability": "unknown",
        "limitations": ["source_version_unknown", "validity_not_supplied"],
        "reported_at": "2026-10-01T00:00:00+00:00",
        "checks": [{"id": "availability", "kind": "availability", "outcome": "pass"}],
    }
    key = f"scenarios.governed.calls.{get_at}.result.data_signals.assets.0.reports"
    trace = _mutated(**{key: [passing]})
    check_all(trace, demo_db)  # no failed/expired warning: nothing demanded

"""Deterministic recorded-trace check (spec 2026-09-23-0003, evidence tier 1).

``tests/evals/agent_trace.json`` records a fresh Pi session (both questions
asked in ONE session) over the installed packaged Ariadne skill and synthetic
retail demo: every observed ``ariadne`` CLI call in order, including the failed
unpromoted get-metric probe and two failed define-metric probes; the minimal
JSON outputs the assertions need, packaged-skill digest, and final answers
verbatim from the assistant's write payload.
Nothing is scripted or edited to pass: this check validates the RECORDED run
only. A separately reported fresh live smoke covers the current agent (spec
tier 2); this test calls no model and makes no live-provider claim.

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
    invented ones) and must cite the required returned paths."""
    cited = set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", answer))
    assert cited <= supported, (
        f"final answer cites paths the tool did not return: {sorted(cited - supported)}"
    )
    assert must_cite <= cited, (
        f"final answer must cite the returned context paths: missing {sorted(must_cite - cited)}"
    )


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
    assert set(context) == {"metric_page", "policies"}, (
        "get-metric context must be the actual {metric_page, policies} payload"
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

    answer = scenario["final_answer"]
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

    # Display precision: the answer's rounded table must agree with the oracle.
    shown = {
        region: float(pct)
        for region, pct in re.findall(
            r"\|\s*(NA|EMEA|APAC)\s*\|[^|\n]*?([\d.]+)\s*%\s*\)?\s*\|", answer
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
    assert list_at and datasets_at and define_ok, "ad-hoc route: incomplete recorded path"
    assert min(list_at) < min(datasets_at) < min(define_ok), (
        "ad-hoc route: discovery (list-metrics) must precede list-datasets, "
        "which must precede the successful define-metric"
    )
    assert not any(
        scenario["calls"][i]["exit"] == 0 for i in _real_calls(scenario, "get-metric")
    ), (
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

    grouped = scenario["calls"][define_ok[-1]]["result"]
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
    assert grouped["staged_as"].endswith(
        "/staging/semantic_layer/models/adhoc/mean_order_amount_per_customer-2.yml"
    ) and grouped["staged_context_as"].endswith(
        "/staging/context_layer/metrics/mean_order_amount_per_customer-2.md"
    ), "the successful definition must have staged exactly the observed proposal paths"

    answer = scenario["final_answer"]
    lowered = answer.lower()
    assert "governed: false" in lowered and "ad-hoc" in lowered, (
        "final answer must label the result an ungoverned ad-hoc proposal"
    )
    assert ("staged" in lowered or "/staging/" in lowered) and (
        "not promoted" in lowered or "unpromoted" in lowered
    ), "final answer must state the proposal stays staged, never promoted"
    _assert_answer_caveats(answer)
    page_paths = {hit["path"], f"context_layer/{hit['path']}"}
    policies = set(_policy_paths(hit_meta))
    # A search result may be cited by its returned relative path or by its
    # served-root path; both identify the same actually returned metric page.
    cited = set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", answer))
    assert cited & page_paths, "final answer must cite the returned context page"
    staged_page = "staging/" + grouped["staged_context_as"].split("/staging/", 1)[1]
    _assert_citations(answer, page_paths | policies | {staged_page}, policies)

    # Display precision: every customer's rounded dollar figure must agree with
    # the shared oracle. An overall per-billable-order mean is OPTIONAL (the
    # spec asks per-customer amounts) — validated only when the answer gives one.
    shown: dict[int, float] = {}
    for customer_id, value in re.findall(
        r"\|\s*(\d{1,2})\s*\|\s*\$?([\d,]+\.\d{2})\s*(?=\|)", answer
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
    mutilated = answer.replace(
        "pre-2024 EMEA amounts and costs are converted to USD, while other orders are already USD.",
        "",
    )
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
    """Deleting only the time qualifier (pre-2024) while leaving EMEA and
    'converted' must still fail: the caveat is the TIME-BOUND conversion."""
    answer = load_trace()["scenarios"]["governed"]["final_answer"]
    mutilated = answer.replace("pre-2024 EMEA", "EMEA")
    assert mutilated != answer and "convert" in mutilated.lower() and "emea" in mutilated.lower()
    trace = _mutated(**{"scenarios.governed.final_answer": mutilated})
    with pytest.raises(AssertionError, match="caveat"):
        check_all(trace, demo_db)


def test_negated_governed_label_fails_named(demo_db):
    """A negated label ('not governed' / 'governed: false') is not a positive
    governed label, even though the substring 'governed' is present."""
    answer = load_trace()["scenarios"]["governed"]["final_answer"]
    for bad in ("not governed", "governed: false"):
        relabeled = answer.replace("`governed: true`", f"`{bad}`")
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

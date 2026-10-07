"""Focused controls for the operator-invoked business-answer checker."""

import copy
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_evals import (  # noqa: E402
    attached_demo,
    independent_expected,
)
from tests.test_seed import run_seed  # noqa: E402

CASES_PATH = ROOT / "tests" / "evals" / "business_answer_cases.json"
CHECKER_PATH = ROOT / "tests" / "evals" / "check_business_answers.py"
spec = importlib.util.spec_from_file_location("business_answer_checker", CHECKER_PATH)
assert spec is not None and spec.loader is not None
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def _fixture(tmp_path, *, cases_path=CASES_PATH):
    db_path = tmp_path / "demo.db"
    run_seed(db_path)
    manifest = {
        "version": 1,
        "id": "synthetic-demo-v1",
        "inputs": [
            {
                "source": "synthetic_demo",
                "kind": "sqlite",
                "path": str(db_path),
                "sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
            }
        ],
    }
    manifest_path = tmp_path / "snapshot-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return db_path, manifest, manifest_path, cases, cases_path


# Independent control oracle: ratio-of-sums arithmetic over every order,
# deliberately not the question's billable-order population.
_WRONG_POPULATION_SQL = """
    WITH converted AS (
        SELECT o.region_code AS region,
            CASE WHEN o.region_code = 'EMEA'
                      AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                 THEN o.amount * r.rate_to_usd ELSE o.amount END AS amount_usd,
            CASE WHEN o.region_code = 'EMEA'
                      AND o.order_timestamp::TIMESTAMP < TIMESTAMP '2024-01-01'
                 THEN o.product_cost * r.rate_to_usd ELSE o.product_cost END AS cost_usd
        FROM demo.orders o
        LEFT JOIN demo.currency_conversion_rate r ON r.currency = o.currency
    )
    SELECT region, (SUM(amount_usd) - SUM(cost_usd)) / SUM(amount_usd) AS gross_margin
    FROM converted GROUP BY region ORDER BY region
"""


def _observed_rows(db_path, population):
    if population == "billable_orders":
        return [
            {"region": region, "gross_margin": value}
            for region, value in independent_expected(db_path, "gross_margin", ["region"]).items()
        ]
    with attached_demo(db_path) as con:
        # nosemgrep — module-level constant SQL, no interpolation or tool input.
        rows = con.execute(_WRONG_POPULATION_SQL).fetchall()
    return [{"region": region, "gross_margin": value} for region, value in rows]


def _observation(
    case,
    *,
    evidence_kind="control",
    population="billable_orders",
    outcome="answer",
    rows=None,
    final_values=None,
):
    route = case["route"]
    arguments = copy.deepcopy(route["parameters"])
    arguments["population"] = population
    rows = [] if rows is None else rows
    final_rows = rows if final_values is None else list(final_values)
    return {
        "case_id": case["id"],
        "evidence_kind": evidence_kind,
        "outcome": outcome,
        "model": "synthetic-control",
        "provider": "local-test",
        "code_revision": "control-revision",
        "artifact_revision": "control-artifact",
        "skill_digest": "a" * 64,
        "snapshot_id": "synthetic-demo-v1",
        "session_id": "control-session",
        "run_id": "control-run",
        "source_hash": "b" * 64,
        "calls": [
            {
                "operation": "get-metric",
                "arguments": arguments,
                "exit": 0,
                "result": {
                    "governed": True,
                    "rows": rows if rows is not None else [],
                    "supported_citations": [],
                },
            }
        ]
        if outcome == "answer"
        else [],
        "final_answer_values": list(final_rows),
        "final_answer": (
            "Governed: true. CANCELLED and RETURNED orders are excluded."
            if outcome == "answer"
            else "This question is unsupported by the available catalog."
        ),
    }


def _control_result(cases, manifest, manifest_path, cases_path, observation):
    trace = {"version": 1, "observations": [observation]}
    return checker.check(cases, trace, manifest, cases_path, manifest_path)["cases"][0]


def test_correct_arithmetic_for_wrong_population_fails_interpretation_and_parameters(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    wrong_rows = _observed_rows(db_path, "all_orders")
    intended = independent_expected(db_path, "gross_margin", ["region"])
    assert all(abs(row["gross_margin"] - intended[row["region"]]) > 1e-6 for row in wrong_rows), (
        "the control must be correct arithmetic over a different population"
    )

    observation = _observation(case, population="all_orders", rows=wrong_rows)
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    control = report["controls"]["observations"][0]
    assert control["axes"]["interpretation"]["status"] == "fail"
    assert "meaning_mismatch:population" in control["axes"]["interpretation"]["reasons"]
    assert control["axes"]["route_parameters"]["status"] == "fail"
    assert control["axes"]["values"]["status"] == "fail"
    assert control["evidence_kind"] == "control"
    assert report["recorded"]["disposition"] == "unverified"


def test_recorded_failure_survives_missing_current_evidence():
    assert checker.worst(["fail", "unverified"]) == "fail"
    assert checker.worst(["pass", "unverified"]) == "unverified"
    statuses = {
        "recorded": {"disposition": "fail"},
        "current": {"disposition": "unverified"},
    }
    assert checker.case_disposition(statuses, {"recorded"}, ["recorded"]) == "fail"


def test_missing_row_key_fails_the_complete_set_comparison(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    rows = _observed_rows(db_path, "billable_orders")[:-1]
    report = _control_result(
        cases, manifest, manifest_path, cases_path, _observation(case, rows=rows)
    )
    values = report["controls"]["observations"][0]["axes"]["values"]
    assert values["status"] == "fail"
    assert "complete_row_keys_mismatch" in values["reasons"]


def test_snapshot_identity_and_digest_failures_are_not_passes(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    observation = _observation(case, rows=_observed_rows(db_path, "billable_orders"))
    observation["snapshot_id"] = "different-snapshot"
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    provenance = report["controls"]["observations"][0]["axes"]["provenance"]
    assert provenance["status"] == "fail"
    assert "snapshot_identity_mismatch" in provenance["reasons"]

    db_path.write_bytes(db_path.read_bytes() + b"changed")
    observation["snapshot_id"] = manifest["id"]
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    values = report["controls"]["observations"][0]["axes"]["values"]
    assert values["status"] == "unverified"
    assert "oracle.snapshot_digest_mismatch" in values["reasons"]


def test_input_shape_is_rejected_with_a_named_reason(tmp_path):
    _, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    observation = _observation(cases["cases"][0])
    observation["calls"] = "not-an-event-list"
    trace = {"version": 1, "observations": [observation]}
    with pytest.raises(checker.InputError) as error:
        checker.check(cases, trace, manifest, cases_path, manifest_path)
    assert error.value.reason == "trace.observations[0].calls_invalid"


def test_call_and_json_bounds_are_named_unverified_evidence(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    rows = _observed_rows(db_path, "billable_orders")
    observation = _observation(case, rows=rows)
    observation["calls"] *= checker.MAX_CALLS + 1
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    control = report["controls"]["observations"][0]
    assert "call_events_exceed_64" in control["bounds"]
    assert control["disposition"] == "unverified"

    oversized = _observation(case, rows=rows)
    oversized["extra"] = "x" * (checker.MAX_OBSERVATION_BYTES + 1)
    report = _control_result(cases, manifest, manifest_path, cases_path, oversized)
    control = report["controls"]["observations"][0]
    assert "observation_json_exceeds_1_mib" in control["bounds"]
    assert control["disposition"] == "unverified"


def test_cli_requires_explicit_inputs_and_writes_named_report(tmp_path):
    cases_path = tmp_path / "cases.json"
    trace_path = tmp_path / "trace.json"
    manifest_path = tmp_path / "manifest.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text('{"version": 7, "cases": []}', encoding="utf-8")
    trace_path.write_text('{"version": 1, "observations": []}', encoding="utf-8")
    manifest_path.write_text('{"version": 1, "id": "local", "inputs": []}', encoding="utf-8")

    result = checker.main(
        [
            "--cases",
            str(cases_path),
            "--trace",
            str(trace_path),
            "--snapshot-manifest",
            str(manifest_path),
            "--report",
            str(report_path),
        ]
    )
    assert result == 2
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["errors"][0]["reason"] == "cases.version_unsupported"


def test_operator_cli_checks_only_explicit_paths_and_writes_report(tmp_path):
    db_path, _, manifest_path, cases, _ = _fixture(tmp_path)
    cases_path = tmp_path / "cases.json"
    trace_path = tmp_path / "trace.json"
    report_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    observation = _observation(cases["cases"][0], rows=_observed_rows(db_path, "billable_orders"))
    trace_path.write_text(
        json.dumps({"version": 1, "observations": [observation]}), encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(CHECKER_PATH),
            "--cases",
            str(cases_path),
            "--trace",
            str(trace_path),
            "--snapshot-manifest",
            str(manifest_path),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    control = report["cases"][0]["controls"]["observations"][0]
    assert control["axes"]["values"]["status"] == "pass"
    assert report["cases"][0]["recorded"]["disposition"] == "unverified"
    assert report["cases"][0]["current"]["disposition"] == "unverified"


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("cases", "cases.version_unsupported"),
        ("trace", "trace.version_unsupported"),
        ("snapshot", "snapshot.version_unsupported"),
    ],
)
def test_unsupported_input_versions_are_rejected_with_named_reasons(tmp_path, field, reason):
    _, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    inputs = {
        "cases": cases,
        "trace": {"version": 1, "observations": []},
        "snapshot": manifest,
    }
    inputs[field]["version"] = 99
    with pytest.raises(checker.InputError) as error:
        checker.check(
            inputs["cases"],
            inputs["trace"],
            inputs["snapshot"],
            cases_path,
            manifest_path,
        )
    assert error.value.reason == reason


def test_evidence_over_row_bound_is_unverified_not_a_partial_pass(tmp_path):
    _, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    observation = _observation(case, rows=[{"region": "NA", "gross_margin": 0.0}] * 1001)
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    control = report["controls"]["observations"][0]
    assert control["axes"]["values"]["status"] == "unverified"
    assert "result_rows_exceed_1000" in control["bounds"]


def test_unsupported_required_answer_is_a_coverage_gap_not_expected_unsupported(tmp_path):
    _, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    answer_case = cases["cases"][0]
    unsupported_run = _observation(answer_case, outcome="unsupported")
    answer_report = _control_result(cases, manifest, manifest_path, cases_path, unsupported_run)
    assert answer_report["controls"]["observations"][0]["disposition"] == "coverage_gap"

    expected_unsupported = copy.deepcopy(cases)
    unsupported_case = expected_unsupported["cases"][0]
    unsupported_case["expected_outcome"] = "unsupported"
    unsupported_case["explanation"] = {
        "required_caveats": [],
        "required_labels": [],
        "required_citations": [],
        "permitted_citations": [],
    }
    unsupported_run["case_id"] = unsupported_case["id"]
    unsupported_report = _control_result(
        expected_unsupported, manifest, manifest_path, cases_path, unsupported_run
    )
    assert unsupported_report["controls"]["observations"][0]["disposition"] == "pass"


def test_explicit_snapshot_manifest_and_reviewed_sql_oracle(tmp_path):
    db_path, manifest, manifest_path, cases, _ = _fixture(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE expected_values (region TEXT, gross_margin REAL)")
        connection.execute("INSERT INTO expected_values VALUES ('NA', 0.0)")
    manifest["inputs"][0]["sha256"] = hashlib.sha256(db_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sql_path = tmp_path / "oracle.sql"
    sql = "SELECT region, gross_margin FROM snapshot.expected_values"
    sql_path.write_text(sql, encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    case = cases["cases"][0]
    case["oracle"] = {
        "kind": "sql",
        "source": "synthetic_demo",
        "path": sql_path.name,
        "sha256": hashlib.sha256(sql_path.read_bytes()).hexdigest(),
        "review_ref": "test-owned independent SQL",
        "comparison": {
            "row_keys": ["region"],
            "value_columns": ["gross_margin"],
            "ordered": False,
            "absolute_tolerance": 0,
            "relative_tolerance": 0,
        },
    }
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    rows = [{"region": "NA", "gross_margin": 0.0}]
    observation = _observation(case, rows=rows)
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    assert report["controls"]["observations"][0]["axes"]["values"]["status"] == "pass"


# --- fix1: reproducing controls for the five accepted review findings
# (spec 0012 §5: incorrect value fails; ad-hoc proposals stay unadmitted;
# §6 AC8 current-vs-recorded identity, AC9 scope preservation).


def test_wrong_final_answer_value_fails_and_undeclared_final_values_are_unverified(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    rows = _observed_rows(db_path, "billable_orders")

    # The tool returns the reviewed rows, but the declared final answer claims a
    # wrong value for every region ("NA: 9999%" must not pass on label/caveat text).
    wrong_final = [{"region": row["region"], "gross_margin": 99.99} for row in rows]
    observation = _observation(case, rows=rows, final_values=wrong_final)
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    values = report["controls"]["observations"][0]["axes"]["values"]
    assert values["status"] == "fail"
    assert "final_answer_value_mismatch:gross_margin" in values["reasons"]

    # A case/observation with no comparable declared final-answer values is
    # unverified with a named reason — never a silent pass.
    undeclared = _observation(case, rows=rows)
    undeclared.pop("final_answer_values")
    report = _control_result(cases, manifest, manifest_path, cases_path, undeclared)
    values = report["controls"]["observations"][0]["axes"]["values"]
    assert values["status"] == "unverified"
    assert "final_answer_values_missing" in values["reasons"]


def test_current_pass_requires_matching_candidate_identity(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    rows = _observed_rows(db_path, "billable_orders")
    candidate = {
        "model": "glm-current",
        "code_revision": "control-revision",
        "artifact_revision": "control-artifact",
        "skill_digest": "a" * 64,
    }
    observation = _observation(case, evidence_kind="current", rows=rows)
    observation["model"] = "old-model"  # otherwise-perfect old-environment run
    trace = {"version": 1, "candidate": candidate, "observations": [observation]}
    report = checker.check(cases, trace, manifest, cases_path, manifest_path)["cases"][0]
    assert report["current"]["disposition"] == "unverified"
    assert report["current"]["missing_prerequisites"] == ["current_observation_missing"]
    downgraded = report["recorded"]["observations"]
    assert len(downgraded) == 1
    assert "current_candidate_mismatch:model" in downgraded[0]["downgraded_to_recorded"]

    # Missing comparison prerequisites stay unverified, never a current pass.
    undeclared = _observation(case, evidence_kind="current", rows=rows)
    trace = {"version": 1, "candidate": {}, "observations": [undeclared]}
    report = checker.check(cases, trace, manifest, cases_path, manifest_path)["cases"][0]
    assert report["current"]["disposition"] == "unverified"
    provenance = report["current"]["observations"][0]["axes"]["provenance"]
    assert provenance["status"] == "unverified"
    assert "current_candidate_identity_undeclared" in provenance["reasons"]


def test_oversized_observation_preserves_recorded_failures(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    rows = _observed_rows(db_path, "billable_orders")
    observation = _observation(case, rows=rows)
    observation["snapshot_id"] = "different-snapshot"  # already-detected failure
    observation["extra"] = "x" * (checker.MAX_OBSERVATION_BYTES + 1)
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    control = report["controls"]["observations"][0]
    provenance = control["axes"]["provenance"]
    assert provenance["status"] == "fail"
    assert "snapshot_identity_mismatch" in provenance["reasons"]
    assert control["axes"]["values"]["status"] == "unverified"
    assert control["axes"]["values"]["reasons"] == ["observation_json_exceeds_1_mib"]
    assert "observation_json_exceeds_1_mib" in control["bounds"]
    assert control["disposition"] == "fail"


def test_row_bound_applies_to_every_captured_call_regardless_of_outcome(tmp_path):
    _, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    expected_unsupported = copy.deepcopy(cases)
    case = expected_unsupported["cases"][0]
    case["expected_outcome"] = "unsupported"
    case["explanation"] = {
        "required_caveats": [],
        "required_labels": [],
        "required_citations": [],
        "permitted_citations": [],
    }
    observation = _observation(case, outcome="unsupported")
    observation["calls"] = [
        {
            "operation": "list-metrics",
            "arguments": {},
            "exit": 0,
            "result": {"rows": [{"region": "NA", "gross_margin": 0.0}] * 1001},
        }
    ]
    report = _control_result(expected_unsupported, manifest, manifest_path, cases_path, observation)
    control = report["controls"]["observations"][0]
    assert "result_rows_exceed_1000" in control["bounds"]
    assert control["axes"]["explanation"]["status"] == "unverified"
    assert control["axes"]["explanation"]["reasons"] == ["result_rows_exceed_1000"]
    assert control["disposition"] == "unverified"


def test_successful_promotion_fails_any_observation_globally(tmp_path):
    db_path, manifest, manifest_path, cases, cases_path = _fixture(tmp_path)
    case = cases["cases"][0]
    rows = _observed_rows(db_path, "billable_orders")

    # "promote" is outside this case's forbidden_operations (["define-metric"]),
    # so only the global no-admission/no-Promotion rule can catch it.
    observation = _observation(case, rows=rows)
    observation["calls"].append(
        {"operation": "promote", "arguments": {"artifact": "adhoc-mean"}, "exit": 0, "result": {}}
    )
    report = _control_result(cases, manifest, manifest_path, cases_path, observation)
    control = report["controls"]["observations"][0]
    route = control["axes"]["route_parameters"]
    assert route["status"] == "fail"
    assert "admission_or_promotion_succeeded:promote" in route["reasons"]
    assert control["disposition"] == "fail"

    # The same global rule holds for a non-answer outcome.
    unsupported = _observation(case, outcome="unsupported")
    unsupported["calls"] = [{"operation": "promote", "arguments": {}, "exit": 0, "result": {}}]
    report = _control_result(cases, manifest, manifest_path, cases_path, unsupported)
    route = report["controls"]["observations"][0]["axes"]["route_parameters"]
    assert route["status"] == "fail"
    assert "admission_or_promotion_succeeded:promote" in route["reasons"]

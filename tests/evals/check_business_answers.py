"""Operator-only checker for bounded business-answer evidence (specification 0012)."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports]

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_evals import (  # noqa: E402
    independent_adhoc_means,
    independent_expected,
)

MAX_CASES, MAX_CALLS, MAX_ROWS = 16, 64, 1000
MAX_OBSERVATION_BYTES = 1024 * 1024
FIELDS = ("entity", "population", "period", "timezone", "units", "grain", "denominator")
AXES = ("interpretation", "route_parameters", "values", "explanation", "provenance")
KINDS = ("recorded", "current", "control")
DISPOSITIONS = ("pass", "fail", "coverage_gap", "unverified")
# Human-only admission/Promotion operation prefixes (ADR-0013). Spec 0012 §5:
# ad-hoc proposals remain unadmitted and must not be promoted by the Agent (AC9).
ADMISSION_OPERATION_PREFIXES = ("promot", "admit")
CURRENT_IDENTITY_FIELDS = ("model", "code_revision", "artifact_revision", "skill_digest")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class InputError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise InputError(reason)


def text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"{name}.json_invalid") from exc
    require(isinstance(value, dict), f"{name}.shape_invalid")
    return value


def validate(cases_doc: dict[str, Any], trace: dict[str, Any], manifest: dict[str, Any]):
    require(
        type(cases_doc.get("version")) is int and cases_doc["version"] == 1,
        "cases.version_unsupported",
    )
    require(
        type(trace.get("version")) is int and trace["version"] == 1,
        "trace.version_unsupported",
    )
    require(
        type(manifest.get("version")) is int and manifest["version"] == 1,
        "snapshot.version_unsupported",
    )
    require(text(manifest.get("id")), "snapshot.id_invalid")
    cases = cases_doc.get("cases")
    observations = trace.get("observations")
    inputs = manifest.get("inputs")
    require(isinstance(cases, list), "cases.shape_invalid")
    require(isinstance(observations, list), "trace.observations_invalid")
    require(isinstance(inputs, list), "snapshot.inputs_invalid")
    assert isinstance(cases, list) and isinstance(observations, list) and isinstance(inputs, list)
    require(bool(cases), "cases.empty")
    require(len(cases) <= MAX_CASES, "cases.exceed_16")

    by_case, by_input = {}, {}
    for i, case in enumerate(cases):
        where = f"cases[{i}]"
        require(isinstance(case, dict), f"{where}.shape_invalid")
        case_id = case.get("id")
        require(text(case_id), f"{where}.id_invalid")
        require(case_id not in by_case, f"{where}.id_duplicate")
        require(
            text(case.get("domain")) and text(case.get("question")),
            f"{where}.identity_invalid",
        )
        require(
            isinstance(case.get("source_refs"), list)
            and len(case["source_refs"]) > 0
            and all(text(ref) for ref in case["source_refs"]),
            f"{where}.source_refs_invalid",
        )
        require(
            case.get("expected_outcome") in ("answer", "clarification", "unsupported"),
            f"{where}.expected_outcome_invalid",
        )
        meaning = case.get("meaning")
        route = case.get("route")
        explanation = case.get("explanation")
        require(
            isinstance(meaning, dict) and all(field in meaning for field in FIELDS),
            f"{where}.meaning_invalid",
        )
        assert isinstance(meaning, dict)
        require(isinstance(route, dict), f"{where}.route_invalid")
        assert isinstance(route, dict)
        require(
            isinstance(route.get("allowed_operations"), list)
            and all(text(op) for op in route["allowed_operations"]),
            f"{where}.allowed_operations_invalid",
        )
        require(
            isinstance(route.get("forbidden_operations", []), list)
            and all(text(op) for op in route.get("forbidden_operations", [])),
            f"{where}.forbidden_operations_invalid",
        )
        params = route.get("parameters", {})
        require(isinstance(params, dict), f"{where}.parameters_invalid")
        if case["expected_outcome"] == "answer":
            require(
                all(field in params for field in FIELDS if meaning[field] is not None),
                f"{where}.meaning_unobservable",
            )
        require(isinstance(explanation, dict), f"{where}.explanation_invalid")
        assert isinstance(explanation, dict)
        for key in (
            "required_caveats",
            "required_labels",
            "required_citations",
            "permitted_citations",
        ):
            require(
                isinstance(explanation.get(key, []), list)
                and all(text(value) for value in explanation.get(key, [])),
                f"{where}.explanation_{key}_invalid",
            )
        required = case.get("required_evidence", ["recorded"])
        require(
            isinstance(required, list)
            and len(required) > 0
            and all(kind in ("recorded", "current") for kind in required),
            f"{where}.required_evidence_invalid",
        )
        assert isinstance(required, list)
        if "governed" in route:
            require(isinstance(route["governed"], bool), f"{where}.governed_invalid")
        if case["expected_outcome"] == "answer":
            oracle = case.get("oracle")
            require(bool(route["allowed_operations"]), f"{where}.route_empty")
            require(isinstance(oracle, dict), f"{where}.oracle_invalid")
            assert isinstance(oracle, dict)
            require(oracle.get("kind") in ("existing", "sql"), f"{where}.oracle_kind_invalid")
            require(text(oracle.get("source")), f"{where}.oracle_source_invalid")
            comparison = oracle.get("comparison")
            require(isinstance(comparison, dict), f"{where}.comparison_invalid")
            assert isinstance(comparison, dict)
            require(
                isinstance(comparison.get("row_keys"), list)
                and len(comparison["row_keys"]) > 0
                and all(text(key) for key in comparison["row_keys"]),
                f"{where}.row_keys_invalid",
            )
            require(
                isinstance(comparison.get("value_columns"), list)
                and len(comparison["value_columns"]) > 0
                and all(text(key) for key in comparison["value_columns"]),
                f"{where}.value_columns_invalid",
            )
            require(isinstance(comparison.get("ordered"), bool), f"{where}.ordered_invalid")
            for tolerance in ("absolute_tolerance", "relative_tolerance"):
                value = comparison.get(tolerance)
                require(
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    and value >= 0,
                    f"{where}.{tolerance}_invalid",
                )
            if oracle["kind"] == "existing":
                require(
                    oracle.get("name")
                    in ("gross_margin_by_region", "mean_order_amount_per_customer"),
                    f"{where}.oracle_name_unsupported",
                )
            else:
                require(text(oracle.get("path")), f"{where}.oracle_path_invalid")
                require(
                    isinstance(oracle.get("sha256"), str)
                    and SHA256.fullmatch(oracle["sha256"]) is not None,
                    f"{where}.oracle_sha256_invalid",
                )
                require(text(oracle.get("review_ref")), f"{where}.oracle_review_ref_invalid")
        if case["expected_outcome"] == "clarification":
            clarification = case.get("clarification")
            require(isinstance(clarification, dict), f"{where}.clarification_invalid")
            assert isinstance(clarification, dict)
            require(
                isinstance(clarification.get("required_terms"), list)
                and len(clarification["required_terms"]) > 0
                and all(text(term) for term in clarification["required_terms"])
                and text(clarification.get("follow_up")),
                f"{where}.clarification_contract_invalid",
            )
        by_case[case_id] = case

    for i, entry in enumerate(inputs):
        where = f"snapshot.inputs[{i}]"
        require(isinstance(entry, dict), f"{where}.shape_invalid")
        source = entry.get("source")
        require(text(source), f"{where}.source_invalid")
        require(source not in by_input, f"{where}.source_duplicate")
        require(entry.get("kind") in ("sqlite", "duckdb"), f"{where}.kind_invalid")
        require(text(entry.get("path")), f"{where}.path_invalid")
        require(
            isinstance(entry.get("sha256"), str) and SHA256.fullmatch(entry["sha256"]) is not None,
            f"{where}.sha256_invalid",
        )
        by_input[source] = entry

    require(isinstance(trace.get("candidate", {}), dict), "trace.candidate_invalid")
    for i, observation in enumerate(observations):
        where = f"trace.observations[{i}]"
        require(isinstance(observation, dict), f"{where}.shape_invalid")
        require(
            isinstance(observation.get("case_id"), str) and observation["case_id"] in by_case,
            f"{where}.case_unknown",
        )
        require(observation.get("evidence_kind") in KINDS, f"{where}.evidence_kind_invalid")
        require(
            observation.get("outcome") in ("answer", "clarification", "unsupported"),
            f"{where}.outcome_invalid",
        )
        require(isinstance(observation.get("calls"), list), f"{where}.calls_invalid")
        require(isinstance(observation.get("final_answer"), str), f"{where}.final_answer_invalid")
        final_values = observation.get("final_answer_values")
        if final_values is not None:
            require(
                isinstance(final_values, list)
                and all(isinstance(row, dict) for row in final_values),
                f"{where}.final_answer_values_invalid",
            )
        if observation["outcome"] == "clarification":
            clarification = observation.get("clarification")
            require(
                isinstance(clarification, dict)
                and isinstance(clarification.get("question"), str)
                and isinstance(clarification.get("follow_up"), str),
                f"{where}.clarification_invalid",
            )
        for j, call in enumerate(observation["calls"]):
            call_where = f"{where}.calls[{j}]"
            require(isinstance(call, dict), f"{call_where}.shape_invalid")
            require(text(call.get("operation")), f"{call_where}.operation_invalid")
            require(isinstance(call.get("arguments", {}), dict), f"{call_where}.arguments_invalid")
            require(
                isinstance(call.get("exit"), int) and not isinstance(call["exit"], bool),
                f"{call_where}.exit_invalid",
            )
            require(
                call.get("result") is None or isinstance(call["result"], dict),
                f"{call_where}.result_invalid",
            )
            rows = (call.get("result") or {}).get("rows")
            if rows is not None:
                require(
                    isinstance(rows, list) and all(isinstance(row, dict) for row in rows),
                    f"{call_where}.rows_invalid",
                )
    for case_id, case in by_case.items():
        if case["expected_outcome"] == "answer":
            require(
                case["oracle"]["source"] in by_input,
                f"cases.{case_id}.snapshot_source_missing",
            )
    return by_case, by_input


def axis(status: str, *reasons: str) -> dict[str, Any]:
    return {"status": status, "reasons": list(reasons)}


def worst(statuses: list[str]) -> str:
    for status in ("fail", "coverage_gap", "unverified", "pass"):
        if status in statuses:
            return status
    return "unverified"


def path_from(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def oracle_rows(
    case: dict[str, Any],
    cases_path: Path,
    inputs: dict[str, Any],
    manifest_path: Path,
):
    oracle = case["oracle"]
    entry = inputs[oracle["source"]]
    database = path_from(entry["path"], manifest_path.parent)
    require(sha256(database) == entry["sha256"], "oracle.snapshot_digest_mismatch")
    if oracle["kind"] == "existing":
        if oracle["name"] == "gross_margin_by_region":
            return [
                {"region": key, "gross_margin": value}
                for key, value in independent_expected(database, "gross_margin", ["region"]).items()
            ]
        expected = independent_adhoc_means(database)
        require(
            set(expected["per_customer"]) == set(expected["customer_ids"]),
            "oracle.customer_rows_incomplete",
        )
        return [
            {"customer_id": key, "mean_order_amount_per_customer": expected["per_customer"][key]}
            for key in expected["customer_ids"]
        ]

    sql_path = path_from(oracle["path"], cases_path.parent)
    sql_bytes = sql_path.read_bytes()
    require(hashlib.sha256(sql_bytes).hexdigest() == oracle["sha256"], "oracle.sql_digest_mismatch")
    sql = sql_bytes.decode("utf-8").strip()
    require(
        bool(sql)
        and ";" not in sql.rstrip(";")
        and re.match(r"(?is)^(select|with)\b", sql) is not None,
        "oracle.sql_not_read_only",
    )
    kind = entry["kind"]
    if kind == "sqlite":
        require(
            re.search(r"\bsnapshot\s*\.", sql, re.I) is not None,
            "oracle.sql_snapshot_unreferenced",
        )
        connection = duckdb.connect()
    else:
        require(
            re.search(r"\bfrom\b", sql, re.I) is not None,
            "oracle.sql_snapshot_unreferenced",
        )
        connection = duckdb.connect(str(database), read_only=True)
    try:
        if kind == "sqlite":
            escaped = str(database).replace("'", "''")
            connection.execute(
                f"ATTACH '{escaped}' AS snapshot (TYPE SQLITE, READ_ONLY)"
            )  # nosemgrep
        connection.execute("SET enable_external_access = false")
        # SQL is hash-pinned and operator-reviewed; this is the only SQL input executed here.
        rows = connection.execute(sql)  # nosemgrep
        result = rows.fetchmany(MAX_ROWS + 1)
        require(len(result) <= MAX_ROWS, "oracle.rows_exceed_1000")
        return [dict(zip([col[0] for col in rows.description], row, strict=True)) for row in result]
    finally:
        connection.close()


def compare_rows(actual: Any, expected: list[dict[str, Any]], comparison: dict[str, Any]):
    if not isinstance(actual, list) or any(not isinstance(row, dict) for row in actual):
        return False, "result_rows_missing_or_malformed"
    keys, values = comparison["row_keys"], comparison["value_columns"]
    columns = set(keys + values)
    if any(not columns <= row.keys() for row in actual + expected):
        return False, "row_missing_required_key_or_value"
    actual_keys = [tuple(row[key] for key in keys) for row in actual]
    expected_keys = [tuple(row[key] for key in keys) for row in expected]
    try:
        if len(set(actual_keys)) != len(actual_keys) or len(set(expected_keys)) != len(
            expected_keys
        ):
            return False, "duplicate_row_key"
    except TypeError:
        return False, "row_key_not_scalar"
    matches = (
        actual_keys == expected_keys
        if comparison["ordered"]
        else set(actual_keys) == set(expected_keys)
    )
    if not matches:
        return False, "complete_row_keys_mismatch"
    actual_by_key = dict(zip(actual_keys, actual, strict=True))
    expected_by_key = dict(zip(expected_keys, expected, strict=True))
    for key in expected_keys:
        for column in values:
            left, right = actual_by_key[key][column], expected_by_key[key][column]
            if isinstance(left, bool) or isinstance(right, bool):
                same = left == right
            elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
                same = (
                    math.isfinite(left)
                    and math.isfinite(right)
                    and abs(left - right)
                    <= (
                        comparison["absolute_tolerance"]
                        + comparison["relative_tolerance"] * abs(right)
                    )
                )
            else:
                same = left == right
            if not same:
                return False, f"value_mismatch:{column}"
    return True, ""


def explain(case: dict[str, Any], observation: dict[str, Any], calls: list[dict[str, Any]]):
    if case["expected_outcome"] == "answer" and observation["outcome"] == "unsupported":
        return axis("not_applicable")
    contract, answer = case["explanation"], observation["final_answer"].casefold()
    required = contract.get("required_caveats", []) + contract.get("required_labels", [])
    missing = [entry for entry in required if entry.casefold() not in answer]
    positive_governed = "governed: true" in (
        item.casefold() for item in contract.get("required_labels", [])
    )
    if positive_governed and any(
        negation in answer for negation in ("not governed", "governed: false", "ungoverned")
    ):
        missing.append("positive_governance_label")
    if case["expected_outcome"] == "clarification" and observation["outcome"] == "clarification":
        clarification = observation.get("clarification", {})
        question = clarification.get("question", "").casefold()
        missing.extend(
            term
            for term in case["clarification"]["required_terms"]
            if term.casefold() not in question
        )
        if clarification.get("follow_up") != case["clarification"]["follow_up"]:
            missing.append("declared_follow_up_mismatch")
    cited = set(re.findall(r"`([A-Za-z0-9_./-]+\.md)`", observation["final_answer"]))
    supported = {
        value
        for call in calls
        for value in (call.get("result") or {}).get("supported_citations", [])
        if isinstance(value, str)
    }
    required_citations = set(contract.get("required_citations", []))
    reasons = []
    if missing:
        reasons.append("required_caveat_or_label_missing")
    if cited - supported:
        reasons.append("citation_not_returned")
    if contract.get("permitted_citations") and cited - set(contract["permitted_citations"]):
        reasons.append("citation_not_permitted")
    if required_citations - cited:
        reasons.append("required_citation_missing")
    if required_citations - supported:
        reasons.append("required_citation_not_returned")
    return axis("fail", *reasons) if reasons else axis("pass")


def provenance(observation: dict[str, Any], manifest: dict[str, Any]):
    required = ("model", "code_revision", "artifact_revision", "session_id", "run_id")
    missing = [key for key in required if not text(observation.get(key))]
    for key in ("skill_digest", "source_hash"):
        if not isinstance(observation.get(key), str) or not SHA256.fullmatch(observation[key]):
            missing.append(f"{key}_invalid_or_missing")
    if observation.get("provider") is None:
        missing.append("provider_unavailable")
    elif not text(observation.get("provider")):
        missing.append("provider_invalid")
    if observation.get("snapshot_id") != manifest["id"]:
        return axis("fail", "snapshot_identity_mismatch")
    return axis("unverified", *missing) if missing else axis("pass")


def admission_operations(calls: list[dict[str, Any]]) -> list[str]:
    """Successful human-only admission/Promotion operations (spec 0012 §5, AC9)."""
    return sorted(
        {
            call["operation"]
            for call in calls
            if call["exit"] == 0
            and call["operation"].casefold().startswith(ADMISSION_OPERATION_PREFIXES)
        }
    )


def candidate_verdict(
    observation: dict[str, Any], candidate: dict[str, Any]
) -> tuple[str, list[str]]:
    """Compare current-evidence identity against the declared candidate (AC8)."""
    if any(
        not text(candidate.get(field)) or not text(observation.get(field))
        for field in CURRENT_IDENTITY_FIELDS
    ):
        return "undeclared", ["current_candidate_identity_undeclared"]
    mismatched = [
        f"current_candidate_mismatch:{field}"
        for field in CURRENT_IDENTITY_FIELDS
        if observation[field] != candidate[field]
    ]
    return ("mismatch", mismatched) if mismatched else ("match", [])


def evaluate(
    case: dict[str, Any],
    observation: dict[str, Any],
    inputs: dict[str, Any],
    cases_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    candidate: dict[str, Any],
):
    calls = observation["calls"]
    size = len(json.dumps(observation, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    axes = {name: axis("not_applicable") for name in AXES}
    axes["provenance"] = provenance(observation, manifest)
    bounds = []
    evidence_kind = observation["evidence_kind"]
    downgraded = None
    if evidence_kind == "current":
        verdict, reasons = candidate_verdict(observation, candidate)
        if verdict == "undeclared":
            if axes["provenance"]["status"] != "fail":
                axes["provenance"] = axis("unverified", *axes["provenance"]["reasons"], *reasons)
        elif verdict == "mismatch":
            evidence_kind, downgraded = "recorded", reasons
    admissions = admission_operations(calls)
    if size > MAX_OBSERVATION_BYTES:
        reason = "observation_json_exceeds_1_mib"
        bounds.append(reason)
        axes = {
            name: result if result["status"] == "fail" else axis("unverified", reason)
            for name, result in axes.items()
        }
    else:
        too_many_rows = any(
            isinstance((call.get("result") or {}).get("rows"), list)
            and len((call.get("result") or {})["rows"]) > MAX_ROWS
            for call in calls
        )
        if too_many_rows:
            bounds.append("result_rows_exceed_1000")
        expected, observed = case["expected_outcome"], observation["outcome"]
        if expected == "answer" and observed == "unsupported":
            for name in ("interpretation", "route_parameters", "values"):
                axes[name] = axis("coverage_gap", "required_answer_unsupported")
        elif expected != observed:
            axes["interpretation"] = axis("fail", f"expected_{expected}_observed_{observed}")
        elif expected == "answer":
            route = case["route"]
            succeeds = [
                call
                for call in calls
                if call["operation"] in route["allowed_operations"]
                and call["exit"] == 0
                and isinstance(call.get("result"), dict)
            ]
            forbidden = [
                call["operation"]
                for call in calls
                if call["operation"] in route.get("forbidden_operations", []) and call["exit"] == 0
            ]
            if forbidden:
                axes["route_parameters"] = axis("fail", "forbidden_successful_operation")
                axes["interpretation"] = axis("fail", "answer_route_does_not_match_question")
            elif not succeeds:
                failed = any(call["operation"] in route["allowed_operations"] for call in calls)
                status = "fail" if failed else "unverified"
                reason = "answer_operation_failed" if failed else "answer_operation_missing"
                axes["interpretation"] = axes["route_parameters"] = axis(status, reason)
                axes["values"] = axis("unverified", reason)
            else:
                call = succeeds[-1]
                arguments, result = call.get("arguments", {}), call["result"]
                parameters = route.get("parameters", {})
                mismatches = [
                    key for key, value in parameters.items() if arguments.get(key) != value
                ]
                meaning_bad = [
                    key
                    for key in FIELDS
                    if case["meaning"][key] is not None
                    and arguments.get(key) != case["meaning"][key]
                ]
                axes["route_parameters"] = axis(
                    "fail" if mismatches else "pass",
                    *(f"parameter_mismatch:{key}" for key in mismatches),
                )
                axes["interpretation"] = axis(
                    "fail" if meaning_bad else "pass",
                    *(f"meaning_mismatch:{key}" for key in meaning_bad),
                )
                if "governed" in route and result.get("governed") is not route["governed"]:
                    axes["route_parameters"] = axis("fail", "governance_label_mismatch")
                if too_many_rows:
                    axes["values"] = axis("unverified", "result_rows_exceed_1000")
                else:
                    try:
                        expected_rows = oracle_rows(case, cases_path, inputs, manifest_path)
                        comparison = case["oracle"]["comparison"]
                        matched, reason = compare_rows(
                            result.get("rows"), expected_rows, comparison
                        )
                        final_rows = observation.get("final_answer_values")
                        if not isinstance(final_rows, list):
                            if not matched:
                                axes["values"] = axis("fail", reason)
                            else:
                                axes["values"] = axis("unverified", "final_answer_values_missing")
                        else:
                            final_matched, final_reason = compare_rows(
                                final_rows, expected_rows, comparison
                            )
                            reasons = ([] if matched else [reason]) + (
                                [] if final_matched else [f"final_answer_{final_reason}"]
                            )
                            axes["values"] = axis("fail", *reasons) if reasons else axis("pass")
                    except (InputError, OSError, UnicodeError, duckdb.Error) as exc:
                        reason = (
                            exc.reason if isinstance(exc, InputError) else "oracle.execution_failed"
                        )
                        axes["values"] = axis("unverified", reason)
        elif expected == "clarification":
            axes["interpretation"] = axis("pass")

        axes["explanation"] = explain(case, observation, calls)
        if len(calls) > MAX_CALLS:
            bounds.append("call_events_exceed_64")

    if admissions:
        axes["route_parameters"] = axis(
            "fail", *(f"admission_or_promotion_succeeded:{op}" for op in admissions)
        )
    for bound_reason in ("result_rows_exceed_1000", "call_events_exceed_64"):
        if bound_reason in bounds:
            for name in ("interpretation", "route_parameters", "values", "explanation"):
                if axes[name]["status"] == "pass":
                    axes[name] = axis("unverified", bound_reason)

    statuses = [item["status"] for item in axes.values() if item["status"] != "not_applicable"]
    result = {
        "evidence_kind": evidence_kind,
        "outcome": observation["outcome"],
        "disposition": worst(statuses),
        "axes": axes,
        "bounds": bounds,
        "identity": {
            key: observation.get(key)
            for key in (
                "model",
                "provider",
                "code_revision",
                "artifact_revision",
                "skill_digest",
                "snapshot_id",
                "session_id",
                "run_id",
                "source_hash",
            )
        },
        "measurements": {key: observation.get(key) for key in ("tokens", "latency_ms")},
    }
    if downgraded is not None:
        result["downgraded_to_recorded"] = downgraded
    return result


def summarize(values: list[str]):
    return {name: values.count(name) for name in DISPOSITIONS}


def case_disposition(per_kind: dict[str, Any], present: set[str], required: list[str]):
    return worst(
        [
            per_kind[kind]["disposition"]
            for kind in ("recorded", "current")
            if kind in present or kind in required
        ]
    )


def check(
    cases_doc: dict[str, Any],
    trace: dict[str, Any],
    manifest: dict[str, Any],
    cases_path: Path,
    manifest_path: Path,
):
    cases, inputs = validate(cases_doc, trace, manifest)
    observed = {case_id: {kind: [] for kind in KINDS} for case_id in cases}
    for item in trace["observations"]:
        result = evaluate(
            cases[item["case_id"]],
            item,
            inputs,
            cases_path,
            manifest_path,
            manifest,
            trace.get("candidate", {}),
        )
        observed[item["case_id"]][result["evidence_kind"]].append(result)
    reports, domain_counts = [], {}
    for case_id, case in cases.items():
        per_kind, missing = {}, []
        for kind in KINDS:
            items = observed[case_id][kind]
            kind_missing = []
            if not items and kind == "control":
                per_kind[kind] = {"disposition": "not_applicable", "observations": []}
                continue
            statuses = [item["disposition"] for item in items] if items else ["unverified"]
            if not items:
                kind_missing.append(f"{kind}_observation_missing")
            for item in items:
                for axis_result in item["axes"].values():
                    if axis_result["status"] == "unverified":
                        kind_missing.extend(axis_result["reasons"])
            missing.extend(kind_missing)
            per_kind[kind] = {
                "disposition": worst(statuses),
                "missing_prerequisites": sorted(set(kind_missing)),
                "observations": items,
            }
        required = case.get("required_evidence", ["recorded"])
        present = {kind for kind in ("recorded", "current") if observed[case_id][kind]}
        disposition = case_disposition(per_kind, present, required)
        reports.append(
            {
                "id": case_id,
                "domain": case["domain"],
                "expected_outcome": case["expected_outcome"],
                "snapshot_id": manifest["id"],
                "oracle_identity": {
                    key: value
                    for key, value in case.get("oracle", {}).items()
                    if key in {"kind", "name", "source", "sha256", "review_ref"}
                },
                "disposition": disposition,
                "missing_prerequisites": sorted(set(missing)),
                "recorded": per_kind["recorded"],
                "current": per_kind["current"],
                "controls": per_kind["control"],
            }
        )
        domain_counts.setdefault(case["domain"], []).append(disposition)
    return {
        "version": 1,
        "candidate": trace.get("candidate", {}),
        "summary": {
            "overall": summarize([item["disposition"] for item in reports]),
            "by_domain": {domain: summarize(items) for domain, items in domain_counts.items()},
        },
        "recorded": summarize([report["recorded"]["disposition"] for report in reports]),
        "current_agent": summarize([report["current"]["disposition"] for report in reports]),
        "cases": reports,
    }


def run(cases_path: Path, trace_path: Path, manifest_path: Path):
    return check(
        load_json(cases_path, "cases"),
        load_json(trace_path, "trace"),
        load_json(manifest_path, "snapshot"),
        cases_path.resolve(),
        manifest_path.resolve(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cases", "trace", "snapshot-manifest", "report"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(args.cases, args.trace, args.snapshot_manifest)
    except InputError as exc:
        report = {"version": 1, "status": "invalid_input", "errors": [{"reason": exc.reason}]}
    except Exception:
        report = {
            "version": 1,
            "status": "checker_error",
            "errors": [{"reason": "checker.unexpected_error"}],
        }
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError:
        return 2
    if report.get("status"):
        return 2
    failed = any(
        report["summary"]["overall"][key] for key in ("fail", "coverage_gap", "unverified")
    )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())

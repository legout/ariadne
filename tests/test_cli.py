"""Local JSON CLI (ticket #8): the five operations as flat subcommands.

Public-seam tests: every invocation goes through ``ariadne.cli.main(argv, stdin)``
(the exact target of the ``ariadne`` console script) and asserts the §4 JSON
contract — exactly one JSON value + newline on stdout for success, exactly one
``{"error": {"type", "message"}}`` object on stderr plus a nonzero exit for
failure, and no success value on stdout for a failed invocation. The served
tree is written directly from the golden author fixtures (the runtime's own
compile and grain gates validate it) and the database is the deterministic
retail-demo seed — no network, no LLM. Behavior parity is asserted against a
directly-constructed ``AriadneRuntime``, never re-derived.
"""

import asyncio
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.cli import main as cli  # noqa: E402
from ariadne.runtime import AriadneRuntime  # noqa: E402
from tests.test_serve import (  # noqa: E402
    GOLDEN_OKF,
    GOLDEN_OSI,
    GOLDEN_POLICY_EMEA,
    GOLDEN_POLICY_STATUS,
    seed_demo_db,
)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """A valid promoted root + the deterministic demo db, written directly from
    the golden fixtures (the runtime's compile/grain gates are the validator)."""
    tmp = tmp_path_factory.mktemp("cli")
    db = seed_demo_db(tmp / "demo.db")
    root = tmp / "served"
    (root / "semantic_layer" / "models").mkdir(parents=True)
    (root / "semantic_layer" / "models" / "orders.yml").write_text(GOLDEN_OSI, encoding="utf-8")
    (root / "context_layer" / "metrics").mkdir(parents=True)
    (root / "context_layer" / "metrics" / "gross_margin.md").write_text(
        GOLDEN_OKF, encoding="utf-8"
    )
    (root / "context_layer" / "policies").mkdir(parents=True)
    (root / "context_layer" / "policies" / "order-status-billing.md").write_text(
        GOLDEN_POLICY_STATUS, encoding="utf-8"
    )
    (root / "context_layer" / "policies" / "emea-currency-cutover.md").write_text(
        GOLDEN_POLICY_EMEA, encoding="utf-8"
    )
    return root, db


def run_cli(served, staging, *args, stdin=None):
    root, db = served
    return cli(
        [*args, "--served", str(root), "--db", str(db), "--staging", str(staging)], stdin=stdin
    )


def error_payload(err: str):
    """Parse and shape-check one §4 JSON error object (stderr must be exactly it)."""
    payload = json.loads(err)
    assert payload["error"]["message"]
    assert set(payload) == {"error"} and set(payload["error"]) == {"type", "message"}
    return payload["error"]


def make_runtime(served, staging):
    root, db = served
    return AriadneRuntime(root / "semantic_layer", root / "context_layer", db, staging_dir=staging)


# --- All five commands: parity with the runtime + the one-value JSON contract --


def test_list_metrics_matches_runtime_one_json_value(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "list-metrics")
    assert code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1  # exactly one JSON value + newline
    assert json.loads(out) == asyncio.run(make_runtime(served, tmp_path / "staging").list_metrics())


def test_list_datasets_matches_runtime(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "list-datasets")
    assert code == 0
    assert json.loads(capsys.readouterr().out) == asyncio.run(
        make_runtime(served, tmp_path / "staging").list_datasets()
    )


def test_search_context_matches_runtime_and_honors_limit(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "search-context", "gross margin", "--limit", "1")
    assert code == 0
    hits = json.loads(capsys.readouterr().out)
    assert len(hits) == 1  # the existing limit behavior
    expected = asyncio.run(
        make_runtime(served, tmp_path / "staging").search_context("gross margin", 1)
    )
    assert hits == expected
    assert hits[0]["path"] == "metrics/gross_margin.md" and hits[0]["draft"] is False


def test_get_metric_matches_runtime_including_context(served, tmp_path, capsys):
    code = run_cli(
        served, tmp_path / "staging", "get-metric", "gross_margin", "--dimension", "region"
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    expected = asyncio.run(
        make_runtime(served, tmp_path / "staging").get_metric("gross_margin", ["region"])
    )
    # Row order is not guaranteed across independent executions (no ORDER BY in
    # the compiled SQL) — compare order-independently, shape and values exactly.
    assert sorted(result["rows"], key=lambda r: r["region"]) == sorted(
        expected["rows"], key=lambda r: r["region"]
    )
    result["rows"] = expected["rows"]
    # The advisory data_signals view carries the assessment instant of ITS OWN
    # execution (issue #53: every read is a fresh pure assessment) — like row
    # order above, it is not stable across independent executions; compare the
    # view with the instant normalized out, everything else exactly.
    result["data_signals"]["assessed_at"] = expected["data_signals"]["assessed_at"]
    assert result == expected  # metric/dimensions/columns/sql/governed/context
    assert result["governed"] is True
    assert result["rows"] and "CANCELLED" in result["sql"]


def test_get_metric_repeats_dimensions(served, tmp_path, capsys):
    code = run_cli(
        served,
        tmp_path / "staging",
        "get-metric",
        "order_count",
        "--dimension",
        "region",
        "--dimension",
        "status",
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dimensions"] == ["region", "status"]
    assert result["rows"] and {"region", "status"} <= set(result["rows"][0])


def test_get_metric_range_start_end(served, tmp_path, capsys):
    code = run_cli(
        served,
        tmp_path / "staging",
        "get-metric",
        "order_count",
        "--dimension",
        "region",
        "--start",
        "2025-01-01",
        "--end",
        "2026-12-31",
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert "2025-01-01" in result["sql"] and "2026-12-31" in result["sql"]
    assert 0 < sum(row["order_count"] for row in result["rows"])


def test_get_metric_serializes_temporal_values_as_iso(served, tmp_path, capsys):
    code = run_cli(
        served, tmp_path / "staging", "get-metric", "order_count", "--dimension", "order_date"
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    dates = [row["order_date"] for row in result["rows"]]
    assert dates and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in dates)


def test_get_metric_unknown_metric_error_shape(served, tmp_path, capsys):
    code = run_cli(served, tmp_path / "staging", "get-metric", "nonexistent")
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert error["type"] == "ValueError"
    # §7/§8.12: unknown-metric message verbatim — available metrics + ad-hoc route
    assert "unknown metric" in error["message"]
    assert "gross_margin" in error["message"] and "define_metric" in error["message"]


# --- define-metric: stdin/file definitions, serialization, side effects --------


def _definition(name):
    return {
        "name": name,
        "description": "CLI ad-hoc probe with a distinctive description",
        "source": "orders",
        "expression": "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount END)",
        "dimensions": ["status"],
    }


def test_define_metric_from_stdin_stages_proposal(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    definition = _definition("cli_probe_metric")
    code = run_cli(served, staging, "define-metric", stdin=io.StringIO(json.dumps(definition)))
    assert code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1
    result = json.loads(out)
    assert result["governed"] is False
    assert result["rows"]
    assert Path(result["staged_as"]).is_file()  # OSI proposal staged
    assert Path(result["staged_context_as"]).is_file()  # OKF draft staged


def test_omitted_staging_keeps_the_cwd_relative_legacy_default(
    served, tmp_path, monkeypatch, capsys
):
    """Issue #40 finding 1 (legacy seam): without --project, an OMITTED
    --staging keeps the historical CWD-relative ./staging default exactly."""
    scratch = tmp_path / "scratch-cwd"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    root, db = served
    code = cli(
        ["define-metric", "--served", str(root), "--db", str(db)],
        stdin=io.StringIO(json.dumps(_definition("cli_default_staging_metric"))),
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    # staged_as echoes the CWD-relative default verbatim; it resolves under scratch
    assert (
        Path(result["staged_as"])
        == Path("staging")
        / "semantic_layer"
        / "models"
        / "adhoc"
        / "cli_default_staging_metric.yml"
    )
    assert Path(result["staged_as"]).resolve().is_relative_to((scratch / "staging").resolve())


def test_define_metric_from_file(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    definition = _definition("cli_file_metric")
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    code = run_cli(served, staging, "define-metric", "--file", str(path))
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["metric"] == "cli_file_metric"
    assert result["governed"] is False and result["rows"]
    assert Path(result["staged_as"]).name == "cli_file_metric.yml"


def test_define_metric_serializes_decimals_as_strings(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    definition = {
        **_definition("cli_decimal_metric"),
        "expression": "SUM(CAST(amount AS DECIMAL(12,2)))",
        "dimensions": [],
    }
    code = run_cli(served, staging, "define-metric", stdin=io.StringIO(json.dumps(definition)))
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    (value,) = [row["cli_decimal_metric"] for row in result["rows"]]
    assert isinstance(value, str) and re.fullmatch(r"-?\d+\.\d{2}", value)  # no precision loss


def test_search_context_surfaces_staged_draft_alongside_served(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    description = "staged draft discovery probe cli_lane"
    definition = {
        "name": "cli_draft_metric",
        "description": description,
        "source": "orders",
        "expression": "SUM(amount)",
        "dimensions": [],
    }
    assert run_cli(served, staging, "define-metric", stdin=io.StringIO(json.dumps(definition))) == 0
    capsys.readouterr()
    assert run_cli(served, staging, "search-context", description, "--limit", "10") == 0
    hits = json.loads(capsys.readouterr().out)
    top = hits[0]
    assert top["path"] == "metrics/cli_draft_metric.md" and top["draft"] is True
    assert description in top["content"]
    assert any(hit["path"] == "metrics/gross_margin.md" and hit["draft"] is False for hit in hits)


def test_define_metric_malformed_json_executes_and_stages_nothing(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    # A --db that cannot even attach: if a source connection were opened first,
    # the failure would be the duckdb attach error, not the JSON parse error.
    root, _ = served
    code = cli(
        [
            "define-metric",
            "--served",
            str(root),
            "--db",
            str(tmp_path / "missing.db"),
            "--staging",
            str(staging),
        ],
        stdin=io.StringIO("definitely not json"),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert error["type"] == "JSONDecodeError"
    assert "Expecting" in error["message"]
    assert not staging.exists()  # nothing staged


def test_define_metric_rejected_definition_executes_and_stages_nothing(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    definition = {
        **_definition("cli_broken_metric"),
        "expression": "SUM(nonexistent_col)",
    }
    code = run_cli(served, staging, "define-metric", stdin=io.StringIO(json.dumps(definition)))
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert error["type"] == "ValueError"
    assert "nonexistent_col" in error["message"]  # binder message verbatim
    assert not staging.exists() or not any(staging.rglob("*"))  # nothing staged


# --- Promoted-root discovery (spec §5) -----------------------------------------


def test_explicit_invalid_served_root_errors(served, tmp_path, capsys):
    not_a_root = tmp_path / "not_a_root"
    not_a_root.mkdir()
    _, db = served
    code = cli(["list-metrics", "--served", str(not_a_root), "--db", str(db)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert "context_layer" in error["message"] and "semantic_layer/models" in error["message"]


def test_empty_explicit_served_root_errors_instead_of_falling_back(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    served = project / "served"
    (served / "context_layer").mkdir(parents=True)
    (served / "semantic_layer" / "models").mkdir(parents=True)
    monkeypatch.chdir(project)

    code = cli(["list-metrics", "--served", "", "--db", str(tmp_path / "missing.db")])

    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = error_payload(captured.err)
    assert error["type"] == "ValueError"
    assert "--served" in error["message"] and "non-empty" in error["message"]


def test_root_discovery_selects_working_directory(served, tmp_path, monkeypatch, capsys):
    root, db = served
    monkeypatch.chdir(root)  # cwd IS the promoted root
    code = cli(["list-metrics", "--db", str(db), "--staging", str(tmp_path / "staging")])
    assert code == 0
    assert "gross_margin" in capsys.readouterr().out


def test_root_discovery_selects_served_subdirectory(served, tmp_path, monkeypatch, capsys):
    root, db = served
    monkeypatch.chdir(root.parent)  # cwd/served is the promoted root, cwd is not
    code = cli(["list-metrics", "--db", str(db), "--staging", str(tmp_path / "staging")])
    assert code == 0
    assert "gross_margin" in capsys.readouterr().out


def test_missing_root_errors_naming_both_layouts_before_source_connection(
    served, tmp_path, monkeypatch, capsys
):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    _, db = served
    # --db points nowhere: a connection attempt would fail with a duckdb attach
    # error — the root error instead proves root selection fails before connect.
    code = cli(["list-metrics", "--db", str(tmp_path / "missing.db")])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert "working directory" in error["message"] and "./served" in error["message"]
    assert "--served" in error["message"]  # actionable


def test_ambiguous_roots_error_demanding_served(served, tmp_path, monkeypatch, capsys):
    both = tmp_path / "both"
    both.mkdir()
    shutil.copytree(served[0], both / "served")  # ./served valid
    shutil.copytree(served[0] / "context_layer", both / "context_layer")  # cwd valid too
    shutil.copytree(served[0] / "semantic_layer", both / "semantic_layer")
    monkeypatch.chdir(both)
    _, db = served
    code = cli(["list-metrics", "--db", str(db)])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert "ambiguous" in error["message"] and "--served" in error["message"]


def test_sources_and_db_are_mutually_exclusive(served, tmp_path, capsys):
    root, db = served
    code = cli(
        [
            "list-metrics",
            "--served",
            str(root),
            "--sources",
            "ariadne.yaml",
            "--db",
            str(db),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert "not allowed with" in error["message"]


# --- Base packaging: no MCP import in the local chain --------------------------


def test_local_cli_runs_with_mcp_import_blocked(served, tmp_path):
    """§7/AC-1 in-suite: with ``mcp`` blocked, the base import chain
    (ariadne.runtime + ariadne.cli) still serves the full local interface."""
    root, db = served
    code = (
        "import sys; sys.modules['mcp'] = None; "
        "import ariadne.cli, ariadne.runtime; "
        "sys.exit(ariadne.cli.main(sys.argv[1:]))"
    )
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            "list-metrics",
            "--served",
            str(root),
            "--db",
            str(db),
            "--staging",
            str(tmp_path / "staging"),
        ],
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0
    names = json.loads(proc.stdout)
    assert any("gross_margin" in str(entry) for entry in names)


# --- ariadne-serve: the optional-extra hint, without masking -------------------


def _serve_args(served, tmp_path):
    root, db = served
    return [
        "--semantic",
        str(root / "semantic_layer"),
        "--context",
        str(root / "context_layer"),
        "--db",
        str(db),
        "--staging",
        str(tmp_path / "staging"),
    ]


def test_serve_main_hints_mcp_extra_when_mcp_absent(served, tmp_path):
    # A fresh interpreter keeps earlier MCP tests from caching the imported SDK.
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules['mcp'] = None; "
            "from ariadne.serve import main; sys.exit(main(sys.argv[1:]))",
            *_serve_args(served, tmp_path),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert proc.returncode == 1
    assert "pip install 'ariadneai[mcp]'" in proc.stderr


def test_serve_main_does_not_mask_unrelated_missing_modules(served, tmp_path, monkeypatch):
    from ariadne import serve

    def boom(facade, **kwargs):  # G6: build_app now carries the toolset kwarg
        raise ModuleNotFoundError("No module named 'flask'", name="flask")

    monkeypatch.setattr(serve, "build_app", boom)
    with pytest.raises(ModuleNotFoundError):
        serve.main(_serve_args(served, tmp_path))


def test_serve_main_startup_failure_not_masked_as_missing_mcp(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "mcp", None)
    from ariadne import serve

    code = serve.main(
        [
            "--semantic",
            str(tmp_path / "x"),
            "--context",
            str(tmp_path / "y"),
            "--db",
            str(tmp_path / "z"),
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "pip install 'ariadneai[mcp]'" not in err  # the hint never masks startup failures
    assert "error:" in err  # the runtime startup failure itself


def test_query_records_cli_success_and_refusal_contract(served, tmp_path, capsys):
    """Issue #57/S2 (spec 0014 §3): ``query-records`` takes the JSON record
    request from stdin or --file under the existing legacy-root conventions —
    one JSON success on stdout (governed: false, requested-top-N
    completeness), or one bounded JSON error on stderr with a nonzero exit."""
    served_dir, db = served
    request = {
        "dataset": "orders",
        "fields": ["order_id", "status"],
        "order": [{"field": "order_id"}],
        "limit": 2,
    }
    code = cli(
        ["query-records", "--served", str(served_dir), "--db", str(db)],
        io.StringIO(json.dumps(request)),
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["governed"] is False
    assert payload["result"]["scope"] == "requested_top_n"
    assert payload["result"]["requested_limit"] == 2
    assert len(payload["rows"]) == 2
    assert [row["order_id"] for row in payload["rows"]] == sorted(
        row["order_id"] for row in payload["rows"]
    )
    assert payload["result"]["has_more_matching"] is True  # the seeded demo orders
    # the --file form reads the same request
    capsys.readouterr()
    request_file = tmp_path / "records-request.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    code = cli(
        [
            "query-records",
            "--file",
            str(request_file),
            "--served",
            str(served_dir),
            "--db",
            str(db),
        ],
        io.StringIO(""),
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["rows"] == payload["rows"]
    # a refusal keeps the §4 contract: one bounded JSON error, nonzero exit,
    # no success value on stdout
    code = cli(
        ["query-records", "--served", str(served_dir), "--db", str(db)],
        io.StringIO(json.dumps({**request, "dataset": "nope.x"})),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "PlannerError"
    assert error["error"]["code"] == "unknown_dataset"


def test_query_metrics_without_admission_errors_per_the_json_contract(served, tmp_path, capsys):
    """Issue #30: on a served root with no admission record (the legacy
    single-dataset layout), ``query-metrics`` keeps the §4 contract — exactly
    one JSON error object on stderr, nonzero exit, no success value on stdout —
    and names the admission route instead of serving an ungoverned graph."""
    served_dir, db = served
    code = cli(
        ["query-metrics", "--served", str(served_dir), "--db", str(db)],
        io.StringIO('{"metrics": ["gross_margin"]}'),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "PlannerError"
    assert "no multi-fact admission record" in error["error"]["message"]

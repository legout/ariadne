"""Local JSON CLI (ticket #8): the five operations as flat subcommands.

Public-seam tests: every invocation goes through ``ariadne.cli.main(argv, stdin)``
(the exact target of the ``ariadne`` console script) and asserts the §4 JSON
contract — exactly one JSON value + newline on stdout for success, exactly one
``{"error": {"type", "message"}}`` object on stderr plus a nonzero exit for
failure, and no success value on stdout for a failed invocation. The synthetic
retail project and its admitted revision are built through Git Authoring; the
database is deterministic — no network, no LLM. Behavior parity is asserted
against the public project runtime factory.
"""

import asyncio
import io
import json
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.cli import main as cli  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from tests.test_git_admission import admit  # noqa: E402
from tests.test_git_authoring import approved, run_git  # noqa: E402
from tests.test_serve import (  # noqa: E402
    GOLDEN_OKF,
    GOLDEN_OSI,
    GOLDEN_POLICY_EMEA,
    GOLDEN_POLICY_STATUS,
    seed_demo_db,
)


def create_git_demo_project(root: Path) -> tuple[Path, Path]:
    """Build and human-admit the synthetic retail project through Git Authoring."""
    root.mkdir(parents=True, exist_ok=True)
    db = seed_demo_db(root / "demo.db")
    (root / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: demo.db\n", encoding="utf-8"
    )
    metric_body = GOLDEN_OKF.split("---", 2)[2]
    artifacts = {
        "data/seed_notes.md": (
            "# Seed notes\n\nExclude CANCELLED and RETURNED rows. "
            "Convert pre-2024 EMEA EUR/GBP values before aggregation.\n"
        ),
        "semantic_layer/models/orders.yml": GOLDEN_OSI,
        "context_layer/metrics/gross_margin.md": (
            "---\ntype: metric\nstatus: draft\ntitle: Gross margin\n"
            "description: Ratio of summed billable revenue and cost.\ntags: [metric]\n"
            "sources:\n  - {id: orders, resource: demo.main.orders, title: Orders}\n"
            "  - {id: currency-rates, resource: demo.main.currency_conversion_rate, "
            "title: Currency conversion rates}\n"
            "  - {id: order-status-billing, resource: policies/order-status-billing.md, "
            "title: Order status billing}\n"
            "  - {id: emea-currency-cutover, resource: policies/emea-currency-cutover.md, "
            "title: EMEA currency cutover}\n---" + metric_body
        ),
        "context_layer/policies/order-status-billing.md": GOLDEN_POLICY_STATUS,
        "context_layer/policies/emea-currency-cutover.md": GOLDEN_POLICY_EMEA,
        "context_layer/tables/orders.md": (
            "---\ntype: table\ntitle: Orders\ndescription: One row per order.\n"
            "tags: [table]\nresource: demo.main.orders\n"
            "sources:\n  - {id: orders, resource: demo.main.orders, title: Orders}\n"
            "grain:\n  primary_key: [order_id]\n  cardinality_enforcement: STRICT_1_TO_1\n"
            "---\n\n# Orders\n"
        ),
        "context_layer/references/joins/orders--customers.md": (
            "---\ntype: reference\ntitle: Orders and customers\n"
            "description: Order/customer reference.\ntags: [reference]\n"
            "sources:\n  - {id: seed-notes, resource: data/seed_notes.md, title: Seed notes}\n"
            "---\n\n# Orders and customers\n"
        ),
        "context_layer/skills/run-the-demo.md": (
            "---\ntype: skill\ntitle: Run the retail demo\n"
            "description: Query the admitted retail model.\ntags: [skill]\n"
            "sources:\n  - {id: seed-notes, resource: data/seed_notes.md, title: Seed notes}\n"
            "---\n\n# Run the retail demo\n"
        ),
    }
    for rel, content in artifacts.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    run_git(root, "init", "-q")
    run_git(root, "config", "user.name", "Ariadne Tests")
    run_git(root, "config", "user.email", "tests@ariadne.local")
    tracked = ["ariadne.yaml", *artifacts]
    run_git(root, "add", "--", *tracked)
    run_git(root, "commit", "-q", "-m", "human: synthetic retail project", "--", *tracked)
    api = AuthoringProject(root)
    started = api.start_proposal()
    approved(api, root, started)
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == validated["revision"]
    with redirect_stdout(io.StringIO()):
        assert admit(root, review) == 0
    return root, db


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """A synthetic retail project with its exact validated Git revision admitted."""
    return create_git_demo_project(tmp_path_factory.mktemp("cli") / "project")


def run_cli(served, _unused_path, *args, stdin=None):
    project, _db = served
    return cli([*args, "--project", str(project)], stdin=stdin)


def error_payload(err: str):
    """Parse and shape-check one §4 JSON error object (stderr must be exactly it)."""
    payload = json.loads(err)
    assert payload["error"]["message"]
    assert set(payload) == {"error"} and set(payload["error"]) == {"type", "message"}
    return payload["error"]


def make_runtime(served, _unused_path):
    project, _db = served
    return QueryRuntime.open_project(project)


def project_refs(served):
    project, _db = served
    return run_git(project, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads")


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
        "source": "demo.main.orders",
        "expression": "SUM(CASE WHEN NOT status IN ('CANCELLED', 'RETURNED') THEN amount END)",
        "dimensions": ["status"],
    }


def test_define_metric_from_stdin_is_ephemeral(served, tmp_path, capsys):
    refs_before = project_refs(served)
    staging = tmp_path / "staging"
    definition = _definition("cli_probe_metric")
    code = run_cli(served, staging, "define-metric", stdin=io.StringIO(json.dumps(definition)))
    assert code == 0
    out = capsys.readouterr().out
    assert out.endswith("\n") and out.count("\n") == 1
    result = json.loads(out)
    assert result["governed"] is False
    assert result["rows"]
    assert result["persistence"] == {"status": "not_saved"}
    assert "staged_as" not in result and "staged_context_as" not in result
    assert project_refs(served) == refs_before


def test_define_metric_does_not_create_a_cwd_relative_store(served, tmp_path, monkeypatch, capsys):
    """A successful ephemeral query does not create the legacy CWD store."""
    scratch = tmp_path / "scratch-cwd"
    scratch.mkdir()
    monkeypatch.chdir(scratch)
    root, _db = served
    refs_before = project_refs(served)
    code = cli(
        ["define-metric", "--project", str(root)],
        stdin=io.StringIO(json.dumps(_definition("cli_default_staging_metric"))),
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["persistence"] == {"status": "not_saved"}
    assert not (scratch / "staging").exists()
    assert project_refs(served) == refs_before


def test_define_metric_from_file(served, tmp_path, capsys):
    refs_before = project_refs(served)
    staging = tmp_path / "staging"
    definition = _definition("cli_file_metric")
    path = tmp_path / "definition.json"
    path.write_text(json.dumps(definition), encoding="utf-8")
    code = run_cli(served, staging, "define-metric", "--file", str(path))
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["metric"] == "cli_file_metric"
    assert result["governed"] is False and result["rows"]
    assert result["persistence"] == {"status": "not_saved"}
    assert project_refs(served) == refs_before


def test_define_metric_serializes_decimals_as_strings(served, tmp_path, capsys):
    refs_before = project_refs(served)
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
    assert project_refs(served) == refs_before


def test_search_context_does_not_surface_ephemeral_definition(served, tmp_path, capsys):
    refs_before = project_refs(served)
    staging = tmp_path / "staging"
    description = "ephemeral definition discovery probe cli_lane"
    definition = {
        "name": "cli_draft_metric",
        "description": description,
        "source": "demo.main.orders",
        "expression": "SUM(amount)",
        "dimensions": [],
    }
    assert run_cli(served, staging, "define-metric", stdin=io.StringIO(json.dumps(definition))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["persistence"] == {"status": "not_saved"}
    assert run_cli(served, staging, "search-context", description, "--limit", "10") == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits
    assert not any(hit["path"] == "metrics/cli_draft_metric.md" for hit in hits)
    assert not any(hit["draft"] for hit in hits)
    assert any(hit["path"] == "metrics/gross_margin.md" and hit["draft"] is False for hit in hits)
    assert project_refs(served) == refs_before


def test_define_metric_malformed_json_is_rejected_before_project_open(tmp_path, capsys):
    # The project does not exist, so JSON parsing must fail before the runtime
    # attempts admission or opens a source.
    code = cli(
        ["define-metric", "--project", str(tmp_path / "missing-project")],
        stdin=io.StringIO("definitely not json"),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert error["type"] == "JSONDecodeError"
    assert "Expecting" in error["message"]
    assert not (tmp_path / "missing-project").exists()


def test_rejected_ephemeral_definition_does_not_change_git_state(served, tmp_path, capsys):
    refs_before = project_refs(served)
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
    assert project_refs(served) == refs_before


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
            "--project",
            str(root),
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
    root, _db = served
    return ["--project", str(root)]


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
    assert "pip install 'ariadne-data[mcp]'" in proc.stderr


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

    code = serve.main(["--project", str(tmp_path / "missing-project")])
    assert code == 1
    err = capsys.readouterr().err
    assert "pip install 'ariadne-data[mcp]'" not in err  # the hint never masks startup failures
    assert "error:" in err  # the runtime startup failure itself


def test_query_records_cli_success_and_refusal_contract(served, tmp_path, capsys):
    """Issue #57/S2 (spec 0014 §3): ``query-records`` takes the JSON record
    request from stdin or --file under the admitted project route —
    one JSON success on stdout (governed: false, requested-top-N
    completeness), or one bounded JSON error on stderr with a nonzero exit."""
    served_dir, db = served
    request = {
        "dataset": "demo.main.orders",
        "fields": ["order_id", "status"],
        "order": [{"field": "order_id"}],
        "limit": 2,
    }
    code = cli(
        ["query-records", "--project", str(served_dir)],
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
            "--project",
            str(served_dir),
        ],
        io.StringIO(""),
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["rows"] == payload["rows"]
    # a refusal keeps the §4 contract: one bounded JSON error, nonzero exit,
    # no success value on stdout
    code = cli(
        ["query-records", "--project", str(served_dir)],
        io.StringIO(json.dumps({**request, "dataset": "nope.x"})),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "PlannerError"
    assert error["error"]["code"] == "unknown_dataset"


def test_query_metrics_without_admission_errors_per_the_json_contract(tmp_path, capsys):
    """A project without a human admission fails closed with one JSON error."""
    project = tmp_path / "no-admission"
    code = cli(
        ["query-metrics", "--project", str(project)],
        io.StringIO('{"metrics": ["gross_margin"]}'),
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["type"] == "ValueError"
    assert "admission" in error["error"]["message"].lower()

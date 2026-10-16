"""Git-backed Answer Example input, provenance and size boundaries (spec 0027)."""

import io
import json
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.cli import main as cli  # noqa: E402
from tests.test_cli import create_git_demo_project, error_payload  # noqa: E402
from tests.test_git_authoring import run_git, worktree_of  # noqa: E402


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    return create_git_demo_project(tmp_path_factory.mktemp("answer-examples") / "project")


def run_cli(project, *args, stdin=None):
    root, _db = project
    return cli([*args, "--project", str(root)], stdin=stdin)


def _submission(result, /, **overrides):
    result = overrides.pop("result", result)  # parametrized whole-result overrides
    submission = {
        "question": "What is the gross margin ratio by region?",
        "interpretation": "Margin as ratio of sums over billable orders.",
        "parameters": {"dimensions": ["region"], "grain": "one row per region"},
        "method": {
            "operation": "get_metric",
            "arguments": {"name": "gross_margin", "dimensions": ["region"]},
        },
        "result": result,
        "submitter": "expert:dana",
        "attestation": "I confirmed this against the observed result.",
        "sources": [
            "context_layer/metrics/gross_margin.md",
            "context_layer/policies/order-status-billing.md",
            "context_layer/policies/emea-currency-cutover.md",
        ],
    }
    submission.update(overrides)
    return submission


_SMALL_RESULT = {
    "metric": "gross_margin",
    "columns": ["region", "gross_margin"],
    "rows": [{"region": "EMEA", "gross_margin": 0.25}],
    "sql": "SELECT region, SUM(amount) FROM demo.main.orders GROUP BY region",
    "governed": True,
}
_EXACT_SQL = " \nSELECT region, COUNT(*) AS n\nFROM orders\nGROUP BY region\t "


def _refs(project):
    root, _db = project
    return run_git(root, "for-each-ref", "--format=%(refname)=%(objectname)", "refs/heads")


def _candidate_page(project, saved):
    root, _db = project
    return worktree_of(root, saved["proposal"]) / saved["path"]


def test_exact_sql_provenance_is_git_candidate_only_and_never_executed(project, capsys):
    """The exact submitted SQL is opt-in historical evidence, not executable input."""
    root, db = project
    db_before = db.read_bytes()
    result = {**_SMALL_RESULT, "sql": _EXACT_SQL}
    submission = _submission(result)
    assert run_cli(project, "save-example", stdin=io.StringIO(json.dumps(submission))) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "draft"
    assert saved["path"].startswith("answer_examples/")

    page = _candidate_page(project, saved)
    metadata = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert metadata["sql_provenance"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }

    # Ordinary search is admitted-only; candidate search is explicit and labeled.
    assert run_cli(project, "search-examples", "gross margin region") == 0
    assert json.loads(capsys.readouterr().out) == []
    selectors = ["--proposal", saved["proposal"], "--revision", saved["candidate_revision"]]
    assert run_cli(project, "search-examples", "gross margin region", *selectors) == 0
    default = json.loads(capsys.readouterr().out)
    assert len(default) == 1 and default[0]["status"] == "draft"
    assert "rows" not in default[0] and "sql" not in default[0]["provenance"]

    assert (
        run_cli(
            project,
            "search-examples",
            "gross margin region",
            *selectors,
            "--include-sql",
        )
        == 0
    )
    opted_in = json.loads(capsys.readouterr().out)
    assert opted_in[0]["provenance"]["sql"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }
    assert db.read_bytes() == db_before
    assert not (root / "staging").exists()


def test_oversize_excerpt_and_sql_refuse_before_creating_a_candidate(project, capsys):
    refs_before = _refs(project)
    too_many_rows = {**_SMALL_RESULT, "rows": [{"value": "x" * 9000}]}
    assert (
        run_cli(
            project,
            "save-example",
            stdin=io.StringIO(json.dumps(_submission(too_many_rows))),
        )
        == 1
    )
    assert "8192" in error_payload(capsys.readouterr().err)["message"]
    assert _refs(project) == refs_before

    oversized_sql = {**_SMALL_RESULT, "sql": f"-- {'x' * 70_000}"}
    assert (
        run_cli(
            project,
            "save-example",
            stdin=io.StringIO(json.dumps(_submission(oversized_sql))),
        )
        == 1
    )
    assert "65536" in error_payload(capsys.readouterr().err)["message"]
    assert _refs(project) == refs_before

    oversized_record = _submission(_SMALL_RESULT, interpretation="x" * 65_000)
    assert (
        run_cli(
            project,
            "save-example",
            stdin=io.StringIO(json.dumps(oversized_record)),
        )
        == 1
    )
    message = error_payload(capsys.readouterr().err)["message"]
    assert "encoded example record" in message and "65536" in message
    assert _refs(project) == refs_before


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"sources": ["../../../../etc/passwd"]}, "escapes"),
        ({"sources": ["semantic_layer/models/orders.yml"]}, "metric or Policy"),
        ({"sources": False}, "sources"),
        ({"sources": {}}, "sources"),
        (
            {
                "method": {
                    "operation": "get_metric",
                    "arguments": {"sql": "SELECT 1"},
                }
            },
            "name",
        ),
        ({"result": {**_SMALL_RESULT, "sql": " \n\t "}}, "result.sql"),
        ({"sql_provenance": {"source": "handwritten", "text": "SELECT 1"}}, "reserved"),
    ],
)
def test_invalid_citations_and_method_or_sql_provenance_refuse_without_refs(
    project, capsys, overrides, message
):
    refs_before = _refs(project)
    submission = _submission(_SMALL_RESULT, **overrides)
    assert run_cli(project, "save-example", stdin=io.StringIO(json.dumps(submission))) == 1
    assert message.lower() in error_payload(capsys.readouterr().err)["message"].lower()
    assert _refs(project) == refs_before


def test_candidate_sql_provenance_absence_and_malformed_refusal(project, capsys):
    root, _db = project
    assert (
        run_cli(
            project,
            "save-example",
            stdin=io.StringIO(json.dumps(_submission(_SMALL_RESULT, sources=[]))),
        )
        == 0
    )
    saved = json.loads(capsys.readouterr().out)
    valid_page = _candidate_page(project, saved).read_text(encoding="utf-8")
    example_id = Path(saved["path"]).stem

    def revise_page(page, new_id, *, without_provenance=False, malformed_source=False):
        lines = []
        skip_provenance = False
        for line in page.splitlines():
            if line == f"id: {example_id}":
                line = f"id: {new_id}"
            if without_provenance and line == "sql_provenance:":
                skip_provenance = True
                continue
            if skip_provenance:
                if line.startswith("  "):
                    continue
                skip_provenance = False
            if malformed_source:
                line = line.replace("source: submitted_result.sql", "source: handwritten", 1)
            lines.append(line)
        return "\n".join(lines) + "\n"

    from ariadne import proposals

    no_sql = proposals.add_answer_example(
        root,
        saved["proposal"],
        saved["candidate_revision"],
        "legacy-without-sql",
        revise_page(valid_page, "legacy-without-sql", without_provenance=True),
    )
    selectors = ["--proposal", saved["proposal"], "--revision", no_sql["revision"]]
    assert (
        run_cli(project, "search-examples", "gross margin region", *selectors, "--include-sql") == 0
    )
    hits = json.loads(capsys.readouterr().out)
    assert (
        next(hit for hit in hits if hit["id"] == "legacy-without-sql")["provenance"]["sql"] is None
    )

    malformed_id = "malformed-provenance"
    malformed = proposals.add_answer_example(
        root,
        saved["proposal"],
        no_sql["revision"],
        malformed_id,
        revise_page(valid_page, malformed_id, malformed_source=True),
    )
    selectors[-1] = malformed["revision"]
    assert (
        run_cli(
            project,
            "search-examples",
            "gross margin region",
            *selectors,
            "--include-sql",
        )
        == 1
    )
    assert "unsupported sql_provenance.source" in error_payload(capsys.readouterr().err)["message"]


def test_define_metric_examples_retain_only_the_actual_operation_arguments(project, capsys):
    submission = _submission(
        _SMALL_RESULT,
        method={
            "operation": "define_metric",
            "arguments": {
                "name": "margin_ratio",
                "description": "margin as ratio of sums",
                "source": "demo.main.orders",
                "expression": "SUM(amount)",
                "dimensions": ["region"],
            },
        },
    )
    assert run_cli(project, "save-example", stdin=io.StringIO(json.dumps(submission))) == 0
    saved = json.loads(capsys.readouterr().out)
    page = _candidate_page(project, saved)
    metadata = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert metadata["method"]["operation"] == "define_metric"
    assert metadata["method"]["arguments"]["source"] == "demo.main.orders"

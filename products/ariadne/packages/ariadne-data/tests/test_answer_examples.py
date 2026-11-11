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


def test_exact_sql_provenance_is_git_candidate_only_and_never_executed(tmp_path, capsys):
    """The exact submitted SQL is opt-in historical evidence, not executable input

    spec0035 C4 native journey: one revision-4 integrated release admits the
    retail knowledge (metric + Policies + the answer_examples category); an
    explicit CLI save authors ONE native knowledge/answer_examples page
    through the shared candidate writer; ordinary search stays admitted-only;
    the explicit candidate preview labels the draft; opt-in returns the exact
    submitted SQL verbatim; and no step ever opens the DuckDB source."""
    import json

    import yaml
    from integration.tests.lumio_metric_mvp import (  # pyright: ignore[reportMissingImports] — qualified test env is external
        CONTROL,
        NAMESPACE,
        activate,
        content_project,
        page_parts,
        preview,
        write_page,
    )

    from ariadne import admission
    from ariadne.authoring import AuthoringProject
    from ariadne.cli import main as cli
    from tests.test_git_authoring import approved, run_git, worktree_of

    project = content_project(tmp_path / "project")
    # The revision-4 integrated selector validates the WHOLE candidate under
    # the producer contract: the scaffolded classic context_layer bundle is
    # retired — the same pure-native base the proven revision-2/3 journeys use.
    run_git(project, "rm", "-q", "-r", "--", "context_layer")
    run_git(
        project,
        "commit",
        "-q",
        "-m",
        "human: pure native knowledge baseline",
        "--",
        "context_layer",
    )
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    def record_revision(proposal):
        from ariadne import proposals

        return proposals._load_record(project, proposal)["candidate_revision"]

    # Candidate 1: the revision-4 integrated opt-in (frozen rev-3 query set
    # plus the answer_example profile and the two Example operations) with the
    # authored metric-binding inventory, and the answer_examples KB category.
    tree = worktree_of(project, started["proposal"])
    # The proven candidate edit: the reference page's typed profile cites a
    # catalog resource outside this project's approved registry — strip the
    # profile as a visible Git candidate edit (an ordinary page thereafter),
    # never an input conversion.
    reference = tree / "knowledge/references/order-number.md"
    ref_meta, ref_body = page_parts(reference)
    del ref_meta["ariadne_profile"]
    write_page(reference, ref_meta, ref_body)
    control = tree / "knowledge" / "lumio.yaml"
    control.write_text(
        CONTROL.replace(
            "  - name: metrics\n",
            "  - name: metrics\n  - name: computations\n  - name: answer-examples\n",
        ).replace(
            "    metric: {}\n",
            "    metric: {}\n    computation: {}\n    answer-example: {}\n",
        )
    )
    bindings = {
        "version": 1,
        "bindings": [
            {
                "subject": {"kind": "metric", "identity": "retail_sales::revenue"},
                "policy": {"namespace": NAMESPACE, "entity_id": "entity:retail-return-policy"},
                "operations": ["get_metric"],
                "enforcement": None,
            }
        ],
    }
    (tree / "context_integration.yaml").write_text(
        "version: 1\nmode: integrated\nsubtree: knowledge\n"
        f"namespace: {NAMESPACE}\nprofile: ariadne-context/1\n"
        + yaml.safe_dump({"support_revision": 4, "policy_bindings": bindings}, sort_keys=False)
    )
    previous = record_revision(started["proposal"])
    run_git(tree, "add", "-f", "--", "knowledge")
    run_git(tree, "add", "--", "context_integration.yaml")
    run_git(tree, "commit", "-q", "-m", "human: revision-4 answer-example candidate")
    revision = run_git(tree, "rev-parse", "HEAD").strip()
    admission.reconcile(project, started["proposal"], previous, revision)
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    activate(project, review, preview(project, review, tmp_path / "published"))

    def cli_run(*args, stdin=None):
        return cli([*args, "--project", str(project)], stdin=stdin)

    db_path = project / "data" / "orders.duckdb"
    db_before = db_path.read_bytes()
    result = {**_SMALL_RESULT, "sql": _EXACT_SQL}
    submission = _submission(result)
    submission["sources"] = ["metrics/retail-revenue.md", "policies/retail-return-policy.md"]
    assert cli_run("save-example", stdin=io.StringIO(json.dumps(submission))) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "draft"
    assert saved["path"] == f"knowledge/answer-examples/{saved['id']}.md"

    page = worktree_of(project, saved["proposal"]) / saved["path"]
    front = yaml.safe_load(page.read_text(encoding="utf-8").split("---", 2)[1])
    assert front["ariadne_profile"]["kind"] == "answer_example"
    assert front["entity_types"] == ["answer-example"]
    assert front["id"] == f"entity:{saved['id']}"
    native = front["ariadne_profile"]["native"]
    assert native["sql_provenance"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }
    import hashlib

    assert native["answer"]["result_digest"] == hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # Ordinary search is admitted-only; candidate search is explicit and labeled.
    assert cli_run("search-examples", "gross margin region") == 0
    assert json.loads(capsys.readouterr().out) == []
    selectors = ["--proposal", saved["proposal"], "--revision", saved["candidate_revision"]]
    assert cli_run("search-examples", "gross margin region", *selectors) == 0
    default = json.loads(capsys.readouterr().out)
    assert len(default) == 1 and default[0]["status"] == "draft"
    assert "rows" not in default[0] and "sql" not in default[0]["provenance"]

    assert (
        cli_run(
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
    assert db_path.read_bytes() == db_before
    assert not (project / "staging").exists()

    # Mandatory human admission of the Example candidate — save never auto-publishes.
    validated = api.validate_proposal(saved["proposal"], saved["candidate_revision"])
    assert validated["ok"] is True, validated["errors"]
    example_review = api.review_proposal(saved["proposal"])
    activate(
        project,
        example_review,
        preview(
            project,
            example_review,
            tmp_path / "published",
            review["revision"],
        ),
    )

    assert cli_run("search-examples", "gross margin region") == 0
    admitted = json.loads(capsys.readouterr().out)
    assert len(admitted) == 1 and admitted[0]["status"] == "stable"
    hit = admitted[0]
    # the admitted Example pins the NEW active Bound Release (post-admission manifest)
    manifest = json.loads((project / ".ariadne" / "current.json").read_text())["bound_release"]
    assert hit["entity_id"] == f"entity:{saved['id']}"
    assert hit["published_version"] == example_review["revision"]
    assert hit["bound_release"] == manifest["digest"]
    assert hit["stale"] is False
    assert "sql" not in hit["provenance"]
    assert "rows" not in hit
    assert cli_run("search-examples", "gross margin region", "--include-sql") == 0
    admitted_sql = json.loads(capsys.readouterr().out)
    assert admitted_sql[0]["provenance"]["sql"] == {
        "source": "submitted_result.sql",
        "text": _EXACT_SQL,
    }
    assert db_path.read_bytes() == db_before
    assert not (project / "staging").exists()


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

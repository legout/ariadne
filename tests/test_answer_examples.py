"""Answer-example storage + CLI (issue #19): explicit save -> labeled draft search.

Public-seam tests: every invocation goes through ``ariadne.cli.main(argv, stdin)``
(the exact target of the ``ariadne`` console script) and asserts the §4 JSON
contract, reusing the golden served fixture from tests/test_cli.py. Scope is
spec 2026-09-29-0006 acceptance 1 and 6 (ADR-0014): an explicit save stages a
bounded OKF draft only under ``staging/answer_examples/``, same-checkout search
finds it immediately as a labeled unapproved record, and governed context is
unchanged. A draft is a labeled reference, never a governed definition or a
cached answer.
"""

import hashlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.cli import main as cli  # noqa: E402
from tests.test_cli import error_payload  # noqa: E402
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
    the golden fixtures (same construction as tests/test_cli.py — the runtime's
    compile/grain gates are the validator)."""
    tmp = tmp_path_factory.mktemp("examples")
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


def _submission(result, **overrides):
    submission = {
        "question": "What is the gross margin ratio by region?",
        "interpretation": (
            "Margin as ratio of sums over billable orders, with the EMEA currency "
            "cutover applied before aggregating"
        ),
        "parameters": {
            "range": {"start": "2024-01-01", "end": "2026-12-31"},
            "dimensions": ["region"],
            "grain": "one row per region",
        },
        "method": {
            "operation": "get_metric",
            "arguments": {"name": "gross_margin", "dimensions": ["region"]},
        },
        "result": result,
        "submitter": "expert:dana",
        "attestation": "The saved interpretation states the business meaning I intended.",
        "sources": ["context_layer/metrics/gross_margin.md"],
    }
    submission.update(overrides)
    return submission


_SMALL_RESULT = {
    "metric": "order_count",
    "columns": ["region", "order_count"],
    "rows": [{"region": "EMEA", "order_count": 1}],
    "sql": "SELECT region, COUNT(*) FROM orders",
    "governed": True,
}


def test_explicit_save_creates_labeled_draft_found_by_search_without_context_change(
    served, tmp_path, capsys
):
    staging = tmp_path / "staging"

    # The governed answer the submitter just examined, and the governed context
    # contract BEFORE any save (what must not change).
    assert run_cli(served, staging, "get-metric", "gross_margin", "--dimension", "region") == 0
    examined = json.loads(capsys.readouterr().out)
    context_before = examined["context"]

    assert run_cli(
        served, staging, "save-example", stdin=io.StringIO(json.dumps(_submission(examined)))
    ) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "draft"
    draft = Path(saved["path"])
    assert draft.is_file() and draft.parent == staging / "answer_examples"
    first_bytes = draft.read_bytes()
    assert not (served[0] / "answer_examples").exists()  # drafts never reach the served root

    # Same-checkout search finds the labeled draft immediately; hits carry
    # identity and provenance, never saved rows/SQL (no cached answer).
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits and hits[0]["id"] == saved["id"]
    assert hits[0]["status"] == "draft" and hits[0]["stale"] is False
    assert hits[0]["question"] == "What is the gross margin ratio by region?"
    assert hits[0]["method"]["operation"] == "get_metric"
    assert hits[0]["provenance"]["submitter"] == "expert:dana"
    assert "rows" not in hits[0] and "sql" not in hits[0]

    # A repeated deliberate save is a distinct draft — never an overwrite.
    assert run_cli(
        served, staging, "save-example", stdin=io.StringIO(json.dumps(_submission(examined)))
    ) == 0
    again = json.loads(capsys.readouterr().out)
    assert again["id"] != saved["id"] and again["path"] != saved["path"]
    assert draft.read_bytes() == first_bytes  # the first record is untouched

    # A reviewed stable record (what operator review in #20 produces) ranks
    # above the draft for the same words; a stale one stays history-only.
    page = served[0] / "context_layer" / "metrics" / "gross_margin.md"
    digest = hashlib.sha256(page.read_bytes()).hexdigest()
    stable_root = served[0] / "answer_examples"
    stable_root.mkdir()
    (stable_root / "stable-margin.md").write_text(
        "---\n"
        "type: answer_example\n"
        "status: stable\n"
        "generated: 2026-09-29T00:00:00+00:00\n"
        "question: gross margin by region benchmark\n"
        "interpretation: reviewed margin ratio of sums benchmark\n"
        "method:\n  operation: get_metric\n"
        "  arguments: {name: gross_margin, dimensions: [region]}\n"
        "submitter:\n  identity: expert:reviewer\n  attestation: reviewed meaning\n"
        "sources:\n  - path: context_layer/metrics/gross_margin.md\n"
        f"    sha256: {digest}\n"
        "---\n\n# gross margin by region benchmark\n",
        encoding="utf-8",
    )
    (stable_root / "stale-margin.md").write_text(
        "---\n"
        "type: answer_example\n"
        "status: stable\n"
        "generated: 2026-09-28T00:00:00+00:00\n"
        "question: stale gross margin region wording\n"
        "interpretation: outdated benchmark\n"
        "sources:\n  - path: context_layer/metrics/gross_margin.md\n"
        "    sha256: deadbeef\n"
        "---\n\n# stale gross margin region wording\n",
        encoding="utf-8",
    )
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["id"] == "stable-margin"  # approved non-stale ranks above drafts
    assert hits[0]["status"] == "stable" and hits[0]["stale"] is False
    assert {hit["id"] for hit in hits} == {"stable-margin", saved["id"], again["id"]}
    assert run_cli(served, staging, "search-examples", "stale gross margin", "--limit", "5") == 0
    assert all(hit["id"] != "stale-margin" for hit in json.loads(capsys.readouterr().out))
    assert run_cli(
        served,
        staging,
        "search-examples",
        "stale gross margin",
        "--limit",
        "5",
        "--include-history",
    ) == 0
    history = json.loads(capsys.readouterr().out)
    stale_hits = [hit for hit in history if hit["id"] == "stale-margin"]
    assert stale_hits and stale_hits[0]["stale"] is True  # labeled history

    # Non-matching input returns [].
    assert run_cli(served, staging, "search-examples", "zanzibar") == 0
    assert json.loads(capsys.readouterr().out) == []

    # Governed context is unchanged by any of it: get_metric.context identical,
    # and search-context surfaces no example (it is not Context Layer content).
    assert run_cli(served, staging, "get-metric", "gross_margin", "--dimension", "region") == 0
    assert json.loads(capsys.readouterr().out)["context"] == context_before
    assert run_cli(served, staging, "search-context", "gross margin", "--limit", "20") == 0
    assert all(hit["draft"] is False for hit in json.loads(capsys.readouterr().out))


def test_oversize_answer_rejected_writes_nothing(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    result = {
        "metric": "order_count",
        "columns": ["blob"],
        "rows": [{"blob": "x" * 9000}],
        "sql": "SELECT 1",
        "governed": False,
    }
    code = run_cli(
        served, staging, "save-example", stdin=io.StringIO(json.dumps(_submission(result)))
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no success value on stdout
    error = error_payload(captured.err)
    assert "8192" in error["message"]  # the bound is named, not silently truncated
    assert not staging.exists() or not any(staging.rglob("*"))  # nothing staged


def test_citation_path_escape_rejected_writes_nothing(served, tmp_path, capsys):
    staging = tmp_path / "staging"
    for escape in ("../../../../etc/passwd", "/etc/hosts"):
        submission = _submission(_SMALL_RESULT, sources=[escape])
        code = run_cli(served, staging, "save-example", stdin=io.StringIO(json.dumps(submission)))
        assert code == 1
        error = error_payload(capsys.readouterr().err)
        assert "escapes the selected served root" in error["message"]
    assert not staging.exists() or not any(staging.rglob("*"))  # nothing staged


def test_staged_page_claiming_stable_is_always_draft(served, tmp_path, capsys):
    """ADR-0014: review authority derives from location — a locally writable
    staged page may not present itself as reviewed (boundary finding 1)."""
    root, _db = served
    staging = tmp_path / "staging"
    staged_dir = staging / "answer_examples"
    staged_dir.mkdir(parents=True)
    (staged_dir / "masquerade.md").write_text(
        "---\n"
        "type: answer_example\n"
        "status: stable\n"
        "generated: 2026-09-29T00:00:00+00:00\n"
        "question: gross margin region masquerade\n"
        "interpretation: claims reviewed authority it does not have\n"
        "method:\n  operation: get_metric\n  arguments: {name: gross_margin}\n"
        "submitter:\n  identity: expert:local-writer\n  attestation: self-declared\n"
        "---\n\n# gross margin region masquerade\n",
        encoding="utf-8",
    )
    # A real served reviewed record for the same words exists and must outrank it.
    stable_root = root / "answer_examples"
    stable_root.mkdir(exist_ok=True)
    digest = hashlib.sha256(
        (root / "context_layer" / "metrics" / "gross_margin.md").read_bytes()
    ).hexdigest()
    (stable_root / "stable-authcheck.md").write_text(
        "---\n"
        "type: answer_example\n"
        "status: stable\n"
        "generated: 2026-09-29T00:00:00+00:00\n"
        "question: gross margin region authority check\n"
        "interpretation: reviewed margin ratio benchmark\n"
        "method:\n  operation: get_metric\n  arguments: {name: gross_margin}\n"
        "submitter:\n  identity: expert:reviewer\n  attestation: reviewed meaning\n"
        "sources:\n  - path: context_layer/metrics/gross_margin.md\n"
        f"    sha256: {digest}\n"
        "---\n\n# gross margin region authority check\n",
        encoding="utf-8",
    )
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    hits = json.loads(capsys.readouterr().out)
    by_id = {hit["id"]: hit for hit in hits}
    assert by_id["masquerade"]["status"] == "draft"  # staged is always draft
    assert hits[0]["id"] == "stable-authcheck"  # only served may rank as approved

    # Saving another draft regenerates the staged index — the untrusted staged
    # status must never reach it as a stable label.
    assert (
        run_cli(
            served,
            staging,
            "save-example",
            stdin=io.StringIO(json.dumps(_submission(_SMALL_RESULT))),
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "draft"
    index = (staging / "answer_examples" / "index.md").read_text(encoding="utf-8")
    assert "stable" not in index  # no masqueraded review state in generated bookkeeping
    assert "— draft" in index


def test_staging_symlink_into_served_rejected_writes_nothing(served, tmp_path, capsys):
    """ADR-0014/acceptance 6: saves stage under staging only — a symlinked
    staging example directory (or bundle bookkeeping file) may not write into
    served (boundary finding 2)."""
    root, _db = served
    served_examples = root / "answer_examples"
    served_examples.mkdir(exist_ok=True)
    sentinel = served_examples / "sentinel.md"
    sentinel.write_bytes(b"reviewed bytes\n")
    before = {p.name: p.read_bytes() for p in served_examples.iterdir()}

    staging = tmp_path / "staging"
    staging.mkdir()
    os.symlink(served_examples, staging / "answer_examples")
    code = run_cli(
        served, staging, "save-example", stdin=io.StringIO(json.dumps(_submission(_SMALL_RESULT)))
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no false success status
    assert "staging" in error_payload(captured.err)["message"]
    assert {p.name: p.read_bytes() for p in served_examples.iterdir()} == before

    # The same boundary on the per-file paths the save actually writes: a
    # symlinked index.md must fail before anything is staged.
    staging2 = tmp_path / "staging2"
    real_dir = staging2 / "answer_examples"
    real_dir.mkdir(parents=True)
    target = tmp_path / "served-index.md"
    target.write_bytes(b"reviewed index\n")
    os.symlink(target, real_dir / "index.md")
    code = run_cli(
        served, staging2, "save-example", stdin=io.StringIO(json.dumps(_submission(_SMALL_RESULT)))
    )
    assert code == 1
    assert error_payload(capsys.readouterr().err)["message"]
    assert target.read_bytes() == b"reviewed index\n"
    assert [p.name for p in real_dir.iterdir()] == ["index.md"]  # no draft page written


def test_non_metric_citation_and_malformed_sources_rejected_writes_nothing(
    served, tmp_path, capsys
):
    """Spec rev 1: citations are existing served metric/Policy pages only, and
    a supplied malformed 'sources' is rejected rather than defaulted (finding 3)."""
    staging = tmp_path / "staging"
    # A realistic served file that is not a metric/Policy page: the OSI model.
    for bad_sources in (["semantic_layer/models/orders.yml"], False, {}):
        submission = _submission(_SMALL_RESULT, sources=bad_sources)
        code = run_cli(served, staging, "save-example", stdin=io.StringIO(json.dumps(submission)))
        assert code == 1
        error = error_payload(capsys.readouterr().err)
        assert (
            "metric or Policy page" in error["message"] or "'sources' must be" in error["message"]
        )
    assert not staging.exists() or not any(staging.rglob("*"))  # nothing staged


def test_sql_only_method_rejected_real_arguments_accepted(served, tmp_path, capsys):
    """Spec rev 1: the recorded method is a rerunnable operation with its real
    runtime arguments — SQL alone is not a get_metric argument (finding 4)."""
    staging = tmp_path / "staging"
    sql_only = _submission(
        _SMALL_RESULT, method={"operation": "get_metric", "arguments": {"sql": "SELECT 1"}}
    )
    code = run_cli(served, staging, "save-example", stdin=io.StringIO(json.dumps(sql_only)))
    assert code == 1
    assert "name" in error_payload(capsys.readouterr().err)["message"]
    assert not staging.exists() or not any(staging.rglob("*"))  # refused before any write

    # define_metric keeps working with the runtime's real definition shape
    # (name/description/source/expression, optional dimensions/time_field).
    defined = _submission(
        _SMALL_RESULT,
        method={
            "operation": "define_metric",
            "arguments": {
                "name": "margin_ratio",
                "description": "margin as ratio of sums",
                "source": "orders",
                "expression": "SUM(margin) / SUM(amount)",
                "dimensions": ["region"],
            },
        },
    )
    assert run_cli(served, staging, "save-example", stdin=io.StringIO(json.dumps(defined))) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["status"] == "draft"
    assert Path(saved["path"]).parent == staging / "answer_examples"

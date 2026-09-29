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
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne.cli import main as cli  # noqa: E402
from ariadne.example_review import (  # noqa: E402  # pyright: ignore[reportMissingImports] — new-module resolver drift
    main as review_cli,
)
from ariadne.promote import _plan  # noqa: E402
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


def test_staging_symlink_into_staged_context_layer_rejected_writes_nothing(
    served, tmp_path, capsys
):
    """ADR-0014/ADR-0003: examples are a separate staged store — a symlinked
    example directory may not redirect a save into staged Context Layer pages
    that human batch promotion would then mark stable (delta finding)."""
    root, _db = served
    staging = tmp_path / "staging"
    metrics = staging / "context_layer" / "metrics"
    metrics.mkdir(parents=True)
    os.symlink(metrics, staging / "answer_examples")

    code = run_cli(
        served, staging, "save-example", stdin=io.StringIO(json.dumps(_submission(_SMALL_RESULT)))
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # no false success status
    assert "symlink" in error_payload(captured.err)["message"]

    # The staged Context Layer store is untouched: no example page/index/log,
    # and the promotion gate receives no example page to batch-promote.
    assert [p.name for p in metrics.iterdir()] == []
    assert _plan(staging, root) == ([], [])


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


# ------------- issue #20: operator review, staleness, promotion isolation -------------


def run_review(served, staging, example_id, decision, tmp_path):
    """Invoke the operator-only console entry with the exact argv a human runs."""
    decision_file = tmp_path / "decision.json"
    decision_file.write_text(json.dumps(decision), encoding="utf-8")
    root, _db = served
    return review_cli(
        [example_id, "--file", str(decision_file), "--served", str(root), "--staging", str(staging)]
    )


def review_error(capsys):
    """The same one-JSON-error-object contract as the ariadne CLI."""
    captured = capsys.readouterr()
    assert captured.out == ""
    return error_payload(captured.err)


def test_maintainer_review_admits_exact_draft_then_policy_change_suspends_reuse(
    served, tmp_path, capsys
):
    """AC3/AC4 red seam: submitter attestation + maintainer technical review
    admits ONE exact staged ID to the served example store as stable (no metric
    promotion); changing the cited served Policy then removes it from ordinary
    method reuse while --include-history keeps it labeled and byte-preserved."""
    root, db = served
    staging = tmp_path / "staging"

    assert run_cli(served, staging, "list-metrics") == 0
    metrics_before = json.loads(capsys.readouterr().out)
    assert run_cli(served, staging, "get-metric", "gross_margin", "--dimension", "region") == 0
    examined = json.loads(capsys.readouterr().out)
    policy = root / "context_layer" / "policies" / "order-status-billing.md"
    policy_bytes = policy.read_bytes()

    assert run_cli(
        served,
        staging,
        "save-example",
        stdin=io.StringIO(
            json.dumps(
                _submission(
                    examined,
                    sources=[
                        "context_layer/metrics/gross_margin.md",
                        "context_layer/policies/order-status-billing.md",
                    ],
                )
            )
        ),
    ) == 0
    saved = json.loads(capsys.readouterr().out)
    staged = Path(saved["path"])
    decision = {
        "id": saved["id"],
        "actor": "maintainer:reviewer",
        "outcome": "approve",
        "technical_review": (
            "Method is the served gross_margin metric grouped by region; the cited "
            "metric and billing Policy match the current served pages."
        ),
        "staged_digest": hashlib.sha256(staged.read_bytes()).hexdigest(),
    }
    assert run_review(served, staging, saved["id"], decision, tmp_path) == 0
    approved = json.loads(capsys.readouterr().out)
    assert approved["outcome"] == "approve" and approved["status"] == "stable"

    served_page = root / "answer_examples" / f"{saved['id']}.md"
    meta = yaml.safe_load(served_page.read_text(encoding="utf-8").split("---")[1])
    assert meta["status"] == "stable"
    assert meta["review"]["actor"] == "maintainer:reviewer"
    assert meta["review"]["outcome"] == "approve"
    assert meta["review"]["technical_review"] == decision["technical_review"]
    assert meta["review"]["at"]  # review time retained
    assert meta["submitter"]["attestation"]  # submitter meaning retained
    assert not staged.exists()  # the review moved the exact staged record

    # Ordinary search now serves the reviewed record as stable with its review
    # provenance; no metric was promoted. (Earlier #19 tests leave reviewed
    # records in the module-scoped served root, so locate this exact ID.)
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    hits = json.loads(capsys.readouterr().out)
    mine = next(hit for hit in hits if hit["id"] == saved["id"])
    assert mine["status"] == "stable" and mine["stale"] is False
    assert mine["provenance"]["review"]["actor"] == "maintainer:reviewer"
    assert all(
        hit["status"] == "stable" for hit in hits[: hits.index(mine) + 1]
    )  # approved ranks ahead of drafts
    assert run_cli(served, staging, "list-metrics") == 0
    assert json.loads(capsys.readouterr().out) == metrics_before

    # The cited Policy changes: normal reuse is suspended without rewriting
    # history; labeled history preserves the exact record.
    policy.write_bytes(policy_bytes + b"\nAmended 2026-09-29: returned orders restock.\n")
    approved_bytes = served_page.read_bytes()
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    assert all(hit["id"] != saved["id"] for hit in json.loads(capsys.readouterr().out))
    assert run_cli(
        served, staging, "search-examples", "gross margin region", "--include-history"
    ) == 0
    history = [hit for hit in json.loads(capsys.readouterr().out) if hit["id"] == saved["id"]]
    assert history and history[0]["stale"] is True and history[0]["status"] == "stable"
    assert served_page.read_bytes() == approved_bytes  # historical file untouched


def _save_draft(served, staging, capsys, **overrides) -> dict:
    """One staged draft through the public save-example seam."""
    submission = _submission(_SMALL_RESULT, **overrides)
    assert run_cli(
        served, staging, "save-example", stdin=io.StringIO(json.dumps(submission))
    ) == 0
    return json.loads(capsys.readouterr().out)


def _decision(saved: dict, staged: Path, **overrides) -> dict:
    decision = {
        "id": saved["id"],
        "actor": "maintainer:reviewer",
        "outcome": "approve",
        "technical_review": "Method and cited served pages match the current definitions.",
        "staged_digest": hashlib.sha256(staged.read_bytes()).hexdigest(),
    }
    decision.update(overrides)
    return decision


def _served_examples(root: Path) -> list[str]:
    """The served example store's current records (module-scoped fixture:
    refusals must not add to it)."""
    directory = root / "answer_examples"
    return sorted(p.name for p in directory.glob("*.md")) if directory.is_dir() else []


def test_review_refuses_malformed_missing_and_escaped_ids(served, tmp_path, capsys):
    """Fail closed on an unreachable ID before anything is read or written."""
    root, _db = served
    staging = tmp_path / "staging"
    saved = _save_draft(
        served, staging, capsys, question="Gross margin by region in the malformed ID case?"
    )
    staged = Path(saved["path"])
    before = staged.read_bytes()
    served_before = _served_examples(root)
    for bad in ("../escape", "no-such-id", "a/b", ".hidden", "index", ""):
        assert run_review(served, staging, bad, _decision(saved, staged), tmp_path) == 1
        error = review_error(capsys)
        assert error["type"] == "ValueError"
        assert "ID" in error["message"] or "no staged" in error["message"]
    assert staged.read_bytes() == before
    assert _served_examples(root) == served_before


def test_review_refuses_staged_content_changed_after_the_decision(served, tmp_path, capsys):
    """The decision binds the exact staged bytes: an edited draft is not the
    reviewed record and nothing is served."""
    root, _db = served
    staging = tmp_path / "staging"
    saved = _save_draft(
        served, staging, capsys, question="Gross margin by region with altered staged bytes?"
    )
    staged = Path(saved["path"])
    decision = _decision(saved, staged)
    staged.write_bytes(staged.read_bytes() + b"sneaked line\n")

    assert run_review(served, staging, saved["id"], decision, tmp_path) == 1
    error = review_error(capsys)
    assert "changed after the decision" in error["message"]
    assert "sneaked line" in staged.read_text(encoding="utf-8")  # staged bytes kept
    assert not (root / "answer_examples" / f"{saved['id']}.md").exists()  # nothing served
    # The edited draft is still an ordinary draft (no review block written).
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    hit = next(h for h in json.loads(capsys.readouterr().out) if h["id"] == saved["id"])
    assert hit["status"] == "draft" and hit["provenance"]["review"] is None


def test_review_refuses_conflicting_reviewed_targets(served, tmp_path, capsys):
    root, _db = served
    staging = tmp_path / "staging"
    saved = _save_draft(
        served, staging, capsys, question="Gross margin by region with conflicting targets?"
    )
    decision = _decision(saved, Path(saved["path"]), id="a-different-record")

    assert run_review(served, staging, saved["id"], decision, tmp_path) == 1
    assert "conflicting reviewed targets" in review_error(capsys)["message"]
    assert Path(saved["path"]).exists()  # the exact staged record is untouched
    assert not (root / "answer_examples" / f"{saved['id']}.md").exists()


def test_review_refuses_incomplete_evidence_and_overstated_claims(served, tmp_path, capsys):
    root, _db = served
    staging = tmp_path / "staging"
    saved = _save_draft(
        served, staging, capsys, question="Gross margin by region with incomplete evidence?"
    )
    staged = Path(saved["path"])
    served_before = _served_examples(root)

    for drop in ("actor", "technical_review"):
        decision = dict(_decision(saved, staged))
        del decision[drop]
        assert run_review(served, staging, saved["id"], decision, tmp_path) == 1
        assert "incomplete reviewer evidence" in review_error(capsys)["message"]

    decision = _decision(saved, staged, historical_value_verified=True)
    assert run_review(served, staging, saved["id"], decision, tmp_path) == 1
    assert "historical numeric value" in review_error(capsys)["message"]

    # A staged record without the submitter's attestation cannot be approved:
    # the maintainer's technical review never substitutes for the submitter's
    # business-meaning claim.
    unattested = staging / "answer_examples" / "unattested.md"
    unattested.parent.mkdir(parents=True, exist_ok=True)
    unattested.write_text(
        "---\n"
        "type: answer_example\n"
        "status: draft\n"
        "generated: 2026-09-29T00:00:00+00:00\n"
        "question: gross margin region without attestation\n"
        "interpretation: meaning never attested by a submitter\n"
        "method:\n  operation: get_metric\n  arguments: {name: gross_margin}\n"
        "submitter:\n  identity: expert:dana\n"
        "---\n\n# gross margin region without attestation\n",
        encoding="utf-8",
    )
    decision = {
        "id": "unattested",
        "actor": "maintainer:reviewer",
        "outcome": "approve",
        "technical_review": "Method checks out.",
        "staged_digest": hashlib.sha256(unattested.read_bytes()).hexdigest(),
    }
    assert run_review(served, staging, "unattested", decision, tmp_path) == 1
    assert "attestation" in review_error(capsys)["message"]
    assert _served_examples(root) == served_before  # every refusal wrote nothing


def test_reject_and_request_revision_keep_labeled_audit_history(served, tmp_path, capsys):
    """A closed record stays staged history: hidden from ordinary reuse,
    labeled through --include-history, and never approvable afterwards."""
    root, _db = served
    staging = tmp_path / "staging"
    saved = _save_draft(
        served,
        staging,
        capsys,
        question="Gross margin by region rejected by the maintainer?",
    )
    staged = Path(saved["path"])
    served_before = _served_examples(root)
    decision = _decision(
        saved,
        staged,
        outcome="reject",
        technical_review="The cited filter no longer matches the billing Policy.",
    )

    assert run_review(served, staging, saved["id"], decision, tmp_path) == 0
    rejected = json.loads(capsys.readouterr().out)
    assert rejected == {
        "id": saved["id"],
        "outcome": "reject",
        "status": "rejected",
        "path": str(staged),
    }
    meta = yaml.safe_load(staged.read_text(encoding="utf-8").split("---")[1])
    assert meta["review"]["outcome"] == "reject"
    assert meta["submitter"]["attestation"]  # history preserved, content kept
    assert _served_examples(root) == served_before  # rejection serves nothing

    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    assert all(hit["id"] != saved["id"] for hit in json.loads(capsys.readouterr().out))
    assert run_cli(
        served, staging, "search-examples", "gross margin region", "--include-history"
    ) == 0
    history = next(
        hit for hit in json.loads(capsys.readouterr().out) if hit["id"] == saved["id"]
    )
    assert history["status"] == "reject" and history["stale"] is False  # labeled, not stale
    staged_index = (staging / "answer_examples" / "index.md").read_text(encoding="utf-8")
    assert f"({saved['id']}.md) — reject (history)" in staged_index
    assert "stable" not in staged_index  # staged bookkeeping still never claims stable

    # The closed record cannot be approved afterwards: a revision is a new
    # submission and a new review.
    again = _decision(saved, staged, outcome="approve")
    assert run_review(served, staging, saved["id"], again, tmp_path) == 1
    assert "already carries a review outcome" in review_error(capsys)["message"]

    # request-revision labels the same way.
    other = _save_draft(served, staging, capsys, question="Gross margin by region revised?")
    other_staged = Path(other["path"])
    revision = _decision(other, other_staged, outcome="request-revision")
    assert run_review(served, staging, other["id"], revision, tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "revision_requested"
    assert run_cli(
        served, staging, "search-examples", "gross margin region", "--include-history"
    ) == 0
    labeled = next(
        hit for hit in json.loads(capsys.readouterr().out) if hit["id"] == other["id"]
    )
    assert labeled["status"] == "request-revision"


def test_fresh_revision_restores_reuse_and_preserves_the_old_record(served, tmp_path, capsys):
    """AC4: after the dependency change, a NEW reviewed revision (distinct
    record, linked through supersedes) restores normal reuse while the old
    record stays byte-preserved history with its original (never flipped)
    dependency digest."""
    root, _db = served
    staging = tmp_path / "staging"
    policy = root / "context_layer" / "policies" / "order-status-billing.md"
    policy_bytes = policy.read_bytes()
    sources = [
        "context_layer/metrics/gross_margin.md",
        "context_layer/policies/order-status-billing.md",
    ]

    first = _save_draft(
        served,
        staging,
        capsys,
        sources=sources,
        question="Gross margin ratio by region for the quarterly review?",
    )
    first_decision = _decision(first, Path(first["path"]))
    assert run_review(served, staging, first["id"], first_decision, tmp_path) == 0
    capsys.readouterr()
    old_page = root / "answer_examples" / f"{first['id']}.md"
    old_meta = yaml.safe_load(old_page.read_text(encoding="utf-8").split("---")[1])
    old_digest = old_meta["sources"][1]["sha256"]

    policy.write_bytes(policy_bytes + b"\nAmended 2026-09-29: returned orders restock.\n")
    second = _save_draft(
        served,
        staging,
        capsys,
        sources=sources,
        question="Gross margin ratio by region for the amended policy?",
    )  # captures the new digest
    decision = _decision(second, Path(second["path"]), supersedes=first["id"])
    assert run_review(served, staging, second["id"], decision, tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "stable"

    # Normal reuse is restored by the fresh reviewed revision.
    assert run_cli(served, staging, "search-examples", "gross margin region") == 0
    hits = json.loads(capsys.readouterr().out)
    fresh = next(hit for hit in hits if hit["id"] == second["id"])
    assert fresh["status"] == "stable" and fresh["stale"] is False
    assert all(hit["id"] != first["id"] for hit in hits)  # the old one no longer guides

    # The superseded record is preserved history: its own question, answer and
    # dependency digest survive verbatim — the old digest was never flipped.
    assert old_page.exists()
    superseded_meta = yaml.safe_load(old_page.read_text(encoding="utf-8").split("---")[1])
    assert superseded_meta["status"] == "superseded"
    assert superseded_meta["superseded_by"] == second["id"]
    assert superseded_meta["question"] == old_meta["question"]
    assert superseded_meta["sources"][1]["sha256"] == old_digest
    assert run_cli(
        served, staging, "search-examples", "gross margin region", "--include-history"
    ) == 0
    old_hit = next(
        hit for hit in json.loads(capsys.readouterr().out) if hit["id"] == first["id"]
    )
    assert old_hit["status"] == "superseded" and old_hit["stale"] is True

    # A supersedes reference to nothing fails closed.
    third = _save_draft(
        served, staging, capsys, sources=sources, question="Gross margin ratio by region once more?"
    )
    bad = _decision(third, Path(third["path"]), supersedes="ghost-record")
    assert run_review(served, staging, third["id"], bad, tmp_path) == 1
    assert "no served example" in review_error(capsys)["message"]


def test_review_invalid_supersedes_predecessor_fails_before_any_served_write(
    served, tmp_path, capsys
):
    """Boundary review finding 1: an invalid (non-OKF) predecessor frontmatter
    fails closed BEFORE the first served write — no new stable record, staged
    and served bytes exactly as they were."""
    root, _db = served
    staging = tmp_path / "staging"
    first = _save_draft(
        served, staging, capsys, question="Gross margin by region predating a corrupt record?"
    )
    assert (
        run_review(served, staging, first["id"], _decision(first, Path(first["path"])), tmp_path)
        == 0
    )
    capsys.readouterr()
    old_page = root / "answer_examples" / f"{first['id']}.md"
    old_page.write_text("not an okf page anymore\n", encoding="utf-8")  # corrupt predecessor
    served_before = {p.name: p.read_bytes() for p in (root / "answer_examples").iterdir()}

    second = _save_draft(
        served, staging, capsys, question="Gross margin by region after the corrupt record?"
    )
    staged = Path(second["path"])
    staged_before = staged.read_bytes()
    decision = _decision(second, staged, supersedes=first["id"])
    assert run_review(served, staging, second["id"], decision, tmp_path) == 1
    assert "frontmatter" in review_error(capsys)["message"]
    assert staged.read_bytes() == staged_before  # the staged record is untouched
    assert (
        {p.name: p.read_bytes() for p in (root / "answer_examples").iterdir()} == served_before
    )  # no new stable record despite the refused approval


def test_review_reject_through_staging_symlink_into_served_fails_closed(tmp_path, capsys):
    """Boundary review finding 2: the review command enforces the same
    stage-vs-served boundary as save — a symlinked staging example directory
    must stop reject/request-revision before it writes audit history, index or
    log into the served store."""
    served_root = tmp_path / "isolated-served"
    (served_root / "semantic_layer" / "models").mkdir(parents=True)
    (served_root / "context_layer" / "metrics").mkdir(parents=True)
    served_examples = served_root / "answer_examples"
    served_examples.mkdir()
    (served_examples / "sentinel-stable.md").write_text(
        "---\ntype: answer_example\nstatus: stable\n---\n\n# sentinel\n", encoding="utf-8"
    )
    (served_examples / "index.md").write_text("# Answer Examples\n", encoding="utf-8")
    (served_examples / "log.md").write_text("# Directory Update Log\n", encoding="utf-8")
    # A staged draft a symlinked staging root would expose to the operator
    # command as if it lived under staging.
    draft = served_examples / "draft-via-symlink.md"
    draft.write_text(
        "---\n"
        "type: answer_example\n"
        "status: draft\n"
        "question: gross margin region through a symlinked staging root\n"
        "interpretation: misconfigured staging boundary\n"
        "submitter:\n  identity: expert:dana\n  attestation: reviewed meaning\n"
        "---\n\n# gross margin region through a symlinked staging root\n",
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    os.symlink(served_examples, staging / "answer_examples")
    served_before = {p.name: p.read_bytes() for p in served_examples.iterdir()}

    decision = {
        "id": draft.stem,
        "actor": "maintainer:reviewer",
        "outcome": "reject",
        "technical_review": "Rejected regardless of where the staged root points.",
        "staged_digest": hashlib.sha256(draft.read_bytes()).hexdigest(),
    }
    decision_file = tmp_path / "decision.json"
    decision_file.write_text(json.dumps(decision), encoding="utf-8")
    assert (
        review_cli(
            [
                draft.stem,
                "--file",
                str(decision_file),
                "--served",
                str(served_root),
                "--staging",
                str(staging),
            ]
        )
        == 1
    )
    assert "symlink" in review_error(capsys)["message"]
    assert {p.name: p.read_bytes() for p in served_examples.iterdir()} == served_before
    # page, index and log all untouched — rejection reported failure and wrote nothing


def test_review_approve_of_tampered_shapeless_record_fails_closed(served, tmp_path, capsys):
    """Boundary review finding 3: an agent-edited staged page that keeps the
    type and submitter attestation but drops the structured method and answer
    evidence and tears out the dependency list (sources: false) cannot be
    approved even when the decision digest matches the tampered bytes."""
    root, _db = served
    staging = tmp_path / "staging"
    saved = _save_draft(
        served, staging, capsys, question="Gross margin by region in a tampered record?"
    )
    staged = Path(saved["path"])
    # The agent-writable edit: same page, same attestation, no structured
    # method, no bounded answer evidence, dependency list replaced by a bare
    # false.
    parts = staged.read_text(encoding="utf-8").split("---")
    meta = yaml.safe_load(parts[1])
    del meta["method"]
    meta["sources"] = False
    stripped = re.sub(
        r"Captured answer excerpt .*?````json\n.*?\n````",
        "Answer evidence removed.",
        parts[2],
        flags=re.DOTALL,
    )
    staged.write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---{stripped}",
        encoding="utf-8",
    )
    tampered = staged.read_bytes()
    served_before = _served_examples(root)

    decision = _decision(saved, staged)  # digest of the tampered bytes — it matches
    assert run_review(served, staging, saved["id"], decision, tmp_path) == 1
    error = review_error(capsys)
    assert "arguments" in error["message"] or "method" in error["message"]
    assert staged.read_bytes() == tampered  # the staged bytes are kept as edited
    assert _served_examples(root) == served_before  # nothing was served


def test_review_approve_of_citation_resolving_to_served_example_fails_closed(
    served, tmp_path, capsys
):
    """Delta recheck finding 3 (resolved citations): a staged record's
    citations are validated by their RESOLVED location, not their lexical
    prefix — a locally edited source pointing through ``..`` at a served
    answer-example page, carrying that page's correct digest, must fail
    approval even when the decision digest matches the tampered bytes."""
    root, _db = served
    staging = tmp_path / "staging"
    old = _save_draft(
        served, staging, capsys, question="Gross margin by region predating the edited source?"
    )
    assert (
        run_review(served, staging, old["id"], _decision(old, Path(old["path"])), tmp_path) == 0
    )
    capsys.readouterr()
    served_page = root / "answer_examples" / f"{old['id']}.md"
    served_before = {p.name: p.read_bytes() for p in (root / "answer_examples").iterdir()}

    saved = _save_draft(
        served, staging, capsys, question="Gross margin by region through an edited citation?"
    )
    staged = Path(saved["path"])
    # The agent-writable edit: the recorded source keeps its metric-looking
    # lexical prefix but resolves to the served example page above, with that
    # page's correct sha256 — both the old prefix check and _is_stale pass it.
    meta = yaml.safe_load(staged.read_text(encoding="utf-8").split("---", 2)[1])
    meta["sources"] = [
        {
            "path": f"context_layer/metrics/../../answer_examples/{old['id']}.md",
            "sha256": hashlib.sha256(served_page.read_bytes()).hexdigest(),
        }
    ]
    body = staged.read_text(encoding="utf-8").split("---", 2)[2]
    staged.write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)}---{body}",
        encoding="utf-8",
    )
    tampered = staged.read_bytes()

    decision = _decision(saved, staged)  # digest of the edited bytes — it matches
    assert run_review(served, staging, saved["id"], decision, tmp_path) == 1
    assert "metric or Policy" in review_error(capsys)["message"]
    assert staged.read_bytes() == tampered  # the staged bytes are kept as edited
    assert (
        {p.name: p.read_bytes() for p in (root / "answer_examples").iterdir()} == served_before
    )  # no new stable record: an example page was never cited as metric evidence


def test_review_second_supersede_of_superseded_predecessor_fails_unchanged(
    served, tmp_path, capsys
):
    """Boundary review finding 4: once a predecessor is superseded, a second
    approval naming it must fail before any write — the first lineage survives
    and every served/staged record is unchanged."""
    root, _db = served
    staging = tmp_path / "staging"
    anchor = _save_draft(
        served, staging, capsys, question="Gross margin by region anchoring the lineage?"
    )
    assert (
        run_review(served, staging, anchor["id"], _decision(anchor, Path(anchor["path"])), tmp_path)
        == 0
    )
    capsys.readouterr()
    first_revision = _save_draft(
        served, staging, capsys, question="Gross margin by region first revision?"
    )
    assert (
        run_review(
            served,
            staging,
            first_revision["id"],
            _decision(first_revision, Path(first_revision["path"]), supersedes=anchor["id"]),
            tmp_path,
        )
        == 0
    )
    capsys.readouterr()
    served_before = {p.name: p.read_bytes() for p in (root / "answer_examples").iterdir()}

    second_revision = _save_draft(
        served, staging, capsys, question="Gross margin by region second revision?"
    )
    capsys.readouterr()
    second_staged = Path(second_revision["path"])
    staged_dir = staging / "answer_examples"
    staged_before = {p.name: p.read_bytes() for p in staged_dir.iterdir()}
    decision = _decision(
        second_revision, second_staged, supersedes=anchor["id"]
    )  # the anchor is already superseded
    assert run_review(served, staging, second_revision["id"], decision, tmp_path) == 1
    assert "stable" in review_error(capsys)["message"]
    assert (
        {p.name: p.read_bytes() for p in (root / "answer_examples").iterdir()} == served_before
    )
    assert {p.name: p.read_bytes() for p in staged_dir.iterdir()} == staged_before
    # First lineage retained: the anchor still points at its first successor.
    anchor_page = root / "answer_examples" / f"{anchor['id']}.md"
    anchor_meta = yaml.safe_load(anchor_page.read_text(encoding="utf-8").split("---")[1])
    assert anchor_meta["status"] == "superseded"
    assert anchor_meta["superseded_by"] == first_revision["id"]


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

"""Human Git Review Admission and pinned querying (issue #37 / G5; spec
2026-10-02-0009 §§4–6, AC3/4/5/6, ADR-0003's scoped amendment + ADR-0016,
plan §2 "Project storage and authority" + "Authoring call contract" rows
admit/reconcile + QueryRuntime.open_project).

Admission is a HUMAN-ONLY local decision over an EXACT reviewed/validated
candidate revision (spec §5): the operator displays the matching review with
``ariadne-admit`` and records an explicit confirmation for that exact revision
(``--confirm``) — reading a review is never sign-off. Admission materializes
ONLY the admitted artifact scope as an immutable snapshot under
``.ariadne/snapshots/<commit>/`` (no operational records, no uploads, no
credentials) and then publishes ``.ariadne/current.json`` atomically AFTER the
snapshot is complete; a failed snapshot/record activation leaves the previous
descriptor and answers intact. ``QueryRuntime.open_project`` serves the pinned
snapshot through the operator-approved resolved source identity (never
snapshot-relative paths, never a mutable worktree/project checkout), pins one
coherent admitted revision per session, rechecks the session's bound snapshot
bytes and source identity, and keeps the staging/ad-hoc/Answer Example stores
in their ORIGINAL project-owned locations.

Real temporary Git repositories (repo-local identity only), real parquet
sources, no network, no provider. Independent expected values are hand-written
from the fixture rows, never derived from runtime output.
"""

import asyncio
import io
import json
import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import admission as admission_module  # noqa: E402
from ariadne import proposals  # noqa: E402
from ariadne.admission import main as admit_cli  # noqa: E402
from ariadne.admission import reconcile  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.validate import candidate_scope_digest  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    METRIC_PAGE,
    POLICY_PAGE,
    approved,
    branch_of,
    complete_bundle_project,
    record_of,
    run_git,
    worktree_of,
)

STATE = proposals.ARIADNE_STATE_DIR
CURRENT = STATE / "current.json"
SNAPSHOTS = STATE / "snapshots"


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def read_current(project: Path) -> dict:
    return json.loads((project / CURRENT).read_text(encoding="utf-8"))


def blobs_of(project: Path, revision: str) -> dict[str, bytes]:
    return {rel: blob for rel, blob in proposals.scope_blobs(project, revision)}


def admitted_ready(api: AuthoringProject, project: Path, edit: dict) -> tuple[dict, dict]:
    """The full admitable journey: start, approve, one edit, validate (ok),
    review. Returns (review, validated) envelopes of the exact final revision."""
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(started["proposal"], started["candidate_revision"], edit)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert validated["ok"] is True and validated["errors"] == []
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == validated["revision"]
    assert review["report"]["ok"] is True
    return review, {"started": started, "validated": validated}


def admit(project: Path, review: dict, *, confirm: bool = True, extra: list[str] = ()) -> int:
    argv = [
        "--project",
        str(project),
        "--proposal",
        review["proposal"],
        "--revision",
        review["revision"],
        "--reviewed-digest",
        review["review_digest"],
        *extra,
    ]
    if confirm:
        argv.append("--confirm")
    return admit_cli(argv)


# ---------------------------------------------------------- [1] the red seam


def test_only_reviewed_validated_revision_activates_without_changing_candidate_bytes(
    tmp_path, capsys
):
    """Issue #37 [1]: ONLY an explicitly confirmed, reviewed and validated
    revision activates — the candidate's commit and bytes are unchanged by
    admission — and the managed runtime answers from the pinned snapshot with
    hand-computed values, staging ad-hoc/Answer Example work in the ORIGINAL
    project-owned stores without moving one snapshot byte."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, journey = admitted_ready(
        api,
        project,
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        },
    )
    revision = review["revision"]
    proposal = review["proposal"]

    # reading the review — even the exact matching one — is never sign-off
    assert not (project / CURRENT).exists()
    assert not (project / SNAPSHOTS).exists()

    # the display step verifies the reviewed digest but admits NOTHING
    assert admit(project, review, confirm=False) == 0
    displayed = json.loads(capsys.readouterr().out)
    assert displayed["review"]["review_digest"] == review["review_digest"]
    assert displayed["review"]["report"]["ok"] is True
    assert "confirm" in displayed["confirmation_required"].lower()
    assert not (project / CURRENT).exists()

    pre_commit = branch_of(project, proposal)
    pre_blobs = blobs_of(project, revision)
    assert pre_commit == revision

    # explicit operator confirmation activates the pinned snapshot
    assert admit(project, review) == 0
    admitted = json.loads(capsys.readouterr().out)
    current = read_current(project)
    assert admitted["commit"] == revision
    assert current["commit"] == revision
    assert current["route"] == "git-review-admission"
    assert current["review_digest"] == review["review_digest"]
    assert current["artifact_digest"] == journey["validated"]["artifact_digest"]
    assert current["source_digest"] == journey["validated"]["source_digest"]
    assert current["validation"]["ok"] is True
    assert current["confirmed"]["review_digest"] == review["review_digest"]

    # admission changed no candidate byte: same commit, same blobs, clean worktree
    assert branch_of(project, proposal) == pre_commit
    assert blobs_of(project, branch_of(project, proposal)) == pre_blobs

    # the pinned snapshot is ONLY the admitted artifact scope at that commit,
    # byte-identical — no post-review frontmatter/index/log decoration
    snapshot = project / SNAPSHOTS / revision
    assert current["snapshot"] == f"{SNAPSHOTS.as_posix()}/{revision}"
    assert snapshot.is_dir()
    files = {p.relative_to(snapshot).as_posix() for p in snapshot.rglob("*") if p.is_file()}
    assert files == set(pre_blobs)
    for rel, blob in pre_blobs.items():
        assert (snapshot / rel).read_bytes() == blob
    policy_text = (snapshot / "context_layer" / "policies" / "all-events-count.md").read_text(
        encoding="utf-8"
    )
    assert "The rule body, revised." in policy_text
    assert "verified:" not in policy_text  # admission never decorates reviewed bytes
    assert run_git(project, "ls-files", "--", ".ariadne") == ""  # state stays untracked

    # query through the project factory: independent hand-computed values
    # (events.parquet holds exactly (1,'a'), (2,'b'), (3,'c'))
    runtime = QueryRuntime.open_project(project)
    total = asyncio.run(runtime.get_metric("event_count"))
    assert total["governed"] is True
    assert total["rows"] == [{"event_count": 3}]
    assert total["admission"]["route"] == "git-review-admission"
    assert total["admission"]["revision"] == revision
    assert "The rule body, revised." in "".join(total["context"]["policies"])
    by_label = asyncio.run(runtime.get_metric("event_count", ["label"]))
    assert sorted(by_label["rows"], key=lambda row: row["label"]) == [
        {"label": "a", "event_count": 1},
        {"label": "b", "event_count": 1},
        {"label": "c", "event_count": 1},
    ]

    # a later authoring HEAD never changes the admitted answers (AC4): the
    # pinned revision serves until a separately admitted revision replaces it
    moved = api.edit_proposal(
        proposal,
        branch_of(project, proposal),
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "A later authoring edit."),
        },
    )
    assert api.validate_proposal(proposal, moved["revision"])["ok"] is True
    assert branch_of(project, proposal) != revision
    assert read_current(project)["commit"] == revision  # still pinned
    fresh = QueryRuntime.open_project(project)
    pinned = asyncio.run(fresh.get_metric("event_count"))
    assert pinned["rows"] == [{"event_count": 3}]
    assert pinned["admission"]["revision"] == revision
    assert "revised" in "".join(pinned["context"]["policies"])  # served page is the pinned one

    # the ad-hoc path and a confirmed Answer Example land in the ORIGINAL
    # project-owned stores — never inside the pinned artifact root
    adhoc = asyncio.run(
        fresh.define_metric(
            {
                "name": "event_ids",
                "description": "Ad-hoc count of event ids",
                "source": "events.events",
                "expression": "COUNT(id)",
            }
        )
    )
    assert adhoc["governed"] is False
    staged_model = project / "staging" / "semantic_layer" / "models" / "adhoc" / "event_ids.yml"
    staged_page = project / "staging" / "context_layer" / "metrics" / "event_ids.md"
    assert staged_model.is_file() and staged_page.is_file()
    assert "status: draft" in staged_page.read_text(encoding="utf-8")
    assert not (snapshot / "staging").exists()

    saved = asyncio.run(
        fresh.save_example(
            {
                "question": "How many events are there in total",
                "interpretation": "Count every event row once.",
                "method": {"operation": "get_metric", "arguments": {"name": "event_count"}},
                "result": {
                    "metric": "event_count",
                    "sql": total["sql"],
                    "columns": ["event_count"],
                    "rows": [{"event_count": 3}],
                    "governed": True,
                },
                "submitter": "analyst",
                "attestation": "self-declared",
                "sources": ["context_layer/metrics/event_count.md"],
            }
        )
    )
    assert saved["status"] == "draft"
    assert (project / "staging" / "answer_examples" / f"{saved['id']}.md").is_file()
    hits = asyncio.run(fresh.search_examples("events"))
    assert hits and hits[0]["id"] == saved["id"] and hits[0]["status"] == "draft"

    # none of it moved one pinned byte
    assert candidate_scope_digest(snapshot) == current["artifact_digest"]


# ------------------------------------- [2] exact-evidence admission refusals


def _validated_ready(api: AuthoringProject, project: Path, edit: dict) -> dict:
    """Start/approve/one edit/validate(ok)/review; returns the review envelope."""
    review, _journey = admitted_ready(api, project, edit)
    return review


def _policy_edit(text: str) -> dict:
    return {
        "kind": "page",
        "section": "policies",
        "name": "all-events-count",
        "content": POLICY_PAGE.replace("The rule body.", text),
    }


def test_admission_requires_explicit_confirmation_and_refuses_dirty_or_moved_candidates(
    tmp_path, capsys
):
    """Issue #37 [2]/[5]: a missing explicit confirmation, a dirty worktree
    (different artifact bytes), a moved candidate and a mismatched review
    digest each refuse — nothing is ever activated."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review = _validated_ready(api, project, _policy_edit("A revised body."))
    proposal = review["proposal"]
    revision = review["revision"]

    # no programmatic call can admit without the explicit human confirmation
    with pytest.raises(ValueError, match="explicit operator confirmation"):
        admission_module.admit_revision(
            project, proposal, revision, review["review_digest"], confirmed_by=None
        )
    with pytest.raises(ValueError, match="explicit operator confirmation"):
        admission_module.admit_revision(
            project, proposal, revision, review["review_digest"], confirmed_by="   "
        )
    assert not (project / CURRENT).exists()

    # a mismatched review digest refuses at DISPLAY time already
    wrong = "2" * 64
    assert admit(project, review, confirm=False, extra=["--reviewed-digest", wrong]) == 1
    assert "review digest mismatch" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert admit(project, {**review, "review_digest": wrong}) == 1
    assert "review digest mismatch" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert not (project / CURRENT).exists()

    # dirty worktree = different artifact bytes than the reviewed commit
    worktree = worktree_of(project, proposal)
    seed = worktree / "data" / "seed_notes.md"
    seed.write_text("# dirty draft\n", encoding="utf-8")
    assert admit(project, review) == 1
    assert "uncommitted changes" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert not (project / CURRENT).exists()
    run_git(worktree, "checkout", "--", "data/seed_notes.md")

    # a candidate that moved past its validated revision is a different revision
    moved = api.edit_proposal(proposal, revision, _policy_edit("A later edit."))
    assert admit(project, review) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "current candidate" in error["message"] and moved["revision"] != revision
    assert not (project / CURRENT).exists() and not (project / SNAPSHOTS).exists()


def _tamper_validation(project: Path, proposal: str, revision: str, mutate) -> None:
    """Hand-edit one stored validation evidence record (the tampering the
    admission gates must refuse)."""
    path = project / STATE / "validation" / proposal / f"{revision}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    mutate(doc)
    path.write_text(json.dumps(doc, sort_keys=True) + "\n", encoding="utf-8")


def test_admission_refuses_partial_mismatched_or_unapproved_evidence(tmp_path, capsys):
    """Issue #37 [2]/[5]: partial checks, a mismatched validator
    identity/configuration, a changed source identity, a withdrawn operator
    approval and changed cited documents each refuse admission — a
    compile-only, hand-edited or source-invalidated report is never admission
    evidence."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review = _validated_ready(api, project, _policy_edit("A revised body."))
    proposal = review["proposal"]
    revision = review["revision"]
    evidence_path = project / STATE / "validation" / proposal / f"{revision}.json"
    original = evidence_path.read_text(encoding="utf-8")
    approvals_path = project / STATE / "source-approvals.json"
    approvals_original = approvals_path.read_text(encoding="utf-8")
    notes_path = project / "data" / "docs" / "notes.md"
    notes_original = notes_path.read_text(encoding="utf-8")

    def refuse(match: str) -> None:
        assert admit(project, review) == 1
        assert match in json.loads(capsys.readouterr().err)["error"]["message"]
        assert not (project / CURRENT).exists()

    # partial checks: a check flipped to not-run makes the report partial
    _tamper_validation(
        project,
        proposal,
        revision,
        lambda doc: [
            check.update(outcome="not-run")
            for check in doc["report"]["checks"]
            if check["name"] == "bind"
        ],
    )
    refuse("partial")
    evidence_path.write_text(original, encoding="utf-8")  # restore between tamperings

    # mismatched validator identity/configuration
    _tamper_validation(
        project,
        proposal,
        revision,
        lambda doc: doc["validator_identity"].update(check_config_digest="0" * 64),
    )
    refuse("different validator identity")
    evidence_path.write_text(original, encoding="utf-8")  # restore between tamperings

    # changed resolved source identity since validation
    _tamper_validation(
        project, proposal, revision, lambda doc: doc.update(source_digest="1" * 64)
    )
    refuse("source identity")
    evidence_path.write_text(original, encoding="utf-8")

    # a withdrawn operator approval (the identity is no longer approved)
    approvals_path.write_text("{}", encoding="utf-8")
    refuse("NO operator approval")
    approvals_path.write_text(approvals_original, encoding="utf-8")

    # changed cited document evidence since validation: the review digest
    # itself binds the VERIFIED citations, so the changed bytes make the current
    # review a different identity — the exact-digest admission refuses
    notes_path.write_text("# Rule notes, changed\n", encoding="utf-8")
    refuse("review digest mismatch")
    notes_path.write_text(notes_original, encoding="utf-8")

    # restored evidence admits cleanly afterwards
    assert admit(project, review) == 0
    capsys.readouterr()
    assert read_current(project)["commit"] == revision


# ---------------------------------------- [3] atomic activation and preservation


def test_failed_snapshot_or_record_activation_preserves_the_previous_admission(
    tmp_path, monkeypatch, capsys
):
    """Issue #37 [3]: an injected snapshot or record activation failure leaves
    the previous descriptor and answers intact, and a retry after the failure
    activates cleanly (a new snapshot is referenced only once the descriptor
    publishes)."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    first_review = _validated_ready(api, project, _policy_edit("First admitted body."))
    assert admit(project, first_review) == 0
    first = read_current(project)

    second_edit = api.edit_proposal(
        first_review["proposal"],
        first["commit"],
        _policy_edit("Second candidate body."),
    )
    second_validated = api.validate_proposal(
        first_review["proposal"], second_edit["revision"]
    )
    assert second_validated["ok"] is True
    second_review = api.review_proposal(first_review["proposal"])
    assert second_review["revision"] == second_validated["revision"]

    # a failed SNAPSHOT activation refuses before anything is referenced
    def snapshot_boom(*args, **kwargs):
        raise OSError("simulated snapshot failure")

    monkeypatch.setattr(admission_module, "_materialize_snapshot", snapshot_boom)
    assert admit(project, second_review) == 1
    assert "simulated snapshot failure" in json.loads(capsys.readouterr().err)["error"][
        "message"
    ]
    assert read_current(project) == first  # previous descriptor + answers intact
    assert QueryRuntime.open_project(project) is not None
    monkeypatch.undo()

    # a failed RECORD activation (descriptor publish): the new snapshot may
    # exist materialized, but the previous descriptor still serves
    def publish_boom(*args, **kwargs):
        raise OSError("simulated activation failure")

    monkeypatch.setattr(admission_module, "_publish_current", publish_boom)
    assert admit(project, second_review) == 1
    assert "simulated activation failure" in json.loads(capsys.readouterr().err)["error"][
        "message"
    ]
    assert read_current(project) == first
    runtime = QueryRuntime.open_project(project)
    answer = asyncio.run(runtime.get_metric("event_count"))
    assert answer["admission"]["revision"] == first["commit"]
    assert "First admitted body." in "".join(answer["context"]["policies"])
    monkeypatch.undo()

    # after the failure clears, the same reviewed revision activates cleanly
    assert admit(project, second_review) == 0
    capsys.readouterr()
    assert read_current(project)["commit"] == second_review["revision"]


# --------------------------- [4] managed vs legacy factory resolution


def test_open_project_distinguishes_managed_projects_from_explicit_legacy_roots(tmp_path):
    """Issue #37 [4]: the factory refuses a Git-managed project with no valid
    admission (never a fallback to the proposal worktrees or the project's own
    mutable files), rechecks the bound snapshot bytes and approved source
    identity at open and per governed answer, and the explicit legacy
    constructors keep their legacy behavior over the very same project root."""
    from ariadne.planner import PlannerError

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    # proposals exist, no admission: EVERY query method is refused by refusing
    # the runtime itself — no fallback to the project's served-looking files
    with pytest.raises(ValueError, match="no valid admission") as excinfo:
        QueryRuntime.open_project(project)
    assert "never falls back" in str(excinfo.value)
    with pytest.raises(ValueError, match="no valid admission"):
        QueryRuntime.open_project(tmp_path / "not-a-project")  # nothing managed here

    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    record = read_current(project)
    snapshot = project / record["snapshot"]
    page = snapshot / "context_layer" / "metrics" / "event_count.md"
    original_page = page.read_text(encoding="utf-8")
    approvals = project / STATE / "source-approvals.json"
    original_approvals = approvals.read_text(encoding="utf-8")

    # bytes staleness at open: a hand-edited snapshot file never serves
    page.write_text(original_page + "<!-- hand edit -->\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches the admitted artifact digest"):
        QueryRuntime.open_project(project)
    page.write_text(original_page, encoding="utf-8")

    # mid-session staleness: a constructed session refuses on the next governed
    # answer once its pinned bytes move
    runtime = QueryRuntime.open_project(project)
    assert asyncio.run(runtime.get_metric("event_count"))["rows"] == [{"event_count": 3}]
    page.write_text(original_page + "<!-- hand edit -->\n", encoding="utf-8")
    with pytest.raises(PlannerError) as stale:
        asyncio.run(runtime.get_metric("event_count"))
    assert stale.value.code == "admission_stale"
    page.write_text(original_page, encoding="utf-8")

    # source-identity staleness: a withdrawn approval refuses at open and in session
    approvals.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="operator's approval"):
        QueryRuntime.open_project(project)
    with pytest.raises(PlannerError) as source_stale:
        asyncio.run(runtime.get_metric("event_count"))
    assert source_stale.value.code == "admission_stale"
    approvals.write_text(original_approvals, encoding="utf-8")

    # the multi-fact gate keeps its own admission meaning on the Git route: no
    # graph in the snapshot -> query_metrics refuses while single metrics serve
    with pytest.raises(PlannerError) as graphless:
        asyncio.run(runtime.query_metrics({"metrics": ["event_count"]}))
    assert graphless.value.code == "not_admitted"

    # the EXPLICIT legacy constructors keep legacy behavior over the very same
    # project root (fixtures/operators) — never masquerading as the Git route
    legacy = QueryRuntime(
        project / "semantic_layer",
        project / "context_layer",
        None,
        staging_dir=tmp_path / "legacy-staging",
        sources=project / "ariadne.yaml",
    )
    legacy_answer = asyncio.run(legacy.get_metric("event_count"))
    assert legacy_answer["rows"] == [{"event_count": 3}]
    assert "admission" not in legacy_answer  # no pinned-revision provenance claimed
    # the legacy multi-fact gate keeps its own meaning over the legacy root
    # (a promotion-written admission.json that does not exist there)
    with pytest.raises(PlannerError) as legacy_graphless:
        asyncio.run(legacy.query_metrics({"metrics": ["event_count"]}))
    assert legacy_graphless.value.code == "not_admitted"
    assert "no multi-fact admission record" in str(legacy_graphless.value)


def test_managed_sources_resolve_through_operator_identity_not_snapshot_paths(
    tmp_path, monkeypatch
):
    """Issue #37 [4]: the managed runtime opens the operator-approved RESOLVED
    identity (absolute host-root locations recorded with the admission) — the
    snapshot's registry spelling and any snapshot-relative path never reach
    the connection."""
    import ariadne.sources

    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review = _validated_ready(api, project, _policy_edit("A revised body."))
    assert admit(project, review) == 0

    runtime = QueryRuntime.open_project(project)
    assert asyncio.run(runtime.get_metric("event_count"))["rows"] == [{"event_count": 3}]
    assert opened, "the shared connection builder was called"
    for paths in opened:
        for path in paths:
            assert path is not None and Path(path).is_absolute()
            assert str(project) in str(Path(path).resolve())
            assert SNAPSHOTS.as_posix() not in str(Path(path))


# --------------------- [5] advanced admitted baseline and explicit reconcile


def test_an_advanced_admitted_baseline_requires_explicit_reconciliation(tmp_path, capsys):
    """Issue #37 [5]/AC3: a proposal started before another admission cannot
    replace served state (the admitted baseline is not in its ancestry); the
    human-only reconcile records a local merge that DOES carry it, invalidates
    the old validation/review, preserves proposal/repair identity, and then
    revalidation and admission succeed — reconcile itself refuses a revision
    lacking the baseline, never merges automatically, and never clears an
    inconsistent transition."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)

    # proposal A is reviewed/validated first; proposal B starts from the
    # same base BEFORE the admission advanced — the served baseline B's
    # record binds as its expected baseline
    a_started = api.start_proposal()
    approved(api, project, a_started)
    a_review = _validated_ready(api, project, _policy_edit("A's admitted body."))
    b_started = api.start_proposal()
    approved(api, project, b_started)

    # A activates first (its policy edit becomes the served baseline)
    assert admit(project, a_review) == 0
    admitted_commit = read_current(project)["commit"]
    b_validated = api.validate_proposal(
        b_started["proposal"], b_started["candidate_revision"]
    )
    assert b_validated["ok"] is True
    b_review = api.review_proposal(b_started["proposal"])

    # B cannot replace served state: explicit reconciliation is required
    assert admit(project, b_review) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "does not carry it in its ancestry" in error["message"]
    assert read_current(project)["commit"] == admitted_commit  # prior state preserved

    worktree = worktree_of(project, b_started["proposal"])

    # reconcile refuses a revision lacking the current admitted baseline
    run_git(worktree, "commit", "-q", "--allow-empty", "-m", "human: unrelated rebase")
    unrelated = branch_of(project, b_started["proposal"])
    assert (
        authoring_cli(
            [
                "reconcile",
                "--proposal",
                b_started["proposal"],
                "--expected-revision",
                b_validated["revision"],
                "--revision",
                unrelated,
                "--project",
                str(project),
            ]
        )
        == 1
    )
    assert "ancestry" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert (
        record_of(project, b_started["proposal"])["candidate_revision"]
        == b_validated["revision"]
    )

    # the human merges the admitted baseline in by hand (no automatic merge)
    run_git(worktree, "merge", "-q", "--no-edit", admitted_commit)
    merged = branch_of(project, b_started["proposal"])

    # a dirty worktree during reconcile refuses and preserves every record
    (worktree / "data" / "seed_notes.md").write_text("# dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="uncommitted changes"):
        reconcile(project, b_started["proposal"], b_validated["revision"], merged)
    run_git(worktree, "checkout", "--", "data/seed_notes.md")

    # recording the reconciled HEAD: preserves repair identity, invalidates the
    # old revision's validation/review
    reconciled = reconcile(project, b_started["proposal"], b_validated["revision"], merged)
    assert reconciled["revision"] == merged
    assert reconciled["admitted_baseline"] == admitted_commit
    record = record_of(project, b_started["proposal"])
    assert record["candidate_revision"] == merged
    # repair identity preserved across the reconcile: B's one validation round
    # is still counted, never reset by the human rebase
    assert record["repair"] == {"attempts": 1, "status": "open"}
    stale_review = api.review_proposal(b_started["proposal"])
    assert stale_review["revision"] == merged and stale_review["report"] is None

    # validation runs again on the reconciled revision and admission succeeds
    revalidated = api.validate_proposal(b_started["proposal"], merged)
    assert revalidated["ok"] is True
    b_review2 = api.review_proposal(b_started["proposal"])
    assert admit(project, b_review2) == 0
    capsys.readouterr()
    assert read_current(project)["commit"] == revalidated["revision"]

    # the new served revision carries BOTH proposals' changes: A's admitted
    # policy body survived the reconciliation, not erased by B's admission
    runtime = QueryRuntime.open_project(project)
    answer = asyncio.run(runtime.get_metric("event_count"))
    assert answer["rows"] == [{"event_count": 3}]
    assert "A's admitted body." in "".join(answer["context"]["policies"])


def test_reconcile_never_clears_exhausted_repair_state_or_inconsistent_transitions(tmp_path):
    """Issue #37 [5]/spec §4/AC6: a human rebase of an EXHAUSTED proposal is
    recorded (repair history preserved — never reset), validation stays
    refused for the human, and an inconsistent worktree/record transition is
    refused for human resolution, never cleared by reconcile."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    # exhaust the three bounded validation rounds with changed broken candidates
    revision = started["candidate_revision"]
    for removed in ("one", "two", "three"):
        edited = api.edit_proposal(
            started["proposal"],
            revision,
            {
                "kind": "page",
                "section": "metrics",
                "name": "event_count",
                "content": METRIC_PAGE.replace(
                    "resource: policies/all-events-count.md",
                    f"resource: policies/removed-{removed}.md",
                ),
            },
        )
        result = api.validate_proposal(started["proposal"], edited["revision"])
        assert result["ok"] is False
        revision = result["revision"]
    assert record_of(project, started["proposal"])["repair"] == {
        "attempts": 3,
        "status": "review_needed",
    }

    # the human rebases the exhausted proposal: reconcile RECORDS the new HEAD
    worktree = worktree_of(project, started["proposal"])
    run_git(worktree, "commit", "-q", "--allow-empty", "-m", "human: rebase")
    rebased = branch_of(project, started["proposal"])
    reconciled = reconcile(project, started["proposal"], revision, rebased)
    assert reconciled["repair"] == {"attempts": 3, "status": "review_needed"}

    # ...but the exhausted repair state is never cleared: validation stays refused
    with pytest.raises(ValueError, match="review_needed"):
        api.validate_proposal(started["proposal"], rebased)

    # an inconsistent interrupted transition (worktree/record disagreement) is
    # refused for human resolution — never recorded over, never cleared
    run_git(worktree, "commit", "-q", "--allow-empty", "-m", "another human move")
    moved = branch_of(project, started["proposal"])
    with pytest.raises(ValueError, match="is at"):
        reconcile(project, started["proposal"], rebased, rebased)
    record = record_of(project, started["proposal"])
    assert record["candidate_revision"] == rebased  # untouched by the refusal
    assert moved != rebased


# ------------------- [6] session pinning and legacy-route separation


def test_sessions_pin_one_admission_and_legacy_promotion_never_mutates_a_snapshot(tmp_path):
    """Issue #37 [6]: each session pins ONE coherent admitted revision (a later
    session picks up a later admission), and a legacy staged Promotion over the
    project's own roots keeps its separate behavior — verified stamps, index
    and log bookkeeping land in the legacy served root, never in a pinned
    snapshot, and never change the admitted answers."""
    from ariadne.promote import promote

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    first_review = _validated_ready(api, project, _policy_edit("First admitted body."))
    assert admit(project, first_review) == 0
    first = read_current(project)
    first_snapshot = project / first["snapshot"]
    first_digest = candidate_scope_digest(first_snapshot)

    # a second admission on the same proposal: the FIRST session keeps serving
    # its pinned revision (session-level coherent pinning)
    session1 = QueryRuntime.open_project(project)
    second_edit = api.edit_proposal(
        first_review["proposal"], first["commit"], _policy_edit("Second admitted body.")
    )
    assert (
        api.validate_proposal(first_review["proposal"], second_edit["revision"])["ok"]
        is True
    )
    second_review = api.review_proposal(first_review["proposal"])
    assert admit(project, second_review) == 0
    second = read_current(project)
    assert second["commit"] != first["commit"]

    pinned = asyncio.run(session1.get_metric("event_count"))
    assert pinned["admission"]["revision"] == first["commit"]
    assert "First admitted body." in "".join(pinned["context"]["policies"])
    session2 = QueryRuntime.open_project(project)
    current_answer = asyncio.run(session2.get_metric("event_count"))
    assert current_answer["admission"]["revision"] == second["commit"]
    assert "Second admitted body." in "".join(current_answer["context"]["policies"])

    # legacy staged Promotion: separate route, separate bookkeeping, separate
    # roots — the pinned snapshots are never its target
    staging = tmp_path / "legacy-staging"
    (staging / "context_layer" / "metrics").mkdir(parents=True)
    (staging / "context_layer" / "metrics" / "legacy-demo.md").write_text(
        "---\n"
        "type: metric\n"
        "status: draft\n"
        "title: legacy demo\n"
        "description: A legacy staged page.\n"
        "tags: [metric]\n"
        "---\n\n"
        "# legacy demo\n",
        encoding="utf-8",
    )
    promote(staging, project, by="human:test", assume_yes=True)
    served_page = project / "context_layer" / "metrics" / "legacy-demo.md"
    assert "verified:" in served_page.read_text(encoding="utf-8")  # legacy decoration
    assert (project / "context_layer" / "log.md").is_file()  # legacy bookkeeping
    assert candidate_scope_digest(first_snapshot) == first_digest  # snapshot untouched
    unchanged = asyncio.run(session2.get_metric("event_count"))
    assert unchanged["admission"]["revision"] == second["commit"]
    assert "Second admitted body." in "".join(unchanged["context"]["policies"])


def test_cli_project_flag_serves_the_managed_route_and_refuses_without_admission(
    tmp_path, capsys
):
    """The local ``ariadne`` CLI reaches the managed factory through --project:
    the same pinned answers as QueryRuntime.open_project, and the explicit
    no-admission error (one JSON error object) before it."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    from ariadne.cli import main as cli

    assert cli(["list-metrics", "--project", str(project)]) == 1
    error = json.loads(capsys.readouterr().err)["error"]
    assert "no valid admission" in error["message"]

    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True
    review = api.review_proposal(started["proposal"])
    assert admit(project, review) == 0
    capsys.readouterr()  # the admit envelope is not part of the CLI output below

    assert cli(["list-metrics", "--project", str(project)]) == 0
    listed = json.loads(capsys.readouterr().out)
    names = [entry["name"] for entry in listed if isinstance(entry, dict)]
    assert "event_count" in names

    assert cli(["get-metric", "event_count", "--project", str(project)]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["rows"] == [{"event_count": 3}]
    assert answer["admission"]["route"] == "git-review-admission"

    # --project and --served are mutually exclusive explicit roots
    assert cli(["list-metrics", "--project", str(project), "--served", str(project)]) == 1
    assert "mutually exclusive" in json.loads(capsys.readouterr().err)["error"]["message"]


def test_cli_managed_route_stages_under_the_selected_project_from_any_cwd(
    tmp_path, monkeypatch, capsys
):
    """Issue #40 finding 1: an OMITTED --staging must not override the managed
    factory's project-owned default — from a working directory OUTSIDE the
    project, save-example/define-metric with --project stage under
    <project>/staging (discoverable through the managed runtime), an explicit
    --staging still wins, and nothing escapes into the operator's CWD."""
    from ariadne.cli import main as cli

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Revised admitted body."))
    assert admit(project, review) == 0
    capsys.readouterr()  # the admit envelope is not part of the CLI output below

    operator_desk = tmp_path / "operator-desk"
    operator_desk.mkdir()
    monkeypatch.chdir(operator_desk)

    submission = {
        "question": "How many events are there in total",
        "interpretation": "Count every event row once.",
        "method": {"operation": "get_metric", "arguments": {"name": "event_count"}},
        "result": {
            "metric": "event_count",
            "sql": "SELECT COUNT(*) AS event_count FROM events.events",
            "columns": ["event_count"],
            "rows": [{"event_count": 3}],
            "governed": True,
        },
        "submitter": "analyst",
        "attestation": "self-declared",
        "sources": ["context_layer/metrics/event_count.md"],
    }
    assert (
        cli(
            ["save-example", "--project", str(project)],
            stdin=io.StringIO(json.dumps(submission)),
        )
        == 0
    )
    saved = json.loads(capsys.readouterr().out)
    staged = Path(saved["path"])
    assert staged.is_relative_to((project / "staging" / "answer_examples").resolve())
    assert not (operator_desk / "staging").exists()  # nothing escaped to the CWD

    assert (
        cli(
            ["define-metric", "--project", str(project)],
            stdin=io.StringIO(
                json.dumps(
                    {
                        "name": "event_ids_cli",
                        "description": "Ad-hoc count of event ids",
                        "source": "events.events",
                        "expression": "COUNT(id)",
                    }
                )
            ),
        )
        == 0
    )
    adhoc = json.loads(capsys.readouterr().out)
    assert Path(adhoc["staged_as"]).is_relative_to((project / "staging").resolve())
    assert not (operator_desk / "staging").exists()  # still nothing in the CWD

    # the project-owned draft is discoverable through the managed runtime
    runtime = QueryRuntime.open_project(project)
    hits = asyncio.run(runtime.search_examples("events total"))
    assert any(hit["id"] == saved["id"] and hit["status"] == "draft" for hit in hits)

    # an explicit --staging still overrides the project-owned default
    explicit = tmp_path / "explicit-staging"
    assert (
        cli(
            ["save-example", "--project", str(project), "--staging", str(explicit)],
            stdin=io.StringIO(
                json.dumps({**submission, "question": "How many event ids exist in total"})
            ),
        )
        == 0
    )
    override = json.loads(capsys.readouterr().out)
    assert Path(override["path"]).is_relative_to(explicit.resolve())


def test_example_review_splits_citation_and_publication_roots(tmp_path, capsys):
    """Issue #40 finding 2: human example review never conflates its citation
    root with its publication root. Against a managed project, citations
    validate against the pinned admitted snapshot (a Policy present ONLY
    there), the stable example publishes under the LOGICAL project root's
    answer_examples store where managed search looks — and a --served pointing
    into .ariadne/ operator state is refused before anything changes, leaving
    the pinned snapshot byte-identical."""
    import hashlib

    from ariadne.cli import main as cli
    from ariadne.example_review import main as review_cli

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    new_policy = POLICY_PAGE.replace("All events count", "Late admitted counting rule").replace(
        "The rule body.", "A newly admitted rule body."
    )
    review, _journey = admitted_ready(
        api,
        project,
        {
            "kind": "page",
            "section": "policies",
            "name": "late-admitted-counting-rule",
            "content": new_policy,
        },
    )
    assert admit(project, review) == 0
    capsys.readouterr()
    current = read_current(project)
    snapshot = project / current["snapshot"]
    cited = "context_layer/policies/late-admitted-counting-rule.md"
    assert (snapshot / cited).is_file()
    assert not (project / cited).exists()  # newly admitted page: snapshot-only

    # a draft citing the SNAPSHOT-ONLY Policy stages under <project>/staging
    submission = {
        "question": "How many events are there under the late admitted counting rule",
        "interpretation": "Count every event row once under the late rule.",
        "method": {"operation": "get_metric", "arguments": {"name": "event_count"}},
        "result": {
            "metric": "event_count",
            "sql": "SELECT COUNT(*) AS event_count FROM events.events",
            "columns": ["event_count"],
            "rows": [{"event_count": 3}],
            "governed": True,
        },
        "submitter": "analyst",
        "attestation": "self-declared",
        "sources": [cited],
    }
    assert (
        cli(
            ["save-example", "--project", str(project)],
            stdin=io.StringIO(json.dumps(submission)),
        )
        == 0
    )
    saved = json.loads(capsys.readouterr().out)
    staged = Path(saved["path"])

    decision_file = tmp_path / "decision.json"
    decision_file.write_text(
        json.dumps(
            {
                "id": saved["id"],
                "actor": "maintainer:operator",
                "outcome": "approve",
                "technical_review": (
                    "Method is the served event_count metric; the cited Policy matches "
                    "the pinned admitted snapshot."
                ),
                "staged_digest": hashlib.sha256(staged.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    assert (
        review_cli(
            [
                saved["id"],
                "--file",
                str(decision_file),
                "--served",
                str(project),
                "--staging",
                str(project / "staging"),
            ]
        )
        == 0
    )
    approved = json.loads(capsys.readouterr().out)
    served_page = project / "answer_examples" / f"{saved['id']}.md"
    assert Path(approved["path"]) == served_page
    assert served_page.is_file() and not staged.exists()  # the exact record moved
    assert not (snapshot / "answer_examples").exists()  # the snapshot was never the store

    runtime = QueryRuntime.open_project(project)
    hits = asyncio.run(runtime.search_examples("events late rule"))
    mine = next(hit for hit in hits if hit["id"] == saved["id"])
    assert mine["status"] == "stable" and mine["stale"] is False

    # a --served root INSIDE .ariadne/ operator state is refused before any
    # write, naming the project root; the pinned snapshot stays byte-identical
    assert (
        cli(
            ["save-example", "--project", str(project)],
            stdin=io.StringIO(
                json.dumps(
                    {
                        **submission,
                        "question": "How many events exist under the late counting rule overall",
                    }
                )
            ),
        )
        == 0
    )
    saved2 = json.loads(capsys.readouterr().out)
    staged2 = Path(saved2["path"])
    second_decision = tmp_path / "decision2.json"
    second_decision.write_text(
        json.dumps(
            {
                "id": saved2["id"],
                "actor": "maintainer:operator",
                "outcome": "approve",
                "technical_review": "Method and cited pages match the pinned snapshot.",
                "staged_digest": hashlib.sha256(staged2.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    assert (
        review_cli(
            [
                saved2["id"],
                "--file",
                str(second_decision),
                "--served",
                str(snapshot),
                "--staging",
                str(project / "staging"),
            ]
        )
        == 1
    )
    error = json.loads(capsys.readouterr().err)["error"]
    assert "operator state" in error["message"]
    assert f"--served {project.resolve()}" in error["message"]
    assert staged2.is_file()  # the staged record was not consumed
    assert candidate_scope_digest(snapshot) == current["artifact_digest"]
    assert not (snapshot / "answer_examples").exists()


# ------------- [7] review fix pass: bound baselines and pinned serving


def test_a_stale_review_of_an_advanced_baseline_never_activates(tmp_path, capsys):
    """Fix pass finding 1 (plan §2): the confirmation binds the CURRENTLY
    expected served baseline. A candidate that already descends from another
    subsequently admitted proposal cannot activate with its OLD review — the
    baseline advance requires reconcile + revalidation + re-review first."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)

    # proposal A: candidate C1, reviewed/validated while NO admission exists
    a_review, _journey = admitted_ready(api, project, _policy_edit("A's admitted body."))

    # proposal B based on C1 itself BEFORE C1 was admitted: B's candidate
    # descends from C1 and its review binds the no-admission baseline
    b_started = api.start_proposal(base_revision=a_review["revision"])
    approved(api, project, b_started)
    b_edit = api.edit_proposal(
        b_started["proposal"], b_started["candidate_revision"], _policy_edit("B's body.")
    )
    b_validated = api.validate_proposal(b_started["proposal"], b_edit["revision"])
    assert b_validated["ok"] is True
    b_review = api.review_proposal(b_started["proposal"])

    # A activates (its own review bound the no-admission baseline)
    assert admit(project, a_review) == 0
    capsys.readouterr()
    admitted_commit = read_current(project)["commit"]

    # B's stale review must refuse although B's candidate descends from the
    # new baseline: the review bound the OLD expected served baseline
    assert admit(project, b_review) == 1
    error = json.loads(capsys.readouterr().err)["error"]["message"]
    assert "baseline" in error and "reconcile" in error
    assert read_current(project)["commit"] == admitted_commit  # prior state preserved

    # resolution: the human reconciles the advanced baseline (B already
    # carries it in its ancestry), revalidates and re-reviews; the NEW review
    # binds the current baseline and activates
    worktree = worktree_of(project, b_started["proposal"])
    run_git(worktree, "commit", "-q", "--allow-empty", "-m", "human: reconcile baseline")
    reconciled_head = branch_of(project, b_started["proposal"])
    reconciled = reconcile(project, b_started["proposal"], b_review["revision"], reconciled_head)
    assert reconciled["admitted_baseline"] == admitted_commit
    assert record_of(project, b_started["proposal"])["expected_baseline"] == admitted_commit
    assert api.validate_proposal(b_started["proposal"], reconciled_head)["ok"] is True
    fresh_review = api.review_proposal(b_started["proposal"])
    assert fresh_review["review_digest"] != b_review["review_digest"]  # new binding
    assert admit(project, fresh_review) == 0
    capsys.readouterr()
    assert read_current(project)["commit"] == reconciled_head
    runtime = QueryRuntime.open_project(project)
    answer = asyncio.run(runtime.get_metric("event_count"))
    assert "B's body." in "".join(answer["context"]["policies"])


def test_new_proposals_default_base_to_the_admitted_revision(tmp_path):
    """Fix pass finding 2 (plan §2): a proposal started after an admission
    bases on the CURRENT admitted revision (the served state), never the
    unserved project HEAD; the record persists the expected admitted
    baseline, and an explicit known base revision stays honoured."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Admitted body."))
    assert admit(project, review) == 0
    admitted_commit = read_current(project)["commit"]

    # the project's own HEAD is still the pre-proposal initial revision: the
    # default base must be the ADMITTED commit, not that unserved checkout
    head = run_git(project, "rev-parse", "HEAD").strip()
    assert head != admitted_commit
    started = api.start_proposal()
    assert started["base_revision"] == admitted_commit
    assert started["candidate_revision"] == admitted_commit
    record = record_of(project, started["proposal"])
    assert record["base_revision"] == admitted_commit
    assert record["expected_baseline"] == admitted_commit

    # an explicit known base revision is still honoured alongside an admission
    explicit = api.start_proposal(base_revision=head)
    assert explicit["base_revision"] == head


def test_managed_search_examples_finds_project_owned_stable_examples(tmp_path):
    """Fix pass finding 3: on the managed route the Answer Example store is
    anchored at the LOGICAL project root (operator-reviewed stable examples
    under <project>/answer_examples stay discoverable), separate from the
    pinned citation/artifact root — and the snapshot bytes never move."""
    import hashlib

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Admitted body."))
    assert admit(project, review) == 0
    current = read_current(project)
    snapshot = project / current["snapshot"]
    page = snapshot / "context_layer" / "metrics" / "event_count.md"
    digest = hashlib.sha256(page.read_bytes()).hexdigest()

    # an operator-reviewed STABLE example in the project-owned example store,
    # citing the pinned served metric page by its exact digest
    stable = project / "answer_examples" / "how-many-events-total.md"
    stable.parent.mkdir(parents=True, exist_ok=True)
    stable.write_text(
        "---\n"
        "type: answer_example\n"
        "status: stable\n"
        "question: How many events are there in total\n"
        "interpretation: Count every event row once.\n"
        "method:\n"
        "  operation: get_metric\n"
        "  arguments:\n"
        "    name: event_count\n"
        "sources:\n"
        "  - path: context_layer/metrics/event_count.md\n"
        f"    sha256: {digest}\n"
        "submitter:\n"
        "  identity: operator\n"
        "  attestation: self-declared\n"
        "generated: '2026-10-02T00:00:00+00:00'\n"
        "answer:\n"
        "  captured: '2026-10-02T00:00:00+00:00'\n"
        "  result_digest: '0000000000000000000000000000000000000000000000000000000000000000'\n"
        "  excerpt: '{}'\n"
        "review:\n"
        "  actor: operator\n"
        "  at: '2026-10-02T00:00:00+00:00'\n"
        "  outcome: approve\n"
        "  technical_review: reviewed by hand\n"
        "---\n\n"
        "# How many events are there in total\n",
        encoding="utf-8",
    )

    runtime = QueryRuntime.open_project(project)
    hits = asyncio.run(runtime.search_examples("events"))
    assert hits, "the stable project-owned example must be found on the managed route"
    assert hits[0]["status"] == "stable"
    assert hits[0]["id"] == "how-many-events-total"
    assert hits[0]["stale"] is False  # its citation digests match the pinned pages

    # the example store never entered the pinned artifact scope
    assert not (snapshot / "answer_examples").exists()
    assert candidate_scope_digest(snapshot) == current["artifact_digest"]


def test_admission_refuses_tampered_source_identity_evidence(tmp_path, capsys):
    """Fix pass finding 4: the stored source identity is verified as the
    COMPLETE resolved identity at admission — not only its digest — and the
    VERIFIED resolved entries are what the descriptor publishes and the
    runtime opens; a tampered path with a correct digest refuses."""
    from ariadne.authoring_sources import candidate_sources

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Admitted body."))
    proposal, revision = review["proposal"], review["revision"]
    evidence_path = project / STATE / "validation" / proposal / f"{revision}.json"
    original = evidence_path.read_text(encoding="utf-8")

    # the identity's PATH is tampered while the source digest stays valid
    _tamper_validation(
        project,
        proposal,
        revision,
        lambda doc: doc["source_identity"][0].update(
            path=str(project / "data" / "tampered.parquet")
        ),
    )
    assert admit(project, review) == 1
    error = json.loads(capsys.readouterr().err)["error"]["message"]
    assert "source identity" in error
    assert not (project / CURRENT).exists()  # nothing was activated

    # restored evidence admits and publishes the VERIFIED resolved identity
    evidence_path.write_text(original, encoding="utf-8")
    assert admit(project, review) == 0
    capsys.readouterr()
    current = read_current(project)
    resolved, _digest = candidate_sources(project, revision)
    assert current["sources"] == resolved
    assert all("tampered" not in str(entry.get("path")) for entry in current["sources"])


def test_reconcile_refuses_an_interrupted_commit_record_disagreement(tmp_path, monkeypatch):
    """Fix pass finding 5: reconcile records intentional HUMAN rebases only —
    an interrupted core transition (the edit commit landed, the record store
    failed) is preserved for human resolution, never recorded over or
    cleared."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    stale_revision = started["candidate_revision"]

    # simulate the crash AFTER the edit commit but BEFORE the record store
    def store_boom(*args, **kwargs):
        raise OSError("simulated record-store crash")

    monkeypatch.setattr(proposals, "_store_record", store_boom)
    with pytest.raises(OSError, match="simulated record-store crash"):
        api.edit_proposal(
            started["proposal"], stale_revision, _policy_edit("An edit that crashed.")
        )
    monkeypatch.undo()

    interrupted_head = branch_of(project, started["proposal"])
    assert interrupted_head != stale_revision  # the core commit landed
    assert record_of(project, started["proposal"])["candidate_revision"] == stale_revision

    # further core mutations are already refused by the coherence gate
    with pytest.raises(ValueError, match="human resolution"):
        api.validate_proposal(started["proposal"], stale_revision)

    # reconcile must NOT clear the interrupted transition: refuse, preserve
    with pytest.raises(ValueError, match="human resolution"):
        reconcile(project, started["proposal"], stale_revision, interrupted_head)
    record = record_of(project, started["proposal"])
    assert record["candidate_revision"] == stale_revision  # evidence preserved
    assert branch_of(project, started["proposal"]) == interrupted_head


def test_search_context_and_list_metrics_refuse_tampered_snapshot_bytes(tmp_path):
    """Fix pass finding 6: EVERY public operation that serves pinned snapshot
    bytes rechecks them — mid-session snapshot tampering makes search_context
    and list_metrics refuse exactly like get_metric, and the refusal clears
    once the bytes are restored."""
    from ariadne.planner import PlannerError

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _journey = admitted_ready(api, project, _policy_edit("Admitted body."))
    assert admit(project, review) == 0
    record = read_current(project)
    snapshot = project / record["snapshot"]
    page = snapshot / "context_layer" / "policies" / "all-events-count.md"
    original = page.read_text(encoding="utf-8")

    runtime = QueryRuntime.open_project(project)
    assert asyncio.run(runtime.search_context("rule"))  # serves pinned pages
    names = asyncio.run(runtime.list_metrics())
    assert any(isinstance(n, dict) and n["name"] == "event_count" for n in names)

    page.write_text(original + "<!-- hand edit -->\n", encoding="utf-8")
    with pytest.raises(PlannerError) as context_error:
        asyncio.run(runtime.search_context("rule"))
    assert context_error.value.code == "admission_stale"
    with pytest.raises(PlannerError) as metrics_error:
        asyncio.run(runtime.list_metrics())
    assert metrics_error.value.code == "admission_stale"

    page.write_text(original, encoding="utf-8")
    assert asyncio.run(runtime.search_context("rule"))  # refusal cleared


def test_post_rename_publication_failure_preserves_the_serving_admission(
    tmp_path, monkeypatch, capsys
):
    """Fix pass finding 7 (ticket criterion 3): a failure at the real
    post-rename publication boundary never leaves a silent new descriptor —
    the previous admission keeps serving (restored bytes), a first-ever
    admission leaves no descriptor at all, and a clean retry activates."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    first_review = _validated_ready(api, project, _policy_edit("First admitted body."))

    assert admit(project, first_review) == 0
    capsys.readouterr()
    first = read_current(project)

    second_edit = api.edit_proposal(
        first_review["proposal"], first["commit"], _policy_edit("Second body.")
    )
    assert api.validate_proposal(first_review["proposal"], second_edit["revision"])["ok"]
    second_review = api.review_proposal(first_review["proposal"])

    real_fsync = proposals._fsync_path

    def flaky_fsync(watch: Path, fail_on: int):
        calls = {"count": 0}

        def fsync(path):
            path = Path(path)
            if path == watch:
                calls["count"] += 1
                if calls["count"] == fail_on:
                    raise OSError("simulated directory fsync failure")
            return real_fsync(path)

        return fsync

    descriptor_dir = (project / admission_module.CURRENT_REL).parent

    # failure BEFORE the rename: nothing is published; the first admission serves
    monkeypatch.setattr(proposals, "_fsync_path", flaky_fsync(descriptor_dir, 1))
    assert admit(project, second_review) == 1
    assert "simulated directory fsync failure" in json.loads(capsys.readouterr().err)[
        "error"
    ]["message"]
    assert read_current(project) == first

    # failure AFTER the atomic rename (the real post-rename boundary): the
    # previous descriptor is restored and still serves — never a silent new one
    monkeypatch.setattr(proposals, "_fsync_path", flaky_fsync(descriptor_dir, 2))
    assert admit(project, second_review) == 1
    assert "restored" in json.loads(capsys.readouterr().err)["error"]["message"]
    assert read_current(project) == first
    runtime = QueryRuntime.open_project(project)
    answer = asyncio.run(runtime.get_metric("event_count"))
    assert answer["admission"]["revision"] == first["commit"]
    assert "First admitted body." in "".join(answer["context"]["policies"])
    monkeypatch.undo()

    # the failure cleared: the same reviewed revision activates cleanly
    assert admit(project, second_review) == 0
    capsys.readouterr()
    assert read_current(project)["commit"] == second_review["revision"]

    # a FIRST-EVER admission failing post-rename leaves no descriptor at all
    fresh = complete_bundle_project(tmp_path / "fresh")
    fresh_api = AuthoringProject(fresh)
    fresh_review = _validated_ready(fresh_api, fresh, _policy_edit("Only body."))
    fresh_dir = (fresh / admission_module.CURRENT_REL).parent
    monkeypatch.setattr(proposals, "_fsync_path", flaky_fsync(fresh_dir, 2))
    assert admit(fresh, fresh_review) == 1
    assert "simulated directory fsync failure" in json.loads(capsys.readouterr().err)[
        "error"
    ]["message"]
    assert not (fresh / admission_module.CURRENT_REL).exists()
    with pytest.raises(ValueError, match="no valid admission"):
        QueryRuntime.open_project(fresh)

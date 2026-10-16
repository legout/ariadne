"""Finalized effective-revision validation and review of Git authoring
proposals (issue #36 / G4; spec 2026-10-02-0009 §§3–4, AC2/4/6, ADR-0016,
plan §2 rows validate_proposal/review_proposal + "Project storage and
authority").

The candidate is the base project state plus the explicit edits: a page-only
or model-only edit inherits the remaining bundle and STILL runs the whole
dependency check stack (per-type page contract, cited-policy resolution,
compile/bind and the live ADR-0006 grain/cardinality audits) against the
operator-approved source identity (the G3 seam). Deterministic generated
content (computation enrichment, computation pages, index trees) is finalized
BEFORE the candidate commit is validated (spec §4), with no wall-clock
stamping, so an unchanged retry is byte-identical and the validated revision
is the EXACT final commit — never the earlier input commit. Validation
evidence lives in the operator-owned ignored ``.ariadne/validation/`` store,
never inside committed artifacts, binding the commit, the COMPLETE artifact
digest (generated/bookkeeping/Seed Notes bytes included — unlike the legacy
served-tree walker), the resolved source identity, the verified citations and
the validator identity. Reading a review is never sign-off (admission is G5),
and the bounded repair policy is never reset by creating another commit.

Real temporary Git repositories (repo-local identity only), real parquet
sources, no network, no provider. Independent fixtures reuse the established
bundle shapes (tests/test_authoring.py); no second numeric oracle exists here
— assertions cover outcomes, not recomputed measurement values.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import proposals  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from ariadne.authoring_sources import candidate_sources  # noqa: E402

SEED_NOTES = "# Seed notes\n\nAll events count.\n"

# The complete existing bundle's model: one dataset over the approved parquet
# source, a unique declared grain, one governed metric (the test_authoring
# shape; a joined source variant lives below for the unsafe-grain regression).
MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: events
    description: Events model
    datasets:
      - name: events
        source: events.events
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: label
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: label
            dimension: {}
    metrics:
      - name: event_count
        description: Count of all events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

# A model edit that introduces an unsafe grain (AC2): the dataset source joins
# the labels table whose event_id REPEATS (one-to-many), so the structural
# ADR-0006 join check must refuse it even though only one file changed.
UNSAFE_GRAIN_MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: events
    description: Events model (unsafe join)
    datasets:
      - name: events
        source: >-
          SELECT e.id AS id, e.label AS label, l.tag AS tag
          FROM events.events e JOIN labels.labels l ON e.id = l.event_id
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: label
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: label
            dimension: {}
          - name: tag
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: tag
            dimension: {}
    metrics:
      - name: event_count
        description: Count of all events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

# A model edit whose semantic_model entry is not a mapping: the edit seam
# accepts invalid DRAFT content (spec §3), so the pre-validation finalizer and
# the check stack must both treat it as a recoverable structural failure —
# never an exception escaping validate_proposal.
MALFORMED_SEMANTIC_MODEL_YML = """\
version: 0.2.0.dev0
semantic_model: [not-a-mapping]
"""

TABLES_PAGE = (
    "---\n"
    "type: table\n"
    "title: Events\n"
    "description: One row per event.\n"
    "tags: [table]\n"
    "sources:\n"
    "  - id: events\n"
    "    resource: events.events\n"
    "    title: events\n"
    "grain:\n"
    "  primary_key: [id]\n"
    "  cardinality_enforcement: STRICT_1_TO_1\n"
    "---\n\n"
    "# Events\n"
)

REFERENCE_PAGE = (
    "---\n"
    "type: reference\n"
    "title: events identity\n"
    "description: One reference page.\n"
    "tags: [reference]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# events identity\n"
)

# The policy cites one input-area document (notes.md) as well as the Seed
# Notes, so the verified document-evidence linkage is exercised end to end.
POLICY_PAGE = (
    "---\n"
    "type: policy\n"
    "status: draft\n"
    "title: All events count\n"
    "description: The counting rule.\n"
    "tags: [policy]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "  - id: rule-notes\n"
    "    resource: notes.md\n"
    "    title: Rule notes\n"
    "---\n\n"
    "# All events count\n\n"
    "The rule body.\n"
)

METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "status: draft\n"
    "title: event_count\n"
    "description: Count of all events.\n"
    "tags: [metric]\n"
    "sources:\n"
    "  - id: all-events-count\n"
    "    resource: policies/all-events-count.md\n"
    "    title: All events count\n"
    "---\n\n"
    "# event_count\n"
)

SKILLS_PAGE = (
    "---\n"
    "type: skill\n"
    "title: run the demo\n"
    "description: One skill page.\n"
    "tags: [skill]\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# run the demo\n"
)


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def run_git(cwd: Path, *argv: str) -> str:
    """Real git for test-side scaffolding (the seam under test never sees it)."""
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


def write_parquet(path: Path, rows: list[tuple], columns: list[str]) -> Path:
    """A real local parquet file (DuckDB-written) with the given rows/columns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(str(row) for row in rows)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) "
        f"t({', '.join(columns)})) TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def complete_bundle_project(tmp_path: Path) -> Path:
    """A real temporary Git data project whose human-created initial artifact
    revision is a COMPLETE existing bundle: registry with two parquet sources
    (events unique; labels repeating — the unsafe-join fixture), Seed Notes,
    the OSI model and every OKF content type the ADR-0007 gate requires, plus
    the operator's input-area document the policy cites (never an artifact)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_parquet(
        project / "data" / "events.parquet",
        [(1, "a"), (2, "b"), (3, "c")],
        ["id", "label"],
    )
    write_parquet(
        project / "data" / "labels.parquet",
        [(1, "x"), (1, "y"), (2, "z")],
        ["event_id", "tag"],
    )
    (project / "ariadne.yaml").write_text(
        "sources:\n"
        "  - name: events\n"
        "    type: parquet\n"
        "    path: data/events.parquet\n"
        "  - name: labels\n"
        "    type: parquet\n"
        "    path: data/labels.parquet\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (project / "data" / "docs").mkdir(parents=True, exist_ok=True)
    (project / "data" / "docs" / "notes.md").write_text("# Rule notes\n", encoding="utf-8")
    (project / "semantic_layer" / "models").mkdir(parents=True, exist_ok=True)
    (project / "semantic_layer" / "models" / "events.yml").write_text(MODEL_YML, encoding="utf-8")
    pages = {
        "context_layer/tables/events.md": TABLES_PAGE,
        "context_layer/references/joins/events--events.md": REFERENCE_PAGE,
        "context_layer/policies/all-events-count.md": POLICY_PAGE,
        "context_layer/metrics/event_count.md": METRIC_PAGE,
        "context_layer/skills/run-the-demo.md": SKILLS_PAGE,
    }
    for rel, content in pages.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    scope = ["ariadne.yaml", "data/seed_notes.md", "semantic_layer/models/events.yml", *pages]
    run_git(project, "add", "--", *scope)
    run_git(project, "commit", "-q", "-m", "human: complete existing bundle", "--", *scope)
    return project


def worktree_of(project: Path, proposal: str) -> Path:
    return project / ".ariadne" / "worktrees" / proposal


def branch_of(project: Path, proposal: str) -> str:
    return run_git(worktree_of(project, proposal), "rev-parse", "HEAD").strip()


def record_of(project: Path, proposal: str) -> dict:
    return json.loads(
        (project / ".ariadne" / "proposals" / f"{proposal}.json").read_text(encoding="utf-8")
    )


def approved(api: AuthoringProject, project: Path, started: dict) -> None:
    """The operator's approval of the candidate's exact resolved source identity
    (the G3 human step): the profile/audit connection opens only after this."""
    resolved, digest = candidate_sources(project, started["candidate_revision"])
    assert resolved is not None and digest is not None
    api.approve_sources(started["proposal"], started["candidate_revision"], digest)


def commit_paths(project: Path, revision: str) -> set[str]:
    return set(run_git(project, "show", "--name-status", "--format=", revision).splitlines())


# ---------------------------------------------------------- [1] the red seam


def test_page_only_edit_validates_inherited_dependencies_and_exact_final_commit(tmp_path):
    """Issue #36 [1]: from a complete existing bundle, submit ONLY a page edit —
    validation checks the whole effective bundle (inherited model compile/bind
    and live grain audits included), finalizes the deterministic generated
    artifacts into the candidate, and reports the EXACT final commit with its
    separately stored evidence."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        },
    )
    assert edited["changed"] is True

    result = api.validate_proposal(started["proposal"], edited["revision"])
    assert result["ok"] is True and result["errors"] == []

    # the validated revision is the FINAL commit: the finalize pass committed
    # the generated artifacts on top of the page edit, and it IS the branch HEAD
    assert result["revision"] != edited["revision"]
    assert result["revision"] == branch_of(project, started["proposal"])
    generated = commit_paths(project, result["revision"])
    assert any(line.endswith("context_layer/computations/event_count.md") for line in generated)
    assert any(line.endswith("index.md") for line in generated)

    # inherited dependencies were checked against the approved live source:
    # compile, bind and the ADR-0006 grain/cardinality audits all ran and passed
    assert set(result["performed_checks"]) >= {
        "structural",
        "compile",
        "bind",
        "grain",
        "page_contract",
        "citations",
    }
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    assert outcomes["bind"] == "passed" and outcomes["grain"] == "passed"

    # evidence is stored SEPARATELY under the operator-owned .ariadne state,
    # never inside committed artifacts, and binds the exact final commit plus
    # the COMPLETE artifact digest (Seed Notes and generated bytes included)
    evidence = project / ".ariadne" / "validation" / started["proposal"]
    record = json.loads((evidence / f"{result['revision']}.json").read_text(encoding="utf-8"))
    assert record["commit"] == result["revision"]
    assert record["artifact_digest"] == result["artifact_digest"]
    assert "data/seed_notes.md" in record["artifact_files"]
    assert any(path.startswith("context_layer/computations/") for path in record["artifact_files"])
    assert any(path.endswith("/index.md") for path in record["artifact_files"])
    assert run_git(project, "ls-files", "--", ".ariadne") == ""

    # determinism (plan residual risk: timestamp regeneration): an unchanged
    # retry is byte-identical — no new commit, the no-op revision stays a no-op
    # and the bounded repair state is neither reset nor advanced
    again = api.validate_proposal(started["proposal"], result["revision"])
    assert again["revision"] == result["revision"]
    assert again["ok"] is True
    assert again["attempts"] == result["attempts"]
    assert branch_of(project, started["proposal"]) == result["revision"]


# ------------------------------------------- [5] the parameterized regression


def _validated_failure(api: AuthoringProject, started: dict, edit: dict) -> dict:
    """Apply one breaking edit and validate: the failed result envelope."""
    edited = api.edit_proposal(started["proposal"], started["candidate_revision"], edit)
    return api.validate_proposal(started["proposal"], edited["revision"])


@pytest.mark.parametrize(
    "edit, why",
    [
        (
            {
                "kind": "page",
                "section": "metrics",
                "name": "event_count",
                "content": METRIC_PAGE.replace(
                    "resource: policies/all-events-count.md",
                    "resource: policies/removed.md",
                ),
            },
            "broken-policy",
        ),
        ({"kind": "model", "name": "events", "content": UNSAFE_GRAIN_MODEL_YML}, "unsafe-grain"),
    ],
    ids=["broken-policy", "unsafe-grain"],
)
def test_single_file_edits_breaking_inherited_dependencies_fail_validation(tmp_path, edit, why):
    """Issue #36 [5]/AC2: a broken cited Policy and a model edit introducing an
    unsafe grain each block the candidate even though only ONE file changed —
    the inherited dependency checks run against the whole effective bundle."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    result = _validated_failure(api, started, edit)
    assert result["ok"] is False and result["status"] == "invalid"
    assert result["attempts"] == 1  # a changed failed validation consumed a round
    if why == "broken-policy":
        assert any("broken citation" in error for error in result["errors"])
        assert any("policies/removed.md" in error for error in result["errors"])
        outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
        assert outcomes["citations"] == "failed"
    else:
        assert any("grain audit failed" in error for error in result["errors"])
        outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
        assert outcomes["grain"] == "failed"
    # the failed validation still reports the EXACT final revision (the finalize
    # commit) and leaves recoverable errors — a stale expected revision is refused
    assert result["revision"] == branch_of(project, started["proposal"])
    with pytest.raises(ValueError, match="stale"):
        api.validate_proposal(started["proposal"], started["candidate_revision"])


def test_validation_runs_only_through_the_approved_source_identity(tmp_path):
    """Issue #36 [3] constraint: a candidate whose registry identity carries NO
    operator approval never reaches a live check — the explicit G3 error names
    the human step, nothing is opened, and the candidate is repairable after
    the approval (the approval binds the unchanged identity)."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError, match="NO operator approval") as excinfo:
        api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert "approve-sources" in str(excinfo.value)
    # no validation evidence exists and no finalize commit was created
    assert not (project / ".ariadne" / "validation").exists()
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    approved(api, project, started)
    result = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert result["ok"] is True and result["attempts"] == 1


# ------------------------------------------------------- bounded repair state


def test_repair_state_persists_across_failures_retries_restarts_and_rebases(tmp_path):
    """Issue #36 [5]: the per-proposal bounded repair state survives failed
    changed validations (three rounds, then review_needed for the human),
    identical no-op retries (never reset, never advanced), restarts (state on
    disk) and rebases (a different commit NEVER resets it) — spec §4."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    # three CHANGED failing validations exhaust the bounded rounds
    revisions = []
    for round_number, removed in enumerate(("one", "two", "three"), start=1):
        edited = api.edit_proposal(
            started["proposal"],
            revisions[-1] if revisions else started["candidate_revision"],
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
        assert result["attempts"] == round_number
        assert result["repair_status"] == ("review_needed" if round_number == 3 else "open")
        revisions.append(result["revision"])

    # the no-op retry of the last failed validation is idempotent: same errors,
    # same revision, and the exhausted state is neither reset nor advanced
    retry = api.validate_proposal(started["proposal"], revisions[-1])
    assert retry["ok"] is False and retry["attempts"] == 3
    assert retry["repair_status"] == "review_needed"
    assert retry["revision"] == revisions[-1]

    # a CHANGED validation on the exhausted proposal is refused for the human
    fixed = api.edit_proposal(
        started["proposal"],
        revisions[-1],
        {
            "kind": "page",
            "section": "metrics",
            "name": "event_count",
            "content": METRIC_PAGE,
        },
    )
    with pytest.raises(ValueError, match="review_needed"):
        api.validate_proposal(started["proposal"], fixed["revision"])

    # restart: a fresh process boundary (state re-read from disk) sees the same
    # exhausted repair state — a restart can never turn it back into rounds
    fresh = AuthoringProject(project)
    with pytest.raises(ValueError, match="review_needed"):
        fresh.validate_proposal(started["proposal"], fixed["revision"])
    assert record_of(project, started["proposal"])["repair"] == {
        "attempts": 3,
        "status": "review_needed",
    }


def test_a_rebased_commit_never_resets_the_repair_rounds(tmp_path):
    """Issue #36 [5]: a human rebase produces a DIFFERENT candidate commit —
    the repair history continues from where it was (the plan's reconcile
    contract: repair history is preserved), never reset because the commit
    changed."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    result = _validated_failure(
        api,
        started,
        {
            "kind": "page",
            "section": "metrics",
            "name": "event_count",
            "content": METRIC_PAGE.replace(
                "resource: policies/all-events-count.md",
                "resource: policies/removed.md",
            ),
        },
    )
    assert result["attempts"] == 1

    # the human rebase: a new commit on the branch (same content), recorded in
    # the proposal like the reconcile step will — preserving repair history
    worktree = worktree_of(project, started["proposal"])
    run_git(worktree, "commit", "-q", "--allow-empty", "-m", "human: rebase")
    rebased = branch_of(project, started["proposal"])
    record_path = project / ".ariadne" / "proposals" / f"{started['proposal']}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["candidate_revision"] = rebased
    record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")

    # the rebased (different) commit continues the repair rounds at 2
    retried = api.validate_proposal(started["proposal"], rebased)
    assert retried["ok"] is False
    assert retried["attempts"] == 2  # continued, not reset to 1
    assert retried["revision"] == branch_of(project, started["proposal"])


def test_unchanged_computation_preserves_attestation_but_a_changed_one_cannot(tmp_path):
    """Issue #36 [2]: an UNCHANGED computation keeps its predecessor's
    independent attestation bytes verbatim; a CHANGED computation is
    regenerated with the honest ``attestation: pending`` — it cannot inherit
    the expected-value attestation of a computation it no longer is."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    result = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert result["ok"] is True
    computation = "context_layer/computations/event_count.md"

    # an unchanged retry keeps the generated bytes verbatim: the finalize pass
    # is deterministic and the computation is unchanged (idempotent evidence)
    again = api.validate_proposal(started["proposal"], result["revision"])
    assert again["idempotent"] is True
    kept = proposals._read_blob(project, again["revision"], computation)
    assert kept is not None and b"attestation: pending" in kept

    # a CHANGED computation (new metric expression) regenerates pending, never
    # inheriting an attester
    changed = api.edit_proposal(
        started["proposal"],
        again["revision"],
        {
            "kind": "model",
            "name": "events",
            "content": MODEL_YML.replace("expression: COUNT(*)", "expression: COUNT(1)"),
        },
    )
    second = api.validate_proposal(started["proposal"], changed["revision"])
    assert second["ok"] is True
    regenerated = proposals._read_blob(project, second["revision"], computation)
    assert regenerated is not None and b"COUNT(1)" in regenerated
    assert b"attestation: pending" in regenerated
    assert b"attester:" not in regenerated


def _attest_computation_on_branch(project: Path, proposal: str, rel: str, attester: str) -> str:
    """The human's independent expected-value attestation of a generated
    computation: a human commit on the proposal branch (like the rebase
    fixture) that replaces the pending state with a real attester, recorded
    as the candidate revision. Returns the attested revision."""
    worktree = worktree_of(project, proposal)
    page = worktree / rel
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "attestation: pending\n", f"attester: {attester}\n"
        ),
        encoding="utf-8",
    )
    run_git(worktree, "add", "--", rel)
    run_git(worktree, "commit", "-q", "-m", "human: independent attestation")
    revision = branch_of(project, proposal)
    record_path = project / ".ariadne" / "proposals" / f"{proposal}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["candidate_revision"] = revision
    record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return revision


def test_a_source_only_model_change_cannot_inherit_the_predecessor_attestation(tmp_path):
    """Review fix (G4, issue #36 criterion 2): attestation preservation binds
    the computation's FULL semantic dependencies. A model edit that keeps the
    expression (COUNT(*)) but CHANGES the dataset source is a changed
    computation — it cannot inherit the predecessor's expected-value
    attestation and is regenerated with ``attestation: pending``; an unchanged
    model keeps the attested bytes verbatim (the existing behavior)."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    first = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert first["ok"] is True
    computation = "context_layer/computations/event_count.md"
    attested = _attest_computation_on_branch(
        project, started["proposal"], computation, "an-independent-oracle"
    )

    # UNCHANGED model (only a policy page moves): the genuinely attested
    # computation is preserved byte-for-byte
    kept = api.edit_proposal(
        started["proposal"],
        attested,
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        },
    )
    second = api.validate_proposal(started["proposal"], kept["revision"])
    assert second["ok"] is True
    preserved = proposals._read_blob(project, second["revision"], computation)
    assert preserved is not None and b"attester: an-independent-oracle" in preserved

    # SOURCE-ONLY model edit (same expression, different dataset source): a
    # changed computation — regenerated pending, the attester is cleared
    source_changed = api.edit_proposal(
        started["proposal"],
        second["revision"],
        {
            "kind": "model",
            "name": "events",
            "content": MODEL_YML.replace(
                "source: events.events",
                "source: SELECT * FROM events.events WHERE id > 1",
            ),
        },
    )
    third = api.validate_proposal(started["proposal"], source_changed["revision"])
    assert third["ok"] is True
    cleared = proposals._read_blob(project, third["revision"], computation)
    assert cleared is not None and b"attestation: pending" in cleared
    assert b"attester:" not in cleared
    # the regenerated page records the NEW dataset source it sanctions
    assert b"SELECT * FROM events.events WHERE id > 1" in cleared


# ------------------------------------------------------------------- review


def test_review_returns_revisions_inventory_bodies_citations_and_is_read_only(tmp_path):
    """Issue #36 [4]: review exposes the exact current/base revisions, the
    change inventory, bounded effective bodies (complete only when whole), the
    verified citations, the full check scope of the stored report and a review
    digest — read-only: no commit, no branch move, no record change."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "The rule body, revised."),
        },
    )
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert validated["ok"] is True

    record_path = project / ".ariadne" / "proposals" / f"{started['proposal']}.json"
    record_before = record_path.read_bytes()
    head = branch_of(project, started["proposal"])

    review = api.review_proposal(started["proposal"])
    assert review["base_revision"] == started["base_revision"]
    assert review["revision"] == validated["revision"] == head
    changes = {(entry["change"], entry["path"]) for entry in review["changes"]}
    assert ("M", "context_layer/policies/all-events-count.md") in changes
    assert any(path.startswith("context_layer/computations/") for _, path in changes)
    assert ("A", "semantic_layer/models/events.yml") not in changes  # inherited
    # the effective bodies cover the WHOLE candidate scope incl. Seed Notes and
    # generated bytes, each with its stable digest
    paths = {entry["resource"] for entry in review["files"]}
    assert {"ariadne.yaml", "data/seed_notes.md"} <= paths
    assert any(path.startswith("context_layer/computations/") for path in paths)
    assert any(path.endswith("/index.md") for path in paths)
    assert all(entry["complete"] is True for entry in review["files"])
    # source identity, verified citations and the stored report with full scope
    assert review["sources_digest"] and review["source_approved"] is True
    citations = {(c["kind"], c["resource"]) for c in review["citations"]}
    assert ("document", "notes.md") in citations
    assert ("bundle", "policies/all-events-count.md") in citations
    assert ("source", "events.events") in citations
    assert review["report"]["revision"] == validated["revision"]
    assert review["report"]["ok"] is True
    assert set(review["report"]["performed_checks"]) >= {"bind", "grain", "page_contract"}
    assert review["validation_stale"] is False
    assert len(review["review_digest"]) == 64

    # read-only: nothing moved, nothing rewritten, a repeat is identical
    assert branch_of(project, started["proposal"]) == head
    assert record_path.read_bytes() == record_before
    assert api.review_proposal(started["proposal"]) == review


def test_review_never_presents_a_moved_candidate_or_changed_evidence_as_validated(tmp_path):
    """Issue #36 [4]: a candidate that moved past its validated revision has NO
    report for the new commit, and changed document evidence marks the stored
    validation stale — neither can be represented as an unchanged validated
    candidate (spec §4: repair invalidates earlier review/validation evidence)."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    validated = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert validated["ok"] is True

    # the candidate moved: no report binds the new commit
    moved = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", "Later edit."),
        },
    )
    after_move = api.review_proposal(started["proposal"])
    assert after_move["revision"] == moved["revision"]
    assert after_move["report"] is None

    # validate the moved candidate, then change the cited document's bytes: the
    # stored validation is reported stale, never silently reused
    revalidated = api.validate_proposal(started["proposal"], moved["revision"])
    assert revalidated["ok"] is True
    (project / "data" / "docs" / "notes.md").write_text("# Rule notes, changed\n", encoding="utf-8")
    stale = api.review_proposal(started["proposal"])
    assert stale["validation_stale"] is True
    assert any("document evidence" in reason for reason in stale["stale_reasons"])
    # the report itself is still readable (the exact validated revision), but
    # the review says the evidence no longer matches the current bytes
    assert stale["report"]["ok"] is True and stale["report"]["revision"] == moved["revision"]
    # ...and an unchanged-retry validation cannot return the stale evidence: the
    # changed binding context re-validates (consuming a round: the moved
    # candidate's validation was round 2, the changed-document re-run round 3)
    refreshed = api.validate_proposal(started["proposal"], moved["revision"])
    assert refreshed.get("idempotent") is None  # a real re-run, not the stored copy
    assert refreshed["attempts"] == 3


def test_review_bodies_arrive_in_bounded_parts(tmp_path):
    """Bounded review bodies: a long artifact arrives in parts and a partial
    part is never claimed complete."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    long_policy = POLICY_PAGE.replace("The rule body.", "policy line " * 4000)
    api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "page", "section": "policies", "name": "all-events-count", "content": long_policy},
    )
    review = api.review_proposal(started["proposal"])
    policy = next(
        entry for entry in review["files"] if entry["resource"].endswith("all-events-count.md")
    )
    assert policy["parts"] > 1 and policy["complete"] is False


def test_review_parts_retrieve_every_artifacts_later_bodies(tmp_path):
    """Review fix (G4, issue #36 criterion 4 + plan §2 bounded-part contract):
    the requested part applies PER-ARTIFACT — requesting part 2 returns the
    long artifacts' LATER bodies, and short artifacts stay in the inventory as
    honestly exhausted entries instead of failing the whole response, so every
    part of every artifact is retrievable through successive review calls."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    long_policy = POLICY_PAGE.replace("The rule body.", "policy line " * 4000)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": long_policy,
        },
    )
    first = api.review_proposal(started["proposal"])
    second = api.review_proposal(started["proposal"], part=2)  # must not raise
    assert second["revision"] == edited["revision"]

    policy1 = next(
        entry for entry in first["files"] if entry["resource"].endswith("all-events-count.md")
    )
    policy2 = next(
        entry for entry in second["files"] if entry["resource"].endswith("all-events-count.md")
    )
    # the long policy's LATER content arrives: part 2 of the same artifact
    assert policy1["parts"] == policy2["parts"] > 1
    assert policy2["part"] == 2 and policy2["exhausted"] is False
    assert policy2["text"] and policy2["text"] != policy1["text"]
    assert len(policy2["text"]) == len(policy1["text"])  # the full part window

    # short artifacts keep their inventory entry with the same identity —
    # honestly exhausted, never a failed response over one short file
    assert {entry["resource"] for entry in second["files"]} == {
        entry["resource"] for entry in first["files"]
    }
    registry1 = next(entry for entry in first["files"] if entry["resource"] == "ariadne.yaml")
    registry2 = next(entry for entry in second["files"] if entry["resource"] == "ariadne.yaml")
    assert registry2["exhausted"] is True and registry2["text"] == ""
    assert registry2["parts"] == 1 and registry2["digest"] == registry1["digest"]
    assert all(entry["exhausted"] is (entry["parts"] < 2) for entry in second["files"])


# --------------------------------------------------------------- the CLI seam


def test_cli_validate_and_review_the_git_proposal(tmp_path, capsys):
    """The public CLI journey: ``validate`` returns the finalized revision with
    its report, ``review --proposal`` returns the review envelope, and a stale
    expected revision writes exactly one JSON error object."""
    project = complete_bundle_project(tmp_path)
    assert authoring_cli(["start", "--project", str(project)]) == 0
    started = json.loads(capsys.readouterr().out)
    resolved, digest = candidate_sources(project, started["candidate_revision"])
    assert resolved is not None and digest is not None
    assert (
        authoring_cli(
            [
                "approve-sources",
                "--proposal",
                started["proposal"],
                "--revision",
                started["candidate_revision"],
                "--source-digest",
                digest,
                "--project",
                str(project),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        authoring_cli(
            [
                "validate",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--project",
                str(project),
            ]
        )
        == 0
    )
    validated = json.loads(capsys.readouterr().out)
    assert validated["ok"] is True
    assert validated["revision"] != started["candidate_revision"]
    assert validated["revision"] == branch_of(project, started["proposal"])

    assert (
        authoring_cli(
            [
                "review",
                "--proposal",
                started["proposal"],
                "--project",
                str(project),
            ]
        )
        == 0
    )
    review = json.loads(capsys.readouterr().out)
    assert review["revision"] == validated["revision"]
    assert review["report"]["ok"] is True

    # a stale expected revision: one JSON error object, exit 1
    assert (
        authoring_cli(
            [
                "validate",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--project",
                str(project),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["type"] == "ValueError" and "stale" in error["message"]


def test_an_unparseable_draft_model_is_a_recoverable_validation_error(tmp_path):
    """The edit seam deliberately accepts invalid DRAFT content (spec §3), so a
    model whose YAML does not parse is a validation ERROR — never a crash of
    the finalize pass — leaving the proposal repairable with actionable
    structural errors and no finalize commit."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {"kind": "model", "name": "events", "content": "version: [unclosed\n"},
    )
    result = api.validate_proposal(started["proposal"], edited["revision"])
    assert result["ok"] is False
    assert any("not valid YAML" in error for error in result["errors"])
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    assert outcomes["structural"] == "failed"
    # the broken draft never rode a finalize commit: the finalize commit carries
    # ONLY bookkeeping (index trees — no computations, no model bytes), the draft
    # model bytes stand exactly as edited, and the error is repairable against
    # the returned final revision
    finalize_paths = commit_paths(project, result["revision"])
    assert finalize_paths and all(path.endswith("index.md") for path in finalize_paths)
    draft = proposals._read_blob(project, result["revision"], "semantic_layer/models/events.yml")
    assert draft == b"version: [unclosed\n"
    repaired = api.edit_proposal(
        started["proposal"],
        result["revision"],
        {"kind": "model", "name": "events", "content": MODEL_YML},
    )
    fixed = api.validate_proposal(started["proposal"], repaired["revision"])
    assert fixed["ok"] is True and fixed["attempts"] == 2


@pytest.mark.parametrize(
    "edit, why",
    [
        (
            {
                "kind": "page",
                "section": "policies",
                "name": "all-events-count",
                "content": POLICY_PAGE.replace("title: All events count", "title: [unclosed"),
            },
            "malformed-page-frontmatter",
        ),
        (
            {"kind": "model", "name": "events", "content": MALFORMED_SEMANTIC_MODEL_YML},
            "non-mapping-model",
        ),
    ],
    ids=["malformed-page-frontmatter", "non-mapping-model"],
)
def test_malformed_drafts_return_a_stored_failed_validation_never_a_crash(tmp_path, edit, why):
    """Review fix (G4, spec §4): the edit seam accepts invalid DRAFT content,
    so malformed page frontmatter and a non-mapping semantic_model entry are
    recoverable validation FAILURES — validate_proposal RETURNS the failed
    report (named errors, stored evidence, repair state advanced) instead of
    raising from a pre-validation walker, and the proposal stays repairable."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(started["proposal"], started["candidate_revision"], edit)

    result = api.validate_proposal(started["proposal"], edited["revision"])  # no exception

    assert result["ok"] is False and result["status"] == "invalid"
    assert result["attempts"] == 1 and result["repair_status"] == "open"
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
    if why == "malformed-page-frontmatter":
        assert any("frontmatter is not valid YAML" in error for error in result["errors"])
        assert outcomes["page_contract"] == "failed"
        assert outcomes["citations"] == "failed"  # the parse failure is a diagnostic
    else:
        assert any("semantic_model entry is not a mapping" in error for error in result["errors"])
        assert outcomes["structural"] == "failed"
    # the failed report is STORED for the exact final revision (repair
    # accounting counted it — never an escaped exception instead of evidence)
    stored = json.loads(
        (
            project / ".ariadne" / "validation" / started["proposal"] / f"{result['revision']}.json"
        ).read_text(encoding="utf-8")
    )
    assert stored["ok"] is False and stored["repair"]["attempts"] == 1
    # the proposal remains recoverable: repairing the malformed artifact
    # validates clean on the next bounded round
    repaired = api.edit_proposal(
        started["proposal"],
        result["revision"],
        {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE,
        }
        if why == "malformed-page-frontmatter"
        else {"kind": "model", "name": "events", "content": MODEL_YML},
    )
    fixed = api.validate_proposal(started["proposal"], repaired["revision"])
    assert fixed["ok"] is True and fixed["attempts"] == 2


def test_onboarding_candidate_reviews_without_models_and_validates_recoverably(tmp_path):
    """AC5 onboarding parity: an empty-project candidate (registry template +
    Seed Notes, no models yet) is REVIEWABLE read-only, and validating it
    reports the K4 applicability decision — every semantic check explicitly
    not_applicable WITH reasons (a context-only candidate; no invented
    missing page categories) — so the flow stays honest before the first
    metric exists."""
    project = tmp_path / "onboarding"
    project.mkdir()
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "data").mkdir()
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m", "human: onboarding base")

    api = AuthoringProject(project)
    started = api.start_proposal()
    review = api.review_proposal(started["proposal"])
    assert review["revision"] == started["candidate_revision"]
    assert {entry["resource"] for entry in review["files"]} == {
        "ariadne.yaml",
        "data/seed_notes.md",
    }
    assert review["report"] is None and review["changes"] == []

    result = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert result["ok"] is True and result["errors"] == []
    checks = {check["name"]: check for check in result["report"]["checks"]}
    for name in ("structural", "compile", "bind", "grain"):
        assert checks[name]["outcome"] == "not_applicable", name
        assert checks[name]["detail"], f"{name} carries no not_applicable reason"
    # issue #41: the page-contract gate is APPLICABLE — a candidate with no
    # pages carries nothing to check (no invented missing categories)
    assert checks["page_contract"]["outcome"] == "passed"
    assert result["repair_status"] == "open"  # recoverable, rounds remain

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

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from lumio_wiki.git_authoring import (  # pyright: ignore[reportMissingImports] — the mandatory SDK
    GitAuthoringError,
)

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

# C6 (spec0035): the fixture's native knowledge pages — producer-profile
# Metric/Policy pages mirroring the classic bundle's governed pair, written in
# the accepted native page conventions (typed Entity identity, producer
# envelope, KB-relative citations).
NATIVE_POLICY_PAGE = (
    "---\n"
    'id: "entity:all-events-count"\n'
    'title: "All events count"\n'
    "entity_types:\n  - policy\n"
    "tags:\n  - policy\n"
    'summary: "The counting rule for every recorded event."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    "  - id: seed-notes\n"
    "    title: Seed notes\n"
    "ariadne_profile:\n"
    "  version: 1\n"
    "  kind: policy\n"
    "  required_policies: []\n"
    "  native:\n"
    "    type: policy\n"
    "    title: All events count\n"
    "    description: The counting rule.\n"
    "    tags:\n      - policy\n"
    "    status: draft\n"
    "    sources:\n"
    "      - id: seed-notes\n"
    "        title: Seed notes\n"
    "        resource: data/seed_notes.md\n"
    "---\n\n"
    "# All events count\n\n"
    "The rule body.\n"
)
NATIVE_METRIC_PAGE = (
    "---\n"
    'id: "entity:event-count"\n'
    'title: "event_count"\n'
    "entity_types:\n  - metric\n"
    "tags:\n  - metric\n"
    'summary: "Count of all events."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    "  - id: all-events-count\n"
    "    title: All events count\n"
    "ariadne_profile:\n"
    "  version: 1\n"
    "  kind: metric\n"
    "  metric_ref:\n"
    "    model: events\n"
    "    metric: event_count\n"
    "  required_policies:\n"
    "    - namespace: \"urn:uuid:authoring-fixture\"\n"
    "      entity_id: \"entity:all-events-count\"\n"
    "  native:\n"
    "    type: metric\n"
    "    title: event_count\n"
    "    description: Count of all events.\n"
    "    tags:\n      - metric\n"
    "    status: draft\n"
    "    sources:\n"
    "      - id: all-events-count\n"
    "        title: All events count\n"
    "        resource: policies/all-events-count.md\n"
    "    governed_by: policies/all-events-count.md\n"
    "---\n\n"
    "# event_count\n"
)
# The revision-2 integrated selector: the five §10.1 base keys plus the
# explicit capability opt-in and the authored policy_bindings block classifying
# the metric's and the generated computation's complete closure.
NATIVE_SELECTOR = (
    "version: 1\n"
    "mode: integrated\n"
    "subtree: knowledge\n"
    "namespace: urn:uuid:authoring-fixture\n"
    "profile: ariadne-context/1\n"
    "support_revision: 2\n"
    "policy_bindings:\n"
    "  version: 1\n"
    "  bindings:\n"
    "    - subject: {kind: metric, identity: events::event_count}\n"
    "      policy: {namespace: urn:uuid:authoring-fixture, entity_id: entity:all-events-count}\n"
    "      operations: [get_metric, query_metrics]\n"
    "      enforcement: null\n"
    "    - subject: {kind: computation, identity: events::event_count}\n"
    "      policy: {namespace: urn:uuid:authoring-fixture, entity_id: entity:all-events-count}\n"
    "      operations: [get_metric, query_metrics]\n"
    "      enforcement: null\n"
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


def complete_bundle_project(tmp_path: Path, *, native_state: bool = True) -> Path:
    """The complete existing bundle fixture; ``native_state=False`` builds the
    LEGACY variant (no knowledge/ KB and no integration selector) for the
    F4 historical-admission protocol."""
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
    if native_state:
        (project / "context_integration.yaml").write_text(NATIVE_SELECTOR, encoding="utf-8")
    kb = project / "knowledge"
    (kb / "lumio.yaml").write_text(
        "version: 2\n"
        'mode: "categorized"\n'
        "categories:\n"
        "  - name: references\n"
        "  - name: metrics\n"
        "  - name: policies\n"
        "ontology:\n"
        "  entity_types:\n"
        "    reference: {}\n"
        "    metric: {}\n"
        "    policy: {}\n"
        "    computation: {}\n"
        "  predicates: {}\n"
        "  redirects: {}\n",
        encoding="utf-8",
    ) if native_state else None
    (kb / ".lumio-authoring.yaml").write_text(
        'version: 1\nnamespace: "urn:uuid:authoring-fixture"\nsources: {}\nbindings: {}\n',
        encoding="utf-8",
    ) if native_state else None
    if native_state:
        # C6 (spec0035): the governed Metric/Policy pair also lives as
        # producer-native knowledge pages, and the selector carries the
        # revision-2 capability opt-in with the authored §10.1 binding
        # inventory — the classic bundle pages stay as inert fixture payload.
        (kb / "policies").mkdir(parents=True, exist_ok=True)
        (kb / "metrics").mkdir(parents=True, exist_ok=True)
        (kb / "policies" / "all-events-count.md").write_text(NATIVE_POLICY_PAGE, encoding="utf-8")
        (kb / "metrics" / "event-count.md").write_text(NATIVE_METRIC_PAGE, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    scope = [
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/models/events.yml",
        *pages,
    ]
    if native_state:
        scope += [
            "context_integration.yaml",
            "knowledge/lumio.yaml",
            "knowledge/.lumio-authoring.yaml",
            "knowledge/policies/all-events-count.md",
            "knowledge/metrics/event-count.md",
        ]
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


# ---------------------------------------------- native knowledge-page batches

# spec0035/AC4 (plan 0035 C1): the NEW-path fixture and its regression. The
# KB bookkeeping and both pages are hand-authored here from the documented
# KB format (docs/kb-format.md: a dangling claim object entity is a blocking
# validation error; every used Entity Type and Predicate must be declared in
# the Control File) — the oracle is the documented contract, never
# implementation output.


NATIVE_CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: references
    description: "Reference landing pages for independently useful sources."
  - name: tables
    description: "Documentation for table relations."
ontology:
  entity_types:
    reference: {}
    table: {}
  predicates:
    documents: {}
  redirects: {}
"""

# The canonical table Resource of the fixture's order table, derived from the
# native payload contract (sources.py table_resource): base64url of the JSON
# array [source, catalog|null, schema, table] with compact separators — an
# independently computed oracle, not implementation output.
ORDERS_PAYLOAD = json.dumps(["retail", None, "main", "orders"], separators=(",", ":"))
ORDERS_TABLE_URI = "ariadne://table/" + base64.urlsafe_b64encode(
    ORDERS_PAYLOAD.encode("utf-8")
).decode("ascii").rstrip("=")

# One profiled native TABLE page with the generated ``ariadne``
# schema/observations block AND its rendered generated body sections — the
# positive producer metadata shape (documented native table families),
# hand-authored. ``stale_after`` is system-stamped; edits inherit verbatim.
PROFILED_TABLE_PAGE = """---
id: "entity:orders-table"
title: "Orders Table"
entity_types:
  - table
tags:
  - "orders"
summary: "Orders Table."
lifecycle: "draft"
visibility: "public"
sources:
  - id: "owner-notes"
    title: "Owner notes"
ariadne_profile:
  version: 1
  kind: table
  core_ref:
    kind: resource
    id: "@ORDERS_URI@"
  native:
    type: table
    title: "Orders Table"
    description: "The orders table."
    tags:
      - orders
    resource: "@ORDERS_URI@"
    stale_after: "2027-11-10"
    sources:
      - id: "owner-notes"
        title: "Owner notes"
    grain:
      primary_key: [order_number]
      cardinality_enforcement: "strict_1_to_1"
    observed_value_columns:
      order_number: VARCHAR
    ariadne:
      schema:
        - column: order_number
          type: VARCHAR
          nullable: unknown
          default: unknown
          comment: unknown
      observations:
        observed_at: "2026-10-01T00:00:00+00:00"
        scope: full
        row_count: 10
        candidate_keys: [order_number]
        columns:
          order_number:
            null_count: 0
            distinct_count: 10
        citation: "@ORDERS_URI@"
        value_evidence:
          order_number:
            state: observed
            top_values:
              - value: "00123"
                count: 1
---

# Orders Table

## Schema

order_number VARCHAR — one column per order row.

## Observations

Observed 2026-10-01: 10 rows, order_number unique.
""".replace("@ORDERS_URI@", ORDERS_TABLE_URI)


def reference_page(title: str, entity_id: str, body: str, claims_yaml: str = "") -> str:
    """One independently authored Compiled Page (the documented frontmatter
    contract: title, declared Entity ID and types, tags, summary, lifecycle,
    visibility, at least one source)."""
    claims = f"claims:\n{claims_yaml}" if claims_yaml else ""
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n  - reference\n"
        'tags:\n  - "orders"\n'
        f'summary: "{title}."\n'
        'lifecycle: "draft"\n'
        'visibility: "public"\n'
        'sources:\n  - id: "owner-notes"\n    title: "Owner notes"\n'
        f"{claims}"
        "---\n\n"
        f"{body}"
    )


def documents_claim(claim_id: str, object_entity: str) -> str:
    return (
        f'  - id: "{claim_id}"\n'
        "    predicate: documents\n"
        f'    object: "{object_entity}"\n'
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
    )


# One profiled Reference page with SYSTEM-STAMPED native trust claims
# (``verified``) and the AUTHORED Reference extension (``native.ariadne`` —
# the exact existing authored-Reference exception mirrored at the native
# kind). Hand-authored from the documented profile contract; the maintainer
# content is committed so edits inherit the claims verbatim.
PROFILED_REFERENCE_PAGE = """---
id: "entity:policy-basis"
title: "Policy Basis"
entity_types:
  - reference
tags:
  - "orders"
summary: "Policy Basis."
lifecycle: "draft"
visibility: "public"
sources:
  - id: "owner-notes"
    title: "Owner notes"
ariadne_profile:
  version: 1
  kind: reference
  native:
    type: reference
    title: "Policy Basis"
    description: "The basis of the order policy."
    tags:
      - orders
    status: stable
    verified:
      - by: "human:owner"
        on: "2026-11-10"
    ariadne:
      version: 1
      reference_role: identifier
      representations: []
      mappings: []
    sources:
      - id: "owner-notes"
        resource: "references/policy-basis.md"
        title: "Owner notes"
---

# Policy Basis

Basis body.
"""


def native_context_project(tmp_path: Path) -> Path:
    """A real temporary Git project on the native path: the KB the scaffold
    creates (Control File with Core's declared vocabulary plus ONE explicit
    claims predicate the fixture's maintainer declares deliberately, and the
    Source Reference Manifest bound to an explicit namespace) plus the inert
    registry and one committed profiled Reference page carrying system-stamped
    native trust claims — committed once as the human-created base."""
    project = tmp_path / "native"
    (project / "knowledge").mkdir(parents=True)
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "knowledge" / "lumio.yaml").write_text(NATIVE_CONTROL, encoding="utf-8")
    (project / "knowledge" / ".lumio-authoring.yaml").write_text(
        'version: 1\nnamespace: "urn:uuid:native-fixture"\nsources: {}\nbindings: {}\n',
        encoding="utf-8",
    )
    (project / "knowledge" / "references").mkdir()
    (project / "knowledge" / "references" / "policy-basis.md").write_text(
        PROFILED_REFERENCE_PAGE, encoding="utf-8"
    )
    (project / "knowledge" / "tables").mkdir()
    (project / "knowledge" / "tables" / "orders-table.md").write_text(
        PROFILED_TABLE_PAGE, encoding="utf-8"
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(
        project,
        "add",
        "--",
        "ariadne.yaml",
        "knowledge/lumio.yaml",
        "knowledge/.lumio-authoring.yaml",
        "knowledge/references/policy-basis.md",
        "knowledge/tables/orders-table.md",
    )
    run_git(project, "commit", "-q", "-m", "human: native base")
    return project


def test_native_context_batch_is_revision_atomic(tmp_path):
    """AC4 (spec0035 §2): a batch of mutually linked valid pages is accepted
    TOGETHER as one coherent candidate revision — each page's Claim resolves
    against a page that only exists through the other batch member, so no
    write ordering could accept them one at a time. A batch whose required
    reference dangles at an Entity absent from the candidate refuses without
    accepting a partial page set: page bytes, branch and recorded revision
    stay exactly as they were. A stale expected revision refuses the same
    way, and an identical repeat is a no-op (no commit, revision unchanged)."""
    project = native_context_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    pid = started["proposal"]

    # two independently authored pages, mutually linked through Claims whose
    # objects resolve only WITHIN the batch
    codes = reference_page(
        "Order Status Codes",
        "entity:order-status",
        "# Order Status Codes\n\n## Overview\n\nEvery order status code.\n",
        documents_claim("claim:codes-documents-glossary", "entity:order-glossary"),
    )
    glossary = reference_page(
        "Order Glossary",
        "entity:order-glossary",
        "# Order Glossary\n\n## Overview\n\nThe order vocabulary.\n",
        documents_claim("claim:glossary-documents-codes", "entity:order-status"),
    )
    batch = [
        {"path": "knowledge/references/order-status-codes.md", "content": codes},
        {"path": "knowledge/references/order-glossary.md", "content": glossary},
    ]

    result = api.edit_pages_batch(pid, started["candidate_revision"], batch)
    assert result["changed"] is True and result["count"] == 2
    revision = result["revision"]

    # one coherent revision: the proposal branch sits exactly at it, the
    # record names it (bookkeeping updated only AFTER the commit), and the
    # commit carries ONLY the batch's intended paths
    assert revision == branch_of(project, pid)
    assert record_of(project, pid)["candidate_revision"] == revision
    paths = {line.split()[1] for line in commit_paths(project, revision)}
    assert paths == {
        "knowledge/references/order-status-codes.md",
        "knowledge/references/order-glossary.md",
    }
    # both pages landed with their exact authored bytes
    assert proposals._read_blob(
        project, revision, "knowledge/references/order-status-codes.md"
    ) == codes.encode("utf-8")
    assert proposals._read_blob(
        project, revision, "knowledge/references/order-glossary.md"
    ) == glossary.encode("utf-8")

    # a batch whose required reference DANGLES at an entity absent from the
    # candidate (and from the KB) is rejected: no partial page set, no commit,
    # no revision movement, no byte change
    dangling = reference_page(
        "Order Status Codes",
        "entity:order-status",
        "# Order Status Codes\n\n## Overview\n\nRevised body.\n",
        documents_claim("claim:codes-documents-glossary", "entity:ghost-page"),
    )
    with pytest.raises(GitAuthoringError, match="dangling object entity"):
        api.edit_pages_batch(
            pid,
            revision,
            [
                {"path": "knowledge/references/order-status-codes.md", "content": dangling},
                {"path": "knowledge/references/order-glossary.md", "content": glossary},
            ],
        )
    assert branch_of(project, pid) == revision  # the branch never moved
    assert record_of(project, pid)["candidate_revision"] == revision
    assert proposals._read_blob(
        project, revision, "knowledge/references/order-status-codes.md"
    ) == codes.encode("utf-8")  # the refused page's bytes are untouched
    assert not any(
        line.endswith("ghost") for line in run_git(project, "status", "--porcelain").splitlines()
    )  # no refused draft leaked into the worktree

    # a stale expected revision refuses before anything is written
    with pytest.raises(ValueError, match="stale"):
        api.edit_pages_batch(pid, started["candidate_revision"], batch)
    assert branch_of(project, pid) == revision
    assert record_of(project, pid)["candidate_revision"] == revision

    # the identical repeat is a no-op: no commit, the candidate stays
    repeat = api.edit_pages_batch(pid, revision, batch)
    assert repeat["changed"] is False
    assert repeat["revision"] == revision
    assert branch_of(project, pid) == revision


def test_native_profile_trust_claims_inherit_or_refuse(tmp_path):
    """F2: the producer-owned native profile carries the same system-owned
    trust/generated claims under ``ariadne_profile.native`` — the batch seam
    applies the inherited-verbatim rule there too: introducing, changing or
    REMOVING a stamped claim (``verified``) refuses before any write, an
    edit inheriting it verbatim stays allowed, and the AUTHORED Reference
    extension (``native.ariadne``, the exact existing exception mirrored at
    the native kind) stays caller-authorable/inherited without refusal."""
    project = native_context_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    pid = started["proposal"]
    rel = "knowledge/references/policy-basis.md"
    base_blob = proposals._read_blob(project, started["candidate_revision"], rel)
    assert base_blob is not None
    base_text = base_blob.decode("utf-8")

    # inherited verbatim: a body-only change is an ordinary edit
    inherited = base_text.replace("Basis body.", "Basis body, clarified.")
    allowed = api.edit_pages_batch(
        pid,
        started["candidate_revision"],
        [{"path": rel, "content": inherited}],
    )
    assert allowed["changed"] is True

    # FORGED: the stamped verification is re-attributed to another author
    forged = inherited.replace('by: "human:owner"', 'by: "agent:forged"')
    with pytest.raises(ValueError, match="native trust/generated claim"):
        api.edit_pages_batch(pid, allowed["revision"], [{"path": rel, "content": forged}])

    # REMOVED: dropping the stamped claim is the same forgery
    removed = inherited.replace(
        '    verified:\n      - by: "human:owner"\n        on: "2026-11-10"\n', ""
    )
    with pytest.raises(ValueError, match="native trust/generated claim"):
        api.edit_pages_batch(pid, allowed["revision"], [{"path": rel, "content": removed}])

    # the branch, the recorded revision and the page bytes never moved
    assert branch_of(project, pid) == allowed["revision"]
    assert record_of(project, pid)["candidate_revision"] == allowed["revision"]
    assert proposals._read_blob(project, allowed["revision"], rel) == inherited.encode("utf-8")

    # the AUTHORED Reference extension inherits without refusal (the exact
    # existing authored-Reference exception mirrored at the native kind)
    assert "ariadne:" in inherited  # the base carries native.ariadne
    # A Reference's authored Schema heading is not a measured Table section.
    inherited += "\n\n## Schema\n\nAuthored reference schema.\n"
    allowed = api.edit_pages_batch(
        pid, allowed["revision"], [{"path": rel, "content": inherited}]
    )
    assert allowed["changed"] is True

    # F2 completion — native TABLE generated facts (positive producer shape):
    table_rel = "knowledge/tables/orders-table.md"
    table_blob = proposals._read_blob(project, allowed["revision"], table_rel)
    assert table_blob is not None
    table_text = table_blob.decode("utf-8")

    # inherited verbatim: an authored addition OUTSIDE the generated sections
    # is an ordinary edit (the generated Schema/Observations sections are
    # carried unchanged)
    table_edited = table_text.replace(
        "# Orders Table\n\n## Schema",
        "# Orders Table\n\nAuthored context note.\n\n## Schema",
    )
    table_ok = api.edit_pages_batch(
        pid, allowed["revision"], [{"path": table_rel, "content": table_edited}]
    )
    assert table_ok["changed"] is True

    # the RENDERED generated sections are core-owned too: altering the
    # rendered schema type (native metadata unchanged) refuses and leaves
    # bytes/branch/record untouched
    rendered = table_edited.replace(
        "order_number VARCHAR — one column per order row.",
        "order_number TEXT — one column per order row.",
    )
    with pytest.raises(ValueError, match="core-generated"):
        api.edit_pages_batch(pid, table_ok["revision"], [{"path": table_rel, "content": rendered}])
    assert branch_of(project, pid) == table_ok["revision"]
    assert proposals._read_blob(project, table_ok["revision"], table_rel) == table_edited.encode(
        "utf-8"
    )

    # changing the envelope kind to reference cannot LAUNDER the inherited
    # generated non-Reference ariadne block into an authored extension
    laundered = table_edited.replace("kind: table", "kind: reference").replace(
        "type: table", "type: reference"
    )
    laundered = laundered.replace("entity_types:\n  - table", "entity_types:\n  - reference")
    laundered = laundered.replace(
        "    ariadne:\n      schema:\n        - column: order_number\n"
        "          type: VARCHAR\n          nullable: unknown\n"
        "          default: unknown\n          comment: unknown\n"
        "      observations:\n"
        '        observed_at: "2026-10-01T00:00:00+00:00"\n'
        "        scope: full\n        row_count: 10\n"
        "        candidate_keys: [order_number]\n"
        "        columns:\n          order_number:\n"
        "            null_count: 0\n            distinct_count: 10\n"
        f'        citation: "{ORDERS_TABLE_URI}"\n'
        "        value_evidence:\n          order_number:\n"
        "            state: observed\n            top_values:\n"
        '              - value: "00123"\n                count: 1\n',
        "    ariadne:\n      version: 1\n      reference_role: identifier\n"
      "      representations: []\n      mappings: []\n",
    )
    assert "reference_role: identifier" in laundered  # the authored extension shape
    with pytest.raises(ValueError, match="native trust/generated claim"):
        api.edit_pages_batch(pid, table_ok["revision"], [{"path": table_rel, "content": laundered}])
    assert branch_of(project, pid) == table_ok["revision"]

    # INTRODUCING system-stamped generated/stale_after claims refuses
    stamped = inherited.replace(
        "    status: stable\n",
        '    status: stable\n    generated: "2026-11-10T00:00:00+00:00"\n'
        '    stale_after: "2027-11-10"\n',
    )
    with pytest.raises(ValueError, match="native trust/generated claim"):
        api.edit_pages_batch(pid, table_ok["revision"], [{"path": rel, "content": stamped}])

    # REMOVING the inherited system-stamped stale_after refuses
    unstamped = table_edited.replace('    stale_after: "2027-11-10"\n', "")
    with pytest.raises(ValueError, match="native trust/generated claim"):
        api.edit_pages_batch(pid, table_ok["revision"], [{"path": table_rel, "content": unstamped}])
    assert branch_of(project, pid) == table_ok["revision"]


def test_path_title_mismatch_refuses_before_any_write(tmp_path):
    """F3: a path-addressed batch entry whose declared canonical title/identity
    resolves to a DIFFERENT recorded page (agent identity mix-up — no hostile
    filesystem needed) refuses BEFORE any write or claim check against the
    wrong page: every page byte, the branch and the recorded revision stay
    exactly as they were, and no extra path is staged as a workaround."""
    project = native_context_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    pid = started["proposal"]
    first = api.edit_pages_batch(
        pid,
        started["candidate_revision"],
        [
            {
                "path": "knowledge/references/order-status-codes.md",
                "content": reference_page(
                    "Order Status Codes",
                    "entity:order-status",
                    "# Order Status Codes\n\n## Overview\n\nCodes.\n",
                ),
            },
            {
                "path": "knowledge/references/order-glossary.md",
                "content": reference_page(
                    "Order Glossary",
                    "entity:order-glossary",
                    "# Order Glossary\n\n## Overview\n\nGlossary.\n",
                ).replace(
                    'summary: "Order Glossary."',
                    'summary: "Order Glossary."\naliases:\n  - "Glossary"',
                ),
            },
        ],
    )
    assert first["changed"] is True
    revision = first["revision"]
    a_bytes = proposals._read_blob(project, revision, "knowledge/references/order-status-codes.md")
    b_bytes = proposals._read_blob(project, revision, "knowledge/references/order-glossary.md")

    # B's identity submitted at A's recorded path, plus a valid new page C
    mixed = [
        {
            "path": "knowledge/references/order-status-codes.md",
            "content": reference_page(
                "Order Glossary",
                "entity:order-glossary",
                "# Order Glossary\n\n## Overview\n\nRelocated attempt.\n",
            ),
        },
        {
            "path": "knowledge/references/order-ledger.md",
            "content": reference_page(
                "Order Ledger",
                "entity:order-ledger",
                "# Order Ledger\n\n## Overview\n\nLedger.\n",
            ),
        },
    ]
    with pytest.raises(ValueError, match="resolves to the recorded page"):
        api.edit_pages_batch(pid, revision, mixed)

    # nothing moved: bytes, branch, record; no refused draft leaked anywhere
    assert branch_of(project, pid) == revision
    assert record_of(project, pid)["candidate_revision"] == revision
    assert proposals._read_blob(
        project, revision, "knowledge/references/order-status-codes.md"
    ) == a_bytes
    assert proposals._read_blob(
        project, revision, "knowledge/references/order-glossary.md"
    ) == b_bytes
    assert run_git(project, "status", "--porcelain") == ""

    # a title resolving THROUGH AN ALIAS to another recorded page cannot
    # redirect the addressed path either ("Glossary" is B's alias)
    aliased = reference_page(
        "Glossary",
        "entity:glossary-alias",
        "# Glossary\n\n## Overview\n\nRedirect attempt.\n",
    )
    with pytest.raises(ValueError, match="resolves to the recorded page"):
        api.edit_pages_batch(
            pid,
            revision,
            [{"path": "knowledge/references/order-ledger.md", "content": aliased}],
        )
    assert branch_of(project, pid) == revision
    assert run_git(project, "status", "--porcelain") == ""


def test_unsupported_project_refuses_on_every_public_open_without_mutation(tmp_path):
    """F4: the opening gate validates the ACTUAL native project/admission
    format — a retired standalone project carrying only a DUMMY ``knowledge/``
    directory refuses, and a legacy ADMITTED project whose checkout/snapshot
    serves retired Context pages refuses on EVERY public open path (proposal,
    discovery, query) before any state is created, with nothing mutated."""
    project = tmp_path / "legacy-admitted"
    (project / "context_layer" / "metrics").mkdir(parents=True)
    (project / "context_layer" / "metrics" / "old.md").write_text(
        "---\ntype: metric\ntitle: Old\n---\n\n# Old\n", encoding="utf-8"
    )
    (project / "knowledge").mkdir()  # a DUMMY directory is not the native KB
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "context_layer/metrics/old.md")
    run_git(project, "commit", "-q", "-m", "human: legacy admitted base")
    # a pinned LEGACY admission whose snapshot serves the retired pages
    commit = "1" * 40
    snapshot = project / ".ariadne" / "snapshots" / commit
    (snapshot / "context_layer" / "metrics").mkdir(parents=True)
    (snapshot / "context_layer" / "metrics" / "old.md").write_text(
        "---\ntype: metric\ntitle: Old\n---\n\n# Old\n", encoding="utf-8"
    )
    record = {
        "route": "git-review-admission",
        "proposal": "p-20260101000000-abcdef",
        "commit": commit,
        "snapshot": f".ariadne/snapshots/{commit}",
        "artifact_digest": "legacy",
        "review_digest": "legacy",
        "source_digest": "legacy",
        "sources": [],
        "validation": {},
        "confirmed": True,
    }
    (project / ".ariadne" / "current.json").write_text(
        json.dumps(record, sort_keys=True), encoding="utf-8"
    )
    state_before = sorted(str(p) for p in project.rglob("*"))

    from ariadne.discovery import DiscoveryRuntime  # noqa: E402 — the public open path
    from ariadne.query import QueryRuntime  # noqa: E402

    with pytest.raises(ValueError, match="retired standalone Context layout"):
        AuthoringProject(project).start_proposal()
    with pytest.raises(ValueError, match="retired standalone Context layout"):
        DiscoveryRuntime.open_project(project)
    with pytest.raises(ValueError, match="retired standalone Context layout"):
        QueryRuntime.open_project(project)

    # the refusal is NONMUTATING: no locks, worktrees, proposals or writes
    assert sorted(str(p) for p in project.rglob("*")) == state_before

    # the checkout-only legacy shape (pages served from the pinned snapshot,
    # checkout cleaned) refuses through the same admission gate
    checkout = tmp_path / "legacy-checkout"
    checkout.mkdir()
    (checkout / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    run_git(checkout, "init", "-q")
    run_git(checkout, "config", "user.name", "Ariadne Tests")
    run_git(checkout, "config", "user.email", "tests@ariadne.local")
    run_git(checkout, "add", "--", "ariadne.yaml")
    run_git(checkout, "commit", "-q", "-m", "human: legacy cleaned checkout")
    snapshot = checkout / ".ariadne" / "snapshots" / commit
    (snapshot / "context_layer" / "metrics").mkdir(parents=True)
    (snapshot / "context_layer" / "metrics" / "old.md").write_text(
        "---\ntype: metric\ntitle: Old\n---\n\n# Old\n", encoding="utf-8"
    )
    (checkout / ".ariadne" / "current.json").write_text(
        json.dumps(record, sort_keys=True), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="retired standalone Context layout"):
        DiscoveryRuntime.open_project(checkout)
    with pytest.raises(ValueError, match="retired standalone Context layout"):
        AuthoringProject(checkout).start_proposal()
    assert not (checkout / "knowledge").exists()


def test_supplied_historical_standalone_admission_refuses_without_mutation(tmp_path):
    """F4 completion: the opening gate parses the ACTUAL producer format —
    occupied-but-invalid knowledge/ marker files refuse before proposal state
    exists, and an EXACT supplied historical standalone admission (real
    commit, real snapshot, admitted through the public protocol from the
    legacy base revision) refuses at QueryRuntime.open_project BEFORE any
    source open, without mutation, while the valid pinned NATIVE current
    admission still opens (AC7: unrelated state never blocks a valid
    admission)."""
    from ariadne import admission
    from ariadne.query import QueryRuntime

    # occupied-but-INVALID marker files are not the native KB state
    invalid = tmp_path / "invalid-markers"
    (invalid / "context_layer" / "metrics").mkdir(parents=True)
    (invalid / "context_layer" / "metrics" / "old.md").write_text(
        "---\ntype: metric\ntitle: Old\n---\n\n# Old\n", encoding="utf-8"
    )
    knowledge = invalid / "knowledge"
    knowledge.mkdir()
    (knowledge / "lumio.yaml").write_text("not: [a: control\n", encoding="utf-8")
    (knowledge / ".lumio-authoring.yaml").write_text("{{ no manifest", encoding="utf-8")
    (invalid / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    run_git(invalid, "init", "-q")
    run_git(invalid, "config", "user.name", "Ariadne Tests")
    run_git(invalid, "config", "user.email", "tests@ariadne.local")
    with pytest.raises(ValueError, match="retired standalone Context layout"):
        AuthoringProject(invalid).start_proposal()
    assert not (invalid / ".ariadne").exists()  # no proposal state was created

    # an ACTUAL valid historical standalone admission: the public admit
    # protocol from the LEGACY base revision, then a native admission on top
    project = complete_bundle_project(tmp_path / "history", native_state=False)
    legacy_commit = run_git(project, "rev-parse", "HEAD").strip()
    (project / "context_integration.yaml").write_text(
        "version: 1\n"
        "mode: integrated\n"
        "subtree: knowledge\n"
        "namespace: urn:uuid:authoring-fixture\n"
        "profile: ariadne-context/1\n",
        encoding="utf-8",
    )
    kb = project / "knowledge"
    kb.mkdir()
    (kb / "lumio.yaml").write_text(
        "version: 2\n"
        'mode: "categorized"\n'
        "categories:\n"
        "  - name: references\n"
        "ontology:\n"
        "  entity_types:\n"
        "    reference: {}\n"
        "  predicates: {}\n"
        "  redirects: {}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_text(
        'version: 1\nnamespace: "urn:uuid:authoring-fixture"\nsources: {}\nbindings: {}\n',
        encoding="utf-8",
    )
    # the native-state commit retires the legacy metric/model pair (the
    # integrated contract sanctions native metric pages against the working
    # model inventory; the historical LEGACY commit below keeps them)
    (project / "semantic_layer" / "models" / "events.yml").unlink()
    (project / "context_layer" / "metrics" / "event_count.md").unlink()
    run_git(project, "add", "--", "context_integration.yaml", "knowledge/lumio.yaml",
            "knowledge/.lumio-authoring.yaml")
    run_git(project, "add", "--", "semantic_layer/models/events.yml",
            "context_layer/metrics/event_count.md")
    run_git(project, "commit", "-q", "-m", "human: native state added")

    api = AuthoringProject(project)

    # the HISTORICAL standalone record: a REAL validated/reviewed candidate
    # from the LEGACY base revision, materialized with the real persistence
    # machinery at its exact revision — never published (exactly like a
    # pre-cutover historical artifact; the integrated composite publication
    # contract is R0-owned and cannot exist in a local fixture). The project
    # gate passes (real native KB, no current admission) so the refusal
    # exercises the EXACT supplied-record boundary.
    def policy_edit(text: str) -> dict:
        return {
            "kind": "page",
            "section": "policies",
            "name": "all-events-count",
            "content": POLICY_PAGE.replace("The rule body.", text),
        }

    started2 = api.start_proposal(base_revision=legacy_commit)
    resolved2, source_digest2 = candidate_sources(project, started2["candidate_revision"])
    assert resolved2 is not None and source_digest2 is not None
    api.approve_sources(started2["proposal"], started2["candidate_revision"], source_digest2)
    edited2 = api.edit_proposal(started2["proposal"], started2["candidate_revision"],
                                policy_edit("Legacy admitted body."))
    validated2 = api.validate_proposal(started2["proposal"], edited2["revision"])
    assert validated2["ok"] is True and validated2["errors"] == []
    review2 = api.review_proposal(started2["proposal"])
    assert review2["report"]["ok"] is True
    admission._materialize_snapshot(
        project, review2["revision"], proposals.scope_blobs(project, review2["revision"])
    )
    legacy_record = {
        "route": admission.ADMISSION_ROUTE,
        "project": str(project),
        "proposal": review2["proposal"],
        "commit": review2["revision"],
        "snapshot": f".ariadne/snapshots/{review2['revision']}",
        "artifact_digest": validated2["artifact_digest"],
        "review_digest": review2["review_digest"],
        "source_digest": source_digest2,
        "sources": resolved2,
        "validation": {"ok": True, "revision": validated2["revision"]},
        "confirmed": True,
    }
    assert admission.load_current(project) is None  # no current: the supplied
    # record alone is gated — exactly the review's bypass path

    state_before = sorted(str(p) for p in project.rglob("*"))
    with pytest.raises(ValueError, match="retired standalone Context layout"):
        QueryRuntime.open_project(project, admission_record=legacy_record)
    assert sorted(str(p) for p in project.rglob("*")) == state_before  # nonmutating

    # AC7 positive control: the refusal never blocks the project itself — the
    # native KB stays authorable (no blanket refusal from unrelated state)
    assert api.start_proposal()["proposal"].startswith("p-")


@pytest.mark.parametrize("native_format", ("missing", "invalid", "unselected", "unbound", "valid"))
def test_selected_snapshot_requires_native_identity_without_classic_pages(tmp_path, native_format):
    from ariadne import admission

    project = tmp_path / "project"
    commit = "a" * 40
    snapshot = project / ".ariadne" / "snapshots" / commit
    snapshot.mkdir(parents=True)
    record = {"commit": commit, "bound_release": {"digest": "0" * 64}}
    if native_format == "unbound":
        record.pop("bound_release")
    if native_format != "unselected":
        (snapshot / "context_integration.yaml").write_text(
            'version: 1\nmode: integrated\nsubtree: knowledge\n'
            'namespace: "urn:uuid:native-fixture"\nprofile: ariadne-context/1\n',
            encoding="utf-8",
        )
    if native_format != "missing":
        knowledge = snapshot / "knowledge"
        knowledge.mkdir()
        (knowledge / "lumio.yaml").write_text(
            "not: [valid" if native_format == "invalid" else NATIVE_CONTROL, encoding="utf-8"
        )
        (knowledge / ".lumio-authoring.yaml").write_text(
            'version: 1\nnamespace: "urn:uuid:native-fixture"\nsources: {}\nbindings: {}\n'
            if native_format != "invalid"
            else "{{ invalid",
            encoding="utf-8",
        )
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    if native_format == "valid":
        admission.refuse_unsupported_admission_snapshot(project, record)
    else:
        with pytest.raises(ValueError, match="retired standalone Context layout"):
            admission.refuse_unsupported_admission_snapshot(project, record)
    assert before == {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }


def test_reference_kind_cannot_author_generated_table_claims(tmp_path):
    import yaml
    from lumio_wiki import load_knowledge_base
    from lumio_wiki.ariadne_context import native_metadata_errors

    project = native_context_project(tmp_path)
    rel = "knowledge/references/policy-basis.md"
    reference = yaml.safe_load(PROFILED_REFERENCE_PAGE.split("---", 2)[1])
    table = yaml.safe_load(PROFILED_TABLE_PAGE.split("---", 2)[1])
    reference["ariadne_profile"]["core_ref"] = table["ariadne_profile"]["core_ref"]
    reference["ariadne_profile"]["native"].update(
        resource=ORDERS_TABLE_URI, stale_after="2027-11-10"
    )
    body = "\n# Policy Basis\n\nBasis body.\n"
    original = "---\n" + yaml.safe_dump(reference) + "---\n" + body
    (project / rel).write_text(original, encoding="utf-8")
    table_rel = "knowledge/tables/orders-table.md"
    (project / table_rel).unlink()
    run_git(project, "add", "--", rel, table_rel)
    run_git(project, "commit", "-q", "-m", "human: authored reference to orders")
    _kb, report = load_knowledge_base(project / "knowledge")
    assert report.is_valid, report

    table["id"] = reference["id"]
    table["title"] = reference["title"]
    table["ariadne_profile"]["native"].update(
        title=reference["title"],
        status="stable",
        verified=reference["ariadne_profile"]["native"]["verified"],
    )
    assert native_metadata_errors("native", table["ariadne_profile"]["native"], kind="table") == []
    forged = "---\n" + yaml.safe_dump(table) + "---\n" + body
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError, match="native trust/generated claim"):
        api.edit_pages_batch(
            started["proposal"], started["candidate_revision"], [{"path": rel, "content": forged}]
        )
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    assert (
        record_of(project, started["proposal"])["candidate_revision"]
        == started["candidate_revision"]
    )

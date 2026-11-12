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
import yaml
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
    # real required metric-native declarations from the fixture model: the
    # label dimension and the dataset's declared [id] primary key
    "    dimensions:\n      - label\n"
    "    grain:\n"
    "      primary_key: [id]\n"
    "      cardinality_enforcement: strict_1_to_1\n"
    "    sources:\n"
    "      - id: all-events-count\n"
    "        title: All events count\n"
    "        resource: policies/all-events-count.md\n"
    "    governed_by: policies/all-events-count.md\n"
    "---\n\n"
    "# event_count\n"
)
# The candidate-side knowledge identities of the governed fixture pages: the
# native page batch addresses pages by these complete {path, content} objects
# (spec0035 §6) — the retired {kind: page, section, name} edit objects refuse.
NATIVE_POLICY_REL = "knowledge/policies/all-events-count.md"
NATIVE_METRIC_REL = "knowledge/metrics/event-count.md"


def policy_pages(text: str) -> list[dict]:
    """The native batch object list revising the governed policy page's rule
    body to ``text`` (the shared one-page journey edit)."""
    return [
        {
            "path": NATIVE_POLICY_REL,
            "content": NATIVE_POLICY_PAGE.replace("The rule body.", text),
        }
    ]


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
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "lumio.yaml").write_text(
        "version: 2\n"
        'mode: "categorized"\n'
        "categories:\n"
        "  - name: references\n"
        "  - name: metrics\n"
        "  - name: policies\n"
        "  - name: computations\n"
        "  - name: tables\n"
        "  - name: datasets\n"
        "ontology:\n"
        "  entity_types:\n"
        "    reference: {}\n"
        "    metric: {}\n"
        "    policy: {}\n"
        "    computation: {}\n"
        "    table: {}\n"
        "    dataset: {}\n"
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

    edited = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        policy_pages("The rule body, revised."),
    )
    assert edited["changed"] is True

    result = api.validate_proposal(started["proposal"], edited["revision"])
    assert result["ok"] is True and result["errors"] == []

    # the validated revision is the FINAL commit: the finalize pass committed
    # the generated artifacts on top of the page edit, and it IS the branch HEAD
    assert result["revision"] != edited["revision"]
    assert result["revision"] == branch_of(project, started["proposal"])
    generated = commit_paths(project, result["revision"])
    assert any(line.endswith("knowledge/computations/event_count.md") for line in generated)
    # the classic index trees retired with the classic finalize (spec0035 §6):
    # the native derivation commits exactly the generated Computation page

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
    assert any(
        path.startswith("knowledge/computations/") for path in record["artifact_files"]
    )
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


def _validated_failure(apply, api: AuthoringProject, started: dict) -> dict:
    """Apply one breaking edit (via its own live seam) and validate: the
    failed result envelope."""
    edited = apply(api, started)
    return api.validate_proposal(started["proposal"], edited["revision"])


@pytest.mark.parametrize(
    "apply, why",
    [
        (
            lambda api, started: api.edit_pages_batch(
                started["proposal"],
                started["candidate_revision"],
                [
                    {
                        "path": NATIVE_METRIC_REL,
                        "content": NATIVE_METRIC_PAGE.replace(
                            "resource: policies/all-events-count.md",
                            "resource: policies/removed.md",
                        ),
                    }
                ],
            ),
            "broken-policy",
        ),
        (
            lambda api, started: api.edit_proposal(
                started["proposal"],
                started["candidate_revision"],
                {"kind": "model", "name": "events", "content": UNSAFE_GRAIN_MODEL_YML},
            ),
            "unsafe-grain",
        ),
    ],
    ids=["broken-policy", "unsafe-grain"],
)
def test_single_file_edits_breaking_inherited_dependencies_fail_validation(tmp_path, apply, why):
    """Issue #36 [5]/AC2: a broken cited Policy and a model edit introducing an
    unsafe grain each block the candidate even though only ONE file changed —
    the inherited dependency checks run against the whole effective bundle."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)

    result = _validated_failure(apply, api, started)
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
        edited = api.edit_pages_batch(
            started["proposal"],
            revisions[-1] if revisions else started["candidate_revision"],
            [
                {
                    "path": NATIVE_METRIC_REL,
                    "content": NATIVE_METRIC_PAGE.replace(
                        "resource: policies/all-events-count.md",
                        f"resource: policies/removed-{removed}.md",
                    ),
                }
            ],
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
    fixed = api.edit_pages_batch(
        started["proposal"],
        revisions[-1],
        [{"path": NATIVE_METRIC_REL, "content": NATIVE_METRIC_PAGE}],
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
        lambda api, started: api.edit_pages_batch(
            started["proposal"],
            started["candidate_revision"],
            [
                {
                    "path": NATIVE_METRIC_REL,
                    "content": NATIVE_METRIC_PAGE.replace(
                        "resource: policies/all-events-count.md",
                        "resource: policies/removed.md",
                    ),
                }
            ],
        ),
        api,
        started,
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
    computation = "knowledge/computations/event_count.md"

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
    computation = "knowledge/computations/event_count.md"
    attested = _attest_computation_on_branch(
        project, started["proposal"], computation, "an-independent-oracle"
    )

    # UNCHANGED model (only a policy page moves): the genuinely attested
    # computation is preserved byte-for-byte
    kept = api.edit_pages_batch(
        started["proposal"], attested, policy_pages("The rule body, revised.")
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
    edited = api.edit_pages_batch(
        started["proposal"], started["candidate_revision"], policy_pages("The rule body, revised.")
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
    assert ("M", "knowledge/policies/all-events-count.md") in changes
    assert any(path.startswith("knowledge/computations/") for _, path in changes)
    assert ("A", "semantic_layer/models/events.yml") not in changes  # inherited
    # the effective bodies cover the WHOLE candidate scope incl. Seed Notes and
    # generated bytes, each with its stable digest
    paths = {entry["resource"] for entry in review["files"]}
    assert {"ariadne.yaml", "data/seed_notes.md"} <= paths
    assert any(path.startswith("knowledge/computations/") for path in paths)
    assert "knowledge/policies/all-events-count.md" in paths
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
    moved = api.edit_pages_batch(
        started["proposal"], validated["revision"], policy_pages("Later edit.")
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
    long_policy = NATIVE_POLICY_PAGE.replace("The rule body.", "policy line " * 4000)
    api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        [{"path": NATIVE_POLICY_REL, "content": long_policy}],
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
    long_policy = NATIVE_POLICY_PAGE.replace("The rule body.", "policy line " * 4000)
    edited = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        [{"path": NATIVE_POLICY_REL, "content": long_policy}],
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
            {"kind": "model", "name": "events", "content": MALFORMED_SEMANTIC_MODEL_YML},
            "non-mapping-model",
        ),
    ],
    ids=["non-mapping-model"],
)
def test_malformed_drafts_return_a_stored_failed_validation_never_a_crash(tmp_path, edit, why):
    """Review fix (G4, spec §4): the OSI/model edit seam accepts invalid DRAFT
    content, so a non-mapping semantic_model entry is a recoverable validation
    FAILURE — validate_proposal RETURNS the failed report (named errors,
    stored evidence, repair state advanced) instead of raising from a
    pre-validation walker, and the proposal stays repairable."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    edited = api.edit_proposal(started["proposal"], started["candidate_revision"], edit)

    result = api.validate_proposal(started["proposal"], edited["revision"])  # no exception

    assert result["ok"] is False and result["status"] == "invalid"
    assert result["attempts"] == 1 and result["repair_status"] == "open"
    outcomes = {check["name"]: check["outcome"] for check in result["report"]["checks"]}
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
        {"kind": "model", "name": "events", "content": MODEL_YML},
    )
    fixed = api.validate_proposal(started["proposal"], repaired["revision"])
    assert fixed["ok"] is True and fixed["attempts"] == 2


def test_malformed_native_page_refuses_the_batch_and_never_crashes(tmp_path):
    """AC4 native counterpart (spec0035 §2/§6): a native knowledge page with
    malformed frontmatter refuses the producer writer INSIDE the public page
    batch before any byte — the candidate and its bounded repair state stay
    at the approved base (the batch never landed, so no validation round is
    consumed) and the flow recovers cleanly — never an escaped exception."""
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    malformed = NATIVE_POLICY_PAGE.replace('title: "All events count"', 'title: "[unclosed')
    with pytest.raises(GitAuthoringError):
        api.edit_pages_batch(
            started["proposal"],
            started["candidate_revision"],
            [{"path": NATIVE_POLICY_REL, "content": malformed}],
        )
    assert branch_of(project, started["proposal"]) == started["candidate_revision"]
    clean = api.validate_proposal(started["proposal"], started["candidate_revision"])
    assert clean["ok"] is True and clean["attempts"] == 1


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
        "entity_types:\n  - table\n"
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
    # exercises the EXACT supplied-record boundary. The candidate's visible
    # edit rides the live seed-notes artifact: the context-layer page kind is
    # retired and the legacy base has no knowledge/ KB for a native page.
    started2 = api.start_proposal(base_revision=legacy_commit)
    resolved2, source_digest2 = candidate_sources(project, started2["candidate_revision"])
    assert resolved2 is not None and source_digest2 is not None
    api.approve_sources(started2["proposal"], started2["candidate_revision"], source_digest2)
    edited2 = api.edit_proposal(
        started2["proposal"],
        started2["candidate_revision"],
        {
            "kind": "seed_notes",
            "content": SEED_NOTES.replace("All events count.", "Legacy admitted body."),
        },
    )
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


# ----------------------------- C6 fix R6: recovered live refresh invariants
# (native recovery of the deleted tests/test_context_schema.py scenarios —
# real native refresh journeys, no classic builders, independently authored
# oracles)


def _evolution_project(tmp_path: Path) -> Path:
    """A Git data project whose two parquet sources both expose a table named
    ``orders`` in distinct sources (issue #41 [1]'s same-named-assets shape)
    with a real native knowledge/ KB and revision-2 selector."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, 10.0), (2, 20.0), (3, 30.0)],
        ["order_id", "amount"],
    )
    write_parquet(
        project / "data" / "support" / "orders.parquet",
        [(1, "t1"), (2, "t2")],
        ["order_id", "ticket"],
    )
    (project / "ariadne.yaml").write_text(
        "sources:\n"
        "  - name: sales\n    type: parquet\n    path: data/sales/orders.parquet\n"
        "  - name: support\n    type: parquet\n    path: data/support/orders.parquet\n",
        encoding="utf-8",
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text("# Notes\n", encoding="utf-8")
    kb = project / "knowledge"
    (kb / "tables").mkdir(parents=True, exist_ok=True)
    (kb / "datasets").mkdir(parents=True, exist_ok=True)
    (kb / "lumio.yaml").write_text(
        "version: 2\n"
        'mode: "categorized"\n'
        "categories:\n"
        "  - name: tables\n"
        "  - name: datasets\n"
        "ontology:\n"
        "  entity_types:\n"
        "    table: {}\n"
        "    dataset: {}\n"
        "  predicates: {}\n"
        "  redirects: {}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_text(
        'version: 1\nnamespace: "urn:uuid:evolution-fixture"\nsources: {}\nbindings: {}\n',
        encoding="utf-8",
    )
    (project / "context_integration.yaml").write_text(
        "version: 1\n"
        "mode: integrated\n"
        "subtree: knowledge\n"
        "namespace: urn:uuid:evolution-fixture\n"
        "profile: ariadne-context/1\n"
        "support_revision: 2\n"
        "policy_bindings:\n"
        "  version: 1\n"
        "  bindings: []\n",
        encoding="utf-8",
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(
        project,
        "add",
        "--",
        "ariadne.yaml",
        "data/seed_notes.md",
        "knowledge",
        "context_integration.yaml",
    )
    run_git(project, "commit", "-q", "-m", "human: two same-named orders sources")
    return project


SALES_ASSET = {"source": "sales", "catalog": None, "schema": "sales", "table": "orders"}
SUPPORT_ASSET = {"source": "support", "catalog": None, "schema": "support", "table": "orders"}


def _generated_rel(resource: str, source: str, kind: str = "tables") -> str:
    from ariadne.context import generated_page_filename

    return f"knowledge/{kind}/{generated_page_filename(resource, source)}"


def _table_resource_of(asset: dict) -> str:
    from ariadne.sources import table_resource

    return table_resource(asset["source"], asset.get("catalog"), asset["schema"], asset["table"])


def _page_split(text: str) -> tuple[str, str]:
    # the text opens with '---', so split yields ('', frontmatter, body) —
    # the FRONTMATTER is the middle part, never the first
    _opening, _front, body = text.split("---", 2)
    return "---" + _front + "---", body


def test_refresh_preserves_only_unchanged_meaning_and_moves_changes_to_history(tmp_path):
    """R6-N1 (native recovery of the deleted combined refresh test, issue #41
    [1]): same-named tables in distinct sources stay distinct resources/pages;
    authored column meaning survives refresh only for identical column
    identity/type; a removed column's meaning — a MULTILINE block complete —
    moves into reviewable Schema history; a new column gets no guessed
    meaning; a narrower refresh keeps still-represented dataset links; the
    identical refresh is a no-op; a malformed authored selection refuses the
    refresh before any write."""
    from ariadne.author import _load_frontmatter_meta

    project = _evolution_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    revision = started["candidate_revision"]

    first = api.refresh_schema(proposal, revision, [SALES_ASSET, SUPPORT_ASSET])
    assert first["changed"] is True
    sales_resource = _table_resource_of(SALES_ASSET)
    support_resource = _table_resource_of(SUPPORT_ASSET)
    assert sales_resource != support_resource  # same name, distinct assets
    sales_rel = _generated_rel(sales_resource, "sales")
    support_rel = _generated_rel(support_resource, "support")
    assert sales_rel != support_rel
    worktree = worktree_of(project, proposal)

    # author meaning for two sales columns — one SINGLE line, one MULTILINE —
    # as CURATED BODY content (the native body is operator space; the core
    # schema/observation facts live in the technical envelope)
    front, body = _page_split((worktree / sales_rel).read_text(encoding="utf-8"))
    authored_body = (
        "\n# sales.sales.orders\n\n"
        "Curated operator notes.\n\n"
        "## Column meanings\n\n"
        "- `order_id` — business key of a sale\n"
        "- `amount` — net amount of the sale\n"
        "  in source currency, taxes included\n"
    )
    assert authored_body != body  # the curated notes replace the placeholder
    edited = api.edit_pages_batch(
        proposal, first["revision"], [{"path": sales_rel, "content": front + authored_body}]
    )
    assert edited["changed"] is True
    # the landed bytes (the writer normalizes the frontmatter boundary) — the
    # independent baseline the refresh must preserve verbatim
    authored_landed = _page_split((worktree / sales_rel).read_text(encoding="utf-8"))[1]

    # the physical source changes: `amount` disappears, `qty` arrives
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, 7), (2, 8), (3, 7)],
        ["order_id", "qty"],
    )
    second = api.refresh_schema(proposal, edited["revision"], [SALES_ASSET, SUPPORT_ASSET])
    sales_entry = next(p for p in second["pages"] if p["resource"] == sales_resource)
    assert sales_entry["changes"] == {"added": ["qty"], "removed": ["amount"], "type_changed": []}
    refreshed = (worktree / sales_rel).read_text(encoding="utf-8")
    _front2, body2 = _page_split(refreshed)
    # the curated body survives — the complete multiline meaning block
    # included: authored meaning is retained for the operator, never rewritten
    # by the core-owned facts regeneration (the writer normalizes only the
    # frontmatter-boundary newline, never body content)
    assert body2.strip() == authored_landed.strip()
    assert "- `amount` — net amount of the sale\n  in source currency, taxes included\n" in body2
    refreshed_native = _load_frontmatter_meta(refreshed)["ariadne_profile"]["native"]
    schema_rows = {row["column"]: row for row in refreshed_native["ariadne"]["schema"]}
    # the core facts moved with the source: amount gone, qty present with its
    # INSPECTED type, no guessed meaning anywhere in the authored body
    assert set(schema_rows) == {"order_id", "qty"}
    assert "`qty`" not in body2  # a new column gets no guessed meaning
    assert "## Column meanings" in body2  # the curated section is intact
    support_entry = next(p for p in second["pages"] if p["resource"] == support_resource)
    assert support_entry["changes"] == {"added": [], "removed": [], "type_changed": []}

    # a NARROWER refresh (sales only) keeps the still-represented support link
    from ariadne.sources import collection_resource

    collection = collection_resource("sales", None, "sales")
    dataset_rel = _generated_rel(collection, "sales", kind="datasets")
    dataset_native = _load_frontmatter_meta(
        (worktree / dataset_rel).read_text(encoding="utf-8")
    )["ariadne_profile"]["native"]
    assert sales_resource in dataset_native["ariadne"]["tables"]
    narrower = api.refresh_schema(proposal, second["revision"], [SALES_ASSET])
    dataset_native = _load_frontmatter_meta(
        (worktree / dataset_rel).read_text(encoding="utf-8")
    )["ariadne_profile"]["native"]
    # the support page (refreshed earlier) stays represented on the shared
    # collection's overview only if it shares the collection — it does not
    # (distinct sources): the invariant is that the SALES overview never drops
    # the sales link and never gains an unrequested one
    assert sales_resource in dataset_native["ariadne"]["tables"]
    assert support_resource not in dataset_native["ariadne"]["tables"]

    # the IDENTICAL refresh is a no-op: same inputs, same content, no commit
    third = api.refresh_schema(proposal, narrower["revision"], [SALES_ASSET])
    assert third["changed"] is False
    assert third["revision"] == narrower["revision"]

    # a MALFORMED authored selection (a list, not a mapping) refuses at the
    # PUBLIC BATCH seam — the producer page gate rejects it before any byte
    # is written (the earlier honest boundary; the refresh keeps the same
    # named refusal for pages arriving by other means): page bytes and the
    # candidate revision are unchanged
    before_bytes = (worktree / sales_rel).read_bytes()
    meta = _load_frontmatter_meta((worktree / sales_rel).read_text(encoding="utf-8"))
    meta["ariadne_profile"]["native"]["observed_value_columns"] = ["qty"]
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    _f, b = _page_split((worktree / sales_rel).read_text(encoding="utf-8"))
    from lumio_wiki.git_authoring import GitAuthoringError

    with pytest.raises(
        GitAuthoringError, match="observed_value_columns must map column names"
    ):
        api.edit_pages_batch(
            proposal,
            third["revision"],
            [{"path": sales_rel, "content": f"---\n{dumped}\n---{b}"}],
        )
    assert (worktree / sales_rel).read_bytes() == before_bytes  # nothing was written
    still = proposals._load_record(project, proposal)["candidate_revision"]
    assert still == third["revision"]  # and no revision moved


def test_refresh_refuses_generated_target_collision_without_overwrite(tmp_path):
    """R6-N2 (native recovery of the deleted collision leg, issue #41 [5]):
    a different page already sitting at the generated table-page path is a
    collision the refresh REFUSES — never an overwrite; the candidate
    revision and the occupant's bytes stay unchanged."""
    project = _evolution_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    sales_resource = _table_resource_of(SALES_ASSET)
    sales_rel = _generated_rel(sales_resource, "sales")
    worktree = worktree_of(project, proposal)

    # an authored ordinary page already occupies the generated target path
    occupant = (
        "---\n"
        "id: entity:occupied-table-slot\n"
        "title: Occupied table slot\n"
        "entity_types:\n  - table\n"
        "tags:\n  - note\n"
        'summary: "A deliberately planted page."\n'
        'lifecycle: "draft"\n'
        'visibility: "public"\n'
        'sources:\n  - id: planted-note\n    title: Planted note\n'
        "---\n\n# Occupied table slot\n\nDeliberately planted at the target.\n"
    )
    planted = api.edit_pages_batch(
        proposal, started["candidate_revision"], [{"path": sales_rel, "content": occupant}]
    )
    assert planted["changed"] is True
    occupant_bytes = (worktree / sales_rel).read_bytes()

    with pytest.raises(ValueError, match="collision"):
        api.refresh_schema(proposal, planted["revision"], [SALES_ASSET])
    # nothing was overwritten and no revision moved
    assert (worktree / sales_rel).read_bytes() == occupant_bytes
    still = proposals._load_record(project, proposal)["candidate_revision"]
    assert still == planted["revision"]


def test_type_change_rebinding_and_deselection_keep_history(tmp_path):
    """R6-N3 (native recovery of the deleted spec0024 §3/§6 AC4 scenario): a
    type change loses usable values with the visible ``type_changed`` reason
    while the human-owned selection is preserved for review; repeating the
    refresh stays unavailable (the old binding is never silently erased);
    explicit rebinding restores evidence; deselection removes ACTIVE evidence
    while the schema history survives. Expectations derive from the authored
    literals (EMEA 2 / AMER 1), never implementation output."""
    from ariadne.author import _load_frontmatter_meta

    project = _evolution_project(tmp_path)
    # one VARCHAR region column with hand-authored literals EMEA, EMEA, AMER
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, "EMEA"), (2, "EMEA"), (3, "AMER")],
        ["order_id", "region"],
    )
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    sales_resource = _table_resource_of(SALES_ASSET)
    sales_rel = _generated_rel(sales_resource, "sales")
    worktree = worktree_of(project, proposal)

    def page_meta() -> dict:
        return _load_frontmatter_meta((worktree / sales_rel).read_text(encoding="utf-8"))

    def edit_selection(selection, revision: str) -> str:
        meta = page_meta()
        if selection is None:
            meta["ariadne_profile"]["native"].pop("observed_value_columns", None)
        else:
            meta["ariadne_profile"]["native"]["observed_value_columns"] = selection
        dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        _f, b = _page_split((worktree / sales_rel).read_text(encoding="utf-8"))
        return api.edit_pages_batch(
            proposal, revision, [{"path": sales_rel, "content": f"---\n{dumped}\n---{b}"}]
        )["revision"]

    first = api.refresh_schema(proposal, started["candidate_revision"], [SALES_ASSET])
    revision = edit_selection({"region": "VARCHAR"}, first["revision"])
    observed = api.refresh_schema(proposal, revision, [SALES_ASSET])
    assert observed["changed"] is True
    evidence = page_meta()["ariadne_profile"]["native"]["ariadne"]["observations"][
        "value_evidence"
    ]
    assert evidence["region"] == {
        "state": "observed",
        "top_values": [
            {"value": "EMEA", "count": 2},
            {"value": "AMER", "count": 1},
        ],
    }  # from the authored literals, deterministic count-desc order

    # the column's TYPE changes: the old binding loses usable values with the
    # visible reason, the human-owned selection stays for review
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, 1), (2, 1), (3, 2)],
        ["order_id", "region"],
    )
    revision = observed["revision"]
    changed_type = api.refresh_schema(proposal, revision, [SALES_ASSET])
    assert changed_type["changed"] is True
    meta = page_meta()
    assert meta["ariadne_profile"]["native"]["observed_value_columns"] == {"region": "VARCHAR"}
    evidence = meta["ariadne_profile"]["native"]["ariadne"]["observations"]["value_evidence"]
    assert evidence["region"] == {"state": "unavailable", "reason": "type_changed"}
    # the reviewable change record is the refresh's STRUCTURED disclosure
    # (native schema facts move with the source; the body stays curated)
    sales_page = next(p for p in changed_type["pages"] if p["resource"] == sales_resource)
    assert sales_page["changes"]["type_changed"] == [
        {"column": "region", "from": "VARCHAR", "to": "INTEGER"}
    ]
    schema_rows = {
        row["column"]: row
        for row in meta["ariadne_profile"]["native"]["ariadne"]["schema"]
    }
    assert schema_rows["region"]["type"] == "INTEGER"  # the current fact moved

    # repeating the refresh stays unavailable (the old binding is never erased)
    repeat = api.refresh_schema(proposal, changed_type["revision"], [SALES_ASSET])
    evidence = page_meta()["ariadne_profile"]["native"]["ariadne"]["observations"][
        "value_evidence"
    ]
    assert evidence["region"] == {"state": "unavailable", "reason": "type_changed"}
    assert repeat["revision"] != changed_type["revision"] or repeat["changed"] is False
    revision = repeat["revision"]

    # explicit rebinding restores exact INTEGER evidence (1:2, 2:1 by literals)
    revision = edit_selection({"region": "INTEGER"}, revision)
    rebound = api.refresh_schema(proposal, revision, [SALES_ASSET])
    evidence = page_meta()["ariadne_profile"]["native"]["ariadne"]["observations"][
        "value_evidence"
    ]
    assert evidence["region"] == {
        "state": "observed",
        "top_values": [
            {"value": 1, "count": 2},
            {"value": 2, "count": 1},
        ],
    }

    # deselection removes ACTIVE evidence; the current core facts survive
    revision = edit_selection(None, rebound["revision"])
    deselected = api.refresh_schema(proposal, revision, [SALES_ASSET])
    meta = page_meta()
    native = meta["ariadne_profile"]["native"]
    assert "observed_value_columns" not in native
    assert "value_evidence" not in native["ariadne"]["observations"]
    schema_rows = {row["column"]: row for row in native["ariadne"]["schema"]}
    assert schema_rows["region"]["type"] == "INTEGER"  # the fact history persists
    assert deselected["changed"] is True


def test_cli_refresh_schema_roundtrip_matches_core_and_noops(tmp_path, capsys):
    """C6 fix R6/C4 (native recovery of the deleted CLI roundtrip, issue #41
    [6]): the local ``ariadne-authoring refresh-schema`` surface returns the
    same JSON envelope as the core operation — generated page identities and
    schema-change flags — and the second identical call reports the no-op."""
    project = _evolution_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    request = tmp_path / "assets.json"
    request.write_text(json.dumps([SALES_ASSET]), encoding="utf-8")

    from ariadne.authoring_cli import main as authoring_cli

    capsys.readouterr()
    code = authoring_cli(
        [
            "refresh-schema",
            "--project",
            str(project),
            "--proposal",
            started["proposal"],
            "--expected-revision",
            started["candidate_revision"],
            "--file",
            str(request),
        ]
    )
    assert code == 0
    first = json.loads(capsys.readouterr().out)
    core = api.refresh_schema(
        started["proposal"], started["candidate_revision"], [SALES_ASSET]
    )
    assert first["revision"] == core["revision"]
    assert {(p["resource"], p["kind"]) for p in first["pages"]} == {
        (p["resource"], p["kind"]) for p in core["pages"]
    }
    sales_entry = next(p for p in first["pages"] if p["kind"] == "table")
    assert sales_entry["changes"] == {
        "added": ["order_id", "amount"],
        "removed": [],
        "type_changed": [],
    }

    capsys.readouterr()
    code = authoring_cli(
        [
            "refresh-schema",
            "--project",
            str(project),
            "--proposal",
            started["proposal"],
            "--expected-revision",
            first["revision"],
            "--file",
            str(request),
        ]
    )
    assert code == 0
    second = json.loads(capsys.readouterr().out)
    assert second["changed"] is False  # the identical retry is the no-op
    assert second["revision"] == first["revision"]


def test_generated_body_sections_cannot_be_forged_or_dropped(tmp_path):
    """C6 fix R6/C6 (native recovery of the deleted body-forgery test,
    issue #41/K1): the core-owned BODY sections of an inherited native
    generated table page (Schema, Observations, Schema history) are system
    facts — an edit that changes or drops them refuses, while authored edits
    outside the core-owned sections stay accepted."""
    from ariadne.author import _load_frontmatter_meta

    project = _evolution_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    first = api.refresh_schema(proposal, started["candidate_revision"], [SALES_ASSET])
    sales_resource = _table_resource_of(SALES_ASSET)
    sales_rel = _generated_rel(sales_resource, "sales")
    worktree = worktree_of(project, proposal)
    original = (worktree / sales_rel).read_text(encoding="utf-8")
    front, body = _page_split(original)

    # a CHANGED core-owned body section refuses at the public batch seam
    forged_body = body.replace("| `order_id` | BIGINT |", "| `order_id` | INTEGER |")
    assert forged_body != body
    with pytest.raises(ValueError, match="core-generated section"):
        api.edit_pages_batch(
            proposal, first["revision"], [{"path": sales_rel, "content": front + forged_body}]
        )
    # DROPPING the section is the same forgery, never a bypass
    dropped = body.split("## Schema", 1)[0] + body.split("## Observations", 1)[-1]
    with pytest.raises(ValueError, match="core-generated section"):
        api.edit_pages_batch(
            proposal, first["revision"], [{"path": sales_rel, "content": front + dropped}]
        )
    # authored edits OUTSIDE the core-owned sections stay accepted
    authored = api.edit_pages_batch(
        proposal,
        first["revision"],
        [
            {
                "path": sales_rel,
                "content": front + body.replace(
                    "Summary: unknown — not yet authored.",
                    "Summary: one row per sale.",
                ),
            }
        ],
    )
    assert authored["changed"] is True
    meta = _load_frontmatter_meta((worktree / sales_rel).read_text(encoding="utf-8"))
    assert meta["ariadne_profile"]["native"]["ariadne"]["schema"]  # facts untouched


def test_selected_column_evidence_family_states(tmp_path):
    """C6 fix R6/C7a (native recovery of the deleted parametrized evidence
    family, spec0024 §6 AC3 — representative members): each selected column
    produces exactly its representation-driven outcome — observed for a
    supported VARCHAR binding, ``unsupported_representation`` for a type the
    v1 contract cannot publish, ``column_missing`` for a selection naming an
    absent column; ONLY selected columns appear in value_evidence."""
    from ariadne.author import _load_frontmatter_meta

    project = _evolution_project(tmp_path)
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, "EMEA"), (2, "AMER")],
        ["order_id", "region"],
    )
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    first = api.refresh_schema(proposal, started["candidate_revision"], [SALES_ASSET])
    sales_resource = _table_resource_of(SALES_ASSET)
    sales_rel = _generated_rel(sales_resource, "sales")
    worktree = worktree_of(project, proposal)

    def refresh_with_selection(selection: dict) -> dict:
        text = (worktree / sales_rel).read_text(encoding="utf-8")
        meta = _load_frontmatter_meta(text)
        meta["ariadne_profile"]["native"]["observed_value_columns"] = selection
        dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        _f, b = _page_split(text)
        revision = api.edit_pages_batch(
            proposal, first["revision"], [{"path": sales_rel, "content": f"---\n{dumped}\n---{b}"}]
        )["revision"]
        api.refresh_schema(proposal, revision, [SALES_ASSET])
        return _load_frontmatter_meta((worktree / sales_rel).read_text(encoding="utf-8"))[
            "ariadne_profile"
        ]["native"]["ariadne"]["observations"]["value_evidence"]

    assert refresh_with_selection({"region": "VARCHAR"})["region"] == {
        "state": "observed",
        "top_values": [
            {"value": "AMER", "count": 1},
            {"value": "EMEA", "count": 1},
        ],
    }  # alphabetical value order at equal counts (deterministic evidence order)
    assert refresh_with_selection({"order_id": "VARCHAR"})["order_id"] == {
        "state": "unavailable",
        "reason": "unsupported_representation",
    }  # BIGINT has no supported v1 literal representation as declared VARCHAR
    evidence = refresh_with_selection({"absent_column": "VARCHAR"})
    assert evidence["absent_column"] == {"state": "unavailable", "reason": "column_missing"}
    assert set(evidence) == {"absent_column"}  # only selected columns appear


def test_value_evidence_bounds_fallback_and_atomic_refusals(tmp_path):
    """C6 fix R6/C7c (native recovery of the deleted spec0024 §3/§6 AC5
    scenarios): a successful mapping that exceeds the 8192-byte compact-JSON
    bound falls back to unavailable/``too_large`` for EVERY selected column —
    never a clipped or partial literal; a status-only mapping that still
    exceeds it refuses the refresh ATOMICALLY (no revision/page move); a
    regenerated page that would exceed the 2,097,152-byte artifact bound
    refuses atomically the same way. Bounds are literal arithmetic, not
    implementation output."""
    from ariadne.author import _load_frontmatter_meta

    project = _evolution_project(tmp_path)
    long_a, long_b = "A" * 4500, "B" * 4500
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, long_a, "x"), (2, long_b, "y"), (3, long_a, "x")],
        ["order_id", "payload", "flag"],
    )
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    sales_resource = _table_resource_of(SALES_ASSET)
    sales_rel = _generated_rel(sales_resource, "sales")
    worktree = worktree_of(project, proposal)
    first = api.refresh_schema(proposal, started["candidate_revision"], [SALES_ASSET])

    def refresh_with_selection(selection: dict, revision: str):
        text = (worktree / sales_rel).read_text(encoding="utf-8")
        meta = _load_frontmatter_meta(text)
        meta["ariadne_profile"]["native"]["observed_value_columns"] = selection
        dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        _f, b = _page_split(text)
        return api.edit_pages_batch(
            proposal, revision, [{"path": sales_rel, "content": f"---\n{dumped}\n---{b}"}]
        )["revision"]

    # (a) fallback half: the two long exact strings (2x4500 + JSON structure)
    # exceed the 8192-byte bound — every selected column falls back, no clip
    revision = refresh_with_selection({"payload": "VARCHAR", "flag": "VARCHAR"}, first["revision"])
    refreshed = api.refresh_schema(proposal, revision, [SALES_ASSET])
    evidence = _load_frontmatter_meta((worktree / sales_rel).read_text(encoding="utf-8"))[
        "ariadne_profile"
    ]["native"]["ariadne"]["observations"]["value_evidence"]
    assert evidence == {
        "payload": {"state": "unavailable", "reason": "too_large"},
        "flag": {"state": "unavailable", "reason": "too_large"},
    }
    assert "A" * 4500 not in (worktree / sales_rel).read_text(encoding="utf-8")

    # (b) refusal half: 200 selected columns make even the status-only
    # mapping ~10.6 KiB > 8 KiB — the refresh refuses, nothing moves
    wide = [(f"c{i:03d}", "a" if i % 2 == 0 else "b") for i in range(200)]
    write_parquet(
        project / "data" / "sales" / "orders.parquet",
        [(1, *(v for _n, v in wide)), (2, *("b" if v == "a" else "a" for _n, v in wide))],
        ["order_id", *(n for n, _v in wide)],
    )
    wide_refresh = api.refresh_schema(proposal, refreshed["revision"], [SALES_ASSET])
    assert wide_refresh["changed"] is True  # the schema itself refreshed…
    revision = refresh_with_selection(
        {name: "VARCHAR" for name in [n for n, _v in wide]}, wide_refresh["revision"]
    )
    before = (worktree / sales_rel).read_bytes()
    with pytest.raises(ValueError, match="bound"):
        api.refresh_schema(proposal, revision, [SALES_ASSET])
    assert (worktree / sales_rel).read_bytes() == before  # atomic: nothing written
    assert proposals._load_record(project, proposal)["candidate_revision"] == revision

    # (c) artifact-bound atomicity: an authored bulk just under the
    # 2,097,152-byte artifact bound plus regenerated facts exceeds it — the
    # refresh refuses atomically, no page/revision moves
    text = (worktree / sales_rel).read_text(encoding="utf-8")
    meta = _load_frontmatter_meta(text)
    meta["ariadne_profile"]["native"]["observed_value_columns"] = {"flag": "VARCHAR"}
    meta["description"] = "authored bulk " + "y" * 2_096_800
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    _f, b = _page_split(text)
    revision = api.edit_pages_batch(
        proposal, revision, [{"path": sales_rel, "content": f"---\n{dumped}\n---{b}"}]
    )["revision"]
    before = (worktree / sales_rel).read_bytes()
    with pytest.raises(ValueError):
        api.refresh_schema(proposal, revision, [SALES_ASSET])
    assert (worktree / sales_rel).read_bytes() == before
    assert proposals._load_record(project, proposal)["candidate_revision"] == revision


def test_uhugeint_native_integer_values_stay_exact(tmp_path):
    """C6 fix R6/C7d (native recovery of the deleted UHUGEINT unit, spec0024
    §3/AC3): UHUGEINT belongs to the native integer family — a selected native
    catalog column publishes exact INTEGER evidence with the hand-specified
    counts 7:2, 8:1, never floats (parquet cannot carry unsigned 128-bit, so
    the fixture is a native DuckDB source)."""
    from ariadne.author import _load_frontmatter_meta
    from ariadne.sources import table_resource

    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(project / "data" / "lake.duckdb"))
    con.execute("CREATE TABLE uhuge (v UHUGEINT)")
    con.executemany("INSERT INTO uhuge VALUES (?)", [(7,), (8,), (7,)])
    con.close()
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: lake\n    type: duckdb\n    path: data/lake.duckdb\n",
        encoding="utf-8",
    )
    (project / "data" / "seed_notes.md").write_text("# Notes\n", encoding="utf-8")
    kb = project / "knowledge"
    (kb / "tables").mkdir(parents=True, exist_ok=True)
    (kb / "datasets").mkdir(parents=True, exist_ok=True)
    (kb / "lumio.yaml").write_text(
        "version: 2\n"
        'mode: "categorized"\n'
        "categories:\n  - name: tables\n"
        "  - name: datasets\n"
        "ontology:\n"
        "  entity_types:\n"
        "    table: {}\n"
        "    dataset: {}\n"
        "  predicates: {}\n"
        "  redirects: {}\n",
        encoding="utf-8",
    )
    (kb / ".lumio-authoring.yaml").write_text(
        'version: 1\nnamespace: "urn:uuid:uhugeint-fixture"\nsources: {}\nbindings: {}\n',
        encoding="utf-8",
    )
    (project / "context_integration.yaml").write_text(
        "version: 1\n"
        "mode: integrated\n"
        "subtree: knowledge\n"
        "namespace: urn:uuid:uhugeint-fixture\n"
        "profile: ariadne-context/1\n"
        "support_revision: 2\n"
        "policy_bindings:\n"
        "  version: 1\n"
        "  bindings: []\n",
        encoding="utf-8",
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md", "knowledge",
            "context_integration.yaml")
    run_git(project, "commit", "-q", "-m", "human: native duckdb lake")

    asset = {"source": "lake", "catalog": None, "schema": "main", "table": "uhuge"}
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    proposal = started["proposal"]
    first = api.refresh_schema(proposal, started["candidate_revision"], [asset])
    resource = table_resource("lake", None, "main", "uhuge")
    rel = _generated_rel(resource, "lake")
    worktree = worktree_of(project, proposal)

    text = (worktree / rel).read_text(encoding="utf-8")
    meta = _load_frontmatter_meta(text)
    meta["ariadne_profile"]["native"]["observed_value_columns"] = {"v": "UHUGEINT"}
    dumped = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    _f, b = _page_split(text)
    revision = api.edit_pages_batch(
        proposal, first["revision"], [{"path": rel, "content": f"---\n{dumped}\n---{b}"}]
    )["revision"]
    api.refresh_schema(proposal, revision, [asset])
    evidence = _load_frontmatter_meta((worktree / rel).read_text(encoding="utf-8"))[
        "ariadne_profile"
    ]["native"]["ariadne"]["observations"]["value_evidence"]
    assert evidence["v"] == {
        "state": "observed",
        "top_values": [
            {"value": 7, "count": 2},
            {"value": 8, "count": 1},
        ],
    }  # exact integers from the hand-inserted 7, 8, 7 — never floats

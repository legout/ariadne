"""Explicit legacy-artifact import into the Git authoring workflow (issue #39
/ G7; spec 2026-10-02-0009 §7 + AC9, plan §2's ``migration.py`` row).

The human-only import copies a legacy project's selected artifacts — the
served OSI models/graph, OKF pages, Seed Notes and ``ariadne.yaml`` — into a
FRESH UNADMITTED Git proposal, or into the human-created initial artifact
revision when the project has none yet, through the SAME layer edit
interfaces the agent surface uses (:mod:`ariadne.authoring_semantic` /
:mod:`ariadne.authoring_context` resolvers + ``edit_proposal``). Pending
legacy work keeps its own stores untouched: ``staging/`` (an outstanding
harness-led bundle, a standalone ingest proposal, an ad-hoc proposal, an
Answer Example) is preserved byte-for-byte, and citations ride along as
content, byte-identical. Existing frontmatter claims (``verified`` history,
``status: stable``) stay CONTENT — the G2 forged-claims gate compares against
the imported base, so importing them as base content preserves them
byte-for-byte without granting new authority.

Import is NEVER admission (AC9): a Git commit of existing files alone is not
human review, an old legacy validation marker (``bundle-state.json`` status
``validated``) is not Git validation evidence, and frontmatter trust claims
are not sign-off. The first admitted snapshot is established only through the
normal steps — operator source approval, ``validate`` (finalize + full check
stack), ``review`` and human ``ariadne-admit --confirm``.

Real temporary Git repositories (repo-local identity only), real parquet
sources, no network, no provider. The public surface is the HUMAN command
adapter ``ariadne-authoring import-legacy --project DIR --from-root ROOT`` —
never an MCP or native Agent tool.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import admission, author, proposals  # noqa: E402
from ariadne.admission import main as admit_cli  # noqa: E402
from ariadne.author import author_to_proposal  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import build_parser  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from ariadne.authoring_sources import candidate_sources  # noqa: E402
from ariadne.init import main as init_cli  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    METRIC_PAGE,
    POLICY_PAGE,
    REFERENCE_PAGE,
    SKILLS_PAGE,
    TABLES_PAGE,
    complete_bundle_project,
)


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config: point them at
    /dev/null so only the repo-local identity seeded below exists."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def run_git(cwd: Path, *argv: str) -> str:
    """Real git for test-side scaffolding (the seam under test never sees it)."""
    proc = subprocess.run(
        ["git", *argv], cwd=cwd, capture_output=True, text=True, check=False
    )
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


# The legacy SERVED bundle: the pages ariadne-promote produced — ``status:
# stable`` plus ``verified`` history (the promotion-stamped trust claims that
# must survive the import as content, byte-for-byte) and the mechanically
# enriched metric page (governed_by/dimensions/grain, ADR-0007).
_BY = "human:tester"
_AT = "2026-10-01T09:00:00+00:00"

SERVED_MODEL_YML = """\
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

SERVED_TABLES_PAGE = (
    "---\n"
    "type: table\n"
    "title: Events\n"
    "description: One row per event.\n"
    "tags: [table]\n"
    "status: stable\n"
    "verified:\n"
    f"  - by: {_BY}\n"
    f"    at: {_AT}\n"
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

SERVED_REFERENCE_PAGE = (
    "---\n"
    "type: reference\n"
    "title: events identity\n"
    "description: One reference page.\n"
    "tags: [reference]\n"
    "status: stable\n"
    "verified:\n"
    f"  - by: {_BY}\n"
    f"    at: {_AT}\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# events identity\n"
)

SERVED_POLICY_PAGE = (
    "---\n"
    "type: policy\n"
    "status: stable\n"
    "title: All events count\n"
    "description: The counting rule.\n"
    "tags: [policy]\n"
    "verified:\n"
    f"  - by: {_BY}\n"
    f"    at: {_AT}\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# All events count\n\n"
    "The rule body.\n"
)

SERVED_METRIC_PAGE = (
    "---\n"
    "type: metric\n"
    "status: stable\n"
    "title: event_count\n"
    "description: Count of all events.\n"
    "tags: [metric]\n"
    "verified:\n"
    f"  - by: {_BY}\n"
    f"    at: {_AT}\n"
    "governed_by: semantic_layer events::event_count\n"
    "dimensions: [label]\n"
    "grain:\n"
    "  primary_key: [id]\n"
    "  cardinality_enforcement: STRICT_1_TO_1\n"
    "sources:\n"
    "  - id: all-events-count\n"
    "    resource: policies/all-events-count.md\n"
    "    title: All events count\n"
    "---\n\n"
    "# event_count\n"
)

SERVED_SKILLS_PAGE = (
    "---\n"
    "type: skill\n"
    "status: stable\n"
    "title: run the demo\n"
    "description: One skill page.\n"
    "tags: [skill]\n"
    "verified:\n"
    f"  - by: {_BY}\n"
    f"    at: {_AT}\n"
    "sources:\n"
    "  - id: seed-notes\n"
    "    resource: data/seed_notes.md\n"
    "    title: Seed notes\n"
    "---\n\n"
    "# run the demo\n"
)

# System-generated served bookkeeping (promotion output): NEVER imported — the
# Git finalize pass owns index trees, log.md and computations pages.
SERVED_ROOT_INDEX = "# Context bundle\n\n- [Policies](policies/index.md)\n"
SERVED_SECTION_INDEX = "# Policy\n\n- [All events count](all-events-count.md)\n"
SERVED_LOG = "# Bundle log\n\n## 2026-10-01\n\n**Creation**\n\n- promoted by human:tester\n"
SERVED_COMPUTATION = (
    "---\n"
    "type: computation\n"
    "title: sanctioned SQL — events::event_count\n"
    "description: Sanctioned computation: SQL, runtime, attester.\n"
    "tags: [computation]\n"
    "status: stable\n"
    "governed_by: semantic_layer events::event_count\n"
    "runtime: duckdb\n"
    "attester: tests/test_evals.py\n"
    "sources:\n"
    "  - id: model-events\n"
    "    resource: ../../semantic_layer/models/events.yml\n"
    "    title: events OSI model\n"
    "---\n\n"
    "# Sanctioned computation\n\n```sql\nCOUNT(*)\n```\n"
)

SERVED_PAGES = {
    "context_layer/tables/events.md": SERVED_TABLES_PAGE,
    "context_layer/references/joins/events--events.md": SERVED_REFERENCE_PAGE,
    "context_layer/policies/all-events-count.md": SERVED_POLICY_PAGE,
    "context_layer/metrics/event_count.md": SERVED_METRIC_PAGE,
    "context_layer/skills/run-the-demo.md": SERVED_SKILLS_PAGE,
}

SEED_NOTES = "# Seed notes\n\nAll events count.\n"
LEGACY_REGISTRY = (
    "sources:\n"
    "  - name: events\n"
    "    type: parquet\n"
    "    path: data/events.parquet\n"
)

# The outstanding LEGACY pending work that must survive byte-for-byte: a
# harness-led bundle proposal (its bundle-state.json even records the OLD
# validation marker ``status: validated``), a standalone ingest proposal, an
# ad-hoc metric proposal and an Answer Example — each in its own store.
LEGACY_STAGING = {
    "authoring/bundle/data/seed_notes.md": "# Seed notes\n\nVersion 2, pending.\n",
    "authoring/bundle/semantic_layer/models/events.yml": "version: 0.2.0.dev0\n",
    "authoring/bundle/citations.json": '{"documents": []}\n',
    "authoring/bundle-state.json": json.dumps(
        {
            "submission_digest": "0" * 64,
            "digest": "1" * 64,
            "revision": 1,
            "attempts": 1,
            "status": "validated",
            "errors": [],
            "provenance": {"mode": "harness-led"},
        }
    ),
    "context_layer/policies/pending-policy.md": (
        "---\ntype: policy\nstatus: draft\ntitle: Pending\n---\n\n# Pending\n"
    ),
    "semantic_layer/models/adhoc/adhoc-orders.yml": "version: 0.2.0.dev0\n",
    "context_layer/metrics/adhoc-orders.md": "---\ntype: metric\nstatus: draft\n---\n",
    "answer_examples/gross-margin-by-region.md": (
        "---\ntype: answer_example\nstatus: draft\n---\n\n# Gross margin by region\n"
    ),
}


def legacy_project(tmp_path: Path) -> Path:
    """One real legacy (staging-gate) project adopting Git: ariadne-init's
    DEFAULT scaffold (whose .gitignore excludes the served OSI/OKF layers) over
    an existing served bundle, with every kind of outstanding legacy proposal
    in staging/ — plus a git init and repo-local identity, no commits yet."""
    root = tmp_path / "legacy"
    root.mkdir(parents=True)
    write_parquet(root / "data" / "events.parquet", [(1, "a"), (2, "b")], ["id", "label"])
    (root / "ariadne.yaml").write_text(LEGACY_REGISTRY, encoding="utf-8")
    (root / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (root / "semantic_layer" / "models").mkdir(parents=True)
    (root / "semantic_layer" / "models" / "events.yml").write_text(
        SERVED_MODEL_YML, encoding="utf-8"
    )
    for rel, content in SERVED_PAGES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # the promotion gate's generated output: never import candidates
    (root / "context_layer" / "index.md").write_text(SERVED_ROOT_INDEX, encoding="utf-8")
    (root / "context_layer" / "policies" / "index.md").write_text(
        SERVED_SECTION_INDEX, encoding="utf-8"
    )
    (root / "context_layer" / "log.md").write_text(SERVED_LOG, encoding="utf-8")
    computation = root / "context_layer" / "computations" / "event_count.md"
    computation.parent.mkdir(parents=True, exist_ok=True)
    computation.write_text(SERVED_COMPUTATION, encoding="utf-8")
    for rel, content in LEGACY_STAGING.items():
        path = root / "staging" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # the DEFAULT scaffold: .gitignore excludes context_layer/semantic_layer/
    # (the "existing ignore rules exclude OSI/OKF" migration case) and every
    # existing file is reported skipped, never overwritten.
    assert init_cli([str(root)]) == 0
    run_git(root, "init", "-q")
    run_git(root, "config", "user.name", "Ariadne Tests")
    run_git(root, "config", "user.email", "tests@ariadne.local")
    return root


def staging_tree(root: Path) -> dict[str, bytes]:
    """Every file under the legacy staging area, byte-for-byte."""
    return {
        path.relative_to(root / "staging").as_posix(): path.read_bytes()
        for path in sorted((root / "staging").rglob("*"))
        if path.is_file()
    }


def import_via_cli(project: Path, from_root: Path, capsys) -> dict:
    """The HUMAN command adapter surface: one JSON envelope on stdout (any
    earlier fixture output is flushed away first)."""
    capsys.readouterr()  # flush fixture noise (the scaffold's own report)
    rc = authoring_cli(
        ["import-legacy", "--project", str(project), "--from-root", str(from_root)]
    )
    assert rc == 0
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------- [1] the red seam


def test_legacy_import_preserves_pending_evidence_and_requires_review_before_admission(
    tmp_path, capsys
):
    """Issue #39 [1]/[3], AC9: the human import copies the legacy served
    bundle into an UNADMITTED Git proposal — tracked despite the scaffold's
    ignore rules, byte-for-byte including promotion-stamped trust claims and
    citations — while the outstanding legacy proposals, state and documents
    survive untouched; and neither the legacy ``validated`` marker, nor the
    imported frontmatter, nor the newly created commits are ever treated as
    review or admission."""
    project = legacy_project(tmp_path)
    before_staging = staging_tree(project)

    imported = import_via_cli(project, project, capsys)

    # the envelope names the human steps and never claims admission
    assert imported["admitted"] is False
    assert imported["mode"] == "initial-artifact-revision"
    steps = " ".join(imported["admission_required"])
    assert "ariadne-authoring approve-sources" in steps
    assert "ariadne-authoring validate" in steps
    assert "ariadne-authoring review" in steps
    assert "ariadne-admit" in steps and "--confirm" in steps
    proposal = imported["proposal"]

    # the outstanding legacy work survived byte-for-byte, in its own stores
    assert staging_tree(project) == before_staging

    # the selected legacy artifacts ARE tracked — despite .gitignore's
    # context_layer//semantic_layer/ rules (the G2 -f literal-pathspec seam)
    expected = {
        "ariadne.yaml",
        "data/seed_notes.md",
        "semantic_layer/models/events.yml",
        *SERVED_PAGES,
    }
    tracked = set(run_git(project, "ls-files").split())
    assert expected <= tracked
    # generated bookkeeping and pending stores are never committed
    assert not any(
        path.endswith(("index.md", "log.md")) or "/computations/" in path
        for path in tracked
    )
    assert not any(path.startswith(("staging/", ".ariadne/")) for path in tracked)
    assert "data/events.parquet" not in tracked  # inputs are never artifacts

    # byte-for-byte: the candidate carries the exact served bytes, including
    # the promotion-stamped verified/status claims (imported as base content,
    # never as model edits claiming new authority) and the exact citations
    blobs = {rel: blob for rel, blob in proposals.scope_blobs(project, imported["revision"])}
    for rel in expected:
        assert blobs[rel] == (project / rel).read_bytes(), rel
    policy = blobs["context_layer/policies/all-events-count.md"].decode("utf-8")
    assert "verified:" in policy and "status: stable" in policy
    assert "data/seed_notes.md" in policy  # citations unchanged
    metric = blobs["context_layer/metrics/event_count.md"].decode("utf-8")
    assert "resource: policies/all-events-count.md" in metric

    # no human review is inferred: not from the old validation marker, not
    # from the imported frontmatter, not from the new commits
    assert admission.load_current(project) is None
    assert proposals.load_validation(project, proposal, imported["revision"]) is None
    rc = admit_cli(
        [
            "--project",
            str(project),
            "--proposal",
            proposal,
            "--revision",
            imported["revision"],
            "--reviewed-digest",
            "0" * 64,
            "--confirm",
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "review digest mismatch" in err
    assert admission.load_current(project) is None  # nothing was served


def test_imported_base_establishes_the_first_snapshot_through_the_normal_human_steps(
    tmp_path, capsys
):
    """Issue #39 [3]: after the import, the NORMAL steps — operator source
    approval of the exact resolved identity, validate (finalize + full check
    stack bound to the exact final commit), review and human ``ariadne-admit
    --confirm`` — establish the first admitted snapshot; the imported legacy
    claims stay content (never restamped as Git review) and the pending legacy
    staging survives the whole journey byte-for-byte."""
    project = legacy_project(tmp_path)
    before_staging = staging_tree(project)
    imported = import_via_cli(project, project, capsys)
    api = AuthoringProject(project)
    proposal = imported["proposal"]

    # operator approval of the candidate's exact resolved identity (G3 seam)
    resolved, digest = candidate_sources(project, imported["revision"])
    assert resolved is not None
    api.approve_sources(proposal, imported["revision"], digest)

    # validate finalizes the deterministic artifacts and validates the EXACT
    # final commit (computations/index are regenerated, not the imported ones)
    validated = api.validate_proposal(proposal, imported["revision"])
    assert validated["ok"] is True, validated["errors"]
    assert validated["revision"] != imported["revision"]
    files = set(validated["artifact_files"])
    assert any(path.startswith("context_layer/computations/") for path in files)
    assert "context_layer/policies/all-events-count.md" in files

    review = api.review_proposal(proposal)
    assert review["revision"] == validated["revision"]
    assert review["report"]["ok"] is True
    # the imported promotion-stamped claims survive as CONTENT: the reviewed
    # policy body still carries its legacy verified history, unrestamped
    policy = next(
        body["text"] if "text" in body else ""
        for body in review["files"]
        if body["resource"] == "context_layer/policies/all-events-count.md"
    )
    assert "verified:" in policy and "status: stable" in policy

    assert (
        admit_cli(
            [
                "--project",
                str(project),
                "--proposal",
                proposal,
                "--revision",
                review["revision"],
                "--reviewed-digest",
                review["review_digest"],
                "--confirm",
            ]
        )
        == 0
    )
    current = admission.load_current(project)
    assert current["commit"] == review["revision"]

    # the admitted snapshot serves the governed metric through the managed
    # route — and the pending legacy staging survived the whole journey
    runtime = QueryRuntime.open_project(project)
    answer = asyncio.run(runtime.get_metric("event_count"))
    assert answer["governed"] is True
    assert staging_tree(project) == before_staging


def test_import_into_an_existing_artifact_base_applies_edits_through_the_layer_seam(
    tmp_path, capsys
):
    """Issue #39 [3]/plan §2: a project that already carries an artifact
    revision gets a fresh UNADMITTED proposal whose legacy artifacts arrive
    through the SAME layer edit interfaces (typed edits, revision-checked,
    registry entries appended through the typed source-proposal seam) — never
    an automatic overwrite or admission."""
    project = complete_bundle_project(tmp_path)  # an existing Git artifact base
    legacy = tmp_path / "older"
    legacy.mkdir()
    (legacy / "data").mkdir()
    (legacy / "semantic_layer" / "models").mkdir(parents=True)
    for rel, content in {
        "data/seed_notes.md": (project / "data" / "seed_notes.md").read_text(
            encoding="utf-8"
        ),
        "context_layer/tables/events.md": TABLES_PAGE,  # identical: no-op
        "context_layer/references/joins/events--events.md": REFERENCE_PAGE,
        "context_layer/metrics/event_count.md": METRIC_PAGE,
        "context_layer/skills/run-the-demo.md": SKILLS_PAGE,
        # a genuinely revised legacy page and one NEW legacy model
        "context_layer/policies/all-events-count.md": POLICY_PAGE.replace(
            "The rule body.", "The rule body, revised by the legacy owner."
        ),
        "semantic_layer/models/labels.yml": "version: 0.2.0.dev0\n",
    }.items():
        path = legacy / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    # one NEW legacy registry entry (the base already declares events+labels)
    (legacy / "ariadne.yaml").write_text(
        "sources:\n"
        "  - name: events\n"
        "    type: parquet\n"
        "    path: data/events.parquet\n"
        "  - name: labels\n"
        "    type: parquet\n"
        "    path: data/labels.parquet\n"
        "  - name: extra\n"
        "    type: parquet\n"
        "    path: data/extra.parquet\n",
        encoding="utf-8",
    )

    imported = import_via_cli(project, legacy, capsys)
    assert imported["mode"] == "proposal-edits"
    assert imported["admitted"] is False
    assert imported["revision"] != imported["base_revision"]  # real edits landed

    changes = {entry["path"]: entry["changed"] for entry in imported["imported"]}
    assert changes["context_layer/policies/all-events-count.md"] is True
    assert changes["semantic_layer/models/labels.yml"] is True
    assert changes["context_layer/tables/events.md"] is False  # identical: no-op

    # the revised page's bytes arrive byte-for-byte through the page seam
    blobs = dict(proposals.scope_blobs(project, imported["revision"]))
    assert (
        blobs["context_layer/policies/all-events-count.md"]
        == (legacy / "context_layer" / "policies" / "all-events-count.md").read_bytes()
    )
    # the new registry entry was appended through the typed seam (inert until
    # the operator approves the new resolved identity), nothing overwritten
    registry = yaml.safe_load(blobs["ariadne.yaml"].decode("utf-8"))
    assert [entry["name"] for entry in registry["sources"]] == [
        "events",
        "labels",
        "extra",
    ]
    assert imported["registry"]["proposed"] == 1
    assert "source_digest" in imported["registry"]


def test_import_refuses_trust_claims_the_base_does_not_carry(tmp_path, capsys):
    """Issue #39 [3]/plan §2 binding: legacy pages import through the SAME
    seam, so a page claiming trust the base does not carry (a ``verified``
    entry the served history never had) is refused by the shared G2
    forged-claims gate — the human-level import grants no new authority."""
    project = complete_bundle_project(tmp_path)
    legacy = tmp_path / "older"
    legacy.mkdir()
    (legacy / "data").mkdir()
    forged = POLICY_PAGE.replace(
        "tags: [policy]\n", "tags: [policy]\nverified:\n  - by: someone\n    at: 2026-01-01\n"
    )
    (legacy / "context_layer" / "policies").mkdir(parents=True)
    (legacy / "context_layer" / "policies" / "all-events-count.md").write_text(
        forged, encoding="utf-8"
    )
    capsys.readouterr()
    rc = authoring_cli(
        ["import-legacy", "--project", str(project), "--from-root", str(legacy)]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert "system-owned trust claim" in err and "verified" in err


def test_import_is_exposed_only_through_the_human_command_adapter(tmp_path, capsys):
    """Issue #39/plan §2: ``import-legacy`` exists ONLY on the human CLI — the
    agent-facing :class:`AuthoringProject` surface (the MCP/native Agent tool
    contract) never grows an import entry point."""
    commands = build_parser()._subparsers._group_actions[0].choices  # noqa: SLF001
    assert "import-legacy" in commands
    api = AuthoringProject(tmp_path)
    assert not hasattr(api, "import_legacy")
    for name in dir(api):
        assert "import" not in name, name  # no agent-reachable import seam


def fake_complete(responses: list[str]):
    """Return (complete_fn, calls); complete_fn replays responses, last one
    repeats — the established tests/test_author.py convention."""
    calls: list[list[dict]] = []

    def complete(messages: list[dict]) -> str:
        calls.append(messages)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return complete, calls


GIT_AUTHOR_BUNDLE = json.dumps(
    {
        "files": [
            {"path": rel, "content": content} for rel, content in SERVED_PAGES.items()
        ]
        + [{"path": "semantic_layer/models/events.yml", "content": SERVED_MODEL_YML}]
    }
)


def test_author_git_mode_drafts_into_an_unadmitted_proposal(tmp_path, capsys):
    """Issue #39 [4]: ``ariadne-author --git`` keeps the SAME three-round
    author loop (a broken first round feeds back, the second drafts the
    bundle) but routes its output into the new proposal workflow — a fresh
    UNADMITTED Git proposal — instead of the legacy staging dir, which is
    never written."""
    project = tmp_path / "gitproj"
    project.mkdir()
    write_parquet(project / "data" / "events.parquet", [(1, "a"), (2, "b")], ["id", "label"])
    (project / "ariadne.yaml").write_text(LEGACY_REGISTRY, encoding="utf-8")
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")

    complete, calls = fake_complete(["not json at all", GIT_AUTHOR_BUNDLE])
    staged, envelope = author_to_proposal(
        str(project / "data" / "seed_notes.md"),
        project=project,
        sources_path=project / "ariadne.yaml",
        complete=complete,
    )
    assert len(calls) == 2  # round 1 fed the parse error back, round 2 drafted
    assert envelope["review_required"] is False
    assert envelope["mode"] == "initial-artifact-revision"
    assert envelope["admitted"] is False
    assert not (project / "staging").exists()  # the legacy staging dir untouched

    # the drafted bundle became the proposal's base content and validates
    api = AuthoringProject(project)
    resolved, digest = candidate_sources(project, envelope["revision"])
    assert resolved is not None
    api.approve_sources(envelope["proposal"], envelope["revision"], digest)
    validated = api.validate_proposal(envelope["proposal"], envelope["revision"])
    assert validated["ok"] is True, validated["errors"]


# A Git-authoring draft bundle over an EXISTING artifact base: the base's own
# draft-shaped pages with one real content change (the policy body) — no
# promotion-stamped or lifecycle claims anywhere, so once Git-mode drafting
# leaves lifecycle stamping to the deterministic finalize pass the import is
# pure content edits through the shared edit seam.
GIT_DRAFT_OVER_BASE = json.dumps(
    {
        "files": [
            {"path": rel, "content": content}
            for rel, content in {
                "context_layer/tables/events.md": TABLES_PAGE,
                "context_layer/references/joins/events--events.md": REFERENCE_PAGE,
                "context_layer/policies/all-events-count.md": POLICY_PAGE.replace(
                    "The rule body.", "The rule body, revised."
                ),
                "context_layer/metrics/event_count.md": METRIC_PAGE,
                "context_layer/skills/run-the-demo.md": SKILLS_PAGE,
                "semantic_layer/models/events.yml": SERVED_MODEL_YML,
            }.items()
        ]
    }
)


def test_author_git_mode_after_an_existing_artifact_base(tmp_path):
    """G7 fix pass F1: an artifact base already exists (an ordinary start —
    the human-created initial artifact revision), and ``ariadne-author --git``
    must still succeed: Git-mode drafts carry NO wall-clock lifecycle stamps
    (generated/verified/stale_after), so the shared forged-claims gate sees
    unstamped draft edits, never fresh stamps the base cannot match. The
    imported proposal stays fully editable and validates end to end."""
    project = complete_bundle_project(tmp_path)
    complete, _ = fake_complete([GIT_DRAFT_OVER_BASE])
    staged, envelope = author_to_proposal(
        str(project / "data" / "seed_notes.md"),
        project=project,
        sources_path=project / "ariadne.yaml",
        complete=complete,
    )
    assert envelope["mode"] == "proposal-edits"
    assert envelope["review_required"] is False
    changed = [item["path"] for item in envelope["imported"] if item["changed"]]
    assert "context_layer/policies/all-events-count.md" in changed  # a real edit

    # editable artifacts: the imported proposal validates end to end
    api = AuthoringProject(project)
    resolved, digest = candidate_sources(project, envelope["revision"])
    assert resolved is not None
    api.approve_sources(envelope["proposal"], envelope["revision"], digest)
    validated = api.validate_proposal(envelope["proposal"], envelope["revision"])
    assert validated["ok"] is True, validated["errors"]


def test_exhausted_git_author_run_preserves_review_evidence_durably(tmp_path):
    """G7 fix pass F2: three unparseable responses exhaust the loop with only
    a root REVIEW_NEEDED.md — outside the import's artifact selection, so the
    import fails and the temp dir's deletion would otherwise destroy the ONLY
    evidence of the run. Durable review-needed evidence must survive in the
    project's staging area under a clearly named location, and the failure
    must name that location."""
    project = complete_bundle_project(tmp_path)
    complete, _ = fake_complete(["no json", "still no json", "nope"])
    with pytest.raises(ValueError, match="author-review-needed"):
        author_to_proposal(
            str(project / "data" / "seed_notes.md"),
            project=project,
            sources_path=project / "ariadne.yaml",
            complete=complete,
        )
    evidence = sorted(
        (project / "staging" / "author-review-needed").glob("*/REVIEW_NEEDED.md")
    )
    assert evidence, "the exhausted run's evidence must exist after the failed import"
    text = evidence[-1].read_text(encoding="utf-8")
    assert "review_needed" in text and "JSON file contract" in text


def test_git_author_envelope_names_preserved_review_evidence(tmp_path):
    """G7 fix pass F2 (importable drafts): when an exhausted run DOES leave
    importable drafts, the import succeeds and the envelope names the durable
    review-needed location alongside ``review_required``."""
    from types import SimpleNamespace

    project = complete_bundle_project(tmp_path)
    complete, _ = fake_complete([GIT_DRAFT_OVER_BASE])
    staged, envelope = author_to_proposal(
        str(project / "data" / "seed_notes.md"),
        project=project,
        sources_path=project / "ariadne.yaml",
        complete=complete,
        validate_fn=lambda staged: SimpleNamespace(ok=False, errors=["forced failure"]),
    )
    assert envelope["review_required"] is True
    evidence = Path(envelope["review_evidence"])
    # the partial drafts carry their review_needed marks durably (no root
    # REVIEW_NEEDED.md in this shape: the marked pages ARE the evidence)
    marked = evidence / "context_layer" / "policies" / "all-events-count.md"
    assert marked.is_file() and "review_needed" in marked.read_text(encoding="utf-8")


def test_git_author_cli_names_the_preserved_review_evidence_location(
    tmp_path, monkeypatch, capsys
):
    """G7 fix pass F2 (CLI surface): ``ariadne-author --git`` with an
    exhausted run reports the failure cleanly and names the durable
    review-needed location in its output instead of a bare traceback."""
    project = complete_bundle_project(tmp_path)
    monkeypatch.setattr(author, "_default_complete", lambda messages: "not json")
    rc = author.main(
        [
            "--git",
            "--project",
            str(project),
            "--sources",
            str(project / "ariadne.yaml"),
            "--notes",
            str(project / "data" / "seed_notes.md"),
        ]
    )
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error: no legacy artifacts found")  # the truthful cause
    assert "author-review-needed" in err  # the durable location is named
    assert sorted(
        (project / "staging" / "author-review-needed").glob("*/REVIEW_NEEDED.md")
    ), "durable evidence exists after the failed run"


def test_how_to_document_maps_legacy_routes_to_the_new_workflow():
    """Issue #39 [5]: docs/how-to/git-authoring.md carries the exact legacy →
    new mappings (runtime constructors, submit/repair/review, promotion vs
    admission, the unchanged routes, split/combined MCP startup)."""
    doc = (REPO_ROOT / "docs" / "how-to" / "git-authoring.md").read_text(encoding="utf-8")
    assert "QueryRuntime.open_project" in doc  # runtime constructors/factory
    assert "ariadne-authoring start" in doc and "ariadne-authoring edit" in doc
    assert "--expected-revision" in doc  # replaces --base-digest repair chaining
    assert "ariadne-admit" in doc  # promote full Git bundle -> human admit
    assert "ariadne-promote" in doc  # the unchanged legacy Promotion route
    assert "ariadne-ingest" in doc  # unchanged standalone ingestion
    assert "--toolset" in doc and "combined" in doc  # split vs combined startup
    assert "import-legacy" in doc  # the human import command
    assert "Answer Example" in doc or "answer example" in doc  # separate store

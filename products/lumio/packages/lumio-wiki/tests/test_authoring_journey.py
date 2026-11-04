"""Extraction and complete managed-candidate authoring (spec 0010 §3, plan J1/V1).

Focused journeys over independently authored facts. The positive candidate
journey starts from J0's NONEMPTY metadata-only imported baseline on a fresh
contributor clone (baseline originals unavailable there), adds one retained
new source producing two explicitly defined pages with real cross-page
references plus an authored ontology addition, and also edits a baseline page
body reusing its exact unchanged binding without any raw-file field. The
failure family proves each named refusal leaves the authored tree unchanged
and discloses private residue honestly. The extraction route test covers the
truthful public contract: normalized UTF-8 text, digest, actual processor and
outside-repo output, with missing/empty refusals.

Oracles are the fixtures: hand-written page bodies and Claims, digests
computed with ``hashlib.sha256`` over hand-written bytes, and filesystem,
Git and registry state — never implementation serialization.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from lumio_wiki.artifact_store import (
    ArtifactAccessDenied,
    LocalDirectoryArtifactStore,
)
from lumio_wiki.cli import SOURCE_STORE_ENV_VAR, main
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry

NAMESPACE = "urn:uuid:8f2f6c2e-3b1d-4e6a-9c21-7d0e5a4b1c02"

MANUAL_BYTES = b"Operate the hydraulic press only after the safety guard is locked."
MEMO_BYTES = b"Shift memo: replace the coolant filter weekly, Sundays before startup."
MANUAL_ID = "operator-manual"
MEMO_ID = "maintenance-memo"
PRESS_ENTITY = "entity:hydraulic-press"
NOTE_ENTITY = "entity:service-memo"
MANUAL_DIGEST = hashlib.sha256(MANUAL_BYTES).hexdigest()
MEMO_DIGEST = hashlib.sha256(MEMO_BYTES).hexdigest()

# The contribution: one hand-written original producing two new pages and an
# ontology addition, plus a body edit to an existing baseline-bound page.
BANDSAW_BYTES = (
    b"# Bandsaw Model BW-3\n\n"
    b"The bandsaw specification fixes the inspection cadence.\n\n"
    b"## Maintenance\n\nBlade guides are inspected at every service stop.\n"
)
BANDSAW_ID = "bandsaw-spec"
BANDSAW_DIGEST = hashlib.sha256(BANDSAW_BYTES).hexdigest()
SAW_ENTITY = "entity:bandsaw"
SAW_CARE_ENTITY = "entity:bandsaw-maintenance"

CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
      literal_kind: string
"""

# The candidate Control File is the complete baseline control plus the
# authored ontology addition (new Entity type + new known predicate).
CANDIDATE_CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
    bandsaw:
      description: "A bandsaw documented by its specification."
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
      literal_kind: string
    inspected-at:
      subject_types:
        - bandsaw
      literal_kind: string
    maintained-with:
      subject_types:
        - bandsaw
      object_types:
        - bandsaw
"""


def _applied_page(page_text: str) -> tuple[dict, str]:
    """Split one applied page into its parsed frontmatter and prose body.

    The independent oracle is the parsed semantic facts, never either
    formatting style of the serializer.
    """
    stripped = page_text.removeprefix("---\n")
    frontmatter_text, body = stripped.split("\n---\n", 1)
    return yaml.safe_load(frontmatter_text), body


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test Author")
    return path


def _managed_page(
    title: str, entity_id: str, entity_type: str, source_id: str, *, claim_id: str
) -> str:
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n"
        f"  - {entity_type}\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The original document permanently supports this page."\n'
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        f'    title: "{title} source"\n'
        "claims:\n"
        f"  - id: {claim_id}\n"
        "    predicate: documented-at\n"
        '    value: "2026-10-01"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Overview\n\n"
        f"Supported by the {source_id} original.\n"
    )


def _bandsaw_page(
    *, title: str, entity_id: str, object_entity: str, claim_id: str, cross_claim_id: str
) -> str:
    """One new authored page: fixed Entity, the new source, new predicates,
    and one evidence-bearing entity-to-entity cross-page Claim (``object``)."""
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n"
        "  - bandsaw\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The bandsaw specification permanently supports this page."\n'
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{BANDSAW_ID}"\n'
        f'    title: "Bandsaw specification"\n'
        "claims:\n"
        f"  - id: {claim_id}\n"
        "    predicate: inspected-at\n"
        '    value: "2026-10-23"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        f"  - id: {cross_claim_id}\n"
        "    predicate: maintained-with\n"
        f'    object: "{object_entity}"\n'
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Overview\n\n"
        "Inspected under the bandsaw specification.\n"
    )


def _service_memo_update() -> str:
    """The baseline-bound page edited in body, reusing its exact binding."""
    page = _managed_page(
        "Service Memo", NOTE_ENTITY, "note", MEMO_ID, claim_id="claim:memo-documented"
    )
    return page.replace(
        "Supported by the maintenance-memo original.",
        "Supported by the maintenance-memo original. Coolant filter changes are "
        "confirmed against the weekly shift memo.",
    )


def _write_base_kb(repo: Path) -> Path:
    kb = repo / "kb"
    kb.mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL)
    pages = {
        "concepts/hydraulic-press.md": _managed_page(
            "Hydraulic Press",
            PRESS_ENTITY,
            "machine",
            MANUAL_ID,
            claim_id="claim:manual-documented",
        ),
        "concepts/service-memo.md": _managed_page(
            "Service Memo", NOTE_ENTITY, "note", MEMO_ID, claim_id="claim:memo-documented"
        ),
    }
    for rel, content in pages.items():
        (kb / rel).parent.mkdir(parents=True, exist_ok=True)
        (kb / rel).write_text(content)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={MANUAL_ID: "active", MEMO_ID: "active"},
                bindings={
                    PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
                    NOTE_ENTITY: {MEMO_ID: MEMO_DIGEST},
                },
            )
        )
    )
    return kb


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _maintainer_fixture(tmp_path: Path):
    repo = _init_repo(tmp_path / "maintainer" / "repo")
    kb = _write_base_kb(repo)
    base = _commit(repo, "baseline revision")
    registry = SourceRegistry(tmp_path / "maintainer" / "registry")
    registry.register_version(
        MANUAL_ID, MANUAL_BYTES, filename="manual.pdf", content_type="application/pdf"
    )
    registry.register_version(MEMO_ID, MEMO_BYTES)
    return repo, kb, registry, base


def _contributor_clone(tmp_path: Path, maintainer_repo: Path) -> tuple[Path, Path]:
    clone = tmp_path / "contributor" / "clone"
    subprocess.run(
        ["git", "clone", "-q", str(maintainer_repo), str(clone)],
        capture_output=True,
        check=True,
    )
    return clone, clone / "kb"


def _write_contribution(tmp_path: Path, ckb: Path, base: str) -> Path:
    """Hand-author the working files (outside the clone) and the v1 request."""
    work = tmp_path / "contributor" / "work"
    work.mkdir(parents=True, exist_ok=True)
    original = work / "bandsaw-spec.md"
    original.write_bytes(BANDSAW_BYTES)
    (work / "bandsaw.md").write_text(
        _bandsaw_page(
            title="Bandsaw",
            entity_id=SAW_ENTITY,
            object_entity=SAW_CARE_ENTITY,
            claim_id="claim:saw-inspected",
            cross_claim_id="claim:saw-maintained-with",
        )
    )
    (work / "bandsaw-maintenance.md").write_text(
        _bandsaw_page(
            title="Bandsaw Maintenance",
            entity_id=SAW_CARE_ENTITY,
            object_entity=SAW_ENTITY,
            claim_id="claim:care-inspected",
            cross_claim_id="claim:care-maintained-with",
        )
    )
    (work / "service-memo-update.md").write_text(_service_memo_update())
    control_dir = work / "candidate-control"
    control_dir.mkdir(exist_ok=True)
    (control_dir / "lumio.yaml").write_text(CANDIDATE_CONTROL)
    request = {
        "schema_version": 1,
        "base_revision": base,
        "sources": [
            {
                "source_id": BANDSAW_ID,
                "original_path": str(original),
                "expected_digest": BANDSAW_DIGEST,
                "intent": "new",
            }
        ],
        "pages": [
            str(work / "bandsaw.md"),
            str(work / "bandsaw-maintenance.md"),
            str(work / "service-memo-update.md"),
        ],
        "control": str(control_dir / "lumio.yaml"),
    }
    request_path = work / "candidate-request.json"
    request_path.write_text(json.dumps(request, indent=2))
    return request_path


def _ingest_candidate_argv(ckb: Path, request_path: Path, creg_dir: Path) -> list[str]:
    return [
        "ingest-candidate",
        str(ckb),
        "--candidate",
        str(request_path),
        "--source-registry",
        str(creg_dir),
        "--json",
    ]


def _tree_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _registry_state_bytes(registry_dir: Path) -> bytes | None:
    state = registry_dir / "sources.json"
    return state.read_bytes() if state.exists() else None


def _bootstrap_with_confirm(tmp_path, mrepo, mkb, mreg, base, capsys) -> tuple[Path, Path]:
    """Export, inspect (capture the preview digest) and confirm the import."""
    snapshot = tmp_path / "transfer" / "baseline.tar"
    code = main(
        [
            "source-bootstrap",
            "export",
            str(mkb),
            "--revision",
            base,
            "--output",
            str(snapshot),
            "--source-registry",
            str(mreg.root),
            "--json",
        ]
    )
    assert code == 0
    capsys.readouterr()
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    _clone, ckb = _contributor_clone(tmp_path, mrepo)
    creg_dir = tmp_path / "contributor" / "registry"
    code = main(
        [
            "source-bootstrap",
            "inspect",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--json",
        ]
    )
    assert code == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["ok"] is True
    code = main(
        [
            "source-bootstrap",
            "import",
            str(ckb),
            "--snapshot",
            str(snapshot),
            "--digest",
            digest,
            "--revision",
            base,
            "--source-registry",
            str(creg_dir),
            "--confirm",
            preview["confirmation_digest"],
            "--json",
        ]
    )
    assert code == 0
    capsys.readouterr()
    return ckb, creg_dir


# ---------------------------------------------------------------------------
# V1 positive: two new pages + ontology + baseline-binding body edit, from a
# J0 metadata-only bootstrap (no baseline originals on the contributor).
# ---------------------------------------------------------------------------


def test_candidate_binds_two_pages_and_ontology(tmp_path, capsys, monkeypatch):
    mrepo, mkb, mreg, base = _maintainer_fixture(tmp_path)
    ckb, creg_dir = _bootstrap_with_confirm(tmp_path, mrepo, mkb, mreg, base, capsys)
    # Baseline metadata resolves on the contributor; no originals exist there.
    creg = SourceRegistry(creg_dir)
    assert creg.find_version(MEMO_ID, MEMO_DIGEST) is not None
    assert creg.find_version(MANUAL_ID, MANUAL_DIGEST) is not None
    cstore_dir = tmp_path / "contributor" / "store"
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(cstore_dir))

    request_path = _write_contribution(tmp_path, ckb, base)
    code = main(_ingest_candidate_argv(ckb, request_path, creg_dir))
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["base_revision"] == base

    # Authored pages landed at their routed paths; bodies are the hand-written
    # facts (fixed expected text, not implementation serialization).
    saw_path = ckb / "concepts" / "bandsaw.md"
    care_path = ckb / "concepts" / "bandsaw_maintenance.md"
    memo_path = ckb / "concepts" / "service-memo.md"
    assert saw_path.is_file() and care_path.is_file() and memo_path.is_file()
    assert payload["page_paths"] == sorted(
        {"concepts/bandsaw.md", "concepts/bandsaw_maintenance.md", "concepts/service-memo.md"}
    )
    saw_body = saw_path.read_text(encoding="utf-8")
    care_body = care_path.read_text(encoding="utf-8")
    memo_body = memo_path.read_text(encoding="utf-8")
    for page_text, entity_id, claim_id, cross_claim_id, object_entity in (
        (
            saw_body,
            SAW_ENTITY,
            "claim:saw-inspected",
            "claim:saw-maintained-with",
            SAW_CARE_ENTITY,
        ),
        (
            care_body,
            SAW_CARE_ENTITY,
            "claim:care-inspected",
            "claim:care-maintained-with",
            SAW_ENTITY,
        ),
    ):
        frontmatter, prose = _applied_page(page_text)
        assert frontmatter["id"] == entity_id
        claims = {claim["id"]: claim for claim in frontmatter["claims"]}
        inspected = claims[claim_id]
        assert inspected["predicate"] == "inspected-at"
        assert inspected["status"] == "accepted"
        assert inspected["evidence"][0]["section"] == "Overview"
        cross = claims[cross_claim_id]
        assert cross["predicate"] == "maintained-with"
        assert cross["object"] == object_entity
        assert cross["status"] == "accepted"
        assert cross["evidence"][0]["section"] == "Overview"
        assert "Inspected under the bandsaw specification." in prose
    assert "Coolant filter changes are confirmed" in memo_body
    assert "maintenance-memo" in memo_body

    # The ontology addition is applied with the candidate.
    control_text = (ckb / "lumio.yaml").read_text(encoding="utf-8")
    assert "bandsaw:" in control_text and "inspected-at:" in control_text
    assert payload["control_updated"] is True

    # Exact bindings: new source bound to both new Entities; baseline
    # bindings (including the edited page's reused exact binding) unchanged.
    from lumio_wiki.source_references import load_source_reference_manifest

    manifest = load_source_reference_manifest(ckb)
    assert manifest is not None
    assert manifest.bindings[SAW_ENTITY] == {BANDSAW_ID: BANDSAW_DIGEST}
    assert manifest.bindings[SAW_CARE_ENTITY] == {BANDSAW_ID: BANDSAW_DIGEST}
    assert manifest.bindings[PRESS_ENTITY] == {MANUAL_ID: MANUAL_DIGEST}
    assert manifest.bindings[NOTE_ENTITY] == {MEMO_ID: MEMO_DIGEST}
    assert manifest.sources[BANDSAW_ID] == "active"

    # New raw bytes are privately retained and retrievable byte-exact.
    store = LocalDirectoryArtifactStore(cstore_dir)
    assert store.get_artifact(source_id=BANDSAW_ID, content_hash=BANDSAW_DIGEST) == BANDSAW_BYTES

    # Baseline originals stay missing while their metadata resolves: metadata
    # and retained coverage are reported separately, both counted per manifest
    # BINDING (Entity→Source): 4 bindings resolve metadata; the 2 new-Entity
    # bindings reference the ONE retained new Source Version, so 2 retained.
    assert store.artifact_exists(source_id=MEMO_ID, content_hash=MEMO_DIGEST) is False
    assert store.artifact_exists(source_id=MANUAL_ID, content_hash=MANUAL_DIGEST) is False
    assert payload["metadata_coverage"] == 4
    assert payload["retained_coverage"] == 2
    by_key = {(entry["entity_id"], entry["source_id"]): entry for entry in payload["bindings"]}
    assert by_key[(SAW_ENTITY, BANDSAW_ID)]["retained"] is True
    assert by_key[(SAW_CARE_ENTITY, BANDSAW_ID)]["retained"] is True
    assert by_key[(NOTE_ENTITY, MEMO_ID)]["retained"] is False
    assert by_key[(PRESS_ENTITY, MANUAL_ID)]["retained"] is False
    assert by_key[(NOTE_ENTITY, MEMO_ID)]["registered"] is False
    assert payload["registered_sources"] == [BANDSAW_ID]

    # The complete candidate validates: cross-page references between the two
    # new pages resolve without any invalid intermediate ingest.
    _kb, report = load_knowledge_base(ckb)
    assert report.is_valid, report

    # No native commit happened: HEAD is still the base, changes uncommitted.
    clone = ckb.parent
    assert _git(clone, "rev-parse", "HEAD") == base
    status = _git(clone, "status", "--porcelain")
    assert status.strip()


# ---------------------------------------------------------------------------
# V1 failure family: each named refusal leaves the authored tree unchanged.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        "invalid_crossref",
        "invalid_ontology",
        "retention_failure",
        "unrelated_local_edit",
        "identity_conflict",
    ],
)
def test_candidate_failure_preserves_authored_tree(case, tmp_path, capsys, monkeypatch):
    mrepo, mkb, mreg, base = _maintainer_fixture(tmp_path)
    ckb, creg_dir = _bootstrap_with_confirm(tmp_path, mrepo, mkb, mreg, base, capsys)
    cstore_dir = tmp_path / "contributor" / "store"
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(cstore_dir))
    request_path = _write_contribution(tmp_path, ckb, base)

    # Case-specific corruption of the hand-authored working files.
    if case == "invalid_crossref":
        broken = tmp_path / "contributor" / "work" / "bandsaw.md"
        broken.write_text(
            _bandsaw_page(
                title="Bandsaw",
                entity_id=SAW_ENTITY,
                object_entity="entity:missing-bandsaw",
                claim_id="claim:saw-inspected",
                cross_claim_id="claim:saw-maintained-with",
            )
        )
    elif case == "invalid_ontology":
        # The pages use the new predicate but the candidate control omits it.
        control = json.loads(request_path.read_text())["control"]
        Path(control).write_text(CONTROL)
    elif case == "unrelated_local_edit":
        # An uncommitted local edit at a candidate target path.
        memo = ckb / "concepts" / "service-memo.md"
        memo.write_text(memo.read_text() + "\nUncommitted local author note.\n")

    if case == "retention_failure":
        from lumio_wiki.artifact_store import LocalDirectoryArtifactStore as _Store

        def _fail(self, **_kwargs):
            raise OSError("synthetic store I/O failure")

        monkeypatch.setattr(_Store, "put_artifact", _fail)

    if case == "identity_conflict":
        request = json.loads(request_path.read_text())
        request["sources"][0]["source_id"] = MEMO_ID  # already in the base
        request_path.write_text(json.dumps(request, indent=2))

    clone = ckb.parent
    tree_before = _tree_files(ckb)
    contents_before = {
        rel: (ckb / rel).read_bytes() for rel in tree_before if (ckb / rel).is_file()
    }
    registry_before = _registry_state_bytes(creg_dir)

    code = main(_ingest_candidate_argv(ckb, request_path, creg_dir))
    payload = json.loads(capsys.readouterr().out)
    assert code == 2, payload
    assert payload["schema_version"] == 1
    assert payload["ok"] is False
    expected_code = {
        "invalid_crossref": "invalid_candidate",
        "invalid_ontology": "invalid_candidate",
        "retention_failure": "retention_failed",
        "unrelated_local_edit": "unsafe_worktree",
        "identity_conflict": "identity_conflict",
    }[case]
    assert payload["error"]["code"] == expected_code

    # Unchanged-tree proof: same files, byte-identical content. The local-edit
    # case keeps exactly the pre-existing edit (nothing overwritten).
    assert _tree_files(ckb) == tree_before
    for rel in tree_before:
        assert (ckb / rel).read_bytes() == contents_before[rel], rel
    if case == "unrelated_local_edit":
        assert b"Uncommitted local author note." in (ckb / "concepts/service-memo.md").read_bytes()
    else:
        assert not _git(clone, "status", "--porcelain").strip()

    # Private residue: everything except the retention failure leaves the
    # registry untouched; the retention failure discloses the immutable,
    # retry-safe registration residue truthfully (bytes present, no artifact).
    if case == "retention_failure":
        registry = SourceRegistry(creg_dir)
        assert registry.find_version(BANDSAW_ID, BANDSAW_DIGEST) is not None
        assert not cstore_dir.exists() or not any(cstore_dir.rglob("*"))
    else:
        assert _registry_state_bytes(creg_dir) == registry_before


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Regression (j1-boundary): fallible coverage reads and the request-file
# location boundary must never leave authored content mutated on failure.
# ---------------------------------------------------------------------------


def test_candidate_coverage_failure_preserves_authored_tree(tmp_path, capsys, monkeypatch):
    """A coverage-read failure after successful retention must refuse BEFORE
    any authored edit: plan0010 J1 rollback guarantee. The thin delegating
    adapter denies reads for ONE fixed baseline source id only; new-source
    retention (put_artifact) works normally through the real local store.
    """
    mrepo, mkb, mreg, base = _maintainer_fixture(tmp_path)
    ckb, creg_dir = _bootstrap_with_confirm(tmp_path, mrepo, mkb, mreg, base, capsys)
    cstore_dir = tmp_path / "contributor" / "store"
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(cstore_dir))
    request_path = _write_contribution(tmp_path, ckb, base)

    original_exists = LocalDirectoryArtifactStore.artifact_exists

    def _denied_for_baseline(self, *, source_id, content_hash):
        if source_id == MEMO_ID:
            raise ArtifactAccessDenied(
                f"synthetic denial: baseline original {source_id} is unreadable"
            )
        return original_exists(self, source_id=source_id, content_hash=content_hash)

    monkeypatch.setattr(LocalDirectoryArtifactStore, "artifact_exists", _denied_for_baseline)

    clone = ckb.parent
    tree_before = _tree_files(ckb)
    contents_before = {
        rel: (ckb / rel).read_bytes() for rel in tree_before if (ckb / rel).is_file()
    }

    code = main(_ingest_candidate_argv(ckb, request_path, creg_dir))
    payload = json.loads(capsys.readouterr().out)
    assert code == 2, payload
    assert payload["schema_version"] == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "artifact_access_failed"

    # Rollback guarantee: authored tree byte-identical, no Git change at all.
    assert _tree_files(ckb) == tree_before
    for rel in tree_before:
        assert (ckb / rel).read_bytes() == contents_before[rel], rel
    assert not _git(clone, "status", "--porcelain").strip()

    # Baseline private history is preserved, and the permitted immutable
    # residue from this run is exactly the registered+retained NEW source
    # (registration and verified retention precede the reporting read).
    registry = SourceRegistry(creg_dir)
    assert registry.find_version(MEMO_ID, MEMO_DIGEST) is not None
    assert registry.find_version(MANUAL_ID, MANUAL_DIGEST) is not None
    assert registry.find_version(BANDSAW_ID, BANDSAW_DIGEST) is not None
    store = LocalDirectoryArtifactStore(cstore_dir)
    assert original_exists(store, source_id=BANDSAW_ID, content_hash=BANDSAW_DIGEST) is True


@pytest.mark.parametrize("location", ["direct", "symlink"])
def test_candidate_request_must_be_outside_repository(location, tmp_path, capsys, monkeypatch):
    """The working request file lives outside the content repository (plan
    Candidate request v1); a request inside the repo — direct or through a
    symlink resolving inside — is refused before any authored or private
    mutation. Referenced page/control/original files stay outside.
    """
    mrepo, mkb, mreg, base = _maintainer_fixture(tmp_path)
    ckb, creg_dir = _bootstrap_with_confirm(tmp_path, mrepo, mkb, mreg, base, capsys)
    cstore_dir = tmp_path / "contributor" / "store"
    monkeypatch.setenv(SOURCE_STORE_ENV_VAR, str(cstore_dir))
    request_path = _write_contribution(tmp_path, ckb, base)

    clone = ckb.parent
    inside_request = clone / "candidate-request.json"
    inside_request.write_text(request_path.read_text(encoding="utf-8"), encoding="utf-8")
    selected = inside_request
    if location == "symlink":
        link = tmp_path / "contributor" / "work" / "inside-link.json"
        link.symlink_to(inside_request)
        selected = link

    registry_before = _registry_state_bytes(creg_dir)
    code = main(_ingest_candidate_argv(ckb, selected, creg_dir))
    payload = json.loads(capsys.readouterr().out)
    assert code == 2, payload
    assert payload["schema_version"] == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "request_inside_repository"

    # Refusal preceded every authored and private mutation: the only new file
    # in the whole clone is the intentionally placed request file itself, and
    # the private registry/store were never touched.
    status = _git(clone, "status", "--porcelain")
    assert status.strip() == "?? candidate-request.json"
    assert _registry_state_bytes(creg_dir) == registry_before
    assert not cstore_dir.exists() or not any(cstore_dir.rglob("*"))


# Focused extraction route: truthful public contract (spec 0010 §3).
# ---------------------------------------------------------------------------


def test_extract_public_route_reports_truthful_material(tmp_path, capsys):
    work = tmp_path / "extraction-work"
    work.mkdir(parents=True)
    original = work / "bandsaw-spec.md"
    original.write_bytes(BANDSAW_BYTES)
    output = tmp_path / "private-extraction"

    code = main(["extract", str(original), "--output", str(output), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0, payload
    assert payload["schema_version"] == 1
    assert payload["ok"] is True
    # Digest oracle: hashlib over the hand-written bytes, not the report.
    assert payload["source_sha256"] == BANDSAW_DIGEST
    # The actual processor identity for a routed text/Markdown source.
    assert payload["processor"] == "markdown"
    # Normalized text is the real file content with real coordinates.
    assert payload["text"] == BANDSAW_BYTES.decode("utf-8")
    assert payload["sections"][0]["line_start"] == 1
    assert payload["incomplete"] is False
    # Working material persisted outside any repository (digest-addressed).
    record = output / f"{BANDSAW_DIGEST}.json"
    assert record.is_file()
    persisted = json.loads(record.read_text(encoding="utf-8"))
    assert persisted["text"] == BANDSAW_BYTES.decode("utf-8")
    assert persisted["processor"] == "markdown"

    # Missing original refuses with a versioned, actionable failure.
    code = main(["extract", str(work / "absent.md"), "--output", str(output), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["schema_version"] == 1
    assert payload["error"]["code"] == "missing_source"

    # Empty original refuses as an empty extraction (disclosed, not success).
    empty = work / "empty.md"
    empty.write_bytes(b"")
    code = main(["extract", str(empty), "--output", str(output), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"]["code"] == "empty_extraction"

    # Output inside a Git worktree is refused: extraction stays outside Git.
    mrepo, mkb, _mreg, _base = _maintainer_fixture(tmp_path)
    inside = mrepo / "private-extraction"
    code = main(["extract", str(original), "--output", str(inside), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["error"]["code"] == "output_inside_repository"


# ---------------------------------------------------------------------------
# Independent J1-J2 review regression preparation (j1-j2-review.md F7-F9).
# Expected values are fixed fixture facts; these nodes are RED against the
# reviewed implementation and must turn green only through the
# parent-authorized product repair.
# ---------------------------------------------------------------------------


def _private_selection_request(work: Path, original_path: Path, base: str) -> Path:
    """A valid two-page candidate request whose original lives at original_path."""
    (work / "bandsaw.md").write_text(
        _bandsaw_page(
            title="Bandsaw",
            entity_id=SAW_ENTITY,
            object_entity=SAW_CARE_ENTITY,
            claim_id="claim:saw-inspected",
            cross_claim_id="claim:saw-maintained-with",
        )
    )
    (work / "bandsaw_maintenance.md").write_text(
        _bandsaw_page(
            title="Bandsaw Maintenance",
            entity_id=SAW_CARE_ENTITY,
            object_entity=SAW_ENTITY,
            claim_id="claim:care-inspected",
            cross_claim_id="claim:care-maintained-with",
        )
    )
    control_dir = work / "candidate-control"
    control_dir.mkdir(exist_ok=True)
    (control_dir / "lumio.yaml").write_text(CANDIDATE_CONTROL)
    request = {
        "schema_version": 1,
        "base_revision": base,
        "sources": [
            {
                "source_id": BANDSAW_ID,
                "original_path": str(original_path),
                "expected_digest": BANDSAW_DIGEST,
                "intent": "new",
            }
        ],
        "pages": [str(work / "bandsaw.md"), str(work / "bandsaw_maintenance.md")],
        "control": str(control_dir / "lumio.yaml"),
    }
    request_path = work / "candidate-request.json"
    request_path.write_text(json.dumps(request, indent=2))
    return request_path


@pytest.mark.parametrize("inside", ["original", "registry", "artifact_store", "original_symlink"])
def test_candidate_refuses_private_paths_inside_repository(inside, tmp_path):
    """F7: originals, registries and local stores never live inside the repository."""
    from lumio_wiki.authoring_journey import (
        AuthoringJourneyError,
        ingest_candidate,
        load_candidate_request,
    )

    repo = _init_repo(tmp_path / "repo")
    kb = _write_base_kb(repo)
    _commit(repo, "baseline revision")
    base = _git(repo, "rev-parse", "HEAD")
    private = repo / "private"
    private.mkdir()
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir"))
    with (git_dir / "info" / "exclude").open("a") as exclude:
        exclude.write("private/\n")

    outside = tmp_path / "outside"
    outside.mkdir()
    work = outside / "work"
    work.mkdir()
    registry_dir = outside / "registry"
    registry = SourceRegistry(registry_dir)
    registry.register_version(MANUAL_ID, MANUAL_BYTES)
    registry.register_version(MEMO_ID, MEMO_BYTES)
    store_dir = outside / "store"

    original_path = work / "bandsaw-spec.md"
    original_path.write_bytes(BANDSAW_BYTES)
    if inside == "original":
        original_path = private / "bandsaw-spec.md"
        original_path.write_bytes(BANDSAW_BYTES)
    elif inside == "original_symlink":
        target = private / "bandsaw-spec.md"
        target.write_bytes(BANDSAW_BYTES)
        original_path = work / "original-link.md"
        original_path.symlink_to(target)
    elif inside == "registry":
        registry_dir = private / "registry"
        registry = SourceRegistry(registry_dir)
        registry.register_version(MANUAL_ID, MANUAL_BYTES)
        registry.register_version(MEMO_ID, MEMO_BYTES)
        registry.register_version(BANDSAW_ID, BANDSAW_BYTES)
    else:
        store_dir = private / "store"
        store_dir.mkdir()

    request_path = _private_selection_request(work, original_path, base)
    private_files_before = _tree_files(private)
    kb_files_before = {p: p.read_bytes() for p in sorted(kb.rglob("*")) if p.is_file()}
    registry_state_before = (
        (registry_dir / "sources.json").read_bytes()
        if (registry_dir / "sources.json").exists()
        else None
    )

    with pytest.raises(AuthoringJourneyError):
        ingest_candidate(
            kb,
            load_candidate_request(request_path),
            source_registry=registry,
            artifact_store=LocalDirectoryArtifactStore(store_dir),
        )
    # Refusal happens before any private or authoring mutation.
    assert _tree_files(private) == private_files_before
    assert {p: p.read_bytes() for p in sorted(kb.rglob("*")) if p.is_file()} == kb_files_before
    registry_state_after = (
        (registry_dir / "sources.json").read_bytes()
        if (registry_dir / "sources.json").exists()
        else None
    )
    assert registry_state_after == registry_state_before


def test_extract_discloses_converter_truncation(tmp_path, monkeypatch):
    """F8: known converter truncation is disclosed, not inferred from length."""
    import hashlib

    from lumio_wiki import authoring_journey
    from lumio_wiki.source_processor import MAX_EXTRACTED_CHARS, MarkItDownSourceProcessor

    line = "x" * 99
    big_text = "# Conversion result\n" + "\n".join([line] * 2100)
    # Documented line-boundary truncation rule, computed from the fixture.
    cut = big_text[:MAX_EXTRACTED_CHARS].rfind("\n")
    expected_text = big_text[:cut]
    assert cut > MAX_EXTRACTED_CHARS // 2 and cut < MAX_EXTRACTED_CHARS
    assert "\n" not in big_text[cut + 1 : MAX_EXTRACTED_CHARS]

    def _fixed_converter(content: bytes, filename: str | None) -> str:
        return big_text

    def _inline_runner(fn, *args, timeout=None, **kwargs):
        # The seam passes the conversion timeout to the runner; an inline
        # runner applies it trivially and never forwards it into the
        # two-argument converter.
        return fn(*args, **kwargs)

    processor = MarkItDownSourceProcessor(converter=_fixed_converter, runner=_inline_runner)
    monkeypatch.setattr(
        authoring_journey, "select_document_processor", lambda filename, content_type: processor
    )
    source_bytes = b"<html>fixture bytes</html>"
    source = tmp_path / "big-report.html"
    source.write_bytes(source_bytes)

    result = authoring_journey.extract_source(source, output_dir=tmp_path / "extract-out")
    assert result.incomplete is True
    assert result.text == expected_text
    assert result.processor == "markitdown"
    assert result.source_sha256 == hashlib.sha256(source_bytes).hexdigest()


def test_candidate_preserves_existing_entity_identity(tmp_path):
    """F9: a same-title update cannot silently change an existing Entity ID."""
    from lumio_wiki.authoring_journey import (
        AuthoringJourneyError,
        ingest_candidate,
        load_candidate_request,
    )
    from lumio_wiki.source_references import (
        SourceReferenceManifest,
        serialize_source_reference_manifest,
    )

    GUIDE_ENTITY = "entity:field-guide"
    GUIDE_V2_ENTITY = "entity:field-guide-v2"
    GUIDE_SOURCE = "field-notes"
    NEW_SOURCE = "guide-spec"
    new_bytes = b"# Field Guide R2\n\nThe revised field guide rounds the ridge counts.\n"
    new_digest = hashlib.sha256(new_bytes).hexdigest()

    repo = _init_repo(tmp_path / "repo")
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _managed_page(
            "Hydraulic Press",
            PRESS_ENTITY,
            "machine",
            MANUAL_ID,
            claim_id="claim:manual-documented",
        )
    )
    # A supported native state: public-only provenance, no managed binding.
    (kb / "concepts" / "field-guide.md").write_text(
        _managed_page(
            "Field Guide",
            GUIDE_ENTITY,
            "note",
            GUIDE_SOURCE,
            claim_id="claim:guide-documented",
        )
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={MANUAL_ID: "active"},
                bindings={PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST}},
            )
        )
    )
    _commit(repo, "baseline revision")
    base = _git(repo, "rev-parse", "HEAD")

    outside = tmp_path / "outside"
    outside.mkdir()
    registry = SourceRegistry(outside / "registry")
    registry.register_version(MANUAL_ID, MANUAL_BYTES)
    original = outside / "guide-spec.md"
    original.write_bytes(new_bytes)
    work = outside / "work"
    work.mkdir()
    (work / "field-guide.md").write_text(
        _managed_page(
            "Field Guide",
            GUIDE_V2_ENTITY,
            "note",
            NEW_SOURCE,
            claim_id="claim:guide-documented",
        )
    )
    request = {
        "schema_version": 1,
        "base_revision": base,
        "sources": [
            {
                "source_id": NEW_SOURCE,
                "original_path": str(original),
                "expected_digest": new_digest,
                "intent": "new",
            }
        ],
        "pages": [str(work / "field-guide.md")],
    }
    request_path = work / "candidate-request.json"
    request_path.write_text(json.dumps(request, indent=2))

    kb_files_before = {p: p.read_bytes() for p in sorted(kb.rglob("*")) if p.is_file()}
    registry_state = outside / "registry" / "sources.json"
    registry_before = registry_state.read_bytes() if registry_state.exists() else None

    with pytest.raises(AuthoringJourneyError):
        ingest_candidate(
            kb,
            load_candidate_request(request_path),
            source_registry=registry,
            artifact_store=LocalDirectoryArtifactStore(outside / "store"),
        )
    assert {p: p.read_bytes() for p in sorted(kb.rglob("*")) if p.is_file()} == kb_files_before
    registry_after = registry_state.read_bytes() if registry_state.exists() else None
    assert registry_after == registry_before


def test_document_first_candidate_uses_neutral_type_without_retyping_existing_page(tmp_path):
    """A neutral runbook coexists with, rather than retypes, an existing Entity."""
    from lumio_wiki import document_first_control_file
    from lumio_wiki.authoring_journey import (
        CandidateRequest,
        CandidateSourceRecord,
        ingest_candidate,
    )
    from lumio_wiki.git_authoring import preview_publication, publish_revision
    from lumio_wiki.knowledge_base import (
        ControlFileError,
        load_control_file,
        seeded_control_file,
        write_control_file,
    )
    from lumio_wiki.location import PublishedFilesystemLocation
    from lumio_wiki.records import EntityTypeDefinition
    from lumio_wiki.source_references import (
        SourceReferenceManifest,
        serialize_source_reference_manifest,
    )

    artifact_description = (
        "A document, record, or other knowledge artifact. Its referent is the "
        "artifact itself, not a person, organization, service, or business object "
        "mentioned in it."
    )
    generic = seeded_control_file()
    assert generic.ontology is not None
    document_first = document_first_control_file()
    assert document_first.ontology is not None
    assert document_first.categories == generic.categories
    assert document_first.hot_index == generic.hot_index
    assert document_first.ontology.entity_types["knowledge-artifact"] == (
        EntityTypeDefinition(description=artifact_description)
    )
    assert document_first.ontology.predicates == {}
    assert document_first.ontology.redirects == []
    # Opting into the new profile never changes the generic empty-ontology seed.
    assert generic.ontology.entity_types == {}
    assert generic.ontology.predicates == {}
    assert generic.ontology.redirects == []

    repo = _init_repo(tmp_path / "repo")
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / "lumio.yaml").write_text(
        """\
version: 2
mode: "categorized"
categories:
  - name: concepts
  - name: procedures
hot_index:
  - title: "Field Guide"
ontology:
  entity_types:
    note:
      description: "An existing note."
  predicates: {}
  redirects:
    entity:old-field-guide: entity:field-guide
"""
    )
    (kb / "concepts" / "field-guide.md").write_text(
        """\
---
id: "entity:field-guide"
title: "Field Guide"
entity_types: ["note"]
category: concepts
type: "note"
durability_rationale: "The field notes permanently support this page."
tags: ["reference"]
summary: "An existing note whose meaning must remain unchanged."
lifecycle: "approved"
visibility: "internal"
sources:
  - id: "field-notes"
    title: "Field notes"
claims: []
synthetic: false
---
# Field Guide

Keep the existing field guide identity.\n"""
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={},
                bindings={},
            )
        )
    )
    base = _commit(repo, "baseline revision")
    existing_control = load_control_file(kb)
    assert existing_control is not None and existing_control.ontology is not None
    candidate_control = document_first_control_file(existing_control)
    assert candidate_control.categories == existing_control.categories
    assert candidate_control.hot_index == existing_control.hot_index
    assert candidate_control.ontology is not None
    assert candidate_control.ontology.entity_types["note"] == (
        existing_control.ontology.entity_types["note"]
    )
    assert candidate_control.ontology.predicates == existing_control.ontology.predicates
    assert candidate_control.ontology.redirects == existing_control.ontology.redirects
    assert document_first_control_file(candidate_control) == candidate_control

    # An independently authored same-name definition is not semantic compatibility.
    outside = tmp_path / "outside"
    conflict_root = outside / "conflict-control"
    conflict_root.mkdir(parents=True)
    (conflict_root / "lumio.yaml").write_text(
        """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    knowledge-artifact:
      description: "A customer mentioned in a document."
  predicates: {}
  redirects: {}
"""
    )
    conflicting_control = load_control_file(conflict_root)
    kb_files_before = {p: p.read_bytes() for p in sorted(kb.rglob("*")) if p.is_file()}
    with pytest.raises(ControlFileError, match="knowledge-artifact.*conflicts"):
        document_first_control_file(conflicting_control)
    assert {p: p.read_bytes() for p in sorted(kb.rglob("*")) if p.is_file()} == kb_files_before

    runbook_entity = "entity:restart-worker-runbook"
    runbook_source = "restart-worker-runbook-source"
    runbook_body = (
        "# Restart Worker\n\nRestart the worker after replacing its configuration.\n"
    )
    original = outside / "originals" / "restart-worker.md"
    original.parent.mkdir(parents=True)
    original.write_text(runbook_body)
    runbook_digest = hashlib.sha256(original.read_bytes()).hexdigest()
    authored = outside / "authored" / "restart-worker.md"
    authored.parent.mkdir(parents=True)
    authored.write_text(
        """\
---
id: "entity:restart-worker-runbook"
title: "Restart Worker"
entity_types: ["knowledge-artifact"]
category: procedures
type: "runbook"
durability_rationale: "The source runbook permanently supports this procedure."
tags: ["operations"]
summary: "Restart the worker after replacing its configuration."
lifecycle: "draft"
visibility: "internal"
sources:
  - id: "restart-worker-runbook-source"
    title: "Restart worker runbook"
claims: []
synthetic: false
---
"""
        + runbook_body
    )
    control_path = write_control_file(outside / "candidate-control", candidate_control)
    request = CandidateRequest(
        schema_version=1,
        base_revision=base,
        sources=[
            CandidateSourceRecord(
                source_id=runbook_source,
                original_path=str(original),
                expected_digest=runbook_digest,
                intent="new",
            )
        ],
        pages=[str(authored)],
        control=str(control_path),
    )
    registry = SourceRegistry(outside / "registry")
    store = LocalDirectoryArtifactStore(outside / "store")
    result = ingest_candidate(
        kb,
        request,
        source_registry=registry,
        artifact_store=store,
    )
    assert result.entity_ids == [runbook_entity]
    assert result.control_updated is True
    assert len(result.bindings) == 1
    binding = result.bindings[0]
    assert binding.entity_id == runbook_entity
    assert binding.source_id == runbook_source
    assert binding.content_hash == runbook_digest
    assert binding.registered is True and binding.retained is True

    revision = _commit(repo, "Add document-first runbook")
    destination = tmp_path / "published"
    review = preview_publication(
        kb,
        revision,
        destination,
        "none",
        source_registry=registry,
        artifact_store=store,
    )
    assert review.blocking_diagnostics == []
    receipt = publish_revision(
        kb,
        revision,
        destination,
        "none",
        review.review_digest,
        source_registry=registry,
        artifact_store=store,
    )
    assert receipt.activated is True

    snapshot = PublishedFilesystemLocation(destination).resolve()
    assert snapshot.validation_report.is_valid
    published_kb = snapshot.knowledge_base
    runbook = published_kb.lookup_by_title("Restart Worker")
    assert len(runbook) == 1
    assert runbook[0].id == runbook_entity
    assert runbook[0].entity_types == ["knowledge-artifact"]
    assert runbook[0].claims == []
    read = published_kb.read_page("Restart Worker")
    assert read.content.strip() == runbook_body.strip()
    assert read.entity_id == runbook_entity
    assert read.entity_types == ["knowledge-artifact"]
    assert read.claims == []
    existing = published_kb.lookup_by_title("Field Guide")
    assert len(existing) == 1
    assert existing[0].id == "entity:field-guide"
    assert existing[0].entity_types == ["note"]
    redirected = published_kb.resolve_entity("entity:old-field-guide")
    assert redirected.entity is not None
    assert redirected.entity.id == "entity:field-guide"
    assert published_kb.control is not None
    assert published_kb.control.hot_index == existing_control.hot_index
    assert published_kb.control.ontology is not None
    assert published_kb.control.ontology.entity_types["knowledge-artifact"] == (
        EntityTypeDefinition(description=artifact_description)
    )

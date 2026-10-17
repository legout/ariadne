"""Git-native authoring and local publication (spec 0008, plan G1, unit L).

One coherent public CLI/SDK journey over an independently authored v2
Entity/Claim fixture: a managed ingest binds raw bytes ``A`` into the Git
authoring worktree, the author commits with Git, ``publish --revision``
produces a stateless preview, and explicit confirmation activates one
immutable local Published Version whose Evidence, private binding, manifest
digest, and receipt all identify the captured revision. Registering
replacement bytes ``B`` after the review of ``A`` never switches the binding.
Distinct refusal scenarios (invalid Claim/anchor/link/source refs, changed
review input or current pointer, failed preparation, edited authoring files),
prior-Snapshot preservation, retry, rollback, and fail-closed reading are
asserted against expectations derived from the fixture and the SHA-256 oracle
``hashlib.sha256`` — never from implementation output.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from lumio_wiki.cli import main
from lumio_wiki.git_authoring import (
    ConfirmationRefused,
    GitAuthoringError,
    PublicationConflict,
    preview_publication,
    preview_rollback,
    publish_revision,
    rollback_publication,
)
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.location import FilesystemLocation, PublishedFilesystemLocation
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    parse_source_reference_manifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry

NAMESPACE = "urn:uuid:0f6f0e3e-1d9a-4b2e-9d47-6c1f0f5f4f3e"

A_BYTES = b"Press the green button for exactly three seconds."
B_BYTES = b"Press the BLUE button for exactly five seconds."

A_DIGEST = hashlib.sha256(A_BYTES).hexdigest()
B_DIGEST = hashlib.sha256(B_BYTES).hexdigest()

ZERO_DIGEST = "0" * 64

CONTROL_V2 = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    press:
      description: "A machine that presses materials."
    material: {}
  predicates:
    presses:
      subject_types:
        - press
      object_types:
        - material
    rated-at:
      subject_types:
        - press
      literal_kind: string
"""


def _entity_page(
    title: str,
    entity_id: str,
    entity_types: list[str],
    *,
    claims_yaml: str = "",
    body_sections: str = "## Overview\n\nOverview paragraph.\n",
    sources_yaml: str | None = None,
) -> str:
    types_yaml = "".join(f"  - {t}\n" for t in entity_types)
    sources = sources_yaml or (
        f'  - id: "src-{entity_id.rsplit(":", 1)[-1]}"\n    title: "{title} Source"\n'
    )
    claims = f"claims:\n{claims_yaml}" if claims_yaml else ""
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        f"entity_types:\n{types_yaml}"
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        f"sources:\n{sources}"
        f"{claims}"
        "---\n\n"
        f"# {title}\n\n{body_sections}"
    )


def _presses_claim(object_entity: str = "entity:steel-blank") -> str:
    return (
        "  - id: claim:press-presses\n"
        "    predicate: presses\n"
        f'    object: "{object_entity}"\n'
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
    )


def _authored_ingest_page(source_id: str) -> str:
    """A host-authored Compiled Page for managed ingest (independently authored)."""
    return (
        "---\n"
        'id: "entity:workbench-press"\n'
        'title: "Workbench Press"\n'
        "entity_types:\n"
        "  - press\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The workshop manual documents this machine permanently."\n'
        'tags:\n  - "workshop"\n'
        'summary: "The workbench press described by the operator manual."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        '    title: "Operator manual"\n'
        "claims:\n"
        "  - id: claim:workbench-rated\n"
        "    predicate: rated-at\n"
        '    value: "5 tons"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        "# Workbench Press\n\n"
        "## Overview\n\n"
        "Rated at five tons per the operator manual.\n"
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test Author")
    return repo


def _write_kb(
    repo: Path,
    *,
    manifest: SourceReferenceManifest | None = None,
    pages: dict[str, str] | None = None,
    control: str | None = CONTROL_V2,
) -> Path:
    kb = repo / "kb"
    kb.mkdir(parents=True, exist_ok=True)
    if control is not None:
        (kb / "lumio.yaml").write_text(control)
    base_pages = pages or {
        "concepts/hydraulic-press.md": _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
        ),
        "concepts/steel-blank.md": _entity_page("Steel Blank", "entity:steel-blank", ["material"]),
    }
    for rel, content in base_pages.items():
        target = kb / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    manifest = manifest or SourceReferenceManifest(version=1, namespace=NAMESPACE)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(manifest)
    )
    return kb


def _commit(repo: Path) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "authoring revision")
    return _git(repo, "rev-parse", "HEAD")


def _preview_digest(out: str) -> str:
    match = re.search(r"Review digest: ([0-9a-f]{64})", out)
    assert match is not None, out
    return match.group(1)


def _published_receipt(destination: Path, version: str) -> dict:
    raw = (destination / ".lumio-publication" / "receipts" / f"{version}.json").read_bytes()
    return json.loads(raw)


def _sealed(destination: Path, version: str) -> dict:
    raw = (destination / ".lumio-publication" / "bindings" / f"{version}.json").read_bytes()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# The complete public CLI/SDK journey (validation unit L).
# ---------------------------------------------------------------------------


def test_git_authoring_journey_publishes_exact_revision(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    destination = tmp_path / "published"
    registry = SourceRegistry(tmp_path / "registry")

    # --- Managed ingest binds raw bytes A into the worktree (CLI seam). ---
    source_file = tmp_path / "manual.txt"
    source_file.write_bytes(A_BYTES)
    compiled = tmp_path / "press.md"
    compiled.write_text(_authored_ingest_page("operator-manual"))
    code = main(
        [
            "ingest",
            str(kb),
            str(source_file),
            "--compiled-page",
            str(compiled),
            "--source-id",
            "operator-manual",
            "--source-registry",
            str(registry.root),
        ]
    )
    assert code == 0
    assert (kb / "concepts" / "workbench_press.md").is_file()
    manifest_on_disk = parse_source_reference_manifest(
        (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
    )
    assert manifest_on_disk.bindings["entity:workbench-press"] == {"operator-manual": A_DIGEST}
    # Independently derived oracle: the exact SHA-256 of the raw bytes A.
    assert A_DIGEST == hashlib.sha256(A_BYTES).hexdigest()
    # No proposal files exist anywhere under the Knowledge Base.
    assert not (kb / ".lumio").exists()
    # The private registry holds exactly the A version.
    assert registry.find_version("operator-manual", A_DIGEST) is not None

    # --- Ordinary Git authoring: the author commits (helpers never commit). ---
    (repo / "notes").mkdir(exist_ok=True)
    (repo / "notes" / "dev.md").write_text("unrelated repository content\n")
    revision = _commit(repo)
    # Uncommitted worktree content exists at preview time but is not part of
    # the revision: capture must read Git blobs only.
    (kb / "concepts" / "uncommitted.md").write_text("not committed yet\n")

    # --- Stateless preview (CLI seam), expected-current none. ---
    code = main(
        [
            "publish",
            str(kb),
            "--revision",
            revision,
            "--to",
            str(destination),
            "--expected-current",
            "none",
            "--source-registry",
            str(registry.root),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "first Git publication" in out
    assert "BLOCKING" not in out
    review_digest = _preview_digest(out)

    # --- Register replacement bytes B AFTER the review of A (AC4). ---
    version_b, action_b = registry.register_version("operator-manual", B_BYTES)
    assert action_b == "registered"
    assert version_b.content_hash == B_DIGEST

    # --- Explicit confirmation: the old review still admits A. ---
    code = main(
        [
            "publish",
            str(kb),
            "--revision",
            revision,
            "--to",
            str(destination),
            "--expected-current",
            "none",
            "--confirm",
            review_digest,
            "--source-registry",
            str(registry.root),
        ]
    )
    assert code == 0

    # The version directory is the captured revision and nothing else.
    version_dir = destination / "versions" / revision
    assert (version_dir / "manifest.json").is_file()
    assert (version_dir / "lumio.yaml").is_file()
    assert (version_dir / "concepts" / "workbench_press.md").is_file()
    assert (version_dir / "derived" / "discovery-graph.msgpack").is_file()
    assert (version_dir / "derived" / "index.md").is_file()
    # Subtree confinement: repository content outside the KB subtree and
    # uncommitted worktree files never enter the Published Version.
    assert not (version_dir / "notes").exists()
    assert not (version_dir / "concepts" / "uncommitted.md").exists()
    assert not (version_dir / SOURCE_REFERENCE_MANIFEST_BASENAME).exists()

    # Published page bytes are the exact Git blob bytes.
    blob = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", f"{revision}:kb/concepts/workbench_press.md"],
        capture_output=True,
        check=True,
    ).stdout
    assert (version_dir / "concepts" / "workbench_press.md").read_bytes() == blob

    # The admission receipt identifies the captured revision (SDK seam).
    receipt = _published_receipt(destination, revision)
    assert receipt["revision"] == revision
    assert receipt["activated"] is True
    assert receipt["review_digest"] == review_digest
    assert (
        receipt["manifest_digest"]
        == hashlib.sha256((kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()).hexdigest()
    )

    # The sealed private binding still pins A, never the newer B.
    sealed = _sealed(destination, revision)
    assert sealed["namespace"] == NAMESPACE
    assert sealed["bindings"]["entity:workbench-press"]["operator-manual"] == A_DIGEST

    # No raw source bytes ever entered the publication destination.
    for path in destination.rglob("*"):
        if path.is_file():
            raw = path.read_bytes()
            assert b"green button" not in raw
            assert b"BLUE button" not in raw

    # Readers resolve ONE immutable Snapshot labelled with the version.
    snapshot = PublishedFilesystemLocation(destination).resolve()
    assert snapshot.published_version == revision
    entity_ids = {page.id for page in snapshot.pages}
    assert {"entity:hydraulic-press", "entity:steel-blank", "entity:workbench-press"} <= entity_ids
    press = next(page for page in snapshot.pages if page.id == "entity:workbench-press")
    assert [claim.id for claim in press.claims] == ["claim:workbench-rated"]
    assert press.claims[0].value == "5 tons"
    # The Evidence anchor resolves against the captured section content.
    assert "five tons" in press.body
    # Plain filesystem loading stays version-free: never silently admitted.
    plain = FilesystemLocation(kb).resolve()
    assert plain.published_version is None

    # --- Identical retry: existing verified receipt, no byte rewrite. ---
    manifest_before = (version_dir / "manifest.json").read_bytes()
    receipt_again = publish_revision(
        kb,
        revision,
        destination,
        "none",
        review_digest,
        source_registry=registry,
    )
    assert receipt_again.review_digest == review_digest
    assert (version_dir / "manifest.json").read_bytes() == manifest_before
    capsys.readouterr()

    # --- Successor publication: new commit, old confirmation refused. ---
    (kb / "concepts" / "uncommitted.md").unlink()
    press_page = kb / "concepts" / "workbench_press.md"
    press_page.write_text(
        _authored_ingest_page("operator-manual")
        .replace("Rated at five tons", "Rated at six tons")
        .replace('"draft"', '"approved"')
    )
    revision2 = _commit(repo)
    assert revision2 != revision
    code = main(
        [
            "publish",
            str(kb),
            "--revision",
            revision2,
            "--to",
            str(destination),
            "--expected-current",
            revision,
            "--confirm",
            review_digest,
            "--source-registry",
            str(registry.root),
        ]
    )
    assert code == 1
    assert "no longer matches" in capsys.readouterr().err

    # The pointer moved? No: it never advanced; a wrong expected-current
    # baseline is a conflict, and 'none' now conflicts with the active version.
    with pytest.raises(PublicationConflict):
        preview_publication(kb, revision2, destination, "none", source_registry=registry)
    review2 = preview_publication(kb, revision2, destination, revision, source_registry=registry)
    assert review2.observed_current == revision
    assert review2.adoption == f"successor to admitted Published Version {revision!r}"
    assert "changed: concepts/workbench_press.md" in review2.page_mutations
    receipt2 = publish_revision(
        kb,
        revision2,
        destination,
        revision,
        review2.review_digest,
        source_registry=registry,
    )
    assert receipt2.activated is True
    assert PublishedFilesystemLocation(destination).read_pointer() == revision2
    # The previously resolved Snapshot remains unchanged after activation.
    assert snapshot.published_version == revision
    assert (
        "five tons"
        in next(page for page in snapshot.pages if page.id == "entity:workbench-press").body
    )

    # --- Retry of v1 must not reactivate over the advanced pointer. ---
    retry1 = publish_revision(
        kb, revision, destination, "none", review_digest, source_registry=registry
    )
    assert retry1.activated is True  # preserves the original successful admission fact
    assert PublishedFilesystemLocation(destination).read_pointer() == revision2

    # --- Local rollback: preview, confirmation, explicit baseline. ---
    rollback_review = preview_rollback(destination, revision, expected_current=revision2)
    rollback_publication(destination, revision, revision2, rollback_review.review_digest)
    assert PublishedFilesystemLocation(destination).read_pointer() == revision
    rolled = PublishedFilesystemLocation(destination).resolve()
    assert rolled.published_version == revision
    assert (
        "five tons"
        in next(page for page in rolled.pages if page.id == "entity:workbench-press").body
    )
    # A stale rollback fails closed and leaves the pointer untouched.
    with pytest.raises(PublicationConflict):
        preview_rollback(destination, revision2, expected_current=revision2)
    assert PublishedFilesystemLocation(destination).read_pointer() == revision


def test_local_lancedb_publication_read_and_rollback(tmp_path: Path, capsys) -> None:
    lumio_lancedb = pytest.importorskip("lumio_lancedb")
    repo = _init_repo(tmp_path)
    pages = {
        "concepts/hydraulic-press.md": _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
            body_sections="## Overview\n\nA copper lens transfers force.\n",
            sources_yaml="  []\n",
        ).replace("sources:\n  []\n", "sources:\n  []\nsynthetic: true\n"),
        "concepts/steel-blank.md": _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            sources_yaml="  []\n",
        ).replace("sources:\n  []\n", "sources:\n  []\nsynthetic: true\n"),
    }
    kb = _write_kb(repo, pages=pages)
    destination = tmp_path / "published"
    revision_a = _commit(repo)

    def publish(revision: str, expected_current: str) -> None:
        args = [
            "publish",
            str(kb),
            "--revision",
            revision,
            "--to",
            str(destination),
            "--expected-current",
            expected_current,
            "--retrieval",
            "lancedb",
            "--json",
        ]
        assert main(args) == 0
        review = json.loads(capsys.readouterr().out)
        assert "derived/lance" in review["requested_artifacts"]
        confirm_args = [arg for arg in args if arg != "--json"]
        rc = main([*confirm_args, "--confirm", review["review_digest"]])
        confirmed = capsys.readouterr()
        assert rc == 0, confirmed.err
        assert f"Admitted Published Version {revision}" in confirmed.out
        assert "activated:      True" in confirmed.out

    publish(revision_a, "none")
    revision_b_page = kb / "concepts" / "hydraulic-press.md"
    revision_b_page.write_text(
        revision_b_page.read_text(encoding="utf-8").replace("copper lens", "silver lens"),
        encoding="utf-8",
    )
    revision_b = _commit(repo)
    publish(revision_b, revision_a)

    snapshot_b = PublishedFilesystemLocation(destination).resolve()
    assert snapshot_b.published_version == revision_b
    assert snapshot_b.index_dir == (destination / "versions" / revision_b / "derived" / "lance")
    manifest_b = PublishedFilesystemLocation(destination).read_manifest(revision_b)
    index_files = [
        item for item in manifest_b.derived_files if item.path.startswith("derived/lance/")
    ]
    assert len(index_files) > 1
    assert any(item.path.endswith("completion.json") for item in index_files)
    for item in index_files:
        raw = (destination / "versions" / revision_b / item.path).read_bytes()
        assert len(raw) == item.size
        assert hashlib.sha256(raw).hexdigest() == item.digest

    adapter = lumio_lancedb.LanceDBRetrievalAdapter()
    results_b = adapter.retrieve(
        snapshot_b.pages,
        "silver",
        index_dir=snapshot_b.index_dir,
        expected_fingerprint=snapshot_b.fingerprint,
    )
    assert any(result.citation.page_title == "Hydraulic Press" for result in results_b)

    rollback_args = [
        "rollback",
        str(destination),
        "--version",
        revision_a,
        "--expected-current",
        revision_b,
        "--json",
    ]
    assert main(rollback_args) == 0
    rollback_review = json.loads(capsys.readouterr().out)
    assert main([*rollback_args, "--confirm", rollback_review["review_digest"]]) == 0
    capsys.readouterr()

    snapshot_a = PublishedFilesystemLocation(destination).resolve()
    assert snapshot_a.published_version == revision_a
    assert snapshot_a.index_dir == (destination / "versions" / revision_a / "derived" / "lance")
    results_a = adapter.retrieve(
        snapshot_a.pages,
        "copper",
        index_dir=snapshot_a.index_dir,
        expected_fingerprint=snapshot_a.fingerprint,
    )
    assert any(result.citation.page_title == "Hydraulic Press" for result in results_a)


def test_local_published_source_inspection_uses_sealed_bindings_without_raw_store(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source_id = "operator-manual"
    raw = b"Private source bytes retained only in the authoring registry."
    registry = SourceRegistry(tmp_path / "registry")
    version, _action = registry.register_version(source_id, raw, filename="manual.txt")
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={source_id: "active"},
        bindings={"entity:hydraulic-press": {source_id: version.content_hash}},
    )
    pages = {
        "concepts/hydraulic-press.md": _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            sources_yaml='  - id: "operator-manual"\n    title: "Manual"\n',
        ),
        "concepts/steel-blank.md": _entity_page(
            "Steel Blank", "entity:steel-blank", ["material"], sources_yaml="  []\n"
        ).replace("sources:\n  []\n", "sources:\n  []\nsynthetic: true\n"),
    }
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision = _commit(repo)
    destination = tmp_path / "published"
    review = preview_publication(kb, revision, destination, "none", source_registry=registry)
    publish_revision(
        kb,
        revision,
        destination,
        "none",
        review.review_digest,
        source_registry=registry,
    )
    monkeypatch.delenv("LUMIO_SOURCE_STORE", raising=False)

    assert (
        main(
            [
                "source",
                "inspect",
                str(destination),
                "--source-id",
                source_id,
                "--published-version",
                revision,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "entity_id:       entity:hydraulic-press" in out
    assert f"local Published Version {revision} (sealed source bindings)" in out
    assert "not retained (no Source Artifact Store configured)" in out
    assert raw.decode() not in out

    assert (
        main(
            [
                "source",
                "resolve",
                str(destination),
                "Hydraulic Press",
                "--published-version",
                revision,
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["entity_id"] == "entity:hydraulic-press"
    assert result["published_version"] == revision
    assert "--entity-id" in result["next"]
    assert revision in result["next"]


# ---------------------------------------------------------------------------
# Invalid authored content: specific collected blocking failures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        "dangling-claim-object",
        "bad-evidence-anchor",
        "broken-internal-link",
        "unregistered-binding-digest",
        "missing-required-binding",
    ],
)
def test_publish_collects_blocking_diagnostics_for_invalid_candidates(tmp_path, mutation):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version("operator-manual", A_BYTES)
    pages = {
        "concepts/hydraulic-press.md": _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
        ),
        "concepts/steel-blank.md": _entity_page("Steel Blank", "entity:steel-blank", ["material"]),
        "concepts/workbench_press.md": _authored_ingest_page("operator-manual"),
    }
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"operator-manual": "active"},
        bindings={"entity:workbench-press": {"operator-manual": A_DIGEST}},
    )
    if mutation == "dangling-claim-object":
        pages["concepts/hydraulic-press.md"] = _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim("entity:missing-target"),
        )
        expected = "dangling object"
    elif mutation == "bad-evidence-anchor":
        pages["concepts/hydraulic-press.md"] = _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim().replace('section: "Overview"', 'section: "Nowhere"'),
        )
        expected = "evidence"
    elif mutation == "broken-internal-link":
        pages["concepts/steel-blank.md"] = _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nSee [[Ghost Page]] for details.\n",
        )
        expected = "broken internal link"
    elif mutation == "unregistered-binding-digest":
        manifest = SourceReferenceManifest(
            version=1,
            namespace=NAMESPACE,
            sources={"operator-manual": "active"},
            bindings={"entity:workbench-press": {"operator-manual": ZERO_DIGEST}},
        )
        expected = "does not resolve to an exact registered Source Version"
    else:  # missing-required-binding
        manifest = SourceReferenceManifest(
            version=1,
            namespace=NAMESPACE,
            sources={"operator-manual": "active"},
            bindings={},
        )
        expected = "requires an exact binding"
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none", source_registry=registry)
    assert review.blocking_diagnostics, mutation
    assert any(expected in diagnostic for diagnostic in review.blocking_diagnostics), (
        review.blocking_diagnostics
    )
    with pytest.raises(GitAuthoringError, match="blocking diagnostics"):
        publish_revision(
            kb,
            revision,
            tmp_path / "dest",
            "none",
            review.review_digest,
            source_registry=registry,
        )
    # Refusal never created a version directory, pointer, or receipt.
    assert not (tmp_path / "dest").exists()


def test_managed_bindings_require_an_explicitly_selected_registry(tmp_path):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version("operator-manual", A_BYTES)
    pages = {
        "concepts/workbench_press.md": _authored_ingest_page("operator-manual"),
    }
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"operator-manual": "active"},
        bindings={"entity:workbench-press": {"operator-manual": A_DIGEST}},
    )
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none")
    assert any(
        "no private source registry is selected" in diagnostic
        for diagnostic in review.blocking_diagnostics
    )


# ---------------------------------------------------------------------------
# Failed preparation preserves prior readers and refuses residue.
# ---------------------------------------------------------------------------


def test_failed_preparation_preserves_the_prior_complete_version(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision1 = _commit(repo)
    review1 = preview_publication(kb, revision1, tmp_path / "dest", "none")
    publish_revision(
        kb,
        revision1,
        tmp_path / "dest",
        "none",
        review1.review_digest,
        source_registry=registry,
    )
    prior_snapshot = PublishedFilesystemLocation(tmp_path / "dest").resolve()

    (kb / "concepts" / "hydraulic-press.md").write_text(
        _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
            body_sections="## Overview\n\nSecond revision of the overview.\n",
        )
    )
    revision2 = _commit(repo)
    review2 = preview_publication(
        kb, revision2, tmp_path / "dest", revision1, source_registry=registry
    )

    # Sabotage preparation: the immutable version directory path is occupied.
    blocker = tmp_path / "dest" / "versions" / revision2
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_bytes(b"not a directory")
    with pytest.raises(GitAuthoringError):
        publish_revision(
            kb,
            revision2,
            tmp_path / "dest",
            revision1,
            review2.review_digest,
            source_registry=registry,
        )
    # Old readers still see ONLY the prior complete version, and the failed
    # preparation wrote no receipt at all for the unadmitted revision.
    pointer = PublishedFilesystemLocation(tmp_path / "dest").read_pointer()
    assert pointer == revision1
    assert prior_snapshot.published_version == revision1
    failed_receipt = tmp_path / "dest" / ".lumio-publication" / "receipts" / f"{revision2}.json"
    assert not failed_receipt.exists()

    # An incomplete version residue is refused, then an explicit cleanup
    # lets the same confirmed review succeed.
    blocker.unlink()
    (tmp_path / "dest" / "versions" / revision2).mkdir()
    (tmp_path / "dest" / "versions" / revision2 / "lumio.yaml").write_text("residue")
    with pytest.raises(GitAuthoringError, match="incomplete version directory"):
        publish_revision(
            kb,
            revision2,
            tmp_path / "dest",
            revision1,
            review2.review_digest,
            source_registry=registry,
        )
    shutil.rmtree(tmp_path / "dest" / "versions" / revision2)
    receipt2 = publish_revision(
        kb,
        revision2,
        tmp_path / "dest",
        revision1,
        review2.review_digest,
        source_registry=registry,
    )
    assert receipt2.activated is True
    assert PublishedFilesystemLocation(tmp_path / "dest").read_pointer() == revision2


# ---------------------------------------------------------------------------
# Edited authoring files: the commit is the truth, not the worktree.
# ---------------------------------------------------------------------------


def test_edited_authoring_files_never_replace_captured_commit_bytes(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none")
    publish_revision(
        kb,
        revision,
        tmp_path / "dest",
        "none",
        review.review_digest,
        source_registry=registry,
    )

    # Uncommitted edits to the authoring worktree never leak into the
    # publication of the reviewed revision.
    hydraulic = kb / "concepts" / "hydraulic-press.md"
    hydraulic.write_text(
        _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
            body_sections="## Overview\n\nDirty uncommitted rewrite of the overview.\n",
        )
    )
    retry = publish_revision(
        kb,
        revision,
        tmp_path / "dest",
        "none",
        review.review_digest,
        source_registry=registry,
    )
    assert retry.activated is True
    published_press = tmp_path / "dest" / "versions" / revision / "concepts" / "hydraulic-press.md"
    assert b"Dirty uncommitted rewrite" not in published_press.read_bytes()
    assert "Dirty uncommitted rewrite" in hydraulic.read_text()

    # A NEW commit changes the review-bound facts: the old confirmation is
    # refused, and the edited files alone prove nothing.
    revision2 = _commit(repo)
    with pytest.raises(ConfirmationRefused):
        publish_revision(
            kb,
            revision2,
            tmp_path / "dest",
            revision,
            review.review_digest,
            source_registry=registry,
        )


def test_an_admitted_namespace_cannot_change_in_a_successor(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision1 = _commit(repo)
    review1 = preview_publication(kb, revision1, tmp_path / "dest", "none")
    publish_revision(
        kb,
        revision1,
        tmp_path / "dest",
        "none",
        review1.review_digest,
        source_registry=registry,
    )
    other_namespace = "urn:uuid:aaaaaaaa-bbbb-4ccc-8ddd-000000000001"
    other = SourceReferenceManifest(version=1, namespace=other_namespace)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(other)
    )
    revision2 = _commit(repo)
    with pytest.raises(GitAuthoringError, match="namespace cannot change"):
        preview_publication(kb, revision2, tmp_path / "dest", revision1)


# ---------------------------------------------------------------------------
# Capture refusals: symlinks, tracked private stores, floating references.
# ---------------------------------------------------------------------------


def test_capture_refuses_non_regular_and_private_git_paths(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    # A tracked private ingest store under the Knowledge Base subtree.
    private = kb / ".lumio" / "ingest" / "proposals"
    private.mkdir(parents=True)
    (private / "p.json").write_text("{}")
    revision = _commit(repo)
    with pytest.raises(GitAuthoringError, match="private ingest store"):
        preview_publication(kb, revision, tmp_path / "dest", "none")

    # Clean the store, add a symlink at a canonical position instead.
    shutil.rmtree(kb / ".lumio")
    link = kb / "concepts" / "alias.md"
    link.symlink_to("hydraulic-press.md")
    revision2 = _commit(repo)
    with pytest.raises(GitAuthoringError, match="not a regular file"):
        preview_publication(kb, revision2, tmp_path / "dest", "none")


def test_only_full_commit_ids_can_be_confirmed(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    with pytest.raises(GitAuthoringError, match="FULL commit id"):
        preview_publication(kb, "main", tmp_path / "dest", "none")


# ---------------------------------------------------------------------------
# Managed ingest refusals preserve the author's files exactly.
# ---------------------------------------------------------------------------


def test_managed_ingest_refusals_preserve_author_files(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    before = {p.relative_to(kb).as_posix(): p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    source_file = tmp_path / "manual.txt"
    source_file.write_bytes(A_BYTES)
    compiled = tmp_path / "press.md"
    compiled.write_text(_authored_ingest_page("some-other-source"))

    from lumio_wiki.git_authoring import ingest_into_worktree

    with pytest.raises(Exception, match="must declare"):
        ingest_into_worktree(
            kb,
            A_BYTES,
            "text/plain",
            "manual.txt",
            "operator-manual",
            compiled.read_text(),
            source_registry=registry,
        )
    after = {p.relative_to(kb).as_posix(): p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    assert after == before

    # A registry selected INSIDE the authoring subtree is refused (§3.2).
    inside = kb / "registry"
    inside.mkdir()
    with pytest.raises(GitAuthoringError, match="OUTSIDE"):
        ingest_into_worktree(
            kb,
            A_BYTES,
            "text/plain",
            "manual.txt",
            "operator-manual",
            _authored_ingest_page("operator-manual"),
            source_registry=SourceRegistry(inside),
        )
    assert after == before


def test_present_but_invalid_manifest_never_falls_back_to_legacy_staging(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_text(
        "version: 1\nversion: 2\nnamespace: x\nsources: {}\nbindings: {}\n"
    )
    source_file = tmp_path / "manual.txt"
    source_file.write_bytes(A_BYTES)
    compiled = tmp_path / "press.md"
    compiled.write_text(_authored_ingest_page("operator-manual"))
    code = main(
        [
            "ingest",
            str(kb),
            str(source_file),
            "--compiled-page",
            str(compiled),
            "--source-id",
            "operator-manual",
            "--source-registry",
            str(tmp_path / "registry"),
        ]
    )
    assert code == 1
    assert "never a fallback" in capsys.readouterr().err
    assert not (kb / ".lumio").exists()


# ---------------------------------------------------------------------------
# Reader seam: fail closed on corruption, never fall back to a worktree.
# ---------------------------------------------------------------------------


def test_published_reader_fails_closed_on_corruption(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none")
    publish_revision(
        kb,
        revision,
        tmp_path / "dest",
        "none",
        review.review_digest,
        source_registry=registry,
    )
    destination = tmp_path / "dest"

    from lumio_wiki.knowledge_base import KnowledgeBaseError

    page_file = destination / "versions" / revision / "concepts" / "steel-blank.md"
    page_file.write_bytes(page_file.read_bytes() + b"\ncorrupted\n")
    with pytest.raises(KnowledgeBaseError, match="manifest size"):
        PublishedFilesystemLocation(destination).resolve()

    missing_pointer = tmp_path / "other-dest"
    missing_pointer.mkdir()
    with pytest.raises(KnowledgeBaseError, match="no published version pointer"):
        PublishedFilesystemLocation(missing_pointer).resolve()

    pinned = PublishedFilesystemLocation(destination, version=revision)
    assert pinned.describe().endswith(revision)


# ---------------------------------------------------------------------------
# A legacy-flat Knowledge Base adopts Git authoring source-free (§3.1).
# ---------------------------------------------------------------------------


def test_legacy_flat_kb_adopts_git_authoring_source_free(tmp_path):
    repo = _init_repo(tmp_path)
    flat_pages = {
        "overview.md": (
            "---\n"
            'title: "Overview"\n'
            'tags:\n  - "test"\n'
            'summary: "Overview."\n'
            'lifecycle: "approved"\n'
            'visibility: "public"\n'
            'sources:\n  - id: "src-overview"\n    title: "Overview Source"\n'
            "---\n\nOverview body.\n"
        )
    }
    kb = _write_kb(repo, control=None, pages=flat_pages)
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none")
    assert review.blocking_diagnostics == []
    assert review.source_refs == []
    receipt = publish_revision(kb, revision, tmp_path / "dest", "none", review.review_digest)
    assert receipt.activated is True
    snapshot = PublishedFilesystemLocation(tmp_path / "dest").resolve()
    assert [page.title for page in snapshot.pages] == ["Overview"]
    # The Knowledge Base itself still loads the plain way, unlabelled.
    kb_loaded, report = load_knowledge_base(kb)
    assert report.is_valid


# ---------------------------------------------------------------------------
# The strict v1 manifest contract (spec 0008 §3.1).
# ---------------------------------------------------------------------------


def test_manifest_rejects_duplicate_keys_unknown_fields_and_malformed_values():
    base = {
        "version": 1,
        "namespace": NAMESPACE,
        "sources": {"operator-manual": "active"},
        "bindings": {"entity:press": {"operator-manual": A_DIGEST}},
    }

    def render(**overrides):
        data = {**base, **overrides}
        lines = [
            f"version: {data['version']}",
            f'namespace: "{data["namespace"]}"',
            "sources:",
        ]
        for source_id, status in data["sources"].items():
            lines.append(f"  {source_id}:")
            lines.append(f"    status: {status}")
        lines.append("bindings:")
        for entity_id, entity_bindings in data["bindings"].items():
            lines.append(f'  "{entity_id}":')
            for source_id, digest in entity_bindings.items():
                lines.append(f"    {source_id}: {digest}")
        return ("\n".join(lines) + "\n").encode()

    good = parse_source_reference_manifest(render())
    assert good.bindings["entity:press"]["operator-manual"] == A_DIGEST

    from lumio_wiki.source_references import SourceReferenceError

    with pytest.raises(SourceReferenceError, match="duplicate key"):
        parse_source_reference_manifest(render() + b"version: 2\n")
    with pytest.raises(SourceReferenceError, match="duplicate key"):
        nested_dup = (
            b"version: 1\n"
            + f'namespace: "{NAMESPACE}"\n'.encode()
            + b'sources: {}\nbindings:\n  "entity:press":\n'
            + f"    operator-manual: {A_DIGEST}\n".encode()
            + f"    operator-manual: {A_DIGEST}\n".encode()
        )
        parse_source_reference_manifest(nested_dup)
    with pytest.raises(SourceReferenceError, match="unknown manifest field"):
        parse_source_reference_manifest(render() + b"extra: 1\n")
    with pytest.raises(SourceReferenceError, match="unsupported manifest version"):
        parse_source_reference_manifest(render(version=2))
    with pytest.raises(SourceReferenceError, match="64-character"):
        parse_source_reference_manifest(
            render(bindings={"entity:press": {"operator-manual": "abc"}})
        )
    with pytest.raises(SourceReferenceError, match="retired"):
        parse_source_reference_manifest(render(sources={"operator-manual": "retired"}))
    with pytest.raises(SourceReferenceError, match="undeclared source"):
        parse_source_reference_manifest(
            render(bindings={"entity:press": {"unknown-src": A_DIGEST}})
        )
    with pytest.raises(SourceReferenceError, match="flow styles"):
        parse_source_reference_manifest(render(sources={}) + b"  x: [a, b]\n")
    with pytest.raises(SourceReferenceError, match="missing required"):
        parse_source_reference_manifest(b'namespace: "x"\nsources: {}\nbindings: {}\n')

    # Canonical serialization round-trips with sorted keys.
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"b-source": "retired", "a-source": "active"},
        bindings={"entity:z": {"a-source": A_DIGEST}, "entity:a": {}},
    )
    raw = serialize_source_reference_manifest(manifest)
    text = raw.decode()
    assert text.index("a-source") < text.index("b-source")
    assert text.index("entity:a") < text.index("entity:z")
    reparsed = parse_source_reference_manifest(raw)
    assert reparsed.sources == manifest.sources
    assert reparsed.bindings == manifest.bindings


# ---------------------------------------------------------------------------
# Fix-pass regressions (reviewer findings 1–17, spec/plan 0008 r2). Wave 1
# cases use the frozen 21ea036 API and are observed red before the repair;
# expectations derive from the spec, not implementation output.
# ---------------------------------------------------------------------------


def _two_source_page(entity_id: str, title: str, source_ids: list[str]) -> str:
    types_yaml = "  - press\n"
    sources_yaml = "".join(f'  - id: "{s}"\n    title: "{s} source"\n' for s in source_ids)
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        f"entity_types:\n{types_yaml}"
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        f"sources:\n{sources_yaml}"
        "---\n\n"
        f"# {title}\n\n## Overview\n\n{title} body.\n"
    )


def test_f12_repository_root_kb_publishes(tmp_path):
    repo = _init_repo(tmp_path)
    kb = repo  # the KB subtree IS the repository root
    (kb / "lumio.yaml").write_text(CONTROL_V2)
    (kb / "concepts").mkdir()
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _entity_page(
            "Hydraulic Press", "entity:hydraulic-press", ["press"], claims_yaml=_presses_claim()
        )
    )
    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page("Steel Blank", "entity:steel-blank", ["material"])
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none")
    assert review.blocking_diagnostics == []
    receipt = publish_revision(kb, revision, tmp_path / "dest", "none", review.review_digest)
    assert receipt.activated is True
    snapshot = PublishedFilesystemLocation(tmp_path / "dest").resolve()
    assert {page.id for page in snapshot.pages} == {"entity:hydraulic-press", "entity:steel-blank"}


def test_f1_ingest_preserves_uncommitted_author_edits(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    registry = SourceRegistry(tmp_path / "registry")

    # The author has uncommitted edits at the destination the ingest would write.
    dirty = kb / "concepts" / "hydraulic-press.md"
    original = dirty.read_bytes()
    dirty.write_text(original.decode() + "\nUncommitted author note.\n")

    authored = (
        _authored_ingest_page("operator-manual")
        .replace('id: "entity:workbench-press"', 'id: "entity:hydraulic-press"')
        .replace('title: "Workbench Press"', 'title: "Hydraulic Press"')
    )
    from lumio_wiki.git_authoring import ingest_into_worktree

    with pytest.raises(GitAuthoringError, match="uncommitted"):
        ingest_into_worktree(
            kb,
            A_BYTES,
            "text/plain",
            "manual.txt",
            "operator-manual",
            authored,
            source_registry=registry,
        )
    assert "Uncommitted author note." in dirty.read_text()


@pytest.mark.parametrize("status_mode", ["ignored", "hidden-untracked"])
def test_r1_ingest_refuses_existing_unreported_destination_before_registration(
    tmp_path, status_mode
):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    relative = "kb/concepts/workbench_press.md"
    if status_mode == "ignored":
        (repo / ".gitignore").write_text(f"/{relative}\n")
    _commit(repo)
    if status_mode == "hidden-untracked":
        _git(repo, "config", "status.showUntrackedFiles", "no")

    destination = repo / relative
    destination.write_text(_authored_ingest_page("operator-manual"))
    assert _git(repo, "status", "--porcelain", "--", relative) == ""
    if status_mode == "ignored":
        _git(repo, "check-ignore", "-q", relative)

    original_page = destination.read_bytes()
    original_manifest = (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
    registry = SourceRegistry(tmp_path / "registry")
    from lumio_wiki.git_authoring import ingest_into_worktree

    with pytest.raises(GitAuthoringError, match="uncommitted"):
        ingest_into_worktree(
            kb,
            A_BYTES,
            "text/plain",
            "manual.txt",
            "operator-manual",
            _authored_ingest_page("operator-manual"),
            source_registry=registry,
        )

    assert destination.read_bytes() == original_page
    assert (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes() == original_manifest
    assert registry.find_version("operator-manual", A_DIGEST) is None


def test_r1_ingest_allows_absent_destination_below_ignored_parent(tmp_path):
    repo = _init_repo(tmp_path)
    kb = repo / "kb"
    kb.mkdir()
    (kb / "lumio.yaml").write_text(CONTROL_V2)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    (repo / ".gitignore").write_text("/kb/concepts/\n")
    _commit(repo)

    (kb / "concepts").mkdir()
    relative = "kb/concepts/workbench_press.md"
    assert _git(
        repo,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--ignored=matching",
        "--",
        relative,
    ).startswith("!!")
    registry = SourceRegistry(tmp_path / "registry")
    from lumio_wiki.git_authoring import ingest_into_worktree

    ingest_into_worktree(
        kb,
        A_BYTES,
        "text/plain",
        "manual.txt",
        "operator-manual",
        _authored_ingest_page("operator-manual"),
        source_registry=registry,
    )

    assert (kb / "concepts" / "workbench_press.md").is_file()
    assert registry.find_version("operator-manual", A_DIGEST) is not None


def test_f1_ingest_requires_a_git_worktree(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    plain = tmp_path / "plain"
    shutil.copytree(kb, plain)
    registry = SourceRegistry(tmp_path / "registry")
    from lumio_wiki.git_authoring import ingest_into_worktree

    with pytest.raises(GitAuthoringError):
        ingest_into_worktree(
            plain,
            A_BYTES,
            "text/plain",
            "manual.txt",
            "operator-manual",
            _authored_ingest_page("operator-manual"),
            source_registry=registry,
        )
    assert not (plain / "concepts" / "workbench_press.md").exists()


def test_f2_obsolete_branch_requires_git_reconciliation(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    base = _commit(repo)
    review = preview_publication(kb, base, tmp_path / "dest", "none")
    publish_revision(kb, base, tmp_path / "dest", "none", review.review_digest)

    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nB edit.\n",
        )
    )
    revision_b = _commit(repo)
    review_b = preview_publication(kb, revision_b, tmp_path / "dest", base)
    publish_revision(kb, revision_b, tmp_path / "dest", base, review_b.review_digest)
    _git(repo, "checkout", "-q", "-b", "side", base)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
            body_sections="## Overview\n\nC edit.\n",
        )
    )
    revision_c = _commit(repo)

    # C diverged from the admitted B without Git reconciliation.
    with pytest.raises(GitAuthoringError, match="reconcil"):
        preview_publication(kb, revision_c, tmp_path / "dest", revision_b)
    # A historical commit is not an ordinary successor either.
    with pytest.raises(GitAuthoringError, match="reconcil"):
        preview_publication(kb, base, tmp_path / "dest", revision_b)
    # Reconciling C with B creates a commit that descends from the admitted
    # revision and can proceed as an ordinary successor.
    _git(repo, "merge", "-q", "--no-edit", revision_b)
    reconciled = _git(repo, "rev-parse", "HEAD")
    reconciled_review = preview_publication(kb, reconciled, tmp_path / "dest", revision_b)
    assert publish_revision(
        kb, reconciled, tmp_path / "dest", revision_b, reconciled_review.review_digest
    ).activated


def test_f3_sdk_requires_an_explicit_expected_current(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    revision = _commit(repo)
    with pytest.raises(GitAuthoringError, match="expected-current"):
        preview_publication(kb, revision, tmp_path / "dest", None)


def test_f4_required_retention_without_store_fails_closed(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version("operator-manual", A_BYTES)
    pages = {"concepts/workbench_press.md": _authored_ingest_page("operator-manual")}
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"operator-manual": "active"},
        bindings={"entity:workbench-press": {"operator-manual": A_DIGEST}},
    )
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision = _commit(repo)

    from lumio_wiki.git_authoring import PublicationRetentionError, preview_publication

    review = preview_publication(
        kb,
        revision,
        tmp_path / "dest",
        "none",
        source_registry=registry,
        retention_required=True,
    )
    digest = review.review_digest
    with pytest.raises(PublicationRetentionError):
        publish_revision(
            kb,
            revision,
            tmp_path / "dest",
            "none",
            digest,
            source_registry=registry,
            retention_required=True,
        )
    assert not (tmp_path / "dest").exists()

    monkeypatch.setenv("LUMIO_ARTIFACT_RETENTION", "required")
    monkeypatch.delenv("LUMIO_SOURCE_STORE", raising=False)
    code = main(
        [
            "publish",
            str(kb),
            "--revision",
            revision,
            "--to",
            str(tmp_path / "dest"),
            "--expected-current",
            "none",
            "--confirm",
            digest,
            "--source-registry",
            str(registry.root),
        ]
    )
    assert code == 1
    assert "retention" in capsys.readouterr().err.lower()
    assert not (tmp_path / "dest").exists()


def test_f5_managed_identity_cannot_disappear_manifest_only(tmp_path):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version("operator-manual", A_BYTES)
    pages = {"concepts/workbench_press.md": _authored_ingest_page("operator-manual")}
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"operator-manual": "active"},
        bindings={"entity:workbench-press": {"operator-manual": A_DIGEST}},
    )
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision1 = _commit(repo)
    review1 = preview_publication(
        kb, revision1, tmp_path / "dest", "none", source_registry=registry
    )
    publish_revision(
        kb, revision1, tmp_path / "dest", "none", review1.review_digest, source_registry=registry
    )

    # Manifest-only deletion: the page still cites the managed source, but the
    # manifest drops the source entry and binding to evade the support gate.
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    revision2 = _commit(repo)
    review2 = preview_publication(
        kb, revision2, tmp_path / "dest", revision1, source_registry=registry
    )
    assert any("disappear" in d or "retained" in d for d in review2.blocking_diagnostics), (
        review2.blocking_diagnostics
    )
    with pytest.raises(GitAuthoringError, match="blocking diagnostics"):
        publish_revision(
            kb,
            revision2,
            tmp_path / "dest",
            revision1,
            review2.review_digest,
            source_registry=registry,
        )


def test_f7_cli_reads_one_pointer_pinned_local_snapshot(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    revision1 = _commit(repo)
    review1 = preview_publication(kb, revision1, tmp_path / "dest", "none")
    publish_revision(kb, revision1, tmp_path / "dest", "none", review1.review_digest)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _entity_page(
            "Hydraulic Press",
            "entity:hydraulic-press",
            ["press"],
            claims_yaml=_presses_claim(),
            body_sections="## Overview\n\nSecond publication body.\n",
        )
    )
    revision2 = _commit(repo)
    review2 = preview_publication(kb, revision2, tmp_path / "dest", revision1)
    publish_revision(kb, revision2, tmp_path / "dest", revision1, review2.review_digest)

    code = main(["page", str(tmp_path / "dest"), "Hydraulic Press"])
    assert code == 0
    out = capsys.readouterr().out
    assert out.count("path:") == 1, out
    assert "Second publication body." in out
    assert "Overview paragraph." not in out
    assert revision2 in out  # the active immutable version's path

    code = main(["validate", str(tmp_path / "dest")])
    assert code == 0

    pointer = tmp_path / "dest" / "current.json"
    pointer.write_text("{corrupt")
    code = main(["page", str(tmp_path / "dest"), "Hydraulic Press"])
    assert code == 1
    capsys.readouterr()

    pointer.unlink()
    code = main(["page", str(tmp_path / "dest"), "Hydraulic Press"])
    assert code == 1
    assert "no published version pointer" in capsys.readouterr().err

    pointer.write_text(json.dumps({"version": "f" * 40}))
    code = main(["page", str(tmp_path / "dest"), "Hydraulic Press"])
    assert code == 1  # a missing version never falls back to recursive loading


def test_r2_plain_versions_v1_kb_remains_readable_and_valid(tmp_path, capsys):
    kb = tmp_path / "plain-kb"
    page = kb / "versions" / "v1" / "overview.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        'title: "Overview"\n'
        'tags:\n  - "test"\n'
        'summary: "Overview."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        'sources:\n  - id: "src-overview"\n    title: "Overview Source"\n'
        "---\n\nOverview body.\n"
    )
    assert not (kb / "current.json").exists()
    assert not (page.parent / "manifest.json").exists()
    assert not (kb / ".lumio-publication").exists()
    _plain_kb, report = load_knowledge_base(kb)
    assert report.is_valid, report

    assert main(["validate", str(kb)]) == 0
    capsys.readouterr()
    assert main(["page", str(kb), "Overview"]) == 0
    assert "Overview body." in capsys.readouterr().out


def test_f8_recovery_enforces_changed_policy_and_private_completeness(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none")
    publish_revision(kb, revision, tmp_path / "dest", "none", review.review_digest)

    def _simulate_interrupted_activation(destination: Path) -> None:
        receipt_file = destination / ".lumio-publication" / "receipts" / f"{revision}.json"
        receipt = json.loads(receipt_file.read_bytes())
        receipt["activated"] = False
        receipt_file.write_bytes(json.dumps(receipt).encode())
        (destination / "current.json").unlink()

    # A genuinely never-activated attempt against its bound baseline recovers.
    _simulate_interrupted_activation(tmp_path / "dest")
    recovered = publish_revision(kb, revision, tmp_path / "dest", "none", review.review_digest)
    assert recovered.activated is True
    assert PublishedFilesystemLocation(tmp_path / "dest").read_pointer() == revision

    # A changed retention policy between admission and recovery refuses.
    dest2 = tmp_path / "dest2"
    review2 = preview_publication(kb, revision, dest2, "none")
    publish_revision(kb, revision, dest2, "none", review2.review_digest)
    _simulate_interrupted_activation(dest2)
    with pytest.raises(ConfirmationRefused, match="retention"):
        publish_revision(
            kb, revision, dest2, "none", review2.review_digest, retention_required=True
        )

    # Missing sealed private bindings refuse the recovery.
    dest3 = tmp_path / "dest3"
    review3 = preview_publication(kb, revision, dest3, "none")
    publish_revision(kb, revision, dest3, "none", review3.review_digest)
    _simulate_interrupted_activation(dest3)
    (dest3 / ".lumio-publication" / "bindings" / f"{revision}.json").unlink()
    with pytest.raises(GitAuthoringError, match="sealed"):
        publish_revision(kb, revision, dest3, "none", review3.review_digest)


def test_f9_successful_retry_cannot_undo_a_later_rollback(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    revision_a = _commit(repo)
    review_a = preview_publication(kb, revision_a, tmp_path / "dest", "none")
    publish_revision(kb, revision_a, tmp_path / "dest", "none", review_a.review_digest)

    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nB body.\n",
        )
    )
    revision_b = _commit(repo)
    review_b = preview_publication(kb, revision_b, tmp_path / "dest", revision_a)
    publish_revision(kb, revision_b, tmp_path / "dest", revision_a, review_b.review_digest)

    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nC body.\n",
        )
    )
    revision_c = _commit(repo)
    review_c = preview_publication(kb, revision_c, tmp_path / "dest", revision_b)
    publish_revision(kb, revision_c, tmp_path / "dest", revision_b, review_c.review_digest)

    rollback_review = preview_rollback(tmp_path / "dest", revision_a, revision_c)
    rollback_publication(tmp_path / "dest", revision_a, revision_c, rollback_review.review_digest)
    assert PublishedFilesystemLocation(tmp_path / "dest").read_pointer() == revision_a

    # Retrying the ALREADY SUCCESSFUL B confirmation — even though its old
    # baseline A is active again — must not reactivate B.
    retried = publish_revision(
        kb, revision_b, tmp_path / "dest", revision_a, review_b.review_digest
    )
    assert retried.activated is True  # the immutable historical admission fact
    assert PublishedFilesystemLocation(tmp_path / "dest").read_pointer() == revision_a


def test_r3_post_activation_receipt_failure_cannot_replay_after_rollback(tmp_path, monkeypatch):
    import lumio_wiki.git_authoring as git_authoring

    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    destination = tmp_path / "dest"
    revision_a = _commit(repo)
    review_a = preview_publication(kb, revision_a, destination, "none")
    publish_revision(kb, revision_a, destination, "none", review_a.review_digest)

    page = kb / "concepts" / "steel-blank.md"
    page.write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nB body.\n",
        )
    )
    revision_b = _commit(repo)
    review_b = preview_publication(kb, revision_b, destination, revision_a)
    receipt_b = destination / ".lumio-publication" / "receipts" / f"{revision_b}.json"
    atomic_write = git_authoring.atomic_write_bytes
    failed_receipt_writes = []

    def fail_activated_receipt(path, data):
        if Path(path) == receipt_b and json.loads(data).get("activated") is True:
            failed_receipt_writes.append(Path(path))
            raise OSError("injected activated receipt bookkeeping failure")
        atomic_write(path, data)

    monkeypatch.setattr(git_authoring, "atomic_write_bytes", fail_activated_receipt)
    with pytest.raises(OSError, match="activated receipt bookkeeping failure"):
        publish_revision(kb, revision_b, destination, revision_a, review_b.review_digest)
    assert failed_receipt_writes == [receipt_b]
    assert PublishedFilesystemLocation(destination).resolve().published_version == revision_b
    assert _published_receipt(destination, revision_b)["activated"] is False

    monkeypatch.setattr(git_authoring, "atomic_write_bytes", atomic_write)
    page.write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nC body.\n",
        )
    )
    revision_c = _commit(repo)
    review_c = preview_publication(kb, revision_c, destination, revision_b)
    publish_revision(kb, revision_c, destination, revision_b, review_c.review_digest)
    assert _published_receipt(destination, revision_b)["activated"] is True

    rollback_review = preview_rollback(destination, revision_a, revision_c)
    rollback_publication(destination, revision_a, revision_c, rollback_review.review_digest)
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_a

    retried_b = publish_revision(kb, revision_b, destination, revision_a, review_b.review_digest)
    assert retried_b.activated is True
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_a


def test_local_retry_recovers_after_private_binding_bookkeeping_failure(tmp_path, monkeypatch):
    """D3: recovery after a post-version, pre-receipt private bookkeeping failure."""
    from lumio_wiki.artifact_store import InMemoryArtifactStore
    from lumio_wiki.location import published_version_path

    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    destination = tmp_path / "dest"
    revision_a = _commit(repo)
    review_a = preview_publication(kb, revision_a, destination, "none")
    publish_revision(kb, revision_a, destination, "none", review_a.review_digest)

    page = kb / "concepts" / "steel-blank.md"
    page.write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nB body.\n",
        )
    )
    revision_b = _commit(repo)
    review_b = preview_publication(kb, revision_b, destination, revision_a)

    class _FailFirstBindingStore(InMemoryArtifactStore):
        """Fails B's first binding-manifest write, after the version is complete."""

        def __init__(self):
            super().__init__()
            self.failed = False

        def put_binding_manifest(self, version, manifest):
            if version == revision_b and not self.failed:
                self.failed = True
                raise OSError("injected private binding manifest failure")
            return super().put_binding_manifest(version, manifest)

    store = _FailFirstBindingStore()
    with pytest.raises(OSError, match="private binding manifest failure"):
        publish_revision(
            kb, revision_b, destination, revision_a, review_b.review_digest, artifact_store=store
        )
    # The immutable version directory completed before the bookkeeping failure.
    version_dir = published_version_path(destination, revision_b)
    assert (version_dir / "manifest.json").is_file()
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_a

    def tree_digests():
        return {
            str(path.relative_to(version_dir)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(version_dir.rglob("*"))
            if path.is_file()
        }

    before = tree_digests()
    receipt = publish_revision(
        kb, revision_b, destination, revision_a, review_b.review_digest, artifact_store=store
    )
    assert receipt.activated is True
    assert receipt.revision == revision_b
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_b
    assert tree_digests() == before  # recovery rewrites no immutable bytes


def test_f10_rollback_verifies_sealed_binding_identity(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    revision1 = _commit(repo)
    review1 = preview_publication(kb, revision1, tmp_path / "dest", "none")
    publish_revision(kb, revision1, tmp_path / "dest", "none", review1.review_digest)
    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nv2 body.\n",
        )
    )
    revision2 = _commit(repo)
    review2 = preview_publication(kb, revision2, tmp_path / "dest", revision1)
    publish_revision(kb, revision2, tmp_path / "dest", revision1, review2.review_digest)

    # Preview is stateless; tampering after review must fail at confirmation.
    rollback_review = preview_rollback(tmp_path / "dest", revision1, revision2)
    sealed_dir = tmp_path / "dest" / ".lumio-publication" / "bindings"
    (sealed_dir / f"{revision1}.json").write_bytes((sealed_dir / f"{revision2}.json").read_bytes())
    with pytest.raises(GitAuthoringError):
        rollback_publication(tmp_path / "dest", revision1, revision2, rollback_review.review_digest)


def test_f11_cli_retry_reaches_the_idempotent_path(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision = _commit(repo)
    argv = [
        "publish",
        str(kb),
        "--revision",
        revision,
        "--to",
        str(tmp_path / "dest"),
        "--expected-current",
        "none",
        "--source-registry",
        str(registry.root),
    ]
    code = main(argv)
    assert code == 0
    digest = _preview_digest(capsys.readouterr().out)
    confirm_argv = [*argv, "--confirm", digest]
    assert main(confirm_argv) == 0
    pointer_before = (tmp_path / "dest" / "current.json").read_bytes()
    manifest_before = (tmp_path / "dest" / "versions" / revision / "manifest.json").read_bytes()

    # Repeating the EXACT successful invocation returns the existing receipt.
    assert main(confirm_argv) == 0
    assert "Admitted Published Version" in capsys.readouterr().out
    assert (tmp_path / "dest" / "current.json").read_bytes() == pointer_before
    assert (
        tmp_path / "dest" / "versions" / revision / "manifest.json"
    ).read_bytes() == manifest_before


def test_f13_destination_inside_authoring_worktree_refused(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "outside", "none")
    digest = review.review_digest

    code = main(
        [
            "publish",
            str(kb),
            "--revision",
            revision,
            "--to",
            str(kb),
            "--expected-current",
            "none",
            "--confirm",
            digest,
            "--source-registry",
            str(registry.root),
        ]
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "outside" in err.lower() or "worktree" in err.lower()
    assert not (kb / "versions").exists()
    assert not (kb / "current.json").exists()

    with pytest.raises(GitAuthoringError, match="worktree"):
        publish_revision(kb, revision, repo / "nested-dest", "none", digest)


def test_f14_tracked_private_selections_refused(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    # An already-tracked private registry inside the authoring repository.
    private = repo / "private"
    private.mkdir()
    seed = SourceRegistry(private)
    seed.register_version("seed", b"seed")
    (repo / "raws").mkdir()
    (repo / "raws" / "manual.txt").write_bytes(A_BYTES)
    private_store = repo / "private-store"
    private_store.mkdir()
    (private_store / "artifact.bin").write_bytes(b"private retained artifact")
    _commit(repo)
    registry_bytes = (private / "sources.json").read_bytes()

    source_file = tmp_path / "manual.txt"
    source_file.write_bytes(A_BYTES)
    compiled = tmp_path / "press.md"
    compiled.write_text(_authored_ingest_page("operator-manual"))
    code = main(
        [
            "ingest",
            str(kb),
            str(repo / "raws" / "manual.txt"),
            "--compiled-page",
            str(compiled),
            "--source-id",
            "operator-manual",
            "--source-registry",
            str(private),
        ]
    )
    assert code == 1
    assert "tracked" in capsys.readouterr().err.lower()
    assert (private / "sources.json").read_bytes() == registry_bytes
    assert not (kb / "concepts" / "workbench_press.md").exists()

    outside_registry = SourceRegistry(tmp_path / "outside-registry")
    code = main(
        [
            "ingest",
            str(kb),
            str(repo / "raws" / "manual.txt"),
            "--compiled-page",
            str(compiled),
            "--source-id",
            "operator-manual",
            "--source-registry",
            str(outside_registry.root),
        ]
    )
    assert code == 1
    assert "tracked" in capsys.readouterr().err.lower()
    assert not (kb / "concepts" / "workbench_press.md").exists()

    revision = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(GitAuthoringError, match="tracked"):
        preview_publication(
            kb, revision, tmp_path / "dest", "none", source_registry=SourceRegistry(private)
        )
    from lumio_wiki.artifact_store import LocalDirectoryArtifactStore

    with pytest.raises(GitAuthoringError, match="tracked"):
        preview_publication(
            kb,
            revision,
            tmp_path / "dest",
            "none",
            source_registry=outside_registry,
            artifact_store=LocalDirectoryArtifactStore(private_store),
        )


def test_f15_source_impact_support_labels(tmp_path):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version("source-s", b"S bytes")
    registry.register_version("source-t", b"T bytes")
    pages = {
        "concepts/dual.md": _two_source_page(
            "entity:dual-press", "Dual Press", ["source-s", "source-t"]
        ),
        "concepts/sole.md": _two_source_page("entity:sole-press", "Sole Press", ["source-s"]),
    }
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"source-s": "active", "source-t": "active"},
        bindings={
            "entity:dual-press": {
                "source-s": hashlib.sha256(b"S bytes").hexdigest(),
                "source-t": hashlib.sha256(b"T bytes").hexdigest(),
            },
            "entity:sole-press": {"source-s": hashlib.sha256(b"S bytes").hexdigest()},
        },
    )
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision1 = _commit(repo)
    review1 = preview_publication(
        kb, revision1, tmp_path / "dest", "none", source_registry=registry
    )
    publish_revision(
        kb, revision1, tmp_path / "dest", "none", review1.review_digest, source_registry=registry
    )

    # Retire source-s and drop its bindings; source-t remains eligible.
    manifest2 = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"source-s": "retired", "source-t": "active"},
        bindings={
            "entity:dual-press": {"source-t": hashlib.sha256(b"T bytes").hexdigest()},
        },
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(manifest2)
    )
    revision2 = _commit(repo)
    review2 = preview_publication(
        kb, revision2, tmp_path / "dest", revision1, source_registry=registry
    )
    by_entity = {(item.entity_id, item.source_id): item for item in review2.source_impact}
    dual = by_entity[("entity:dual-press", "source-s")]
    assert dual.support == "still-supported", review2.source_impact
    sole = by_entity[("entity:sole-press", "source-s")]
    assert sole.support == "sole-source-lost", review2.source_impact
    assert not any(item.support == "replaced-exact-version" for item in review2.source_impact)


@pytest.mark.parametrize("alternative", ["unregistered", "undeclared"])
def test_r4_retirement_ignores_ineligible_alternative_support(tmp_path, alternative):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    source_s = b"S bytes"
    source_t = b"T bytes"
    digest_s = hashlib.sha256(source_s).hexdigest()
    digest_t = hashlib.sha256(source_t).hexdigest()
    registry.register_version("source-s", source_s)
    source_ids = ["source-s", "source-t"]
    if alternative == "undeclared":
        registry.register_version("source-t", source_t)
        source_ids = ["source-s"]

    page_path = "concepts/dual.md"
    pages = {page_path: _two_source_page("entity:dual-press", "Dual Press", source_ids)}
    initial = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"source-s": "active"},
        bindings={"entity:dual-press": {"source-s": digest_s}},
    )
    kb = _write_kb(repo, manifest=initial, pages=pages)
    revision_a = _commit(repo)
    review_a = preview_publication(
        kb, revision_a, tmp_path / "dest", "none", source_registry=registry
    )
    assert not review_a.blocking_diagnostics, review_a.blocking_diagnostics
    publish_revision(
        kb,
        revision_a,
        tmp_path / "dest",
        "none",
        review_a.review_digest,
        source_registry=registry,
    )

    retired = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"source-s": "retired", "source-t": "active"},
        bindings={"entity:dual-press": {"source-t": digest_t}},
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(retired)
    )
    revision_b = _commit(repo)
    review_b = preview_publication(
        kb, revision_b, tmp_path / "dest", revision_a, source_registry=registry
    )
    by_entity = {(item.entity_id, item.source_id): item for item in review_b.source_impact}
    assert by_entity[("entity:dual-press", "source-s")].support == "sole-source-lost"
    diagnostic = (
        "does not resolve to an exact registered Source Version"
        if alternative == "unregistered"
        else "is not declared in that page's sources[].id"
    )
    assert any(diagnostic in item for item in review_b.blocking_diagnostics)
    with pytest.raises(GitAuthoringError, match="blocking diagnostics"):
        publish_revision(
            kb,
            revision_b,
            tmp_path / "dest",
            revision_a,
            review_b.review_digest,
            source_registry=registry,
        )
    assert PublishedFilesystemLocation(tmp_path / "dest").read_pointer() == revision_a


def test_f16_publication_records_carry_provenance_and_inspection_metadata(tmp_path):
    repo = _init_repo(tmp_path)
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version(
        "operator-manual", A_BYTES, filename="manual.txt", content_type="text/plain"
    )
    pages = {"concepts/workbench_press.md": _authored_ingest_page("operator-manual")}
    manifest = SourceReferenceManifest(
        version=1,
        namespace=NAMESPACE,
        sources={"operator-manual": "active"},
        bindings={"entity:workbench-press": {"operator-manual": A_DIGEST}},
    )
    kb = _write_kb(repo, manifest=manifest, pages=pages)
    revision = _commit(repo)
    review = preview_publication(kb, revision, tmp_path / "dest", "none", source_registry=registry)
    publish_revision(
        kb, revision, tmp_path / "dest", "none", review.review_digest, source_registry=registry
    )

    public_manifest = json.loads(
        (tmp_path / "dest" / "versions" / revision / "manifest.json").read_bytes()
    )
    assert public_manifest["revision"] == revision
    assert public_manifest["subtree"] == "kb"
    assert (
        public_manifest["source_reference_digest"]
        == hashlib.sha256((kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()).hexdigest()
    )
    assert public_manifest["format_identity"] == "lumio-wiki/git-authoring/1"

    sealed = _sealed(tmp_path / "dest", revision)
    versions = {entry["source_id"]: entry for entry in sealed["source_versions"]}
    assert versions["operator-manual"]["content_hash"] == A_DIGEST
    assert versions["operator-manual"]["filename"] == "manual.txt"
    assert versions["operator-manual"]["content_type"] == "text/plain"
    assert versions["operator-manual"]["size"] == len(A_BYTES)


def test_f17_preview_json_is_machine_readable(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")
    revision = _commit(repo)
    code = main(
        [
            "publish",
            str(kb),
            "--revision",
            revision,
            "--to",
            str(tmp_path / "dest"),
            "--expected-current",
            "none",
            "--source-registry",
            str(registry.root),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert re.fullmatch(r"[0-9a-f]{64}", payload["review_digest"])
    assert not (tmp_path / "dest").exists()


def test_f6_rollback_requires_review_confirmation_and_current_baseline(tmp_path, capsys):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    destination = tmp_path / "dest"

    revision_a = _commit(repo)
    review_a = preview_publication(kb, revision_a, destination, "none")
    publish_revision(kb, revision_a, destination, "none", review_a.review_digest)
    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nB body.\n",
        )
    )
    revision_b = _commit(repo)
    review_b_publication = preview_publication(kb, revision_b, destination, revision_a)
    publish_revision(kb, revision_b, destination, revision_a, review_b_publication.review_digest)
    (kb / "concepts" / "steel-blank.md").write_text(
        _entity_page(
            "Steel Blank",
            "entity:steel-blank",
            ["material"],
            body_sections="## Overview\n\nC body.\n",
        )
    )
    revision_c = _commit(repo)
    review_c = preview_publication(kb, revision_c, destination, revision_b)
    publish_revision(kb, revision_c, destination, revision_b, review_c.review_digest)

    # Previewing the rollback is read-only and returns the exact confirmation.
    rollback_args = [
        "rollback",
        str(destination),
        "--version",
        revision_a,
        "--expected-current",
        revision_c,
    ]
    assert main(rollback_args) == 0
    digest_a = _preview_digest(capsys.readouterr().out)
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_c

    # Another confirmed rollback advances the baseline. The stale review may
    # not overwrite that newer current version.
    review_b = preview_rollback(destination, revision_b, revision_c)
    rollback_publication(destination, revision_b, revision_c, review_b.review_digest)
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_b
    assert main([*rollback_args, "--confirm", digest_a]) == 1
    assert "expected the active version" in capsys.readouterr().err.lower()
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_b

    # Re-review against the exact new baseline, then explicitly confirm it.
    fresh_args = [*rollback_args[:-1], revision_b]
    assert main(fresh_args) == 0
    digest = _preview_digest(capsys.readouterr().out)
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_b
    assert main([*fresh_args, "--confirm", digest]) == 0
    assert PublishedFilesystemLocation(destination).read_pointer() == revision_a


def test_native_source_retirement_edits_git_lifecycle_intent(tmp_path, capsys):
    """G3 (spec 0008 §3.2/§3.3): retirement intent is a reviewed Git manifest
    edit, never a proposal-keyed pending transition.

    A retirement with eligible support drops the retired source's binding and
    keeps the page bound to its exact remaining source (independently derived
    digest over known bytes); a sole-source retirement REFUSES with the
    affected page named, leaving the manifest untouched.
    """
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    registry = SourceRegistry(tmp_path / "registry")

    source_file = tmp_path / "manual.txt"
    source_file.write_bytes(A_BYTES)
    compiled = tmp_path / "press.md"
    compiled.write_text(_authored_ingest_page("operator-manual"))
    ingest_args = [
        "ingest",
        str(kb),
        str(source_file),
        "--compiled-page",
        str(compiled),
        "--source-id",
        "operator-manual",
        "--source-registry",
        str(registry.root),
    ]
    assert main(ingest_args) == 0
    _commit(repo)

    # A second exact supporting source: the authored page declares both.
    service_bytes = b"Service bulletin: verify the ram annually."
    service_digest = hashlib.sha256(service_bytes).hexdigest()
    second_page = _authored_ingest_page("operator-manual").replace(
        '  - id: "operator-manual"\n    title: "Operator manual"\n',
        '  - id: "operator-manual"\n    title: "Operator manual"\n'
        '  - id: "service-manual"\n    title: "Service bulletin"\n',
    )
    service_file = tmp_path / "service.txt"
    service_file.write_bytes(service_bytes)
    compiled2 = tmp_path / "press2.md"
    compiled2.write_text(second_page)
    assert (
        main(
            [
                "ingest",
                str(kb),
                str(service_file),
                "--compiled-page",
                str(compiled2),
                "--source-id",
                "service-manual",
                "--source-registry",
                str(registry.root),
            ]
        )
        == 0
    )
    _commit(repo)

    # --- Retire the operator manual: an ordinary manifest edit. ---
    code = main(["source", "retire", str(kb), "--source-id", "operator-manual"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Retired Knowledge Source 'operator-manual'" in out
    manifest = parse_source_reference_manifest(
        (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
    )
    assert manifest.sources["operator-manual"] == "retired"
    assert manifest.sources["service-manual"] == "active"
    # A retired source cannot keep supporting bindings: only the exact
    # service digest remains (independent SHA-256 oracle over known bytes).
    assert manifest.bindings["entity:workbench-press"] == {"service-manual": service_digest}
    # No proposal lifecycle was created anywhere.
    assert not (kb / ".lumio").exists()
    # The intent edit never rewrites the authored page.
    page_text = (kb / "concepts" / "workbench_press.md").read_text(encoding="utf-8")
    assert "operator-manual" in page_text

    # --- A sole-source retirement refuses and preserves the manifest. ---
    code = main(["source", "retire", str(kb), "--source-id", "service-manual"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Workbench Press" in captured.err
    manifest_after = parse_source_reference_manifest(
        (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
    )
    assert manifest_after.sources["service-manual"] == "active"
    assert manifest_after.bindings["entity:workbench-press"] == {"service-manual": service_digest}

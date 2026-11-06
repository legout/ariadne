"""Plan0033 A1/VA1: managed admission through an explicit private profile.

All Git projects, originals, registries, artifact stores and operator actions are
local synthetic fixtures. Expected page/original digests are fixed independently
from the implementation under test.
"""

import asyncio
import hashlib
import json
import os

import pytest
from ariadne import admission, lumio_context
from ariadne.admission import main as admission_main
from ariadne.discovery import DiscoveryRuntime
from lumio_wiki.artifact_store import LocalDirectoryArtifactStore, retain_artifact
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry
from tests.test_git_authoring import worktree_of

from integration.tests.lumio_metric_mvp import (
    NAMESPACE,
    current_bytes,
    page_parts,
    reconcile_knowledge,
    supported_candidate,
    write_page,
)

BASELINE_SOURCE = "managed-baseline-source"
NEW_SOURCE = "managed-addition-source"
BASELINE_ENTITY = "entity:managed-baseline"
NEW_ENTITY = "entity:managed-addition"
BASELINE_PAGE_PATH = "references/managed-baseline.md"
NEW_PAGE_PATH = "references/managed-addition.md"

BASELINE_ORIGINAL = b"Baseline operating note: keep the audited source available.\n"
BASELINE_ORIGINAL_DIGEST = "e534894a04abb692671f08d2a9f779963568fe894ea7a286a0ad5510978ff472"
NEW_ORIGINAL = b"New operating note: retain this additional original exactly.\n"
NEW_ORIGINAL_DIGEST = "f2c5e1f6b876265dd960ec3ba18ea48fd005e5c36996e3e525ec0632849b7d07"

BASELINE_PAGE = """---
id: "entity:managed-baseline"
title: "Managed Baseline"
entity_types:
  - reference
tags:
  - managed
summary: "Managed baseline citation."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "managed-baseline-source"
    title: "Baseline original"
---

# Managed Baseline

Baseline body retained from the admitted managed source.
"""
BASELINE_PAGE_DIGEST = "4a04657ca209e3ab7c6cd0d3388f8f23eca6bf05821e1f35a1a4218ae1859d76"
NEW_PAGE = """---
id: "entity:managed-addition"
title: "Managed Addition"
entity_types:
  - reference
tags:
  - managed
summary: "Managed addition citation."
lifecycle: "approved"
visibility: "public"
sources:
  - id: "managed-addition-source"
    title: "Additional original"
---

# Managed Addition

Additional body retained from the new managed source.
"""
NEW_PAGE_DIGEST = "0b2e92e86edacc1c9d7aa0bccea063523e1e5eed4f84e88f33ac160777d0d4fc"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    for name in list(os.environ):
        if name.startswith(("LUMIO_", "AWS_")):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def _manifest(bindings):
    return serialize_source_reference_manifest(
        SourceReferenceManifest(
            version=1,
            namespace=NAMESPACE,
            sources={source: "active" for source, _digest in bindings.values()},
            bindings={
                entity: {source: digest}
                for entity, (source, digest) in bindings.items()
            },
        )
    )


def _profile(profile_path, registry_root, store_root):
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(registry_root),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(store_root)},
            },
            indent=2,
        )
    )


def _retain(store, registry, source, raw):
    return retain_artifact(
        store,
        registry,
        source_id=source,
        raw_bytes=raw,
        content_type="text/plain",
        filename=f"{source}.txt",
    )


def _review(api, proposal, revision):
    validated = api.validate_proposal(proposal, revision)
    assert validated["ok"] is True, validated["errors"]
    return api.review_proposal(proposal)


def _python_preview(project, review, destination, profile, expected):
    return admission.overall_review(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        destination=destination,
        expected_current=expected,
        private_profile=profile,
    )


def _python_admit(project, review, preview, profile):
    return admission.admit_revision(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        confirmed_by="human:synthetic-operator",
        overall_preview=preview,
        confirmed_overall_digest=preview["digest"],
        private_profile=profile,
    )


def test_managed_admission_binds_profile_and_retention(tmp_path, capsys, monkeypatch):
    project, api, started, base_revision = supported_candidate(tmp_path / "project")
    proposal = started["proposal"]
    tree = worktree_of(project, proposal)
    for path in (tree / "knowledge").rglob("*.md"):
        metadata, body = page_parts(path)
        metadata["synthetic"] = True
        write_page(path, metadata, body)
    (tree / "knowledge" / BASELINE_PAGE_PATH).write_text(BASELINE_PAGE)
    (tree / "knowledge" / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        _manifest({BASELINE_ENTITY: (BASELINE_SOURCE, BASELINE_ORIGINAL_DIGEST)})
    )
    base_revision = reconcile_knowledge(project, proposal, base_revision)
    base_review = _review(api, proposal, base_revision)
    base_revision = base_review["revision"]

    private = tmp_path / "private"
    private.mkdir()
    registry_root = private / "registry"
    store_root = private / "store-one"
    alternate_store_root = private / "store-two"
    profile = private / "profile.json"
    registry = SourceRegistry(registry_root)
    registry.register_version(BASELINE_SOURCE, BASELINE_ORIGINAL)
    store = LocalDirectoryArtifactStore(store_root)
    assert _retain(store, registry, BASELINE_SOURCE, BASELINE_ORIGINAL) == (
        BASELINE_ORIGINAL_DIGEST
    )
    _profile(profile, registry_root, store_root)
    destination = tmp_path / "published"

    # Exercise the actual CLI preview and confirmation for the managed base.
    cli_args = [
        "--project",
        str(project),
        "--proposal",
        proposal,
        "--revision",
        base_revision,
        "--reviewed-digest",
        base_review["review_digest"],
        "--context-destination",
        str(destination),
        "--context-private-profile",
        str(profile),
    ]
    assert admission_main(cli_args) == 0
    base_preview = json.loads(capsys.readouterr().out)
    assert base_preview["source_configuration"]["binding"] == {
        "schema_version": 1,
        "namespace": NAMESPACE,
        "retention": "required",
        "source_registry": {"kind": "local", "root": str(registry_root)},
        "artifact_store": {"kind": "local", "root": str(store_root)},
    }
    assert (
        f"{BASELINE_ENTITY} -> {BASELINE_SOURCE}:{BASELINE_ORIGINAL_DIGEST}"
        in base_preview["publication_review"]["bindings"]
    )

    # The same existing valid profile must not become cwd-dependent when selected
    # through the CLI or either shared Python admission entry point.
    monkeypatch.chdir(private)
    relative_profile = profile.name
    relative_cli_args = [relative_profile if arg == str(profile) else arg for arg in cli_args]
    for confirm_args in (
        [],
        [
            "--confirm",
            "--by",
            "human:synthetic-operator",
            "--overall-digest",
            base_preview["digest"],
        ],
    ):
        assert admission_main([*relative_cli_args, *confirm_args]) == 1
        cli_error = capsys.readouterr()
        assert cli_error.out == ""
        assert json.loads(cli_error.err) == {
            "error": {
                "type": "ValueError",
                "message": "private profile path must be absolute",
            }
        }
    with pytest.raises(ValueError, match="private profile path must be absolute"):
        _python_preview(project, base_review, destination, relative_profile, "none")
    with pytest.raises(ValueError, match="private profile path must be absolute"):
        _python_admit(project, base_review, base_preview, relative_profile)
    assert not (project / ".ariadne/current.json").exists()
    assert PublishedFilesystemLocation(destination).read_pointer() is None

    assert admission_main(
        [
            *cli_args,
            "--confirm",
            "--by",
            "human:synthetic-operator",
            "--overall-digest",
            base_preview["digest"],
        ]
    ) == 0
    capsys.readouterr()
    prior_descriptor = current_bytes(project)
    prior_pointer = PublishedFilesystemLocation(destination).read_pointer()
    assert prior_pointer == base_revision

    # Add one hand-authored document while the known baseline original is absent.
    (tree / "knowledge" / NEW_PAGE_PATH).write_text(NEW_PAGE)
    (tree / "knowledge" / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        _manifest(
            {
                BASELINE_ENTITY: (BASELINE_SOURCE, BASELINE_ORIGINAL_DIGEST),
                NEW_ENTITY: (NEW_SOURCE, NEW_ORIGINAL_DIGEST),
            }
        )
    )
    registry.register_version(NEW_SOURCE, NEW_ORIGINAL)
    assert store.delete_artifact(
        source_id=BASELINE_SOURCE, content_hash=BASELINE_ORIGINAL_DIGEST
    )
    new_revision = reconcile_knowledge(project, proposal, base_revision)
    new_review = _review(api, proposal, new_revision)
    new_revision = new_review["revision"]
    missing = _python_preview(project, new_review, destination, profile, base_revision)
    with pytest.raises(lumio_context.OverallAdmissionError, match=BASELINE_SOURCE):
        _python_admit(project, new_review, missing, profile)
    assert current_bytes(project) == prior_descriptor
    assert PublishedFilesystemLocation(destination).read_pointer() == prior_pointer

    # Verified coverage permits a preview; a same-content but different store
    # still changes configuration identity and refuses the old overall consent.
    assert _retain(store, registry, BASELINE_SOURCE, BASELINE_ORIGINAL) == (
        BASELINE_ORIGINAL_DIGEST
    )
    assert _retain(store, registry, NEW_SOURCE, NEW_ORIGINAL) == NEW_ORIGINAL_DIGEST
    preview = _python_preview(project, new_review, destination, profile, base_revision)
    alternate = LocalDirectoryArtifactStore(alternate_store_root)
    _retain(alternate, registry, BASELINE_SOURCE, BASELINE_ORIGINAL)
    _retain(alternate, registry, NEW_SOURCE, NEW_ORIGINAL)
    _profile(profile, registry_root, alternate_store_root)
    with pytest.raises(ValueError, match="composite review changed"):
        _python_admit(project, new_review, preview, profile)
    assert current_bytes(project) == prior_descriptor
    assert PublishedFilesystemLocation(destination).read_pointer() == prior_pointer

    _profile(profile, registry_root, store_root)
    matching = _python_preview(project, new_review, destination, profile, base_revision)
    admitted = _python_admit(project, new_review, matching, profile)
    marker = admitted["bound_release"]["source_admission"]
    assert marker == {
        "schema_version": 1,
        "binding_digest": matching["source_configuration"]["binding_digest"],
        "retention": "required",
    }
    assert "source_configuration" not in admitted["bound_release"]
    assert str(private) not in json.dumps(admitted["bound_release"])
    version = destination / "versions" / new_revision
    assert hashlib.sha256((version / BASELINE_PAGE_PATH).read_bytes()).hexdigest() == (
        BASELINE_PAGE_DIGEST
    )
    assert hashlib.sha256((version / NEW_PAGE_PATH).read_bytes()).hexdigest() == NEW_PAGE_DIGEST

    # No profile, registry or either raw store remains available to the reader.
    profile.rename(private / "profile.unavailable")
    registry_root.rename(private / "registry.unavailable")
    store_root.rename(private / "store-one.unavailable")
    alternate_store_root.rename(private / "store-two.unavailable")
    session = DiscoveryRuntime.open_project(project)
    served = asyncio.run(session.read_context_page(NEW_PAGE_PATH))
    assert served["content"] == NEW_PAGE
    assert served["citation"] == (
        f"{NAMESPACE} {NEW_ENTITY} v{new_revision} {NEW_PAGE_PATH}"
    )
    assert served["bound_release"] == admitted["bound_release"]["digest"]

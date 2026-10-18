"""Ariadne Context Profile journey and refusals (spec 0009, unit L, new-test).

One coherent SDK journey over the committed canonical fixture at
``tests/fixtures/ariadne_context/`` (independently authored bytes): profiled
pages are authored in a disposable Git KB, inspected as an explicit unadmitted
candidate, published through the native preview/confirm admission, and read
back through the exact pinned Context Snapshot. Policy full text, Reference
representation/mapping/evidence metadata, typed required-Policy edges and
identities survive the round-trip. Distinct refusal variants cover unsupported
profile versions/fields, duplicate metric bindings, missing/wrong-kind
Policies, identity mismatches, unadmitted/unpinned inputs and hidden
out-of-scope Policies. Expectations derive from the fixture bytes, the
SHA-256 oracle ``hashlib`` and the spec's acceptance criteria — never from
implementation output.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import msgspec
import pytest
from lumio_wiki.ariadne_context import (
    PUBLIC_VISIBILITY_SCOPE,
    ContextIdentity,
    IdentityMismatchError,
    OutOfScopeDependencyError,
    UnadmittedInputError,
    disclose_native,
    inspect_ariadne_candidate,
    open_published_context,
    validate_ariadne_profiles,
)
from lumio_wiki.git_authoring import (
    preview_publication,
    publish_revision,
    rename_page_in_worktree,
)
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.location import FilesystemLocation, PublishedFilesystemLocation
from lumio_wiki.s3_location import S3Manifest
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)

NAMESPACE = "urn:demo:retail"
FIXTURE = Path(__file__).parent / "fixtures" / "ariadne_context"

CONTROL_V2 = """\
version: 2
mode: "categorized"
categories:
  - name: policies
  - name: references
  - name: metrics
ontology:
  entity_types:
    policy: {}
    reference: {}
    metric: {}
"""

FIXTURE_PAGES = {
    "policies/retail-return-policy.md": "policies/retail-return-policy.md",
    "references/order-number.md": "references/order-number.md",
    "metrics/retail-revenue.md": "metrics/retail-revenue.md",
}


@pytest.fixture(autouse=True)
def _sanitized_environment(tmp_path, monkeypatch):
    """Own HOME/XDG/TMP and empty AWS paths; no inherited LUMIO_/PYTHONPATH."""
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    (home / ".aws" / "config").write_text("")
    (home / ".aws" / "credentials").write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".state"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    short_tmp = tmp_path / "t"
    short_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(short_tmp))
    for name in list(os.environ):
        if name.startswith(("LUMIO_", "AWS_", "PYTHONPATH")):
            monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)
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
    pages: dict[str, str] | None = None,
    mutate: dict[str, str] | None = None,
) -> Path:
    """A disposable Git KB from the committed fixture (bytes copied verbatim)."""
    kb = repo / "kb"
    (kb).mkdir(parents=True, exist_ok=True)
    (kb / "lumio.yaml").write_text(CONTROL_V2)
    for rel, fixture_rel in (pages or FIXTURE_PAGES).items():
        target = kb / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((FIXTURE / fixture_rel).read_bytes())
    for rel, content in (mutate or {}).items():
        target = kb / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    return kb


def _plain_kb(tmp_path: Path, pages: dict[str, str]) -> Path:
    """A plain (non-Git) KB directory for loader-level refusal variants."""
    kb = tmp_path / f"kb{len(list(tmp_path.iterdir()))}"
    kb.mkdir()
    (kb / "lumio.yaml").write_text(CONTROL_V2)
    for rel, content in pages.items():
        target = kb / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return kb


def _commit(repo: Path) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "authoring revision")
    return _git(repo, "rev-parse", "HEAD")


def _expected_identity(kb: Path, destination: Path, version: str) -> ContextIdentity:
    """The expected Context Identity, assembled from independent oracles.

    The publication-manifest digest is the SHA-256 of the exact on-disk
    ``manifest.json`` bytes; the Source Reference digest is the SHA-256 of the
    KB's reviewed manifest bytes (both ``hashlib`` oracles, not SDK output).
    """
    manifest_json = (destination / "versions" / version / "manifest.json").read_bytes()
    return ContextIdentity(
        namespace=NAMESPACE,
        profile_version=1,
        published_version=version,
        fingerprint=_published_manifest(destination, version).fingerprint,
        publication_manifest_digest=hashlib.sha256(manifest_json).hexdigest(),
        source_reference_digest=hashlib.sha256(
            (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
        ).hexdigest(),
        scope=PUBLIC_VISIBILITY_SCOPE,
    )


def _published_manifest(destination: Path, version: str) -> S3Manifest:
    raw = (destination / "versions" / version / "manifest.json").read_bytes()
    return msgspec.json.decode(raw, type=S3Manifest)


def _publish(kb: Path, revision: str, destination: Path, expected_current) -> None:
    review = preview_publication(kb, revision, destination, expected_current)
    publish_revision(kb, revision, destination, expected_current, review.review_digest)


# ---------------------------------------------------------------------------
# The complete profile journey (validation unit L).
# ---------------------------------------------------------------------------


def test_ariadne_context_journey(tmp_path):
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    destination = tmp_path / "published"
    revision = _commit(repo)

    # --- Candidate inspection: exact, clean, and always unadmitted (§5). ---
    inspection = inspect_ariadne_candidate(str(kb), revision, namespace=NAMESPACE)
    assert inspection.admitted is False
    assert inspection.revision == revision
    assert inspection.subtree == "kb"
    assert inspection.namespace == NAMESPACE
    assert inspection.diagnostics == ()
    with pytest.raises(IdentityMismatchError):
        inspect_ariadne_candidate(str(kb), revision, namespace="urn:other:ns")

    # --- Native admission: stateless preview, explicit confirmation. ---
    _publish(kb, revision, destination, "none")
    expected = _expected_identity(kb, destination, revision)
    # The published manifest independently discloses the same identity facts.
    published = _published_manifest(destination, revision)
    assert published.namespace == NAMESPACE
    assert published.source_reference_digest == expected.source_reference_digest
    assert inspection.fingerprint == expected.fingerprint

    # --- Unadmitted and unpinned inputs refuse before anything is read. ---
    with pytest.raises(UnadmittedInputError, match="plain directories"):
        open_published_context(FilesystemLocation(kb), expected)
    with pytest.raises(UnadmittedInputError, match="no exact version pin"):
        open_published_context(PublishedFilesystemLocation(destination), expected)

    # --- Every expected-identity component is verified (AC5/§5). ---
    wrong_fingerprint = msgspec.structs.replace(expected, fingerprint="0" * 64)
    with pytest.raises(IdentityMismatchError, match="fingerprint"):
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision), wrong_fingerprint
        )
    wrong_manifest_digest = msgspec.structs.replace(expected, publication_manifest_digest="1" * 64)
    with pytest.raises(IdentityMismatchError, match="publication_manifest_digest"):
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision),
            wrong_manifest_digest,
        )
    wrong_namespace = msgspec.structs.replace(expected, namespace="urn:other:ns")
    with pytest.raises(IdentityMismatchError, match="namespace"):
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision), wrong_namespace
        )
    wrong_version = msgspec.structs.replace(expected, published_version="f" * 40)
    with pytest.raises(IdentityMismatchError, match="published_version"):
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision), wrong_version
        )

    # --- The exact Context Snapshot: full native preservation (AC1). ---
    context = open_published_context(
        PublishedFilesystemLocation(destination, version=revision), expected
    )
    assert context.identity == expected
    assert {view.kind for view in context.pages} == {"policy", "reference", "metric"}

    policy = next(view for view in context.pages if view.entity_id == "entity:retail-return-policy")
    fixture_policy = (FIXTURE / "policies/retail-return-policy.md").read_bytes()
    assert policy.content == fixture_policy.decode()  # exact published bytes
    assert policy.path == "policies/retail-return-policy.md"
    assert "within 30 days of purchase" in policy.body
    assert "reduced by recognized refunds" in policy.body
    assert policy.body_start_line > 40  # stable coordinates under the envelope
    assert policy.native["status"] == "stable"
    assert disclose_native(policy.native["stale_after"]) == "2027-06-30"
    assert policy.native["verified"][0]["by"] == "human:owner@retail.example"
    assert policy.citation == (
        f"{NAMESPACE} entity:retail-return-policy v{revision} policies/retail-return-policy.md"
    )

    reference = next(view for view in context.pages if view.entity_id == "entity:order-number")
    assert reference.content == (FIXTURE / "references/order-number.md").read_bytes().decode()
    extension = reference.native["ariadne"]
    assert extension["version"] == 1
    assert extension["reference_role"] == "identifier"
    assert [r["id"] for r in extension["representations"]] == [
        "global-order-number",
        "local-order-number",
    ]
    assert extension["representations"][0]["fields"] == [
        {"resource": "retail.main/orders", "column": "order_number"}
    ]
    assert extension["representations"][1]["scope"] == [
        {"resource": "retail.main/orders", "column": "store_id"}
    ]
    mapping = extension["mappings"][0]
    assert mapping["id"] == "store-prefix-composition"
    assert mapping["family"] == "prefix"
    assert (mapping["from"], mapping["to"]) == (
        "local-order-number",
        "global-order-number",
    )
    assert mapping["claim"] == "asserted"
    assert mapping["source_ids"] == ["src-owner-rule"]
    summary = reference.native["ariadne_evidence"]["store-prefix-composition"][0]
    assert summary["tested_left"] == 1200
    assert summary["eligible_right"] == 3500
    assert summary["matched_left_in_right"] == 1198
    assert summary["mismatch_count"] == 2
    assert disclose_native(summary["observed_at"]) == "2026-09-28T14:05:00+02:00"

    # --- The typed Context Binding and its complete Policy Closure (§4). ---
    (binding,) = context.bindings
    assert binding.metric_entity_id == "entity:retail-revenue"
    assert (binding.metric_ref.model, binding.metric_ref.metric) == (
        "retail_sales",
        "revenue",
    )
    (closure_view,) = binding.required_policies
    assert closure_view.entity_id == "entity:retail-return-policy"
    assert closure_view.citation == policy.citation

    # --- AC3: a profile-only change alters the bound identity. ---
    policy_file = kb / "policies/retail-return-policy.md"
    original_policy_text = policy_file.read_text()
    policy_file.write_text(
        original_policy_text.replace("stale_after: 2027-06-30", "stale_after: 2028-01-31")
    )
    revision2 = _commit(repo)
    inspection2 = inspect_ariadne_candidate(str(kb), revision2, namespace=NAMESPACE)
    assert inspection2.fingerprint != inspection.fingerprint
    _publish(kb, revision2, destination, revision)
    # The old pinned version still opens with its old identity...
    old_context = open_published_context(
        PublishedFilesystemLocation(destination, version=revision), expected
    )
    old_policy = next(
        view for view in old_context.pages if view.entity_id == "entity:retail-return-policy"
    )
    assert disclose_native(old_policy.native["stale_after"]) == "2027-06-30"
    # ...and the new version refuses that identity (no fingerprint reuse).
    with pytest.raises(IdentityMismatchError, match="fingerprint"):
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision2), expected
        )

    # --- AC4: a hidden mandatory Policy blocks without leaking (§4). ---
    policy_file.write_text(
        original_policy_text.replace('visibility: "public"', 'visibility: "internal"')
    )
    revision3 = _commit(repo)
    # Operator review may inspect its own candidate normally.
    hidden_inspection = inspect_ariadne_candidate(str(kb), revision3, namespace=NAMESPACE)
    assert hidden_inspection.diagnostics == ()
    _publish(kb, revision3, destination, revision2)
    expected_internal = msgspec.structs.replace(
        _expected_identity(kb, destination, revision3), scope=("public", "internal")
    )
    with pytest.raises(OutOfScopeDependencyError) as excinfo:
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision3), expected
        )
    refusal = str(excinfo.value)
    assert "Retail Return Policy" not in refusal  # no hidden title
    assert "within 30 days" not in refusal  # no hidden text
    assert "depth" not in refusal  # no hidden topology
    widened = open_published_context(
        PublishedFilesystemLocation(destination, version=revision3), expected_internal
    )
    assert any(view.entity_id == "entity:retail-return-policy" for view in widened.pages)

    # --- AC5: a native rename preserves the profile; pins stay immutable. ---
    rename_page_in_worktree(
        kb,
        "Retail Return Policy",
        new_title="Customer Return Policy",
        keep_old_title_alias=True,
    )
    revision4 = _commit(repo)
    _publish(kb, revision4, destination, revision3)
    kb_now, report_now = load_knowledge_base(kb)
    assert report_now.is_valid
    renamed = next(page for page in kb_now.pages if page.id == "entity:retail-return-policy")
    assert renamed.title == "Customer Return Policy"
    assert renamed.ariadne_profile is not None
    assert renamed.ariadne_profile.kind == "policy"
    assert renamed.ariadne_profile.required_policies == []
    assert renamed.ariadne_profile.native["status"] == "stable"
    assert disclose_native(renamed.ariadne_profile.native["stale_after"]) == "2027-06-30"
    # The first pinned Snapshot is unchanged by every later publication.
    first_context = open_published_context(
        PublishedFilesystemLocation(destination, version=revision), expected
    )
    first_policy = next(
        view for view in first_context.pages if view.entity_id == "entity:retail-return-policy"
    )
    assert first_policy.content == fixture_policy.decode()
    assert "# Retail Return Policy" in first_policy.content


# ---------------------------------------------------------------------------
# Envelope refusals (AC2): unsupported versions/fields never pass silently.
# ---------------------------------------------------------------------------


def _profile_page(profile_yaml: str) -> str:
    return (
        "---\n"
        'id: "entity:probe"\n'
        'title: "Probe"\n'
        "entity_types:\n  - policy\n"
        "tags:\n  - probe\n"
        'summary: "Probe page."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        '  - id: "src-probe"\n'
        '    title: "Probe source"\n'
        f"ariadne_profile:\n{profile_yaml}"
        "---\n\n"
        "# Probe\n\nProbe body.\n"
    )


def test_profile_envelope_refusals(tmp_path):
    cases = {
        "unsupported version": (
            _profile_page(
                "  version: 2\n  kind: policy\n  required_policies: []\n"
                "  native:\n    type: policy\n"
            ),
            "unsupported profile version 2",
        ),
        "unsupported native field": (
            _profile_page(
                "  version: 1\n  kind: policy\n  required_policies: []\n  native:\n"
                "    type: policy\n    mystery_field: 1\n"
            ),
            "unsupported native field(s) ['mystery_field']",
        ),
        "metric without required_policies": (
            _profile_page(
                "  version: 1\n  kind: metric\n  metric_ref:\n    model: m\n    metric: x\n"
                "  native:\n    type: metric\n"
            ),
            "requires an explicit required_policies list",
        ),
        "dataset without core_ref": (
            _profile_page("  version: 1\n  kind: dataset\n  native:\n    type: dataset\n"),
            "requires core_ref",
        ),
        "metric without metric_ref": (
            _profile_page(
                "  version: 1\n  kind: metric\n  required_policies: []\n"
                "  native:\n    type: metric\n"
            ),
            "requires metric_ref",
        ),
        "unresolvable mapping endpoint": (
            _profile_page(
                "  version: 1\n  kind: reference\n  native:\n"
                "    type: reference\n"
                "    sources:\n      - id: s1\n        title: S\n"
                "    ariadne:\n      version: 1\n      reference_role: identifier\n"
                "      representations:\n        - id: rep-a\n          fields:\n"
                "            - resource: r\n              column: c\n          scope: []\n"
                "      mappings:\n        - id: map-x\n          family: equality\n"
                "          from: rep-a\n          to: rep-missing\n"
                "          claim: hypothesis\n          source_ids: []\n"
            ),
            "does not resolve to a representation",
        ),
    }
    for label, (page, needle) in cases.items():
        kb = _plain_kb(tmp_path, {"policies/probe.md": page})
        loaded, report = load_knowledge_base(kb)
        assert not report.is_valid, label
        messages = "; ".join(issue.message for issue in report.issues)
        assert needle in messages, (label, messages)
        probe = next(p for p in loaded.pages if p.id == "entity:probe")
        assert probe.ariadne_profile is None, label


# ---------------------------------------------------------------------------
# Cross-page refusals (AC2): duplicate bindings and broken closures.
# ---------------------------------------------------------------------------


def _metric_page(entity_id: str, metric: str, required: str) -> str:
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{entity_id} page"\n'
        "entity_types:\n  - metric\n"
        "tags:\n  - probe\n"
        'summary: "Metric page."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        "sources:\n"
        '  - id: "src-metric"\n'
        '    title: "Metric source"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: metric\n"
        "  metric_ref:\n    model: retail_sales\n"
        f"    metric: {metric}\n"
        "  required_policies:\n"
        f"{required}"
        "  native:\n    type: metric\n"
        "---\n\n# Metric\n\nBody.\n"
    )


def test_profile_cross_page_refusals(tmp_path):
    required = f"    - namespace: {NAMESPACE}\n      entity_id: entity:retail-return-policy\n"
    policy_page = (FIXTURE / "policies/retail-return-policy.md").read_text()

    # Duplicate metric binding: two pages bind the same exact metric.
    duplicate_kb = _plain_kb(
        tmp_path,
        {
            "policies/policy.md": policy_page,
            "metrics/m1.md": _metric_page("entity:m1", "revenue", required),
            "metrics/m2.md": _metric_page("entity:m2", "revenue", required),
        },
    )
    duplicate_pages = load_knowledge_base(duplicate_kb)[0].pages
    diagnostics = validate_ariadne_profiles(duplicate_pages, namespace=NAMESPACE)
    assert any(d.category == "duplicate-binding" for d in diagnostics)

    # Missing closure target.
    missing_kb = _plain_kb(
        tmp_path,
        {
            "policies/policy.md": policy_page,
            "metrics/m1.md": _metric_page(
                "entity:m1",
                "revenue",
                f"    - namespace: {NAMESPACE}\n      entity_id: entity:absent\n",
            ),
        },
    )
    missing_pages = load_knowledge_base(missing_kb)[0].pages
    diagnostics = validate_ariadne_profiles(missing_pages, namespace=NAMESPACE)
    assert any(
        d.category == "unresolved-reference" and "does not exist" in d.message for d in diagnostics
    )

    # Wrong-kind closure target: the required entity is a reference page.
    wrong_kind_kb = _plain_kb(
        tmp_path,
        {
            "references/order-number.md": (FIXTURE / "references/order-number.md").read_text(),
            "metrics/m1.md": _metric_page(
                "entity:m1",
                "revenue",
                f"    - namespace: {NAMESPACE}\n      entity_id: entity:order-number\n",
            ),
        },
    )
    wrong_kind_pages = load_knowledge_base(wrong_kind_kb)[0].pages
    diagnostics = validate_ariadne_profiles(wrong_kind_pages, namespace=NAMESPACE)
    assert any(
        d.category == "unresolved-reference" and "not a Policy page" in d.message
        for d in diagnostics
    )

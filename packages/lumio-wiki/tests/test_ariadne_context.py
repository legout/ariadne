"""Ariadne Context Profile journey and refusals (spec 0009, unit L, new-test).

One coherent SDK journey over the committed canonical fixture at
``tests/fixtures/ariadne_context/`` (independently authored bytes): profiled
pages are authored in a disposable Git KB, inspected as an explicit unadmitted
candidate, published through the native preview/confirm admission (local and
in-memory S3 object store), and read back through the exact pinned Context
Snapshot. Policy full text, Reference representation/mapping/evidence
metadata, typed required-Policy edges and identities survive the round-trip.
Distinct refusal variants cover unsupported profile versions/fields, malformed
structural candidates, duplicate metric bindings, missing/wrong-kind
Policies, native Policy path contradictions, ontology declarations, identity
mismatches, unadmitted/unpinned inputs, profile-impacting mutations and
hidden out-of-scope Policies. Expectations derive from the fixture bytes,
the SHA-256 oracle ``hashlib``, the documented ariadne:// resource payload
contract and the spec's acceptance criteria — never from implementation
output.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
from datetime import date
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
from lumio_wiki.artifact_store import InMemoryArtifactStore
from lumio_wiki.git_authoring import (
    GitAuthoringError,
    ingest_into_worktree,
    merge_entities_in_worktree,
    preview_publication,
    publish_revision,
    remove_page_in_worktree,
    rename_page_in_worktree,
    write_pages_into_worktree,
)
from lumio_wiki.ingest import ProposedPage
from lumio_wiki.knowledge_base import _parse_frontmatter as parse_frontmatter
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.location import FilesystemLocation, PublishedFilesystemLocation
from lumio_wiki.s3_location import S3Location, S3Manifest, _get_bytes
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry
from msgspec import yaml

NAMESPACE = "urn:demo:retail"
FIXTURE = Path(__file__).parent / "fixtures" / "ariadne_context"

# The canonical table Resource of the fixture's order table, derived from the
# native payload contract (sources.py table_resource): base64url of the JSON
# array [source, catalog|null, schema, table] with compact separators.
ORDERS_PAYLOAD = json.dumps(["retail", None, "main", "orders"], separators=(",", ":"))
ORDERS_TABLE_URI = "ariadne://table/" + base64.urlsafe_b64encode(
    ORDERS_PAYLOAD.encode("utf-8")
).decode("ascii").rstrip("=")

CONTROL_V2 = """\
version: 2
mode: "categorized"
categories:
  - name: policies
  - name: references
  - name: metrics
  - name: archive
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
    monkeypatch.setenv("AWS_CONFIG_FILE", str(home / ".aws" / "config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / ".aws" / "credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


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
    kb.mkdir(parents=True, exist_ok=True)
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
    The subtree is the authored repository layout (``kb``).
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
        subtree="kb",
        scope=PUBLIC_VISIBILITY_SCOPE,
    )


def _published_manifest(destination: Path, version: str) -> S3Manifest:
    raw = (destination / "versions" / version / "manifest.json").read_bytes()
    return msgspec.json.decode(raw, type=S3Manifest)


def _publish(kb: Path, revision: str, destination: Path, expected_current) -> None:
    review = preview_publication(kb, revision, destination, expected_current)
    publish_revision(kb, revision, destination, expected_current, review.review_digest)


def _internal_fee_pages() -> dict[str, str]:
    """An unrelated fully internal metric graph (F12: hidden graphs never
    block a public reader and never leak into its diagnostics)."""
    policy = (
        "---\n"
        'id: "entity:internal-fee-policy"\n'
        'title: "Internal Fee Policy"\n'
        "entity_types:\n  - policy\n"
        "tags:\n  - internal\n"
        'summary: "Internal fee rules."\n'
        'lifecycle: "approved"\n'
        'visibility: "internal"\n'
        "sources:\n"
        '  - id: "src-fee"\n'
        '    title: "Fee note"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: policy\n"
        "  required_policies: []\n"
        "  native:\n"
        "    type: policy\n"
        '    title: "Internal Fee Policy"\n'
        '    description: "Internal fee rules."\n'
        "    tags:\n      - policy\n"
        "    status: stable\n"
        "    sources:\n"
        '      - id: "okf-fee"\n'
        '        title: "Fee policy page"\n'
        "---\n\n"
        "# Internal Fee Policy\n\nInternal-only fee rules.\n"
    )
    metric = (
        "---\n"
        'id: "entity:internal-fee"\n'
        'title: "Internal Fee (Metric)"\n'
        "entity_types:\n  - metric\n"
        "tags:\n  - internal\n"
        'summary: "Internal fee metric."\n'
        'lifecycle: "approved"\n'
        'visibility: "internal"\n'
        "sources:\n"
        '  - id: "src-fee-model"\n'
        '    title: "Fee model"\n'
        "ariadne_profile:\n"
        "  version: 1\n"
        "  kind: metric\n"
        "  metric_ref:\n"
        '    model: "retail_sales"\n'
        '    metric: "fee"\n'
        "  required_policies:\n"
        f"    - namespace: {NAMESPACE}\n"
        "      entity_id: entity:internal-fee-policy\n"
        "  native:\n"
        "    type: metric\n"
        '    title: "Internal fee"\n'
        '    description: "Internal fee totals."\n'
        "    tags:\n      - finance\n"
        "    status: stable\n"
        "    sources:\n"
        '      - id: "pol-fee"\n'
        '        title: "Governing policy"\n'
        '        resource: "policies/internal-fee-policy.md"\n'
        '    governed_by: "policies/internal-fee-policy.md"\n'
        "    dimensions:\n      - store\n"
        "    grain:\n"
        "      primary_key:\n        - order_number\n"
        '      cardinality_enforcement: "strict_1_to_1"\n'
        "---\n\n"
        "# Internal Fee (Metric)\n\nInternal-only metric body.\n"
    )
    return {
        "policies/internal-fee-policy.md": policy,
        "metrics/internal-fee.md": metric,
    }


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
    assert published.subtree == "kb"
    assert published.source_reference_digest == expected.source_reference_digest
    assert inspection.fingerprint == expected.fingerprint

    # --- Unadmitted and unpinned inputs refuse before anything is read. ---
    with pytest.raises(UnadmittedInputError, match="plain directories"):
        open_published_context(FilesystemLocation(kb), expected)
    with pytest.raises(UnadmittedInputError, match="no exact version pin"):
        open_published_context(PublishedFilesystemLocation(destination), expected)

    # --- Every expected-identity component is verified (AC5/§5), including
    # the selected subtree; each wrong expectation refuses with its named
    # component (identity gates run before any scope/view logic). ---
    pinned = PublishedFilesystemLocation(destination, version=revision)

    def _refuses_mismatch(identity: ContextIdentity, component: str) -> None:
        with pytest.raises(IdentityMismatchError, match=component):
            open_published_context(pinned, identity)

    _refuses_mismatch(msgspec.structs.replace(expected, fingerprint="0" * 64), "fingerprint")
    _refuses_mismatch(
        msgspec.structs.replace(expected, publication_manifest_digest="1" * 64),
        "publication_manifest_digest",
    )
    _refuses_mismatch(msgspec.structs.replace(expected, namespace="urn:other:ns"), "namespace")
    _refuses_mismatch(
        msgspec.structs.replace(expected, published_version="f" * 40), "published_version"
    )
    _refuses_mismatch(msgspec.structs.replace(expected, subtree="knowledge/"), "subtree")

    # --- The exact Context Snapshot: full native preservation (AC1). ---
    context = open_published_context(pinned, expected)
    assert context.identity == expected
    assert {view.kind for view in context.pages} == {"policy", "reference", "metric"}

    policy = next(view for view in context.pages if view.entity_id == "entity:retail-return-policy")
    fixture_policy = (FIXTURE / "policies/retail-return-policy.md").read_bytes()
    assert policy.content == fixture_policy.decode()  # exact published bytes
    assert policy.path == "policies/retail-return-policy.md"
    assert "within 30 days of purchase" in policy.body
    assert "reduced by recognized refunds" in policy.body
    # Independent coordinate oracle from the fixture bytes: the closing
    # frontmatter delimiter is line 35 (the body's first character is that
    # line's terminating newline, so the body begins on line 35 and the H1
    # sits on line 37).
    assert policy.body_start_line == 35
    assert policy.native["status"] == "stable"
    assert disclose_native(policy.native["stale_after"]) == "2027-06-30"
    assert policy.native["verified"][0]["by"] == "human:owner@retail.example"
    assert policy.citation == (
        f"{NAMESPACE} entity:retail-return-policy v{revision} policies/retail-return-policy.md"
    )
    # Deep-immutable view containers (F13): direct mutation refuses.
    with pytest.raises(TypeError):
        policy.native["status"] = "draft"
    with pytest.raises(TypeError):
        policy.native["verified"][0]["by"] = "x"
    with pytest.raises(TypeError):
        policy.sources[0] = policy.sources[0]  # tuple refuses item assignment

    reference = next(view for view in context.pages if view.entity_id == "entity:order-number")
    assert reference.content == (FIXTURE / "references/order-number.md").read_bytes().decode()
    extension = reference.native["ariadne"]
    assert extension["version"] == 1
    assert extension["reference_role"] == "identifier"
    assert [r["id"] for r in extension["representations"]] == [
        "global-order-number",
        "local-order-number",
    ]
    assert disclose_native(extension["representations"][0]["fields"]) == [
        {"resource": ORDERS_TABLE_URI, "column": "order_number"}
    ]
    assert disclose_native(extension["representations"][1]["scope"]) == [
        {"resource": ORDERS_TABLE_URI, "column": "store_id"}
    ]
    mapping = extension["mappings"][0]
    assert mapping["id"] == "store-prefix-composition"
    assert mapping["family"] == "prefix"
    assert (mapping["from"], mapping["to"]) == (
        "local-order-number",
        "global-order-number",
    )
    assert mapping["claim"] == "asserted"
    assert disclose_native(mapping["source_ids"]) == ["src-owner-rule"]
    summary = reference.native["ariadne_evidence"]["store-prefix-composition"][0]
    assert summary["tested_left"] == 1200
    assert summary["eligible_right"] == 3500
    assert summary["matched_left_in_right"] == 1198
    assert summary["mismatch_count"] == 2
    assert disclose_native(summary["observed_at"]) == "2026-09-28T14:05:00+02:00"
    # Ordered native values survive disclosure as ordinary JSON lists (F13).
    assert disclose_native(extension["representations"][1]["fields"])[0]["column"] == "store_id"

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
    assert "stale_after: 2027-06-30" in original_policy_text
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

    # --- AC4 + F12: a hidden mandatory Policy blocks generically, without
    # leaking; an unrelated fully internal metric graph neither blocks the
    # public reader nor appears anywhere in her refusal. ---
    policy_file.write_text(
        original_policy_text.replace('visibility: "public"', 'visibility: "internal"')
    )
    for rel, content in _internal_fee_pages().items():
        target = kb / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    revision3 = _commit(repo)
    # Operator review may inspect its own candidate normally.
    hidden_inspection = inspect_ariadne_candidate(str(kb), revision3, namespace=NAMESPACE)
    assert hidden_inspection.diagnostics == ()
    _publish(kb, revision3, destination, revision2)
    # The hidden-dependency case uses revision3's FULL matching identity with
    # the public scope, so the refusal is the visibility gate itself (F14).
    expected3_public = _expected_identity(kb, destination, revision3)
    with pytest.raises(OutOfScopeDependencyError) as excinfo:
        open_published_context(
            PublishedFilesystemLocation(destination, version=revision3), expected3_public
        )
    refusal = str(excinfo.value)
    assert "Retail Return Policy" not in refusal  # no hidden title
    assert "within 30 days" not in refusal  # no hidden text
    assert "internal-fee" not in refusal  # no unrelated hidden graph
    assert "Internal Fee" not in refusal
    assert "depth" not in refusal  # no hidden topology
    # A widened operator scope resolves the same exact identity completely.
    expected3_wide = msgspec.structs.replace(expected3_public, scope=("public", "internal"))
    widened = open_published_context(
        PublishedFilesystemLocation(destination, version=revision3), expected3_wide
    )
    widened_ids = {view.entity_id for view in widened.pages}
    assert {
        "entity:retail-return-policy",
        "entity:retail-revenue",
        "entity:order-number",
        "entity:internal-fee",
        "entity:internal-fee-policy",
    } <= widened_ids
    assert {binding.metric_entity_id for binding in widened.bindings} == {
        "entity:retail-revenue",
        "entity:internal-fee",
    }
    # The public scope never lists the hidden pages in its views (§4).
    public_try = open_published_context(
        PublishedFilesystemLocation(destination, version=revision2),
        _expected_identity(kb, destination, revision2),
    )
    assert "entity:internal-fee" not in {view.entity_id for view in public_try.pages}

    # --- F7: profile-impacting mutations refuse BEFORE any worktree write. ---
    with pytest.raises(GitAuthoringError, match="resolves to no page"):
        rename_page_in_worktree(kb, "Retail Return Policy", new_category="archive")
    assert (kb / "policies/retail-return-policy.md").is_file()
    with pytest.raises(GitAuthoringError, match="no safe automatic survivor"):
        merge_entities_in_worktree(kb, "entity:retail-return-policy", "entity:order-number")
    with pytest.raises(GitAuthoringError, match="does not exist in the selected"):
        remove_page_in_worktree(kb, "Retail Return Policy")
    assert (kb / "policies/retail-return-policy.md").is_file()
    assert _git(repo, "status", "--porcelain") == ""  # refusals wrote nothing

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
# Envelope refusals (AC2): unsupported versions/fields never pass silently;
# per-kind native families (F3) parse their real supported structures.
# ---------------------------------------------------------------------------


def _profile_page(profile_yaml: str, *, visibility: str = "public") -> str:
    return (
        "---\n"
        'id: "entity:probe"\n'
        'title: "Probe"\n'
        "entity_types:\n  - policy\n"
        "tags:\n  - probe\n"
        'summary: "Probe page."\n'
        'lifecycle: "approved"\n'
        f'visibility: "{visibility}"\n'
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
                "    title: t\n    description: d\n    tags: [a]\n"
                "    status: stable\n"
                "    sources:\n      - id: s\n        title: S\n"
            ),
            "unsupported profile version 2",
        ),
        "unsupported native field": (
            _profile_page(
                "  version: 1\n  kind: policy\n  required_policies: []\n"
                "  native:\n    type: policy\n    title: t\n    description: d\n"
                "    tags: [a]\n    status: stable\n"
                "    sources:\n      - id: s\n        title: S\n    mystery_field: 1\n"
            ),
            "unsupported native field(s) ['mystery_field']",
        ),
        "metric without required_policies": (
            _profile_page(
                "  version: 1\n  kind: metric\n  metric_ref:\n"
                "    model: m\n    metric: x\n"
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
                "    type: reference\n    title: t\n    description: d\n    tags: [a]\n"
                "    sources:\n      - id: s1\n        title: S\n"
                "    ariadne:\n      version: 1\n      reference_role: identifier\n"
                "      representations:\n        - id: rep-a\n          fields:\n"
                f"            - resource: {ORDERS_TABLE_URI}\n"
                "              column: c\n          scope: []\n"
                "      mappings:\n        - id: map-x\n          family: equality\n"
                "          from: rep-a\n          to: rep-missing\n"
                "          claim: hypothesis\n          source_ids: []\n"
            ),
            "does not resolve to a representation",
        ),
        "candidate carries SQL": (
            _profile_page(
                "  version: 1\n  kind: reference\n  native:\n"
                "    type: reference\n    title: t\n    description: d\n    tags: [a]\n"
                "    sources:\n      - id: s1\n        title: S\n"
                "    ariadne:\n      version: 1\n      reference_role: identifier\n"
                "      representations:\n        - id: rep-a\n          fields:\n"
                f"            - resource: {ORDERS_TABLE_URI}\n"
                "              column: c\n          scope: []\n"
                "      mappings:\n        - id: map-x\n          family: equality\n"
                "          from: rep-a\n          to: rep-a\n"
                "          claim: hypothesis\n          source_ids: []\n"
                "          candidate:\n            family: equality\n"
                "            sql: SELECT 1\n"
            ),
            "there is no SQL",
        ),
        "non-canonical binding resource": (
            _profile_page(
                "  version: 1\n  kind: reference\n  native:\n"
                "    type: reference\n    title: t\n    description: d\n    tags: [a]\n"
                "    sources:\n      - id: s1\n        title: S\n"
                "    ariadne:\n      version: 1\n      reference_role: identifier\n"
                "      representations:\n        - id: rep-a\n          fields:\n"
                '            - resource: "retail.main/orders"\n'
                "              column: c\n          scope: []\n"
            ),
            "is not a canonical ariadne:// URI",
        ),
        "kind list crashes nothing": (
            _profile_page("  version: 1\n  kind: [policy]\n  native:\n    type: policy\n"),
            "kind must be one of",
        ),
        "native sources integer is named, not fatal": (
            _profile_page(
                "  version: 1\n  kind: policy\n  required_policies: []\n"
                "  native:\n    type: policy\n    title: t\n    description: d\n"
                "    tags: [a]\n    status: stable\n    sources: 7\n"
            ),
            "sources must be a list",
        ),
        "floating ontology revision refuses": (
            _profile_page(
                "  version: 1\n  kind: reference\n"
                "  ontology_refs:\n"
                '    - namespace: "urn:demo:catalog"\n'
                "      identifier: retail-hierarchy\n"
                '      revision: "main"\n'
                "  native:\n    type: reference\n    title: t\n    description: d\n"
                "    tags: [a]\n    sources:\n      - id: s\n        title: S\n"
            ),
            "floating revision 'main'",
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

    # Positive controls (F3): the real per-kind native families parse.
    table_page = _profile_page(
        "  version: 1\n  kind: table\n"
        "  core_ref:\n    kind: resource\n"
        f"    id: {ORDERS_TABLE_URI}\n"
        "  native:\n    type: table\n    title: t\n    description: d\n"
        "    tags: [table]\n"
        f"    resource: {ORDERS_TABLE_URI}\n"
        "    sources:\n      - id: s\n        title: S\n"
        "    grain:\n      primary_key: [order_number]\n"
        '      cardinality_enforcement: "strict_1_to_1"\n'
        "    observed_value_columns:\n      order_number: VARCHAR\n"
        "    ariadne:\n      schema:\n        - column: order_number\n"
        "          type: VARCHAR\n          nullable: unknown\n"
        "          default: unknown\n          comment: unknown\n"
        "      observations:\n"
        '        observed_at: "2026-10-01T00:00:00+00:00"\n'
        "        scope: full\n        row_count: 10\n"
        "        candidate_keys: [order_number]\n"
        "        columns:\n          order_number:\n"
        "            null_count: 0\n            distinct_count: 10\n"
        f"        citation: {ORDERS_TABLE_URI}\n"
        "        value_evidence:\n          order_number:\n"
        "            state: observed\n"
        '            top_values:\n              - value: "00123"\n                count: 1\n'
    )
    computation_page = _profile_page(
        "  version: 1\n  kind: computation\n"
        "  core_ref:\n    kind: semantic\n"
        '    id: "retail_sales::revenue"\n'
        "  native:\n    type: computation\n    title: c\n    description: d\n"
        "    tags: [c]\n    status: stable\n"
        "    sources:\n      - id: m\n        title: M\n"
        '        resource: "../../semantic_layer/models/retail_sales.yml"\n'
        '    governed_by: "semantic_layer retail_sales::revenue"\n'
        '    runtime: "duckdb"\n'
        '    attestation: "pending"\n'
        "    dataset_sources: [retail]\n"
    )
    for label, page in (("table", table_page), ("computation", computation_page)):
        kb = _plain_kb(tmp_path, {"policies/probe.md": page})
        loaded, report = load_knowledge_base(kb)
        assert report.is_valid, (label, [i.message for i in report.issues])
        probe = next(p for p in loaded.pages if p.id == "entity:probe")
        assert probe.ariadne_profile is not None, label
        assert probe.ariadne_profile.core_ref is not None, label


# ---------------------------------------------------------------------------
# Cross-page refusals (AC2): duplicate bindings, broken closures, native
# Policy agreement (F5) and pinned ontology declarations (F6).
# ---------------------------------------------------------------------------


def _metric_page(entity_id: str, metric: str, required: str, *, native_policy: str) -> str:
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
        "  native:\n"
        "    type: metric\n"
        f'    title: "{metric}"\n'
        '    description: "Metric."\n'
        "    tags: [probe]\n"
        "    status: stable\n"
        "    sources:\n"
        '      - id: "pol-x"\n'
        '        title: "Governing policy"\n'
        f'        resource: "{native_policy}"\n'
        f'    governed_by: "{native_policy}"\n'
        "    dimensions: [store]\n"
        "    grain:\n      primary_key: [order_number]\n"
        '      cardinality_enforcement: "strict_1_to_1"\n'
        "---\n\n# Metric\n\nBody.\n"
    )


def test_profile_cross_page_refusals(tmp_path):
    policy_page = (FIXTURE / "policies/retail-return-policy.md").read_text()
    required_return_policy = (
        f"    - namespace: {NAMESPACE}\n      entity_id: entity:retail-return-policy\n"
    )

    # Duplicate metric binding: two pages bind the same exact metric.
    duplicate_kb = _plain_kb(
        tmp_path,
        {
            "policies/policy.md": policy_page,
            "metrics/m1.md": _metric_page(
                "entity:m1",
                "revenue",
                required_return_policy,
                native_policy="policies/retail-return-policy.md",
            ),
            "metrics/m2.md": _metric_page(
                "entity:m2",
                "revenue",
                required_return_policy,
                native_policy="policies/retail-return-policy.md",
            ),
        },
    )
    duplicate_pages = load_knowledge_base(duplicate_kb)[0].pages
    diagnostics = validate_ariadne_profiles(duplicate_pages, namespace=NAMESPACE)
    assert any(d.category == "duplicate-binding" and d.path == "metrics/m2.md" for d in diagnostics)

    # Missing closure target.
    missing_kb = _plain_kb(
        tmp_path,
        {
            "policies/policy.md": policy_page,
            "metrics/m1.md": _metric_page(
                "entity:m1",
                "revenue",
                f"    - namespace: {NAMESPACE}\n      entity_id: entity:absent\n",
                native_policy="policies/retail-return-policy.md",
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
                native_policy="policies/retail-return-policy.md",
            ),
        },
    )
    wrong_kind_pages = load_knowledge_base(wrong_kind_kb)[0].pages
    diagnostics = validate_ariadne_profiles(wrong_kind_pages, namespace=NAMESPACE)
    assert any(
        d.category == "unresolved-reference" and "not a Policy page" in d.message
        for d in diagnostics
    )

    # Retained native Policy path contradicts the typed closure (F5): the
    # typed list is explicitly empty while the native metadata still cites
    # the governing policy.
    contradiction_kb = _plain_kb(
        tmp_path,
        {
            "policies/retail-return-policy.md": policy_page,
            "metrics/m1.md": _metric_page(
                "entity:m1",
                "margin",
                "    []\n",
                native_policy="policies/retail-return-policy.md",
            ),
        },
    )
    contradiction_pages = load_knowledge_base(contradiction_kb)[0].pages
    assert next(p for p in contradiction_pages if p.id == "entity:m1").ariadne_profile is not None
    diagnostics = validate_ariadne_profiles(contradiction_pages, namespace=NAMESPACE)
    assert any(
        d.category == "unresolved-reference"
        and "contradicts the typed required_policies closure" in d.message
        for d in diagnostics
    )

    # Ontology declarations resolve only against a pinned declared catalog (F6).
    ontology_page = _profile_page(
        "  version: 1\n  kind: reference\n"
        "  ontology_refs:\n"
        '    - namespace: "urn:demo:catalog"\n'
        "      identifier: retail-hierarchy\n"
        '      revision: "r7"\n'
        "  native:\n    type: reference\n    title: t\n    description: d\n"
        "    tags: [a]\n    sources:\n      - id: s\n        title: S\n"
    )
    ontology_kb = _plain_kb(tmp_path, {"policies/onto.md": ontology_page})
    ontology_pages = load_knowledge_base(ontology_kb)[0].pages
    assert next(p for p in ontology_pages if p.id == "entity:probe").ariadne_profile is not None
    diagnostics = validate_ariadne_profiles(ontology_pages, namespace=NAMESPACE)
    assert any("no pinned declared catalog" in d.message for d in diagnostics)
    catalog = {"urn:demo:catalog": {"retail-hierarchy": "r7"}}
    assert (
        validate_ariadne_profiles(ontology_pages, namespace=NAMESPACE, ontology_catalog=catalog)
        == ()
    )
    wrong_catalog = {"urn:demo:catalog": {"retail-hierarchy": "r6"}}
    diagnostics = validate_ariadne_profiles(
        ontology_pages, namespace=NAMESPACE, ontology_catalog=wrong_catalog
    )
    assert any("does not allow" in d.message for d in diagnostics)


# ---------------------------------------------------------------------------
# The S3 object-store branch (F9/F10): native MemoryStore publication,
# namespace propagation, exact pinned opening and admission verification.
# ---------------------------------------------------------------------------


def test_s3_published_context_journey(tmp_path):
    import obstore
    from lumio_wiki.s3_location import MANIFEST_OBJECT

    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    revision = _commit(repo)
    store = obstore.store.MemoryStore()
    s3_location = S3Location(store, "kb", store_uri="s3://test-bucket")
    metadata = InMemoryArtifactStore()

    # Native S3 admission through the exact pinned object-store seams.
    review = preview_publication(
        kb,
        revision,
        "s3://test-bucket/kb",
        "none",
        s3_location=s3_location,
        metadata_store=metadata,
    )
    receipt = publish_revision(
        kb,
        revision,
        "s3://test-bucket/kb",
        "none",
        review.review_digest,
        s3_location=s3_location,
        metadata_store=metadata,
    )
    assert receipt.activated is True

    # The manifest bytes in the store carry the propagated namespace (F9).
    manifest_key = f"kb/{revision}/{MANIFEST_OBJECT}"
    manifest_raw = _get_bytes(store, manifest_key)
    manifest = msgspec.json.decode(manifest_raw, type=S3Manifest)
    assert manifest.namespace == NAMESPACE
    assert manifest.subtree == "kb"

    expected_s3 = ContextIdentity(
        namespace=NAMESPACE,
        profile_version=1,
        published_version=revision,
        fingerprint=manifest.fingerprint,
        publication_manifest_digest=hashlib.sha256(manifest_raw).hexdigest(),
        source_reference_digest=hashlib.sha256(
            (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
        ).hexdigest(),
        subtree="kb",
        scope=PUBLIC_VISIBILITY_SCOPE,
    )
    assert receipt.fingerprint == manifest.fingerprint

    # Unpinned S3 input and missing metadata store refuse (F9/F10).
    with pytest.raises(UnadmittedInputError, match="no exact version pin"):
        open_published_context(S3Location(store, "kb"), expected_s3)
    pinned_s3 = S3Location(store, "kb", version=revision)
    with pytest.raises(UnadmittedInputError, match="producer-side metadata store"):
        open_published_context(pinned_s3, expected_s3)
    with pytest.raises(UnadmittedInputError, match="no completed private admission"):
        open_published_context(pinned_s3, expected_s3, metadata_store=InMemoryArtifactStore())
    wrong_s3 = msgspec.structs.replace(expected_s3, fingerprint="0" * 64)
    with pytest.raises(IdentityMismatchError, match="fingerprint"):
        open_published_context(pinned_s3, wrong_s3, metadata_store=metadata)

    # The exact admitted S3 version opens with the identical preserved view.
    context = open_published_context(pinned_s3, expected_s3, metadata_store=metadata)
    policy = next(view for view in context.pages if view.entity_id == "entity:retail-return-policy")
    assert policy.content == (FIXTURE / "policies/retail-return-policy.md").read_bytes().decode()
    (binding,) = context.bindings
    assert binding.metric_entity_id == "entity:retail-revenue"
    (closure_view,) = binding.required_policies
    assert closure_view.entity_id == "entity:retail-return-policy"


# B1 regressions: native Ariadne 24630dbd and spec 0009 r2 are the oracles.
# Inline cases leave the canonical three-page consumer fixture unchanged.


def _case_markdown(data: dict, body: str = "# Case\n\nReviewed case.\n") -> str:
    return "---\n" + yaml.encode(data).decode() + "---\n" + body


def _literal_profile_page(profile: dict, *, entity_id="entity:probe", title="Probe") -> str:
    kind = profile["kind"]
    return _case_markdown(
        {
            "id": entity_id,
            "title": title,
            "entity_types": [kind if kind in {"metric", "policy"} else "reference"],
            "tags": ["probe"],
            "summary": "Independently authored native case.",
            "lifecycle": "approved",
            "visibility": "public",
            "sources": [{"id": "src-probe", "title": "Reviewed source"}],
            "ariadne_profile": profile,
        }
    )


def _native_metric(sources: list) -> dict:
    # Native attach_model_metadata uses the OSI identity, not a Policy path.
    return {
        "type": "metric",
        "title": "Revenue",
        "description": "Reviewed revenue definition.",
        "tags": ["finance"],
        "status": "stable",
        "sources": sources,
        "governed_by": "semantic_layer retail_sales::revenue",
        "dimensions": ["store"],
        "grain": {"primary_key": ["order_number"], "cardinality_enforcement": "strict_1_to_1"},
    }


def test_native_schema_matches_pinned_producers(tmp_path):
    """D1: authoring._schema_columns + context.build_{table,dataset}_page."""
    collection_uri = "ariadne://collection/" + base64.urlsafe_b64encode(
        b'["retail",null,"main"]'
    ).decode().rstrip("=")
    # Ordinal schema and declared metadata from the pinned _schema_columns.
    schema = [
        {
            "column": "order_number",
            "type": "VARCHAR",
            "nullable": False,
            "default": None,
            "comment": "unknown",
        },
        {
            "column": "region",
            "type": "VARCHAR",
            "nullable": True,
            "default": "'EMEA'",
            "comment": "unknown",
        },
        {
            "column": "active",
            "type": "BOOLEAN",
            "nullable": "unknown",
            "default": "unknown",
            "comment": "unknown",
        },
        {
            "column": "units",
            "type": "INTEGER",
            "nullable": "unknown",
            "default": "unknown",
            "comment": "unknown",
        },
        {
            "column": "ratio",
            "type": "DOUBLE",
            "nullable": "unknown",
            "default": "unknown",
            "comment": "unknown",
        },
    ]
    # Spec 0024's three-row measured literals; no database measurement in Lumio.
    evidence = {
        "region": {
            "state": "observed",
            "top_values": [{"value": "EMEA", "count": 2}, {"value": "AMER", "count": 1}],
        },
        "order_number": {
            "state": "observed",
            "top_values": [{"value": "00123", "count": 2}, {"value": "123", "count": 1}],
        },
        "active": {
            "state": "observed",
            "top_values": [{"value": True, "count": 2}, {"value": None, "count": 1}],
        },
        "units": {
            "state": "observed",
            "top_values": [{"value": 2, "count": 2}, {"value": 1, "count": 1}],
        },
        "ratio": {
            "state": "observed",
            "top_values": [{"value": 1.5, "count": 2}, {"value": 0.5, "count": 1}],
        },
        "removed": {"state": "unavailable", "reason": "column_missing"},
    }
    observations = {
        "observed_at": "2026-10-13T12:00:00+00:00",
        "scope": "full",
        "row_count": 3,
        "candidate_keys": [],
        "columns": {
            row["column"]: {"null_count": int(row["column"] == "active"), "distinct_count": 2}
            for row in schema
        },
        "citation": ORDERS_TABLE_URI,
        "value_evidence": evidence,
    }
    table_native = {
        "type": "table",
        "title": "retail.main.orders",
        "description": "Physical orders.",
        "tags": ["table", "schema"],
        "resource": ORDERS_TABLE_URI,
        "sources": [
            {
                "id": "catalog-retail-main-orders",
                "resource": ORDERS_TABLE_URI,
                "title": "catalog and profile of retail.main.orders",
            }
        ],
        "stale_after": date(2027, 6, 30),
        "observed_value_columns": {row["column"]: row["type"] for row in schema}
        | {"removed": "VARCHAR"},
        "ariadne": {"schema": schema, "observations": observations},
    }
    table_profile = {
        "version": 1,
        "kind": "table",
        "native": table_native,
        "core_ref": {"kind": "resource", "id": ORDERS_TABLE_URI},
    }
    dataset_native = {
        "type": "dataset",
        "title": "retail.main",
        "description": "Physical collection.",
        "tags": ["dataset"],
        "resource": collection_uri,
        "sources": [
            {
                "id": "catalog-retail-main",
                "resource": collection_uri,
                "title": "catalog of retail.main",
            }
        ],
        "ariadne": {"tables": [ORDERS_TABLE_URI]},
    }
    dataset_profile = {
        "version": 1,
        "kind": "dataset",
        "native": dataset_native,
        "core_ref": {"kind": "resource", "id": collection_uri},
    }
    repo = _init_repo(tmp_path)
    kb = _write_kb(
        repo,
        mutate={
            "references/native-table.md": _literal_profile_page(
                table_profile, entity_id="entity:table", title="Native table"
            ),
            "references/native-dataset.md": _literal_profile_page(
                dataset_profile, entity_id="entity:dataset", title="Native dataset"
            ),
        },
    )
    _, report = load_knowledge_base(kb)
    assert report.is_valid, ("D1 native producer literals", [i.message for i in report.issues])
    revision = _commit(repo)
    assert inspect_ariadne_candidate(str(kb), revision, namespace=NAMESPACE).diagnostics == ()
    destination = tmp_path / "published"
    _publish(kb, revision, destination, "none")
    context = open_published_context(
        PublishedFilesystemLocation(destination, version=revision),
        _expected_identity(kb, destination, revision),
    )
    table = next(p for p in context.pages if p.entity_id == "entity:table")
    dataset = next(p for p in context.pages if p.entity_id == "entity:dataset")
    assert table.content == _literal_profile_page(
        table_profile, entity_id="entity:table", title="Native table"
    )
    assert disclose_native(table.native) == {**table_native, "stale_after": "2027-06-30"}
    assert disclose_native(dataset.native) == dataset_native
    assert type(table.native["ariadne"]["schema"][0]["nullable"]) is bool
    values = table.native["ariadne"]["observations"]["value_evidence"]
    assert type(values["units"]["top_values"][0]["value"]) is int
    assert type(values["active"]["top_values"][0]["value"]) is bool
    # State-specific payloads are structural contracts, not authenticated receipts.
    for invalid in (
        {"state": "observed"},
        {"state": "unavailable"},
        {"state": "confirmed", "top_values": [{"value": "EMEA", "count": 2}]},
    ):
        malformed = copy.deepcopy(table_profile)
        malformed["native"]["ariadne"]["observations"]["value_evidence"]["region"] = invalid
        bad_kb = _plain_kb(tmp_path, {"references/bad.md": _literal_profile_page(malformed)})
        _, bad_report = load_knowledge_base(bad_kb)
        assert not bad_report.is_valid, ("D1 malformed value_evidence accepted", invalid)
        assert any("value_evidence" in i.message for i in bad_report.issues)


@pytest.mark.parametrize("scenario", ["intentional-empty", "scalar-policy-disagreement"])
def test_policy_requirements_allow_empty_and_check_scalar_sources(tmp_path, scenario):
    """D2: native _metric_context reads scalar and structured Policy sources."""
    policy_native = {
        "type": "policy",
        "title": "Policy A",
        "description": "Reviewed policy.",
        "tags": ["policy"],
        "status": "stable",
        "sources": ["policies/a.md"],
    }
    policy_a = _literal_profile_page(
        {"version": 1, "kind": "policy", "required_policies": [], "native": policy_native},
        entity_id="entity:a",
        title="Policy A",
    )
    policy_b_native = {**policy_native, "title": "Policy B", "sources": ["policies/b.md"]}
    policy_b = _literal_profile_page(
        {"version": 1, "kind": "policy", "required_policies": [], "native": policy_b_native},
        entity_id="entity:b",
        title="Policy B",
    )
    provenance = {
        "id": "model",
        "title": "Reviewed OSI",
        "resource": "../../semantic_layer/models/retail_sales.yml",
    }
    required = (
        []
        if scenario == "intentional-empty"
        else [{"namespace": NAMESPACE, "entity_id": "entity:b"}]
    )
    sources = (
        [provenance]
        if not required
        else ["policies/a.md", {"id": "policy-b", "resource": "policies/b.md"}, provenance]
    )
    profile = {
        "version": 1,
        "kind": "metric",
        "metric_ref": {"model": "retail_sales", "metric": "revenue"},
        "required_policies": required,
        "native": _native_metric(sources),
    }
    kb = _plain_kb(
        tmp_path,
        {
            "policies/a.md": policy_a,
            "policies/b.md": policy_b,
            "metrics/revenue.md": _literal_profile_page(profile),
        },
    )
    loaded, report = load_knowledge_base(kb)
    assert report.is_valid, ("D2 explicit requirements", [i.message for i in report.issues])
    diagnostics = validate_ariadne_profiles(loaded.pages, namespace=NAMESPACE)
    if scenario == "intentional-empty":
        assert diagnostics == ()
        missing = copy.deepcopy(profile)
        del missing["required_policies"]
        absent_kb = _plain_kb(tmp_path, {"metrics/revenue.md": _literal_profile_page(missing)})
        _, absent_report = load_knowledge_base(absent_kb)
        assert not absent_report.is_valid
        assert any("required_policies" in i.message for i in absent_report.issues)
    else:
        assert any(
            d.category == "unresolved-reference" and "policies/a.md" in d.message
            for d in diagnostics
        ), ("D2 retained scalar Policy A was ignored", diagnostics)
        profile["required_policies"].insert(0, {"namespace": NAMESPACE, "entity_id": "entity:a"})
        (kb / "metrics/revenue.md").write_text(_literal_profile_page(profile))
        agreed, agreed_report = load_knowledge_base(kb)
        assert agreed_report.is_valid
        assert validate_ariadne_profiles(agreed.pages, namespace=NAMESPACE) == ()
        profile["native"]["sources"] = ["policies/a.md", provenance]
        profile["required_policies"] = [{"namespace": NAMESPACE, "entity_id": "entity:a"}]
        (kb / "metrics/revenue.md").write_text(_literal_profile_page(profile))
        scalar, scalar_report = load_knowledge_base(kb)
        assert scalar_report.is_valid
        assert validate_ariadne_profiles(scalar.pages, namespace=NAMESPACE) == ()


def test_control_catalog_flows_through_native_gates(tmp_path):
    """D3: the authored Control File, never a caller override, owns the catalog."""
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    plain_control = (kb / "lumio.yaml").read_bytes()
    plain_revision = _commit(repo)
    plain = inspect_ariadne_candidate(str(kb), plain_revision, namespace=NAMESPACE)
    assert plain.diagnostics == ()
    assert (kb / "lumio.yaml").read_bytes() == plain_control
    catalog = {"version": 1, "ontology_catalog": {"urn:demo:catalog": {"retail-hierarchy": "r7"}}}
    control = (
        CONTROL_V2
        + 'hot_index:\n  - title: "Order Number"\n'
        + yaml.encode({"ariadne_context": catalog}).decode()
    )
    (kb / "lumio.yaml").write_text(control)
    reference_file = kb / "references/order-number.md"
    reference_data, body, _ = parse_frontmatter(reference_file.read_text(), reference_file)
    reference_data["ariadne_profile"]["ontology_refs"] = [
        {"namespace": "urn:demo:catalog", "identifier": "retail-hierarchy", "revision": "r7"}
    ]
    reference_file.write_text(_case_markdown(reference_data, body))
    revision = _commit(repo)
    inspection = inspect_ariadne_candidate(str(kb), revision, namespace=NAMESPACE)
    assert inspection.diagnostics == (), (
        "D3 captured Control File catalog",
        inspection.diagnostics,
    )
    assert inspection.fingerprint != plain.fingerprint
    destination = tmp_path / "published"
    _publish(kb, revision, destination, "none")
    expected = _expected_identity(kb, destination, revision)
    original = open_published_context(
        PublishedFilesystemLocation(destination, version=revision), expected
    )
    assert (destination / "versions" / revision / "lumio.yaml").read_bytes() == control.encode()
    # The same captured Control File also governs in-memory S3 admission/read.
    import obstore

    store = obstore.store.MemoryStore()
    metadata = InMemoryArtifactStore()
    s3 = S3Location(store, "catalog", store_uri="s3://test-bucket")
    review = preview_publication(
        kb, revision, "s3://test-bucket/catalog", "none", s3_location=s3, metadata_store=metadata
    )
    publish_revision(
        kb,
        revision,
        "s3://test-bucket/catalog",
        "none",
        review.review_digest,
        s3_location=s3,
        metadata_store=metadata,
    )
    manifest_raw = _get_bytes(store, f"catalog/{revision}/manifest.json")
    manifest = msgspec.json.decode(manifest_raw, type=S3Manifest)
    s3_identity = msgspec.structs.replace(
        expected,
        fingerprint=manifest.fingerprint,
        publication_manifest_digest=hashlib.sha256(manifest_raw).hexdigest(),
    )
    s3_context = open_published_context(
        S3Location(store, "catalog", version=revision), s3_identity, metadata_store=metadata
    )
    assert s3_context.pages == original.pages
    assert _get_bytes(store, f"catalog/{revision}/lumio.yaml") == control.encode()
    rename_page_in_worktree(
        kb, "Order Number", new_title="Order Identifier", keep_old_title_alias=True
    )
    assert yaml.decode((kb / "lumio.yaml").read_bytes())["ariadne_context"] == catalog
    renamed_revision = _commit(repo)
    renamed = inspect_ariadne_candidate(str(kb), renamed_revision, namespace=NAMESPACE)
    assert renamed.diagnostics == ()
    _publish(kb, renamed_revision, destination, revision)
    # Catalog-only edit: an unused exact declaration, not a page rewrite.
    changed = yaml.decode((kb / "lumio.yaml").read_bytes())
    changed["ariadne_context"]["ontology_catalog"]["urn:demo:catalog"]["other-target"] = "r8"
    (kb / "lumio.yaml").write_bytes(yaml.encode(changed))
    changed_revision = _commit(repo)
    changed_inspection = inspect_ariadne_candidate(str(kb), changed_revision, namespace=NAMESPACE)
    assert changed_inspection.diagnostics == ()
    assert changed_inspection.fingerprint != renamed.fingerprint
    assert changed_inspection.source_reference_manifest_digest == (
        renamed.source_reference_manifest_digest
    )
    assert _git(repo, "diff", "--name-only", renamed_revision, changed_revision) == "kb/lumio.yaml"
    _publish(kb, changed_revision, destination, renamed_revision)
    current = open_published_context(
        PublishedFilesystemLocation(destination, version=changed_revision),
        _expected_identity(kb, destination, changed_revision),
    )
    assert next(p for p in current.pages if p.entity_id == "entity:order-number").content == (
        reference_file.read_text()
    )
    assert (
        open_published_context(PublishedFilesystemLocation(destination, version=revision), expected)
        == original
    )
    # Unknown, mismatched and floating targets refuse through the native write gate.
    current_data, current_body, _ = parse_frontmatter(reference_file.read_text(), reference_file)
    before = {p.relative_to(kb).as_posix(): p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    for target in (
        {"namespace": "urn:unknown", "identifier": "retail-hierarchy", "revision": "r7"},
        {"namespace": "urn:demo:catalog", "identifier": "retail-hierarchy", "revision": "r6"},
        {"namespace": "urn:demo:catalog", "identifier": "retail-hierarchy", "revision": "main"},
    ):
        invalid = copy.deepcopy(current_data)
        invalid["ariadne_profile"]["ontology_refs"] = [target]
        with pytest.raises(GitAuthoringError, match="ontology|catalog|revision"):
            write_pages_into_worktree(
                kb,
                [
                    ProposedPage(
                        relative_path="references/order-number.md",
                        title="Order Identifier",
                        markdown=_case_markdown(invalid, current_body),
                    )
                ],
            )
        assert {
            p.relative_to(kb).as_posix(): p.read_bytes() for p in kb.rglob("*") if p.is_file()
        } == before


def test_managed_policy_revision_retains_recorded_path(tmp_path):
    """D4: a same-title revision is not a move, even when ingest proposes a new slug."""
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    registry = SourceRegistry(tmp_path / "private-registry")
    policy_path = kb / "policies/retail-return-policy.md"
    data, body, _ = parse_frontmatter(
        (FIXTURE / "policies/retail-return-policy.md").read_text(), policy_path
    )
    source_bytes = b"Returns Handbook, 2026 edition: Finance reviews this policy quarterly.\n"
    revised_body = body + "\nFinance reviews this policy quarterly.\n"
    authored = _case_markdown(
        {
            **data,
            "category": "policies",
            "type": "policy",
            "durability_rationale": "Durable returns and refund rules.",
        },
        revised_body,
    )

    ingest_into_worktree(
        kb,
        source_bytes,
        "text/plain",
        "returns-handbook.txt",
        "src-returns-handbook",
        authored,
        source_registry=registry,
    )

    written = policy_path.read_text()
    written_data, written_body, _ = parse_frontmatter(written, policy_path)
    assert written_data == {**data, "type": "policy"}
    assert written_body.strip("\n") == revised_body.strip("\n")
    assert not (kb / "policies/retail_return_policy.md").exists()
    assert (kb / "metrics/retail-revenue.md").read_bytes() == (
        FIXTURE / "metrics/retail-revenue.md"
    ).read_bytes()
    manifest = yaml.decode((kb / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes())
    assert manifest["namespace"] == NAMESPACE
    assert manifest["bindings"]["entity:retail-return-policy"]["src-returns-handbook"] == (
        hashlib.sha256(source_bytes).hexdigest()
    )
    loaded, report = load_knowledge_base(kb)
    assert report.is_valid
    assert validate_ariadne_profiles(loaded.pages, namespace=NAMESPACE) == ()


@pytest.mark.parametrize("operation", ["managed-ingest", "effective-compound"])
def test_effective_ingest_and_compound_gate_before_writes(tmp_path, operation):
    """D4: refusal precedes private registration and effective compound writes."""
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    registry = SourceRegistry(tmp_path / "private-registry")
    before = {p.relative_to(kb).as_posix(): p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    private_before = registry.snapshot_state_bytes()
    refusal = None
    if operation == "managed-ingest":
        profile = {
            "version": 1,
            "kind": "metric",
            "metric_ref": {"model": "retail_sales", "metric": "missing_policy_revenue"},
            "required_policies": [{"namespace": NAMESPACE, "entity_id": "entity:missing-policy"}],
            "native": _native_metric([{"id": "missing", "resource": "policies/missing.md"}]),
        }
        authored = _literal_profile_page(profile, title="Missing Policy Revenue")
        data, body, _ = parse_frontmatter(authored, Path("authored.md"))
        data.update(category="metrics", type="metric", durability_rationale="Durable metric rule.")
        try:
            ingest_into_worktree(
                kb,
                b"Reviewed metric source",
                "text/plain",
                "metric.txt",
                "src-probe",
                _case_markdown(data, body),
                source_registry=registry,
            )
        except GitAuthoringError as exc:
            refusal = str(exc)
    else:
        metric_path = kb / "metrics/retail-revenue.md"
        metric_data, metric_body, _ = parse_frontmatter(metric_path.read_text(), metric_path)
        del metric_data["ariadne_profile"]
        policy_path = kb / "policies/retail-return-policy.md"
        policy_data, policy_body, _ = parse_frontmatter(policy_path.read_text(), policy_path)
        policy_data["ariadne_profile"] = {
            "version": 1,
            "kind": "reference",
            "native": {
                "type": "reference",
                "title": "Returns reference",
                "description": "Background.",
                "tags": ["returns"],
                "sources": ["policies/retail-return-policy.md"],
            },
        }
        try:
            write_pages_into_worktree(
                kb,
                [
                    ProposedPage(
                        relative_path="metrics/retail-revenue.md",
                        title="Retail Revenue (Metric)",
                        markdown=_case_markdown(metric_data, metric_body),
                        compound_revision=True,
                    ),
                    ProposedPage(
                        relative_path="policies/retail-return-policy.md",
                        title="Retail Return Policy",
                        markdown=_case_markdown(policy_data, policy_body),
                    ),
                ],
            )
        except GitAuthoringError as exc:
            refusal = str(exc)
    after = {p.relative_to(kb).as_posix(): p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    private_after = registry.snapshot_state_bytes()
    assert (refusal is not None, after == before, private_after == private_before) == (
        True,
        True,
        True,
    ), (
        "D4 unsafe effects",
        operation,
        refusal,
        "worktree_unchanged",
        after == before,
        "private_history_unchanged",
        private_after == private_before,
    )
    assert refusal is not None
    if operation == "managed-ingest":
        assert "entity:missing-policy" in refusal
    else:
        assert "not a Policy" in refusal
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("backend", ["local", "s3"])
def test_admission_rejects_foreign_source_subtree_binding(tmp_path, monkeypatch, backend):
    """D5: prepared bytes must not borrow another KB's genuine admission facts."""
    import lumio_wiki.git_authoring as native

    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    other = repo / "other"
    shutil.copytree(kb, other)
    registry = SourceRegistry(tmp_path / "private-registry")
    # Same pages and Content Commit, different exact private Source Versions.
    for root, raw in ((kb, b"Finance review A"), (other, b"Finance review B")):
        version, _ = registry.register_version(
            "src-finance-model", raw, filename="finance.txt", content_type="text/plain"
        )
        assert version.content_hash == hashlib.sha256(raw).hexdigest()
        (root / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
            serialize_source_reference_manifest(
                SourceReferenceManifest(
                    version=1,
                    namespace=NAMESPACE,
                    sources={"src-finance-model": "active"},
                    bindings={
                        "entity:retail-revenue": {
                            "src-finance-model": hashlib.sha256(raw).hexdigest()
                        }
                    },
                )
            )
        )
    revision = _commit(repo)
    destination = tmp_path / "admitted"
    prepared_destination = tmp_path / "prepared"
    metadata = InMemoryArtifactStore()
    prepared_metadata = InMemoryArtifactStore()
    store = None
    if backend == "s3":
        import obstore

        store = obstore.store.MemoryStore()

    def publish(root, version, expected_current, *, prepared=False):
        s3_location = None
        private_store = None
        if backend == "local":
            target = prepared_destination if prepared else destination
        else:
            prefix = "prepared" if prepared else "admitted"
            target = f"s3://test-bucket/{prefix}"
            s3_location = S3Location(store, prefix, store_uri="s3://test-bucket")
            private_store = prepared_metadata if prepared else metadata
        review = preview_publication(
            root,
            version,
            target,
            expected_current,
            source_registry=registry,
            s3_location=s3_location,
            metadata_store=private_store,
        )
        assert review.blocking_diagnostics == []
        return publish_revision(
            root,
            version,
            target,
            expected_current,
            review.review_digest,
            source_registry=registry,
            s3_location=s3_location,
            metadata_store=private_store,
        )

    def pinned_identity(root, *, prepared=False):
        if backend == "local":
            target = prepared_destination if prepared else destination
            raw = (target / "versions" / revision / "manifest.json").read_bytes()
            location = PublishedFilesystemLocation(target, version=revision)
        else:
            prefix = "prepared" if prepared else "admitted"
            raw = _get_bytes(store, f"{prefix}/{revision}/manifest.json")
            location = S3Location(store, prefix, version=revision, store_uri="s3://test-bucket")
        manifest = msgspec.json.decode(raw, type=S3Manifest)
        identity = ContextIdentity(
            namespace=NAMESPACE,
            profile_version=1,
            published_version=revision,
            fingerprint=manifest.fingerprint,
            publication_manifest_digest=hashlib.sha256(raw).hexdigest(),
            source_reference_digest=hashlib.sha256(
                (root / SOURCE_REFERENCE_MANIFEST_BASENAME).read_bytes()
            ).hexdigest(),
            subtree="other" if prepared else "kb",
            scope=PUBLIC_VISIBILITY_SCOPE,
        )
        return location, identity

    publish(kb, revision, "none")
    admitted_location, admitted_identity = pinned_identity(kb)
    selected_metadata = metadata if backend == "s3" else None
    original = open_published_context(
        admitted_location, admitted_identity, metadata_store=selected_metadata
    )
    # Inject only a storage failure after real preparation, before private admission.
    with monkeypatch.context() as failure:

        def unavailable(*args, **kwargs):
            raise OSError("synthetic private admission storage failure")

        if backend == "s3":
            failure.setattr(native, "_persist_s3_publication_record", unavailable)
        else:
            write = native.atomic_write_bytes

            def fail_receipt(path, raw):
                if path == native._receipt_path(prepared_destination, revision):
                    unavailable()
                return write(path, raw)

            failure.setattr(native, "atomic_write_bytes", fail_receipt)
        with pytest.raises(OSError, match="synthetic private admission storage failure"):
            publish(other, revision, "none", prepared=True)
    prepared_location, prepared_identity = pinned_identity(other, prepared=True)
    assert prepared_identity.fingerprint == admitted_identity.fingerprint
    assert prepared_identity.source_reference_digest != admitted_identity.source_reference_digest
    assert prepared_identity.subtree != admitted_identity.subtree
    # Full expected public identity is correct, but preparation is not admission.
    with pytest.raises(UnadmittedInputError):
        open_published_context(
            prepared_location,
            prepared_identity,
            metadata_store=prepared_metadata if backend == "s3" else None,
        )
    # Admitted historical reads must survive advancement of the native pointer.
    policy = kb / "policies/retail-return-policy.md"
    policy.write_text(policy.read_text() + "\nReviewed clarification.\n")
    successor = _commit(repo)
    publish(kb, successor, revision)
    assert (
        open_published_context(
            admitted_location, admitted_identity, metadata_store=selected_metadata
        )
        == original
    )
    if backend == "local":
        # Wrong local state selection: unmodified genuine records, no invented success.
        shutil.copyfile(
            native._receipt_path(destination, revision),
            native._receipt_path(prepared_destination, revision),
        )
        shutil.copyfile(
            native._sealed_path(destination, revision),
            native._sealed_path(prepared_destination, revision),
        )
    # S3's ordinary wrong-store selection supplies the admitted A records to B.
    with pytest.raises(UnadmittedInputError):
        open_published_context(
            prepared_location, prepared_identity, metadata_store=selected_metadata
        )


# ---------------------------------------------------------------------------
# Approved local navigation amendment r3 (spec 0009): scoped published
# navigation over ordinary and profiled pages through the additive SDK.
# ---------------------------------------------------------------------------

# Independently authored visible ordinary documentation page with every
# line joined by explicit '\r\n' (CRLF canonical bytes). Canonical line
# map: 1 '---', 2 id plus an inline YAML distractor comment carrying a
# literal 'halcyon' that no native search field parses, 3 title, 4
# entity_types, 5 '  - reference', 6 tags, 7 '  - guides', 8 tag authored as
# the double-quoted YAML escape '  - "\u0068alcyon"' (decodes to 'halcyon',
# never literal in the raw bytes), 9 'summary: >-' with its folded value on
# 10 '  borealis care' and 11 '  continues indoors', 12 lifecycle,
# 13 visibility, 14 review_after, 15 sources, 16 source id, 17 source title,
# 18 closing '---' (the body's first character is this line's terminating
# newline, so body_start_line == 18), 19 blank, 20 H1, 21 blank, 22 intro,
# 23 blank, 24 '## Ventilation', 25 blank, 26 'The zephyr lane stays open
# during storms.'
_AURORA_TEXT = (
    "---\r\n"
    'id: "entity:aurora-care-guide" # halcyon is metadata-only\r\n'
    'title: "Aurora Care Guide"\r\n'
    "entity_types:\r\n"
    "  - reference\r\n"
    "tags:\r\n"
    "  - guides\r\n"
    '  - "\\u0068alcyon"\r\n'
    "summary: >-\r\n"
    "  borealis care\r\n"
    "  continues indoors\r\n"
    'lifecycle: "approved"\r\n'
    'visibility: "public"\r\n'
    'review_after: "2027-09-30"\r\n'
    "sources:\r\n"
    '  - id: "src-aurora-guide"\r\n'
    '    title: "Aurora keeper handbook"\r\n'
    "---\r\n"
    "\r\n"
    "# Aurora Care Guide\r\n"
    "\r\n"
    "Morning care keeps the terrarium calm.\r\n"
    "\r\n"
    "## Ventilation\r\n"
    "\r\n"
    "The zephyr lane stays open during storms.\r\n"
)

# Independently authored hidden ordinary page (internal visibility) sharing
# the unique body token 'zephyr' with the two visible pages.
_HIDDEN_TEXT = (
    "---\n"
    'id: "entity:hidden-zephyr-notes"\n'
    'title: "Hidden Zephyr Notes"\n'
    "entity_types:\n"
    "  - reference\n"
    "tags:\n"
    "  - internal\n"
    'summary: "Internal zephyr calibration notes."\n'
    'lifecycle: "approved"\n'
    'visibility: "internal"\n'
    "sources:\n"
    '  - id: "src-zephyr-calibration"\n'
    '    title: "Calibration log"\n'
    "---\n"
    "\n"
    "# Hidden Zephyr Notes\n"
    "\n"
    "The zephyr calibration table stays internal.\n"
)

# One authored body section appended to B's disposable copy so all three
# pages share the unique body token; the committed golden fixture bytes on
# disk are never modified.
_POLICY_ZEPHYR_APPEND = "\n## Zephyr handling\n\nThe zephyr lane stays open during winter storms.\n"


def test_scoped_published_navigation_includes_ordinary_pages(tmp_path):
    """One focused native-publication navigation journey (spec0009 r3).

    Visible ordinary A, visible profiled policy B and hidden ordinary C share
    the unique body token ``zephyr``; the metadata-only token ``halcyon``
    exists solely in A's frontmatter as the double-quoted YAML escape on
    canonical line 8 (decoded tag value, never literal in the raw bytes),
    with a literal-'halcyon' distractor comment on the line-2 id that no
    native search field parses. Expected bytes
    and coordinates are hand-counted from the authored lines above, never
    observed from implementation output.
    """
    # Future public SDK surface (spec0009 r3): imported inside the test body
    # so the unchanged SDK still collects this module for the baseline nodes.
    from lumio_wiki.ariadne_context import (
        list_published_context_pages,
        read_published_context_page,
        search_published_context_pages,
    )

    aurora_path = "references/aurora-care-guide.md"
    hidden_path = "references/hidden-zephyr-notes.md"
    policy_path = "policies/retail-return-policy.md"

    repo = _init_repo(tmp_path)
    # Exactly B comes from the valid policy fixture (``pages={}`` would
    # silently copy every golden page); A and C are authored via mutate.
    kb = _write_kb(
        repo,
        pages={policy_path: policy_path},
        mutate={aurora_path: _AURORA_TEXT, hidden_path: _HIDDEN_TEXT},
    )
    policy_b_text = (kb / policy_path).read_text() + _POLICY_ZEPHYR_APPEND
    (kb / policy_path).write_text(policy_b_text)

    revision = _commit(repo)
    destination = tmp_path / "published"
    _publish(kb, revision, destination, "none")
    expected = _expected_identity(kb, destination, revision)
    pinned = PublishedFilesystemLocation(destination, version=revision)

    # --- Plain, unpinned and S3 navigation inputs refuse explicitly. ---
    with pytest.raises(UnadmittedInputError, match="plain directories"):
        list_published_context_pages(FilesystemLocation(kb), expected)
    with pytest.raises(UnadmittedInputError, match="no exact version pin"):
        read_published_context_page(PublishedFilesystemLocation(destination), expected, aurora_path)
    with pytest.raises(UnadmittedInputError):
        search_published_context_pages(
            S3Location(InMemoryArtifactStore(), "kb", version=revision), expected, "zephyr"
        )

    # --- List: exactly A+B metadata sorted by exact relative path, no bodies. ---
    metas = list_published_context_pages(pinned, expected)
    assert [meta.path for meta in metas] == [policy_path, aurora_path]
    policy_meta, aurora_meta = metas
    assert aurora_meta.namespace == NAMESPACE
    assert aurora_meta.entity_id == "entity:aurora-care-guide"
    assert aurora_meta.title == "Aurora Care Guide"
    assert aurora_meta.kind == "unprofiled"
    assert aurora_meta.published_version == revision
    assert aurora_meta.citation == f"{NAMESPACE} entity:aurora-care-guide v{revision} {aurora_path}"
    assert aurora_meta.lifecycle == "approved"
    assert str(aurora_meta.review_after) == "2027-09-30"
    assert policy_meta.title == "Retail Return Policy"
    assert policy_meta.kind == "policy"
    assert policy_meta.review_after is None  # absent advisory fact stays absent
    assert all(not hasattr(meta, "body") and not hasattr(meta, "content") for meta in metas)
    with pytest.raises((TypeError, AttributeError)):  # records are immutable
        metas[0].title = "X"

    # --- Read: one byte-exact canonical page with immutable identity. ---
    aurora = read_published_context_page(pinned, expected, aurora_path)
    assert aurora.content == _AURORA_TEXT
    assert aurora.body_start_line == 18  # closing frontmatter delimiter line
    assert "# Aurora Care Guide" in aurora.body
    assert "The zephyr lane stays open during storms." in aurora.body
    assert "halcyon" not in aurora.body  # metadata stays metadata
    assert disclose_native(aurora.native) == {}  # empty when unprofiled
    assert [source.id for source in aurora.sources] == ["src-aurora-guide"]
    assert aurora.kind == "unprofiled"
    assert aurora.citation == f"{NAMESPACE} entity:aurora-care-guide v{revision} {aurora_path}"
    policy_view = read_published_context_page(pinned, expected, policy_path)
    assert policy_view.content == policy_b_text
    assert policy_view.kind == "policy"
    assert policy_view.native["status"] == "stable"

    # --- Hidden and unknown paths refuse indistinguishably, without leaks. ---
    with pytest.raises(UnadmittedInputError) as hidden_refusal:
        read_published_context_page(pinned, expected, hidden_path)
    with pytest.raises(UnadmittedInputError) as missing_refusal:
        read_published_context_page(pinned, expected, "references/no-such-page.md")
    hidden_msg = str(hidden_refusal.value)
    missing_msg = str(missing_refusal.value)
    assert hidden_msg.replace(hidden_path, "<path>") == missing_msg.replace(
        "references/no-such-page.md", "<path>"
    )
    assert "Hidden Zephyr" not in hidden_msg
    assert "entity:hidden-zephyr-notes" not in hidden_msg
    assert "calibration" not in hidden_msg

    # --- Body search: A+B visible-only; C never contributes. B carries two
    # authored body occurrences of the shared token (appended heading and
    # sentence) against A's one, so the native weighting ranks B first. ---
    hits = search_published_context_pages(pinned, expected, "zephyr")
    assert [hit.page.path for hit in hits] == [policy_path, aurora_path]
    assert all(hit.candidates_seen == 2 and hit.results_dropped == 0 for hit in hits)
    assert hits[0].score > hits[1].score > 0
    aurora_hit = next(hit for hit in hits if hit.page.path == aurora_path)
    assert tuple(aurora_hit.matched_fields) == ("body",)
    assert tuple(aurora_hit.matched_terms) == ("zephyr",)
    assert "zephyr" in aurora_hit.snippet
    assert aurora_hit.page.content == _AURORA_TEXT
    # Hand-counted verbatim excerpt: authored line 26, inside the
    # 'Ventilation' section (its heading sits on line 24).
    assert aurora_hit.excerpt == "The zephyr lane stays open during storms."
    assert (aurora_hit.line_start, aurora_hit.line_end) == (26, 26)
    assert aurora_hit.section == "Ventilation"

    # --- Metadata-only match cites the real canonical metadata passage,
    # never a fabricated body passage: the escaped tag line 8 decodes to
    # 'halcyon' for native search but is not literal in the raw bytes, and
    # the line-2 id distractor comment carrying a literal 'halcyon' is not
    # the matched field (authored tag line 8, before the body). ---
    (halcyon_hit,) = search_published_context_pages(pinned, expected, "halcyon")
    assert halcyon_hit.page.path == aurora_path
    assert tuple(halcyon_hit.matched_fields) == ("tag",)
    assert tuple(halcyon_hit.matched_terms) == ("halcyon",)
    assert halcyon_hit.excerpt == '  - "\\u0068alcyon"'
    assert (halcyon_hit.line_start, halcyon_hit.line_end) == (8, 8)
    assert halcyon_hit.line_start < aurora.body_start_line
    assert halcyon_hit.section is None
    assert halcyon_hit.candidates_seen == 1 and halcyon_hit.results_dropped == 0

    # --- Summary-only multiline match extends the same metadata-passage
    # scenario: the folded summary authored on canonical lines 9-11 must be
    # cited as its verbatim span with the original CRLF separators kept
    # (hand-counted above) and is a literal substring of the byte-exact
    # full page content. ---
    (borealis_hit,) = search_published_context_pages(pinned, expected, "borealis")
    assert borealis_hit.page.path == aurora_path
    assert tuple(borealis_hit.matched_fields) == ("summary",)
    assert tuple(borealis_hit.matched_terms) == ("borealis",)
    assert borealis_hit.excerpt == "summary: >-\r\n  borealis care\r\n  continues indoors"
    assert borealis_hit.excerpt in aurora.content
    assert (borealis_hit.line_start, borealis_hit.line_end) == (9, 11)
    assert borealis_hit.section is None
    assert borealis_hit.candidates_seen == 1 and borealis_hit.results_dropped == 0

    # --- Honest limit accounting: the native ranking keeps B alone. ---
    (only_hit,) = search_published_context_pages(pinned, expected, "zephyr", limit=1)
    assert only_hit.page.path == policy_path
    assert only_hit.candidates_seen == 2 and only_hit.results_dropped == 1

    # --- A later publication never mutates the pinned v1 reads or search. ---
    aurora_v2_text = _AURORA_TEXT + "\n## Winter notes\n\nThe aurora dims near the equinox.\n"
    (kb / aurora_path).write_text(aurora_v2_text)
    revision2 = _commit(repo)
    _publish(kb, revision2, destination, revision)
    assert read_published_context_page(pinned, expected, aurora_path).content == _AURORA_TEXT
    assert [
        hit.page.path for hit in search_published_context_pages(pinned, expected, "zephyr")
    ] == [policy_path, aurora_path]
    # The v2 pin refuses the v1 expected identity; latest is never substituted.
    with pytest.raises(IdentityMismatchError, match="published_version"):
        read_published_context_page(
            PublishedFilesystemLocation(destination, version=revision2), expected, aurora_path
        )
    expected2 = _expected_identity(kb, destination, revision2)
    pinned2 = PublishedFilesystemLocation(destination, version=revision2)
    assert read_published_context_page(pinned2, expected2, aurora_path).content == aurora_v2_text

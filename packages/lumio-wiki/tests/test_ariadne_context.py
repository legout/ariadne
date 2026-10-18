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
import hashlib
import json
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
from lumio_wiki.artifact_store import InMemoryArtifactStore
from lumio_wiki.git_authoring import (
    GitAuthoringError,
    merge_entities_in_worktree,
    preview_publication,
    publish_revision,
    remove_page_in_worktree,
    rename_page_in_worktree,
)
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.location import FilesystemLocation, PublishedFilesystemLocation
from lumio_wiki.s3_location import S3Location, S3Manifest, _get_bytes
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)

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
    assert mapping["source_ids"] == ["src-owner-rule"]
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
        "    ariadne:\n      schema:\n        - name: order_number\n"
        "          type: VARCHAR\n"
        "      observations:\n"
        '        observed_at: "2026-10-01T00:00:00+00:00"\n'
        "        scope: full\n        row_count: 10\n"
        "        candidate_keys: [order_number]\n"
        "        columns:\n          order_number:\n"
        "            null_count: 0\n            distinct_count: 10\n"
        f"        citation: {ORDERS_TABLE_URI}\n"
        "        value_evidence:\n          order_number:\n"
        "            state: observed\n"
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
            "policies/policy.md": policy_page,
            "metrics/m1.md": _metric_page(
                "entity:m1",
                "margin",
                "",
                native_policy="policies/retail-return-policy.md",
            ).replace("  required_policies:\n\n", "  required_policies: []\n"),
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

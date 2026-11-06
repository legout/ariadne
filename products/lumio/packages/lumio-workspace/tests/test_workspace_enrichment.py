from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

from lumio_wiki.artifact_store import LocalDirectoryArtifactStore
from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
from starlette.testclient import TestClient

NAMESPACE = "urn:uuid:6c6e21ec-98a4-4c0b-9153-c2eb5d3c2210"
CORPUS = (
    b"# Operations notes\n\n"
    b"## Ownership\n\n"
    b"Team A operates Service B.\n\n"
    b"Team C is mentioned in the escalation roster.\n\n"
    b"## Meeting notes\n\n"
    b"Alex proposed retaining logs for 30 days.\n"
)
SOURCE_DIGEST = hashlib.sha256(CORPUS).hexdigest()
CONTROL = """version: 2
mode: "categorized"
categories:
  - name: "entities"
  - name: "procedures"
ontology:
  entity_types:
    knowledge-artifact:
      description: >-
        A document, record, or other knowledge artifact. Its referent is the artifact
        itself, not a person, organization, service, or business object mentioned in it.
    team:
      description: "A team."
    service:
      description: "A service."
  predicates:
    operates:
      subject_types: ["team"]
      object_types: ["service"]
    proposed-log-retention-days:
      subject_types: ["service"]
      literal_kind: number
      description: "A source-attributed proposal, not an adopted retention Policy."
    runbook-note:
      subject_types: ["knowledge-artifact"]
      literal_kind: string
    team-note:
      subject_types: ["team"]
      literal_kind: string
  redirects: {}
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _page(title: str, entity_id: str, entity_type: str, *, source: bool, claims: str = "") -> str:
    source_block = (
        'sources:\n  - id: "operations-notes"\n    title: "Operations notes"\n'
        if source
        else "sources: []\n"
    )
    category = "procedures" if entity_type == "knowledge-artifact" else "entities"
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        f'entity_types: ["{entity_type}"]\n'
        f"category: {category}\n"
        'type: "synthetic"\n'
        'durability_rationale: "The synthetic source permanently supports this record."\n'
        'tags: ["synthetic"]\n'
        f'summary: "{title} synthetic record."\n'
        'lifecycle: "approved"\n'
        'visibility: "internal"\n'
        f"{source_block}"
        f"claims: {claims if claims else '[]'}\n"
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Ownership\n\n"
        + (
            "Team C is mentioned in the escalation roster.\n"
            if entity_id == "entity:team-c"
            else "Team A operates Service B.\n"
            if entity_id in {"entity:team-a", "entity:operations-runbook"}
            else "Service B ownership is discussed in the operations notes.\n"
        )
        + "\n## Meeting notes\n\nAlex proposed retaining logs for 30 days.\n"
    )


def _claim_page(
    title: str,
    entity_id: str,
    entity_type: str,
    *,
    source: bool,
    claim_block: str,
) -> str:
    return _page(title, entity_id, entity_type, source=source).replace(
        "claims: []", f"claims:\n{claim_block}"
    )


OPERATES_CLAIM = """  - id: "claim:team-a-operates-service-b"
    predicate: "operates"
    object: "entity:service-b"
    status: "accepted"
    evidence:
      - section: "Ownership"
"""
RETENTION_PROPOSAL_CLAIM = """  - id: "claim:service-b-proposed-log-retention"
    predicate: "proposed-log-retention-days"
    value: 30
    value_type: "number"
    status: "accepted"
    evidence:
      - section: "Meeting notes"
"""
TEAM_C_OPERATES_DISPUTED_CLAIM = """  - id: "claim:team-c-operates-service-b"
    predicate: "operates"
    object: "entity:service-b"
    status: "disputed"
    evidence:
      - section: "Ownership"
"""
BASE_RUNBOOK_CLAIMS = """  - id: "claim:runbook-note-one"
    predicate: "runbook-note"
    value: "original-one"
    value_type: "string"
    status: "accepted"
    evidence:
      - section: "Ownership"
  - id: "claim:runbook-note-two"
    predicate: "runbook-note"
    value: "original-two"
    value_type: "string"
    status: "accepted"
    evidence:
      - section: "Meeting notes"
"""


def _call_tool(client: TestClient, token: str, name: str, arguments: dict, request_id: int):
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        },
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def _tool(client: TestClient, token: str, name: str, arguments: dict, request_id: int) -> dict:
    response = _call_tool(client, token, name, arguments, request_id)
    payload = response.json()["result"]
    assert payload["isError"] is False, payload
    return payload["structuredContent"]


def _login(client: TestClient, token: str) -> None:
    response = client.post(
        "/auth/login",
        headers={"Origin": "https://workspace.test"},
        data={"token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303


def _digest(html: str) -> str:
    match = re.search(r'name="digest" value="([0-9a-f]{64})"', html)
    assert match is not None
    return match.group(1)


def _decision(client: TestClient, task_id: str, digest: str, decision: str):
    return client.post(
        f"/review/{task_id}",
        headers={"Origin": "https://workspace.test"},
        data={"digest": digest, "decision": decision},
    )


def _fixture(tmp_path: Path) -> tuple[WorkspaceConfig, WorkspaceState, dict[str, str], str]:
    authoring_repo = tmp_path / "authoring-repo"
    kb = authoring_repo / "kb"
    kb.mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL, encoding="utf-8")
    pages = {
        "procedures/operations_runbook.md": _claim_page(
            "Operations Runbook",
            "entity:operations-runbook",
            "knowledge-artifact",
            source=True,
            claim_block=BASE_RUNBOOK_CLAIMS,
        ),
        "entities/team_a.md": _page("Team A", "entity:team-a", "team", source=True),
        "entities/service_b.md": _page("Service B", "entity:service-b", "service", source=True),
        "entities/team_c.md": _page("Team C", "entity:team-c", "team", source=True),
    }
    for relative, markdown in pages.items():
        target = kb / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
    bindings = {
        entity_id: {"operations-notes": SOURCE_DIGEST}
        for entity_id in (
            "entity:operations-runbook",
            "entity:team-a",
            "entity:service-b",
            "entity:team-c",
        )
    }
    (kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(
            SourceReferenceManifest(
                version=1,
                namespace=NAMESPACE,
                sources={"operations-notes": "active"},
                bindings=bindings,
            )
        )
    )
    _git(authoring_repo, "init", "-q")
    _git(authoring_repo, "config", "user.name", "Fixture")
    _git(authoring_repo, "config", "user.email", "fixture@example.invalid")
    _git(authoring_repo, "add", "kb")
    _git(authoring_repo, "commit", "-qm", "admitted synthetic corpus")
    revision = _git(authoring_repo, "rev-parse", "HEAD")

    private = tmp_path / "profile-private"
    private.mkdir()
    registry = SourceRegistry(private / "registry")
    version, _action = registry.register_version(
        "operations-notes", CORPUS, filename="operations-notes.md"
    )
    assert version.content_hash == SOURCE_DIGEST
    store = LocalDirectoryArtifactStore(private / "artifacts")
    store.put_artifact(
        source_id="operations-notes",
        content_hash=SOURCE_DIGEST,
        raw_bytes=CORPUS,
        content_type="text/markdown",
        filename="operations-notes.md",
    )
    destination = tmp_path / "published"
    review = preview_publication(
        kb,
        revision,
        destination,
        "none",
        source_registry=registry,
        artifact_store=store,
        retention_required=True,
    )
    assert review.blocking_diagnostics == []
    assert publish_revision(
        kb,
        revision,
        destination,
        "none",
        review.review_digest,
        source_registry=registry,
        artifact_store=store,
        retention_required=True,
    ).activated

    profile_path = private / "profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": NAMESPACE,
                "source_registry": str(private / "registry"),
                "retention": "required",
                "artifact_store": {"kind": "local", "root": str(private / "artifacts")},
            }
        ),
        encoding="utf-8",
    )
    config = WorkspaceConfig(
        workspace_id="workspace-fixture",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=None,
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        authoring_path=kb,
        private_profile_path=profile_path,
        private_root=tmp_path / "operations",
        namespace=NAMESPACE,
    )
    state = WorkspaceState(config.state_path)
    for user in ("owner", "contributor", "reviewer"):
        state.create_local_user(user)
    owner = Actor(tenant_id="local", object_id="owner")
    contributor = Actor(tenant_id="local", object_id="contributor")
    reviewer = Actor(tenant_id="local", object_id="reviewer")
    state.grant(config.workspace_id, owner, "setup")
    state.grant(config.workspace_id, contributor)
    state.grant(config.workspace_id, contributor, "contribute")
    state.grant(config.workspace_id, reviewer, "review")
    expires = int(time.time()) + 3600
    tokens = {
        "owner_browser": state.issue_local_credential("owner", "browser", expires_at=expires)[1],
        "contributor_api": state.issue_local_credential("contributor", "api", expires_at=expires)[
            1
        ],
        "reviewer_browser": state.issue_local_credential("reviewer", "browser", expires_at=expires)[
            1
        ],
    }
    return config, state, tokens, revision


def test_enrichment_stays_pending_and_subset_requires_fresh_review(tmp_path: Path) -> None:
    config, state, tokens, base = _fixture(tmp_path)
    selected_ids = [
        "entity:operations-runbook",
        "entity:team-a",
        "entity:service-b",
        "entity:team-c",
    ]
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
    ):
        _login(owner, tokens["owner_browser"])
        setup = owner.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(owner.get("/setup").text)},
        )
        assert setup.status_code == 200, setup.text

        request = {
            "workspace_id": config.workspace_id,
            "page_ids": selected_ids,
            "expected_version": base,
            "request_key": "bounded-enrichment-request",
        }
        prepared = _tool(contributor, tokens["contributor_api"], "prepare_enrichment", request, 1)
        task_id = prepared["task_id"]
        assert prepared["status"] == "pending"
        assert prepared["published"] is False
        assert prepared["limits"] == {
            "pages": 20,
            "characters": 200_000,
            "proposed_claims": 40,
        }
        assert prepared["external_lookup"]["enabled"] is False
        assert [page["id"] for page in prepared["pages"]] == selected_ids
        assert prepared["sources"][0]["content_hash"] == SOURCE_DIGEST
        assert prepared["sources"][0]["original_available"] is True
        retried = _tool(contributor, tokens["contributor_api"], "prepare_enrichment", request, 2)
        assert retried["task_id"] == task_id

        original_answer = _tool(
            contributor,
            tokens["contributor_api"],
            "read_knowledge",
            {"title": "Operations Runbook"},
            3,
        )
        before = PublishedFilesystemLocation(config.published_path).resolve()
        assert before.lookup_by_title("Team A")[0].claims == []
        assert before.lookup_by_title("Service B")[0].claims == []
        assert before.lookup_by_title("Team C")[0].claims == []

        over_limit_team_notes = "".join(
            f'  - id: "claim:team-a-note-{index}"\n'
            '    predicate: "team-note"\n'
            f'    value: "note-{index}"\n'
            '    value_type: "string"\n'
            '    status: "accepted"\n'
            '    evidence:\n      - section: "Ownership"\n'
            for index in range(39)
        )
        changed_runbook_claims = BASE_RUNBOOK_CLAIMS.replace(
            'value: "original-one"', 'value: "edited-one"', 1
        ).replace(
            '  - id: "claim:runbook-note-two"\n'
            '    predicate: "runbook-note"\n'
            '    value: "original-two"\n'
            '    value_type: "string"\n'
            '    status: "accepted"',
            '  - id: "claim:runbook-note-two"\n'
            '    predicate: "runbook-note"\n'
            '    value: "original-two"\n'
            '    value_type: "string"\n'
            '    status: "disputed"',
            1,
        )
        over_limit = _call_tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "enrichment-over-limit",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": [
                    {
                        "filename": "team-a.md",
                        "markdown": _claim_page(
                            "Team A",
                            "entity:team-a",
                            "team",
                            source=True,
                            claim_block=over_limit_team_notes,
                        ),
                    },
                    {
                        "filename": "operations-runbook.md",
                        "markdown": _claim_page(
                            "Operations Runbook",
                            "entity:operations-runbook",
                            "knowledge-artifact",
                            source=True,
                            claim_block=changed_runbook_claims,
                        ),
                    },
                ],
            },
            40,
        ).json()["result"]
        assert over_limit["isError"] is True, over_limit
        assert "more than 40 Claims" in over_limit["content"][0]["text"]
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == base

        whole_pages = [
            {
                "filename": "team-a.md",
                "markdown": _claim_page(
                    "Team A",
                    "entity:team-a",
                    "team",
                    source=True,
                    claim_block=OPERATES_CLAIM,
                ),
            },
            {
                "filename": "service-b.md",
                "markdown": _claim_page(
                    "Service B",
                    "entity:service-b",
                    "service",
                    source=True,
                    claim_block=RETENTION_PROPOSAL_CLAIM,
                ),
            },
            {
                "filename": "team-c.md",
                "markdown": _claim_page(
                    "Team C",
                    "entity:team-c",
                    "team",
                    source=True,
                    claim_block=TEAM_C_OPERATES_DISPUTED_CLAIM,
                ),
            },
        ]
        whole = _tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "enrichment-whole-draft",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": whole_pages,
            },
            4,
        )
        assert whole["task_id"] == task_id
        assert whole["status"] == "pending_review"
        assert whole["published"] is False
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == base
        pending = PublishedFilesystemLocation(config.published_path).resolve()
        assert pending.lookup_by_title("Team A")[0].claims == []

        state.grant(
            config.workspace_id,
            Actor(tenant_id="local", object_id="reviewer"),
            "inspect_source",
        )
        _login(reviewer, tokens["reviewer_browser"])
        whole_review = reviewer.get(f"/review/{task_id}")
        assert whole_review.status_code == 200, whole_review.text
        assert "Team A operates Service B." in whole_review.text
        assert "Alex proposed retaining logs for 30 days." in whole_review.text
        assert SOURCE_DIGEST in whole_review.text
        assert "not semantic verification" in whole_review.text
        assert "claim:team-a-operates-service-b" in whole_review.text
        assert "claim:service-b-proposed-log-retention" in whole_review.text
        assert "claim:team-c-operates-service-b" in whole_review.text
        assert "potential intra-candidate conflict" in whole_review.text
        assert "Source-backed passage (exact text match" in whole_review.text
        whole_action = _digest(whole_review.text)

        rejected = _decision(reviewer, task_id, whole_action, "reject")
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "rejected"
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == base
        rejected_answer = _tool(
            contributor,
            tokens["contributor_api"],
            "read_knowledge",
            {"title": "Operations Runbook"},
            5,
        )
        assert rejected_answer == original_answer
        assert _decision(reviewer, task_id, whole_action, "approve").status_code == 409

        changed_input = _call_tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "enrichment-whole-draft",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": whole_pages[:1],
            },
            50,
        ).json()["result"]
        assert changed_input["isError"] is True, changed_input
        assert "different enrichment input" in changed_input["content"][0]["text"]

        subset = _tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "enrichment-corrected-subset",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": whole_pages[:1],
            },
            6,
        )
        assert subset["task_id"] == task_id
        assert subset["status"] == "pending_review"
        assert subset["native_candidate"] != whole["native_candidate"]
        obsolete = _call_tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "enrichment-whole-draft",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": whole_pages,
            },
            51,
        ).json()["result"]
        assert obsolete["isError"] is True, obsolete
        assert "superseded" in obsolete["content"][0]["text"]
        current = _tool(
            contributor, tokens["contributor_api"], "get_task", {"task_id": task_id}, 52
        )
        assert current["native_candidate"] == subset["native_candidate"]
        assert current["status"] == "pending_review"
        stale_subset = _decision(reviewer, task_id, whole_action, "approve")
        assert stale_subset.status_code == 409, stale_subset.text
        assert PublishedFilesystemLocation(config.published_path).read_pointer() == base

        subset_review = reviewer.get(f"/review/{task_id}")
        assert subset_review.status_code == 200, subset_review.text
        assert "Team A operates Service B." in subset_review.text
        assert "claim:team-a-operates-service-b" in subset_review.text
        assert "claim:service-b-proposed-log-retention" not in subset_review.text
        subset_action = _digest(subset_review.text)
        assert subset_action != whole_action
        approved = _decision(reviewer, task_id, subset_action, "approve")
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "published"

        admitted = PublishedFilesystemLocation(config.published_path).resolve()
        team_a_claims = admitted.lookup_by_title("Team A")[0].claims
        assert [(claim.predicate, claim.object) for claim in team_a_claims] == [
            ("operates", "entity:service-b")
        ]
        assert admitted.lookup_by_title("Service B")[0].claims == []
        assert admitted.lookup_by_title("Team C")[0].claims == []
        final_answer = _tool(
            contributor,
            tokens["contributor_api"],
            "read_knowledge",
            {"title": "Operations Runbook"},
            7,
        )
        assert final_answer["markdown"] == original_answer["markdown"]
        assert final_answer["citation"] == {
            "title": "Operations Runbook",
            "path": "procedures/operations_runbook.md",
            "published_version": subset["native_candidate"],
        }

        repeated_request = _tool(
            contributor, tokens["contributor_api"], "prepare_enrichment", request, 8
        )
        assert repeated_request["task_id"] == task_id
        assert repeated_request["status"] == "published"
        repeated_subset = _tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "enrichment-corrected-subset",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": whole_pages[:1],
            },
            9,
        )
        assert repeated_subset["native_candidate"] == subset["native_candidate"]
        assert repeated_subset["status"] == "published"


def test_enrichment_pending_recovery_precedes_correction(tmp_path: Path, monkeypatch) -> None:
    config, _state, tokens, base = _fixture(tmp_path)
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
    ):
        _login(owner, tokens["owner_browser"])
        setup = owner.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(owner.get("/setup").text)},
        )
        assert setup.status_code == 200, setup.text
        prepared = _tool(
            contributor,
            tokens["contributor_api"],
            "prepare_enrichment",
            {
                "workspace_id": config.workspace_id,
                "page_ids": [
                    "entity:operations-runbook",
                    "entity:team-a",
                    "entity:service-b",
                    "entity:team-c",
                ],
                "expected_version": base,
                "request_key": "recovery-enrichment-request",
            },
            1,
        )
        task_id = prepared["task_id"]
        whole = _tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "recovery-whole-draft",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": [
                    {
                        "filename": "team-a.md",
                        "markdown": _claim_page(
                            "Team A",
                            "entity:team-a",
                            "team",
                            source=True,
                            claim_block=OPERATES_CLAIM,
                        ),
                    }
                ],
            },
            2,
        )
        _login(reviewer, tokens["reviewer_browser"])
        action = _digest(reviewer.get(f"/review/{task_id}").text)

        original_finish = WorkspaceState.finish_review_task

        def fail_task_bookkeeping(*args, **kwargs):
            raise RuntimeError("injected SQLite failure after native activation")

        monkeypatch.setattr(WorkspaceState, "finish_review_task", fail_task_bookkeeping)
        interrupted = _decision(reviewer, task_id, action, "approve")
        assert interrupted.status_code == 409, interrupted.text
        monkeypatch.setattr(WorkspaceState, "finish_review_task", original_finish)
        assert (
            PublishedFilesystemLocation(config.published_path).read_pointer()
            == whole["native_candidate"]
        )

        correction = _call_tool(
            contributor,
            tokens["contributor_api"],
            "prepare_contribution",
            {
                "retry_key": "recovery-correction",
                "enrichment_task_id": task_id,
                "sources": [],
                "pages": [
                    {
                        "filename": "service-b.md",
                        "markdown": _claim_page(
                            "Service B",
                            "entity:service-b",
                            "service",
                            source=True,
                            claim_block=RETENTION_PROPOSAL_CLAIM,
                        ),
                    }
                ],
            },
            3,
        ).json()["result"]
        assert correction["isError"] is True, correction
        assert "published enrichment cannot be replaced" in correction["content"][0]["text"]
        recovered = _tool(
            contributor, tokens["contributor_api"], "get_task", {"task_id": task_id}, 4
        )
        assert recovered["status"] == "published"
        assert recovered["native_candidate"] == whole["native_candidate"]
        assert (
            PublishedFilesystemLocation(config.published_path).read_pointer()
            == whole["native_candidate"]
        )
        admitted = PublishedFilesystemLocation(config.published_path).resolve()
        assert [
            (claim.predicate, claim.object)
            for claim in admitted.lookup_by_title("Team A")[0].claims
        ] == [("operates", "entity:service-b")]
        assert admitted.lookup_by_title("Service B")[0].claims == []

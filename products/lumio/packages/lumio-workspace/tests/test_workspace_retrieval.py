"""Focused scoped-Evidence retrieval checks (spec0034 §12.2, AC22/23/28).

One parameterized scenario: an independently authored runbook with known
section lines, an internal reference, a restricted page with a unique marker
and alias, and a later admitted edit. Every expected value is derived from the
authored fixture text or the native publication receipts, never from service
output. Retrieval runs through the real MCP HTTP surface with the default
ZeroIndex adapter and, when the local optional dependency is present, the
operator-prepared BM25 cache.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import replace
from pathlib import Path

import lumio_wiki.git_authoring as git_authoring
import pytest
from lumio_wiki.git_authoring import preview_publication, publish_revision
from lumio_wiki.knowledge_base import (
    document_first_control_file,
    seeded_control_file,
    write_control_file,
)
from lumio_wiki.location import PublishedFilesystemLocation
from lumio_wiki.source_references import (
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_workspace import Actor, WorkspaceConfig, WorkspaceState, create_app
from lumio_workspace.__main__ import main as workspace_main
from starlette.testclient import TestClient

NAMESPACE = "urn:uuid:3f2b1c4e-8a7d-4e2f-9c1b-5d6e7f8a9b0c"

RESTRICTED_MARKER = "zebramark-restricted-escalation"
RESTRICTED_ALIAS = "zebra-escalation-alias"
# F1 collision: the visible runbook's alias equals the hidden page's canonical
# title — a valid combination (duplicate canonical titles and duplicate
# aliases are validated separately, never title/alias collisions).
COLLISION_NAME = "Escalation Secrets"
# F2 residue: the line only the interrupted candidate would contain.
RESIDUE_MARKER = "unadmitted residue marker"
# Genuinely absent from every fixture page, including as a substring.
NONSENSE_QUERY = "qqqzzq absent neverwritten"

# Independent authored fixture. The v2 admitted edit appends the "Drain
# connections" section; v1 never contains it.
RUNBOOK_V1 = (
    "---\n"
    'id: "entity:restart-runbook"\n'
    'title: "Restart Runbook"\n'
    f'aliases: ["{COLLISION_NAME}"]\n'
    'entity_types: ["knowledge-artifact"]\n'
    "category: procedures\n"
    'type: "runbook"\n'
    'durability_rationale: "The synthetic runbook permanently supports this procedure."\n'
    'tags: ["operations"]\n'
    'summary: "Restart the synthetic worker safely."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "restart-runbook-source"\n'
    '    title: "Restart runbook source"\n'
    "claims: []\n"
    "synthetic: true\n"
    "---\n"
    "\n"
    "# Restart Runbook\n"
    "\n"
    "Prepare the worker for a safe restart.\n"
    "\n"
    "## Quiesce the worker\n"
    "\n"
    "Quiesce the worker before stopping it.\n"
)
RUNBOOK_V2 = RUNBOOK_V1 + (
    "\n## Drain connections\n\nDrain open connections after the quiesce step.\n"
)
# The interrupted candidate: an ordinary native publication whose pointer
# activation never happened, leaving complete-but-unadmitted residue.
RUNBOOK_V3 = RUNBOOK_V2 + (
    "\n## Interrupted candidate note\n\nThe unadmitted residue marker stays unpublished.\n"
)

NETWORK_PAGE = (
    "---\n"
    'id: "entity:network-topology"\n'
    'title: "Network Topology"\n'
    'entity_types: ["knowledge-artifact"]\n'
    "category: references\n"
    'type: "reference"\n'
    'durability_rationale: "The synthetic overview permanently supports this check."\n'
    'tags: ["network"]\n'
    'summary: "Synthetic network topology overview."\n'
    'lifecycle: "approved"\n'
    'visibility: "internal"\n'
    "sources:\n"
    '  - id: "network-source"\n'
    '    title: "Network source"\n'
    "claims: []\n"
    "synthetic: true\n"
    "---\n"
    "\n"
    "# Network Topology\n"
    "\n"
    "The reviewed gateway inventory stays internal.\n"
    "\n"
    "## Gateway inventory\n"
    "\n"
    "Only the synthetic gateway fleet is listed here.\n"
)

ESCALATION_PAGE = (
    "---\n"
    'id: "entity:escalation-secrets"\n'
    'title: "Escalation Secrets"\n'
    f'aliases: ["{RESTRICTED_ALIAS}"]\n'
    'entity_types: ["knowledge-artifact"]\n'
    "category: procedures\n"
    'type: "runbook"\n'
    'durability_rationale: "The synthetic escalation record permanently supports this path."\n'
    'tags: ["escalation"]\n'
    'summary: "Restricted synthetic escalation path."\n'
    'lifecycle: "approved"\n'
    'visibility: "restricted"\n'
    "sources:\n"
    '  - id: "escalation-source"\n'
    '    title: "Escalation source"\n'
    "claims: []\n"
    "synthetic: true\n"
    "---\n"
    "\n"
    "# Escalation Secrets\n"
    "\n"
    "## Restricted escalation path\n"
    "\n"
    f"{RESTRICTED_MARKER} pages the on-call gateway.\n"
)

APPENDIX_FILLER = "appendix filler for the bounded read check. " * 420
APPENDIX_PAGE = (
    "---\n"
    'id: "entity:operations-appendix"\n'
    'title: "Operations Appendix"\n'
    'entity_types: ["knowledge-artifact"]\n'
    "category: references\n"
    'type: "reference"\n'
    'durability_rationale: "The synthetic appendix permanently supports this check."\n'
    'tags: ["operations"]\n'
    'summary: "Synthetic appendix with a long section."\n'
    'lifecycle: "approved"\n'
    'visibility: "public"\n'
    "sources:\n"
    '  - id: "appendix-source"\n'
    '    title: "Appendix source"\n'
    "claims: []\n"
    "synthetic: true\n"
    "---\n"
    "\n"
    "# Operations Appendix\n"
    "\n"
    "## Short appendix note\n"
    "\n"
    "appendix token appears here.\n"
    "\n"
    "## Full appendix dump\n"
    "\n"
    f"{APPENDIX_FILLER}\n"
)

# Hand-counted from the authored fixture text above (1-based file lines; the
# published loader numbers the body from the closing frontmatter fence, so the
# 18-line frontmatter puts "# Restart Runbook" on line 20). The splitlines
# checks tie each literal to the exact fixture text.
assert RUNBOOK_V1.splitlines()[19] == "# Restart Runbook"
assert RUNBOOK_V1.splitlines()[23] == "## Quiesce the worker"
assert RUNBOOK_V1.splitlines()[25] == "Quiesce the worker before stopping it."
assert RUNBOOK_V2.splitlines()[27] == "## Drain connections"
assert RUNBOOK_V2.splitlines()[29] == "Drain open connections after the quiesce step."
V1_QUIESCE_SPAN = (24, 26)
V2_QUIESCE_SPAN = (24, 27)
V2_DRAIN_SPAN = (28, 30)
QUIESCE_SECTION_TEXT = "## Quiesce the worker\n\nQuiesce the worker before stopping it."
DRAIN_SECTION_TEXT = "## Drain connections\n\nDrain open connections after the quiesce step."
V1_RUNBOOK_MARKDOWN = (
    "# Restart Runbook\n\nPrepare the worker for a safe restart.\n\n"
    "## Quiesce the worker\n\nQuiesce the worker before stopping it."
)
APPENDIX_SHORT_TEXT = "## Short appendix note\n\nappendix token appears here."
assert APPENDIX_PAGE.splitlines()[20] == "## Short appendix note"
assert APPENDIX_PAGE.splitlines()[22] == "appendix token appears here."
assert APPENDIX_PAGE.splitlines()[24] == "## Full appendix dump"
APPENDIX_SHORT_SPAN = (21, 24)
APPENDIX_FULL_SPAN = (25, 27)
APPENDIX_FULL_TEXT = "## Full appendix dump\n\n" + APPENDIX_FILLER.strip()
assert len(APPENDIX_SHORT_TEXT) <= 16000 < len(APPENDIX_FULL_TEXT)

VISIBLE_ENTITY_IDS = {
    "entity:restart-runbook",
    "entity:network-topology",
    "entity:operations-appendix",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _published_fixture(
    tmp_path: Path, monkeypatch, backend: str = "zero-index"
) -> tuple[WorkspaceConfig, str, str, str]:
    """v1, the admitted v2 edit, and complete-but-unadmitted residue (F2).

    The residue is produced by injecting an ordinary interruption into the
    native publication's pointer activation: the candidate version directory,
    manifest, sealed record, and preactivation receipt are all complete, while
    the current pointer stays at v2 — exactly the state an interrupted
    publication leaves behind.
    """
    repo = tmp_path / "authoring-repo"
    kb = repo / "kb"
    kb.mkdir(parents=True)
    write_control_file(kb, document_first_control_file(seeded_control_file()))
    (kb / "restart_runbook.md").write_text(RUNBOOK_V1, encoding="utf-8")
    (kb / "network_topology.md").write_text(NETWORK_PAGE, encoding="utf-8")
    (kb / "escalation_runbook.md").write_text(ESCALATION_PAGE, encoding="utf-8")
    (kb / "operations_appendix.md").write_text(APPENDIX_PAGE, encoding="utf-8")
    (kb / ".lumio-authoring.yaml").write_bytes(
        serialize_source_reference_manifest(SourceReferenceManifest(version=1, namespace=NAMESPACE))
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    destination = tmp_path / "published"
    _git(repo, "add", "kb")
    _git(repo, "commit", "-qm", "synthetic retrieval baseline")
    v1 = _git(repo, "rev-parse", "HEAD")
    review_v1 = preview_publication(kb, v1, destination, "none")
    assert review_v1.blocking_diagnostics == []
    assert publish_revision(kb, v1, destination, "none", review_v1.review_digest).activated
    (kb / "restart_runbook.md").write_text(RUNBOOK_V2, encoding="utf-8")
    _git(repo, "add", "kb")
    _git(repo, "commit", "-qm", "admitted runbook edit")
    v2 = _git(repo, "rev-parse", "HEAD")
    review_v2 = preview_publication(kb, v2, destination, v1)
    assert review_v2.blocking_diagnostics == []
    assert publish_revision(kb, v2, destination, v1, review_v2.review_digest).activated
    # Third candidate: publish it with the pointer activation interrupted so
    # only complete unadmitted residue remains (cheap stable seam on the
    # public module-level atomic write; readers never publish).
    (kb / "restart_runbook.md").write_text(RUNBOOK_V3, encoding="utf-8")
    _git(repo, "add", "kb")
    _git(repo, "commit", "-qm", "interrupted candidate")
    residue = _git(repo, "rev-parse", "HEAD")
    review_residue = preview_publication(kb, residue, destination, v2)
    assert review_residue.blocking_diagnostics == []
    real_write = git_authoring.atomic_write_bytes

    def interrupted_write(path, *args, **kwargs):
        if str(path).endswith("current.json"):
            raise OSError("synthetic interruption before pointer activation")
        return real_write(path, *args, **kwargs)

    monkeypatch.setattr(git_authoring, "atomic_write_bytes", interrupted_write)
    try:
        publish_revision(kb, residue, destination, v2, review_residue.review_digest)
    except OSError:
        pass
    else:
        raise AssertionError("the injected publication interruption did not occur")
    monkeypatch.setattr(git_authoring, "atomic_write_bytes", real_write)
    assert PublishedFilesystemLocation(destination).read_pointer() == v2
    config = WorkspaceConfig(
        workspace_id="workspace-retrieval",
        external_url="https://workspace.test",
        published_path=destination,
        published_version=None,
        state_path=tmp_path / "state.sqlite3",
        identity=None,
        auth_mode="local-token",
        private_root=tmp_path / "operations",
        retrieval_backend=backend,
    )
    return config, v1, v2, residue


def _reader_token(config: WorkspaceConfig) -> str:
    state = WorkspaceState(config.state_path)
    state.create_local_user("reader")
    state.grant(config.workspace_id, Actor(tenant_id="local", object_id="reader"))
    expires = int(time.time()) + 3600
    return state.issue_local_credential("reader", "api", expires_at=expires)[1]


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


def _tool_result(client: TestClient, token: str, name: str, arguments: dict, request_id: int):
    response = _call_tool(client, token, name, arguments, request_id)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


def _prepare_bm25_cache(config: WorkspaceConfig, monkeypatch, v2: str) -> None:
    """Run the operator-only prepare-retrieval command against the fixture env."""
    monkeypatch.setenv("LUMIO_WORKSPACE_AUTH_MODE", "local-token")
    monkeypatch.setenv("LUMIO_WORKSPACE_ID", config.workspace_id)
    monkeypatch.setenv("LUMIO_WORKSPACE_EXTERNAL_URL", config.external_url)
    monkeypatch.setenv("LUMIO_WORKSPACE_PUBLISHED_PATH", str(config.published_path))
    monkeypatch.delenv("LUMIO_WORKSPACE_PUBLISHED_VERSION", raising=False)
    monkeypatch.setenv("LUMIO_WORKSPACE_STATE_PATH", str(config.state_path))
    monkeypatch.setenv("LUMIO_WORKSPACE_PRIVATE_ROOT", str(config.private_root))
    monkeypatch.setenv("LUMIO_WORKSPACE_RETRIEVAL_BACKEND", "bm25")
    assert workspace_main(["prepare-retrieval"]) == 0
    cache = config.operational_root / "retrieval-cache" / v2
    assert cache.exists()


@pytest.mark.parametrize("retrieval_backend", ["zero-index", "bm25"])
def test_scoped_evidence_preserves_version_and_hides_restricted(
    tmp_path: Path, monkeypatch, retrieval_backend: str
) -> None:
    config, v1, v2, residue = _published_fixture(tmp_path, monkeypatch, retrieval_backend)
    token = _reader_token(config)

    if retrieval_backend == "bm25":
        pytest.importorskip(
            "lancedb",
            reason="optional BM25 dependency unavailable; only the zero-index lane runs",
        )
        _prepare_bm25_cache(config, monkeypatch, v2)

    with TestClient(create_app(config), base_url="https://workspace.test") as reader:
        # --- A hidden alias and a missing title are indistinguishable from
        # missing (the hidden canonical title case is the F1 collision below).
        for title in (RESTRICTED_ALIAS, "Page That Never Existed"):
            assert _tool_result(reader, token, "read_knowledge", {"title": title}, 1) == {
                "found": False
            }
        marker_search = _tool_result(
            reader, token, "search_knowledge", {"query": RESTRICTED_MARKER, "limit": 20}, 2
        )
        nonsense_search = _tool_result(
            reader, token, "search_knowledge", {"query": NONSENSE_QUERY, "limit": 20}, 3
        )
        assert marker_search == nonsense_search
        assert marker_search["published_version"] == v2
        assert marker_search["results"] == []
        marker_retrieve = _tool_result(
            reader, token, "retrieve_knowledge", {"query": RESTRICTED_MARKER}, 4
        )
        nonsense_retrieve = _tool_result(
            reader, token, "retrieve_knowledge", {"query": NONSENSE_QUERY}, 5
        )
        assert marker_retrieve == nonsense_retrieve
        assert marker_retrieve["results"] == []
        assert marker_retrieve["omitted"] == []
        assert marker_retrieve["published_version"] == v2

        # --- Visible-only rank and counts: restricted content never enters the
        # candidate set, so its unique terms cannot alter ranking or counts.
        search = _tool_result(
            reader, token, "search_knowledge", {"query": "gateway", "limit": 20}, 6
        )
        assert [entry["title"] for entry in search["results"]] == ["Network Topology"]
        assert search["results"][0]["citation"] == {
            "title": "Network Topology",
            "path": "network_topology.md",
        }
        assert search["results"][0]["entity_id"] == "entity:network-topology"
        gateway = _tool_result(reader, token, "retrieve_knowledge", {"query": "gateway"}, 7)
        assert {result["evidence"]["page_path"] for result in gateway["results"]} == {
            "network_topology.md"
        }
        # The restricted escalation section also contains "gateway"; if it were
        # postfiltered instead of excluded before ranking, this count would be 3.
        assert gateway["results"][0]["trace"]["candidates_seen"] == 2
        assert {result["entity_id"] for result in gateway["results"]} == {"entity:network-topology"}

        quiesce = _tool_result(reader, token, "retrieve_knowledge", {"query": "quiesce"}, 8)
        assert [result["evidence"]["section_title"] for result in quiesce["results"]] == [
            "Quiesce the worker",
            "Drain connections",
        ]
        assert [result["evidence"]["text"] for result in quiesce["results"]] == [
            QUIESCE_SECTION_TEXT,
            DRAIN_SECTION_TEXT,
        ]
        assert [result["evidence"]["line_start"] for result in quiesce["results"]] == [
            V2_QUIESCE_SPAN[0],
            V2_DRAIN_SPAN[0],
        ]
        assert [result["evidence"]["line_end"] for result in quiesce["results"]] == [
            V2_QUIESCE_SPAN[1],
            V2_DRAIN_SPAN[1],
        ]
        assert quiesce["published_version"] == v2
        assert all(result["entity_id"] == "entity:restart-runbook" for result in quiesce["results"])

        # --- Bounded text with truthful omission of the oversized indivisible unit.
        appendix = _tool_result(reader, token, "retrieve_knowledge", {"query": "appendix"}, 9)
        assert [result["evidence"]["text"] for result in appendix["results"]] == [
            APPENDIX_SHORT_TEXT
        ]
        assert appendix["text_characters"] == len(APPENDIX_SHORT_TEXT)
        assert len(appendix["omitted"]) == 1
        omitted = appendix["omitted"][0]
        assert omitted["page_title"] == "Operations Appendix"
        assert omitted["page_path"] == "operations_appendix.md"
        assert omitted["section_title"] == "Full appendix dump"
        assert (omitted["line_start"], omitted["line_end"]) == APPENDIX_FULL_SPAN
        assert "text" not in omitted
        assert appendix["published_version"] == v2

        # --- Exact old-version reread of the cited section and page.
        quiesce_v1 = _tool_result(
            reader,
            token,
            "retrieve_knowledge",
            {"query": "quiesce", "published_version": v1},
            10,
        )
        assert quiesce_v1["published_version"] == v1
        assert [result["evidence"]["section_title"] for result in quiesce_v1["results"]] == [
            "Quiesce the worker"
        ]
        assert quiesce_v1["results"][0]["evidence"]["text"] == QUIESCE_SECTION_TEXT
        assert (quiesce_v1["results"][0]["evidence"]["line_start"],) == (V1_QUIESCE_SPAN[0],)
        assert (quiesce_v1["results"][0]["evidence"]["line_end"],) == (V1_QUIESCE_SPAN[1],)
        assert "Drain" not in quiesce_v1["results"][0]["evidence"]["text"]
        read_v1 = _tool_result(
            reader,
            token,
            "read_knowledge",
            {"title": "Restart Runbook", "published_version": v1},
            11,
        )
        assert read_v1["found"] is True
        assert read_v1["markdown"].strip() == V1_RUNBOOK_MARKDOWN
        assert read_v1["summary"] == "Restart the synthetic worker safely."
        assert read_v1["entity_id"] == "entity:restart-runbook"
        assert read_v1["citation"] == {
            "title": "Restart Runbook",
            "path": "restart_runbook.md",
            "published_version": v1,
        }
        assert set(read_v1) == {
            "found", "title", "summary", "markdown", "entity_id", "citation", "sources"
        }
        # #104: published attribution plus a reference action only; no private store facts
        assert all(set(s) == {"id", "title", "url", "reference"} for s in read_v1["sources"])

        # --- Stable Entity IDs and exact versions across surfaces and versions.
        current_read = _tool_result(
            reader, token, "read_knowledge", {"title": "Restart Runbook"}, 12
        )
        assert current_read["citation"]["published_version"] == v2
        assert "Drain connections" in current_read["markdown"]
        assert current_read["entity_id"] == read_v1["entity_id"]
        assert quiesce["results"][0]["entity_id"] == read_v1["entity_id"]
        runbook_search = _tool_result(
            reader, token, "search_knowledge", {"query": "quiesce", "limit": 20}, 13
        )
        assert [entry["title"] for entry in runbook_search["results"]] == ["Restart Runbook"]
        assert runbook_search["results"][0]["entity_id"] == read_v1["entity_id"]
        assert runbook_search["published_version"] == v2

        # An unsupported version is refused, never silently served as current.
        refused = _call_tool(
            reader,
            token,
            "read_knowledge",
            {"title": "Restart Runbook", "published_version": "9999-not-admitted"},
            14,
        )
        assert refused.json()["result"]["isError"] is True
        refused_retrieve = _call_tool(
            reader,
            token,
            "retrieve_knowledge",
            {"query": "quiesce", "published_version": "9999-not-admitted"},
            15,
        )
        assert refused_retrieve.json()["result"]["isError"] is True

        # --- F1: a visible alias resolves even when a hidden page claims the
        # same canonical title; the authorized result equals the canonical read
        # of that same visible page (title precedence inside the authorized
        # view; hidden content can neither suppress nor be distinguished).
        collision_read = _tool_result(
            reader, token, "read_knowledge", {"title": COLLISION_NAME}, 30
        )
        canonical_read = _tool_result(
            reader, token, "read_knowledge", {"title": "Restart Runbook"}, 31
        )
        assert collision_read == canonical_read
        assert collision_read["found"] is True
        collision_search = _tool_result(
            reader, token, "search_knowledge", {"query": COLLISION_NAME, "limit": 20}, 32
        )
        assert [entry["title"] for entry in collision_search["results"]] == ["Restart Runbook"]

        # --- F2: complete-but-unadmitted publication residue is denied
        # generically on caller-selected reads and Evidence — a verified
        # preactivation receipt alone never admits a version; the admitted
        # older version stays readable and residue content never surfaces.
        residue_denied_read = _call_tool(
            reader,
            token,
            "read_knowledge",
            {"title": "Restart Runbook", "published_version": residue},
            33,
        )
        assert residue_denied_read.json()["result"]["isError"] is True
        residue_denied_retrieve = _call_tool(
            reader,
            token,
            "retrieve_knowledge",
            {"query": "quiesce", "published_version": residue},
            34,
        )
        assert residue_denied_retrieve.json()["result"]["isError"] is True
        assert (
            _tool_result(
                reader, token, "search_knowledge", {"query": RESIDUE_MARKER, "limit": 20}, 35
            )["results"]
            == []
        )
        assert (
            _tool_result(reader, token, "retrieve_knowledge", {"query": RESIDUE_MARKER}, 36)[
                "results"
            ]
            == []
        )
        assert (
            _tool_result(
                reader,
                token,
                "read_knowledge",
                {"title": "Restart Runbook", "published_version": v1},
                37,
            )["found"]
            is True
        )

        # --- Effective backend disclosure for this lane.
        bm25_healthy = retrieval_backend == "bm25" and quiesce["retrieval"]["fallback"] is None
        expected_backend = "lancedb-bm25" if bm25_healthy else "zero-index"
        if retrieval_backend == "bm25":
            # The v1 reread has no prepared cache for that version: explicit
            # truthful lexical fallback over the same admitted view.
            assert quiesce_v1["retrieval"]["backend"] == "zero-index"
            assert quiesce_v1["retrieval"]["fallback"] is not None
            assert "BM25" in quiesce["results"][0]["trace"]["stages"][0]["detail"]
        else:
            assert quiesce["retrieval"] == {"backend": "zero-index", "fallback": None}
            assert quiesce_v1["retrieval"] == {"backend": "zero-index", "fallback": None}
        assert quiesce["retrieval"]["backend"] == expected_backend

    # --- AC28: the integrated workspace refuses the standalone Evidence tool
    # instead of changing its governed knowledge view; existing reads remain.
    integrated = replace(config, analytics_project_id="synthetic-project")
    with TestClient(create_app(integrated), base_url="https://workspace.test") as client:
        refused_integrated = _call_tool(
            client, token, "retrieve_knowledge", {"query": "quiesce"}, 20
        )
        assert refused_integrated.json()["result"]["isError"] is True
        assert "integrated" in refused_integrated.json()["result"]["content"][0]["text"]
        still_reads = _tool_result(
            client, token, "read_knowledge", {"title": "Restart Runbook"}, 21
        )
        assert still_reads["found"] is True

from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

from lumio_wiki.location import PublishedFilesystemLocation
from lumio_workspace import create_app
from lumio_workspace.operations import quiesced_backup, restore
from starlette.testclient import TestClient

_review = importlib.import_module(
    "products.lumio.packages.lumio-workspace.tests.test_workspace_review"
)
_call_tool = _review._call_tool
_confirm_setup = _review._confirm_setup
_contribute = _review._contribute
_decision = _review._decision
_digest = _review._digest
_fixture = _review._fixture
_login = _review._login

TITLE_A = "Operations Runbook"
TITLE_B = "Operations Followup"
ADDITION_A = "Version A: quiesce, back up, and restore before swapping the data root."
ADDITION_B = "Version B stays pending until a fresh review."
# Independent oracle: the admitted body is exactly the reviewed page markdown.
EXPECTED_A_BODY = (
    "# Operations Runbook\n\nStop the old worker.\n\n<unsafe>&review\n\n"
    "Version A: quiesce, back up, and restore before swapping the data root."
)


def test_restore_and_revocation_preserve_admitted_only_access(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _fixture(tmp_path, monkeypatch)
    config = fixture.config
    with (
        TestClient(create_app(config), base_url="https://workspace.test") as owner,
        TestClient(create_app(config), base_url="https://workspace.test") as contributor,
        TestClient(create_app(config), base_url="https://workspace.test") as reviewer,
    ):
        _confirm_setup(owner, fixture)
        task_a = _contribute(
            contributor,
            fixture,
            retry_key="operations-version-a",
            title=TITLE_A,
            addition=ADDITION_A,
            source_id="operations-runbook-source",
            filename="operations-runbook.md",
            request_id=1,
        )
        task_b = _contribute(
            contributor,
            fixture,
            retry_key="operations-version-b",
            title=TITLE_B,
            addition=ADDITION_B,
            source_id="operations-followup-source",
            filename="operations-followup.md",
            # Chains from A's candidate, so B stays reviewable after A is admitted.
            continuation_task_id=task_a["task_id"],
            request_id=2,
        )
        _login(reviewer, fixture.reviewer_browser)
        digest_a = _digest(reviewer.get(f"/review/{task_a['task_id']}").text)
        approved_a = _decision(reviewer, task_a["task_id"], digest_a, "approve")
        assert approved_a.status_code == 200, approved_a.text
        version_a = PublishedFilesystemLocation(config.published_path).read_pointer()
        assert version_a == task_a["native_candidate"]
        # An outstanding browser review action exists for the pending candidate B.
        outstanding = _digest(reviewer.get(f"/review/{task_b['task_id']}").text)

    # Quiesced offline backup, then restore into a second data directory. The
    # restored service resolves the current pointer instead of the old pin.
    backup_root = quiesced_backup(config, tmp_path / "workspace-backup")
    second_root = tmp_path / "second-data-root"
    restored = restore(backup_root, second_root, replace(config, published_version=None))
    assert restored.state_path == second_root / "state.sqlite3"
    assert restored.private_root == second_root / "private"
    assert restored.authoring_path == second_root / "authoring-repo" / "kb"
    assert restored.published_path == second_root / "published"
    assert restored.private_profile_path == second_root / "profile.json"

    with (
        TestClient(create_app(restored), base_url="https://workspace.test") as owner2,
        TestClient(create_app(restored), base_url="https://workspace.test") as contributor2,
        TestClient(create_app(restored), base_url="https://workspace.test") as reviewer2,
    ):
        # Admitted A remains the sole readable version after the restore.
        result_a = _call_tool(
            contributor2, fixture.contributor_api, "read_knowledge", {"title": TITLE_A}, 10
        ).json()["result"]
        assert result_a["isError"] is False, result_a
        read_a = result_a["structuredContent"]
        assert read_a["markdown"].strip() == EXPECTED_A_BODY
        assert read_a["citation"]["published_version"] == version_a
        hidden_b = _call_tool(
            contributor2, fixture.contributor_api, "read_knowledge", {"title": TITLE_B}, 11
        ).json()["result"]
        assert hidden_b["isError"] is False, hidden_b
        assert hidden_b["structuredContent"] == {"found": False}
        pending_b = _call_tool(
            contributor2, fixture.contributor_api, "get_task", {"task_id": task_b["task_id"]}, 12
        ).json()["result"]["structuredContent"]
        assert pending_b["status"] == "pending_review"
        assert pending_b["published"] is False

        # The moved data root changes the setup attachment identity by design;
        # the owner re-confirms the restored target before new writes are accepted.
        _login(owner2, fixture.owner_browser)
        setup_confirm = owner2.post(
            "/setup",
            headers={"Origin": "https://workspace.test"},
            data={"digest": _digest(owner2.get("/setup").text)},
        )
        assert setup_confirm.status_code == 200, setup_confirm.text

        # Restore dropped browser sessions; the reviewer signs in again with the
        # unchanged operator-issued credential, re-established outside content.
        _login(reviewer2, fixture.reviewer_browser)
        fresh_page = reviewer2.get(f"/review/{task_b['task_id']}")
        assert fresh_page.status_code == 200, fresh_page.text
        fresh_digest = _digest(fresh_page.text)
        assert fresh_digest != outstanding
        assert reviewer2.get("/membership").status_code == 403

        # The pre-backup review action cannot activate anything after the restore.
        stale = _decision(reviewer2, task_b["task_id"], outstanding, "approve")
        assert stale.status_code == 409
        assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_a

        # The owner assigns and then removes the reviewer through the browser
        # membership surface; original/source/data access stays off this page.
        listing = owner2.get("/membership")
        assert listing.status_code == 200, listing.text
        assert "reviewer" in listing.text

        def membership_post(**data):
            return owner2.post(
                "/membership", headers={"Origin": "https://workspace.test"}, data=data
            )

        granted = membership_post(user_id="reviewer", capability="read", action="grant")
        assert granted.status_code == 200, granted.text
        assert granted.json()["capabilities"] == ["read", "review"]
        revoked_read = membership_post(
            user_id="reviewer", capability="read", action="revoke"
        )
        assert revoked_read.status_code == 200, revoked_read.text
        assert revoked_read.json()["capabilities"] == ["review"]
        refused = membership_post(
            user_id="reviewer", capability="inspect_source", action="grant"
        )
        assert refused.status_code == 400
        revoked_review = membership_post(
            user_id="reviewer", capability="review", action="revoke"
        )
        assert revoked_review.status_code == 200, revoked_review.text
        assert revoked_review.json()["capabilities"] == []

        # The removed member is denied on both routes despite valid credentials
        # and a fresh session; the API denial follows this page's own grant.
        assert reviewer2.get(f"/review/{task_b['task_id']}").status_code == 403
        assert _decision(reviewer2, task_b["task_id"], fresh_digest, "approve").status_code == 403
        denied_status = _call_tool(
            reviewer2, fixture.reviewer_api, "workspace_status", {}, 13
        ).json()["result"]
        assert denied_status["isError"] is True

        # Nothing activated: A stays the sole readable version and B stays pending.
        assert PublishedFilesystemLocation(restored.published_path).read_pointer() == version_a
        still_pending = _call_tool(
            contributor2, fixture.contributor_api, "get_task", {"task_id": task_b["task_id"]}, 14
        ).json()["result"]["structuredContent"]
        assert still_pending["status"] == "pending_review"
        assert still_pending["published"] is False

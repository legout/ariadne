"""Source grants (spec 0040 §3.4.2/§3.4.4; AC2, AC4): the append-only grant record
that replaces the proposal-local approval file, and `add`'s credential-free entries.
Expected values are hand-worked from the spec."""

import json
import os
import sys
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import authoring_sources  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from tests.test_git_authoring import complete_bundle_project, grant_sources  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.mark.parametrize(
    "dsn", ["postgresql://svc:hunter2pass@db.example/app", "postgres://db.example/app"]
)
def test_add_refuses_an_inline_postgres_dsn_and_names_the_connection_env_form(dsn):
    with pytest.raises(ValueError, match="connection_env") as error:
        authoring_sources.source_entry(dsn, type="postgres")
    assert "hunter2pass" not in str(error.value)  # the credential is never echoed


def test_add_builds_a_credential_free_entry_for_a_file_and_a_postgres_variable():
    assert authoring_sources.source_entry("data/Orders 2026.parquet") == {
        "name": "orders_2026",
        "type": "parquet",
        "path": "data/Orders 2026.parquet",
    }
    assert authoring_sources.source_entry("WAREHOUSE_DSN", name="wh", type="postgres") == {
        "name": "wh",
        "type": "postgres",
        "connection_env": "WAREHOUSE_DSN",
    }


def test_a_grant_is_append_only_and_binds_attribution_to_the_exact_identity(tmp_path):
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    resolved, digest = authoring_sources.candidate_sources(project, started["candidate_revision"])
    assert resolved is not None and digest is not None
    # nothing is granted before the human step
    assert authoring_sources.approval_state(project, resolved, digest)["state"] == "absent"

    grant_sources(api, started["proposal"], started["candidate_revision"], digest)
    first = json.loads((project / ".ariadne" / "source_grants.json").read_text(encoding="utf-8"))
    # the fixture registry declares two parquet sources: one grant each, in order
    assert [g["source"]["name"] for g in first["grants"]] == ["events", "labels"]
    assert {g["by"] for g in first["grants"]} == {"human:test-operator"}
    assert [g["seq"] for g in first["grants"]] == [1, 2]
    assert authoring_sources.approval_state(project, resolved, digest)["state"] == "current"

    grant_sources(api, started["proposal"], started["candidate_revision"], digest)
    second = json.loads((project / ".ariadne" / "source_grants.json").read_text(encoding="utf-8"))
    assert second["grants"][:2] == first["grants"]  # earlier grants are never rewritten
    assert [g["seq"] for g in second["grants"]] == [1, 2, 3, 4]


def test_a_grant_refuses_a_stale_digest_and_writes_nothing(tmp_path):
    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    started = api.start_proposal()
    with pytest.raises(ValueError, match="digest"):
        grant_sources(api, started["proposal"], started["candidate_revision"], "0" * 64)
    assert not (project / ".ariadne" / "source_grants.json").exists()


def test_the_served_release_covers_its_own_identities_without_a_grant(tmp_path):
    from tests.test_git_admission import _policy_edit, admit, admitted_ready

    project = complete_bundle_project(tmp_path)
    api = AuthoringProject(project)
    review, _ = admitted_ready(api, project, _policy_edit("Served body."))
    assert admit(project, review) == 0
    (project / ".ariadne" / "source_grants.json").unlink()  # no grant record at all
    resolved, digest = authoring_sources.candidate_sources(project, review["revision"])
    assert authoring_sources.approval_state(project, resolved, digest)["state"] == "current"

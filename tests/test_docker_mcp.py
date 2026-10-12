"""Opt-in real Compose check: build first, set ARIADNE_DOCKER_TEST_IMAGE to its tag."""

import json
import os
import secrets
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get("ARIADNE_DOCKER_TEST_IMAGE")

CLIENT = """
import asyncio, json, os, sys, urllib.request, urllib.error
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from httpx import AsyncClient
url = 'http://ariadne:8000'
headers = {'Authorization': 'Bearer ' + os.environ['ARIADNE_HTTP_TOKEN']}
if sys.argv[1] == 'probes':
    for path, body in [('/healthz', {'status':'ok'}), ('/readyz', {'status':'ready'})]:
        try:
            urllib.request.urlopen(url + path, timeout=10)
        except urllib.error.HTTPError as error:
            assert error.code == 401 and json.load(error) == {'error':'unauthorized'}
        else:
            raise AssertionError('probe allowed without bearer')
        request = urllib.request.Request(url + path, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            assert response.status == 200 and json.load(response) == body
    print(json.dumps({'probes':'ok', 'uid':os.getuid()}))
else:
    async def run():
        async with AsyncClient(headers=headers) as client:
            async with streamable_http_client(url + '/mcp', http_client=client) as (r,w,_):
                async with ClientSession(r,w) as session:
                    await session.initialize()
                    if sys.argv[1] == 'tools':
                        return [t.name for t in (await session.list_tools()).tools]
                    result = await session.call_tool(sys.argv[1], json.loads(sys.argv[2]))
                    assert not result.isError, result
                    return json.loads(result.content[0].text)
    print(json.dumps(asyncio.run(run())))
"""


@pytest.mark.skipif(not IMAGE, reason="set ARIADNE_DOCKER_TEST_IMAGE after building the Dockerfile")
def test_compose_external_project_auth_and_proposals_survive_recreation(tmp_path):
    """A real network client authors mounted Git state; host and replacement container read it."""
    if os.getuid() == 0:
        pytest.skip("run as a non-root project owner to verify matching mount permissions")
    project = tmp_path / "external-project"
    project.mkdir()
    (project / "README.md").write_text("Synthetic external data project.\n")
    for args in (
        ["init", "-q"],
        ["config", "user.name", "Synthetic Docker test"],
        ["config", "user.email", "docker-test@example.invalid"],
        ["add", "README.md"],
        ["commit", "-qm", "Synthetic initial revision"],
    ):
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)

    name = "ariadne-test-" + secrets.token_hex(6)
    env = {
        **os.environ,
        "ARIADNE_IMAGE": IMAGE,
        "ARIADNE_PROJECT_DIR": str(project),
        "ARIADNE_UID": str(os.getuid()),
        "ARIADNE_GID": str(os.getgid()),
        "ARIADNE_TOOLSET": "authoring",
        "ARIADNE_HTTP_TOKEN": secrets.token_urlsafe(24),
    }
    compose = [
        "docker",
        "compose",
        "--env-file",
        "/dev/null",
        "-p",
        name,
        "-f",
        str(ROOT / "compose.yaml"),
    ]

    def command(argv, *, check=True):
        return subprocess.run(
            argv, env=env, cwd=ROOT, text=True, capture_output=True, check=check, timeout=120
        )

    def client(operation, arguments=None):
        result = command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                name + "_default",
                "-e",
                "ARIADNE_HTTP_TOKEN",
                "--entrypoint",
                "python",
                IMAGE,
                "-c",
                CLIENT,
                operation,
                json.dumps(arguments or {}),
            ]
        )
        return json.loads(result.stdout)

    config = json.loads(command([*compose, "config", "--format", "json"]).stdout)
    service = config["services"]["ariadne"]
    assert not service.get("ports")
    assert service["volumes"][0]["source"] == service["volumes"][0]["target"] == str(project)
    loopback = json.loads(
        command(
            [
                *compose,
                "-f",
                str(ROOT / "compose.loopback.yaml"),
                "config",
                "--format",
                "json",
            ]
        ).stdout
    )
    assert [p["host_ip"] for p in loopback["services"]["ariadne"]["ports"]] == ["127.0.0.1"]

    try:
        command([*compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "90"])
        container = command([*compose, "ps", "-q", "ariadne"]).stdout.strip()
        [inspection] = json.loads(command(["docker", "inspect", container]).stdout)
        assert inspection["Config"]["User"] == f"{os.getuid()}:{os.getgid()}"
        assert not inspection["HostConfig"]["PortBindings"]
        assert inspection["State"]["Health"]["Status"] == "healthy"
        assert client("probes")["uid"] != 0
        tools = client("tools")
        assert "authoring_start_proposal" in tools and "get_metric" not in tools
        started = client("authoring_start_proposal")
        notes = "# Seed Notes\n\nSynthetic rule, pending human review.\n"
        edited = client(
            "authoring_edit_proposal",
            {
                "proposal": started["proposal"],
                "expected_revision": started["candidate_revision"],
                "edit": {"kind": "seed_notes", "content": notes},
            },
        )
        worktrees = command(["git", "-C", str(project), "worktree", "list", "--porcelain"])
        paths = [
            line.removeprefix("worktree ")
            for line in worktrees.stdout.splitlines()
            if line.startswith("worktree ")
        ]
        assert len(paths) == 2 and all(Path(path).is_dir() for path in paths)
        for path in paths:
            command(["git", "-C", path, "status", "--porcelain"])

        command(
            [
                *compose,
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                "--wait",
                "--wait-timeout",
                "90",
            ]
        )
        restored = client(
            "authoring_read_artifact",
            {
                "proposal": started["proposal"],
                "kind": "seed_notes",
            },
        )
        assert restored["content"] == notes and restored["revision"] == edited["revision"]
        assert (project / ".ariadne" / "proposals" / (started["proposal"] + ".json")).is_file()
        assert not (project / ".ariadne" / "current.json").exists()  # no human admission
    finally:
        command([*compose, "down", "--remove-orphans"])

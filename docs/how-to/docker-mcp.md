# How-to: Docker MCP with an external data project

For an operator preparing a private HTTPS MCP service. This template packages
Ariadne software, not your data project. It does not deploy a proxy or approve
exposure. Build locally from this checkout; the image has Python, Git and
`ariadneai[mcp]`, but no optional PDF/Office converters. Markdown/text inputs
work; pre-convert other documents or separately prepare a `[documents]` image.

## Prepare the project and environment

Use an initialized **data project**, not this software checkout. For Git-backed
authoring, use its standalone Git repository root, with a valid initial commit
and local `user.name`/`user.email`. See [Git authoring](git-authoring.md).

The Compose mount is read-write and uses the **same absolute path on host and
container**. Git proposal worktrees live under `.ariadne/`; their pointers and
approved resolved source identities must remain usable by both the server and
the human operator. Do not remap an already managed project to `/project`.
A linked checkout with a `.git` file needs its common Git directory mounted at
the same path too; other worktrees the operator uses also need their actual
paths. This minimal template assumes the standalone root.

Set the `.env.example` Docker entries in an existing `.env` (do not overwrite
existing credentials), or export them in your shell:

```bash
export ARIADNE_PROJECT_DIR=/srv/ariadne/retail  # existing absolute project root
export ARIADNE_UID="$(id -u)" ARIADNE_GID="$(id -g)"
export ARIADNE_HTTP_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export ARIADNE_MCP_HOST=mcp.example.org
export ARIADNE_MCP_ORIGIN=https://mcp.example.org
export ARIADNE_TOOLSET=authoring  # bootstrap; combined needs a usable catalog

docker compose config --quiet
docker compose build
docker compose up -d
```

Use the data-project owner's UID/GID if different from your login, never UID 0.
The container's default is `1000:1000`; HOME is writable `/tmp`. Match ownership
rather than disabling Git's ownership checks or making the project world-writable.
The mount source must already exist; Compose does not silently create it.

Keep the token stable in your operator secret environment for subsequent
commands/recreation; the generated shell value above lasts only that shell.
Do not commit `.env`, project data or credentials. The build context is an
allowlist of package sources/metadata, so local projects and `.env` are excluded.
Do not print `docker compose config` without `--quiet`: it resolves secrets.

Local sources/documents outside the project need explicit additional mounts at
their referenced absolute paths. Mount SQLite with its containing directory if
journals/WAL sidecars are needed. Credentials such as `ARIADNE_PG_DSN` must be
explicitly passed in a local Compose override's `environment`; an operator's
host environment alone is **not** forwarded by the template. Source approvals
and human Git Review Admission remain separate; neither happens on startup.
If using DuckDB extensions requiring a download, provide the existing runtime's
outbound access. This image does not bundle every source extension.

## Connect your private HTTPS proxy

The default publishes **no host port**. A client/proxy sharing the service's
network connects to `http://ariadne:8000/mcp` with `Authorization: Bearer TOKEN`.
For a proxy in another Compose project, attach Ariadne to its existing network
via a local override, for example:

```yaml
networks:
  default:
    external: true
    name: YOUR_EXISTING_PROXY_NETWORK
```

Use `docker compose -f compose.yaml -f /path/to/proxy-network.yaml ...` for
all operations in that variant. The proxy must preserve Authorization/MCP
headers and HTTP streaming. Set `ARIADNE_MCP_HOST` to the actual incoming Host
(including its port when needed), and `ARIADNE_MCP_ORIGIN` to the client's exact
Origin. Requests without Origin need no match. No wildcard bypass is used.
Configure and validate your private nginx/Caddy HTTPS route separately; Docker
network attachment is not authorization to expose a public endpoint.

For a **host-side** proxy, including Tailscale Serve, opt into loopback only:

```bash
docker compose -f compose.yaml -f compose.loopback.yaml up -d
```

Its upstream is `http://127.0.0.1:8000`; clients use the approved private HTTPS
URL ending in `/mcp`. Set Host/Origin to that HTTPS hostname, e.g. the real
Tailscale `.ts.net` name. `ARIADNE_LOCAL_PORT` optionally changes the loopback
port, not the container port. Use both Compose files for subsequent operations.
Do not change the binding to `0.0.0.0`, and do not use Tailscale Funnel.

## Readiness and local validation

Compose calls authenticated `/readyz` using Python, not curl. Authoring can be
healthy without a catalog. Analyst/Combined require usable discovery/admission;
a fresh unadmitted project is expected to be unhealthy in those roles. After
human approval/admission, set `ARIADNE_TOOLSET=combined` (or `analyst`) and
recreate the service. No admission or metric-value attestation is automatic.
`/healthz` only checks the responding process. Both probes require the token.
Readiness does not attest every source connection or metric result.

Run the focused disposable-container check after building:

```bash
ARIADNE_DOCKER_TEST_IMAGE=ariadne-mcp:local uv run pytest tests/test_docker_mcp.py
```

It uses a synthetic external Git project, a separate container client, an
isolated Compose project/network, no host ports, and removes its containers and
network afterward. It checks authenticated probes, non-root permissions,
host-readable proposal worktrees, and persistence after container recreation.
Without that environment variable the test is skipped. It does not test a real
HTTPS proxy, remote client, production sources or another CPU architecture;
those remain deployment acceptance work, not evidence supplied by this template.

# Core Python 3.14 / MCP 2 baseline

Date: 2026-10-15. Classification: source/test evidence, not an approved behavioral specification. Owning design: [0026](../specs/2026-10-15-0026-core-python314-mcp2.md). No implementation or target integration was performed to obtain this baseline.

## Revisions and ownership

- Ariadne main and the remote main SHA both resolve to `21f9b29e7c510130ecfc150c34ccffe3eb6e0fff`. The only original worktree is the main checkout. Its pre-existing two-line addition in `project/research/2026-09-23-ariadne-ktx-nao-omnigraph-comparison.md` was left untouched; a clean isolated design worktree starts from the committed baseline.
- Both other Ariadne Pi sessions confirmed no active writers/reserved worktrees. Paseo reports this session as a Pi agent; its effective allocator root is `~/.local/state/worktrees`. Old `.orchestrator/` directories are history, not active writer evidence.
- Lumio Wiki baseline: `93951f84f0dfe0c60f8e42ae3d607074a8c262cf`. Its active session owns a separate documentation namespace migration, not runtime/dependency work or #76 interfaces. Do not copy its dirty tree into the compatibility fixture.
- Read [#73](https://github.com/legout/ariadne/issues/73), [#74](https://github.com/legout/ariadne/issues/74), [#75](https://github.com/legout/ariadne/issues/75), [#76](https://github.com/legout/ariadne/issues/76) through `gh issue view --repo legout/ariadne`. All are open intake scopes, not approved written behavior. Their recorded update times are 20:22:33Z, 20:22:36Z, 20:22:38Z and 20:23:30Z respectively on this date.

## Dependency and codec facts

Ariadne [`pyproject.toml`](../../pyproject.toml), [`Dockerfile`](../../Dockerfile), [`uv.lock`](../../uv.lock) and [`serve.py`](../../src/ariadne/serve.py) show Python ≥3.12, Python 3.12 Docker, MCP 1.30.0 resolution and `mcp>=1.2,<2` constraints. Core and Agent have separate lockfiles. The root publish workflow builds both distributions but currently tests only the Core wheel; it does not certify Agent compatibility.

At the pinned [Lumio package metadata](https://github.com/legout/lumio-wiki/blob/93951f84f0dfe0c60f8e42ae3d607074a8c262cf/packages/lumio-wiki/pyproject.toml), the Python floor is ≥3.14 and the MCP constraint is `>=2.2.0`, **not** an exact metadata pin. Its [lockfile](https://github.com/legout/lumio-wiki/blob/93951f84f0dfe0c60f8e42ae3d607074a8c262cf/uv.lock) resolves `mcp==2.2.0` and `mcp-types==2.2.0`. [Its server](https://github.com/legout/lumio-wiki/blob/93951f84f0dfe0c60f8e42ae3d607074a8c262cf/packages/lumio-wiki/src/lumio_wiki/mcp_server.py) imports `mcp.server.mcpserver.MCPServer` lazily. A direct check of the local Lumio interpreter confirmed CPython 3.14.0, installed MCP 2.2.0 and that import path. This is import/version evidence, not an MCP session test. An earlier filesystem listing did not locate MCP; that negative inference was corrected by the direct interpreter check.

Source inspection of the cached official MCP 2.2.0 wheel established:

- The `MCPServer`/explicit `Tool` paths replace `fastmcp`. `Tool.from_function` remains, but registration/type consumers need checking, not a global text-only rename.
- The SDK exposes Python fields such as `structured_content` and `is_error`, while retaining wire aliases. `func_metadata.convert_result` passes `CallToolResult` through; otherwise text conversion and inferred structured output depend on metadata. Existing Ariadne result/refusal construction must be ported deliberately.
- stdio and HTTP serializers use `model_dump_json(by_alias=True, exclude_unset=True)`. Ariadne's current size helpers explicitly model the 1.30 `exclude_none`/error-framing path. The 2.x high-level exception handler also differs. Source inspection does not prove the replacement byte measure; actual emitted frames are required.
- `MCPServer.streamable_http_app` takes `max_request_body_size`, `transport_security` and `host` as arguments. Its `Settings` no longer owns those transport options. Ariadne currently mutates those settings, so a class/import rename alone cannot preserve the HTTP boundary.
- MCP 2.2.0 metadata requires `mcp-types==2.2.0`, `httpx2>=2.5.0`, and Python-3.14-specific floors including AnyIO ≥4.10 and Starlette ≥0.48. Their installation/runtime compatibility remains to be established in the isolated target environment.

The cached wheel matches Lumio's named SDK version; Lumio's lockfile records wheel SHA256 `bde982589473a060ae145e3406e9a5333fe538c97229ba841f5a7f92be004f81`. No independent wheel-archive digest verification or new dependency resolution was performed in this research.

## Executed baseline

On unchanged Ariadne runtime files at `21f9b29`:

```text
.venv/bin/python -m pytest -q tests/test_mcp_toolsets.py tests/test_query_results.py
42 passed (42 progress markers, exit 0; 56.8 s)

ariadne-agent/.venv/bin/python -m pytest -q ariadne-agent/tests/test_mcp_roles.py
10 passed (10 progress markers, exit 0; 53.5 s)
```

The actual baseline environments use CPython 3.12.8. Core has MCP 1.30.0, DuckDB 1.5.6, SQLGlot 30.20.0 and pytest 9.1.1. The Agent environment has `tau-ai==0.4.6`, local `tau-mcp==0.1.0`, `ariadne-data==0.3.1` and pytest 9.1.1. These results establish only the old focused baseline, not Python 3.14/MCP 2 compatibility or independent implementation review. No full suite, Docker build or live target-version MCP test was run.

## Deferred dependency and design boundaries

The owner explicitly deferred Ariadne Agent and Tau/tau-mcp after the initial investigation:

- Agent metadata requires `tau-ai==0.4.6` and `tau-mcp>=0.1.0`, with an absolute local `tool.uv.sources` override for tau-mcp. The local Tau checkout reports 0.4.4, so testing it would not prove the required 0.4.6 release.
- Local `legout/tau-mcp` is at `7d10a60c787da436dd0f503dca8391d14b938880`, five commits ahead of local `origin/main@b44b3b0`. Those commits include the embeddable core and dispatch allowlist Ariadne consumes. The PyPI JSON endpoint returned HTTP 404. No publication, dependency replacement or source push was authorized or attempted.
- tau-mcp is a stdlib protocol client, not a consumer of the Python MCP SDK. Its source offers protocol `2025-11-25`, accepts several older versions, and reads `content`/`isError`. This is not proof of interoperability with an MCP 2 server; the deferred Agent work must verify actual calls and role restrictions.

#74 cannot silently replace approved spec 0009's retained legacy paths, spec 0021's standalone staging ingestion, or spec 0007/0023's separate Answer Example review/store. Its migration/disposition and ephemeral-versus-durable behavior need their own approved amendments. #75 depends on tracked durable contract ownership and jointly agreed stable IDs; supported ODCS version/profile and unknown/unavailable drift semantics remain design work. #76 Context Provider, IDs, policy closure and release/admission manifest are not defined by the SDK migration. None was decided unilaterally here.

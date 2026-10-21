# ariadne-agent

The installable Ariadne Agent backend: a fixed-role, in-memory conversation
over **native Ariadne Python tools** — no CLI, no shell, no server, no raw SQL
([spec 2026-09-29-0006](../../project/specs/2026-09-29-0006-ariadne-agent-backend.md),
[ADR-0014](../../project/adr/0014-embedded-tau-agent-backend.md), issue #23).
This revision ships the **Analyst** and **Authoring** roles plus optionally
configured **role-restricted stdio MCP** tools (issue #25).

> **Compatibility boundary:** this separately versioned Agent/Tau stack was not
> qualified by the Core 0.6.0 / Lumio 0.4.0 release. The API examples below
> describe this package, not a certified install of the new pair. Start with
> the [local CLI tutorial](../../../../integration/docs/tutorials/lumio-ariadne-local.md); optional
> Core MCP is documented separately in the [CLI reference](../../docs/reference/cli.md#mcp).

## Install

Depends on `ariadne-data` (never the unrelated PyPI `ariadne` GraphQL project),
the verified Tau release `tau-ai==0.4.6`, whose embeddable
`tau_agent.AgentHarness` / `tau_ai.OpenAICompatibleProvider` import paths this
package uses, and the owned `tau-mcp` embeddable stdio MCP core. The `tau-ai`
wheel also installs `tau_coding`'s files, but this package never imports or
invokes `tau_coding` at runtime (the `tau_mcp.proxy` module is likewise not
imported here because it is the Tau-extension flavor), and never launches a
server — installing `ariadne-data` alone does not install the agent.

Local development resolves `ariadne-data` from the repository checkout through
`[tool.uv.sources]` in `pyproject.toml` (non-published tool configuration
only; the published dependency metadata names the distribution); `tau-mcp`
resolves the same way from its own repository checkout:

```bash
cd products/ariadne/packages/ariadne-agent && uv run pytest -q tests/test_analyst.py
```

## Use

The host selects everything up front — project root, role, model, and a fully
configured provider (model identity, endpoint and credentials are constructed
outside user messages and data-project artifacts; the agent loads no global
provider or MCP configuration):

```python
from ariadne_agent import AssistantText, ToolActivity, open_session
from tau_ai import OpenAICompatibleProvider, OpenAICompatibleConfig

provider = OpenAICompatibleProvider(OpenAICompatibleConfig(api_key=..., base_url=...))
session = open_session(role="analyst", project="/path/to/project",
                       model="your-model", provider=provider)
async for event in session.send("gross margin by region?"):
    match event:
        case AssistantText(text=text):   print(text)
        case ToolActivity(tool=tool):    print(f"[tool] {tool}")
session.cancel()   # cooperative: ends subsequent model turns
session.close()
```

## MCP (optional, role-restricted)

Passing `mcp_settings` attaches ONE restricted MCP registry to that session,
built from host-supplied configuration only — validated stdio server entries,
a cache root, and each role's operator-approved qualified tool names. No
`~/.tau/mcp.json` or any other ambient MCP configuration is ever loaded, and a
model request can never alter server commands, the allowlist, or credentials:

```python
from ariadne_agent.mcp_tools import McpSettings
from tau_mcp.config import ServerConfig

mcp = McpSettings(
    servers={"weather": ServerConfig(name="weather", command="...", args=(...))},
    cache_root=Path("/var/cache/ariadne-mcp"),
    role_tools={"analyst": ("weather__lookup",)},  # authoring absent => no MCP tools
)
session = open_session(role="analyst", ..., mcp_settings=mcp)
```

Permitted tools surface to the model as one `mcp` proxy tool (search and call
by `server__tool` name); direct MCP registration stays a Tau extension and is
not offered. The registry's frozen per-instance allowlist restricts discovery
**and** dispatch, so a forbidden name the model supplies through the proxy is
rejected before any spawn or call — the server never sees it. `close()` reaps
every MCP child this session spawned; a call already executing finishes or
times out under the MCP client's bounded request timeout (no immediate
interruption is promised). Omit `mcp_settings` and the native tool surface is
exactly as before.

The host always selects a **Git data project** root: the session resolves
through `QueryRuntime.open_project` and serves its pinned human-admitted
snapshot. Before the first admission an Analyst session still opens (discovery
stays source-free); the first governed query then refuses honestly, naming the
human-only `ariadne-admit` step — never a fallback to mutable files or a plain
artifact root. The first real admission is picked up once and stays pinned for
the session.

## Contract

- **Typed async events**: assistant text, tool activity (verbatim JSON payload,
  error flag), session errors, and run completion. Harness-internal event
  types never leak through.
- **One active run per session**; `send` while running raises. **Fixed**
  role/project/model — a different one requires a new session, with no silent
  transcript or tool-access transfer.
- **In memory only**: a process restart loses the messages; there is no resume
  operation, deliberately.
- **Analyst tools** are exactly the nine read-only admitted-snapshot operations
  (`discover`, `list_metrics`, `search_context`, `get_metric`, `list_datasets`,
  `define_metric`, `resolve_term`, `list_context_pages`, `read_context_page`)
  as thin native tools: values, Policy text and citations, paths, and
  `governed` labels pass through verbatim. `define_metric` is ephemeral
  (`persistence: not_saved`) — it writes nothing. Term resolution is read-only
  admitted-context guidance — an alias never authorizes a join. No source
  approval, no admission, no filesystem writes.
- **Authoring tools** mirror `AuthoringProject`'s Git contract one-to-one —
  `start_proposal`, `read_artifact`, `edit_proposal`, `propose_sources`,
  `inputs`, `validate_proposal`, `refresh_schema`, `inspect_mapping`,
  `resolve_term`, `review_proposal`, `read_skill_reference` — with automatic
  labeled-hypothesis saves through `edit_proposal` (no per-save prompt) and
  restart-readable Git/evidence state. Original documents are external,
  operator-placed inputs: there is no upload tool, and the agent never reads
  outside the operator-managed boundary. Source approval, admission,
  reconciliation and Git Review Admission are deliberately absent: human-only,
  outside the agent. `propose_sources` accepts optional named `storages:` S3
  profile declarations: the agent proposes the credential-free declarations and
  never reads or sets environment values — the host process supplies them, and
  the human-only approval gate is unchanged.
- **Data Contracts (development candidate)** use existing tools only:
  `discover` adds the pinned snapshot’s contracts/as-of metadata group without
  source access; `list_datasets` retains the approved live catalog and actual
  columns with snapshot-only contract annotations. Authoring `read_artifact` /
  `edit_proposal` accept `contract` and separate `contract_bindings` kinds,
  preserving producer identity/content. Static validity is not live conformance;
  dependent admission needs complete passing evidence plus the human gate.
  See [the limited ODCS v3.2.0 profile](../../docs/reference/data-contracts.md);
  no full ODCS, current source health or #76 integration claim is implied.
- **Guidance**: the version-matched packaged `ariadne/skill_assets/SKILL.md`
  from the installed `ariadne-data`, plus a short native-tool mapping. No
  global skill scans, no model-invocable skill scripts.
- **No admission yet**: an Analyst session on a not-yet-admitted Git project
  opens with source-free discovery; the first governed query fails fast with an
  actionable error naming the human `ariadne-admit` step. The failure is
  session-local — it cannot block a later (e.g. Authoring) session.

# ariadne-agent

The installable Ariadne Agent backend: a fixed-role, in-memory conversation
over **native Ariadne Python tools** — no CLI, no shell, no server, no raw SQL
([spec 2026-09-29-0006](../project/specs/2026-09-29-0006-ariadne-agent-backend.md),
[ADR-0014](../project/adr/0014-embedded-tau-agent-backend.md), issue #23).
This revision ships the **Analyst** role; the Authoring role and external MCP
tools arrive in their own lanes.

## Install

Depends on `ariadne-core` (never the unrelated PyPI `ariadne` GraphQL project)
and the verified Tau release `tau-ai==0.4.6`, whose embeddable
`tau_agent.AgentHarness` / `tau_ai.OpenAICompatibleProvider` import paths this
package uses. The `tau-ai` wheel also installs `tau_coding`'s files, but this
package never imports or invokes `tau_coding` at runtime, and never launches a
server — installing `ariadne-core` alone does not install the agent.

Local development resolves `ariadne-core` from the repository checkout through
`[tool.uv.sources]` in `pyproject.toml` (non-published tool configuration
only; the published dependency metadata names the distribution):

```bash
cd ariadne-agent && uv run pytest -q tests/test_analyst.py
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

The project root must contain the served `semantic_layer/` and `context_layer/`
directories and either a source registry (`ariadne.yaml`) or a `demo.db`; every
path resolves against that root, never the ambient working directory.

## Contract

- **Typed async events**: assistant text, tool activity (verbatim JSON payload,
  error flag), session errors, and run completion. Harness-internal event
  types never leak through.
- **One active run per session**; `send` while running raises. **Fixed**
  role/project/model — a different one requires a new session, with no silent
  transcript or tool-access transfer.
- **In memory only**: a process restart loses the messages; there is no resume
  operation, deliberately.
- **Analyst tools** are exactly `ariadne.runtime.AriadneRuntime`'s five public
  operations (`list_metrics`, `search_context`, `get_metric`, `list_datasets`,
  `define_metric`) as thin native tools: values, Policy text and citations,
  paths, and `governed` labels pass through verbatim. No source approval, no
  promotion, no filesystem writes beyond the runtime's own staging.
- **Guidance**: the version-matched packaged `ariadne/skill_assets/SKILL.md`
  from the installed `ariadne-core`, plus a short native-tool mapping. No
  global skill scans, no model-invocable skill scripts.
- **Missing promoted catalog**: opening an Analyst session fails fast with an
  actionable error naming the human promotion step. The failure is
  session-local — it cannot block a later (e.g. Authoring) session.

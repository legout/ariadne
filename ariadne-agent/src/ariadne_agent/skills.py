"""Curated skill guidance for the agent roles (spec 2026-09-29-0006, ADR-0014).

Skills are instructions, not permissions: the agent loads the version-matched
packaged Ariadne skill (``ariadne/skill_assets/SKILL.md``, shipped inside the
installed ``ariadne-core`` and version-locked to it per ADR-0011) plus a short
mapping onto this session's native tools. There is no scan of the user's
global agent directories and no model-invocable skill script execution — and
no CLI or shell tool is granted to read the skill's commands literally.
"""

from ariadne.skill import ASSETS

# The packaged skill documents the local-CLI workflow. This session has no CLI
# and no shell, so the mapping restates each command as the native tool that
# performs the identical runtime operation — keeping the skill's rules
# truthful without opening any command-execution surface.
_TOOL_MAP = """\
## Native tool mapping

This session has no CLI and no shell. The packaged skill's `ariadne` commands
are native tools here — call them directly, never through a command:

- `ariadne list-metrics`    -> `list_metrics()`
- `ariadne search-context`  -> `search_context(query, limit?)`
- `ariadne get-metric`      -> `get_metric(name, dimensions?, range?)`
- `ariadne list-datasets`   -> `list_datasets()`
- `ariadne define-metric`   -> `define_metric(definition)`

Every rule in the skill below applies unchanged; substitute the native tool
for each CLI command it names.
"""


def packaged_skill() -> str:
    """The version-matched packaged ``SKILL.md`` body, from the installed
    ``ariadne-core`` (never a user-installed or global copy)."""
    return (ASSETS / "SKILL.md").read_text(encoding="utf-8")


def analyst_guidance() -> str:
    """Analyst guidance: the native-tool mapping followed by the packaged skill."""
    return _TOOL_MAP + "\n" + packaged_skill()

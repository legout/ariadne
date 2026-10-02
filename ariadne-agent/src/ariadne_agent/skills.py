"""Curated skill guidance for the agent roles (spec 2026-09-29-0006, ADR-0014).

Skills are instructions, not permissions: the agent loads the version-matched
packaged Ariadne skill (``ariadne/skill_assets/SKILL.md``, shipped inside the
installed ``ariadne-core`` and version-locked to it per ADR-0011) plus a short
mapping onto this session's native tools. There is no scan of the user's
global agent directories and no model-invocable skill script execution — and
no CLI or shell tool is granted to read the skill's commands literally.
"""

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from ariadne.skill import ASSETS

# One bounded page of skill-reference text (the packaged rubric is ~3.5 KB;
# anything far larger is not a skill reference — spec: bounded references,
# no script execution).
MAX_REFERENCE_BYTES = 256 * 1024

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


_AUTHORING_TOOL_MAP = """\
## Native tool mapping

This session has no CLI and no shell. The packaged skill's authoring
workflow is native tools over the project's Git proposals here (issue #38;
the G6 mapping of the complete-bundle submission to independent
revision-checked edits) — call them directly, never through a command:

- `ariadne-authoring start`          -> `start_proposal(base_revision?)`
- `ariadne-authoring propose-sources` -> `propose_sources(proposal, expected_revision, sources)`
- upload a document                   -> `upload_document(name, content)`
- `ariadne-authoring inputs`          -> `inputs(proposal, documents?, part?, sample_rows?)`
- `ariadne-authoring read`            -> `read_artifact(proposal, kind, name?, section?, part?)`
- `ariadne-authoring edit`            -> `edit_proposal(proposal, expected_revision, edit)`
- `ariadne-authoring validate`        -> `validate_proposal(proposal, expected_revision)`
- `ariadne-authoring review`          -> `review_proposal(proposal, part?)`
- skill reference                     -> `read_skill_reference(reference)`

Every rule in the skill below applies unchanged; substitute the native tool
for each CLI command it names.
"""


def authoring_guidance() -> str:
    """Authoring guidance: the native-tool mapping, the packaged skill, and
    the packaged grain rubric — the one bounded reference this role always
    needs (spec 2026-09-29-0006 Skills: notably ``grain-rubric.md`` for
    authoring). Host-declared trusted roots add references read through
    ``read_skill_reference`` at run time."""
    return (
        _AUTHORING_TOOL_MAP
        + "\n"
        + packaged_skill()
        + "\n\n---\n\n# Packaged reference: references/grain-rubric.md\n\n"
        + packaged_reference("references/grain-rubric.md")
    )


def packaged_reference(reference: str) -> str:
    """One bounded reference under the packaged skill assets — version-matched
    with the installed ``ariadne-core``, exactly like :func:`packaged_skill`."""
    return read_skill_reference(reference)


def read_skill_reference(
    reference: str, trusted_roots: Sequence[str | Path] = ()
) -> str:
    """One bounded ``.md`` skill reference under the packaged skill or a
    host-declared trusted skill root (spec 2026-09-29-0006 Skills).

    A reference is a plain relative POSIX ``.md`` path (``SKILL.md`` counts):
    absolute paths, traversal (``..``), anything that is not ``.md``, and
    anything outside the roots are refused BEFORE any read — scripts are
    never read and never executed, and there is no directory scan. Roots are
    consulted packaged-first, then each host-declared root in order; a
    symlinked entry whose target resolves outside its root fails the same
    containment check."""
    pure = PurePosixPath(reference)
    if (
        not reference
        or pure.is_absolute()
        or "\\" in reference
        or any(part in ("", ".", "..") for part in pure.parts)
        or pure.suffix != ".md"
    ):
        raise ValueError(
            f"{reference!r}: a skill reference is one relative .md path under a "
            "trusted skill root — absolute paths, traversal ('..'), and anything "
            "that is not .md are refused; scripts are never read or executed"
        )
    for root in (ASSETS, *trusted_roots):
        base = Path(root).resolve()
        resolved = (base / pure).resolve()
        if resolved.is_relative_to(base) and resolved.is_file():
            if resolved.stat().st_size > MAX_REFERENCE_BYTES:
                raise ValueError(
                    f"{reference}: reference exceeds the {MAX_REFERENCE_BYTES}-byte "
                    "bound — bounded references only"
                )
            return resolved.read_text(encoding="utf-8")
    raise ValueError(
        f"{reference}: not a declared reference under the packaged skill or this "
        "session's trusted skill roots — reads stay inside them (no scan)"
    )

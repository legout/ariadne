"""Authoring role tools: the harness-led authoring service as native tools.

Thin wrappers only (spec 2026-09-29-0006 session/role interface): proposal
shape checks, digest/attempt contracts, staging discipline and the review
snapshot all live in ``ariadne-core``'s ``ariadne.authoring``; nothing is
reimplemented here. Each tool's payload is the service's verbatim JSON
envelope, and service failures propagate with their verbatim message as tool
errors — an unavailable source, a failed check, a stale digest, an
interrupted transition or a ``review_needed`` state surfaces to the model
exactly as the service reports it; nothing here clears or overrides one.
``approve_sources`` and ``ariadne-promote`` are deliberately absent: source
approval and Promotion are human-only operations outside the agent.

Adapter-owned temporary intake documents bridge the service's file-based
inputs (:func:`ariadne.authoring.propose_sources` and :func:`submit_bundle`
read submission documents): the model supplies CONTENT — proposed source
entries, bundle files as relative paths + bodies — never a write path. Every
intake file is created and removed by this adapter inside a private temporary
directory, and every project-relative write happens inside the service's own
validated staging.
"""

import json
import tempfile
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

import yaml
from ariadne import authoring as authoring_service
from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult, ToolExecutor

from ariadne_agent.skills import read_skill_reference

TOOL_NAMES = (
    "propose_sources",
    "harness_inputs",
    "store_upload",
    "submit_bundle",
    "review_bundle",
    "read_skill_reference",
)


def _payload(value: object) -> AgentToolResult:
    """One verbatim JSON payload — the service envelope is the whole contract."""
    return AgentToolResult(content=[TextContent(text=json.dumps(value, default=str))])


@contextmanager
def _intake(document: str, suffix: str):
    """One adapter-owned temporary intake document for the service's
    file-based inputs: created and removed by this adapter under a private
    temporary directory, so no model argument ever selects a write path."""
    with tempfile.TemporaryDirectory(prefix="ariadne-agent-intake-") as tmp:
        intake = Path(tmp) / f"intake{suffix}"
        intake.write_text(document, encoding="utf-8")
        yield intake


def authoring_tools(project: Path, skill_roots: Sequence[Path] = ()) -> list[AgentTool]:
    """The Authoring tool set: the five harness-led authoring service
    operations plus the bounded skill-reference reader. The project root and
    the trusted skill roots are host-selected at session open — never model
    arguments."""
    # Each wrapper mirrors the service's own signature; every bound, digest
    # and staging rule stays the service's (spec: not reimplemented here).
    async def propose_sources(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        entries = arguments["sources"]
        with _intake(yaml.safe_dump({"sources": entries}, sort_keys=False), ".yaml") as file:
            return _payload(authoring_service.propose_sources(file, project=project))

    async def harness_inputs(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            authoring_service.harness_inputs(
                project=project,
                documents=arguments.get("documents") or (),
                part=arguments.get("part", 1),
            )
        )

    async def store_upload(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            authoring_service.store_upload(
                arguments["name"], arguments["content"].encode("utf-8"), project=project
            )
        )

    async def submit_bundle(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        submission = arguments["submission"]
        with _intake(json.dumps(submission), ".json") as file:
            return _payload(
                authoring_service.submit_bundle(
                    file, project=project, base_digest=arguments.get("base_digest")
                )
            )

    async def review_bundle(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            authoring_service.review_bundle(project=project, part=arguments.get("part", 1))
        )

    async def read_skill_reference_tool(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        reference = arguments["reference"]
        return _payload(
            {"reference": reference, "content": read_skill_reference(reference, skill_roots)}
        )

    executor: dict[str, ToolExecutor] = {
        "propose_sources": propose_sources,
        "harness_inputs": harness_inputs,
        "store_upload": store_upload,
        "submit_bundle": submit_bundle,
        "review_bundle": review_bundle,
        "read_skill_reference": read_skill_reference_tool,
    }
    descriptions = {
        "propose_sources": (
            "Propose registry source entries as inert data — nothing is ever "
            "opened. Returns the exact digest and the stored staging location. "
            "STOP after proposing: the operator approves the exact digest "
            "outside this session; you have no tool that approves, and none exists."
        ),
        "harness_inputs": (
            "The measured inputs, bounded: the deterministic per-source profile "
            "(profile is null until the operator approves sources) and converted "
            "document evidence for referenced documents, one bounded part each. "
            "Documents must already be in the operator's input area "
            "(store_upload or operator-staged); approval never comes from here."
        ),
        "store_upload": (
            "Upload one bounded text document into the project input area; "
            "returns its stable {resource, digest}. Large or binary documents "
            "are operator-staged, never uploaded."
        ),
        "submit_bundle": (
            "Submit the complete bundle — Seed Notes, OSI models, OKF pages — as "
            "relative paths + bodies through the SAME deterministic checks the "
            "author loop uses; cite document references. Errors are actionable "
            "and repair the SAME proposal only with its current digest, within "
            "the attempt limit; nothing here ever serves or promotes."
        ),
        "review_bundle": (
            "The staged review — never a signoff: inventory, source identities, "
            "verified document citations, errors, the exact reviewed-content "
            "digest, and bounded bodies of the staged proposal."
        ),
        "read_skill_reference": (
            "Read one bounded .md skill reference (e.g. references/grain-rubric.md) "
            "under the packaged skill or this session's trusted skill roots. "
            "Relative .md paths only; traversal and scripts are refused."
        ),
    }
    schemas = {
        "propose_sources": {
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "path": {"type": "string"},
                            "connection_string": {"type": "string"},
                        },
                        "required": ["name", "type"],
                    },
                }
            },
            "required": ["sources"],
            "additionalProperties": False,
        },
        "harness_inputs": {
            "type": "object",
            "properties": {
                "documents": {"type": "array", "items": {"type": "string"}},
                "part": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
        "store_upload": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["name", "content"],
            "additionalProperties": False,
        },
        "submit_bundle": {
            "type": "object",
            "properties": {
                "submission": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "object"},
                        },
                        "documents": {"type": "array", "items": {"type": "string"}},
                        "base_digest": {"type": "string"},
                    },
                    "required": ["files"],
                },
                "base_digest": {"type": "string"},
            },
            "required": ["submission"],
            "additionalProperties": False,
        },
        "review_bundle": {
            "type": "object",
            "properties": {"part": {"type": "integer", "minimum": 1}},
            "additionalProperties": False,
        },
        "read_skill_reference": {
            "type": "object",
            "properties": {"reference": {"type": "string"}},
            "required": ["reference"],
            "additionalProperties": False,
        },
    }
    return [
        AgentTool(
            name=name,
            label=name.replace("_", " ").title(),
            description=descriptions[name],
            parameters=schemas[name],
            execute_fn=executor[name],
        )
        for name in TOOL_NAMES
    ]

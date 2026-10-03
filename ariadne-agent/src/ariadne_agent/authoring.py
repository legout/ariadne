"""Authoring role tools: the Git authoring contract as native tools (issue
#38/G6 migration; spec 2026-09-29-0006 session/role interface over the
2026-10-02-0009 §3–4 lifecycle, ADR-0013/0016).

Thin wrappers only: every proposal-shape check, revision check, digest
contract, staging discipline, bounded read and review snapshot lives in
``ariadne-core``'s :class:`ariadne.authoring.AuthoringProject` (plan §2's
Authoring call contract); nothing is reimplemented here. The native tools
mirror that interface one-to-one — ``start_proposal``, ``read_artifact``,
``edit_proposal``, ``propose_sources``, ``inputs``, ``upload_document``,
``validate_proposal``, ``refresh_schema`` (issue #41: the explicit physical
schema refresh), ``inspect_mapping`` (issue #43/K3: the bounded
mapping-inspection operation with authentic retained receipts),
``resolve_term`` (issue #42/K2: read-only resolution against
the explicitly selected proposal's candidate, with the candidate identity
visible), ``review_proposal`` — replacing the legacy
complete-bundle submission tools (the explicit G6 mapping: one proposal +
per-artifact edits + validation/review, never a resubmitted whole bundle).
Issue #45/K5 adds no tool: automatic hypothesis capture is the SAME loop —
the guidance shipped with this surface reads existing References/hypotheses
FIRST and saves labeled hypotheses through ``edit_proposal`` automatically
(no per-save prompt), reusing stable identities and citing retained
receipts, and a restart reads Git/evidence state rather than chat memory.
Each tool's payload is the service's verbatim JSON envelope, and service
failures propagate with their verbatim message as tool errors — an
unavailable source, a failed check, a stale revision, an interrupted
transition or an unreviewed state surfaces to the model exactly as the
service reports it; nothing here clears or overrides one.
``approve_sources``, ``ariadne-admit`` and ``ariadne-promote`` are
deliberately absent: source approval, admission and Promotion are human-only
operations outside the agent (spec §5).
"""

import json
from collections.abc import Sequence
from pathlib import Path

from ariadne.authoring import AuthoringProject
from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult, ToolExecutor

from ariadne_agent.skills import read_skill_reference

TOOL_NAMES = (
    "start_proposal",
    "read_artifact",
    "edit_proposal",
    "propose_sources",
    "inputs",
    "upload_document",
    "validate_proposal",
    "refresh_schema",
    "inspect_mapping",  # K3 (issue #43): bounded mapping inspection + receipts
    "resolve_term",  # K2 (issue #42): read-only candidate term resolution
    "review_proposal",
    "read_skill_reference",
)


def _payload(value: object) -> AgentToolResult:
    """One verbatim JSON payload — the service envelope is the whole contract."""
    return AgentToolResult(content=[TextContent(text=json.dumps(value, default=str))])


def authoring_tools(project: Path, skill_roots: Sequence[Path] = ()) -> list[AgentTool]:
    """The Authoring tool set: the AuthoringProject Git contract plus the
    bounded skill-reference reader. The project root and the trusted skill
    roots are host-selected at session open — never model arguments; tool
    arguments carry only proposal IDs, revisions, typed artifact identities
    and content."""
    api = AuthoringProject(project)

    # Each wrapper mirrors the service's own signature; every revision,
    # bound and staging rule stays the service's (spec: not reimplemented).
    async def start_proposal(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(api.start_proposal(arguments.get("base_revision")))

    async def read_artifact(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        identity: dict = {"kind": arguments["kind"]}
        if arguments.get("name") is not None:
            identity["name"] = arguments["name"]
        if arguments.get("section") is not None:
            identity["section"] = arguments["section"]
        return _payload(
            api.read_artifact(arguments["proposal"], identity, part=arguments.get("part", 1))
        )

    async def edit_proposal(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.edit_proposal(
                arguments["proposal"],
                arguments["expected_revision"],
                arguments["edit"],
            )
        )

    async def propose_sources(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.propose_sources(
                arguments["proposal"],
                arguments["expected_revision"],
                arguments["sources"],
            )
        )

    async def inputs(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.inputs(
                arguments["proposal"],
                documents=arguments.get("documents") or (),
                part=arguments.get("part", 1),
                sample_rows=arguments.get("sample_rows"),
            )
        )

    async def upload_document(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.upload_document(
                arguments["name"], arguments["content"].encode("utf-8")
            )
        )

    async def validate_proposal(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.validate_proposal(
                arguments["proposal"], arguments["expected_revision"]
            )
        )

    async def refresh_schema(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.refresh_schema(
                arguments["proposal"],
                arguments["expected_revision"],
                arguments["assets"],
            )
        )

    async def inspect_mapping(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.inspect_mapping(
                arguments["proposal"],
                arguments["expected_revision"],
                arguments["candidate"],
                limits=arguments.get("limits"),
            )
        )

    async def resolve_term(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.resolve_term(
                arguments["proposal"], arguments["request"], part=arguments.get("part", 1)
            )
        )

    async def review_proposal(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        return _payload(
            api.review_proposal(arguments["proposal"], part=arguments.get("part", 1))
        )

    async def read_skill_reference_tool(
        tool_call_id: str, arguments: dict, signal=None, on_update=None
    ) -> AgentToolResult:
        reference = arguments["reference"]
        return _payload(
            {"reference": reference, "content": read_skill_reference(reference, skill_roots)}
        )

    executor: dict[str, ToolExecutor] = {
        "start_proposal": start_proposal,
        "read_artifact": read_artifact,
        "edit_proposal": edit_proposal,
        "propose_sources": propose_sources,
        "inputs": inputs,
        "upload_document": upload_document,
        "validate_proposal": validate_proposal,
        "refresh_schema": refresh_schema,
        "inspect_mapping": inspect_mapping,
        "resolve_term": resolve_term,
        "review_proposal": review_proposal,
        "read_skill_reference": read_skill_reference_tool,
    }
    descriptions = {
        "start_proposal": (
            "Start one isolated Git authoring proposal in this session's "
            "project: a system-generated proposal ID with its branch and "
            "worktree. Returns {proposal, base_revision, candidate_revision}; "
            "never approval, validation or admission."
        ),
        "read_artifact": (
            "Read one artifact of the proposal's current candidate revision "
            "(inherited from the base when never edited) in bounded parts: "
            "the revision, path, content part and completeness."
        ),
        "edit_proposal": (
            "Apply one COMPLETE artifact edit — {kind: model|graph|page|"
            "seed_notes, name?, section?, content} — requiring the expected "
            "candidate revision; a stale revision or competing writer is "
            "refused, an identical edit is a no-op. Labeled mapping "
            "hypotheses/evidence save AUTOMATICALLY through this seam — no "
            "per-save prompt: cite the receipt id and reuse the stable "
            "artifact/mapping IDs, never suffixed duplicates. Unchanged "
            "artifacts are inherited: never resend the whole bundle."
        ),
        "propose_sources": (
            "Append typed source-registry entries to the proposal's candidate "
            "registry — inert DATA, nothing is opened. Returns the resolved "
            "identity digest. STOP after proposing: the operator approves the "
            "exact digest outside this session; you have no tool that "
            "approves, and none exists."
        ),
        "inputs": (
            "The proposal's measured inputs, bounded: the profile of the "
            "operator-APPROVED resolved registry identity (an unapproved "
            "entry is an explicit error), converted document evidence for "
            "referenced documents, and the candidate's Seed Notes — one "
            "bounded part each."
        ),
        "upload_document": (
            "Upload one bounded text document into the project input area; "
            "returns its stable {resource, digest}. Large or binary documents "
            "are operator-staged, never uploaded."
        ),
        "validate_proposal": (
            "Validate the proposal's effective candidate at its EXACT final "
            "revision: the deterministic checks finalize, the final commit is "
            "validated against the approved source identity, and that "
            "revision returns with its report/errors. Never a signoff."
        ),
        "refresh_schema": (
            "Regenerate the core-owned physical schema facts and Dataset "
            "Overviews of an EXPLICIT catalog asset list {source, catalog, "
            "schema, table} inside the proposal. Reads only the operator-"
            "APPROVED resolved source identity — if the sources were just "
            "proposed, STOP for the operator's approval first. Authored meaning "
            "survives only for identical column identity/type; removed or "
            "type-changed columns keep their old meaning as reviewable "
            "history; an identical refresh is a no-op. Returns the revision, "
            "generated page identities and schema-change flags; never "
            "admission."
        ),
        "inspect_mapping": (
            "Measure one structured mapping-inspection candidate "
            "(equality/composite, string prefix with an optional scoped prefix "
            "lookup, or explicit scoped lookup) over the operator-APPROVED "
            "resolved source identity. The candidate is a discriminated JSON "
            "object — never SQL or a path; requests may only LOWER the "
            "operator's finite ceilings. Read the existing References, "
            "hypotheses and schemas FIRST (resolve_term, read_artifact) and "
            "reuse their stable IDs. The retained receipt reports honest "
            "counts, coverage, collisions, multiplicity, containment-versus-"
            "pairing basis and sampled/full limitations; raw identifier "
            "examples need the operator's explicit sample permission. A failed "
            "or inconclusive result stays honest — never present a sampled "
            "match as a business rule — and save the labeled hypothesis "
            "immediately through edit_proposal at the current revision citing "
            "the receipt id, automatically with no per-save prompt (you never "
            "edit a page from this tool; confirmation is human-only)."
        ),
        "resolve_term": (
            "Resolve a shared business term or an exact {resource, column} "
            "field lookup against this EXPLICITLY selected proposal's current "
            "candidate revision — read-only, with the candidate revision "
            "visible in the response: representations, exact bindings, scope, "
            "ambiguity and UNCONFIRMED claim status with page/source "
            "citations. Read existing terminology, schemas and mapping "
            "hypotheses with their cited receipts FIRST — before drafting a "
            "new Reference or rediscovering a rule a saved hypothesis already "
            "records; never approval, admission or a query."
        ),
        "review_proposal": (
            "The proposal's review — never a signoff: exact current/base "
            "revisions, change inventory, bounded effective bodies, "
            "citations, the validation report and the review digest. Report "
            "the EXACT digest and stop: admission is human-only and happens "
            "outside this session."
        ),
        "read_skill_reference": (
            "Read one bounded .md skill reference (e.g. references/grain-rubric.md) "
            "under the packaged skill or this session's trusted skill roots. "
            "Relative .md paths only; traversal and scripts are refused."
        ),
    }
    schemas = {
        "start_proposal": {
            "type": "object",
            "properties": {"base_revision": {"type": "string"}},
            "additionalProperties": False,
        },
        "read_artifact": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "kind": {"type": "string", "enum": ["model", "graph", "page", "seed_notes"]},
                "name": {"type": "string"},
                "section": {"type": "string"},
                "part": {"type": "integer", "minimum": 1},
            },
            "required": ["proposal", "kind"],
            "additionalProperties": False,
        },
        "edit_proposal": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "expected_revision": {"type": "string"},
                "edit": {"type": "object", "minProperties": 2},
            },
            "required": ["proposal", "expected_revision", "edit"],
            "additionalProperties": False,
        },
        "propose_sources": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "expected_revision": {"type": "string"},
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
                },
            },
            "required": ["proposal", "expected_revision", "sources"],
            "additionalProperties": False,
        },
        "inputs": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "documents": {"type": "array", "items": {"type": "string"}},
                "part": {"type": "integer", "minimum": 1},
                "sample_rows": {"type": "integer", "minimum": 1},
            },
            "required": ["proposal"],
            "additionalProperties": False,
        },
        "upload_document": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["name", "content"],
            "additionalProperties": False,
        },
        "validate_proposal": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "expected_revision": {"type": "string"},
            },
            "required": ["proposal", "expected_revision"],
            "additionalProperties": False,
        },
        "refresh_schema": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "expected_revision": {"type": "string"},
                "assets": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {"type": "string"},
                            "catalog": {"type": ["string", "null"]},
                            "schema": {"type": "string"},
                            "table": {"type": "string"},
                        },
                        "required": ["source", "catalog", "schema", "table"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["proposal", "expected_revision", "assets"],
            "additionalProperties": False,
        },
        "inspect_mapping": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "expected_revision": {"type": "string"},
                "candidate": {
                    "type": "object",
                    "properties": {
                        "family": {"type": "string", "enum": ["equality", "prefix", "lookup"]},
                        "left": {"type": "array", "minItems": 1},
                        "right": {"type": "array", "minItems": 1},
                    },
                    "required": ["family", "left", "right"],
                },
                "limits": {
                    "type": "object",
                    "properties": {
                        "sample_rows": {"type": "number", "minimum": 1},
                        "execution_seconds": {"type": "number", "minimum": 0},
                        "response_bytes": {"type": "number", "minimum": 1},
                        "examples": {"type": "integer", "minimum": 0, "maximum": 10},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["proposal", "expected_revision", "candidate"],
            "additionalProperties": False,
        },
        "resolve_term": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "request": {
                    "anyOf": [
                        {"type": "string", "minLength": 1},
                        {
                            "type": "object",
                            "properties": {
                                "resource": {"type": "string", "minLength": 1},
                                "column": {"type": "string", "minLength": 1},
                            },
                            "required": ["resource", "column"],
                            "additionalProperties": False,
                        },
                    ]
                },
                "part": {"type": "integer", "minimum": 1},
            },
            "required": ["proposal", "request"],
            "additionalProperties": False,
        },
        "review_proposal": {
            "type": "object",
            "properties": {
                "proposal": {"type": "string"},
                "part": {"type": "integer", "minimum": 1},
            },
            "required": ["proposal"],
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

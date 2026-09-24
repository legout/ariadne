"""Harness-led authoring, slice 1: source proposal and operator approval
(issue #13; spec 2026-09-24-0005 "Evidence and source-access boundary" §1,
ADR-0013).

The harness proposes registry entries; the proposals are DATA, never active
connections. :func:`propose_sources` shape-checks a registry-shaped proposal
document by reusing the existing registry validator (:func:`ariadne.sources.
load_registry` — slugs, known types, ADR-0010 inline-credential rejection),
stores it inert under the project's agent-writable staging area, and reports a
content digest plus the precise locations. No proposed location is opened:
validation is pure YAML parsing and nothing here builds a connection.

:func:`approve_sources` is the separate, human-operated, server-side step
(the packaged skill and every MCP tool are barred from invoking it). It
installs the stored entries into the project's ``ariadne.yaml`` only when the
operator-supplied digest matches the digest re-derived from the STORED
content — so a re-proposal or a hand-edited staging file fails the earlier
approval — and it never overwrites anything: unrelated config keys, existing
registry entries, and their fields survive verbatim (a YAML round-trip drops
comments; the scaffolded template is inert comments). Once installed, the
source is profileable through the same shared connection as every existing
command (``ariadne-profiler --sources ariadne.yaml``) — including its failure:
profiling an approved-but-absent location reports that location honestly.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.sources import _resolve_against, load_registry

# One pending source proposal per project, in the agent-writable staging area
# (a dedicated subdir: never collides with ad-hoc metric or ingest proposals).
PROPOSAL_REL = Path("staging") / "authoring" / "source-proposal.yaml"


def propose_sources(file: str | Path, *, project: str | Path = ".") -> dict:
    """Validate and store one inert source proposal; return its digest and the
    precise proposed locations. Raises the registry validator's errors (naming
    the offending entry) for any invalid or credential-carrying proposal.
    Never opens a location. Relative paths are resolved against the project
    root — the directory of the eventual ``ariadne.yaml`` — so a location means
    the same thing when proposed, digested, and (after approval) profiled,
    whatever directory the intake file arrived in."""
    proposal_path = Path(file)
    load_registry(proposal_path)  # reuse the ADR-0010 validation, verbatim
    entries = _entries(proposal_path)
    base = Path(project).resolve()  # NOT the intake file's directory (spec §1)
    for entry in entries:
        if isinstance(entry.get("path"), str):
            entry["path"] = _resolve_against(base, entry["path"])
    digest = _digest(entries)
    stored = Path(project) / PROPOSAL_REL
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text(
        yaml.safe_dump({"digest": digest, "sources": entries}, sort_keys=False),
        encoding="utf-8",
    )
    return {"digest": digest, "proposal": str(stored), "sources": entries}


def approve_sources(digest: str, *, project: str | Path = ".") -> dict:
    """Human-only: install the digest-matched pending proposal into the
    project's ``ariadne.yaml`` (append-only, preserving unrelated config).
    Raises ``ValueError`` — before writing anything — for a missing or edited
    proposal, a digest mismatch, or a proposed name that already exists."""
    project = Path(project)
    stored = project / PROPOSAL_REL
    if not stored.is_file():
        raise ValueError(
            f"no pending source proposal at {stored} — run propose-sources first"
        )
    load_registry(stored)  # revalidate the stored entries before any install
    entries = _entries(stored)
    current = _digest(entries)
    if current != digest:
        raise ValueError(
            f"digest mismatch: approval is exact-content — the pending proposal "
            f"digest is {current}, not {digest}; review and approve the current digest"
        )
    registry_path = project / "ariadne.yaml"
    if not registry_path.is_file():
        raise ValueError(
            f"no {registry_path} in this project — approval installs into the "
            "configured project's registry"
        )
    doc = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"{registry_path}: top level is not a mapping")
    existing = doc.get("sources") or []
    if not isinstance(existing, list):
        raise ValueError(f"{registry_path}: 'sources' is not a list")
    taken = {
        entry.get("name") for entry in existing if isinstance(entry, dict)
    }
    clashes = [entry["name"] for entry in entries if entry["name"] in taken]
    if clashes:
        raise ValueError(
            f"source name(s) {clashes} already exist in {registry_path} — approval "
            "appends, it never overwrites an existing entry"
        )
    doc["sources"] = [*existing, *entries]
    registry_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return {"digest": digest, "registry": str(registry_path), "sources": entries}


def _entries(path: Path) -> list[dict]:
    """The raw ``sources:`` entries of a proposal/registry document, verbatim
    (validation is load_registry's job; these are what the digest binds and
    the install writes)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = doc.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{path}: no 'sources:' entries")
    return entries


def _digest(entries: list[dict]) -> str:
    """sha256 over the canonical form of the entries: identity is the exact
    proposed content (whitespace and key order do not matter)."""
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

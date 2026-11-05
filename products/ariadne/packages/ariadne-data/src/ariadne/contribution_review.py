"""Read-only whole-contribution review and post-commit identity checks.

The selected contribution is the proposal worktree's staged Git tree. Core owns
its complete inventory and authored diffs; Lumio is imported lazily only for an
integrated Knowledge Base. Neither operation approves, admits, commits or pushes.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import tempfile
from pathlib import Path

from ariadne import (  # pyright: ignore[reportMissingImports] — external qualified env
    answer_examples,
    authoring,
    authoring_sources,
    proposals,
)
from ariadne.validate import validate, validator_identity  # pyright: ignore[reportMissingImports]

_SCHEMA_VERSION = 1
_CONTRACT = "ariadne/contribution-review/1"
_OID = re.compile(r"[0-9a-f]{40}")
_MISSING_OID = "0" * 40
_REVIEW_FIELDS = frozenset(
    {
        "schema_version",
        "validator_contract",
        "proposal",
        "base_revision",
        "head_revision",
        "base_tree",
        "candidate_tree",
        "changes",
        "excluded_unstaged",
        "excluded_untracked",
        "core_changes",
        "unknown_paths",
        "knowledge",
        "source",
        "validation",
        "validator_identities",
        "review_digest",
    }
)


def _digest(record: dict) -> str:
    payload = dict(record)
    payload.pop("review_digest", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _full_commit(project: Path, revision: str, label: str) -> str:
    if not isinstance(revision, str) or not _OID.fullmatch(revision):
        raise ValueError(f"{label} must be one exact full commit object id")
    return proposals._validate_revision(project, revision)


def _tree(project: Path, revision: str) -> str:
    return proposals._git(["rev-parse", f"{revision}^{{tree}}"], project).stdout.strip()


def _changes(worktree: Path, base_tree: str, candidate_tree: str) -> list[dict]:
    raw = proposals._git(
        [
            "diff-tree",
            "-r",
            "--raw",
            "-z",
            "--no-renames",
            base_tree,
            candidate_tree,
        ],
        worktree,
        text=False,
    ).stdout
    records = raw.split(b"\0")
    changes = []
    for index in range(0, len(records) - 1, 2):
        if not records[index]:
            continue
        old_mode, new_mode, old_oid, new_oid, status = (
            part.decode("utf-8") for part in records[index].split(b" ")
        )
        old_mode = old_mode.removeprefix(":")
        changes.append(
            {
                "change": status,
                "path": records[index + 1].decode("utf-8"),
                "base_mode": None if old_mode == "000000" else old_mode,
                "candidate_mode": None if new_mode == "000000" else new_mode,
                "base_blob": None if old_oid == _MISSING_OID else old_oid,
                "candidate_blob": None if new_oid == _MISSING_OID else new_oid,
            }
        )
    return sorted(changes, key=lambda entry: entry["path"])


def _paths(worktree: Path, *argv: str) -> list[str]:
    raw = proposals._git(["--no-optional-locks", *argv], worktree).stdout
    return sorted(path for path in raw.split("\0") if path)


def _text_diff(path: str, before: bytes | None, after: bytes | None) -> str:
    old = (before or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
    new = (after or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
    return "".join(difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}"))


def _core_changes(
    project: Path,
    base_tree: str,
    candidate_tree: str,
    changes: list[dict],
    integrated: bool,
) -> tuple[list[dict], list[str]]:
    reviewed = []
    unknown = []
    for entry in changes:
        path = entry["path"]
        is_knowledge = integrated and path.startswith("knowledge/")
        if is_knowledge:
            continue
        if path.startswith("knowledge/") or not proposals._in_snapshot(path):
            unknown.append(path)
            continue
        reviewed.append(
            {
                "path": path,
                "change": entry["change"],
                "body_diff": _text_diff(
                    path,
                    proposals._read_blob(project, base_tree, path)
                    if entry["base_blob"] is not None
                    else None,
                    proposals._read_blob(project, candidate_tree, path)
                    if entry["candidate_blob"] is not None
                    else None,
                ),
            }
        )
    return reviewed, sorted(unknown)


def _private_registry(private_profile, worktree: Path):
    if private_profile is None:
        return None, None
    if not Path(private_profile).is_absolute():
        raise ValueError("private profile path must be absolute")
    from lumio_wiki.private_profile import (  # pyright: ignore[reportMissingImports]
        load_private_profile,
        resolve_private_profile,
    )

    kb_root = worktree / "knowledge"
    profile = load_private_profile(private_profile, kb_root=kb_root)
    resolved = resolve_private_profile(profile, kb_root=kb_root, needs=frozenset({"registry"}))
    return resolved, profile.namespace


def _static_validation(project: Path, record: dict, tree: Path, resolved_sources) -> dict:
    result = validate(tree)
    errors = list(result.errors)
    approval = authoring_sources.approval_state(
        project,
        resolved_sources,
        authoring_sources.resolved_digest(resolved_sources) if resolved_sources else None,
    )
    errors.extend(authoring._bundle_errors(tree))
    errors.extend(authoring._graph_citation_errors(tree))
    errors.extend(
        authoring._stale_schema_binding_errors(tree, approval.get("approval_digest"))
    )
    errors.extend(authoring._asserted_claim_errors(tree))
    errors.extend(answer_examples.validate_candidate_records(project, record, tree))
    names = {entry["name"] for entry in resolved_sources or []}
    _citations, citation_errors = authoring._verified_citations(tree, project, names)
    errors.extend(citation_errors)
    performed_set = {check.name for check in result.report.checks} if result.report else set()
    performed_set.update(
        {"page_contract", "answer_examples", "citations", "mapping_assertions", "schema_binding"}
    )
    performed = sorted(performed_set)
    return {
        "ok": result.ok and not errors,
        "errors": errors,
        "report": authoring._report_view(result.report) if result.report else None,
        "validator_identity": validator_identity(performed),
    }


def review_contribution(
    project,
    proposal,
    *,
    base_revision,
    private_profile=None,
):
    """Review the complete staged tree without opening live source validation."""
    project = Path(project).resolve()
    record = proposals._load_record(project, proposal)
    worktree = project / proposals.WORKTREES_REL / proposal
    base = _full_commit(project, base_revision, "base_revision")
    head = proposals._git(["rev-parse", "HEAD"], worktree).stdout.strip()
    base_tree = _tree(project, base)
    candidate_tree = proposals._git(["write-tree"], worktree).stdout.strip()
    changes = _changes(worktree, base_tree, candidate_tree)
    excluded_unstaged = _paths(worktree, "diff", "--name-only", "-z")
    excluded_untracked = _paths(worktree, "ls-files", "--others", "--exclude-standard", "-z")

    with tempfile.TemporaryDirectory(prefix="ariadne-contribution-") as tmp:
        tree = Path(tmp) / "bundle"
        tree.mkdir()
        authoring._materialize(project, proposal, candidate_tree, tree)
        from ariadne import lumio_context  # pyright: ignore[reportMissingImports]

        selected = lumio_context.selector(tree)
        core_changes, unknown_paths = _core_changes(
            project, base_tree, candidate_tree, changes, selected is not None
        )
        resolved_sources, source_digest = authoring_sources.candidate_sources(
            project, candidate_tree
        )
        approval = authoring_sources.approval_state(project, resolved_sources, source_digest)
        knowledge = None
        profile_binding_digest = None
        if selected is not None:
            resolved, profile_namespace = _private_registry(private_profile, worktree)
            import msgspec  # pyright: ignore[reportMissingImports]
            from lumio_wiki.authoring_review import (  # pyright: ignore[reportMissingImports]
                review_knowledge_changes,
            )

            knowledge_record = review_knowledge_changes(
                worktree / "knowledge",
                base,
                source_registry=resolved.source_registry if resolved else None,
                candidate_tree=candidate_tree,
            )
            if profile_namespace is not None and profile_namespace != knowledge_record.namespace:
                raise ValueError("the private profile namespace does not match the captured tree")
            knowledge = msgspec.to_builtins(knowledge_record)
            profile_binding_digest = resolved.binding_digest if resolved else None
        elif private_profile is not None:
            raise ValueError("a private source profile requires an integrated Knowledge Base")
        static = _static_validation(project, record, tree, resolved_sources)

    core_identity = static.pop("validator_identity")
    source = {
        "source_digest": source_digest,
        "approval_digest": approval.get("approval_digest"),
        "approval_state": approval["state"],
        "private_profile_binding_digest": profile_binding_digest,
    }
    review = {
        "schema_version": _SCHEMA_VERSION,
        "validator_contract": _CONTRACT,
        "proposal": proposal,
        "base_revision": base,
        "head_revision": head,
        "base_tree": base_tree,
        "candidate_tree": candidate_tree,
        "changes": changes,
        "excluded_unstaged": excluded_unstaged,
        "excluded_untracked": excluded_untracked,
        "core_changes": core_changes,
        "unknown_paths": unknown_paths,
        "knowledge": knowledge,
        "source": source,
        "validation": {
            "static": static,
            "live": {
                "status": "pending",
                "reason": "whole-contribution review is static and opens no source; "
                "native approved-source validation remains a separate operation",
            },
            "admission_ready": False,
        },
        "validator_identities": {
            "core": core_identity,
            "knowledge": knowledge["validator_contract"] if knowledge else None,
        },
        "review_digest": "",
    }
    review["review_digest"] = _digest(review)
    return review


def _require_review(review: dict, proposal: str) -> None:
    if not isinstance(review, dict) or set(review) != _REVIEW_FIELDS:
        raise ValueError("invalid contribution review record")
    if review["schema_version"] != _SCHEMA_VERSION or review["validator_contract"] != _CONTRACT:
        raise ValueError("unsupported contribution review schema or validator contract")
    if review["proposal"] != proposal:
        raise ValueError("the contribution review names a different proposal")
    for key in ("base_revision", "head_revision", "base_tree", "candidate_tree"):
        if not isinstance(review[key], str) or not _OID.fullmatch(review[key]):
            raise ValueError(f"invalid contribution review {key}")
    if not isinstance(review["changes"], list) or not isinstance(review["unknown_paths"], list):
        raise ValueError("invalid contribution review inventory")
    if not isinstance(review["validation"], dict) or not isinstance(
        review["validation"].get("static"), dict
    ):
        raise ValueError("invalid contribution review validation record")
    if review["review_digest"] != _digest(review):
        raise ValueError("contribution review digest mismatch")


def check_contribution_commit(project, proposal, review, revision):
    """Compare one real commit's complete tree, base ancestry and parent to review."""
    project = Path(project).resolve()
    proposals._load_record(project, proposal)
    _require_review(review, proposal)
    worktree = project / proposals.WORKTREES_REL / proposal
    commit = _full_commit(project, revision, "revision")
    base = _full_commit(project, review["base_revision"], "review base_revision")
    commit_tree = _tree(project, commit)
    mismatches = []

    ancestry = proposals._git(
        ["merge-base", "--is-ancestor", base, commit], worktree, check=False
    )
    if ancestry.returncode != 0:
        mismatches.append(f"commit {commit} does not descend from reviewed base {base}")
    if commit_tree != review["candidate_tree"]:
        mismatches.append(
            f"commit tree {commit_tree} differs from reviewed tree {review['candidate_tree']}"
        )

    parent = None
    if commit != review["head_revision"]:
        parents = proposals._git(
            ["rev-list", "--parents", "-n", "1", commit], worktree
        ).stdout.split()[1:]
        if review["head_revision"] in parents:
            parent = review["head_revision"]
        else:
            mismatches.append(
                f"new commit {commit} does not have captured HEAD {review['head_revision']} "
                "as its parent"
            )

    if review["unknown_paths"]:
        mismatches.append(f"review contains unclassified paths: {review['unknown_paths']}")
    knowledge = review["knowledge"]
    if knowledge is not None:
        if knowledge.get("unreviewed_paths"):
            mismatches.append(
                f"review contains undisclosed knowledge paths: {knowledge['unreviewed_paths']}"
            )

    return {
        "schema_version": _SCHEMA_VERSION,
        "validator_contract": _CONTRACT,
        "proposal": proposal,
        "base_revision": base,
        "commit": commit,
        "commit_tree": commit_tree,
        "reviewed_tree": review["candidate_tree"],
        "head_revision": review["head_revision"],
        "parent": parent,
        "matches_reviewed_candidate": not mismatches,
        "mismatches": mismatches,
    }

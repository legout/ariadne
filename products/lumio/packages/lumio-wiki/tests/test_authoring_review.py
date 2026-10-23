"""Review of the staged candidate and exact-commit verification (spec 0010 §4, plan J2/V2).

One focused family, ``test_review_detects_changed_commit``, over real Git and
one fixed hand-authored change set: two cross-referenced new pages (one
evidence-bearing entity-to-entity Claim each in ``object`` form), a body-only
page update, a frontmatter-only page update, one explicit deletion with its
manifest consequences, and one authored ontology addition. Parameter cases
prove only the exact reviewed candidate passes ``authoring-check``: a
post-review frontmatter edit, an unrelated staged repository file (disclosed
by the scoped SDK result, refused by the standalone wrapper), and an actual
pre-commit hook altering committed content all refuse. The same fixtures show
staged-snapshot semantics against differing unstaged/untracked work, excluded
path disclosure, exact-source verification with and without a registry, the
CLI JSON report round-trip (including a tampered report refusal), and that
review never mutates the user's index or worktree.

Oracles are the fixtures and native Git: hand-written page bodies and Claims,
``hashlib.sha256`` digests over hand-written bytes, and Git's own
``write-tree``/``rev-parse``/``show`` blob and tree identities — never
implementation serialization or helper internals.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from lumio_wiki.cli import main
from lumio_wiki.source_references import (
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)
from lumio_wiki.source_registry import SourceRegistry

NAMESPACE = "urn:uuid:5d1c8a34-9e27-4b8f-b0a6-2c4d7e9f1a53"

# Private originals: the marker never appears in any compiled page, so its
# absence from every report proves raw source bytes never leak into reviews.
PRIVATE_MARKER = "PRIVATE-ORIGINAL-BYTES-7f3a42"
MANUAL_BYTES = (
    b"# Operator Manual\n\n"
    + PRIVATE_MARKER.encode()
    + b"\nOperate the hydraulic press only after the safety guard is locked.\n"
)
MEMO_BYTES = b"Shift memo: the weekly service stop covers guard verification."
TOOLLOG_BYTES = b"Tool log: the old tool log retires with this change."
BANDSAW_BYTES = (
    b"# Bandsaw Model BW-3\n\n"
    b"The bandsaw specification fixes the inspection cadence.\n\n"
    b"## Maintenance\n\nBlade guides are inspected at every service stop.\n"
)
MANUAL_ID = "operator-manual"
MEMO_ID = "maintenance-memo"
TOOLLOG_ID = "tool-log-source"
BANDSAW_ID = "bandsaw-spec"
MANUAL_DIGEST = hashlib.sha256(MANUAL_BYTES).hexdigest()
MEMO_DIGEST = hashlib.sha256(MEMO_BYTES).hexdigest()
TOOLLOG_DIGEST = hashlib.sha256(TOOLLOG_BYTES).hexdigest()
BANDSAW_DIGEST = hashlib.sha256(BANDSAW_BYTES).hexdigest()

PRESS_ENTITY = "entity:hydraulic-press"
MEMO_ENTITY = "entity:service-memo"
TOOLLOG_ENTITY = "entity:tool-log"
SAW_ENTITY = "entity:bandsaw"
SAW_CARE_ENTITY = "entity:bandsaw-maintenance"

CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
    journal: {}
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
        - journal
      literal_kind: string
"""

# The candidate Control File adds the authored ontology: one new Entity type
# and two new predicates (literal and object-valued) over it.
CANDIDATE_CONTROL = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
    journal: {}
    bandsaw:
      description: "A bandsaw documented by its specification."
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
        - journal
      literal_kind: string
    inspected-at:
      subject_types:
        - bandsaw
      literal_kind: string
    maintained-with:
      subject_types:
        - bandsaw
      object_types:
        - bandsaw
"""

UNSTAGED_MARKER = "UNSTAGED-EDIT-MARKER-9c11"
HOOK_MARKER = "HOOK-ALTERED-4e08"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr.decode()}")
    return result.stdout.decode().strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test Author")
    return path


def _page(
    title: str,
    entity_id: str,
    entity_type: str,
    source_id: str,
    claim_id: str,
    *,
    summary: str | None = None,
    body_extra: str = "",
) -> str:
    summary_text = f'"{summary}"' if summary is not None else f'"{title} summary."'
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n"
        f"  - {entity_type}\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The original document permanently supports this page."\n'
        'tags:\n  - "workshop"\n'
        f"summary: {summary_text}\n"
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        f'    title: "{source_id} source"\n'
        "claims:\n"
        f"  - id: {claim_id}\n"
        "    predicate: documented-at\n"
        '    value: "2026-10-01"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Overview\n\n"
        f"Supported by the {source_id} original.\n" + body_extra
    )


def _bandsaw_page(
    *, title: str, entity_id: str, object_entity: str, claim_id: str, cross_claim_id: str
) -> str:
    """One new authored page: fixed Entity, the new source, new predicates,
    and one evidence-bearing entity-to-entity cross-page Claim (``object``)."""
    return (
        "---\n"
        f'id: "{entity_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n"
        "  - bandsaw\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The bandsaw specification permanently supports this page."\n'
        'tags:\n  - "workshop"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{BANDSAW_ID}"\n'
        f'    title: "Bandsaw specification"\n'
        "claims:\n"
        f"  - id: {claim_id}\n"
        "    predicate: inspected-at\n"
        '    value: "2026-10-23"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        f"  - id: {cross_claim_id}\n"
        "    predicate: maintained-with\n"
        f'    object: "{object_entity}"\n'
        "    status: accepted\n"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        f"# {title}\n\n"
        "## Overview\n\n"
        "Inspected under the bandsaw specification.\n"
    )


def _manifest(sources: dict[str, str], bindings: dict[str, dict[str, str]]) -> bytes:
    return serialize_source_reference_manifest(
        SourceReferenceManifest(
            version=1,
            namespace=NAMESPACE,
            sources=sources,
            bindings=bindings,
        )
    )


BASE_MANIFEST = _manifest(
    {
        MANUAL_ID: "active",
        MEMO_ID: "active",
        TOOLLOG_ID: "active",
    },
    {
        PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
        MEMO_ENTITY: {MEMO_ID: MEMO_DIGEST},
        TOOLLOG_ENTITY: {TOOLLOG_ID: TOOLLOG_DIGEST},
    },
)

CANDIDATE_MANIFEST = _manifest(
    {
        MANUAL_ID: "active",
        MEMO_ID: "active",
        BANDSAW_ID: "active",
    },
    {
        PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
        MEMO_ENTITY: {MEMO_ID: MEMO_DIGEST},
        SAW_ENTITY: {BANDSAW_ID: BANDSAW_DIGEST},
        SAW_CARE_ENTITY: {BANDSAW_ID: BANDSAW_DIGEST},
    },
)


def _write_base_kb(repo: Path) -> Path:
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / "lumio.yaml").write_text(CONTROL)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _page("Hydraulic Press", PRESS_ENTITY, "machine", MANUAL_ID, "claim:manual-documented")
    )
    (kb / "concepts" / "service-memo.md").write_text(
        _page("Service Memo", MEMO_ENTITY, "note", MEMO_ID, "claim:memo-documented")
    )
    (kb / "concepts" / "tool-log.md").write_text(
        _page("Tool Log", TOOLLOG_ENTITY, "journal", TOOLLOG_ID, "claim:tool-log-documented")
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(BASE_MANIFEST)
    return kb


def _apply_change_set(repo: Path) -> None:
    """Hand-author the fixed candidate and stage exactly its intended paths."""
    kb = repo / "kb"
    (kb / "concepts" / "bandsaw.md").write_text(
        _bandsaw_page(
            title="Bandsaw",
            entity_id=SAW_ENTITY,
            object_entity=SAW_CARE_ENTITY,
            claim_id="claim:saw-inspected",
            cross_claim_id="claim:saw-maintained-with",
        )
    )
    # New pages route with underscores: "Bandsaw Maintenance" -> bandsaw_maintenance.
    (kb / "concepts" / "bandsaw_maintenance.md").write_text(
        _bandsaw_page(
            title="Bandsaw Maintenance",
            entity_id=SAW_CARE_ENTITY,
            object_entity=SAW_ENTITY,
            claim_id="claim:care-inspected",
            cross_claim_id="claim:care-maintained-with",
        )
    )
    # Body-only update: identical frontmatter, extended prose.
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _page(
            "Hydraulic Press",
            PRESS_ENTITY,
            "machine",
            MANUAL_ID,
            "claim:manual-documented",
            body_extra="## Pressure\n\nThe guard interlock is verified weekly.\n",
        )
    )
    # Frontmatter-only update: identical body, changed summary.
    (kb / "concepts" / "service-memo.md").write_text(
        _page(
            "Service Memo",
            MEMO_ENTITY,
            "note",
            MEMO_ID,
            "claim:memo-documented",
            summary="Revised service summary.",
        )
    )
    # Explicit deletion with its manifest consequences.
    (kb / "concepts" / "tool-log.md").unlink()
    (kb / "lumio.yaml").write_text(CANDIDATE_CONTROL)
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(CANDIDATE_MANIFEST)
    _git(repo, "add", "-A", "--", "kb")


def _staged_candidate(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = _init_repo(tmp_path / "repo")
    kb = _write_base_kb(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline revision")
    base = _git(repo, "rev-parse", "HEAD")
    _apply_change_set(repo)
    return repo, kb, base


def _run_cli(argv: list[str], capsys) -> tuple[int, dict]:
    code = main(argv)
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def _index_bytes(repo: Path) -> bytes:
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir"))
    return (git_dir / "index").read_bytes()


def _page_entry(payload: dict, path: str) -> dict:
    pages = {page["path"]: page for page in payload["knowledge"]["pages"]}
    assert path in pages, f"expected reviewed page {path} in {sorted(pages)}"
    return pages[path]


@pytest.mark.parametrize(
    "case",
    [
        "unchanged_exact_candidate",
        "post_review_frontmatter_edit",
        "unrelated_staged_file",
        "commit_hook_alters_content",
    ],
)
def test_review_detects_changed_commit(case, tmp_path, capsys):
    repo, kb, base = _staged_candidate(tmp_path)

    if case == "unchanged_exact_candidate":
        # Excluded work after staging: an unstaged worktree edit on a staged
        # path and one untracked file at the repository root.
        bandsaw = kb / "concepts" / "bandsaw.md"
        staged_bandsaw_bytes = bandsaw.read_bytes()
        bandsaw.write_bytes(staged_bandsaw_bytes + f"\n{UNSTAGED_MARKER}\n".encode())
        (repo / "contributor-note.txt").write_text("Local contributor note.\n")
        # Independent native oracle FIRST: write-tree may update index
        # cache-tree information, so it must not run inside the measured
        # interval; all test status observations use --no-optional-locks so
        # they never opportunistically refresh the live index.
        expected_submitted_tree = _git(repo, "write-tree")
        status_before = _git(repo, "--no-optional-locks", "status", "--porcelain")
        index_before = _index_bytes(repo)

        code, payload = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
        assert code == 0, payload
        # Byte-exact index preservation, asserted before any further test Git
        # command can touch the live index.
        assert _index_bytes(repo) == index_before
        assert payload["ok"] is True
        assert payload["schema_version"] == 1
        assert payload["validator_contract"] == "lumio-wiki/authoring-review/1"
        assert payload["namespace"] == NAMESPACE
        assert payload["kb_subtree"] == "kb"
        assert payload["base_revision"] == base
        assert payload["head_revision"] == base
        # Independent Git oracle captured before the measured interval: the
        # reported tree is exactly the staged index tree.
        assert payload["submitted_tree"] == expected_submitted_tree
        assert payload["base_tree"] == _git(repo, "rev-parse", f"{base}^{{tree}}")
        assert payload["excluded_unstaged"] == ["kb/concepts/bandsaw.md"]
        assert payload["excluded_untracked"] == ["contributor-note.txt"]
        assert payload["knowledge"]["changes_outside_kb"] == []
        assert payload["knowledge"]["kb_valid"] is True
        # Expected warnings derived from the topology warning contract in
        # knowledge_base.py (severity="warning", field "topology", message
        # "orphan page (discovery scope): no inbound topology at all") and
        # the fixed fixture topology: only hydraulic-press and service-memo
        # lack inbound topology (the bandsaw pair links via maintained-with
        # object Claims; tool-log is deleted). Warnings never block review.
        assert payload["knowledge"]["validation_issues"] == [
            "concepts/hydraulic-press.md: topology: "
            "orphan page (discovery scope): no inbound topology at all",
            "concepts/service-memo.md: topology: "
            "orphan page (discovery scope): no inbound topology at all",
        ]
        assert payload["knowledge"]["exact_source_verification"] == "unavailable"
        assert payload["knowledge"]["control_updated"] is True

        # Staged-snapshot semantics: the reviewed body is the staged body,
        # never the unstaged worktree edit.
        saw = _page_entry(payload, "concepts/bandsaw.md")
        assert saw["change"] == "added"
        assert saw["body_changed"] is True
        assert "Inspected under the bandsaw specification." in saw["body_diff"]
        assert UNSTAGED_MARKER not in json.dumps(payload)

        # The fixed change set, displayed: additions, updates (body-only and
        # frontmatter-only), the explicit deletion, and its removed Claims.
        care = _page_entry(payload, "concepts/bandsaw_maintenance.md")
        assert care["change"] == "added"
        press = _page_entry(payload, "concepts/hydraulic-press.md")
        assert press["change"] == "updated"
        assert press["body_changed"] is True
        assert press["frontmatter_only"] is False
        assert "The guard interlock is verified weekly." in press["body_diff"]
        memo = _page_entry(payload, "concepts/service-memo.md")
        assert memo["change"] == "updated"
        assert memo["body_changed"] is False
        assert memo["frontmatter_only"] is True
        removed = _page_entry(payload, "concepts/tool-log.md")
        assert removed["change"] == "removed"
        removed_claim_ids = {c["claim_id"]: c["change"] for c in removed["claims"]}
        assert removed_claim_ids == {"claim:tool-log-documented": "removed"}
        saw_claims = {c["claim_id"]: c["predicate"] for c in saw["claims"]}
        assert saw_claims == {
            "claim:saw-inspected": "inspected-at",
            "claim:saw-maintained-with": "maintained-with",
        }

        ontology = {(c["change"], c["name"]) for c in payload["knowledge"]["ontology_changes"]}
        assert ontology == {
            ("entity_type_added", "bandsaw"),
            ("predicate_added", "inspected-at"),
            ("predicate_added", "maintained-with"),
        }
        manifest_changes = set(payload["knowledge"]["manifest_changes"])
        assert f"source added: {BANDSAW_ID} (active)" in manifest_changes
        assert f"source removed: {TOOLLOG_ID}" in manifest_changes
        assert f"binding removed: {TOOLLOG_ENTITY}" in manifest_changes
        assert f"binding added: {SAW_ENTITY} -> {BANDSAW_ID}@{BANDSAW_DIGEST}" in manifest_changes
        assert (
            f"binding added: {SAW_CARE_ENTITY} -> {BANDSAW_ID}@{BANDSAW_DIGEST}" in manifest_changes
        )

        # Exact path/blob identities against native Git blob oids.
        identities = {i["path"]: i for i in payload["knowledge"]["path_identities"]}
        assert identities["concepts/bandsaw.md"]["change"] == "added"
        assert identities["concepts/bandsaw.md"]["base_blob"] is None
        assert identities["concepts/bandsaw.md"]["candidate_blob"] == _git(
            repo, "rev-parse", ":kb/concepts/bandsaw.md"
        )
        assert identities["concepts/tool-log.md"]["change"] == "removed"
        assert identities["concepts/tool-log.md"]["candidate_blob"] is None
        assert identities["concepts/tool-log.md"]["base_blob"] == _git(
            repo, "rev-parse", f"{base}:kb/concepts/tool-log.md"
        )
        assert identities["concepts/service-memo.md"]["change"] == "updated"

        # No private original bytes and no absolute private paths in the report.
        assert PRIVATE_MARKER not in json.dumps(payload)
        assert str(tmp_path) not in json.dumps(payload)

        # Inspection preserved the user's index and worktree exactly.
        assert _index_bytes(repo) == index_before
        assert _git(repo, "--no-optional-locks", "status", "--porcelain") == status_before
        assert bandsaw.read_bytes() == staged_bandsaw_bytes + f"\n{UNSTAGED_MARKER}\n".encode()

        # A selected registry resolves every candidate binding exactly.
        registry_dir = tmp_path / "registry"
        registry = SourceRegistry(registry_dir)
        registry.register_version(MANUAL_ID, MANUAL_BYTES)
        registry.register_version(MEMO_ID, MEMO_BYTES)
        registry.register_version(BANDSAW_ID, BANDSAW_BYTES)
        code, resolved = _run_cli(
            [
                "authoring-review",
                str(kb),
                "--base",
                base,
                "--source-registry",
                str(registry_dir),
                "--json",
            ],
            capsys,
        )
        assert code == 0, resolved
        assert resolved["knowledge"]["exact_source_verification"] == "registry"
        assert resolved["knowledge"]["kb_valid"] is True
        assert PRIVATE_MARKER not in json.dumps(resolved)
        assert _index_bytes(repo) == index_before

        # The report round-trips through a file for the public journey.
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(payload))
        _git(repo, "commit", "-q", "-m", "reviewed candidate")
        commit = _git(repo, "rev-parse", "HEAD")
        code, check = _run_cli(
            [
                "authoring-check",
                str(kb),
                "--review",
                str(report_path),
                "--revision",
                commit,
                "--json",
            ],
            capsys,
        )
        assert code == 0, check
        assert check["matches_reviewed_candidate"] is True
        assert check["mismatches"] == []
        assert check["commit_tree"] == _git(repo, "rev-parse", f"{commit}^{{tree}}")
        assert check["reviewed_tree"] == payload["submitted_tree"]

        # A tampered report refuses boundedly (digest mismatch).
        tampered = json.loads(json.dumps(payload))
        tampered["namespace"] = "urn:uuid:00000000-0000-0000-0000-000000000000"
        (tmp_path / "tampered.json").write_text(json.dumps(tampered))
        code, refused = _run_cli(
            [
                "authoring-check",
                str(kb),
                "--review",
                str(tmp_path / "tampered.json"),
                "--revision",
                commit,
                "--json",
            ],
            capsys,
        )
        assert code == 1
        assert refused["ok"] is False
        assert refused["schema_version"] == 1
        assert refused["error"]["code"] == "invalid_review_report"

        # Unknown keys refuse boundedly: one top-level and one embedded in
        # the scoped knowledge review (owned v1 records forbid unknown fields).
        unknown_top = json.loads(json.dumps(payload))
        unknown_top["unexpected_top_level"] = True
        (tmp_path / "unknown-top.json").write_text(json.dumps(unknown_top))
        code, refused_top = _run_cli(
            [
                "authoring-check",
                str(kb),
                "--review",
                str(tmp_path / "unknown-top.json"),
                "--revision",
                commit,
                "--json",
            ],
            capsys,
        )
        assert code == 1
        assert refused_top["ok"] is False
        assert refused_top["error"]["code"] == "invalid_review_report"

        unknown_nested = json.loads(json.dumps(payload))
        unknown_nested["knowledge"]["unexpected_knowledge"] = True
        (tmp_path / "unknown-nested.json").write_text(json.dumps(unknown_nested))
        code, refused_nested = _run_cli(
            [
                "authoring-check",
                str(kb),
                "--review",
                str(tmp_path / "unknown-nested.json"),
                "--revision",
                commit,
                "--json",
            ],
            capsys,
        )
        assert code == 1
        assert refused_nested["ok"] is False
        assert refused_nested["error"]["code"] == "invalid_review_report"

    elif case == "post_review_frontmatter_edit":
        code, payload = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
        assert code == 0, payload
        reviewed_blob = _git(repo, "rev-parse", ":kb/concepts/bandsaw.md")
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(payload))

        # A post-review frontmatter edit changes the submitted content.
        bandsaw = kb / "concepts" / "bandsaw.md"
        bandsaw.write_text(
            bandsaw.read_text().replace(
                'summary: "Bandsaw summary."', 'summary: "Post-review summary."'
            )
        )
        _git(repo, "add", "--", "kb/concepts/bandsaw.md")
        _git(repo, "commit", "-q", "-m", "edited after review")
        commit = _git(repo, "rev-parse", "HEAD")
        # Independent Git oracle: the committed blob is not the reviewed blob.
        assert _git(repo, "rev-parse", f"{commit}:kb/concepts/bandsaw.md") != reviewed_blob

        code, check = _run_cli(
            [
                "authoring-check",
                str(kb),
                "--review",
                str(report_path),
                "--revision",
                commit,
                "--json",
            ],
            capsys,
        )
        assert code == 1
        assert check["matches_reviewed_candidate"] is False
        assert "changed after review: kb/concepts/bandsaw.md" in check["mismatches"]

    elif case == "unrelated_staged_file":
        (repo / "README.md").write_text("Unrelated repository work.\n")
        _git(repo, "add", "--", "README.md")

        # The scoped SDK result discloses the outside change and still
        # displays the authored knowledge; it authorizes no submission.
        from lumio_wiki.authoring_review import review_knowledge_changes

        scoped = review_knowledge_changes(kb, base)
        assert scoped.changes_outside_kb == ["README.md"]
        assert scoped.kb_valid is True
        assert "concepts/bandsaw.md" in {page.path for page in scoped.pages}

        # The standalone wrapper refuses it outright.
        code, refused = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
        assert code == 1
        assert refused["ok"] is False
        assert refused["schema_version"] == 1
        assert refused["error"]["code"] == "changes_outside_kb"

    elif case == "commit_hook_alters_content":
        code, payload = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
        assert code == 0, payload
        reviewed_blob = _git(repo, "rev-parse", ":kb/concepts/bandsaw.md")
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps(payload))

        # A real pre-commit hook alters the submitted content.
        hooks = Path(_git(repo, "rev-parse", "--absolute-git-dir")) / "hooks"
        hook = hooks / "pre-commit"
        hook.write_text(
            "#!/bin/sh\n"
            f"printf '\\n{HOOK_MARKER}\\n' >> \"kb/concepts/bandsaw.md\"\n"
            'git add "kb/concepts/bandsaw.md"\n'
        )
        hook.chmod(0o755)
        _git(repo, "commit", "-q", "-m", "hook-altered candidate")
        commit = _git(repo, "rev-parse", "HEAD")
        committed = _git(repo, "show", f"{commit}:kb/concepts/bandsaw.md")
        # Independent Git oracle: the hook changed the committed bytes.
        assert HOOK_MARKER in committed
        assert _git(repo, "rev-parse", f"{commit}:kb/concepts/bandsaw.md") != reviewed_blob

        code, check = _run_cli(
            [
                "authoring-check",
                str(kb),
                "--review",
                str(report_path),
                "--revision",
                commit,
                "--json",
            ],
            capsys,
        )
        assert code == 1
        assert check["matches_reviewed_candidate"] is False
        assert any(
            "differs from the reviewed submitted tree" in mismatch
            for mismatch in check["mismatches"]
        )
        assert "changed after review: kb/concepts/bandsaw.md" in check["mismatches"]


# ---------------------------------------------------------------------------
# Independent J1-J2 review regression preparation (j1-j2-review.md F1-F6, F10).
# Expected values are fixed fixture facts and documented contracts; these
# nodes are RED against the reviewed implementation and must turn green only
# through the parent-authorized product repair.
# ---------------------------------------------------------------------------


def _committed_review(tmp_path, capsys):
    """The standard staged candidate, reviewed and committed exactly."""
    repo, kb, base = _staged_candidate(tmp_path)
    code, payload = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
    assert code == 0, payload
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(payload))
    _git(repo, "commit", "-q", "-m", "reviewed candidate")
    commit = _git(repo, "rev-parse", "HEAD")
    return repo, kb, base, payload, report_path, commit


@pytest.mark.parametrize(
    "tamper",
    ["body_diff", "kb_valid", "page_title", "claim_predicate", "pages_cleared"],
)
def test_review_rejects_inconsistent_report_facts(tamper, tmp_path, capsys):
    """F1: every displayed embedded fact is bound to the review digest."""
    import msgspec

    from lumio_wiki.authoring_review import (
        AuthoringReview,
        AuthoringReviewError,
        check_authoring_commit,
        load_authoring_review_report,
    )

    repo, kb, base, payload, report_path, commit = _committed_review(tmp_path, capsys)
    # Control: the intact report stays valid and verifies its exact commit.
    intact = load_authoring_review_report(report_path)
    assert check_authoring_commit(kb, intact, commit).matches_reviewed_candidate is True

    tampered = json.loads(json.dumps(payload))
    knowledge = tampered["knowledge"]
    if tamper == "body_diff":
        _page_entry(tampered, "concepts/hydraulic-press.md")["body_diff"] = (
            "tampered: unrelated body text"
        )
    elif tamper == "kb_valid":
        knowledge["kb_valid"] = False
    elif tamper == "page_title":
        _page_entry(tampered, "concepts/bandsaw.md")["title"] = "Bandsaw (misleading)"
    elif tamper == "claim_predicate":
        for claim in _page_entry(tampered, "concepts/bandsaw.md")["claims"]:
            if claim["claim_id"] == "claim:saw-inspected":
                claim["predicate"] = "inspected-never"
    else:
        knowledge["pages"] = []

    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered))
    # The public loader must refuse the inconsistent report.
    with pytest.raises(AuthoringReviewError):
        load_authoring_review_report(tampered_path)
    # The public CLI check boundary must refuse it too.
    code, refused = _run_cli(
        [
            "authoring-check",
            str(kb),
            "--review",
            str(tampered_path),
            "--revision",
            commit,
            "--json",
        ],
        capsys,
    )
    assert code == 1
    assert refused["ok"] is False
    # A changed report record must not clear the public SDK check either.
    record = msgspec.json.decode(json.dumps(tampered), type=AuthoringReview)
    try:
        sdk_check = check_authoring_commit(kb, record, commit)
    except AuthoringReviewError:
        sdk_check = None
    assert sdk_check is None or sdk_check.matches_reviewed_candidate is False


@pytest.mark.parametrize("undisplayed", ["plain_notes_file", "reserved_navigation_index"])
def test_review_refuses_undisplayed_submitted_paths(undisplayed, tmp_path, capsys):
    """F2: submitted paths the review never displays must refuse, not ride along."""
    repo, kb, base = _staged_candidate(tmp_path)
    if undisplayed == "plain_notes_file":
        (kb / "notes.txt").write_text("Scratch notes that were never reviewed as knowledge.\n")
    else:
        # A valid marked Navigation Index (reserved derived artifact, issue #64):
        # excluded from loaded pages by contract, so the review displays no
        # readable content for it.
        (kb / "index.md").write_text(
            "---\n"
            "lumio:\n"
            "  artifact: navigation-index\n"
            "  version: 1\n"
            "---\n"
            "\n"
            "# Navigation Index\n"
            "\n"
            "- Hydraulic Press\n"
        )
    _git(repo, "add", "--", "kb")
    code, refused = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
    assert code == 1, refused
    assert refused["ok"] is False
    assert refused["schema_version"] == 1
    assert refused["error"]["code"]


def _press_page(mark: str, *, summary: str, confidence: str | None, body_extra: str = "") -> str:
    """One press page whose source identity/URL, summary and Claim confidence vary."""
    confidence_line = f"    confidence: {confidence}\n" if confidence is not None else ""
    return (
        "---\n"
        f'id: "{PRESS_ENTITY}"\n'
        'title: "Hydraulic Press"\n'
        "entity_types:\n"
        "  - machine\n"
        "category: concepts\n"
        'type: "machine page"\n'
        'durability_rationale: "The original document permanently supports this page."\n'
        'tags:\n  - "workshop"\n'
        f'summary: "{summary}"\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{MANUAL_ID}"\n'
        f'    title: "Operator Manual {mark}"\n'
        f'    url: "https://fixt.example/manual-{mark}"\n'
        "claims:\n"
        "  - id: claim:manual-documented\n"
        "    predicate: documented-at\n"
        '    value: "2026-10-01"\n'
        "    value_type: string\n"
        "    status: accepted\n"
        f"{confidence_line}"
        "    evidence:\n"
        '      - section: "Overview"\n'
        "synthetic: false\n"
        "---\n\n"
        "# Hydraulic Press\n\n"
        "## Overview\n\n"
        f"Supported by the {MANUAL_ID} original.\n"
        + body_extra
    )


def test_review_displays_semantic_before_and_after(tmp_path, capsys):
    """F3: changed semantic values are recoverable before AND after, in the
    structured report and the ordinary CLI review."""
    repo = _init_repo(tmp_path / "repo")
    kb = repo / "kb"
    (kb / "concepts").mkdir(parents=True)
    base_control = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    machine:
      description: "A machine documented by an original source."
    note: {}
    journal: {}
  predicates:
    documented-at:
      subject_types:
        - machine
        - note
      literal_kind: string
"""
    candidate_control = base_control.replace(
        "        - machine\n        - note\n      literal_kind: string",
        "        - machine\n        - note\n        - journal\n      literal_kind: string",
    )
    (kb / "lumio.yaml").write_text(base_control)
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _press_page("v1", summary="Hydraulic Press summary.", confidence=None)
    )
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        _manifest(
            {MANUAL_ID: "active"},
            {PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST}},
        )
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline revision")
    base = _git(repo, "rev-parse", "HEAD")
    (kb / "concepts" / "hydraulic-press.md").write_text(
        _press_page(
            "v2",
            summary="Revised press summary.",
            confidence="0.9",
            body_extra="## Pressure\n\nThe guard interlock is verified weekly.\n",
        )
    )
    (kb / "lumio.yaml").write_text(candidate_control)
    _git(repo, "add", "--", "kb")

    code, payload = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
    assert code == 0, payload
    report = json.dumps(payload)
    # Source URL and title before/after (same Source ID).
    assert "https://fixt.example/manual-v1" in report
    assert "https://fixt.example/manual-v2" in report
    assert "Operator Manual v1" in report
    assert "Operator Manual v2" in report
    # Summary before/after.
    assert "Hydraulic Press summary." in report
    assert "Revised press summary." in report
    # Claim confidence after (fixed fixture fact, absent from the base).
    assert "0.9" in report
    # Predicate domain change: only the candidate definition contains journal.
    assert "journal" in report
    # The ordinary (non-JSON) review renders body and semantic changes too.
    code = main(["authoring-review", str(kb), "--base", base])
    plain = capsys.readouterr().out
    assert code == 0
    assert "The guard interlock is verified weekly." in plain
    assert "https://fixt.example/manual-v2" in plain
    assert "Revised press summary." in plain


def test_authoring_check_rejects_wrong_selected_kb(tmp_path, capsys):
    """F4: the check binds the selected Knowledge Base, not just the repository."""
    namespace_a = "urn:uuid:1f0e3d99-0001-4001-8001-00000000000a"
    namespace_b = "urn:uuid:1f0e3d99-0001-4001-8001-00000000000b"
    repo = _init_repo(tmp_path / "repo")
    kb_a = repo / "kb-a"
    kb_b = repo / "kb-b"
    for kb, namespace in ((kb_a, namespace_a), (kb_b, namespace_b)):
        (kb / "concepts").mkdir(parents=True)
        (kb / "lumio.yaml").write_text(CONTROL)
    (kb_a / "concepts" / "hydraulic-press.md").write_text(
        _page("Hydraulic Press", PRESS_ENTITY, "machine", MANUAL_ID, "claim:manual-documented")
    )
    (kb_a / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        _manifest({MANUAL_ID: "active"}, {PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST}})
    )
    (kb_b / "concepts" / "registry-note.md").write_text(
        _page("Registry Note", MEMO_ENTITY, "note", MEMO_ID, "claim:memo-documented")
    )
    (kb_b / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        _manifest({MEMO_ID: "active"}, {MEMO_ENTITY: {MEMO_ID: MEMO_DIGEST}})
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline revision")
    base = _git(repo, "rev-parse", "HEAD")
    (kb_a / "concepts" / "hydraulic-press.md").write_text(
        _page(
            "Hydraulic Press",
            PRESS_ENTITY,
            "machine",
            MANUAL_ID,
            "claim:manual-documented",
            body_extra="## Pressure\n\nThe guard interlock is verified weekly.\n",
        )
    )
    _git(repo, "add", "--", "kb-a")
    code, payload = _run_cli(["authoring-review", str(kb_a), "--base", base, "--json"], capsys)
    assert code == 0, payload
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(payload))
    _git(repo, "commit", "-q", "-m", "reviewed kb-a candidate")
    commit = _git(repo, "rev-parse", "HEAD")

    # Checking with kb-b selected must refuse: that Knowledge Base was never
    # the reviewed scope, even though the commit tree is exact.
    code, check = _run_cli(
        [
            "authoring-check",
            str(kb_b),
            "--review",
            str(report_path),
            "--revision",
            commit,
            "--json",
        ],
        capsys,
    )
    assert code == 1
    if check.get("ok") is True:
        assert check["matches_reviewed_candidate"] is False
    else:
        assert check["ok"] is False


@pytest.mark.parametrize("structural_defect", ["missing_binding", "nonexistent_entity"])
def test_review_validates_bindings_without_registry(structural_defect, tmp_path, capsys):
    """F5: structural Source Reference Manifest validation never depends on a registry."""
    repo, kb, base = _staged_candidate(tmp_path)
    if structural_defect == "missing_binding":
        # The active managed operator-manual source is declared by the press
        # page but carries no binding for its Entity.
        tampered_bindings = {
            MEMO_ENTITY: {MEMO_ID: MEMO_DIGEST},
            SAW_ENTITY: {BANDSAW_ID: BANDSAW_DIGEST},
            SAW_CARE_ENTITY: {BANDSAW_ID: BANDSAW_DIGEST},
        }
    else:
        tampered_bindings = {
            PRESS_ENTITY: {MANUAL_ID: MANUAL_DIGEST},
            MEMO_ENTITY: {MEMO_ID: MEMO_DIGEST},
            TOOLLOG_ENTITY: {TOOLLOG_ID: TOOLLOG_DIGEST},
            SAW_ENTITY: {BANDSAW_ID: BANDSAW_DIGEST},
            SAW_CARE_ENTITY: {BANDSAW_ID: BANDSAW_DIGEST},
            "entity:ghost": {MANUAL_ID: MANUAL_DIGEST},
        }
    (kb / SOURCE_REFERENCE_MANIFEST_BASENAME).write_bytes(
        _manifest(
            {MANUAL_ID: "active", MEMO_ID: "active", BANDSAW_ID: "active"},
            tampered_bindings,
        )
    )
    _git(repo, "add", "--", "kb")
    code, payload = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
    if code == 0:
        issues = json.dumps(payload["knowledge"]["validation_issues"])
        assert payload["knowledge"]["kb_valid"] is False
        assert "entity:ghost" in issues or "entity:hydraulic-press" in issues or (
            MANUAL_ID in issues
        )
    else:
        assert payload["ok"] is False
        assert payload["schema_version"] == 1


@pytest.mark.parametrize("expression", ["HEAD^{tree}", "movable-branch^{tree}"])
def test_review_requires_immutable_candidate_tree(expression, tmp_path):
    """F6: candidate_tree must be one exact full tree OID, not a movable expression."""
    from lumio_wiki.authoring_review import AuthoringReviewError, review_knowledge_changes

    repo, kb, base = _staged_candidate(tmp_path)
    _git(repo, "branch", "movable-branch")
    with pytest.raises(AuthoringReviewError):
        review_knowledge_changes(kb, base, candidate_tree=expression)
    # Control: an independently obtained full native Git tree OID is accepted
    # and reported as the immutable identity.
    tree_oid = _git(repo, "write-tree")
    scoped = review_knowledge_changes(kb, base, candidate_tree=tree_oid)
    assert scoped.candidate_tree == tree_oid


@pytest.mark.parametrize("malformed", ["invalid_yaml_syntax", "ontology_wrong_shape"])
def test_review_handles_invalid_staged_ontology(malformed, tmp_path, capsys):
    """F10: invalid staged Control Files produce bounded versioned failures."""
    repo, kb, base = _staged_candidate(tmp_path)
    if malformed == "invalid_yaml_syntax":
        (kb / "lumio.yaml").write_text(
            'version: 2\nmode: "categorized"\ncategories:\n  - name: concepts\nontology: [unclosed\n'
        )
    else:
        (kb / "lumio.yaml").write_text(
            'version: 2\nmode: "categorized"\ncategories:\n  - name: concepts\n'
            "ontology:\n  - documented-at\n"
        )
    _git(repo, "add", "--", "kb")
    status_before = _git(repo, "--no-optional-locks", "status", "--porcelain")
    code, refused = _run_cli(["authoring-review", str(kb), "--base", base, "--json"], capsys)
    assert code == 1
    assert refused["ok"] is False
    assert refused["schema_version"] == 1
    assert refused["error"]["code"]
    assert _git(repo, "--no-optional-locks", "status", "--porcelain") == status_before

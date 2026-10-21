"""Issue #169 retained Claim and Entity Merge oracles on native Git seams.

Covers Claim additions/edits/lifecycle/removals and reviewed Entity Merge:
Claim retargeting and migration, exactly resolved link repair, ontology
redirects, retired-page removal, and stable surviving Entity identity.
Collisions and invalid resulting ontologies refuse without authoring writes.
The live proposal pipeline is retired by spec 0008 §7; explicit Git commits
and exact-revision publication remain separate from these worktree edits.
"""

from __future__ import annotations

import re
from pathlib import Path

import lumio_wiki as lw
import pytest
from lumio_wiki.cli import main
from lumio_wiki.git_authoring import merge_entities_in_worktree
from lumio_wiki.ingest import (
    CLAIM_CHANGE_ADDED,
    CLAIM_CHANGE_EDITED,
    CLAIM_CHANGE_REMOVED,
    CLAIM_CHANGE_STATUS,
)
from lumio_wiki.knowledge_base import load_knowledge_base

# ---------------------------------------------------------------------------
# Fixtures (mirroring test_page_removal.py conventions)
# ---------------------------------------------------------------------------


def _slug(text: str) -> str:
    """Entity-id slug: lowercase, non-alphanumerics collapsed to hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(
    title: str,
    *,
    body: str = "Body.",
    sources=None,
    relationships=None,
    aliases=None,
    claim_overrides=None,
) -> str:
    """Render a Compiled Page.

    Typed edges are accepted, evidence-bearing Claims whose object is the
    target page's Entity id. ``claim_overrides`` replaces the generated
    claims block with literal YAML lines (for hand-crafted Claim IDs).
    """
    src = (
        sources
        if sources is not None
        else [{"id": f"{title.lower()}-src", "title": f"{title} src"}]
    )
    als = aliases if aliases is not None else []
    src_lines = "\n".join(
        f'  - id: "{s.get("id", "")}"\n    title: "{s.get("title", "")}"' for s in src
    )
    if claim_overrides is not None:
        claims_lines = claim_overrides
    else:
        claims_lines = "".join(
            f'  - id: "claim:{_slug(title)}-{_slug(rel["target"])}-{n}"\n'
            f'    predicate: "{rel["type"]}"\n'
            f'    object: "entity:{_slug(rel["target"])}"\n'
            f"    status: accepted\n"
            f'    evidence:\n      - section: "Evidence"\n'
            for n, rel in enumerate(relationships or [])
        )
    entity_lines = f'id: "entity:{_slug(title)}"\nentity_types:\n  - concept\n'
    if claims_lines:
        entity_lines += f"claims:\n{claims_lines}"
    body_text = (
        f"{body}\n\n## Evidence\n\nSupporting evidence for the edges.\n" if claims_lines else body
    )
    return (
        "---\n"
        f'title: "{title}"\n'
        f"aliases: {als}\n"
        'tags:\n  - "t"\n'
        f'summary: "{title} summary."\n'
        'lifecycle: "approved"\n'
        'visibility: "public"\n'
        f"sources:\n{src_lines}\n"
        f"{entity_lines}"
        "synthetic: false\n"
        "---\n"
        f"# {title}\n\n{body_text}\n"
    )


def _categorized_kb(
    tmp_path: Path,
    *,
    hot_pins: list[str] | None = None,
    redirects: str = "",
    extra_predicates: str = "",
) -> Path:
    """A categorized Knowledge Base root with a Control File."""
    root = tmp_path / "kb"
    root.mkdir(parents=True)
    pins_block = ""
    if hot_pins:
        pin_lines = "\n".join(f'  - {{title: "{p}"}}' for p in hot_pins)
        pins_block = f"\nhot_index:\n{pin_lines}\n"
    _write(
        root,
        "lumio.yaml",
        (
            "version: 2\n"
            "mode: categorized\n"
            "categories:\n"
            "  - {name: concepts}\n"
            "ontology:\n"
            "  entity_types:\n"
            "    concept: {}\n"
            "  predicates:\n"
            "    depends-on:\n"
            "      subject_types: [concept]\n"
            "      object_types: [concept]\n"
            "    see:\n"
            "      subject_types: [concept]\n"
            "      object_types: [concept]\n"
            f"{extra_predicates}"
            "  redirects:"
            f"{redirects}\n"
            f"{pins_block}"
        ),
    )
    return root


def _merge_kb(tmp_path: Path) -> Path:
    """The canonical three-page merge Knowledge Base.

    Alpha depends-on Beta and links to it; Beta depends-on Alpha; Gamma sees
    Alpha. The default merge under test retires ``entity:beta`` into
    ``entity:gamma``.
    """
    root = _categorized_kb(tmp_path)
    _write(
        root,
        "concepts/alpha.md",
        _page(
            "Alpha",
            body="See [[Beta]].",
            relationships=[{"target": "Beta", "type": "depends-on"}],
        ),
    )
    _write(
        root,
        "concepts/beta.md",
        _page("Beta", relationships=[{"target": "Alpha", "type": "depends-on"}]),
    )
    _write(
        root,
        "concepts/gamma.md",
        _page("Gamma", relationships=[{"target": "Alpha", "type": "see"}]),
    )
    return root


def _git_authoring_worktree(root: Path) -> Path:
    """Wrap the built Knowledge Base in a committed Git authoring worktree (G3)."""
    import subprocess

    def _git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)

    _git("init", "-q")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test Author")
    _git("add", "-A")
    _git("commit", "-q", "-m", "authoring revision")
    return root


def _claim_objects(root: Path) -> set[tuple[str, str, str]]:
    """All (page title, claim id, object entity id) triples in a KB."""
    kb, report = load_knowledge_base(root)
    assert report.is_valid, report
    return {
        (page.title, claim.id, claim.object)
        for page in kb.pages
        for claim in page.claims
        if claim.object is not None
    }


# ---------------------------------------------------------------------------
# Entity Merge: the reviewed, atomic mutation
# ---------------------------------------------------------------------------


def test_entity_merge_publishes_one_atomic_candidate(tmp_path):
    """Retarget, migrate, repair links, redirect, remove — ONE proposal."""
    root = _merge_kb(tmp_path)
    kb, _ = load_knowledge_base(root)
    _git_authoring_worktree(root)

    proposal = lw.assemble_entity_merge_candidate(kb, "entity:beta", "entity:gamma")
    assert proposal.validation_report.is_valid, proposal.validation_report
    assert proposal.blast_radius is not None  # populated by assemble; narrows the type
    # Blast radius discloses the Claim-level changes without page bodies.
    changed = {(c.claim_id, c.change) for c in proposal.blast_radius.claim_changes}
    assert ("claim:alpha-beta-0", CLAIM_CHANGE_EDITED) in changed
    assert ("claim:beta-alpha-0", CLAIM_CHANGE_ADDED) in changed  # migrated to Gamma
    assert "# Beta" not in proposal.diff.split("deleted file:")[0]

    from lumio_wiki.git_authoring import merge_entities_in_worktree

    merge_entities_in_worktree(root, "entity:beta", "entity:gamma")
    kb, report = load_knowledge_base(root)
    assert report.is_valid, report
    titles = {page.title for page in kb.pages}
    assert titles == {"Alpha", "Gamma"}  # retired page excluded atomically
    objects = _claim_objects(root)
    # Alpha's claim retargeted to the surviving Entity ID.
    assert ("Alpha", "claim:alpha-beta-0", "entity:gamma") in objects
    assert not any(obj == "entity:beta" for _t, _c, obj in objects)
    # Beta's claim migrated onto the surviving page; Gamma keeps its own.
    assert ("Gamma", "claim:beta-alpha-0", "entity:alpha") in objects
    assert ("Gamma", "claim:gamma-alpha-0", "entity:alpha") in objects
    # Stable surviving ID: Gamma's page keeps its Entity ID and path.
    gamma = next(page for page in kb.pages if page.title == "Gamma")
    assert gamma.id == "entity:gamma"
    assert gamma.path == "concepts/gamma.md"
    # Exactly-resolved body link repaired to the survivor.
    alpha_markdown = (root / "concepts/alpha.md").read_text(encoding="utf-8")
    assert "[[Gamma]]" in alpha_markdown and "[[Beta]]" not in alpha_markdown
    # Retired Entity ID recorded as an ontology redirect.
    control_yaml = (root / "lumio.yaml").read_text(encoding="utf-8")
    assert "entity:beta: entity:gamma" in control_yaml


def test_entity_merge_collision_blocks_publication(tmp_path):
    """A migrated Claim whose subject violates the predicate domain blocks.

    From a valid base every Claim ID is Knowledge-Base-wide unique, so the
    reachable merge collision is semantic: the retired TOOL page's
    ``built-with`` Claim (subject_types: [tool]) migrates onto the CONCEPT
    survivor, whose types no longer satisfy the predicate domain.
    Publication blocks; the working Knowledge Base is unchanged.
    """
    root = tmp_path / "kb"
    root.mkdir(parents=True)
    _write(
        root,
        "lumio.yaml",
        (
            "version: 2\n"
            "mode: categorized\n"
            "categories:\n"
            "  - {name: concepts}\n"
            "ontology:\n"
            "  entity_types:\n"
            "    concept: {}\n"
            "    tool: {}\n"
            "  predicates:\n"
            "    depends-on:\n"
            "      subject_types: [concept]\n"
            "      object_types: [concept]\n"
            "    see:\n"
            "      subject_types: [concept]\n"
            "      object_types: [concept]\n"
            "    built-with:\n"
            "      subject_types: [tool]\n"
            "      object_types: [concept]\n"
            "  redirects:\n"
        ),
    )
    _write(root, "concepts/alpha.md", _page("Alpha"))
    # The retired TOOL page holds a domain-valid built-with Claim.
    hammer = _page(
        "Hammer",
        claim_overrides=(
            '  - id: "claim:hammer-alpha-0"\n'
            '    predicate: "built-with"\n'
            '    object: "entity:alpha"\n'
            "    status: accepted\n"
            '    evidence:\n      - section: "Evidence"\n'
        ),
    ).replace("  - concept\n", "  - tool\n", 1)
    _write(root, "concepts/hammer.md", hammer)
    _write(root, "concepts/anvil.md", _page("Anvil"))
    before = _claim_objects(root)
    kb, _ = load_knowledge_base(root)
    _git_authoring_worktree(root)

    proposal = lw.assemble_entity_merge_candidate(kb, "entity:hammer", "entity:anvil")

    assert not proposal.validation_report.is_valid
    assert any(
        "domain violation" in issue.message for issue in proposal.validation_report.issues
    ), proposal.validation_report
    from lumio_wiki.git_authoring import GitAuthoringError, merge_entities_in_worktree

    with pytest.raises(GitAuthoringError):
        merge_entities_in_worktree(root, "entity:hammer", "entity:anvil")
    # Failed publication leaves the prior state active and unchanged.
    assert _claim_objects(root) == before
    kb, report = load_knowledge_base(root)
    assert report.is_valid, report
    assert {page.title for page in kb.pages} == {"Alpha", "Hammer", "Anvil"}


def test_entity_merge_invalid_resulting_ontology_blocks_publication(tmp_path):
    """A retargeted Claim that violates the predicate range blocks."""
    root = tmp_path / "kb"
    root.mkdir(parents=True)
    _write(
        root,
        "lumio.yaml",
        (
            "version: 2\n"
            "mode: categorized\n"
            "categories:\n"
            "  - {name: concepts}\n"
            "ontology:\n"
            "  entity_types:\n"
            "    concept: {}\n"
            "    tool: {}\n"
            "  predicates:\n"
            "    depends-on:\n"
            "      subject_types: [concept]\n"
            "      object_types: [concept]\n"
            "    see:\n"
            "      subject_types: [concept]\n"
            "      object_types: [concept]\n"
            "    built-with:\n"
            "      subject_types: [concept]\n"
            "      object_types: [tool]\n"
            "  redirects:\n"
        ),
    )
    _write(
        root,
        "concepts/alpha.md",
        _page(
            "Alpha",
            claim_overrides=(
                '  - id: "claim:alpha-tool-0"\n'
                '    predicate: "built-with"\n'
                '    object: "entity:hammer"\n'
                "    status: accepted\n"
                '    evidence:\n      - section: "Evidence"\n'
            ),
        ),
    )
    # A tool-typed page (hand-authored: different entity_types).
    hammer = _page("Hammer").replace("  - concept\n", "  - tool\n")
    _write(root, "concepts/hammer.md", hammer)
    _write(root, "concepts/anvil.md", _page("Anvil"))
    kb, _ = load_knowledge_base(root)
    _git_authoring_worktree(root)

    # Merging the TOOL entity into a CONCEPT page retargets Alpha's
    # built-with claim at a concept object: a range violation.
    proposal = lw.assemble_entity_merge_candidate(kb, "entity:hammer", "entity:anvil")

    assert not proposal.validation_report.is_valid
    assert any("range violation" in issue.message for issue in proposal.validation_report.issues), (
        proposal.validation_report
    )
    from lumio_wiki.git_authoring import GitAuthoringError, merge_entities_in_worktree

    with pytest.raises(GitAuthoringError):
        merge_entities_in_worktree(root, "entity:hammer", "entity:anvil")
    kb, report = load_knowledge_base(root)
    assert report.is_valid, report


def test_claim_changes_report_additions_edits_lifecycle_and_removals(tmp_path):
    root = _categorized_kb(tmp_path)
    _write(root, "concepts/beta.md", _page("Beta"))
    _write(root, "concepts/gamma.md", _page("Gamma"))
    # Existing Alpha: two claims (a1 disputed later, a2 removed later).
    existing = _page(
        "Alpha",
        claim_overrides=(
            '  - id: "claim:a1"\n'
            '    predicate: "depends-on"\n'
            '    object: "entity:beta"\n'
            "    status: accepted\n"
            '    evidence:\n      - section: "Evidence"\n'
            '  - id: "claim:a2"\n'
            '    predicate: "see"\n'
            '    object: "entity:gamma"\n'
            "    status: accepted\n"
            '    evidence:\n      - section: "Evidence"\n'
            '  - id: "claim:a5"\n'
            '    predicate: "see"\n'
            '    object: "entity:beta"\n'
            "    status: accepted\n"
            '    evidence:\n      - section: "Evidence"\n'
            '      - section: "Evidence"\n'
        ),
    )
    _write(root, "concepts/alpha.md", existing)
    kb, _ = load_knowledge_base(root)

    # Proposed Alpha: a1 disputed (lifecycle), a2 gone (removed), a3 added
    # (accepted), a4 added (proposed — stays in proposal state), a5 same
    # status but one more evidence anchor (edited).
    revised = _page(
        "Alpha",
        claim_overrides=(
            '  - id: "claim:a1"\n'
            '    predicate: "depends-on"\n'
            '    object: "entity:beta"\n'
            "    status: disputed\n"
            '    evidence:\n      - section: "Evidence"\n'
            '  - id: "claim:a3"\n'
            '    predicate: "see"\n'
            '    object: "entity:gamma"\n'
            "    status: accepted\n"
            '    evidence:\n      - section: "Evidence"\n'
            '  - id: "claim:a4"\n'
            '    predicate: "see"\n'
            '    object: "entity:beta"\n'
            "    status: proposed\n"
            '    evidence:\n      - section: "Evidence"\n'
            '  - id: "claim:a5"\n'
            '    predicate: "see"\n'
            '    object: "entity:beta"\n'
            "    status: accepted\n"
            '    evidence:\n      - section: "Evidence"\n'
            '      - section: "Evidence"\n'
            '      - section: "Evidence"\n'
        ),
    )
    pages = [lw.ProposedPage("concepts/alpha.md", "Alpha", revised)]
    blast_radius = lw.compute_blast_radius(pages, kb)

    assert blast_radius is not None  # populated by assemble; narrows the type
    changes = {c.claim_id: c for c in blast_radius.claim_changes}
    assert set(changes) == {"claim:a1", "claim:a2", "claim:a3", "claim:a4", "claim:a5"}
    assert changes["claim:a1"].change == CLAIM_CHANGE_STATUS
    assert "status=accepted" in changes["claim:a1"].before
    assert "status=disputed" in changes["claim:a1"].after
    assert changes["claim:a2"].change == CLAIM_CHANGE_REMOVED
    assert changes["claim:a3"].change == CLAIM_CHANGE_ADDED
    assert "status=accepted" in changes["claim:a3"].after
    assert changes["claim:a4"].change == CLAIM_CHANGE_ADDED
    assert "status=proposed" in changes["claim:a4"].after  # proposal-state lifecycle
    assert changes["claim:a5"].change == CLAIM_CHANGE_EDITED
    assert "evidence=2" in changes["claim:a5"].before
    assert "evidence=3" in changes["claim:a5"].after

    # Proposed/rejected assertions stay in proposal state: the proposal carries
    # them, but publication is blocked (active pages only hold accepted,
    # disputed, or superseded Claims — ADR-0021).
    report = lw.validate_candidate_knowledge_base(pages, root)
    assert not report.is_valid
    assert (root / "concepts/alpha.md").read_text() == existing


def test_entity_merge_repairs_alias_links_and_prefers_title_over_alias(tmp_path):
    """Exactly-resolved links repair even when another page shares an alias.

    ``[[Beta]]`` resolves by the retired page's unique Canonical Title (the
    resolver's first key), so Zeta's alias "Beta" cannot make it ambiguous:
    the link repairs to the surviving title (G3-S R2 contract, preserved on
    the native worktree route after the pipeline retirement).
    """
    root = _categorized_kb(tmp_path)
    _write(
        root,
        "concepts/alpha.md",
        _page("Alpha", body="See [[Beta]]."),
    )
    _write(root, "concepts/beta.md", _page("Beta"))
    _write(root, "concepts/zeta.md", _page("Zeta", aliases=["Beta"]))
    _write(root, "concepts/gamma.md", _page("Gamma"))

    _git_authoring_worktree(root)
    merge_entities_in_worktree(root, "entity:beta", "entity:gamma")

    alpha_markdown = (root / "concepts/alpha.md").read_text(encoding="utf-8")
    assert "[[Gamma]]" in alpha_markdown and "[[Beta]]" not in alpha_markdown


def test_merge_entity_cli_edits_the_authoring_worktree(tmp_path, capsys):
    # G3 (spec 0008 §2/§6/§7): the CLI merge edits the selected Git authoring
    # worktree as ordinary files — the retired page is an explicit tree
    # deletion, the redirect lands in the Control File, no proposal is
    # staged, and nothing is committed (the author reviews the diff).
    root = _git_authoring_worktree(_merge_kb(tmp_path))
    ingest_dir = tmp_path / "cli-ingest"

    exit_code = main(
        ["merge-entity", str(root), "entity:beta", "entity:gamma", "--ingest-dir", str(ingest_dir)]
    )
    out = capsys.readouterr().out
    assert exit_code == 0, out
    assert "Merged entity 'entity:beta' into 'entity:gamma'" in out

    assert not (root / "concepts" / "beta.md").exists()
    assert "entity:beta: entity:gamma" in (root / "lumio.yaml").read_text(encoding="utf-8")
    # Ordinary files only: no ingest store, no staged proposal.
    assert not ingest_dir.exists()
    assert not (root / ".lumio").exists()

    kb, report = load_knowledge_base(root)
    assert report.is_valid, report
    assert {page.title for page in kb.pages} == {"Alpha", "Gamma"}


def test_merge_entity_cli_blocked_merge_is_an_error(tmp_path, capsys):
    # The domain-violation merge (tool page retired into a concept survivor)
    # stages BLOCKED; the CLI reports the block.
    root = _merge_kb(tmp_path)
    exit_code = main(
        [
            "merge-entity",
            str(root),
            "entity:beta",
            "entity:nope",
            "--ingest-dir",
            str(tmp_path / "i"),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Staged proposal" not in captured.out
    assert "error:" in captured.err

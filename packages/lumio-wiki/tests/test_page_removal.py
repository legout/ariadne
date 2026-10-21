"""Retained removal/Claim/link/pin oracles, migrated from the original tests."""

import re
from pathlib import Path

import lumio_wiki as lw
from lumio_wiki.git_authoring import remove_page_in_worktree
from lumio_wiki.knowledge_base import load_knowledge_base
from lumio_wiki.publish import assemble_page_removal_candidate

from .test_entity_merge import _git_authoring_worktree


def _slug(text: str) -> str:
    """Entity-id slug: lowercase, non-alphanumerics collapsed to hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(
    title: str, *, body: str = "Body.", sources=None, relationships=None, aliases=None
) -> str:
    """Render a Compiled Page.

    Since ADR-0021 the title-based ``relationships`` frontmatter input is
    gone: a typed edge to another page is an accepted, evidence-bearing Claim
    whose object is the target page's Entity id ("entity:<slug-of-title>").
    Every page declares its Entity id and type so claim objects resolve.
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


def _categorized_kb(tmp_path: Path, *, hot_pins: list[str] | None = None) -> Path:
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
            f"{pins_block}"
        ),
    )
    return root


def test_relationship_repair_drops_edges_and_repairs_exactly_resolved_links(tmp_path):
    root = _categorized_kb(tmp_path, hot_pins=["Beta"])
    _write(
        root,
        "concepts/alpha.md",
        _page(
            "Alpha",
            body=(
                "Details in [[Beta]] and [[Beta|the beta notes]] and "
                "[plain](beta.md) and [other](gamma.md)."
            ),
            relationships=[{"target": "Beta", "type": "depends-on"}],
        ),
    )
    _write(root, "concepts/beta.md", _page("Beta"))
    _write(root, "concepts/gamma.md", _page("Gamma"))
    kb, _ = load_knowledge_base(root)

    proposal = assemble_page_removal_candidate(kb, "Beta")

    # AC5: Alpha gets ONE repair revision that drops the depends-on edge.
    assert [p.title for p in proposal.proposed_pages] == ["Alpha"]
    repair = proposal.proposed_pages[0]
    # The dropped edge surfaces in the blast radius (review disclosure).
    assert proposal.blast_radius is not None
    assert any(
        c.claim_id == "claim:alpha-beta-0" and c.change == "removed"
        for c in proposal.blast_radius.claim_changes
    )
    # The repair markdown no longer claims the removed page's Entity.
    _data, _body, _ = lw.parse_frontmatter(repair.markdown, Path("concepts/alpha.md"))
    assert all(c.get("object") != "entity:beta" for c in _data.get("claims", []))

    # AC6: every exactly-resolved link to Beta is unwrapped to its readable
    # text; the unrelated link to Gamma is untouched.
    assert "Details in Beta and the beta notes and plain and [other](gamma.md)." in (
        repair.markdown
    )
    assert "[[Beta]]" not in repair.markdown and "(beta.md)" not in repair.markdown
    # Disclosure lists each repaired link exactly once (reviewer visibility).
    alpha_beta = [
        c
        for c in proposal.body_link_repairs
        if c.source_title == "Alpha" and c.target_title == "Beta"
    ]
    assert len(alpha_beta) == 1
    _git_authoring_worktree(root)
    remove_page_in_worktree(root, "Beta")
    after, report = load_knowledge_base(root)
    assert report.is_valid, report
    assert {p.title for p in after.pages} == {"Alpha", "Gamma"}
    assert after.control is not None
    assert after.control.hot_index == []


def test_external_images_code_and_ambiguous_links_are_untouched(tmp_path):
    """External URLs, images, inline code, and ambiguous targets stay verbatim."""
    root = _categorized_kb(tmp_path)
    _write(
        root,
        "concepts/alpha.md",
        _page(
            "Alpha",
            body=(
                "Web at [site](https://example.com/beta) and ![alt](beta.md) and "
                'code `[[Beta]]` plus [x](beta.md "title") end.'
            ),
        ),
    )
    _write(root, "concepts/beta.md", _page("Beta"))
    _write(
        root,
        "concepts/zeta.md",
        _page("BETA").replace('id: "entity:beta"', 'id: "entity:beta-shadow"'),
    )
    kb, _ = load_knowledge_base(root)

    proposal = assemble_page_removal_candidate(kb, "Beta")

    # Nothing staged: the only internal link is ambiguous (Beta AND BETA),
    # never guessed. The removal itself still stages (diagnostic, not blocking).
    assert proposal.proposed_pages == []
    assert proposal.validation_report.is_valid

    # With the case collision gone, exactly-resolved links unwrap while the
    # external URL, image, and inline-code span stay verbatim.
    (root / "concepts/zeta.md").unlink()
    kb2, _ = load_knowledge_base(root)
    proposal2 = assemble_page_removal_candidate(kb2, "Beta")
    assert [p.title for p in proposal2.proposed_pages] == ["Alpha"]
    markdown = proposal2.proposed_pages[0].markdown
    assert "[site](https://example.com/beta)" in markdown
    assert "![alt](beta.md)" in markdown
    assert "`[[Beta]]`" in markdown
    assert "code `[[Beta]]` plus x end." in markdown

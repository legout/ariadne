"""skills/ mirrors the packaged agent skills byte for byte.

`npx skills add legout/ariadne` discovers skills under skills/<name>/SKILL.md;
the packages stay the source of truth. Regenerate with
`python scripts/sync_skills.py` after editing a packaged skill.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGED = {
    "ariadne": ROOT / "products/ariadne/packages/ariadne-data/src/ariadne/skill_assets",
    "lumio-wiki": ROOT / "products/lumio/packages/lumio-wiki/src/lumio_wiki/data/skill",
}


def _skill_files(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.suffix == ".md"
    }


def test_skills_dir_mirrors_packaged_skills():
    mirrored = {p.name for p in (ROOT / "skills").iterdir() if p.is_dir()}
    assert mirrored == set(PACKAGED)
    for name, source in PACKAGED.items():
        assert _skill_files(ROOT / "skills" / name) == _skill_files(source), (
            f"skills/{name} is stale: run python scripts/sync_skills.py"
        )

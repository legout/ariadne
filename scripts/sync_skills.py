"""Mirror the packaged agent skills into skills/<name>/ for `npx skills add`.

The packages stay the source of truth; tests/test_skills_mirror.py fails when
the mirror is stale. Run from anywhere: python scripts/sync_skills.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGED = {
    "ariadne": ROOT / "products/ariadne/packages/ariadne-data/src/ariadne/skill_assets",
    "lumio-wiki": ROOT / "products/lumio/packages/lumio-wiki/src/lumio_wiki/data/skill",
}

for name, source in PACKAGED.items():
    target = ROOT / "skills" / name
    shutil.rmtree(target, ignore_errors=True)
    for path in sorted(source.rglob("*.md")):
        dest = target / path.relative_to(source)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
    print(f"skills/{name} <- {source.relative_to(ROOT)}")

#!/usr/bin/env bash
# Assemble the monorepo documentation into docs-site/docs/ for Zensical.
# Source files stay in their canonical locations; this script copies them
# into the layout Zensical expects, rewriting cross-references where needed.
set -eu
cd "$(dirname "$0")"

DOCS="docs"
rm -rf "$DOCS"
mkdir -p "$DOCS"

# --- Welcome page ---
cat > "$DOCS/index.md" <<'EOF'
# Welcome

**Ariadne** is a governed-metrics platform that lets autonomous agents query
business data through a compile-gated SQL engine with mandatory human
admission.

**Lumio** is a portable Knowledge Base SDK with Git-native authoring,
reviewed publication, and optional retrieval.

Together they provide the **shared workspace** — a single-server deployment
where contributors submit content and data through a managed boundary,
humans review and approve in the browser, and results stay governed.

## Quick links

- [Ariadne getting started](ariadne/tutorials/getting-started.md)
- [Lumio quickstart](lumio/tutorials/quickstart.md)
- [Pi agent workflow (Ariadne)](ariadne/how-to/pi-agent-workflow.md)
- [Pi agent guide (Lumio workspace)](lumio/how-to/howto-pi-agent.md)
- [How Ariadne works](ariadne/explanations/how-ariadne-works.md)

## Current releases

| Package | Version |
|---------|---------|
| ariadne-data | 0.8.0 |
| lumio-wiki | 0.6.0 |
| lumio-lancedb | 0.6.0 |

See [Lumio release notes](lumio/reference/release-notes/v0.6.0.md) and
[bound-release pairings](integration/reference/lumio-bound-releases.md).
EOF

# --- Ariadne docs ---
mkdir -p "$DOCS/ariadne/"{tutorials,how-to,reference,explanations}

cp ../products/ariadne/docs/tutorials/getting-started.md "$DOCS/ariadne/tutorials/"

for f in ../products/ariadne/docs/how-to/*.md; do
  cp "$f" "$DOCS/ariadne/how-to/"
done

for f in ../products/ariadne/docs/reference/*.md; do
  cp "$f" "$DOCS/ariadne/reference/"
done

for f in ../products/ariadne/docs/explanations/*.md; do
  cp "$f" "$DOCS/ariadne/explanations/"
done

# --- Lumio docs ---
mkdir -p "$DOCS/lumio/"{tutorials,how-to,reference/release-notes}

cp ../products/lumio/docs/quickstart.md "$DOCS/lumio/tutorials/"

for f in ../products/lumio/docs/howto-*.md; do
  cp "$f" "$DOCS/lumio/how-to/"
done

for f in usage.md kb-format.md ariadne-context.md packaging.md; do
  cp "../products/lumio/docs/$f" "$DOCS/lumio/reference/"
done

for f in ../products/lumio/docs/release-notes/*.md; do
  cp "$f" "$DOCS/lumio/reference/release-notes/"
done

# --- Integration docs ---
mkdir -p "$DOCS/integration/"{tutorials,reference,how-to}

cp ../integration/docs/tutorials/lumio-ariadne-local.md "$DOCS/integration/tutorials/"
cp ../integration/docs/reference/lumio-bound-releases.md "$DOCS/integration/reference/"
cp ../integration/docs/how-to/lumio-git-local.md "$DOCS/integration/how-to/"

# --- Rewrite cross-references between the three sections ---
# The source files use relative paths like ../products/lumio/docs/quickstart.md
# which don't work in the assembled structure. Rewrite to the new layout.
python3 - <<'PY'
import re
from pathlib import Path

docs = Path("docs")
rewrites = [
    # Old cross-product paths -> new site-relative paths
    (r'\.\./\.\./products/lumio/docs/quickstart\.md', 'lumio/tutorials/quickstart.md'),
    (r'\.\./\.\./products/lumio/docs/usage\.md', 'lumio/reference/usage.md'),
    (r'\.\./\.\./products/lumio/docs/kb-format\.md', 'lumio/reference/kb-format.md'),
    (r'\.\./\.\./products/lumio/docs/packaging\.md', 'lumio/reference/packaging.md'),
    (r'\.\./\.\./products/lumio/docs/ariadne-context\.md', 'lumio/reference/ariadne-context.md'),
    (r'\.\./\.\./products/lumio/docs/release-notes/', 'lumio/reference/release-notes/'),
    (r'\.\./\.\./products/ariadne/docs/', 'ariadne/'),
    (r'\.\./\.\./integration/docs/', 'integration/'),
    # Same-product relative paths that shift due to the new directory depth
    (r'\.\./how-to/', '../how-to/'),
    (r'\.\./reference/', '../reference/'),
    (r'\.\./explanations/', '../explanations/'),
    (r'\.\./tutorials/', '../tutorials/'),
]

count = 0
for md in docs.rglob('*.md'):
    s = md.read_text()
    orig = s
    for old, new in rewrites:
        s = re.sub(old, new, s)
    if s != orig:
        md.write_text(s)
        count += 1

print(f"Rewrote links in {count} files")
PY

echo "Docs assembled in $DOCS/"

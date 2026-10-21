"""Issue #97: the standalone ingestion -> distill -> propose -> validate ->
review -> publish -> discard journey runs from ``lumio_wiki`` alone.

Proven in a fresh subprocess that installs a meta-path finder blocking the
heavyweight optional dependencies forbidden to the base wheel by ADR-0010
(LanceDB, PyArrow, Stario, Piccolo, OpenAI, LiteParse, MarkItDown) AND the
full ``lumio`` application package (equivalent to an environment with only
``lumio-wiki`` installed), then drives the full model-free text/Markdown
ingestion journey through the package's public interfaces. Asserts the journey
succeeds AND that none of those libraries nor ``lumio`` were ever imported.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "lumio" / "fixtures" / "valid"

# Authored Compiled Page Markdown the host coding agent would produce. Defined
# here in the parent (no escaping issues) and passed to the child via a temp
# file.
MARKDOWN = """---
title: "Isolation Page"
aliases: []
tags:
  - "isolation"
summary: "Authored without any model or document converter."
lifecycle: "draft"
visibility: "internal"
sources:
  - id: "iso"
    title: "Isolation source"
synthetic: false
---

# Isolation Page

Body authored by the host agent.
"""

_CHILD = textwrap.dedent(
    """
    import importlib.abc, shutil, sys, tempfile
    from pathlib import Path

    FIXTURES = Path(sys.argv[1])
    MARKDOWN_PATH = Path(sys.argv[2])

    class _Blocker(importlib.abc.MetaPathFinder):
        # Heavyweight optional dependencies the base wheel must NOT need, plus
        # the full ``lumio`` application: ``lumio-wiki`` stands alone. The full
        # forbidden set is dictated by ADR-0010 (LanceDB, PyArrow, Stario,
        # Piccolo, OpenAI, LiteParse, MarkItDown) plus the ``lumio`` app.
        _BLOCKED = {
            "lancedb",
            "pyarrow",
            "stario",
            "piccolo",
            "openai",
            "liteparse",
            "markitdown",
            "lumio",
        }

        def find_spec(self, name, path, target=None):
            if name.split(".")[0] in self._BLOCKED:
                raise ImportError(f"blocked for isolation test: {name}")
            return None

    sys.meta_path.insert(0, _Blocker())

    import subprocess
    from lumio_wiki import load_knowledge_base
    from lumio_wiki.cli import main
    from lumio_wiki.git_authoring import preview_publication, publish_revision

    root = Path(tempfile.mkdtemp()) / "kb"
    shutil.copytree(FIXTURES, root)
    (root / ".lumio-authoring.yaml").write_text(
        "version: 1\\nnamespace: isolation-kb\\nsources: {}\\nbindings: {}\\n"
    )
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test Author")
    git("add", "-A")
    git("commit", "-qm", "baseline")
    assert main(["ingest", str(root), str(MARKDOWN_PATH)]) == 0
    assert (root / "isolation_page.md").exists()
    assert not (root / ".lumio").exists()
    kb, report = load_knowledge_base(root)
    assert report.is_valid, report
    git("add", "-A")
    git("commit", "-qm", "authored page")
    revision = git("rev-parse", "HEAD")
    destination = root.parent / "published"
    review = preview_publication(root, revision, destination, "none")
    assert not destination.exists()
    publish_revision(root, revision, destination, "none", review.review_digest)
    assert load_knowledge_base(destination)[1].is_valid

    for blocked in (
        "lancedb",
        "pyarrow",
        "stario",
        "piccolo",
        "openai",
        "liteparse",
        "markitdown",
        "lumio",
    ):
        assert blocked not in sys.modules, f"{blocked} was imported"

    print("ISOLATION_OK")
    """
)


def test_standalone_ingest_journey_runs_from_lumio_wiki_without_optionals(tmp_path):
    markdown_path = tmp_path / "iso.md"
    markdown_path.write_text(MARKDOWN, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-c", _CHILD, str(FIXTURES), str(markdown_path)],
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    assert result.returncode == 0, (
        f"child failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    assert "ISOLATION_OK" in result.stdout
    assert "ImportError" not in result.stderr

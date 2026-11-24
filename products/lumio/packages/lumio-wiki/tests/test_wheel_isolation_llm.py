"""Issue #101, AC6: the ``[llm]`` and ``[all]`` ingestion capabilities verified
from isolated built-wheel installations using a FAKE provider.

These tests are the authoritative proof that:

- the ``[llm]`` extra installs the OpenAI-compatible provider dependency and a
  smoke ingest → staged proposal succeeds with a FAKE provider (AC2, AC6) —
  never a real API call;
- the ``[all]`` extra installs both document and unattended-provider
  capabilities WITHOUT adding LanceDB / PyArrow (AC5).

The base-wheel half of the proof — AC1 (``openai`` is not importable until
the ``[llm]`` extra is installed) and AC4 (unattended distillation from the
base install fails actionably, naming the exact extra; PRD user story 18) —
runs in ``test_wheel_isolation.py`` against its base venv instead of a second
identical one (issue #140).

The fake provider is injected by monkeypatching ``OpenAIDistiller`` so the
test never constructs a real OpenAI client and never makes a network call.
Building and installing wheels into fresh venvs is expensive, so the whole
module is marked ``slow`` and only runs when the workspace is available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Building and installing into fresh venvs is expensive; skip under the
# standard fast suite unless explicitly requested or running from the repo
# root (where the workspace is available). venvs and installs go through uv
# only (owner decision, epic #139): without uv the module skips, no pip
# fallback.
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is required to build and install"),
]


def _build_wheel(wheel_dir: Path) -> Path:
    """Build the lumio-wiki wheel into ``wheel_dir`` and return its path."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = Path(__file__).parents[3]
    cmd = ["uv", "build", "--package", "lumio-wiki", "--wheel", "--out-dir", str(wheel_dir)]
    subprocess.run(cmd, cwd=str(workspace_root), check=True, capture_output=True)
    wheels = list(wheel_dir.glob("lumio_wiki-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def _create_isolated_venv(venv_dir: Path) -> Path:
    """Create a fresh venv with the runner's interpreter (no pip); return its python."""
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv_dir)], check=True, capture_output=True
    )
    if os.name == "nt":  # pragma: no cover
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _uv_pip(python: Path, *args: str) -> subprocess.CompletedProcess:
    """Install requirements into the venv behind ``python`` with ``uv pip install``."""
    return subprocess.run(
        ["uv", "pip", "install", "--python", str(python), *args],
        check=True,
        capture_output=True,
        text=True,
    )


# The distilled page a fake provider returns. It carries the routing/durability
# fields a provider-distilled page is expected to declare.
_FAKE_PROVIDER_MARKDOWN = (
    "---\n"
    'id: "entity:llm-wheel-page"\n'
    'title: "LLM Wheel Page"\n'
    "entity_types:\n"
    "  - page\n"
    "aliases: []\n"
    "tags:\n"
    '  - "llm"\n'
    'summary: "Distilled by the fake provider in the isolated wheel test."\n'
    'category: "concepts"\n'
    'type: "definition"\n'
    'durability_rationale: "Durable concept distilled for the wheel test."\n'
    'lifecycle: "draft"\n'
    'visibility: "internal"\n'
    "sources:\n"
    '  - id: "llm"\n'
    '    title: "Fake provider source"\n'
    "---\n\n"
    "# LLM Wheel Page\n\n"
    "Body distilled by the fake provider.\n"
)

# A tiny Python script that monkeypatches ``OpenAIDistiller`` with a fake
# client and then drives ``ingest --distiller llm`` through the CLI. Written
# to a temp file and run by the isolated interpreter so the in-process fake
# never touches the network.
_FAKE_DISTILLER_DRIVER = """
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import lumio_wiki
from lumio_wiki import cli

# argv: [script, fake_markdown, kb_root, source_file]
FAKE_MARKDOWN = sys.argv[1]
KB_ROOT = sys.argv[2]
SOURCE_FILE = sys.argv[3]

def _make_fake_distiller():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=FAKE_MARKDOWN))]
    )
    return lumio_wiki.OpenAIDistiller(model="fake-model", client=client)

# Patch the CLI's distiller factory so --distiller llm uses the fake client.
real_build = cli._build_distiller
def _fake_build(args):
    if getattr(args, "distiller", None) == "llm":
        return _make_fake_distiller()
    return real_build(args)
cli._build_distiller = _fake_build

rc = cli.main(["ingest", KB_ROOT, SOURCE_FILE, "--distiller", "llm"])
sys.exit(rc)
"""


@pytest.fixture(scope="module")
def llm_wheel_env(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """Build the wheel once and install it with the ``[llm]`` extra into a
    fresh venv. The base install is ``isolated_wheel_env`` in
    ``test_wheel_isolation.py``; its base-wheel tests live there."""
    wheel_dir = tmp_path_factory.mktemp("wheels")
    wheel_path = _build_wheel(wheel_dir)

    llm_venv = tmp_path_factory.mktemp("llm_venv")
    llm_python = _create_isolated_venv(llm_venv)
    # Install the wheel WITH the [llm] extra so ``openai`` is present.
    _uv_pip(llm_python, str(wheel_path) + "[llm]")
    _uv_pip(llm_python, "msgpack>=1.0", "msgspec[yaml]>=0.21.1")

    return {
        "wheel": wheel_path,
        "llm_python": llm_python,
    }


def test_llm_extra_installs_openai(llm_wheel_env: dict):
    """AC1: the ``[llm]`` extra installs the OpenAI-compatible provider dependency."""
    python = llm_wheel_env["llm_python"]
    result = subprocess.run(
        [str(python), "-c", "import openai; print('openai', openai.__version__)"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"openai must be importable with [llm]:\n{result.stderr}"
    assert "openai" in result.stdout


def test_llm_extra_smoke_ingest_with_fake_provider(llm_wheel_env: dict, tmp_path: Path):
    """Installed [llm] prepares a valid native worktree edit using a fake provider."""
    python = llm_wheel_env["llm_python"]
    bin_dir = python.parent
    script = bin_dir / ("lumio-wiki.exe" if os.name == "nt" else "lumio-wiki")
    kb_root = tmp_path / "kb"
    subprocess.run([str(script), "init", str(kb_root)], check=True, capture_output=True)
    # A version-2 Knowledge Base requires the Entity contract (ADR-0021): the
    # Maintainer declares the ``page`` Entity Type in the control file's
    # ontology, and the distilled page declares a stable ``entity:<slug>`` id.
    control_file = kb_root / "lumio.yaml"
    control_file.write_text(
        control_file.read_text(encoding="utf-8").replace(
            "  entity_types:\n  predicates:",
            "  entity_types:\n    page: {}\n  predicates:",
        ),
        encoding="utf-8",
    )
    source = tmp_path / "source.txt"
    source.write_text("some source text for the fake provider", encoding="utf-8")
    metadata_before = {
        p.relative_to(kb_root): p.read_bytes() if p.is_file() else None
        for p in (kb_root / ".lumio").rglob("*")
    }

    subprocess.run(["git", "-C", str(kb_root), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(kb_root), "config", "user.email", "test@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(kb_root), "config", "user.name", "Test Author"], check=True)
    subprocess.run(["git", "-C", str(kb_root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(kb_root), "commit", "-qm", "baseline"], check=True)
    driver = tmp_path / "drive_fake_distiller.py"
    driver.write_text(_FAKE_DISTILLER_DRIVER, encoding="utf-8")

    result = subprocess.run(
        [
            str(python),
            str(driver),
            _FAKE_PROVIDER_MARKDOWN,
            str(kb_root),
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"fake-provider ingest failed:\n{result.stderr}"
    assert not (kb_root / ".lumio" / "ingest").exists()
    assert {
        p.relative_to(kb_root): p.read_bytes() if p.is_file() else None
        for p in (kb_root / ".lumio").rglob("*")
    } == metadata_before
    assert "converted_by:   text" in result.stdout
    page_text = (kb_root / "concepts" / "llm_wheel_page.md").read_text()
    import msgspec

    metadata = msgspec.yaml.decode(page_text.split("---", 2)[1].encode())
    assert metadata["title"] == "LLM Wheel Page"
    assert metadata["id"] == "entity:llm-wheel-page"
    assert metadata["entity_types"] == ["page"]
    assert metadata["sources"] == [{"id": "llm", "title": "Fake provider source"}]
    assert "Body distilled by the fake provider." in page_text

    result = subprocess.run([str(script), "validate", str(kb_root)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_all_extra_installs_documents_and_llm_without_lancedb(
    tmp_path_factory: pytest.TempPathFactory,
):
    """AC5: the ``[all]`` extra installs documents + llm WITHOUT LanceDB/PyArrow."""
    wheel_dir = tmp_path_factory.mktemp("all_wheels")
    wheel_path = _build_wheel(wheel_dir)
    all_venv = tmp_path_factory.mktemp("all_venv")
    python = _create_isolated_venv(all_venv)
    _uv_pip(python, str(wheel_path) + "[all]")
    _uv_pip(python, "msgpack>=1.0", "msgspec[yaml]>=0.21.1")

    # The [all] extra brings in the documents deps (liteparse, markitdown) and
    # the llm dep (openai) ...
    result = subprocess.run(
        [str(python), "-c", "import liteparse, markitdown, openai; print('all extras ok')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"[all] must install documents + llm deps:\n{result.stderr}"
    assert "all extras ok" in result.stdout

    # ... but MUST NOT bring in LanceDB or PyArrow.
    for forbidden in ("lancedb", "pyarrow"):
        result = subprocess.run(
            [str(python), "-c", f"import {forbidden}"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"{forbidden} must NOT be importable from lumio-wiki[all] (AC5)"
        )

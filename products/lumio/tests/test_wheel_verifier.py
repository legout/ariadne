from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # make the product scripts/ tree importable
    sys.path.insert(0, str(ROOT))

from scripts.verify_lumio_wiki_wheel import _python_roots  # noqa: E402


def test_python_roots_includes_packages_top_level_modules_and_extensions(
    tmp_path: Path,
):
    wheel = tmp_path / "example.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("package/__init__.py", "")
        archive.writestr("native_package/_speedups.cpython-314-x86_64-linux-gnu.so", "")
        archive.writestr("module.py", "")
        archive.writestr("extension.cpython-314-x86_64-linux-gnu.so", "")
        archive.writestr("windows_extension.cp314-win_amd64.pyd", "")
        archive.writestr("example-1.0.dist-info/metadata.py", "")
        archive.writestr("example-1.0.data/scripts/helper.py", "")

    assert _python_roots(wheel) == {
        "extension",
        "module",
        "native_package",
        "package",
        "windows_extension",
    }


def test_python_roots_includes_relocated_purelib_and_platlib_modules(
    tmp_path: Path,
):
    wheel = tmp_path / "example.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example-1.0.data/purelib/pure_package/__init__.py", "")
        archive.writestr("example-1.0.data/purelib/pure_module.py", "")
        archive.writestr(
            "example-1.0.data/platlib/platform_extension.cp314-win_amd64.pyd",
            "",
        )
        archive.writestr("example-1.0.data/scripts/helper.py", "")
        archive.writestr("example-1.0.data/headers/generated.py", "")
        archive.writestr("example-1.0.data/data/templates/example.py", "")

    assert _python_roots(wheel) == {
        "platform_extension",
        "pure_module",
        "pure_package",
    }


def test_workspace_dependency_boundary_tracks_approved_metadata(monkeypatch):
    import runpy
    from types import SimpleNamespace

    import pytest

    verifier = runpy.run_path(
        str(ROOT / "packages/lumio-workspace/scripts/verify_workspace_wheel.py")
    )
    boundary = verifier["assert_dependency_boundary"]
    requirements = [
        "authlib<2,>=1.6",
        "httpx<1,>=0.28",
        "itsdangerous<3,>=2.2",
        "lumio-wiki[documents,mcp,s3]<0.8,>=0.7",
        "mcp<3,>=2.2",
        "starlette<2,>=1.7",
        "uvicorn<1,>=0.54",
        'ariadne-data[spreadsheets]<0.9.0,>=0.8.0; extra == "analytics"',
        'lumio-lancedb<0.7.0,>=0.6.0; extra == "retrieval"',
    ]
    installed = [SimpleNamespace(metadata={"Name": "lumio-workspace"})]
    metadata = verifier["importlib"].metadata
    monkeypatch.setattr(metadata, "requires", lambda name: requirements)
    monkeypatch.setattr(metadata, "distributions", lambda: installed)
    util = verifier["importlib"].util
    real_find_spec = util.find_spec
    monkeypatch.setattr(
        util,
        "find_spec",
        lambda name: (
            None if name in {"ariadne", "duckdb", "sqlglot", "pyarrow"} else real_find_spec(name)
        ),
    )
    boundary()
    requirements.append('unexpected>=1; extra == "unreviewed"')
    with pytest.raises(AssertionError):
        boundary()
    requirements.pop()
    for name in ("ariadne-data", "lumio-lancedb"):
        installed.append(SimpleNamespace(metadata={"Name": name}))
        with pytest.raises(AssertionError):
            boundary()
        installed.pop()

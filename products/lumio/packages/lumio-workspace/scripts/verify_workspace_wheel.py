"""Packaging verification for the built lumio-workspace wheel (issue #98, W6).

This is a PACKAGING check, not a behavioral suite: it binds one candidate
archive to the source tree and the actual installation, proves the service
templates ship in the wheel, pins the base dependency set against
optional-dependency leakage (Core must stay behind the ``analytics`` extra),
and proves the analytics boundary stays lazy in a Core-less environment.
Behavioral service coverage lives in the member test tree and the documented
shared-workspace journey.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

# Distributions that must never ride along in the base service environment:
# the Ariadne producer (plus its heavyweight runtime) is gated behind the
# ``analytics`` extra, and the LanceDB adapter is not a service dependency.
FORBIDDEN_DISTRIBUTIONS = {
    "ariadne-data",
    "ariadne",
    "duckdb",
    "sqlglot",
    "pyarrow",
    "lumio-lancedb",
    "openai",
    "stario",
    "piccolo",
}
FORBIDDEN_MODULES = {"ariadne", "duckdb", "sqlglot", "pyarrow"}

EXPECTED_BASE_REQUIREMENTS = sorted(
    [
        "authlib<2,>=1.6",
        "httpx<1,>=0.28",
        "itsdangerous<3,>=2.2",
        "lumio-wiki[documents,mcp]<0.7.0,>=0.6.0",
        "mcp<3,>=2.2",
        "starlette<2,>=1.7",
        "uvicorn<1,>=0.54",
    ]
)
EXPECTED_ANALYTICS_REQUIREMENTS = ["ariadne-data[spreadsheets]<0.8.0,>=0.7.0"]

# The hatch force-include assets: losing either template breaks the owner
# setup and browser review surfaces even though imports still succeed.
REQUIRED_TEMPLATES = (
    "lumio_workspace/templates/setup.html",
    "lumio_workspace/templates/review.html",
)


def _python_roots(wheel: Path) -> set[str]:
    roots: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            parts = name.split("/")
            if parts[0].endswith(".data"):
                if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
                    continue
                name = "/".join(parts[2:])
            root, separator, _ = name.partition("/")
            if root.endswith(".dist-info"):
                continue
            if not name.endswith((".py", ".so", ".pyd")):
                continue
            roots.add(root if separator else root.split(".", 1)[0])
    return roots


def assert_installed_wheel(wheel: Path) -> None:
    """Bind a candidate archive to source members and the actual installation."""
    wheel = wheel.resolve()
    name = wheel.name.split("-", 1)[0].replace("_", "-")
    root = name.replace("-", "_")
    distribution = importlib.metadata.distribution(name)
    installed_root = Path(str(distribution.locate_file(root))).resolve()
    assert installed_root.is_relative_to(Path(sys.prefix).resolve()), installed_root
    module = importlib.import_module(root)
    assert module.__file__ is not None, root
    assert Path(module.__file__).resolve() == installed_root / "__init__.py"
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    # Index installs omit origin metadata; member bytes still bind the artifact.
    direct: dict[str, Any] = {}
    direct_text = distribution.read_text("direct_url.json")
    if direct_text is not None:
        try:
            parsed = json.loads(direct_text)
        except ValueError as exc:
            raise AssertionError(f"malformed direct_url.json: {direct_text!r}") from exc
        assert isinstance(parsed, dict), parsed
        direct = parsed
    if direct_text is not None:
        assert direct.get("url") == wheel.as_uri() and "dir_info" not in direct, direct
    archive_info = direct.get("archive_info", {})
    hashes = archive_info.get("hashes", {})
    if "sha256" in hashes:
        assert hashes["sha256"] == digest, direct
    legacy_hash = archive_info.get("hash", "")
    if legacy_hash.startswith("sha256="):
        assert legacy_hash == f"sha256={digest}", direct
    source = Path(__file__).resolve().parents[1] / "src"
    members = {}
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.namelist():
            if member.startswith(f"{root}/") and not member.endswith("/"):
                raw = archive.read(member)
                assert (source / member).read_bytes() == raw, f"stale source member: {member}"
                assert Path(str(distribution.locate_file(member))).read_bytes() == raw, member
                members[member] = hashlib.sha256(raw).hexdigest()
        metadata = next(p for p in archive.namelist() if p.endswith(".dist-info/METADATA"))
        installed_metadata = distribution.read_text("METADATA")
        assert installed_metadata is not None, "METADATA missing from the installation"
        assert installed_metadata.encode() == archive.read(metadata)
    assert members
    for template in REQUIRED_TEMPLATES:
        assert template in members, f"service template missing from the wheel: {template}"
    print(
        "wheel_identity:",
        json.dumps(
            {
                "wheel": str(wheel),
                "sha256": digest,
                "distribution": name,
                "installed_root": str(installed_root),
                "members": members,
            },
            sort_keys=True,
        ),
    )


def assert_dependency_boundary() -> None:
    """Pin the base dependency set and the analytics-only Core gate."""
    requirements = importlib.metadata.requires("lumio-workspace") or []
    base: list[str] = []
    extras: dict[str, list[str]] = {}
    for requirement in requirements:
        if ";" not in requirement:
            base.append(requirement.replace(" ", "").lower())
            continue
        spec, marker = requirement.split(";", 1)
        assert marker.strip().startswith("extra =="), requirement
        extra = marker.split("==", 1)[1].strip().strip("'\"").lower()
        extras.setdefault(extra, []).append(spec.replace(" ", "").lower())
    assert sorted(base) == EXPECTED_BASE_REQUIREMENTS, base
    assert extras == {"analytics": EXPECTED_ANALYTICS_REQUIREMENTS}, extras
    assert all(importlib.util.find_spec(name) is None for name in FORBIDDEN_MODULES)
    installed = {
        distribution.metadata["Name"].lower().replace("_", "-")
        for distribution in importlib.metadata.distributions()
    }
    assert "lumio-workspace" in installed
    assert installed.isdisjoint(FORBIDDEN_DISTRIBUTIONS), sorted(
        installed & FORBIDDEN_DISTRIBUTIONS
    )


def assert_analytics_stays_optional() -> None:
    """The service module imports without Core; the adapter must not sneak in."""
    import lumio_workspace.app  # noqa: F401 -- import itself is the check

    try:
        importlib.import_module("lumio_workspace.analytics")
    except ImportError:
        pass
    else:
        raise AssertionError("analytics Core leaked into the base service environment")
    imported_forbidden = {
        name.split(".", 1)[0] for name in sys.modules if name.split(".", 1)[0] in FORBIDDEN_MODULES
    }
    assert not imported_forbidden, sorted(imported_forbidden)


def _service_entry_point() -> None:
    entry = Path(sys.prefix) / "bin" / "lumio-workspace"
    assert entry.is_file(), f"console entry point missing from the environment: {entry}"
    result = subprocess.run(
        [str(entry), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for command in ("serve", "grant", "revoke", "local-user", "local-membership", "local-token"):
        assert command in result.stdout, f"service entry point lost subcommand {command!r}"


def main() -> int:
    """Verify the candidate workspace wheel as deployed without Core."""
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_workspace_wheel.py WORKSPACE_WHEEL")
    wheel = Path(sys.argv[1])

    assert _python_roots(wheel) == {"lumio_workspace"}
    assert_installed_wheel(wheel)
    assert_dependency_boundary()
    assert_analytics_stays_optional()
    _service_entry_point()
    print("lumio-workspace isolated base wheel verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

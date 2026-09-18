"""``ariadne-skill`` — the packaged agent skill (ADR-0011, spec rev 10 §8.21).

The wheel ships the skill as package data (``ariadne/skill_assets/``:
SKILL.md + the grain-rubric reference), version-locked to the package.
Subcommands:

- ``path``     — print the packaged skill directory.
- ``install``  — copy it to ``~/.agents/skills/ariadne/`` (``--scope user``,
  default) or ``.agents/skills/ariadne/`` (``--scope project``, relative to
  the working directory); ``--agent pi|claude|hermes`` additionally wires the
  agent-specific dir as a SYMLINK to the installed copy (plain copy + note
  where the platform has no symlinks). Idempotent: re-install refreshes.
- ``status``   — hash every managed target against the packaged assets and
  report drift per target (manual edits, tampering, stale versions).

The ``.agents/skills`` convention is the cross-agent location; the
agent-specific dirs only point at it, so one install serves every agent.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "skill_assets"

# Agent-specific dirs per scope: (user, project). pi reads skills from
# ~/.pi/agent/skills (user) or .pi/skills (project); the rest follow their
# own dotdir convention.
AGENT_DIRS: dict[str, tuple[str, str]] = {
    "pi": ("~/.pi/agent/skills/ariadne", ".pi/skills/ariadne"),
    "claude": ("~/.claude/skills/ariadne", ".claude/skills/ariadne"),
    "hermes": ("~/.hermes/skills/ariadne", ".hermes/skills/ariadne"),
}


def _scope_target(scope: str) -> Path:
    """The installed-copy location for a scope (user home or project root)."""
    if scope == "user":
        return Path.home() / ".agents" / "skills" / "ariadne"
    return (Path(".agents") / "skills" / "ariadne").absolute()


def _replace(source: Path, target: Path) -> None:
    """Refresh one target with a fresh copy of ``source`` (never merges)."""
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)


def _dir_hash(root: Path) -> str:
    """Content hash of a directory tree: relpath + file digest, order-stable."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _managed_targets() -> list[Path]:
    """Every target install manages, in reporting order: both scope roots plus
    each agent dir in both scopes."""
    targets = [_scope_target("user"), _scope_target("project")]
    for user, project in AGENT_DIRS.values():
        targets.append(Path(user).expanduser())
        targets.append(Path(project).absolute())
    return targets


def _install(scope: str, agent: str | None) -> int:
    target = _scope_target(scope)
    _replace(ASSETS, target)
    print(f"installed: {target}")
    if agent:
        link = Path(AGENT_DIRS[agent][0 if scope == "user" else 1]).expanduser()
        try:
            if link.is_symlink() or link.is_file():
                link.unlink()
            elif link.exists():
                shutil.rmtree(link)
            link.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target.resolve(), link)
            print(f"linked: {link} -> {target.resolve()}")
        except OSError:  # platform without symlink support: copy + note instead
            _replace(ASSETS, link)
            print(f"copied (symlinks unavailable): {link} — re-run install to refresh")
    return 0


def _status() -> int:
    packaged = _dir_hash(ASSETS)
    for target in _managed_targets():
        if not target.exists() and not target.is_symlink():
            print(f"absent  {target}")
            continue
        actual = target.resolve()
        state = "ok" if _dir_hash(actual) == packaged else "drift"
        note = " (symlink)" if target.is_symlink() else ""
        print(f"{state}{note}  {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ariadne-skill",
        description="Install/status the packaged ariadne agent skill (ADR-0011).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("path", help="print the packaged skill directory")
    install = sub.add_parser("install", help="install the skill (idempotent refresh)")
    install.add_argument("--scope", choices=("user", "project"), default="user")
    install.add_argument("--agent", choices=tuple(sorted(AGENT_DIRS)), default=None)
    sub.add_parser("status", help="report per-target drift against the packaged skill")
    args = parser.parse_args(argv)
    if args.command == "path":
        print(ASSETS)
        return 0
    if args.command == "install":
        return _install(args.scope, args.agent)
    return _status()


if __name__ == "__main__":
    raise SystemExit(main())

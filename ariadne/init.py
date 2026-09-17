"""Project scaffolder (``ariadne-init [TARGET_DIR]``): writes the INPUT files a
fresh ariadne project needs — seed notes, .env.example, .mcp.json, .gitignore,
and an empty ``data/``. It never creates OUTPUTS: the served bundle
(``context_layer/``, ``semantic_layer/``) arrives only via ``ariadne-author`` +
``ariadne-promote`` (spec §6: served artifacts are promoted, never pre-seeded).

Idempotent: an existing file is reported and skipped, never overwritten. A
directory that already holds an ariadne ``pyproject.toml`` (i.e. this repo) is
refused unless ``--force``; so is an unparsable ``pyproject.toml`` (ambiguous
project). Fail closed on symlinks: if any scaffold path under TARGET — or a
parent of it — is a symlink (e.g. ``data`` linked outside TARGET, or a dangling
``.env.example``), nothing is written through the link.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

# Same lines the ariadne repo itself ignores: generated DBs, served layers,
# staging, secrets, build junk.
GITIGNORE = """\
data/*.db
staging/
context_layer/
semantic_layer/
.env
__pycache__/
.venv/
"""

# Same variables ariadne.author loads from ARIADNE_ENV (default .env next to
# the project) — the real file is never committed.
ENV_EXAMPLE = """\
# Live LLM credentials for ariadne-author (secrets: never commit the real .env).
# cp .env.example .env, fill in, and point ARIADNE_ENV at it if it lives elsewhere.
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=
"""

# Facade entry for MCP-capable agents (pi via pi-mcp-adapter, or any MCP client).
# Same shape as the ariadne repo's .mcp.json, minus the worktree-specific cwd.
MCP_JSON = {
    "mcpServers": {
        "ariadne": {
            "command": "ariadne-serve",
            "args": [
                "--db",
                "data/YOURDB.db",
                "--semantic",
                "semantic_layer",
                "--context",
                "context_layer",
            ],
            "lifecycle": "lazy",
            "requestTimeoutMs": 120000,
        }
    }
}

SEED_NOTES = """\
# Seed notes — TODO: name your database

Notes from the data owner: the business documentation that profiling cannot
derive. If a generated metric contradicts a rule here, the metric is wrong,
not the rule.

## What this database is

TODO: one paragraph — domain, time span, rough size.

## Rules you must follow (the gotchas)

1. **Cancelled orders are not revenue.** Example rule, in the owner's voice:
   rows with `status IN ('CANCELLED', 'RETURNED')` are excluded from every
   revenue and margin number. Replace it with YOUR rules — the "why these
   numbers are right" facts no schema scan reveals (status semantics,
   currency cutovers, which table is the fact table, join-key traps).

## Metric definitions

TODO: the metrics you want governed, in plain words, each citing the rule(s)
above that make them right.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ariadne-init",
        description="Scaffold a fresh ariadne project: seed notes, .env.example, "
        ".mcp.json, .gitignore, and an empty data/ (inputs only — the served "
        "layers come from ariadne-author + ariadne-promote).",
    )
    parser.add_argument("target", nargs="?", default=".", help="directory to scaffold (default: .)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="scaffold even if the target already holds an ariadne pyproject.toml",
    )
    args = parser.parse_args(argv)

    target = Path(args.target)
    pyproject = target / "pyproject.toml"
    if not args.force and pyproject.is_file():
        refusal = _project_conflict(pyproject)
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 1

    files = [
        ("data/seed_notes.md", SEED_NOTES),
        (".env.example", ENV_EXAMPLE),
        (".mcp.json", json.dumps(MCP_JSON, indent=2) + "\n"),
        (".gitignore", GITIGNORE),
    ]

    # Fail closed: refuse before any write if a scaffold path, or a parent of it
    # under TARGET, is a symlink (even dangling) — never write through a link.
    for rel in ("data", *(rel for rel, _ in files)):
        offender = _symlink_under(target, rel)
        if offender is not None:
            print(
                f"error: refusing to scaffold through a symlink: {offender} is a "
                f"symlink under {target}; remove it and re-run",
                file=sys.stderr,
            )
            return 1

    target.mkdir(parents=True, exist_ok=True)
    (target / "data").mkdir(exist_ok=True)  # empty: the author builds the DB here
    created = skipped = 0
    for rel, content in files:
        path = target / rel
        if path.exists():  # idempotent: never overwrite, only report
            print(f"  skipped (exists): {path}")
            skipped += 1
            continue
        path.write_text(content, encoding="utf-8")
        print(f"  created: {path}")
        created += 1
    print(
        f"ariadne project ready in {target}: {created} file(s) created, "
        f"{skipped} skipped — next: cp .env.example .env, add credentials, "
        "then ariadne-author --db data/YOURDB.db --notes data/seed_notes.md"
    )
    return 0


def _project_conflict(pyproject: Path) -> str | None:
    """Refusal message for an existing ``pyproject.toml``, or None if safe."""
    try:
        with pyproject.open("rb") as fh:
            manifest = tomllib.load(fh)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return (
            f"error: {pyproject} is not valid TOML; refusing to scaffold an "
            "ambiguous project (fix or remove the file, or use --force to override)"
        )
    project = manifest.get("project")
    name = project.get("name") if isinstance(project, dict) else None
    if name == "ariadne":
        return (
            f"error: {pyproject.parent} already holds an ariadne project ({pyproject}); "
            "refusing to scaffold over it (use --force to override)"
        )
    return None


def _symlink_under(target: Path, rel: str) -> str | None:
    """First symlinked component of ``target/rel`` (from TARGET down), or None.

    ``Path.is_symlink`` (lstat-based) also catches dangling links, which plain
    ``exists()`` misses.
    """
    path = target
    for part in Path(rel).parts:
        path = path / part
        if path.is_symlink():
            return str(path)
    return None


if __name__ == "__main__":
    raise SystemExit(main())

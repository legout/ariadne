"""Project scaffolder (``ariadne-init [TARGET_DIR]``): writes the INPUT files a
fresh ariadne project needs — seed notes, .env.example, .mcp.json, .gitignore,
and an empty ``data/``. It never creates OUTPUTS: the served bundle
(``context_layer/``, ``semantic_layer/``) arrives only via ``ariadne-author`` +
``ariadne-promote`` (spec §6: served artifacts are promoted, never pre-seeded).

Idempotent: an existing file is reported and skipped, never overwritten. A
directory that already holds an ariadne ``pyproject.toml`` (i.e. this repo) is
refused unless ``--force``.
"""

from __future__ import annotations

import argparse
import json
import sys
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
    if (
        not args.force
        and pyproject.is_file()
        and 'name = "ariadne"' in pyproject.read_text(encoding="utf-8", errors="replace")
    ):
        print(
            f"error: {target} already holds an ariadne project ({pyproject}); "
            "refusing to scaffold over it (use --force to override)",
            file=sys.stderr,
        )
        return 1

    target.mkdir(parents=True, exist_ok=True)
    (target / "data").mkdir(exist_ok=True)  # empty: the author builds the DB here
    files = [
        ("data/seed_notes.md", SEED_NOTES),
        (".env.example", ENV_EXAMPLE),
        (".mcp.json", json.dumps(MCP_JSON, indent=2) + "\n"),
        (".gitignore", GITIGNORE),
    ]
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


if __name__ == "__main__":
    raise SystemExit(main())

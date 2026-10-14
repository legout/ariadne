"""Project scaffolder (``ariadne-init [TARGET_DIR]``): writes the INPUT files a
fresh ariadne project needs — seed notes, an AGENTS.md pointer page, .env.example,
.gitignore, and an empty ``data/`` (with ``data/docs/`` for source
documents destined for ``ariadne-ingest``, ADR-0009). It never creates OUTPUTS:
the served bundle (``context_layer/``, ``semantic_layer/``) arrives only via
``ariadne-author`` + ``ariadne-promote`` (spec §6: served artifacts are promoted,
never pre-seeded).

AGENTS.md is deliberately a pointer page (ADR-0011, spec rev 10): project facts,
the directory layout, the promotion-gate rule, and "load the ariadne skill" —
the workflow itself lives in the packaged skill (``ariadne-skill install``),
not duplicated here. ``.mcp.json`` is opt-in (spec 2026-09-23-0001 §7, ADR-0012):
``--with-mcp`` scaffolds the registry-aware config — it points the facade at
``ariadne.yaml``, whose ``sources:`` block is the single source of truth for
what the project serves (ADR-0010). The default scaffold omits it: querying
happens through the local ``ariadne`` CLI, which needs no server, and an
existing ``.mcp.json`` is never removed or overwritten.

Idempotent: an existing file is reported and skipped, never overwritten. A
directory that already holds an ariadne ``pyproject.toml`` (i.e. this repo) is
refused unless ``--force``; so is an unparsable ``pyproject.toml`` (ambiguous
project). Fail closed on symlinks: if any scaffold path under TARGET — or a
parent of it — is a symlink (e.g. ``data`` linked outside TARGET, or a dangling
``.env.example``), nothing is written through the link.

``--git`` (issue #39/G7) scaffolds for the Git authoring workflow: the
artifact layers become TRACKED artifacts (the ignore template drops the
``context_layer/``/``semantic_layer/`` rules and ignores ``.ariadne/``
instead), the pointer page describes the proposal/admission layout and gate,
and still no OUTPUT is pre-seeded — an existing ``.gitignore`` or AGENTS.md is
never overwritten, so adopting Git over a legacy scaffold keeps its rules
while the proposal seams track chosen artifacts explicitly.
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

# The Git-mode scaffold (issue #39/G7, spec 2026-10-02-0009 §7): the served
# artifact layers are TRACKED Git artifacts (the proposal/admission workflow
# owns them), while the operator-owned state dir, pending proposals and
# inputs/secrets stay ignored. The supported INPUT locations under data/ —
# databases, parquet/csv/json/delta datasets, data/docs/ documents — are
# ignored wholesale; ONLY data/seed_notes.md is re-included because it is an
# artifact the proposal seams track through the allowlisted literal-pathspec
# seam (G7 fix pass: ordinary git add must never pick up local data inputs).
# An existing .gitignore is never rewritten — a legacy scaffold's ignore
# rules stay, and the proposal seams track chosen artifacts explicitly
# (git add -f with literal pathspecs) despite them.
GIT_MODE_GITIGNORE = """\
data/*
!data/seed_notes.md
staging/
.env
__pycache__/
.venv/
.ariadne/
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

# Facade entry for MCP-capable agents (pi via pi-mcp-adapter, or any MCP client) —
# OPT-IN only: created by ``ariadne-init --with-mcp`` (spec 2026-09-23-0001 §7);
# the default scaffold omits it because the local ``ariadne`` CLI needs no server.
# Registry-aware (ADR-0010/spec rev 10): --sources names the project's ariadne.yaml
# — its sources: block (declared after init) is what the facade serves. The
# semantic/context paths are the project-root defaults ariadne-promote creates on
# first promotion in a fresh project.
MCP_JSON = {
    "mcpServers": {
        "ariadne": {
            "command": "ariadne-serve",
            "args": [
                "--sources",
                "ariadne.yaml",
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

# Rev 10 (ADR-0011): AGENTS.md shrinks to project facts + the layout table + the
# promotion-gate rule + a pointer to the packaged skill — the workflow prose the
# skill owns is NOT duplicated here (per-project files describe the project;
# the skill describes how to work).
AGENTS_MD = """\
# Ariadne project facts

## What this project is

TODO: one paragraph — what the database is about, who owns it, which questions
the governed metrics answer. The human-owned rules live in `data/seed_notes.md`;
served policy pages cite them.

## The ariadne skill

Load the ariadne skill (`ariadne-skill install` if absent) — it carries the
workflow and the grain rules. This file holds only project facts.

## Layout

| Directory | Role |
| :--- | :--- |
| `data/` | Inputs: the database(s), `data/seed_notes.md`, `data/docs/` source documents. |
| `staging/` | Authoring output awaiting human review — the only place agents write. |
| `context_layer/` | OKF pages: tables, references, policies, metrics, computations (promoted). |
| `semantic_layer/` | Served OSI models: the governed metric definitions (promotion output). |

## Promotion gate

Served artifacts arrive ONLY by human promotion (`ariadne-promote`): agents never
write outside `staging/`, and anything staged with `status: review_needed` refuses
promotion until a human resolves it.
"""

# The Git-mode scaffold's pointer page (issue #39/G7): same project-facts
# contract (ADR-0011), but the layout and the human gate describe the Git
# authoring workflow — tracked artifact layers, operator-owned state, and
# human Git Review Admission instead of staging promotion.
AGENTS_MD_GIT = """\
# Ariadne project facts

## What this project is

TODO: one paragraph — what the database is about, who owns it, which questions
the governed metrics answer. The human-owned rules live in `data/seed_notes.md`;
served policy pages cite them.

## The ariadne skill

Load the ariadne skill (`ariadne-skill install` if absent) — it carries the
workflow and the grain rules. This file holds only project facts.

## Layout

| Directory | Role |
| :--- | :--- |
| `data/` | Inputs: the database(s), `data/seed_notes.md`, `data/docs/` source documents. |
| `semantic_layer/` | OSI models — tracked Git artifacts edited through proposals. |
| `context_layer/` | OKF pages: datasets, tables, references, policies, metrics, computations. |
| `staging/` | Pending ad-hoc/standalone-ingest/example proposals in their own stores. |
| `.ariadne/` | Operator-owned state: proposals, approvals, snapshots (never committed). |

## Admission gate

Served state arrives ONLY by human Git Review Admission (`ariadne-admit`) of an
exact reviewed, validated candidate revision. Agents draft through
`ariadne-authoring` proposals; source approval (`approve-sources`), admission,
legacy migration (`import-legacy`, `enrich-legacy`) and any direct Git/shell/file
mutation are human operations, never agent ones.
"""

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

# ADR-0010 source registry template: all comments — an empty/parsed-absent
# registry counts as absent (commands fall back to --db), so a fresh project
# boots unchanged until the owner declares sources. Credentials are NEVER
# written here: postgres sources name an environment variable (connection_env);
# an inline connection string is a validation error (ADR-0010).
ARIADNE_YAML = """\
# ariadne.yaml — declarative source registry (ADR-0010, spec rev 9 §8.20).
# Uncomment and edit the block below to declare your sources; every command
# (serve/author/validate/profiler) picks this file up automatically — or pass
# --sources explicitly. Each source is addressable as <name>.<table>.
# Paths are relative to this file's directory; globs need an explicit table name.
#
# Named S3 storage profiles (development candidate, not published 0.3.0):
# uncomment to read independently credentialed S3-compatible storages. The
# profile names environment VARIABLES — the executing process supplies the
# values; credentials never live in this file. Explicit non-overlapping
# scopes select the credential; see docs/how-to/multiple-s3-storages.md.
# Only the seven reader types (csv/json/parquet/duckdb/delta/iceberg/ducklake)
# take storage:. Proposal, then human approve-sources, still gate every read.
#
# storages:
#   local:
#     type: s3
#     access_key_id_env: LOCAL_S3_ACCESS_KEY_ID
#     secret_access_key_env: LOCAL_S3_SECRET_ACCESS_KEY
#     endpoint_url_env: LOCAL_S3_ENDPOINT_URL
#     url_style: path
#     scopes:
#       - s3://retail/
#
# sources:
#   - name: demo
#     type: sqlite
#     path: data/YOURDB.db
#   - name: events
#     type: parquet
#     path: data/events/*.parquet
#     table: events              # one view over the whole glob
#   - name: raw_orders
#     type: csv                  # also: json, parquet (local or https:// / s3://)
#     path: data/orders.csv      # view named after the file stem: raw_orders.orders
#   - name: lake
#     type: delta
#     path: data/lake/orders
#   - name: iceberg_catalog
#     type: iceberg
#     path: s3://bucket/warehouse/sales        # with a storages: profile this
#     storage: local                          # needs storage: local + scope
#     table: sales                            # s3://retail/ covering bucket/
#   - name: lake
#     type: ducklake
#     path: ducklake:warehouse.ducklake
#   - name: warehouse
#     type: duckdb              # native DuckDB database, attached read-only
#     path: data/warehouse.duckdb
#   - name: rail                # trusted operator view catalog over https/s3;
#     type: duckdb              # remote catalogs attach READ_ONLY and need
#     path: https://example.com/rail_catalog.duckdb   # the httpfs extension
#     read_only: true
#   - name: pg
#     type: postgres
#     connection_env: ARIADNE_PG_DSN   # the NAME of the env var holding the DSN
#     read_only: true
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ariadne-init",
        description="Scaffold a fresh ariadne project: seed notes, an AGENTS.md "
        "pointer page, a commented ariadne.yaml source registry template, "
        ".env.example, .gitignore, and an empty data/ (inputs only — the served "
        "layers come from ariadne-author + ariadne-promote).",
    )
    parser.add_argument("target", nargs="?", default=".", help="directory to scaffold (default: .)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="scaffold even if the target already holds an ariadne pyproject.toml",
    )
    parser.add_argument(
        "--with-mcp",
        action="store_true",
        help="also scaffold .mcp.json, the registry-aware MCP server config "
        "(optional transport — the local ariadne CLI needs no server)",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="scaffold for the Git authoring workflow: the artifact layers "
        "(context_layer/, semantic_layer/) are TRACKED artifacts while "
        ".ariadne/, staging/ and inputs/secrets stay ignored; existing files "
        "(including an existing .gitignore) are never overwritten",
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
        ("ariadne.yaml", ARIADNE_YAML),
        ("AGENTS.md", AGENTS_MD_GIT if args.git else AGENTS_MD),
        (".env.example", ENV_EXAMPLE),
        (".gitignore", GIT_MODE_GITIGNORE if args.git else GITIGNORE),
    ]
    if args.with_mcp:  # opt-in only (spec §7): the local CLI needs no MCP config
        files.append((".mcp.json", json.dumps(MCP_JSON, indent=2) + "\n"))

    # Fail closed: refuse before any write if a scaffold path, or a parent of it
    # under TARGET, is a symlink (even dangling) — never write through a link.
    for rel in ("data", "data/docs", *(rel for rel, _ in files)):
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
    (target / "data" / "docs").mkdir(parents=True, exist_ok=True)  # ingest inputs (ADR-0009)
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
        + (
            "git init && ariadne-authoring start (Git authoring workflow), "
            if args.git
            else "then ariadne-author --db data/YOURDB.db --notes data/seed_notes.md "
            "(source documents for ariadne-ingest go in data/docs/), "
        )
        + "query with the local ariadne CLI (MCP config: re-run with --with-mcp)"
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

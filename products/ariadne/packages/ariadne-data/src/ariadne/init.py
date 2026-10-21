"""Project scaffolder (``ariadne-init [TARGET_DIR]``): writes the INPUT files a
fresh ariadne project needs — Seed Notes, an AGENTS.md pointer page, inert source
registry and Git-ignore templates. It never creates admitted artifacts or accesses
original source documents:
served artifacts are authored through revision-checked Git proposals and
become queryable only after human Git Review Admission.

AGENTS.md is deliberately a pointer page (ADR-0011, spec rev 10): project facts,
the directory layout, the admission-gate rule, and "load the ariadne skill" —
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

The Git-only scaffold uses the proposal workflow: the
artifact layers become TRACKED artifacts (the ignore template drops the
``context_layer/``/``semantic_layer/`` rules and ignores ``.ariadne/``
instead), the pointer page describes the proposal/admission layout and gate,
and still no OUTPUT is pre-seeded — an existing ``.gitignore`` or AGENTS.md is
never overwritten, while proposal seams track only explicitly selected artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

# Local inputs, secrets and operator state are excluded; authored layers remain tracked.
GITIGNORE = """\
data/*
!data/seed_notes.md
.env
__pycache__/
.venv/
.ariadne/
"""

# Optional document distillation may load credentials from the operator-selected
# ARIADNE_ENV file; the real file is never committed.
ENV_EXAMPLE = """\
# Optional LLM-backed document distillation credentials (never commit real values).
# Point ARIADNE_ENV at this file only when using that optional ingestion path.
# Add private values referenced by ariadne.yaml to your process environment.
# Never commit credentials or copy original source documents into this project.
"""

# MCP is optional. The server is bound to this project and reads the same
# human-admitted Git snapshot as the local CLI.
MCP_JSON = {
    "mcpServers": {
        "ariadne": {
            "command": "ariadne-serve",
            "args": ["--project", "."],
            "lifecycle": "lazy",
            "requestTimeoutMs": 120000,
        }
    }
}

# The project-facts pointer page describes tracked Git artifacts, operator-owned
# state and human Git Review Admission.
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
| `data/` | Private source inputs; originals remain operator-controlled. |
| `semantic_layer/` | OSI models — tracked Git artifacts edited through proposals. |
| `context_layer/` | OKF pages: datasets, tables, references, policies, metrics, computations. |
| `.ariadne/` | Operator-owned state: proposals, approvals, snapshots (never committed). |

## Admission gate

Governed calls use one exact human-admitted Git revision. Agents draft through
`ariadne-authoring`; source permission and Admission remain separate human
decisions. Original documents stay outside the authored artifact snapshot.
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

# ADR-0010 source registry template. A fresh project has no approved sources
# until a human declares and approves the exact candidate identity. Credentials
# are NEVER written here: postgres sources name an environment variable
# (connection_env); an inline connection string is a validation error.
ARIADNE_YAML = """\
# ariadne.yaml — inert source registry (ADR-0010, spec rev 9 §8.20).
# Declare sources through Git Authoring; operators approve the resolved identity
# before the registry is opened. Each source is addressable as <name>.<table>.
# Paths are relative to this file's directory; globs need an explicit table name.
#
# Named S3 storage profiles reference independently credentialed S3-compatible storages. The
# profile names environment VARIABLES — the executing process supplies the
# values; credentials never live in this file. Explicit non-overlapping
# scopes select the credential; see docs/how-to/multiple-s3-storages.md.
# Only the seven reader types (csv/json/parquet/duckdb/delta/iceberg/ducklake)
# take storage:. Human approval gates any source read.
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
#     type: iceberg                 # profile-based s3:// path must fall
#     path: s3://retail/warehouse/sales   # inside local's scope s3://retail/
#     storage: local
#     table: sales
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
        description=(
            "Scaffold a fresh Git-authoring project without initializing Git "
            "or granting source access."
        ),
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
        ("AGENTS.md", AGENTS_MD_GIT),
        (".env.example", ENV_EXAMPLE),
        (".gitignore", GITIGNORE),
    ]
    if args.with_mcp:  # opt-in only (spec §7): the local CLI needs no MCP config
        files.append((".mcp.json", json.dumps(MCP_JSON, indent=2) + "\n"))

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
    (target / "data").mkdir(exist_ok=True)  # local inputs are ignored by the project template
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
        f"{skipped} skipped — next: initialize Git yourself, then use "
        "ariadne-authoring start; source permission and Admission remain "
        "separate human decisions (MCP config: re-run with --with-mcp)"
    )
    return 0


def _project_conflict(pyproject: Path) -> str | None:
    """Refusal message for an existing ``pyproject.toml``, or None if safe."""
    try:
        with pyproject.open("rb") as fh:
            manifest = tomllib.load(fh)
    except OSError, UnicodeDecodeError, tomllib.TOMLDecodeError:
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

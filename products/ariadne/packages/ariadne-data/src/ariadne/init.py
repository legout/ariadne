"""Project scaffolder (``ariadne-init TARGET``): creates ONE native Lumio
Knowledge Base under the project's ``knowledge/`` subtree through the SDK's
public confirmed empty-setup contract (spec0035 §2, ADR-0029) plus the Core
input files the fresh project needs — the inert source registry, AGENTS.md
pointer page, Git-ignore and env templates. It never creates admitted
artifacts, initializes Git, publishes, or accesses original source documents:
authored layers arrive through revision-checked Git proposals and become
queryable only after human Git Review Admission.

The KB creation is the SDK's own digest-bound preview → recheck → guarded
apply path (``plan_empty_setup``/``recheck_plan``/``apply_plan``): explicit
namespace and private-profile selection are REQUIRED, a nonempty or existing
KB target is refused before any write (never adopted or reinitialized), and
Core supplies only its own declared configuration-write callbacks — no agent
skill install, no automatic Git initialization (the target must already be a
registered Git worktree; ``discover_authoring_location`` refuses otherwise
with fresh-setup guidance). After apply, the Control File gains Core's
declared page vocabulary (categories + the supported ariadne profile Entity
Types) through the public Control File contract, so a fresh project accepts
native page batches immediately (never a second KB file format).

Idempotency contract: an existing managed KB is never reinitialized (the
SDK's adoption guard refuses the second run); an existing Core input file is
reported and skipped, never overwritten. A directory that already holds an
ariadne ``pyproject.toml`` is refused unless ``--force``; so is an unparsable
``pyproject.toml`` (ambiguous project), and a retired standalone
``context_layer/`` project without a ``knowledge/`` KB refuses with
fresh-setup guidance (spec0035 §6: no silent conversion or reset). Fail
closed on symlinks: if any scaffold path under TARGET — or a parent of it —
is a symlink, nothing is written through the link.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from ariadne.proposals import refuse_unsupported_project

# Local inputs, secrets and operator state are excluded; the knowledge/ KB and
# authored layers remain tracked.
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
# Private environment values referenced by ariadne.yaml (never commit real values).
# Documents are onboarded through the native Lumio intake (spec0035); the optional
# [documents] converter extra serves the bounded Seed-Notes document parts only.
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

# The project-facts pointer page describes the native knowledge KB, tracked
# Core artifacts, operator-owned state and human Git Review Admission
# (spec0035 §2: one content and authoring path).
AGENTS_MD_GIT = """\
# Ariadne project facts

## What this project is

TODO: one paragraph — what the database is about, who owns it, which questions
the governed metrics answer. The human-owned rules live in `data/seed_notes.md`;
knowledge pages cite them.

## The ariadne skill

Load the ariadne skill (`ariadne-skill install` if absent) — it carries the
workflow and the grain rules. This file holds only project facts.

## Layout

| Directory | Role |
| :--- | :--- |
| `knowledge/` | The Lumio Knowledge Base — one native authoring path. |
| `data/` | Private source inputs; originals remain operator-controlled. |
| `semantic_layer/` | OSI models — tracked Git artifacts edited through proposals. |
| `.ariadne/` | Operator-owned state: proposals, approvals, snapshots (never committed). |

Knowledge pages cover datasets, tables, references, policies, metrics and
guides; technical facts and curated explanations share the same KB.

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

# The supported ariadne profile Entity Types (spec0029 §1.5 SUPPORT["profiles"],
# plus the table kinds the managed journey documents): the KB-local vocabulary
# Core's native pages declare. Predicates stay KB-local Maintainer content and
# are NOT seeded — a project declares claims vocabulary deliberately.
_ARIADNE_ENTITY_TYPES = (
    "metric",
    "policy",
    "reference",
    "dataset",
    "table",
    "computation",
    "answer-example",
)

# Core's own KB categories beyond the SDK's seeded catalog: the page kinds of
# the ariadne knowledge path (spec0035 §2).
_CORE_CATEGORIES = ("metrics", "policies", "computations", "answer-examples")


def _core_control_file():  # noqa: PLR0911 - none; single return path
    """Core's declared Control File: the SDK seed plus Core's categories and
    Entity Type vocabulary, validated through the public proposed-Control
    contract BEFORE anything is written (never a second KB file format)."""
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        EntityTypeDefinition,
        Ontology,
        extend_control_file_categories,
        seeded_control_file,
        validate_proposed_control_file,
    )

    control = extend_control_file_categories(seeded_control_file(), _CORE_CATEGORIES)
    control = control.__class__(
        version=control.version,
        categories=control.categories,
        hot_index=control.hot_index,
        ontology=Ontology(
            entity_types={
                name: EntityTypeDefinition(description=f"Ariadne {name} knowledge page.")
                for name in _ARIADNE_ENTITY_TYPES
            },
            predicates=control.ontology.predicates,
            redirects=control.ontology.redirects,
        ),
    )
    issues = validate_proposed_control_file(control)
    blocking = [issue for issue in issues if issue.severity != "warning"]
    if blocking:  # pragma: no cover - the declared vocabulary is valid by contract
        raise ValueError(
            "the declared Ariadne Control File vocabulary failed validation: "
            + "; ".join(issue.message for issue in blocking)
        )
    return control


def _default_private_locations(namespace: str) -> tuple[Path, Path]:
    """Core's default private registry/store roots for a NEW profile (always
    under the machine home, never inside any content repository)."""
    home = Path.home()
    return home / ".ariadne" / "registries" / namespace, home / ".ariadne" / "artifacts" / namespace


def _new_profile_payload(namespace: str) -> str:
    """The declaration for a NEW private profile (spec 0010 §2.1 shape):
    required retention, machine-local registry and artifact store."""
    registry, store = _default_private_locations(namespace)
    payload = {
        "schema_version": 1,
        "namespace": namespace,
        "source_registry": str(registry.expanduser().resolve()),
        "retention": "required",
        "artifact_store": {"kind": "local", "root": str(store.expanduser().resolve())},
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ariadne-init",
        description=(
            "Create a fresh Git-authoring project: one native Lumio Knowledge "
            "Base (knowledge/) plus the Core input files. Explicit namespace "
            "and private-profile selection are required; Git, admission and "
            "source access stay separate human steps."
        ),
    )
    parser.add_argument("target", nargs="?", default=".", help="directory to scaffold (default: .)")
    parser.add_argument(
        "--namespace",
        required=True,
        help="explicit Knowledge Base namespace (stable identity, e.g. "
        "urn:uuid:...); never generated or taken from an unrelated profile",
    )
    parser.add_argument(
        "--private-profile",
        required=True,
        type=Path,
        help="machine-local private source profile file (must live OUTSIDE "
        "the repository); created from Core defaults when absent",
    )
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

    target = Path(args.target).resolve()
    pyproject = target / "pyproject.toml"
    if not args.force and pyproject.is_file():
        refusal = _project_conflict(pyproject)
        if refusal is not None:
            print(refusal, file=sys.stderr)
            return 1

    # spec0035 §6: a retired standalone project refuses BEFORE any mutation,
    # with fresh-setup guidance — never a reset or conversion.
    try:
        refuse_unsupported_project(target)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not args.namespace.strip():
        print(
            "error: --namespace must be an explicit non-empty namespace "
            "(spec 0010 §2.2)",
            file=sys.stderr,
        )
        return 1
    namespace = args.namespace.strip()

    files = [
        ("data/seed_notes.md", SEED_NOTES),
        ("ariadne.yaml", ARIADNE_YAML),
        (".env.example", ENV_EXAMPLE),
        (".gitignore", GITIGNORE),
    ]
    if args.with_mcp:  # opt-in only (spec §7): the local CLI needs no MCP config
        files.append((".mcp.json", json.dumps(MCP_JSON, indent=2) + "\n"))

    # Fail closed: refuse before any write if a scaffold path, a callback
    # destination, or a parent of it under TARGET, is a symlink (even
    # dangling) — never write through a link.
    for rel in ("data", "knowledge", ".env", "AGENTS.md", *(rel for rel, _ in files)):
        offender = _symlink_under(target, rel)
        if offender is not None:
            print(
                f"error: refusing to scaffold through a symlink: {offender} is a "
                f"symlink under {target}; remove it and re-run",
                file=sys.stderr,
            )
            return 1

    kb_target = target / "knowledge"
    profile_path = args.private_profile
    new_payload = None if profile_path.is_file() else _new_profile_payload(namespace)

    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        EmptySetupError,
        apply_plan,
        plan_empty_setup,
        recheck_plan,
    )
    from lumio_wiki.private_profile import (  # pyright: ignore[reportMissingImports]
        PrivateProfileError,
    )

    # The SDK's digest-bound plan validates every selection and the target
    # (absent/empty KB target only) BEFORE any byte is written — an occupied
    # or adopted target refuses here with the SDK's own recovery guidance.
    try:
        plan = plan_empty_setup(
            target=kb_target,
            namespace=namespace,
            profile_path=profile_path,
            new_profile_payload=new_payload,
            submission={"mode": "commit", "remote": None, "branch": None},
            project_dir=target,
            agents_enabled=True,
            env_bytes=f"LUMIO_KB_PATH={kb_target}\n".encode(),
            agents_bytes=AGENTS_MD_GIT.encode(),
            skill=None,  # Core installs no agent skill implicitly
        )
        # The guarded apply is authorized by this one explicit command in one
        # process: the digest-bound recheck refuses any drift before apply.
        recheck_plan(
            plan,
            env_bytes=f"LUMIO_KB_PATH={kb_target}\n".encode(),
            agents_bytes=AGENTS_MD_GIT.encode(),
            skill=None,
        )
    except (EmptySetupError, PrivateProfileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # The no-overwrite contract covers the SDK apply callbacks exactly like
    # the plain scaffold files: an existing operator AGENTS.md/.env refuses
    # the WHOLE scaffold before any write (checked here so the KB-exists
    # refusal keeps precedence on a re-run; plan/recheck never write).
    for rel in (".env", "AGENTS.md"):
        occupied = target / rel
        if occupied.exists() or occupied.is_symlink():
            print(
                f"error: refusing to scaffold: {occupied} already exists — setup "
                "never overwrites existing operator files; move or remove it "
                "(or choose a different target) and re-run. Nothing was written.",
                file=sys.stderr,
            )
            return 1

    def _write_env() -> None:
        destination = target / ".env"
        if destination.exists() or destination.is_symlink():  # appeared mid-apply
            raise EmptySetupError(
                f"{destination} appeared during setup — nothing is overwritten; "
                "inspect it and re-run the preview",
                code="setup_target_changed",
            )
        destination.write_text(plan.env_bytes.decode("utf-8"), encoding="utf-8")

    def _write_agents() -> None:
        destination = target / "AGENTS.md"
        if destination.exists() or destination.is_symlink():  # appeared mid-apply
            raise EmptySetupError(
                f"{destination} appeared during setup — nothing is overwritten; "
                "inspect it and re-run the preview",
                code="setup_target_changed",
            )
        destination.write_bytes(plan.agents_bytes)

    try:
        apply_plan(plan, write_env=_write_env, write_agents=_write_agents, install_skill=None)
    except EmptySetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Core's declared page vocabulary rides the same uncommitted scaffold
    # transaction through the public Control File contract.
    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        write_control_file,
    )

    write_control_file(kb_target, _core_control_file())

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
        f"ariadne project ready in {target}: knowledge/ Knowledge Base "
        f"(namespace {namespace}) plus {created} input file(s) created, "
        f"{skipped} skipped — next: stage and commit the created files with "
        "native Git, then use ariadne-authoring start; source permission and "
        "Admission remain separate human decisions (MCP config: re-run with "
        "--with-mcp)"
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

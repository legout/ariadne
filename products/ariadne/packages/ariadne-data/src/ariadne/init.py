"""Project scaffolder (``ariadne-init TARGET``): creates ONE native Lumio
Knowledge Base under the project's ``knowledge/`` subtree through the SDK's
public confirmed empty-setup contract plus the Core
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
            "command": "ariadne",
            "args": ["serve", "--project", "."],
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

Load the ariadne skill (`ariadne skill install` if absent) — it carries the
workflow and the grain rules. This file holds only project facts.

## Layout

| Directory | Role |
| :--- | :--- |
| `knowledge/` | The Lumio Knowledge Base — one native authoring path. |
| `data/` | Private source inputs; originals remain operator-controlled. |
| `semantic_layer/` | OSI models — tracked Git artifacts edited in the one active draft. |
| `.ariadne/` | Operator-owned state: the draft, source grants, snapshots (never committed). |

Knowledge pages cover datasets, tables, references, policies, metrics and
guides; technical facts and curated explanations share the same KB.

## Admission gate

Governed calls use one exact human-approved Git revision. Agents draft with
`ariadne draft edit` and the `authoring_*` MCP tools and may run `ariadne validate`,
`ariadne diff` and `ariadne draft status`; only the human runs `ariadne approve`
(sources first, then the calculation). Original documents stay outside the authored
artifact snapshot.
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
# the ariadne knowledge path.
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
    assert control.ontology is not None  # the seeded Control File always carries its ontology
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


def _scaffold_files(with_mcp: bool) -> list[tuple[str, str]]:
    files = [
        ("data/seed_notes.md", SEED_NOTES),
        ("ariadne.yaml", ARIADNE_YAML),
        (".env.example", ENV_EXAMPLE),
        (".gitignore", GITIGNORE),
    ]
    if with_mcp:  # opt-in only: the local CLI needs no MCP config
        files.append((".mcp.json", json.dumps(MCP_JSON, indent=2) + "\n"))
    return files


def preflight_targets(target: Path, *, with_mcp: bool = False) -> list[str]:
    """Check EVERY file init would create BEFORE anything is written (spec 0040 §3.2.4):
    an existing target with different content — or a symlink, or any file the SDK writes
    (``.env``, ``AGENTS.md``) — refuses and is named. Identical content is allowed (it is
    skipped); unrelated files are never examined. Returns the targets that already match."""
    matching: list[str] = []
    for rel, content in _scaffold_files(with_mcp):
        path = target / rel
        offender = _symlink_under(target, rel)
        if offender is not None:
            raise ValueError(
                f"init refuses: {offender} is a symlink under {target} — remove it and re-run"
            )
        if path.exists():
            if path.read_text(encoding="utf-8", errors="replace") != content:
                raise ValueError(
                    f"init refuses: {rel} already exists with different content — init never "
                    "overwrites it; move it aside or merge it by hand and re-run. "
                    "Nothing was written."
                )
            matching.append(rel)
    for rel in (".env", "AGENTS.md", "data", "knowledge"):
        offender = _symlink_under(target, rel)
        if offender is not None:
            raise ValueError(
                f"init refuses: {offender} is a symlink under {target} — remove it and re-run"
            )
    for rel in (".env", "AGENTS.md"):
        if (target / rel).exists():
            raise ValueError(
                f"init refuses: {rel} already exists — init never overwrites operator files; "
                "move it aside and re-run. Nothing was written."
            )
    return matching


def _scaffold(
    target: Path, namespace: str, profile_path: Path, *, force: bool = False, with_mcp: bool = False
) -> list[str]:
    """Create the native Lumio KB and the Core input files (the private scaffold of
    ``init_project``). Raises ``ValueError`` BEFORE any write for every refusal; returns the
    relative paths it created."""
    pyproject = target / "pyproject.toml"
    if not force and pyproject.is_file():
        refusal = _project_conflict(pyproject)
        if refusal is not None:
            raise ValueError(refusal.removeprefix("error: "))
    # a retired standalone project refuses BEFORE any mutation, with fresh-setup guidance
    refuse_unsupported_project(target)
    if not namespace.strip():
        raise ValueError("a non-empty namespace is required (spec 0010 §2.2)")
    namespace = namespace.strip()
    matching = preflight_targets(target, with_mcp=with_mcp)

    kb_target = target / "knowledge"
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
        recheck_plan(
            plan,
            env_bytes=f"LUMIO_KB_PATH={kb_target}\n".encode(),
            agents_bytes=AGENTS_MD_GIT.encode(),
            skill=None,
        )
    except (EmptySetupError, PrivateProfileError) as exc:
        raise ValueError(str(exc)) from exc

    def _write_env() -> None:
        destination = target / ".env"
        if destination.exists() or destination.is_symlink():  # appeared mid-apply
            raise EmptySetupError(
                f"{destination} appeared during setup — nothing is overwritten",
                code="setup_target_changed",
            )
        destination.write_text(plan.env_bytes.decode("utf-8"), encoding="utf-8")

    def _write_agents() -> None:
        destination = target / "AGENTS.md"
        if destination.exists() or destination.is_symlink():  # appeared mid-apply
            raise EmptySetupError(
                f"{destination} appeared during setup — nothing is overwritten",
                code="setup_target_changed",
            )
        assert plan.agents_bytes is not None  # agents_enabled=True above
        destination.write_bytes(plan.agents_bytes)

    try:
        sdk_created = apply_plan(
            plan, write_env=_write_env, write_agents=_write_agents, install_skill=None
        )
    except EmptySetupError as exc:
        raise ValueError(str(exc)) from exc

    from lumio_wiki import (  # pyright: ignore[reportMissingImports] — SDK now mandatory
        write_control_file,
    )

    write_control_file(kb_target, _core_control_file())
    (target / "data").mkdir(exist_ok=True)  # local inputs are ignored by the project template
    created = [  # the SDK's own files, as it reports them (directories and outside paths dropped)
        Path(p).relative_to(target).as_posix()
        for p in sdk_created
        if Path(p).is_file() and Path(p).is_relative_to(target)
    ]
    for rel, content in _scaffold_files(with_mcp):
        if rel in matching:
            continue  # byte-identical: nothing to write
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(rel)
    return created


# ---------------------------------------------------------------- `ariadne init`

SELECTOR_YAML = """\
version: 1
mode: integrated
subtree: knowledge
namespace: {namespace}
profile: ariadne-context/1
support_revision: {revision}
policy_bindings:
  version: 1
  bindings: []
"""


def _git(target: Path, *argv: str, check: bool = True) -> str:
    from ariadne import proposals

    return proposals._git(list(argv), target, check=check).stdout


def ensure_git(target: Path, *, assume_yes: bool, stdin, stdout, prompt=None) -> None:
    """Create the repository if absent and make sure a Git identity resolves; with no
    identity prompt once and set a repository-LOCAL identity (spec 0040 §3.2.1)."""
    from ariadne import proposals

    target.mkdir(parents=True, exist_ok=True)
    top = proposals._git(["rev-parse", "--show-toplevel"], target, check=False)
    if top.returncode != 0:
        _git(target, "init", "-q")
    elif Path(top.stdout.strip()).resolve() != target.resolve():
        raise ValueError(
            f"{target} is inside the Git repository {top.stdout.strip()}; run init at its top level"
        )
    import os

    if os.environ.get("GIT_AUTHOR_NAME") and os.environ.get("GIT_AUTHOR_EMAIL"):
        return
    missing = [
        k
        for k in ("user.name", "user.email")
        if not _git(target, "config", "--get", k, check=False).strip()
    ]
    if not missing:
        return
    if assume_yes or not (stdin.isatty() and stdout.isatty()):
        raise ValueError(
            "no Git identity resolves; set one with:\n"
            f"  git -C {target} config user.name '<your name>'\n"
            f"  git -C {target} config user.email '<you@example.org>'"
        )
    for key in missing:
        out = prompt or stdout  # the consent check above stays on the ORIGINAL streams
        out.write(f"Git {key}: ")
        out.flush()
        value = stdin.readline().strip()
        if not value:
            raise ValueError(f"no value for {key}; nothing was changed")
        _git(target, "config", key, value)


def init_project(
    target: str | Path, *, assume_yes: bool = False, stdin=None, stdout=None, prompt=None
) -> dict:
    """``ariadne init [DIR]`` (spec 0040 §3.2): repository, identity, namespace, the
    private profile pair, the selector at the highest support_revision and the native
    Lumio KB, as ONE commit holding only the files init created. A re-run on an
    initialized project validates it and changes nothing; a conflicting existing file
    refuses before any write."""
    from ariadne import lumio_context, profile_pair, proposals

    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    target = Path(target).resolve()
    if (target / "context_integration.yaml").is_file():
        return _revalidate(target)
    conflicts = [
        rel
        for rel in ("context_integration.yaml", "knowledge", "ariadne.yaml", "data/seed_notes.md")
        if (target / rel).exists() or (target / rel).is_symlink()
    ]
    if conflicts:
        raise ValueError(
            f"init refuses: {', '.join(conflicts)} already exist(s) without a complete "
            "Ariadne project — move or remove them; nothing was written"
        )
    # EVERY target file is checked before anything (repository, profile, files) is created
    preflight_targets(target)
    record_path = target / profile_pair.RECORD_REL
    if record_path.exists() or record_path.is_symlink():  # a dangling link counts
        raise ValueError(
            f"init refuses: {profile_pair.RECORD_REL} already records a private profile for "
            "this directory without a complete project — it is never replaced silently; "
            "inspect or remove it and re-run. Nothing was written."
        )
    ensure_git(target, assume_yes=assume_yes, stdin=stdin, stdout=stdout, prompt=prompt)
    # the user's index and working tree stay untouched except for init's own files
    staged_before = _git(target, "diff", "--cached", "--name-only").split()
    identifier = profile_pair.new_identifier()
    namespace = f"urn:uuid:{identifier}"
    lumio_profile = profile_pair.config_dir() / f"{identifier}.json"
    sibling = profile_pair.sibling_path(lumio_profile)
    revision = max(lumio_context.IMPLEMENTED_PROFILE_REVISIONS)
    created = _scaffold(target, namespace, lumio_profile)
    (target / "context_integration.yaml").write_text(
        SELECTOR_YAML.format(namespace=namespace, revision=revision), encoding="utf-8"
    )
    profile_pair.write_private(
        sibling,
        json.dumps(profile_pair.default_sibling(identifier), indent=2, sort_keys=True) + "\n",
    )
    profile_pair.record(target, lumio_profile, sibling)
    created += ["context_integration.yaml"]  # the record lives in .ariadne/, never committed
    tracked = sorted(rel for rel in created if not rel.startswith(".ariadne/"))
    ignored = [
        rel
        for rel in tracked
        if proposals._git(["check-ignore", "-q", "--", rel], target, check=False).returncode == 0
    ]
    tracked = [rel for rel in tracked if rel not in ignored]
    literal = [proposals._literal(rel) for rel in tracked]
    _git(target, "add", "-f", "--", *literal)
    _git(target, "commit", "-q", "-m", "ariadne: init", "--", *literal)
    after = _git(target, "diff", "--cached", "--name-only").split()
    assert sorted(set(after) - set(staged_before)) == []  # nothing else was staged
    return {
        "initialized": True,
        "namespace": namespace,
        "committed": tracked,
        "profile": str(lumio_profile),
    }


def _revalidate(target: Path) -> dict:
    """The no-op re-run: the project must still be a valid managed project."""
    from ariadne import profile_pair, proposals

    proposals.refuse_unsupported_project(target)
    settings = profile_pair.load(target)
    return {
        "initialized": False,
        "message": "already initialized",
        "profile": settings["lumio_profile"],
    }


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

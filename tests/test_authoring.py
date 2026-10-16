"""Operator-owned document inputs and revision-bound source evidence.

Tests use synthetic Git projects and local fixtures. External originals remain
outside authored artifacts; no real source, network or LLM is accessed.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.execution  # noqa: E402
import ariadne.profiler  # noqa: E402
import ariadne.sources  # noqa: E402
from ariadne import (  # noqa: E402 — inputs: the moved evidence seam (#35)
    authoring,
    authoring_inputs,
)
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402

# ---------------------------------------------------------------- fixtures


def write_parquet(path: Path, rows: int = 3) -> Path:
    """A real local parquet file (DuckDB-written) the approved profile reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) t(id, label)) "
        f"TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def scaffold_project(tmp_path: Path, *, seed_notes: str | None = None) -> Path:
    """A synthetic Git project with operator registry and optional Seed Notes."""
    (tmp_path / "ariadne.yaml").write_text(
        "# ariadne.yaml — declarative source registry (ADR-0010).\nretention_days: 90\n",
        encoding="utf-8",
    )
    paths = ["ariadne.yaml"]
    if seed_notes is not None:
        notes = tmp_path / "data" / "seed_notes.md"
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text(seed_notes, encoding="utf-8")
        paths.append("data/seed_notes.md")
    for command in (
        ["init", "-q"],
        ["config", "user.name", "Ariadne Tests"],
        ["config", "user.email", "tests@ariadne.local"],
        ["add", "--", *paths],
        ["commit", "-q", "-m", "human: synthetic project scaffold", "--", *paths],
    ):
        subprocess.run(["git", *command], cwd=tmp_path, check=True, capture_output=True, text=True)
    return tmp_path


@pytest.fixture
def connection_spy(monkeypatch):
    """Record every registry handed to THE connection builder (the single
    chokepoint query/profiler/validate share through ariadne.execution) — the
    canary proving a proposed location is never opened."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    monkeypatch.setattr(ariadne.execution, "build_connection", spy)
    return opened


# ------------------------------------------- slice 2 (issue #14): harness evidence


def test_operator_document_reference_converts_to_stable_identity_evidence(tmp_path, connection_spy):
    """Operator-placed originals stay external while evidence derives from one snapshot."""
    project = scaffold_project(
        tmp_path, seed_notes="# Seed notes\n\nGross revenue excludes churned rows.\n"
    )
    bytes_ = b"# Pricing policy\n\nUSD is the only billing currency.\n"

    docs = project / "data" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    original = docs / "pricing.md"
    original.write_bytes(bytes_)
    digest = hashlib.sha256(bytes_).hexdigest()

    # Referenced conversion: complete text, source identity, no connection opened.
    evidence = authoring.document_evidence("pricing.md", project=project)
    assert evidence["complete"] is True
    assert "USD is the only billing currency" in evidence["text"]
    assert evidence["digest"] == digest
    assert evidence["resource"] == str(original.resolve())
    assert authoring.document_evidence("pricing.md", project=project) == evidence
    assert original.read_bytes() == bytes_
    assert not (project / "data" / "object-store").exists()

    api = AuthoringProject(project)
    started = api.start_proposal()

    # Before source approval: evidence yes, profile no — nothing opened.
    early = api.inputs(started["proposal"], documents=["pricing.md"])
    assert early["profile"] is None
    assert early["documents"][0]["digest"] == digest
    assert early["seed_notes"]["complete"] is True
    assert connection_spy == []  # no proposed location was ever opened

    # After the human approval: the same call now carries the real profile.
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    proposed = api.propose_sources(
        started["proposal"],
        started["candidate_revision"],
        [{"name": "events", "type": "parquet", "path": str(parquet)}],
    )
    api.approve_sources(proposed["proposal"], proposed["revision"], proposed["source_digest"])
    inputs = api.inputs(started["proposal"], documents=["pricing.md"])
    (source,) = inputs["profile"]["sources"]
    assert source["name"] == "events"  # the measured, approved source
    assert source["tables"]["events"]["row_count"] == 3
    assert inputs["documents"][0] == evidence
    assert "churned rows" in inputs["seed_notes"]["text"]
    assert connection_spy == [[str(parquet)]]  # exactly one open: the approved source


def test_reference_escaping_the_input_area_is_refused(tmp_path):
    """The document-input boundary: a reference that leaves the
    operator-configured input area — by traversal or by absolute path — is
    refused before anything is read, even when the target file really exists."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    (docs / "inside.md").write_text("# Inside\n", encoding="utf-8")
    secret = project / "secret.md"  # a real file OUTSIDE the input area
    secret.write_text("server-side secret", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes"):
        authoring.document_evidence("../secret.md", project=project)
    with pytest.raises(ValueError, match="escapes"):
        authoring.document_evidence(str(secret), project=project)

    # The input area itself still works; the refusals read nothing of the target.
    assert authoring.document_evidence("inside.md", project=project)["complete"]


def test_unapproved_object_reference_is_refused_before_any_fetch(tmp_path, monkeypatch):
    """A remote URI reference the operator has NOT approved in the project
    config is refused before any network or file I/O — no fetch seam runs, for
    an unapproved s3 URI or any other scheme (owner decision 2026-09-24)."""
    project = scaffold_project(tmp_path)
    fetched: list[str] = []
    monkeypatch.setattr(
        authoring_inputs, "_fetch_object_bytes", lambda uri: fetched.append(uri) or b"x"
    )
    for reference in (
        "s3://ariadne-docs/policies/secret.md",
        "https://cdn.example.com/doc.md",
        "https://ro:s3cret@cdn.example.com/doc.md",  # no credential-in-URL policy exists
    ):
        with pytest.raises(ValueError, match="not approved"):
            authoring.document_evidence(reference, project=project)
    assert fetched == []  # nothing fetched, nothing retained
    assert not (project / "data" / "object-store").exists()


def test_approved_object_reference_fetches_each_read_without_retention(tmp_path, monkeypatch):
    """Approved object URIs are fetched per read; Core retains no original copy."""
    project = scaffold_project(tmp_path)
    approved = "s3://ariadne-docs/policies/pricing.md"
    (project / "ariadne.yaml").write_text(
        f"retention_days: 90\ndocuments:\n  object_store:\n    - {approved}\n",
        encoding="utf-8",
    )
    fetched: list[str] = []
    payload = b"# Pricing policy\n\nUSD is the only billing currency.\n"

    def fake_fetch(uri):
        fetched.append(uri)
        return payload

    monkeypatch.setattr(authoring_inputs, "_fetch_object_bytes", fake_fetch)

    evidence = authoring.document_evidence(approved, project=project)
    assert evidence["resource"] == approved  # the exact approved URI, not a local path
    assert evidence["title"] == "pricing.md"
    assert evidence["digest"] == hashlib.sha256(payload).hexdigest()
    assert "USD is the only billing currency" in evidence["text"]
    assert evidence["complete"] is True
    assert fetched == [approved]  # fetched exactly once, server-side seam

    assert not (project / "data" / "object-store").exists()

    # Repeat calls fetch the still-approved URI again and preserve its identity.
    assert authoring.document_evidence(approved, project=project) == evidence
    assert fetched == [approved, approved]


def test_object_store_config_is_validated_by_the_registry_rules(tmp_path):
    """The human-managed config itself is shape-checked: a credentialed s3 URI
    (ADR-0010 inline-credential rule), a non-s3 scheme, and a bucket-only URI
    are refused as config errors before any reference is served."""
    project = scaffold_project(tmp_path)
    for bad, why in (
        ("s3://AKIA:s3cret@ariadne-docs/policy.md", "ADR-0010"),
        ("https://cdn.example.com/policy.md", "only s3"),
        ("s3://ariadne-docs", "exact"),
    ):
        (project / "ariadne.yaml").write_text(
            f"documents:\n  object_store:\n    - {bad}\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match=why):
            authoring.document_evidence("pricing.md", project=project)  # loads config


def test_local_input_roots_come_from_the_project_config(tmp_path):
    """Allowed local input roots are operator-configured in ariadne.yaml
    (documents.roots); the default project keeps the scaffolded data/docs root,
    and an explicitly configured root set is exactly what references may read."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"  # default root, no documents key
    docs.mkdir(parents=True)
    (docs / "inside.md").write_text("# Inside\n", encoding="utf-8")
    assert "Inside" in authoring.document_evidence("inside.md", project=project)["text"]

    (project / "ariadne.yaml").write_text(
        "documents:\n  roots:\n    - data/specs\n", encoding="utf-8"
    )
    specs = project / "data" / "specs"
    specs.mkdir(parents=True)
    (specs / "rule.md").write_text("# Configured root rule\n", encoding="utf-8")
    evidence = authoring.document_evidence("rule.md", project=project)  # root-relative
    assert "Configured root rule" in evidence["text"]
    # The former default root is no longer readable: a root-relative miss is an
    # honest no-document, and traversal into it from the configured root escapes.
    with pytest.raises(ValueError, match="no readable document"):
        authoring.document_evidence("inside.md", project=project)
    with pytest.raises(ValueError, match="escapes"):
        authoring.document_evidence("../docs/inside.md", project=project)


def test_fetch_object_bytes_uses_duckdb_read_blob(tmp_path):
    """The retrieval transport itself: DuckDB 1.5.5 read_blob returns exact
    bytes for one exact reference. Verified against the LOCAL filesystem only;
    live S3 access is UNVERIFIED in this lane (no real provider credentials)."""
    doc = tmp_path / "transport.md"
    data = b"# transport check\n"
    doc.write_bytes(data)
    assert authoring._fetch_object_bytes(str(doc)) == data


@pytest.mark.parametrize("dangling", [False, True], ids=["existing", "dangling"])
def test_document_reference_refuses_symlinks_outside_the_input_root(tmp_path, dangling):
    """Local document reads refuse outside/dangling symlinks before opening a target."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    secret = project / "server-secret.txt"
    secret.write_text("server-side secret", encoding="utf-8")
    target = project / "absent.txt" if dangling else secret
    (docs / "pricing.md").symlink_to(target)

    with pytest.raises(ValueError, match="escapes"):
        authoring.document_evidence("pricing.md", project=project)

    if dangling:
        assert not (project / "absent.txt").exists()  # nothing written outside the root
    assert secret.read_text() == "server-side secret"  # the existing file untouched


def test_proposal_inputs_bound_the_document_batch(tmp_path):
    """The documents batch is explicitly bounded against repeated conversion."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# a\n", encoding="utf-8")
    api = AuthoringProject(project)
    started = api.start_proposal()
    limit = authoring.MAX_DOCUMENTS_PER_CALL

    ok = api.inputs(started["proposal"], documents=["a.md"] * limit)
    assert len(ok["documents"]) == limit

    with pytest.raises(ValueError, match="bound"):
        api.inputs(started["proposal"], documents=["a.md"] * (limit + 1))


def test_document_evidence_digest_and_text_come_from_one_stable_snapshot(tmp_path, monkeypatch):
    """A file replaced between the digest read and the conversion read must
    never yield evidence whose digest describes different bytes than its text:
    both come from one stable snapshot (review finding: concurrent replacement)."""
    project = scaffold_project(tmp_path)
    doc = project / "data" / "docs" / "raced.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# original policy\n", encoding="utf-8")
    original_bytes = doc.read_bytes()

    real_convert = authoring_inputs._convert_snapshot

    def convert_then_replace(data, suffix, *, display):
        text = real_convert(data, suffix, display=display)
        doc.write_text("# replaced mid-flight\n", encoding="utf-8")
        return text

    monkeypatch.setattr(authoring_inputs, "_convert_snapshot", convert_then_replace)
    evidence = authoring.document_evidence("raced.md", project=project)
    assert evidence["text"].startswith("# original policy")
    assert evidence["digest"] == hashlib.sha256(original_bytes).hexdigest()


def test_seed_notes_input_is_bound_to_the_candidate_revision(tmp_path):
    """Seed Notes text/digest come from the selected immutable Git revision."""
    original = "# original seed notes\n"
    project = scaffold_project(tmp_path, seed_notes=original)
    api = AuthoringProject(project)
    started = api.start_proposal()

    inputs = api.inputs(started["proposal"])
    assert inputs["seed_notes"]["text"] == original
    assert inputs["seed_notes"]["digest"] == hashlib.sha256(original.encode()).hexdigest()

    # A mutable project-root edit cannot change evidence for the selected commit.
    (project / "data" / "seed_notes.md").write_text("# replaced seed notes\n", encoding="utf-8")
    after = api.inputs(started["proposal"])
    assert after["revision"] == started["candidate_revision"]
    assert after["seed_notes"] == inputs["seed_notes"]


def test_long_document_evidence_is_bounded_and_never_claimed_complete(tmp_path):
    """Converted text arrives in bounded parts: every partial part reports
    complete: false with the total part count, parts retrieve consistently, and
    the identity stays the digest of the ORIGINAL bytes."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    text = "# Long notes\n\n" + ("renewal policy " * 3000)  # > one bounded part
    doc = docs / "long.md"
    doc.write_text(text, encoding="utf-8")
    bound = authoring.EVIDENCE_PART_CHARS

    first = authoring.document_evidence("long.md", project=project)
    assert first["parts"] == -(-len(text) // bound)  # ceil, one bound per part
    assert first["part"] == 1 and first["complete"] is False
    assert first["text"] == text[:bound]

    last = authoring.document_evidence("long.md", project=project, part=first["parts"])
    assert last["text"] == text[(first["parts"] - 1) * bound :]
    assert last["complete"] is False
    assert last["digest"] == first["digest"] == hashlib.sha256(doc.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="out of range"):
        authoring.document_evidence("long.md", project=project, part=first["parts"] + 1)


# ------------------------------------------------------------------- CLI (inputs)


def test_cli_inputs_returns_documents_and_optional_pieces(tmp_path, capsys):
    """The spec-named ``inputs`` command: one JSON value — document evidence,
    profile only once sources are approved, and Seed Notes only when present."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    (docs / "policy.md").write_text("# Policy\n", encoding="utf-8")

    proposal = AuthoringProject(project).start_proposal()
    assert (
        authoring_cli(
            [
                "inputs",
                "--proposal",
                proposal["proposal"],
                "--document",
                "policy.md",
                "--project",
                str(project),
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["profile"] is None  # nothing approved yet: no profile, no opening
    assert out["documents"][0]["complete"] and "Policy" in out["documents"][0]["text"]
    assert out["seed_notes"] is None  # absent Seed Notes stay absent

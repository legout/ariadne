"""Harness-led authoring, slice 1 (issue #13; spec 2026-09-24-0005 §Evidence
and source-access boundary, ADR-0013).

Public-seam tests over ``ariadne.authoring`` and ``ariadne.authoring_cli``:
a proposed registry entry is inert data until a digest-matched, human-operated
``approve-sources`` installs it into the project's ``ariadne.yaml`` — and only
then does it become profileable through the same shared connection
(``ariadne.sources.build_connection``) every existing command uses. The canary
in the first test spies on that one chokepoint to prove no proposed location is
ever opened before approval. No network, no LLM.
"""

import errno
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.profiler  # noqa: E402
import ariadne.sources  # noqa: E402
from ariadne import authoring  # noqa: E402
from ariadne.authoring_cli import main as authoring_cli  # noqa: E402
from ariadne.promote import main as promote_main  # noqa: E402
from ariadne.promote import promote_bundle  # noqa: E402

# ---------------------------------------------------------------- fixtures


def write_parquet(path: Path, rows: int = 3) -> Path:
    """A real local parquet file (DuckDB-written) the approved profile reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1, 'a'), (2, 'b'), (3, 'c')) t(id, label)) "
        f"TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def scaffold_project(tmp_path: Path) -> Path:
    """A fresh ariadne project: the commented ariadne.yaml template plus one
    unrelated real config key that approval must preserve."""
    (tmp_path / "ariadne.yaml").write_text(
        "# ariadne.yaml — declarative source registry (ADR-0010).\n"
        "# Sources arrive only via ariadne-authoring approve-sources (issue #13).\n"
        f"retention_days: {90}\n",
        encoding="utf-8",
    )
    return tmp_path


def write_proposal(tmp_path: Path, sources: list[dict], name: str = "proposed.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"sources": sources}, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def connection_spy(monkeypatch):
    """Record every registry handed to THE connection builder (the single
    chokepoint serve/author/validate/profiler all share) — the canary proving a
    proposed location is never opened."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    monkeypatch.setattr(ariadne.profiler, "build_connection", spy)
    return opened


# ------------------------------------------------------ the red/green seam


def test_proposed_source_is_inert_until_digest_matched_approval(
    tmp_path, monkeypatch, connection_spy
):
    """Issue #13 seam: propose -> (nothing opened) -> wrong digest refused ->
    matching digest installs exactly the approved entries, preserving unrelated
    config -> the source profiles through the same connection as every
    existing command."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    proposal = write_proposal(
        tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]
    )
    monkeypatch.chdir(project)

    # Propose: shape-checked, stored inert, digest reported — nothing opened.
    result = authoring.propose_sources(proposal, project=project)
    assert result["sources"][0]["path"] == str(parquet)  # the precise location
    digest = result["digest"]
    assert len(digest) == 64
    assert connection_spy == []
    stored = yaml.safe_load(
        (project / "staging" / "authoring" / "source-proposal.yaml").read_text(encoding="utf-8")
    )
    assert stored["digest"] == digest
    assert stored["sources"] == [{"name": "events", "type": "parquet", "path": str(parquet)}]

    # Before approval the project registry still holds no sources: the only
    # profile path there is refuses to open anything.
    with pytest.raises(ValueError, match="no 'sources:' entries"):
        ariadne.profiler.profile(sources_path=project / "ariadne.yaml")
    assert connection_spy == []  # the proposed parquet was never handed to DuckDB

    # A wrong digest approves nothing.
    with pytest.raises(ValueError, match="[Dd]igest"):
        authoring.approve_sources("0" * 64, project=project)
    registry_doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert "sources" not in registry_doc  # untouched
    assert connection_spy == []

    # The matching digest installs exactly the approved entries.
    installed = authoring.approve_sources(digest, project=project)
    assert installed["sources"] == [{"name": "events", "type": "parquet", "path": str(parquet)}]
    registry_doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert registry_doc["retention_days"] == 90  # unrelated config preserved
    assert registry_doc["sources"] == [{"name": "events", "type": "parquet", "path": str(parquet)}]

    # Only now does the source profile — through the same shared connection.
    profile = ariadne.profiler.profile(sources_path=project / "ariadne.yaml")
    assert connection_spy == [[str(parquet)]]  # the approved path, once
    (source,) = profile["sources"]
    assert source["name"] == "events"
    assert source["tables"]["events"]["row_count"] == 3


def test_stale_digest_after_re_proposal_is_refused(tmp_path, connection_spy):
    """A re-proposed (changed) pending proposal invalidates the earlier digest:
    the operator's approval binds the exact content, not the slot."""
    project = scaffold_project(tmp_path)
    first = write_parquet(tmp_path / "a.parquet")
    second = write_parquet(tmp_path / "b.parquet")
    stale = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(first)}]),
        project=project,
    )["digest"]
    current = authoring.propose_sources(
        write_proposal(
            tmp_path,
            [{"name": "events", "type": "parquet", "path": str(second)}],
            name="proposed-2.yaml",
        ),
        project=project,
    )["digest"]
    assert stale != current
    with pytest.raises(ValueError, match="[Dd]igest"):
        authoring.approve_sources(stale, project=project)
    assert "sources" not in yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert connection_spy == []


def test_credential_shaped_proposal_is_rejected_inertly(tmp_path, connection_spy):
    """The registry's ADR-0010 credential rules apply verbatim to proposals:
    an inline connection string never becomes a pending proposal."""
    project = scaffold_project(tmp_path)
    proposal = write_proposal(
        tmp_path,
        [{"name": "pg", "type": "postgres", "connection": "postgresql://u:p@h/db"}],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        authoring.propose_sources(proposal, project=project)
    assert not (project / "staging" / "authoring" / "source-proposal.yaml").exists()
    assert connection_spy == []


def test_relative_proposal_paths_bind_to_the_project_registry(tmp_path, connection_spy):
    """A relative path in a proposal means the same thing before and after
    approval: relative to the project's ariadne.yaml directory, never to the
    intake file's directory — the displayed location is the precise one the
    operator approves and the profiler opens (spec rev2 §1)."""
    intake = tmp_path / "intake"
    intake.mkdir()
    project = tmp_path / "proj"
    project.mkdir()
    scaffold_project(project)
    parquet = write_parquet(project / "data" / "events.parquet")
    write_parquet(intake / "data" / "events.parquet")  # same-named decoy under intake/
    proposal = write_proposal(
        intake, [{"name": "events", "type": "parquet", "path": "data/events.parquet"}]
    )
    result = authoring.propose_sources(proposal, project=project)
    assert result["sources"][0]["path"] == str(parquet)  # project-relative, not intake-relative
    stored = yaml.safe_load(
        (project / "staging" / "authoring" / "source-proposal.yaml").read_text(encoding="utf-8")
    )
    assert stored["sources"][0]["path"] == str(parquet)

    authoring.approve_sources(result["digest"], project=project)
    registry_doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert registry_doc["sources"][0]["path"] == str(parquet)
    profile = ariadne.profiler.profile(sources_path=project / "ariadne.yaml")
    assert connection_spy == [[str(parquet)]]  # the approved dataset, not the intake decoy
    assert profile["sources"][0]["tables"]["events"]["row_count"] == 3


@pytest.mark.parametrize(
    "url",
    [
        "https://ro:s3cret@cdn.example.com/events.parquet",
        "https://:s3cret@cdn.example.com/events.parquet",
    ],
)
def test_credentialed_url_proposal_is_rejected_inertly(tmp_path, connection_spy, url):
    """A URL with password-bearing userinfo is an inline credential
    (spec rev2 §1, ADR-0010): it never becomes a pending proposal."""
    project = scaffold_project(tmp_path)
    proposal = write_proposal(
        tmp_path,
        [{"name": "cdn", "type": "parquet", "path": url}],
    )
    with pytest.raises(ValueError, match="ADR-0010"):
        authoring.propose_sources(proposal, project=project)
    assert not (project / "staging" / "authoring" / "source-proposal.yaml").exists()
    assert connection_spy == []


def test_approval_never_overwrites_existing_sources(tmp_path, connection_spy):
    """Installing a name that already exists in ariadne.yaml fails whole —
    existing registry entries and unrelated config are never overwritten."""
    project = tmp_path
    parquet = write_parquet(tmp_path / "events.parquet")
    (project / "ariadne.yaml").write_text(
        yaml.safe_dump(
            {
                "retention_days": 30,
                "sources": [{"name": "events", "type": "parquet", "path": "keep.parquet"}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    with pytest.raises(ValueError, match="already exist"):
        authoring.approve_sources(digest, project=project)
    doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert doc == {
        "retention_days": 30,
        "sources": [{"name": "events", "type": "parquet", "path": "keep.parquet"}],
    }
    assert connection_spy == []


def test_approval_without_a_registry_fails_before_writing(tmp_path):
    """A project without ariadne.yaml cannot be approved into: the failure is
    actionable and writes nothing."""
    project = tmp_path
    digest = authoring.propose_sources(
        write_proposal(
            tmp_path, [{"name": "events", "type": "parquet", "path": "data/events.parquet"}]
        ),
        project=project,
    )["digest"]
    with pytest.raises(ValueError, match="ariadne.yaml"):
        authoring.approve_sources(digest, project=project)
    assert not (project / "ariadne.yaml").exists()


def test_approval_survives_an_edited_stored_proposal(tmp_path):
    """The stored proposal lives in agent-writable staging: approval re-derives
    the digest from the stored content, so a hand-edited file never installs
    under the operator's digest."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "a.parquet")
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    stored = project / "staging" / "authoring" / "source-proposal.yaml"
    doc = yaml.safe_load(stored.read_text(encoding="utf-8"))
    doc["sources"][0]["path"] = str(tmp_path / "sneaky.parquet")
    stored.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError, match="[Dd]igest"):
        authoring.approve_sources(digest, project=project)
    assert "sources" not in yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))


# ------------------------------------------------------------------- CLI


def test_cli_propose_then_wrong_digest_then_approval(tmp_path, capsys, monkeypatch):
    """The console-script seam: propose-sources emits one JSON value with the
    digest and precise locations; approve-sources with the wrong digest writes
    one JSON error object to stderr and exits 1 without touching the registry."""
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    proposal = write_proposal(
        tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]
    )
    assert (
        authoring_cli(["propose-sources", "--file", str(proposal), "--project", str(project)]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["digest"] and out["sources"] == [
        {"name": "events", "type": "parquet", "path": str(parquet)}
    ]
    assert authoring_cli(["approve-sources", "--digest", "0" * 64, "--project", str(project)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err)["error"]["type"] == "ValueError"
    assert "sources" not in yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    assert (
        authoring_cli(["approve-sources", "--digest", out["digest"], "--project", str(project)])
        == 0
    )
    installed = json.loads(capsys.readouterr().out)
    assert installed["sources"][0]["name"] == "events"


def test_cli_malformed_invocation_writes_one_json_error(tmp_path, capsys):
    """A malformed invocation (absent --digest) keeps the written JSON
    contract: exactly one {"error": ...} object on stderr and exit 1, never
    argparse usage text (the ariadne CLI's UsageError pattern)."""
    project = scaffold_project(tmp_path)
    assert authoring_cli(["approve-sources", "--project", str(project)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["type"] == "UsageError"
    assert "--digest" in error["message"]
    assert "retention_days: 90" in (project / "ariadne.yaml").read_text(encoding="utf-8")


def test_cli_inputs_can_bound_approved_profile(tmp_path, capsys):
    project = scaffold_project(tmp_path)
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    authoring.approve_sources(digest, project=project)
    assert authoring_cli(["inputs", "--sample-rows", "1", "--project", str(project)]) == 0
    table = json.loads(capsys.readouterr().out)["profile"]["sources"][0]["tables"]["events"]
    assert table["row_count"] == 1 and table["sampled"] is True
    assert table["primary_key_candidates"] == []


# ------------------------------------------- slice 2 (issue #14): harness evidence


def test_upload_then_reference_converts_to_stable_identity_evidence(tmp_path, connection_spy):
    """Issue #14 seam: a bounded upload retains its original bytes in the
    project-controlled input area; the referenced document converts WITHOUT any
    model and retrieves with the exact same identity/digest every time; and
    harness_inputs returns it beside the deterministic per-source profile —
    which appears only after the #13 approval — and the approved Seed Notes."""
    project = scaffold_project(tmp_path)
    bytes_ = b"# Pricing policy\n\nUSD is the only billing currency.\n"

    # Bounded upload: original bytes retained, digest reported.
    upload = authoring.store_upload("pricing.md", bytes_, project=project)
    assert upload["digest"] == hashlib.sha256(bytes_).hexdigest()
    retained = project / "data" / "docs" / "pricing.md"
    assert retained.read_bytes() == bytes_

    # An identical re-upload keeps the same identity (nothing multiplied).
    again = authoring.store_upload("pricing.md", bytes_, project=project)
    assert again == upload

    # Referenced conversion: complete text, source identity, no connection opened.
    evidence = authoring.document_evidence("pricing.md", project=project)
    assert evidence["complete"] is True
    assert "USD is the only billing currency" in evidence["text"]
    assert evidence["digest"] == upload["digest"]
    assert evidence["resource"] == upload["resource"]
    assert authoring.document_evidence("pricing.md", project=project) == evidence

    (project / "data" / "seed_notes.md").write_text(
        "# Seed notes\n\nGross revenue excludes churned rows.\n", encoding="utf-8"
    )

    # Before source approval: evidence yes, profile no — nothing opened.
    early = authoring.harness_inputs(project=project, documents=["pricing.md"])
    assert early["profile"] is None
    assert early["documents"][0]["digest"] == upload["digest"]
    assert early["seed_notes"]["complete"] is True
    assert connection_spy == []  # no proposed location was ever opened

    # After the human approval: the same call now carries the real profile.
    parquet = write_parquet(tmp_path / "data" / "events.parquet")
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    authoring.approve_sources(digest, project=project)
    inputs = authoring.harness_inputs(project=project, documents=["pricing.md"])
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
    monkeypatch.setattr(authoring, "_fetch_object_bytes", lambda uri: fetched.append(uri) or b"x")
    for reference in (
        "s3://ariadne-docs/policies/secret.md",
        "https://cdn.example.com/doc.md",
        "https://ro:s3cret@cdn.example.com/doc.md",  # no credential-in-URL policy exists
    ):
        with pytest.raises(ValueError, match="not approved"):
            authoring.document_evidence(reference, project=project)
    assert fetched == []  # nothing fetched, nothing retained
    assert not (project / "data" / "object-store").exists()


def test_approved_object_reference_converts_with_retained_bytes(tmp_path, monkeypatch):
    """Issue #14 owner decision: the operator lists EXACT approved object-store
    URIs under documents.object_store in ariadne.yaml. The approved reference is
    fetched once with server-held credentials, its original bytes RETAINED in
    the project input area, and converted to evidence whose resource is the
    exact URI — and the retained copy serves repeat calls without a re-fetch."""
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

    monkeypatch.setattr(authoring, "_fetch_object_bytes", fake_fetch)

    evidence = authoring.document_evidence(approved, project=project)
    assert evidence["resource"] == approved  # the exact approved URI, not a local path
    assert evidence["title"] == "pricing.md"
    assert evidence["digest"] == hashlib.sha256(payload).hexdigest()
    assert "USD is the only billing currency" in evidence["text"]
    assert evidence["complete"] is True
    assert fetched == [approved]  # fetched exactly once, server-side seam

    # Original bytes retained in the project input area, digest-identical.
    retained = list((project / "data" / "object-store").rglob("*"))
    assert [p for p in retained if p.is_file()] and all(
        p.read_bytes() == payload for p in retained if p.is_file()
    )

    # Repeat calls read the retained snapshot: same identity, no re-fetch.
    assert authoring.document_evidence(approved, project=project) == evidence
    assert fetched == [approved]


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
def test_upload_refuses_a_preexisting_symlink_in_the_input_root(tmp_path, dangling):
    """A client-named upload filename that matches a pre-existing symlink in
    the input root — pointing outside it, or dangling — is refused without
    following the link: no read through it, no write at its target."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    secret = project / "server-secret.txt"
    secret.write_text("server-side secret", encoding="utf-8")
    target = project / "absent.txt" if dangling else secret
    (docs / "pricing.md").symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        authoring.store_upload("pricing.md", b"# client payload\n", project=project)

    if dangling:
        assert not (project / "absent.txt").exists()  # nothing written outside the root
    assert secret.read_text() == "server-side secret"  # the existing file untouched


def test_harness_inputs_bounds_the_document_batch(tmp_path):
    """Spec §3 bounded responses: the documents batch has an explicit small
    count bound, so repeating valid references cannot force an unbounded
    aggregate response or unbounded repeated conversion."""
    project = scaffold_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("# a\n", encoding="utf-8")
    limit = authoring.MAX_DOCUMENTS_PER_CALL

    ok = authoring.harness_inputs(project=project, documents=["a.md"] * limit)
    assert len(ok["documents"]) == limit

    with pytest.raises(ValueError, match="bound"):
        authoring.harness_inputs(project=project, documents=["a.md"] * (limit + 1))


def test_document_evidence_digest_and_text_come_from_one_stable_snapshot(tmp_path, monkeypatch):
    """A file replaced between the digest read and the conversion read must
    never yield evidence whose digest describes different bytes than its text:
    both come from one stable snapshot (review finding: concurrent replacement)."""
    project = scaffold_project(tmp_path)
    doc = project / "data" / "docs" / "raced.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# original policy\n", encoding="utf-8")
    original_bytes = doc.read_bytes()

    real_convert = authoring._convert

    def convert_then_replace(path):  # the replacement lands between the two reads
        text = real_convert(path)
        if path.suffix == doc.suffix:
            doc.write_text("# replaced mid-flight\n", encoding="utf-8")
        return text

    monkeypatch.setattr(authoring, "_convert", convert_then_replace)
    evidence = authoring.document_evidence("raced.md", project=project)
    assert evidence["text"].startswith("# original policy")
    assert evidence["digest"] == hashlib.sha256(original_bytes).hexdigest()


def test_seed_notes_digest_and_text_come_from_one_stable_snapshot(tmp_path, monkeypatch):
    """The same single-snapshot rule for Seed Notes: a replacement between the
    digest read and the text read cannot split identity from content."""
    project = scaffold_project(tmp_path)
    notes = project / "data" / "seed_notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("# original seed notes\n", encoding="utf-8")
    original_bytes = notes.read_bytes()

    real_digest = authoring._sha256_hex

    def digest_then_replace(data):  # replacement lands after the digest read
        value = real_digest(data)
        notes.write_text("# replaced seed notes\n", encoding="utf-8")
        return value

    monkeypatch.setattr(authoring, "_sha256_hex", digest_then_replace)
    inputs = authoring.harness_inputs(project=project)
    assert inputs["seed_notes"]["text"].startswith("# original seed notes")
    assert inputs["seed_notes"]["digest"] == real_digest(original_bytes)


def test_oversize_upload_is_refused_before_anything_is_written(tmp_path):
    """A bounded upload that exceeds the limit fails explicitly and writes
    nothing — not even the input-area directory."""
    project = scaffold_project(tmp_path)
    with pytest.raises(ValueError, match="over the"):
        authoring.store_upload("big.pdf", b"x" * 11, project=project, max_bytes=10)
    assert not (project / "data").exists()


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

    assert authoring_cli(["inputs", "--document", "policy.md", "--project", str(project)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["profile"] is None  # nothing approved yet: no profile, no opening
    assert out["documents"][0]["complete"] and "Policy" in out["documents"][0]["text"]
    assert out["seed_notes"] is None  # absent Seed Notes stay absent


# --------------------------- slice 3 (issue #15): full-bundle submission + review


MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: events
    description: Events model
    datasets:
      - name: events
        source: events.events
        primary_key: [{pk}]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: label
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: label
            dimension: {{}}
    metrics:
      - name: event_count
        description: Count of all events
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""


def _page(page_type: str, title: str, *, status: str | None = None, sources: str = "") -> str:
    """One minimal gate-clean OKF page of ``page_type`` (ADR-0007 frontmatter)."""
    front = (
        f"type: {page_type}\ntitle: {title}\n"
        f"description: One {page_type} page.\ntags: [{page_type}]\n"
    )
    if status:
        front += f"status: {status}\n"
    front += (
        "sources:\n  - id: seed-notes\n    resource: data/seed_notes.md\n    title: Seed notes\n"
    )
    return f"---\n{front}---\n\n# {title}\n" + sources


def bundle_submission(
    *, pk: str = "id", seed_notes: str = "# Seed notes\n\nAll events count.\n"
) -> dict:
    """One complete proposed bundle: Seed Notes, OSI model, and OKF pages
    (spec "Authoring interface and lifecycle") as relative paths and bodies."""
    return {
        "files": [
            {
                "path": "data/seed_notes.md",
                "content": seed_notes,
            },
            {
                "path": "semantic_layer/models/events.yml",
                "content": MODEL_YML.format(pk=pk),
            },
            {
                "path": "context_layer/tables/events.md",
                "content": (
                    "---\ntype: table\ntitle: Events\ndescription: One row per event.\n"
                    "tags: [table]\n"
                    "sources:\n  - id: events\n    resource: events.events\n    title: events\n"
                    f"grain:\n  primary_key: [{pk}]\n  cardinality_enforcement: STRICT_1_TO_1\n"
                    "---\n\n# Events\n"
                ),
            },
            {
                "path": "context_layer/references/joins/events--events.md",
                "content": _page("reference", "events identity"),
            },
            {
                "path": "context_layer/policies/all-events-count.md",
                "content": _page("policy", "All events count", status="draft"),
            },
            {
                "path": "context_layer/metrics/event_count.md",
                "content": (
                    "---\ntype: metric\nstatus: draft\ntitle: event_count\n"
                    "description: Count of all events.\ntags: [metric]\n"
                    "sources:\n  - id: all-events-count\n"
                    "    resource: policies/all-events-count.md\n    title: All events count\n"
                    "---\n\n# event_count\n"
                ),
            },
            {
                "path": "context_layer/skills/run-the-demo.md",
                "content": _page("skill", "run the demo"),
            },
        ]
    }


def write_submission(tmp_path: Path, submission: dict, name: str = "bundle.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(submission), encoding="utf-8")
    return path


def approved_project(tmp_path: Path) -> Path:
    """A fresh project with one APPROVED parquet source (the #13/#14 flow), so
    the bundle's deterministic checks run against a real registry connection.
    The ``label`` column deliberately repeats (a,a,b): it is NOT a unique grain."""
    project = scaffold_project(tmp_path)
    parquet = project / "data" / "events.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1, 'a'), (2, 'a'), (3, 'b')) t(id, label)) "
        f"TO '{parquet}' (FORMAT PARQUET)"
    ).close()
    digest = authoring.propose_sources(
        write_proposal(tmp_path, [{"name": "events", "type": "parquet", "path": str(parquet)}]),
        project=project,
    )["digest"]
    authoring.approve_sources(digest, project=project)
    return project


def submit_cli(project: Path, submission: dict, *extra: str, name: str = "bundle.json") -> int:
    """One public-CLI ``submit`` invocation over a written submission file."""
    file = write_submission(project, submission, name=name)
    return authoring_cli(["submit", "--file", str(file), "--project", str(project), *extra])


def test_identical_retry_is_idempotent_and_never_resets_attempts(tmp_path, capsys):
    """Distinct case (ticket): re-submitting IDENTICAL content creates no new
    candidate and resets nothing — same revision, same attempt count, no rewrite."""
    project = approved_project(tmp_path)
    bad = bundle_submission(pk="label")
    first = json.loads(_submit_captured(project, bad, capsys, name="b1.json"))
    assert first["status"] == "invalid" and first["attempts"] == 1
    before = (project / "staging" / "authoring" / "bundle-state.json").read_text()

    retry = json.loads(_submit_captured(project, bad, capsys, name="b2.json"))
    assert retry["revision"] == first["revision"] == 1
    assert retry["attempts"] == 1  # not reset, not incremented
    assert retry["status"] == "invalid"
    assert (project / "staging" / "authoring" / "bundle-state.json").read_text() == before


def test_state_survives_a_process_restart(tmp_path, capsys, monkeypatch):
    """Distinct case (ticket): the active proposal persists across a restart —
    a SEPARATE PROCESS (python -m ariadne.authoring_cli) sees the same proposal,
    refuses a repair without the current digest, and accepts it with the digest
    recorded by the first process."""
    project = approved_project(tmp_path)
    bad = bundle_submission(pk="label")
    first = json.loads(_submit_captured(project, bad, capsys, name="b1.json"))

    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    good = write_submission(project, bundle_submission(), name="b2.json")
    no_base = subprocess.run(
        [
            sys.executable,
            "-m",
            "ariadne.authoring_cli",
            "submit",
            "--file",
            str(good),
            "--project",
            str(project),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert no_base.returncode == 1  # the restarted process refuses a digest-less repair
    assert "base-digest mismatch" in json.loads(no_base.stderr)["error"]["message"]

    repaired = subprocess.run(
        [
            sys.executable,
            "-m",
            "ariadne.authoring_cli",
            "submit",
            "--file",
            str(good),
            "--base-digest",
            first["digest"],
            "--project",
            str(project),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert repaired.returncode == 0
    out = json.loads(repaired.stdout)
    assert out["status"] == "validated" and out["revision"] == 2 and out["attempts"] == 2


def test_three_failed_rounds_exhaust_to_review_needed(tmp_path, capsys):
    """Distinct case (ticket): at most three authoring rounds — the third
    failure marks the staged files ``review_needed`` and a fourth submission is
    refused for human resolution, without replacing anything."""
    project = approved_project(tmp_path)
    base = None
    for round_no in (1, 2, 3):
        bad = bundle_submission(pk="label", seed_notes=f"# round {round_no}\n")
        extra = ("--base-digest", base) if base else ()
        out = json.loads(_submit_captured(project, bad, capsys, *extra, name=f"b{round_no}.json"))
        assert out["attempts"] == round_no
        base = out["digest"]
    assert out["status"] == "review_needed"
    staged = (project / "staging" / "authoring" / "bundle").rglob("*.md")
    assert any("review_needed" in p.read_text(encoding="utf-8") for p in staged)

    fourth = bundle_submission(pk="label", seed_notes="# round 4\n")
    file = write_submission(project, fourth, name="b4.json")
    assert authoring_cli(["submit", "--file", str(file), "--project", str(project)]) == 1
    err = json.loads(capsys.readouterr().err)["error"]
    assert "review_needed" in err["message"] and "human" in err["message"]
    state = json.loads((project / "staging" / "authoring" / "bundle-state.json").read_text())
    assert state["attempts"] == 3  # the refusal replaced nothing


def test_pending_attestation_computation_cites_no_demo_oracle(tmp_path, capsys):
    """Distinct case (ticket/ADR-0013): a metric with no independent
    expected-value oracle gets an honest ``attestation: pending`` computation —
    the demo eval harness is NEVER cited, and the per-type contract accepts it."""
    project = approved_project(tmp_path)
    good = json.loads(_submit_captured(project, bundle_submission(), capsys))
    assert good["status"] == "validated"  # the pending state passes the bundle gate
    comp = (
        project
        / "staging"
        / "authoring"
        / "bundle"
        / "context_layer"
        / "computations"
        / "event_count.md"
    ).read_text(encoding="utf-8")
    assert "attestation: pending" in comp
    assert "tests/test_evals.py" not in comp and "attester:" not in comp
    meta = yaml.safe_load(comp.split("---")[1])
    assert meta["attestation"] == "pending" and not meta.get("attester")


def test_competing_or_stale_writer_cannot_replace_the_active_proposal(tmp_path, capsys):
    """Distinct case (ticket): a repair without the CURRENT digest — stale or
    competing — fails and the active proposal is untouched."""
    project = approved_project(tmp_path)
    first = json.loads(_submit_captured(project, bundle_submission(pk="label"), capsys))
    competing = bundle_submission(pk="label", seed_notes="# competing\n")
    file = write_submission(project, competing, name="c.json")
    assert (
        authoring_cli(
            ["submit", "--file", str(file), "--base-digest", "0" * 64, "--project", str(project)]
        )
        == 1
    )
    assert "base-digest mismatch" in json.loads(capsys.readouterr().err)["error"]["message"]
    state = json.loads((project / "staging" / "authoring" / "bundle-state.json").read_text())
    assert state["submission_digest"] == first["digest"]  # not replaced
    assert state["attempts"] == 1


def test_changed_source_registry_invalidates_the_active_proposal(tmp_path, capsys):
    """Distinct case (ticket/spec): a source change while a bundle proposal is
    active invalidates it — submission fails without replacement, for the human."""
    project = approved_project(tmp_path)
    json.loads(_submit_captured(project, bundle_submission(pk="label"), capsys))
    doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    doc["sources"][0]["path"] = str(project / "data" / "other.parquet")
    (project / "ariadne.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    file = write_submission(project, bundle_submission(), name="b2.json")
    assert authoring_cli(["submit", "--file", str(file), "--project", str(project)]) == 1
    err = json.loads(capsys.readouterr().err)["error"]["message"]
    assert "source registry changed" in err and "no replacement" in err


@pytest.mark.parametrize(
    ("bad_path", "why"),
    [
        ("../escape.md", "path traversal"),
        ("/abs/path.md", "relative POSIX"),
        ("context_layer/metrics/../../escape.md", "traversal"),
        ("context_layer/index.md", "index.md"),
        ("context_layer/log.md", "log.md"),
        ("context_layer/computations/event_count.md", "generated"),
        ("served/thing.md", "documented submission roots"),
    ],
)
def test_out_of_scope_paths_are_refused_before_any_write(tmp_path, bad_path, why):
    """The pre-write boundary: escapes, generated bookkeeping, service-owned
    computations, and undocumented roots never reach staging."""
    project = approved_project(tmp_path)
    submission = bundle_submission()
    submission["files"][0]["path"] = bad_path
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match=why):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()


def test_credential_carrying_submission_is_refused_before_any_write(tmp_path):
    """Inline URL credentials never enter staging (ADR-0010 credential shape)."""
    project = approved_project(tmp_path)
    submission = bundle_submission()
    submission["files"][0]["content"] += (
        "\nConnect via postgresql://admin:hunter2@db.internal:5432/events\n"
    )
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match="credentials"):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()


def test_unbounded_submission_is_refused_before_any_write(tmp_path):
    """The payload bound: an over-limit submission writes nothing."""
    project = approved_project(tmp_path)
    submission = bundle_submission()
    submission["files"][0]["content"] = "x" * (authoring.MAX_BUNDLE_BYTES + 1)
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match="bound"):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()
    assert not (project / "staging" / "authoring" / "bundle-state.json").exists()


@pytest.mark.parametrize("dangling", [False, True], ids=["existing", "dangling"])
def test_symlinked_staging_component_is_refused(tmp_path, dangling):
    """A symlink planted on the bundle staging path — pointing outside the
    project or dangling — never redirects staging writes."""
    project = approved_project(tmp_path)
    authoring_dir = project / "staging" / "authoring"
    authoring_dir.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (authoring_dir / "bundle").symlink_to(outside if not dangling else tmp_path / "absent")
    file = write_submission(project, bundle_submission())
    with pytest.raises(ValueError, match="symlinked staging component"):
        authoring.submit_bundle(file, project=project)
    assert list(outside.rglob("*")) == []  # nothing written through the link


def test_review_without_a_proposal_is_an_actionable_error(tmp_path, capsys):
    """``review`` on a proposal-less project keeps the JSON error contract."""
    project = scaffold_project(tmp_path)
    assert authoring_cli(["review", "--project", str(project)]) == 1
    err = json.loads(capsys.readouterr().err)["error"]
    assert err["type"] == "ValueError" and "submit" in err["message"]


def _submit_captured(
    project: Path, submission: dict, capsys, *extra: str, name: str = "bundle.json"
) -> str:
    """Submit through the public CLI and return captured stdout (one JSON value)."""
    assert submit_cli(project, submission, *extra, name=name) == 0
    return capsys.readouterr().out


def test_cli_grain_invalid_bundle_fails_checks_and_serves_nothing(tmp_path, capsys):
    """Issue #15 red seam, the public journey: a harness-owned-model bundle
    whose model violates the ADR-0006 grain rules is submitted through the
    local CLI, fails the SAME deterministic checks with actionable errors and
    a repair digest — and nothing reaches the served layers."""
    project = approved_project(tmp_path)
    bad = bundle_submission(pk="label")  # label repeats across rows: not a unique grain

    file = write_submission(project, bad)
    assert (
        authoring_cli(["submit", "--file", str(file), "--project", str(project)]) == 0
    )  # accepted for review, validation failed — errors are the harness's data
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "invalid"
    assert any("grain audit failed" in error for error in out["errors"])
    assert len(out["digest"]) == 64 and out["revision"] == 1 and out["attempts"] == 1
    assert out["provenance"]["mode"] == "harness-led"

    # nothing was served: no served layer exists, the seed notes are untouched
    assert not (project / "context_layer").exists()
    assert not (project / "semantic_layer").exists()
    assert not (project / "data" / "seed_notes.md").exists()

    # the staged proposal is repairable with the returned digest and then valid
    assert (
        submit_cli(
            project, bundle_submission(), "--base-digest", out["digest"], name="bundle-2.json"
        )
        == 0
    )
    good = json.loads(capsys.readouterr().out)
    assert good["status"] == "validated"
    assert good["errors"] == []
    assert good["revision"] == 2 and good["attempts"] == 2
    assert not (project / "context_layer").exists()  # still nothing served

    # review exposes the exact reviewed content digest (never a signoff)
    assert authoring_cli(["review", "--project", str(project)]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["status"] == "validated"
    assert review["digest"] == good["review_digest"]
    paths = [entry["resource"] for entry in review["files"]]
    assert "data/seed_notes.md" in paths
    assert any(path.startswith("context_layer/computations/") for path in paths)

    # human Promotion under a STALE reviewed digest is denied before any write
    stale = promote_main(
        [
            "--yes",
            "--digest",
            "0" * 64,
            "--staging",
            str(project / "staging"),
            "--served",
            str(project),
        ]
    )
    assert stale == 1
    assert not (project / "context_layer").exists()  # denied before any served write
    assert not (project / "data" / "seed_notes.md").exists()


def test_pyproject_exposes_ariadne_authoring():
    """The console script the spec names is installed."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ariadne-authoring = "ariadne.authoring_cli:main"' in text


# ------- issue #15 fix pass: boundary findings from the exact-content review -------


def _wait_for(path: Path, timeout: float = 60.0) -> None:
    """Poll until ``path`` exists (subprocess handshakes in the race tests)."""
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {path}")
        time.sleep(0.02)


def test_unapproved_dataset_source_is_refused_before_any_duckdb_execution(tmp_path):
    """Review finding P1: a remotely authored dataset.source naming a table
    function over an unregistered server file must be refused BEFORE any
    validate bind/audit opens it — the file below is real and readable, so a
    submission that reaches DuckDB would audit it and come back validated."""
    project = approved_project(tmp_path)
    secret = write_parquet(project / "data" / "unregistered.parquet")  # outside the registry
    submission = bundle_submission()
    submission["files"][1]["content"] = MODEL_YML.format(pk="id").replace(
        "source: events.events",
        f"source: (SELECT * FROM read_parquet('{secret}'))",
    )
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match="approved"):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()
    assert not (project / "staging" / "authoring" / "bundle-state.json").exists()


def test_domain_layout_bundle_is_refused_at_the_source_boundary(tmp_path):
    """mf-t1 review finding F1: the source-access boundary walks the rendered
    SQL of ONE dataset per envelope, so a multi-dataset (domain-layout) model
    can carry an unauthorized second-dataset source past render-based
    authorization while a graph-aware validator would bind it. Fail closed at
    the boundary until authorization understands the normalized graph."""
    project = approved_project(tmp_path)
    secret = write_parquet(project / "data" / "unregistered.parquet")  # outside the registry
    second_dataset = f"""      - name: event_details
        source: (SELECT * FROM read_parquet('{secret}'))
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
"""
    submission = bundle_submission()
    # one semantic_model entry carrying TWO datasets: the domain authoring layout
    submission["files"][1]["content"] = MODEL_YML.format(pk="id").replace(
        "    metrics:", second_dataset + "    metrics:"
    )
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match="multi-dataset"):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()
    assert not (project / "staging" / "authoring" / "bundle-state.json").exists()


def test_empty_registry_cannot_validate_a_full_bundle(tmp_path):
    """Review finding P1: with NO approved sources, a full bundle must never
    be marked validated through the compile-only path — there is no approved
    identity its models could legitimately read."""
    project = scaffold_project(tmp_path)  # template registry: no approved sources
    file = write_submission(project, bundle_submission())
    with pytest.raises(ValueError, match="approved"):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()
    assert not (project / "staging" / "authoring" / "bundle-state.json").exists()


def test_nested_okf_page_is_refused_and_never_reaches_validation(tmp_path):
    """Review finding P1: a page nested below a section (never checked by the
    per-type bundle gate, which reads only the section's immediate .md files)
    must be refused before any write — it can never ride along to validation
    and Promotion. The documented references/joins layout stays accepted."""
    project = approved_project(tmp_path)
    submission = bundle_submission()
    submission["files"].append(
        {"path": "context_layer/metrics/extra/untyped.md", "content": "# no frontmatter\n"}
    )
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match="nested"):
        authoring.submit_bundle(file, project=project)
    assert not (project / "staging" / "authoring" / "bundle").exists()
    assert not (project / "staging" / "authoring" / "bundle-state.json").exists()


def test_named_aws_credential_assignment_is_refused_and_prose_is_not(tmp_path):
    """Review finding P2: a named AWS credential assignment in Seed Notes is
    a credential (the URL-password rule alone misses it); the rejection names
    the class, never echoes the value — and ordinary business-rule prose that
    merely mentions the variable name is not rejected."""
    project = approved_project(tmp_path)
    submission = bundle_submission()
    submission["files"][0]["content"] += (
        "\nAWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n"
    )
    file = write_submission(project, submission)
    with pytest.raises(ValueError, match="credential") as excinfo:
        authoring.submit_bundle(file, project=project)
    assert "wJalrXUtnFEMI" not in str(excinfo.value)  # the value is never echoed
    assert not (project / "staging" / "authoring" / "bundle").exists()

    prose = bundle_submission()
    prose["files"][0]["content"] += (
        "\nThe AWS_SECRET_ACCESS_KEY environment variable supplies credentials at "
        "runtime; values are never pasted into Seed Notes.\n"
    )
    out = authoring.submit_bundle(
        write_submission(project, prose, name="prose.json"), project=project
    )
    assert out["status"] == "validated"  # business-rule prose passes


_RACE_CHILD = """\
import json, sys, time
from pathlib import Path

from ariadne import authoring

project, submission_file, base_digest, ready, go = sys.argv[1:6]
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.time() + 60
while not Path(go).exists() and time.time() < deadline:
    time.sleep(0.01)
try:
    result = authoring.submit_bundle(
        submission_file, project=project, base_digest=base_digest
    )
    print(json.dumps({"ok": True, "digest": result["digest"], "status": result["status"]}))
except ValueError as exc:
    print(json.dumps({"ok": False, "error": str(exc)}))
"""


def test_concurrent_submissions_cannot_both_replace_the_active_proposal(tmp_path):
    """Review finding P1, the named race: two real CLI processes released by
    a barrier with the SAME base digest — exactly one may replace the active
    proposal; the other must fail as a stale/competing writer, and the final
    state must pair with the staged bytes it names."""
    project = approved_project(tmp_path)
    first = authoring.submit_bundle(
        write_submission(project, bundle_submission(pk="label"), name="b1.json"),
        project=project,
    )  # round 1 fails the grain audit: an active, repairable proposal
    assert first["status"] == "invalid"

    ready_a, ready_b, go = project / "ra", project / "rb", project / "GO"
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _RACE_CHILD,
                str(project),
                str(write_submission(project, sub, name=f"{tag}.json")),
                first["digest"],
                str(ready),
                str(go),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        for tag, sub, ready in (
            ("a", bundle_submission(seed_notes="# writer A\n"), ready_a),
            ("b", bundle_submission(seed_notes="# writer B\n"), ready_b),
        )
    ]
    try:
        _wait_for(ready_a)
        _wait_for(ready_b)
        go.write_text("go", encoding="utf-8")  # the barrier: both race from one state
        results = []
        for proc in procs:
            out, _err = proc.communicate(timeout=120)
            results.append(json.loads(out))
    finally:
        for proc in procs:
            if proc.poll() is None:  # pragma: no cover - failure path only
                proc.kill()

    winners = [r for r in results if r["ok"]]
    losers = [r for r in results if not r["ok"]]
    assert len(winners) == 1 and winners[0]["status"] == "validated"
    assert len(losers) == 1 and "stale or competing" in losers[0]["error"]
    state = json.loads(
        (project / "staging" / "authoring" / "bundle-state.json").read_text(encoding="utf-8")
    )
    assert state["submission_digest"] == winners[0]["digest"]
    # the recorded exact-content digest pairs with the staged bytes (no split state)
    assert state["digest"] == authoring._tree_digest(project / "staging" / "authoring" / "bundle")
    assert not (project / "context_layer").exists()  # the human gate still holds


# ---- issue #15 crash-recovery repair: the surviving P1 (owner fail-closed) ----


def test_crashed_transition_blocks_the_retry_that_would_delete_the_retained_copy(
    tmp_path, monkeypatch
):
    """Issue #15 surviving P1 (owner fail-closed decision): a transition that
    renamed A into ``bundle.discarded`` and swapped B in, then died before
    storing B's state, leaves state=A + A-only-in-bundle.discarded + B-staged.
    The retry with A's CURRENT base digest is refused with EVERY copy intact —
    pre-fix it ran the transition and deleted A's last surviving copy."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    assert a["status"] == "validated"

    def crash_after_swap(project, state):  # the interruption the finding names
        raise RuntimeError("simulated crash: swap done, state not stored")

    monkeypatch.setattr(authoring, "_store_bundle_state", crash_after_swap)
    with pytest.raises(RuntimeError, match="simulated crash"):
        authoring.submit_bundle(
            write_submission(
                project, bundle_submission(seed_notes="# Seed notes\n\nVersion B.\n"), name="b.json"
            ),
            project=project,
            base_digest=a["digest"],
        )
    monkeypatch.undo()
    staging = project / "staging" / "authoring"
    # the exact interrupted layout: B staged, A surviving ONLY under bundle.discarded
    assert "Version B." in (staging / "bundle" / "data" / "seed_notes.md").read_text()
    assert (
        "All events count." in (staging / "bundle.discarded" / "data" / "seed_notes.md").read_text()
    )
    assert (
        json.loads((staging / "bundle-state.json").read_text())["submission_digest"] == a["digest"]
    )

    # the fatal retry pre-fix: chained on A's current base digest, the
    # transition rmtree'd bundle.discarded BEFORE any state update
    with pytest.raises(ValueError, match="human resolution"):
        authoring.submit_bundle(
            write_submission(
                project, bundle_submission(seed_notes="# Seed notes\n\nVersion C.\n"), name="c.json"
            ),
            project=project,
            base_digest=a["digest"],
        )
    # refused: every copy stays exactly as the crash left it
    assert "Version B." in (staging / "bundle" / "data" / "seed_notes.md").read_text()
    assert (
        "All events count." in (staging / "bundle.discarded" / "data" / "seed_notes.md").read_text()
    )
    assert (
        json.loads((staging / "bundle-state.json").read_text())["submission_digest"] == a["digest"]
    )

    # review and the human Promotion refuse the same layout without touching it
    with pytest.raises(ValueError, match="human resolution"):
        authoring.review_bundle(project=project)
    with pytest.raises(ValueError, match="human resolution"):
        promote_bundle(
            a["review_digest"],
            staging_root=project / "staging",
            served_root=project,
            by="human:tester",
            assume_yes=True,
        )
    assert not (project / "context_layer").exists()  # nothing served
    assert "Version B." in (staging / "bundle" / "data" / "seed_notes.md").read_text()


def test_successful_transition_cleans_the_discard_under_the_bundle_lock(tmp_path, monkeypatch):
    """Issue #15 surviving P1, the cleanup race: dropping the superseded
    bundle.discarded must happen INSIDE the bundle lock — after the lock is
    released the cleanup can interleave with the next writer's swap and remove
    ITS retained copy. A monkeypatched rmtree proves the lock is held (a second
    non-blocking flock on the lock file blocks) exactly when the copy is dropped."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    lock_file = project / "staging" / "authoring" / "bundle.lock"
    real_rmtree = shutil.rmtree
    cleaned: list[str] = []

    def rmtree_only_under_the_lock(path, *args, **kwargs):
        if Path(path).name == authoring.BUNDLE_DISCARD_NAME:
            fd = os.open(lock_file, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                cleaned.append(str(path))  # held: cleanup is in the critical section
            else:
                raise AssertionError(f"discard cleanup ran without the bundle lock: {path}")
            finally:
                os.close(fd)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(authoring.shutil, "rmtree", rmtree_only_under_the_lock)
    b = authoring.submit_bundle(
        write_submission(
            project, bundle_submission(seed_notes="# Seed notes\n\nVersion B.\n"), name="b.json"
        ),
        project=project,
        base_digest=a["digest"],
    )
    assert b["status"] == "validated"  # the clean successful path stays usable
    assert cleaned, "the discard cleanup never ran"
    assert not (project / "staging" / "authoring" / "bundle.discarded").exists()
    state = json.loads((project / "staging" / "authoring" / "bundle-state.json").read_text())
    assert state["submission_digest"] == b["digest"]


def test_state_staging_disagreement_blocks_repair_instead_of_replacing(tmp_path):
    """The incoherent layout without a retained discard: staging that no longer
    matches the recorded state (hand-edited or drifted by an interruption) — a
    repair submission is refused for the human, never run on top of it."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    notes = project / "staging" / "authoring" / "bundle" / "data" / "seed_notes.md"
    notes.write_text("# hand-edited out from under the recorded state\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no longer matches"):
        authoring.submit_bundle(
            write_submission(
                project, bundle_submission(seed_notes="# Seed notes\n\nRepair.\n"), name="r.json"
            ),
            project=project,
            base_digest=a["digest"],
        )
    assert notes.read_text().startswith("# hand-edited")  # untouched
    assert (
        json.loads((project / "staging" / "authoring" / "bundle-state.json").read_text())[
            "submission_digest"
        ]
        == a["digest"]
    )


def test_retained_discard_blocks_submit_review_and_promotion_until_human_resolution(tmp_path):
    """A crash between the durable state store and the in-lock cleanup leaves a
    COHERENT state/bundle plus a retained ``bundle.discarded``: retries, review,
    and human Promotion all fail closed with every copy intact (owner decision:
    keep both copies, block agents, no command silently deletes evidence)."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    b = authoring.submit_bundle(
        write_submission(
            project, bundle_submission(seed_notes="# Seed notes\n\nVersion B.\n"), name="b.json"
        ),
        project=project,
        base_digest=a["digest"],
    )
    assert b["status"] == "validated"
    staging = project / "staging" / "authoring"
    (staging / "bundle.discarded").mkdir()  # the leftover the crash never cleaned
    (staging / "bundle.discarded" / "leftover.md").write_text("prior copy\n", encoding="utf-8")

    with pytest.raises(ValueError, match="human resolution"):
        authoring.submit_bundle(
            write_submission(
                project, bundle_submission(seed_notes="# Seed notes\n\nVersion C.\n"), name="c.json"
            ),
            project=project,
            base_digest=b["digest"],
        )
    with pytest.raises(ValueError, match="human resolution"):
        authoring.review_bundle(project=project)
    with pytest.raises(ValueError, match="human resolution"):
        promote_bundle(
            b["review_digest"],
            staging_root=project / "staging",
            served_root=project,
            by="human:tester",
            assume_yes=True,
        )
    # every copy intact, nothing served, nothing reset
    assert "Version B." in (staging / "bundle" / "data" / "seed_notes.md").read_text()
    assert (staging / "bundle.discarded" / "leftover.md").read_text() == "prior copy\n"
    assert (
        json.loads((staging / "bundle-state.json").read_text())["submission_digest"] == b["digest"]
    )
    assert not (project / "context_layer").exists()
    assert not (project / "data" / "seed_notes.md").exists()


def test_durability_barriers_precede_the_prior_copy_removal(tmp_path, monkeypatch):
    """Issue #15 review P1: "durably stored" is a fsync barrier, not rename
    atomicity. Before ``bundle.discarded`` (prior proposal A) is removed, the
    transition must have synced B's staged file data, the staged tree's
    directory entries — INCLUDING the staged tree's own ``bundle-*`` root,
    whose top-level entries no descendant's fsync persists — as well as BOTH
    sides of the cross-directory rename (staging root
    and authoring/), the replaced state file's data, and the state file's
    containing directory — otherwise a power interruption can recover state A
    alongside a deleted A while B half-survives."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    assert a["status"] == "validated"

    # ordered probe of the real syscall seam: every fsync'd/opened path, every
    # rename, and the discard removal, in the order submit_bundle performed them
    events: list[tuple[str, str, bool]] = []  # (kind, path, is_dir at the time)
    fd_paths: dict[int, str] = {}
    real_open, real_fsync, real_rmtree, real_replace = (
        os.open,
        os.fsync,
        shutil.rmtree,
        os.replace,
    )

    def spy_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        fd_paths[fd] = str(path)
        return fd

    def spy_fsync(fd):
        path = fd_paths.get(fd, f"fd:{fd}")
        events.append(("fsync", path, os.path.isdir(path)))
        return real_fsync(fd)

    def spy_rmtree(path, *args, **kwargs):
        if Path(path).name == authoring.BUNDLE_DISCARD_NAME:
            events.append(("rmtree", str(path), True))
        return real_rmtree(path, *args, **kwargs)

    def spy_replace(src, dst):
        events.append(("rename", f"{src} -> {dst}", False))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    monkeypatch.setattr(shutil, "rmtree", spy_rmtree)
    monkeypatch.setattr(os, "replace", spy_replace)

    b = authoring.submit_bundle(
        write_submission(
            project, bundle_submission(seed_notes="# Seed notes\n\nVersion B.\n"), name="b.json"
        ),
        project=project,
        base_digest=a["digest"],
    )
    assert b["status"] == "validated"

    removals = [i for i, (kind, _, _) in enumerate(events) if kind == "rmtree"]
    assert len(removals) == 1, "exactly one prior-copy removal per transition"
    cut = removals[0]  # nothing below may happen only after this point
    barrier = events[:cut]
    fsynced = [(p, d) for kind, p, d in barrier if kind == "fsync"]
    synced_files = [p for p, d in fsynced if not d]
    synced_dirs = {p for p, d in fsynced if d}
    renames = [p for kind, p, _ in barrier if kind == "rename"]

    # B's file DATA was synced while it still lived in the rename-staging tree
    # (every file of the final bundle went through it), and that tree's own
    # directory entries were synced too — deepest-first is verified by code
    # review; presence and position are what a crash can observe.
    staging_root = project / "staging"
    bundle = staging_root / "authoring" / "bundle"
    staged = [p for p in synced_files if p.startswith(str(staging_root) + "/bundle-")]
    assert staged, "no staged-tree file data was synced before the prior copy was removed"
    for rel in sorted(p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()):
        assert any(p.endswith(rel) for p in staged), f"staged file never synced: {rel}"
    # B's staged tree's own ROOT directory (the exact ``bundle-*`` dir, not a
    # descendant) must be fsynced — its own top-level entries (data/,
    # semantic_layer/, context_layer/, ...) are persisted only by syncing the
    # root itself — and BEFORE the prior copy's rename-aside, let alone its
    # removal below.
    root_syncs = [
        i
        for i, (p, d) in enumerate(fsynced)
        if d and Path(p).parent == staging_root and Path(p).name.startswith("bundle-")
    ]
    assert root_syncs, "B's staged root directory itself was never synced"
    discarded_path = staging_root / "authoring" / authoring.BUNDLE_DISCARD_NAME
    a_rename_at = next(
        i
        for i, (kind, p, _) in enumerate(barrier)
        if kind == "rename" and p.endswith(f"-> {discarded_path}")
    )
    assert max(root_syncs) < a_rename_at, (
        "B's staged root was synced only after the prior copy was renamed aside"
    )

    # BOTH sides of the cross-directory rename: the staging root lost the tmp
    # entry, authoring/ gained bundle (and discarded) — and the initial
    # proposal path renames across the same two directories.
    assert str(staging_root) in synced_dirs
    assert str(staging_root / "authoring") in synced_dirs

    # the replaced state file's DATA was synced before its rename, and the
    # state file's containing directory entry afterwards
    state_path = staging_root / "authoring" / "bundle-state.json"
    state_syncs = [
        i
        for i, (p, d) in enumerate(fsynced)
        if not d and p.endswith(".tmp") and Path(p).parent == state_path.parent
    ]
    assert state_syncs, "the state file data was never synced before the rename"
    state_renames = [p for p in renames if p.endswith(f"-> {state_path}")]
    assert state_renames, "the state file was never renamed into place"
    state_rename_at = next(
        i for i, (kind, p, _) in enumerate(barrier) if kind == "rename" and p in state_renames
    )
    assert max(state_syncs) < state_rename_at, (
        "the state rename happened before the state data was durable"
    )
    after_state_rename = barrier[state_rename_at + 1 :]
    assert any(
        kind == "fsync" and p == str(staging_root / "authoring")
        for kind, p, _ in after_state_rename
    ), "the state directory entry was not synced after the state rename"


def test_fsync_failure_fails_closed_and_retains_the_prior_proposal(tmp_path, monkeypatch):
    """The barrier is load-bearing: an fsync failure (EIO/ENOSPC on a full or
    failing disk) must abort the transition BEFORE the prior proposal copy is
    deleted — the operator keeps every copy instead of a silently non-durable
    replacement (issue #15 review P1, fail-closed requirement)."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    assert a["status"] == "validated"
    staging = project / "staging" / "authoring"
    state_before = (staging / "bundle-state.json").read_text()

    def failing_fsync(fd):
        raise OSError(errno.EIO, "simulated fsync failure")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="simulated fsync failure"):
        authoring.submit_bundle(
            write_submission(
                project,
                bundle_submission(seed_notes="# Seed notes\n\nVersion B.\n"),
                name="b.json",
            ),
            project=project,
            base_digest=a["digest"],
        )
    monkeypatch.undo()

    # fail-closed: no retained discard, the prior proposal is still the active
    # staging AND the recorded state — nothing was replaced or dropped
    assert not (staging / "bundle.discarded").exists()
    assert "All events count." in (staging / "bundle" / "data" / "seed_notes.md").read_text()
    assert (staging / "bundle-state.json").read_text() == state_before
    assert not any(p.name.startswith("bundle-") for p in (project / "staging").iterdir())

    # the project stays usable: a retry once the IO failure is gone succeeds
    b = authoring.submit_bundle(
        write_submission(
            project, bundle_submission(seed_notes="# Seed notes\n\nVersion B.\n"), name="b2.json"
        ),
        project=project,
        base_digest=a["digest"],
    )
    assert b["status"] == "validated"
    assert "Version B." in (staging / "bundle" / "data" / "seed_notes.md").read_text()
    assert not (staging / "bundle.discarded").exists()


# ---- candidate-integration fix pass: review findings P1 (document citations
# vanish at the review boundary) and P2 (review of a source-invalidated
# proposal) ----


def test_document_citations_travel_from_inputs_to_submit_and_review(tmp_path, capsys):
    """Candidate review P1, the public journey: ``inputs --document policy.md``
    -> ``submit`` carrying the document reference -> ``review``: the
    server-verified citation (exact resource, current-snapshot digest, title)
    is recorded with the proposal and returned by review beside the staged
    bodies — pre-fix, submit recorded no document evidence and review omitted
    every citation, so the human never saw which converted evidence a policy
    was drafted from."""
    project = approved_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    policy = docs / "policy.md"
    policy.write_text("# Pricing policy\n\nUSD is the only billing currency.\n", encoding="utf-8")

    inputs = authoring.harness_inputs(project=project, documents=["policy.md"])
    cited = inputs["documents"][0]

    submission = bundle_submission()
    submission["documents"] = ["policy.md"]
    file = write_submission(project, submission, name="cited.json")
    assert authoring_cli(["submit", "--file", str(file), "--project", str(project)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "validated"
    # the citation is server-derived: the same identity inputs reported, and
    # the digest of the actual current bytes — never a client-supplied string
    assert out["documents"] == [
        {"resource": cited["resource"], "title": "policy.md", "digest": cited["digest"]}
    ]
    assert out["documents"][0]["digest"] == hashlib.sha256(policy.read_bytes()).hexdigest()

    # an identical retry (same files AND same references) is idempotent: the
    # recorded citations and digests are preserved, attempts are not reset
    again = json.loads(_submit_captured(project, submission, capsys, name="cited-again.json"))
    assert again["documents"] == out["documents"]
    assert again["attempts"] == 1 and again["digest"] == out["digest"]

    # review re-reads the PERSISTED proposal (a fresh process would too): the
    # citations ride with it, and the bodies stay the proposed content alone
    assert authoring_cli(["review", "--project", str(project)]) == 0
    review = json.loads(capsys.readouterr().out)
    assert review["documents"] == out["documents"]
    assert review["digest"] == out["review_digest"]
    paths = [entry["resource"] for entry in review["files"]]
    assert "data/seed_notes.md" in paths
    assert "citations.json" not in paths  # the manifest is not a proposed body


def test_unapproved_cited_document_is_refused_before_any_write(tmp_path, monkeypatch):
    """Candidate review P1: each requested citation is verified at the SAME
    operator boundary as document reads, before anything is staged — a cited
    reference escaping the input roots or naming an unapproved object URI is
    refused with no fetch, no staging write, and no state file."""
    project = approved_project(tmp_path)
    (project / "server-secret.md").write_text("server-side secret", encoding="utf-8")
    fetched: list[str] = []
    monkeypatch.setattr(authoring, "_fetch_object_bytes", lambda uri: fetched.append(uri) or b"x")
    for reference in ("../server-secret.md", "s3://ariadne-docs/policies/secret.md"):
        submission = bundle_submission()
        submission["documents"] = [reference]
        file = write_submission(project, submission)
        with pytest.raises(ValueError, match="escapes|not approved"):
            authoring.submit_bundle(file, project=project)
    assert fetched == []  # nothing fetched for the unapproved URI
    assert not (project / "staging" / "authoring" / "bundle").exists()
    assert not (project / "staging" / "authoring" / "bundle-state.json").exists()


def test_changed_citations_invalidate_the_previously_reviewed_digest(tmp_path):
    """Candidate review P1 binding: the recorded citations are part of the
    proposal the exact review digest covers — resubmitting the SAME files with
    a DIFFERENT verified citation produces a new review digest, so the digest a
    human took before the change can no longer promote the changed citation
    metadata, and nothing is served."""
    project = approved_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "policy.md").write_text("# Pricing policy\n", encoding="utf-8")
    (docs / "other.md").write_text("# Other policy\n", encoding="utf-8")

    first = bundle_submission()
    first["documents"] = ["policy.md"]
    a = authoring.submit_bundle(write_submission(project, first, name="a.json"), project=project)
    assert a["status"] == "validated"

    # the harness swaps the citation linkage: identical files, different document
    second = bundle_submission()
    second["documents"] = ["other.md"]
    b = authoring.submit_bundle(
        write_submission(project, second, name="b.json"),
        project=project,
        base_digest=a["digest"],
    )
    assert b["review_digest"] != a["review_digest"]
    assert b["documents"][0]["title"] == "other.md"

    review = authoring.review_bundle(project=project)
    assert review["digest"] == b["review_digest"]
    assert review["documents"] == b["documents"]

    # the earlier human-reviewed digest no longer covers the changed citations
    with pytest.raises(ValueError, match="digest mismatch"):
        promote_bundle(
            a["review_digest"],
            staging_root=project / "staging",
            served_root=project,
            by="human:tester",
            assume_yes=True,
        )
    assert not (project / "context_layer").exists()  # nothing served


def test_review_refuses_a_source_invalidated_proposal_without_touching_it(tmp_path):
    """Candidate review P2: after the human-managed registry changes, review
    refuses as source-invalidated BEFORE describing bodies or status — the
    original staging and state stay byte-identical for the human (Promotion
    already refuses the same proposal; review must not call it validated)."""
    project = approved_project(tmp_path)
    a = authoring.submit_bundle(
        write_submission(project, bundle_submission(), name="a.json"), project=project
    )
    assert a["status"] == "validated"
    staging = project / "staging" / "authoring"
    state_before = (staging / "bundle-state.json").read_bytes()
    tree_before = authoring._tree_digest(staging / "bundle")

    doc = yaml.safe_load((project / "ariadne.yaml").read_text(encoding="utf-8"))
    doc["sources"][0]["path"] = str(project / "data" / "other.parquet")
    (project / "ariadne.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="source registry changed"):
        authoring.review_bundle(project=project)

    assert (staging / "bundle-state.json").read_bytes() == state_before
    assert authoring._tree_digest(staging / "bundle") == tree_before
    assert not (project / "context_layer").exists()  # no served effects


# ---- candidate citation repair (delta verdict P1s): a citation must be
# convertible evidence, and changed document bytes cannot ride an identical
# retry back to the old staged citation ----


def test_unconvertible_cited_document_is_refused_before_any_write(tmp_path):
    """Citation repair P1: a VERIFIED converted-document citation requires the
    SAME conversion inputs would run — a valid-root ``policy.bin`` (unsupported
    format) or a PDF whose converter errors is refused with the actionable
    conversion error BEFORE anything is staged or written, exactly as
    ``inputs`` would refuse it (spec §2–3: unsupported formats, missing
    converters, and conversion failures fail explicitly)."""
    project = approved_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "policy.bin").write_bytes(b"\x00\x01binary policy")
    (docs / "policy.pdf").write_bytes(b"this is not a pdf")  # converter errors
    cases = (("policy.bin", "unsupported document type"), ("policy.pdf", "conversion failed"))
    for reference, message in cases:
        submission = bundle_submission()
        submission["documents"] = [reference]
        with pytest.raises(ValueError, match=message):
            authoring.submit_bundle(write_submission(project, submission), project=project)
    staging = project / "staging" / "authoring"
    assert not (staging / "bundle").exists()  # nothing staged
    assert not (staging / "bundle-state.json").exists()  # no state write


def test_changed_document_bytes_break_the_same_reference_retry(tmp_path):
    """Citation repair P1: the submission digest covers the SERVER-VERIFIED
    citation triples, not just file bodies and reference strings — when
    policy.md changes after the original submission, a same-files/
    same-reference retry without the current base digest is refused instead of
    silently returning the OLD staged citation and review digest; with the
    current base it stages a correctly chained NEW revision whose citations
    and review digest differ, and the earlier human review digest refuses
    Promotion."""
    project = approved_project(tmp_path)
    docs = project / "data" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    policy = docs / "policy.md"
    policy.write_text("# Pricing policy\n\nUSD only.\n", encoding="utf-8")

    early = authoring.harness_inputs(project=project, documents=["policy.md"])
    submission = bundle_submission()
    submission["documents"] = ["policy.md"]
    a = authoring.submit_bundle(
        write_submission(project, submission, name="a.json"), project=project
    )
    assert a["status"] == "validated"
    old_citation = a["documents"][0]

    policy.write_text("# Pricing policy v2\n\nEUR also allowed.\n", encoding="utf-8")
    fresh = authoring.harness_inputs(project=project, documents=["policy.md"])
    assert fresh["documents"][0]["digest"] != early["documents"][0]["digest"]

    # same files, same reference, NO current base: the identical-retry branch
    # must not hand back the old staged citation and old review digest
    with pytest.raises(ValueError, match="base-digest mismatch"):
        authoring.submit_bundle(
            write_submission(project, submission, name="retry.json"), project=project
        )

    # with the CURRENT submission digest as base: a correctly chained new
    # revision whose verified citations and review digest differ
    b = authoring.submit_bundle(
        write_submission(project, submission, name="b.json"),
        project=project,
        base_digest=a["digest"],
    )
    assert b["revision"] == 2 and b["attempts"] == 2
    assert b["documents"][0]["digest"] == fresh["documents"][0]["digest"]
    assert b["documents"][0] != old_citation
    assert b["review_digest"] != a["review_digest"]

    review = authoring.review_bundle(project=project)
    assert review["documents"] == b["documents"]
    assert review["digest"] == b["review_digest"]

    # the earlier human review digest no longer covers the changed citation
    with pytest.raises(ValueError, match="digest mismatch"):
        promote_bundle(
            a["review_digest"],
            staging_root=project / "staging",
            served_root=project,
            by="human:tester",
            assume_yes=True,
        )
    assert not (project / "context_layer").exists()  # nothing served


def test_graph_yml_is_the_one_non_model_semantic_submission_path():
    """Issue #30: the remote-submission path gate admits exactly
    ``semantic_layer/graph.yml`` (the cross-file graph of the source layout) —
    nothing broader: any other semantic_layer/ path outside models/*.yml stays
    refused before any write."""
    files = [(entry["path"], entry["content"]) for entry in bundle_submission()["files"]]
    authoring._check_submission(files + [("semantic_layer/graph.yml", "version: 1\n")])
    for bad in ("semantic_layer/graph.yaml", "semantic_layer/other.yml"):
        with pytest.raises(ValueError, match="outside the documented submission roots"):
            authoring._check_submission(files + [(bad, "version: 1\n")])


def test_submit_normalizes_escaped_multiline_sources_to_block_scalars(tmp_path):
    """Issue #31: an agent draft serializes a dataset source as ONE double-
    quoted line full of \\n escapes — unreadable at the human staging gate.
    Ariadne re-emits semantic-layer YAML with multi-line scalars as literal
    blocks when it stages the bundle; parsed meaning is unchanged."""
    project = approved_project(tmp_path)
    submission = bundle_submission()
    submission["files"][1]["content"] = MODEL_YML.format(pk="id").replace(
        "source: events.events",
        'source: "SELECT id, label\\nFROM events.events\\nWHERE id IS NOT NULL"',
    )
    file = write_submission(project, submission)
    result = authoring.submit_bundle(file, project=project)
    assert result["status"] in ("validated", "review_needed"), result.get("errors")

    staged = (
        project / "staging" / "authoring" / "bundle"
        / "semantic_layer" / "models" / "events.yml"
    ).read_text(encoding="utf-8")
    # the literal block form: no escaped newlines, SQL readable on its own lines
    assert "\\n" not in staged
    assert "source: |" in staged
    assert "FROM events.events" in staged
    # meaning preserved: the parsed source is the same SQL string
    doc = yaml.safe_load(staged)
    dataset = doc["semantic_model"][0]["datasets"][0]
    assert dataset["source"] == (
        "SELECT id, label\nFROM events.events\nWHERE id IS NOT NULL"
    )

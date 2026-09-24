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

import hashlib
import json
import sys
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
    assert registry_doc["sources"] == [
        {"name": "events", "type": "parquet", "path": str(parquet)}
    ]

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
    assert "sources" not in yaml.safe_load(
        (project / "ariadne.yaml").read_text(encoding="utf-8")
    )
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
    assert "sources" not in yaml.safe_load(
        (project / "ariadne.yaml").read_text(encoding="utf-8")
    )


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
        authoring_cli(["propose-sources", "--file", str(proposal), "--project", str(project)])
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["digest"] and out["sources"] == [
        {"name": "events", "type": "parquet", "path": str(parquet)}
    ]
    assert authoring_cli(["approve-sources", "--digest", "0" * 64, "--project", str(project)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err)["error"]["type"] == "ValueError"
    assert "sources" not in yaml.safe_load(
        (project / "ariadne.yaml").read_text(encoding="utf-8")
    )
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


def test_pyproject_exposes_ariadne_authoring():
    """The console script the spec names is installed."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'ariadne-authoring = "ariadne.authoring_cli:main"' in text

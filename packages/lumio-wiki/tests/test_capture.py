"""Explicit capture of coding-agent sessions and research results (issue #179).

Covers the acceptance criteria through the same in-process surface a client
adapter uses:

- AC1  one reviewable proposal per capture (managed contract, single staged
  proposal, declarative page bound to the transcript bytes);
- AC2  preview before registration/staging (unconfirmed capture registers
  nothing, stages nothing);
- AC3  published content is declarative knowledge (raw transcripts refused,
  hidden reasoning stripped);
- AC4  secret fixtures are redacted and never reach the page, the manifest
  record, or output;
- AC5  one vendor-neutral manifest contract across client fixtures (pi,
  codex, claude-code, hermes, manual);
- AC6  capture is explicit and side-effect-free on normal ingest (flag
  parity, ordinary ingest unchanged).

Also covers the rules: adapters report missing transcripts instead of
fabricating continuity, digest mismatches refuse staging, and capture never
auto-publishes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import lumio_wiki as lw
import pytest
from lumio_wiki.capture import (
    CaptureError,
    CaptureManifest,
    capture_session,
    detect_raw_transcript,
    format_capture_preview,
    load_capture_manifest,
    redact_capture_text,
)

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "lumio" / "fixtures"
CAPTURE_FIXTURES = FIXTURES / "capture"
SECRET_FIXTURES = [
    # (label, secret-bearing text, category asserted in redaction_counts)
    ("api-key", "Used key sk-ant-0123456789abcdef0123 in the run.", "api-key"),
    (
        "signed-url",
        "Fetched https://s3.example/bucket/a?X-Amz-Signature=abc123def456ghi789 during research.",
        "signed-url",
    ),
    (
        "env-dump",
        "export LUMIO_PROVIDER_API_KEY=super-secret-value-123\nkept working",
        "environment",
    ),
    (
        "credential-assignment",
        'config had api_key: "hunter2000secret" inside',
        "credential",
    ),
]


CAPTURE_CONTROL_V2 = """\
version: 2
mode: "categorized"
categories:
  - name: concepts
ontology:
  entity_types:
    session-note: {}
  predicates: {}
  redirects: {}
"""


def _kb(tmp_path: Path):
    """A manifest-adopted Git authoring KB (native managed ingest route)."""
    from lumio_wiki.source_references import SourceReferenceManifest

    repo = _init_repo(tmp_path)
    root = _write_kb(
        repo,
        manifest=SourceReferenceManifest(
            version=1, namespace="urn:uuid:0f9c2b7a-capture-4b1e-9c2d-capturekb000001"
        ),
        control=CAPTURE_CONTROL_V2,
        # ``pages={}`` is falsy in ``_write_kb`` (defaults would apply); one
        # seed page keeps the dict truthy without colliding with test titles.
        pages={"concepts/seed-note.md": _page("seed", title="Seed Note")},
    )
    kb, report = lw.load_knowledge_base(root)
    assert report.is_valid, report
    return kb


def _capture_registry(tmp_path: Path):
    from lumio_wiki.source_registry import SourceRegistry

    return SourceRegistry(tmp_path / "registry")


def _worktree_ingest(kb_root: Path, registry, manifest_path):
    """The native confirmed-capture route (mirrors the CLI's callback)."""
    from lumio_wiki.capture import write_versioned_capture_record
    from lumio_wiki.git_authoring import ingest_into_worktree

    def _ingest(
        raw_bytes,
        content_type,
        filename,
        source_id,
        redacted_markdown,
        safe_manifest,
        transcript_digest,
        transcript_source_path=None,
    ):
        def _persist(source_id, content_hash):
            write_versioned_capture_record(
                registry.root, source_id, content_hash, safe_manifest, transcript_digest
            )

        return ingest_into_worktree(
            kb_root,
            raw_bytes,
            content_type,
            filename,
            source_id,
            redacted_markdown,
            source_registry=registry,
            raw_source_path=transcript_source_path or manifest_path,
            persist_observation=_persist,
        )

    return _ingest


def _page(source_id: str, *, title: str = "Session Findings", body: str = "") -> str:
    body = body or (
        "# Decisions\n\n- Reader returns `not covered` when Evidence is "
        "insufficient (verified against the guardrail).\n\n"
        "# Commands\n\n- `uv run pytest -q tests/test_capture.py` passed "
        "with 12 focused tests.\n"
    )
    return (
        "---\n"
        f'id: "entity:{source_id}"\n'
        f'title: "{title}"\n'
        "entity_types:\n  - session-note\n"
        "category: concepts\n"
        'type: "session note"\n'
        'durability_rationale: "The captured session documents verified findings."\n'
        'tags:\n  - "session-notes"\n'
        'summary: "Verified findings from a captured coding-agent session."\n'
        'lifecycle: "draft"\n'
        'visibility: "internal"\n'
        "sources:\n"
        f'  - id: "{source_id}"\n'
        f'    title: "{source_id} capture"\n'
        "synthetic: false\n"
        "---\n\n" + body
    )


def _manifest_bytes(tmp_path: Path, manifest: CaptureManifest) -> tuple[Path, bytes]:
    """Materialize a manifest file so capture resolves relative transcripts."""
    import msgspec  # type: ignore[import-not-found]

    raw = msgspec.yaml.encode(manifest)
    path = tmp_path / "capture-manifest.yaml"
    path.write_bytes(raw)
    return path, raw


# ---------------------------------------------------------------------------
# Manifest loading and validation.
# ---------------------------------------------------------------------------


def test_load_manifest_rejects_unknown_fields(tmp_path: Path):
    path = tmp_path / "m.yaml"
    path.write_text("client: pi\nsurprise: 1\n")
    with pytest.raises(CaptureError, match="invalid capture manifest"):
        load_capture_manifest(path)


def test_load_manifest_rejects_bad_client_label(tmp_path: Path):
    path = tmp_path / "m.yaml"
    path.write_text("client: Not A Label\n")
    with pytest.raises(CaptureError, match="client must be a lowercase label"):
        load_capture_manifest(path)


def test_load_manifest_rejects_inverted_time_range(tmp_path: Path):
    path = tmp_path / "m.yaml"
    path.write_text(
        'client: pi\nstarted_at: "2026-08-24T10:00:00Z"\nended_at: "2026-08-24T09:00:00Z"\n'
    )
    with pytest.raises(CaptureError, match="started_at is after ended_at"):
        load_capture_manifest(path)


def test_load_manifest_rejects_missing_file(tmp_path: Path):
    with pytest.raises(CaptureError, match="not readable"):
        load_capture_manifest(tmp_path / "absent.yaml")


# ---------------------------------------------------------------------------
# Redaction safety net.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label, secret_text, category", SECRET_FIXTURES)
def test_secret_fixtures_are_redacted_with_counts(label, secret_text, category):
    redacted, counts = redact_capture_text(secret_text)
    assert "sk-ant-" not in redacted
    assert "X-Amz-Signature" not in redacted
    assert "super-secret-value-123" not in redacted
    assert "hunter2000secret" not in redacted
    assert counts.get(category, 0) >= 1, f"{label}: expected a {category} redaction"


def test_hidden_reasoning_blocks_are_stripped_entirely():
    text = "Finding A.\n<think>chain of thought: the user probably wants...</think>\nFinding B."
    redacted, counts = redact_capture_text(text)
    assert "chain of thought" not in redacted
    assert "Finding A." in redacted and "Finding B." in redacted
    assert counts.get("hidden-reasoning", 0) == 1


def test_unclosed_reasoning_tag_strips_to_end_of_text():
    redacted, _ = redact_capture_text("Finding A.\n<think>leaked partial reasoning")
    assert "leaked partial reasoning" not in redacted


def test_private_key_blocks_are_redacted():
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
    redacted, counts = redact_capture_text(f"signing key:\n{pem}\ndone")
    assert "MIIEowIBAAKCAQEA" not in redacted
    assert counts.get("private-key", 0) == 1


def test_plain_prose_is_untouched():
    text = "# Decisions\n\n- `uv run pytest -q` passed with 12 focused tests."
    redacted, counts = redact_capture_text(text)
    assert redacted == text
    assert counts == {}


# ---------------------------------------------------------------------------
# Raw-transcript refusal (AC3).
# ---------------------------------------------------------------------------


def test_session_page_with_chat_turns_is_refused(tmp_path: Path):
    kb = _kb(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")
    manifest_path, manifest_bytes = CAPTURE_FIXTURES / "pi.yaml", raw
    page = _page(
        "session-pi",
        body=(
            "# Transcript\n\n"
            "user: why does it fail?\n"
            "assistant: because of the guardrail.\n"
            "user: ok fix it\n"
            "assistant: done.\n"
        ),
    )
    with pytest.raises(CaptureError, match="raw conversational transcript"):
        capture_session(
            compiled_page_markdown=page,
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            manifest_path=manifest_path,
            source_id="session-pi",
            transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
            confirmed=True,
            ingest=_worktree_ingest(kb.root, _capture_registry(tmp_path), manifest_path),
        )


def test_single_turn_mention_does_not_trigger_refusal():
    # One quoted turn inside declarative knowledge is legitimate; two or
    # more bare chat-turn lines is transcript-shaped and refused.
    assert len(detect_raw_transcript("assistant: said it works")) < 2


def test_two_turn_page_is_refused_as_raw_transcript():
    assert len(detect_raw_transcript("user: hi\nassistant: hello")) >= 2


# ---------------------------------------------------------------------------
# AC2 — preview before registration/staging.
# ---------------------------------------------------------------------------


def test_unconfirmed_capture_registers_and_writes_nothing(tmp_path: Path):
    kb = _kb(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")

    outcome = capture_session(
        compiled_page_markdown=_page("session-preview"),
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "pi.yaml",
        source_id="session-preview",
        transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
        confirmed=False,
    )

    assert outcome.worktree is None
    assert outcome.preview.client == "pi"
    assert outcome.preview.source_id == "session-preview"
    assert "Decisions" in outcome.preview.sections and "Commands" in outcome.preview.sections
    assert not (tmp_path / "registry").exists()
    # The KB itself is untouched.
    assert not any("Session Findings" in p.title for p in kb.pages)


def test_preview_text_lists_sections_and_redaction_counts(tmp_path: Path):
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")
    page = _page("session-preview2").replace(
        "passed with 12 focused tests", "used key sk-ant-0123456789abcdef0123"
    )
    outcome = capture_session(
        compiled_page_markdown=page,
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "pi.yaml",
        source_id="session-preview2",
        transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
    )
    text = format_capture_preview(outcome.preview)
    assert "sections:" in text and "Decisions" in text
    assert "redactions applied: 1 (1 api-key)" in text
    assert "sk-ant-" not in text


# ---------------------------------------------------------------------------
# AC1 — one confirmed capture stages exactly one reviewable proposal.
# ---------------------------------------------------------------------------


def test_confirmed_capture_edits_the_worktree_once(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")

    outcome = capture_session(
        compiled_page_markdown=_page("session-2026-pi"),
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "pi.yaml",
        source_id="session-2026-pi",
        transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, CAPTURE_FIXTURES / "pi.yaml"),
    )

    result = outcome.worktree
    assert result is not None
    assert result.source_id == "session-2026-pi"
    assert len(result.page_paths) == 1
    # Declarative page content, not transcript bytes, landed in the worktree.
    written = (Path(kb.root) / result.page_paths[0]).read_text(encoding="utf-8")
    assert "Verified findings" in written
    assert "Retrieval found no Evidence" not in written
    # The private source registration and versioned capture record live in
    # the private registry root, never inside the Knowledge Base.
    assert registry.get("session-2026-pi").status == "active"
    assert _all_private_capture_contents(registry.root), "no capture record written"


def test_confirmed_capture_binds_transcript_as_source_bytes(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "codex.yaml")

    capture_session(
        compiled_page_markdown=_page("session-2026-codex"),
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "codex.yaml",
        source_id="session-2026-codex",
        transcript_path=CAPTURE_FIXTURES / "codex-session.jsonl",
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, CAPTURE_FIXTURES / "codex.yaml"),
    )

    sources = registry.list()
    assert [s.source_id for s in sources] == ["session-2026-codex"]
    assert sources[0].status == "active"
    # The registered bytes are the REDACTED transcript bytes.
    version = sources[0].versions[-1]
    transcript = (CAPTURE_FIXTURES / "codex-session.jsonl").read_bytes()
    import hashlib

    from lumio_wiki.capture import redact_capture_text

    expected = redact_capture_text(transcript.decode())[0].encode()
    assert version.content_hash == hashlib.sha256(expected).hexdigest()


# ---------------------------------------------------------------------------
# AC4 — secrets never reach the page, the manifest record, or output.
# ---------------------------------------------------------------------------


def test_secrets_never_reach_written_page_or_capture_record(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")
    page = _page(
        "session-secrets",
        body=(
            "# Findings\n\n"
            "- Signed fetch used "
            "https://s3.example/bucket/r?X-Amz-Signature=deadbeefdeadbeefdead "
            "and key sk-ant-998877665544332211 during verification.\n"
        ),
    )

    outcome = capture_session(
        compiled_page_markdown=page,
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "pi.yaml",
        source_id="session-secrets",
        transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, CAPTURE_FIXTURES / "pi.yaml"),
    )

    result = outcome.worktree
    assert result is not None
    markdown = (Path(kb.root) / result.page_paths[0]).read_text(encoding="utf-8")
    assert "sk-ant-998877665544332211" not in markdown
    assert "X-Amz-Signature" not in markdown
    assert "[REDACTED]" in markdown
    for record_bytes in _all_private_capture_contents(registry.root):
        record_text = record_bytes.decode("utf-8")
        assert "sk-ant-998877665544332211" not in record_text
        assert "deadbeef" not in record_text


def test_secret_bearing_transcript_is_registered_redacted(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    transcript = tmp_path / "secret-session.jsonl"
    transcript.write_text(
        '{"role":"assistant","text":"deploy token: ghp_abc123abc123abc123abc123 done"}\n'
    )
    manifest = CaptureManifest(client="pi", project="p")
    manifest_path, manifest_bytes = _manifest_bytes(tmp_path, manifest)

    capture_session(
        compiled_page_markdown=_page("session-secret-transcript"),
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_path=manifest_path,
        source_id="session-secret-transcript",
        transcript_path=transcript,
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, manifest_path),
    )

    # The secret never entered the registered source identity either: the
    # registry content hash is over the REDACTED transcript bytes (raw bytes
    # are hash-only in the registry, ADR-0014 — nothing is written out).
    import hashlib

    source = registry.get("session-secret-transcript")
    redacted_bytes = redact_capture_text(transcript.read_text())[0].encode()
    assert source.versions[-1].content_hash == hashlib.sha256(redacted_bytes).hexdigest()
    assert "ghp_" not in json.dumps(_registry_state(registry), default=str)


def _registry_state(registry) -> dict:
    """The registry's persisted private state as plain data (for asserts)."""
    import msgspec  # type: ignore[import-not-found]

    return msgspec.to_builtins(registry._read())


# ---------------------------------------------------------------------------
# AC5 — one contract across client fixtures, manual fallback.
# ---------------------------------------------------------------------------


def test_manual_manifest_without_transcript_registers_manifest_record(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "manual.yaml")

    outcome = capture_session(
        compiled_page_markdown=_page("session-manual-only"),
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "manual.yaml",
        source_id="session-manual-only",
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, CAPTURE_FIXTURES / "manual.yaml"),
    )

    # The manifest bytes themselves became the private registered source and
    # the versioned capture record exists under the registry root.
    assert outcome.worktree is not None
    assert outcome.worktree.source_id == "session-manual-only"
    assert _all_private_capture_contents(registry.root)


# ---------------------------------------------------------------------------
# Adapter-limitation rules.
# ---------------------------------------------------------------------------


def test_missing_named_transcript_is_reported_not_fabricated(tmp_path: Path):
    kb = _kb(tmp_path)
    manifest = CaptureManifest(client="codex", transcript="vanished.jsonl")
    manifest_path, manifest_bytes = _manifest_bytes(tmp_path, manifest)

    with pytest.raises(CaptureError, match="transcript not found"):
        capture_session(
            compiled_page_markdown=_page("session-gone"),
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            manifest_path=manifest_path,
            source_id="session-gone",
            confirmed=True,
            ingest=_worktree_ingest(kb.root, _capture_registry(tmp_path), manifest_path),
        )


def test_digest_only_manifest_reports_limitation_and_registers_manifest(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    manifest = CaptureManifest(client="pi", transcript="sha256:" + "0" * 64)
    manifest_path, manifest_bytes = _manifest_bytes(tmp_path, manifest)

    outcome = capture_session(
        compiled_page_markdown=_page("session-digest-only"),
        manifest=manifest,
        manifest_bytes=manifest_bytes,
        manifest_path=manifest_path,
        source_id="session-digest-only",
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, manifest_path),
    )

    assert any("digest only" in w for w in outcome.preview.warnings)
    assert outcome.worktree is not None
    assert _all_private_capture_contents(registry.root)


def test_digest_mismatch_refuses_staging(tmp_path: Path):
    kb = _kb(tmp_path)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"role":"user","text":"hello"}\n')
    manifest = CaptureManifest(client="pi", transcript="sha256:" + "f" * 64)
    manifest_path, manifest_bytes = _manifest_bytes(tmp_path, manifest)

    with pytest.raises(CaptureError, match="do not match the digest"):
        capture_session(
            compiled_page_markdown=_page("session-mismatch"),
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            manifest_path=manifest_path,
            source_id="session-mismatch",
            transcript_path=transcript,
            confirmed=True,
            ingest=_worktree_ingest(kb.root, _capture_registry(tmp_path), manifest_path),
        )
    assert not (tmp_path / "registry").exists()


def test_page_must_declare_source_id_before_any_registration(tmp_path: Path):
    kb = _kb(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")
    page = _page("different-id")

    with pytest.raises(CaptureError, match="must declare source_id"):
        capture_session(
            compiled_page_markdown=page,
            manifest=manifest,
            manifest_bytes=raw,
            manifest_path=CAPTURE_FIXTURES / "pi.yaml",
            source_id="session-mismatched",
            transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
            confirmed=True,
            ingest=_worktree_ingest(
                kb.root, _capture_registry(tmp_path), CAPTURE_FIXTURES / "pi.yaml"
            ),
        )
    assert not (tmp_path / "registry").exists()
    assert not any("Session Findings" in p.title for p in kb.pages)


# ---------------------------------------------------------------------------
# AC6 — capture stays optional; ordinary ingest is unchanged.
# ---------------------------------------------------------------------------


def test_ordinary_managed_ingest_still_works_alongside_capture(tmp_path: Path):
    from lumio_wiki.git_authoring import ingest_into_worktree

    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    source = tmp_path / "plain.md"
    source.write_text("# Plain Source\n\nordinary bytes\n")
    page = _page("plain-source", title="Plain Captured Note")
    result = ingest_into_worktree(
        kb.root,
        source.read_bytes(),
        "text/markdown",
        "plain.md",
        "plain-source",
        page,
        source_registry=registry,
    )
    assert result.source_id == "plain-source"
    assert len(result.page_paths) == 1
    # Registry holds the ordinary source; no capture record was created.
    assert not _all_private_capture_contents(registry.root)


# ---------------------------------------------------------------------------
# CLI — preview-first contract over the public command surface.
# ---------------------------------------------------------------------------


def _run_cli(tmp_path: Path, *argv: str | Path) -> tuple[int, str]:
    import contextlib
    import io

    from lumio_wiki.cli import main

    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        try:
            code = main([str(a) for a in argv])
        except SystemExit as exc:  # argparse --help / usage errors
            code = exc.code if isinstance(exc.code, int) else 2
    return code, buf.getvalue() + err.getvalue()


def test_cli_preview_mode_stages_nothing(tmp_path: Path, capsys):
    kb_root = tmp_path / "kb"
    shutil.copytree(FIXTURES / "valid", kb_root)
    page = tmp_path / "page.md"
    page.write_text(_page("session-cli-preview"))

    code, out = _run_cli(
        tmp_path,
        "capture",
        "session",
        kb_root,
        "--compiled-page",
        page,
        "--manifest",
        CAPTURE_FIXTURES / "pi.yaml",
        "--source-id",
        "session-cli-preview",
        "--transcript",
        CAPTURE_FIXTURES / "pi-session.jsonl",
    )

    assert code == 0
    assert "sections:" in out and "Decisions" in out
    assert "redactions applied:" in out
    assert "Preview only" in out
    assert "Staged proposal" not in out
    kb, report = lw.load_knowledge_base(kb_root)
    assert report.is_valid
    assert not any(p.title == "Session Findings" for p in kb.pages)


def test_cli_yes_edits_the_authoring_worktree(tmp_path: Path):
    kb = _kb(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(_page("session-cli-yes"))
    registry = _capture_registry(tmp_path)

    code, out = _run_cli(
        tmp_path,
        "capture",
        "session",
        kb.root,
        "--compiled-page",
        page,
        "--manifest",
        CAPTURE_FIXTURES / "pi.yaml",
        "--source-id",
        "session-cli-yes",
        "--transcript",
        CAPTURE_FIXTURES / "pi-session.jsonl",
        "--source-registry",
        registry.root,
        "--yes",
    )

    assert code == 0
    assert "Captured into the Git authoring worktree" in out
    assert "source:   session-cli-yes" in out
    # Preview prints BEFORE the apply (issue #179 AC2 + Spec review): the
    # sections list is on screen before the worktree outcome, even when
    # --yes is given up front.
    assert out.index("sections:") < out.index("Captured into")
    assert out.index("redactions applied:") < out.index("Captured into")
    assert [s.source_id for s in registry.list()] == ["session-cli-yes"]
    assert _all_private_capture_contents(registry.root)


def test_cli_manifest_secret_fields_are_redacted_in_output(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(_page("session-cli-mf-secret"))
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        "client: pi\n"
        "project: sk-ant-0123456789abcdef0123-leaked\n"
        'started_at: "2026-08-24T09:00:00Z"\n'
        "transcript: session.jsonl\n"
        "artifacts: []\n"
        "redactions: []\n"
    )
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"role":"user","text":"hi"}\n')

    code, out = _run_cli(
        tmp_path,
        "capture",
        "session",
        kb.root,
        "--compiled-page",
        page,
        "--manifest",
        manifest,
        "--source-id",
        "session-cli-mf-secret",
        "--transcript",
        transcript,
        "--source-registry",
        registry.root,
        "--yes",
    )

    assert code == 0
    assert "sk-ant-" not in out
    assert "[REDACTED]" in out
    # The private versioned capture records are redacted too.
    for record_bytes in _all_private_capture_contents(registry.root):
        assert "sk-ant-" not in record_bytes.decode("utf-8")


def test_cli_secret_in_page_is_redacted_in_output(tmp_path: Path):
    kb = _kb(tmp_path)
    page = tmp_path / "page.md"
    page.write_text(
        _page("session-cli-secret").replace(
            "passed with 12 focused tests", "used key sk-ant-0123456789abcdef0123"
        )
    )
    registry = _capture_registry(tmp_path)

    code, out = _run_cli(
        tmp_path,
        "capture",
        "session",
        kb.root,
        "--compiled-page",
        page,
        "--manifest",
        CAPTURE_FIXTURES / "pi.yaml",
        "--source-id",
        "session-cli-secret",
        "--transcript",
        CAPTURE_FIXTURES / "pi-session.jsonl",
        "--source-registry",
        registry.root,
        "--yes",
    )

    assert code == 0
    assert "sk-ant-" not in out
    assert "redactions applied: 1 (1 api-key)" in out


def test_cli_missing_manifest_errors_cleanly(tmp_path: Path):
    kb_root = tmp_path / "kb"
    shutil.copytree(FIXTURES / "valid", kb_root)
    page = tmp_path / "page.md"
    page.write_text(_page("session-cli-missing"))

    code, out = _run_cli(
        tmp_path,
        "capture",
        "session",
        kb_root,
        "--compiled-page",
        page,
        "--manifest",
        tmp_path / "absent.yaml",
        "--source-id",
        "session-cli-missing",
    )
    assert code == 2
    assert "capture manifest not found" in out


def test_quoted_json_credentials_are_redacted_before_capture_staging(tmp_path: Path):
    kb = _kb(tmp_path)
    registry = _capture_registry(tmp_path)
    manifest, raw = load_capture_manifest(CAPTURE_FIXTURES / "pi.yaml")
    page = _page(
        "session-json-secret",
        body=(
            "# Findings\n\n"
            '```json\n{"api_key": "synthetic-json-credential-value"}\n'
            '{"password": "synthetic p@ss\\"word-value"}\n```\n'
        ),
    )

    outcome = capture_session(
        compiled_page_markdown=page,
        manifest=manifest,
        manifest_bytes=raw,
        manifest_path=CAPTURE_FIXTURES / "pi.yaml",
        source_id="session-json-secret",
        transcript_path=CAPTURE_FIXTURES / "pi-session.jsonl",
        confirmed=True,
        ingest=_worktree_ingest(kb.root, registry, CAPTURE_FIXTURES / "pi.yaml"),
    )

    result = outcome.worktree
    assert result is not None
    written = (Path(kb.root) / result.page_paths[0]).read_text(encoding="utf-8")
    assert "synthetic-json-credential-value" not in written
    assert "[REDACTED]" in written


# ---------------------------------------------------------------------------
# G3 fix-a1 (plan 0008 r11): focused native-route capture regressions for the
# accepted F5/F6 findings. Expectations derive from the fixture bytes and the
# SHA-256 oracle — never from implementation output.
# ---------------------------------------------------------------------------

from test_git_authoring import (  # noqa: E402
    _authored_ingest_page,
    _commit,
    _init_repo,
    _write_kb,
)


def _run_capture(kb, page, manifest_path, source_id, *, registry, transcript=None):
    import contextlib
    import io

    from lumio_wiki.cli import main

    args = [
        "capture",
        "session",
        str(kb),
        "--compiled-page",
        str(page),
        "--manifest",
        str(manifest_path),
        "--source-id",
        source_id,
        "--source-registry",
        str(registry),
        "--yes",
    ]
    if transcript is not None:
        args.extend(["--transcript", str(transcript)])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


def _all_private_capture_contents(registry_root):
    """Every capture-record JSON byte under the registry root (layout-free)."""
    root = Path(registry_root)
    contents = []
    for path in sorted(root.rglob("*.json")):
        if "captures" in path.relative_to(root).parts[:1]:
            contents.append(path.read_bytes())
    return contents


def test_native_capture_preserves_distinct_manifests_per_version(tmp_path):
    """F5: repeated captures under one Source ID retain their Capture
    Manifests immutably — changed bytes AND changed metadata for the SAME
    bytes each keep their own record; nothing is overwritten, even with raw
    retention disabled."""
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    registry = tmp_path / "registry"

    one = tmp_path / "one"
    one.mkdir()
    first = _manifest_bytes(one, CaptureManifest(client="pi", project="alpha"))[0]
    two = tmp_path / "two"
    two.mkdir()
    second = _manifest_bytes(two, CaptureManifest(client="pi", project="beta"))[0]
    three = tmp_path / "three"
    three.mkdir()
    third = _manifest_bytes(three, CaptureManifest(client="pi", project="gamma"))[0]
    transcript_a = tmp_path / "a.jsonl"
    transcript_a.write_bytes(b"session one findings\n")
    transcript_b = tmp_path / "b.jsonl"
    transcript_b.write_bytes(b"session TWO findings, different bytes\n")
    page = tmp_path / "page.md"
    page.write_text(_authored_ingest_page("pi-session"))

    # Capture 1: transcript A, manifest alpha.
    code, _out, err = _run_capture(
        kb, page, first, "pi-session", registry=registry, transcript=transcript_a
    )
    assert code == 0, err
    _commit(repo)
    # Capture 2: transcript B (changed bytes), manifest beta.
    page2 = tmp_path / "page2.md"
    page2.write_text(_authored_ingest_page("pi-session"))
    code, _out, err = _run_capture(
        kb, page2, second, "pi-session", registry=registry, transcript=transcript_b
    )
    assert code == 0, err
    _commit(repo)
    # Capture 3: transcript A AGAIN (identical registered bytes), a
    # DIFFERENT manifest (gamma) — same version, distinct observation.
    page3 = tmp_path / "page3.md"
    page3.write_text(_authored_ingest_page("pi-session"))
    code, _out, err = _run_capture(
        kb, page3, third, "pi-session", registry=registry, transcript=transcript_a
    )
    assert code == 0, err

    records = _all_private_capture_contents(registry)
    joined = b"\n".join(records).decode("utf-8", "replace")
    # All three observations survive: two distinct manifests for the SAME
    # registered bytes (alpha/gamma) plus the changed-bytes manifest (beta).
    assert "alpha" in joined
    assert "beta" in joined
    assert "gamma" in joined
    assert len(records) >= 3


def test_native_capture_refuses_git_tracked_manifest_named_transcript(tmp_path, capsys):
    """F6: the tracked-input safety guard must check the ACTUALLY resolved
    original transcript (the manifest-named path), not merely the manifest
    that names it — a Git-tracked transcript inside the authoring repository
    refuses before any registration or write."""
    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    # The transcript is Git-tracked inside the authoring repository; the
    # manifest lives OUTSIDE the repo and names the transcript by ABSOLUTE
    # path, so only a guard that checks the ACTUALLY resolved original
    # transcript refuses (a manifest-only check passes).
    transcript = repo / "tracked-session.jsonl"
    transcript.write_bytes(b"tracked session findings\n")
    _commit(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    manifest_path = _manifest_bytes(
        outside, CaptureManifest(client="pi", transcript=str(transcript))
    )[0]
    page = tmp_path / "page.md"
    page.write_text(_authored_ingest_page("pi-session"))

    code, _out, err = _run_capture(
        kb, page, manifest_path, "pi-session", registry=tmp_path / "registry"
    )
    captured = capsys.readouterr()
    assert code == 1, captured.out + err
    assert "Git-tracked" in captured.err + err
    # No private version was registered and no page was written.
    from lumio_wiki.source_registry import SourceRegistry

    assert all(s.source_id != "pi-session" for s in SourceRegistry(tmp_path / "registry").list())
    assert not (kb / "concepts" / "workbench_press.md").exists()


def test_native_capture_observation_failure_leaves_worktree_unchanged(tmp_path, monkeypatch):
    """R4: required private Capture Manifest storage is part of the native refusal gate."""
    import hashlib

    from lumio_wiki.source_registry import SourceRegistry

    repo = _init_repo(tmp_path)
    kb = _write_kb(repo)
    _commit(repo)
    before = {p.relative_to(kb): p.read_bytes() for p in kb.rglob("*") if p.is_file()}
    manifest_path, _raw = _manifest_bytes(tmp_path, CaptureManifest(client="pi", project="safety"))
    transcript = tmp_path / "session.txt"
    transcript_bytes = b"Verified workshop findings without credentials.\n"
    transcript.write_bytes(transcript_bytes)
    page = tmp_path / "page.md"
    page.write_text(_authored_ingest_page("capture-safety"))
    registry = tmp_path / "registry"
    attempted = []

    def failing_write(path, data):
        attempted.append(path)
        raise OSError("capture record storage unavailable")

    monkeypatch.setattr("lumio_wiki.private_provenance.atomic_write_bytes", failing_write)
    code, out, err = _run_capture(
        kb, page, manifest_path, "capture-safety", registry=registry, transcript=transcript
    )
    assert code == 1, out
    assert "private provenance observation" in err
    assert "immutable registration may remain" in err
    assert "Traceback" not in err
    assert len(attempted) == 1 and attempted[0].is_relative_to(registry / "captures")
    assert {p.relative_to(kb): p.read_bytes() for p in kb.rglob("*") if p.is_file()} == before
    sources = SourceRegistry(registry).list()
    assert [(s.source_id, [v.content_hash for v in s.versions]) for s in sources] == [
        ("capture-safety", [hashlib.sha256(transcript_bytes).hexdigest()])
    ]
    assert _all_private_capture_contents(registry) == []

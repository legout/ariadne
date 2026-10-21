from __future__ import annotations

import hashlib
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
from pathlib import Path

import lumio_wiki as lw
import msgspec
import pytest
from lumio_wiki.ingest import SourceProvenance
from lumio_wiki.legacy_proposals import IngestProposal, SourceChangeImpact, SourceLifecycleChange
from lumio_wiki.mutation import (
    MutationLockError,
    lock_directory,
    mutation_lock,
    resource_identity,
)
from lumio_wiki.records import ValidationReport
from lumio_wiki.source_registry import (
    SourceRegistry,
    SourceRegistryError,
)


def _knowledge_base(tmp_path: Path, source_ids: list[str]):
    root = tmp_path / "kb"
    root.mkdir()
    source_lines = "\n".join(
        f'  - id: "{source_id}"\n    title: "{source_id} source"' for source_id in source_ids
    )
    (root / "policy.md").write_text(
        f"""---
title: "Policy"
aliases: []
tags:
  - "policy"
summary: "The policy."
lifecycle: "approved"
visibility: "public"
sources:
{source_lines}
synthetic: false
---

# Policy

Policy text.
""",
        encoding="utf-8",
    )
    kb, report = lw.load_knowledge_base(root)
    assert report.is_valid, report
    return kb


def _categorized_knowledge_base(tmp_path: Path):
    root = tmp_path / "categorized-kb"
    fixtures = Path(__file__).parents[3] / "tests" / "lumio" / "fixtures"
    shutil.copytree(fixtures / "categorized_kb", root)
    kb, report = lw.load_knowledge_base(root)
    assert report.is_valid, report
    return kb


def test_register_creates_a_single_version_active_identity(tmp_path):
    registry = SourceRegistry(tmp_path / "ingest")

    version = registry.register_source("handbook", b"v1")

    reloaded = SourceRegistry(tmp_path / "ingest")
    source = reloaded.get("handbook")
    assert source.status == "active"
    assert [v.content_hash for v in source.versions] == [version.content_hash]


def test_second_register_of_active_source_is_refused_without_appending(tmp_path):
    # #133 final review: register establishes a NEW identity only. A second
    # registration of an already-known active id must NOT append a version —
    # unreviewed replacement cannot bypass review. Reactivation is the only
    # reviewed path that appends a new Source Version.
    registry = SourceRegistry(tmp_path / "ingest")
    first = registry.register_source("handbook", b"v1")
    prior = _state_snapshot(registry)

    with pytest.raises(SourceRegistryError, match="replacement is not available"):
        registry.register_source("handbook", b"v2")

    source = registry.get("handbook")
    assert [v.content_hash for v in source.versions] == [first.content_hash]
    # No mutation at all: the live and reloaded registry are byte-identical.
    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


def test_second_register_error_does_not_echo_the_source_id(tmp_path):
    # The id may carry secret-bearing material; the generic error must never
    # echo it (mirrors the trigger-validation boundary contract).
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("handbook", b"v1")
    secret_id = "sk-leaked-api-key"

    with pytest.raises(SourceRegistryError) as exc:
        registry.register_source(secret_id, b"v2")

    assert secret_id not in str(exc.value)
    assert "handbook" not in str(exc.value)


def test_proposal_source_lifecycle_metadata_round_trips_without_page_changes():
    change = SourceLifecycleChange(
        action="retire",
        source_id="handbook",
        trigger="source handbook retired",
        impacts=[SourceChangeImpact(page_title="Handbook", status="sole-source-lost")],
    )
    proposal = IngestProposal(
        id="proposal",
        status="staged",
        created_at="2026-07-27T00:00:00+00:00",
        provenance=SourceProvenance(None, None, "source-lifecycle"),
        proposed_pages=[],
        affected_pages=["Handbook"],
        diff="",
        validation_report=ValidationReport(),
        blocked=False,
        source_change=change,
    )

    decoded = msgspec.json.decode(msgspec.json.encode(proposal), type=IngestProposal)

    assert decoded.proposed_pages == []
    assert decoded.source_change == change


def _raise_registry_write() -> None:
    raise OSError("registry persistence failed")


def _state_snapshot(registry: SourceRegistry) -> bytes:
    """Encode the full private registry state for byte-exact comparison."""
    return msgspec.json.encode(registry._state)


def test_register_source_write_failure_restores_live_and_reloaded_state(
    tmp_path, monkeypatch
) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("handbook", b"v1")
    prior = _state_snapshot(registry)
    monkeypatch.setattr(registry, "_write", _raise_registry_write)

    # Register a NEW identity so the write path is reached (a second register
    # of an existing id is refused before persistence — see
    # test_second_register_of_active_source_is_refused_without_appending).
    with pytest.raises(OSError, match="registry persistence failed"):
        registry.register_source("manual", b"v1")

    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


def test_record_retirement_candidate_write_failure_restores_live_and_reloaded_state(
    tmp_path, monkeypatch
) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("handbook", b"v1")
    prior = _state_snapshot(registry)
    monkeypatch.setattr(registry, "_write", _raise_registry_write)

    with pytest.raises(OSError, match="registry persistence failed"):
        registry.record_retirement_candidate("handbook", "watched file missing")

    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


def test_decide_candidate_write_failure_restores_live_and_reloaded_state(
    tmp_path, monkeypatch
) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("handbook", b"v1")
    candidate = registry.record_retirement_candidate("handbook", "watched file missing")
    prior = _state_snapshot(registry)
    monkeypatch.setattr(registry, "_write", _raise_registry_write)

    with pytest.raises(OSError, match="registry persistence failed"):
        registry.confirm_retirement_candidate(candidate.id)

    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


_EXPECTED_RETIREMENT_TRIGGERS = (
    "watched file missing",
    "failed read",
    "object store unavailable",
    "incomplete upload",
)


def test_retirement_candidate_trigger_vocabulary_is_the_controlled_set() -> None:
    # #133: the pipeline exposes ONE shared, public constant naming the only
    # accepted candidate triggers, so every surface (CLI, Workshop) shares the
    # exact safe vocabulary instead of each inventing its own.
    assert tuple(lw.RETIREMENT_CANDIDATE_TRIGGERS) == _EXPECTED_RETIREMENT_TRIGGERS


_INVALID_SOURCE_IDS = (
    "",  # empty
    "   ",  # whitespace only
    "Policy",  # uppercase rejected (lowercase ASCII label only)
    "pol icy",  # internal whitespace
    "pol/icy",  # path separator
    "pol\\icy",  # path separator (backslash)
    "http://example.com/policy",  # URL
    "s3://bucket/policy",  # object-store URI
    "policy:v2",  # colon (scheme/credential separator)
    "a" * 49,  # exceeds the 48-char maximum
    "9policy",  # must start with a letter
    "_policy",  # must start with a letter
    "-policy",  # must start with a letter
    "1" * 64,  # 64-char hash rejected (length + not a letter-led label)
    "sk-abc123secret",  # credential prefix
    "token-policy",  # credential prefix
    "password-vault",  # credential prefix
    "secret-handbook",  # credential prefix
    "api-key-policy",  # credential prefix
)


@pytest.mark.parametrize("source_id", _INVALID_SOURCE_IDS)
def test_register_rejects_invalid_source_id_without_persisting_or_echoing(
    source_id, tmp_path
) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    prior = _state_snapshot(registry)

    with pytest.raises(SourceRegistryError) as exc:
        registry.register_source(source_id, b"bytes")

    # The rejected value is never echoed into the generic error. (The empty /
    # whitespace cases are skipped: the empty string is trivially a substring
    # of every message, so the echo check is only meaningful for real input.)
    if source_id.strip():
        assert source_id not in str(exc.value)
    # Nothing was persisted and the live/reloaded registry is byte-identical.
    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


def test_register_accepts_the_safe_label_contract(tmp_path) -> None:
    # A Maintainer-authored lowercase ASCII label — letters, digits, dot,
    # underscore, hyphen, letter-led, at most 48 chars — is accepted.
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("handbook", b"v1")
    registry.register_source("policy.v2", b"v1")
    registry.register_source("team_handbook", b"v1")
    registry.register_source("release-notes", b"v1")
    registry.register_source("a" * 48, b"v1")  # exactly the maximum length

    ids = {source.source_id for source in registry.list()}
    assert ids == {"handbook", "policy.v2", "team_handbook", "release-notes", "a" * 48}


_SECRET_SOURCE_IDS = (
    "sk-leaked-api-key",
    "token=abc123",
    "/secret/credentials.key",
    "s3://bucket/leaked",
)


_SECRET_CANDIDATE_IDS = (
    "sk-leaked-api-key",
    "token=abc123;password=hunter2",
    "/var/lib/lumio/secret.key",
    "not-a-uuid-hex",
    "deadbeef",  # too short to be a 32-char uuid hex
)


@pytest.mark.parametrize("source_id", _SECRET_SOURCE_IDS)
def test_registry_get_rejects_secret_bearing_source_id_without_echoing(source_id, tmp_path) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("policy", b"v1")

    with pytest.raises(SourceRegistryError) as exc:
        registry.get(source_id)

    assert source_id not in str(exc.value)


@pytest.mark.parametrize("source_id", _SECRET_SOURCE_IDS)
def test_registry_record_candidate_rejects_secret_bearing_source_id(source_id, tmp_path) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("policy", b"v1")
    prior = _state_snapshot(registry)

    with pytest.raises(SourceRegistryError) as exc:
        registry.record_retirement_candidate(source_id, "watched file missing")

    assert source_id not in str(exc.value)
    # No candidate recorded.
    assert registry.list_candidates() == []
    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


@pytest.mark.parametrize("candidate_id", _SECRET_CANDIDATE_IDS)
def test_registry_get_candidate_rejects_secret_bearing_candidate_id(candidate_id, tmp_path) -> None:
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("policy", b"v1")
    real = registry.record_retirement_candidate("policy", "watched file missing")

    with pytest.raises(SourceRegistryError) as exc:
        registry.get_candidate(candidate_id)

    assert candidate_id not in str(exc.value)
    # The real candidate is untouched.
    assert registry.get_candidate(real.id).id == real.id


@pytest.mark.parametrize("candidate_id", _SECRET_CANDIDATE_IDS)
def test_registry_decide_candidate_rejects_secret_bearing_candidate_id(
    candidate_id, tmp_path
) -> None:
    # The registry-level confirm/dismiss must validate the candidate id before
    # lookup or interpolation, so a secret-bearing id is rejected generically
    # and the real candidate is left pending.
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("policy", b"v1")
    real = registry.record_retirement_candidate("policy", "watched file missing")
    prior = _state_snapshot(registry)

    with pytest.raises(SourceRegistryError) as exc:
        registry.confirm_retirement_candidate(candidate_id)
    assert candidate_id not in str(exc.value)

    with pytest.raises(SourceRegistryError) as exc:
        registry.dismiss_retirement_candidate(candidate_id)
    assert candidate_id not in str(exc.value)

    assert _state_snapshot(registry) == prior
    assert registry.get_candidate(real.id).status == "pending"


def test_safe_candidate_trigger_display_masks_unrecognized_secret() -> None:
    # A legacy candidate persisted with a secret-bearing trigger must never have
    # the stored value reflected into the UI. The function returns the fixed
    # generic label and NEVER the stored value.
    secret = "password=hunter2;token=abc123"
    rendered = lw.safe_candidate_trigger_display(secret)
    assert rendered == lw.RETIREMENT_CANDIDATE_TRIGGER_UNRECOGNIZED
    assert secret not in rendered
    # The fallback is the same fixed label regardless of the unrecognized value.
    assert lw.safe_candidate_trigger_display("") == lw.RETIREMENT_CANDIDATE_TRIGGER_UNRECOGNIZED
    assert (
        lw.safe_candidate_trigger_display("upstream repo archived")
        == lw.RETIREMENT_CANDIDATE_TRIGGER_UNRECOGNIZED
    )


def test_safe_lifecycle_trigger_display_masks_unknown_action() -> None:
    # Any action outside the controlled retire/reactivate vocabulary renders the
    # single fixed generic label — including a legacy/future action string that
    # itself carries secret-bearing material. The stored value is never echoed.
    secret_action = "password=hunter2;token=abc123"
    rendered = lw.safe_lifecycle_trigger_display(secret_action)
    assert rendered == lw.SOURCE_LIFECYCLE_TRIGGER_UNRECOGNIZED
    assert secret_action not in rendered
    # Empty / unrecognized values share the same fixed generic fallback.
    assert lw.safe_lifecycle_trigger_display("") == lw.SOURCE_LIFECYCLE_TRIGGER_UNRECOGNIZED
    assert lw.safe_lifecycle_trigger_display("purge") == lw.SOURCE_LIFECYCLE_TRIGGER_UNRECOGNIZED


def test_safe_lifecycle_impact_status_display_masks_unknown_status() -> None:
    # Any status outside the controlled vocabulary renders the single fixed
    # generic label — including a legacy/future status string that itself
    # carries secret-bearing material. The stored value is never echoed.
    secret_status = "purged?token=abc123&password=hunter2"
    rendered = lw.safe_lifecycle_impact_status_display(secret_status)
    assert rendered == lw.SOURCE_LIFECYCLE_IMPACT_STATUS_UNRECOGNIZED
    assert secret_status not in rendered
    assert "token=abc123" not in rendered
    assert "password=hunter2" not in rendered
    # Empty / unrecognized values share the same fixed generic fallback.
    assert (
        lw.safe_lifecycle_impact_status_display("")
        == lw.SOURCE_LIFECYCLE_IMPACT_STATUS_UNRECOGNIZED
    )
    assert (
        lw.safe_lifecycle_impact_status_display("orphaned")
        == lw.SOURCE_LIFECYCLE_IMPACT_STATUS_UNRECOGNIZED
    )


def test_safe_lifecycle_impact_status_display_never_echoes_status_material() -> None:
    # The display label is derived ONLY from the allowlisted status. A
    # legacy/future proposal whose persisted impact status carries a content
    # hash or a secret must never leak it through the rendered label.
    hash_status = "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
    secret_status = "password=hunter2;token=abc123"
    for status in (hash_status, secret_status):
        rendered = lw.safe_lifecycle_impact_status_display(status)
        assert rendered == lw.SOURCE_LIFECYCLE_IMPACT_STATUS_UNRECOGNIZED
        assert status not in rendered
        assert "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08" not in rendered
        assert "password=hunter2" not in rendered
        assert "token=abc123" not in rendered


def test_register_or_reuse_creates_a_new_active_identity(tmp_path):
    registry = SourceRegistry(tmp_path / "ingest")

    version, action = registry.register_or_reuse("handbook", b"v1")

    assert action == "registered"
    source = registry.get("handbook")
    assert source.status == "active"
    assert source.source_id == "handbook"
    assert [v.content_hash for v in source.versions] == [version.content_hash]
    # The version hash is over the original raw bytes (ADR-0014).
    import hashlib

    assert version.content_hash == hashlib.sha256(b"v1").hexdigest()
    assert version.source_id == "handbook"


def test_register_or_reuse_reuses_identical_bytes_idempotently(tmp_path):
    registry = SourceRegistry(tmp_path / "ingest")
    first, first_action = registry.register_or_reuse("handbook", b"v1")
    assert first_action == "registered"
    prior = _state_snapshot(registry)

    reused, action = registry.register_or_reuse("handbook", b"v1")

    assert action == "reused"
    assert reused.content_hash == first.content_hash
    assert reused.source_id == "handbook"
    # No duplicate Source Version: the identity still has exactly one version.
    source = registry.get("handbook")
    assert [v.content_hash for v in source.versions] == [first.content_hash]
    # No mutation at all — the retry is byte-identical to the first registration.
    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


def test_register_or_reuse_changed_bytes_is_rejected_without_mutation(tmp_path):
    registry = SourceRegistry(tmp_path / "ingest")
    first, _ = registry.register_or_reuse("handbook", b"v1")
    prior = _state_snapshot(registry)

    with pytest.raises(SourceRegistryError, match="retire and reactivate"):
        registry.register_or_reuse("handbook", b"v2-changed")

    # No registry or version mutation: the single immutable version is intact.
    source = registry.get("handbook")
    assert [v.content_hash for v in source.versions] == [first.content_hash]
    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior


def test_register_or_reuse_refusal_never_echoes_the_source_id(tmp_path):
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_or_reuse("handbook", b"v1")
    secret_id = "sk-leaked-api-key"

    with pytest.raises(SourceRegistryError) as exc:
        registry.register_or_reuse(secret_id, b"v2")

    assert secret_id not in str(exc.value)
    assert "handbook" not in str(exc.value)


def test_register_or_reuse_rejects_an_unsafe_id_at_the_boundary(tmp_path):
    registry = SourceRegistry(tmp_path / "ingest")

    with pytest.raises(SourceRegistryError):
        registry.register_or_reuse("reports/secret.md", b"v1")
    assert registry.list() == []


_REGISTRY_WRITER_CHILD = textwrap.dedent(
    """
    import os
    import sys

    from lumio_wiki.source_registry import SourceRegistry

    root, source_id, raw = sys.argv[1], sys.argv[2], sys.argv[3]
    release_fd, signal_fd = int(sys.argv[4]), int(sys.argv[5])

    # Open this process's registry instance BEFORE the barrier so both
    # writers hold an already-open pre-mutation view when they race.
    registry = SourceRegistry(root)
    os.write(signal_fd, b"open")
    os.read(release_fd, 1)
    registry.register_source(source_id, raw.encode("utf-8"))
    os.write(signal_fd, b"done")
    os.read(release_fd, 1)
    """
)


def _signal_reader(fd: int, results: queue.Queue) -> None:
    try:
        results.put(os.read(fd, 8))
    except OSError as exc:  # pragma: no cover - defensive
        results.put(exc)


def _await_signal(fd: int, expected: bytes, timeout: float = 120.0) -> None:
    """Block until a writer subprocess signals ``expected`` through ``fd``.

    The blocking pipe read IS the barrier rendezvous; the deadline only
    converts a hung child into a test failure instead of a CI stall.
    """
    results: queue.Queue = queue.Queue()
    reader = threading.Thread(target=_signal_reader, args=(fd, results), daemon=True)
    reader.start()
    try:
        signal: object = results.get(timeout=timeout)
    except queue.Empty:
        signal = None
    assert signal == expected, (
        f"registry writer subprocess did not signal {expected!r} (got {signal!r}): "
        "a hung or crashed writer is a failed rendezvous, not a timing assumption"
    )


def test_source_registry_process_writers_preserve_successful_updates(tmp_path):
    # B02 (Plan 02 / P3): two SEPARATE processes, each with its own
    # already-open SourceRegistry instance, register a different source.
    # Mutations are serialized by the durable per-registry interprocess lock
    # and each registration is recomputed from the state read UNDER that
    # lock, so BOTH successful registrations survive a fresh reload —
    # neither writer loses the other's committed update.
    root = tmp_path / "ingest"
    writers: list[tuple[subprocess.Popen, int, int]] = []
    try:
        for source_id in ("alpha", "beta"):
            release_read, release_write = os.pipe()
            signal_read, signal_write = os.pipe()
            writer = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    _REGISTRY_WRITER_CHILD,
                    str(root),
                    source_id,
                    f"{source_id}-v1",
                    str(release_read),
                    str(signal_write),
                ],
                # The rendezvous pipes must survive the child's default
                # close_fds=True descriptor hygiene.
                pass_fds=(release_read, signal_write),
            )
            os.close(release_read)
            os.close(signal_write)
            writers.append((writer, release_write, signal_read))

        # Barrier 1: both processes hold an already-open registry instance.
        for _writer, _release, signal_read in writers:
            _await_signal(signal_read, b"open")
        # Release both; each process registers a different source.
        for _writer, release_write, _signal in writers:
            os.write(release_write, b"1")
        # Barrier 2: both registrations reported successful commit.
        for _writer, _release, signal_read in writers:
            _await_signal(signal_read, b"done")
        for _writer, release_write, _signal in writers:
            os.write(release_write, b"1")
    finally:
        for _writer, release_write, signal_read in writers:
            os.close(release_write)
            os.close(signal_read)
    for writer, _release, _signal in writers:
        assert writer.wait(timeout=120) == 0

    reloaded = SourceRegistry(root)
    assert {source.source_id for source in reloaded.list()} == {"alpha", "beta"}
    for source_id in ("alpha", "beta"):
        expected_hash = hashlib.sha256(f"{source_id}-v1".encode()).hexdigest()
        assert [v.content_hash for v in reloaded.get(source_id).versions] == [expected_hash]


def test_atomic_write_failure_cleans_temp_files_and_restores_state(tmp_path, monkeypatch):
    # Plan 02 / P3 resource-bound behavior: a persistence failure inside the
    # atomic write path (unique temp file + os.replace) must leave the private
    # registry directory holding EXACTLY the durable file — no leaked temp
    # artifacts a later writer or a portable export could trip over — and the
    # live in-memory state must still agree with the durable state.
    registry = SourceRegistry(tmp_path / "ingest")
    registry.register_source("handbook", b"v1")
    prior = _state_snapshot(registry)

    def fail_replace(src, dst, *args, **kwargs):
        raise OSError("atomic replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="atomic replace failed"):
        registry.register_source("manual", b"v1")
    monkeypatch.undo()

    # Live state agrees with durable state; the durable file is intact.
    assert _state_snapshot(registry) == prior
    assert _state_snapshot(SourceRegistry(tmp_path / "ingest")) == prior
    # No temp file survived the failed write.
    leftovers = sorted(p.name for p in (tmp_path / "ingest").iterdir())
    assert leftovers == ["sources.json"]
    # A retry through the same path succeeds and persists exactly one file.
    registry.register_source("manual", b"v1")
    assert SourceRegistry(tmp_path / "ingest").get("manual").status == "active"
    assert sorted(p.name for p in (tmp_path / "ingest").iterdir()) == ["sources.json"]


def test_registry_lock_is_reentrant_for_nested_reads_and_writes(tmp_path):
    # Lock ownership covers read/check/mutate/commit/rollback, and registry
    # operations legitimately nest (a mutation method reads through get()).
    # Acquiring the same resource lock from nested calls in one thread must
    # reenter rather than deadlock; the durable result is one writer state.
    registry = SourceRegistry(tmp_path / "ingest")
    with mutation_lock(registry.root):
        registry.register_source("handbook", b"v1")
        assert registry.get("handbook").status == "active"
        registry.register_source("policy", b"v1")
    reloaded = SourceRegistry(tmp_path / "ingest")
    assert {source.source_id for source in reloaded.list()} == {"handbook", "policy"}


def test_mutation_lock_files_stay_outside_resource_roots(tmp_path):
    # Lock files must never land in portable Knowledge Base or private store
    # artifacts: they live in the dedicated temp-directory lock directory and
    # are keyed by the normalized resource identity.
    resource = tmp_path / "ingest"
    registry = SourceRegistry(resource)
    registry.register_source("handbook", b"v1")
    with mutation_lock(resource):
        lock_dir = lock_directory()
        assert lock_dir == Path(tempfile.gettempdir()) / "lumio-mutation-locks"
        resolved_resource = resource.resolve()
        assert resolved_resource not in lock_dir.resolve().parents
        assert lock_dir.resolve() not in resolved_resource.parents
        # The private store itself holds only durable registry state.
        assert sorted(p.name for p in resource.iterdir()) == ["sources.json"]


@pytest.mark.parametrize("trigger", _EXPECTED_RETIREMENT_TRIGGERS)
def test_retirement_candidate_accepts_each_controlled_trigger(trigger, tmp_path):
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_source("policy", b"policy-v1")
    candidate = registry.record_retirement_candidate("policy", trigger)
    assert candidate.trigger == trigger
    assert candidate.status == "pending"
    assert registry.get_candidate(candidate.id).trigger == trigger


def test_retirement_candidate_rejects_trigger_outside_controlled_vocabulary(tmp_path):
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_source("policy", b"policy-v1")
    secret = "password=hunter2;token=abc123"
    with pytest.raises(SourceRegistryError) as exc:
        registry.record_retirement_candidate("policy", secret)
    assert secret not in str(exc.value)
    assert registry.list_candidates() == []
    assert registry.get("policy").status == "active"


def test_register_or_reuse_retired_identity_is_rejected_until_reactivation(tmp_path):
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_source("policy", b"policy-v1")
    state = msgspec.structs.replace(
        registry._state, sources=[msgspec.structs.replace(registry.get("policy"), status="retired")]
    )
    registry.restore_state_bytes(msgspec.json.encode(state))  # original retired wire fixture
    prior = _state_snapshot(registry)
    with pytest.raises(SourceRegistryError, match="retired"):
        registry.register_or_reuse("policy", b"policy-v1")
    assert registry.get("policy").status == "retired"
    assert _state_snapshot(registry) == prior


def test_private_registry_activity_does_not_change_kb_or_export_bytes(tmp_path):
    kb = _knowledge_base(tmp_path, ["policy"])
    before = (
        lw.fingerprint_sources(kb.root),
        lw.export_bundle(kb),
        msgspec.json.encode(lw.export_okf_profile1(kb.public_pages())),
    )
    registry = SourceRegistry(tmp_path / "registry")
    registry.register_version("policy", b"policy-v1")
    registry.register_version("policy", b"policy-v2")
    registry.record_retirement_candidate("policy", "watched file missing")
    after = (
        lw.fingerprint_sources(kb.root),
        lw.export_bundle(kb),
        msgspec.json.encode(lw.export_okf_profile1(kb.public_pages())),
    )
    assert after == before


def test_mutation_lock_refuses_unsafe_nested_expansion_without_deadlock(tmp_path):
    # Review blocker 2: sorting each call cannot order a NESTED call that
    # expands an already-held set DOWNWARD in the canonical order — two
    # writers each holding one resource and nesting the wider set wait on
    # each other forever (ABBA). The lock refuses that expansion up front
    # with an actionable MutationLockError instead of entering a possible
    # deadlock; the refusal acquires nothing and the held lock stays intact.
    early = tmp_path / "a-early"
    late = tmp_path / "z-late"
    early.mkdir()
    late.mkdir()
    assert resource_identity(early) < resource_identity(late)

    with mutation_lock(late):
        # Reentrant re-request of the held resource stays legal.
        with mutation_lock(late):
            pass
        # A nested call adding the EARLIER identity is refused before any
        # acquisition — it raises promptly (no timeout/sleep involved).
        with pytest.raises(MutationLockError, match="unsafe nested mutation_lock expansion"):
            with mutation_lock(early, late):
                raise AssertionError("unsafe expansion must never be entered")
    # After the outer hold ends, the refused resource acquires cleanly: the
    # refusal left nothing half-acquired behind.
    with mutation_lock(early):
        pass


def test_mutation_lock_allows_order_preserving_nested_expansion(tmp_path):
    # Review blocker 2, safe side: a nested call may re-request held
    # resources (reentrant) or add resources that sort AFTER everything its
    # thread already holds — canonical order is preserved, so cooperating
    # writers can never cycle.
    early = tmp_path / "a-early"
    late = tmp_path / "z-late"
    early.mkdir()
    late.mkdir()

    with mutation_lock(early):
        with mutation_lock(early, late):
            # Both held: further reentrant requests of each still work.
            with mutation_lock(late):
                pass
            with mutation_lock(early):
                pass
    # Release is complete: both resources re-acquire from scratch.
    with mutation_lock(late, early):
        pass


def test_resource_identity_canonicalizes_case_variants_of_one_location(tmp_path):
    # Review blocker 3: os.path.normcase is a no-op on POSIX, so on a
    # case-insensitive macOS filesystem differently cased spellings of one
    # location would take separate lock identities and race. The identity
    # lower-cases explicitly (conservatively on every platform: over-
    # serializing distinct case-sensitive paths only adds mutual exclusion).
    root = tmp_path / "CamelCase-Store"
    root.mkdir()
    variants = [
        root,
        tmp_path / "camelcase-store",
        tmp_path / "CAMELCASE-STORE",
        tmp_path / "CamelCase-Store",
    ]
    identities = {resource_identity(variant) for variant in variants}
    assert len(identities) == 1
    assert resource_identity(root) == resource_identity(root).lower()

    # One canonical identity means one lock file for every spelling...
    digest = hashlib.sha256(resource_identity(root).encode("utf-8")).hexdigest()
    assert lock_directory() / f"{digest}.lock" == lock_directory() / (
        hashlib.sha256(resource_identity(tmp_path / "camelcase-store").encode("utf-8")).hexdigest()
        + ".lock"
    )

    # ...and one lock end to end: a mutation_lock taken over one spelling is
    # reentered (not re-acquired) through a differently cased spelling.
    registry = SourceRegistry(root)
    registry.register_source("handbook", b"v1")
    with mutation_lock(tmp_path / "camelcase-store"):
        with mutation_lock(root):
            registry.register_source("policy", b"v1")
    reloaded = SourceRegistry(root)
    assert {source.source_id for source in reloaded.list()} == {"handbook", "policy"}

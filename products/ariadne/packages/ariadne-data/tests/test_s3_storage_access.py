"""Named S3 storage profiles — LIVE signed routing, secret lifecycle and
effective-endpoint authority (issue #71/S1; spec 0025 §§7 AC2/AC4–AC6).

Real loopback S3-compatible endpoints (see ``tests/s3_fixture.py``): two
containers with DISTINCT synthetic credentials expose the independently
specified datasets — storage A (retail): count 3, sum 60, EMEA 40; storage B
(analytics): count 2, sum 200. Expected rows/arithmetic come from that
fixture, never from observed implementation output; wrong credentials are
rejected by the fixture itself. Global AWS_* values are deliberately WRONG so
they cannot hide missing profile configuration. No mock connection ever
substitutes for these proofs: everything runs through the real shared builder
(``ariadne.sources.build_connection``) and the real managed runtime.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import ariadne.sources  # noqa: E402
from ariadne import admission as admission_module  # noqa: E402
from ariadne.sources import build_connection, load_registry  # noqa: E402
from tests import s3_fixture as fx  # noqa: E402
from tests.test_git_authoring import (  # noqa: E402
    METRIC_PAGE,
    MODEL_YML,
    POLICY_PAGE,
    REFERENCE_PAGE,
    SEED_NOTES,
    SKILLS_PAGE,
    TABLES_PAGE,
    run_git,
)

STATE = admission_module.proposals.ARIADNE_STATE_DIR
CURRENT = STATE / "current.json"

# One governed metric over the retail source (the test_sources.py minimal-OSI
# pattern): SUM(amount) must come from storage A (60), never storage B (200).
ORDERS_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: orders.orders
        primary_key: [id]
        fields:
          - name: id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: id
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    metrics:
      - name: total_amount
        description: Sum of order amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
"""


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


@pytest.fixture(autouse=True)
def clean_profile_environment(monkeypatch):
    for name in (
        "ARIADE_S1_LOCAL_KEY_ID",
        "ARIADE_S1_LOCAL_SECRET",
        "ARIADE_S1_LOCAL_ENDPOINT",
        "ARIADE_S1_REMOTE_KEY_ID",
        "ARIADE_S1_REMOTE_SECRET",
        "ARIADE_S1_REMOTE_ENDPOINT",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def builder_spy(monkeypatch):
    """Record every registry handed to the shared builder (the one chokepoint)."""
    opened: list[list[str | None]] = []
    real = ariadne.sources.build_connection

    def spy(registry, read_only=True, *, deadline=None):
        opened.append([src.path for src in registry.sources])
        return real(registry, read_only, deadline=deadline)

    monkeypatch.setattr(ariadne.sources, "build_connection", spy)
    return opened


def registry_file(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "ariadne.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


# ------------------------------------------------------------- AC2 (live)


# ------------------------------------------------------------- AC4 (live)


def test_secret_setup_failure_is_redacted_and_closes_connection(tmp_path, monkeypatch):
    """A deterministic setup failure with synthetic credentials and an error
    that echoes the failing statement: neither public plans, returned/chained
    errors nor persisted state reveal any key/token value; the refused setup
    leaves no persistent secret file and no usable connection (spec 0025 §7
    AC4). Missing variables and invalid endpoint values refuse explicitly."""
    fx.require_docker()
    home = tmp_path / "duckdb-home"
    (home / ".duckdb" / "extensions").mkdir(parents=True, exist_ok=True)
    real_extensions = Path.home() / ".duckdb" / "extensions"
    if real_extensions.is_dir():
        shutil.copytree(real_extensions, home / ".duckdb" / "extensions", dirs_exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    a, b = fx.storage_pair(tmp_path / "fixture")
    try:
        fx.export_environment(a, b, monkeypatch)
        registry_path = registry_file(
            tmp_path,
            {
                "storages": fx.profile_definitions(a, b),
                "sources": [
                    {
                        "name": "orders",
                        "type": "parquet",
                        "storage": "local",
                        "path": "s3://retail/orders/orders.parquet",
                    }
                ],
            },
        )
        registry = load_registry(registry_path)
        loads, statements = ariadne.sources.plan(registry)
        joined = "\n".join([*loads, *statements])
        assert "CREATE SECRET" not in joined  # public plans carry no secret SQL

        # WRONG key values: the fixture rejects the signed request, the view
        # binding fails, and the error echoes the statement — never the values
        wrong_key, wrong_secret = "wrongsynthetickey", "wrongsyntheticsecret"
        monkeypatch.setenv("ARIADE_S1_LOCAL_KEY_ID", wrong_key)
        monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", wrong_secret)
        with pytest.raises(Exception) as refused:
            build_connection(registry)
        message = str(refused.value)
        fx.assert_no_secret_values(message, [wrong_key, wrong_secret, a.secret_key])
        assert "orders" in message  # the failing source binding is named
        stored = home / ".duckdb" / "stored_secrets"
        assert not stored.exists() or not any(stored.iterdir())  # nothing persisted

        # a missing required variable refuses naming the variable identity
        monkeypatch.delenv("ARIADE_S1_LOCAL_SECRET", raising=False)
        with pytest.raises(ValueError, match="ARIADE_S1_LOCAL_SECRET"):
            build_connection(registry)

        # an invalid endpoint VALUE refuses during identity resolution
        monkeypatch.setenv("ARIADE_S1_LOCAL_SECRET", a.secret_key)
        monkeypatch.setenv("ARIADE_S1_LOCAL_ENDPOINT", "http://127.0.0.1:1/base/path")
        with pytest.raises(ValueError, match="root path"):
            build_connection(registry)
    finally:
        fx.stop_pair(a, b)


# ---------------------------------------------- fix pass (finding 1, AC4)


def test_secret_creation_failure_redacts_echoed_statement(tmp_path, monkeypatch):
    """Fix finding 1 (spec 0025 §3/AC4): a failing CREATE SECRET whose error
    echoes the full statement — including the key/token literals — is
    redacted: the redaction values are collected BEFORE the secret SQL
    executes, so neither the returned nor a chained error ever carries a
    credential value. Deterministic injected failure on the real owned
    connection; no network is needed (creation fails first)."""

    registry_path = registry_file(
        tmp_path,
        {
            "storages": {
                "local": {
                    "type": "s3",
                    "access_key_id_env": "F1_KEY_ID",
                    "secret_access_key_env": "F1_SECRET",
                    "endpoint_url_env": "F1_ENDPOINT",
                    "scopes": ["s3://retail/"],
                }
            },
            "sources": [
                {
                    "name": "orders",
                    "type": "parquet",
                    "storage": "local",
                    "path": "s3://retail/orders/orders.parquet",
                }
            ],
        },
    )
    key_value, secret_value = "f1-synthetic-key", "f1's-synthetic-secret-with-quote"
    monkeypatch.setenv("F1_KEY_ID", key_value)
    monkeypatch.setenv("F1_SECRET", secret_value)
    monkeypatch.setenv("F1_ENDPOINT", "http://127.0.0.1:9")

    class EchoingFailure:
        """Proxy over the REAL owned connection: LOAD passes through, the
        first CREATE SECRET fails with an error that echoes its statement."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kwargs):
            if "CREATE SECRET" in sql:
                raise duckdb.IOException(f"Fake failure echoing statement: {sql}")
            return self._real.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_connect = duckdb.connect

    def connect(*args, **kwargs):
        return EchoingFailure(real_connect(*args, **kwargs))

    monkeypatch.setattr(duckdb, "connect", connect)
    registry = load_registry(registry_path)
    with pytest.raises(Exception) as refused:
        build_connection(registry)
    message = str(refused.value)
    assert "Fake failure echoing statement" in message  # the injected seam fired
    assert "CREATE SECRET ariadne_local" in message  # the statement WAS echoed
    # no recoverable credential material (spec 0025 §3/AC4): neither the RAW
    # value nor the SQL-DOUBLED-QUOTE form the echoed statement carries
    fx.assert_no_secret_values(message, [key_value, secret_value])
    assert secret_value.replace("'", "''") not in message  # the escaped form too
    assert key_value.replace("'", "''") not in message


# ---------------------------------------------------- AC5/AC6 (live, Git)


def s3_git_project(tmp_path: Path) -> Path:
    """A real temporary Git data project whose human baseline is a COMPLETE
    bundle over one S3 parquet source ``events.events`` — except the registry
    is the commented template: the sources AND storages arrive through the Git
    propose-sources seam (spec 0025 §5)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    (project / "data" / "docs").mkdir(parents=True, exist_ok=True)
    (project / "data" / "docs" / "notes.md").write_text("# Rule notes\n", encoding="utf-8")
    (project / "semantic_layer" / "models").mkdir(parents=True, exist_ok=True)
    (project / "semantic_layer" / "models" / "events.yml").write_text(MODEL_YML, encoding="utf-8")
    pages = {
        "context_layer/tables/events.md": TABLES_PAGE,
        "context_layer/references/joins/events--events.md": REFERENCE_PAGE,
        "context_layer/policies/all-events-count.md": POLICY_PAGE,
        "context_layer/metrics/event_count.md": METRIC_PAGE,
        "context_layer/skills/run-the-demo.md": SKILLS_PAGE,
    }
    for rel, content in pages.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    scope = ["ariadne.yaml", "data/seed_notes.md", "semantic_layer/models/events.yml", *pages]
    run_git(project, "add", "--", *scope)
    message = "human: complete bundle, registry template"
    run_git(project, "commit", "-q", "-m " + message, "--", *scope)
    return project


# ------------------------- fix pass (findings 4 and 5, spec 0025 §§4–5/AC6–7)



"""Named S3 storage profiles — the declarative, inert, credential-free
contract (issue #71/S1; spec 0025 §§2–4, AC1/AC3).

Everything here is offline: parsing, proposal merging, digest identity and
refusals happen with NO environment values, NO network and NO connection —
the builder canary asserts the shared connection is never called. Expected
behaviors come from spec 0025's written contract (the §2 example verbatim),
never from observed implementation output. The live signed-routing,
secret-lifecycle and effective-endpoint approval journeys live in
``tests/test_s3_storage_access.py`` against the real loopback fixture.
"""

from __future__ import annotations

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
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.authoring_sources import (  # noqa: E402
    _resolved_entries,
    candidate_sources,
    resolved_digest,
)
from ariadne.sources import (  # noqa: E402
    StorageProfile,
    build_connection,
    canonical_endpoint,
    load_registry,
    plan,
    validate_storages,
)
from tests.test_git_authoring import run_git  # noqa: E402

SEED_NOTES = "# Seed notes\n\nAll events count.\n"

# Spec 0025 §2's own example registry (shape-faithful; variable names chosen
# by the spec, endpoint values supplied only by the host process).
SPEC_EXAMPLE = """\
storages:
  local:
    type: s3
    access_key_id_env: LOCAL_S3_ACCESS_KEY_ID
    secret_access_key_env: LOCAL_S3_SECRET_ACCESS_KEY
    endpoint_url_env: LOCAL_S3_ENDPOINT_URL
    region_env: LOCAL_S3_REGION
    # session_token_env: LOCAL_S3_SESSION_TOKEN
    url_style: path
    scopes:
      - s3://retail/
  remote:
    type: s3
    access_key_id_env: REMOTE_S3_ACCESS_KEY_ID
    secret_access_key_env: REMOTE_S3_SECRET_ACCESS_KEY
    endpoint_url_env: REMOTE_S3_ENDPOINT_URL
    scopes:
      - s3://analytics/

sources:
  - name: orders
    type: parquet
    storage: local
    path: s3://retail/orders/*.parquet
    table: orders
  - name: events
    type: delta
    storage: remote
    path: s3://analytics/events
"""

PROFILE_ENV_VARS = [
    "LOCAL_S3_ACCESS_KEY_ID",
    "LOCAL_S3_SECRET_ACCESS_KEY",
    "LOCAL_S3_ENDPOINT_URL",
    "LOCAL_S3_REGION",
    "REMOTE_S3_ACCESS_KEY_ID",
    "REMOTE_S3_SECRET_ACCESS_KEY",
    "REMOTE_S3_ENDPOINT_URL",
]


@pytest.fixture(autouse=True)
def no_profile_environment(monkeypatch):
    """The inert contract must hold with NO environment values at all."""
    for name in PROFILE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def builder_canary(monkeypatch):
    """Fail the test if the shared connection builder is ever called."""
    def boom(registry, read_only=True, *, deadline=None):
        raise AssertionError("the inert contract must never open a connection")

    monkeypatch.setattr(ariadne.sources, "build_connection", boom)
    return boom


def write_registry(tmp_path: Path, document: str | dict) -> Path:
    path = tmp_path / "ariadne.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False),
        encoding="utf-8",
    )
    return path


def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    (project / "ariadne.yaml").write_text("# registry template\n", encoding="utf-8")
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m " + "human: initial artifacts")
    return project


# --------------------------------------------------------------------- AC1


def test_profiles_are_inert_and_credential_free(tmp_path, builder_canary):
    """The spec's §2 example parses as credential-free registry data with no
    environment values: profiles validate, references resolve, the public
    plan stays extension/source-DDL text (never secret SQL), and the identity
    carries the COMPLETE referenced profile definitions (spec 0025 §4)."""
    registry = load_registry(write_registry(tmp_path, SPEC_EXAMPLE))
    assert registry.storages is not None
    assert sorted(registry.storages) == ["local", "remote"]
    assert registry.storages["local"].region_env == "LOCAL_S3_REGION"
    assert registry.storages["remote"].region_env is None
    assert registry.storages["remote"].url_style == "path"
    assert [src.storage for src in registry.sources] == ["local", "remote"]

    loads, statements = plan(registry)
    assert "httpfs" in loads and "delta" in loads  # profile use loads httpfs (spec §3)
    joined = "\n".join([*loads, *statements])
    assert "CREATE SECRET" not in joined  # public plans never carry secret SQL (spec §3)
    for name in PROFILE_ENV_VARS:  # and never a variable VALUE (none exist anyway)
        assert name not in joined

    # identity: the resolved declaration embeds each complete referenced
    # profile definition — variable names and scopes, never resolved values
    identity = _resolved_entries(registry.sources, registry.storages)
    orders = next(entry for entry in identity if entry["name"] == "orders")
    assert orders["storage"]["name"] == "local"
    assert orders["storage"]["access_key_id_env"] == "LOCAL_S3_ACCESS_KEY_ID"
    assert orders["storage"]["scopes"] == ["s3://retail/"]
    assert "LOCAL_S3_ENDPOINT_URL" in orders["storage"]["endpoint_url_env"]

    # profile-free digests keep their existing shape: no storage block at all
    plain = write_registry(
        tmp_path / "plain",
        {
            "sources": [
                {"name": "events", "type": "parquet", "path": "data/events.parquet"},
            ]
        },
    )
    plain_registry = load_registry(plain)
    plain_identity = _resolved_entries(plain_registry.sources, plain_registry.storages)
    assert all("storage" not in entry for entry in plain_identity)
    baseline = resolved_digest(plain_identity)  # an old profile-free grant's exact key
    # the same location with REORDERED keys resolves to the same digest: old
    # grants keep their exact key (spec 0025 §4)
    reordered = write_registry(
        tmp_path / "plain",
        yaml.safe_dump(yaml.safe_load(plain.read_text()), sort_keys=True),
    )
    same_again = load_registry(reordered)
    assert (
        resolved_digest(_resolved_entries(same_again.sources, same_again.storages)) == baseline
    )

    # a conflicting profile EDIT inside the candidate refuses, leaving the
    # candidate untouched (spec §5): identical re-proposition is reuse.
    project = git_project(tmp_path / "git")
    api = AuthoringProject(project)
    started = api.start_proposal()
    revision = started["candidate_revision"]
    profiles = {
        "local": {
            "type": "s3",
            "access_key_id_env": "LOCAL_S3_ACCESS_KEY_ID",
            "secret_access_key_env": "LOCAL_S3_SECRET_ACCESS_KEY",
            "endpoint_url_env": "LOCAL_S3_ENDPOINT_URL",
            "scopes": ["s3://retail/"],
        }
    }
    first = api.propose_sources(
        started["proposal"],
        revision,
        sources=[
            {
                "name": "orders",
                "type": "parquet",
                "storage": "local",
                "path": "s3://retail/orders/orders.parquet",
            }
        ],
        storages=profiles,
    )
    assert first["changed"] is True
    resolved, _digest = candidate_sources(project, first["revision"])
    assert resolved is not None and resolved[0]["storage"]["name"] == "local"

    # re-proposing the IDENTICAL profile definition alongside a new source is reuse
    reuse = api.propose_sources(
        started["proposal"],
        first["revision"],
        sources=[
            {
                "name": "more",
                "type": "parquet",
                "storage": "local",
                "path": "s3://retail/more/orders.parquet",
            }
        ],
        storages=profiles,
    )
    doc = yaml.safe_load(
        (project / ".ariadne" / "worktrees" / first["proposal"] / "ariadne.yaml").read_text()
    )
    assert set(doc["storages"]) == {"local"}  # reused, not duplicated

    # a CONFLICTING definition under the same name refuses; candidate untouched
    conflicting = {**profiles, "local": {**profiles["local"], "scopes": ["s3://other/"]}}
    before = reuse["revision"]
    with pytest.raises(ValueError, match="conflicting replacement"):
        api.propose_sources(
            started["proposal"], before, sources=[], storages=conflicting
        )
    record = yaml.safe_load(
        (project / ".ariadne" / "proposals" / f"{first['proposal']}.json").read_text()
    )
    assert record["candidate_revision"] == before  # the refusal consumed nothing


@pytest.mark.parametrize(
    "mutate,label",
    [
        (lambda d: d["storages"]["local"].__setitem__("bogus", True), "unknown profile key"),
        (lambda d: d["storages"]["local"].__setitem__("type", "gs"), "non-s3 type"),
        (
            lambda d: d["storages"]["local"].__setitem__("access_key_id_env", "s3://x"),
            "variable-value-as-name",
        ),
        (lambda d: d["storages"]["local"].__setitem__("scopes", []), "empty scopes"),
        (
            lambda d: d["storages"]["local"].__setitem__(
                "scopes", ["s3://retail/", "s3://retail/"]
            ),
            "duplicate scope",
        ),
        (
            lambda d: d["storages"]["local"].__setitem__("scopes", ["s3://retail"]),
            "unterminated scope",
        ),
        (lambda d: d["storages"]["local"].__setitem__("scopes", ["s3://retail/*"]), "glob scope"),
        (
            lambda d: d["storages"]["local"].__setitem__("scopes", ["http://retail/"]),
            "non-s3 scope",
        ),
        (lambda d: d["storages"]["local"].__setitem__("url_style", "virtual"), "bad url_style"),
        (lambda d: d["sources"][0].__setitem__("storage", "missing"), "undeclared reference"),
        (lambda d: d["sources"][0].__setitem__("storage", 7), "non-name reference"),
    ],
)
def test_invalid_profile_shapes_refuse(tmp_path, builder_canary, mutate, label):
    document = yaml.safe_load(SPEC_EXAMPLE)
    mutate(document)
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, document))


def test_missing_unused_profile_env_values_never_looked_up(tmp_path, monkeypatch):
    """Only USED profiles resolve (spec 0025 §2): with the remote profile
    declared but unreferenced, its env values are never read — sentinel values
    prove it; the refusal that follows names the USED profile's own variable."""
    document = {
        "storages": {
            "local": {
                "type": "s3",
                "access_key_id_env": "USED_KEY",
                "secret_access_key_env": "USED_SECRET",
                "endpoint_url_env": "USED_ENDPOINT",
                "scopes": ["s3://retail/"],
            },
            "unused": {
                "type": "s3",
                "access_key_id_env": "UNUSED_SENTRY_KEY",
                "secret_access_key_env": "UNUSED_SENTRY_SECRET",
                "endpoint_url_env": "UNUSED_SENTRY_ENDPOINT",
                "scopes": ["s3://unreferenced/"],
            },
        },
        "sources": [
            {
                "name": "orders",
                "type": "parquet",
                "storage": "local",
                "path": "s3://retail/orders/orders.parquet",
            }
        ],
    }
    # sentinel values: if the unused profile were ever resolved, its endpoint
    # would appear in the failing path's identity
    monkeypatch.setenv("UNUSED_SENTRY_KEY", "sentry-key-value")
    monkeypatch.setenv("UNUSED_SENTRY_SECRET", "sentry-secret-value")
    monkeypatch.setenv("UNUSED_SENTRY_ENDPOINT", "http://sentry-endpoint.invalid:1")
    monkeypatch.setenv("USED_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setenv("USED_KEY", "used-key")
    # the USED profile's missing secret is the refusal — naming ITS variable
    monkeypatch.delenv("USED_SECRET", raising=False)
    registry = load_registry(write_registry(tmp_path, document))
    with pytest.raises(ValueError, match="USED_SECRET"):
        build_connection(registry)
    monkeypatch.setenv("USED_SECRET", "used-secret")
    with pytest.raises(Exception) as refused:  # and no sentinel anywhere in it
        build_connection(registry)
    assert "sentry" not in str(refused.value).lower()


# --------------------------------------------------------------------- AC3


@pytest.mark.parametrize(
    "scopes,label",
    [
        (["s3://retail/"], "equal scopes of different used profiles"),
        (["s3://retail/data/"], "nested under the other used profile's scope"),
        (["s3://retail/data/deep/"], "deeply nested"),
    ],
)
def test_intersecting_used_profile_scopes_refuse(tmp_path, builder_canary, scopes, label):
    document = yaml.safe_load(SPEC_EXAMPLE)
    document["storages"]["remote"]["scopes"] = scopes
    document["sources"][1]["path"] = scopes[0] + "events"
    with pytest.raises(ValueError):
        load_registry(write_registry(tmp_path, document))


def test_profile_free_direct_s3_source_cannot_inherit_a_named_secret(tmp_path, builder_canary):
    document = yaml.safe_load(SPEC_EXAMPLE)
    document["sources"].append(
        {"name": "stray", "type": "parquet", "path": "s3://retail/other/x.parquet"}
    )
    with pytest.raises(ValueError, match="explicitly"):
        load_registry(write_registry(tmp_path, document))


def test_directory_prefix_boundary_is_respected(tmp_path, builder_canary):
    """``s3://retail/`` does NOT cover ``s3://retail-other/…`` (or any other
    similarly named bucket/directory): boundary-similar paths outside the
    scope validate normally instead of colliding."""
    document = yaml.safe_load(SPEC_EXAMPLE)
    document["sources"].append(
        {"name": "other", "type": "parquet", "path": "s3://retail-other/x.parquet"}
    )
    registry = load_registry(write_registry(tmp_path, document))
    assert [src.name for src in registry.sources] == ["orders", "events", "other"]


def test_ambient_persistent_secret_with_more_specific_scope_refuses(tmp_path, monkeypatch):
    """A test-owned AMBIENT persistent secret covering a MORE SPECIFIC scope
    (``s3://retail/orders/``) than the profile (``s3://retail/``) must make
    named execution REFUSE before any source request — never follow the other
    endpoint (spec 0025 §3, the effective-binding invariant). The persistent
    secret directory is isolated under this test's temp root; operator state
    is untouched."""
    home = tmp_path / "duckdb-home"
    (home / ".duckdb" / "extensions").mkdir(parents=True, exist_ok=True)
    real_extensions = Path.home() / ".duckdb" / "extensions"
    if real_extensions.is_dir():
        shutil.copytree(real_extensions, home / ".duckdb" / "extensions", dirs_exist_ok=True)
    monkeypatch.setenv("HOME", str(home))

    con = duckdb.connect()
    con.execute("LOAD httpfs")
    con.execute(
        "CREATE PERSISTENT SECRET ambient_spy (TYPE S3, PROVIDER CONFIG, "
        "KEY_ID 'ambientkey', SECRET 'ambientsecret', ENDPOINT '127.0.0.1:9', "
        "USE_SSL false, URL_STYLE 'path', REGION 'us-east-1', "
        "SCOPE ['s3://retail/orders/'])"
    )
    con.close()
    stored = home / ".duckdb" / "stored_secrets"
    assert stored.is_dir() and any(stored.iterdir())  # the planted ambient secret

    document = yaml.safe_load(SPEC_EXAMPLE)
    del document["sources"][1]  # only the retail profile is used
    document["sources"][0]["path"] = "s3://retail/orders/orders.parquet"
    monkeypatch.setenv("LOCAL_S3_ACCESS_KEY_ID", "namedkey")
    monkeypatch.setenv("LOCAL_S3_SECRET_ACCESS_KEY", "namedsecret")
    monkeypatch.setenv("LOCAL_S3_ENDPOINT_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("LOCAL_S3_REGION", "us-east-1")
    registry = load_registry(write_registry(tmp_path, document))
    with pytest.raises(ValueError, match="would.*override storage profile"):
        build_connection(registry)
    # the builder's own temporary secret never persisted (spec 0025 §3)
    assert [path.name for path in stored.iterdir()] == ["ambient_spy.duckdb_secret"]


# ------------------------------------------------- endpoint identity (§3)


@pytest.mark.parametrize(
    "raw,canonical,hostport,use_ssl",
    [
        ("http://127.0.0.1:8333", "http://127.0.0.1:8333", "127.0.0.1:8333", False),
        ("http://localhost:80", "http://localhost", "localhost", False),
        ("https://Example.COM:443", "https://example.com", "example.com", True),
        ("  https://host.example:9443/  ", "https://host.example:9443", "host.example:9443", True),
    ],
)
def test_endpoint_canonicalization(raw, canonical, hostport, use_ssl):
    assert canonical_endpoint(raw, "p") == (canonical, hostport, use_ssl)


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://host",
        "http://user:pass@host",
        "http://host/base/path",
        "http://host?query=1",
        "http://host#fragment",
        "http://host:99999",
        "http://",
        "not-a-url",
    ],
)
def test_invalid_endpoint_urls_refuse(raw):
    with pytest.raises(ValueError):
        canonical_endpoint(raw, "p")


def test_storage_profile_identity_is_order_insensitive():
    """Canonical profile representation is deterministic: YAML key ordering
    never changes identity (spec 0025 §2)."""
    first = validate_storages(
        {
            "p": {
                "type": "s3",
                "access_key_id_env": "K",
                "secret_access_key_env": "S",
                "endpoint_url_env": "E",
                "url_style": "path",
                "scopes": ["s3://b/"],
            }
        },
        "test",
    )
    second = validate_storages(
        {
            "p": {
                "scopes": ["s3://b/"],
                "url_style": "path",
                "endpoint_url_env": "E",
                "secret_access_key_env": "S",
                "access_key_id_env": "K",
                "type": "s3",
            }
        },
        "test",
    )
    assert isinstance(first["p"], StorageProfile)
    assert first["p"].identity() == second["p"].identity()

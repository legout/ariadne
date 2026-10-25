"""Explicit machine-local private source configuration (spec 0010 §2.1, JP).

One explicitly selected profile file describes ONE configuration: the private
Source Registry, the canonical original-artifact store, an explicit retention
policy and optionally a separate private exchange connection for a single
Knowledge Base namespace. There is no discovery by cwd, namespace or project
name, and no default profile. Credential fields NAME environment variables;
secret values stay in the host environment and are read only when an
operation actually needs that connection — never for validation, identity or
diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

import msgspec

if TYPE_CHECKING:  # pragma: no cover - import for type checkers only
    from lumio_wiki.artifact_store import SourceArtifactStore
    from lumio_wiki.source_registry import SourceRegistry

#: The only profile format version this resolver understands.
PRIVATE_PROFILE_SCHEMA_VERSION: Final[int] = 1

#: Operation-scoped resources a profile can resolve (plan 0010 JP).
PROFILE_RESOURCE_NEEDS: Final[frozenset[str]] = frozenset({"registry", "artifacts", "exchange"})

_RETENTION_VALUES: Final[tuple[str, ...]] = ("required", "disabled")
_URL_STYLES: Final[tuple[str, ...]] = ("path", "vhost")
_S3_KEYS: Final[frozenset[str]] = frozenset(
    {"kind", "bucket", "prefix", "endpoint", "region", "url_style", "credentials"}
)
_CREDENTIAL_KEYS: Final[frozenset[str]] = frozenset(
    {"access_key_id_env", "secret_access_key_env", "session_token_env"}
)


class PrivateProfileError(Exception):
    """A private source profile is invalid or cannot be resolved.

    Messages are safe operator diagnostics: the loader never reads a
    credential value, and resolvers name declared environment variables, so
    no secret can be echoed into an exception.
    """


class PrivateLocalStore(msgspec.Struct, frozen=True):
    """A canonical local original-artifact store declaration (non-secret)."""

    root: Path


class PrivateS3Connection(msgspec.Struct, frozen=True):
    """An explicit private S3-compatible connection declaration (non-secret).

    Credential fields carry environment variable NAMES only; endpoint,
    region and URL style are explicit non-secret literals.
    """

    bucket: str
    prefix: str
    endpoint: str
    region: str
    url_style: str
    access_key_id_env: str
    secret_access_key_env: str
    session_token_env: str | None = None


class PrivateSourceProfile(msgspec.Struct, frozen=True):
    """The immutable, non-secret declaration read from one selected file."""

    schema_version: int
    namespace: str
    source_registry: Path
    retention: str
    artifact_store: PrivateLocalStore | PrivateS3Connection
    exchange: PrivateS3Connection | None = None


class ResolvedS3Exchange(msgspec.Struct, frozen=True):
    """An explicitly constructed private exchange client bound to its prefix."""

    store: object
    prefix: str


class ResolvedPrivateSources(msgspec.Struct, frozen=True):
    """Operation-scoped adapters plus the deterministic non-secret binding.

    Unused resource entries are ``None``; the adapters are runtime objects
    and are never JSON-serialized. ``binding_digest`` is the SHA-256 of the
    canonical JSON (sorted keys, compact separators, UTF-8) of ``binding``.
    """

    source_registry: SourceRegistry | None
    artifact_store: SourceArtifactStore | None
    exchange: ResolvedS3Exchange | None
    binding: dict[str, object]
    binding_digest: str
    retention_required: bool


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise PrivateProfileError(f"duplicate private profile key {key!r}")
        seen.add(key)
        result[key] = value
    return result


def _require_text(value: object, *, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PrivateProfileError(f"{what} must be a non-empty string")
    return value


def _exact_keys(
    raw: dict[str, object],
    required: frozenset[str] | set[str],
    optional: frozenset[str] | set[str] = frozenset(),
    *,
    what: str,
) -> None:
    unknown = set(raw) - set(required) - set(optional)
    if unknown:
        raise PrivateProfileError(f"unknown {what} field(s): {', '.join(sorted(unknown))}")
    missing = set(required) - set(raw)
    if missing:
        raise PrivateProfileError(f"missing {what} field(s): {', '.join(sorted(missing))}")


def _absolute_directory(value: object, *, what: str) -> Path:
    text = _require_text(value, what=what)
    path = Path(text)
    if not path.is_absolute():
        raise PrivateProfileError(f"{what} must be an absolute directory path")
    return path.resolve()


def _parse_s3_connection(value: object, *, what: str) -> PrivateS3Connection:
    if not isinstance(value, dict):
        raise PrivateProfileError(f"{what} must be an object with the S3 connection shape")
    _exact_keys(value, _S3_KEYS, what=what)
    if value.get("kind") != "s3":
        raise PrivateProfileError(f"{what} must declare kind 's3'")
    bucket = _require_text(value.get("bucket"), what=f"{what} bucket")
    if any(character in bucket for character in ("/", "@", ":")):
        raise PrivateProfileError(f"{what} bucket must be a bare bucket name")
    prefix = value.get("prefix")
    if not isinstance(prefix, str):
        raise PrivateProfileError(f"{what} prefix must be a string")
    prefix = prefix.strip("/")
    if prefix.startswith("/") or ".." in prefix.split("/"):
        raise PrivateProfileError(f"{what} prefix must be a plain object prefix")
    endpoint = _require_text(value.get("endpoint"), what=f"{what} endpoint")
    try:
        parsed = urlsplit(endpoint)
    except ValueError as exc:
        # A malformed endpoint (e.g. a truncated IPv6 literal) is one fixed
        # value-free refusal on the safe inspection/error route (§2.1).
        raise PrivateProfileError(f"{what} endpoint must be a well-formed http(s) URL") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PrivateProfileError(f"{what} endpoint must be an http(s) URL with a host")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise PrivateProfileError(
            f"{what} endpoint must not carry credentials, a query, or a fragment"
        )
    region = _require_text(value.get("region"), what=f"{what} region")
    url_style = value.get("url_style")
    if url_style not in _URL_STYLES:
        raise PrivateProfileError(f"{what} url_style must be one of: {', '.join(_URL_STYLES)}")
    credentials = value.get("credentials")
    if not isinstance(credentials, dict):
        raise PrivateProfileError(f"{what} credentials must name environment variables")
    unknown = set(credentials) - _CREDENTIAL_KEYS
    if unknown:
        raise PrivateProfileError(
            f"{what} credentials must name environment variables (unknown "
            f"field(s): {', '.join(sorted(unknown))}); inline credential values "
            "are not allowed"
        )
    access_key_id_env = _require_text(
        credentials.get("access_key_id_env"), what=f"{what} access_key_id_env"
    )
    secret_access_key_env = _require_text(
        credentials.get("secret_access_key_env"), what=f"{what} secret_access_key_env"
    )
    session_token_env: str | None = None
    if "session_token_env" in credentials:
        session_token_env = _require_text(
            credentials["session_token_env"], what=f"{what} session_token_env"
        )
    return PrivateS3Connection(
        bucket=bucket,
        prefix=prefix,
        endpoint=endpoint,
        region=region,
        url_style=url_style,
        access_key_id_env=access_key_id_env,
        secret_access_key_env=secret_access_key_env,
        session_token_env=session_token_env,
    )


def _parse_artifact_store(value: object) -> PrivateLocalStore | PrivateS3Connection:
    if not isinstance(value, dict):
        raise PrivateProfileError("artifact_store must be an object")
    kind = value.get("kind")
    if kind == "s3":
        return _parse_s3_connection(value, what="artifact_store")
    if kind == "local":
        _exact_keys(value, {"kind", "root"}, what="artifact_store")
        return PrivateLocalStore(
            root=_absolute_directory(value.get("root"), what="artifact_store root")
        )
    raise PrivateProfileError("artifact_store must declare kind 'local' or 's3'")


def _refuse_inside_repository(path: Path, repo_root: Path, *, what: str) -> None:
    """Keep private state outside the Content Repository (spec 0010 §2.1).

    Includes ignored locations inside it: any resolved private selection at
    or below the repository root is refused.
    """
    if path == repo_root or path.is_relative_to(repo_root):
        raise PrivateProfileError(
            f"the selected private {what} must live OUTSIDE the content repository"
        )


def _binding_digest(binding: dict[str, object]) -> str:
    canonical = json.dumps(binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _s3_binding(connection: PrivateS3Connection) -> dict[str, object]:
    credentials: dict[str, str] = {
        "access_key_id_env": connection.access_key_id_env,
        "secret_access_key_env": connection.secret_access_key_env,
    }
    if connection.session_token_env is not None:
        credentials["session_token_env"] = connection.session_token_env
    return {
        "kind": "s3",
        "bucket": connection.bucket,
        "prefix": connection.prefix,
        "endpoint": connection.endpoint,
        "region": connection.region,
        "url_style": connection.url_style,
        "credentials": credentials,
    }


def _binding_resource(store: PrivateLocalStore | PrivateS3Connection) -> dict[str, object]:
    if isinstance(store, PrivateLocalStore):
        return {"kind": "local", "root": str(store.root)}
    return _s3_binding(store)


def _s3_connection_client(
    connection: PrivateS3Connection, environ, *, what: str
) -> tuple[object, str]:
    """Construct the existing obstore adapter from declared values only.

    Missing declared credentials refuse without global/provider-chain
    fallback. The profile stays authoritative over ambient environment
    selection: the top-precedence S3-specific endpoint key
    (``aws_endpoint_url_s3``), the generic endpoint, URL style and signing
    are set explicitly, and credentials come from a static
    declared-reference provider whose token is ``None`` unless the profile
    declares one. Construction uses ``S3Store(bucket, ...)`` directly
    because ``from_url`` re-parses config keys in their Python-facing
    ``aws_``-stripped form, in which the S3-specific endpoint key is not
    parseable (obstore 0.11.1 / object_store 0.14.0 round-trip asymmetry;
    see test_profile_s3_connection_ignores_ambient_selection). Diagnostics
    and bindings keep the declared references, never secret values.
    """
    declared = [
        name
        for name in (
            connection.access_key_id_env,
            connection.secret_access_key_env,
            connection.session_token_env,
        )
        if name is not None
    ]
    missing = [name for name in declared if not environ.get(name)]
    if missing:
        raise PrivateProfileError(
            f"declared credential environment variable(s) for the private {what} "
            f"are not set: {', '.join(missing)}"
        )
    from lumio_wiki.s3_location import _require_obstore

    obstore = _require_obstore()

    def _declared_credentials():
        # Static credentials from the declared references only (documented
        # S3Credential shape): an undeclared session token is None, never an
        # ambient one.
        return {
            "access_key_id": environ[connection.access_key_id_env],
            "secret_access_key": environ[connection.secret_access_key_env],
            "token": (
                environ.get(connection.session_token_env)
                if connection.session_token_env is not None
                else None
            ),
            "expires_at": None,
        }

    config: dict[str, object] = {
        # The S3-specific endpoint key outranks the generic endpoint and the
        # ambient AWS_ENDPOINT_URL_S3 it is derived from (object_store build
        # resolves s3_endpoint before endpoint); setting it explicitly keeps
        # the profile's endpoint effective at the documented top precedence.
        "aws_endpoint_url_s3": connection.endpoint,
        "aws_endpoint": connection.endpoint,
        "aws_region": connection.region,
        "aws_virtual_hosted_style_request": connection.url_style == "vhost",
        "aws_skip_signature": False,
    }
    if what == "exchange":
        # J4 amendment (spec 0010 §6 r4): ONLY exchange clients pin conditional
        # copy-if-absent, required by the streaming staging/copy transport.
        # Artifact-store and publication construction stay unchanged.
        config["copy_if_not_exists"] = "multipart"
    client_options: dict[str, object] | None = (
        {"allow_http": True} if connection.endpoint.startswith("http://") else None
    )
    try:
        store = obstore.store.S3Store(
            connection.bucket,
            config=config,
            client_options=client_options,
            credential_provider=_declared_credentials,
        )
    except Exception as exc:
        raise PrivateProfileError(
            f"could not construct the private {what} connection: {exc}"
        ) from exc
    return store, connection.prefix


def _declaration_from_object(raw: dict, *, repo_root: Path, namespace: str) -> PrivateSourceProfile:
    """Validate one parsed profile object against an explicit repository
    root and namespace (internal shared seam, plan 0010 JP/J5a).

    ``load_private_profile`` and the prospective empty-setup preview share
    this one schema/namespace/containment implementation; the public loader
    keeps its adopted-KB precondition, while setup's preview passes the
    selected repository root and namespace directly.
    """
    _exact_keys(
        raw,
        {"schema_version", "namespace", "source_registry", "retention", "artifact_store"},
        {"exchange"},
        what="private profile",
    )
    version = raw["schema_version"]
    if type(version) is not int or version != PRIVATE_PROFILE_SCHEMA_VERSION:
        raise PrivateProfileError(
            f"private profile schema_version must be {PRIVATE_PROFILE_SCHEMA_VERSION}"
        )
    declared = _require_text(raw["namespace"], what="private profile namespace")
    if declared != namespace:
        raise PrivateProfileError(
            f"the profile namespace {declared!r} does not match the selected "
            f"namespace {namespace!r}"
        )
    retention = raw["retention"]
    if retention not in _RETENTION_VALUES:
        raise PrivateProfileError(
            f"private profile retention must be one of: {', '.join(_RETENTION_VALUES)}"
        )
    source_registry = _absolute_directory(raw["source_registry"], what="source_registry")
    artifact_store = _parse_artifact_store(raw["artifact_store"])
    exchange: PrivateS3Connection | None = None
    if raw.get("exchange") is not None:
        exchange = _parse_s3_connection(raw["exchange"], what="exchange")
    _refuse_inside_repository(source_registry, repo_root, what="Source Registry directory")
    if isinstance(artifact_store, PrivateLocalStore):
        _refuse_inside_repository(artifact_store.root, repo_root, what="artifact store directory")
    return PrivateSourceProfile(
        schema_version=version,
        namespace=declared,
        source_registry=source_registry,
        retention=retention,
        artifact_store=artifact_store,
        exchange=exchange,
    )


def _load_declaration(
    profile_path: Path, *, repo_root: Path, namespace: str
) -> PrivateSourceProfile:
    """Read and validate one profile file against an explicit repository
    root and namespace (internal; no adopted-KB precondition)."""
    # The profile FILE itself stays outside the Content Repository too
    # (§2.1), including ignored locations — resolved before its contents are
    # read, so an inside placement never reaches parsing or any resolution.
    try:
        resolved_profile = profile_path.resolve()
    except OSError as exc:
        raise PrivateProfileError(f"cannot resolve the private profile file: {exc}") from exc
    _refuse_inside_repository(resolved_profile, repo_root, what="profile file")
    try:
        raw_bytes = profile_path.read_bytes()
    except OSError as exc:
        raise PrivateProfileError(
            f"cannot read the private profile file: {exc.strerror or exc}"
        ) from exc
    try:
        raw = json.loads(raw_bytes, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PrivateProfileError(f"the private profile is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PrivateProfileError("the private profile must be a single JSON object")
    return _declaration_from_object(raw, repo_root=repo_root, namespace=namespace)


def load_private_profile(profile_path: str | Path, *, kb_root: str | Path) -> PrivateSourceProfile:
    """Read and validate ONE explicitly selected private profile file.

    Validates schema, namespace and containment against the selected
    Knowledge Base and returns the immutable non-secret declaration. This
    opens no registry/store and reads no credential values.
    """
    from lumio_wiki.git_authoring import GitAuthoringError, resolve_repository
    from lumio_wiki.source_references import (
        SourceReferenceError,
        load_source_reference_manifest,
    )

    kb = Path(kb_root)
    try:
        repo_root, _subtree = resolve_repository(kb)
        manifest = load_source_reference_manifest(kb)
    except (GitAuthoringError, SourceReferenceError) as exc:
        raise PrivateProfileError(
            f"cannot validate the private profile against the selected Knowledge Base: {exc}"
        ) from exc
    if manifest is None:
        raise PrivateProfileError(
            "the selected Knowledge Base has no Source Reference Manifest; a private "
            "profile requires an adopted Git-authoring Knowledge Base"
        )
    return _load_declaration(Path(profile_path), repo_root=repo_root, namespace=manifest.namespace)


def resolve_private_profile(
    profile: PrivateSourceProfile,
    *,
    kb_root: str | Path,
    needs: Iterable[str],
    environ: Mapping[str, str] | None = None,
) -> ResolvedPrivateSources:
    """Resolve only the requested resources into operation-scoped adapters.

    ``needs`` is a set drawn from ``registry``, ``artifacts`` and
    ``exchange``. With ``environ=None`` the current process environment is
    read explicitly at call time; declared credential variables that are
    missing refuse without global/provider-chain fallback. The returned
    ``binding``/``binding_digest`` cover namespace, retention and only the
    requested resource declarations/effective identities — never a
    credential value.
    """
    from lumio_wiki.source_references import (
        SourceReferenceError,
        load_source_reference_manifest,
    )

    requested = frozenset(needs)
    unknown = requested - PROFILE_RESOURCE_NEEDS
    if unknown:
        raise PrivateProfileError(
            f"unknown private profile resource need(s): {', '.join(sorted(unknown))}"
        )
    kb = Path(kb_root)
    try:
        manifest = load_source_reference_manifest(kb)
    except SourceReferenceError as exc:
        raise PrivateProfileError(
            f"cannot validate the private profile against the selected Knowledge Base: {exc}"
        ) from exc
    if manifest is None or manifest.namespace != profile.namespace:
        raise PrivateProfileError(
            "the selected Knowledge Base namespace does not match the private profile"
        )
    environment = os.environ if environ is None else environ
    source_registry: SourceRegistry | None = None
    artifact_store: SourceArtifactStore | None = None
    exchange: ResolvedS3Exchange | None = None
    if "registry" in requested:
        from lumio_wiki.source_registry import SourceRegistry as _SourceRegistry

        try:
            source_registry = _SourceRegistry(profile.source_registry)
        except OSError as exc:
            raise PrivateProfileError(
                f"cannot open the selected private Source Registry: {exc}"
            ) from exc
    if "artifacts" in requested:
        store = profile.artifact_store
        if isinstance(store, PrivateLocalStore):
            from lumio_wiki.artifact_store import LocalDirectoryArtifactStore

            try:
                artifact_store = LocalDirectoryArtifactStore(store.root)
            except OSError as exc:
                raise PrivateProfileError(
                    f"cannot open the selected private artifact store: {exc}"
                ) from exc
        else:
            from lumio_wiki.artifact_store import S3ArtifactStore

            client, prefix = _s3_connection_client(store, environment, what="artifact store")
            artifact_store = S3ArtifactStore(client, prefix)
    if "exchange" in requested:
        if profile.exchange is None:
            raise PrivateProfileError(
                "the selected private profile declares no private exchange connection"
            )
        client, prefix = _s3_connection_client(profile.exchange, environment, what="exchange")
        exchange = ResolvedS3Exchange(store=client, prefix=prefix)
    binding: dict[str, object] = {
        "schema_version": PRIVATE_PROFILE_SCHEMA_VERSION,
        "namespace": profile.namespace,
        "retention": profile.retention,
    }
    if source_registry is not None:
        binding["source_registry"] = {"kind": "local", "root": str(profile.source_registry)}
    if artifact_store is not None:
        binding["artifact_store"] = _binding_resource(profile.artifact_store)
    if "exchange" in requested and profile.exchange is not None:
        binding["exchange"] = _s3_binding(profile.exchange)
    return ResolvedPrivateSources(
        source_registry=source_registry,
        artifact_store=artifact_store,
        exchange=exchange,
        binding=binding,
        binding_digest=_binding_digest(binding),
        retention_required=profile.retention == "required",
    )

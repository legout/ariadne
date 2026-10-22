"""Optional local Lumio binding for spec0029 r2; no SDK import in standalone."""

# pyright: reportMissingImports=false
# Optional SDK is qualified in the external M1 environment, not the editor's environment.

import copy
import hashlib
import importlib.metadata
import importlib.util
import json
import sys
from pathlib import Path

import yaml

SUPPORT = {
    "storage": "local-immutable",
    # T2 (spec0029 §1.5, 2026-10-20): the `reference` profile joins the
    # supported integrated kinds — ONLY after complete native validation of
    # every Reference annotation across the captured candidate. Dataset/
    # table/computation/skill profiles and unrelated extensions still refuse.
    "profiles": ["metric", "policy", "reference"],
    # Q2 (spec0029 §1.2, 2026-10-20): query_metrics and list_datasets join
    # the supported integrated operations. A2 (spec0029 §1.3) adds the three
    # scoped SDK navigation operations; T2 (spec0029 §1.5) adds resolve_term
    # over the pinned structured References — every other r2 refusal stands.
    "operations": [
        "get_metric",
        "discover",
        "list_metrics",
        "query_metrics",
        "list_datasets",
        "list_context_pages",
        "read_context_page",
        "search_context",
        "resolve_term",
    ],
    "unsupported": [
        "query_detail",
        "query_records",
        "define_metric",
        "save_example",
        "search_examples",
    ],
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def selector(root):
    path = Path(root) / "context_integration.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text())
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "mode", "subtree", "namespace", "profile"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or data["mode"] != "integrated"
        or data["subtree"] != "knowledge"
        or data["profile"] != "ariadne-context/1"
        or not isinstance(data["namespace"], str)
        or not data["namespace"]
    ):
        raise ValueError(
            "unsupported or malformed context_integration.yaml; no standalone fallback"
        )
    return data


def knowledge_path(rel):
    pure = Path(rel)
    return (
        pure.parts[:1] == ("knowledge",)
        and len(pure.parts) >= 2
        and (
            pure.suffix.lower() == ".md"
            or rel in ("knowledge/lumio.yaml", "knowledge/.lumio-authoring.yaml")
        )
        and not any(part in (".", "..") for part in pure.parts)
    )


def candidate(root, kb_root, revision):
    """Reuse the producer's captured schema/catalog gate, then apply consumer support."""
    selected = selector(root)
    if selected is None:
        return None, []
    from lumio_wiki.ariadne_context import inspect_ariadne_candidate
    from lumio_wiki.git_authoring import capture_revision

    inspection = inspect_ariadne_candidate(str(kb_root), revision, namespace=selected["namespace"])
    errors = [item.message for item in inspection.diagnostics]
    captured = capture_revision(kb_root, revision)
    for page in captured.kb.pages:
        profile = page.ariadne_profile
        if profile is None:
            continue
        where = f"knowledge/{page.path}"
        if profile.kind not in SUPPORT["profiles"]:
            errors.append(f"{where}: unsupported Ariadne profile kind '{profile.kind}'")
        elif profile.kind == "reference":
            # T2 (spec0029 §1.5): the structured declaration (native.ariadne)
            # and the Core-attached disclosure slot (native.ariadne_evidence)
            # ARE the Reference contract; every other technical extension —
            # and any authored evidence value as authority — still refuses.
            if (
                set(profile.native)
                & {
                    "resource",
                    "observed_value_columns",
                    "attestation",
                    "attester",
                    "runtime",
                    "dataset_sources",
                }
                or profile.core_ref is not None
            ):
                errors.append(f"{where}: unsupported technical Ariadne profile extension")
        elif (
            set(profile.native)
            & {
                "ariadne",
                "ariadne_evidence",
                "resource",
                "observed_value_columns",
                "attestation",
                "attester",
                "runtime",
                "dataset_sources",
            }
            or profile.core_ref is not None
        ):
            errors.append(f"{where}: unsupported technical Ariadne profile extension")
    if not errors:
        expected = set()
        for path in sorted((Path(root) / "semantic_layer" / "models").glob("*.y*ml")):
            doc = yaml.safe_load(path.read_text()) or {}
            for model in doc.get("semantic_model") or []:
                expected.update(
                    (model["name"], metric["name"]) for metric in model.get("metrics") or []
                )
        actual = {
            (page.ariadne_profile.metric_ref.model, page.ariadne_profile.metric_ref.metric)
            for page in captured.kb.pages
            if page.ariadne_profile is not None and page.ariadne_profile.kind == "metric"
        }
        if actual != expected:
            errors.append(
                "knowledge: every native metric requires exactly one matching Context Binding"
            )
    return captured, errors


def _module_root(name):
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin is None:
        raise ValueError(f"execution identity unavailable: {name}")
    path = Path(spec.origin).resolve()
    return path.parent if path.name == "__init__.py" else path


def execution_identity():
    result = {"python": {"version": sys.version, "abi": sys.implementation.cache_tag}}
    for name, distribution in (
        ("ariadne", "ariadne-data"),
        ("lumio_wiki", "lumio-wiki"),
        ("sqlglot", "sqlglot"),
        ("duckdb", "duckdb"),
        ("_duckdb", "duckdb"),
        ("msgspec", "msgspec"),
        ("yaml", "PyYAML"),
        ("jsonschema", "jsonschema"),
    ):
        root = _module_root(name)
        files = (
            [root]
            if root.is_file()
            else sorted(
                p
                for p in root.rglob("*")
                if p.is_file() and p.suffix in (".py", ".so", ".json", ".yaml", ".yml")
            )
        )
        if not files:
            raise ValueError(f"execution content unavailable: {name}")
        result[name] = {
            "version": importlib.metadata.version(distribution),
            "content": digest(
                [
                    [
                        p.name if root.is_file() else p.relative_to(root).as_posix(),
                        hashlib.sha256(p.read_bytes()).hexdigest(),
                    ]
                    for p in files
                ]
            ),
        }
    return result


def validation_build_identity(root):
    """Standalone never resolves the optional SDK, even for evidence applicability."""
    if not (Path(root) / "context_integration.yaml").is_file():
        return None
    return execution_identity()


def require_validation_build(evidence, identity):
    if identity is not None and evidence.get("execution_identity") != identity:
        raise ValueError("integrated validation build identity mismatch; revalidation required")


def core_binding(record, evidence):
    return {
        "commit": record["commit"],
        "artifact_digest": record["artifact_digest"],
        "source_digest": record["source_digest"],
        "source_declaration_digest": record["source_declaration_digest"],
        "source_identity_digest": digest(record["sources"]),
        "storage_bindings_digest": digest(record["storage_bindings"]),
        "review_digest": record["review_digest"],
        "validation_digest": digest(evidence),
        "contracts_digest": digest(record.get("contracts") or {}),
    }


def _binding_inventory(captured, scope):
    from lumio_wiki.ariadne_context import policy_closure

    inventory = []
    for page in captured.kb.pages:
        profile = page.ariadne_profile
        if profile is None or profile.kind != "metric":
            continue
        if page.visibility not in scope:
            raise ValueError("required metric context is outside the operator Visibility Scope")
        closure, diagnostics = policy_closure(
            captured.kb.pages, profile, namespace=captured.manifest.namespace, scope=scope
        )
        if diagnostics:
            raise ValueError(
                "required Policy Closure is unavailable in the operator Visibility Scope"
            )
        by_id = {p.id: p for p in captured.kb.pages}

        def identity(p):
            return {
                "entity_id": p.id,
                "path": p.path,
                "content_digest": hashlib.sha256(captured.content[p.path]).hexdigest(),
            }

        inventory.append(
            {
                "model": profile.metric_ref.model,
                "metric": profile.metric_ref.metric,
                "entity": identity(page),
                "policies": [identity(by_id[r.entity_id]) for r in closure],
            }
        )
    return sorted(inventory, key=lambda item: (item["model"], item["metric"]))


def _s3_destination_parts(destination: str) -> tuple[str, str]:
    """Split one credential-free ``s3://bucket/prefix`` destination."""
    from urllib.parse import urlsplit

    parts = urlsplit(str(destination))
    if parts.scheme != "s3" or not parts.netloc or parts.username or parts.password:
        raise ValueError(
            "the integrated S3 destination must be a credential-free "
            "s3://bucket/prefix URI"
        )
    bucket = parts.netloc
    prefix = parts.path.strip("/")
    if not prefix or any(segment in (".", "..") for segment in prefix.split("/")):
        raise ValueError(
            f"the integrated S3 destination needs a nonempty key prefix: {destination!r}"
        )
    return bucket, prefix


def _declared_knowledge_profile(root: Path, name: str):
    """The candidate's own declared Knowledge storage profile (env NAMES)."""
    from ariadne import sources

    registry = sources.load_registry(Path(root) / "ariadne.yaml")
    profile = (registry.storages or {}).get(name)
    if profile is None:
        raise ValueError(
            f"storage profile {name!r} is not declared in the candidate ariadne.yaml; "
            "an S3 Knowledge destination requires its explicit declaration"
        )
    return profile


def _require_scope_coverage(profile, destination: str) -> None:
    """The declared scopes must contain the complete publication destination."""
    if not any(
        destination == scope.rstrip("/") or destination.startswith(scope)
        for scope in profile.scopes
    ):
        raise ValueError(
            f"storage profile {profile.name!r} scopes do not contain the complete "
            f"publication destination {destination}"
        )


def _s3_transport(profile, binding, bucket: str):
    """The obstore client plus the exact non-secret transport settings the
    native effective-identity builder AND the client both honor (the SDK
    CLI's documented ``from_url`` wiring: endpoint/region into the target
    config, the HTTP scheme into ``allow_http``, and the declared native
    URL style honored through obstore's documented option). Credentials come
    only from the declared ENV NAMES and never enter the returned identity
    view; the optional obstore dependency resolves only inside this call,
    so standalone Core never imports it."""
    import os

    try:
        import obstore  # pyright: ignore[reportMissingImports] — optional [s3] extra
    except ImportError as exc:
        raise ValueError(
            "the S3 Knowledge transport needs the optional obstore dependency "
            "(lumio-wiki[s3]); there is no local fallback"
        ) from exc

    def _value(variable: str, what: str) -> str:
        value = os.environ.get(variable)
        if value is None or not value.strip():
            raise ValueError(
                f"storage profile {profile.name!r}: environment variable {variable} "
                f"({what}) is not set — the host process supplies declared values; "
                "no credential fallback"
            )
        return value

    config: dict[str, str | bool] = {
        "aws_region": binding.region,
        "aws_endpoint": binding.endpoint,
        "aws_access_key_id": _value(profile.access_key_id_env, "access key id"),
        "aws_secret_access_key": _value(profile.secret_access_key_env, "secret access key"),
    }
    if profile.session_token_env is not None:
        config["aws_session_token"] = _value(profile.session_token_env, "session token")
    if binding.url_style == "vhost":
        config["virtual_hosted_style_request"] = True  # obstore-documented S3 option
    client_options: dict[str, bool] = {"allow_http": not binding.use_ssl}
    store = obstore.store.from_url(f"s3://{bucket}", config=config, client_options=client_options)
    # The frozen identity view is credential-free: exactly the non-secret
    # endpoint/region/transport keys the native identity builder reads.
    target_config = {
        key: value
        for key, value in config.items()
        if key not in ("aws_access_key_id", "aws_secret_access_key", "aws_session_token")
    }
    return store, target_config, client_options


def _admission_s3_binding(root: Path, storage_profile, destination: str):
    """Resolve the explicitly selected Knowledge profile at admission: the
    candidate's declared env-NAMES profile, its resolved non-secret binding,
    scope coverage of the exact destination and the native effective target
    identity — every piece frozen into the composite consent (spec0029 r6)."""
    from lumio_wiki.s3_location import S3Location

    from ariadne import sources

    profile = _declared_knowledge_profile(root, storage_profile)
    binding = sources.resolve_binding(profile)  # env values; never a secret in output
    bucket, prefix = _s3_destination_parts(destination)
    _require_scope_coverage(profile, destination)
    store, target_config, client_options = _s3_transport(profile, binding, bucket)
    # The admission-side transport view stays unpinned: native preview and
    # publication observe and advance the pointer through the same store.
    location = S3Location(
        store,
        prefix,
        store_uri=f"s3://{bucket}",
        target_config=target_config,
        client_options=client_options,
    )
    return profile, binding, location


def _frozen_s3_runtime(manifest: dict):
    """Rebuild the pinned S3 reader from the FROZEN Bound Release binding.

    The declaration's env NAMES supply values in the executing process; the
    resolved endpoint/region/URL style/scopes and the native effective target
    identity must equal the frozen non-secret binding — any drift refuses
    before store access, SQL or an analytical-registry fallback (r6)."""
    from lumio_wiki.artifact_store import local_publication_metadata_store
    from lumio_wiki.s3_location import S3Location

    from ariadne import sources

    name = manifest.get("storage_profile")
    declaration = manifest.get("storage_declaration") or {}
    if not isinstance(name, str) or not name or not isinstance(declaration, dict):
        raise ValueError("the S3 Bound Release carries no frozen storage profile declaration")
    profile = sources.profile_from_identity(name, declaration)
    binding = sources.resolve_binding(profile)
    frozen = manifest.get("storage_binding") or {}
    if (
        binding.endpoint != frozen.get("endpoint")
        or binding.region != frozen.get("region")
        or binding.url_style != frozen.get("url_style")
        or sorted(binding.scopes) != sorted(frozen.get("scopes") or [])
    ):
        raise ValueError(
            "the resolved storage endpoint/region/style/scopes do not match the "
            "frozen Bound Release binding; a drifted endpoint refuses before any "
            "store access or SQL"
        )
    identity = manifest.get("storage_target_identity")
    if not isinstance(identity, str) or not identity:
        raise ValueError("the S3 Bound Release carries no frozen target identity")
    bucket, prefix = _s3_destination_parts(manifest["destination"])
    store, target_config, client_options = _s3_transport(profile, binding, bucket)
    # The reader is IMMUTABLY pinned to the admitted Published Version —
    # never the moving pointer (the SDK verifier refuses an unpinned
    # location before any read).
    location = S3Location(
        store,
        prefix,
        version=manifest["knowledge"]["published_version"],
        store_uri=f"s3://{bucket}",
        target_config=target_config,
        client_options=client_options,
    )
    if location.effective_target_identity != identity:
        raise ValueError(
            "the effective S3 target identity does not match the frozen Bound "
            "Release identity; refusing before any store access or SQL"
        )
    return location, local_publication_metadata_store(identity)


def prepare_release(
    project,
    proposal,
    revision,
    review,
    evidence,
    destination,
    expected_current,
    scope,
    mapping_selections=(),
    storage_profile=None,
):
    """Stateless composite preview; future receipts never enter its consent digest."""
    import msgspec
    from lumio_wiki import git_authoring as native
    from lumio_wiki.s3_location import build_published_manifest

    from ariadne import admission, proposals

    s3_destination = str(destination).startswith("s3://")
    if s3_destination:
        if not isinstance(storage_profile, str) or not storage_profile.strip():
            raise ValueError(
                "an S3 Knowledge destination requires the explicit storage-profile "
                "selection (--context-storage-profile) of a declared profile"
            )
    elif storage_profile is not None:
        raise ValueError("a storage-profile selection requires an s3:// destination")
    if not isinstance(destination, (str, Path)):
        raise ValueError("the publication destination must be a path or an s3:// URI")
    if (
        not isinstance(scope, (list, tuple))
        or not scope
        or any(not isinstance(item, str) or not item for item in scope)
    ):
        raise ValueError("operator Visibility Scope must be an explicit nonempty set")
    scope = sorted(set(scope))
    root = Path(project) / proposals.WORKTREES_REL / proposal
    selected = selector(root)
    if selected is None:
        raise ValueError("overall admission requires an integrated selector")
    # A2 (spec0029 §1.3): the Bound Release advertises the scoped navigation
    # operations, so admitting one requires an SDK that actually provides
    # them — an older installed SDK refuses admission instead of being
    # advertised with capabilities it lacks. An S3 destination additionally
    # needs the r4 private-admission navigation keyword (plan0029 r29).
    _navigation_gate()
    support = copy.deepcopy(SUPPORT)
    storage_fields: dict = {}
    s3_location = None
    if s3_destination:
        _s3_navigation_capability()
        profile, binding, s3_location = _admission_s3_binding(
            root, storage_profile, str(destination)
        )
        support["storage"] = "s3-immutable"
        storage_fields = {
            "storage_profile": storage_profile,
            "storage_binding": binding.record(),
            "storage_declaration": profile.identity(),
            "storage_target_identity": s3_location.effective_target_identity,
        }
    require_validation_build(evidence, validation_build_identity(root))
    captured, errors = candidate(root, root / "knowledge", revision)
    if errors:
        raise ValueError("; ".join(errors))
    assert captured is not None
    if s3_destination:
        publication = native.preview_publication(
            root / "knowledge", revision, destination, expected_current, s3_location=s3_location
        )
    else:
        publication = native.preview_publication(
            root / "knowledge", revision, destination, expected_current
        )
    if publication.blocking_diagnostics:
        raise ValueError("; ".join(publication.blocking_diagnostics))
    if s3_destination:
        from lumio_wiki.s3_publish import _GRAPH_REL, _serialize_graph_bytes

        # Native S3 publication carries the graph only; local adds navigation indexes.
        derived_content = {
            _GRAPH_REL: _serialize_graph_bytes(captured.kb, captured.fingerprint)
        }
    else:
        derived_content = native._derived_content(captured)
    manifest = build_published_manifest(
        revision,
        captured.fingerprint.digest,
        captured.content,
        derived_content=derived_content,
        revision=revision,
        subtree=captured.subtree,
        source_reference_digest=captured.manifest_digest,
        format_identity=native.VALIDATOR_CONTRACT_ID,
        namespace=captured.manifest.namespace,
    )
    pseudo = {
        "commit": revision,
        "artifact_digest": evidence["artifact_digest"],
        "source_digest": evidence["approval_digest"],
        "source_declaration_digest": evidence["source_digest"],
        "sources": evidence["source_identity"],
        "storage_bindings": evidence["storage_bindings"],
        "review_digest": review["review_digest"],
        "contracts": admission._contracts_descriptor_view(evidence["contracts"])
        if (evidence.get("contracts") or {}).get("present")
        else {},
    }
    binding = {
        "version": 1,
        "content_commit": revision,
        "selector": selected,
        "input_scopes": {"core": ".", "knowledge": selected["subtree"]},
        "support": support,
        "core": core_binding(pseudo, evidence),
        "execution": evidence["execution_identity"],
        "visibility_scope": scope,
        "destination": (str(destination) if s3_destination else str(Path(destination).resolve())),
        **storage_fields,
        "knowledge": {
            "namespace": captured.manifest.namespace,
            "profile_version": 1,
            "published_version": revision,
            "fingerprint": captured.fingerprint.digest,
            "publication_manifest_digest": hashlib.sha256(
                msgspec.json.encode(manifest)
            ).hexdigest(),
            "source_reference_digest": captured.manifest_digest,
            "subtree": captured.subtree,
            "scope": scope,
        },
        "bindings": _binding_inventory(captured, scope),
        "publication_review_digest": publication.review_digest,
    }
    binding["digest"] = digest(binding)
    preview = {
        "manifest": binding,
        "core_review_digest": review["review_digest"],
        "core_review": review,
        "mapping_selections": sorted(mapping_selections),
        "publication_review": msgspec.to_builtins(publication),
        "expected_core_digest": digest(admission.load_current(project)),
        "side_effects": [
            "native Lumio publication, receipt and standalone current pointer may complete",
            "immutable Core snapshot preparation; atomic Core current descriptor last",
            "failed overall admission preserves native residue, not rollback",
        ],
    }
    preview["digest"] = digest(preview)
    return preview


class OverallAdmissionError(ValueError):
    """Actual publication outcome survives a subsequent reader/activation failure."""

    def __init__(self, message, outcome):
        self.outcome = outcome
        super().__init__(f"{message}; observed overall-admission outcome: {json.dumps(outcome)}")


def _s3_navigation_capability() -> None:
    """The approved r4 ``metadata_store`` navigation keyword, or an explicit
    refusal: an older local-only SDK generation must never be admitted or
    advertised as S3-capable (plan0029 r29)."""
    import inspect

    for function in _navigation_gate():
        parameter = inspect.signature(function).parameters.get("metadata_store")
        if parameter is None or parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
            raise ValueError(
                "the installed Lumio SDK provides no private-admission S3 "
                "navigation (metadata_store); an older local-only SDK refuses "
                "S3 publication instead of being advertised as S3-capable"
            )


def publish_and_verify(preview):
    import msgspec
    from lumio_wiki.git_authoring import S3PublicationRecord, publish_revision

    review = preview["publication_review"]
    manifest = preview["manifest"]
    s3_destination = str(review["destination"]).startswith("s3://")
    try:
        if s3_destination:
            # The SAME exact resolved location/private metadata store as the
            # preview: rebuilt from the frozen binding, drift-checked again.
            location, metadata_store = _frozen_s3_runtime(manifest)
            receipt = publish_revision(
                review["kb_path"],
                review["revision"],
                review["destination"],
                review["expected_current"],
                review["review_digest"],
                s3_location=location,
                metadata_store=metadata_store,
            )
        else:
            receipt = publish_revision(
                review["kb_path"],
                review["revision"],
                review["destination"],
                review["expected_current"],
                review["review_digest"],
            )
    except Exception as exc:
        outcome = {"integrated_activated": False, "publication_completion": "unverified"}
        try:
            if s3_destination:
                from lumio_wiki.s3_publish import observe_current_pointer

                location, metadata_store = _frozen_s3_runtime(manifest)
                outcome["observed_native_current"] = observe_current_pointer(
                    location.store, location.prefix
                ).version
                raw = metadata_store.get_publication_record(review["revision"])
                outcome["publication_receipt"] = msgspec.to_builtins(
                    msgspec.json.decode(raw, type=S3PublicationRecord)
                )["receipt"]
            else:
                from lumio_wiki.git_authoring import PublicationReceipt, _receipt_path
                from lumio_wiki.location import PublishedFilesystemLocation

                outcome["observed_native_current"] = PublishedFilesystemLocation(
                    review["destination"]
                ).read_pointer()
                path = _receipt_path(Path(review["destination"]), review["revision"])
                if path.is_file():
                    outcome["publication_receipt"] = msgspec.to_builtins(
                        msgspec.json.decode(path.read_bytes(), type=PublicationReceipt)
                    )
        except Exception:
            outcome["native_residue_inspection"] = "unavailable"
        raise OverallAdmissionError(str(exc), outcome) from exc
    outcome = {"publication_receipt": msgspec.to_builtins(receipt), "integrated_activated": False}
    try:
        open_context(preview["manifest"])
    except Exception as exc:
        raise OverallAdmissionError(str(exc), outcome) from exc
    return outcome


def open_context(manifest):
    from lumio_wiki.ariadne_context import ContextIdentity, open_published_context

    identity = dict(manifest["knowledge"])
    identity["scope"] = tuple(identity["scope"])
    if str(manifest["destination"]).startswith("s3://"):
        location, metadata_store = _frozen_s3_runtime(manifest)
        return open_published_context(
            location, ContextIdentity(**identity), metadata_store=metadata_store
        )
    from lumio_wiki.location import PublishedFilesystemLocation

    return open_published_context(
        PublishedFilesystemLocation(manifest["destination"], version=identity["published_version"]),
        ContextIdentity(**identity),
    )


def verify_release(record, snapshot):
    """Verify the complete Core/SDK association, not a self-consistent foreign pin."""
    from ariadne import proposals

    selected = selector(snapshot)
    manifest = record.get("bound_release")
    if selected is None:
        if manifest is not None:
            raise ValueError("mixed standalone/Core Bound Release")
        return None
    if not isinstance(manifest, dict) or "digest" not in manifest:
        raise ValueError("integrated admission is missing its Bound Release")
    if (
        digest({key: value for key, value in manifest.items() if key != "digest"})
        != manifest["digest"]
    ):
        raise ValueError("Bound Release manifest integrity failure")
    evidence = proposals.load_validation(
        Path(record["project"]), record["proposal"], record["commit"]
    )
    if evidence is None or not evidence["ok"]:
        raise ValueError("Bound Release lacks native Core validation")
    validation = record.get("validation") or {}
    s3_destination = str(manifest.get("destination") or "").startswith("s3://")
    expected_support = copy.deepcopy(SUPPORT)
    if s3_destination:
        # The frozen S3 transport binding is part of the digest-protected
        # identity; every piece must be present before any comparison.
        expected_support["storage"] = "s3-immutable"
        for key in (
            "storage_profile",
            "storage_binding",
            "storage_declaration",
            "storage_target_identity",
        ):
            if key not in manifest:
                raise ValueError("incomplete Bound Release identity")
    for key in (
        "commit",
        "ok",
        "status",
        "report",
        "performed_checks",
        "validator_identity",
        "execution_identity",
        "artifact_digest",
        "source_digest",
        "approval_digest",
        "validated_at",
    ):
        if validation.get(key) != evidence.get(key):
            raise ValueError("Bound Release Core validation descriptor mismatch")
    try:
        matches = (
            manifest["version"] == 1
            and manifest["content_commit"] == record["commit"]
            and manifest["selector"] == selected
            and manifest["input_scopes"] == {"core": ".", "knowledge": selected["subtree"]}
            and manifest["support"] == expected_support
            and manifest["core"] == core_binding(record, evidence)
            and manifest["execution"] == evidence.get("execution_identity") == execution_identity()
            and record["overall_confirmation"]["manifest_digest"] == manifest["digest"]
            and record["native_publication"]["review_digest"]
            == manifest["publication_review_digest"]
            and record["native_publication"]["manifest_digest"]
            == manifest["knowledge"]["source_reference_digest"]
            and record["native_publication"]["version"] == record["commit"]
            and record["native_publication"]["destination"] == manifest["destination"]
            and manifest["knowledge"]["namespace"] == selected["namespace"]
            and manifest["knowledge"]["subtree"] == selected["subtree"]
            and manifest["knowledge"]["published_version"] == record["commit"]
            and manifest["knowledge"]["scope"] == manifest["visibility_scope"]
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("incomplete Bound Release identity") from exc
    if not matches:
        raise ValueError("Bound Release mismatches Core/selector/scope/execution identity")
    context = open_context(manifest)
    actual = []
    pages = {page.entity_id: page for page in context.pages}
    for binding in context.bindings:

        def identity(page):
            return {
                "entity_id": page.entity_id,
                "path": page.path,
                "content_digest": hashlib.sha256(page.content.encode()).hexdigest(),
            }

        actual.append(
            {
                "model": binding.metric_ref.model,
                "metric": binding.metric_ref.metric,
                "entity": identity(pages[binding.metric_entity_id]),
                "policies": [identity(page) for page in binding.required_policies],
            }
        )
    if sorted(actual, key=lambda item: (item["model"], item["metric"])) != manifest["bindings"]:
        raise ValueError("Bound Release metric/Policy binding mismatch")
    return context


def metric_context(snapshot, manifest, context_dir, model, metric, *, _now=None):
    # ``_now`` is the runtime's multi-metric seam: one assessment instant for
    # every metric of one query_metrics answer (spec 0011 §2); the public
    # single-metric call keeps its own clock.
    from lumio_wiki.ariadne_context import disclose_native

    from ariadne import context

    bindings = [
        b
        for b in snapshot.bindings
        if b.metric_ref.model == model and b.metric_ref.metric == metric
    ]
    if len(bindings) != 1:
        raise ValueError("required metric Context Binding unavailable")
    binding = bindings[0]
    page = next(p for p in snapshot.pages if p.entity_id == binding.metric_entity_id)
    consumed = [page, *binding.required_policies]
    now = _now if _now is not None else context._assessment_now()
    signals = [context._page_view(p.citation, disclose_native(p.native), now) for p in consumed]
    computation = context._computation_meta(Path(context_dir), metric)
    if computation is not None:
        signals.append(context._page_view(f"computations/{metric}.md", computation, now))
    result = {
        "metric_page": page.content,
        "policies": [p.content for p in binding.required_policies],
        "context_signals": context._context_signals(signals),
        "bound_release": manifest["digest"],
        "citations": [
            {
                "namespace": p.namespace,
                "entity_id": p.entity_id,
                "path": p.path,
                "published_version": p.published_version,
                "citation": p.citation,
                "line_start": 1,
                "line_end": len(p.content.splitlines()),
            }
            for p in consumed
        ],
    }
    if computation is not None and computation.get("attestation") == "pending":
        result.update(
            attestation="pending",
            governed_note="governed: true means admitted, not independently value-attested",
        )
    return result


# --------------------------------------------- A2 scoped SDK navigation (§1.3)


def _navigation_gate():
    """The three approved scoped-navigation SDK operations (spec0009 r3), or
    an explicit refusal: an installed SDK that lacks them must never be
    advertised as supporting navigation it cannot serve."""
    try:
        from lumio_wiki.ariadne_context import (
            list_published_context_pages,
            read_published_context_page,
            search_published_context_pages,
        )
    except ImportError as exc:
        raise ValueError(
            "the installed Lumio SDK provides no approved scoped navigation "
            "APIs; integrated navigation refuses instead of advertising support"
        ) from exc
    return (
        list_published_context_pages,
        read_published_context_page,
        search_published_context_pages,
    )


def _navigation_identity(manifest):
    """The exact pinned location/expected-identity pair of one Bound Release
    (the same verified binding ``open_context`` resolves: an immutable
    version-pinned location — local, or S3 rebuilt from the frozen storage
    binding with its private metadata store — never a moving pointer)."""
    from lumio_wiki.ariadne_context import ContextIdentity
    from lumio_wiki.location import PublishedFilesystemLocation

    identity = dict(manifest["knowledge"])
    identity["scope"] = tuple(identity["scope"])
    if str(manifest["destination"]).startswith("s3://"):
        location, metadata_store = _frozen_s3_runtime(manifest)
        return location, ContextIdentity(**identity), metadata_store
    return (
        PublishedFilesystemLocation(manifest["destination"], version=identity["published_version"]),
        ContextIdentity(**identity),
        None,
    )


def _list_row(page, manifest, now, meta):
    """One metadata-only list entry: existing Core outer fields plus the SDK
    identity additions; no page body (spec0029 §1.3)."""
    from ariadne import context

    return {
        "path": page.path,
        "draft": False,
        "title": page.title,
        "kind": page.kind,
        "namespace": page.namespace,
        "entity_id": page.entity_id,
        "published_version": page.published_version,
        "citation": page.citation,
        "bound_release": manifest["digest"],
        "context_signals": context._context_signals([context._page_view(page.path, meta, now)]),
    }


def _full_page_fields(page, manifest, now, meta):
    """The shared identity/content/advisory fields of one complete canonical
    page."""
    from ariadne import context

    return {
        "path": page.path,
        "draft": False,
        "kind": page.kind,
        "namespace": page.namespace,
        "entity_id": page.entity_id,
        "published_version": page.published_version,
        "citation": page.citation,
        "bound_release": manifest["digest"],
        "content": page.content,
        "context_signals": context._context_signals([context._page_view(page.path, meta, now)]),
    }


def list_context_pages(manifest, verified_native=None):
    """Every visible page of the pinned Bound Release, SDK-sorted by exact
    path, metadata only. Profiled entries reuse the session's
    already-verified native metadata (exact path match) for the Core
    advisory view — the same disclosure the accepted metric context uses;
    ordinary unprofiled pages carry no native metadata and stay unknown. No
    page body is read or reparsed per row."""
    from lumio_wiki.ariadne_context import disclose_native

    from ariadne import context

    listing, _read, _search = _navigation_gate()
    location, expected, metadata_store = _navigation_identity(manifest)
    known = dict(verified_native or {})
    now = context._assessment_now()
    if metadata_store is None:  # local: exact pre-r4 call shape (SDK 0.4.1 compatible)
        pages = listing(location, expected)
    else:
        pages = listing(location, expected, metadata_store=metadata_store)
    return [
        _list_row(
            page,
            manifest,
            now,
            disclose_native(known[page.path]) if page.path in known else {},
        )
        for page in pages
    ]


def read_context_page(manifest, path):
    """One complete visible canonical page by exact relative path through
    the pinned SDK facade; hidden and unknown paths refuse identically with
    no hidden disclosure."""
    from lumio_wiki.ariadne_context import disclose_native

    from ariadne import context

    _listing, read, _search = _navigation_gate()
    location, expected, metadata_store = _navigation_identity(manifest)
    if metadata_store is None:  # local: exact pre-r4 call shape (SDK 0.4.1 compatible)
        page = read(location, expected, path)
    else:
        page = read(location, expected, path, metadata_store=metadata_store)
    return _full_page_fields(
        page, manifest, context._assessment_now(), disclose_native(page.native)
    )


def search_context(manifest, query, limit=10):
    """Native Lumio lexical search over exactly the visible page set of the
    pinned Bound Release: SDK ranking, verbatim canonical passages with
    inclusive 1-based coordinates and fence-aware sections, and visible-only
    completeness counters (spec0029 §1.3)."""
    from lumio_wiki.ariadne_context import disclose_native

    from ariadne import context

    _listing, _read, search = _navigation_gate()
    location, expected, metadata_store = _navigation_identity(manifest)
    now = context._assessment_now()
    if metadata_store is None:  # local: exact pre-r4 call shape (SDK 0.4.1 compatible)
        results = search(location, expected, query, limit=limit)
    else:
        results = search(location, expected, query, limit=limit, metadata_store=metadata_store)
    hits = []
    for hit in results:
        hits.append(
            {
                **_full_page_fields(hit.page, manifest, now, disclose_native(hit.page.native)),
                "score": hit.score,
                "excerpt": hit.excerpt,
                "line_start": hit.line_start,
                "line_end": hit.line_end,
                "section": hit.section,
                "matched_fields": list(hit.matched_fields),
                "matched_terms": list(hit.matched_terms),
                "candidates_seen": hit.candidates_seen,
                "results_dropped": hit.results_dropped,
            }
        )
    return hits


def resolve_term(
    manifest,
    request,
    *,
    part: int = 1,
    confirmations=None,
    evidence_max_age_hours: float | None = None,
):
    """T2 (spec0029 §1.5): resolve one shared business term or exact field
    lookup against the pinned Bound Release's captured structured References
    through the ONE shared native resolver (the structured-entry seam in
    :func:`ariadne.context.resolve_term_entries` — there is no second matcher
    or ranking engine). The SDK's already-validated native metadata is
    adapted in memory; the operator Visibility Scope is applied by the pinned
    SDK context BEFORE matching, counting or citations; there is no legacy
    context_layer fallback and no Core-side KB YAML parse. Each match carries
    the version-qualified SDK identity and the Bound Release digest — the
    enrichment happens before the shared part/byte ceilings are computed, so
    the whole-output bounds always bind the enriched form."""
    from lumio_wiki.ariadne_context import disclose_native

    from ariadne import context

    published = open_context(manifest)
    identity = {}
    entries: list[tuple[str, dict, bool]] = []
    for page in published.pages:
        native = disclose_native(page.native)
        if not isinstance(native, dict):
            continue
        extension = native.get("ariadne")
        if not isinstance(extension, dict) or not isinstance(extension.get("mappings"), list):
            continue  # ordinary pages stay documentation, never References
        # F3 (fix pass): the COMPLETE producer-validated native mapping is
        # the resolver input — title/description/aliases/sources/status/
        # stale_after keep their authored values through the EXISTING output
        # fields; only provenance/draft are serving-layer facts
        meta = {"type": "reference", **native}
        entries.append((page.path, meta, False))
        identity[page.path] = {
            "namespace": page.namespace,
            "entity_id": page.entity_id,
            "published_version": page.published_version,
            "citation": page.citation,
            "bound_release": manifest["digest"],
        }

    def _enrich(match):
        return {**match, **identity[match["page"]]}

    return context.resolve_term_entries(
        entries,
        request,
        part=part,
        confirmations=confirmations,
        evidence_max_age_hours=evidence_max_age_hours,
        enrich=_enrich,
    )

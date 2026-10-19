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
    "profiles": ["metric", "policy"],
    "operations": ["get_metric", "discover", "list_metrics"],
    "unsupported": [
        "query_metrics",
        "query_detail",
        "query_records",
        "define_metric",
        "save_example",
        "search_examples",
        "search_context",
        "resolve_term",
        "list_context_pages",
        "read_context_page",
        "list_datasets",
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
):
    """Stateless composite preview; future receipts never enter its consent digest."""
    import msgspec
    from lumio_wiki import git_authoring as native
    from lumio_wiki.s3_location import build_published_manifest

    from ariadne import admission, proposals

    if not isinstance(destination, (str, Path)) or str(destination).startswith("s3://"):
        raise ValueError("unsupported integrated S3 destination; local immutable publication only")
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
    captured, errors = candidate(root, root / "knowledge", revision)
    if errors:
        raise ValueError("; ".join(errors))
    assert captured is not None
    publication = native.preview_publication(
        root / "knowledge", revision, destination, expected_current
    )
    if publication.blocking_diagnostics:
        raise ValueError("; ".join(publication.blocking_diagnostics))
    manifest = build_published_manifest(
        revision,
        captured.fingerprint.digest,
        captured.content,
        derived_content=native._derived_content(captured),
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
        "support": copy.deepcopy(SUPPORT),
        "core": core_binding(pseudo, evidence),
        "execution": execution_identity(),
        "visibility_scope": scope,
        "destination": str(Path(destination).resolve()),
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


def publish_and_verify(preview):
    import msgspec
    from lumio_wiki.git_authoring import publish_revision

    review = preview["publication_review"]
    try:
        receipt = publish_revision(
            review["kb_path"],
            review["revision"],
            review["destination"],
            review["expected_current"],
            review["review_digest"],
        )
    except Exception as exc:
        from lumio_wiki.git_authoring import PublicationReceipt, _receipt_path
        from lumio_wiki.location import PublishedFilesystemLocation

        outcome = {"integrated_activated": False, "publication_completion": "unverified"}
        try:
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
    from lumio_wiki.location import PublishedFilesystemLocation

    identity = dict(manifest["knowledge"])
    identity["scope"] = tuple(identity["scope"])
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
    for key in (
        "commit",
        "ok",
        "status",
        "report",
        "performed_checks",
        "validator_identity",
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
            and manifest["support"] == SUPPORT
            and manifest["core"] == core_binding(record, evidence)
            and manifest["execution"] == execution_identity()
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
            and not manifest["destination"].startswith("s3://")
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


def metric_context(snapshot, manifest, context_dir, model, metric):
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
    now = context._assessment_now()
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

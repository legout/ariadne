"""The bound approved-source observation and SQL-execution seam of the ODCS
consumer profile (spec 2028 §§4–6, issue #77/C1).

Only this module opens sources for contract inspection. It combines the
static binding resolution (contract/binding/model agreement, declaration-level
unsupported facts) with the live observation: targeted catalog reads of the
explicitly bound asset, the required-NULL full-dataset checks and the SQL
quality rules executed under the operator's existing inspection ceilings
through :class:`ariadne.execution.DeadlineBudget` and the reviewed
ad-hoc SQL authority, narrowed to the selected asset. Contract servers,
URLs, variable tokens and binding files never create a source, replace an
approved endpoint or supply credentials (ADR-0025): the only connection is
the operator-approved resolved identity built by the authoring seam.

Pure document/profile validation lives in :mod:`ariadne.contracts`; this
module never rewrites producer bytes and stores its evidence through the
caller's operator-owned validation store.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import sqlglot  # pyright: ignore[reportMissingImports] — same
from sqlglot import (  # pyright: ignore[reportMissingImports] — same
    exp,
)

from ariadne import (  # pyright: ignore[reportMissingImports] — new module, stale analysis index; resolves in the qualified env
    contracts,  # pyright: ignore[reportAttributeAccessIssue] — same stale index
    execution,
    sql_authority,
    validate,
)
from ariadne.authoring_sources import identity_registry
from ariadne.contracts import (  # pyright: ignore[reportMissingImports] — same
    Binding,
    ContractError,
    DocumentResult,
)

# The observation clock seam (the execution._deadline_clock discipline): a
# module attribute so tests control observation times DETERMINISTICALLY —
# never a wall-clock race for the evidence-age gate.
_observation_clock = lambda: datetime.now(UTC)  # noqa: E731 — seam, reassigned by tests

_QUALITY_UNSUPPORTED = (
    "the declared quality rule type {type!r} is outside this slice's evaluator "
    "(SQL rules over an approved native DuckDB source only) — preserved and "
    "reported, never silently dropped"
)
_SQL_DIALECT_UNSUPPORTED = (
    "the binding's producer server {server!r} declares type {type!r} — only "
    "native DuckDB quality execution is supported, never implicit transpilation"
)


def _quote(identifier: str) -> str:
    """Quote one SQL identifier (the authoring inspection discipline)."""
    return '"' + identifier.replace('"', '""') + '"'


def _sql_ref(ref: str) -> str:
    """The catalog entry's dotted ``ref`` as a quoted SQL prefix."""
    alias, dot, schema = ref.partition(".")
    return f"{_quote(alias)}.{_quote(schema)}" if dot else _quote(ref)


def _qualified_table(table: dict) -> str:
    return f"{_sql_ref(table['ref'])}.{_quote(table['name'])}"


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


# ------------------------------------------------------- static binding checks


def _tree_contracts(tree: Path) -> list[tuple[str, str]]:
    """Every contract document of a materialized candidate tree (relative
    path, text), plus the fixed binding file when present."""
    found: list[tuple[str, str]] = []
    directory = tree / "contracts"
    if directory.is_dir():
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix in (".yaml", ".yml"):
                found.append(
                    (f"contracts/{path.name}", path.read_text(encoding="utf-8", errors="strict"))
                )
    return found


def _tree_bindings(tree: Path) -> str | None:
    path = tree / "contract_bindings.yaml"
    return path.read_text(encoding="utf-8", errors="strict") if path.is_file() else None


def _find_object(document: dict, object_id: str) -> tuple[dict | None, str | None]:
    """Select the bound schema object by its exact stable ID: an ID that
    matches nothing is an explicit error, never a name-based guess."""
    matches = [
        obj
        for obj in document.get("schema") or []
        if isinstance(obj, dict) and obj.get("id") == object_id
    ]
    if not matches:
        return None, (
            f"the contract declares no schema object with id {object_id!r} — bindings "
            "select exact producer object IDs, never names"
        )
    # scoped-ID uniqueness already refused duplicates within the schema array
    return matches[0], None


def _find_server(document: dict, server_id: str) -> tuple[dict | None, str | None]:
    """Resolve the binding's producer server ID against the contract's
    ``servers`` (by ``server`` identifier or stable ``id``): ambiguity is an
    error, a miss is explicit."""
    matches = [
        server
        for server in document.get("servers") or []
        if isinstance(server, dict) and server_id in (server.get("server"), server.get("id"))
    ]
    if not matches:
        return None, (
            f"the contract declares no server {server_id!r} — SQL-quality rules "
            "evaluate only against an explicitly selected producer server"
        )
    if len(matches) > 1:
        return None, f"server selector {server_id!r} is ambiguous between {len(matches)} servers"
    return matches[0], None


def _physical_source_tables(source: str) -> list[list[str]]:
    """The physical table parts of one OSI dataset source: a bare qualified
    reference is read directly, a SELECT/WITH through sqlglot scope resolution
    (CTE and derived-table aliases are not physical relations)."""
    text = source.strip()
    try:
        statements = sqlglot.parse(text, dialect="duckdb")
    except Exception:
        return []  # the compile gate owns the verbatim parse error
    if len(statements) != 1 or statements[0] is None:
        return []
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
        return []
    tables: list[list[str]] = []
    for node in tree.find_all(exp.Table):
        if not isinstance(node.this, exp.Identifier):
            return []  # a table function: the source-access boundary owns that error
        tables.append([part.name for part in node.parts if part.name])
    return tables


def _dataset_agrees(asset: dict, source: str) -> tuple[bool, str]:
    """The binding must agree with the selected OSI dataset's actual physical
    source: its single physical table is exactly the bound asset. A derived
    or joined source whose relationship the native resolver cannot establish
    is unsupported, not guessed equivalent (spec 2028 §3)."""
    tables = _physical_source_tables(source)
    if not tables:
        return False, (
            f"the OSI dataset source {source!r} is not a resolvable physical table "
            "reference — the binding/asset relationship cannot be established"
        )
    expected = (
        [asset["catalog"], asset["schema"], asset["table"]]
        if asset.get("catalog")
        else [asset["source"], asset["table"]]
    )
    for parts in tables:
        if parts != expected:
            return False, (
                f"the OSI dataset source {source!r} reads {parts} but the binding "
                f"selects {expected} — a mismatched source/model binding never "
                "redirects reads"
            )
    if len(tables) != 1:
        return False, (
            f"the OSI dataset source {source!r} derives from {len(tables)} physical "
            "tables — a derived source whose relationship the native resolver "
            "cannot establish is unsupported"
        )
    return True, ""


def _declaration_requirements(
    contract_object: dict, binding: Binding
) -> tuple[list[dict], list[str]]:
    """The declaration-level requirements and errors of one bound object:
    property mapping completeness, physicalName agreement and the field
    profile's explicitly unsupported assertions (displayed per property,
    never silently ignored — spec 2028 §§3–4)."""
    requirements: list[dict] = []
    errors: list[str] = []
    where = f"binding {binding.id!r}"
    properties = [
        prop for prop in contract_object.get("properties") or [] if isinstance(prop, dict)
    ]
    mapped_ids = set(binding.properties)
    object_ids = {prop.get("id") for prop in properties if isinstance(prop.get("id"), str)}
    for prop in properties:
        pointer = f"schema/{binding.object_id}/properties/{prop.get('id') or prop.get('name')}"
        prop_id = prop.get("id")
        if not isinstance(prop_id, str) or not prop_id:
            errors.append(
                f"{where}: property {prop.get('name')!r} carries no stable id — an "
                "attempted stable binding without the needed IDs is unsupported"
            )
            continue
        if prop_id not in mapped_ids:
            errors.append(
                f"{where}: property id {prop_id!r} is not mapped — all physical "
                "properties of the bound object must be identified and mapped; "
                "omitting a property is not a way to remove its requirements"
            )
            continue
        column = binding.properties[prop_id]
        physical_name = prop.get("physicalName")
        if isinstance(physical_name, str) and physical_name and physical_name != column:
            errors.append(
                f"{where}: property {prop_id!r} declares physicalName {physical_name!r} "
                f"but the binding maps it to column {column!r} — a binding cannot "
                "silently overwrite a producer's expected physical name"
            )
        for flag in contracts._UNSUPPORTED_PROPERTY_FLAGS:
            if prop.get(flag) is True:
                requirements.append(
                    {
                        "kind": f"field_{flag}",
                        "pointer": pointer,
                        "outcome": "unsupported",
                        "detail": (
                            f"the asserted {flag} constraint is outside the supported "
                            "field profile — preserved and reported, never silently "
                            "ignored or inferred from a different SQL rule"
                        ),
                    }
                )
        if isinstance(prop.get("enum"), list):
            requirements.append(
                {
                    "kind": "field_enum",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": "enum value assertions are unsupported in this slice",
                }
            )
        logical_type = prop.get("logicalType")
        if isinstance(logical_type, str) and logical_type not in (
            "string",
            "date",
            "timestamp",
            "time",
            "number",
            "integer",
            "boolean",
        ):
            requirements.append(
                {
                    "kind": "field_logical_type",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": (
                        f"logical type {logical_type!r} (nested collection/object or "
                        "unknown) is outside the supported field profile"
                    ),
                }
            )
        if prop.get("logicalTypeOptions"):
            requirements.append(
                {
                    "kind": "field_logical_type_options",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": "nonempty logicalTypeOptions are unsupported in this slice",
                }
            )
        if prop.get("transformLogic") or prop.get("transformSourceObjects"):
            requirements.append(
                {
                    "kind": "field_transform",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": "executable transformations are preserved but unsupported",
                }
            )
    extra = sorted(mapped_ids - object_ids)
    if extra:
        errors.append(
            f"{where}: the property mapping names unknown producer property id(s) "
            f"{extra} — mappings bind exact contract property IDs"
        )
    physical_name = contract_object.get("physicalName")
    if isinstance(physical_name, str) and physical_name and physical_name != binding.asset["table"]:
        errors.append(
            f"{where}: the bound object declares physicalName {physical_name!r} but the "
            f"asset table is {binding.asset['table']!r} — a binding cannot silently "
            "overwrite a producer's expected physical name"
        )
    return requirements, errors


def _quality_requirements(
    contract_object: dict, binding: Binding, document: dict
) -> tuple[list[dict], list[str]]:
    """Enumerate the bound object's applicable declared quality rules: SQL
    rules carry their resolved producer server; library/text/custom rules are
    preserved but explicitly unsupported — no severity or selection flag drops
    a declared requirement (spec 2028 §5)."""
    requirements: list[dict] = []
    errors: list[str] = []
    where = f"binding {binding.id!r}"
    sql_rules: list[tuple[str, dict, str | None]] = []

    def _collect(rules: object, pointer: str, property_id: str | None) -> None:
        entries = rules if isinstance(rules, list) else []
        for index, rule in enumerate(entries):
            if not isinstance(rule, dict):
                continue
            rule_pointer = f"{pointer}/quality[{index}]"
            rule_type = rule.get("type", "library")
            if rule_type != "sql":
                requirements.append(
                    {
                        "kind": "quality_rule",
                        "pointer": rule_pointer,
                        "outcome": "unsupported",
                        "detail": _QUALITY_UNSUPPORTED.format(type=rule_type),
                    }
                )
                continue
            sql_rules.append((rule_pointer, rule, property_id))

    _collect(contract_object.get("quality"), f"schema/{binding.object_id}", None)
    for prop in contract_object.get("properties") or []:
        if not isinstance(prop, dict) or not isinstance(prop.get("id"), str):
            continue
        _collect(
            prop.get("quality"),
            f"schema/{binding.object_id}/properties/{prop['id']}",
            prop["id"],
        )
    server = None
    if sql_rules:
        if binding.server_id is None:
            errors.append(
                f"{where}: the bound object declares SQL-quality rules but the binding "
                "carries no server_id — the producer's server ID is required when "
                "SQL-quality rules apply"
            )
            return requirements + [
                {
                    "kind": "quality_rule",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": "no producer server selected",
                }
                for pointer, _rule, _prop in sql_rules
            ], errors
        server, error = _find_server(document, binding.server_id)
        if error is not None:
            errors.append(f"{where}: {error}")
            return requirements + [
                {
                    "kind": "quality_rule",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": error,
                }
                for pointer, _rule, _prop in sql_rules
            ], errors
        assert server is not None
        if server.get("type") != "duckdb":
            detail = _SQL_DIALECT_UNSUPPORTED.format(
                server=binding.server_id, type=server.get("type")
            )
            return requirements + [
                {
                    "kind": "quality_rule",
                    "pointer": pointer,
                    "outcome": "unsupported",
                    "detail": detail,
                }
                for pointer, _rule, _prop in sql_rules
            ], errors
    for pointer, rule, property_id in sql_rules:
        requirements.append(
            {
                "kind": "quality_sql",
                "pointer": pointer,
                "outcome": "not_run",
                "detail": "",
                "query": rule.get("query"),
                "property_id": property_id,
                # the exact enumerated rule (operator and query): bound at
                # enumeration so duplicate queries with different operators
                # can never mis-bind at execution time
                "rule": rule,
            }
        )
    return requirements, errors


def static_contract_checks(tree: Path) -> tuple[dict, list[str]]:
    """The OFFLINE contract checks of one materialized candidate tree: every
    contract document under the pinned profile, the fixed binding document,
    exact contract/object resolution, property-mapping completeness and the
    binding's agreement with the selected OSI dataset (spec 0028 §§2–3).
    Returns (static evidence, errors) — errors carry artifact and instance
    paths and fail validation; nothing here opens a connection."""
    evidence: dict = {"present": False, "documents": [], "bindings": []}
    errors: list[str] = []
    entries = _tree_contracts(tree)
    bindings_text = _tree_bindings(tree)
    if not entries and bindings_text is None:
        return evidence, errors
    evidence["present"] = True
    documents: list[tuple[str, dict | None, DocumentResult]] = []
    for rel, text in entries:
        try:
            document, result = contracts.validate_document(text, rel)
        except ContractError as exc:  # defensive: validate_document reports, never raises
            errors.append(str(exc))
            continue
        documents.append((rel, document, result))
        evidence["documents"].append(result.summary())
        errors.extend(f"{rel}: {error}" for error in result.errors)
    if bindings_text is None:
        return evidence, errors
    bindings, binding_errors = contracts.validate_bindings_document(
        bindings_text, "contract_bindings.yaml"
    )
    evidence["bindings"] = [binding.digest_payload() for binding in bindings]
    evidence["bindings_digest"] = _sha(evidence["bindings"])
    errors.extend(binding_errors)
    if binding_errors:
        return evidence, errors
    datasets = validate._datasets(tree)
    dataset_by_key = {(model, dataset): source for model, dataset, source, _pk in datasets}
    for binding in bindings:
        document, error = contracts.resolve_contract(
            documents, binding.contract_id, binding.contract_version
        )
        if error is not None:
            errors.append(f"contract_bindings.yaml: binding {binding.id!r}: {error}")
            continue
        assert document is not None
        contract_object, error = _find_object(document, binding.object_id)
        if error is not None:
            errors.append(f"contract_bindings.yaml: binding {binding.id!r}: {error}")
            continue
        assert contract_object is not None
        source = dataset_by_key.get((binding.model, binding.dataset))
        if source is None:
            errors.append(
                f"contract_bindings.yaml: binding {binding.id!r} selects OSI dataset "
                f"{binding.model}.{binding.dataset} which the candidate's semantic "
                "layer does not declare — resolved without fuzzy matching"
            )
            continue
        agrees, detail = _dataset_agrees(binding.asset, source)
        if not agrees:
            errors.append(f"contract_bindings.yaml: binding {binding.id!r}: {detail}")
            continue
        _declaration, declaration_errors = _declaration_requirements(contract_object, binding)
        errors.extend(declaration_errors)
        _requirements, quality_errors = _quality_requirements(contract_object, binding, document)
        errors.extend(quality_errors)
    return evidence, errors


# ------------------------------------------------------------- live observation


def _narrowed_authority(con, table: dict) -> sql_authority.AdHocAuthority:
    """The ad-hoc SQL authority narrowed to EXACTLY the selected asset: the
    reviewed function/relation checks of ``sql_authority`` apply to the whole
    expanded tree, and the permitted relation scope is the bound table alone —
    joins and foreign reads are refused before execution (spec 2028 §5)."""
    current = con.execute("SELECT current_catalog(), current_schema()").fetchone() or ("", "")
    return sql_authority.AdHocAuthority(
        relations=frozenset({(table.get("catalog"), table["schema"], table["name"])}),
        default_catalog=str(current[0]),
        default_schema=str(current[1]),
    )


def _expand_placeholders(
    query: object, *, table_sql: str, column: str | None
) -> tuple[str, str | None]:
    """Expand the pinned SQL documentation's fixed ``{object}`` and
    ``{property}`` identifier placeholders through their exact checked
    binding: each expands to ONE quoted identifier, never an expression,
    path or arbitrary text. General ``${...}`` variables and other
    unresolved placeholders are unsupported; no template engine runs and no
    environment value is consulted (spec 0028 §5)."""
    if not isinstance(query, str) or not query.strip():
        return "", "the rule carries no query — an SQL rule is one SELECT over the selected dataset"
    text = query
    if "${" in text:
        return text, (
            "the query carries ${...} variable syntax — variables are preserved "
            "unsupported; unresolved tokens are never used as endpoints or identifiers"
        )
    text = text.replace("{object}", table_sql)
    if "{property}" in text:
        if column is None:
            return text, (
                "the {property} placeholder appears in an object-level rule — only "
                "property rules bind a column"
            )
        text = text.replace("{property}", column)
    leftover = re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", text)
    if leftover:
        return text, (
            f"the query carries the unresolved placeholder {leftover.group(0)!r} — "
            "only {object} and {property} expand, through their exact binding"
        )
    return text, None


def _execute_quality_rule(con, budget, table: dict, requirement: dict) -> dict:
    """Authorize, execute and compare one SQL-quality rule. The expanded
    tree passes the existing ad-hoc authority (narrowed to the selected
    asset) BEFORE any execution; one guarded single statement must return
    exactly one row/column finite numeric or boolean scalar (spec 2028 §5)."""
    column = (
        _quote(requirement["property_column"])
        if requirement.get("property_column") is not None
        else None
    )
    sql, error = _expand_placeholders(
        requirement["query"], table_sql=_qualified_table(table), column=column
    )
    if error is not None:
        return {**requirement, "outcome": "unsupported", "detail": error}
    try:
        sql_authority.assert_ad_hoc_authority(
            sql, kind="source", authority=_narrowed_authority(con, table)
        )
    except ValueError as exc:
        return {**requirement, "outcome": "refused", "detail": str(exc)}
    try:
        execution.assert_single_statement(sql)
        with budget.guard(con):
            relation = con.sql(sql)
            columns = list(relation.columns)
            rows = relation.fetchall()
    except execution.DeadlineExhausted:
        raise
    except duckdb.Error as exc:
        return {
            **requirement,
            "outcome": "error",
            "detail": f"the rule's query did not execute: {type(exc).__name__}: {exc}",
        }
    if len(rows) != 1 or len(rows[0]) != 1 or len(columns) != 1:
        return {
            **requirement,
            "outcome": "error",
            "detail": (
                f"the rule's query must return exactly one row and one column, got "
                f"{len(rows)} row(s) over {len(columns)} column(s)"
            ),
        }
    outcome, detail = contracts.compare_quality_rule(requirement["rule"], rows[0][0])
    return {**requirement, "outcome": outcome, "detail": detail}


def _observe_binding(con, budget, catalog, *, binding, document, contract_digest) -> dict:
    """Observe ONE bound dataset against the approved catalog: presence,
    per-property type/physical-type checks, full-dataset required-NULL counts
    and the SQL-quality rules — each with its own honest outcome. Never a
    whole-registry scan (spec 0028 §§4–5)."""
    contract_object, _error = _find_object(document, binding.object_id)
    assert contract_object is not None  # static resolution already refused otherwise
    declaration, _declaration_errors = _declaration_requirements(contract_object, binding)
    quality, _quality_errors = _quality_requirements(contract_object, binding, document)
    requirements: list[dict] = [*declaration, *quality]
    observed_at = _observation_clock().isoformat(timespec="seconds")
    table = None
    for entry in catalog:
        for candidate in entry["tables"]:
            if (
                candidate.get("source") == binding.asset["source"]
                and candidate.get("catalog") == binding.asset["catalog"]
                and candidate.get("schema") == binding.asset["schema"]
                and candidate["name"] == binding.asset["table"]
            ):
                table = candidate
    if table is None:
        names = {entry["name"] for entry in catalog}
        if binding.asset["source"] not in names:
            reason = (
                f"the binding names source {binding.asset['source']!r} which is not an "
                f"approved registry identity (approved: {', '.join(sorted(names)) or 'none'}) "
                "— a contract/binding alone cannot open a source; nothing was read"
            )
            outcome = "refused"
        else:
            reason = (
                f"the bound asset {binding.asset['source']}.{binding.asset['schema']}."
                f"{binding.asset['table']} is not present in the approved resolved "
                "source identity — an observed missing dataset is drift, never a "
                "reason to redirect the binding"
            )
            outcome = "drift"
        return {
            "binding": binding.id,
            "contract": {
                "id": binding.contract_id,
                "version": binding.contract_version,
                "digest": contract_digest,
            },
            "object_id": binding.object_id,
            "asset": binding.asset,
            "model": binding.model,
            "dataset": binding.dataset,
            "requirements": [
                *requirements,
                {
                    "kind": "dataset_presence",
                    "pointer": f"schema/{binding.object_id}",
                    "outcome": outcome,
                    "detail": reason,
                },
            ],
            "outcome": "failed",
            "scope": "full",
            "observed_at": observed_at,
            "dependencies": {
                "contract_digest": contract_digest,
                "binding_digest": _sha(binding.digest_payload()),
                "profile": contracts.CONSUMER_PROFILE,
                "schema_pin": contracts.SCHEMA_SHA256,
            },
        }
    assert table is not None
    columns = {column["name"]: column["type"] for column in table["columns"]}
    property_by_id = {
        prop.get("id"): prop
        for prop in contract_object.get("properties") or []
        if isinstance(prop, dict) and isinstance(prop.get("id"), str)
    }
    observed: list[dict] = []
    for prop_id, column_name in binding.properties.items():
        prop = property_by_id.get(prop_id)
        if prop is None:
            continue  # static resolution already refused the mapping
        pointer = f"schema/{binding.object_id}/properties/{prop_id}"
        if column_name not in columns:
            observed.append(
                {
                    "kind": "field_presence",
                    "pointer": pointer,
                    "outcome": "drift",
                    "detail": (
                        f"the mapped column {column_name!r} is missing from the bound "
                        f"asset {binding.asset['table']!r} — an observed missing column "
                        "is drift, never a reason to redirect the binding"
                    ),
                }
            )
            continue
        observed_type = columns[column_name]
        if prop.get("logicalType") is not None:
            outcome, detail = contracts.logical_type_matches(prop.get("logicalType"), observed_type)
            observed.append(
                {
                    "kind": "field_logical_type",
                    "pointer": pointer,
                    "outcome": outcome,
                    "detail": (
                        f"{detail} (declared logical type {prop.get('logicalType')!r}, "
                        f"observed column {column_name!r} {observed_type!r})"
                    ),
                }
            )
        if prop.get("physicalType") is not None:
            outcome, detail = contracts.compare_physical_type(
                prop.get("physicalType"), observed_type
            )
            observed.append(
                {
                    "kind": "field_physical_type",
                    "pointer": pointer,
                    "outcome": outcome,
                    "detail": f"{detail} (observed column {column_name!r})",
                }
            )
        if prop.get("required") is True:
            sql = (
                f"SELECT COUNT(*) FILTER (WHERE {_quote(column_name)} IS NULL) "
                f"FROM {_qualified_table(table)}"
            )
            try:
                execution.assert_single_statement(sql)
                with budget.guard(con):
                    nulls = con.execute(sql).fetchone()[0]
            except execution.DeadlineExhausted:
                raise
            except duckdb.Error as exc:
                observed.append(
                    {
                        "kind": "field_required",
                        "pointer": pointer,
                        "outcome": "unavailable",
                        "detail": (
                            f"the required-NULL count over column {column_name!r} could "
                            f"not be read ({type(exc).__name__}) — unavailable, never compliant"
                        ),
                    }
                )
                continue
            observed.append(
                {
                    "kind": "field_required",
                    "pointer": pointer,
                    "outcome": "passed" if nulls == 0 else "drift",
                    "detail": (
                        f"required means no observed NULLs over the entire bound "
                        f"dataset: {nulls} NULL row(s) in column {column_name!r}"
                    ),
                }
            )
    quality_requirements: list[dict] = []
    for requirement in quality:
        if requirement["kind"] != "quality_sql":
            quality_requirements.append(requirement)
            continue
        quality_requirements.append(
            _execute_quality_rule(
                con,
                budget,
                table,
                {
                    **requirement,
                    "property_column": (
                        binding.properties.get(requirement["property_id"])
                        if requirement.get("property_id") is not None
                        else None
                    ),
                },
            )
        )
    requirements = [*observed, *quality_requirements]
    return {
        "binding": binding.id,
        "contract": {
            "id": binding.contract_id,
            "version": binding.contract_version,
            "digest": contract_digest,
        },
        "object_id": binding.object_id,
        "asset": binding.asset,
        "model": binding.model,
        "dataset": binding.dataset,
        "requirements": requirements,
        "outcome": "passed"
        if all(requirement["outcome"] == "passed" for requirement in requirements)
        else "failed",
        "scope": "full",
        "observed_at": observed_at,
        "dependencies": {
            "contract_digest": contract_digest,
            "binding_digest": _sha(binding.digest_payload()),
            "profile": contracts.CONSUMER_PROFILE,
            "schema_pin": contracts.SCHEMA_SHA256,
        },
        "observed_schema": [
            {"column": column["name"], "type": column["type"]} for column in table["columns"]
        ],
    }


def _dependencies_current(observation: dict, *, contract_digest, binding) -> bool:
    """Whether one retained observation's dependency identities still bind the
    current candidate: exact contract/binding digests plus the consumer
    profile/pin. Age is checked separately by the caller (spec 0028 §6: a
    changed dependency invalidates applicable evidence; age cannot excuse a
    known mismatch)."""
    dependencies = observation.get("dependencies") or {}
    return (
        dependencies.get("contract_digest") == contract_digest
        and dependencies.get("binding_digest") == _sha(binding.digest_payload())
        and dependencies.get("profile") == contracts.CONSUMER_PROFILE
        and dependencies.get("schema_pin") == contracts.SCHEMA_SHA256
        and observation.get("outcome") == "passed"
    )


def observation_expired(observation: dict, max_age_hours: float) -> bool:
    """Whether one retained observation aged past the operator's evidence-age
    budget (the shared receipt ceiling): unversioned data stays honestly
    as-of; expiry means it can no longer attest a new validation/admission."""
    raw_time = observation.get("observed_at")
    if not isinstance(raw_time, str):
        return True
    try:
        observed_at = datetime.fromisoformat(raw_time)
    except ValueError:
        return True
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - observed_at > timedelta(hours=max_age_hours)


def observe_contracts(
    project: Path,
    tree: Path,
    *,
    approval: dict | None,
    prior_observations: dict[str, dict] | None,
    limits: dict,
) -> tuple[dict, list[str]]:
    """The complete contract leg of one candidate validation: the static
    document/binding checks plus — only for resolved bindings under an
    operator-approved source identity — the live observation of every bound
    dataset under the operator's inspection ceilings. Still-applicable
    retained observations are reused with their ORIGINAL observation time;
    expired or dependency-mismatched evidence is re-observed, never restamped
    (spec 2028 §6).

    Returns (evidence, errors): the evidence rides the validation store; the
    errors are the validation failures (static errors plus one actionable
    line per non-passed requirement outcome)."""
    evidence, errors = static_contract_checks(tree)
    if not evidence["present"] or errors or not evidence.get("bindings"):
        return evidence, errors
    # Re-parse the resolved documents/bindings for the live pass (static
    # checks already validated them; nothing here re-reports those errors).
    documents: list[tuple[str, dict | None, DocumentResult]] = []
    for rel, text in _tree_contracts(tree):
        document, result = contracts.validate_document(text, rel)
        documents.append((rel, document, result))
    bindings, _binding_errors = contracts.validate_bindings_document(
        _tree_bindings(tree) or "", "contract_bindings.yaml"
    )
    if approval is None:
        errors.append(
            "contract_bindings.yaml: the candidate binds contracts but declares no "
            "approved source identity — a binding requires the operator's Source "
            "Approval before anything is inspected (missing permission refuses "
            "before inspection)"
        )
        return evidence, errors
    observations: list[dict] = []
    budget = execution.DeadlineBudget(limits["execution_seconds"])

    def _unavailable_observation(binding: Binding, detail: str) -> dict:
        """The honest unavailable observation: the permitted source/observation
        could not be obtained (an exhausted budget or an unopenable setup) —
        never a compliant claim (spec 0028 §6)."""
        return {
            "binding": binding.id,
            "contract": {"id": binding.contract_id, "version": binding.contract_version},
            "object_id": binding.object_id,
            "asset": binding.asset,
            "model": binding.model,
            "dataset": binding.dataset,
            "requirements": [
                {
                    "kind": "execution_budget",
                    "pointer": f"binding/{binding.id}",
                    "outcome": "unavailable",
                    "detail": detail,
                }
            ],
            "outcome": "incomplete",
            "scope": "partial",
            "observed_at": _observation_clock().isoformat(timespec="seconds"),
            "dependencies": {
                "contract_digest": next(
                    (
                        result.digest
                        for _rel, _doc, result in documents
                        if result.contract_id == binding.contract_id
                        and result.contract_version == binding.contract_version
                    ),
                    None,
                ),
                "binding_digest": _sha(binding.digest_payload()),
                "profile": contracts.CONSUMER_PROFILE,
                "schema_pin": contracts.SCHEMA_SHA256,
            },
        }

    try:
        owned = execution.DuckDBExecution(
            identity_registry(approval["sources"], approval.get("storage_bindings")),
            budget=budget,
        )
    except ValueError as exc:
        # DeadlineExhausted (its subclass) or a redacted setup refusal — the
        # permitted observation could not be obtained: every binding reports
        # unavailable, never compliant (spec 0028 §6).
        evidence["observations"] = [
            _unavailable_observation(
                binding,
                f"the contract observation could not be obtained under the operator's "
                f"ceilings: {exc}",
            )
            for binding in bindings
        ]
        for observation in evidence["observations"]:
            errors.append(
                f"contract observation of binding {observation['binding']!r} is "
                f"unavailable — {observation['requirements'][0]['detail']}"
            )
        return evidence, errors
    except duckdb.Error as exc:
        evidence["observations"] = [
            _unavailable_observation(binding, f"the approved source did not open: {exc}")
            for binding in bindings
        ]
        for observation in evidence["observations"]:
            errors.append(
                f"contract observation of binding {observation['binding']!r} is "
                f"unavailable — the approved source did not open ({type(exc).__name__})"
            )
        return evidence, errors
    try:
        catalog = owned.catalog
        for binding in bindings:
            document, error = contracts.resolve_contract(
                documents, binding.contract_id, binding.contract_version
            )
            if error is not None or document is None:
                continue  # the static leg already reported the error
            contract_object, object_error = _find_object(document, binding.object_id)
            if object_error is not None or contract_object is None:
                continue
            contract_digest = next(
                result.digest
                for _rel, _doc, result in documents
                if result.contract_id == binding.contract_id
                and result.contract_version == binding.contract_version
            )
            prior = (prior_observations or {}).get(binding.id)
            if (
                prior is not None
                and _dependencies_current(prior, contract_digest=contract_digest, binding=binding)
                and not observation_expired(prior, limits["receipt_max_age_hours"])
            ):
                observations.append({**prior, "reused": True})
                continue
            try:
                observations.append(
                    _observe_binding(
                        owned.con,
                        budget,
                        catalog,
                        binding=binding,
                        document=document,
                        contract_digest=contract_digest,
                    )
                )
            except execution.DeadlineExhausted as exc:
                observations.append(_unavailable_observation(binding, str(exc)))
    finally:
        owned.close()
    evidence["observations"] = observations
    for observation in observations:
        evidence.setdefault("approval_digest", approval.get("approval_digest"))
        for requirement in observation["requirements"]:
            if requirement["outcome"] != "passed":
                errors.append(
                    f"contract observation of binding {observation['binding']!r} "
                    f"({observation['contract'].get('id')}@"
                    f"{observation['contract'].get('version')}, "
                    f"dataset {observation['model']}.{observation['dataset']}): "
                    f"{requirement['pointer']} {requirement['kind']} is "
                    f"{requirement['outcome']} — {requirement['detail']}"
                )
    return evidence, errors

"""The ad-hoc SQL IO-authority boundary (issue #59, spec 0014 §9).

:class:`ariadne.query.QueryRuntime.define_metric` is the one shared seam behind
the Python API, the local CLI, the MCP Facade and the Analyst toolset, and it
accepts two ordinary Analyst-supplied SQL fragments: ``source`` and
``expression``. Compile success (ADR-0005/ADR-0008), the single-statement
guard, read-only source attaches (ADR-0010) and the shared output ceilings
(spec 0014 §4) are statement-shape and OUTPUT controls — none of them confines
what the credential-bearing DuckDB process READS. This module is that
confinement: one transport-neutral, static, fail-closed authority predicate
over the PARSED fragments, applied in the runtime BEFORE the grain guard, the
render compile gate, the EXPLAIN bind or any collection runs — so a refusal
stages nothing and no caller-derived SQL ever reaches DuckDB (issue #59 AC2).

Rules (issue #59 AC1/AC3, spec 0014 §9):

- **Physical relations.** Every physical table a fragment touches must be one
  of the ALREADY-BUILT execution catalog's enumerated tables/views, resolved
  with DuckDB's own qualification rules (the connection's current
  catalog/schema for one- and two-part references). Resolution is
  scope-aware, so CTE and derived-table aliases are resolved through their own
  subquery scopes and never mistaken for physical relations. The registry's
  own file/network readers stay usable exactly because they ARE the enumerated
  views, and the legacy ``--db`` bare-table resolution (``USE demo.main``) is
  preserved.
- **Table functions, path/URI shorthand, metadata catalogs and indirect SQL
  functions are refused**: ``read_blob``/``read_csv``/``parquet_scan`` in a
  FROM clause, ``'./data.csv'`` as a table name, ``information_schema`` /
  ``pg_catalog`` tables, and ``query()`` / ``query_table()`` never enter
  execution — including a scalar subquery in ``expression``.
- **Functions are positively restricted** to the reviewed built-in analytics
  set below (aggregate, arithmetic, date/time, string, conditional and cast
  behavior, plus the nested-type constructors the output guard already
  refuses as result types). Unknown names are refused whether sqlglot parses
  them as anonymous calls or as typed nodes — ``READ_CSV`` and
  ``GENERATE_SERIES`` are typed nodes, not ``Anonymous`` calls — and nothing
  trusts presence in the DuckDB catalog.
- **Statement shapes.** Exactly one SELECT-shaped statement for ``source`` (a
  bare table reference is read as the wrapped ``SELECT * FROM <table>`` the
  compiler builds), one expression for ``expression``, and no
  DML/DDL/command node anywhere in either tree — including a
  ``WITH <name> AS (INSERT ...) SELECT`` smuggling a write into a read.
- **Dialect honesty.** Each fragment is parsed BOTH with the generic dialect
  the compiler (:mod:`ariadne.render`) parses it with AND with the DuckDB
  dialect that executes it, and both trees must pass the same predicate: a
  dialect discrepancy can never make the executed SQL read something the
  validated SQL did not (fail closed on either parse failure).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
from sqlglot import (  # pyright: ignore[reportMissingImports] — analysis env lacks site-packages
    expressions as exp,
)
from sqlglot.optimizer.scope import (  # pyright: ignore[reportMissingImports] — analysis env lacks site-packages
    Scope,
    build_scope,
)

# The bounded identifier form every refusal may echo (the shared complete-output
# bounding helper, spec 0014 §4: attacker-supplied names never grow a refusal).
from ariadne.query_results import _bound_name  # pyright: ignore[reportMissingImports] — drift

if TYPE_CHECKING:
    from duckdb import (
        DuckDBPyConnection,  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
    )

# One shared guidance sentence for every refusal branch (the grain guard's
# GRAIN_GUIDANCE pattern): what IS allowed and that nothing staged/executed.
AD_HOC_AUTHORITY_GUIDANCE = (
    "ad-hoc SQL may read only the registered catalog relations using built-in analytics "
    "functions; file, network, table-function, metadata-catalog and indirect SQL access "
    "is refused before any execution — nothing staged, nothing executed"
)

# The reviewed pure built-in analytics set (issue #59: positively restricted, no
# blacklist). Names are the canonical sql_name() forms of BOTH the generic and
# the DuckDB dialect parses of the supported spellings. Adding an entry is a
# review decision: an entry must be a pure built-in with no file, network,
# catalog, SQL-string or side-effect behavior.
_AGGREGATES = frozenset(
    {
        "SUM",
        "COUNT",
        "COUNT_IF",
        "AVG",
        "MIN",
        "MAX",
        "MEDIAN",
        "MODE",
        "ANY_VALUE",
        "ARBITRARY",
        "FIRST",
        "LAST",
        "STDDEV",
        "STDDEV_SAMP",
        "STDDEV_POP",
        "VARIANCE",
        "VARIANCE_POP",
        "LOGICAL_AND",
        "LOGICAL_OR",
        "ARRAY_AGG",
        "LIST",
        "GROUP_CONCAT",
        "APPROX_DISTINCT",
        "BITWISE_AND_AGG",
        "BITWISE_OR_AGG",
        "BITWISE_XOR_AGG",
        "KURTOSIS",
        "SKEWNESS",
        "PERCENTILE_CONT",
        "PERCENTILE_DISC",
        "QUANTILE_CONT",
        "QUANTILE_DISC",
        "BIT_AND",
        "BIT_OR",
        "BIT_XOR",
    }
)
_ARITHMETIC = frozenset(
    {
        "ABS",
        "CEIL",
        "FLOOR",
        "ROUND",
        "TRUNC",
        "SIGN",
        "SQRT",
        "CBRT",
        "EXP",
        "LN",
        "LOG",
        "POWER",
        "GREATEST",
        "LEAST",
        "PI",
        "DEGREES",
        "RADIANS",
        "SIN",
        "COS",
        "TAN",
        "ASIN",
        "ACOS",
        "ATAN",
        "ATAN2",
        "SINH",
        "COSH",
        "TANH",
        "COT",
        "FACTORIAL",
        "IS_NAN",
        "IS_INF",
        "SIGNBIT",
        "EVEN",
    }
)
_TEMPORAL = frozenset(
    {
        "DATE_TRUNC",
        "TIMESTAMP_TRUNC",
        "DATE_BIN",
        "TIME_BUCKET",
        "EXTRACT",
        "DATE_PART",
        "DATEDIFF",
        "DATE_ADD",
        "DATE_SUB",
        "LAST_DAY",
        "YEAR",
        "QUARTER",
        "MONTH",
        "WEEK",
        "WEEK_OF_YEAR",
        "DAY",
        "DAY_OF_WEEK",
        "DAY_OF_MONTH",
        "DAY_OF_YEAR",
        "HOUR",
        "MINUTE",
        "SECOND",
        "TIME_TO_UNIX",
        "UNIX_TO_TIME",
        "EPOCH",
        "EPOCH_MS",
        "DATE_FROM_PARTS",
        "TIMESTAMP_FROM_PARTS",
        "TIME_FROM_PARTS",
        "MAKE_DATE",
        "MAKE_TIMESTAMP",
        "MAKE_TIME",
        "AGE",
        "NOW",
        "CURRENT_DATE",
        "CURRENT_TIMESTAMP",
    }
)
_TEXT = frozenset(
    {
        "LENGTH",
        "BIT_LENGTH",
        "UPPER",
        "LOWER",
        "TRIM",
        "BTRIM",
        "SUBSTRING",
        "LEFT",
        "RIGHT",
        "CONCAT",
        "CONCAT_WS",
        "REPLACE",
        "TRANSLATE",
        "REVERSE",
        "REPEAT",
        "PAD",
        "STARTS_WITH",
        "ENDS_WITH",
        "CONTAINS",
        "STR_POSITION",
        "SPLIT",
        "SPLIT_PART",
        "STRING_SPLIT",
        "STR_TO_ARRAY",
        "STRTOK",
        "FORMAT",
        "REGEXP_LIKE",
        "REGEXP_MATCHES",
        "REGEXP_REPLACE",
        "REGEXP_EXTRACT",
        "MD5",
        "SHA2",
        "SHA256",
        "CHR",
        "ASCII",
        "HEX",
        "ENCODE",
        "DECODE",
        "TO_BASE64",
        "FROM_BASE64",
        "TIME_TO_STR",
        "STR_TO_TIME",
        "STRFTIME",
        "STRPTIME",
        "STRIP_ACCENTS",
    }
)
_CONDITIONAL = frozenset({"COALESCE", "IFNULL", "NVL", "NULLIF", "NVL2", "IF", "IIF"})
# CAST/TRY_CAST/EXTRACT are syntax nodes (below), not calls; TYPEOF is the pure
# type introspection; ARRAY/MAP/STRUCT are the nested-type constructors whose
# OUTPUT types the S1 output guard already refuses (tests pin that path).
_COMPOSITE = frozenset({"TYPEOF", "ARRAY", "MAP", "STRUCT", "CAST", "TRY_CAST"})
# Window-only ranking/navigation helpers (pure; their aggregate operands are
# authorized above).
_WINDOW = frozenset(
    {
        "ROW_NUMBER",
        "RANK",
        "DENSE_RANK",
        "NTILE",
        "LAG",
        "LEAD",
        "FIRST_VALUE",
        "LAST_VALUE",
        "NTH_VALUE",
        "CUME_DIST",
        "PERCENT_RANK",
    }
)
REVIEWED_SQL_FUNCTIONS = (
    _AGGREGATES | _ARITHMETIC | _TEMPORAL | _TEXT | _CONDITIONAL | _COMPOSITE | _WINDOW
)

# sqlglot nodes that are SQL SYNTAX rather than named function calls: their
# operands are still walked (functions, relations), but they carry no callable
# name to authorize.
_SYNTAX_NODES = (exp.And, exp.Or, exp.Case, exp.Cast, exp.TryCast, exp.Extract, exp.Exists)

# Statement/data-modification constructs refused ANYWHERE in a validated tree:
# ``WITH t AS (INSERT ... RETURNING ...) SELECT`` is one statement that still
# writes, and ``LOAD``/``INSTALL`` fall back to a generic Command node.
# SQLGlot 25 lacks newer dedicated nodes; its generic Command still refuses them.
_SIDE_EFFECT_NODES = tuple(
    node_type
    for name in (
        "Delete",
        "Copy",
        "Insert",
        "Update",
        "Merge",
        "DDL",
        "Command",
        "Transaction",
        "Commit",
        "Rollback",
        "Set",
        "Use",
        "Pragma",
        "Grant",
        "Analyze",
        "Attach",
        "Detach",
        "LoadData",
        "Export",
        "Cache",
        "Refresh",
    )
    if isinstance(node_type := getattr(exp, name, None), type)
)

# The statement shapes an ad-hoc SOURCE may take (a bare table reference is
# wrapped into a Subquery by the parse helper below, mirroring render).
_QUERY_STATEMENTS = (exp.Select, exp.Union, exp.Except, exp.Intersect, exp.Subquery)

# DuckDB's own metadata catalogs (refusal-guidance refinement only — the
# enforcement is the positive catalog-relation match above).
_METADATA_SCHEMAS = frozenset({"information_schema", "pg_catalog", "duckdb", "temp"})

# render's dataset-source wrap rule (ariadne/render._source_subquery): only a
# leading SELECT/WITH passes through unwrapped — the boundary parses the exact
# text the compiler will parse.
_SOURCE_PREFIX_RE = re.compile(r"(?is)\s*(select|with)\b")
# A URI scheme prefix (file:, https:, s3:, ducklake:, ...): never a relation name.
_URI_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")


@dataclass(frozen=True)
class AdHocAuthority:
    """The physical-relation identity set ad-hoc fragments may read.

    ``relations`` carries the complete ``(catalog, schema, table)`` tuples of
    the ALREADY-BUILT execution catalog (a file view's catalog is ``None``:
    it lives in the connection's in-memory catalog), and
    ``default_catalog``/``default_schema`` are the connection's own current
    catalog/schema — exactly what DuckDB uses to resolve one- and two-part
    references (the legacy ``--db`` route's ``USE demo.main`` makes bare table
    names resolve; a registry route keeps its ``<source>.<table>`` form)."""

    relations: frozenset[tuple[str | None, str, str]]
    default_catalog: str
    default_schema: str

    @classmethod
    def build(cls, catalog: list[dict], con: DuckDBPyConnection) -> AdHocAuthority:
        """The authority of ONE runtime's built catalog and connection — read
        once at construction (trusted internal reads, never caller SQL), so an
        ad-hoc refusal never needs a DuckDB call of its own."""
        relations = {
            (table.get("catalog"), table["schema"], table["name"])
            for source in catalog
            for table in source["tables"]
        }
        current = con.execute("SELECT current_catalog(), current_schema()").fetchone() or ("", "")
        return cls(frozenset(relations), str(current[0]), str(current[1]))

    def authorizes(self, identity: tuple[str, str, str]) -> bool:
        """Whether one resolved ``(catalog, schema, table)`` identity is an
        enumerated catalog relation (case-insensitive, like DuckDB's unquoted
        identifiers; a ``None``-catalog view belongs to the connection's own
        in-memory catalog)."""
        catalog, schema, table = (part.casefold() for part in identity)
        in_memory = self.default_catalog.casefold()
        for approved_catalog, approved_schema, approved_table in self.relations:
            if approved_table.casefold() != table or approved_schema.casefold() != schema:
                continue
            if approved_catalog is None:
                if catalog == in_memory:
                    return True
            elif approved_catalog.casefold() == catalog:
                return True
        return False

    def describe(self, limit: int = 8) -> str:
        """The bounded list of approved relation names for refusal guidance."""
        names = sorted(
            ".".join(part for part in relation if part is not None) for relation in self.relations
        )
        shown = ", ".join(_bound_name(name) for name in names[:limit])
        if not names:
            return "none attached"
        if len(names) > limit:
            return f"{shown}, +{len(names) - limit} more"
        return shown


def assert_ad_hoc_authority(fragment: str, *, kind: str, authority: AdHocAuthority) -> None:
    """Authorize one untrusted Analyst SQL fragment (``kind`` is ``"source"``
    or ``"expression"``) against ``authority``: the WHOLE nested tree — every
    CTE, derived table, join and scalar/predicate subquery — may read only the
    enumerated catalog relations and call only the reviewed analytics
    functions. Any refusal raises ``ValueError`` BEFORE the grain guard, the
    compile gate, bind or collection: nothing staged, nothing executed
    (issue #59 AC1/AC2)."""
    for tree in _parse_fragment(fragment, kind=kind):
        _assert_statement_shape(tree, kind=kind)
        _assert_no_side_effects(tree, kind=kind)
        _assert_functions(tree, kind=kind)
        _assert_relations(tree, kind=kind, authority=authority)


def _parse_fragment(fragment: str, *, kind: str) -> list[exp.Expr]:
    """Both dialect parses of one fragment: the generic dialect the compiler
    parses it with (that tree is what reaches execution as SQL) and the DuckDB
    dialect that interprets it. The source wrap mirrors
    :func:`ariadne.render._source_subquery` exactly, so the validated text is
    the text the compiler parses. Anything unparseable or not exactly one
    statement is refused here — fail closed on AST ambiguity (issue #59 AC1)."""
    text = fragment.strip()
    if kind == "source" and not _SOURCE_PREFIX_RE.match(text):
        text = f"(SELECT * FROM {text})"
    trees: list[exp.Expr] = []
    for dialect in (None, "duckdb"):
        try:
            statements = sqlglot.parse(text, dialect=dialect)
        except Exception as exc:
            raise ValueError(f"{_parse_guidance(kind)}: {_first_line(exc)}") from exc
        if len(statements) != 1 or statements[0] is None:
            raise ValueError(
                f"the ad-hoc {kind} must be exactly one statement, got {len(statements)} "
                f"(no-unvalidated-execution invariant, spec §6); {AD_HOC_AUTHORITY_GUIDANCE}"
            )
        trees.append(statements[0])
    return trees


def _parse_guidance(kind: str) -> str:
    """The unparseable-fragment refusal opening (kept compatible with the
    compile gate's verbatim-error contract for the two shapes tests pin)."""
    if kind == "source":
        return "the ad-hoc source must be exactly one statement; could not parse it"
    return "could not parse expression for the ad-hoc metric; it must be exactly one expression"


def _first_line(exc: BaseException) -> str:
    """The parser error's bounded first line (its following lines repeat the
    SQL text; the refusal never echoes the fragment back)."""
    text = " ".join(str(exc).split())[:200]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _assert_statement_shape(tree: exp.Expr, *, kind: str) -> None:
    """A source is one SELECT/WITH query; an expression is one expression — a
    statement-shaped ``expression`` (a bare SELECT) is not an expression."""
    if kind == "source":
        if not isinstance(tree, _QUERY_STATEMENTS):
            raise ValueError(
                f"the ad-hoc source must be one SELECT (or WITH ... SELECT) query, got "
                f"{type(tree).__name__}; {AD_HOC_AUTHORITY_GUIDANCE}"
            )
    elif isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect)) or isinstance(
        tree, _SIDE_EFFECT_NODES
    ):
        raise ValueError(
            f"the ad-hoc expression must be one expression, not a {type(tree).__name__} "
            f"statement; {AD_HOC_AUTHORITY_GUIDANCE}"
        )


def _assert_no_side_effects(tree: exp.Expr, *, kind: str) -> None:
    """No DML/DDL/command/transaction node anywhere in the tree — nested inside
    a CTE, a subquery or a function argument alike (issue #59 AC1: reject
    nested side-effect constructs before DuckDB)."""
    for node in tree.walk():
        if isinstance(node, _SIDE_EFFECT_NODES):
            raise ValueError(
                f"the ad-hoc {kind} carries a {type(node).__name__} construct; ad-hoc "
                f"definitions never modify data or the catalog; {AD_HOC_AUTHORITY_GUIDANCE}"
            )


def _assert_functions(tree: exp.Expr, *, kind: str) -> None:
    """Every function call must be a reviewed pure built-in analytics function,
    positively listed above — unknown names, schema-qualified calls and typed
    sqlglot nodes alike are refused (never a blacklist, never the DuckDB
    catalog)."""
    for node in tree.find_all(exp.Func):
        if isinstance(node, _SYNTAX_NODES):
            continue  # CASE/CAST/EXTRACT/EXISTS/AND/OR: syntax, not a callable
        name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).upper()
        if not name or name not in REVIEWED_SQL_FUNCTIONS:
            raise ValueError(
                f"the ad-hoc {kind} calls {_bound_name(name or '?')}(...), which is not one "
                "of the reviewed built-in analytics functions (aggregates, arithmetic, "
                "date/time, string, conditional and cast operations over the registered "
                f"relations); {AD_HOC_AUTHORITY_GUIDANCE}"
            )
        if _reaches_dot(node):
            raise ValueError(
                f"the ad-hoc {kind} calls the schema-qualified function "
                f"{_bound_name(name)}(...) — only unqualified built-in analytics functions "
                f"are supported; {AD_HOC_AUTHORITY_GUIDANCE}"
            )


def _reaches_dot(node: exp.Expr) -> bool:
    """Whether a call is reached through a dotted chain (``duckdb.read_csv``):
    sqlglot keeps only the final name on the call node, so the qualification
    itself must be refused rather than trusted to be harmless."""
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Dot):
            return True
        parent = parent.parent
    return False


def _assert_relations(tree: exp.Expr, *, kind: str, authority: AdHocAuthority) -> None:
    """Every physical relation of every query scope in the tree must be an
    enumerated catalog relation. Scope-aware resolution (SQLGlot's own scope
    machinery, the same selected_sources seam
    ``QueryRuntime._direct_table_dependencies`` uses) resolves CTE and
    derived-table aliases through their own scopes — they are never physical
    relations, while their defining statements are checked like any other
    scope."""
    for query in _outermost_queries(tree):
        scope = build_scope(query)
        if not isinstance(scope, Scope):
            raise ValueError(
                f"could not scope the ad-hoc {kind}'s {type(query).__name__} — refused "
                f"rather than guessed; {AD_HOC_AUTHORITY_GUIDANCE}"
            )
        _assert_scope_relations(scope, kind=kind, authority=authority)


def _outermost_queries(tree: exp.Expr) -> list[exp.Expr]:
    """The query roots of a tree: the statement itself for a source, and every
    query NOT nested inside another one for an expression (its scalar
    subqueries). Nested queries are reached through their owning scope's CTE/
    derived/subquery scopes, where CTE names still resolve (a detached
    branch scope would misread a CTE reference as a physical table)."""
    queries: list[exp.Expr] = []
    for node in tree.find_all(*_QUERY_STATEMENTS):
        parent = node.parent
        while parent is not None and not isinstance(parent, _QUERY_STATEMENTS):
            parent = parent.parent
        if parent is None:
            queries.append(node)
    return queries


def _assert_scope_relations(scope: Scope, *, kind: str, authority: AdHocAuthority) -> None:
    """Check every nested scope through SQLGlot's version-stable traversal.

    CTE/derived aliases resolve to their defining Scope; only physical Table
    entries require catalog authorization. The traversal includes their
    definitions, set operations and predicate/scalar subqueries."""
    seen: set[int] = set()
    for current in scope.traverse():
        if id(current) in seen:
            continue
        seen.add(id(current))
        for udtf in current.udtfs:
            raise ValueError(
                f"the ad-hoc {kind} reads the table function "
                f"{_bound_name(udtf.alias_or_name or '?')}(...) — table functions never enter "
                f"ad-hoc execution; {AD_HOC_AUTHORITY_GUIDANCE}"
            )
        for _alias, entry in (current.selected_sources or {}).items():
            table, origin = entry
            if isinstance(origin, Scope):
                continue
            _authorize_relation(table, kind=kind, authority=authority)


def _authorize_relation(table: exp.Expr, *, kind: str, authority: AdHocAuthority) -> None:
    """One physical FROM-clause reference must resolve to an enumerated catalog
    relation under DuckDB's own qualification rules."""
    if not isinstance(table, exp.Table):
        raise ValueError(
            f"unsupported ad-hoc {kind} relation {type(table).__name__}; "
            f"{AD_HOC_AUTHORITY_GUIDANCE}"
        )
    if not isinstance(table.this, exp.Identifier):
        # a table FUNCTION in FROM (read_blob('...'), read_parquet('...'),
        # generate_series(...)): sqlglot keeps the call node in the table slot
        call = table.this
        function = call.name if isinstance(call, exp.Anonymous) else type(call).__name__
        raise ValueError(
            f"the ad-hoc {kind} reads the table function {_bound_name(function)}(...) — "
            f"raw file/network/table-function scans never enter ad-hoc execution; "
            f"{AD_HOC_AUTHORITY_GUIDANCE}"
        )
    parts = [part.name for part in table.parts]
    reference = ".".join(part for part in parts if part)
    lowered = reference.casefold()
    if len(parts) > 3:
        raise ValueError(
            f"the ad-hoc {kind} reads the {len(parts)}-part reference "
            f"{_bound_name(reference)}; {AD_HOC_AUTHORITY_GUIDANCE}"
        )
    if "/" in lowered or "\\" in lowered or _URI_SCHEME_RE.match(lowered):
        raise ValueError(
            f"the ad-hoc {kind} scans {_bound_name(reference)} directly — ad-hoc SQL "
            f"never opens files or URIs; {AD_HOC_AUTHORITY_GUIDANCE}"
        )
    if len(parts) == 3:
        identity = (parts[0], parts[1], parts[2])
    elif len(parts) == 2:
        # DuckDB accepts both schema.table and attached_catalog.table shorthand.
        if authority.authorizes((parts[0], authority.default_schema, parts[1])):
            return
        identity = (authority.default_catalog, parts[0], parts[1])
    else:
        identity = (authority.default_catalog, authority.default_schema, parts[0])
    if authority.authorizes(identity):
        return
    qualifier = next((part for part in reversed(parts[:-1]) if part), "")
    if qualifier.casefold() in _METADATA_SCHEMAS:
        raise ValueError(
            f"the ad-hoc {kind} reads the {_bound_name(qualifier)} metadata catalog — "
            f"metadata catalogs never enter ad-hoc execution; {AD_HOC_AUTHORITY_GUIDANCE}"
        )
    raise ValueError(
        f"the ad-hoc {kind} reads {_bound_name(reference)}, which is not one of the "
        f"registered catalog relations ({authority.describe()}); {AD_HOC_AUTHORITY_GUIDANCE}"
    )

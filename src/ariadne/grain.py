"""The grain-preservation guard, shared by the facade and the validate audit.

Spec rev 5 §13: agent-authored sources whose joins fan out the fact grain are
rejected (upstream finding Datus-ai/Datus-agent#1426: the compiler aggregates
at joined-row grain and does NOT prevent this). ONE implementation, two entry
points (mvp-5 round 2 owner decision — structural guard reuse over further
tracer patching):

- ``ariadne.serve`` applies it to ad-hoc ``define_metric`` sources before
  compile: nothing staged, nothing executed.
- ``ariadne.validate``'s grain audit applies it to every authored dataset
  source — any join ANYWHERE in the tree (CTEs included) must be
  grain-preserving; the audit's sum-invariance assertions stay as secondary
  defense in depth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

# sqlglot exposes its AST node module lazily (sqlglot.exp is a real module but not
# statically exported), so resolve it at runtime like the duckdb imports above.
_exp = getattr(sqlglot, "exp")

if TYPE_CHECKING:
    from duckdb import DuckDBPyConnection  # pyright: ignore[reportMissingImports]

# Rev 6: the guidance names the ADR-0006 resolution rubric by pattern instead of
# the bare GROUP BY phrasing. Shared by every rejection branch of
# check_grain_preserving so tests and agents see one text.
GRAIN_GUIDANCE = (
    "source violates the grain-preservation invariant: a join fans out the fact "
    "grain (its key is not unique on the joined side), so aggregates over the joined "
    "rows would double-count. Resolve the relationship per the ADR-0006 rubric "
    "(project/adr/0006-grain-governance-multi-cardinality-joins.md): upstream conditional "
    "pivot (Pattern 1), child-grain fact model (Pattern 2), or fact weight allocation "
    "(Pattern 5) — the many side must be pre-aggregated to the fact grain inside "
    "source before registration; nothing staged, nothing executed."
)


@dataclass(frozen=True)
class TargetKeyAudit:
    """Live audit facts for one relationship target key (issue #27; ADR-0006
    §5 composite-key exactness): full TUPLE uniqueness plus non-NULL key
    components, distinct from :func:`check_grain_preserving`'s stricter
    per-column legacy check."""

    rows: int
    duplicates: int
    null_rows: int

    @property
    def ok(self) -> bool:
        return self.duplicates == 0 and self.null_rows == 0


def _audit_statement(source: str, keys: tuple[str, ...]) -> str:
    """Assemble the one-scan audit SELECT from compiler-rendered key
    expressions (fix pass F1: nothing here interpolates raw field text)."""
    wrapped = f"({source})" if re.match(r"(?is)\s*(select|with)\b", source) else (
        f"(SELECT * FROM {source})"
    )
    key_list = ", ".join(keys)
    complete = " AND ".join(f"{key} IS NOT NULL" for key in keys)
    nulls = " OR ".join(f"{key} IS NULL" for key in keys)
    # duplicates counts repeated COMPLETE non-null key tuples: COUNT(DISTINCT)
    # skips NULLs for single-column keys, so NULL rows must not be counted as
    # duplicates — they are their own null_rows finding.
    return (
        f"SELECT COUNT(*), COUNT(DISTINCT ({key_list})) FILTER (WHERE {complete}), "
        f"COUNT(*) FILTER (WHERE {nulls}) FROM {wrapped}"
    )


def relationship_target_audit(
    con: DuckDBPyConnection, source: str, keys: tuple[str, ...]
) -> TargetKeyAudit:
    """Exact composite target-key uniqueness + NULL-component audit over a
    relationship target source, one scan (issue #27). Returns facts; callers
    own error reporting. Unlike :func:`check_grain_preserving` (per-column,
    stricter, for legacy authored sources), this is exact tuple uniqueness —
    the many_to_one/one_to_one guarantee the planner's in-branch lookup joins
    and the validation graph audit rely on.

    ``keys`` are key EXPRESSIONS (a field name or its resolved expression SQL).
    Graph validation accepts quote-bearing field names, so no key may reach the
    statement as raw text: every key is parsed and re-rendered by sqlglot
    (embedded quotes double into one quoted identifier), and the assembled
    audit must parse back as exactly ONE statement — anything else fails
    closed before execution (fix pass F1; no-unvalidated-execution, spec §6).
    """
    if not keys:
        raise ValueError("relationship target key audit requires at least one key field")
    try:
        rendered = tuple(sqlglot.parse_one(key).sql(dialect="duckdb") for key in keys)
        sql = _audit_statement(source, rendered)
        statements = sqlglot.parse(sql)
    except Exception as exc:
        raise ValueError(
            f"relationship target-key audit did not compile as one statement: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if len(statements) != 1 or statements[0] is None:
        raise ValueError(
            f"relationship target-key audit must be exactly one statement, got "
            f"{len(statements)} — refusing (no-unvalidated-execution invariant, spec §6)"
        )
    # nosemgrep — never raw field text: every key above is compiler-rendered
    # with correct identifier quoting, the assembled statement is proven single
    # above, and the source is the staged authored declaration (spec §6).
    # pi-lens-ignore: python-sql-injection — compiler-rendered identifiers, proven single statement
    fetched = con.execute(sql).fetchone()  # nosemgrep — read-only attach, compiler-rendered keys
    rows, distinct_complete, null_rows = fetched or (0, 0, 0)
    return TargetKeyAudit(
        rows=rows, duplicates=rows - null_rows - distinct_complete, null_rows=null_rows
    )


def check_grain_preserving(con: DuckDBPyConnection, source: str) -> None:
    """Reject sources whose joins fan out the fact grain (spec rev 5 §13).

    Rule: for every join in the source, each ON key must be unique on the JOINED
    side — joins run many-to-one from the fact table. The compiler does not
    enforce this (Datus-ai/Datus-agent#1426: it aggregates at joined-row grain),
    so the guard does, before compile: for each key it runs
    ``SELECT COUNT(*) = COUNT(DISTINCT <key>) FROM <joined side>`` on the
    read-only attach. ``find_all`` walks the WHOLE tree, so joins hidden inside
    CTEs are guarded exactly like top-level ones. Subquery join targets
    (pre-aggregated lines) are checked the same way as plain tables, which is
    exactly how a one-to-many gets legitimate. Fail-closed on anything it cannot
    prove: missing ON (cross/comma join), an ON with no attributable equality
    key (``ON TRUE``, a pure inequality) or a non-conjunctive predicate (OR'd
    keys — per-key uniqueness proves nothing about the OR as a whole), a
    non-column or unattributable key, or a check that does not bind.

    Rejection raises ValueError(GRAIN_GUIDANCE): nothing staged, nothing executed.

    ponytail: PoC-scale exactness — one COUNT scan per key per call (fine at demo
    scale; cache/EXPLAIN ANALYZE if sources grow), and composite keys are checked
    per column (stricter than tuple-uniqueness — may reject a grain-safe join on
    two individually-duplicate keys; rare, fail-closed is the safe direction).
    """
    try:
        tree = sqlglot.parse_one(source)
    except Exception:
        return  # not one parseable statement — the compile gate owns that error verbatim
    for join in tree.find_all(_exp.Join):
        on = join.args.get("on")
        if on is None:  # CROSS/comma join: unbounded multiplication, no key to prove
            raise ValueError(GRAIN_GUIDANCE)
        if isinstance(on, (_exp.Or, _exp.Xor, _exp.Not)):  # non-conjunctive: per-key
            raise ValueError(GRAIN_GUIDANCE)  # uniqueness proves nothing — fail closed
        eqs = list(on.find_all(_exp.EQ))
        if not eqs:  # ON TRUE / pure inequality: zero provable keys, fan-out and all
            raise ValueError(GRAIN_GUIDANCE)
        side = join.this  # the joined table or subquery expression
        qualifier = side.alias_or_name
        for eq in eqs:
            key = next(
                (
                    c
                    for c in (eq.left, eq.right)
                    if isinstance(c, _exp.Column) and c.table == qualifier
                ),
                None,
            )
            if key is None:  # key not attributable to the joined side — cannot prove
                raise ValueError(GRAIN_GUIDANCE)
            check = (
                f"SELECT COUNT(*) = COUNT(DISTINCT {key.sql(dialect='duckdb')}) "
                f"FROM {side.sql(dialect='duckdb')}"
            )
            try:
                # nosemgrep — never raw source text: sqlglot re-renders its own parse
                # tree (multi-statement input cannot reach here — parse_one rejects
                # it), and the check runs on the read-only attach (spec §6).
                row = con.execute(check).fetchone()  # nosemgrep — read-only attach, no side effects
            except Exception as exc:  # unresolvable standalone — cannot prove, reject
                raise ValueError(GRAIN_GUIDANCE) from exc
            if row is None or not row[0]:
                raise ValueError(GRAIN_GUIDANCE)

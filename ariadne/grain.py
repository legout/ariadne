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
    "(docs/adr/0006-grain-governance-multi-cardinality-joins.md): upstream conditional "
    "pivot (Pattern 1), child-grain fact model (Pattern 2), or fact weight allocation "
    "(Pattern 5) — the many side must be pre-aggregated to the fact grain inside "
    "source before registration; nothing staged, nothing executed."
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

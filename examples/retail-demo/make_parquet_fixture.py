#!/usr/bin/env python3
"""Deterministic support-tickets parquet fixture (spec rev 9 Lane B, §8.20).

Writes ``<outdir>/*.parquet`` (default ``examples/retail-demo/data/support_tickets/``), sharded by
year — the registry's parquet glob (``table: tickets``) turns the whole
directory into one view ``support.tickets`` alongside the demo sqlite source.

Deterministic by construction: seeded RNG, fixed row count, fixed severities.
Re-running converges to identical files (idempotent).

Schema (200 tickets):
  ticket_id        INTEGER  primary key 1..200
  customer_id      INTEGER  FK-shaped reference into demo.customers.id (1..30)
  status           TEXT     'open' | 'closed'
  severity         TEXT     'low' | 'medium' | 'high' | 'critical'
  created_at       TEXT     ISO-8601 'YYYY-MM-DD HH:MM:SS', 2024-01-01..2025-06-30
  resolution_hours DOUBLE   hours open->closed; NULL while status = 'open'

The NULL-for-open rule is the seed-notes rule ("average resolution excludes
open tickets") made visible in the data.

Usage:
    python examples/retail-demo/make_parquet_fixture.py [outdir]
    # default: examples/retail-demo/data/support_tickets
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTDIR = REPO_ROOT / "data" / "support_tickets"

SEED = 42
TICKET_COUNT = 200
CUSTOMER_COUNT = 30  # matches examples/retail-demo/seed_db.py customers so joins are plausible

FIRST_TICKET = datetime(2024, 1, 1)
LAST_TICKET = datetime(2025, 6, 30)

# severity -> (weight, resolution-hours low, high): the windows make
# "avg resolution by severity" a meaningful metric.
SEVERITIES = (
    ("low", 30, 24.0, 168.0),
    ("medium", 35, 12.0, 72.0),
    ("high", 25, 4.0, 24.0),
    ("critical", 10, 1.0, 8.0),
)
CLOSED_SHARE = 0.8


def build_rows(rng: random.Random) -> list[tuple]:
    weights = [s[1] for s in SEVERITIES]
    spans = {s[0]: (s[2], s[3]) for s in SEVERITIES}
    span_days = (LAST_TICKET - FIRST_TICKET).days
    rows = []
    for ticket_id in range(1, TICKET_COUNT + 1):
        created = FIRST_TICKET + timedelta(
            days=rng.randint(0, span_days),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )
        severity = rng.choices([s[0] for s in SEVERITIES], weights=weights, k=1)[0]
        closed = rng.random() < CLOSED_SHARE
        low, high = spans[severity]
        hours = round(rng.uniform(low, high), 1) if closed else None
        rows.append(
            (
                ticket_id,
                rng.randint(1, CUSTOMER_COUNT),
                "closed" if closed else "open",
                severity,
                created.strftime("%Y-%m-%d %H:%M:%S"),
                hours,
            )
        )
    return rows


def write_fixture(outdir: Path) -> list[Path]:
    rows = build_rows(random.Random(SEED))
    years = {row[4][:4] for row in rows}  # fixture invariant: the date bounds
    assert years <= {"2024", "2025"}, f"row year outside the shard plan: {sorted(years)}"
    outdir.mkdir(parents=True, exist_ok=True)
    for stale in outdir.glob("*.parquet"):  # converge: a re-run replaces every shard
        stale.unlink()
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE tickets ("
            "ticket_id INTEGER, customer_id INTEGER, status TEXT, "
            "severity TEXT, created_at TEXT, resolution_hours DOUBLE)"
        )
        for row in rows:  # bound parameters only; no SQL text assembly
            con.execute("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)", row)
        # Two static shards; the years assert above guarantees full coverage.
        written = [outdir / "tickets_2024.parquet", outdir / "tickets_2025.parquet"]
        con.table("tickets").filter(
            "created_at >= '2024-01-01' AND created_at < '2025-01-01'"
        ).write_parquet(str(written[0]))
        con.table("tickets").filter("created_at >= '2025-01-01'").write_parquet(str(written[1]))
    finally:
        con.close()
    return written


def summarize(written: list[Path]) -> str:
    """Stats over the same seeded rows the shards hold, via the relation API —
    no file paths in SQL text."""
    rows = build_rows(random.Random(SEED))
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TABLE tickets ("
            "ticket_id INTEGER, customer_id INTEGER, status TEXT, "
            "severity TEXT, created_at TEXT, resolution_hours DOUBLE)"
        )
        # parameterized insert — lens sink heuristic false positive
        # pi-lens-ignore: sql-injection-sink
        con.executemany("INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)", rows)
        stats = (
            con.table("tickets")
            .aggregate(
                "COUNT(*) AS n, COUNT(resolution_hours) AS closed, "
                "AVG(resolution_hours) FILTER (WHERE status = 'closed') AS avg_h"
            )
            .fetchone()
        )
    finally:
        con.close()
    if stats is None:  # unreachable for an aggregate query, but keeps pyright honest
        raise RuntimeError("fixture summary query returned no row")
    return (
        f"Wrote {len(written)} shard(s): {', '.join(p.name for p in written)}\n"
        f"  tickets: {stats[0]} (closed with resolution_hours: {stats[1]})\n"
        f"  avg resolution (closed only): {round(stats[2], 2)}h"
    )


def main() -> None:
    outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTDIR
    written = write_fixture(outdir)
    print(summarize(written))


if __name__ == "__main__":
    main()

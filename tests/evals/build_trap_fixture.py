"""Fan-out trap fixture builder (spec rev 5 §13) — scratch dataset + naive model.

Builds, into a caller-provided scratch root, the tiny deterministic dataset and
the OSI model for the eval's fan-out trap proof:

``trap.db``     orders 1:N order_lines — the classic fan-out. Three orders whose
                per-order line sums equal the order amounts, so the CORRECT
                SUM(orders.amount) is 700 (NA 300, EMEA 400) while the naive
                join would count order 1 three times and order 2 twice
                (NA 700, EMEA 400 = 1100 overall).
``semantic/``   one OSI model whose dataset source bakes the orders⋈lines join
                in and sums BOTH the order amount and the line amounts over the
                joined rows — the naive join WOULD inflate order totals.

The eval test compiles this scratch set through the same Datus gate the facade
uses (a real Facade over the scratch tree) and asserts the compiled result
equals the correct deduplicated value. A failure there is the documented
INFLATED finding (lane report.md) — do not weaken the assertion to pass.
"""

import sqlite3
from pathlib import Path

# The naive model: the 1:N join lives inside the dataset source, and both the
# order amount and the line amount are summed over the joined rows.
TRAP_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: trap_orders
    description: Naive orders-to-lines join (fan-out trap)
    datasets:
      - name: trap_join
        source: >-
          SELECT o.order_id, o.region, o.amount, l.line_amount
          FROM demo.main.orders o
          JOIN demo.main.order_lines l ON l.order_id = o.order_id
        primary_key: [order_id]
        fields:
          - name: order_id
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_id
          - name: region
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: region
            dimension: {}
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
          - name: line_amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: line_amount
    metrics:
      - name: orders_total
        description: SUM of the order amount over the naive join (the trap)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: lines_total
        description: SUM of the line amounts (immune to this fan-out by construction)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""

# (order_id, region, amount) and the per-order lines, whose sums equal the
# order amounts — the deduplicated ground truth the trap test asserts on.
ORDERS = [(1, "NA", 100.0), (2, "NA", 200.0), (3, "EMEA", 400.0)]
LINES = [
    (11, 1, 60.0),
    (12, 1, 30.0),
    (13, 1, 10.0),  # order 1: 3 lines, sum 100
    (21, 2, 150.0),
    (22, 2, 50.0),  # order 2: 2 lines, sum 200
    (31, 3, 400.0),  # order 3: 1 line, sum 400
]


def build(root: Path) -> Path:
    """Write trap.db + the scratch served tree under ``root``; return ``root``."""
    root.mkdir(parents=True, exist_ok=True)
    db = root / "trap.db"
    con = sqlite3.connect(db)
    try:
        con.executescript(
            """
            DROP TABLE IF EXISTS orders;
            DROP TABLE IF EXISTS order_lines;
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY,
                region   TEXT NOT NULL,
                amount   REAL NOT NULL
            );
            CREATE TABLE order_lines (
                line_id     INTEGER PRIMARY KEY,
                order_id    INTEGER NOT NULL REFERENCES orders (order_id),
                line_amount REAL NOT NULL
            );
            """
        )
        con.executemany("INSERT INTO orders VALUES (?, ?, ?)", ORDERS)
        con.executemany("INSERT INTO order_lines VALUES (?, ?, ?)", LINES)
        con.commit()
    finally:
        con.close()

    (root / "semantic" / "models").mkdir(parents=True, exist_ok=True)
    (root / "semantic" / "models" / "trap.yml").write_text(TRAP_MODEL, encoding="utf-8")
    (root / "context").mkdir(exist_ok=True)  # Facade requires the path; unused by get_metric
    _assert_planted_premise(db)
    return root


def _assert_planted_premise(db: Path) -> None:
    """The trap premise: per-order line sums equal the order amounts, so the
    deduplicated totals are known (NA 300, EMEA 400) while the raw joined rows
    would sum higher. Fails loudly if the fixture ever stops fanning out.
    Static single-table reads; the arithmetic happens in Python."""
    with sqlite3.connect(db) as con:
        orders = con.execute("SELECT order_id, region, amount FROM orders").fetchall()
        lines = con.execute("SELECT order_id, line_amount FROM order_lines").fetchall()
    lines_per_order: dict[int, int] = {}
    for order_id, line_amount in lines:
        lines_per_order[order_id] = lines_per_order.get(order_id, 0) + 1
        assert any(o[0] == order_id for o in orders), "orphan line"
    assert sum(la for _, la in lines) == 700.0, "line sums must equal the order amounts"
    assert sum(amount for _, _, amount in orders) == 700.0, "order amounts must total 700"
    joined_naive = sum(amount * lines_per_order[oid] for oid, _, amount in orders)
    assert joined_naive == 1100.0, "the naive join must inflate (1100 > 700)"
    naive_region: dict[str, float] = {}
    for oid, region, amount in orders:
        naive_region[region] = naive_region.get(region, 0.0) + amount * lines_per_order[oid]
    assert naive_region == {"NA": 700.0, "EMEA": 400.0}, "NA must carry the fan-out"

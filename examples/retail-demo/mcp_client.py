#!/usr/bin/env python3
"""Scripted MCP stdio client for the Ariadne facade (ticket #6, spec §8.7).

Spawns ``python -m ariadne.serve`` over stdio and runs the acceptance calls:
``list_metrics()``, ``search_context("gross margin")``,
``get_metric("gross_margin", ["region"])``, ``get_metric("order_count",
["region"])``, and one unknown-metric error display. Output is human-readable;
the two metric results are asserted against tests/fixtures/expected_metrics.json
(hand-computed; order-insensitive via region-keyed dicts, rounded to the
fixture's precision — same rule as tests/test_serve.py). Exit 0 = all served.

Usage::

    python examples/retail-demo/mcp_client.py [--db examples/retail-demo/data/demo.db]
        [--semantic semantic_layer] [--context context_layer]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((REPO_ROOT / "tests" / "fixtures" / "expected_metrics.json").read_text())


def result_data(res) -> Any:
    """Unwrap a tool result to its payload.

    FastMCP wraps non-dict returns as ``{"result": [...]}`` in structuredContent;
    serve.py's bare ``dict`` tools carry no output schema, so their payload is
    JSON in the first text content block.
    """
    data = res.structuredContent
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    if data is not None:
        return data
    return json.loads(res.content[0].text)


def error_text(res) -> str:
    return "\n".join(getattr(content, "text", "") for content in res.content)


def rows_by_region(result: dict, column: str) -> dict:
    """Order-insensitive view: rows may arrive in any order."""
    return {row["region"]: row[column] for row in result["rows"]}


def assert_matches_fixture(result: dict, metric: str) -> None:
    precision = FIXTURE["_meta"]["precision"][metric]
    actual = {
        region: round(value, precision) if isinstance(precision, int) else int(value)
        for region, value in rows_by_region(result, metric).items()
    }
    assert actual == FIXTURE[metric], f"{metric} mismatch: {actual} != {FIXTURE[metric]}"


def show_rows(result: dict) -> None:
    columns = result["columns"]
    print("  columns:", ", ".join(columns))
    for row in result["rows"]:
        cells = (
            f"{row[col]:.6f}" if isinstance(row[col], float) else str(row[col]) for col in columns
        )
        print("   ", "  ".join(f"{cell:>14}" for cell in cells))
    print("  compiled SQL:")
    print("\n".join(f"    {line}" for line in result["sql"].splitlines()))


async def run(args: argparse.Namespace) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "ariadne.serve",
            "--db",
            args.db,
            "--semantic",
            args.semantic,
            "--context",
            args.context,
        ],
        cwd=str(REPO_ROOT),  # serve.py resolves layers relative to the repo root
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("== list_metrics()")
            metrics = result_data(await session.call_tool("list_metrics", {}))
            for entry in metrics[:-1]:
                print(f"  {entry['name']}: {entry['description']}")
            hint = metrics[-1]  # spec rev 4 §8.12: the response ends with the routing hint
            assert isinstance(hint, str) and "define_metric" in hint, "routing hint missing"
            print(f"  routing hint: {hint}")
            assert {"gross_margin", "order_count"} <= {m["name"] for m in metrics[:-1]}

            print('== search_context("gross margin")')
            hits = result_data(await session.call_tool("search_context", {"query": "gross margin"}))
            assert hits, "no context hits for 'gross margin'"
            for hit in hits[:3]:
                print(f"  {hit['score']:>3}  {hit['path']}")

            for metric in ("gross_margin", "order_count"):
                print(f'== get_metric("{metric}", dimensions=["region"])')
                result = result_data(
                    await session.call_tool(
                        "get_metric", {"name": metric, "dimensions": ["region"]}
                    )
                )
                show_rows(result)
                assert_matches_fixture(result, metric)
                print(f"  matches tests/fixtures/expected_metrics.json ({metric})")

            print('== get_metric("nonexistent") — expected error (spec §7)')
            res = await session.call_tool(
                "get_metric", {"name": "nonexistent", "dimensions": ["region"]}
            )
            assert res.isError, "unknown metric must error, never execute"
            print("  " + error_text(res).replace("\n", "\n  "))

    print()
    print("OK: acceptance calls served; metric rows match the hand-computed fixture")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scripted MCP client: run the spec §8 acceptance calls against the facade."
    )
    parser.add_argument(
        "--db", default="examples/retail-demo/data/demo.db", help="SQLite database to attach"
    )
    parser.add_argument("--semantic", default="semantic_layer", help="served OSI layer directory")
    parser.add_argument("--context", default="context_layer", help="served OKF layer directory")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

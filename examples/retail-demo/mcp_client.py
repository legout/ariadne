#!/usr/bin/env python3
"""Run the retail MCP example against an explicitly admitted Git project.

The project's source data and authored layers must match the retail fixtures;
expected rows come from the independent hand-computed test fixture.

Usage::

    python examples/retail-demo/mcp_client.py --project /path/to/retail-project
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
    ClientSession,
    StdioServerParameters,
)
from mcp.client.stdio import (  # pyright: ignore[reportMissingImports] — the [mcp] extra
    stdio_client,
)

REPO_ROOT = Path(__file__).resolve().parents[2]  # examples/retail-demo/ → repo root
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "expected_metrics.json"


def _fixture() -> dict:
    """The hand-computed expectations, loaded lazily: a missing or corrupt
    fixture must surface through main()'s FAIL report, never an import-time
    traceback."""
    try:
        return json.loads(FIXTURE_PATH.read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"expected-metrics fixture unreadable ({FIXTURE_PATH}): {exc}") from exc


def result_data(res) -> Any:
    """Unwrap a tool result to its payload.

    MCPServer (mcp 2.x) wraps non-dict returns as ``{"result": [...]}`` in
    structuredContent; serve.py's bare ``dict`` tools carry no output schema,
    so their payload is JSON in the first text content block.
    """
    data = res.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    if data is not None:
        return data
    try:
        return json.loads(res.content[0].text)
    except ValueError as exc:
        raise RuntimeError(f"tool result payload is not JSON: {exc}") from exc


def error_text(res) -> str:
    return "\n".join(getattr(content, "text", "") for content in res.content)


def rows_by_region(result: dict, column: str) -> dict:
    """Order-insensitive view: rows may arrive in any order."""
    return {row["region"]: row[column] for row in result["rows"]}


def assert_matches_fixture(result: dict, metric: str) -> None:
    fixture = _fixture()
    precision = fixture["_meta"]["precision"][metric]
    actual = {
        region: round(value, precision) if isinstance(precision, int) else int(value)
        for region, value in rows_by_region(result, metric).items()
    }
    assert actual == fixture[metric], f"{metric} mismatch: {actual} != {fixture[metric]}"


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
            "--project",
            str(Path(args.project).resolve()),
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
            assert res.is_error, "unknown metric must error, never execute"
            print("  " + error_text(res).replace("\n", "\n  "))

    print()
    print("OK: acceptance calls served; metric rows match the hand-computed fixture")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scripted MCP client: run the spec §8 acceptance calls against the facade."
    )
    parser.add_argument(
        "--project", required=True, help="Git-managed project with a valid admitted snapshot"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""MCP facade server (ticket #5): three governed tools over stdio.

Exactly three tools (spec §4):

    list_metrics()                     -> served governed metrics with descriptions
    search_context(query)              -> ranked matches over context_layer/**/*.md
    get_metric(name, dimensions, range)-> rows PLUS the compiled SQL (provenance)

Mechanism per docs/research/datus-spike.md §5: Datus compiles the OSI metric to
SQL (``query_metrics(dry_run=True)`` -> ``metadata["sql"]``) and the
facade-owned DuckDB connection — with the SQLite database ATTACHed read-only as
catalog ``demo`` — executes it. ``range`` is an optional ``{start, end}`` applied
by the compiler to the metric's primary date dimension.

Invariants and failure behavior (spec §6/§7): ``get_metric`` accepts only named
governed metrics — never raw SQL; unknown metric -> error listing the available
metrics; Datus absent/broken or no served models -> fail fast at startup with an
install hint.

Usage::

    python -m ariadne.serve --db data/demo.db \\
        --semantic semantic_layer --context context_layer
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

# Captured when datus is missing so startup can fail fast with a hint (spec §7).
# The imports live inside the try: a missing datus must not abort the module import
# itself — the CLI fails fast with INSTALL_HINT instead of a raw ImportError.
# Tests exercise the branch offline via monkeypatching / blocked imports.
try:
    from datus_semantic_osi.adapter import DatusOSIAdapter  # pyright: ignore[reportMissingImports]
    from datus_semantic_osi.config import DatusOSIConfig  # pyright: ignore[reportMissingImports]

    _DATUS_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:
    DatusOSIAdapter = None  # type: ignore[assignment, misc]
    DatusOSIConfig = None  # type: ignore[assignment, misc]
    _DATUS_IMPORT_ERROR = exc

INSTALL_HINT = (
    "datus-semantic-osi is required to serve governed metrics "
    "(uv pip install 'datus-semantic-osi[metricflow]' on Python 3.12)"
)


class Facade:
    """Governed-metric facade: Datus compile + facade-owned DuckDB execution."""

    def __init__(self, semantic_dir: str | Path, context_dir: str | Path, db_path: str | Path):
        if _DATUS_IMPORT_ERROR is not None:  # spec §7: fail fast with the hint
            raise RuntimeError(f"{INSTALL_HINT}: {_DATUS_IMPORT_ERROR}")
        assert DatusOSIAdapter is not None and DatusOSIConfig is not None

        self.context_dir = Path(context_dir)
        models = Path(semantic_dir) / "models"
        if not models.is_dir():
            raise RuntimeError(
                f"no semantic models under {models} — promote staging/semantic_layer/ first"
            )
        self.adapter = DatusOSIAdapter(DatusOSIConfig(semantic_models_path=str(models)))
        try:
            metrics = asyncio.run(self.adapter.list_metrics())
        except Exception as exc:
            raise RuntimeError(f"served OSI models under {models} do not compile: {exc}") from exc
        if not metrics:  # spec §7: nothing servable -> fail fast, not at query time
            raise RuntimeError(f"no governed metrics found under {models}")
        self._metrics: dict[str, Any] = {metric.name: metric for metric in metrics}

        # Spike §6.2: non-DuckDB attaches are connection-local, so the facade
        # attaches once on its long-lived connection; compiled SQL references
        # demo.main.<table> (the authoring contract's catalog name).
        self.con = duckdb.connect()
        self.con.execute(f"ATTACH '{Path(db_path)}' AS demo (TYPE SQLITE, READ_ONLY)")

    async def list_metrics(self) -> list[dict]:
        return [
            {"name": metric.name, "description": metric.description or ""}
            for metric in self._metrics.values()
        ]

    async def get_metric(
        self,
        name: str,
        dimensions: list[str] | None = None,
        range: dict | None = None,  # noqa: A002 — spec §4 names the parameter
    ) -> dict:
        if name not in self._metrics:  # spec §7: discovery before failure
            available = ", ".join(sorted(self._metrics))
            raise ValueError(f"unknown metric {name!r}; available metrics: {available}")
        time_start = range.get("start") if range else None
        time_end = range.get("end") if range else None
        result = await self.adapter.query_metrics(
            metrics=[name],
            dimensions=dimensions or [],
            time_start=time_start,
            time_end=time_end,
            dry_run=True,
        )
        sql = (result.metadata or {}).get("sql")
        if not sql:
            raise RuntimeError(f"Datus returned no compiled SQL for metric {name!r}")
        # Compiled by Datus from the human-promoted OSI models only — never from
        # user input (get_metric takes a metric name, not SQL text, spec §6).
        relation = self.con.execute(sql)
        columns = [description[0] for description in relation.description]
        rows = [dict(zip(columns, row)) for row in relation.fetchall()]
        return {
            "metric": name,
            "dimensions": dimensions or [],
            "columns": columns,
            "rows": rows,
            "sql": sql,
        }

    async def search_context(self, query: str, limit: int = 10) -> list[dict]:
        """Rank OKF pages by query-term frequency (name-anchored ties by path)."""
        terms = query.lower().split()
        hits: list[dict] = []
        for path in sorted(self.context_dir.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            score = sum(text.lower().count(term) for term in terms)
            if not score:
                continue
            hits.append(
                {
                    "path": path.relative_to(self.context_dir).as_posix(),
                    "score": score,
                    "content": text,  # full OKF page: the rules are the payload
                }
            )
        hits.sort(key=lambda hit: (-hit["score"], hit["path"]))
        return hits[:limit]


def build_app(facade: Facade):
    """Wire the facade onto an MCP stdio server: exactly three tools (spec §4)."""
    from mcp.server.fastmcp import FastMCP  # pyright: ignore[reportMissingImports]

    app: FastMCP = FastMCP("ariadne")

    @app.tool()
    async def list_metrics() -> list[dict]:
        """List the served governed metrics with their descriptions."""
        return await facade.list_metrics()

    @app.tool()
    async def search_context(query: str) -> list[dict]:
        """Search the Context Layer (OKF pages) for business rules; ranked matches."""
        return await facade.search_context(query)

    @app.tool()
    async def get_metric(
        name: str, dimensions: list[str] | None = None, range: dict | None = None
    ) -> dict:
        """Rows plus compiled SQL for a named governed metric — never raw SQL.

        Args:
            name: governed metric name (see list_metrics).
            dimensions: dimensions to group by (e.g. ["region"]).
            range: optional {"start", "end"} dates on the primary date dimension.
        """
        return await facade.get_metric(name, dimensions, range)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ariadne.serve",
        description="MCP stdio facade over the served context and semantic layers.",
    )
    parser.add_argument("--db", default="data/demo.db", help="SQLite database to attach read-only")
    parser.add_argument("--semantic", default="semantic_layer", help="served OSI layer directory")
    parser.add_argument("--context", default="context_layer", help="served OKF layer directory")
    args = parser.parse_args(argv)

    try:
        facade = Facade(args.semantic, args.context, args.db)
    except Exception as exc:  # fail fast before any MCP traffic
        print(f"error: {exc}", file=sys.stderr)
        return 1
    build_app(facade).run()  # stdio transport
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

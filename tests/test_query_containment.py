"""Issue #59 (spec 0014 §9): the static ad-hoc IO-authority boundary at the
ONE shared seam — public ``QueryRuntime.define_metric`` — behind the Python
API, the CLI, the Facade and the Analyst MCP toolset.

The runtime under test is a REAL runtime over a tiny declared CSV registry
source (values 2 and 3): no adapter, authority helper or implementation under
test is mocked. The canary is a synthetic readable file OUTSIDE the project
(``OUTSIDE_PROJECT_CANARY_DO_NOT_RETURN``) — never a real secret.

Expectations are derived independently of the implementation (issue #59):

- the declared fixture values 2 and 3 sum to 5 — hand-arithmetic, not output;
- every IO-authority refusal raises ``ValueError`` BEFORE any caller-derived
  DuckDB call: grain probes, bind (EXPLAIN) and collection all stay unreached
  (grain/bind/collect sentinels plus a connection spy counting every call that
  reaches the owned connection), nothing is staged, and no refusal carries the
  canary bytes or their hex form;
- sanctioned SELECT/CTE/grain-safe-join definitions over the declared relation
  keep working (issue #59 AC3) — the boundary confines reads, not analytics.
"""

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.query import QueryRuntime  # pyright: ignore[reportMissingImports] — drift

REPO_ROOT = Path(__file__).resolve().parents[1]

CANARY = b"OUTSIDE_PROJECT_CANARY_DO_NOT_RETURN"
CANARY_TEXT = CANARY.decode("ascii")
CANARY_HEX = CANARY.hex().upper()

# One governed model over the declared registry view (vals.vals) so the runtime
# constructs and compiles exactly like every production route.
_MODELS = """version: 0.2.0.dev0
semantic_model:
  - name: probe
    description: containment probe
    datasets:
      - name: vals
        source: vals.vals
        fields:
          - name: v
            expression: {dialects: [{dialect: ANSI_SQL, expression: v}]}
    metrics:
      - name: total
        description: sum of the fixture values
        expression: {dialects: [{dialect: ANSI_SQL, expression: "SUM(v)"}]}
"""


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    """An isolated project with a declared CSV source (values 2 and 3) plus a
    readable canary directory OUTSIDE the project — a permissions failure can
    never masquerade as containment (issue #59)."""
    root = tmp_path_factory.mktemp("containment_project")
    (root / "data").mkdir()
    (root / "data" / "vals.csv").write_text("v\n2\n3\n", encoding="utf-8")
    (root / "semantic_layer" / "models").mkdir(parents=True)
    (root / "semantic_layer" / "models" / "probe.yml").write_text(_MODELS, encoding="utf-8")
    (root / "context_layer").mkdir()
    registry = root / "ariadne.yaml"
    registry.write_text(
        f"sources:\n  - name: vals\n    type: csv\n    path: {root / 'data' / 'vals.csv'}\n",
        encoding="utf-8",
    )
    outside = root.parent / f"{root.name}-outside-project"
    outside.mkdir()
    (outside / "private.txt").write_bytes(CANARY)
    (outside / "private.csv").write_text(f"v\n{CANARY_TEXT}\n", encoding="utf-8")
    # the canary is runtime-readable: an OS permissions refusal is not containment
    for probe in (outside / "private.txt", outside / "private.csv"):
        assert probe.read_bytes() and os.access(probe, os.R_OK), f"canary {probe} unreadable"
    return root, registry, outside


@pytest.fixture(scope="module")
def runtime(project):
    root, registry, _outside = project
    return QueryRuntime(
        root / "semantic_layer",
        root / "context_layer",
        None,  # the registry route: no legacy --db attach
        staging_dir=root / "staging",
        sources=str(registry),
    )


def _staged(runtime: QueryRuntime) -> set[str]:
    staging = runtime.staging_dir
    if not staging.exists():
        return set()
    return {str(path.relative_to(staging)) for path in staging.rglob("*") if path.is_file()}


class _ConnectionSpy:
    """Counts every CALL that reaches the owned DuckDB connection (execute,
    sql, fetch*): a pre-DuckDB refusal performs none — attribute reads such as
    the deadline guard's ``interrupt`` lookup are forwarded, not counted."""

    def __init__(self, con) -> None:
        self._con = con
        self.calls: list[str] = []

    def __getattr__(self, name):
        attr = getattr(self.__dict__["_con"], name)
        if not callable(attr):
            return attr

        def traced(*args, **kwargs):
            self.__dict__["calls"].append(name)
            return attr(*args, **kwargs)

        return traced


@pytest.fixture
def pre_duckdb_spies(runtime, monkeypatch):
    """Grain/bind/collect sentinels plus the connection spy: if the boundary is
    bypassed, the sentinel replaces the refusal with an AssertionError, and any
    call the caller-derived SQL would have caused is counted — never mocked is
    the boundary helper itself or anything it calls."""

    def unreachable(*args, **kwargs):  # pragma: no cover - only on a bypass
        raise AssertionError("caller-derived SQL reached DuckDB before the IO-authority refusal")

    spy = _ConnectionSpy(runtime._execution.con)
    monkeypatch.setattr(runtime._execution, "con", spy)
    monkeypatch.setattr(runtime, "con", spy)
    monkeypatch.setattr("ariadne.query.check_grain_preserving", unreachable)
    monkeypatch.setattr(runtime._execution, "bind", unreachable)
    monkeypatch.setattr(runtime, "_collect", unreachable)
    return spy


def _refusal_definitions(project) -> dict[str, dict]:
    _root, _registry, outside = project
    private_txt = outside / "private.txt"
    private_csv = outside / "private.csv"
    probe = "Synthetic IO-boundary regression only (issue #59)"
    return {
        "source_read_blob": {
            "name": "outside_project_read_probe",
            "description": probe,
            "source": f"SELECT content FROM read_blob('{private_txt}')",
            "expression": "MAX(HEX(content))",
        },
        "expression_scalar_subquery": {
            "name": "expression_subquery_probe",
            "description": probe,
            "source": "vals.vals",
            "expression": f"(SELECT MAX(HEX(content)) FROM read_blob('{private_txt}'))",
        },
        "nested_cte_alias": {
            "name": "cte_smuggle_probe",
            "description": probe,
            "source": (
                f"WITH leak AS (SELECT content FROM read_blob('{private_txt}')) "
                "SELECT content FROM leak"
            ),
            "expression": "MAX(HEX(content))",
        },
        "derived_table_alias": {
            "name": "derived_alias_probe",
            "description": probe,
            "source": f"SELECT content FROM (SELECT content FROM read_blob('{private_txt}')) leak",
            "expression": "MAX(HEX(content))",
        },
        "typed_read_csv_node": {
            "name": "typed_node_probe",
            "description": probe,
            "source": f"SELECT * FROM read_csv('{private_csv}')",
            "expression": "MAX(v)",
        },
        "path_as_table_shorthand": {
            "name": "path_shorthand_probe",
            "description": probe,
            "source": f"SELECT * FROM '{private_csv}'",
            "expression": "MAX(v)",
        },
        "indirect_query_function": {
            "name": "indirect_query_probe",
            "description": probe,
            "source": "SELECT * FROM query('SELECT 42 AS v')",
            "expression": "MAX(v)",
        },
        "indirect_query_table_function": {
            "name": "indirect_query_table_probe",
            "description": probe,
            # the target is an APPROVED relation: indirect SQL functions are
            # refused regardless of what they would resolve to (issue #59 AC1)
            "source": "SELECT * FROM query_table('vals.vals')",
            "expression": "MAX(v)",
        },
        "special_node_generate_series": {
            "name": "special_node_probe",
            "description": probe,
            "source": "SELECT v FROM generate_series(1, 3) AS t(v)",
            "expression": "SUM(v)",
        },
        "metadata_catalog_information_schema": {
            "name": "metadata_catalog_probe",
            "description": probe,
            "source": "SELECT COUNT(*) AS n FROM information_schema.tables",
            "expression": "MAX(n)",
        },
    }


@pytest.mark.parametrize(
    "case",
    sorted(
        _refusal_definitions_names := {
            "source_read_blob",
            "expression_scalar_subquery",
            "nested_cte_alias",
            "derived_table_alias",
            "typed_read_csv_node",
            "path_as_table_shorthand",
            "indirect_query_function",
            "indirect_query_table_function",
            "special_node_generate_series",
            "metadata_catalog_information_schema",
        }
    ),
)
def test_ad_hoc_io_authority_refuses_before_duckdb(case, runtime, project, pre_duckdb_spies):
    """Issue #59 AC1/AC2: every distinct bypass shape — read_blob in source or
    expression scalar subquery, CTE/derived aliases, typed table-function
    nodes, path-as-table shorthand, indirect query()/query_table() and metadata
    catalogs — is refused by ValueError BEFORE any caller-derived DuckDB call,
    leaks no canary content (raw or hex), and stages nothing."""
    definition = _refusal_definitions(project)[case]
    before = _staged(runtime)
    expected = "may read only the registered catalog relations"
    with pytest.raises(ValueError, match=expected) as raised:
        asyncio.run(runtime.define_metric(dict(definition)))
    message = str(raised.value)
    # no canary content or encoded form in any refusal (issue #59 AC2)
    assert CANARY_TEXT not in message
    assert CANARY_HEX not in message.upper()
    assert CANARY.hex() not in message.lower()
    # the refusal preceded grain/bind/collection and every DuckDB call
    assert pre_duckdb_spies.calls == []
    # nothing staged: no proposal model or draft context page appeared
    assert _staged(runtime) == before


@pytest.mark.parametrize(
    ("name", "source", "expression"),
    [
        ("declared_relation_sum", "vals.vals", "SUM(v)"),
        ("cte_sum", "WITH base AS (SELECT v FROM vals.vals) SELECT v FROM base", "SUM(v)"),
        (
            "grain_safe_join_sum",
            "SELECT a.v AS v FROM vals.vals a JOIN vals.vals b ON a.v = b.v",
            "SUM(v)",
        ),
    ],
)
def test_sanctioned_definitions_stay_usable(name, source, expression, runtime):
    """Issue #59 AC3: sanctioned SELECT, CTE and grain-safe-join definitions
    over the declared relation still execute — 2 + 3 = 5 from the fixture, not
    from implementation output — and stage their proposals as before."""
    result = asyncio.run(
        runtime.define_metric(
            {
                "name": name,
                "description": "AC3 positive control",
                "source": source,
                "expression": expression,
                "dimensions": [],
            }
        )
    )
    assert result["governed"] is False
    (value,) = (row[name] for row in result["rows"])
    assert value == 5  # independent expectation: fixture values 2 and 3
    assert Path(result["staged_as"]).is_file() and Path(result["staged_context_as"]).is_file()
    Path(result["staged_as"]).unlink()
    Path(result["staged_context_as"]).unlink()


def test_attached_catalog_shorthand_stays_usable(tmp_path):
    """AC3: DuckDB's catalog.table shorthand retains the declared 2 + 3 = 5."""
    database = tmp_path / "demo.db"
    with sqlite3.connect(database) as con:
        con.execute("CREATE TABLE vals (v INTEGER)")
        con.execute("INSERT INTO vals VALUES (2), (3)")
    models = tmp_path / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "probe.yml").write_text(_MODELS.replace("vals.vals", "demo.vals"), encoding="utf-8")
    context = tmp_path / "context_layer"
    context.mkdir()
    runtime = QueryRuntime(models.parent, context, database, staging_dir=tmp_path / "staging")
    try:
        result = asyncio.run(
            runtime.define_metric(
                {
                    "name": "attached_sum",
                    "description": "catalog shorthand positive control",
                    "source": "demo.vals",
                    "expression": "SUM(v)",
                    "dimensions": [],
                }
            )
        )
        assert result["governed"] is False
        assert result["rows"] == [{"attached_sum": 5}]
        assert Path(result["staged_as"]).is_file()
    finally:
        runtime.con.close()

"""Advisory supplied source-quality evidence (issues #53 + #54 /
spec 2026-10-06-0013 §§2–5, §7; plan §2).

Expectations are derived from the specification and plan contract, never from
the implementation under test:

- an admitted governed metric keeps its rows/SQL/governance while an EXPIRED
  supplied report is disclosed with its reported outcome/age/limitations
  (AC1); a recent event-time watermark and a reported completeness failure
  stay SEPARATE facts, neither implying live health (AC2);
- exact identity: same-named tables in distinct source assets never share a
  report by name (AC3's quality-only slice); evidence is read only from the
  exactly bound DIRECTLY CITED table page, and a supplied `source_version`
  alone never establishes correspondence — unknown applicability with the
  named limitation, never a matching pass (spec §3/§4);
- absent optional profiles and missing optionals stay explicit unknowns, and
  legacy queries remain usable (AC5);
- malformed/unsupported new declarations fail AUTHORING validation before
  human admission — never as a query refusal (AC6);
- reads are pure: identical retries do not alter the page bytes (AC9).

Issue #54 adds the multi-metric association slice (spec §4, §7 AC3/AC4/
AC7–AC9): exact dependency identity for multi-fact work through the executed
plan/graph, known period contradiction disclosed as inapplicable, expiry
boundaries crossed by assessment only, absent citations unread, explicit
reader-bounds truncation, and scope-aware CTE/derived-alias resolution.

All fixtures are explicitly synthetic; no real report was acquired, no source
probed, no external document read. The full ``context_signals``/``data_signals``
axis-separation assertions stay pending until accepted 0011 exists.
"""

import asyncio
import copy
import json
import re
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path, PurePath

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import context  # noqa: E402
from ariadne.context import _page_contract_errors, generated_page_filename  # noqa: E402
from ariadne.runtime import AriadneRuntime  # noqa: E402
from ariadne.sources import parse_resource, table_resource  # noqa: E402

# The pinned assessment instant every test derives its expectations from (the
# integrated internal clock seam, patched per test).
ASSESS_NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)

# (order_id, region, amount): the hand-computed governed answer is NA=2, EMEA=1.
ORDERS = [(1, "NA", 100.0), (2, "NA", 200.0), (3, "EMEA", 400.0)]

MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Orders model
    datasets:
      - name: orders
        source: demo.main.orders
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
    metrics:
      - name: order_count
        description: Count of all orders
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

# The expired supplied report of the AC1/AC2 fixture: validity past, a FAILED
# completeness check over an explicit tested period, AND a RECENT event-time
# watermark — three separate facts that never merge into a health claim.
EXPIRED_REPORT = {
    "id": "orders-completeness-2026-09",
    "source_ids": ["owner-report"],
    "scope": {
        "kind": "asset",
        "description": "All rows of the orders table as loaded upstream.",
        "population": "every row of the physical orders table",
        "period": None,
    },
    "reported_at": "2026-09-01T00:00:00+00:00",
    "observed_at": "2026-09-02T00:00:00+00:00",
    "source_version": {"kind": "version", "value": "pipeline-run-2026-09-01"},
    "provenance": "Domain owner's monthly completeness report, supplied explicitly.",
    "reported_by": "upstream pipeline owner",
    "cadence": "monthly",
    "valid_until": "2026-09-30T00:00:00+00:00",
    "checks": [
        {
            "id": "august-completeness",
            "kind": "completeness",
            "outcome": "fail",
            "criterion": "every order placed in the tested period is present",
            "tested_population": "all orders placed in the tested period",
            "tested_period": {
                "field": "order_date",
                "start": "2026-08-01T00:00:00+00:00",
                "end": "2026-09-01T00:00:00+00:00",
            },
        }
    ],
    "watermark": {
        "kind": "event_time",
        "value": "2026-10-06T23:00:00+00:00",
        "field": "order_date",
        "meaning": (
            "latest order event time observed upstream — an event-time boundary, "
            "not proof that every expected record has arrived"
        ),
        "units": "ISO 8601 instant",
        "timezone": "UTC",
        "observed_at": "2026-10-06T23:00:00+00:00",
    },
}

# The unknown-applicability control (AC5): subset scope, no supplied source
# version, no validity — every missing optional is an explicit limitation.
UNKNOWN_REPORT = {
    "id": "subset-availability",
    "source_ids": ["owner-report"],
    "scope": {
        "kind": "subset",
        "description": "Rows loaded by the nightly batch.",
        "population": "rows attributed to a nightly batch load",
        "period": None,
    },
    "reported_at": "2026-09-20T00:00:00+00:00",
    "checks": [
        {
            "id": "availability",
            "kind": "availability",
            "outcome": "pass",
            "criterion": "the nightly batch produced a load record",
            "tested_population": "nightly batch loads",
            "tested_period": None,
        }
    ],
}


def _sqlite_db(path: Path, rows: list[tuple]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(
            "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
            " amount REAL NOT NULL)"
        )
        # static literal SQL with ?-bound parameters; rows are module constants
        statement = "INSERT INTO orders VALUES (?, ?, ?)"
        con.executemany(statement, rows)  # pi-lens-ignore: python-sql-injection
        con.commit()
    finally:
        con.close()
    return path


def _project(
    tmp_path: Path,
    *,
    sources: dict[str, Path],
    quality_reports: list | None = None,
    bound_resource: str | None = None,
    metric_sources: list | None = None,
    model: str = MODEL_YML,
) -> tuple[AriadneRuntime, Path]:
    """A legacy-route runtime over one registered sqlite source per entry, the
    orders model (overridable — issue #54's CTE/period fixtures), an optional
    quality-profiled table page bound to ``bound_resource`` (default: the demo
    asset the model reads) and an optional consuming metric page whose
    ``sources[]`` carry the recorded DIRECT table citations (spec 0013 §4:
    only a citation recorded on the consuming side establishes a directly
    cited table page)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    registry_lines = ["sources:"]
    for name, db in sources.items():
        registry_lines += [f"  - name: {name}", "    type: sqlite", f"    path: {db}"]
    (project / "ariadne.yaml").write_text("\n".join(registry_lines) + "\n", encoding="utf-8")
    models = project / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "orders.yml").write_text(model, encoding="utf-8")
    context_dir = project / "context_layer"
    if metric_sources is not None:
        metrics_dir = context_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        (metrics_dir / "order_count.md").write_text(_metric_page(metric_sources), encoding="utf-8")
    if quality_reports is not None:
        resource = bound_resource or table_resource("demo", "demo", "main", "orders")
        page = context_dir / _cited_page_rel(resource)
        page.parent.mkdir(parents=True)
        page.write_text(_table_page(resource, quality_reports), encoding="utf-8")
    if metric_sources is not None or quality_reports is not None:
        # the served bundle's core-generated bookkeeping: the regenerated
        # index trees (spec 0010 §4 — ``resource`` markers make
        # ``tables/index.md`` the reader's resource->page resolution source)
        context._regenerate_indexes(context_dir)
    first_db = next(iter(sources.values()))
    runtime = AriadneRuntime(
        project / "semantic_layer",
        context_dir,
        first_db,
        staging_dir=project / "staging",
        sources=project / "ariadne.yaml",
    )
    return runtime, context_dir


def _quality_meta(resource: str, reports: list | None = None) -> dict:
    """The frontmatter meta of one bound table page, optionally carrying the
    supplied reports (each tied to the page's exact canonical asset)."""
    meta = {
        "type": "table",
        "title": "demo.main.orders",
        "description": "One row per order.",
        "tags": ["table"],
        "sources": [
            {
                "id": "owner-report",
                "resource": resource,
                "title": "owner-supplied source-quality report citation",
            }
        ],
        "resource": resource,
    }
    if reports is not None:
        meta["ariadne_quality"] = {
            "version": 1,
            "reports": [{**report, "asset": resource} for report in reports],
        }
    return meta


def _table_page(resource: str, reports: list | None = None) -> str:
    frontmatter = yaml.safe_dump(
        _quality_meta(resource, reports), sort_keys=False, allow_unicode=True
    ).strip()
    return f"---\n{frontmatter}\n---\n\n# Orders\n"


def _metric_page(sources: list) -> str:
    """The consuming metric's OKF page: its frontmatter ``sources[]`` record
    the DIRECT table citations — ``tables/...`` page paths or canonical table
    resources — that name the table pages allowed to supply evidence (spec
    0013 §4's "admitted table citations"; a table page citing its own source
    is a self-citation and establishes nothing)."""
    meta = {
        "type": "metric",
        "title": "order_count",
        "description": "Count of all orders",
        "sources": sources,
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n# order_count\n"


def _table_citation(resource: str) -> dict:
    """A direct table citation of one canonical resource, in the same
    ``{id, resource, title}`` form the OKF sources mechanism already uses."""
    return {
        "id": "orders-table",
        "resource": resource,
        "title": "the physical orders table",
    }


def _cited_page_rel(resource: str) -> str:
    """The served page path authoring generates for one canonical table
    resource (``<source-slug>-<sha256>.md`` — existing pages bound to
    resources keep their names; spec 0010 §4 makes the filename navigational
    and ``resource`` authoritative, so the reader resolves citations through
    the regenerated ``tables/index.md``, never through this convention)."""
    return f"tables/{generated_page_filename(resource, parse_resource(resource)[1][0])}"


def _rows_by_region(result: dict) -> dict:
    return {row["region"]: row["order_count"] for row in result["rows"]}


def _get_metric(runtime: AriadneRuntime, monkeypatch) -> dict:
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    return asyncio.run(runtime.get_metric("order_count", ["region"]))


def _report_views(result: dict) -> dict:
    [asset] = result["data_signals"]["assets"]
    return {view["id"]: view for view in asset["reports"]}


def _warning_codes(result: dict) -> set[str]:
    return {warning["code"] for warning in result["data_signals"]["warnings"]}


def test_expired_report_preserves_rows_sql_and_discloses_as_of_evidence(tmp_path, monkeypatch):
    """Spec §7 AC1 (quality-only slice) + AC2: the governed answer keeps its
    rows/SQL/governance over the same fixture with and without supplied
    evidence; the expired report is disclosed as-of with its failed outcome;
    the recent event watermark stays a separate fact that implies no health."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    plain, _ctx = _project(tmp_path / "plain", sources={"demo": db})
    quality, context_dir = _project(
        tmp_path / "quality",
        sources={"demo": db},
        quality_reports=[EXPIRED_REPORT, UNKNOWN_REPORT],
        metric_sources=[_table_citation(resource)],  # the consuming side cites
    )
    baseline = _get_metric(plain, monkeypatch)
    result = _get_metric(quality, monkeypatch)

    # the governed number is unchanged by the supplied evidence (spec §5);
    # row order is not guaranteed across independent executions (no ORDER BY)
    assert _rows_by_region(result) == _rows_by_region(baseline) == {"NA": 2, "EMEA": 1}
    assert result["sql"] == baseline["sql"] and result["governed"] is True

    signals = result["data_signals"]
    assert set(signals) == {
        "version",
        "assessed_at",
        "metrics",
        "assets",
        "warnings",
        "truncated",
        "omitted",
    }  # the closed view contract (plan §2)
    assert signals["assessed_at"] == ASSESS_NOW.isoformat()
    [metric] = signals["metrics"]
    resource = table_resource("demo", "demo", "main", "orders")
    assert metric == {"name": "order_count", "assets": [resource], "coverage": "unknown"}
    # the identified, cited dependency keeps its attached as-of evidence, but
    # COVERAGE stays unknown: version correspondence cannot be mechanically
    # established — the runtime holds no dataset-version fact to cross-check
    # the supplied source_version against (an admission digest is not a
    # dataset version), so no supplied-only version is a matching assessment
    # (spec §§3–4; plan §2's "unknown when correspondence/evidence is
    # unavailable")
    [asset] = signals["assets"]
    assert asset["resource"] == resource and asset["page"] == _cited_page_rel(resource)
    assert asset["coverage"] == "unknown"

    views = _report_views(result)
    expired = views["orders-completeness-2026-09"]
    assert expired["evidence_kind"] == "supplied"
    assert expired["age"] == "expired"  # supplied validity is past the assessment
    # the supplied source_version is an upstream CLAIM, not established
    # correspondence: unknown applicability with the named limitation, never
    # a matching pass (spec §3: "when correspondence cannot be established,
    # disclose the unknown applicability instead of normalizing or guessing")
    assert expired["applicability"] == "unknown"
    assert expired["limitations"] == ["source_version_unknown"]
    # the reported FAILED outcome is preserved with its tested scope (AC1)
    [(check)] = expired["checks"]
    assert check["outcome"] == "fail" and check["tested_period"]["field"] == "order_date"
    # the RECENT event watermark is preserved verbatim and stays an event-time
    # boundary — never relabeled ingestion/currency/completeness (AC2)
    watermark = expired["watermark"]
    assert watermark["kind"] == "event_time"
    assert watermark["value"] == "2026-10-06T23:00:00+00:00"  # recent vs ASSESS_NOW
    assert watermark["meaning"].startswith("latest order event time observed upstream")

    unknown = views["subset-availability"]
    assert unknown["age"] == "unknown" and unknown["applicability"] == "unknown"
    assert set(unknown["limitations"]) == {
        "scope_unknown",
        "source_version_unknown",
        "validity_not_supplied",
    }

    assert _warning_codes(result) == {
        "data_report_expired",
        "data_report_failed",
        "data_applicability_unknown",
    }
    assert signals["truncated"] is False
    assert signals["omitted"] == {"metrics": 0, "assets": 0, "pages": 0, "reports": 0}

    # AC9 (read-only): an identical retry returns the same assessment over the
    # same bytes and never restamps or rewrites the page
    page = context_dir / _cited_page_rel(resource)
    before = page.read_bytes()
    again = _get_metric(quality, monkeypatch)
    assert again["data_signals"] == result["data_signals"]
    assert _rows_by_region(again) == _rows_by_region(result) and again["sql"] == result["sql"]
    assert page.read_bytes() == before


def test_absent_profile_keeps_legacy_metric_usable_and_coverage_unknown(tmp_path, monkeypatch):
    """Spec §7 AC5: a project without the optional profile keeps its query
    behavior — the numerically valid query succeeds and discloses unknown
    coverage, with NO warning invented merely for the profile's absence."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    runtime, _ctx = _project(tmp_path / "proj", sources={"demo": db})
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric["coverage"] == "unknown"
    [asset] = signals["assets"]
    assert asset["page"] is None and asset["coverage"] == "unknown" and asset["reports"] == []
    assert signals["warnings"] == []


def test_later_unreadable_report_yields_unknown_evidence_and_query_succeeds(tmp_path, monkeypatch):
    """Spec §5: when declared report metadata later cannot be interpreted, the
    view exposes unknown evidence with the unavailability warning while the
    numerically valid query still succeeds — never a fabricated assessment,
    never a quality-based refusal."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    corrupted = copy.deepcopy(EXPIRED_REPORT)
    corrupted["reported_at"] = "2026-09-01T00:00:00"  # naive — no longer interpretable
    runtime, _ctx = _project(
        tmp_path / "proj",
        sources={"demo": db},
        quality_reports=[corrupted],
        metric_sources=[_table_citation(resource)],
    )
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric["coverage"] == "unknown"
    [asset] = signals["assets"]
    assert asset["coverage"] == "unknown" and asset["reports"] == []
    assert _warning_codes(result) == {"data_evidence_unavailable"}


def test_same_named_tables_in_distinct_sources_never_share_a_report_by_name(tmp_path, monkeypatch):
    """Spec §7 AC3 (quality-only slice): the executed query reads demo's
    orders; archive's same-named orders carries a valid report — the report
    stays on archive's exact canonical asset and never reaches the metric's
    evidence by table name."""
    demo_db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    archive_db = _sqlite_db(tmp_path / "archive.db", ORDERS)
    archive_resource = table_resource("archive", "archive", "main", "orders")
    demo_resource = table_resource("demo", "demo", "main", "orders")
    runtime, _ctx = _project(
        tmp_path / "proj",
        sources={"demo": demo_db, "archive": archive_db},
        quality_reports=[EXPIRED_REPORT],
        bound_resource=archive_resource,
        metric_sources=[_table_citation(demo_resource)],  # cites DEMO's asset only
    )
    # the fixture means what it asserts: two same-named catalog assets with
    # distinct canonical identities
    catalog_orders = {
        (source["name"], table["name"], table["resource"])
        for source in runtime.catalog
        for table in source["tables"]
        if table["name"] == "orders"
    }
    assert len(catalog_orders) == 2
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric["assets"] == [demo_resource]
    assert metric["coverage"] == "unknown"  # demo's asset has no report of its own
    [asset] = signals["assets"]
    assert asset["resource"] == demo_resource and asset["page"] is None
    assert asset["reports"] == []
    # the index holds no page bound to demo's resource (the only table page
    # declares archive's) — the URI citation cannot resolve and degrades to
    # the binding_unknown disclosure, never to a scan or a name-based guess
    assert _warning_codes(result) == {"data_binding_unknown"}
    # the archive report is nowhere in the metric's evidence
    import json

    assert archive_resource not in json.dumps(signals)


def test_only_directly_cited_table_pages_supply_evidence_and_consume_budget(tmp_path, monkeypatch):
    """Issue #53's interface (spec §4, §7 AC7): a DIRECT table citation is
    recorded on the CONSUMING metric page — a table page citing its own source
    through its own ``sources[]`` is a self-citation and establishes nothing.
    An unrelated earlier-sorting page carrying the SAME canonical resource and
    its own catalog citation therefore supplies NO evidence, and the 32-page
    budget counts pages PHYSICALLY READ during discovery, never bindings:
    unrelated pages are skipped unread whenever the cited set resolves without
    them, while a resource-cited page sorting after 32 reads is disclosed as
    truncated unknown coverage — never silently assessed, never hidden."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    filler_resource = table_resource("archive", "archive", "main", "orders")

    # (a) the consuming metric page cites ONE table page by path; an unrelated
    # earlier-sorting page carries the same resource, its own catalog
    # citation and a decoy report — only the cited page may supply evidence
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": db},
        metric_sources=[
            {"id": "orders-table", "resource": "tables/z-cited.md", "title": "orders page"}
        ],
    )
    tables = context_dir / "tables"
    tables.mkdir(parents=True)
    (tables / "a-unrelated.md").write_text(
        _table_page(resource, [{**EXPIRED_REPORT, "id": "unrelated-decoy"}]), encoding="utf-8"
    )
    (tables / "z-cited.md").write_text(_table_page(resource, [EXPIRED_REPORT]), encoding="utf-8")

    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # the query never degrades
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric["coverage"] == "unknown"  # no established version correspondence
    [asset] = signals["assets"]
    assert asset["resource"] == resource and asset["page"] == "tables/z-cited.md"
    assert [view["id"] for view in asset["reports"]] == ["orders-completeness-2026-09"]
    import json

    assert "unrelated-decoy" not in json.dumps(signals)
    # the skipped unrelated page consumed none of the page-read budget
    assert signals["truncated"] is False
    assert signals["omitted"] == {"metrics": 0, "assets": 0, "pages": 0, "reports": 0}
    # the cited (expired, reported-failed) report is disclosed as such — and
    # the skipped page contributes no unavailability warning
    assert _warning_codes(result) == {
        "data_report_expired",
        "data_report_failed",
        "data_applicability_unknown",
    }

    # (b) a canonical-URI citation resolves through the REGENERATED INDEX to
    # the exact page the served context binds that resource to — here an
    # ACTUAL (non-generated) name, ``tables/orders.md`` (spec 0010 §4:
    # ``resource`` is authoritative, filenames navigational; existing pages
    # bound to resources keep their names): 33 unrelated earlier-sorting
    # pages carrying the SAME canonical resource are never named by the
    # index for it — never candidates, never read, never charged to the
    # read budget — and the bound page supplies the evidence (spec §4: the
    # exact identity comes from the citation's index resolution, not from
    # scan order or a generated-name guess)
    uri_runtime, uri_context = _project(
        tmp_path / "uri",
        sources={"demo": db},
        metric_sources=[_table_citation(resource)],
    )
    uri_tables = uri_context / "tables"
    uri_tables.mkdir(parents=True)
    for index in range(33):
        (uri_tables / f"a{index:02d}.md").write_text(
            _table_page(resource, [{**EXPIRED_REPORT, "id": f"unrelated-decoy-{index}"}]),
            encoding="utf-8",
        )
    (uri_tables / "orders.md").write_text(_table_page(resource, [EXPIRED_REPORT]), encoding="utf-8")
    # the served core-generated index line for the bound page (the enriched
    # form ``_index_for`` emits — title, link, description, resource marker)
    (uri_tables / "index.md").write_text(
        "# Tables\n\n* [demo.main.orders](orders.md) - One row per order."
        f" - resource: `{resource}`\n",
        encoding="utf-8",
    )

    uri_result = _get_metric(uri_runtime, monkeypatch)
    assert _rows_by_region(uri_result) == {"NA": 2, "EMEA": 1}  # never a refusal
    uri_signals = uri_result["data_signals"]
    [uri_asset] = uri_signals["assets"]
    assert uri_asset["resource"] == resource and uri_asset["page"] == "tables/orders.md"
    assert [view["id"] for view in uri_asset["reports"]] == ["orders-completeness-2026-09"]
    import json

    assert "unrelated-decoy" not in json.dumps(uri_signals)
    # the never-read unrelated pages consumed none of the page-read budget
    assert uri_signals["truncated"] is False
    assert uri_signals["omitted"] == {"metrics": 0, "assets": 0, "pages": 0, "reports": 0}
    assert _warning_codes(uri_result) == {
        "data_report_expired",
        "data_report_failed",
        "data_applicability_unknown",
    }

    # (c) the one legitimate truncation scenario: MORE directly cited pages
    # than the budget reads — 33 path-cited pages, the 32nd read stops the
    # discovery, and the last-sorting cited page is disclosed as omitted
    # unknown coverage (a binding-count budget would have bound it silently)
    trunc_runtime, trunc_context = _project(
        tmp_path / "trunc",
        sources={"demo": db},
        metric_sources=[
            {"id": f"filler-{index}", "resource": f"tables/a{index:02d}.md", "title": "filler"}
            for index in range(32)
        ]
        + [{"id": "orders-table", "resource": "tables/z-budget.md", "title": "orders page"}],
    )
    trunc_tables = trunc_context / "tables"
    trunc_tables.mkdir(parents=True)
    for index in range(32):
        (trunc_tables / f"a{index:02d}.md").write_text(
            _table_page(filler_resource, None), encoding="utf-8"
        )
    (trunc_tables / "z-budget.md").write_text(
        _table_page(resource, [EXPIRED_REPORT]), encoding="utf-8"
    )

    trunc_result = _get_metric(trunc_runtime, monkeypatch)
    assert _rows_by_region(trunc_result) == {"NA": 2, "EMEA": 1}  # still never a refusal
    trunc_signals = trunc_result["data_signals"]
    [trunc_asset] = trunc_signals["assets"]
    assert trunc_asset["page"] is None and trunc_asset["coverage"] == "unknown"
    assert trunc_asset["reports"] == []
    assert trunc_signals["truncated"] is True
    assert trunc_signals["omitted"]["pages"] >= 1  # the read budget never reached it
    assert _warning_codes(trunc_result) == {"data_signals_truncated"}


def test_index_without_resource_markers_degrades_to_binding_unknown(tmp_path, monkeypatch):
    """Owner-approved fix4 design (spec 0010 §4 + spec 0013 §4): a PRE-EXISTING
    served context whose ``tables/index.md`` predates resource markers cannot
    resolve a canonical-URI citation — the citation degrades to the
    ``binding_unknown`` disclosure while the numerically valid query still
    succeeds; nothing is scanned, no table page is read (the budget is never
    charged), and no error escapes the advisory reader."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": db},
        metric_sources=[_table_citation(resource)],
    )
    tables = context_dir / "tables"
    tables.mkdir(parents=True)
    # the page COULD supply evidence, but the old-format index cannot name it
    (tables / "orders.md").write_text(_table_page(resource, [EXPIRED_REPORT]), encoding="utf-8")
    (tables / "index.md").write_text(
        "# Tables\n\n* [demo.main.orders](orders.md) - One row per order.\n",
        encoding="utf-8",
    )

    reads: list[str] = []
    real_read = context._read_page_meta_bounded

    def counting_read(path):
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr(context, "_read_page_meta_bounded", counting_read)
    result = _get_metric(runtime, monkeypatch)  # must not raise

    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # the query still succeeds
    signals = result["data_signals"]
    [asset] = signals["assets"]
    assert asset["resource"] == resource and asset["page"] is None
    assert asset["coverage"] == "unknown" and asset["reports"] == []
    assert _warning_codes(result) == {"data_binding_unknown"}
    [warning] = signals["warnings"]
    assert warning["asset"] == resource  # the disclosure names the citation
    # honest degradation reads NO table page: only the metric page was read
    assert [path for path in reads if PurePath(path).parent.name == "tables"] == []
    assert signals["truncated"] is False
    assert signals["omitted"] == {"metrics": 0, "assets": 0, "pages": 0, "reports": 0}


def test_bracketed_titles_still_resolve_through_the_index(tmp_path, monkeypatch):
    """Fix5 (delta-recheck finding; spec 0010 §4 + the owner-approved fix4
    design): ``_index_for`` preserves authored titles verbatim, so an enriched
    line's link label may itself contain ``]`` — here ``Orders [daily]``. The
    index line still carries the resource binding, so a URI-cited table with
    such a title must bind its supplied reports exactly as a plainly titled
    one does — never degrade to ``binding_unknown``."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": db},
        metric_sources=[_table_citation(resource)],
    )
    tables = context_dir / "tables"
    tables.mkdir(parents=True)
    meta = _quality_meta(resource, [EXPIRED_REPORT])
    meta["title"] = "Orders [daily]"  # authored titles are preserved verbatim
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    (tables / "orders.md").write_text(f"---\n{front}\n---\n\n# Orders\n", encoding="utf-8")
    # the served core-generated index carries the bracketed-title line
    context._regenerate_indexes(context_dir)
    index_line = next(
        line
        for line in (tables / "index.md").read_text(encoding="utf-8").splitlines()
        if "orders.md" in line
    )
    assert index_line == (
        f"* [Orders [daily]](orders.md) - One row per order. - resource: `{resource}`"
    )

    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # the query never degrades
    signals = result["data_signals"]
    [asset] = signals["assets"]
    assert asset["resource"] == resource and asset["page"] == "tables/orders.md"
    assert [view["id"] for view in asset["reports"]] == ["orders-completeness-2026-09"]
    assert _warning_codes(result) == {
        "data_report_expired",
        "data_report_failed",
        "data_applicability_unknown",
    }  # exactly the plainly-titled case's disclosure — no binding_unknown


def test_malformed_citation_id_never_fails_a_valid_query(tmp_path, monkeypatch):
    """Spec §5 / checklist item 4: a later-edited citation with a NON-STRING
    id (``id: [owner-report]``) is malformed advisory metadata — the computed
    numerical result is preserved and the view discloses unknown evidence
    with the unavailability warning; no exception escapes the advisory
    reader, and the authoring gate rejects the declaration before admission."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": db},
        quality_reports=[EXPIRED_REPORT],
        metric_sources=[_table_citation(resource)],
    )
    meta = _quality_meta(resource, [EXPIRED_REPORT])
    meta["sources"][0]["id"] = ["owner-report"]  # a later edit breaks the id type
    (context_dir / _cited_page_rel(resource)).write_text(
        f"---\n{yaml.safe_dump(meta, sort_keys=False).strip()}\n---\n\n# Orders\n",
        encoding="utf-8",
    )

    result = _get_metric(runtime, monkeypatch)  # must not raise
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1} and result["governed"] is True
    signals = result["data_signals"]
    [asset] = signals["assets"]
    assert asset["page"] == _cited_page_rel(resource)  # the bound page is still identified
    assert asset["coverage"] == "unknown" and asset["reports"] == []
    assert _warning_codes(result) == {"data_evidence_unavailable"}

    # the same malformed citation fails AUTHORING validation before admission
    staging, page = _staged_table_page(
        tmp_path / "gate", lambda m: m["sources"][0].__setitem__("id", ["owner-report"])
    )
    errors = _page_contract_errors(staging, page, "table")
    assert errors and all(error.startswith("context_layer/tables/orders.md") for error in errors)


# ---------------------------------------------- authoring validation (AC6)


def _staged_table_page(tmp_path: Path, mutator=None) -> tuple[Path, Path]:
    """One staged table page carrying both fixture reports; ``mutator``
    (called on the parsed frontmatter) builds the malformed variant. The
    fixture reports are DEEP-copied so every case starts from the clean
    shared fixture — a mutating case never leaks into the next one."""
    staging = tmp_path / "staging"
    page = staging / "context_layer" / "tables" / "orders.md"
    page.parent.mkdir(parents=True)
    resource = table_resource("demo", "demo", "main", "orders")
    meta = copy.deepcopy(_quality_meta(resource, [EXPIRED_REPORT, UNKNOWN_REPORT]))
    if mutator is not None:
        mutator(meta)
    frontmatter = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    page.write_text(f"---\n{frontmatter}\n---\n\n# Orders\n", encoding="utf-8")
    return staging, page


def test_valid_supplied_profile_passes_the_authoring_gate(tmp_path):
    staging, page = _staged_table_page(tmp_path)
    assert _page_contract_errors(staging, page, "table") == []


def test_malformed_supplied_profiles_fail_authoring_validation_before_admission(tmp_path):
    """Spec §2/§7 AC6: unsupported versions, naive/plain-date timestamps,
    executable payload keys, mismatched asset/citation identity, duplicate IDs
    and broken period/ordering/count invariants fail the shared per-type gate
    BEFORE human admission."""
    period_backwards = {"start": "2026-09-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"}

    def drop_tested_scope(meta: dict) -> None:
        check = meta["ariadne_quality"]["reports"][0]["checks"][0]
        for key in ("criterion", "tested_population", "tested_period"):
            check.pop(key)

    def nine_reports(meta: dict) -> None:
        lead = meta["ariadne_quality"]["reports"][0]
        meta["ariadne_quality"]["reports"] = [
            {**lead, "id": f"{lead['id']}-{index}"} for index in range(9)
        ]

    cases = {
        "unsupported-version": lambda m: m["ariadne_quality"].__setitem__("version", 2),
        "naive-iso-timestamp": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "reported_at", "2026-09-01T00:00:00"
        ),
        "naive-yaml-datetime": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "reported_at", datetime(2026, 9, 1)
        ),
        "plain-date-value": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "reported_at", date(2026, 9, 1)
        ),
        "executable-payload-key": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "sql", "SELECT 1"
        ),
        "mismatched-asset": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "asset", table_resource("other", "other", "main", "orders")
        ),
        "unresolved-citation": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "source_ids", ["no-such-citation"]
        ),
        "duplicate-report-ids": lambda m: m["ariadne_quality"]["reports"][1].__setitem__(
            "id", m["ariadne_quality"]["reports"][0]["id"]
        ),
        "period-start-not-before-end": lambda m: m["ariadne_quality"]["reports"][0]["checks"][
            0
        ].__setitem__("tested_period", {**period_backwards, "field": "order_date"}),
        "omitted-scope-period": lambda m: m["ariadne_quality"]["reports"][0]["scope"].pop(
            "period"
        ),  # plan §2: the field is required — null is the explicit
        # non-time-bounded declaration; omission is not one
        "validity-before-report": lambda m: m["ariadne_quality"]["reports"][0].__setitem__(
            "valid_until", "2026-08-01T00:00:00+00:00"
        ),
        "empty-checks": lambda m: m["ariadne_quality"]["reports"][0].__setitem__("checks", []),
        "check-without-tested-scope": drop_tested_scope,
        "page-without-resource-binding": lambda m: m.pop("resource"),
        "null-profile": lambda m: m.__setitem__("ariadne_quality", None),
        "report-count-bound": nine_reports,
    }
    for name, mutator in cases.items():
        staging, page = _staged_table_page(tmp_path / name, mutator)
        errors = _page_contract_errors(staging, page, "table")
        assert errors, f"{name}: expected an authoring-validation failure"
        assert all(error.startswith("context_layer/tables/orders.md") for error in errors), (
            name,
            errors,
        )


# ---------------------------------------------- issue #54 (spec 0013 §4/§7
# AC3/AC4/AC7/AC8/AC9; plan 0013 §2's multi-metric contract) — expectations
# derived from the specification/plan contract and independently declared
# identity tuples, never from the resolver/compiler under test.

# An unexpired asset-scoped supplied report (the archive fact's evidence).
AS_OF_REPORT = {
    "id": "archive-completeness-2026-10",
    "source_ids": ["owner-report"],
    "scope": {
        "kind": "asset",
        "description": "All rows of the archive orders table as loaded upstream.",
        "population": "every row of the physical archive orders table",
        "period": None,
    },
    "reported_at": "2026-10-01T00:00:00+00:00",
    "valid_until": "2027-01-01T00:00:00+00:00",
    "checks": [
        {
            "id": "archive-load-ok",
            "kind": "completeness",
            "outcome": "pass",
            "criterion": "every archived order row is present",
            "tested_population": "all archived orders",
            "tested_period": None,
        }
    ],
}

# An asset-scoped report whose evidence period is September 2026 and whose
# check FAILED — the period-contradiction fixture (the requested November
# range is provably outside the declared [start, end) evidence period).
PERIOD_REPORT = {
    "id": "orders-completeness-september",
    "source_ids": ["owner-report"],
    "scope": {
        "kind": "asset",
        "description": "Rows of the orders table loaded during September.",
        "population": "every row of the physical orders table",
        "period": {
            "field": "order_date",
            "start": "2026-09-01T00:00:00+00:00",
            "end": "2026-10-01T00:00:00+00:00",
        },
    },
    "reported_at": "2026-09-25T00:00:00+00:00",
    "valid_until": "2027-01-01T00:00:00+00:00",
    "checks": [
        {
            "id": "september-completeness",
            "kind": "completeness",
            "outcome": "fail",
            "criterion": "every order of the tested period is present",
            "tested_population": "all orders placed in the tested period",
            "tested_period": {
                "field": "order_date",
                "start": "2026-09-01T00:00:00+00:00",
                "end": "2026-10-01T00:00:00+00:00",
            },
        }
    ],
}

# The expiry-boundary fixture: validity ends BETWEEN two pinned assessment
# instants (ASSESS_NOW=12:00 < 13:00 < the later 14:00 read).
BOUNDARY_REPORT = {
    **EXPIRED_REPORT,
    "id": "orders-completeness-boundary",
    "reported_at": "2026-10-01T00:00:00+00:00",
    "valid_until": "2026-10-07T13:00:00+00:00",
}

# (order_id, region, amount, order_date): hand-derived sums — November range
# [Nov 1, Nov 30] keeps NA 50 / EMEA 400; [Sep 15, Nov 15] keeps NA 150.
DATED_ORDERS = [
    (1, "NA", 100.0, "2026-09-20"),
    (2, "NA", 50.0, "2026-11-03"),
    (3, "EMEA", 400.0, "2026-11-20"),
]

DATED_MODEL_YML = """\
version: 0.2.0.dev0
semantic_model:
  - name: orders
    description: Dated orders model
    datasets:
      - name: orders
        source: demo.main.orders
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
          - name: order_date
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: order_date
            dimension:
              is_time: true
          - name: amount
            expression:
              dialects:
                - dialect: ANSI_SQL
                  expression: amount
    metrics:
      - name: order_count
        description: Sum of order amounts at order grain
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
"""

# A dataset source that reads through a CTE: the alias is NOT a physical
# dependency — the resolved dependency is exactly demo's orders table.
CTE_MODEL_YML = MODEL_YML.replace(
    "        source: demo.main.orders\n",
    "        source: WITH recent AS (SELECT order_id, region, amount FROM"
    " demo.main.orders) SELECT order_id, region, amount FROM recent\n",
)

# A same-named CTE over the OTHER source's same-named table: scope-aware
# resolution must return archive's asset, never demo's same-named orders.
CTE_SHADOW_MODEL_YML = MODEL_YML.replace(
    "        source: demo.main.orders\n",
    "        source: WITH orders AS (SELECT order_id, region, amount FROM"
    " archive.main.orders) SELECT order_id, region, amount FROM orders\n",
).replace(
    "        expression: COUNT(*)\n",
    "        expression: SUM(amount)\n",
)

# The unqualified legacy shorthand: a bare table name is not an exact
# catalog/schema/source identity and stays UNKNOWN, never a guessed match.
BARE_MODEL_YML = MODEL_YML.replace("source: demo.main.orders", "source: orders")


def _dated_db(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(
            "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
            " amount REAL NOT NULL, order_date DATE NOT NULL)"
        )
        statement = "INSERT INTO orders VALUES (?, ?, ?, ?)"
        con.executemany(statement, DATED_ORDERS)  # pi-lens-ignore: python-sql-injection
        con.commit()
    finally:
        con.close()
    return path


# --- the admitted two-source multi-fact fixture (issues #54 checklist 1/3) ---

_MF_LIVE_DB_ROWS = ORDERS  # NA 300 / EMEA 400, hand-derived from the module rows
_MF_ARCHIVE_DB_ROWS = [(1, "EMEA", 400.0), (2, "EMEA", 900.0)]  # EMEA 1300

_MF_FACT_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: {model}
    description: {dataset} fact
    datasets:
      - name: {dataset}
        source: {source}
        primary_key: [order_id]
        fields:
          - name: order_id
            expression: {{dialects: [{{dialect: ANSI_SQL, expression: order_id}}]}}
          - name: region
            expression: {{dialects: [{{dialect: ANSI_SQL, expression: region}}]}}
            dimension: {{}}
          - name: amount
            expression: {{dialects: [{{dialect: ANSI_SQL, expression: amount}}]}}
    metrics:
      - name: {metric}
        dataset: {dataset}
        description: Sum of amounts
        expression: {{dialects: [{{dialect: ANSI_SQL, expression: SUM(amount)}}]}}
{derived}"""

_MF_DERIVED_METRIC = """\
      - name: combined_orders_total
        description: Live plus archive totals (cross-fact derived)
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: live_orders_total + archive_orders_total
"""

_MF_REGIONS_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: regions
    description: Region lookup
    datasets:
      - name: regions
        source: demo.main.regions
        primary_key: [region]
        fields:
          - name: region
            expression: {dialects: [{dialect: ANSI_SQL, expression: region}]}
          - name: zone
            expression: {dialects: [{dialect: ANSI_SQL, expression: zone}]}
            dimension: {}
    metrics:
      - name: region_count
        dataset: regions
        description: Count of regions
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: COUNT(*)
"""

_MF_GRAPH_YML = """\
version: 1
relationships:
  - name: live_region
    cardinality: many_to_one
    from_dataset: live_orders
    from_fields: [region]
    to_dataset: regions
    to_fields: [region]
  - name: archive_region
    cardinality: many_to_one
    from_dataset: archive_orders
    from_fields: [region]
    to_dataset: regions
    to_fields: [region]
conformed_dimensions:
  - name: region
    members:
      - dataset: live_orders
        field: region
      - dataset: archive_orders
        field: region
"""

_MF_POLICY_PAGE = (
    "---\ntype: policy\nstatus: draft\ntitle: Region rollup\n"
    "description: Roll up by region.\ntags: [policy]\nsources:\n"
    "  - id: seed-notes\n    resource: data/seed_notes.md\n    title: Seed notes\n"
    "---\n\n# Region rollup\n"
)


def _mf_metric_page(name: str, table_resources: list[str]) -> str:
    """One gate-clean bundle metric page: the mandatory governing Policy
    citation plus the DIRECT table citations of the metric's own facts."""
    citations = "".join(
        f"  - id: fact-table-{index}\n    resource: {resource}\n"
        "    title: the physical fact table\n"
        for index, resource in enumerate(table_resources)
    )
    return (
        f"---\ntype: metric\nstatus: draft\ntitle: {name}\n"
        f"description: The {name} metric.\ntags: [metric]\nsources:\n"
        "  - id: governing-policy\n    resource: policies/region-rollup.md\n"
        f"    title: Region rollup policy\n{citations}---\n\n# {name}\n"
    )


def _admit_quality_project(
    tmp_path: Path, *, quality: bool, at: str
) -> tuple[AriadneRuntime, Path]:
    """One TWO-SOURCE project (demo + archive, each with its own same-named
    ``orders`` table) whose multi-fact graph bundle — two facts, a shared
    region lookup, a cross-fact derived metric, metric pages citing their own
    facts' canonical resources, and (``quality=True``) archive's table page
    carrying the as-of supplied report — is validated, humanly Promoted under
    the pinned ``at`` stamp and served by an admitted runtime. The promoted
    ``served/context_layer`` path is returned for byte-purity assertions."""
    from ariadne.promote import promote_bundle

    project = tmp_path / "proj"
    project.mkdir(parents=True)
    demo_db = _sqlite_db(project / "mf.db", _MF_LIVE_DB_ROWS)
    archive_db = _sqlite_db(project / "archive.db", _MF_ARCHIVE_DB_ROWS)
    (project / "ariadne.yaml").write_text(
        "sources:\n"
        f"  - name: demo\n    type: sqlite\n    path: {demo_db}\n"
        f"  - name: archive\n    type: sqlite\n    path: {archive_db}\n",
        encoding="utf-8",
    )
    demo_resource = table_resource("demo", "demo", "main", "orders")
    archive_resource = table_resource("archive", "archive", "main", "orders")
    regions_resource = table_resource("demo", "demo", "main", "regions")
    con = sqlite3.connect(demo_db)
    try:
        con.executescript("CREATE TABLE regions (region TEXT PRIMARY KEY, zone TEXT NOT NULL)")
        con.executemany(
            "INSERT INTO regions VALUES (?, ?)",  # pi-lens-ignore: python-sql-injection
            [("NA", "north"), ("EMEA", "south")],
        )
        con.commit()
    finally:
        con.close()
    bundle = {
        "files": [
            {"path": "data/seed_notes.md", "content": "# Seed notes\n\nTwo facts.\n"},
            {
                "path": "semantic_layer/models/live_orders.yml",
                "content": _MF_FACT_MODEL.format(
                    model="live_orders",
                    dataset="live_orders",
                    source="demo.main.orders",
                    metric="live_orders_total",
                    derived="",
                ),
            },
            {
                "path": "semantic_layer/models/archive_orders.yml",
                "content": _MF_FACT_MODEL.format(
                    model="archive_orders",
                    dataset="archive_orders",
                    source="archive.main.orders",
                    metric="archive_orders_total",
                    derived=_MF_DERIVED_METRIC,
                ),
            },
            {"path": "semantic_layer/models/regions.yml", "content": _MF_REGIONS_MODEL},
            {"path": "semantic_layer/graph.yml", "content": _MF_GRAPH_YML},
            {"path": "context_layer/policies/region-rollup.md", "content": _MF_POLICY_PAGE},
            {
                "path": "context_layer/tables/live-orders.md",
                "content": _table_page(demo_resource, None),
            },
            {
                "path": "context_layer/tables/archive-orders.md",
                "content": _table_page(archive_resource, [AS_OF_REPORT] if quality else None),
            },
            {
                "path": "context_layer/tables/regions.md",
                "content": _table_page(regions_resource, None),
            },
            {
                "path": "context_layer/metrics/live_orders_total.md",
                "content": _mf_metric_page("live_orders_total", [demo_resource]),
            },
            {
                "path": "context_layer/metrics/archive_orders_total.md",
                "content": _mf_metric_page("archive_orders_total", [archive_resource]),
            },
            {
                "path": "context_layer/metrics/combined_orders_total.md",
                "content": _mf_metric_page(
                    "combined_orders_total", [demo_resource, archive_resource]
                ),
            },
            {
                "path": "context_layer/metrics/region_count.md",
                "content": _mf_metric_page("region_count", [regions_resource]),
            },
        ]
    }
    submission = tmp_path / "submission.json"
    submission.write_text(json.dumps(bundle), encoding="utf-8")
    from ariadne import authoring as _authoring  # noqa: F811 — local import style

    view = _authoring.submit_bundle(submission, project=project)
    assert view["status"] == "validated", view["errors"]
    promote_bundle(
        view["review_digest"],
        staging_root=project / "staging",
        served_root=project / "served",
        by="human:test",
        assume_yes=True,
        at=at,
    )
    runtime = AriadneRuntime(
        project / "served" / "semantic_layer",
        project / "served" / "context_layer",
        demo_db,
        staging_dir=project / "staging",
        sources=project / "ariadne.yaml",
    )
    return runtime, project / "served" / "context_layer"


def test_query_metrics_associates_each_metric_with_its_own_facts_exact_identity(
    tmp_path, monkeypatch
):
    """Issue #54 checklist 1/3, spec 0013 §7 AC3/AC4 (the distinct multi-fact
    partial-dependency failure): two independently declared source/catalog/
    schema/table tuples — demo and archive, each with its own same-named
    ``orders`` — are queried together. Expected identities come from the
    DECLARED tuples via the approved identity contract, never from the
    resolver under test: each metric is associated with exactly its own fact's
    asset (the archive report can never reach demo's asset, and a metric never
    inherits the whole query's asset union), the cross-fact derived metric's
    closure spans exactly its two facts, and the metric without its own
    report keeps partial/unknown coverage with its evidence visible — never
    "all sources passed"."""
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    demo_resource = table_resource("demo", "demo", "main", "orders")
    archive_resource = table_resource("archive", "archive", "main", "orders")
    regions_resource = table_resource("demo", "demo", "main", "regions")
    runtime, served_context = _admit_quality_project(
        tmp_path / "quality", quality=True, at="2026-10-07T09:00:00+00:00"
    )
    # the fixture means what it asserts: two same-named catalog assets with
    # distinct canonical identities, established BEFORE any query
    catalog_orders = {
        (source["name"], table["resource"])
        for source in runtime.catalog
        for table in source["tables"]
        if table["name"] == "orders"
    }
    assert len(catalog_orders) == 2

    request = {
        "metrics": ["live_orders_total", "archive_orders_total", "combined_orders_total"],
        "dimensions": ["region"],
    }
    result = asyncio.run(runtime.query_metrics(request))
    assert result["governed"] is True and len(sqlglot.parse(result["sql"])) == 1

    # hand-derived from the inserted fixture rows (NA 300, EMEA 400 live;
    # EMEA 1300 archive; the aligned union keeps NA's absent archive NULL)
    rows = {row["region"]: row for row in result["rows"]}
    assert rows["NA"]["live_orders_total"] == 300.0
    assert rows["NA"]["archive_orders_total"] is None
    assert rows["EMEA"]["live_orders_total"] == 400.0
    assert rows["EMEA"]["archive_orders_total"] == 1300.0
    assert rows["EMEA"]["combined_orders_total"] == 1700.0

    signals = result["data_signals"]
    assert set(signals) == {
        "version",
        "assessed_at",
        "metrics",
        "assets",
        "warnings",
        "truncated",
        "omitted",
    }  # the closed view contract (plan §2), shared with get_metric
    assert signals["assessed_at"] == ASSESS_NOW.isoformat()

    # PER-METRIC ASSOCIATION (AC4; the named whole-query-union failure): each
    # metric lists exactly its own fact's canonical asset
    metrics = {entry["name"]: entry for entry in signals["metrics"]}
    assert set(metrics) == {
        "live_orders_total",
        "archive_orders_total",
        "combined_orders_total",
    }
    assert metrics["live_orders_total"]["assets"] == [demo_resource]
    assert metrics["archive_orders_total"]["assets"] == [archive_resource]
    # the derived metric's closure provably spans exactly its two facts (the
    # plan's sorted branch order), never the shared lookup or anything else
    assert metrics["combined_orders_total"]["assets"] == [archive_resource, demo_resource]
    assert all(entry["coverage"] == "unknown" for entry in metrics.values())

    # EXACT IDENTITY (AC3): the archive report stays on archive's asset and
    # never reaches demo's same-named asset by name
    assets = {entry["resource"]: entry for entry in signals["assets"]}
    assert set(assets) == {demo_resource, archive_resource}  # shared, not duplicated
    assert assets[demo_resource]["reports"] == []
    assert assets[demo_resource]["page"] == "tables/live-orders.md"
    [report_view] = assets[archive_resource]["reports"]
    assert report_view["id"] == AS_OF_REPORT["id"]
    assert assets[archive_resource]["page"] == "tables/archive-orders.md"
    assert report_view["age"] == "as_of" and report_view["applicability"] == "unknown"
    assert report_view["limitations"] == ["source_version_unknown"]
    serialized = json.dumps(signals["assets"])
    assert serialized.count(AS_OF_REPORT["id"]) == 1  # attached to ONE asset only
    assert AS_OF_REPORT["id"] not in json.dumps(assets[demo_resource])

    # PARTIAL DEPENDENCY (AC4): demo's fact has NO report of its own — its
    # identified dependency keeps unknown coverage without an invented
    # warning, while archive's single unknown-applicability report warns once
    assert {warning["code"] for warning in signals["warnings"]} == {"data_applicability_unknown"}
    assert signals["truncated"] is False
    assert signals["omitted"] == {"metrics": 0, "assets": 0, "pages": 0, "reports": 0}

    # the lookup association through the plan's traversed joins: each fact
    # metric additionally carries the shared regions lookup it actually
    # joined — and the lookup's own page, cited by no REQUESTED metric page,
    # stays pageless unknown coverage without a scan or a guessed binding
    zone = asyncio.run(
        runtime.query_metrics(
            {"metrics": ["live_orders_total", "archive_orders_total"], "dimensions": ["zone"]}
        )
    )
    zone_rows = {row["zone"]: row for row in zone["rows"]}
    assert zone_rows["north"]["live_orders_total"] == 300.0  # hand-derived
    assert zone_rows["south"]["archive_orders_total"] == 1300.0
    zone_metrics = {entry["name"]: entry for entry in zone["data_signals"]["metrics"]}
    assert zone_metrics["live_orders_total"]["assets"] == [demo_resource, regions_resource]
    assert zone_metrics["archive_orders_total"]["assets"] == [
        archive_resource,
        regions_resource,
    ]
    zone_assets = {entry["resource"]: entry for entry in zone["data_signals"]["assets"]}
    assert zone_assets[regions_resource]["page"] is None  # never cited: unknown
    assert zone_assets[regions_resource]["reports"] == []
    assert zone_assets[regions_resource]["coverage"] == "unknown"
    assert "data_binding_unknown" not in _warning_codes(zone)  # nothing unresolved

    # BEFORE/AFTER DISCLOSURE (AC8/AC9, checklist 5): the identical query over
    # the same bundle WITHOUT the quality profile keeps every old envelope —
    # rows, SQL, plan, columns, context (incl. accepted context_signals) and
    # the admission view modulo its necessarily different digests — and the
    # retry is pure: identical bytes, identical assessment
    plain, _plain_context = _admit_quality_project(
        tmp_path / "plain", quality=False, at="2026-10-07T09:00:00+00:00"
    )
    baseline = asyncio.run(plain.query_metrics(request))
    for key in ("metrics", "dimensions", "columns", "sql", "plan"):
        assert baseline[key] == result[key], key
    assert sorted(baseline["rows"], key=lambda row: row["region"]) == sorted(
        result["rows"], key=lambda row: row["region"]
    )

    def _sans_machine_noise(payload: object) -> str:
        # the twins were finalized/promoted by independent wall-clock calls;
        # per-run ISO second stamps and per-bytes digests are machine facts,
        # not disclosure — normalized out so every CONTENT field compares exactly
        text = json.dumps(payload, default=str, sort_keys=True)
        text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", "<stamp>", text)
        text = re.sub(r"[0-9a-f]{64}", "<digest>", text)
        return text.replace(f"{tmp_path}/quality", "<project>").replace(
            f"{tmp_path}/plain", "<project>"
        )

    assert _sans_machine_noise(baseline["context"]) == _sans_machine_noise(result["context"])
    assert _sans_machine_noise(baseline["admission"]) == _sans_machine_noise(result["admission"])
    assert baseline["governed"] is True
    # the disclosure delta is exactly the archive report and its warning
    assert baseline["data_signals"]["metrics"] == signals["metrics"]
    assert [asset["reports"] for asset in baseline["data_signals"]["assets"]] == [[], []]
    assert baseline["data_signals"]["warnings"] == []

    page = served_context / "tables" / "archive-orders.md"
    before = page.read_bytes()
    again = asyncio.run(runtime.query_metrics(request))
    assert again["data_signals"] == signals  # a pure read of the same bytes
    assert (
        sorted(again["rows"], key=lambda row: row["region"])
        == sorted(result["rows"], key=lambda row: row["region"])
        and again["sql"] == result["sql"]
    )
    assert page.read_bytes() == before


def test_known_period_contradiction_is_inapplicable_never_a_matching_pass(tmp_path, monkeypatch):
    """Issue #54 checklist 4, spec 0013 §3/§4 (§7 AC3): the requested range is
    the runtime's OWN mechanical fact — a November request over a report whose
    declared [start, end) evidence period is September is a KNOWN
    contradiction: the report is disclosed ``inapplicable`` with the
    ``scope_mismatch`` limitation and the ``data_report_inapplicable`` warning
    — never as a matching pass, never as the requested data's failed check.
    An OVERLAPPING control keeps unknown applicability (overlap proves
    nothing), and its reported failed check still warns."""
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    db = _dated_db(tmp_path / "dated.db")
    resource = table_resource("demo", "demo", "main", "orders")

    def _dated_project(where: str, reports: list | None) -> AriadneRuntime:
        runtime, _ctx = _project(
            tmp_path / where,
            sources={"demo": db},
            quality_reports=reports,
            metric_sources=[_table_citation(resource)],
            model=DATED_MODEL_YML,
        )
        return runtime

    quality = _dated_project("quality", [PERIOD_REPORT])
    plain = _dated_project("plain", None)
    november = {"start": "2026-11-01", "end": "2026-11-30"}  # inclusive render range
    result = asyncio.run(quality.get_metric("order_count", ["region"], range=november))
    baseline = asyncio.run(plain.get_metric("order_count", ["region"], range=november))

    # the governed numbers are hand-derived from DATED_ORDERS and unchanged by
    # the supplied evidence (spec §5)
    assert _rows_by_region(result) == _rows_by_region(baseline) == {"NA": 50.0, "EMEA": 400.0}
    assert result["sql"] == baseline["sql"] and result["governed"] is True

    [asset] = result["data_signals"]["assets"]
    [report_view] = asset["reports"]
    assert report_view["age"] == "as_of"  # validity is unexpired
    assert report_view["applicability"] == "inapplicable"  # KNOWN contradiction
    assert report_view["limitations"] == ["scope_mismatch", "source_version_unknown"]
    [metric] = result["data_signals"]["metrics"]
    assert metric["coverage"] == "unknown"  # never a matching pass
    # disclosed as inapplicable ONLY — never as the requested data's failed
    # check, never as unknown applicability, never as expired
    assert _warning_codes(result) == {"data_report_inapplicable"}

    # the overlapping control (a [Sep 15, Nov 15] request over September's
    # evidence): no contradiction is established — unknown applicability, no
    # scope_mismatch — and the reported FAILED check still warns on its own
    overlap = {"start": "2026-09-15", "end": "2026-11-15"}
    control = asyncio.run(quality.get_metric("order_count", ["region"], range=overlap))
    control_baseline = asyncio.run(plain.get_metric("order_count", ["region"], range=overlap))
    assert _rows_by_region(control) == _rows_by_region(control_baseline) == {"NA": 150.0}
    [control_view] = control["data_signals"]["assets"][0]["reports"]
    assert control_view["applicability"] == "unknown"
    assert control_view["limitations"] == ["source_version_unknown"]  # no mismatch claim
    assert _warning_codes(control) == {"data_report_failed", "data_applicability_unknown"}

    # and a no-range request keeps Q1's exact behavior: unknown applicability
    unbounded = asyncio.run(quality.get_metric("order_count", ["region"]))
    [unbounded_view] = unbounded["data_signals"]["assets"][0]["reports"]
    assert unbounded_view["applicability"] == "unknown"
    assert unbounded_view["limitations"] == ["source_version_unknown"]


def test_read_across_expiry_boundary_changes_assessment_only(tmp_path, monkeypatch):
    """Issue #54 checklist 4 tail / spec §5+§7 AC9: a retry whose assessment
    instant crosses the supplied validity boundary changes ONLY the
    assessment (age as_of -> expired, one more warning, the new assessed_at) —
    never the page bytes, the producer stamps, the data or the governed
    rows/SQL."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": db},
        quality_reports=[BOUNDARY_REPORT],
        metric_sources=[_table_citation(resource)],
    )
    page = context_dir / _cited_page_rel(resource)
    db_bytes = db.read_bytes()
    page_bytes = page.read_bytes()

    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)  # 12:00
    before = asyncio.run(runtime.get_metric("order_count", ["region"]))  # valid_until 13:00
    assert _warning_codes(before) == {"data_report_failed", "data_applicability_unknown"}
    assert _report_views(before)[BOUNDARY_REPORT["id"]]["age"] == "as_of"

    later = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)  # crosses the boundary
    monkeypatch.setattr(context, "_assessment_now", lambda: later)
    after = asyncio.run(runtime.get_metric("order_count", ["region"]))

    # assessment-only delta: age flips, one warning added, instant moves
    assert _report_views(after)[BOUNDARY_REPORT["id"]]["age"] == "expired"
    assert _warning_codes(after) == {
        "data_report_failed",
        "data_applicability_unknown",
        "data_report_expired",
    }
    assert after["data_signals"]["assessed_at"] == later.isoformat()
    assert before["data_signals"]["assessed_at"] == ASSESS_NOW.isoformat()
    # nothing else moved: rows, SQL, metric/asset identity and coverage
    assert _rows_by_region(after) == _rows_by_region(before) == {"NA": 2, "EMEA": 1}
    assert after["sql"] == before["sql"]
    after["data_signals"]["assessed_at"] = before["data_signals"]["assessed_at"]
    assert after["data_signals"]["metrics"] == before["data_signals"]["metrics"]
    assert [a["resource"] for a in after["data_signals"]["assets"]] == [
        a["resource"] for a in before["data_signals"]["assets"]
    ]
    # and the read stayed pure: same pinned bytes, same data
    assert page.read_bytes() == page_bytes and db.read_bytes() == db_bytes


def test_absent_citation_reads_no_table_page_and_invents_no_warning(tmp_path, monkeypatch):
    """Issue #54 checklist 4/5, spec 0013 §4: a bound table page EXISTS and
    carries a report, but the consuming metric page records NO table citation
    — the dependency stays unknown coverage with the page unread (direct
    pages only, no scan, no probe) and NO warning invented for the absent
    citation."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": db},
        quality_reports=[EXPIRED_REPORT],  # the page COULD supply evidence…
        metric_sources=[],  # …but the consuming side cites nothing
    )
    reads: list[str] = []
    real_read = context._read_page_meta_bounded

    def counting_read(path):
        reads.append(str(path))
        return real_read(path)

    monkeypatch.setattr(context, "_read_page_meta_bounded", counting_read)
    result = _get_metric(runtime, monkeypatch)  # must not raise

    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric == {"name": "order_count", "assets": [resource], "coverage": "unknown"}
    [asset] = signals["assets"]
    assert asset["page"] is None and asset["coverage"] == "unknown" and asset["reports"] == []
    assert signals["warnings"] == []  # absent citation never warns by itself
    assert signals["truncated"] is False and signals["omitted"]["pages"] == 0
    # the no-probe/direct-pages-only evidence: only the METRIC page was read
    assert [path for path in reads if PurePath(path).parent.name == "tables"] == []


def test_reader_bounds_truncate_explicitly_never_silently_narrowing(tmp_path, monkeypatch):
    """Issue #54 checklist 4 (exceeded RESULT bounds; W1 failure mode d),
    plan 0013 §2: beyond the metric/asset/report bounds and the total byte
    ceiling, entries are elided deterministically, counted under ``omitted``
    and marked ``truncated``, and elided evidence never leaves a
    complete/warning-free quality claim. The bounds themselves are the
    approved public-contract values; the elision ACCOUNTING is exercised at
    small patched values so the fixture stays focused."""
    context_dir = tmp_path / "ctx"
    metrics_dir = context_dir / "metrics"
    tables_dir = context_dir / "tables"
    metrics_dir.mkdir(parents=True)
    tables_dir.mkdir(parents=True)
    resources = {name: table_resource("demo", "demo", "main", name) for name in ("ta", "tb", "tc")}
    for name, resource in resources.items():
        reports = [EXPIRED_REPORT, UNKNOWN_REPORT] if name in ("ta", "tb") else None
        (tables_dir / f"{name}.md").write_text(_table_page(resource, reports), encoding="utf-8")
        (metrics_dir / f"{name}.md").write_text(
            _metric_page([{"id": "table", "resource": f"tables/{name}.md", "title": "t"}]),
            encoding="utf-8",
        )
    dependencies: dict[str, list[str | None]] = {
        name: [resource] for name, resource in resources.items()
    }
    full = context.data_signals(context_dir, dependencies)  # unbounded control
    assert full["truncated"] is False and len(full["metrics"]) == 3

    # (a) the ASSET bound: ta+tb stay, tc is omitted — its metric keeps an
    # identified-but-omitted dependency (asset ref None, PARTIAL coverage,
    # the partial warning), never a silently narrowed complete claim
    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_ASSETS", 2)
    # (b) the REPORT bound: the fourth report (tb's second) is elided — tb's
    # coverage degrades to partial with the elision counted under omitted
    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_REPORTS", 3)
    view = context.data_signals(context_dir, dependencies)
    assert [entry["name"] for entry in view["metrics"]] == ["ta", "tb", "tc"]
    metrics = {entry["name"]: entry for entry in view["metrics"]}
    assert metrics["tc"]["assets"] == [None] and metrics["tc"]["coverage"] == "partial"
    assert metrics["tb"]["coverage"] == "partial"
    assert metrics["ta"]["coverage"] == "unknown"  # no applicability was established
    assets = {entry["resource"]: entry for entry in view["assets"]}
    assert set(assets) == {resources["ta"], resources["tb"]}
    assert len(assets[resources["tb"]]["reports"]) == 1  # the second was elided
    assert view["truncated"] is True  # a bound prevented disclosure — never False
    assert view["omitted"] == {"metrics": 0, "assets": 1, "pages": 0, "reports": 1}
    assert {warning["code"] for warning in view["warnings"]} >= {
        "data_coverage_partial",
        "data_signals_truncated",
    }
    monkeypatch.undo()

    # (c) the total byte ceiling: re-assessing under a budget one byte below
    # the full view's size must elide trailing reports until it fits — the
    # same explicit truncation contract, never a silent narrowing
    single: dict[str, list[str | None]] = {"ta": [resources["ta"]]}
    one = context.data_signals(context_dir, single)
    assert one["truncated"] is False and len(one["assets"][0]["reports"]) == 2
    size = len(json.dumps(one, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_BYTES", size - 1)
    squeezed = context.data_signals(context_dir, single)
    assert squeezed["truncated"] is True
    assert squeezed["omitted"]["reports"] >= 1
    assert len(squeezed["assets"][0]["reports"]) < 2  # trailing elision happened
    assert squeezed["metrics"][0]["coverage"] == "partial"
    assert {warning["code"] for warning in squeezed["warnings"]} >= {
        "data_coverage_partial",
        "data_signals_truncated",
    }


def test_cte_and_derived_aliases_resolve_to_physical_identity_only(tmp_path, monkeypatch):
    """Issue #54 checklist 2, spec 0013 §4: a SELECT dataset source is
    resolved with installed SQLGlot's scope-aware parsing — CTE and
    derived-table aliases are resolved THROUGH to the physical tables they
    read, never reported as dependencies themselves, and a same-named CTE
    never borrows a same-named physical table's identity. An unqualified bare
    name is not an exact catalog/schema/source identity: unknown coverage,
    never a guessed match."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    demo_resource = table_resource("demo", "demo", "main", "orders")

    # (a) a CTE source: the dependency is exactly demo's orders table — the
    # alias introduces NO unknown second dependency
    cte_runtime, _ctx = _project(
        tmp_path / "cte",
        sources={"demo": db},
        quality_reports=[EXPIRED_REPORT],
        metric_sources=[_table_citation(demo_resource)],
        model=CTE_MODEL_YML,
    )
    result = _get_metric(cte_runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # reads through the CTE
    [metric] = result["data_signals"]["metrics"]
    assert metric["assets"] == [demo_resource]  # exactly ONE identified asset
    [asset] = result["data_signals"]["assets"]
    assert asset["resource"] == demo_resource and asset["page"] is not None

    # (b) the same-named CTE over the OTHER source's same-named table: the
    # resolved identity is ARCHIVE's asset, never demo's same-named orders
    archive_db = _sqlite_db(tmp_path / "archive.db", [(1, "EMEA", 70.0)])
    archive_resource = table_resource("archive", "archive", "main", "orders")
    shadow_runtime, _ctx = _project(
        tmp_path / "shadow",
        sources={"demo": db, "archive": archive_db},
        quality_reports=[EXPIRED_REPORT],
        bound_resource=archive_resource,
        metric_sources=[_table_citation(archive_resource)],
        model=CTE_SHADOW_MODEL_YML,
    )
    shadow = _get_metric(shadow_runtime, monkeypatch)
    assert _rows_by_region(shadow) == {"EMEA": 70.0}  # archive's own rows
    [shadow_metric] = shadow["data_signals"]["metrics"]
    assert shadow_metric["assets"] == [archive_resource]
    assert demo_resource not in json.dumps(shadow["data_signals"])

    # (c) the unqualified legacy shorthand: a bare table name binds at EXECUTION
    # (USE demo.main) but is NOT an exact identity — unknown coverage, and no
    # resource is guessed into the view
    project = _project(
        tmp_path / "bare",
        sources={"demo": db},
        model=BARE_MODEL_YML,
    )
    bare_runtime = AriadneRuntime(
        project[1].parent / "semantic_layer",
        project[1],
        db,
        staging_dir=project[1].parent / "staging",
    )
    bare = _get_metric(bare_runtime, monkeypatch)
    assert _rows_by_region(bare) == {"NA": 2, "EMEA": 1}  # the legacy route still serves
    [bare_metric] = bare["data_signals"]["metrics"]
    assert bare_metric == {"name": "order_count", "assets": [None], "coverage": "unknown"}
    assert bare["data_signals"]["assets"] == []
    assert demo_resource not in json.dumps(bare["data_signals"])


# ---------------------------------------------- W1 fix pass 1 (issue #54):
# expectations derived from spec 0013 §3/§4 and plan 0013 §2 (the approved
# reader/output bounds), never from the implementation under test.

# Fix 1: a predicate-subquery read is a physical dependency. The archive
# table's ids filter the answer, so its asset — and only its asset — carries
# its report; the IN-subquery table is exactly the second dependency.
SUBQUERY_MODEL_YML = MODEL_YML.replace(
    "        source: demo.main.orders\n",
    "        source: SELECT order_id, region, amount FROM demo.main.orders"
    " WHERE order_id IN (SELECT order_id FROM archive.main.orders)\n",
)

# Fix 4: a past report time with a FUTURE observation time and unexpired
# validity — plan §2's unknown-age case.
FUTURE_OBSERVED_REPORT = {
    **EXPIRED_REPORT,
    "id": "future-observed",
    "reported_at": "2026-09-01T00:00:00+00:00",
    "observed_at": "2026-10-08T00:00:00+00:00",  # after ASSESS_NOW
    "valid_until": "2027-01-01T00:00:00+00:00",
}


def test_predicate_subquery_reads_are_physical_dependencies(tmp_path, monkeypatch):
    """W1 fix1, spec 0013 §4/§7 AC3–AC4: the dataset source's IN-subquery
    reads the ARCHIVE table's rows to shape the answer — that table is a
    physical dependency whose identified asset keeps its report. Dropping
    predicate-subquery tables (the scope walk of the first Q2 pass) silently
    lost exactly this evidence."""
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    demo_db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    archive_db = _sqlite_db(tmp_path / "archive.db", [(1, "EMEA", 7.0)])
    demo_resource = table_resource("demo", "demo", "main", "orders")
    archive_resource = table_resource("archive", "archive", "main", "orders")
    as_of_fail = {
        **EXPIRED_REPORT,
        "reported_at": "2026-10-01T00:00:00+00:00",
        "valid_until": "2027-01-01T00:00:00+00:00",
    }
    runtime, context_dir = _project(
        tmp_path / "proj",
        sources={"demo": demo_db, "archive": archive_db},
        quality_reports=[as_of_fail],
        bound_resource=archive_resource,
        metric_sources=[_table_citation(demo_resource), _table_citation(archive_resource)],
        model=SUBQUERY_MODEL_YML,
    )
    # the OUTER table's own unprofiled page, so both URI citations resolve
    # through the index and the assertion isolates the subquery dependency
    demo_page = context_dir / _cited_page_rel(demo_resource)
    demo_page.write_text(_table_page(demo_resource, None), encoding="utf-8")
    context._regenerate_indexes(context_dir)
    result = _get_metric(runtime, monkeypatch)
    # hand-derived: only demo order 1 appears in archive, so NA counts 1
    assert _rows_by_region(result) == {"NA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    # BOTH physical reads are identified — the outer table and the
    # predicate-subquery table, in source order, never a dropped dependency
    assert metric["assets"] == [demo_resource, archive_resource]
    assets = {entry["resource"]: entry for entry in signals["assets"]}
    assert set(assets) == {demo_resource, archive_resource}
    [report_view] = assets[archive_resource]["reports"]
    assert report_view["id"] == as_of_fail["id"]
    assert report_view["age"] == "as_of" and report_view["applicability"] == "unknown"
    # the subquery table's failed check and unknown applicability stay
    # disclosed — previously this evidence vanished with the dropped table
    assert _warning_codes(result) == {"data_report_failed", "data_applicability_unknown"}
    assert signals["truncated"] is False


def test_report_less_views_over_the_byte_ceiling_converge(tmp_path, monkeypatch):
    """W1 fix2, plan 0013 §2 (approved output bound): a view with NO reports
    anywhere that exceeds the total byte ceiling must converge — trailing
    entries elided deterministically, counted under ``omitted``, ``truncated``
    never false — instead of returning an over-ceiling view with a silent
    zero-omission flag. The ceiling here is the view's own natural size minus
    one byte: a bound that provably prevented disclosure, derived from the
    fixture, not from implementation output values."""
    context_dir = tmp_path / "ctx"
    metrics_dir = context_dir / "metrics"
    tables_dir = context_dir / "tables"
    metrics_dir.mkdir(parents=True)
    tables_dir.mkdir(parents=True)
    resources = {name: table_resource("demo", "demo", "main", name) for name in ("ta", "tb", "tc")}
    for name, resource in resources.items():
        (tables_dir / f"{name}.md").write_text(_table_page(resource, None), encoding="utf-8")
        (metrics_dir / f"{name}.md").write_text(
            _metric_page([{"id": "table", "resource": f"tables/{name}.md", "title": "t"}]),
            encoding="utf-8",
        )
    dependencies: dict[str, list[str | None]] = {
        name: [resource] for name, resource in resources.items()
    }
    full = context.data_signals(context_dir, dependencies)
    assert full["truncated"] is False and len(full["metrics"]) == 3
    natural = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_BYTES", natural - 1)
    view = context.data_signals(context_dir, dependencies)

    # the ceiling is honored and the view is a valid closed view — never an
    # oversized escape and never an invalid return
    assert len(json.dumps(view, ensure_ascii=False).encode("utf-8")) <= natural - 1
    assert set(view) == {
        "version",
        "assessed_at",
        "metrics",
        "assets",
        "warnings",
        "truncated",
        "omitted",
    }
    # report-less entries elide trailing METRIC entries first: the bound is
    # explicit and never silently narrows the disclosed coverage
    assert view["truncated"] is True
    assert view["omitted"]["metrics"] >= 1
    assert view["omitted"]["reports"] == 0
    assert len(view["metrics"]) < 3
    assert {warning["code"] for warning in view["warnings"]} >= {"data_signals_truncated"}


# --- the windowed consumed-range fixture (W1 fix3) ----------------------------

_WINDOWED_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: dated_orders
    description: Dated orders fact (W1 fix3 fixture)
    datasets:
      - name: dated_orders
        source: demo.main.dated_orders
        primary_key: [order_id]
        fields:
          - name: order_id
            expression: {dialects: [{dialect: ANSI_SQL, expression: order_id}]}
          - name: region
            expression: {dialects: [{dialect: ANSI_SQL, expression: region}]}
            dimension: {}
          - name: ordered_on
            expression: {dialects: [{dialect: ANSI_SQL, expression: ordered_on}]}
            dimension:
              is_time: true
          - name: amount
            expression: {dialects: [{dialect: ANSI_SQL, expression: amount}]}
    metrics:
      - name: orders_total
        dataset: dated_orders
        description: Sum of amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(amount)
      - name: orders_value_1m
        description: Value-window sum of orders_total, one grain period back
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: orders_total
        window:
          kind: value_window
          size: 1
          function: sum
"""

_WINDOWED_LINES_MODEL = """\
version: 0.2.0.dev0
semantic_model:
  - name: dated_lines
    description: Dated lines fact (the conformed time's second member)
    datasets:
      - name: dated_lines
        source: demo.main.dated_lines
        primary_key: [line_id]
        fields:
          - name: line_id
            expression: {dialects: [{dialect: ANSI_SQL, expression: line_id}]}
          - name: order_id
            expression: {dialects: [{dialect: ANSI_SQL, expression: order_id}]}
          - name: shipped_on
            expression: {dialects: [{dialect: ANSI_SQL, expression: shipped_on}]}
            dimension:
              is_time: true
          - name: line_amount
            expression: {dialects: [{dialect: ANSI_SQL, expression: line_amount}]}
    metrics:
      - name: lines_total
        dataset: dated_lines
        description: Sum of line amounts
        expression:
          dialects:
            - dialect: ANSI_SQL
              expression: SUM(line_amount)
"""

_WINDOWED_GRAPH_YML = """\
version: 1
relationships: []
conformed_dimensions:
  - name: business_date
    members:
      - dataset: dated_orders
        field: ordered_on
        native_grain: day
      - dataset: dated_lines
        field: shipped_on
        native_grain: day
"""

# (order_id, region, ordered_on, amount): monthly totals Oct=100, Nov=450 —
# the display range [Nov 1, Dec 1) with a one-month value window fetches
# [Oct 1, Dec 1) and the Nov group sums Oct+Nov = 550.
_WINDOWED_DATED_ROWS = [
    (1, "NA", "2026-10-05", 100.0),
    (2, "NA", "2026-11-03", 50.0),
    (3, "EMEA", "2026-11-20", 400.0),
]


def _period_report(report_id: str, start: str, end: str, field: str = "ordered_on") -> dict:
    """One asset-scoped failed-check report whose evidence period is the
    explicit [start, end) window on ``field`` (the W1 fix3 fixture axis)."""
    return {
        "id": report_id,
        "source_ids": ["owner-report"],
        "scope": {
            "kind": "asset",
            "description": f"Evidence period {start} to {end}.",
            "population": "every row of the physical dated orders table",
            "period": {"field": field, "start": start, "end": end},
        },
        "reported_at": "2026-09-25T00:00:00+00:00",
        "valid_until": "2027-01-01T00:00:00+00:00",
        "checks": [
            {
                "id": f"{report_id}-check",
                "kind": "completeness",
                "outcome": "fail",
                "criterion": "every order of the tested period is present",
                "tested_population": "all orders placed in the tested period",
                "tested_period": None,
            }
        ],
    }


def _admit_windowed_quality_project(tmp_path: Path, at: str) -> AriadneRuntime:
    """One admitted single-registry project whose fact carries a one-month
    value-windowed metric over the conformed ``business_date`` time, with the
    fact's table page supplying three period reports: October evidence
    (inside the window lookback extension), September evidence (disjoint from
    the consumed fetch range) and a same-period report declared on an
    unrelated field."""
    from ariadne import authoring
    from ariadne.promote import promote_bundle

    project = tmp_path / "proj"
    project.mkdir(parents=True)
    con = sqlite3.connect(project / "mf.db")
    try:
        con.executescript(
            "CREATE TABLE dated_orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
            " ordered_on DATE NOT NULL, amount REAL NOT NULL);"
            "CREATE TABLE dated_lines (line_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,"
            " shipped_on DATE NOT NULL, line_amount REAL NOT NULL)"
        )
        statement = "INSERT INTO dated_orders VALUES (?, ?, ?, ?)"
        con.executemany(statement, _WINDOWED_DATED_ROWS)  # pi-lens-ignore: python-sql-injection
        con.execute(
            "INSERT INTO dated_lines VALUES (?, ?, ?, ?)",  # pi-lens-ignore: python-sql-injection
            (1, 1, "2026-11-10", 25.0),
        )
        con.commit()
    finally:
        con.close()
    (project / "ariadne.yaml").write_text(
        "sources:\n  - name: demo\n    type: sqlite\n    path: mf.db\n", encoding="utf-8"
    )
    orders_resource = table_resource("demo", "demo", "main", "dated_orders")
    lines_resource = table_resource("demo", "demo", "main", "dated_lines")
    reports = [
        # inside the value window's one-month fetch extension, disjoint from
        # the DISPLAY range — materially consumed, never inapplicable
        _period_report(
            "lookback-october", "2026-10-01T00:00:00+00:00", "2026-11-01T00:00:00+00:00"
        ),
        # disjoint even from the consumed fetch range, on the conformed field
        _period_report(
            "disjoint-september", "2026-09-01T00:00:00+00:00", "2026-10-01T00:00:00+00:00"
        ),
        # same September period, declared on a field the range never predicates
        _period_report(
            "field-mismatch",
            "2026-09-01T00:00:00+00:00",
            "2026-10-01T00:00:00+00:00",
            field="some_other_field",
        ),
    ]
    bundle = {
        "files": [
            {"path": "data/seed_notes.md", "content": "# Seed notes\n\nDated facts.\n"},
            {"path": "semantic_layer/models/dated_orders.yml", "content": _WINDOWED_MODEL},
            {"path": "semantic_layer/models/dated_lines.yml", "content": _WINDOWED_LINES_MODEL},
            {"path": "semantic_layer/graph.yml", "content": _WINDOWED_GRAPH_YML},
            {"path": "context_layer/policies/region-rollup.md", "content": _MF_POLICY_PAGE},
            {
                "path": "context_layer/tables/dated-orders.md",
                "content": _table_page(orders_resource, reports),
            },
            {
                "path": "context_layer/tables/dated-lines.md",
                "content": _table_page(lines_resource, None),
            },
            {
                "path": "context_layer/metrics/orders_total.md",
                "content": _mf_metric_page("orders_total", [orders_resource]),
            },
            {
                "path": "context_layer/metrics/orders_value_1m.md",
                "content": _mf_metric_page("orders_value_1m", [orders_resource]),
            },
            {
                "path": "context_layer/metrics/lines_total.md",
                "content": _mf_metric_page("lines_total", [lines_resource]),
            },
        ]
    }
    submission = tmp_path / "submission.json"
    submission.write_text(json.dumps(bundle), encoding="utf-8")
    view = authoring.submit_bundle(submission, project=project)
    assert view["status"] == "validated", view["errors"]
    promote_bundle(
        view["review_digest"],
        staging_root=project / "staging",
        served_root=project / "served",
        by="human:test",
        assume_yes=True,
        at=at,
    )
    return AriadneRuntime(
        project / "served" / "semantic_layer",
        project / "served" / "context_layer",
        project / "mf.db",
        staging_dir=project / "staging",
        sources=project / "ariadne.yaml",
    )


def test_windowed_lookback_evidence_is_consumed_not_inapplicable(tmp_path, monkeypatch):
    """W1 fix3, spec 0013 §4 (§7 AC3): the request's mechanically CONSUMED
    range is the planner's fetch range — the value window's one-month lookback
    extension precedes the display trim. October evidence is display-disjoint
    but materially consumed: unknown applicability, its failed check still
    disclosed — never suppressed as inapplicable. September evidence is
    disjoint from the consumed range AND declared on the conformed time's own
    field: inapplicable. The same September period on an unrelated field
    proves no field correspondence: unknown, never an unproven inapplicable."""
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    runtime = _admit_windowed_quality_project(tmp_path / "windowed", at="2026-10-07T09:00:00+00:00")
    result = asyncio.run(
        runtime.query_metrics(
            {
                "metrics": ["orders_value_1m"],
                "time": {
                    "dimension": "business_date",
                    "grain": "month",
                    "start": "2026-11-01",
                    "end": "2026-12-01",
                },
            }
        )
    )
    assert result["governed"] is True and len(result["rows"]) == 1
    # hand-derived from _WINDOWED_DATED_ROWS: monthly Oct=100/Nov=450, the
    # RANGE frame one period back sums Oct+Nov = 550 for the November group
    [row] = result["rows"]
    assert row["orders_value_1m"] == 550.0 and str(row["business_date"]).startswith("2026-11")

    signals = result["data_signals"]
    [asset] = signals["assets"]
    reports = {view["id"]: view for view in asset["reports"]}
    assert set(reports) == {"lookback-october", "disjoint-september", "field-mismatch"}

    # THE regression: display-disjoint but FETCH-consumed October evidence is
    # unknown applicability with NO mismatch claim, and its failed check
    # stays disclosed — the first pass marked it inapplicable from the
    # display range and suppressed the failure warning
    lookback = reports["lookback-october"]
    assert lookback["applicability"] == "unknown"
    assert lookback["limitations"] == ["source_version_unknown"]
    assert lookback["age"] == "as_of"

    # consumed-range-disjoint evidence on the conformed time's own field:
    # the one mechanically provable contradiction — inapplicable
    disjoint = reports["disjoint-september"]
    assert disjoint["applicability"] == "inapplicable"
    assert disjoint["limitations"] == ["scope_mismatch", "source_version_unknown"]

    # the same period on a field the range never predicates: correspondence
    # unproven, so that axis stays unknown — never an unproven inapplicable
    mismatched = reports["field-mismatch"]
    assert mismatched["applicability"] == "unknown"
    assert mismatched["limitations"] == ["source_version_unknown"]

    # the warning set keeps every fact separate: the lookback failure still
    # warns, the inapplicable report discloses exactly its own code
    report_warnings = {(warning["code"], warning["report"]) for warning in signals["warnings"]}
    assert ("data_report_failed", "lookback-october") in report_warnings
    assert ("data_applicability_unknown", "lookback-october") in report_warnings
    assert ("data_report_inapplicable", "disjoint-september") in report_warnings
    assert not any(
        code == "data_report_inapplicable" and rid != "disjoint-september"
        for code, rid in report_warnings
    )
    assert signals["truncated"] is False
    assert [metric["coverage"] for metric in signals["metrics"]] == ["unknown"]


def test_future_observation_time_leaves_age_unknown(tmp_path, monkeypatch):
    """W1 fix4, plan 0013 §2: a report whose REPORT time is past but whose
    OBSERVATION time is later than the assessment instant has UNKNOWN age and
    the ``report_time_in_future`` limitation — never an as-of disclosure over
    an observation that has not happened yet. The unexpired supplied validity
    does not rescue an as-of age."""
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    resource = table_resource("demo", "demo", "main", "orders")
    runtime, _ctx = _project(
        tmp_path / "proj",
        sources={"demo": db},
        quality_reports=[FUTURE_OBSERVED_REPORT],
        metric_sources=[_table_citation(resource)],
    )
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # the query never degrades
    [view] = _report_views(result).values()
    assert view["age"] == "unknown"  # not as_of: the observation is in the future
    assert set(view["limitations"]) == {"source_version_unknown", "report_time_in_future"}
    # the reported FAILED check still warns; no expiry claim is invented
    assert _warning_codes(result) == {"data_report_failed", "data_applicability_unknown"}

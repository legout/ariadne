"""Advisory supplied source-quality evidence, quality-only slice (issue #53 /
spec 2026-10-06-0013 §§2–5, §7 AC1/AC2/AC3/AC5/AC6; plan §2).

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

All fixtures are explicitly synthetic; no real report was acquired, no source
probed, no external document read. The full ``context_signals``/``data_signals``
axis-separation assertions stay pending until accepted 0011 exists.
"""

import asyncio
import copy
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path, PurePath

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
) -> tuple[AriadneRuntime, Path]:
    """A legacy-route runtime over one registered sqlite source per entry, the
    orders model, an optional quality-profiled table page bound to
    ``bound_resource`` (default: the demo asset the model reads) and an
    optional consuming metric page whose ``sources[]`` carry the recorded
    DIRECT table citations (spec 0013 §4: only a citation recorded on the
    consuming side establishes a directly cited table page)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    registry_lines = ["sources:"]
    for name, db in sources.items():
        registry_lines += [f"  - name: {name}", "    type: sqlite", f"    path: {db}"]
    (project / "ariadne.yaml").write_text("\n".join(registry_lines) + "\n", encoding="utf-8")
    models = project / "semantic_layer" / "models"
    models.mkdir(parents=True)
    (models / "orders.yml").write_text(MODEL_YML, encoding="utf-8")
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

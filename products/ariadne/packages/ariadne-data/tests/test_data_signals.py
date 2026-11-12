"""Advisory supplied source-quality evidence over the PINNED native surface
(issues #53 + #54 / spec 2026-10-06-0013 §§2–5, §7; plan §2; C6 native
cutover, spec0035 §6 + the owner-approved spec0009 §9 quality amendment).

Every scenario runs the REAL public chain: an admitted native project
(authoring batch → validation → human confirmation → native admission) is
opened through ``QueryRuntime.open_project`` and the advisory view is the
pinned typed-SDK disclosure (``context.data_signals_pinned``) over the
admission's captured snapshot. Expectations are derived from the
specification and plan contract, never from the implementation under test:

- a governed metric keeps its rows/SQL/governance while an EXPIRED supplied
  report is disclosed with its reported outcome/age/limitations (AC1); a
  recent event-time watermark and a reported completeness failure stay
  SEPARATE facts, neither implying live health (AC2);
- exact identity: same-named tables in distinct source assets never share a
  report by name (AC3's quality-only slice); evidence is read only from the
  exactly bound DIRECTLY CITED table page — a consuming-side citation — and
  a supplied ``source_version`` alone never establishes correspondence
  (spec §3/§4);
- absent optional profiles and missing optionals stay explicit unknowns,
  and existing metric queries remain usable (AC5);
- malformed/unsupported declarations fail the producer structural gate
  inside the native page batch BEFORE any byte is written — never as a
  query refusal (AC6); a producer-accepted declaration Core cannot
  interpret discloses unknown evidence at query time;
- reads are pure: identical retries do not alter the page bytes (AC9).

Issue #54's multi-fact slice (spec §4, §7 AC3/AC4/AC7–AC9) runs as one real
admission: exact dependency identity for multi-fact work through the
executed plan/graph, known period contradiction disclosed as inapplicable,
expiry boundaries crossed by assessment only, absent citations unread,
explicit reader-bounds truncation, and scope-aware CTE/derived-alias
resolution.

The retired served-tree machinery (``_regenerate_indexes``/``_index_for``
resource-marker resolution, the 32-page physical read budget, the
non-managed ``AriadneRuntime`` seam and the synthetic graph admission) is
deleted with the C6 retirement: the pinned snapshot carries the visible
pages already, citations resolve scope-first against the captured view, and
the real bounds (metrics/assets/reports/bytes) are exercised directly. All
fixtures are explicitly synthetic; no real report was acquired, no source
probed, no external document read.
"""

import asyncio
import json
import re
import sqlite3
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import sqlglot  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

import pytest  # noqa: E402
from lumio_wiki.git_authoring import (  # noqa: E402
    GitAuthoringError,
)
from lumio_wiki.source_references import (  # noqa: E402
    SOURCE_REFERENCE_MANIFEST_BASENAME,
    SourceReferenceManifest,
    serialize_source_reference_manifest,
)

from ariadne import admission, context  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.query import QueryRuntime  # noqa: E402
from ariadne.sources import parse_resource, table_resource  # noqa: E402
from tests.test_git_authoring import approved, run_git, worktree_of  # noqa: E402

MONOREPO_ROOT = Path(__file__).resolve().parents[5]
# The accepted producer bytes of the governing Policy fixture (independently
# authored, unchanged input — the proven native Policy page of the baseline).
_POLICY_PAGE = (
    MONOREPO_ROOT
    / "integration"
    / "tests"
    / "fixtures"
    / "lumio_context_baseline"
    / "policies"
    / "retail-return-policy.md"
).read_text(encoding="utf-8")

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

# W1 fix4: a past report time with a FUTURE observation time and unexpired
# validity — plan §2's unknown-age case.
FUTURE_OBSERVED_REPORT = {
    **EXPIRED_REPORT,
    "id": "future-observed",
    "reported_at": "2026-09-01T00:00:00+00:00",
    "observed_at": "2026-10-08T00:00:00+00:00",  # after ASSESS_NOW
    "valid_until": "2027-01-01T00:00:00+00:00",
}

# The expiry-boundary fixture: validity ends BETWEEN two pinned assessment
# instants (ASSESS_NOW=12:00 < 13:00 < the later 14:00 read).
BOUNDARY_REPORT = {
    **EXPIRED_REPORT,
    "id": "orders-completeness-boundary",
    "reported_at": "2026-10-01T00:00:00+00:00",
    "valid_until": "2026-10-07T13:00:00+00:00",
}

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

# Fix 1: a predicate-subquery read is a physical dependency. The archive
# table's ids filter the answer, so its asset — and only its asset — carries
# its report; the IN-subquery table is exactly the second dependency.
SUBQUERY_MODEL_YML = MODEL_YML.replace(
    "        source: demo.main.orders\n",
    "        source: SELECT order_id, region, amount FROM demo.main.orders"
    " WHERE order_id IN (SELECT order_id FROM archive.main.orders)\n",
)

NAMESPACE = "urn:demo:quality"
POLICY_ENTITY = "entity:retail-return-policy"

# The KB source-reference manifest every fixture carries (the accepted
# producer scaffolding of the mvp content_project, authored for this
# module's namespace).
_MANIFEST_BYTES = serialize_source_reference_manifest(
    SourceReferenceManifest(version=1, namespace=NAMESPACE)
)

KB_CONTROL = """version: 2
mode: categorized
categories:
  - name: policies
  - name: references
  - name: metrics
  - name: datasets
  - name: tables
  - name: computations
ontology:
  entity_types:
    policy: {}
    computation: {}
    reference: {}
    metric: {}
    dataset: {}
    table: {}
"""


def _sqlite_db(path: Path, rows: list[tuple], *, ddl: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(
            ddl
            or "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
            " amount REAL NOT NULL)"
        )
        # static literal SQL with ?-bound parameters; rows are module constants
        statement = "INSERT INTO orders VALUES (" + ", ".join("?" * len(rows[0])) + ")"
        con.executemany(statement, rows)  # pi-lens-ignore: python-sql-injection
        con.commit()
    finally:
        con.close()
    return path


def _policy_binding(identity: str, *, operations=("get_metric", "query_metrics")) -> dict:
    """The §10.1 explanatory classification of one metric subject's complete
    closure (the accepted fixture convention: the governing narrative Policy,
    enforcement null — these fixtures run no graph audit)."""
    return {
        "subject": {"kind": "metric", "identity": identity},
        "policy": {"namespace": NAMESPACE, "entity_id": POLICY_ENTITY},
        "operations": list(operations),
        "enforcement": None,
    }


def _table_slug(resource: str) -> tuple[str, str, str, str]:
    """(source, catalog, schema, table) of one canonical table resource."""
    kind, parts = parse_resource(resource)
    assert kind == "table"
    source, catalog, schema, table = parts
    return source, catalog, schema, table


def _table_entity(resource: str) -> str:
    # entity ids are producer slugs: lowercase ASCII letters, digits and
    # hyphens only — the canonical resource stays the binding identity
    source, _catalog, _schema, table = _table_slug(resource)
    return f"entity:{(source + '-' + table).replace('_', '-')}"


def _table_title(resource: str) -> str:
    source, catalog, schema, table = _table_slug(resource)
    return f"{source}.{schema}.{table}"


def _table_page(resource: str, reports: list | None = None, *, name: str = "orders.md") -> str:
    """A producer-valid native Table page bound to the canonical resource,
    optionally carrying the supplied reports (each tied to the page's exact
    asset). The page's own ``owner-report`` citation is the source the
    quality reports' ``source_ids`` resolve against."""
    native: dict = {
        "type": "table",
        "title": _table_title(resource),
        "description": "One row per order.",
        "tags": ["table"],
        "resource": resource,
        "sources": [
            {
                "id": "owner-report",
                "resource": resource,
                "title": "owner-supplied source-quality report citation",
            }
        ],
    }
    if reports is not None:
        native["ariadne_quality"] = {
            "version": 1,
            "reports": [{**report, "asset": resource} for report in reports],
        }
    meta = {
        "id": _table_entity(resource),
        "title": _table_title(resource),
        "entity_types": ["table"],
        "tags": ["table"],
        "summary": "One row per order.",
        "lifecycle": "approved",
        "visibility": "public",
        "sources": [{"id": "src-table-catalog", "title": "Catalog and profile, 2026-01-01"}],
        "ariadne_profile": {
            "version": 1,
            "kind": "table",
            "core_ref": {"kind": "resource", "id": resource},
            "native": native,
        },
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n# {name[:-3].replace('-', ' ')}\n"


def _metric_page(
    name: str,
    model: str,
    metric: str,
    citations: list[str],
    *,
    primary_key: str = "order_id",
    extra_policy_bindings: list[dict] | None = None,
) -> str:
    """The consuming gate-clean native metric page: the mandatory governing
    Policy closure plus the DIRECT table citations — the recorded canonical
    resources that name the table pages allowed to supply evidence (spec
    0013 §4's "admitted table citations"; a table page citing its own source
    is a self-citation and establishes nothing)."""
    sources = [
        {
            "id": "governing-policy",
            "resource": "policies/retail-return-policy.md",
            "title": "Retail Return Policy",
        }
    ]
    for index, resource in enumerate(citations):
        sources.append(
            {
                "id": f"fact-table-{index}",
                "resource": resource,
                "title": "the physical fact table",
            }
        )
    meta = {
        # entity ids are producer slugs: lowercase ASCII letters, digits and
        # hyphens only — the underscored metric identity stays in metric_ref
        "id": f"entity:{name.replace('_', '-')}",
        "title": f"{name} (Metric)",
        "entity_types": ["metric"],
        "tags": ["metric"],
        "summary": f"The {name} metric.",
        "lifecycle": "approved",
        "visibility": "public",
        "sources": [
            {"id": "src-metric-review", "title": "Metric review, 2026-10-05"}
        ],
        "ariadne_profile": {
            "version": 1,
            "kind": "metric",
            "metric_ref": {"model": model, "metric": metric},
            "required_policies": [
                {"namespace": NAMESPACE, "entity_id": POLICY_ENTITY}
            ],
            "native": {
                "type": "metric",
                "status": "stable",
                "title": name,
                "description": f"The {name} metric.",
                "tags": ["metric"],
                "stale_after": date(2027, 6, 30),
                "sources": sources,
                "governed_by": "policies/retail-return-policy.md",
                "dimensions": ["region"],
                "grain": {
                    "primary_key": [primary_key],
                    "cardinality_enforcement": "strict_1_to_1",
                },
            },
        },
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n# {name}\n"


def _selector(bindings: list[dict]) -> str:
    """The revision-2 integrated selector carrying the authored §10.1
    binding inventory classifying the candidate's complete closures."""
    return yaml.safe_dump(
        {
            "version": 1,
            "mode": "integrated",
            "subtree": "knowledge",
            "namespace": NAMESPACE,
            "profile": "ariadne-context/1",
            "support_revision": 2,
            "policy_bindings": {"version": 1, "bindings": bindings},
        },
        sort_keys=False,
    )


def _write_files(project: Path, files: dict[str, str | bytes]) -> None:
    for rel, content in files.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")


def _admit_project(tmp_path: Path, files: dict[str, str | bytes], *, name: str = "proj"):
    """The REAL public chain over an explicit synthetic bundle: initial
    human commit → proposal → source approval → native validation (the
    finalize derivation commits the generated Computation) → review →
    composite confirmation → native admission → pinned runtime open."""
    from lumio_wiki.ariadne_context import (
        inspect_ariadne_candidate,
    )

    project = tmp_path / name
    _write_files(project, files)
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "-A", "--", ".")
    run_git(project, "commit", "-q", "-m", "human: synthetic joint orders and SDK inputs")
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    revision = started["candidate_revision"]
    # the candidate's KB must be genuinely producer-valid BEFORE validation:
    # a fixture bug is never a substitute for the gate under test
    inspection = inspect_ariadne_candidate(
        str(worktree_of(project, started["proposal"]) / "knowledge"),
        revision,
        namespace=NAMESPACE,
    )
    assert inspection.diagnostics == (), "fixture KB must be producer-valid"
    validated = api.validate_proposal(started["proposal"], revision)
    assert validated["ok"] is True, validated["errors"]
    review = api.review_proposal(started["proposal"])
    assert review["source_approved"] is True
    destination = tmp_path / f"{name}-published"
    composite = admission.overall_review(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        destination=destination,
        expected_current="none",
        scope=("public",),
    )
    admission.admit_revision(
        project,
        review["proposal"],
        review["revision"],
        review["review_digest"],
        confirmed_by="human:synthetic-operator",
        overall_preview=composite,
        confirmed_overall_digest=composite["digest"],
    )
    return QueryRuntime.open_project(project), project


def _simple_quality_project(
    tmp_path: Path,
    *,
    reports: list | None,
    cited: bool = True,
    citations: list[str] | None = None,
    model: str = MODEL_YML,
    name: str = "proj",
    sources: dict[str, Path] | None = None,
    extra_table_pages: dict[str, str] | None = None,
    with_demo_page: bool = True,
):
    """One admitted single-fact project: the orders model over the demo
    sqlite source, an optionally quality-profiled table page bound to the
    demo asset and a consuming metric page whose citations name the table
    pages allowed to supply evidence (default: the demo asset itself)."""
    db = _sqlite_db(tmp_path / f"{name}.db", ORDERS)
    sources = sources or {"demo": db}
    resource = table_resource("demo", "demo", "main", "orders")
    if citations is None:
        citations = [resource] if cited else []
    files: dict[str, str | bytes] = {
        "data/seed_notes.md": "# Seed notes\n\nAll events count.\n",
        "ariadne.yaml": "sources:\n"
        + "".join(
            f"  - name: {source_name}\n    type: sqlite\n    path: {db_path}\n"
            for source_name, db_path in sources.items()
        ),
        "semantic_layer/models/orders.yml": model,
        "context_integration.yaml": _selector([_policy_binding("orders::order_count")]),
        "knowledge/lumio.yaml": KB_CONTROL,
        f"knowledge/{SOURCE_REFERENCE_MANIFEST_BASENAME}": _MANIFEST_BYTES,
        "knowledge/policies/retail-return-policy.md": _POLICY_PAGE,
        "knowledge/metrics/order_count.md": _metric_page(
            "order_count", "orders", "order_count", citations
        ),
    }
    if with_demo_page:
        files["knowledge/tables/orders.md"] = _table_page(resource, reports)
    for rel, page in (extra_table_pages or {}).items():
        files[f"knowledge/tables/{rel}"] = page
    return _admit_project(tmp_path, files, name=name), resource


def _get_metric(runtime, monkeypatch) -> dict:
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    return asyncio.run(runtime.get_metric("order_count", ["region"]))


def _rows_by_region(result: dict) -> dict:
    return {row["region"]: row["order_count"] for row in result["rows"]}


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
    (plain_runtime, _plain_project), resource = _simple_quality_project(
        tmp_path, name="plain", sources={"demo": db}, reports=None
    )
    (runtime, project), _resource = _simple_quality_project(
        tmp_path, name="quality", sources={"demo": db}, reports=[EXPIRED_REPORT, UNKNOWN_REPORT]
    )
    baseline = _get_metric(plain_runtime, monkeypatch)
    result = _get_metric(runtime, monkeypatch)

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
    assert metric == {"name": "order_count", "assets": [resource], "coverage": "unknown"}
    # the identified, cited dependency keeps its attached as-of evidence, but
    # COVERAGE stays unknown: version correspondence cannot be mechanically
    # established — the runtime holds no dataset-version fact to cross-check
    # the supplied source_version against (an admission digest is not a
    # dataset version), so no supplied-only version is a matching assessment
    # (spec §§3–4; plan §2's "unknown when correspondence/evidence is
    # unavailable")
    [asset] = signals["assets"]
    assert asset["resource"] == resource
    assert asset["page"] == "knowledge/tables/orders.md"  # the authored KB identity
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
    # same immutable admission — never restamped, never rewritten
    again = _get_metric(runtime, monkeypatch)
    assert again["data_signals"] == result["data_signals"]
    assert _rows_by_region(again) == _rows_by_region(result) and again["sql"] == result["sql"]


def test_absent_profile_keeps_metric_usable_and_coverage_unknown(tmp_path, monkeypatch):
    """Spec §7 AC5: a project without the optional profile keeps its query
    behavior — the numerically valid query succeeds and discloses unknown
    coverage for the IDENTIFIED pinned page, with NO warning invented merely
    for the profile's absence."""
    (runtime, _project), resource = _simple_quality_project(
        tmp_path, reports=None
    )
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric["coverage"] == "unknown"
    [asset] = signals["assets"]
    assert asset["page"] == "knowledge/tables/orders.md"
    assert asset["coverage"] == "unknown" and asset["reports"] == []
    assert signals["warnings"] == []


# The former producer-accepted/Core-uninterpretable backwards-period
# disclosure scenario (a tested_period with start >= end admitted past the
# producer gate) is retired BY CONSTRUCTION: the producer structural gate
# restores the retained ``start < end`` authoring rule (spec0013 §2), and a
# pinned snapshot is immutable, so such a declaration can never reach the
# pinned disclosure. The refusal is asserted by the authoring matrix above
# and the disclosure honesty stays exercised with producer-valid inputs.


def test_same_named_tables_in_distinct_sources_never_share_a_report_by_name(
    tmp_path, monkeypatch
):
    """Spec §7 AC3 (quality-only slice): the executed query reads demo's
    orders; archive's same-named orders carries a valid report — the report
    stays on archive's exact canonical asset and never reaches the metric's
    evidence by table name. The uncited demo asset degrades to the honest
    ``binding_unknown`` disclosure while the query still succeeds."""
    demo_db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    archive_db = _sqlite_db(tmp_path / "archive.db", ORDERS)
    archive_resource = table_resource("archive", "archive", "main", "orders")
    (runtime, _project), demo_resource = _simple_quality_project(
        tmp_path,
        sources={"demo": demo_db, "archive": archive_db},
        reports=None,
        with_demo_page=False,  # no pinned page binds demo's asset
        extra_table_pages={
            "archive-orders.md": _table_page(archive_resource, [EXPIRED_REPORT])
        },
    )
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric["assets"] == [demo_resource]
    assert metric["coverage"] == "unknown"  # demo's asset has no report of its own
    [asset] = signals["assets"]
    assert asset["resource"] == demo_resource and asset["page"] is None
    assert asset["reports"] == []
    # the URI citation cannot resolve (no pinned page binds demo's resource —
    # the only table page declares archive's) and degrades to the
    # binding_unknown disclosure, never to a scan or a name-based guess
    assert _warning_codes(result) == {"data_binding_unknown"}
    # the archive report is nowhere in the metric's evidence
    assert archive_resource not in json.dumps(signals)


def test_known_period_contradiction_is_inapplicable_never_a_matching_pass(
    tmp_path, monkeypatch
):
    """Issue #54 checklist 4, spec 0013 §3/§4 (§7 AC3): the requested range is
    the runtime's OWN mechanical fact — a November request over a report whose
    declared [start, end) evidence period is September is a KNOWN
    contradiction: the report is disclosed ``inapplicable`` with the
    ``scope_mismatch`` limitation and the ``data_report_inapplicable`` warning
    — never as a matching pass, never as the requested data's failed check.
    An OVERLAPPING control keeps unknown applicability (overlap proves
    nothing), and its reported failed check still warns."""
    db = _sqlite_db(
        tmp_path / "dated.db",
        DATED_ORDERS,
        ddl=(
            "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
            " amount REAL NOT NULL, order_date DATE NOT NULL)"
        ),
    )
    (quality, _p1), resource = _simple_quality_project(
        tmp_path,
        name="quality",
        sources={"demo": db},
        model=DATED_MODEL_YML,
        reports=[PERIOD_REPORT],
    )
    (plain, _p2), _resource2 = _simple_quality_project(
        tmp_path, name="plain", sources={"demo": db}, model=DATED_MODEL_YML, reports=None
    )
    november = {"start": "2026-11-01", "end": "2026-11-30"}  # inclusive render range
    result = asyncio.run(quality.get_metric("order_count", ["region"], range=november))
    baseline = asyncio.run(plain.get_metric("order_count", ["region"], range=november))

    # the governed numbers are hand-derived from DATED_ORDERS and unchanged by
    # the supplied evidence (spec §5)
    assert _rows_by_region(result) == _rows_by_region(baseline) == {"NA": 50.0, "EMEA": 400.0}
    assert result["sql"] == baseline["sql"] and result["governed"] is True

    [asset] = result["data_signals"]["assets"]
    assert asset["page"] == "knowledge/tables/orders.md"
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

    # and a no-range request keeps the unbounded behavior: unknown applicability
    unbounded = asyncio.run(quality.get_metric("order_count", ["region"]))
    [unbounded_view] = unbounded["data_signals"]["assets"][0]["reports"]
    assert unbounded_view["applicability"] == "unknown"
    assert unbounded_view["limitations"] == ["source_version_unknown"]


def test_read_across_expiry_boundary_changes_assessment_only(tmp_path, monkeypatch):
    """Issue #54 checklist 4 tail / spec §5+§7 AC9: a retry whose assessment
    instant crosses the supplied validity boundary changes ONLY the
    assessment (age as_of -> expired, one more warning, the new assessed_at) —
    never the immutable admission bytes, the producer stamps, the data or the
    governed rows/SQL."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    (runtime, _project), _resource = _simple_quality_project(
        tmp_path, sources={"demo": db}, reports=[BOUNDARY_REPORT]
    )

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


def test_absent_citation_supplies_no_evidence_and_invents_no_warning(tmp_path, monkeypatch):
    """Issue #54 checklist 4/5, spec 0013 §4: a bound table page EXISTS and
    carries a report, but the consuming metric page records NO table citation
    — the dependency stays unknown coverage with nothing supplied (direct
    consuming-side citations only, no scan, no probe) and NO warning invented
    for the absent citation. An uncited same-resource page is never a
    supplier: only the CONSUMING side's citation establishes evidence."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    (runtime, _project), resource = _simple_quality_project(
        tmp_path,
        sources={"demo": db},
        reports=[EXPIRED_REPORT],  # the page COULD supply evidence…
        cited=False,  # …but the consuming side cites nothing
    )
    result = _get_metric(runtime, monkeypatch)  # must not raise

    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}
    signals = result["data_signals"]
    [metric] = signals["metrics"]
    assert metric == {"name": "order_count", "assets": [resource], "coverage": "unknown"}
    [asset] = signals["assets"]
    assert asset["page"] is None and asset["coverage"] == "unknown" and asset["reports"] == []
    assert signals["warnings"] == []  # absent citation never warns by itself
    assert signals["truncated"] is False and signals["omitted"]["pages"] == 0
    assert EXPIRED_REPORT["id"] not in json.dumps(signals)


def test_future_observation_time_leaves_age_unknown(tmp_path, monkeypatch):
    """W1 fix4, plan 0013 §2: a report whose REPORT time is past but whose
    OBSERVATION time is later than the assessment instant has UNKNOWN age and
    the ``report_time_in_future`` limitation — never an as-of disclosure over
    an observation that has not happened yet. The unexpired supplied validity
    does not rescue an as-of age."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    (runtime, _project), _resource = _simple_quality_project(
        tmp_path, sources={"demo": db}, reports=[FUTURE_OBSERVED_REPORT]
    )
    result = _get_metric(runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # the query never degrades
    [view] = _report_views(result).values()
    assert view["age"] == "unknown"  # not as_of: the observation is in the future
    assert set(view["limitations"]) == {"source_version_unknown", "report_time_in_future"}
    # the reported FAILED check still warns; no expiry claim is invented
    assert _warning_codes(result) == {"data_report_failed", "data_applicability_unknown"}


def test_cte_and_derived_aliases_resolve_to_physical_identity_only(tmp_path, monkeypatch):
    """Issue #54 checklist 2, spec 0013 §4: a SELECT dataset source is
    resolved with installed SQLGlot's scope-aware parsing — CTE and
    derived-table aliases are resolved THROUGH to the physical tables they
    read, never reported as dependencies themselves, and a same-named CTE
    never borrows a same-named physical table's identity."""
    db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    demo_resource = table_resource("demo", "demo", "main", "orders")

    # (a) a CTE source: the dependency is exactly demo's orders table — the
    # alias introduces NO unknown second dependency
    (cte_runtime, _p1), _resource = _simple_quality_project(
        tmp_path,
        name="cte",
        sources={"demo": db},
        model=CTE_MODEL_YML,
        reports=[EXPIRED_REPORT],
    )
    result = _get_metric(cte_runtime, monkeypatch)
    assert _rows_by_region(result) == {"NA": 2, "EMEA": 1}  # reads through the CTE
    [metric] = result["data_signals"]["metrics"]
    assert metric["assets"] == [demo_resource]  # exactly ONE identified asset
    [asset] = result["data_signals"]["assets"]
    assert asset["resource"] == demo_resource
    assert asset["page"] == "knowledge/tables/orders.md"

    # (b) the same-named CTE over the OTHER source's same-named table: the
    # resolved identity is ARCHIVE's asset, never demo's same-named orders
    archive_db = _sqlite_db(tmp_path / "archive.db", [(1, "EMEA", 70.0)])
    archive_resource = table_resource("archive", "archive", "main", "orders")
    (shadow_runtime, _p2), _r2 = _simple_quality_project(
        tmp_path,
        name="shadow",
        sources={"demo": db, "archive": archive_db},
        model=CTE_SHADOW_MODEL_YML,
        reports=[EXPIRED_REPORT],
        citations=[archive_resource],
        extra_table_pages={
            "archive-orders.md": _table_page(archive_resource, [EXPIRED_REPORT])
        },
    )
    shadow = _get_metric(shadow_runtime, monkeypatch)
    assert _rows_by_region(shadow) == {"EMEA": 70.0}  # archive's own rows
    [shadow_metric] = shadow["data_signals"]["metrics"]
    assert shadow_metric["assets"] == [archive_resource]
    assert demo_resource not in json.dumps(shadow["data_signals"])


def test_predicate_subquery_reads_are_physical_dependencies(tmp_path, monkeypatch):
    """W1 fix1, spec 0013 §4/§7 AC3–AC4: the dataset source's IN-subquery
    reads the ARCHIVE table's rows to shape the answer — that table is a
    physical dependency whose identified asset keeps its report. Dropping
    predicate-subquery tables (the scope walk of the first Q2 pass) silently
    lost exactly this evidence."""
    demo_db = _sqlite_db(tmp_path / "mf.db", ORDERS)
    archive_db = _sqlite_db(tmp_path / "archive.db", [(1, "EMEA", 7.0)])
    demo_resource = table_resource("demo", "demo", "main", "orders")
    archive_resource = table_resource("archive", "archive", "main", "orders")
    as_of_fail = {
        **EXPIRED_REPORT,
        "reported_at": "2026-10-01T00:00:00+00:00",
        "valid_until": "2027-01-01T00:00:00+00:00",
    }
    # demo's own page stays unprofiled; the quality-profiled page binds
    # ARCHIVE's asset (the subquery dependency), exactly the classic fixture's
    # identity split
    (runtime, _project), _resource = _simple_quality_project(
        tmp_path,
        name="subquery",
        sources={"demo": demo_db, "archive": archive_db},
        model=SUBQUERY_MODEL_YML,
        reports=None,
        citations=[demo_resource, archive_resource],
        extra_table_pages={
            "archive-orders.md": _table_page(archive_resource, [as_of_fail])
        },
    )
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
    assert assets[archive_resource]["page"] == "knowledge/tables/archive-orders.md"
    [report_view] = assets[archive_resource]["reports"]
    assert report_view["id"] == as_of_fail["id"]
    assert report_view["age"] == "as_of" and report_view["applicability"] == "unknown"
    # the subquery table's failed check and unknown applicability stay
    # disclosed — previously this evidence vanished with the dropped table
    assert _warning_codes(result) == {"data_report_failed", "data_applicability_unknown"}
    assert signals["truncated"] is False


# ---------------------------------------------- authoring validation (AC6)


def _batch_table_page_markdown(resource: str, reports: list | None, mutator=None) -> str:
    """The batch-page content of one quality-profiled native table page;
    ``mutator`` (called on the parsed frontmatter) builds each variant."""
    meta = yaml.safe_load(
        _table_page(resource, reports).split("---\n", 2)[1]
    )
    if mutator is not None:
        mutator(meta)
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n# Orders\n"


def _batch_project(tmp_path: Path, resource: str):
    """One real authoring project whose initial bundle carries the plain
    native table page; the batch matrix submits every variant against its
    proposal (the producer gate refuses before any byte, so the candidate
    never moves)."""
    project = tmp_path / "proj"
    _write_files(
        project,
        {
            "ariadne.yaml": "# registry template\n",
            "data/seed_notes.md": "# Seed notes\n\nAll events count.\n",
            "knowledge/lumio.yaml": KB_CONTROL,
            f"knowledge/{SOURCE_REFERENCE_MANIFEST_BASENAME}": _MANIFEST_BYTES,
            "knowledge/tables/orders.md": _table_page(resource, None),
        },
    )
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "-A", "--", ".")
    run_git(project, "commit", "-q", "-m", "human: initial artifacts")
    api = AuthoringProject(project)
    started = api.start_proposal()
    page = worktree_of(project, started["proposal"]) / "knowledge" / "tables" / "orders.md"
    return api, started, page


def test_valid_supplied_profile_passes_the_native_batch(tmp_path):
    """The clean control: the same harness accepts the producer-valid
    profile — the refusals below are the gate, never a broken fixture."""
    resource = table_resource("demo", "demo", "main", "orders")
    api, started, page = _batch_project(tmp_path, resource)
    edited = api.edit_pages_batch(
        started["proposal"],
        started["candidate_revision"],
        [
            {
                "path": "knowledge/tables/orders.md",
                "content": _batch_table_page_markdown(
                    resource, [EXPIRED_REPORT, UNKNOWN_REPORT]
                ),
            }
        ],
    )
    assert edited["changed"] is True
    added = yaml.safe_load(page.read_text(encoding="utf-8").split("---\n", 2)[1])
    assert added["ariadne_profile"]["native"]["ariadne_quality"]["reports"], (
        "the authored profile landed verbatim"
    )


def test_malformed_supplied_profiles_fail_the_native_batch_before_admission(tmp_path):
    """Spec §2/§7 AC6, native migration (spec0035 §6): unsupported versions,
    naive/plain-date timestamps, broken period/ordering invariants,
    executable payload keys, mismatched asset/citation identity, duplicate
    IDs, missing scope declarations, validity and count invariants fail the
    producer structural gate INSIDE the public native page batch — before any
    byte is written, never as a query refusal."""
    period_backwards = {"start": "2026-09-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"}

    def drop_tested_scope(meta: dict) -> None:
        check = meta["ariadne_profile"]["native"]["ariadne_quality"]["reports"][0]["checks"][0]
        for key in ("criterion", "tested_population", "tested_period"):
            check.pop(key)

    def nine_reports(meta: dict) -> None:
        lead = meta["ariadne_profile"]["native"]["ariadne_quality"]["reports"][0]
        meta["ariadne_profile"]["native"]["ariadne_quality"]["reports"] = [
            {**lead, "id": f"{lead['id']}-{index}"} for index in range(9)
        ]

    cases = {
        "unsupported-version": lambda m: m["ariadne_profile"]["native"][
            "ariadne_quality"
        ].__setitem__("version", 2),
        "naive-iso-timestamp": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("reported_at", "2026-09-01T00:00:00"),
        "naive-yaml-datetime": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("reported_at", datetime(2026, 9, 1)),
        "plain-date-value": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("reported_at", date(2026, 9, 1)),
        "executable-payload-key": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("sql", "SELECT 1"),
        "mismatched-asset": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("asset", table_resource("other", "other", "main", "orders")),
        "unresolved-citation": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("source_ids", ["no-such-citation"]),
        "duplicate-report-ids": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][1].__setitem__(
            "id", m["ariadne_profile"]["native"]["ariadne_quality"]["reports"][0]["id"]
        ),
        "period-start-not-before-end": lambda m: m["ariadne_profile"]["native"][
            "ariadne_quality"
        ]["reports"][0]["checks"][0].__setitem__(
            "tested_period", {**period_backwards, "field": "order_date"}
        ),
        "omitted-scope-period": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0]["scope"].pop(
            "period"
        ),  # plan §2: the field is required — null is the explicit
        # non-time-bounded declaration; omission is not one
        "validity-before-report": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("valid_until", "2026-08-01T00:00:00+00:00"),
        "empty-checks": lambda m: m["ariadne_profile"]["native"]["ariadne_quality"][
            "reports"
        ][0].__setitem__("checks", []),
        "check-without-tested-scope": drop_tested_scope,
        "page-without-resource-binding": lambda m: m["ariadne_profile"]["native"].pop(
            "resource"
        ),
        "null-profile": lambda m: m["ariadne_profile"]["native"].__setitem__(
            "ariadne_quality", None
        ),
        "report-count-bound": nine_reports,
    }
    resource = table_resource("demo", "demo", "main", "orders")
    api, started, page = _batch_project(tmp_path, resource)
    for name, mutator in cases.items():
        content = _batch_table_page_markdown(resource, [EXPIRED_REPORT, UNKNOWN_REPORT], mutator)
        if name == "page-without-resource-binding":
            # stripping the core-owned resource binding is the same forgery:
            # the native trust/generated-claim boundary refuses the edit
            with pytest.raises(ValueError, match="trust/generated claim"):
                api.edit_pages_batch(
                    started["proposal"],
                    started["candidate_revision"],
                    [{"path": "knowledge/tables/orders.md", "content": content}],
                )
        else:
            with pytest.raises(GitAuthoringError):
                api.edit_pages_batch(
                    started["proposal"],
                    started["candidate_revision"],
                    [{"path": "knowledge/tables/orders.md", "content": content}],
                )
        # every refusal left the candidate untouched: the batch is atomic
        current = yaml.safe_load(page.read_text(encoding="utf-8").split("---\n", 2)[1])
        assert current == yaml.safe_load(
            _table_page(resource, None).split("---\n", 2)[1]
        ), name


# ---------------------------------------------- issue #54 (spec 0013 §4/§7
# AC3/AC4/AC7/AC8/AC9; plan 0013 §2's multi-metric contract) — the admitted
# multi-fact fixture. Expectations derived from the specification/plan
# contract and independently declared identity tuples, never from the
# resolver under test.

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


def _admit_multifact_project(tmp_path: Path, *, quality: bool):
    """One real admitted project with two same-named orders facts (demo and
    archive), the regions lookup and the cross-fact derived metric. The
    archive fact optionally carries the AS_OF report; the §10.1 inventory
    classifies every fact metric's closure (the region-rollup narrative is
    explanatory; the zone traversal is attested by the REAL relationship
    audits through the two executable query_metrics bindings)."""
    project = tmp_path / "proj"
    demo_db = _sqlite_db(project / "mf.db", _MF_LIVE_DB_ROWS)
    archive_db = _sqlite_db(project / "archive.db", _MF_ARCHIVE_DB_ROWS)
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
    bindings = [
        _policy_binding("live_orders::live_orders_total"),
        _policy_binding("archive_orders::archive_orders_total"),
        _policy_binding("archive_orders::combined_orders_total"),
        _policy_binding("regions::region_count"),
    ]
    files = {
        "data/seed_notes.md": "# Seed notes\n\nTwo facts.\n",
        "ariadne.yaml": "sources:\n"
        f"  - name: demo\n    type: sqlite\n    path: {demo_db}\n"
        f"  - name: archive\n    type: sqlite\n    path: {archive_db}\n",
        "semantic_layer/models/live_orders.yml": _MF_FACT_MODEL.format(
            model="live_orders",
            dataset="live_orders",
            source="demo.main.orders",
            metric="live_orders_total",
            derived="",
        ),
        "semantic_layer/models/archive_orders.yml": _MF_FACT_MODEL.format(
            model="archive_orders",
            dataset="archive_orders",
            source="archive.main.orders",
            metric="archive_orders_total",
            derived=_MF_DERIVED_METRIC,
        ),
        "semantic_layer/models/regions.yml": _MF_REGIONS_MODEL,
        "semantic_layer/graph.yml": _MF_GRAPH_YML,
        "context_integration.yaml": _selector(bindings),
        "knowledge/lumio.yaml": KB_CONTROL,
        f"knowledge/{SOURCE_REFERENCE_MANIFEST_BASENAME}": _MANIFEST_BYTES,
        "knowledge/policies/retail-return-policy.md": _POLICY_PAGE,
        "knowledge/tables/live-orders.md": _table_page(demo_resource, None),
        "knowledge/tables/archive-orders.md": _table_page(
            archive_resource, [AS_OF_REPORT] if quality else None
        ),
        "knowledge/tables/regions.md": _table_page(regions_resource, None),
        "knowledge/metrics/live_orders_total.md": _metric_page(
            "live_orders_total", "live_orders", "live_orders_total", [demo_resource]
        ),
        "knowledge/metrics/archive_orders_total.md": _metric_page(
            "archive_orders_total", "archive_orders", "archive_orders_total", [archive_resource]
        ),
        "knowledge/metrics/combined_orders_total.md": _metric_page(
            "combined_orders_total",
            "archive_orders",  # the derived metric lives in archive_orders.yml
            "combined_orders_total",
            [demo_resource, archive_resource],
        ),
        "knowledge/metrics/region_count.md": _metric_page(
            "region_count",
            "regions",
            "region_count",
            [regions_resource],
            primary_key="region",
        ),
    }
    runtime, project = _admit_project(tmp_path, files)
    return runtime, project, demo_resource, archive_resource, regions_resource


def test_query_metrics_associates_each_metric_with_its_own_facts_exact_identity(
    tmp_path, monkeypatch
):
    """Issue #54 checklist 1/3, spec 0013 §7 AC3/AC4 (the distinct multi-fact
    partial-dependency failure): two independently declared source/catalog/
    schema/table tuples — demo and archive, each with its own same-named
    ``orders`` — are queried together. Expected identities come from the
    DECLARED tuples via the approved identity contract, never from the
    resolver under test: each metric is associated with exactly its own
    fact's asset (the archive report can never reach demo's asset by name),
    the cross-fact derived metric's closure spans exactly its two facts, and
    the metric without its own report keeps partial/unknown coverage with
    its evidence visible — never "all sources passed"."""
    monkeypatch.setattr(context, "_assessment_now", lambda: ASSESS_NOW)
    runtime, _project, demo_resource, archive_resource, regions_resource = (
        _admit_multifact_project(tmp_path / "quality", quality=True)
    )

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
    assert assets[demo_resource]["page"] == "knowledge/tables/live-orders.md"
    [report_view] = assets[archive_resource]["reports"]
    assert report_view["id"] == AS_OF_REPORT["id"]
    assert assets[archive_resource]["page"] == "knowledge/tables/archive-orders.md"
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
    plain, _plain_project, _r1, _r2, _r3 = _admit_multifact_project(
        tmp_path / "plain", quality=False
    )
    baseline = asyncio.run(plain.query_metrics(request))
    for key in ("metrics", "dimensions", "columns", "sql", "plan"):
        assert baseline[key] == result[key], key
    assert sorted(baseline["rows"], key=lambda row: row["region"]) == sorted(
        result["rows"], key=lambda row: row["region"]
    )

    def _sans_machine_noise(payload: object) -> str:
        # the twins were finalized/admitted by independent wall-clock calls;
        # per-run ISO second stamps and per-bytes digests are machine facts,
        # not disclosure — normalized out so every CONTENT field compares exactly
        text = json.dumps(payload, default=str, sort_keys=True)
        text = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", "<stamp>", text)
        text = re.sub(r"[0-9a-f]{64}", "<digest>", text)
        # the twins are independent REAL admissions: their 40-hex content
        # commits are machine facts of identical bytes, normalized like the
        # digests above (the synthetic-admission fixture had one constant)
        text = re.sub(r"[0-9a-f]{40}", "<digest>", text)
        # timestamp-named proposal ids are machine facts the same way
        text = re.sub(r"p-\d{14}-[0-9a-f]{6}", "<proposal>", text)
        return text.replace(f"{tmp_path / 'quality'}", "<project>").replace(
            f"{tmp_path / 'plain'}", "<project>"
        )

    assert _sans_machine_noise(baseline["context"]) == _sans_machine_noise(result["context"])
    assert _sans_machine_noise(baseline["admission"]) == _sans_machine_noise(result["admission"])
    assert baseline["governed"] is True
    # the disclosure delta is exactly the archive report and its warning
    assert baseline["data_signals"]["metrics"] == signals["metrics"]
    assert [asset["reports"] for asset in baseline["data_signals"]["assets"]] == [[], []]
    assert baseline["data_signals"]["warnings"] == []

    again = asyncio.run(runtime.query_metrics(request))
    assert again["data_signals"] == signals  # a pure read of the same bytes
    assert (
        sorted(again["rows"], key=lambda row: row["region"])
        == sorted(result["rows"], key=lambda row: row["region"])
        and again["sql"] == result["sql"]
    )


# ---------------------------------------------- reader/output bounds (plan
# 0013 §2): the approved public-contract bounds are patched to small values
# so the elision ACCOUNTING is exercised on the REAL pinned view (captured
# from a real admission), never silently narrowed.


def _bounds_project(tmp_path: Path, *, with_reports: bool):
    """One admitted project with three fact metrics over three tables; ta/tb
    optionally carry the two shared reports, tc stays report-less."""
    project = tmp_path / "proj"
    db = _sqlite_db(project / "mf.db", ORDERS, ddl=(
        "CREATE TABLE orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
        " amount REAL NOT NULL);"
        "CREATE TABLE ta (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
        " amount REAL NOT NULL);"
        "CREATE TABLE tb (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
        " amount REAL NOT NULL);"
        "CREATE TABLE tc (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
        " amount REAL NOT NULL)"
    ))
    resources = {name: table_resource("demo", "demo", "main", name) for name in ("ta", "tb", "tc")}
    files: dict[str, str | bytes] = {
        "data/seed_notes.md": "# Seed notes\n\nBounds.\n",
        "ariadne.yaml": f"sources:\n  - name: demo\n    type: sqlite\n    path: {db}\n",
        "context_integration.yaml": _selector(
            [_policy_binding(f"{name}::{name}_count") for name in ("ta", "tb", "tc")]
        ),
        "knowledge/lumio.yaml": KB_CONTROL,
        f"knowledge/{SOURCE_REFERENCE_MANIFEST_BASENAME}": _MANIFEST_BYTES,
        "knowledge/policies/retail-return-policy.md": _POLICY_PAGE,
    }
    for name, resource in resources.items():
        model = MODEL_YML.replace("source: demo.main.orders", f"source: demo.main.{name}")
        model = model.replace("name: orders\n", f"name: {name}\n")
        model = model.replace("order_count", f"{name}_count")
        files[f"semantic_layer/models/{name}.yml"] = model
        reports = [EXPIRED_REPORT, UNKNOWN_REPORT] if with_reports and name != "tc" else None
        files[f"knowledge/tables/{name}.md"] = _table_page(resource, reports)
        files[f"knowledge/metrics/{name}_count.md"] = _metric_page(
            f"{name}_count", name, f"{name}_count", [resource]
        )
    runtime, _project = _admit_project(tmp_path, files)
    snapshot = runtime._context_snapshot
    dependencies: dict[str, list[str | None]] = {
        f"{name}_count": [resource] for name, resource in resources.items()
    }
    return snapshot, dependencies, resources


def test_reader_bounds_truncate_explicitly_never_silently_narrowing(tmp_path, monkeypatch):
    """Issue #54 checklist 4 (exceeded RESULT bounds; W1 failure mode d),
    plan 0013 §2: beyond the metric/asset/report bounds and the total byte
    ceiling, entries are elided deterministically, counted under ``omitted``
    and marked ``truncated``, and elided evidence never leaves a
    complete/warning-free quality claim. The bounds themselves are the
    approved public-contract values; the elision ACCOUNTING is exercised at
    small patched values over the REAL pinned view so the fixture stays
    focused."""
    snapshot, dependencies, resources = _bounds_project(tmp_path, with_reports=True)
    full = context.data_signals_pinned(snapshot, dependencies)  # unbounded control
    assert full["truncated"] is False and len(full["metrics"]) == 3

    # (a) the ASSET bound: ta+tb stay, tc is omitted — its metric keeps an
    # identified-but-omitted dependency (asset ref None, PARTIAL coverage,
    # the partial warning), never a silently narrowed complete claim
    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_ASSETS", 2)
    # (b) the REPORT bound: the fourth report (tb's second) is elided — tb's
    # coverage degrades to partial with the elision counted under omitted
    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_REPORTS", 3)
    view = context.data_signals_pinned(snapshot, dependencies)
    assert [entry["name"] for entry in view["metrics"]] == ["ta_count", "tb_count", "tc_count"]
    metrics = {entry["name"]: entry for entry in view["metrics"]}
    assert metrics["tc_count"]["assets"] == [None] and metrics["tc_count"]["coverage"] == "partial"
    assert metrics["tb_count"]["coverage"] == "partial"
    assert metrics["ta_count"]["coverage"] == "unknown"  # no applicability was established
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
    single: dict[str, list[str | None]] = {"ta_count": [resources["ta"]]}
    one = context.data_signals_pinned(snapshot, single)
    assert one["truncated"] is False and len(one["assets"][0]["reports"]) == 2
    size = len(json.dumps(one, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_BYTES", size - 1)
    squeezed = context.data_signals_pinned(snapshot, single)
    assert squeezed["truncated"] is True
    assert squeezed["omitted"]["reports"] >= 1
    assert len(squeezed["assets"][0]["reports"]) < 2  # trailing elision happened
    assert squeezed["metrics"][0]["coverage"] == "partial"
    assert {warning["code"] for warning in squeezed["warnings"]} >= {
        "data_coverage_partial",
        "data_signals_truncated",
    }


def test_report_less_views_over_the_byte_ceiling_converge(tmp_path, monkeypatch):
    """W1 fix2, plan 0013 §2 (approved output bound): a view with NO reports
    anywhere that exceeds the total byte ceiling must converge — trailing
    entries elided deterministically, counted under ``omitted``, ``truncated``
    never false — instead of returning an over-ceiling view with a silent
    zero-omission flag. The ceiling here is the view's own natural size minus
    one byte: a bound that provably prevented disclosure, derived from the
    fixture, not from implementation output values."""
    snapshot, dependencies, _resources = _bounds_project(tmp_path, with_reports=False)
    full = context.data_signals_pinned(snapshot, dependencies)
    assert full["truncated"] is False and len(full["metrics"]) == 3
    natural = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))

    monkeypatch.setattr(context, "DATA_SIGNALS_MAX_BYTES", natural - 1)
    view = context.data_signals_pinned(snapshot, dependencies)

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


def _admit_windowed_quality_project(tmp_path: Path):
    """One real admitted project whose fact carries a one-month value-windowed
    metric over the conformed ``business_date`` time, with the fact's table
    page supplying three period reports: October evidence (inside the window
    lookback extension), September evidence (disjoint from the consumed fetch
    range) and a same-period report declared on an unrelated field."""
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
    bindings = [
        _policy_binding("dated_orders::orders_total"),
        _policy_binding("dated_orders::orders_value_1m"),
        _policy_binding("dated_lines::lines_total"),
    ]
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(project / "mf.db")
    try:
        # static literal DDL over test-local column constants
        # pi-lens-ignore: python-sql-injection
        con.executescript(
            "CREATE TABLE dated_orders (order_id INTEGER PRIMARY KEY, region TEXT NOT NULL,"
            " ordered_on DATE NOT NULL, amount REAL NOT NULL);"
            "CREATE TABLE dated_lines (line_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,"
            " shipped_on DATE NOT NULL, line_amount REAL NOT NULL)"
        )
        con.executemany(  # pi-lens-ignore: python-sql-injection
            "INSERT INTO dated_orders VALUES (?, ?, ?, ?)",
            _WINDOWED_DATED_ROWS,
        )
        con.execute(  # pi-lens-ignore: python-sql-injection
            "INSERT INTO dated_lines VALUES (?, ?, ?, ?)",
            (1, 1, "2026-11-10", 25.0),
        )
        con.commit()
    finally:
        con.close()
    files = {
        "data/seed_notes.md": "# Seed notes\n\nDated facts.\n",
        "ariadne.yaml": (
            f"sources:\n  - name: demo\n    type: sqlite\n    path: {project / 'mf.db'}\n"
        ),
        "semantic_layer/models/dated_orders.yml": _WINDOWED_MODEL,
        "semantic_layer/models/dated_lines.yml": _WINDOWED_LINES_MODEL,
        "semantic_layer/graph.yml": _WINDOWED_GRAPH_YML,
        "context_integration.yaml": _selector(bindings),
        "knowledge/lumio.yaml": KB_CONTROL,
        f"knowledge/{SOURCE_REFERENCE_MANIFEST_BASENAME}": _MANIFEST_BYTES,
        "knowledge/policies/retail-return-policy.md": _POLICY_PAGE,
        "knowledge/tables/dated-orders.md": _table_page(orders_resource, reports),
        "knowledge/tables/dated-lines.md": _table_page(lines_resource, None),
        "knowledge/metrics/orders_total.md": _metric_page(
            "orders_total", "dated_orders", "orders_total", [orders_resource]
        ),
        "knowledge/metrics/orders_value_1m.md": _metric_page(
            "orders_value_1m", "dated_orders", "orders_value_1m", [orders_resource]
        ),
        "knowledge/metrics/lines_total.md": _metric_page(
            "lines_total",
            "dated_lines",
            "lines_total",
            [lines_resource],
            primary_key="line_id",
        ),
    }
    runtime, _project = _admit_project(tmp_path, files)
    return runtime


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
    runtime = _admit_windowed_quality_project(tmp_path / "windowed")
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

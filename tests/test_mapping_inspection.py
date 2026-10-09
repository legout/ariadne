"""Context knowledge K3: bounded identifier-mapping inspection with authentic
receipts (issue #43 / spec 2026-10-02-0010 §§7–8, §10 AC5/6/AC8/AC9-inspection;
plan §2 "Inspection candidate and finite limits"; ADR-0017).

``AuthoringProject.inspect_mapping`` is the ONE typed authoring operation: a
discriminated JSON candidate (never an executable string) from exactly the
three approved families — equality/composite, string prefix with an optional
scoped prefix lookup, and explicit scoped lookup — measured against the
operator-APPROVED resolved source identity through guarded core-generated
read-only statements, under operator-owned finite ceilings (sample rows,
execution deadline, response bytes, participating assets, bindings, scope
predicates, in-list sizes; raw examples need explicit operator sample
permission). The receipt — eligible/tested denominators, actual scope,
null/missing/unknown-lookup counts, coverage, mismatches, collisions,
multiplicity, containment-versus-pairing basis, sampled/full designation,
complete|inconclusive outcome with limitations — is retained atomically in the
core-controlled ``.ariadne/`` evidence area, and Git validation verifies
receipt existence/integrity and declaration/schema/source/lookup dependency
identity: a model-authored id or count proves nothing.

Real temporary Git repositories, real local parquet sources, no network, no
hosted service; the deadline is exercised through a deterministic patched
clock, never a wall-clock race.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages
import yaml  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # keep tests runnable from the source tree
    sys.path.insert(0, str(REPO_ROOT))

from ariadne import execution  # noqa: E402
from ariadne.authoring import AuthoringProject  # noqa: E402
from ariadne.sources import table_resource  # noqa: E402
from tests.test_git_authoring import approved  # noqa: E402 — the operator's G3 step

SEED_NOTES = "# Seed notes\n\nOrder numbers are store-scoped.\n"

# One store-scoped order identity (the owner's illustrative example, spec
# §5): ABC and XYZ both carry local number 123123 as TWO identities; the
# leading zero of 00123 is retained; QQQ is unknown to the prefix map.
ORDERS_ROWS = [
    # store_id, local_order_number, global_order_number, region, currency, currency_symbol
    ("ABC", "123123", "ABC123123", "EU", "EUR", "EUR-SYM"),
    ("XYZ", "123123", "XYZ123123", "EU", "EUR", "EUR-SYM"),
    ("ABC", "00123", "ABC00123", "EU", "USD", "USD-SYM"),
    ("QQQ", "999999", None, "EU", "JPY", "JPY-SYM"),
    (None, "777777", None, "EU", "GBP", "GBP-SYM"),
    ("ABC", "555555", "ABC555555", "US", "EUR", "EUR-SYM"),
]
PREFIX_MAP_ROWS = [  # duplicate 'ABC' key carrying the SAME value (disclosed multiplicity)
    ("ABC", "ABC"),
    ("XYZ", "XYZ"),
    ("ABC", "ABC"),
]
ERP_ROWS = [  # order 1's number differs from orders: an independently paired mismatch
    (1, "ABC", "123124"),
    (2, "XYZ", "123123"),
]
CURRENCY_MAP_ROWS = [  # 'USD' maps to TWO distinct values (ambiguity), 'EUR' duplicates one
    ("EUR", "EUR-SYM"),
    ("EUR", "EUR-SYM"),
    ("USD", "USD-SYM"),
    ("USD", "US-DOLLAR"),
    ("GBP", None),  # a NULL mapped value: counted null evidence, never skipped silently
]

ORDERS_RESOURCE = "ariadne-placeholder"  # set by resource() below per fixture


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch):
    """Never touch the operator's global/system Git config (the established
    Git-suite fixture): repo-local identity only."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def run_git(cwd: Path, *argv: str) -> str:
    proc = subprocess.run(["git", *argv], cwd=cwd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"git {argv} failed: {proc.stderr}"
    return proc.stdout


def write_parquet(path: Path, rows: list[tuple], columns: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ", ".join(
        "("
        + ", ".join(
            "NULL" if value is None else f"'{value}'" if isinstance(value, str) else str(value)
            for value in row
        )
        + ")"
        for row in rows
    )
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) "
        f"t({', '.join(columns)})) TO '{path}' (FORMAT PARQUET)"
    ).close()
    return path


def mapping_project(tmp_path: Path, *, sample_permission: bool = False) -> Path:
    """A real temporary Git data project over four local parquet sources,
    committed as the human-created initial artifact revision. The HOST
    ``ariadne.yaml`` may carry the operator's explicit raw-example sample
    permission (never a candidate artifact)."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    write_parquet(
        project / "data" / "orders" / "orders.parquet",
        ORDERS_ROWS,
        [
            "store_id",
            "local_order_number",
            "global_order_number",
            "region",
            "currency",
            "currency_symbol",
        ],
    )
    write_parquet(
        project / "data" / "storemeta" / "prefix_map.parquet",
        PREFIX_MAP_ROWS,
        ["store_id", "prefix"],
    )
    write_parquet(
        project / "data" / "erp" / "erp_orders.parquet",
        ERP_ROWS,
        ["order_id", "store_id", "order_number"],
    )
    write_parquet(
        project / "data" / "refdata" / "currency_map.parquet",
        CURRENCY_MAP_ROWS,
        ["from_ccy", "symbol"],
    )
    registry: dict = {
        "sources": [
            {"name": "orders", "type": "parquet", "path": "data/orders/orders.parquet"},
            {"name": "storemeta", "type": "parquet", "path": "data/storemeta/prefix_map.parquet"},
            {"name": "erp", "type": "parquet", "path": "data/erp/erp_orders.parquet"},
            {"name": "refdata", "type": "parquet", "path": "data/refdata/currency_map.parquet"},
        ]
    }
    if sample_permission:
        registry["inspection"] = {"raw_examples": True}
    (project / "ariadne.yaml").write_text(
        yaml.safe_dump(registry, sort_keys=False), encoding="utf-8"
    )
    (project / "data").mkdir(exist_ok=True)
    (project / "data" / "seed_notes.md").write_text(SEED_NOTES, encoding="utf-8")
    run_git(project, "init", "-q")
    run_git(project, "config", "user.name", "Ariadne Tests")
    run_git(project, "config", "user.email", "tests@ariadne.local")
    run_git(project, "add", "--", "ariadne.yaml", "data/seed_notes.md")
    run_git(project, "commit", "-q", "-m human: initial artifacts")
    return project


def resource(source: str, table: str, schema: str | None = None) -> str:
    return table_resource(source, None, schema or source, table)


def approved_project(tmp_path: Path, *, sample_permission: bool = False):
    """The started+approved proposal triple (project, api, started)."""
    project = mapping_project(tmp_path, sample_permission=sample_permission)
    api = AuthoringProject(project)
    started = api.start_proposal()
    approved(api, project, started)
    return project, api, started


def prefix_candidate() -> dict:
    """The scoped prefix candidate of the first red seam: components
    (store_id, local_order_number) with an explicit prefix lookup, an empty
    literal separator and the global-order-number target, scoped to the EU
    region."""
    storemeta = resource("storemeta", "prefix_map")
    return {
        "family": "prefix",
        "left": [
            {"resource": resource("orders", "orders"), "column": "store_id"},
            {"resource": resource("orders", "orders"), "column": "local_order_number"},
        ],
        "right": [{"resource": resource("orders", "orders"), "column": "global_order_number"}],
        "separator": "",
        "prefix_lookup": {
            "asset": storemeta,
            "key_fields": [{"resource": storemeta, "column": "store_id"}],
            "prefix_field": {"resource": storemeta, "column": "prefix"},
        },
        "scope": [
            {
                "resource": resource("orders", "orders"),
                "column": "region",
                "op": "eq",
                "value": "EU",
            }
        ],
    }


# ---------------------------------------------------------- [1] the red seam


def test_scoped_prefix_inspection_records_limited_coverage_without_exposing_identifiers(
    tmp_path,
):
    """Issue #43 [1], the red seam: through AuthoringProject.inspect_mapping,
    the approved ABC/XYZ fixtures that both carry local number 123123 are
    measured as TWO distinct prefix identities; the leading zero of 00123 is
    retained by construction (never a numeric cast); the unknown QQQ prefix
    lookup and the duplicate lookup key are disclosed as counts; the lowered
    sample bound records limited coverage with explicit denominators — and
    WITHOUT the operator's sample permission the receipt exposes NO raw
    identifier values at all."""
    project, api, started = approved_project(tmp_path)

    result = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        prefix_candidate(),
        limits={"sample_rows": 3},
    )

    assert result["proposal"] == started["proposal"]
    assert result["revision"] == started["candidate_revision"]
    receipt = result["receipt"]
    assert receipt["family"] == "prefix"
    assert receipt["sample_rows"] == 3
    assert receipt["designation"] == "sampled"  # 3 of 4 eligible left rows tested
    assert receipt["comparison_basis"] == "containment-only"
    assert receipt["outcome"] == "complete"  # completion OF THE STATED SAMPLE
    assert any("sample" in note for note in receipt["limitations"])
    # the EU scope narrowed the measured rows (the US row is out of scope)
    assert receipt["scope"][0]["value"] == "EU"
    counts = receipt["counts"]
    assert counts["eligible_left"] == 4  # ABC123123, XYZ123123, ABC00123, QQQ999999
    assert counts["eligible_right"] == 3  # the three non-null EU globals
    assert counts["tested_left"] == 3
    # the right side reuses the SAME single orders sample (one bounded sample
    # per participating asset): the QQQ row it carries has a NULL target, so
    # only two complete right tuples were tested
    assert counts["tested_right"] == 2
    assert counts["unavailable"] == []
    assert receipt["null_counts"] == {"left": 1, "right": 2}
    # TWO distinct identities for the repeated 123123 — counted, never exposed
    assert receipt["coverage"]["left_in_right"] == {"matched": 2, "tested": 3}
    assert receipt["coverage"]["right_in_left"] == {"matched": 2, "tested": 2}
    assert receipt["distinct_matched"] == 2
    assert receipt["mismatch_count"] == 0
    assert receipt["unknown_lookup_count"] == 1  # QQQ is absent from the prefix map
    assert receipt["ambiguous_key_count"] == 0  # the duplicate 'ABC' carries one value
    assert receipt["multiplicity"] == {
        "lookup_duplicate_keys": 1,
        "lookup_max_rows_per_key": 2,
    }
    assert receipt["collisions"]["left"] == {"values": 0, "max_multiplicity": 1}
    assert receipt["collisions"]["right"] == {"values": 0, "max_multiplicity": 1}

    # NO raw identifier examples without the operator's explicit sample
    # permission — not in the receipt, not anywhere in the response
    assert "examples" not in receipt
    serialized = json.dumps(result)
    for identifier in ("123123", "00123", "ABC", "XYZ", "QQQ", "999999"):
        assert identifier not in serialized, identifier

    # the receipt is retained atomically in the core-controlled evidence area
    evidence = Path(result["evidence"])
    assert evidence == project / ".ariadne" / "evidence" / started["proposal"] / (
        receipt["receipt_id"] + ".json"
    )
    stored = json.loads(evidence.read_text(encoding="utf-8"))
    assert stored["receipt_id"] == receipt["receipt_id"]
    assert stored["integrity_digest"] == receipt["integrity_digest"]
    assert len(receipt["integrity_digest"]) == 64
    assert receipt["receipt_id"].startswith("mr-")
    # the receipt binds the measured declaration and the approved identity
    assert len(receipt["candidate_digest"]) == 64
    assert receipt["candidate"]["family"] == "prefix"
    assert len(receipt["source_digest"]) == 64
    assert receipt["inspection_revision"] == started["candidate_revision"]
    assets = {asset["resource"] for asset in receipt["dependencies"]["assets"]}
    assert assets == {
        resource("orders", "orders"),
        resource("storemeta", "prefix_map"),
    }
    # unversioned local files are observed AS OF the measurement, never fresh
    assert receipt["version_signal"]["state"] == "as_of"
    assert receipt["observed_at"] == receipt["version_signal"]["observed_at"]


# ------------------------------------- [2]/[6]: the three families at the seam


def equality_candidate(*, pairing: list | None = None) -> dict:
    """Composite equality between the orders tuple and the ERP copy (the ERP
    row of order 1 carries a different number: an independently paired
    mismatch), optionally with record-key pairing."""
    orders, erp = resource("orders", "orders"), resource("erp", "erp_orders")
    candidate = {
        "family": "equality",
        "left": [
            {"resource": orders, "column": "store_id"},
            {"resource": orders, "column": "local_order_number"},
        ],
        "right": [
            {"resource": erp, "column": "store_id"},
            {"resource": erp, "column": "order_number"},
        ],
        "scope": [
            {"resource": orders, "column": "region", "op": "eq", "value": "EU"},
            {"resource": erp, "column": "order_id", "op": "lt", "value": 100},
        ],
    }
    if pairing is not None:
        candidate["pairing"] = pairing
    return candidate


def lookup_candidate() -> dict:
    """The explicit currency lookup: orders.currency -> the mapped symbol,
    compared against the fact side's own currency_symbol column."""
    orders, refdata = resource("orders", "orders"), resource("refdata", "currency_map")
    return {
        "family": "lookup",
        "left": [{"resource": orders, "column": "currency"}],
        "right": [{"resource": orders, "column": "currency_symbol"}],
        "lookup": {
            "asset": refdata,
            "key_fields": [{"resource": refdata, "column": "from_ccy"}],
            "value_fields": [{"resource": refdata, "column": "symbol"}],
        },
        "scope": [{"resource": orders, "column": "region", "op": "in", "value": ["EU", "US"]}],
    }


@pytest.mark.parametrize(
    "candidate, expected",
    [
        (
            "bare-numbers",
            {
                "basis": "containment-only",
                "tested_left": 6,
                "matched_left": 2,
                "collisions_left": {"values": 1, "max_multiplicity": 2},
                "mismatch": 4,
            },
        ),
        (
            "composite-pairing",
            {
                "basis": "independently-paired",
                "tested_left": 4,
                "paired": 2,
                "mismatch": 1,
            },
        ),
        (
            "lookup",
            {
                "basis": "key-paired",
                "tested_left": 6,
                "matched": 3,
                "missing": 2,
                "ambiguous": 1,
                "mismatch": 0,
                "duplicates": 2,
                "max_rows": 2,
            },
        ),
    ],
    ids=["bare-numbers", "composite-pairing", "lookup"],
)
def test_the_three_families_report_honest_shape_evidence(tmp_path, candidate, expected):
    """Issue #43 [2]/[6]: the parameterized public-seam regression — equality
    of the BARE numbers records the collision/multiplicity evidence that a
    plain-number join would fan out (never equivalence); composite equality
    with independently supplied pairing keys reports paired rows AND the one
    real mismatch; the lookup family reports missing keys, duplicate keys and
    a many-valued ambiguity without ever collapsing rows."""
    project, api, started = approved_project(tmp_path)
    orders = resource("orders", "orders")
    erp = resource("erp", "erp_orders")
    if candidate == "bare-numbers":
        request = {
            "family": "equality",
            "left": [{"resource": orders, "column": "local_order_number"}],
            "right": [{"resource": erp, "column": "order_number"}],
        }
    elif candidate == "composite-pairing":
        request = equality_candidate(
            pairing=[
                {
                    "left": {"resource": orders, "column": "local_order_number"},
                    "right": {"resource": erp, "column": "order_number"},
                }
            ]
        )
    else:
        request = lookup_candidate()
    result = api.inspect_mapping(started["proposal"], started["candidate_revision"], request)
    receipt = result["receipt"]
    assert receipt["family"] == request["family"]
    assert receipt["comparison_basis"] == expected["basis"]
    counts = receipt["counts"]
    assert counts["tested_left"] == expected["tested_left"]
    assert receipt["coverage"]["left_in_right"]["matched"] == expected.get(
        "matched_left", receipt["coverage"]["left_in_right"]["matched"]
    )
    if "collisions_left" in expected:
        assert receipt["collisions"]["left"] == expected["collisions_left"]
    if "paired" in expected:
        assert receipt["pairing"]["paired"] == expected["paired"]
        assert receipt["pairing"]["status"] == "usable"
    assert receipt["mismatch_count"] == expected["mismatch"]
    if "missing" in expected:
        assert receipt["missing_key_count"] == expected["missing"]
        assert receipt["ambiguous_key_count"] == expected["ambiguous"]
        assert receipt["multiplicity"] == {
            "lookup_duplicate_keys": expected["duplicates"],
            "lookup_max_rows_per_key": expected["max_rows"],
        }
    assert receipt["outcome"] == "complete"


def test_equality_refuses_lossy_type_coercion_and_prefix_requires_strings(tmp_path):
    """Issue #43 [2]: a string identifier beside a numeric column is NEVER
    silently compared (no string equivalence from a numeric cast), and a
    prefix candidate's components must be string-typed — distinct refusals,
    nothing measured."""
    project, api, started = approved_project(tmp_path)
    orders = resource("orders", "orders")
    erp = resource("erp", "erp_orders")
    with pytest.raises(ValueError, match="incompatible types.*no lossy coercion"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                "family": "equality",
                "left": [{"resource": orders, "column": "local_order_number"}],
                "right": [{"resource": erp, "column": "order_id"}],
            },
        )
    with pytest.raises(ValueError, match="must be VARCHAR"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                "family": "prefix",
                "left": [
                    {"resource": resource("erp", "erp_orders"), "column": "order_id"},
                    {"resource": resource("erp", "erp_orders"), "column": "order_number"},
                ],
                "right": [{"resource": orders, "column": "global_order_number"}],
                "separator": "-",
            },
        )
    # nothing was measured: no receipt exists for either refusal
    evidence_dir = project / ".ariadne" / "evidence" / started["proposal"]
    assert not evidence_dir.exists() or not any(evidence_dir.iterdir())


def test_stale_revision_and_unapproved_or_unknown_participation_refuse(tmp_path):
    """Issue #43 [6]: the distinct authority refusals — a stale expected
    revision, an UNAPPROVED source registry (nothing opens), and a candidate
    naming a source that is not an approved registry identity at all."""
    project, api, started = approved_project(tmp_path)
    candidate = prefix_candidate()
    with pytest.raises(ValueError, match="stale revision"):
        api.inspect_mapping(started["proposal"], "0" * 40, candidate)
    # no approval: the committed registry resolves to an identity with NO
    # operator permission — nothing opens, nothing is measured
    project2 = mapping_project(tmp_path / "unapproved")
    api2 = AuthoringProject(project2)
    started2 = api2.start_proposal()
    with pytest.raises(ValueError, match="NO operator approval"):
        api2.inspect_mapping(started2["proposal"], started2["candidate_revision"], candidate)
    # a participating source outside the approved registry identity
    decoy = table_resource("decoy", None, "decoy", "orders")
    with pytest.raises(ValueError, match="not an approved registry identity"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                "family": "equality",
                "left": [{"resource": resource("orders", "orders"), "column": "store_id"}],
                "right": [{"resource": decoy, "column": "store_id"}],
            },
        )
    # an approved source, but an asset it does not hold
    missing = table_resource("orders", None, "orders", "no_such_table")
    with pytest.raises(ValueError, match="not present in the approved resolved"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                "family": "equality",
                "left": [{"resource": resource("orders", "orders"), "column": "store_id"}],
                "right": [{"resource": missing, "column": "store_id"}],
            },
        )


# ------------------------------------------- [3]: the operator ceilings table


def test_requests_may_only_lower_the_operator_ceilings(tmp_path):
    """Issue #43 [3]: a request may LOWER the finite ceilings, never raise
    them — sample rows, execution seconds and response bytes each refuse a
    raising request by naming the ceiling, and the raw-example cap of ten is
    enforced even with permission."""
    project, api, started = approved_project(tmp_path / "perm", sample_permission=True)
    candidate = prefix_candidate()
    ok = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        candidate,
        limits={"sample_rows": 2},
    )
    assert ok["receipt"]["sample_rows"] == 2  # lowering is fine
    for key, ceiling in (
        ("sample_rows", 1000),
        ("execution_seconds", 20.0),
        ("response_bytes", 64 * 1024),
    ):
        with pytest.raises(ValueError, match=f"RAISE the operator ceiling {ceiling}"):
            api.inspect_mapping(
                started["proposal"],
                started["candidate_revision"],
                candidate,
                limits={key: ceiling + 1},
            )
    with pytest.raises(ValueError, match="raw-example cap of 10"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            candidate,
            limits={"examples": 11},
        )
    # a lowered response ceiling refuses an envelope that cannot fit it
    with pytest.raises(ValueError, match="over the 512-byte ceiling"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            candidate,
            limits={"response_bytes": 512},
        )


def test_raw_examples_need_explicit_operator_sample_permission(tmp_path):
    """Issue #43 [3]: raw identifier examples are absent by default —
    requesting them without the operator's explicit permission is a refusal;
    WITH permission the examples are bounded by the requested cap and carry
    the constructed value, the components and the target (the retained 00123
    leading zero visible as the string it is)."""
    project, api, started = approved_project(tmp_path)  # no sample permission
    with pytest.raises(ValueError, match="EXPLICIT sample permission"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            prefix_candidate(),
            limits={"examples": 2},
        )
    granted, api2, started2 = approved_project(tmp_path / "granted", sample_permission=True)
    result = api2.inspect_mapping(
        started2["proposal"],
        started2["candidate_revision"],
        prefix_candidate(),
        limits={"examples": 2, "sample_rows": 2},
    )
    examples = result["receipt"]["examples"]
    assert len(examples) == 2
    constructed = [example["constructed"] for example in examples]
    assert "ABC00123" in constructed  # the leading zero retained, never cast
    assert all("components" in example and "target" in example for example in examples)


def test_structural_ceilings_of_one_candidate_refuse_up_front():
    """Issue #43 [3]: the structural ceilings — sixteen candidate field
    bindings, eight scope predicates, one hundred in-list values — refuse
    before anything is measured (the shared candidate schema, the same one a
    Reference declaration validates through)."""
    from ariadne.context import validate_inspection_candidate

    assets = [table_resource(f"s{i}", None, f"s{i}", "t") for i in range(5)]
    binding = [{"resource": assets[0], "column": "c"}]
    wide_left = [{"resource": assets[0], "column": f"c{i}"} for i in range(9)]
    with pytest.raises(ValueError, match="at most 16 candidate field bindings"):
        validate_inspection_candidate(
            {"family": "equality", "left": wide_left, "right": list(wide_left)}
        )
    with pytest.raises(ValueError, match="at most 8 are measurable"):
        validate_inspection_candidate(
            {
                "family": "equality",
                "left": binding,
                "right": binding,
                "scope": [
                    {"resource": assets[0], "column": "c", "op": "eq", "value": i} for i in range(9)
                ],
            }
        )
    with pytest.raises(ValueError, match="at most 100 typed scalar values"):
        validate_inspection_candidate(
            {
                "family": "equality",
                "left": binding,
                "right": binding,
                "scope": [
                    {
                        "resource": assets[0],
                        "column": "c",
                        "op": "in",
                        "value": list(range(101)),
                    }
                ],
            }
        )


def test_deadline_exhaustion_refuses_deterministically_without_a_receipt(tmp_path, monkeypatch):
    """Issue #43 [3]/[6]: deadline exhaustion is a DISTINCT refusal — every
    statement was interrupted, no receipt is retained, nothing is claimed
    complete. The timeout is controlled deterministically through the deadline
    clock seam (never a wall-clock race or a hosted service)."""
    import time as _time

    project, api, started = approved_project(tmp_path)
    real = _time.monotonic
    ticks = {"n": 0}

    def jumped_clock():  # every read advances 10,000s: the budget is spent at once
        ticks["n"] += 1
        return real() + 10_000 * ticks["n"]

    monkeypatch.setattr(execution, "_deadline_clock", jumped_clock)
    with pytest.raises(ValueError, match="deadline"):
        api.inspect_mapping(started["proposal"], started["candidate_revision"], prefix_candidate())
    evidence_dir = project / ".ariadne" / "evidence" / started["proposal"]
    assert not evidence_dir.exists() or not any(evidence_dir.iterdir())


# ------------------------------------------- [4]: guarded statements only


def test_core_generated_statements_are_guarded_read_only_and_parameterized():
    """Issue #43 [4]: the measurement statements are core-generated and
    inspectable — single SELECT statements over EXACTLY the bound columns
    (no all-column scan), quoted identifiers, scope values and the row bound
    as parameters, deterministic ordering and an explicit LIMIT."""
    from ariadne.authoring import (
        inspection_count_statement,
        inspection_sample_statement,
    )

    table = {
        "name": 'ord"ers',
        "ref": "orders",
        "resource": "ariadne://table/x",
    }
    scope = [
        {
            "resource": "ariadne://table/x",
            "column": "region",
            "op": "in",
            "value": ["EU", "US"],
        },
        {
            "resource": "ariadne://table/x",
            "column": "store_id",
            "op": "gte",
            "value": "A",
        },
    ]
    sql, params = inspection_sample_statement(table, ["store_id", "order_n"], scope, 50)
    assert sql == (
        'SELECT "store_id", "order_n" FROM orders."ord""ers" '
        'WHERE "region" IN (?, ?) AND "store_id" >= ? '
        'ORDER BY "store_id", "order_n" LIMIT ?'
    )
    assert params == ["EU", "US", "A", 50]
    execution.assert_single_statement(sql)  # one statement, nothing smuggled
    count_sql, count_params = inspection_count_statement(table, ["store_id"], scope[:1])
    assert count_sql.startswith("SELECT COUNT(*) FILTER")
    assert count_params == ["EU", "US"]
    execution.assert_single_statement(count_sql)


# ---------------------------------- [5]: authentic receipts through Git validation


def reference_page(
    candidate: dict,
    receipt_ids: list[str],
    *,
    separator_note: str = "",
    sources: list | None = None,
) -> str:
    """A structured Identifier Mapping Reference citing measured receipts.
    The endpoint representations declare the candidate's own measured columns
    and required scope (the correspondence evidence verification enforces)."""
    orders = resource("orders", "orders")
    page_sources = sources or [{"id": "seed-notes", "resource": "data/seed_notes.md"}]
    meta = {
        "type": "reference",
        "title": "Order number",
        "description": "The store-scoped and global order-number identities.",
        "tags": ["reference"],
        "sources": page_sources,
        "ariadne": {
            "version": 1,
            "reference_role": "identifier",
            "representations": [
                {
                    "id": "local-order-number",
                    "aliases": ["local order number"],
                    "fields": [
                        {"resource": orders, "column": "store_id"},
                        {"resource": orders, "column": "local_order_number"},
                    ],
                    "scope": [{"resource": orders, "column": "region"}],
                },
                {
                    "id": "global-order-number",
                    "aliases": ["global order number"],
                    "fields": [{"resource": orders, "column": "global_order_number"}],
                    "scope": [],
                },
            ],
            "mappings": [
                {
                    "id": "local-to-global-prefix",
                    "family": "prefix",
                    "from": "local-order-number",
                    "to": "global-order-number",
                    "claim": "hypothesis",
                    "source_ids": [source["id"] for source in page_sources],
                    "candidate": candidate,
                    "receipt_ids": receipt_ids,
                }
            ],
        },
    }
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = (
        "# Order number\n\n"
        "The local identity is store-scoped; the global identity concatenates\n"
        f"the store prefix with the local number{separator_note}. The mapping is an\n"
        "unconfirmed hypothesis carried by the measured receipt.\n"
    )
    return f"---\n{front}\n---\n\n{body}\n"


REFERENCE_EDIT = {"kind": "page", "section": "references", "name": "order-number"}


def measured_hypothesis(tmp_path: Path):
    """The shared journey: approved project, one measured prefix candidate and
    its retained receipt, and the Reference page citing that receipt."""
    project, api, started = approved_project(tmp_path)
    candidate = prefix_candidate()
    measured = api.inspect_mapping(started["proposal"], started["candidate_revision"], candidate)
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {
            **REFERENCE_EDIT,
            "content": reference_page(candidate, [measured["receipt_id"]]),
        },
    )
    return project, api, started, candidate, measured, edited


def _evidence_block(page_text: str) -> dict | None:
    return _frontmatter(page_text).get("ariadne_evidence")


def _frontmatter(text: str) -> dict:
    return yaml.safe_load(text.split("---", 2)[1])


def test_validation_attaches_verified_summaries_and_receipts_survive_saves(tmp_path):
    """Issue #43 [5]: Git validation resolves the cited receipt in the
    project's evidence records, verifies its integrity digest and its
    declaration/source/schema dependency identities, and attaches the bounded
    verified summary to the Reference page as core-owned frontmatter; the
    receipt's validity SURVIVES the revision created by saving unrelated
    content (dependency matching, not blanket candidate-commit equality)."""
    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)

    validated = api.validate_proposal(started["proposal"], edited["revision"])
    outcomes = {check["name"]: check["outcome"] for check in validated["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "passed"
    assert outcomes["page_contract"] == "passed"
    # K4 (issue #44): no semantic models exist — the candidate is context-only,
    # its semantic checks are explicitly not_applicable, and the mapping
    # evidence is the applicable gate that passed
    assert validated["ok"] is True and validated["errors"] == []
    assert outcomes["structural"] == "not_applicable"

    page = api.read_artifact(started["proposal"], REFERENCE_EDIT)
    block = _evidence_block(page["content"])
    assert block is not None
    assert set(block) == {"local-to-global-prefix"}
    [summary] = block["local-to-global-prefix"]
    receipt = measured["receipt"]
    assert summary["id"] == receipt["receipt_id"]
    assert summary["digest"] == receipt["integrity_digest"]
    assert summary["family"] == "prefix"
    assert summary["outcome"] == "complete"
    assert summary["designation"] == "full"  # the default bound covered every eligible row
    assert summary["comparison_basis"] == "containment-only"
    assert summary["tested_left"] == receipt["counts"]["tested_left"]
    # the summary is bounded and credential-free: no raw identifier examples
    assert "examples" not in summary
    assert "123123" not in json.dumps(summary)

    # an UNRELATED save commit does not invalidate the measurement: the
    # hypothesis stays evidence-backed through the new revision
    notes = api.read_artifact(started["proposal"], {"kind": "seed_notes"})
    saved = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {"kind": "seed_notes", "content": notes["content"] + "\nLater note.\n"},
    )
    again = api.validate_proposal(started["proposal"], saved["revision"])
    outcomes = {check["name"]: check["outcome"] for check in again["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "passed"
    page = api.read_artifact(started["proposal"], REFERENCE_EDIT)
    assert _evidence_block(page["content"]) == block  # unchanged, still verified


def test_changed_declaration_invalidates_the_receipt_and_drops_the_summary(tmp_path):
    """Issue #43 [5]: a CHANGED mapping declaration (different normalized
    candidate) no longer matches the receipt's declaration digest — the
    mapping-evidence check fails naming the dependency, and the stale
    attached summary is removed from the page (never silently inherited)."""
    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert validated["revision"] != edited["revision"]  # the evidence attached

    changed = {**candidate, "separator": "-"}  # a different normalized candidate
    page = api.read_artifact(started["proposal"], REFERENCE_EDIT)
    meta = _frontmatter(page["content"])
    meta["ariadne"]["mappings"][0]["candidate"] = changed
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = page["content"].split("---", 2)[2]
    revised = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {**REFERENCE_EDIT, "content": f"---\n{front}\n---{body}"},
    )
    failed = api.validate_proposal(started["proposal"], revised["revision"])
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any("measures a different declaration" in error for error in failed["errors"])
    page = api.read_artifact(started["proposal"], REFERENCE_EDIT)
    assert _evidence_block(page["content"]) is None  # the stale summary is gone


def test_changed_measured_input_invalidates_the_receipt(tmp_path):
    """Issue #43 [5]/AC8: a changed measured INPUT — the source file's schema
    changing underneath the unchanged registry identity — invalidates the
    dependent receipt: the schema dependency identity no longer matches."""
    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    # rewrite the parquet with the target column now numeric: the registry
    # identity (path/type) is unchanged, the measured columns are not
    rows = [
        (
            store,
            local,
            1 if global_id is None else int(global_id[3:]) if global_id else 0,
            region,
            currency,
            symbol,
        )
        for store, local, global_id, region, currency, symbol in ORDERS_ROWS
    ]
    write_parquet(
        project / "data" / "orders" / "orders.parquet",
        rows,
        [
            "store_id",
            "local_order_number",
            "global_order_number",
            "region",
            "currency",
            "currency_symbol",
        ],
    )
    # a fresh validation round (an unrelated save) re-verifies the receipt
    # against the CURRENT dependency identities
    notes = api.read_artifact(started["proposal"], {"kind": "seed_notes"})
    saved = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {"kind": "seed_notes", "content": notes["content"] + "\nSchema changed.\n"},
    )
    failed = api.validate_proposal(started["proposal"], saved["revision"])
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any("measured columns changed" in error for error in failed["errors"])


def test_allowlisted_ids_and_authored_counts_are_never_proof(tmp_path):
    """Issue #43 [5]: allowlisting an evidence ID proves nothing — a
    well-formed id with no retained receipt behind it fails validation; a
    tampered stored receipt fails its integrity digest; and an authored
    ``ariadne_evidence`` block is refused at the edit seam as a system-owned
    claim."""
    project, api, started = approved_project(tmp_path)
    candidate = prefix_candidate()
    forged = "mr-" + "0" * 16
    edited = api.edit_proposal(
        started["proposal"],
        started["candidate_revision"],
        {**REFERENCE_EDIT, "content": reference_page(candidate, [forged])},
    )
    failed = api.validate_proposal(started["proposal"], edited["revision"])
    assert any(
        "does not resolve in the project's evidence records" in error for error in failed["errors"]
    )

    # a real measurement whose STORED record is then tampered with
    project2, api2, started2, candidate2, measured2, edited2 = measured_hypothesis(
        tmp_path / "tampered"
    )
    path = Path(measured2["evidence"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["counts"]["tested_left"] = 999  # a forged count
    path.write_text(json.dumps(stored), encoding="utf-8")
    failed = api2.validate_proposal(started2["proposal"], edited2["revision"])
    assert any("integrity check failed" in error for error in failed["errors"])

    # an authored evidence block never enters the candidate at all
    project3, api3, started3, candidate3, measured3, edited3 = measured_hypothesis(
        tmp_path / "authored"
    )
    api3.validate_proposal(started3["proposal"], edited3["revision"])
    page = api3.read_artifact(started3["proposal"], REFERENCE_EDIT)
    meta = _frontmatter(page["content"])
    meta["ariadne_evidence"]["local-to-global-prefix"][0]["tested_left"] = 999
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = page["content"].split("---", 2)[2]
    with pytest.raises(ValueError, match="system-owned trust claim"):
        api3.edit_proposal(
            started3["proposal"],
            started3["proposal"] and api3.review_proposal(started3["proposal"])["revision"],
            {**REFERENCE_EDIT, "content": f"---\n{front}\n---{body}"},
        )


# ------------------------------------------------ [7]: the local CLI adapter


def test_cli_inspect_mapping_roundtrip_matches_the_core(tmp_path, capsys):
    """Issue #43 [7]: the shared operation is wired to the local CLI with the
    same one-JSON-value contract — the request file carries the candidate (or
    the {candidate, limits} object form), and the printed envelope is the
    core's receipt with its retained evidence path."""
    from ariadne.authoring_cli import main as authoring_cli

    project, api, started = approved_project(tmp_path)
    request = tmp_path / "candidate.json"
    request.write_text(
        json.dumps({"candidate": prefix_candidate(), "limits": {"sample_rows": 3}}),
        encoding="utf-8",
    )
    assert (
        authoring_cli(
            [
                "inspect-mapping",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--file",
                str(request),
                "--project",
                str(project),
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    receipt = out["receipt"]
    twin = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        prefix_candidate(),
        limits={"sample_rows": 3},
    )
    assert out["receipt_id"] == receipt["receipt_id"]
    assert receipt["counts"] == twin["receipt"]["counts"]
    assert receipt["coverage"] == twin["receipt"]["coverage"]
    assert receipt["sample_rows"] == 3
    assert Path(out["evidence"]).is_file()
    # refusals keep the one-JSON-error-object contract
    capsys.readouterr()
    assert (
        authoring_cli(
            [
                "inspect-mapping",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--file",
                str(request),
                "--project",
                str(project),
            ]
        )
        == 0
    )
    capsys.readouterr()
    raising = tmp_path / "raised.json"
    raising.write_text(
        json.dumps({"candidate": prefix_candidate(), "limits": {"sample_rows": 1001}}),
        encoding="utf-8",
    )
    assert (
        authoring_cli(
            [
                "inspect-mapping",
                "--proposal",
                started["proposal"],
                "--expected-revision",
                started["candidate_revision"],
                "--file",
                str(raising),
                "--project",
                str(project),
            ]
        )
        == 1
    )
    error = json.loads(capsys.readouterr().err)
    assert "RAISE the operator ceiling" in error["error"]["message"]


def test_deadline_guard_interrupts_and_refuses_uncancellable_execution():
    """Issue #43 [3]: the deadline guard converts an interruption that fired
    at/after expiry into the explicit deadline refusal, cancels its watchdog
    (no background read keeps running), and a backend whose execution cannot
    be interrupted is an explicit refusal — never a fake passing check."""
    import duckdb as _duckdb

    budget = execution.DeadlineBudget(0.05)
    expired = execution.DeadlineBudget(1e-9)
    while not expired.expired():  # the tiny budget is spent deterministically
        pass
    with pytest.raises(ValueError, match="deadline"):
        with expired.guard(object()):
            raise AssertionError("never reached")  # pragma: no cover

    class InterruptedConnection:
        """A connection whose query is interrupted by the watchdog."""

        def __init__(self):
            self.interrupted = False

        def interrupt(self):
            self.interrupted = True

    con = InterruptedConnection()
    clock = {"now": 0.0}
    with pytest.raises(ValueError, match="deadline"):
        with execution.DeadlineBudget(1e-9, clock=lambda: clock["now"]).guard(con):
            while not con.interrupted:
                pass  # the watchdog fires mid-"statement"
            clock["now"] = 100.0  # the budget is spent as the interruption lands
            raise _duckdb.InterruptException()
    # a non-deadline backend error keeps its own type (never mislabeled)
    with pytest.raises(_duckdb.Error):
        with budget.guard(con):
            raise _duckdb.InvalidInputException("bad input")

    class SilentConnection:  # no interrupt(): unbounded by construction
        pass

    with pytest.raises(ValueError, match="cannot be bounded and cancelled"):
        with budget.guard(SilentConnection()):
            raise AssertionError("never reached")  # pragma: no cover


# ------------------------- the K3 fix pass: review findings 1–9


def test_pairing_and_scope_must_bind_participating_measured_assets(tmp_path):
    """Finding 1: a pairing binding names a column of ITS side's measured
    asset (a pairing key naming another asset's identity refuses), a scope
    predicate attached to no participating measured asset refuses, and every
    bound column must exist BEFORE anything is measured — a pairing identity
    can never name assets other than those actually read."""
    project, api, started = approved_project(tmp_path)
    orders = resource("orders", "orders")
    erp = resource("erp", "erp_orders")
    storemeta = resource("storemeta", "prefix_map")
    base = {
        "family": "equality",
        "left": [{"resource": orders, "column": "store_id"}],
        "right": [{"resource": erp, "column": "store_id"}],
    }
    with pytest.raises(ValueError, match="pairing\\[0\\] left binding must name"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                **base,
                "pairing": [
                    {
                        "left": {"resource": storemeta, "column": "store_id"},
                        "right": {"resource": erp, "column": "store_id"},
                    }
                ],
            },
        )
    with pytest.raises(ValueError, match="not a participating measured asset"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                **base,
                "scope": [
                    {"resource": storemeta, "column": "store_id", "op": "eq", "value": "ABC"}
                ],
            },
        )
    # a bound column that exists on no participating asset refuses up front
    with pytest.raises(ValueError, match="not present in the catalog asset"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                **base,
                "scope": [{"resource": orders, "column": "no_such_column", "op": "eq", "value": 1}],
            },
        )
    with pytest.raises(ValueError, match="not present in the catalog asset"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            {
                **base,
                "pairing": [
                    {
                        "left": {"resource": orders, "column": "no_such_column"},
                        "right": {"resource": erp, "column": "order_id"},
                    }
                ],
            },
        )
    evidence_dir = project / ".ariadne" / "evidence" / started["proposal"]
    assert not evidence_dir.exists() or not any(evidence_dir.iterdir())


def test_one_bounded_union_sample_per_participating_asset(tmp_path, monkeypatch):
    """Finding 2: the sampled-row ceiling is PER ASSET, not per query — the
    prefix candidate's two sides address the SAME orders asset, so exactly ONE
    bounded union-column sample is taken from it and both sides (and the
    lookup) reuse it."""
    import ariadne.authoring as authoring_module

    project, api, started = approved_project(tmp_path)
    calls: list[tuple[str, tuple]] = []
    real = authoring_module.inspection_sample_statement

    def counting(table, columns, scope, limit):
        calls.append((table["resource"], tuple(columns)))
        return real(table, columns, scope, limit)

    monkeypatch.setattr(authoring_module, "inspection_sample_statement", counting)
    result = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        prefix_candidate(),
        limits={"sample_rows": 3},
    )
    orders_resource = resource("orders", "orders")
    orders_samples = [entry for entry in calls if entry[0] == orders_resource]
    assert len(orders_samples) == 1  # ONE sample of the shared asset
    assert orders_samples[0][1] == ("store_id", "local_order_number", "global_order_number")
    storemeta_samples = [
        entry for entry in calls if entry[0] == resource("storemeta", "prefix_map")
    ]
    assert len(storemeta_samples) == 1  # the lookup asset also sampled once
    # the union sample (ordered by the union columns) carries the QQQ row whose
    # target is NULL: the right side tests two complete rows of that one sample
    counts = result["receipt"]["counts"]
    assert counts["tested_left"] == 3
    assert counts["tested_right"] == 2


def test_duplicate_pairing_keys_disclose_ambiguity_never_collapse(tmp_path):
    """Finding 3: duplicate pairing keys keep EVERY right row — a key carrying
    multiple right rows (EUR duplicated, USD conflicting) is disclosed as an
    ambiguous pairing: the basis never claims unique independent pairing and
    no counterevidence (US-DOLLAR beside USD-SYM) is silently discarded."""
    project, api, started = approved_project(tmp_path)
    orders, refdata = resource("orders", "orders"), resource("refdata", "currency_map")
    result = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        {
            "family": "equality",
            "left": [{"resource": orders, "column": "currency"}],
            "right": [{"resource": refdata, "column": "symbol"}],
            "pairing": [
                {
                    "left": {"resource": orders, "column": "currency"},
                    "right": {"resource": refdata, "column": "from_ccy"},
                }
            ],
        },
    )
    receipt = result["receipt"]
    assert receipt["pairing"]["status"] == "ambiguous"
    assert receipt["pairing"]["ambiguous_keys"] == 2  # EUR and USD carry two rows
    assert receipt["pairing"]["max_rows_per_key"] == 2
    assert receipt["pairing"]["paired"] == 0  # nothing silently paired
    assert receipt["comparison_basis"] == "ambiguous-pairing"
    assert any("ambiguous" in note for note in receipt["limitations"])


def test_truncated_lookup_disclosure_and_null_mapped_values(tmp_path):
    """Finding 4: a truncated lookup sample never claims full measurement —
    with the fact side fully measured and the lookup asset's sample cut, the
    designation drops to sampled with the truncation disclosed, a fact key
    beyond the sampled lookup rows is an UNKNOWN lookup (not missing), and the
    lookup-side denominators count null mapped values."""
    project, api, started = approved_project(tmp_path)
    orders = resource("orders", "orders")
    candidate = {
        **lookup_candidate(),
        "scope": [{"resource": orders, "column": "currency", "op": "eq", "value": "GBP"}],
    }
    result = api.inspect_mapping(
        started["proposal"],
        started["candidate_revision"],
        candidate,
        limits={"sample_rows": 3},
    )
    receipt = result["receipt"]
    counts = receipt["counts"]
    assert counts["eligible_left"] == 1 and counts["tested_left"] == 1  # fact side full
    assert receipt["designation"] == "sampled"  # the truncated lookup forbids 'full'
    lookup_counts = receipt["lookup_counts"]
    assert lookup_counts["eligible"] == 4  # the NULL-symbol GBP row is not eligible
    assert lookup_counts["nulls"] == 1  # the null mapped value is COUNTED
    assert lookup_counts["tested"] == 2  # two of four complete rows sampled (GBP sorts in)
    assert receipt["unknown_lookup_count"] == 1  # the GBP key is beyond the sample
    assert receipt["missing_key_count"] == 0
    assert any(
        "lookup" in note and ("sample" in note or "truncat" in note)
        for note in receipt["limitations"]
    )


def test_retargeted_representation_invalidates_the_receipt_summary(tmp_path):
    """Finding 5: a verified receipt attaches only to the declaration it
    measured — retargeting an endpoint representation's column (keeping the
    old candidate and receipt ids) fails evidence verification and drops the
    attached summary."""
    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"])
    page = api.read_artifact(started["proposal"], REFERENCE_EDIT)
    meta = _frontmatter(page["content"])
    meta["ariadne"]["representations"][1]["fields"] = [  # retargeted 'to' endpoint
        {"resource": resource("orders", "orders"), "column": "local_order_number"}
    ]
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = page["content"].split("---", 2)[2]
    revised = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {**REFERENCE_EDIT, "content": f"---\n{front}\n---{body}"},
    )
    failed = api.validate_proposal(started["proposal"], revised["revision"])
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any(
        "measured right bindings" in error or "measured left bindings" in error
        for error in failed["errors"]
    )
    assert (
        _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"]) is None
    )


def test_unmeasured_required_scope_invalidates_the_receipt_summary(tmp_path):
    """Finding 5 (the scope half): the measured candidate must also correspond
    to the endpoints' REQUIRED scope — a representation requiring a scope
    column the receipt did not measure under never keeps its summary."""
    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    page = api.read_artifact(started["proposal"], REFERENCE_EDIT)
    meta = _frontmatter(page["content"])
    meta["ariadne"]["representations"][0]["scope"] = [  # required scope widened
        {"resource": resource("orders", "orders"), "column": "store_id"}
    ]
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    body = page["content"].split("---", 2)[2]
    revised = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {**REFERENCE_EDIT, "content": f"---\n{front}\n---{body}"},
    )
    failed = api.validate_proposal(started["proposal"], revised["revision"])
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any("required scope" in error for error in failed["errors"])
    assert (
        _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"]) is None
    )


def test_aged_receipt_beyond_the_operator_budget_loses_its_summary(tmp_path):
    """Finding 6: the operator's evidence age budget (default 24h, host
    config) bounds a receipt's validity for ATTACHMENT — an aged receipt loses
    its verified summary; unversioned data stays as_of, age never claims
    currency."""
    from ariadne.context import _canonical_digest

    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"])
    # age the STORED receipt past the default 24h budget, re-sealing its
    # integrity digest: the aging is the only change
    path = Path(measured["evidence"])
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored.pop("integrity_digest")
    aged = (datetime.now(UTC) - timedelta(hours=25)).isoformat(timespec="seconds")
    stored["observed_at"] = aged
    stored["version_signal"]["observed_at"] = aged
    stored["integrity_digest"] = _canonical_digest(stored)
    path.write_text(json.dumps(stored, sort_keys=True) + "\n", encoding="utf-8")
    notes = api.read_artifact(started["proposal"], {"kind": "seed_notes"})
    saved = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {"kind": "seed_notes", "content": notes["content"] + "\nAged evidence.\n"},
    )
    failed = api.validate_proposal(started["proposal"], saved["revision"])
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any("age budget" in error for error in failed["errors"])
    assert (
        _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"]) is None
    )


POLICY_PAGE = (
    "---\n"
    "type: policy\n"
    "status: draft\n"
    "title: Order numbering\n"
    "description: How local and global order numbers relate.\n"
    "tags:\n"
    "- policy\n"
    "sources:\n"
    "- data/seed_notes.md\n"
    "---\n\n"
    "# Order numbering\n\n"
    "Local order numbers are store-scoped; the global identity carries the\n"
    "store prefix.\n"
)


def test_changed_cited_policy_page_invalidates_the_receipt(tmp_path):
    """Finding 6: the receipt binds the cited Policy/OSI pages of the
    Reference that declares its candidate — a changed cited Policy page
    invalidates the dependent receipt immediately (the summary drops)."""
    project, api, started = approved_project(tmp_path)
    candidate = prefix_candidate()
    policy_edit = {"kind": "page", "section": "policies", "name": "order-numbering"}
    citing = [
        {"id": "policy-order-numbering", "resource": "context_layer/policies/order-numbering.md"}
    ]
    revision = api.edit_proposal(
        started["proposal"], started["candidate_revision"], {**policy_edit, "content": POLICY_PAGE}
    )["revision"]
    revision = api.edit_proposal(
        started["proposal"],
        revision,
        {**REFERENCE_EDIT, "content": reference_page(candidate, [], sources=citing)},
    )["revision"]
    measured = api.inspect_mapping(started["proposal"], revision, candidate)
    policy_deps = measured["receipt"]["dependencies"]["policy_osi"]
    assert [entry["resource"] for entry in policy_deps] == [
        "context_layer/policies/order-numbering.md"
    ]
    assert all(entry["digest"] for entry in policy_deps)
    revision = api.edit_proposal(
        started["proposal"],
        revision,
        {
            **REFERENCE_EDIT,
            "content": reference_page(candidate, [measured["receipt_id"]], sources=citing),
        },
    )["revision"]
    validated = api.validate_proposal(started["proposal"], revision)
    outcomes = {check["name"]: check["outcome"] for check in validated["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "passed"
    assert _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"])
    # change the CITED POLICY page: the measured dependency digest no longer
    # matches — referenced Policy content changes invalidate immediately
    revision = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {
            **policy_edit,
            "content": POLICY_PAGE.replace("store-scoped", "globally unique"),
        },
    )["revision"]
    failed = api.validate_proposal(started["proposal"], revision)
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any("cited Policy/OSI" in error for error in failed["errors"])
    assert (
        _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"]) is None
    )


def test_changed_lookup_asset_schema_invalidates_the_receipt(tmp_path):
    """Finding 6: the receipt binds the lookup asset's FULL schema digest — a
    schema change on the lookup asset (even an added UNMEASURED column)
    invalidates the dependent receipt immediately."""
    project, api, started, candidate, measured, edited = measured_hypothesis(tmp_path)
    validated = api.validate_proposal(started["proposal"], edited["revision"])
    assert measured["receipt"]["dependencies"]["lookup_schema_digest"]
    write_parquet(
        project / "data" / "storemeta" / "prefix_map.parquet",
        [(*row, "note") for row in PREFIX_MAP_ROWS],
        ["store_id", "prefix", "note"],
    )
    notes = api.read_artifact(started["proposal"], {"kind": "seed_notes"})
    saved = api.edit_proposal(
        started["proposal"],
        validated["revision"],
        {"kind": "seed_notes", "content": notes["content"] + "\nLookup schema changed.\n"},
    )
    failed = api.validate_proposal(started["proposal"], saved["revision"])
    outcomes = {check["name"]: check["outcome"] for check in failed["report"]["checks"]}
    assert outcomes["mapping_evidence"] == "failed"
    assert any("lookup asset" in error for error in failed["errors"])
    assert (
        _evidence_block(api.read_artifact(started["proposal"], REFERENCE_EDIT)["content"]) is None
    )


def test_requested_bindings_receive_bounded_shape_summaries(tmp_path):
    """Finding 7 (spec §7): each REQUESTED binding of the measured candidate
    receives a bounded aggregate identifier-shape summary from its asset's
    permitted sample — lengths, nulls, distinct-within-sample and charset
    classes only; never raw values without the operator's permission."""
    project, api, started = approved_project(tmp_path)
    result = api.inspect_mapping(
        started["proposal"], started["candidate_revision"], prefix_candidate()
    )
    shapes = {(s["resource"], s["column"]): s for s in result["receipt"]["shapes"]}
    orders = resource("orders", "orders")
    storemeta = resource("storemeta", "prefix_map")
    assert set(shapes) == {
        (orders, "store_id"),
        (orders, "local_order_number"),
        (orders, "global_order_number"),
        (storemeta, "store_id"),
        (storemeta, "prefix"),
    }
    local = shapes[(orders, "local_order_number")]
    assert local["sampled"] == 5  # every scoped EU row of the one orders sample
    assert local["nulls"] == 0
    assert local["distinct"] == 4  # 00123, 123123, 999999, 777777
    assert local["length"] == {"min": 5, "max": 6, "avg": 5.8}
    assert local["charset"]["digits_only"] == 5
    target = shapes[(orders, "global_order_number")]
    assert target["nulls"] == 2  # the QQQ row and the NULL-store row
    serialized = json.dumps(result["receipt"]["shapes"])
    for identifier in ("123123", "00123", "ABC", "XYZ", "QQQ", "EUR"):
        assert identifier not in serialized, identifier


def test_non_finite_limits_refuse_and_the_ceiling_measures_the_final_envelope(tmp_path):
    """Finding 8: a non-finite numeric limit (NaN/inf) is an explicit refusal —
    it can never disable a ceiling comparison — and the response ceiling
    measures the COMPLETE final envelope, evidence path included, before any
    receipt is retained."""
    from ariadne.authoring_inputs import DEFAULT_INSPECTION_LIMITS, effective_inspection_limits

    with pytest.raises(ValueError, match="finite"):
        effective_inspection_limits(DEFAULT_INSPECTION_LIMITS, {"response_bytes": float("nan")})
    with pytest.raises(ValueError, match="finite"):
        effective_inspection_limits(DEFAULT_INSPECTION_LIMITS, {"sample_rows": float("inf")})
    project, api, started = approved_project(tmp_path)
    full = api.inspect_mapping(
        started["proposal"], started["candidate_revision"], prefix_candidate()
    )
    without_path = {key: full[key] for key in ("proposal", "revision", "receipt_id", "receipt")}
    base = len(json.dumps(without_path, ensure_ascii=False).encode("utf-8"))
    total = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))
    assert total > base + 8  # the evidence path materially grows the envelope
    evidence_dir = project / ".ariadne" / "evidence" / started["proposal"]
    retained_before = len(list(evidence_dir.iterdir())) if evidence_dir.exists() else 0
    with pytest.raises(ValueError, match="over the"):
        api.inspect_mapping(
            started["proposal"],
            started["candidate_revision"],
            prefix_candidate(),
            limits={"response_bytes": base + 8},
        )
    assert len(list(evidence_dir.iterdir())) == retained_before  # nothing retained


def test_successful_late_completion_is_deadline_exhaustion():
    """Finding 9: a guarded statement that COMPLETES beyond the budget is an
    exhaustion refusal too — the deadline is never claimed to have stopped a
    phase whose result escaped the budget."""
    times = [0.0, 0.0, 0.5, 9.0]

    class Connection:
        def interrupt(self):
            pass

    budget = execution.DeadlineBudget(1.0, clock=lambda: times.pop(0) if times else 9.0)
    with pytest.raises(ValueError, match="deadline"):
        with budget.guard(Connection()):
            pass  # the guarded statement "succeeds" — after the budget elapsed


def test_source_setup_failure_closes_the_owned_connection(tmp_path, monkeypatch):
    """Finding 9: a failing source SETUP closes the connection it opened — no
    leaked read or session survives the refused setup."""
    import ariadne.sources as sources_module

    created = []
    real_connect = sources_module.duckdb.connect

    def tracking(*args, **kwargs):
        con = real_connect(*args, **kwargs)
        created.append(con)
        return con

    monkeypatch.setattr(sources_module.duckdb, "connect", tracking)
    registry = tmp_path / "ariadne.yaml"
    registry.write_text(
        yaml.safe_dump(
            {"sources": [{"name": "broken", "type": "parquet", "path": "data/missing.parquet"}]}
        )
    )
    with pytest.raises(Exception, match="missing.parquet|IO Error"):
        sources_module.build_connection(sources_module.load_registry(registry))
    assert created, "a connection was opened and must now be closed"
    with pytest.raises(Exception, match="Connection Error|already closed|Cannot call"):
        created[0].execute("SELECT 1")  # closed: no leaked session remains usable

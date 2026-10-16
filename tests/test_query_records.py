"""Bounded record selection through the core (spec 0014 §3, issue #57/S2) —
the V1 contract.

ONE parameterized ``test_query_records_contract`` at QueryRuntime using ONLY
specification §7's synthetic fixture: ``fixture.events`` with the real
request's five column roles (the spec §3 normative example names them), the
e1–e8 table with the exact synthetic values, Berlin 2026-01-15, MAT-B/MAT-C
assignment. The N=2/N=3/N=10 top-N answers, ties, suffix controls, declared
time comparisons, winter/summer instants, both DST refusals, eligible/
ineligible malformed handling, the identity/request refusals, and the
legacy/managed admission boundary.

Expectations derive ONLY from specification §7 V1 (the fixture table above is
the oracle) and the spec's own normative example — never from the
compiler/planner under test; no invented event key, no private identifiers
(every value is synthetic).
"""

import asyncio
import sqlite3

import pytest  # pyright: ignore[reportMissingImports] — analysis env may lack site-packages

from ariadne.planner import PlannerError
from ariadne.query import QueryRuntime, _QueryRuntimeSession
from ariadne.query_results import QueryResultError  # pyright: ignore[reportMissingImports] — drift

_MODELS = """version: 0.2.0.dev0
semantic_model:
  - name: records_probe
    description: V1 probe model
    datasets:
      - name: ev
        source: fixture.main.events
        fields:
          - name: productnumber
            expression: {dialects: [{dialect: ANSI_SQL, expression: productnumber}]}
    metrics:
      - name: probe_count
        description: probe count
        expression: {dialects: [{dialect: ANSI_SQL, expression: "COUNT(*)"}]}
"""

# the §7 V1 fixture identities, insertion order e1..e8 (trace type 2
# throughout; MAT-B except e3's MAT-C); every non-null assembly string is
# 2026-01-15 in Berlin
_EVENTS = [
    ("motor-A", "MAT-B", "synthetic-A/253", 2, "2026-01-15 09:00:00"),  # e1
    ("motor-A", "MAT-B", "synthetic-B/25A", 2, "2026-01-15 11:00:00"),  # e2
    ("motor-B", "MAT-C", "synthetic-C/259", 2, "2026-01-15 11:00:00"),  # e3
    ("motor-C", "MAT-B", None, 2, "2026-01-15 12:00:00"),  # e4
    ("motor-D", "MAT-B", "synthetic-X/25,", 2, "2026-01-15 13:00:00"),  # e5
    ("motor-E", "MAT-B", "", 2, "2026-01-15 14:00:00"),  # e6
    ("motor-F", "MAT-B", "synthetic-F/251", 2, None),  # e7
    ("motor-G", "MAT-B", "   ", 2, "2026-01-15 14:00:00"),  # e8
]

_EVENT_COLUMNS = """
    productnumber TEXT,
    genealogydata_materialnumber TEXT,
    genealogydata_tracedata TEXT,
    genealogydata_genealogytracetype INTEGER,
    genealogydata_assembleddatetime VARCHAR
"""

# the normative §3 example request over the synthetic fixture (synthetic
# values, the documented Berlin clock, the approved brake suffix rule)
_RECORDS_REQUEST = {
    "dataset": "fixture.events",
    "fields": [
        "productnumber",
        "genealogydata_materialnumber",
        "genealogydata_tracedata",
        "genealogydata_genealogytracetype",
        "genealogydata_assembleddatetime",
    ],
    "filters": [
        {"field": "genealogydata_tracedata", "op": "regex", "value": "/2[0-9][0-9A-Z]$"},
        {"field": "genealogydata_assembleddatetime", "op": "is_not_null"},
    ],
    "timestamp": {
        "field": "genealogydata_assembleddatetime",
        "format": "%Y-%m-%d %H:%M:%S",
        "timezone": "Europe/Berlin",
    },
    "order": [{"field": "genealogydata_assembleddatetime", "direction": "desc"}],
}


def _motors(result):
    """(motor, tracedata) per returned row — the fixture's row identities."""
    return [(row["productnumber"], row["genealogydata_tracedata"]) for row in result["rows"]]


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """One tiny real local served tree + registry over two sqlite sources:
    the §7 V1 events fixture (plus a shuffled-insertion control), the
    suffix/clock/DST/malformed/poisoning control tables and a second source
    carrying a same-named table for the ambiguous-dataset case."""
    root = tmp_path_factory.mktemp("s2_served")
    models = root / "semantic_layer" / "models"
    models.mkdir(parents=True)
    models.joinpath("probe.yml").write_text(_MODELS, encoding="utf-8")
    (root / "context_layer").mkdir()
    db = root / "fixture.db"
    con = sqlite3.connect(db)

    def events_table(name, rows):
        # pi-lens-ignore: python-sql-injection — the fixed local fixture names below
        con.execute(f"CREATE TABLE {name} ({_EVENT_COLUMNS})")
        # pi-lens-ignore: python-sql-injection — the fixed local fixture names below
        con.executemany(f"INSERT INTO {name} VALUES (?,?,?,?,?)", rows)

    events_table("events", _EVENTS)
    events_table("events_shuffled", list(reversed(_EVENTS)))
    # both DST rejection examples of §7 V1 (eligible rows: suffix matches,
    # non-null wall time)
    events_table(
        "dst_ambiguous",
        [("motor-Z", "MAT-B", "synthetic-Z/253", 2, "2026-10-25 02:30:00")],
    )
    events_table(
        "dst_nonexistent", [("motor-Z", "MAT-B", "synthetic-Z/253", 2, "2026-03-29 02:30:00")]
    )
    # an ELIGIBLE malformed wall time (suffix matches, value is not the
    # documented encoding)
    events_table("malformed", [("motor-Z", "MAT-B", "synthetic-Z/253", 2, "2026-01-15 11:00")])
    # the ineligible-malformed control: a suffix-INELIGIBLE row carries a
    # malformed wall time and must never poison the eligible answer
    events_table(
        "poisoned",
        [
            ("motor-A", "MAT-B", "synthetic-A/253", 2, "2026-01-15 09:00:00"),
            ("motor-A", "MAT-B", "synthetic-B/25A", 2, "2026-01-15 11:00:00"),
            ("motor-B", "MAT-C", "synthetic-C/259", 2, "2026-01-15 11:00:00"),
            ("motor-D", "MAT-B", "synthetic-X/25,", 2, "not-a-time"),
        ],
    )
    # fully identical projections stay repeated, never silently deduplicated
    events_table(
        "dups",
        [
            ("motor-A", "MAT-B", "synthetic-A/253", 2, "2026-01-15 09:00:00"),
            ("motor-A", "MAT-B", "synthetic-B/25A", 2, "2026-01-15 11:00:00"),
            ("motor-A", "MAT-B", "synthetic-A/253", 2, "2026-01-15 09:00:00"),
        ],
    )
    # the winter/summer instant controls (spec §7 V1-4):
    # 2026-01-15 11:00 Berlin -> 10:00 UTC; 2026-07-15 11:00 Berlin -> 09:00
    # UTC (and hence 2026-07-15 12:00 Berlin -> 10:00 UTC)
    con.execute("CREATE TABLE clocks (label TEXT, genealogydata_assembleddatetime VARCHAR)")
    con.executemany(
        "INSERT INTO clocks VALUES (?, ?)",
        [
            ("winter-11", "2026-01-15 11:00:00"),
            ("summer-11", "2026-07-15 11:00:00"),
            ("summer-12", "2026-07-15 12:00:00"),
        ],
    )
    # the §7 V1-3 suffix controls: /253 and /25A accept; /25, /25a /2530,
    # trailing whitespace and null/empty/blank reject. 'pad /253' accepts:
    # DuckDB's regexp_matches is the spec's named (search) semantics.
    con.execute("CREATE TABLE suffixes (probe VARCHAR)")
    con.executemany(
        "INSERT INTO suffixes VALUES (?)",
        [
            ("/253",),
            ("/25A",),
            ("/25,",),
            ("/25a",),
            ("/2530",),
            ("synthetic-X/253 ",),
            ("pad /253",),
            (None,),
            ("",),
            ("   ",),
        ],
    )
    # no implicit trace-type/SAP filter: both trace types stay in the answer
    con.execute(
        "CREATE TABLE typemix (genealogydata_tracedata TEXT, "
        "genealogydata_genealogytracetype INTEGER)"
    )
    con.executemany("INSERT INTO typemix VALUES (?, ?)", [("syn-T/253", 2), ("syn-U/251", 7)])
    # fix pass 1, finding 2: physical columns named exactly like the
    # execution helper namespace — ordinary value columns, never helpers
    con.execute(
        "CREATE TABLE helper_named ("
        '"__ariadne_record_ts" VARCHAR, "__ariadne_record_rn" INTEGER, '
        '"__ariadne_record_has_more" BOOLEAN, "__ariadne_record_base" VARCHAR, '
        '"__ariadne_record_topn" VARCHAR, productnumber TEXT)'
    )
    con.executemany(
        "INSERT INTO helper_named VALUES (?,?,?,?,?,?)",
        [
            ("2026-01-15 09:00:00", 7, False, "base-1", "topn-1", "motor-A"),
            ("2026-01-15 11:00:00", 8, False, "base-2", "topn-2", "motor-B"),
            ("2026-01-15 12:00:00", 9, False, "base-3", "topn-3", "motor-C"),
        ],
    )
    # fix pass 1, finding 3: a declared timestamp on a field that is neither
    # selected nor an order key must still be interpreted on every eligible
    # row (the second row's value is malformed on an ELIGIBLE row)
    events_table(
        "ts_unselected",
        [
            ("motor-A", "MAT-B", "synthetic-A/253", 2, "2026-01-15 11:00:00"),
            ("motor-Z", "MAT-B", "synthetic-Z/253", 2, "not-a-time"),
        ],
    )
    # fix pass 1, finding 5: Australia/Lord_Howe folds 30 minutes — the
    # fold wall time 2026-04-05 01:45:00 happens twice; 03:00 is ordinary
    con.execute("CREATE TABLE lord_howe (label TEXT, wall VARCHAR)")
    con.executemany(
        "INSERT INTO lord_howe VALUES (?, ?)",
        [("fold-0145", "2026-04-05 01:45:00"), ("plain-0300", "2026-04-05 03:00:00")],
    )
    # fix pass 2: the same helper namespace in UPPERCASE physical columns —
    # DuckDB resolves identifiers case-insensitively, so allocation must
    # treat these as collisions too
    con.execute(
        "CREATE TABLE upcase_named ("
        '"__ARIADNE_RECORD_RN" INTEGER, "__ARIADNE_RECORD_HAS_MORE" BOOLEAN, '
        '"__ARIADNE_RECORD_TS" VARCHAR, productnumber TEXT)'
    )
    con.executemany(
        "INSERT INTO upcase_named VALUES (?,?,?,?)",
        [
            (7, False, "2026-01-15 09:00:00", "motor-A"),
            (8, False, "2026-01-15 11:00:00", "motor-B"),
            (9, False, "2026-01-15 12:00:00", "motor-C"),
        ],
    )
    con.commit()
    con.close()
    # a second source carrying a same-named table: the bare display name is
    # then ambiguous and must refuse with the canonical resources
    db2 = root / "fixture2.db"
    con2 = sqlite3.connect(db2)
    con2.execute("CREATE TABLE events (productnumber TEXT)")
    con2.execute("INSERT INTO events VALUES ('motor-2')")
    con2.commit()
    con2.close()
    registry = root / "ariadne.yaml"
    registry.write_text(
        "sources:\n"
        "  - name: fixture\n"
        "    type: sqlite\n"
        f"    path: {db}\n"
        "  - name: fixture2\n"
        "    type: sqlite\n"
        f"    path: {db2}\n",
        encoding="utf-8",
    )
    return root, db, registry


def make_runtime(served, **limits):
    root, _db, registry = served
    return _QueryRuntimeSession(
        root / "semantic_layer",
        root / "context_layer",
        None,
        sources=str(registry),
        query_limits=limits or None,
    )


def make_synthetic_db_runtime(served):
    """Use the private numerical seam with a synthetic implicit SQLite attach."""
    root, db, _registry = served
    return _QueryRuntimeSession(root / "semantic_layer", root / "context_layer", db)


def _refusal(exc: QueryResultError) -> dict:
    return exc.refusal()


@pytest.mark.parametrize(
    "case",
    [
        "top2_returns_e2_e3_with_more_matches",
        "top3_keeps_the_repeated_motor",
        "top10_returns_the_three_matches",
        "motor_equality_filter_returns_e2_e1",
        "timestamp_comparison_uses_the_declared_clock",
        "dropping_the_null_test_includes_e7_last",
        "insertion_order_does_not_change_visible_ties",
        "identical_projections_stay_repeated",
        "empty_match_set_returns_no_rows",
        "suffix_controls",
        "match_is_on_trace_data_not_material_number",
        "no_implicit_trace_type_or_sap_filter",
        "winter_and_summer_instants",
        "ambiguous_fall_back_refuses",
        "nonexistent_spring_forward_refuses",
        "eligible_malformed_refuses",
        "ineligible_malformed_never_poisons",
        "unknown_dataset_refuses",
        "ambiguous_dataset_refuses",
        "unknown_field_refuses",
        "sql_shaped_identities_refuse_before_execution",
        "unknown_request_keys_refuse",
        "invalid_regex_refuses",
        "wrong_types_and_encodings_refuse",
        "excessive_limits_refuse",
        "synthetic_session_without_admission_refuses_graph_queries",
        "missing_managed_admission_still_refuses",
        "helper_named_physical_columns_stay_values",
        "declared_timestamp_evaluated_without_selection_or_order",
        "regex_validity_follows_the_duckdb_engine",
        "sub_hour_folds_refuse_like_hour_folds",
        "uppercase_helper_named_columns_stay_values",
    ],
)
def test_query_records_contract(case, served, tmp_path):
    if case == "top2_returns_e2_e3_with_more_matches":
        rt = make_runtime(served)
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 2}))
        # §7 V1-1: exactly e2, e3 (the repeated 11:00 tie breaks on the
        # selected columns — motor-A before motor-B) with more matches
        assert _motors(result) == [("motor-A", "synthetic-B/25A"), ("motor-B", "synthetic-C/259")]
        # rows keep the ORIGINAL selected wall-time value, not the instant
        assert [row["genealogydata_assembleddatetime"] for row in result["rows"]] == [
            "2026-01-15 11:00:00",
            "2026-01-15 11:00:00",
        ]
        assert result["governed"] is False  # every Ad-hoc Record Query
        assert result["result"] == {
            "status": "complete",
            "complete": True,
            "scope": "requested_top_n",
            "requested_limit": 2,
            "returned_rows": 2,
            "has_more_matching": True,
        }
        # truthful bounded provenance + the logical/executed distinction
        assert result["dataset"] == "fixture.main.events"
        assert result["resource"].startswith("ariadne://table/")
        # the private numerical seam's honest route label (the legacy
        # plain-root route is retired; no Git snapshot identity exists here)
        assert result["provenance"]["route"] == "internal-synthetic-session"
        assert result["provenance"]["admission"] is None
        assert "unversioned" in result["provenance"]["disclosure"]
        assert "LIMIT 2" in result["sql"]  # the logical top-N selection
        assert result["executed_sql"] != result["sql"]
        assert "ROW_NUMBER" in result["executed_sql"] and "LEAD" in result["executed_sql"]
        # the plan discloses the tie order, the timestamp interpretation and
        # the same-execution lookahead
        plan = result["plan"]
        assert plan["tie_order"] == [
            "productnumber",
            "genealogydata_materialnumber",
            "genealogydata_tracedata",
            "genealogydata_genealogytracetype",
        ]
        assert plan["timestamp"]["timezone"] == "Europe/Berlin"
        assert "interpretation" in plan["timestamp"]
        assert "same execution" in plan["lookahead"]

    elif case == "top3_keeps_the_repeated_motor":
        rt = make_runtime(served)
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 3}))
        # §7 V1-1: e2, e3, e1 — the repeated motor-A is retained (no dedup)
        assert _motors(result) == [
            ("motor-A", "synthetic-B/25A"),
            ("motor-B", "synthetic-C/259"),
            ("motor-A", "synthetic-A/253"),
        ]
        assert result["result"]["has_more_matching"] is False
        assert result["result"]["complete"] is True  # complete for the top-N

    elif case == "top10_returns_the_three_matches":
        rt = make_runtime(served)
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 10}))
        assert len(result["rows"]) == 3
        assert result["result"]["has_more_matching"] is False
        assert result["result"]["returned_rows"] == 3
        # complete means the requested top-N, never the full population
        assert result["result"]["scope"] == "requested_top_n"

    elif case == "motor_equality_filter_returns_e2_e1":
        rt = make_runtime(served)
        request = {
            **_RECORDS_REQUEST,
            "limit": 10,
            "filters": [
                *_RECORDS_REQUEST["filters"],
                {"field": "productnumber", "op": "=", "value": "motor-A"},
            ],
        }
        result = asyncio.run(rt.query_records(request))
        # §7 V1-2: the extra equality filter returns e2, e1
        assert _motors(result) == [("motor-A", "synthetic-B/25A"), ("motor-A", "synthetic-A/253")]

    elif case == "timestamp_comparison_uses_the_declared_clock":
        rt = make_runtime(served)
        # §7 V1-2: a timestamp comparison uses the declared interpretation —
        # '< 2026-01-15 11:00:00' in Berlin is '< 10:00 UTC', so e2/e3
        # (11:00 Berlin == 10:00 UTC) are OUT and only e1 remains; the
        # complementary '>= 11:00' keeps exactly e2, e3. The clocks case
        # below carries the lexical-vs-instant distinguishing control.
        request = {
            **_RECORDS_REQUEST,
            "limit": 10,
            "filters": [
                *_RECORDS_REQUEST["filters"],
                {
                    "field": "genealogydata_assembleddatetime",
                    "op": "<",
                    "value": "2026-01-15 11:00:00",
                },
            ],
        }
        result = asyncio.run(rt.query_records(request))
        assert _motors(result) == [("motor-A", "synthetic-A/253")]
        request["filters"][-1] = {
            "field": "genealogydata_assembleddatetime",
            "op": ">=",
            "value": "2026-01-15 11:00:00",
        }
        result = asyncio.run(rt.query_records(request))
        assert _motors(result) == [("motor-A", "synthetic-B/25A"), ("motor-B", "synthetic-C/259")]

    elif case == "dropping_the_null_test_includes_e7_last":
        rt = make_runtime(served)
        request = {
            **_RECORDS_REQUEST,
            "limit": 10,
            "filters": _RECORDS_REQUEST["filters"][:1],  # no is_not_null
        }
        result = asyncio.run(rt.query_records(request))
        # §7 V1-2: e7 (null timestamp) joins LAST under NULLS LAST
        assert _motors(result) == [
            ("motor-A", "synthetic-B/25A"),
            ("motor-B", "synthetic-C/259"),
            ("motor-A", "synthetic-A/253"),
            ("motor-F", "synthetic-F/251"),
        ]
        assert result["rows"][-1]["genealogydata_assembleddatetime"] is None
        assert result["result"]["has_more_matching"] is False

    elif case == "insertion_order_does_not_change_visible_ties":
        rt = make_runtime(served)
        shuffled = {**_RECORDS_REQUEST, "dataset": "fixture.events_shuffled", "limit": 2}
        result = asyncio.run(rt.query_records(shuffled))
        # §7 V1-2: reordering fixture insertion does not change visible ties
        assert _motors(result) == [("motor-A", "synthetic-B/25A"), ("motor-B", "synthetic-C/259")]

    elif case == "identical_projections_stay_repeated":
        rt = make_runtime(served)
        request = {**_RECORDS_REQUEST, "dataset": "fixture.dups", "limit": 10}
        result = asyncio.run(rt.query_records(request))
        # §7 V1-2: fully identical projections remain repeated records
        assert _motors(result) == [
            ("motor-A", "synthetic-B/25A"),
            ("motor-A", "synthetic-A/253"),
            ("motor-A", "synthetic-A/253"),
        ]
        assert result["result"]["returned_rows"] == 3

    elif case == "empty_match_set_returns_no_rows":
        rt = make_runtime(served)
        request = {
            **_RECORDS_REQUEST,
            "filters": [
                *_RECORDS_REQUEST["filters"],
                {"field": "productnumber", "op": "=", "value": "motor-Z"},
            ],
        }
        result = asyncio.run(rt.query_records(request))
        assert result["rows"] == []
        assert result["result"]["returned_rows"] == 0
        assert result["result"]["has_more_matching"] is False
        assert result["result"]["complete"] is True

    elif case == "suffix_controls":
        rt = make_runtime(served)
        result = asyncio.run(
            rt.query_records(
                {
                    "dataset": "fixture.suffixes",
                    "fields": ["probe"],
                    "filters": [{"field": "probe", "op": "regex", "value": "/2[0-9][0-9A-Z]$"}],
                    "order": [{"field": "probe"}],
                    "limit": 10,
                }
            )
        )
        # §7 V1-3: /253 and /25A accept; /25, /25a /2530, trailing whitespace
        # and null/empty/blank reject; DuckDB's search semantics accept the
        # leading-padding control
        assert [row["probe"] for row in result["rows"]] == ["/253", "/25A", "pad /253"]

    elif case == "match_is_on_trace_data_not_material_number":
        rt = make_runtime(served)
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 10}))
        # §7 V1-3: the predicate matches trace data, not material number —
        # e3 (MAT-C) is included through its trace data while MAT-B rows
        # without the suffix (e4–e8) are absent
        assert {row["genealogydata_materialnumber"] for row in result["rows"]} == {
            "MAT-B",
            "MAT-C",
        }
        assert all(row["genealogydata_tracedata"] for row in result["rows"])

    elif case == "no_implicit_trace_type_or_sap_filter":
        rt = make_runtime(served)
        result = asyncio.run(
            rt.query_records(
                {
                    "dataset": "fixture.typemix",
                    "fields": ["genealogydata_tracedata", "genealogydata_genealogytracetype"],
                    "filters": [
                        {
                            "field": "genealogydata_tracedata",
                            "op": "regex",
                            "value": "/2[0-9][0-9A-Z]$",
                        }
                    ],
                    "order": [{"field": "genealogydata_genealogytracetype"}],
                    "limit": 10,
                }
            )
        )
        # §7 V1-3: no implicit trace-type or SAP filter is added — both
        # suffix-matching trace types are in the answer
        assert [row["genealogydata_genealogytracetype"] for row in result["rows"]] == [2, 7]

    elif case == "winter_and_summer_instants":
        rt = make_runtime(served)

        def clocks(timezone, value):
            return asyncio.run(
                rt.query_records(
                    {
                        "dataset": "fixture.clocks",
                        "fields": ["label", "genealogydata_assembleddatetime"],
                        "filters": [
                            {
                                "field": "genealogydata_assembleddatetime",
                                "op": "=",
                                "value": value,
                            }
                        ],
                        "timestamp": {
                            "field": "genealogydata_assembleddatetime",
                            "format": "%Y-%m-%d %H:%M:%S",
                            "timezone": timezone,
                        },
                        "order": [{"field": "label"}],
                        "limit": 10,
                    }
                )
            )

        # §7 V1-4: comparisons run under the DECLARED clock — an equality on
        # a Berlin wall time matches the row at that very instant, on winter
        # and summer dates alike (a lexical compare would also match here;
        # the distinguishing observables are the literal interpretation
        # refusals below — a lexical implementation would compare the strings
        # happily and never refuse a fold/gap literal)
        winter = clocks("Europe/Berlin", "2026-01-15 11:00:00")
        assert [row["label"] for row in winter["rows"]] == ["winter-11"]
        summer = clocks("Europe/Berlin", "2026-07-15 11:00:00")
        assert [row["label"] for row in summer["rows"]] == ["summer-11"]
        none_at_nine_utc = clocks("Europe/Berlin", "2026-01-15 10:00:00")
        assert none_at_nine_utc["rows"] == []  # 10:00 Berlin is 09:00 UTC
        # an ambiguous or nonexistent literal under the declared clock
        # refuses — never a fold/offset guess, never a silent lexical compare
        for literal in ("2026-10-25 02:30:00", "2026-03-29 02:30:00"):
            with pytest.raises(PlannerError) as raised:
                clocks("Europe/Berlin", literal)
            assert raised.value.code == "timestamp_interpretation"
        # the winter/summer normalizations themselves (11:00 Berlin is 10:00
        # UTC in January and 09:00 UTC in July) are the declared
        # interpretation the two DST refusals pin down (the CET/CEST offset
        # rules); the plan §1 zoneinfo/ICU probe is the prerequisite evidence
        # and the plan discloses the interpretation in every response.

    elif case == "ambiguous_fall_back_refuses":
        rt = make_runtime(served)
        request = {**_RECORDS_REQUEST, "dataset": "fixture.dst_ambiguous", "limit": 10}
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.query_records(request))
        refusal = raised.value
        # §7 V1-4: the ambiguous 2026-10-25 02:30:00 refuses explicitly —
        # no fold is guessed, no rows are returned
        assert refusal.code == "timestamp_interpretation"
        assert "ambiguous" in str(refusal) and "fall-back" in str(refusal)
        assert "02:30" not in str(refusal)  # the source value is never dumped
        body = _refusal(refusal)
        assert body["result"] == {"status": "refused", "complete": False, "returned_rows": 0}
        assert body["rows"] == [] and body["persistence"] == {"status": "not_saved"}

    elif case == "nonexistent_spring_forward_refuses":
        rt = make_runtime(served)
        request = {**_RECORDS_REQUEST, "dataset": "fixture.dst_nonexistent", "limit": 10}
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.query_records(request))
        refusal = raised.value
        # §7 V1-4: the nonexistent 2026-03-29 02:30:00 refuses — no offset guess
        assert refusal.code == "timestamp_interpretation"
        assert "nonexistent" in str(refusal) and "spring-forward" in str(refusal)
        assert "02:30" not in str(refusal)
        assert _refusal(refusal)["result"]["complete"] is False

    elif case == "eligible_malformed_refuses":
        rt = make_runtime(served)
        request = {**_RECORDS_REQUEST, "dataset": "fixture.malformed", "limit": 10}
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.query_records(request))
        refusal = raised.value
        # §7 V1-4: a malformed non-null timestamp on an ELIGIBLE row refuses,
        # identifying the field/interpretation without dumping the value
        assert refusal.code == "timestamp_interpretation"
        assert "malformed" in str(refusal)
        assert "genealogydata_assembleddatetime" in str(refusal)
        assert "2026-01-15 11:00" not in str(refusal)
        assert _refusal(refusal)["rows"] == []

    elif case == "ineligible_malformed_never_poisons":
        rt = make_runtime(served)
        request = {**_RECORDS_REQUEST, "dataset": "fixture.poisoned", "limit": 10}
        result = asyncio.run(rt.query_records(request))
        # §7 V1-4: the suffix-INELIGIBLE row's malformed wall time does not
        # poison the eligible answer
        assert _motors(result) == [
            ("motor-A", "synthetic-B/25A"),
            ("motor-B", "synthetic-C/259"),
            ("motor-A", "synthetic-A/253"),
        ]
        assert result["result"]["complete"] is True

    elif case == "helper_named_physical_columns_stay_values":
        # fix pass 1, finding 2: physical columns named exactly like each
        # execution-only helper are ordinary selected values — the correct
        # values return, the completeness indicator stays truthful (all
        # physical has_more values are false while a third row matches) and
        # the echoed columns carry every requested field
        rt = make_runtime(served)
        fields = [
            "__ariadne_record_ts",
            "__ariadne_record_rn",
            "__ariadne_record_has_more",
            "__ariadne_record_base",
            "__ariadne_record_topn",
            "productnumber",
        ]
        result = asyncio.run(
            rt.query_records(
                {
                    "dataset": "fixture.helper_named",
                    "fields": fields,
                    "timestamp": {
                        "field": "__ariadne_record_ts",
                        "format": "%Y-%m-%d %H:%M:%S",
                        "timezone": "Europe/Berlin",
                    },
                    "order": [{"field": "productnumber"}],
                    "limit": 2,
                }
            )
        )
        assert result["columns"] == fields
        assert [row["productnumber"] for row in result["rows"]] == ["motor-A", "motor-B"]
        assert [row["__ariadne_record_ts"] for row in result["rows"]] == [
            "2026-01-15 09:00:00",
            "2026-01-15 11:00:00",
        ]
        assert [row["__ariadne_record_rn"] for row in result["rows"]] == [7, 8]
        assert [row["__ariadne_record_has_more"] for row in result["rows"]] == [False, False]
        assert [row["__ariadne_record_base"] for row in result["rows"]] == ["base-1", "base-2"]
        assert [row["__ariadne_record_topn"] for row in result["rows"]] == ["topn-1", "topn-2"]
        assert result["result"]["has_more_matching"] is True  # the LEAD fact, not the column
        assert result["result"]["returned_rows"] == 2

    elif case == "declared_timestamp_evaluated_without_selection_or_order":
        # fix pass 1, finding 3: the declared interpretation is evaluated on
        # every ELIGIBLE row even when the field is neither selected nor an
        # order key — the malformed eligible value refuses, never a complete
        # answer that silently skipped the interpretation
        rt = make_runtime(served)
        request = {
            "dataset": "fixture.ts_unselected",
            "fields": ["productnumber"],
            "filters": [
                {"field": "genealogydata_tracedata", "op": "regex", "value": "/2[0-9][0-9A-Z]$"}
            ],
            "timestamp": {
                "field": "genealogydata_assembleddatetime",
                "format": "%Y-%m-%d %H:%M:%S",
                "timezone": "Europe/Berlin",
            },
            "order": [{"field": "productnumber"}],
        }
        with pytest.raises(QueryResultError) as raised:
            asyncio.run(rt.query_records(request))
        refusal = raised.value
        assert refusal.code == "timestamp_interpretation"
        assert "malformed" in str(refusal)
        assert "not-a-time" not in str(refusal)  # the source value is never dumped
        assert _refusal(refusal)["rows"] == []

    elif case == "regex_validity_follows_the_duckdb_engine":
        # fix pass 1, finding 4: pattern validity is DuckDB's RE2 judgement,
        # not Python re's — an RE2-valid Unicode class that Python refuses
        # must run, and a Python-valid lookahead that RE2 refuses must be
        # filter_invalid BEFORE result execution
        rt = make_runtime(served)
        result = asyncio.run(
            rt.query_records(
                {
                    "dataset": "fixture.events",
                    "fields": ["productnumber"],
                    "filters": [
                        {"field": "productnumber", "op": "regex", "value": "motor-\\p{Lu}$"}
                    ],
                    "order": [{"field": "productnumber"}],
                    "limit": 3,
                }
            )
        )
        assert [row["productnumber"] for row in result["rows"]] == [
            "motor-A",
            "motor-A",  # e1 and e2 both carry motor-A
            "motor-B",
        ]
        with pytest.raises(PlannerError) as raised:
            asyncio.run(
                rt.query_records(
                    {
                        "dataset": "fixture.events",
                        "fields": ["productnumber"],
                        "filters": [
                            {"field": "productnumber", "op": "regex", "value": "motor-(?=A)"}
                        ],
                        "order": [{"field": "productnumber"}],
                    }
                )
            )
        assert raised.value.code == "filter_invalid"

    elif case == "sub_hour_folds_refuse_like_hour_folds":
        # fix pass 1, finding 5: ambiguity follows the zone's actual fold
        # width — Australia/Lord_Howe repeats 2026-04-05 01:45:00 in a
        # 30-minute fold and must refuse exactly like the ±1-hour Berlin
        # fall-back; an ordinary Lord_Howe wall time still answers
        rt = make_runtime(served)

        def lord_howe(label):
            return asyncio.run(
                rt.query_records(
                    {
                        "dataset": "fixture.lord_howe",
                        "fields": ["label", "wall"],
                        "filters": [{"field": "label", "op": "=", "value": label}],
                        "timestamp": {
                            "field": "wall",
                            "format": "%Y-%m-%d %H:%M:%S",
                            "timezone": "Australia/Lord_Howe",
                        },
                        "order": [{"field": "label"}],
                    }
                )
            )

        with pytest.raises(QueryResultError) as raised:
            lord_howe("fold-0145")
        refusal = raised.value
        assert refusal.code == "timestamp_interpretation"
        assert "ambiguous" in str(refusal) and "fall-back" in str(refusal)
        assert "01:45" not in str(refusal)  # the source value is never dumped
        plain = lord_howe("plain-0300")
        assert [row["label"] for row in plain["rows"]] == ["plain-0300"]
        assert plain["result"]["complete"] is True

    elif case == "uppercase_helper_named_columns_stay_values":
        # fix pass 2: DuckDB resolves identifiers case-insensitively, so
        # UPPERCASE physical columns named like the helper namespace collide
        # with the allocated lowercase helpers — the correct values must
        # return and completeness must stay truthful
        rt = make_runtime(served)
        fields = [
            "__ARIADNE_RECORD_RN",
            "__ARIADNE_RECORD_HAS_MORE",
            "__ARIADNE_RECORD_TS",
            "productnumber",
        ]
        result = asyncio.run(
            rt.query_records(
                {
                    "dataset": "fixture.upcase_named",
                    "fields": fields,
                    "timestamp": {
                        "field": "__ARIADNE_RECORD_TS",
                        "format": "%Y-%m-%d %H:%M:%S",
                        "timezone": "Europe/Berlin",
                    },
                    "order": [{"field": "productnumber"}],
                    "limit": 2,
                }
            )
        )
        assert result["columns"] == fields
        assert [row["productnumber"] for row in result["rows"]] == ["motor-A", "motor-B"]
        assert [row["__ARIADNE_RECORD_RN"] for row in result["rows"]] == [7, 8]
        assert [row["__ARIADNE_RECORD_HAS_MORE"] for row in result["rows"]] == [False, False]
        assert [row["__ARIADNE_RECORD_TS"] for row in result["rows"]] == [
            "2026-01-15 09:00:00",
            "2026-01-15 11:00:00",
        ]
        assert result["result"]["has_more_matching"] is True  # three match, two return
        assert result["result"]["returned_rows"] == 2

    elif case == "unknown_dataset_refuses":
        rt = make_runtime(served)
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records({**_RECORDS_REQUEST, "dataset": "nope.x"}))
        assert raised.value.code == "unknown_dataset"

    elif case == "ambiguous_dataset_refuses":
        rt = make_runtime(served)
        # 'events' names tables in BOTH sources — the request must name the
        # canonical resource of the intended one instead of guessing
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records({**_RECORDS_REQUEST, "dataset": "events"}))
        assert raised.value.code == "ambiguous_dataset"
        assert len(raised.value.candidates) == 2
        for candidate in raised.value.candidates:
            assert candidate.startswith("ariadne://table/")
        # the qualified form resolves deterministically
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 2}))
        assert len(result["rows"]) == 2

    elif case == "unknown_field_refuses":
        rt = make_runtime(served)
        request = {
            **_RECORDS_REQUEST,
            "fields": ["productnumber", "bogus_col"],
        }
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records(request))
        assert raised.value.code == "unknown_field"

    elif case == "sql_shaped_identities_refuse_before_execution":
        rt = make_runtime(served)
        with pytest.raises(PlannerError) as raised:
            asyncio.run(
                rt.query_records({**_RECORDS_REQUEST, "dataset": "events; DROP TABLE events"})
            )
        assert raised.value.code == "unknown_dataset"
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records({**_RECORDS_REQUEST, "fields": ["productnumber OR 1=1"]}))
        assert raised.value.code == "unknown_field"
        # nothing executed: the table is intact and the canonical request
        # still returns its three records
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 10}))
        assert len(result["rows"]) == 3

    elif case == "unknown_request_keys_refuse":
        rt = make_runtime(served)
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records({**_RECORDS_REQUEST, "bogus": 1}))
        assert raised.value.code == "request_invalid"
        with pytest.raises(PlannerError):
            # deliberate wrong type: the refusal is the check
            asyncio.run(rt.query_records("not-a-mapping"))  # pyright: ignore[reportArgumentType]

    elif case == "invalid_regex_refuses":
        rt = make_runtime(served)
        request = {
            **_RECORDS_REQUEST,
            "filters": [{"field": "genealogydata_tracedata", "op": "regex", "value": "("}],
        }
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records(request))
        assert raised.value.code == "filter_invalid"

    elif case == "wrong_types_and_encodings_refuse":
        rt = make_runtime(served)
        ts = _RECORDS_REQUEST["timestamp"]
        attempts = [
            ({**_RECORDS_REQUEST, "limit": True}, "limit_invalid"),  # booleans are not integers
            ({**_RECORDS_REQUEST, "limit": 1.5}, "limit_invalid"),
            ({**_RECORDS_REQUEST, "limit": 0}, "limit_invalid"),
            ({**_RECORDS_REQUEST, "limit": "10"}, "limit_invalid"),
            ({**_RECORDS_REQUEST, "timestamp": {**ts, "format": "%d.%m.%Y"}}, "timestamp_invalid"),
            (
                {**_RECORDS_REQUEST, "timestamp": {**ts, "timezone": "Mars/Olympus"}},
                "timestamp_invalid",
            ),
            # the declared type must carry the documented text encoding
            (
                {
                    **_RECORDS_REQUEST,
                    "timestamp": {**ts, "field": "genealogydata_genealogytracetype"},
                },
                "timestamp_invalid",
            ),
            ({**_RECORDS_REQUEST, "timestamp": {**ts, "field": "bogus"}}, "unknown_field"),
            (
                {**_RECORDS_REQUEST, "timestamp": {"field": ts["field"], "format": ts["format"]}},
                "timestamp_invalid",
            ),
            ({**_RECORDS_REQUEST, "filters": "not-a-list"}, "filter_invalid"),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "sideways", "value": 1}],
                },
                "filter_invalid",
            ),
            # null belongs to a null test, not a comparison
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "=", "value": None}],
                },
                "filter_invalid",
            ),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "is_null", "value": "x"}],
                },
                "filter_invalid",
            ),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "=", "value": {"a": 1}}],
                },
                "filter_invalid",
            ),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "=", "value": float("nan")}],
                },
                "filter_invalid",
            ),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "regex", "value": 42}],
                },
                "filter_invalid",
            ),
            # the retained 100-value IN and 4,096-character ceilings
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [
                        {
                            "field": "productnumber",
                            "op": "in",
                            "value": [f"m{i}" for i in range(101)],
                        }
                    ],
                },
                "filter_invalid",
            ),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [{"field": "productnumber", "op": "=", "value": "x" * 4097}],
                },
                "filter_invalid",
            ),
            (
                {
                    **_RECORDS_REQUEST,
                    "filters": [
                        {
                            "field": "genealogydata_tracedata",
                            "op": "regex",
                            "value": "x" * 4097,
                        }
                    ],
                },
                "filter_invalid",
            ),
            ({**_RECORDS_REQUEST, "order": []}, "order_invalid"),
            (
                {
                    **_RECORDS_REQUEST,
                    "order": [{"field": "productnumber", "direction": "sideways"}],
                },
                "order_invalid",
            ),
            ({**_RECORDS_REQUEST, "order": [{"field": "bogus"}]}, "unknown_field"),
        ]
        for request, code in attempts:
            with pytest.raises(PlannerError) as raised:
                asyncio.run(rt.query_records(request))
            assert raised.value.code == code, (code, raised.value)

    elif case == "excessive_limits_refuse":
        rt = make_runtime(served)
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 1001}))
        assert raised.value.code == "limit_invalid"
        # ≤ the effective host row ceiling: a tightened host refuses 3
        tightened = make_runtime(served, max_rows=2)
        with pytest.raises(PlannerError) as raised:
            asyncio.run(tightened.query_records({**_RECORDS_REQUEST, "limit": 3}))
        assert raised.value.code == "limit_invalid"
        fitting = asyncio.run(tightened.query_records({**_RECORDS_REQUEST, "limit": 2}))
        assert len(fitting["rows"]) == 2

    elif case == "synthetic_session_without_admission_refuses_graph_queries":
        # The private numeric session can answer records from its synthetic
        # registry, but graph queries still require a Git admission.
        rt = make_runtime(served)
        result = asyncio.run(rt.query_records({**_RECORDS_REQUEST, "limit": 2}))
        assert len(result["rows"]) == 2 and result["governed"] is False
        assert rt._graph is None
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_detail({"dataset": "events", "fields": ["productnumber"]}))
        assert raised.value.code == "not_admitted"
        with pytest.raises(PlannerError) as raised:
            asyncio.run(rt.query_metrics({"metrics": ["probe_count"]}))
        assert raised.value.code == "not_admitted"
        # The synthetic implicit attach resolves bare and qualified identities alike.
        synthetic = make_synthetic_db_runtime(served)
        bare = asyncio.run(
            synthetic.query_records({**_RECORDS_REQUEST, "dataset": "events", "limit": 2})
        )
        qualified = asyncio.run(
            synthetic.query_records({**_RECORDS_REQUEST, "dataset": "demo.main.events", "limit": 2})
        )
        assert _motors(bare) == _motors(qualified)

    elif case == "missing_managed_admission_still_refuses":
        # A Git-managed project with no valid admission is refused at the
        # project construction seam.
        bare = tmp_path / "bare_project"
        bare.mkdir()
        with pytest.raises(ValueError) as raised:
            QueryRuntime.open_project(bare)
        assert "no valid admission" in str(raised.value)

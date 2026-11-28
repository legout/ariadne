"""Focused freshness regressions through the shared term resolver."""

import inspect
import json
import pathlib
from datetime import UTC, date, datetime, timedelta, timezone

import yaml

from ariadne import context
from ariadne.cli import _json_default as cli_json_default
from ariadne.context import resolve_term
from ariadne.sources import table_resource

_ABSENT = object()


def _reference_page(stale_after: object = _ABSENT) -> str:
    meta = {
        "type": "reference",
        "title": "Term",
        "description": "A term reference.",
        "tags": ["reference"],
        "sources": [],
        "aliases": ["term concept"],
        "ariadne": {
            "version": 1,
            "reference_role": "term",
            "representations": [
                {
                    "id": "term",
                    "aliases": ["test term"],
                    "fields": [
                        {
                            "resource": table_resource("orders", None, "orders", "orders"),
                            "column": "id",
                        }
                    ],
                    "scope": [],
                }
            ],
            "mappings": [],
        },
    }
    if stale_after is not _ABSENT:
        meta["stale_after"] = stale_after
    frontmatter = yaml.safe_dump(meta, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n# Term\n"


def _resolve_freshness(
    tmp_path,
    stale_after: object = _ABSENT,
    *,
    monkeypatch,
    now=datetime(2026, 10, 7, 12, 0, tzinfo=UTC),
) -> dict:
    root = tmp_path / "context_layer"
    page = root / "references" / "term.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(_reference_page(stale_after), encoding="utf-8")
    before = page.read_bytes()
    monkeypatch.setattr(context, "_assessment_now", lambda: now)
    [match] = resolve_term([(root, False)], "test term")["matches"]
    assert page.read_bytes() == before
    return match["freshness"]


def test_explicit_offset_expiry_is_stale_at_the_exact_instant(tmp_path, monkeypatch):
    """At 12:00Z, the stated 14:00+02:00 expiry is exactly reached (spec §3)."""
    expiry = "2026-10-07T14:00:00+02:00"
    assert _resolve_freshness(tmp_path, expiry, monkeypatch=monkeypatch) == {
        "stale_after": expiry,
        "state": "stale",
    }


def test_equivalent_expiry_offsets_agree_and_future_instants_are_current(tmp_path, monkeypatch):
    """Equivalent expressed offsets name one instant; a later instant is current."""
    equivalent = [
        "2026-10-07T12:00:00Z",
        "2026-10-07T14:00:00+02:00",
        "2026-10-07T07:00:00-05:00",
    ]
    results = [
        _resolve_freshness(tmp_path, expiry, monkeypatch=monkeypatch) for expiry in equivalent
    ]
    assert [result["state"] for result in results] == ["stale"] * 3
    assert [result["stale_after"] for result in results] == equivalent
    assert _resolve_freshness(tmp_path, "2026-10-07T12:00:01Z", monkeypatch=monkeypatch) == {
        "stale_after": "2026-10-07T12:00:01Z",
        "state": "current",
    }


def test_native_yaml_datetime_and_legacy_date_boundaries(tmp_path, monkeypatch):
    """Native datetime is instant-based; date-only expiry lasts through its UTC day."""
    exact_native_datetime = datetime(2026, 10, 7, 14, 0, tzinfo=timezone(timedelta(hours=2)))
    assert _resolve_freshness(tmp_path, exact_native_datetime, monkeypatch=monkeypatch) == {
        "stale_after": "2026-10-07T14:00:00+02:00",
        "state": "stale",
    }
    for expiry in ("2026-10-07", date(2026, 10, 7)):
        assert _resolve_freshness(tmp_path, expiry, monkeypatch=monkeypatch) == {
            "stale_after": "2026-10-07",
            "state": "current",
        }

    next_midnight = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
    for expiry in ("2026-10-07", date(2026, 10, 7)):
        assert _resolve_freshness(tmp_path, expiry, now=next_midnight, monkeypatch=monkeypatch) == {
            "stale_after": "2026-10-07",
            "state": "stale",
        }


def test_naive_malformed_and_absent_expiry_stay_unknown(tmp_path, monkeypatch):
    """Ambiguous, invalid and missing expiry values never imply freshness."""
    assert _resolve_freshness(tmp_path, datetime(2026, 10, 7, 12, 0), monkeypatch=monkeypatch) == {
        "stale_after": "2026-10-07T12:00:00",
        "state": "unknown",
    }
    assert _resolve_freshness(tmp_path, "not-an-ISO-expiry", monkeypatch=monkeypatch) == {
        "stale_after": "not-an-ISO-expiry",
        "state": "unknown",
    }
    assert _resolve_freshness(tmp_path, monkeypatch=monkeypatch) == {
        "stale_after": None,
        "state": "unknown",
    }


# --------------- the additive context_signals envelope (spec 0011 §§4–5) ----


def _write(root_rel: str, text: str, tmp_path) -> pathlib.Path:
    page = tmp_path / "context_layer" / root_rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")
    return page


# The classic served-tree envelope/search legs (search_pages hit envelopes,
# navigation files, warning codes, verification tiers over served hits,
# metric_context over served trees, unsupported optional evidence through the
# hit serializer) are DELETED with their exclusively-retired surface (C6 G3,
# spec0035 section 6): `context.search_pages`/`context.metric_context` are
# removed. The live verification/freshness disclosure semantics ride the Core
# disclosure assembly (`_page_view`/`_context_signals`) exercised through the
# native query journeys (see the context_signals views in the admitted
# multi-fact journeys and node 1/2).


def test_term_match_carries_the_envelope_and_serializes_through_the_json_adapter(
    tmp_path, monkeypatch
):
    """§4: every term-resolution match receives its Reference's envelope, and
    every value — including YAML-native evidence dates — serializes through the
    existing CLI JSON adapter (AC8: no adapter change, no new schema)."""
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(context, "_assessment_now", lambda: now)
    meta = yaml.safe_load(_reference_page().split("---")[1])
    meta["stale_after"] = "2026-10-07T11:00:00Z"
    meta["generated"] = {"by": "ariadne-author", "at": date(2026, 1, 1)}
    meta["verified"] = [{"by": "human:volker", "at": date(2026, 1, 2)}]
    front = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False).strip()
    _write("references/term.md", f"---\n{front}\n---\n\n# Term\n", tmp_path)
    [match] = resolve_term([(tmp_path / "context_layer", False)], "test term")["matches"]
    signals = match["context_signals"]
    assert signals["pages"][0]["path"] == "references/term.md"
    assert signals["pages"][0]["verification_tier"] == "human-reviewed"
    assert signals["pages"][0]["generated"]["at"] == "2026-01-01"
    assert signals["pages"][0]["verified"] == [{"by": "human:volker", "at": "2026-01-02"}]
    assert signals["warnings"] == [{"code": "context_stale", "path": "references/term.md"}]
    # the existing CLI adapter serializes the whole match, dates included
    json.dumps(match, default=cli_json_default)


def _tier(tmp_path, monkeypatch, verified, generated=_ABSENT, generated_map=None) -> str:
    monkeypatch.setattr(context, "_assessment_now", lambda: datetime(2026, 10, 7, tzinfo=UTC))
    meta = yaml.safe_load(_reference_page().split("---")[1])
    if generated is not _ABSENT:
        meta["generated"] = {"by": "ariadne-author", "at": generated}
    if generated_map is not None:
        meta["generated"] = generated_map
    meta["verified"] = verified
    front = yaml.safe_dump(meta, sort_keys=False).strip()
    _write("references/term.md", f"---\n{front}\n---\n\n# Term\n", tmp_path)
    [match] = resolve_term([(tmp_path / "context_layer", False)], "test term")["matches"]
    return match["context_signals"]["pages"][0]["verification_tier"]


def test_verification_tier_counts_only_events_current_since_generation(tmp_path, monkeypatch):
    """OKF v0.3 §5.3: a confirmation older than generated.at is stale (issue #214)."""
    human = {"by": "human:volker", "at": "2026-06-25T09:00:00Z"}
    gen = "2026-06-26T00:00:00Z"
    tier = lambda *a, **k: _tier(tmp_path, monkeypatch, *a, **k)  # noqa: E731
    # (a) human review predates regeneration -> not human-reviewed
    assert tier([human], gen) == "unverified"
    # (f) current process event + stale human event -> machine-confirmed
    process = {"by": "process:lint", "at": "2026-06-27T00:00:00Z"}
    assert tier([human, process], gen) == "machine-confirmed"
    # (b) a later human event -> human-reviewed
    assert tier([human, {"by": "human:ann", "at": "2026-06-27"}], gen) == "human-reviewed"
    # (c) no generated -> any human event counts
    assert tier([human]) == "human-reviewed"
    # (d) date-only generated.at is the start of that UTC day
    assert tier([{"by": "human:volker", "at": "2026-06-26T00:00:00Z"}], "2026-06-26") == (
        "human-reviewed"
    )
    # (e) events lacking at / unparsable at are ignored
    assert tier([{"by": "human:volker"}, {"by": "human:x", "at": "soon"}], gen) == "unverified"
    # a declared generated with missing / unparsable / naive at waives nothing
    fresh = {"by": "human:ann", "at": "2026-06-27T12:00:00Z"}
    for bad in ({}, {"at": "unknown"}, {"at": "2026-06-26T00:00:00"}):
        meta_gen = {"by": "ariadne-author", **bad}
        assert _tier(tmp_path, monkeypatch, [fresh], _ABSENT, meta_gen) == "unverified"
    # a declared non-mapping generated (scalar date / string) has no established time
    for scalar in (date(2026, 6, 27), "2026-06-27"):
        for ev in ("2026-06-26T00:00:00Z", "2026-06-28T00:00:00Z"):
            event = {"by": "human:ann", "at": ev}
            assert _tier(tmp_path, monkeypatch, [event], _ABSENT, scalar) == "unverified"
    # verification timestamps: seconds required, lowercase t/z accepted
    assert tier([{"by": "human:x", "at": "2026-06-27T12:00Z"}], gen) == "unverified"
    assert tier([{"by": "human:x", "at": "2026-06-27t12:00:00z"}], gen) == "human-reviewed"
    # YAML-native datetime and date values behave the same as quoted ones
    native = {"by": "human:volker", "at": datetime(2026, 6, 27, tzinfo=UTC)}
    assert tier([native], date(2026, 6, 26)) == "human-reviewed"


def test_revision1_native_context_never_reads_classic_computation(tmp_path):
    """C6: a frozen revision-1 SDK view cannot acquire classic attestation signals."""
    from lumio_wiki.ariadne_context import (
        ContextBinding,
        ContextIdentity,
        ContextPageView,
        ContextSnapshot,
    )
    from lumio_wiki.records import AriadneMetricReference

    from ariadne.lumio_context import metric_context

    classic = tmp_path / "context_layer"
    (classic / "computations").mkdir(parents=True)
    (classic / "computations/revenue.md").write_text(
        "---\ntype: computation\nattestation: pending\n---\n\nRetired computation.\n",
        encoding="utf-8",
    )
    page = ContextPageView(
        namespace="urn:uuid:context-signals",
        entity_id="entity:revenue",
        kind="metric",
        path="metrics/revenue.md",
        content="# Revenue\n",
        body="# Revenue\n",
        body_start_line=1,
        native={"type": "metric", "title": "Revenue", "sources": []},
        sources=(),
        published_version="published-1",
        citation="exact-pinned-native-citation",
    )
    snapshot = ContextSnapshot(
        identity=ContextIdentity(
            page.namespace, 1, page.published_version, "a" * 64, "b" * 64, "c" * 64
        ),
        pages=(page,),
        bindings=(ContextBinding(page.entity_id, AriadneMetricReference("sales", "revenue"), ()),),
    )
    result = metric_context(
        snapshot, {"selector": {}, "digest": "d" * 64}, classic, "sales", "revenue"
    )
    assert [entry["path"] for entry in result["context_signals"]["pages"]] == ["metrics/revenue.md"]
    assert "attestation" not in result and "governed_note" not in result
    assert result["bound_release"] == "d" * 64
    assert [entry["citation"] for entry in result["citations"]] == ["exact-pinned-native-citation"]


def test_public_surface_exposes_no_clock_parameter_or_clock_api():
    """Issue #48 fix pass, interface rule (spec 0011 §2 / issues #47–#48):
    the assessment clock is an internal seam only. The live public advisory
    operations (the kept resolver family and the pinned data-signal view; the
    classic served-tree entry retired with C6) carry no clock parameter, and
    the module surface gains no public callable that drives the clock (tests
    freeze time on ``context._assessment_now``)."""
    for fn in (resolve_term, context.data_signals_pinned):
        clockish = [
            name
            for name in inspect.signature(fn).parameters
            if "now" in name.lower() or "clock" in name.lower()
        ]
        assert clockish == [], f"{fn.__name__} leaks a clock parameter: {clockish}"
    public_clock = sorted(
        name
        for name in vars(context)
        if not name.startswith("_")
        and callable(getattr(context, name))
        and ("now" in name.lower() or "clock" in name.lower())
    )
    assert public_clock == [], f"public clock API on ariadne.context: {public_clock}"

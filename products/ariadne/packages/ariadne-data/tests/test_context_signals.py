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


def test_public_surface_exposes_no_clock_parameter_or_clock_api():
    """Issue #48 fix pass, interface rule (spec 0011 §2 / issues #47–#48):
    the assessment clock is an internal seam only. The live public advisory
    operations (the kept resolver family and the pinned/classic data-signal
    views) carry no clock parameter, and the module surface gains no public
    callable that drives the clock (tests freeze time on
    ``context._assessment_now``)."""
    for fn in (resolve_term, context.data_signals, context.data_signals_pinned):
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

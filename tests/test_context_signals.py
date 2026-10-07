"""Focused freshness regressions through the shared term resolver."""

from datetime import UTC, date, datetime, timedelta, timezone

import yaml

from ariadne import context
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

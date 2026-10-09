"""Focused freshness regressions through the shared term resolver."""

import inspect
import json
import pathlib
from datetime import UTC, date, datetime, timedelta, timezone

import yaml

from ariadne import context
from ariadne.cli import _json_default as cli_json_default
from ariadne.context import metric_context, resolve_term, search_pages
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


def _write(root_rel: str, text: str, tmp_path) -> "pathlib.Path":
    page = tmp_path / "context_layer" / root_rel
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(text, encoding="utf-8")
    return page


def test_search_hit_carries_its_page_envelope_and_reads_nothing_else(tmp_path, monkeypatch):
    """§4: each hit carries its page's advisory view; absent optional evidence
    stays null/unknown without a warning, and the read stays byte-identical
    (§8 AC9: assessments are read-only)."""
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(context, "_assessment_now", lambda: now)
    page = _write(
        "policies/plain.md",
        "---\ntype: policy\ntitle: Plain\ndescription: A plain rule.\n---\n\n"
        "# Plain\n\nA plain rule.\n",
        tmp_path,
    )
    root = tmp_path / "context_layer"
    before = page.read_bytes()
    [hit] = search_pages("plain rule", 5, [(root, False)])
    assert hit["context_signals"] == {
        "pages": [
            {
                "path": "policies/plain.md",
                "status": "stable",  # absent status on a readable concept: OKF default
                "freshness": {"stale_after": None, "state": "unknown"},
                "verification_tier": "unverified",
                "generated": None,
                "verified": None,
                "sources": [],
            }
        ],
        "warnings": [],
    }
    assert page.read_bytes() == before


def test_navigation_file_hit_never_becomes_a_concept(tmp_path):
    """§4: a reserved navigation file without concept frontmatter stays
    unknown and acquires no invented verification evidence."""
    _write("index.md", "# Context Layer\n\n* [Policies](policies/) - the rules\n", tmp_path)
    [hit] = search_pages("policies rules", 5, [(tmp_path / "context_layer", False)])
    view = hit["context_signals"]["pages"][0]
    assert view["path"] == "index.md"
    assert view["status"] == "unknown"  # no concept frontmatter: no stable default
    assert view["freshness"] == {"stale_after": None, "state": "unknown"}
    assert view["verification_tier"] == "unverified"
    assert view["generated"] is None and view["verified"] is None and view["sources"] == []
    assert hit["context_signals"]["warnings"] == []


def test_search_warns_only_for_the_two_concrete_codes(tmp_path, monkeypatch):
    """§5: exactly a reached supported expiry (context_stale) and an explicitly
    declared deprecated status (context_deprecated) warn; malformed optional
    values never warn and never become fabricated evidence."""
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(context, "_assessment_now", lambda: now)
    _write(
        "policies/expired.md",
        "---\ntype: policy\nstale_after: '2026-10-07T11:00:00Z'\n---\n\n# Expired\n",
        tmp_path,
    )
    _write(
        "policies/sunset.md",
        "---\ntype: policy\nstatus: deprecated\n---\n\n# Sunset\n",
        tmp_path,
    )
    _write(
        "policies/broken.md",
        "---\ntype: policy\nstatus: [not, a, string]\nverified: seed-notes\n"
        "stale_after: eventually\n---\n\n# Broken\n",
        tmp_path,
    )
    hits = {
        hit["path"]: hit["context_signals"]
        for hit in search_pages("policy", 10, [(tmp_path / "context_layer", False)])
    }
    assert hits["policies/expired.md"]["warnings"] == [
        {"code": "context_stale", "path": "policies/expired.md"}
    ]
    assert hits["policies/sunset.md"]["warnings"] == [
        {"code": "context_deprecated", "path": "policies/sunset.md"}
    ]
    broken = hits["policies/broken.md"]
    assert broken["warnings"] == []  # malformed optional metadata is not a §5 problem
    view = broken["pages"][0]
    assert view["status"] == "unknown"
    assert view["verification_tier"] == "unverified" and view["verified"] is None
    assert view["freshness"] == {"stale_after": "eventually", "state": "unknown"}


def test_verification_tiers_follow_only_usable_confirmations(tmp_path):
    """§4: tiers derive conservatively from usable document verification
    declarations — an empty list is unverified, machine confirmations are
    machine-confirmed, a declared human: actor is human-reviewed — and
    YAML-native evidence dates disclose as ISO strings."""
    _write(
        "references/none.md",
        "---\ntype: reference\nverified: []\n---\n\n# None\n",
        tmp_path,
    )
    _write(
        "references/machine.md",
        "---\ntype: reference\nverified:\n  - {by: ci-runner, at: '2026-01-01T00:00:00Z'}\n"
        "---\n\n# Machine\n",
        tmp_path,
    )
    _write(
        "references/human.md",
        "---\ntype: reference\nverified:\n  - {by: ci-runner, at: 2026-01-01 00:00:00}\n"
        "  - {by: human:volker, at: 2026-01-02 00:00:00}\n---\n\n# Human\n",
        tmp_path,
    )
    views = {
        hit["path"]: hit["context_signals"]["pages"][0]
        for hit in search_pages("reference", 10, [(tmp_path / "context_layer", False)])
    }
    assert views["references/none.md"]["verification_tier"] == "unverified"
    assert views["references/none.md"]["verified"] == []
    assert views["references/machine.md"]["verification_tier"] == "machine-confirmed"
    assert views["references/human.md"]["verification_tier"] == "human-reviewed"
    assert views["references/human.md"]["verified"][1]["at"] == "2026-01-02T00:00:00"


def test_missing_optional_computation_never_warns_or_fails(tmp_path, monkeypatch):
    """§5: an absent optional computation is no query failure and no
    required-context warning — it simply stays outside the consumed set."""
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(context, "_assessment_now", lambda: now)
    root = tmp_path / "context_layer"
    _write(
        "metrics/margin.md",
        "---\ntype: metric\nsources:\n  - {id: p, resource: policies/p.md}\n---\n\n# Margin\n",
        tmp_path,
    )
    _write("policies/p.md", "---\ntype: policy\n---\n\n# P\n", tmp_path)
    result = metric_context(root, "margin")
    assert result["metric_page"] and len(result["policies"]) == 1
    assert [page["path"] for page in result["context_signals"]["pages"]] == [
        "metrics/margin.md",
        "policies/p.md",
    ]
    assert result["context_signals"]["warnings"] == []
    assert "attestation" not in result


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
    the assessment clock is an internal seam only. The public context
    operations keep their base signatures — metric_context stays exactly
    (context_dir, name) — and the module surface gains no public callable
    that drives the clock (a prior settled finding removed a public ``_now``
    for exactly this; tests freeze time on ``context._assessment_now``)."""
    assert list(inspect.signature(metric_context).parameters) == ["context_dir", "name"]
    for fn in (metric_context, resolve_term, search_pages):
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


def test_unsupported_optional_evidence_degrades_and_stays_serializable(tmp_path, monkeypatch):
    """Issue #48 fix pass: a readable page whose optional evidence carries
    YAML-native objects outside the JSON contract (!!set, !!binary) serialized
    fine before the signals view existed. The advisory view must degrade that
    optional field to its absent form (generated/verified -> null) instead of
    emitting non-serializable objects, keep assessing the rest of the page,
    fabricate no warning from the malformed evidence, and the whole hit must
    serialize through the unchanged existing CLI adapter."""
    now = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(context, "_assessment_now", lambda: now)
    root = tmp_path / "context_layer"
    _write(
        "references/native.md",
        "---\n"
        "type: reference\n"
        "stale_after: '2026-10-07T11:00:00Z'\n"
        "generated: {tool: !!set {legacy-exporter}}\n"
        "verified:\n"
        "  - {by: ci-runner, at: 2026-01-01 00:00:00}\n"
        "  - {by: human:volker, badge: !!binary aGVsbG8=}\n"
        "---\n\n# Native\n",
        tmp_path,
    )
    [hit] = search_pages("native", 10, [(root, False)])
    json.dumps(hit, default=cli_json_default)  # the existing CLI serializer path
    view = hit["context_signals"]["pages"][0]
    assert view["path"] == "references/native.md"
    assert view["generated"] is None  # unsupported evidence degrades to absent
    assert view["verified"] is None
    assert view["freshness"] == {"stale_after": "2026-10-07T11:00:00Z", "state": "stale"}
    # the tier follows the declared actor (settled §4 rule, pinned by the
    # dedicated tier test); the degraded evidence FIELD is the payload view
    assert view["verification_tier"] == "human-reviewed"
    assert hit["context_signals"]["warnings"] == [
        {"code": "context_stale", "path": "references/native.md"}
    ]  # the well-formed expiry still warns; the malformed evidence adds nothing

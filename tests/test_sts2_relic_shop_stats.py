"""Tests for the STS2 relic Shop Stats parser / snapshot builder.

The source is the Untapped relic page "Shop Stats" section rendered as
StatCells (Bought %, offered N times, Act/Run Winrate deltas).  Event /
Starter / Ancient pages render no such section, and data-insufficient
pages render only skeleton cells.  All fixtures are synthetic.
"""

import json

from scripts.sts2_relic_shop_stats import (
    SHOP_STATUS_FETCH_OR_PARSE_ERROR,
    SHOP_STATUS_INSUFFICIENT,
    SHOP_STATUS_MISSING_FROM_CATALOG,
    SHOP_STATUS_NO_SHOP_STATS,
    SHOP_STATUS_VALID,
    build_relic_shop_snapshot,
    completion_ledger_complete,
    completion_report,
    parse_relic_shop_html,
    parse_relic_shop_page,
    sample_distribution,
    shop_completion_counts,
    validate_relic_shop_snapshot,
)

RELICS = [
    {"id": "BELT_BUCKLE", "name": "腰带扣", "name_en": "Belt Buckle", "tier": "Shop"},
    {"id": "AKABEKO", "name": "赤牛", "name_en": "Akabeko", "tier": "Uncommon"},
    {"id": "AMETHYST_AUBERGINE", "name": "紫水晶茄子", "name_en": "Amethyst Aubergine", "tier": "Common"},
    {"id": "BLACK_BLOOD", "name": "黑血", "name_en": "Black Blood", "tier": "Starter"},
    {"id": "BIG_MUSHROOM", "name": "大蘑菇", "name_en": "Big Mushroom", "tier": "Event"},
    {"id": "QUANTUM_LOOP", "name": "量子回路", "name_en": "Quantum Loop", "tier": "Ancient"},
]


def cell(act, bought=None, offered=None, act_win=None, run_win=None, warn=False):
    offered_html = (
        f'<span class="X__offered">offered {offered:,} times</span>'
        if offered is not None
        else ""
    )
    content = ""
    if warn:
        content = '<div class="X__lowData">Insufficient Data</div>'
    elif bought is not None:
        content += (
            '<div class="X__dataRow"><div class="X__pickRate">'
            f"<span>Bought</span><strong>{bought}%</strong></div>"
            '<div class="X__winRates">'
        )
        if act_win is not None:
            content += (
                '<div class="W__winRate"><span>Act Winrate</span>'
                f'<div class="W__win"><strong>{act_win:+d}%</strong></div></div>'
            )
        if run_win is not None:
            content += (
                '<div class="W__winRate"><span>Run Winrate</span>'
                f'<div class="W__win"><strong>{run_win:+d}%</strong></div></div>'
            )
        content += "</div></div>"
    return (
        f'<div class="StatCell__cell">'
        f'<div class="StatCell__header"><span class="StatCell__label">In Act {act}</span>'
        f'{offered_html}</div><div class="StatCell__content">{content}</div></div>'
    )


def shop_page(name, tier, cells_html, no_section=False):
    section = ""
    if not no_section:
        section = (
            "<section><h2>"
            f"{name} <span>Shop</span> Stats"
            "</h2><div class='StatsSection__container'>"
            f"{cells_html}</div></section>"
        )
    return f"<html><body>{section}</body></html>"


def test_parse_relic_shop_html_extracts_three_acts():
    html = shop_page(
        "Belt Buckle",
        "Shop",
        cell(1, bought=5, offered=34000, act_win=2, run_win=4)
        + cell(2, bought=10, offered=21000, act_win=3, run_win=3)
        + cell(3, bought=22, offered=11000, act_win=-1, run_win=2),
    )
    parsed = parse_relic_shop_html(html)
    assert list(parsed) == ["act_1", "act_2", "act_3"]
    assert parsed["act_1"]["offered"] == 34000
    assert parsed["act_1"]["purchase_rate"]["value"] == 5.0
    assert parsed["act_1"]["run_win_rate_impact"]["value"] == 4.0
    assert parsed["act_1"]["act_win_rate_impact"]["value"] == 2.0
    assert parsed["act_3"]["purchase_rate"]["value"] == 22.0


def test_parse_relic_shop_html_omits_unrendered_cells_without_zero_fill():
    html = shop_page(
        "Amethyst Aubergine",
        "Common",
        cell(1, offered=900)
        + cell(2)  # skeleton: label only, no Bought
        + cell(3, bought=1, offered=40),
    )
    parsed = parse_relic_shop_html(html)
    assert "offered" in parsed["act_1"]
    assert "purchase_rate" not in parsed["act_1"]
    assert parsed["act_2"] == {}
    assert parsed["act_3"]["purchase_rate"]["value"] == 1.0
    assert parsed["act_3"]["offered"] == 40


def test_parse_relic_shop_html_ignores_pages_without_shop_section():
    assert parse_relic_shop_html(shop_page("Black Blood", "Starter", "", no_section=True)) == {}
    assert parse_relic_shop_html(shop_page("Quantum Loop", "Ancient", "", no_section=True)) == {}


def test_build_snapshot_keeps_only_parsed_shop_rows():
    parsed = {
        "BELT_BUCKLE": {
            "act_1": {"offered": 34000, "purchase_rate": {"value": 5.0}},
        }
    }
    snapshot = build_relic_shop_snapshot(
        RELICS, parsed, collected_at="2026-09-07T00:00:00Z"
    )
    validate_relic_shop_snapshot(snapshot)
    assert snapshot["game"] == "sts2"
    entry = snapshot["relics"]["BELT_BUCKLE"]
    assert entry["name_en"] == "Belt Buckle"
    assert entry["tier"] == "Shop"
    assert entry["shop"]["act_1"]["offered"] == 34000
    assert "AMETHYST_AUBERGINE" not in snapshot["relics"]


def test_sample_distribution_reports_min_median_max_and_empty():
    snapshot = build_relic_shop_snapshot(
        RELICS,
        {
            "BELT_BUCKLE": {
                "act_1": {"offered": 34000, "purchase_rate": {"value": 5.0}},
                "act_2": {"offered": 21000, "purchase_rate": {"value": 10.0}},
                "act_3": {"offered": 11000, "purchase_rate": {"value": 22.0}},
            },
            "AKABEKO": {
                "act_1": {"offered": 9000, "purchase_rate": {"value": 3.0}},
            },
        },
        collected_at="2026-09-07T00:00:00Z",
    )
    dist = sample_distribution(snapshot)
    assert dist["act_samples"] == [34000, 21000, 11000, 9000]
    assert dist["min"] == 9000
    assert dist["median"] == 16000.0
    assert dist["max"] == 34000
    assert dist["shop_eligible"] == 3
    assert dist["entries_with_data"] == 2
    assert dist["entries_without_rendered_data"] == 1


def test_build_snapshot_reports_unknown_parsed_relic():
    snapshot = build_relic_shop_snapshot(
        RELICS, {"NOT_A_RELIC": {"act_1": {"offered": 1}}},
        collected_at="2026-09-07T00:00:00Z",
    )
    assert any(
        row["id"] == "NOT_A_RELIC"
        and row["status"] == SHOP_STATUS_MISSING_FROM_CATALOG
        for row in snapshot["unresolved"]
    )


def flight_shop_page(cell_props):
    """Wrap Shop Stats flight cells in a synthetic RSC script payload."""
    body = "".join(
        json.dumps(props).replace("\\", "\\\\").replace('"', '\\"')
        for props in cell_props
    )
    return (
        "<html><body><script>self.__next_f.push([1,\"prefix"
        + body
        + 'suffix"])</script></body></html>'
    )


def flight_cell(act, data_state, children, offered="offered 34,000 times"):
    return {
        "label": f"In Act {act}",
        "offered": offered,
        "dataState": data_state,
        "children": [children],
    }


def test_parse_relic_shop_page_classifies_valid_markup():
    html = shop_page(
        "Belt Buckle",
        "Shop",
        cell(1, bought=5, offered=34000, act_win=2, run_win=4)
        + cell(2, bought=10, offered=21000)
        + cell(3, bought=22, offered=11000),
    )
    parsed = parse_relic_shop_page(html)
    assert parsed["panel"] is True
    assert parsed["states"] == {"act_1": "ok", "act_2": "ok", "act_3": "ok"}
    assert parsed["rows"]["act_1"]["offered"] == 34000


def test_parse_relic_shop_page_classifies_insufficient_markup():
    html = shop_page(
        "Amethyst Aubergine",
        "Common",
        cell(1, warn=True) + cell(2, warn=True) + cell(3, warn=True),
    )
    parsed = parse_relic_shop_page(html)
    assert parsed["panel"] is True
    assert parsed["states"] == {
        "act_1": "insufficient",
        "act_2": "insufficient",
        "act_3": "insufficient",
    }
    assert parsed["rows"] == {}


def test_parse_relic_shop_page_no_section_is_not_a_panel():
    assert parse_relic_shop_page(shop_page("Black Blood", "Starter", "", no_section=True)) == {
        "panel": False,
        "states": {},
        "rows": {},
    }


def test_parse_relic_shop_page_uses_flight_data_state():
    ok_html = flight_shop_page(
        [
            flight_cell(1, "ok", "Bought 5 % Act Winrate+2% Run Winrate+4%"),
            flight_cell(2, "ok", "Bought 10 % Act Winrate+3%"),
            flight_cell(3, "ok", "Bought 22 % Run Winrate+2%"),
        ]
    )
    parsed = parse_relic_shop_page(ok_html)
    assert parsed["panel"] is True
    assert parsed["states"]["act_2"] == "ok"
    assert parsed["rows"]["act_1"]["purchase_rate"]["value"] == 5.0

    low_html = flight_shop_page(
        [
            flight_cell(1, "insufficient", "Bought 0 %"),
            flight_cell(2, "insufficient", "Bought 38 %"),
            flight_cell(3, "insufficient", "Insufficient Data"),
        ]
    )
    parsed = parse_relic_shop_page(low_html)
    assert parsed["panel"] is True
    assert parsed["states"] == {
        "act_1": "insufficient",
        "act_2": "insufficient",
        "act_3": "insufficient",
    }
    assert parsed["rows"] == {}


def test_parse_relic_shop_page_ignores_other_panels_with_act_cells():
    html = flight_shop_page(
        [
            {
                "label": "In Act 2",
                "offered": "offered 46,000 times",
                "dataState": "ok",
                "children": ["Picked 24 % Act Winrate+2% Run Winrate+1%"],
            }
        ]
    )
    parsed = parse_relic_shop_page(html)
    assert parsed == {"panel": False, "states": {}, "rows": {}}


def test_build_snapshot_classifies_insufficient_and_no_shop_stats():
    outcomes = {
        "BELT_BUCKLE": {
            "panel": True,
            "states": {"act_1": "ok"},
            "rows": {
                "act_1": {
                    "offered": 34000,
                    "purchase_rate": {"value": 5.0, "unit": "percent"},
                }
            },
        },
        "AKABEKO": {
            "panel": True,
            "states": {"act_1": "insufficient"},
            "rows": {},
        },
        "AMETHYST_AUBERGINE": {"panel": False, "states": {}, "rows": {}},
    }
    snapshot = build_relic_shop_snapshot(
        RELICS, outcomes, collected_at="2026-09-07T00:00:00Z"
    )
    validate_relic_shop_snapshot(snapshot)
    assert set(snapshot["relics"]) == {"BELT_BUCKLE"}
    statuses = {
        row["id"]: row["status"] for row in snapshot["unresolved"]
    }
    assert statuses["AKABEKO"] == SHOP_STATUS_INSUFFICIENT
    assert statuses["AMETHYST_AUBERGINE"] == SHOP_STATUS_NO_SHOP_STATS
    assert completion_ledger_complete(snapshot)
    assert "insufficient" not in json.dumps(snapshot["relics"])


def test_build_snapshot_preserves_fetch_or_parse_errors():
    outcomes = {
        "BELT_BUCKLE": {"error": "http_404"},
        "AKABEKO": {
            "panel": True,
            "states": {"act_1": "ok"},
            "rows": {"act_1": {"offered": 19000}},
        },
        "AMETHYST_AUBERGINE": {"error": "page_not_cached_offline"},
    }
    snapshot = build_relic_shop_snapshot(
        RELICS, outcomes, collected_at="2026-09-07T00:00:00Z"
    )
    validate_relic_shop_snapshot(snapshot)
    assert "BELT_BUCKLE" not in snapshot["relics"]
    assert "AMETHYST_AUBERGINE" not in snapshot["relics"]
    by_id = {row["id"]: row for row in snapshot["unresolved"]}
    assert by_id["BELT_BUCKLE"]["status"] == SHOP_STATUS_FETCH_OR_PARSE_ERROR
    assert by_id["BELT_BUCKLE"]["reason"] == "http_404"
    assert by_id["AMETHYST_AUBERGINE"]["reason"] == "page_not_cached_offline"
    assert completion_ledger_complete(snapshot)


def test_four_status_counts_cover_every_shop_eligible_relic():
    outcomes = {
        "BELT_BUCKLE": {
            "panel": True,
            "states": {"act_1": "ok", "act_2": "ok", "act_3": "ok"},
            "rows": {
                f"act_{act}": {"offered": 1000 * act}
                for act in (1, 2, 3)
            },
        },
        "AKABEKO": {"panel": True, "states": {"act_1": "insufficient"}, "rows": {}},
        "AMETHYST_AUBERGINE": {"panel": False, "states": {}, "rows": {}},
    }
    snapshot = build_relic_shop_snapshot(
        RELICS, outcomes, collected_at="2026-09-07T00:00:00Z"
    )
    counts = shop_completion_counts(snapshot)
    assert counts[SHOP_STATUS_VALID] == 1
    assert counts[SHOP_STATUS_INSUFFICIENT] == 1
    assert counts[SHOP_STATUS_NO_SHOP_STATS] == 1
    assert counts.get(SHOP_STATUS_FETCH_OR_PARSE_ERROR, 0) == 0
    assert sum(counts.values()) == len(snapshot["shop_eligible_ids"])
    report = completion_report(snapshot)
    assert report["ledger_complete"] is True
    assert report["valid"] == 1
    assert report["relics_with_all_three_act_data"] == 1
    assert report["offered_by_act"]["act_1"]["min"] == 1000


def test_validator_rejects_unknown_unresolved_status():
    snapshot = build_relic_shop_snapshot(
        RELICS,
        {"BELT_BUCKLE": {"panel": True, "states": {}, "rows": {}}},
        collected_at="2026-09-07T00:00:00Z",
    )
    snapshot["unresolved"][0]["status"] = "not_a_real_status"
    try:
        validate_relic_shop_snapshot(snapshot)
    except ValueError as exc:
        assert "unexpected status" in str(exc)
    else:
        raise AssertionError("validator must reject unknown statuses")

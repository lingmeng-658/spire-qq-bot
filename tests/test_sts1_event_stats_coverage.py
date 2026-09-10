"""STS1 Event Stats full-coverage closure tests (52 catalog events).

Covers the coverage invariant (every player-visible choice is either mapped or
explicitly exempted, never silently missing), the cross-act aggregation rules,
and real-draft smokes for the required target events.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from card_guess.event_interaction import (
    STS1_PLAYABLE_EVENT_IDS,
    STS1_UNSUPPORTED_EVENT_IDS,
)
from card_guess.events import get_event, load_events
from card_guess.event_presentation import build_event_display, render_event
from card_guess.sts1_event_stats import load_sts1_event_stats_snapshot
from card_guess.sts1_event_stats_coverage import (
    EVENT_LEVEL_STATS_ONLY,
    _PLANS,
    display_slots,
    exempt_category,
    mapped_keys,
    slot_entry,
)


def _catalog_events():
    return load_events("sts1").events


def _slots_by_event():
    return {event.id: display_slots(event) for event in _catalog_events()}


# ---------------------------------------------------------------- invariant

def test_plan_length_matches_display_slots_for_all_52_events():
    for event in _catalog_events():
        slots = display_slots(event)
        plan = _PLANS.get(event.id, ())
        if slots:
            assert len(plan) == len(slots), event.id
        else:
            assert not plan, event.id


def test_every_visible_choice_is_mapped_or_exempted_no_silent_missing():
    allowed = {
        "page_flow",
        "no_dump_choice",
        "stage_ambiguous",
        "outcome_variant",
        "duplicate_catalog_row",
        "no_occurrence",
    }
    for event in _catalog_events():
        for index, _choice in enumerate(display_slots(event)):
            entry = slot_entry(event.id, index)
            assert entry is not None, f"{event.id}[{index}] missing plan"
            kind, payload = entry
            assert kind in {"M", "E"}, f"{event.id}[{index}]"
            if kind == "M":
                assert payload, f"{event.id}[{index}] empty mapped keys"
            else:
                assert payload[0] in allowed, f"{event.id}[{index}]"


def test_dump_key_is_never_shared_by_two_rows_of_the_same_event():
    for event in _catalog_events():
        owner: dict[str, int] = {}
        for index, _choice in enumerate(display_slots(event)):
            keys = mapped_keys(event.id, index)
            if not keys:
                continue
            for key in keys:
                assert key not in owner, f"{event.id} shares {key!r}"
                owner[key] = index


def test_fallback_events_have_no_mapped_rows():
    for event in _catalog_events():
        if event.id not in EVENT_LEVEL_STATS_ONLY:
            continue
        for index, _choice in enumerate(display_slots(event)):
            assert exempt_category(event.id, index) is not None, event.id


def test_all_mapped_keys_exist_in_the_real_draft_rows():
    draft = Path("data/stats/sts1_event_stats_draft.json")
    if not draft.exists():
        pytest.skip("real draft snapshot not present")
    snapshot = load_sts1_event_stats_snapshot(draft)
    rows = {row["id"]: row for row in snapshot["events"]}
    for event in _catalog_events():
        row = rows.get(event.id)
        if row is None:
            continue
        observed = {
            option["choice_key"]
            for act in row["acts"].values()
            for option in act.get("options", [])
        }
        for index, _choice in enumerate(display_slots(event)):
            keys = mapped_keys(event.id, index)
            if keys:
                assert set(keys) <= observed, f"{event.id}[{index}] {keys}"


# --------------------------------------------------------- cross-act formulas


def _assoc(wins, runs):
    return {
        "value": wins / runs * 100 if runs else None,
        "unit": "percent",
        "provenance": "computed",
        "numerator": wins,
        "denominator": runs,
        "sample_size": runs,
    }


def _option(key, chosen, wins=None, runs=None):
    option = {
        "choice_key": key,
        "encounters": None,
        "chosen_count": chosen,
        "chosen_share": {"value": 0.0, "numerator": chosen, "denominator": 100},
        "associated_win_rate": _assoc(wins, runs) if wins is not None else None,
        "sample_size": runs,
    }
    return option


def test_cross_act_share_is_sum_over_encounters_not_averaged():
    from card_guess.sts1_event_stats import build_cross_act_view

    row = {
        "acts": {
            "act_1": {
                "encounters": 60,
                "options": [_option("A", 36, wins=18, runs=36)],
            },
            "act_2": {
                "encounters": 40,
                "options": [_option("A", 20, wins=8, runs=20)],
            },
        }
    }
    view = build_cross_act_view(row)
    assert view is not None
    assert view["encounters"] == 100
    option = view["options"][0]
    assert option["chosen_count"] == 56
    assert option["chosen_share"]["value"] == pytest.approx(56.0)
    association = option["associated_win_rate"]
    assert association is not None
    assert association["value"] == pytest.approx(26 / 56 * 100)


def test_cross_act_association_suppressed_when_any_act_lacks_assoc():
    from card_guess.sts1_event_stats import build_cross_act_view

    row = {
        "acts": {
            "act_1": {
                "encounters": 60,
                "options": [_option("A", 36, wins=18, runs=36)],
            },
            "act_2": {
                "encounters": 40,
                "options": [_option("A", 20, wins=None)],
            },
        }
    }
    view = build_cross_act_view(row)
    option = view["options"][0]
    assert option["associated_win_rate"] is None
    assert option["chosen_share"]["value"] == pytest.approx(56.0)


# ------------------------------------------------------- real-draft smokes

REAL_DRAFT = Path("data/stats/sts1_event_stats_draft.json")

REQUIRED_PLAYABLE_SMOKES = {
    "UPGRADE_SHRINE": "选项占比",
    "TRANSMORGRIFIER": "选项占比",
    "NEST": "事件级）",
    "SENSORYSTONE": "选项占比",
    "VAMPIRES": "选项占比",
    "BIG_FISH": "选项占比",
    "N_LOTH": "选项占比",
}

REQUIRED_UNSUPPORTED_SMOKES = {
    "MATCH_AND_KEEP": "事件级）",
    "CURSED_TOME": "选项占比",
    "SCRAP_OOZE": "选项占比",
    "KNOWING_SKULL": "事件级）",
    "COLOSSEUM": "事件级）",
}


@pytest.mark.skipif(not REAL_DRAFT.exists(), reason="real draft snapshot absent")
def test_required_smoke_events_show_stats_on_their_own_pages():
    snapshot = load_sts1_event_stats_snapshot(REAL_DRAFT)
    for event_id, marker in {**REQUIRED_PLAYABLE_SMOKES, **REQUIRED_UNSUPPORTED_SMOKES}.items():
        reply = render_event(get_event("sts1", event_id), stats_snapshot=snapshot)
        assert "样本：" in reply, event_id
        assert marker in reply, event_id


@pytest.mark.skipif(not REAL_DRAFT.exists(), reason="real draft snapshot absent")
def test_unsupported_events_show_stats_through_the_full_query_entry():
    from card_guess.event_presentation import render_event_full_query

    for event_id in REQUIRED_UNSUPPORTED_SMOKES:
        reply = render_event_full_query(get_event("sts1", event_id))
        assert "样本：" in reply, event_id


def test_display_slot_count_matches_rendered_number_of_choice_rows():
    for event in _catalog_events():
        display = build_event_display(event, stats_snapshot={})
        assert len(display_slots(event)) == len(display.choices), event.id


def test_playable_and_unsupported_partition_is_complete():
    catalog_ids = {event.id for event in _catalog_events()}
    assert catalog_ids == (STS1_PLAYABLE_EVENT_IDS | STS1_UNSUPPORTED_EVENT_IDS)

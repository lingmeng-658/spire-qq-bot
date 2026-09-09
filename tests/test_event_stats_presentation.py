"""STS1 Event Stats QQ presentation tests.

Synthetic snapshots drive formatting and mapping assertions so the suite never
depends on private run data; the frozen catalogs are used only as audited
fixtures whose raw option tokens drive the mapping.  One integration check
against the real draft artifact is skipped when the file is absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import card_guess.event_presentation as event_presentation
from card_guess.event_presentation import (
    render_event,
    render_event_full_query,
)
from card_guess.events import EventChoice, EventRecord, get_event
from card_guess.qq import bot, event_sessions, sessions

REAL_DRAFT = Path("data/stats/sts1_event_stats_draft.json")


# ------------------------------------------------------------------ helpers


def inject_stats(monkeypatch, fixture):
    """Feed a synthetic snapshot through the presentation loader seam."""
    monkeypatch.setattr(event_presentation, "_EVENT_STATS_LOADER", lambda: fixture)
    monkeypatch.setattr(event_presentation, "_EVENT_STATS_SNAPSHOT", None)


def _option(key, share_value, *, assoc_value=None):
    option = {
        "choice_key": key,
        "chosen_share": {"value": share_value, "denominator": 1},
    }
    option["associated_win_rate"] = (
        {"value": assoc_value, "denominator": 1} if assoc_value is not None else None
    )
    return option


def _snapshot(event_id, act, encounters, options):
    return {
        "events": [
            {
                "id": event_id,
                "acts": {act: {"encounters": encounters, "options": options}},
            }
        ]
    }


def _segment(reply, start_marker, end_marker=None):
    start = reply.index(start_marker)
    end = reply.index(end_marker, start) if end_marker is not None else len(reply)
    return reply[start:end]


def _option_line(reply, option_marker):
    """The part of the reply that belongs to one numbered option row."""
    tail = reply.split(option_marker, 1)[1]
    if "\n\n" in tail:
        tail = tail.split("\n\n", 1)[0]
    return tail


def _make_event(
    *,
    game="sts1",
    event_id="NO_STATS_EVENT",
    name="无数据事件",
    act=1,
    choices=None,
):
    return EventRecord(
        game=game,
        id=event_id,
        name_zh=name,
        name_en="No Stats Event",
        category="Event",
        act=act,
        pool="act_specific",
        description_zh="一段正文。",
        choices=tuple(
            choices
            if choices is not None
            else (
                EventChoice(
                    id="C",
                    text_zh="选项",
                    description_zh="效果。",
                    result_zh=None,
                    locked_zh=None,
                    raw={"option": "[Any] Do a thing."},
                ),
            )
        ),
        raw={},
    )


@pytest.fixture(autouse=True)
def clean_state():
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()


def patch_pool(monkeypatch, event):
    monkeypatch.setattr(
        bot, "default_random_pool", lambda game: (event,), raising=False
    )


def patch_query_sources(monkeypatch, *, events=()):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [], raising=False)
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(
        bot,
        "_find_events_by_name",
        lambda name, generation=None: [
            event
            for event in events
            if event.name_zh == name
            and (generation is None or event.game == f"sts{generation}")
        ],
        raising=False,
    )


def big_fish_fixture():
    return _snapshot(
        "BIG_FISH",
        "act_1",
        6702,
        [
            _option("Banana", 15.0, assoc_value=11.6),
            _option("Donut", 51.1, assoc_value=11.1),
            _option("Box", 33.8, assoc_value=6.6),
        ],
    )


def cleric_fixture():
    return _snapshot(
        "THE_CLERIC",
        "act_1",
        6218,
        [
            _option("Card Removal", 60.9, assoc_value=10.7),
            _option("Healed", 23.8, assoc_value=7.9),
            _option("Leave", 15.3, assoc_value=5.8),
        ],
    )


def drug_dealer_fixture():
    return _snapshot(
        "DRUG_DEALER",
        "act_2",
        2445,
        [
            _option("Became Test Subject", 47.4, assoc_value=24.5),
            _option("Inject Mutagens", 43.4, assoc_value=20.2),
            _option("Obtain J.A.X.", 9.2, assoc_value=17.8),
            _option("Ignored", 0.0),
        ],
    )


# ------------------------------------------------------------- BIG_FISH rows


def test_big_fish_three_options_show_their_own_share():
    reply = render_event(
        get_event("sts1", "BIG_FISH"), stats_snapshot=big_fish_fixture()
    )

    banana = _segment(reply, "1. 香蕉", "2. 甜甜圈")
    assert "选项占比 15.0% · 历史通关率 11.6%" in banana
    donut = _segment(reply, "2. 甜甜圈", "3. 盒子")
    assert "选项占比 51.1% · 历史通关率 11.1%" in donut
    box = _segment(reply, "3. 盒子", "4. 离开")
    assert "选项占比 33.8% · 历史通关率 6.6%" in box


def test_big_fish_stats_appear_before_user_chooses():
    reply = render_event(
        get_event("sts1", "BIG_FISH"), stats_snapshot=big_fish_fixture()
    )

    assert reply.index("选项占比") < reply.index("样本：6,702 次遭遇")
    assert reply.index("样本：6,702 次遭遇") < reply.index("※ 选项占比不是")


def test_big_fish_sample_size_and_single_disclaimer():
    reply = render_event(
        get_event("sts1", "BIG_FISH"), stats_snapshot=big_fish_fixture()
    )

    assert "样本：6,702 次遭遇" in reply
    assert reply.count("※ 选项占比不是“可选时选择率”") == 1


def test_big_fish_unmapped_leave_row_keeps_plain_catalog_text():
    reply = render_event(
        get_event("sts1", "BIG_FISH"), stats_snapshot=big_fish_fixture()
    )

    assert "选项占比" not in _option_line(reply, "4. 离开")


# ------------------------------------------------------------- mapping smoke


def test_the_cleric_options_map_to_audited_dump_keys():
    reply = render_event(
        get_event("sts1", "THE_CLERIC"), stats_snapshot=cleric_fixture()
    )

    heal = _segment(reply, "1. 治疗", "2. 净化")
    assert "选项占比 23.8% · 历史通关率 7.9%" in heal  # Healed, not Card Removal
    purify = _segment(reply, "2. 净化", "3. 离开")
    assert "选项占比 60.9% · 历史通关率 10.7%" in purify  # Card Removal
    leave = _option_line(reply, "3. 离开")
    assert "选项占比 15.3% · 历史通关率 5.8%" in leave


def test_drug_dealer_options_map_to_audited_dump_keys():
    reply = render_event(
        get_event("sts1", "DRUG_DEALER"), stats_snapshot=drug_dealer_fixture()
    )

    jax = _segment(reply, "1. 试一下J.A.X.", "2. 当一下实验对象")
    assert "选项占比 9.2% · 历史通关率 17.8%" in jax  # Obtain J.A.X.
    subject = _segment(reply, "2. 当一下实验对象", "3. 喝一下突变剂")
    assert "选项占比 47.4% · 历史通关率 24.5%" in subject  # Became Test Subject
    mutagens = _segment(reply, "3. 喝一下突变剂", "4. 离开")
    assert "选项占比 43.4% · 历史通关率 20.2%" in mutagens  # Inject Mutagens


def test_low_sample_null_win_rate_shows_only_share_without_na():
    reply = render_event(
        get_event("sts1", "DRUG_DEALER"), stats_snapshot=drug_dealer_fixture()
    )

    leave = _option_line(reply, "4. 离开")
    assert "选项占比 0.0%" in leave
    assert "历史通关率" not in leave
    assert "N/A" not in reply


# ------------------------------------------------------------- fallback


def test_event_without_stats_falls_back_to_plain_catalog_render():
    event = _make_event(event_id="NO_STATS_EVENT")
    plain = render_event(event, stats_snapshot={})

    assert "1. 选项 —— 效果。" in plain
    assert "选项占比" not in plain
    assert "样本：" not in plain
    assert "※ 选项占比不是" not in plain


def test_missing_snapshot_is_safe_fallback_for_real_event():
    reply = render_event(get_event("sts1", "BIG_FISH"), stats_snapshot={})

    assert "1. 香蕉" in reply
    assert "选项占比" not in reply
    assert "样本：" not in reply


# ------------------------------------------------------------- fixed rewards


def test_fixed_relic_rewards_still_rendered_before_stats():
    reply = render_event(
        get_event("sts1", "DRUG_DEALER"), stats_snapshot=drug_dealer_fixture()
    )

    block = _segment(reply, "3. 喝一下突变剂", "4. 离开")
    assert "突变之力" in block
    assert "效果：" in block
    assert "选项占比 43.4%" in block
    assert block.index("效果：") < block.index("选项占比 43.4%")


# ------------------------------------------------------------- STS2 / full query


def test_sts2_event_never_shows_sts1_stats():
    reply = render_event(
        get_event("sts2", "WATERLOGGED_SCRIPTORIUM"),
        stats_snapshot=big_fish_fixture(),
    )

    assert "触手羽毛笔" in reply
    assert "选项占比" not in reply


def test_event_full_query_path_is_unchanged():
    cases = {
        "SLIPPERY_BRIDGE": "再撑一会",
        "ROUND_TEA_PARTY": "挑事斗殴",
        "WELLSPRING": "装瓶",
    }
    for event_id, expected_text in cases.items():
        reply = render_event_full_query(get_event("sts2", event_id))
        assert expected_text in reply
        assert "选项占比" not in reply


# ------------------------------------------------------------- bot paths


def test_direct_event_query_shows_stats_before_choice(monkeypatch):
    inject_stats(monkeypatch, big_fish_fixture())
    patch_query_sources(monkeypatch, events=(get_event("sts1", "BIG_FISH"),))

    reply = bot.route_group_command(101, "大鱼")

    assert reply is not None
    text = str(reply)
    assert "选项占比 51.1% · 历史通关率 11.1%" in text
    assert "样本：6,702 次遭遇" in text
    assert event_sessions.get(101) is None


def test_random_interaction_first_screen_shows_stats(monkeypatch):
    inject_stats(monkeypatch, big_fish_fixture())
    patch_pool(monkeypatch, get_event("sts1", "BIG_FISH"))

    reply = bot.route_group_command(101, "事件1")

    assert reply is not None
    text = str(reply)
    assert "选项占比 51.1% · 历史通关率 11.1%" in text
    assert "样本：6,702 次遭遇" in text
    assert event_sessions.get(101) is not None


def test_outcome_after_choice_does_not_repeat_stats(monkeypatch):
    inject_stats(monkeypatch, big_fish_fixture())
    patch_pool(monkeypatch, get_event("sts1", "BIG_FISH"))

    assert bot.route_group_command(101, "事件1") is not None
    reply = str(bot.route_group_command(101, "2", actor="小明"))

    assert "小明选择了" in reply
    assert "选项占比" not in reply
    assert "样本：" not in reply


# ------------------------------------------------------------- real draft smoke


@pytest.mark.skipif(not REAL_DRAFT.exists(), reason="draft snapshot not present")
def test_real_draft_values_round_trip_through_three_smoke_events():
    """Numbers are not hardcoded here; output is derived from the draft rows."""
    from card_guess.sts1_event_stats import load_sts1_event_stats_snapshot

    snapshot = load_sts1_event_stats_snapshot(REAL_DRAFT)
    expected = {
        "BIG_FISH": ("act_1", "1. 香蕉", "Banana"),
        "THE_CLERIC": ("act_1", "1. 治疗", "Healed"),
        "DRUG_DEALER": ("act_2", "1. 试一下J.A.X.", "Obtain J.A.X."),
    }
    rows = {row["id"]: row for row in snapshot["events"]}
    for event_id, (act, marker, key) in expected.items():
        event = get_event("sts1", event_id)
        row = rows[event_id]
        act_map = row["acts"][act]
        option = next(o for o in act_map["options"] if o["choice_key"] == key)
        reply = render_event(event, stats_snapshot=snapshot)
        share_text = f"选项占比 {option['chosen_share']['value']:.1f}%"
        assert share_text in _segment(reply, marker)
        assert f"样本：{act_map['encounters']:,} 次遭遇" in reply

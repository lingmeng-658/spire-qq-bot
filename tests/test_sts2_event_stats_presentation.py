"""STS2 Event Stats QQ presentation tests.

Synthetic snapshots use the v1 shape consumed by the shared Event enrichment
layer.  Real catalog records are used only as audited display fixtures; no
private run data is required.
"""

from __future__ import annotations

import pytest

import card_guess.event_presentation as event_presentation
from card_guess.event_presentation import render_event
from card_guess.events import EventChoice, EventRecord, get_event
from card_guess.qq import bot, event_sessions, sessions


def _metric(value: float, numerator: int, denominator: int) -> dict:
    return {
        "value": value,
        "unit": "percent",
        "provenance": "computed",
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
    }


def _choice_row(
    *,
    occurrence_count: int,
    encounter_count: int,
    run_count: int | None = None,
    run_wins: int = 0,
    occurrence_wins: int = 0,
) -> dict:
    share = _metric(
        occurrence_count / encounter_count * 100,
        occurrence_count,
        encounter_count,
    )
    run_rate = None
    if run_count is not None:
        run_rate = _metric(run_wins / run_count * 100, run_wins, run_count)
    occurrence_rate = None
    if run_count is not None:
        occurrence_rate = _metric(
            occurrence_wins / occurrence_count * 100,
            occurrence_wins,
            occurrence_count,
        )
    return {
        "occurrence_count": occurrence_count,
        "occurrence_share": share,
        "associated_occurrence_wins": occurrence_wins,
        "associated_occurrence_win_rate": occurrence_rate,
        "associated_run_count": occurrence_count if run_count is None else run_count,
        "associated_run_wins": run_wins,
        "associated_run_win_rate": run_rate,
    }


def _snapshot(event_id: str, encounter_count: int, rows: dict[str, dict]) -> dict:
    return {"events": {event_id: {"encounter_count": encounter_count, "choices": rows}}}


def _wellspring_snapshot() -> dict:
    key = "WELLSPRING.pages.INITIAL.options.BATHE.title"
    return _snapshot(
        "WELLSPRING",
        120,
        {
            key: _choice_row(
                occurrence_count=100,
                encounter_count=120,
                run_count=100,
                run_wins=40,
                occurrence_wins=40,
            )
        },
    )


def _slippery_bridge_snapshot() -> dict:
    first = "SLIPPERY_BRIDGE.pages.INITIAL.options.HOLD_ON_0.title"
    repeated = "SLIPPERY_BRIDGE.pages.HOLD_ON_0.options.HOLD_ON_1.title"
    return _snapshot(
        "SLIPPERY_BRIDGE",
        100,
        {
            first: _choice_row(
                occurrence_count=70,
                encounter_count=100,
                run_count=70,
                run_wins=20,
            ),
            repeated: _choice_row(
                occurrence_count=130,
                encounter_count=100,
                run_count=90,
                run_wins=25,
            ),
        },
    )


def _make_event(
    event_id: str,
    *,
    name: str,
    choice_ids=("LINGER",),
    page_id: str = "INITIAL",
) -> EventRecord:
    pages = [
        {
            "id": page_id,
            "description": "页面正文。",
            "options": [
                {"id": choice_id, "title": "选项", "description": "效果。"}
                for choice_id in choice_ids
            ],
        }
    ]
    return EventRecord(
        game="sts2",
        id=event_id,
        name_zh=name,
        name_en=name,
        category="Event",
        act=1,
        pool="act_specific",
        description_zh="一段正文。",
        choices=tuple(
            EventChoice(
                id=choice_id,
                text_zh="选项",
                description_zh="效果。",
                result_zh="结束。",
                locked_zh=None,
                raw={"id": choice_id},
            )
            for choice_id in choice_ids
        ),
        raw={"pages": pages},
    )


def _big_fish_fixture() -> dict:
    return {
        "events": [
            {
                "id": "BIG_FISH",
                "acts": {
                    "act_1": {
                        "encounters": 6702,
                        "options": [
                            {
                                "choice_key": "Banana",
                                "chosen_share": {"value": 15.0, "denominator": 1},
                                "associated_win_rate": {
                                    "value": 11.6,
                                    "denominator": 1,
                                },
                            }
                        ],
                    }
                },
            }
        ]
    }


def _segment(reply: str, start_marker: str, end_marker: str | None = None) -> str:
    start = reply.index(start_marker)
    end = reply.index(end_marker, start) if end_marker is not None else len(reply)
    return reply[start:end]


def _patch_query_sources(monkeypatch) -> None:
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [], raising=False)
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [], raising=False)


@pytest.fixture(autouse=True)
def clean_state():
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()
    event_presentation._STS2_EVENT_STATS_SNAPSHOT = None
    yield
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()
    event_presentation._STS2_EVENT_STATS_SNAPSHOT = None


def test_wellspring_renders_sts2_occurrence_share_and_history_win_rate():
    reply = render_event(
        get_event("sts2", "WELLSPRING"), stats_snapshot=_wellspring_snapshot()
    )

    bathe = _segment(reply, "2. 沐浴", "样本：120 次遭遇")
    assert "选项出现占比 83.3% · 历史通关率 40.0%" in bathe
    assert "样本：120 次遭遇" in reply
    assert "※ 选项出现占比以事件遭遇次数为分母，重复选择时可能超过100%；" in reply
    assert "历史通关率仅表示历史关联，不代表因果。" in reply


def test_slippery_bridge_repeated_choice_snapshot_renders_without_misleading_rate():
    reply = render_event(
        get_event("sts2", "SLIPPERY_BRIDGE"),
        stats_snapshot=_slippery_bridge_snapshot(),
    )

    assert "选项出现占比 70.0%" in _segment(reply, "2. 再撑一会", "样本：100 次遭遇")
    assert "事件资料" not in reply
    assert "节点选择率" not in reply
    assert "选择率" not in reply
    assert "Pick Rate" not in reply


def test_abyssal_baths_linger_can_display_share_above_one_hundred_percent():
    event = _make_event("ABYSSAL_BATHS", name="深水浴场", choice_ids=("LINGER",))
    key = "ABYSSAL_BATHS.pages.INITIAL.options.LINGER.title"
    snapshot = _snapshot(
        "ABYSSAL_BATHS",
        50,
        {
            key: _choice_row(
                occurrence_count=80,
                encounter_count=50,
                run_count=45,
                run_wins=10,
            )
        },
    )

    reply = render_event(event, stats_snapshot=snapshot)

    assert "选项出现占比 160.0%" in reply
    assert "样本：50 次遭遇" in reply


def test_stats_missing_falls_back_to_plain_event_catalog():
    reply = render_event(get_event("sts2", "WELLSPRING"), stats_snapshot={})

    assert "1. 装瓶" in reply
    assert "选项出现占比" not in reply
    assert "历史通关率" not in reply
    assert "样本：" not in reply


def test_direct_event_query_shows_sts2_stats(monkeypatch):
    _patch_query_sources(monkeypatch)
    monkeypatch.setattr(
        event_presentation, "_STS2_EVENT_STATS_SNAPSHOT", _wellspring_snapshot()
    )

    reply = str(bot.route_group_command(101, "泉水"))

    assert reply.startswith("【事件资料｜泉水｜STS2 · 第一层】")
    assert "选项出现占比 83.3% · 历史通关率 40.0%" in reply
    assert "样本：120 次遭遇" in reply
    assert event_sessions.get(101) is None


def test_random_interaction_first_screen_shows_sts2_stats(monkeypatch):
    event = get_event("sts2", "WELLSPRING")
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (event,))
    monkeypatch.setattr(
        event_presentation, "_STS2_EVENT_STATS_SNAPSHOT", _wellspring_snapshot()
    )

    reply = str(bot.route_group_command(101, "事件2"))

    assert reply.startswith("【泉水｜STS2 · 第一层】")
    assert "选项出现占比 83.3% · 历史通关率 40.0%" in reply
    assert "样本：120 次遭遇" in reply
    assert event_sessions.get(101) is not None


def test_outcome_after_choice_does_not_repeat_stats(monkeypatch):
    event = get_event("sts2", "WELLSPRING")
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (event,))
    monkeypatch.setattr(
        event_presentation, "_STS2_EVENT_STATS_SNAPSHOT", _wellspring_snapshot()
    )
    bot.route_group_command(101, "事件2")

    reply = str(bot.route_group_command(101, "1", actor="群友甲"))

    assert "群友甲选择了「装瓶」" in reply
    assert "选项出现占比" not in reply
    assert "历史通关率" not in reply
    assert "样本：" not in reply


def test_fixed_sts2_relic_effect_keeps_rendering_before_stats():
    event = get_event("sts2", "ROOM_FULL_OF_CHEESE")
    key = "ROOM_FULL_OF_CHEESE.pages.INITIAL.options.SEARCH.title"
    snapshot = _snapshot(
        "ROOM_FULL_OF_CHEESE",
        200,
        {
            key: _choice_row(
                occurrence_count=60,
                encounter_count=200,
                run_count=60,
                run_wins=30,
            )
        },
    )

    reply = render_event(event, stats_snapshot=snapshot)
    block = _segment(reply, "2. 仔细翻找", "样本：200 次遭遇")

    assert "遗物「天选芝士」" in block
    assert "效果：" in block
    assert "选项出现占比 30.0%" in block
    assert block.index("效果：") < block.index("选项出现占比")


def test_sts1_presentation_wording_is_unified_to_history_win_rate():
    reply = render_event(get_event("sts1", "BIG_FISH"), stats_snapshot=_big_fish_fixture())

    assert "选项占比 15.0% · 历史通关率 11.6%" in reply
    assert "关联胜率" not in reply


def test_sts2_output_never_uses_misleading_choice_rate_terms():
    reply = render_event(
        get_event("sts2", "WELLSPRING"), stats_snapshot=_wellspring_snapshot()
    )

    for misleading in ("选择率", "节点选择率", "Pick Rate"):
        assert misleading not in reply

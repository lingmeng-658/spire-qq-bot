"""Event encyclopedia queries stay separate from interactive Event screens."""

from __future__ import annotations

import importlib

import pytest

import card_guess.event_presentation as event_presentation
from card_guess.event_presentation import render_event_choice_outcome
from card_guess.events import get_event
from card_guess.qq import bot, event_sessions


def _isolate_event_queries(monkeypatch):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [])
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [])
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [])


def _drug_dealer_stats():
    return {
        "events": [
            {
                "id": "DRUG_DEALER",
                "acts": {
                    "act_2": {
                        "encounters": 2_445,
                        "options": [
                            {
                                "choice_key": "Inject Mutagens",
                                "chosen_share": {"value": 43.4, "denominator": 1},
                                "associated_win_rate": {
                                    "value": 20.2,
                                    "denominator": 1,
                                },
                            }
                        ],
                    }
                },
            }
        ]
    }


def test_pure_query_planner_and_renderer_use_encyclopedia_language():
    try:
        event_query = importlib.import_module("card_guess.event_query")
    except ModuleNotFoundError:
        pytest.fail("card_guess.event_query planner module is missing")

    plan = event_query.plan_event_query(
        get_event("sts1", "BIG_FISH"), stats_snapshot={}
    )
    reply = event_query.render_event_query(plan)

    assert reply.startswith("【事件资料｜大鱼｜STS1 · 第一层】")
    assert "可能的选择：" in reply
    assert "\n\n选择：" not in reply


def test_drug_dealer_direct_query_keeps_fixed_relic_effects_and_stats(monkeypatch):
    _isolate_event_queries(monkeypatch)
    monkeypatch.setattr(
        event_presentation, "_EVENT_STATS_SNAPSHOT", _drug_dealer_stats()
    )

    reply = str(bot.route_group_command(101, "增益研究者"))

    assert "【事件资料｜增益研究者｜STS1 · 第二层】" in reply
    assert "可能的选择：" in reply
    assert "遗物「突变之力」" in reply
    assert "效果：" in reply
    assert "选项占比 43.4% · 历史通关率 20.2%" in reply
    assert "样本：2,445 次遭遇" in reply
    assert event_sessions.get(101) is None


def test_wellspring_direct_query_does_not_create_session(monkeypatch):
    _isolate_event_queries(monkeypatch)

    reply = str(bot.route_group_command(102, "泉水"))

    assert reply.startswith("【事件资料｜泉水｜STS2 · 第一层】")
    assert "可能的选择：" in reply
    assert event_sessions.get(102) is None


def test_unsupported_interaction_event_still_has_direct_query(monkeypatch):
    _isolate_event_queries(monkeypatch)

    reply = str(bot.route_group_command(103, "遗物交换商"))

    assert reply.startswith("【事件资料｜遗物交换商｜STS2 · 共享事件】")
    assert "可能的选择：" in reply
    assert "拿上面那件" in reply
    assert event_sessions.get(103) is None


def test_direct_query_during_active_event_session_preserves_session(monkeypatch):
    _isolate_event_queries(monkeypatch)
    wellspring = get_event("sts2", "WELLSPRING")
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (wellspring,))
    monkeypatch.setattr(bot.random, "choice", lambda items: items[0])

    interaction = str(bot.route_group_command(104, "事件2"))
    before = event_sessions.get(104)
    assert before is not None
    assert "\n\n选择：" in interaction

    query = str(bot.route_group_command(104, "大鱼"))

    assert query.startswith("【事件资料｜大鱼｜STS1 · 第一层】")
    assert event_sessions.get(104) is before


def test_slippery_bridge_query_uses_normalized_initial_choice_text(monkeypatch):
    _isolate_event_queries(monkeypatch)

    reply = str(bot.route_group_command(105, "滑脚木桥"))

    assert reply.startswith("【事件资料｜滑脚木桥｜STS2 · 共享事件】")
    assert "随机卡牌将从你的牌组中被移除" in reply
    assert "a random Card" not in reply
    assert "11+" in reply
    assert "循环" in reply


@pytest.mark.parametrize(
    ("command", "game", "event_id"),
    [("事件1", "sts1", "BIG_FISH"), ("事件2", "sts2", "WELLSPRING")],
)
def test_random_interaction_keeps_action_language(
    monkeypatch, command, game, event_id
):
    event = get_event(game, event_id)
    monkeypatch.setattr(bot, "default_random_pool", lambda selected: (event,))
    monkeypatch.setattr(bot.random, "choice", lambda items: items[0])

    reply = str(bot.route_group_command(106, command))

    assert reply.startswith(f"【{event.name_zh}｜")
    assert "事件资料" not in reply
    assert "\n\n选择：" in reply
    assert "可能的选择：" not in reply
    assert event_sessions.get(106) is not None


def test_interaction_outcome_text_is_unchanged():
    choice = get_event("sts2", "WELLSPRING").choices[0]

    reply = render_event_choice_outcome(choice, "小明")

    assert reply == f"小明选择了「装瓶」\n\n{choice.result_zh}\n\n事件结束。"

# -*- coding: utf-8 -*-
"""QQ leaderboard & single-relic display tests for STS2 Ancient choice stats.

The Ancient entry is now NPC + layer (达弗2 / 涅奥) with full-cohort boards;
排行/最高/最低 no longer route to a leaderboard.  All NPCs, relic ids, and
Chinese names below are fictional
fixtures so no network or real run data is touched.
"""

from __future__ import annotations

import pytest

from card_guess.qq import bot, renderer, sessions
from card_guess.qq.renderer import RenderedReply
from card_guess.sts2_ancient_choice import build_sts2_ancient_choice_snapshot

RELIC_ZH = {
    "F_A": "幻想遗物甲",
    "F_B": "幻想遗物乙",
    "F_C": "幻想遗物丙",
    "F_D": "幻想遗物丁",
    "F_E": "幻想遗物戊",
    "F_F": "幻想遗物己",
}


def _row(relic_id, npc_id, act, offered, picked):
    return {
        "relic_id": relic_id,
        "npc_id": npc_id,
        "act": act,
        "offered_count": offered,
        "picked_rate": picked,
    }


def _darv_rows():
    return [
        _row("F_A", "DARV", 2, 18000, 58),
        _row("F_B", "DARV", 2, 18000, 53),
        _row("F_C", "DARV", 2, 18000, 45),
        _row("F_D", "DARV", 2, 18000, 34),
        _row("F_E", "DARV", 2, 18000, 30),
        _row("F_F", "DARV", 2, 18000, 21),
        _row("F_A", "DARV", 3, 4400, 54),
        _row("F_B", "DARV", 3, 4500, 53),
    ]


def _darv_snapshot():
    return build_sts2_ancient_choice_snapshot(
        _darv_rows(),
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=RELIC_ZH,
        npc_names_zh={"DARV": "达弗"},
    )


def _neow_snapshot():
    return build_sts2_ancient_choice_snapshot(
        [_row("F_A", "NEOW", 1, 120000, 76)],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=RELIC_ZH,
        npc_names_zh={"NEOW": "涅奥"},
    )


def patch_loader(monkeypatch, snapshot):
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: snapshot)


def make_relic(relic_id="F_A", tier="Ancient"):
    return {
        "game": "sts2",
        "id": relic_id,
        "name": RELIC_ZH[relic_id],
        "name_en": "Fictional Relic",
        "description": "每场战斗开始时，获得1点能量。",
        "description_en": "Gain 1 Energy at combat start.",
        "tier": tier,
        "color": "shared",
    }


@pytest.fixture(autouse=True)
def idle_session(monkeypatch):
    monkeypatch.setattr(sessions, "get", lambda group_id: None)


# Leaderboard rendering -------------------------------------------------------

def test_full_leaderboard_shows_rank_zh_name_and_rate():
    board = renderer.render_ancient_choice_leaderboard(
        "DARV", 2, "full", snapshot=_darv_snapshot()
    )
    assert board is not None
    assert board.splitlines()[0] == "达弗 · 第二层 Ancient 遗物选择率排行"
    assert "1. 幻想遗物甲 —— 58%" in board
    assert "6. 幻想遗物己 —— 21%" in board
    for banned in ["F_A", "DARV", "relic_id", "offered", "picked_rate", "rank"]:
        assert banned not in board


def test_full_leaderboard_is_complete_cohort_not_top_n():
    board = renderer.render_ancient_choice_leaderboard(
        "DARV", 2, "full", snapshot=_darv_snapshot()
    )
    rows = [line for line in board.splitlines()[1:] if line.strip()]
    assert len(rows) == 6
    assert "Top" not in board and "最高" not in board and "最低" not in board


def test_full_leaderboard_third_layer_cohort():
    board = renderer.render_ancient_choice_leaderboard(
        "DARV", 3, "full", snapshot=_darv_snapshot()
    )
    assert board.splitlines()[0] == "达弗 · 第三层 Ancient 遗物选择率排行"
    rows = [line for line in board.splitlines()[1:] if line.strip()]
    assert rows == ["1. 幻想遗物甲 —— 54%", "2. 幻想遗物乙 —— 53%"]


def test_leaderboard_does_not_mix_acts():
    board = renderer.render_ancient_choice_leaderboard(
        "DARV", 2, "full", snapshot=_darv_snapshot()
    )
    assert "第三层" not in board and "第三幕" not in board
    rows = [line for line in board.splitlines()[1:] if line.strip()]
    assert len(rows) == 6


def test_leaderboard_auto_resolves_single_act_npc():
    board = renderer.render_ancient_choice_leaderboard(
        "NEOW", None, "full", snapshot=_neow_snapshot()
    )
    assert "涅奥 · 第一层 Ancient 遗物选择率排行" in board
    assert "1. 幻想遗物甲 —— 76%" in board


def test_leaderboard_multiact_npc_without_act_returns_layers_hint():
    board = renderer.render_ancient_choice_leaderboard(
        "DARV", None, "full", snapshot=_darv_snapshot()
    )
    assert board == "达弗有多个可查询层：\n达弗2\n达弗3"


def test_leaderboard_invalid_act_returns_layers_hint():
    board = renderer.render_ancient_choice_leaderboard(
        "DARV", 1, "full", snapshot=_darv_snapshot()
    )
    assert board == "达弗有多个可查询层：\n达弗2\n达弗3"
    board = renderer.render_ancient_choice_leaderboard(
        "NEOW", 2, "full", snapshot=_neow_snapshot()
    )
    assert board == "涅奥目前只有第一层的数据。\n可发送：涅奥"


def test_leaderboard_unresolved_npc_zh_never_leaks_english_id():
    snapshot = build_sts2_ancient_choice_snapshot(
        [_row("F_A", "ZZZ", 2, 4000, 60)],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=RELIC_ZH,
        npc_names_zh={},
    )
    board = renderer.render_ancient_choice_leaderboard(
        "ZZZ", 2, "full", snapshot=snapshot
    )
    assert board is None


# Single relic display --------------------------------------------------------

def test_single_relic_choice_line_shows_rate_and_rank():
    relic = make_relic("F_E", tier="Ancient")
    text = renderer.render_sts2_ancient_choice_stats(relic, _darv_snapshot())
    assert "达弗 · 第二层：约30%会选，选择率第5 / 6。" in text
    for banned in ["同级遗物携带率", "携带率", "picks", "presence", "出现时"]:
        assert banned not in text


def test_single_relic_multiact_shows_each_context():
    relic = make_relic("F_A", tier="Ancient")
    text = renderer.render_sts2_ancient_choice_stats(relic, _darv_snapshot())
    assert "达弗 · 第二层：约58%会选，选择率第1 / 6。" in text
    assert "达弗 · 第三层：约54%会选，选择率第1 / 2。" in text


def test_single_relic_without_choice_data_returns_empty():
    relic = make_relic("F_F", tier="Rare")
    assert renderer.render_sts2_ancient_choice_stats(relic, _darv_snapshot()) == ""
    relic = make_relic("F_B", tier="Ancient")
    assert renderer.render_sts2_ancient_choice_stats(relic, _neow_snapshot()) == ""


# QQ relic query reply --------------------------------------------------------

def test_sts2_relic_query_reply_no_longer_shows_presence_rank(monkeypatch):
    relic = make_relic("F_A", tier="Ancient")
    patch_loader(monkeypatch, _darv_snapshot())
    reply = renderer.render_relic_query_reply([relic])
    assert "达弗 · 第二层：约58%会选，选择率第1 / 6。" in reply
    assert "=== 幻想遗物甲 · STS2 ===" in reply
    assert "先古遗物" in reply
    for banned in ["同级遗物携带率", "携带率", "picks", "presence", "sample_size"]:
        assert banned not in reply


def test_sts2_relic_query_non_ancient_has_no_stats_paragraph(monkeypatch):
    relic = make_relic("F_C", tier="Uncommon")
    patch_loader(monkeypatch, _darv_snapshot())
    reply = renderer.render_relic_query_reply([relic])
    assert "=== 幻想遗物丙 · STS2 ===" in reply
    assert "罕见遗物" in reply
    for banned in ["同级遗物携带率", "携带率", "选择率", "出现时约", "picks"]:
        assert banned not in reply


# Bot command routing ---------------------------------------------------------

def test_bot_full_leaderboard_command(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, "达弗2")
    assert isinstance(reply, RenderedReply)
    assert "达弗 · 第二层 Ancient 遗物选择率排行" in reply
    assert "1. 幻想遗物甲 —— 58%" in reply
    rows = [line for line in reply.splitlines()[1:] if line.strip()]
    assert len(rows) == 6


def test_bot_third_layer_leaderboard_command(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, "达弗3")
    assert isinstance(reply, RenderedReply)
    assert "达弗 · 第三层 Ancient 遗物选择率排行" in reply
    assert "2. 幻想遗物乙 —— 53%" in reply


def test_bot_single_act_npc_bare_name_returns_board(monkeypatch):
    patch_loader(monkeypatch, _neow_snapshot())
    reply = bot.route_group_command(101, "涅奥")
    assert isinstance(reply, RenderedReply)
    assert "涅奥 · 第一层 Ancient 遗物选择率排行" in reply
    assert "1. 幻想遗物甲 —— 76%" in reply
    assert "涅奥1" not in reply


def test_bot_multiact_npc_bare_name_prompts_for_layer(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, "达弗")
    assert str(reply) == "达弗有多个可查询层：\n达弗2\n达弗3"


def test_bot_paihang_suffix_no_longer_routes(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    assert (
        str(bot.route_group_command(101, "达弗2 排行2"))
        == bot.UNKNOWN_COMMAND_REPLY
    )
    assert (
        str(bot.route_group_command(101, "达弗2排行"))
        == bot.UNKNOWN_COMMAND_REPLY
    )


def test_bot_npc_invalid_layer_gets_short_hint(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, "达弗1")
    assert str(reply) == "达弗有多个可查询层：\n达弗2\n达弗3"
    patch_loader(monkeypatch, _neow_snapshot())
    reply = bot.route_group_command(101, "涅奥2")
    assert str(reply) == "涅奥目前只有第一层的数据。\n可发送：涅奥"


@pytest.mark.parametrize(
    "command",
    ["达弗2最高", "达弗2 最高", "达弗2最低", "达弗2 最低", "达弗 第三幕 最低"],
)
def test_bot_top_and_bottom_no_longer_route_to_leaderboard(monkeypatch, command):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, command)
    text = str(reply)
    assert "选择排行" not in text
    assert "最高 5" not in text and "最低 5" not in text
    assert text == bot.UNKNOWN_COMMAND_REPLY


def test_bot_act_word_after_keyword_is_not_a_board(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, "达弗2 排行 第二幕")
    assert "选择排行" not in str(reply)
    assert str(reply) == bot.UNKNOWN_COMMAND_REPLY


def test_unrelated_messages_are_not_swallowed_by_npc_commands(monkeypatch):
    patch_loader(monkeypatch, _darv_snapshot())
    reply = bot.route_group_command(101, "不存在遗物2")
    assert not (isinstance(reply, RenderedReply) and "选择排行" in reply.text)


def test_sts1_relic_query_path_is_untouched(monkeypatch, tmp_path):
    sts1_relic = {
        "game": "sts1",
        "id": "STARTER_ONE",
        "name": "试验性遗物",
        "name_en": "Starter One",
        "description": "每场战斗开始时，获得1点能量。",
        "description_en": "Gain energy.",
        "tier": "starter",
        "color": "ironclad",
    }
    snapshot = {
        "game": "sts1",
        "relics": {
            "STARTER_ONE": {
                "tier": "starter",
                "supported_roles": ["IRONCLAD"],
                "overall": {"presence_rate": {"value": 99.9}},
                "per_character": {
                    "IRONCLAD": {
                        "hold_rate": {"value": 99.9, "numerator": 1000, "denominator": 1001}
                    }
                },
            }
        },
    }
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: snapshot)
    reply = renderer.render_relic_query_reply([sts1_relic])
    assert "=== 试验性遗物 · STS1 ===" in reply
    assert "试验性遗物" in reply

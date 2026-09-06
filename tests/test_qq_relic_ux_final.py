# -*- coding: utf-8 -*-
"""Relic UX Final: STS1 Boss boards, STS2 Ancient full boards, layer copy.

Independent RED->GREEN targets for the relic final UX scope:
- Boss1/Boss2 complete-cohort boards reusing boss_choice_act_rows();
- Boss3 only returns a short no-cohort hint;
- NPC<layer> / bare-NPC Ancient full boards replace 排行/最高/最低 keywords;
- single-relic copy uses 层 and drops the redundant 出现时 phrase;
- relic images / whitespace normalization / Card routing stay intact.

All relics, NPCs, names, and snapshots below are fictional fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from card_guess import leaderboard as lb
from card_guess.qq import bot, renderer
from card_guess.qq import sessions
from card_guess.relic_stats import boss_choice_act_rows
from card_guess.sts2_ancient_choice import build_sts2_ancient_choice_snapshot

BOSS_ZH = {
    "SOZU": "添水",
    "CALLING_BELL": "幻唤之铃",
    "SLAVERS_COLLAR": "囚仆项圈",
    "RING_OF_THE_SERPENT": "灵蛇之戒",
    "ECTOPLASM": "幻灵体",
    "RUNE_DOME": "符文穹顶",
}

ANCIENT_ZH = {
    "F_A": "幻想遗物甲",
    "F_B": "幻想遗物乙",
    "F_C": "幻想遗物丙",
    "F_D": "幻想遗物丁",
    "F_E": "幻想遗物戊",
    "F_F": "幻想遗物己",
}


def rate(value, numerator=None, denominator=None):
    metric = {"value": value, "unit": "percent"}
    if numerator is not None:
        metric["numerator"] = numerator
    if denominator is not None:
        metric["denominator"] = denominator
    return metric


def count(value):
    return {"value": value, "unit": "count"}


def boss_act(offered, picked):
    return {
        "offered_count": count(offered),
        "picked_count": count(picked),
        "pick_rate": rate(picked / offered * 100.0, picked, offered),
    }


def boss_snapshot(offers_by_relic):
    """Snapshot from ``{relic_id: {act_key: (offered, picked)}}``."""
    relics = {}
    for relic_id, acts in offers_by_relic.items():
        choice = {
            act_key: boss_act(*pair)
            for act_key, pair in acts.items()
        }
        relics[relic_id] = {
            "overall": rate(40.0, 4000, 10000),
            "per_character": {
                role: rate(30.0)
                for role in ("IRONCLAD", "THE_SILENT", "DEFECT", "WATCHER")
            },
            "supported_roles": ["IRONCLAD", "THE_SILENT", "DEFECT", "WATCHER"],
            "boss_choice": choice,
        }
    return {"relics": relics}


def patch_boss(monkeypatch, snapshot, zh=None):
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: snapshot)
    names = dict(zh) if zh is not None else dict(BOSS_ZH)
    monkeypatch.setattr(renderer, "load_sts1_relic_zh_names", lambda: names)


def full_boss_snapshot():
    """Six-relic act1 cohort plus a six-relic act2 cohort (full, not Top N)."""
    zh = {
        "F_TOP": "顶冠遗物",
        "F_2ND": "次冠遗物",
        "F_SOZU": "添水",
        "F_4TH": "四冠遗物",
        "F_5TH": "五冠遗物",
        "F_6TH": "六冠遗物",
    }
    snapshot = boss_snapshot({
        "F_TOP": {"act1": (12000, 7200), "act2": (11000, 5500)},   # 60.0 / 50.0
        "F_2ND": {"act1": (10000, 5200), "act2": (10000, 4500)},   # 52.0 / 45.0
        "F_SOZU": {"act1": (3000, 1200), "act2": (3000, 300)},     # 40.0 / 10.0
        "F_4TH": {"act1": (8000, 2800), "act2": (8000, 2800)},     # 35.0 / 35.0
        "F_5TH": {"act1": (7000, 1750), "act2": (7000, 2100)},     # 25.0 / 30.0
        "F_6TH": {"act1": (6000, 600), "act2": (6000, 1200)},      # 10.0 / 20.0
    })
    return snapshot, zh


def make_boss_relic(relic_id="SOZU", name="添水"):
    return {
        "game": "sts1",
        "id": relic_id,
        "name": name,
        "name_en": relic_id,
        "description": "虚构的 Boss 遗物效果。",
        "description_en": "fictional",
        "tier": "Boss",
        "color": None,
    }


# Ancient fixtures -----------------------------------------------------------


def _row(relic_id, npc_id, act, offered, picked):
    return {
        "relic_id": relic_id,
        "npc_id": npc_id,
        "act": act,
        "offered_count": offered,
        "picked_rate": picked,
    }


def darv_snapshot():
    return build_sts2_ancient_choice_snapshot(
        [
            _row("F_A", "DARV", 2, 18000, 58),
            _row("F_B", "DARV", 2, 18000, 53),
            _row("F_C", "DARV", 2, 18000, 45),
            _row("F_D", "DARV", 2, 18000, 34),
            _row("F_E", "DARV", 2, 18000, 30),
            _row("F_F", "DARV", 2, 18000, 21),
            _row("F_A", "DARV", 3, 4400, 54),
            _row("F_B", "DARV", 3, 4500, 53),
        ],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=ANCIENT_ZH,
        npc_names_zh={"DARV": "达弗"},
    )


def neow_snapshot():
    return build_sts2_ancient_choice_snapshot(
        [_row("F_A", "NEOW", 1, 120000, 76)],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=ANCIENT_ZH,
        npc_names_zh={"NEOW": "涅奥"},
    )


def patch_ancient(monkeypatch, snapshot):
    monkeypatch.setattr(
        renderer, "load_sts2_ancient_choice_stats", lambda: snapshot
    )


def make_ancient_relic(relic_id="F_A", tier="Ancient"):
    return {
        "game": "sts2",
        "id": relic_id,
        "name": ANCIENT_ZH[relic_id],
        "name_en": "Fictional Relic",
        "description": "虚构效果。",
        "description_en": "fictional",
        "tier": tier,
        "color": "shared",
    }


@pytest.fixture(autouse=True)
def idle_session(monkeypatch):
    monkeypatch.setattr(sessions, "get", lambda group_id: None)


# 1-2. STS1 Boss full boards -------------------------------------------------

def test_boss1_renders_first_layer_full_board(monkeypatch):
    snapshot, zh = full_boss_snapshot()
    patch_boss(monkeypatch, snapshot, zh)
    reply = bot.route_group_command(101, "Boss1")
    text = str(reply)
    assert text.splitlines()[0] == "第一层 Boss 遗物选择率排行"
    rows = [line for line in text.splitlines()[1:] if line.strip()]
    assert len(rows) == len(boss_choice_act_rows(snapshot, "act1"))
    assert rows[0] == "1. 顶冠遗物 —— 60.0%"


def test_boss2_renders_second_layer_full_board(monkeypatch):
    snapshot, zh = full_boss_snapshot()
    patch_boss(monkeypatch, snapshot, zh)
    reply = bot.route_group_command(101, "Boss2")
    text = str(reply)
    assert text.splitlines()[0] == "第二层 Boss 遗物选择率排行"
    rows = [line for line in text.splitlines()[1:] if line.strip()]
    assert len(rows) == len(boss_choice_act_rows(snapshot, "act2"))
    assert "F_TOP" not in text and "F_SOZU" not in text
    assert "1. 顶冠遗物 —— 50.0%" in text


def test_boss3_returns_safe_hint_without_fake_board(monkeypatch):
    snapshot, zh = full_boss_snapshot()
    patch_boss(monkeypatch, snapshot, zh)
    reply = bot.route_group_command(101, "Boss3")
    text = str(reply)
    assert "第一层" in text and "第二层" in text
    assert "第三层 Boss" not in text
    assert "F_" not in text


def test_boss_board_is_complete_cohort_not_top_n(monkeypatch):
    snapshot, zh = full_boss_snapshot()
    patch_boss(monkeypatch, snapshot, zh)
    reply = bot.route_group_command(101, "Boss 遗物 1")
    text = str(reply)
    rows = [line for line in text.splitlines()[1:] if line.strip()]
    assert len(rows) == 6
    assert "Top" not in text and "最高" not in text


def test_boss_board_keeps_competition_rank_ties(monkeypatch):
    snapshot = boss_snapshot({
        "F_TOP": {"act1": (10000, 5000)},   # 50.0
        "F_B": {"act1": (9000, 3600)},      # 40.0 ties
        "F_C": {"act1": (8000, 3200)},      # 40.0 ties
        "F_D": {"act1": (7000, 2100)},      # 30.0 -> rank 4
        "F_E": {"act1": (6000, 1200)},      # 20.0
        "F_F": {"act1": (5000, 500)},       # 10.0
    })
    zh = {
        "F_TOP": "顶冠遗物",
        "F_B": "乙冠遗物",
        "F_C": "丙冠遗物",
        "F_D": "丁冠遗物",
        "F_E": "戊冠遗物",
        "F_F": "己冠遗物",
    }
    patch_boss(monkeypatch, snapshot, zh)
    text = str(bot.route_group_command(101, "Boss1"))
    assert "1. 顶冠遗物 —— 50.0%" in text
    assert "2. 乙冠遗物 —— 40.0%" in text
    assert "2. 丙冠遗物 —— 40.0%" in text
    assert "4. 丁冠遗物 —— 30.0%" in text
    assert "3." not in text


# 6. STS1 Boss single relic uses 层 ------------------------------------------

def test_sts1_boss_single_relic_uses_layer_words(monkeypatch):
    snapshot = boss_snapshot({
        "SOZU": {"act1": (3000, 1200), "act2": (3000, 300)},
        "CALLING_BELL": {"act1": (9000, 5400), "act2": (9000, 7200)},
        "SLAVERS_COLLAR": {"act1": (2000, 1000), "act2": (2000, 200)},
        "RING_OF_THE_SERPENT": {"act1": (5000, 1000), "act2": (999, 900)},
    })
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: snapshot)
    reply = renderer.render_relic_query_reply([make_boss_relic()])
    assert "第一层 Boss 奖励：\n约40.0%会选，选择率第 3 / 4。" in str(reply)
    assert "第二层 Boss 奖励：\n约10.0%会选，选择率第 2 / 3。" in str(reply)
    assert "第一幕" not in str(reply) and "第二幕" not in str(reply)


# 7-8. STS2 Ancient full boards ----------------------------------------------

def test_darv2_renders_ancient_second_layer_full_board(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    reply = bot.route_group_command(101, "达弗2")
    text = str(reply)
    assert text.splitlines()[0] == "达弗 · 第二层 Ancient 遗物选择率排行"
    rows = [line for line in text.splitlines()[1:] if line.strip()]
    assert len(rows) == 6
    assert rows[0] == "1. 幻想遗物甲 —— 58%"
    assert rows[-1] == "6. 幻想遗物己 —— 21%"


def test_darv3_renders_ancient_third_layer_full_board(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    reply = bot.route_group_command(101, "达弗3")
    text = str(reply)
    assert text.splitlines()[0] == "达弗 · 第三层 Ancient 遗物选择率排行"
    rows = [line for line in text.splitlines()[1:] if line.strip()]
    assert len(rows) == 2
    assert rows[0] == "1. 幻想遗物甲 —— 54%"


# 9. Multi-layer NPC prompt ---------------------------------------------------

def test_bare_darv_prompts_available_layers(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    reply = bot.route_group_command(101, "达弗")
    assert str(reply) == "达弗有多个可查询层：\n达弗2\n达弗3"


# 10. Single-act NPC bare name returns the full board --------------------------

def test_bare_neow_returns_unique_full_board(monkeypatch):
    patch_ancient(monkeypatch, neow_snapshot())
    reply = bot.route_group_command(101, "涅奥")
    text = str(reply)
    assert text.splitlines()[0] == "涅奥 · 第一层 Ancient 遗物选择率排行"
    assert "1. 幻想遗物甲 —— 76%" in text
    assert "排行1" not in text


# 11. NPC + invalid layer -> valid-layer hint ---------------------------------

def test_npc_invalid_layer_gets_valid_layer_hint(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    reply = bot.route_group_command(101, "达弗1")
    assert str(reply) == "达弗有多个可查询层：\n达弗2\n达弗3"

    patch_ancient(monkeypatch, neow_snapshot())
    reply = bot.route_group_command(101, "涅奥2")
    assert str(reply) == "涅奥目前只有第一层的数据。\n可发送：涅奥"
    assert "错误" not in str(reply) and "报错" not in str(reply)


# 12-14. Old Ancient syntax ----------------------------------------------------

def test_darv2_paihang_old_syntax_stays_compatible(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    main = str(bot.route_group_command(101, "达弗2"))
    compat = str(bot.route_group_command(101, "达弗2排行"))
    assert compat == main
    assert "达弗 · 第二层 Ancient 遗物选择率排行" in compat


@pytest.mark.parametrize("command", ["达弗2最高", "达弗2 最高", "达弗2最低", "达弗2 最低"])
def test_ancient_top_and_bottom_no_longer_enter_leaderboard(monkeypatch, command):
    patch_ancient(monkeypatch, darv_snapshot())
    reply = bot.route_group_command(101, command)
    text = str(reply)
    assert "选择排行" not in text
    assert "最高 5" not in text and "最低 5" not in text
    assert "当前没有进行中的游戏" in text


# 15-16. STS2 Ancient single relic copy -----------------------------------------

def test_ancient_single_relic_uses_layer_and_is_compressed(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    relic = make_ancient_relic("F_A")
    reply = renderer.render_relic_query_reply([relic])
    text = str(reply)
    assert "达弗 · 第二层：约58%会选，选择率第1 / 6。" in text
    assert "出现时约" not in text
    assert "第二幕" not in text


def test_ancient_single_relic_multicontext_stays_per_line(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    relic = make_ancient_relic("F_A")
    text = renderer.render_sts2_ancient_choice_stats(relic, darv_snapshot())
    assert text.splitlines() == [
        "达弗 · 第二层：约58%会选，选择率第1 / 6。",
        "达弗 · 第三层：约54%会选，选择率第1 / 2。",
    ]


# 17. STS2 non-Ancient relic shows no statistics -------------------------------

def test_sts2_non_ancient_relic_has_no_stats(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    relic = make_ancient_relic("F_C", tier="Uncommon")
    reply = str(renderer.render_relic_query_reply([relic]))
    assert "罕见遗物" in reply
    assert "选择率" not in reply and "出现时约" not in reply


# 18. Relic images keep flowing through the query reply ------------------------

def test_relic_query_reply_keeps_image_path(monkeypatch):
    fake = Path("C:/fake/relics/sts1/SOZU.png")
    monkeypatch.setattr(renderer, "resolve_local_relic_image", lambda relic: fake)
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: {})
    reply = renderer.render_relic_query_reply([make_boss_relic()])
    assert reply.image_path == fake
    assert reply.image_paths == (fake,)


# 19. Whitespace normalization keeps working for relic boards -------------------

def test_boss_spaced_spelling_equals_compact(monkeypatch):
    snapshot, zh = full_boss_snapshot()
    patch_boss(monkeypatch, snapshot, zh)
    assert str(bot.route_group_command(101, "Boss 遗物 1")) == str(
        bot.route_group_command(101, "Boss1")
    )
    assert str(bot.route_group_command(101, "Boss1")) == str(
        bot.route_group_command(101, "BOSS 1")
    )


def test_ancient_spaced_spelling_equals_compact(monkeypatch):
    patch_ancient(monkeypatch, darv_snapshot())
    assert str(bot.route_group_command(101, "达弗 2")) == str(
        bot.route_group_command(101, "达弗2")
    )
    assert str(bot.route_group_command(101, "达弗2 排行")) == str(
        bot.route_group_command(101, "达弗2排行")
    )


# 20. Card router unaffected ----------------------------------------------------

def test_card_layer_board_routing_unaffected(monkeypatch):
    snapshot = {
        "cards": {
            "A": {
                "name": "虚甲",
                "color": "watcher",
                "rarity": "Common",
                "metrics": {
                    lb.STS1_ASC7PLUS_SOURCE_ID: {
                        "character_pick_contexts": {
                            "watcher": {
                                "act_1": {"offered_count": 100, "picked_count": 90}
                            }
                        }
                    }
                },
            }
        }
    }
    monkeypatch.setattr(
        lb, "_load_unified_snapshot", lambda game: snapshot if game == "sts1" else {}
    )
    reply = bot.route_group_command(101, "观者1普通")
    text = str(reply)
    assert "观者 · 第一层 · 普通卡选择率排行" in text
    assert "1. 虚甲 —— 90.0%" in text

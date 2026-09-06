"""Short relic summaries for STS1 Boss / STS2 Ancient full leaderboards.

Descriptions are literal copies of the official Chinese effect text already
present in the local data fixtures.  No network or private user data is used.
"""

from __future__ import annotations

from card_guess.qq import renderer


def _summary(description, relic_id, game):
    from card_guess.qq.relic_short_summary import short_relic_effect

    return short_relic_effect(
        description,
        relic_id=relic_id,
        game=game,
    )


def _override_keys():
    from card_guess.qq.relic_short_summary import RELIC_SHORT_SUMMARY_OVERRIDES

    return set(RELIC_SHORT_SUMMARY_OVERRIDES)


def test_representative_real_effects_keep_core_semantics():
    cases = [
        ("SACREDBARK", "sts1", "药水的效果翻倍。", ["药水的效果翻倍"]),
        (
            "HOLYWATER",
            "sts1",
            "在每场战斗开始时，将 3 张 奇迹 放入你的手牌。",
            ["战斗开始时", "3张奇迹", "手牌"],
        ),
        (
            "BLESSED_ANTLER",
            "sts2",
            "在每回合开始时获得[E]。在战斗开始时，将3张晕眩放入你的抽牌堆。",
            ["回合开始", "能量", "战斗开始", "3张晕眩", "抽牌堆"],
        ),
        (
            "LEAFY_POULTICE",
            "sts2",
            "拾起时，变化你的1张打击和1张防御，然后失去12点最大生命。",
            ["拾起", "变化1张打击和1张防御", "失去12点最大生命"],
        ),
        ("GOLDEN_PEARL", "sts2", "拾起时，获得150金币。", ["拾起", "150金币"]),
        (
            "DIAMOND_DIADEM",
            "sts2",
            "如果你在本回合打出的牌少于等于2张，则受到敌人的伤害减半。",
            ["少于等于2张", "伤害减半"],
        ),
        (
            "TOY_BOX",
            "sts2",
            "拾起时，获得4件蜡制遗物。每经过3场战斗，你最左侧的蜡制遗物将会融化。",
            ["4件蜡制遗物", "每经过3场战斗", "融化"],
        ),
        (
            "BLACK_STAR",
            "sts1",
            "精英 敌人在被打败时多掉落一件 遗物 。",
            ["精英", "多掉落一件遗物"],
        ),
        ("DUSTY_TOME", "sts2", "拾起时，获得一张先古牌。", ["拾起", "先古牌"]),
        (
            "TINY_HOUSE",
            "sts1",
            "拾起时，获得 1 瓶药水。\n"
            "获得 ?  金币 。\n"
            "将你的最大生命值提升 5 。\n"
            "获得 1 张牌。\n"
            "随机升级 1 张牌。小小的屋子！",
            ["1瓶药水", "金币", "最大生命值", "随机升级"],
        ),
    ]

    for relic_id, game, description, required in cases:
        summary = _summary(description, relic_id, game)
        assert summary, (relic_id, game)
        for fragment in required:
            assert fragment in summary, (relic_id, game, summary)


def test_summaries_do_not_add_evaluation_or_advice_language():
    descriptions = [
        ("BLACK_STAR", "sts1", "精英 敌人在被打败时多掉落一件 遗物 。"),
        (
            "LEAFY_POULTICE",
            "sts2",
            "拾起时，变化你的1张打击和1张防御，然后失去12点最大生命。",
        ),
        (
            "BLESSED_ANTLER",
            "sts2",
            "在每回合开始时获得[E]。在战斗开始时，将3张晕眩放入你的抽牌堆。",
        ),
        ("SILKEN_TRESS", "sts2", "拾起时，失去所有金币。为第一次卡牌奖励中的所有牌附魔：华彩。"),
        (
            "TINY_HOUSE",
            "sts1",
            "拾起时，获得 1 瓶药水。\n"
            "获得 ?  金币 。\n"
            "将你的最大生命值提升 5 。\n"
            "获得 1 张牌。\n"
            "随机升级 1 张牌。小小的屋子！",
        ),
    ]
    banned = ("推荐", "建议", "强", "弱", "必选", "必拿", "垃圾")

    for relic_id, game, description in descriptions:
        summary = _summary(description, relic_id, game)
        for word in banned:
            assert word not in summary, (relic_id, summary)


def test_complex_messy_official_text_has_explicit_override():
    overrides = _override_keys()

    assert ("sts1", "TINY_HOUSE") in overrides
    assert ("sts1", "CALLING_BELL") in overrides

    summary = _summary(
        "获得一个独特的 诅咒 和 3 件 遗物 。铃铛鸣响……跳过奖励关闭",
        "CALLING_BELL",
        "sts1",
    )
    assert "独特诅咒" in summary
    assert "3件遗物" in summary
    assert "铃铛鸣响" not in summary


def test_boss_and_ancient_leaderboards_render_summaries(monkeypatch):
    boss_relic = {
        "id": "BLACK_STAR",
        "name": "黑星",
        "description": "精英 敌人在被打败时多掉落一件 遗物 。",
    }
    monkeypatch.setattr(
        renderer,
        "boss_choice_act_rows",
        lambda snapshot, act: [{"relic_id": "BLACK_STAR", "rank": 1, "pick_rate": 50.8}],
    )
    monkeypatch.setattr(
        renderer,
        "load_sts1_relic_zh_names",
        lambda: {"BLACK_STAR": "黑星"},
    )
    monkeypatch.setattr(
        renderer,
        "load_relics",
        lambda game: [boss_relic] if game == "sts1" else [],
    )

    boss_line = renderer.render_sts1_boss_leaderboard(1, snapshot={}).splitlines()[1]
    assert boss_line.startswith("1. 黑星 —— 50.8%｜")
    assert "多掉落一件遗物" in boss_line

    snapshot = {
        "ancient_choice": {
            "npc_names_zh": {"NEOW": "涅奥"},
            "relic_names_zh": {"SILKEN_TRESS": "华美发束"},
        }
    }
    monkeypatch.setattr(
        renderer,
        "leaderboard_npc_acts",
        lambda snap, npc_id: [1],
    )
    monkeypatch.setattr(
        renderer,
        "leaderboard_contexts",
        lambda snap, npc_id, act: [
            {"relic_id": "SILKEN_TRESS", "rank": 1, "picked_rate": 76}
        ],
    )
    ancient_relic = {
        "id": "SILKEN_TRESS",
        "name": "华美发束",
        "description": "拾起时，失去所有金币。为第一次卡牌奖励中的所有牌附魔：华彩。",
    }
    monkeypatch.setattr(
        renderer,
        "load_relics",
        lambda game: [ancient_relic] if game == "sts2" else [],
    )

    ancient_line = renderer.render_ancient_choice_leaderboard(
        "NEOW", 1, snapshot=snapshot
    ).splitlines()[1]
    assert ancient_line.startswith("1. 华美发束 —— 76%｜")
    assert "华彩" in ancient_line


def test_leaderboard_without_summary_falls_back_to_rate_only(monkeypatch):
    monkeypatch.setattr(
        renderer,
        "boss_choice_act_rows",
        lambda snapshot, act: [{"relic_id": "UNKNOWN", "rank": 1, "pick_rate": 60.0}],
    )
    monkeypatch.setattr(
        renderer,
        "load_sts1_relic_zh_names",
        lambda: {"UNKNOWN": "未知遗物"},
    )
    monkeypatch.setattr(renderer, "load_relics", lambda game: [])

    line = renderer.render_sts1_boss_leaderboard(1, snapshot={}).splitlines()[1]

    assert line == "1. 未知遗物 —— 60.0%"
    assert "｜" not in line


def test_overlong_leaderboard_row_folds_summary_to_second_line(monkeypatch):
    monkeypatch.setattr(
        renderer,
        "boss_choice_act_rows",
        lambda snapshot, act: [{"relic_id": "TINY_HOUSE", "rank": 1, "pick_rate": 31.0}],
    )
    monkeypatch.setattr(
        renderer,
        "load_sts1_relic_zh_names",
        lambda: {"TINY_HOUSE": "小屋子"},
    )
    monkeypatch.setattr(
        renderer,
        "load_relics",
        lambda game: [
            {
                "id": "TINY_HOUSE",
                "name": "小屋子",
                "description": (
                    "拾起时，获得 1 瓶药水。\n"
                    "获得 ?  金币 。\n"
                    "将你的最大生命值提升 5 。\n"
                    "获得 1 张牌。\n"
                    "随机升级 1 张牌。小小的屋子！"
                ),
            }
        ]
        if game == "sts1"
        else [],
    )

    lines = renderer.render_sts1_boss_leaderboard(1, snapshot={}).splitlines()

    assert lines[1] == "1. 小屋子 —— 31.0%"
    assert lines[2].startswith("  拾起：")
    assert "｜" not in lines[1]


def test_single_relic_query_still_shows_full_effect(monkeypatch):
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})
    relic = {
        "game": "sts2",
        "id": "FICTIONAL",
        "name": "虚构遗物",
        "name_en": "Fictional",
        "description": "这是一句完整的官方效果文本，单遗物查询必须原样保留。",
        "description_en": "Full fictional effect text.",
        "tier": "Uncommon",
        "color": None,
    }

    reply = str(renderer.render_relic_query_reply([relic]))

    assert "这是一句完整的官方效果文本，单遗物查询必须原样保留。" in reply
    assert "｜" not in reply

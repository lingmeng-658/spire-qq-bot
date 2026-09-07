"""Fictional tests for the STS1/STS2 Top-10 leaderboards (抓取/胜率).

Ranking and copy logic are tested with fabricated cards + fabricated unified
snapshots so results never depend on the real snapshot ranking.  Retired QQ
routing is covered by the Command UX test file instead.

A-D scope:
- STS1 bare 抓取/胜率 = global boards (whole-run pick_rate / win_delta)
- STS1 抓取1/2/3、胜率1/2/3 = per-act boards
- STS2 only 抓取1/2/3、胜率1/2/3; bare 抓取/胜率 is rejected up-front
- 终局 leaderboards are retired on both generations
"""
import pytest

from card_guess import leaderboard as lb

def _metric(value, unit="percent"):
    return {"value": value, "unit": unit, "sample_size": 100}


def _win_metric(value, denominator=30, comparison_denominator=30, unit="percentage_points"):
    return {
        "value": value,
        "unit": unit,
        "provenance": "computed",
        "numerator": max(0, denominator // 2),
        "denominator": denominator,
        "comparison_numerator": 0,
        "comparison_denominator": comparison_denominator,
        "sample_size": denominator + comparison_denominator,
    }


def _sts1_source(pick=None, win=None, presence=None):
    """Spec: pick = global pick_rate value; win = global win_delta value."""
    source = {}
    if presence is not None:
        source["final_deck_presence_rate"] = _metric(presence)
    if pick is not None:
        source["pick_rate"] = _metric(pick)
    if win is not None:
        source["win_delta"] = _win_metric(win)
    return source


def _sts1_entry(card_id, pool, name, pick=None, win=None, presence=None):
    return {
        "name": name,
        "metrics": {
            lb.STS1_ASC7PLUS_SOURCE_ID: _sts1_source(pick, win, presence),
        },
    }


def _sts1_unified(specs):
    """specs: (card_id, pool, name, pick, win, presence)."""
    cards = {}
    for card_id, pool, name, pick, win, presence in specs:
        cards[card_id] = _sts1_entry(card_id, pool, name, pick, win, presence)
    return {"cards": cards}


def _sts2_entry(pick, delta, presence):
    untapped = {}
    if pick is not None:
        untapped["act_pick_rate"] = {"act_1": _metric(pick)}
    if delta is not None:
        untapped["act_win_delta"] = {"act_1": _metric(delta, "percentage_points")}
    entry = {"metrics": {}}
    if untapped:
        entry["metrics"]["untapped"] = untapped
    if presence is not None:
        entry["metrics"]["spire_codex"] = {
            "final_deck_presence_rate": _metric(presence),
        }
    return entry


def _sts2_unified(specs):
    cards = {}
    for card_id, pool, name, pick, delta, presence in specs:
        entry = _sts2_entry(pick, delta, presence)
        entry["name"] = name
        cards[card_id] = entry
    return {"cards": cards}


STS1_SPECS = [
    ("IRON_A", "ironclad", "燃烧", 95.0, 4.2, 9.10),
    ("IRON_B", "ironclad", "撕裂", 88.0, 2.1, 8.20),
    ("IRON_C", "ironclad", "痛击", 84.0, 1.0, 7.30),
    ("IRON_D", "ironclad", "顺劈", 80.0, -1.2, 6.40),
    ("IRON_E", "ironclad", "重刃", 75.0, -3.5, 5.50),
    ("IRON_F", "ironclad", "飞剑", 70.0, 0.4, 4.60),
    ("IRON_G", "ironclad", "双刃", 66.0, 2.9, 3.70),
    ("IRON_H", "ironclad", "战吼", 55.0, -4.1, 2.80),
    ("IRON_I", "ironclad", "洗牌", 40.0, 1.5, 1.90),
    ("IRON_J", "ironclad", "断魂", 33.0, -0.8, 1.00),
    ("IRON_K", "ironclad", "无痛", None, 0.0, 0.30),
    ("IRON_L", "ironclad", "堕落", 5.0, -9.0, 0.05),
    ("SIL_A", "silent", "毒雾", 92.0, 3.3, 9.90),
    ("SIL_B", "silent", "影袭", 1.0, -2.2, 0.01),
]
STS1_CARDS = [
    {"id": card_id, "pool": pool, "name": name}
    for card_id, pool, name, _p, _w, _f in STS1_SPECS
]
STS1_UNIFIED = _sts1_unified(STS1_SPECS)

STS2_SPECS = [
    ("NEC_A", "necrobinder", "骨甲", 86.0, 5.5, 12.31),
    ("NEC_B", "necrobinder", "死鞭", 60.0, -1.0, 8.00),
    ("REG_A", "regent", "王令", 40.0, 0.5, 3.03),
    ("REG_B", "regent", "封赏", None, None, None),
    ("SIL2_A", "silent", "毒雾", 20.0, -4.0, 1.11),
]
STS2_CARDS = [
    {"id": card_id, "pool": pool, "name": name}
    for card_id, pool, name, _p, _d, _f in STS2_SPECS
]
STS2_UNIFIED = _sts2_unified(STS2_SPECS)


@pytest.fixture(autouse=True)
def patch_loaders(monkeypatch):
    monkeypatch.setattr(
        lb,
        "_load_unified_snapshot",
        lambda game: STS1_UNIFIED if game == "sts1" else STS2_UNIFIED,
    )
    monkeypatch.setattr(
        lb,
        "load_cards",
        lambda game: STS1_CARDS if game == "sts1" else STS2_CARDS,
    )
    yield


# ---------------------------------------------------------------- parse layer

def test_parse_leaderboard_keyword_global_and_acts():
    assert lb.parse_leaderboard_keyword("抓取") == ("抓取", None)
    assert lb.parse_leaderboard_keyword("抓取1") == ("抓取", 1)
    assert lb.parse_leaderboard_keyword("抓取2") == ("抓取", 2)
    assert lb.parse_leaderboard_keyword("抓取3") == ("抓取", 3)
    assert lb.parse_leaderboard_keyword("胜率") == ("胜率", None)
    assert lb.parse_leaderboard_keyword("胜率2") == ("胜率", 2)
    assert lb.parse_leaderboard_keyword("胜率3") == ("胜率", 3)
    for invalid in ("终局", "抓取4", "胜率4", "抓取0", "传说"):
        assert lb.parse_leaderboard_keyword(invalid) is None
    assert lb.parse_leaderboard_keyword(None) is None


def test_keyword_heading_global_and_act():
    assert lb.keyword_heading("抓取") == "全局抓取率"
    assert lb.keyword_heading("胜率") == "全局胜率差"
    assert lb.keyword_heading("抓取", 1) == "第一幕抓取率"
    assert lb.keyword_heading("胜率", 3) == "第三幕胜率差"


# ---------------------------------------------------------------- STS1 boards

def test_sts1_global_pick_board_no_role_top_10_descending():
    text = lb.build_leaderboard_reply("1", "抓取")
    assert "=== STS1 · 全部角色 · 全局抓取率 Top 10 ===" in text
    assert "1. 燃烧  95.0%" in text
    assert "2. 毒雾  92.0%" in text
    assert "3. 撕裂  88.0%" in text
    assert "10. 洗牌  40.0%" in text
    assert "断魂" not in text
    assert "堕落" not in text
    assert "影袭" not in text
    assert "无痛" not in text
    assert "11." not in text


def test_sts1_role_filter_uses_alias():
    text = lb.build_leaderboard_reply("1", "抓取", role="战士")
    assert "=== STS1 · 铁甲战士 · 全局抓取率 Top 10 ===" in text
    assert "1. 燃烧  95.0%" in text
    assert "10. 断魂  33.0%" in text
    assert "毒雾" not in text
    assert "影袭" not in text


def test_sts1_global_win_delta_board_formats_and_disclaimer():
    text = lb.build_leaderboard_reply("1", "胜率")
    assert "=== STS1 · 全部角色 · 全局胜率差 Top 10 ===" in text
    assert "1. 燃烧  +4.2 个百分点" in text
    assert "统计关联" in text
    assert "因果" in text

    pick = lb.build_leaderboard_reply("1", "抓取")
    assert "因果" not in pick


def test_global_board_reads_whole_run_metric_not_acts():
    cards = [
        {"id": "G1", "pool": "silent", "name": "全局甲"},
        {"id": "G2", "pool": "silent", "name": "全局乙"},
    ]
    unified = {
        "cards": {
            "G1": {
                "name": "全局甲",
                "metrics": {
                    lb.STS1_ASC7PLUS_SOURCE_ID: {
                        "pick_rate": _metric(50.0),
                        "act_pick_rate": {"act_1": _metric(90.0)},
                        "win_delta": _win_metric(1.0),
                    }
                },
            },
            "G2": {
                "name": "全局乙",
                "metrics": {
                    lb.STS1_ASC7PLUS_SOURCE_ID: {
                        "pick_rate": _metric(10.0),
                        "act_pick_rate": {"act_1": _metric(99.0)},
                        "win_delta": _win_metric(9.0),
                    }
                },
            },
        }
    }
    global_rows = lb.build_rankings("sts1", "抓取", cards=cards, unified=unified)
    assert [(row.card_id, row.value) for row in global_rows] == [("G1", 50.0), ("G2", 10.0)]
    act_rows = lb.build_rankings("sts1", "抓取", cards=cards, unified=unified, act=1)
    assert [(row.card_id, row.value) for row in act_rows] == [("G2", 99.0), ("G1", 90.0)]
    win_rows = lb.build_rankings("sts1", "胜率", cards=cards, unified=unified)
    assert [(row.card_id, row.value) for row in win_rows] == [("G2", 9.0), ("G1", 1.0)]


# ---------------------------------------------------------------- act boards

def _multi_act_unified(specs):
    """specs: (card_id, name, pool, picks, wins).

    picks is {act: value}; wins is {act: (value, denom, comp)}.
    """
    cards = {}
    for card_id, name, pool, picks, wins in specs:
        source = {}
        if picks:
            source["pick_rate"] = _metric(max(picks.values()))
            source["act_pick_rate"] = {
                f"act_{act}": _metric(value) for act, value in picks.items()
            }
        if wins:
            source["win_delta"] = _win_metric(max(w[0] for w in wins.values()))
            source["act_win_delta"] = {
                f"act_{act}": _win_metric(value, denom, comp)
                for act, (value, denom, comp) in wins.items()
            }
        cards[card_id] = {
            "name": name,
            "metrics": {lb.STS1_ASC7PLUS_SOURCE_ID: source},
        }
    return {"cards": cards}


MULTI_ACT_CARDS = [
    {"id": "ALPHA", "pool": "silent", "name": "甲影"},
    {"id": "BETA", "pool": "silent", "name": "乙刃"},
]


def test_pick_rankings_use_requested_act():
    unified = _multi_act_unified(
        [
            ("ALPHA", "甲影", "silent", {1: 90.0, 2: 10.0, 3: 20.0}, {}),
            ("BETA", "乙刃", "silent", {1: 80.0, 2: 85.0, 3: 5.0}, {}),
        ]
    )
    act1 = lb.build_rankings("sts1", "抓取", role_pool="silent", act=1,
                             cards=MULTI_ACT_CARDS, unified=unified)
    act2 = lb.build_rankings("sts1", "抓取", role_pool="silent", act=2,
                             cards=MULTI_ACT_CARDS, unified=unified)
    assert [(row.card_id, row.value) for row in act1] == [("ALPHA", 90.0), ("BETA", 80.0)]
    assert [(row.card_id, row.value) for row in act2] == [("BETA", 85.0), ("ALPHA", 10.0)]


def test_win_guard_applies_to_requested_act():
    unified = _multi_act_unified(
        [
            (
                "ALPHA",
                "甲影",
                "silent",
                {},
                {1: (5.0, 40, 40), 2: (50.0, 5, 100), 3: (2.0, 30, 30)},
            ),
            (
                "BETA",
                "乙刃",
                "silent",
                {},
                {1: (4.0, 40, 40), 2: (1.0, 40, 40), 3: (8.0, 40, 40)},
            ),
        ]
    )
    act1 = lb.build_rankings("sts1", "胜率", role_pool="silent", act=1,
                             cards=MULTI_ACT_CARDS, unified=unified)
    act2 = lb.build_rankings("sts1", "胜率", role_pool="silent", act=2,
                             cards=MULTI_ACT_CARDS, unified=unified)
    act3 = lb.build_rankings("sts1", "胜率", role_pool="silent", act=3,
                             cards=MULTI_ACT_CARDS, unified=unified)
    assert [(row.card_id, row.value) for row in act1] == [("ALPHA", 5.0), ("BETA", 4.0)]
    assert [(row.card_id, row.value) for row in act2] == [("BETA", 1.0)]
    assert [(row.card_id, row.value) for row in act3] == [("BETA", 8.0), ("ALPHA", 2.0)]


# ------------------------------------------------- global win small-sample guard

def test_global_win_delta_small_sample_guard_skips_rows():
    cards = [
        {"id": "SMALL_A", "pool": "ironclad", "name": "极端小样"},
        {"id": "BIG_C", "pool": "ironclad", "name": "稳健卡"},
    ]
    unified = {
        "cards": {
            "SMALL_A": {
                "name": "极端小样",
                "metrics": {
                    lb.STS1_ASC7PLUS_SOURCE_ID: {
                        "pick_rate": _metric(10.0),
                        "win_delta": _win_metric(90.0, 5, 5),
                        "act_win_delta": {},
                    }
                },
            },
            "BIG_C": {
                "name": "稳健卡",
                "metrics": {
                    lb.STS1_ASC7PLUS_SOURCE_ID: {
                        "pick_rate": _metric(12.0),
                        "win_delta": _win_metric(40.0, 30, 30),
                        "act_win_delta": {},
                    }
                },
            },
        }
    }
    win_rows = lb.build_rankings("sts1", "胜率", cards=cards, unified=unified)
    assert [row.card_id for row in win_rows] == ["BIG_C"]
    pick_rows = lb.build_rankings("sts1", "抓取", cards=cards, unified=unified)
    assert [row.card_id for row in pick_rows] == ["BIG_C", "SMALL_A"]


def test_sts2_win_board_is_not_guarded_by_cohort_denominators():
    cards = [{"id": "REG_X", "pool": "regent", "name": "御令"}]
    unified = _sts2_unified([("REG_X", "regent", "御令", 30.0, 3.0, None)])

    rows = lb.build_rankings("sts2", "胜率", cards=cards, unified=unified, act=1)

    assert [(row.card_id, row.value) for row in rows] == [("REG_X", 3.0)]


# ------------------------------------------------------------ STS2 capability

def test_sts2_bare_metric_rejected_before_role_pool_lookup():
    for keyword in ("抓取", "胜率"):
        assert lb.build_leaderboard_reply("2", keyword) == lb.STS2_GLOBAL_NOTICE
        for role in (None, "骨妹", "储君", "幽灵"):
            assert lb.build_leaderboard_reply("2", keyword, role=role) == (
                lb.STS2_GLOBAL_NOTICE
            )


def test_sts2_act_board_still_works():
    text = lb.build_leaderboard_reply("2", "抓取1", role="储君")
    assert "=== STS2 · 储君 · 第一幕抓取率 Top 10 ===" in text
    assert "1. 王令  40.0%" in text
    assert "骨甲" not in text


# ------------------------------------------------------------ terminal boards removed

def test_final_board_removed_for_both_generations():
    for tag in ("1", "2"):
        reply = lb.build_leaderboard_reply(tag, "终局")
        assert "该榜单已取消" in reply
        assert "抓取/胜率" in reply
def test_final_keyword_rejected_by_rankings():
    with pytest.raises(ValueError):
        lb.build_rankings("sts1", "终局")
    with pytest.raises(ValueError):
        lb.build_rankings("sts2", "终局")


# ------------------------------------------------------------ missing/tie/limit

def test_missing_values_skipped_not_zero_filled():
    rows = lb.build_rankings("sts1", "抓取", role_pool="ironclad")
    names = [row.name for row in rows]
    assert "无痛" not in names  # pick_rate is None -> skipped
    assert len(names) == 10
    assert "堕落" not in names  # only 10 rows, never zero-filled extras


def test_short_list_ranks_available_only():
    rows = lb.build_rankings("sts1", "抓取", role_pool="silent")
    assert [row.rank for row in rows] == [1, 2]
    assert [row.name for row in rows] == ["毒雾", "影袭"]


def test_tie_break_is_deterministic_by_card_id():
    cards = [
        {"id": "TIE_AA", "pool": "ironclad", "name": "快刀"},
        {"id": "TIE_AB", "pool": "ironclad", "name": "慢刀"},
    ]
    unified = _sts1_unified(
        [
            ("TIE_AA", "ironclad", "快刀", 50.0, 0.0, 1.0),
            ("TIE_AB", "ironclad", "慢刀", 50.0, 0.0, 1.0),
        ]
    )
    first = lb.build_rankings("sts1", "抓取", cards=cards, unified=unified)
    second = lb.build_rankings("sts1", "抓取", cards=cards, unified=unified)
    assert [row.card_id for row in first] == ["TIE_AA", "TIE_AB"]
    assert [row.card_id for row in second] == ["TIE_AA", "TIE_AB"]
def test_build_rankings_rejects_unknown_game_or_keyword():
    with pytest.raises(ValueError):
        lb.build_rankings("sts3", "抓取")
    with pytest.raises(ValueError):
        lb.build_rankings("sts1", "传说")
    with pytest.raises(ValueError):
        lb.build_rankings("sts2", "抓取")  # STS2 has no global scope
HEART_CARDS = [
    {"id": "HEART_SILENT", "pool": "silent", "name": "毒雾"},
    {"id": "HEART_SILENT2", "pool": "silent", "name": "影袭"},
    {"id": "HEART_IRON", "pool": "ironclad", "name": "燃烧"},
    {"id": "HEART_NO_DATA", "pool": "silent", "name": "无数据"},
]
HEART_VALUES = {
    "HEART_SILENT": 33.33,
    "HEART_SILENT2": 85.5,
    "HEART_IRON": 12.34,
}


def _heart_unified():
    cards = {}
    for card in HEART_CARDS:
        card_id = card["id"]
        source = {}
        if card_id in HEART_VALUES:
            source["heart_win_deck_presence_rate"] = _metric(HEART_VALUES[card_id])
        cards[card_id] = {
            "name": card["name"],
            "metrics": {lb.STS1_ASC7PLUS_SOURCE_ID: source},
        }
    return {"cards": cards}


def test_keyword_heading_supports_heart():
    assert lb.keyword_heading("心脏") == "心脏胜利卡组"
    with pytest.raises(ValueError):
        lb.keyword_heading("心脏", 1)


def test_heart_board_skips_missing_and_ranks_descending():
    rows = lb.build_rankings("sts1", "心脏", cards=HEART_CARDS, unified=_heart_unified())
    assert [(row.card_id, row.name, row.value) for row in rows] == [
        ("HEART_SILENT2", "影袭", 85.5),
        ("HEART_SILENT", "毒雾", 33.33),
        ("HEART_IRON", "燃烧", 12.34),
    ]
    with pytest.raises(ValueError):
        lb.build_rankings("sts1", "心脏", cards=HEART_CARDS, unified=_heart_unified(), act=1)
    with pytest.raises(ValueError):
        lb.build_rankings("sts2", "心脏", cards=HEART_CARDS, unified=_heart_unified())
# ------------------------------------------------- heart board starter filtering

def _starter_board_cards_and_unified():
    cards = [
        {"id": "STRIKE_IC", "pool": "ironclad", "name": "打击", "rarity": "Basic"},
        {"id": "BASH", "pool": "ironclad", "name": "痛击", "rarity": "Basic"},
        {"id": "CARN", "pool": "ironclad", "name": "残杀", "rarity": "Uncommon"},
    ]
    values = {
        "STRIKE_IC": (70.0, 90.0),
        "BASH": (60.0, 50.0),
        "CARN": (30.0, 40.0),
    }
    unified = {
        "cards": {
            card["id"]: {
                "name": card["name"],
                "metrics": {
                    lb.STS1_ASC7PLUS_SOURCE_ID: {
                        "pick_rate": _metric(values[card["id"]][0]),
                        "heart_win_deck_presence_rate": _metric(values[card["id"]][1]),
                    }
                },
            }
            for card in cards
        }
    }
    return cards, unified


def test_heart_board_excludes_starter_cards_but_keeps_stats_metric():
    cards, unified = _starter_board_cards_and_unified()
    rows = lb.build_rankings("sts1", "心脏", cards=cards, unified=unified)
    assert [row.card_id for row in rows] == ["CARN"]
    # the underlying metric still exists for starter cards in the source
    source = unified["cards"]["STRIKE_IC"]["metrics"][lb.STS1_ASC7PLUS_SOURCE_ID]
    assert source["heart_win_deck_presence_rate"]["value"] == 90.0


def test_pick_board_is_not_affected_by_starter_filter():
    cards, unified = _starter_board_cards_and_unified()
    rows = lb.build_rankings("sts1", "抓取", cards=cards, unified=unified)
    assert [row.card_id for row in rows] == ["STRIKE_IC", "BASH", "CARN"]


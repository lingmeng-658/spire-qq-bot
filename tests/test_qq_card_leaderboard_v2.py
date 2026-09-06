"""STS1 character x layer x rarity full-cohort QQ leaderboard (新主榜).

Fictional watcher/silent cohorts exercise: rarity-pick prompt for 观者1,
full 观者1普通 board (never Top-N truncated), act / rarity / character
separation, low-sample exclusion, competition ties, empty-cohort safety and
the STS2 no-fake-ranking notice.  All data is fabricated; nothing depends on
the real snapshot.
"""
import pytest

from card_guess import leaderboard as lb
from card_guess.qq import bot

SRC = lb.STS1_ASC7PLUS_SOURCE_ID

NOTICE_STS2 = "二代目前暂无可靠的同类卡牌排行榜。"
EMPTY_LINE = "（该范围暂无可排名的卡牌）"


def _cell(offered, picked):
    return {"offered_count": offered, "picked_count": picked}


def _entry(color, rarity, name, character_cells):
    return {
        "name": name,
        "color": color,
        "rarity": rarity,
        "metrics": {
            SRC: {"character_pick_contexts": character_cells},
        },
    }


def _watcher_entry(rarity, name, act_counts):
    """act_counts: {act_key: (offered, picked)} under the watcher pool."""
    return _entry("watcher", rarity, name, {"watcher": {a: _cell(*c) for a, c in act_counts.items()}})


# watcher Common act_1 rows, ordered by true pick rate.
_W1 = [
    ("虚卡01", (100, 90)),
    ("虚卡02", (100, 80)),
    ("虚卡03", (100, 70)),
    ("虚卡04", (120, 60)),
    ("虚卡05", (100, 50)),
    ("虚卡06", (100, 40)),
    ("虚卡07", (100, 35)),
    ("虚卡08", (100, 30)),
    ("虚卡09", (100, 25)),
    ("虚卡10", (100, 20)),
    ("虚卡11", (100, 15)),
    ("虚卡12", (100, 10)),
]

SNAPSHOT = {
    "cards": {
        f"W_C1_{name}": _watcher_entry("Common", name, {"act_1": counts})
        for name, counts in _W1
    }
}
# Second layer has its own watcher Common cohort.
SNAPSHOT["cards"]["W_C2_FIRST"] = _watcher_entry("Common", "虚构二层首卡", {"act_2": (100, 90)})
SNAPSHOT["cards"]["W_C2_SECOND"] = _watcher_entry("Common", "虚构二层次卡", {"act_2": (100, 40)})
SNAPSHOT["cards"]["W_C2_ONLY"] = _watcher_entry("Common", "虚构二层专属", {"act_2": (100, 55)})
# Low sample: must never enter the cohort board.
SNAPSHOT["cards"]["W_LOW"] = _watcher_entry("Common", "虚构低样本卡", {"act_1": (10, 9)})
# Rarity separation: an Uncommon watcher card only shows on 罕见 boards.
SNAPSHOT["cards"]["W_U1"] = _watcher_entry("Uncommon", "虚构罕见甲", {"act_1": (200, 190)})
SNAPSHOT["cards"]["W_U2"] = _watcher_entry("Uncommon", "虚构罕见乙", {"act_1": (200, 60)})
# Character separation: a silent Common card never appears on watcher boards.
SNAPSHOT["cards"]["S_HIGH"] = _entry(
    "silent", "Common", "虚构静默卡", {"silent": {"act_1": _cell(200, 190)}}
)
# Third-layer Rare cohort is intentionally empty for the safety test.


@pytest.fixture(autouse=True)
def patch_snapshot(monkeypatch):
    monkeypatch.setattr(
        lb,
        "_load_unified_snapshot",
        lambda game: SNAPSHOT if game == "sts1" else {},
    )


def _reply(command, group_id=90001):
    return str(bot.route_group_command(group_id, command))


def test_character_layer_asks_rarity_without_guessing():
    reply = _reply("观者1")
    assert "观者 · 第一层" in reply
    assert "请选择稀有度" in reply
    assert "观者1普通\n观者1罕见\n观者1稀有" in reply
    assert "──" not in reply


def test_alias_spelling_of_prompt_is_canonical():
    assert _reply("紫皮1") == _reply("观者1")


def test_full_common_cohort_board_is_not_top_n_truncated():
    reply = _reply("观者1普通")
    assert "观者 · 第一层 · 普通卡选择率排行" in reply
    assert "1. 虚卡01 —— 90.0%" in reply
    assert "4. 虚卡04 —— 50.0%" in reply
    assert "12. 虚卡12 —— 10.0%" in reply
    assert "Top" not in reply
    assert "第一幕" not in reply


def test_board_hides_internal_fields_and_language():
    reply = _reply("观者1普通")
    for hidden in ("denominator", "sample_size", "offered_count", "picked_count", "强度"):
        assert hidden not in reply


def test_competition_ties_share_rank_and_skip_next():
    reply = _reply("观者1普通")
    assert "4. 虚卡04 —— 50.0%" in reply
    assert "4. 虚卡05 —— 50.0%" in reply
    assert "6. 虚卡06 —— 40.0%" in reply
    assert "5. 虚卡" not in reply


def test_layer_cohorts_do_not_mix():
    second = _reply("观者2普通")
    assert "观者 · 第二层 · 普通卡选择率排行" in second
    assert "1. 虚构二层首卡 —— 90.0%" in second
    assert "2. 虚构二层专属 —— 55.0%" in second
    assert "虚卡01" not in second
    first = _reply("观者1普通")
    assert "虚构二层首卡" not in first


def test_rarity_cohorts_do_not_mix():
    rare_board = _reply("观者1罕见")
    assert "观者 · 第一层 · 罕见卡选择率排行" in rare_board
    assert "1. 虚构罕见甲 —— 95.0%" in rare_board
    assert "2. 虚构罕见乙 —— 30.0%" in rare_board
    assert "虚卡01" not in rare_board
    common_board = _reply("观者1普通")
    assert "虚构罕见甲" not in common_board


def test_character_cohorts_do_not_mix():
    reply = _reply("观者1普通")
    assert "虚构静默卡" not in reply
    silent = _reply("静默猎手1普通")
    assert "观者 · " not in silent
    assert "1. 虚构静默卡 —— 95.0%" in silent


def test_low_sample_card_is_excluded():
    reply = _reply("观者1普通")
    assert "虚构低样本卡" not in reply


def test_empty_cohort_returns_safe_prompt():
    reply = _reply("观者3稀有")
    assert "观者 · 第三层 · 稀有卡选择率排行" in reply
    assert EMPTY_LINE in reply
    assert "1." not in reply


def test_sts2_request_gets_no_fake_ranking():
    for command in ("骨妹1普通", "储君2稀有"):
        reply = _reply(command)
        assert NOTICE_STS2 in reply
        assert "──" not in reply
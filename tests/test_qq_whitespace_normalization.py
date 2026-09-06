"""QQ command whitespace normalization: spaced forms equal compact commands.

Rules exercised through the real router:
- 观者1普通 == 观 者 1 普 通 (new leaderboard family)
- old short board 猎宝 1 抓取 == 猎宝1抓取
- ancient board 达弗 2 排行 == 达弗2排行
- relic/card generation queries keep working for 添水 2 / 黑星 2
- whitespace that still cannot hit a legal command keeps the original
  behaviour (idle: the same unknown-message reply as before).
"""
import pytest

from card_guess import leaderboard as lb
from card_guess.qq import bot
from card_guess.qq.renderer import RenderedReply

SRC = lb.STS1_ASC7PLUS_SOURCE_ID


def _metric(value):
    return {"value": value, "unit": "percent", "sample_size": 100}


MINI_UNIFIED = {
    "cards": {
        "A": {
            "name": "虚甲",
            "metrics": {SRC: {"pick_rate": _metric(66.0)}},
        }
    }
}
MINI_CARDS = [{"id": "A", "pool": "silent", "name": "虚甲"}]


@pytest.fixture(autouse=True)
def idle_session(monkeypatch):
    from card_guess.qq import sessions

    monkeypatch.setattr(sessions, "get", lambda group_id: None)


@pytest.fixture
def patch_old_board(monkeypatch):
    monkeypatch.setattr(lb, "_load_unified_snapshot", lambda game: MINI_UNIFIED if game == "sts1" else MINI_UNIFIED)
    monkeypatch.setattr(lb, "load_cards", lambda game: MINI_CARDS)


@pytest.fixture
def patch_new_board(monkeypatch):
    snapshot = {
        "cards": {
            "A": {
                "name": "虚甲",
                "color": "watcher",
                "rarity": "Common",
                "metrics": {
                    SRC: {
                        "character_pick_contexts": {
                            "watcher": {"act_1": {"offered_count": 100, "picked_count": 90}}
                        }
                    }
                },
            }
        }
    }
    monkeypatch.setattr(lb, "_load_unified_snapshot", lambda game: snapshot if game == "sts1" else {})


def test_new_leaderboard_spacing_is_equivalent(patch_new_board):
    texts = [
        str(bot.route_group_command(91001, command))
        for command in ("观者1普通", "观者 1 普通", "观者1 普通", "观者 1普通", "观 者 1 普 通")
    ]
    assert texts[0] == texts[1] == texts[2] == texts[3] == texts[4]
    assert "观者 · 第一层 · 普通卡选择率排行" in texts[0]
    assert "1. 虚甲 —— 90.0%" in texts[0]


def test_old_short_leaderboard_spacing_is_equivalent(patch_old_board):
    reply_a = str(bot.route_group_command(91002, "猎宝1抓取"))
    reply_b = str(bot.route_group_command(91002, "猎宝1 抓取"))
    reply_c = str(bot.route_group_command(91002, "猎宝 1抓取"))
    reply_d = str(bot.route_group_command(91002, "猎 宝1 抓 取"))
    assert reply_a == reply_b == reply_c == reply_d
    assert "虚甲" in reply_a


def test_ancient_board_spacing_is_equivalent(monkeypatch):
    from card_guess.qq import renderer as qq_renderer

    monkeypatch.setattr(
        qq_renderer,
        "load_sts2_ancient_choice_stats",
        lambda: {"ancient_choice": {"npc_names_zh": {"DARV": "达弗"}}},
    )
    monkeypatch.setattr(
        qq_renderer,
        "render_ancient_choice_leaderboard",
        lambda *args, **kwargs: "达弗排行内容",
    )
    replies = [
        str(bot.route_group_command(91003, command))
        for command in ("达弗2 排行", "达弗 2 排行", "达弗2排行")
    ]
    assert replies[0] == replies[1] == replies[2]
    assert "达弗排行内容" in replies[0]


def test_relic_generation_query_spacing_still_routes(monkeypatch):
    monkeypatch.setattr(bot, "_render_generation_query", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        bot,
        "_render_relic_generation_query",
        lambda name, generation, role=None: RenderedReply(f"relic:{name}{generation}"),
    )
    for command in ("黑星2", "黑星 2"):
        assert str(bot.route_group_command(91004, command)) == "relic:黑星2"
    for command in ("添水2", "添水 2"):
        assert str(bot.route_group_command(91004, command)) == "relic:添水2"


def test_card_generation_query_spacing_still_routes(monkeypatch):
    monkeypatch.setattr(
        bot,
        "_render_generation_query",
        lambda name, generation, role=None: RenderedReply(f"card:{name}{generation}"),
    )
    for command in ("打击2", "打击 2"):
        assert str(bot.route_group_command(91005, command)) == "card:打击2"


def test_whitespace_that_hits_no_command_keeps_original_behaviour():
    expected = str(bot.route_group_command(91006, "完全 不存在的 词"))
    for command in ("完全 不存在的 词", "完 全 不 存 在 的 词", "测试 文字 加空格 123"):
        assert str(bot.route_group_command(91006, command)) == expected
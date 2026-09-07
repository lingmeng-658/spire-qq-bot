# -*- coding: utf-8 -*-
"""Command UX v1: finalized help, routing, aliases, and copy.

All names and snapshots are fictional fixtures; nothing depends on QQ
messages, real run data, or network access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from card_guess.qq import bot, renderer, sessions
from card_guess.qq.renderer import RenderedReply


def make_card(name="虚卡甲", game="sts1", card_id="FAKE_CARD_1"):
    return {
        "name": name,
        "game": game,
        "id": card_id,
        "pool": "ironclad",
        "type": "Attack",
        "cost": 1,
        "star_cost": None,
        "rarity": "Common",
        "description": "造成伤害。",
        "vars": {},
        "upgrade": {},
    }


def make_relic(name="虚遗甲", game="sts1", relic_id="FAKE_RELIC_1"):
    return {
        "name": name,
        "game": game,
        "id": relic_id,
        "name_en": relic_id,
        "description": "虚构遗物效果。",
        "description_en": "fictional",
        "tier": "common",
        "color": None,
    }


def patch_env(
    monkeypatch,
    *,
    cards=(),
    relics=(),
    card_image=None,
    relic_image=None,
):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: list(cards))
    monkeypatch.setattr(bot, "_load_query_relics", lambda: list(relics))
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(renderer, "load_sts1_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr(renderer, "load_sts2_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: {})
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})
    monkeypatch.setattr(renderer, "load_sts2_relic_shop_stats", lambda: {})
    monkeypatch.setattr(renderer, "resolve_local_card_image", lambda card: card_image)
    monkeypatch.setattr(
        renderer,
        "resolve_local_upgraded_card_image",
        lambda card: None,
    )
    monkeypatch.setattr(renderer, "resolve_local_relic_image", lambda relic: relic_image)


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()


def start_game(monkeypatch, card):
    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: [card])
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])
    monkeypatch.setattr(
        sessions,
        "find_opening_reveal_positions",
        lambda description: set(),
    )
    return sessions.start(101, "sts1")


# Homepage help ---------------------------------------------------------------


def test_top_help_aliases_share_one_text(monkeypatch):
    patch_env(monkeypatch)
    for command in ("帮助", "help", "功能"):
        assert str(bot.route_group_command(123, command)) == bot.HELP_TEXT


def test_top_help_keeps_finalized_structure():
    text = bot.HELP_TEXT
    assert "直接发送名字即可查询卡牌 / 遗物" in text
    assert "例：白噪声 / 赤牛" in text
    assert "例：观者1普通 / Boss1 / 达弗2" in text
    assert "注：上面的数字均表示第几层。" in text
    assert "发送「先古遗民」" in text
    assert "可查看所有先古遗民的名字与对应图片" in text
    assert "猜卡：开始" in text
    assert "例：开始2 骨妹" in text
    assert "帮助 查询 · 帮助 猜卡 · 帮助 排行" in text
    assert "两代同名时，在名字最后加 1 / 2 指定代际。" in text
    assert "群聊请 @我，私聊直接发送。" in text
    for banned in ("榜单", "抓取", "胜率", "心脏", "终局", "帮助 查卡"):
        assert banned not in text


def test_only_three_formal_help_subcommands(monkeypatch):
    patch_env(monkeypatch)
    assert set(bot.HELP_SUBCOMMANDS) == {"查询", "猜卡", "排行"}
    for command in ("帮助 查卡", "帮助 题库", "帮助 榜单"):
        reply = str(bot.route_group_command(123, command))
        assert "没有子帮助" in reply
        assert "=== 帮助" not in reply


def test_query_subhelp_text():
    text = bot.HELP_SUBCOMMANDS["查询"]
    assert "直接发卡名或遗物名即可查询" in text
    assert "只在某一代存在 → 直接查询" in text
    assert "两代同名 → 提示加 1 / 2" in text
    assert "空格可以忽略" in text
    assert "不讲拼音 / 模糊匹配" in text


def test_guess_subhelp_text_keeps_only_formal_commands():
    text = bot.HELP_SUBCOMMANDS["猜卡"]
    assert "开始 / 结束" in text
    assert "例：开始2 骨妹" in text
    assert "开始1 无色" in text
    for banned in ("猜词", "猜谜", "开局", "开始游戏", "end"):
        assert banned not in text


def test_rank_subhelp_text_only_promotes_final_entries():
    text = bot.HELP_SUBCOMMANDS["排行"]
    assert "观者1" in text
    assert "观者1普通" in text
    assert "Boss1" in text
    assert "Boss2" in text
    assert "先古遗民" in text
    assert "达弗2" in text
    assert "涅奥" in text
    assert "上面的数字均表示第几层。" in text
    for banned in ("Top", "抓取", "胜率", "心脏", "榜单", "终局"):
        assert banned not in text


# Retired commands ------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    ["猜词", "猜词1", "猜谜", "猜谜2", "开局", "开局2", "开始游戏", "开始游戏1", "end"],
)
def test_retired_start_and_end_words_no_longer_start_or_end(monkeypatch, command):
    calls = []
    monkeypatch.setattr(sessions, "start", lambda *args, **kwargs: calls.append(args))
    patch_env(monkeypatch)

    reply = str(bot.route_group_command(123, command))

    assert reply == bot.UNKNOWN_COMMAND_REPLY
    assert calls == []


def test_end_does_not_end_active_session(monkeypatch):
    game = start_game(monkeypatch, make_card(name="谜底牌", card_id="ANSWER"))
    monkeypatch.setattr(renderer, "resolve_local_card_image", lambda card: None)

    reply = str(bot.route_group_command(101, "end"))

    assert "本局游戏结束" not in reply
    assert game.ended is False
    assert sessions.get(101) is game


@pytest.mark.parametrize(
    "command",
    [
        "榜单1",
        "榜单1 抓取",
        "猎宝1 抓取",
        "战士1 胜率3",
        "骨妹1 心脏",
        "终局",
    ],
)
def test_old_card_leaderboards_no_longer_route(monkeypatch, command):
    patch_env(monkeypatch)

    reply = str(bot.route_group_command(123, command))

    assert reply == bot.UNKNOWN_COMMAND_REPLY
    assert "选择率排行" not in reply
    assert "Top" not in reply


@pytest.mark.parametrize("command", ["Boss遗物1", "Boss遗物2"])
def test_boss_relic_aliases_no_longer_route(monkeypatch, command):
    patch_env(monkeypatch)

    reply = str(bot.route_group_command(123, command))

    assert reply == bot.UNKNOWN_COMMAND_REPLY
    assert "Boss 遗物选择率排行" not in reply


@pytest.mark.parametrize("command", ["达弗2排行", "达弗2 排行2"])
def test_ancient_paihang_compatibility_no_longer_routes(monkeypatch, command):
    patch_env(monkeypatch)
    monkeypatch.setattr(
        renderer,
        "load_sts2_ancient_choice_stats",
        lambda: {"ancient_choice": {"npc_names_zh": {"DARV": "达弗"}}},
    )

    reply = str(bot.route_group_command(123, command))

    assert reply == bot.UNKNOWN_COMMAND_REPLY
    assert "Ancient 遗物选择率排行" not in reply


# Generation behavior for cards and relics ------------------------------------


def test_no_suffix_sts1_only_card_queries_directly(monkeypatch):
    patch_env(monkeypatch, cards=[make_card(name="虚卡甲", game="sts1")])

    reply = bot.route_group_command(101, "虚卡甲")

    assert isinstance(reply, RenderedReply)
    assert "=== 虚卡甲 · STS1 · 铁甲战士 ===" in reply


def test_no_suffix_sts2_only_card_queries_directly(monkeypatch):
    patch_env(
        monkeypatch,
        cards=[make_card(name="虚卡乙", game="sts2", card_id="FAKE_CARD_2")],
    )

    reply = bot.route_group_command(101, "虚卡乙")

    assert isinstance(reply, RenderedReply)
    assert "=== 虚卡乙 · STS2 · 铁甲战士 ===" in reply


def test_no_suffix_cross_generation_card_prompts_for_generation(monkeypatch):
    cards = [
        make_card(name="虚卡同", game="sts1", card_id="FAKE_CARD_A"),
        make_card(name="虚卡同", game="sts2", card_id="FAKE_CARD_B"),
    ]
    patch_env(monkeypatch, cards=cards)

    reply = str(bot.route_group_command(101, "虚卡同"))

    assert reply == "找到两代同名内容：\n虚卡同1\n虚卡同2"
    assert "杀戮尖塔" not in reply
    assert "请发送" not in reply


def test_no_suffix_sts1_only_relic_queries_directly(monkeypatch):
    patch_env(monkeypatch, relics=[make_relic(name="虚遗甲", game="sts1")])

    reply = bot.route_group_command(101, "虚遗甲")

    assert isinstance(reply, RenderedReply)
    assert "=== 虚遗甲 · STS1 ===" in reply


def test_no_suffix_sts2_only_relic_queries_directly(monkeypatch):
    patch_env(
        monkeypatch,
        relics=[make_relic(name="虚遗乙", game="sts2", relic_id="FAKE_RELIC_2")],
    )

    reply = bot.route_group_command(101, "虚遗乙")

    assert isinstance(reply, RenderedReply)
    assert "=== 虚遗乙 · STS2 ===" in reply


def test_no_suffix_cross_generation_relic_prompts_for_generation(monkeypatch):
    relics = [
        make_relic(name="虚遗同", game="sts1", relic_id="FAKE_RELIC_A"),
        make_relic(name="虚遗同", game="sts2", relic_id="FAKE_RELIC_B"),
    ]
    patch_env(monkeypatch, relics=relics)

    reply = str(bot.route_group_command(101, "虚遗同"))

    assert reply == "找到两代同名内容：\n虚遗同1\n虚遗同2"
    assert "找到 2 个同名遗物" not in reply


# Ancient alias ---------------------------------------------------------------


def test_ancient_overview_alias_is_equivalent(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path / "empty-repo")

    main = bot.route_group_command(101, "先古遗民")
    alias = bot.route_group_command(101, "先古之民")

    assert isinstance(main, RenderedReply)
    assert isinstance(alias, RenderedReply)
    assert str(main) == str(alias)
    assert str(main).startswith("先古遗民\n\n")


def test_ancient_alias_spacing_normalizes(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path / "empty-repo")

    assert str(bot.route_group_command(101, "先 古 之 民")) == str(
        bot.route_group_command(101, "先古之民")
    )


# Unknown commands and active sessions ---------------------------------------


def test_unknown_command_uses_short_hint(monkeypatch):
    patch_env(monkeypatch)

    reply = str(bot.route_group_command(101, "完全不存在的输入"))

    assert reply == bot.UNKNOWN_COMMAND_REPLY
    assert "当前没有进行中的游戏" not in reply


def test_unknown_generation_query_uses_short_hint(monkeypatch):
    patch_env(monkeypatch)

    reply = str(bot.route_group_command(101, "不存在的牌2"))

    assert reply == bot.UNKNOWN_COMMAND_REPLY


def test_session_card_name_without_suffix_stays_a_guess(monkeypatch):
    game = start_game(monkeypatch, make_card(name="谜底牌", card_id="ANSWER"))
    cards = [
        make_card(name="虚猜牌", game="sts1", card_id="GUESS_A"),
        make_card(name="虚猜牌", game="sts2", card_id="GUESS_B"),
    ]
    patch_env(monkeypatch, cards=cards)

    reply = str(bot.route_group_command(101, "虚猜牌"))

    assert game.wrong_count == 1
    assert game.wrong_guesses == ["虚猜牌"]
    assert "找到两代同名内容" not in reply
    assert "=== 本轮题目 ===" in reply


def test_session_explicit_suffix_still_forces_query(monkeypatch):
    game = start_game(monkeypatch, make_card(name="谜底牌", card_id="ANSWER"))
    cards = [
        make_card(name="虚猜牌", game="sts1", card_id="GUESS_A"),
        make_card(name="虚猜牌", game="sts2", card_id="GUESS_B"),
    ]
    patch_env(monkeypatch, cards=cards)

    reply = str(bot.route_group_command(101, "虚猜牌2"))

    assert game.wrong_count == 0
    assert game.total_guess_count == 0
    assert sessions.get(101) is game
    assert "=== 虚猜牌 · STS2 · 铁甲战士 ===" in reply
    assert "=== 本轮题目 ===" not in reply


# Channel-neutral copy ---------------------------------------------------------


def test_duplicate_start_reply_is_channel_neutral(monkeypatch):
    sessions.SESSIONS[67890] = object()

    reply = str(bot.route_group_command(67890, "开始"))

    assert reply == "当前会话已有一局"
    assert "本群" not in reply


# STS2 card copy --------------------------------------------------------------


def test_sts2_card_smith_copy_uses_rest_and_hammer_words(monkeypatch):
    card = make_card(name="虚敲牌", game="sts2", card_id="STS2_HAMMER")
    snapshot = {
        "cards": {
            "STS2_HAMMER": {
                "untapped": {
                    "smith": {
                        "act_1": {"upgrade_rate": {"value": 25}},
                        "act_2": {"upgrade_rate": {"value": 14}},
                        "act_3": {"upgrade_rate": {"value": 10}},
                    }
                }
            }
        }
    }
    monkeypatch.setattr(renderer, "load_sts2_card_stats", lambda: snapshot)
    monkeypatch.setattr(renderer, "resolve_local_card_image", lambda c: None)
    monkeypatch.setattr(
        renderer,
        "resolve_local_upgraded_card_image",
        lambda c: None,
    )

    reply = str(renderer.render_card_query_reply([card]))

    assert "休息时：25% / 14% / 10% 会敲牌" in reply
    assert "铁匠铺" not in reply
    assert "会升级" not in reply
    assert "幕" not in reply


# Image and spacing regression -------------------------------------------------


def test_card_image_still_attaches_after_help_rewrite(monkeypatch, tmp_path):
    image = tmp_path / "fake.png"
    image.write_bytes(b"fake")
    patch_env(
        monkeypatch,
        cards=[make_card(name="虚图卡", game="sts1", card_id="IMAGE_CARD")],
        card_image=image,
    )

    reply = bot.route_group_command(101, "虚图卡")

    assert isinstance(reply, RenderedReply)
    assert reply.image_path == image
    assert reply.image_paths == (image,)


def test_relic_image_still_attaches(monkeypatch, tmp_path):
    image = tmp_path / "fake-relic.png"
    image.write_bytes(b"fake")
    patch_env(
        monkeypatch,
        relics=[make_relic(name="虚遗图", game="sts1", relic_id="IMAGE_RELIC")],
        relic_image=image,
    )

    reply = bot.route_group_command(101, "虚遗图")

    assert isinstance(reply, RenderedReply)
    assert reply.image_path == image
    assert reply.image_paths == (image,)

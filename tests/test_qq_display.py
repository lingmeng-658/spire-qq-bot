from pathlib import Path

import pytest

from card_guess.game import GameState
from card_guess.qq import bot, sessions
from card_guess.qq.renderer import RenderedReply


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()


def make_card(name="机械降神", description="造成18点伤害。", card_id="MECHANIC"):
    return {
        "name": name,
        "game": "sts1",
        "id": card_id,
        "pool": "ironclad",
        "type": "Attack",
        "cost": 1,
        "star_cost": None,
        "rarity": "Common",
        "description": description,
        "vars": {},
    }


def start_game(monkeypatch, card):
    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: [card])
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])
    monkeypatch.setattr(sessions, "find_opening_reveal_positions", lambda description: set())
    return sessions.start(101, "sts1")


def test_description_hit_returns_feedback_and_updated_puzzle(monkeypatch):
    start_game(monkeypatch, make_card())

    reply = bot.route_group_command(101, "伤害")

    assert "🎯 描述命中！揭开 2 个新字符！" in reply
    assert "=== 本轮题目 ===" in reply
    assert "伤害" in reply
    assert "累计猜测：1 次" in reply


def test_name_fragment_hit_returns_feedback_and_updated_puzzle(monkeypatch):
    start_game(monkeypatch, make_card())

    reply = bot.route_group_command(101, "机械")

    assert "🎯 牌名命中！揭开 2 个新字符！" in reply
    assert "=== 本轮题目 ===" in reply
    assert "机械□□" in reply


def test_wrong_guess_returns_feedback_and_full_puzzle(monkeypatch):
    start_game(monkeypatch, make_card())

    reply = bot.route_group_command(101, "格挡")

    assert "猜错了。" in reply
    assert "=== 本轮题目 ===" in reply


def test_rarity_hint_returns_rarity_and_updated_puzzle(monkeypatch):
    start_game(monkeypatch, make_card())

    for phrase in ["格挡", "重击", "屏障"]:
        reply = bot.route_group_command(101, phrase)

    assert "猜错了，提示：稀有度为 普通" in reply
    assert "稀有度：普通" in reply
    assert "=== 本轮题目 ===" in reply


def test_description_hint_returns_hint_and_updated_puzzle(monkeypatch):
    monkeypatch.setattr("card_guess.game.random.choice", lambda seq: seq[0])
    start_game(monkeypatch, make_card(description="获得能量。"))

    for _ in range(6):
        reply = bot.route_group_command(101, "格挡")

    assert "猜错了，提示：揭开了新的描述内容。" in reply
    assert "=== 本轮题目 ===" in reply
    assert "获得" in reply


def test_name_hint_returns_hint_and_updated_puzzle(monkeypatch):
    monkeypatch.setattr("card_guess.game.random.choice", lambda seq: seq[0])
    start_game(monkeypatch, make_card(description="获得能量。"))

    for _ in range(10):
        reply = bot.route_group_command(101, "格挡")

    assert "猜错了，提示：揭开了一个牌名字符。" in reply
    assert "=== 本轮题目 ===" in reply
    assert "机□□□" in reply


def test_description_hit_with_extra_name_hint(monkeypatch):
    monkeypatch.setattr("card_guess.game.random.choice", lambda seq: seq[0])
    start_game(monkeypatch, make_card(description="造成伤害获得能量。"))

    for phrase in ["造成", "伤害", "获得", "能量"]:
        reply = bot.route_group_command(101, phrase)

    assert "🎯 描述命中！揭开 2 个新字符！" in reply
    assert "额外提示：揭开了一个牌名字符。" in reply
    assert "=== 本轮题目 ===" in reply
    assert "机□□□" in reply


def test_already_revealed_returns_hint_and_full_puzzle(monkeypatch):
    start_game(monkeypatch, make_card())

    bot.route_group_command(101, "伤害")
    reply = bot.route_group_command(101, "伤害")

    assert "这部分已经揭开了，换个地方猜吧。" in reply
    assert "=== 本轮题目 ===" in reply


def test_invalid_returns_short_text_without_puzzle(monkeypatch):
    start_game(monkeypatch, make_card())

    reply = bot.route_group_command(101, "18")

    assert reply == "这个输入没有可猜的文字。"
    assert "=== 本轮题目 ===" not in reply


def test_full_name_guess_ends_with_success_and_cleanup(monkeypatch):
    start_game(monkeypatch, make_card())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: Path("/tmp/MECHANIC.png"))

    reply = bot.route_group_command(101, "机械降神")

    assert isinstance(reply, RenderedReply)
    assert "🎉 恭喜猜出！" in reply
    assert "正确答案：机械降神" in reply
    assert reply.image_path == Path("/tmp/MECHANIC.png")
    assert sessions.get(101) is None


def test_name_fully_revealed_via_fragments_is_success(monkeypatch):
    start_game(monkeypatch, make_card())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: Path("/tmp/MECHANIC.png"))

    bot.route_group_command(101, "机械")
    reply = bot.route_group_command(101, "降神")

    assert isinstance(reply, RenderedReply)
    assert "🎉 恭喜猜出！" in reply
    assert "正确答案：机械降神" in reply
    assert reply.image_path == Path("/tmp/MECHANIC.png")
    assert sessions.get(101) is None


def test_hint_exhaustion_result_carries_terminal_reason(monkeypatch):
    card = make_card(name="A", description="X")
    game = GameState(card)
    game.wrong_count = 11
    game.revealed_positions = {0}
    game.revealed_name_positions = {0}

    result = game.handle_input("B")

    assert result.status == "wrong"
    assert result.hint_type is None
    assert result.terminal_reason == "hint_exhausted"
    assert game.ended is True


def test_hint_exhaustion_reveals_answer_and_cleans_up(monkeypatch):
    card = make_card(name="A", description="X")
    game = GameState(card)
    game.wrong_count = 11
    game.revealed_positions = {0}
    game.revealed_name_positions = {0}
    sessions.SESSIONS[101] = game
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: Path("/tmp/MECHANIC.png"))

    reply = bot.route_group_command(101, "B")

    assert isinstance(reply, RenderedReply)
    assert "提示耗尽，本局结束" in reply
    assert "正确答案：A" in reply
    assert reply.image_path == Path("/tmp/MECHANIC.png")
    assert sessions.get(101) is None


def test_active_end_reveals_answer_and_cleans_up(monkeypatch):
    start_game(monkeypatch, make_card())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: Path("/tmp/MECHANIC.png"))

    reply = bot.route_group_command(101, "结束")

    assert isinstance(reply, RenderedReply)
    assert "本局游戏结束" in reply
    assert "正确答案：机械降神" in reply
    assert reply.image_path == Path("/tmp/MECHANIC.png")
    assert sessions.get(101) is None


def test_active_end_without_image_still_reveals_answer(monkeypatch):
    start_game(monkeypatch, make_card())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: None)

    reply = bot.route_group_command(101, "结束")

    assert isinstance(reply, RenderedReply)
    assert "本局游戏结束" in reply
    assert "正确答案：机械降神" in reply
    assert reply.image_path is None
    assert sessions.get(101) is None


def test_exact_card_query_without_game_returns_details_and_image(monkeypatch):
    card = make_card(name="痛击", description="造成8点伤害。", card_id="BASH")
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [card], raising=False)
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda queried_card: Path("/tmp/BASH.png"),
    )

    reply = bot.route_group_command(101, "痛击")

    assert isinstance(reply, RenderedReply)
    assert "=== 卡牌资料 ===" in reply
    assert "卡名：痛击" in reply
    assert "代际：杀戮尖塔 1" in reply
    assert "来源：铁甲战士" in reply
    assert "类型：攻击牌" in reply
    assert "稀有度：普通" in reply
    assert "描述：\n造成8点伤害。" in reply
    assert reply.image_path == Path("/tmp/BASH.png")


def test_exact_card_query_without_game_falls_back_to_text_when_image_missing(monkeypatch):
    card = make_card(name="痛击", card_id="BASH")
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [card], raising=False)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: None)

    reply = bot.route_group_command(101, "痛击")

    assert isinstance(reply, RenderedReply)
    assert "卡名：痛击" in reply
    assert reply.image_path is None


def test_non_card_name_without_game_keeps_unknown_input_reply(monkeypatch):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [make_card()], raising=False)

    reply = bot.route_group_command(101, "这不是卡名")

    assert reply == "当前没有进行中的游戏"


def test_duplicate_exact_card_name_without_suffix_requires_generation_hint(monkeypatch):
    sts1_card = make_card(name="白噪声", card_id="WHITE_NOISE")
    sts2_card = {
        **make_card(name="白噪声", card_id="WHITE_NOISE_2"),
        "game": "sts2",
        "pool": "defect",
    }
    monkeypatch.setattr(
        bot,
        "_load_query_cards",
        lambda: [sts1_card, sts2_card],
        raising=False,
    )

    reply = bot.route_group_command(101, "白噪声")

    assert "白噪声" in reply
    assert "白噪声1" in reply
    assert "白噪声2" in reply
    assert "请发送" in reply
    assert reply.image_path is None


def test_duplicate_exact_card_name_with_suffix_selects_generation(monkeypatch):
    sts1_card = make_card(name="白噪声", card_id="WHITE_NOISE")
    sts2_card = {
        **make_card(name="白噪声", card_id="WHITE_NOISE_2"),
        "game": "sts2",
        "pool": "defect",
    }
    monkeypatch.setattr(
        bot,
        "_load_query_cards",
        lambda: [sts1_card, sts2_card],
        raising=False,
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda queried_card: Path("/tmp/WHITE_NOISE.png") if queried_card["game"] == "sts1" else Path("/tmp/WHITE_NOISE_2.png"),
    )

    reply = bot.route_group_command(101, "白噪声2")

    assert "=== 卡牌资料 ===" in reply
    assert "代际：杀戮尖塔 2" in reply
    assert reply.image_path == Path("/tmp/WHITE_NOISE_2.png")


def test_wrong_exact_card_name_in_game_keeps_game_result_and_adds_card(monkeypatch):
    answer = make_card()
    guessed_card = make_card(name="铁斩波", description="造成5点伤害。", card_id="IRON_WAVE")
    game = start_game(monkeypatch, answer)
    game.wrong_count = 2
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [guessed_card], raising=False)
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda card: Path("/tmp/IRON_WAVE.png"),
    )

    reply = bot.route_group_command(101, "铁斩波")

    assert game.wrong_count == 3
    assert game.total_guess_count == 1
    assert game.wrong_guesses == ["铁斩波"]
    assert game.rarity_revealed is True
    assert answer["rarity"] == "Common"
    assert "❌ 不是这张" in reply
    assert "你猜的是：铁斩波" in reply
    assert "描述：\n造成5点伤害。" in reply
    assert "猜错了，提示：稀有度为 普通" in reply
    assert "=== 本轮题目 ===" in reply
    assert "稀有度：普通" in reply
    assert reply.image_path == Path("/tmp/IRON_WAVE.png")


def test_exact_card_name_that_hits_description_uses_game_result(monkeypatch):
    answer = make_card(description="获得伤害。")
    real_card = make_card(name="伤害", card_id="DAMAGE_CARD")
    start_game(monkeypatch, answer)
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [real_card], raising=False)

    reply = bot.route_group_command(101, "伤害")

    assert "🎯 描述命中！揭开 2 个新字符！" in reply
    assert "❌ 不是这张" not in reply
    assert "你猜的是：伤害" not in reply
    assert reply.image_path is None


def test_game_wrong_guess_uses_current_generation_for_crossgen_name(monkeypatch):
    answer = make_card(name="机械降神", description="造成伤害。")
    sts1_card = make_card(name="白噪声", card_id="WHITE_NOISE")
    sts2_card = {**make_card(name="白噪声", card_id="WHITE_NOISE_2"), "game": "sts2", "pool": "defect"}
    start_game(monkeypatch, answer)
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [sts1_card, sts2_card], raising=False)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: Path("/tmp/WHITE_NOISE_2.png"))

    reply = bot.route_group_command(101, "白噪声")

    assert "❌ 不是这张" in reply
    assert "代际：杀戮尖塔 1" in reply or "代际：杀戮尖塔 2" in reply
    assert "你猜的是：白噪声" in reply
    assert "猜错了" in reply

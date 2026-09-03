import pytest

from card_guess.qq import bot, sessions


BASE_WORDS = ["猜词", "猜谜", "开始", "开局", "开始游戏"]


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()


def patch_start(monkeypatch):
    calls = []
    monkeypatch.setattr(sessions, "get", lambda group_id: None)

    def fake_start(group_id, mode, character=None):
        calls.append((group_id, mode, character))
        return object()

    monkeypatch.setattr(sessions, "start", fake_start)
    return calls


def test_all_base_words_start_mixed(monkeypatch):
    calls = patch_start(monkeypatch)

    for word in BASE_WORDS:
        bot.route_group_command(101, word)

    assert calls == [(101, "mixed", None)] * len(BASE_WORDS)


def test_all_base_words_with_suffix_1_start_sts1(monkeypatch):
    calls = patch_start(monkeypatch)

    for word in BASE_WORDS:
        bot.route_group_command(101, word + "1")

    assert calls == [(101, "sts1", None)] * len(BASE_WORDS)


def test_all_base_words_with_suffix_2_start_sts2(monkeypatch):
    calls = patch_start(monkeypatch)

    for word in BASE_WORDS:
        bot.route_group_command(101, word + "2")

    assert calls == [(101, "sts2", None)] * len(BASE_WORDS)


def test_start_with_character_uses_mixed_and_defect(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始 鸡煲")

    assert calls == [(101, "mixed", "defect")]


def test_start1_with_character_uses_sts1_and_defect(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始1 鸡煲")

    assert calls == [(101, "sts1", "defect")]


def test_guess2_with_character_uses_sts2_and_necrobinder(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "猜谜2 骨妹")

    assert calls == [(101, "sts2", "necrobinder")]


def test_open2_with_character_uses_sts2_and_regent(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开局2 储君")

    assert calls == [(101, "sts2", "regent")]


def test_unknown_suffix_3_is_not_a_start_command(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = bot.route_group_command(101, "开始3")

    assert reply == "当前没有进行中的游戏"
    assert calls == []


def test_non_start_card_names_with_generation_suffix_are_not_start_commands(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = bot.route_group_command(101, "愤怒1")
    assert "愤怒" in str(reply)
    assert "本轮题目" not in str(reply)
    assert calls == []

    reply = bot.route_group_command(101, "愤怒2")
    assert "愤怒" in str(reply)
    assert "本轮题目" not in str(reply)
    assert calls == []

    reply = bot.route_group_command(101, "内心宁静")
    assert "内心宁静" in str(reply)
    assert "当前没有进行中的游戏" not in str(reply)
    assert calls == []

    reply = bot.route_group_command(101, "abc1")
    assert reply == "当前没有进行中的游戏"

    reply = bot.route_group_command(101, "测试2")
    assert reply == "当前没有进行中的游戏"


def test_unknown_suffix_letters_are_not_a_start_command(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = bot.route_group_command(101, "猜词abc")

    assert reply == "当前没有进行中的游戏"
    assert calls == []


def test_unknown_suffix_12_is_not_a_start_command(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = bot.route_group_command(101, "开局12")

    assert reply == "当前没有进行中的游戏"
    assert calls == []


def test_legacy_guess_words_keep_existing_modes(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "猜词")
    bot.route_group_command(101, "猜词1")
    bot.route_group_command(101, "猜词2")

    assert calls == [
        (101, "mixed", None),
        (101, "sts1", None),
        (101, "sts2", None),
    ]


def test_start1_colorless_uses_sts1_and_colorless(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始1 无色")

    assert calls == [(101, "sts1", "colorless")]


def test_start2_colorless_uses_sts2_and_colorless(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2 无色")

    assert calls == [(101, "sts2", "colorless")]


def test_start2_event_uses_sts2_and_event(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2 事件")

    assert calls == [(101, "sts2", "event")]


def test_start2_quest_uses_sts2_and_quest(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2 任务")

    assert calls == [(101, "sts2", "quest")]


def test_start2_token_uses_sts2_and_token(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2 衍生")

    assert calls == [(101, "sts2", "token")]


def test_start2_special_pool_aliases_with_card_suffix(monkeypatch):
    calls = patch_start(monkeypatch)

    for phrase in ["开始2 无色牌", "开始2 事件牌", "开始2 任务牌", "开始2 衍生牌"]:
        bot.route_group_command(101, phrase)

    assert calls == [
        (101, "sts2", "colorless"),
        (101, "sts2", "event"),
        (101, "sts2", "quest"),
        (101, "sts2", "token"),
    ]


@pytest.mark.parametrize(
    "phrase",
    ["开始1 任务", "开始1 衍生", "开始1 事件"],
)
def test_special_pool_without_cards_does_not_fallback(monkeypatch, phrase):
    reply = bot.route_group_command(101, phrase)

    assert reply == "当前版本没有可用的该类题库"
    assert sessions.get(101) is None


def test_start2_quest_picks_quest_pool_card(monkeypatch):
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])

    reply = bot.route_group_command(101, "开始2 任务")

    game = sessions.get(101)
    assert game is not None
    assert game.card["pool"] == "quest"
    assert "任务" in str(reply)


def test_start2_token_picks_token_pool_card(monkeypatch):
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])

    reply = bot.route_group_command(101, "开始2 衍生")

    game = sessions.get(101)
    assert game is not None
    assert game.card["pool"] == "token"
    assert "衍生" in str(reply)


def test_original_character_aliases_still_work(monkeypatch):
    calls = patch_start(monkeypatch)

    for phrase, expected in [
        ("开始2 战士哥", "ironclad"),
        ("开始2 猎豹", "silent"),
        ("开始2 鸡煲", "defect"),
        ("开始2 紫皮", "watcher"),
        ("开始2 骨妹", "necrobinder"),
        ("开始2 储君", "regent"),
    ]:
        bot.route_group_command(101, phrase)

    assert calls == [
        (101, "sts2", "ironclad"),
        (101, "sts2", "silent"),
        (101, "sts2", "defect"),
        (101, "sts2", "watcher"),
        (101, "sts2", "necrobinder"),
        (101, "sts2", "regent"),
    ]


@pytest.mark.parametrize(
    "phrase",
    ["开始1猎宝", "开始 1 猎宝", "开始 1猎宝", "开始1 猎宝"],
)
def test_start1_silent_ignores_whitespace_between_tokens(monkeypatch, phrase):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, phrase)

    assert calls == [(101, "sts1", "silent")]


def test_start2_colorless_ignores_extra_whitespace(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始   2   无色")

    assert calls == [(101, "sts2", "colorless")]


def test_start_space_before_generation_suffix_starts_sts1(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始 1")

    assert calls == [(101, "sts1", None)]


def test_whitespace_normalization_applies_only_to_start_word(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = bot.route_group_command(101, "猜词1猎宝")

    assert reply == "当前没有进行中的游戏"
    assert calls == []

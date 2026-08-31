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

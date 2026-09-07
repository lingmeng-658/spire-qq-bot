# -*- coding: utf-8 -*-
"""QQ start-command routing after Command UX v1."""

import pytest

from card_guess.qq import bot, sessions


RETIRED_START_WORDS = ("猜词", "猜谜", "开局", "开始游戏")


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


def test_start_is_the_only_mixed_mode_entry(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始")

    assert calls == [(101, "mixed", None)]


def test_retired_start_words_do_not_start(monkeypatch):
    calls = patch_start(monkeypatch)

    for word in RETIRED_START_WORDS:
        bot.route_group_command(101, word)

    assert calls == []


def test_start_with_suffix_1_uses_sts1(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始1")

    assert calls == [(101, "sts1", None)]


def test_start_with_suffix_2_uses_sts2(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2")

    assert calls == [(101, "sts2", None)]


def test_start_with_character_uses_mixed_and_defect(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始 鸡煲")

    assert calls == [(101, "mixed", "defect")]


def test_start1_with_character_uses_sts1_and_defect(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始1 鸡煲")

    assert calls == [(101, "sts1", "defect")]


def test_start2_with_character_uses_sts2_and_necrobinder(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2 骨妹")

    assert calls == [(101, "sts2", "necrobinder")]


def test_start2_with_character_uses_sts2_and_regent(monkeypatch):
    calls = patch_start(monkeypatch)

    bot.route_group_command(101, "开始2 储君")

    assert calls == [(101, "sts2", "regent")]


def test_unknown_suffix_3_is_not_a_start_command(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = str(bot.route_group_command(101, "开始3"))

    assert reply == bot.UNKNOWN_COMMAND_REPLY
    assert calls == []


def test_non_start_card_names_with_generation_suffix_are_not_start_commands(monkeypatch):
    calls = patch_start(monkeypatch)

    reply = bot.route_group_command(101, "愤怒1")
    assert "本轮题目" not in str(reply)
    assert calls == []

    reply = bot.route_group_command(101, "内心宁静")
    assert "当前没有进行中的游戏" not in str(reply)
    assert calls == []


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


def test_duplicate_start_returns_channel_neutral_copy(monkeypatch):
    fake_game = object()
    monkeypatch.setattr(sessions, "get", lambda group_id: fake_game)

    assert str(bot.route_group_command(101, "开始")) == "当前会话已有一局"

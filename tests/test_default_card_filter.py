import pytest

from card_guess.cards import load_all_standard_cards, load_game_cards
from card_guess.qq import sessions

STS2_RESTORED_COLORLESS = {
    "FINESSE",
    "FLASH_OF_STEEL",
    "MASTER_OF_STRATEGY",
    "PURITY",
    "SECRET_TECHNIQUE",
    "SECRET_WEAPON",
    "THINKING_AHEAD",
}

STS1_BLACKLIST_COLORLESS = STS2_RESTORED_COLORLESS

STS1_STATUS_JUNK = {"BURN", "DAZED", "SLIMED", "VOID", "WOUND"}

STS2_STATUS_POOL = {
    "BECKON",
    "BURN",
    "DAZED",
    "DEBRIS",
    "FRANTIC_ESCAPE",
    "INFECTION",
    "SLIMED",
    "SOOT",
    "TOXIC",
    "VOID",
    "WITHER",
    "WOUND",
}

BASIC_STRIKES_DEFENDS = {
    "STRIKE_R", "STRIKE_G", "STRIKE_B", "STRIKE_P",
    "DEFEND_R", "DEFEND_G", "DEFEND_B", "DEFEND_P",
    "STRIKE_IRONCLAD", "STRIKE_SILENT", "STRIKE_DEFECT",
    "STRIKE_NECROBINDER", "STRIKE_REGENT",
    "DEFEND_IRONCLAD", "DEFEND_SILENT", "DEFEND_DEFECT",
    "DEFEND_NECROBINDER", "DEFEND_REGENT",
}


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()


def _ids(cards):
    return {card["id"] for card in cards}


def test_sts1_default_bank_excludes_blacklist_colorless():
    default_ids = _ids(load_game_cards("sts1"))
    assert default_ids.isdisjoint(STS1_BLACKLIST_COLORLESS)


def test_sts2_restored_colorless_enter_default_bank():
    default_ids = _ids(load_game_cards("sts2"))
    assert STS2_RESTORED_COLORLESS <= default_ids


def test_default_bank_excludes_normal_curse_and_status():
    for mode in ["sts1", "sts2"]:
        default_ids = _ids(load_game_cards(mode))
        assert default_ids.isdisjoint({"CLUMSY", "DOUBT", "SHAME", "REGRET", "INJURY"})
        assert default_ids.isdisjoint(STS1_STATUS_JUNK)
        assert default_ids.isdisjoint(STS2_STATUS_POOL)


def test_special_meme_curses_stay_in_default_bank():
    sts1_ids = _ids(load_game_cards("sts1"))
    assert {"NORMALITY", "PAIN", "DECAY"} <= sts1_ids

    sts2_ids = _ids(load_game_cards("sts2"))
    assert "BAD_LUCK" in sts2_ids
    assert sts2_ids.isdisjoint({"NORMALITY", "DECAY"})


def test_default_bank_excludes_basic_strike_and_defend():
    for mode in ["sts1", "sts2"]:
        default_ids = _ids(load_game_cards(mode))
        assert default_ids.isdisjoint(BASIC_STRIKES_DEFENDS)


def test_default_bank_keeps_non_basic_named_cards():
    sts2_ids = _ids(load_game_cards("sts2"))
    assert {"ULTIMATE_STRIKE", "ULTIMATE_DEFEND"} <= sts2_ids
    assert "SEEKER_STRIKE" not in sts2_ids


def test_special_pool_entrance_uses_complete_pool_not_default_filter(monkeypatch):
    from card_guess.qq import bot

    finesse = next(card for card in load_all_standard_cards("sts1") if card["id"] == "FINESSE")
    monkeypatch.setattr(sessions.random, "choice", lambda cards: finesse)

    bot.route_group_command(101, "开始1 无色")

    game = sessions.get(101)
    assert game is not None
    assert game.card["id"] == "FINESSE"


def test_special_pool_entrance_curse_uses_complete_curse_pool(monkeypatch):
    from card_guess.qq import bot

    doubt = next(card for card in load_all_standard_cards("sts2") if card["id"] == "DOUBT")
    monkeypatch.setattr(sessions.random, "choice", lambda cards: doubt)

    bot.route_group_command(101, "开始2 诅咒")

    game = sessions.get(101)
    assert game is not None
    assert game.card["id"] == "DOUBT"


def test_card_query_still_finds_default_blocked_cards():
    from card_guess.qq import bot

    reply = bot.route_group_command(101, "疼痛")

    assert "卡牌资料" in str(reply)
    assert "疼痛" in str(reply)

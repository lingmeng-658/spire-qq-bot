"""Event QQ command, query-disambiguation, and session-priority tests."""

from __future__ import annotations

import pytest

from card_guess.events import EventChoice, EventRecord, get_event
from card_guess.qq import bot, sessions
from card_guess.qq.renderer import RenderedReply


def make_event(game="sts1", event_id="FIXTURE_EVENT", name="虚构事件"):
    return EventRecord(
        game=game,
        id=event_id,
        name_zh=name,
        name_en="Fixture Event",
        category="event",
        act=1,
        pool="act_specific",
        description_zh="虚构事件正文。",
        choices=(
            EventChoice(
                id="LEAVE",
                text_zh="离开",
                description_zh=None,
                result_zh=None,
                locked_zh=None,
                raw={"id": "LEAVE"},
            ),
        ),
        raw={},
    )


def make_card(name="虚构卡牌", game="sts1"):
    return {
        "name": name,
        "game": game,
        "id": "FIXTURE_CARD",
        "pool": "ironclad",
        "type": "Attack",
        "cost": 1,
        "star_cost": None,
        "rarity": "Common",
        "description": "造成伤害。",
        "vars": {},
        "upgrade": {},
    }


def make_relic(name="虚构遗物", game="sts1"):
    return {
        "name": name,
        "game": game,
        "id": "FIXTURE_RELIC",
        "name_en": "Fixture Relic",
        "description": "虚构遗物效果。",
        "description_en": "Fixture relic effect.",
        "tier": "common",
        "color": None,
    }


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()


def patch_query_sources(monkeypatch, *, cards=(), relics=(), events=()):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: list(cards))
    monkeypatch.setattr(bot, "_load_query_relics", lambda: list(relics))
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(
        bot,
        "_find_events_by_name",
        lambda name, generation=None: [
            event
            for event in events
            if event.name_zh == name
            and (generation is None or event.game == f"sts{generation}")
        ],
        raising=False,
    )
    monkeypatch.setattr(
        bot,
        "render_event",
        lambda event: f"event:{event.game}:{event.name_zh}",
        raising=False,
    )


@pytest.mark.parametrize(
    ("command", "game"),
    [("事件1", "sts1"), ("事 件 1", "sts1"), ("事件2", "sts2")],
)
def test_generation_random_event_uses_only_that_default_pool(
    monkeypatch, command, game
):
    chosen = make_event(game=game, event_id=f"{game}_CHOSEN")
    pools = {"sts1": (make_event("sts1"),), "sts2": (make_event("sts2"),)}
    pools[game] = (chosen,)
    seen = []

    monkeypatch.setattr(
        bot, "default_random_pool", lambda selected_game: pools[selected_game], raising=False
    )
    monkeypatch.setattr(
        bot,
        "random",
        type("FixtureRandom", (), {"choice": staticmethod(lambda pool: seen.append(pool) or pool[0])}),
        raising=False,
    )
    monkeypatch.setattr(bot, "render_event", lambda event: event.id, raising=False)

    assert str(bot.route_group_command(101, command)) == chosen.id
    assert seen == [pools[game]]


def test_mixed_random_event_selects_game_before_selecting_from_its_pool(monkeypatch):
    sts1 = (make_event("sts1", "STS1_ONLY"),)
    sts2 = (make_event("sts2", "STS2_ONLY"),)
    calls = []

    def choose(items):
        calls.append(items)
        if items == ("sts1", "sts2"):
            return "sts2"
        return items[0]

    monkeypatch.setattr(
        bot,
        "default_random_pool",
        lambda game: {"sts1": sts1, "sts2": sts2}[game],
        raising=False,
    )
    monkeypatch.setattr(
        bot, "random", type("FixtureRandom", (), {"choice": staticmethod(choose)}), raising=False
    )
    monkeypatch.setattr(bot, "render_event", lambda event: event.id, raising=False)

    assert str(bot.route_group_command(101, "事件")) == "STS2_ONLY"
    assert calls == [("sts1", "sts2"), sts2]


@pytest.mark.parametrize(
    ("command", "game", "event_id"),
    [
        ("大鱼", "sts1", "BIG_FISH"),
        ("泉水", "sts2", "WELLSPRING"),
        ("大鱼1", "sts1", "BIG_FISH"),
        ("泉水2", "sts2", "WELLSPRING"),
    ],
)
def test_event_name_query_supports_implicit_and_generation_forms(
    monkeypatch, command, game, event_id
):
    event = get_event(game, event_id)
    patch_query_sources(monkeypatch, events=(event,))

    assert str(bot.route_group_command(101, command)) == f"event:{game}:{event.name_zh}"


def test_unknown_name_is_not_misclassified_as_an_event(monkeypatch):
    patch_query_sources(monkeypatch)

    assert str(bot.route_group_command(101, "并不存在的事件")) == bot.UNKNOWN_COMMAND_REPLY


@pytest.mark.parametrize(
    ("card", "relic", "expected_types"),
    [
        (make_card(name="重名"), None, "卡牌 / 事件"),
        (None, make_relic(name="重名"), "遗物 / 事件"),
    ],
)
def test_cross_entity_exact_name_returns_short_disambiguation(
    monkeypatch, card, relic, expected_types
):
    patch_query_sources(
        monkeypatch,
        cards=(card,) if card else (),
        relics=(relic,) if relic else (),
        events=(make_event(name="重名"),),
    )

    reply = str(bot.route_group_command(101, "重名"))

    assert "“重名”同时是" in reply
    assert expected_types in reply
    assert "卡牌 重名" in reply if card else "遗物 重名" in reply
    assert "事件 重名" in reply


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("卡牌 重名", "card-only"),
        ("遗物 重名", "relic-only"),
        ("事件 重名", "event-only"),
    ],
)
def test_typed_name_form_resolves_cross_entity_collision(monkeypatch, command, expected):
    event = make_event(name="重名")
    patch_query_sources(
        monkeypatch,
        cards=(make_card(name="重名"),),
        relics=(make_relic(name="重名"),),
        events=(event,),
    )
    monkeypatch.setattr(
        bot, "render_card_query_reply", lambda matches: RenderedReply("card-only")
    )
    monkeypatch.setattr(
        bot, "render_relic_query_reply", lambda matches: RenderedReply("relic-only")
    )
    monkeypatch.setattr(bot, "render_event", lambda record: "event-only", raising=False)

    assert str(bot.route_group_command(101, command)) == expected


def test_card_and_relic_queries_still_route_when_there_is_no_event_collision(monkeypatch):
    patch_query_sources(
        monkeypatch,
        cards=(make_card(name="独有卡牌"),),
        relics=(make_relic(name="独有遗物"),),
    )
    monkeypatch.setattr(
        bot, "render_card_query_reply", lambda matches: RenderedReply("card-ok")
    )
    monkeypatch.setattr(
        bot, "render_relic_query_reply", lambda matches: RenderedReply("relic-ok")
    )

    assert str(bot.route_group_command(101, "独有卡牌")) == "card-ok"
    assert str(bot.route_group_command(101, "独有遗物")) == "relic-ok"


class FixtureGuessGame:
    def __init__(self):
        self.ended = False
        self.card = {"name": "谜底"}
        self.inputs = []

    def handle_input(self, text):
        self.inputs.append(text)
        return type(
            "Result",
            (),
            {"status": "wrong", "hint_type": None, "terminal_reason": None},
        )()

    def build_puzzle(self):
        return {
            "masked_name": "谜□",
            "pool": "铁甲战士",
            "type": "攻击牌",
            "cost": "1",
            "star_cost": None,
            "masked_description": "造成伤害。",
            "rarity": None,
        }


def test_active_session_plain_event_name_remains_a_guess(monkeypatch):
    game = FixtureGuessGame()
    sessions.SESSIONS[101] = game
    patch_query_sources(monkeypatch, events=(make_event(name="虚构事件"),))

    reply = str(bot.route_group_command(101, "虚构事件"))

    assert game.inputs == ["虚构事件"]
    assert "event:" not in reply


@pytest.mark.parametrize("command", ["虚构事件1", "事件 虚构事件"])
def test_active_session_explicit_event_query_bypasses_guess(monkeypatch, command):
    game = FixtureGuessGame()
    sessions.SESSIONS[101] = game
    patch_query_sources(monkeypatch, events=(make_event(name="虚构事件"),))

    reply = str(bot.route_group_command(101, command))

    assert reply == "event:sts1:虚构事件"
    assert game.inputs == []


def test_help_adds_event_entry_without_advertising_typed_disambiguators():
    assert "直接发送名字即可查询卡牌 / 遗物 / 事件" in bot.HELP_TEXT
    assert "随机事件：事件 / 事件1 / 事件2" in bot.HELP_TEXT
    assert "事件名" in bot.HELP_SUBCOMMANDS["查询"]
    assert "卡牌 名字" not in bot.HELP_TEXT
    assert "事件 名字" not in bot.HELP_TEXT


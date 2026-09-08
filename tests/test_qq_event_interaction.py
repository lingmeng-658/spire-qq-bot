"""STS2 Interactive Event Level 1 tests.

Choice -> official result_zh -> end, first-valid-answerer semantics.  All
session state lives in ``card_guess.qq.event_sessions`` so the guess-card
session system stays untouched.  Real frozen catalog records are used only
for the audited smoke examples; every behavioural test uses fictional
fixtures.
"""

from __future__ import annotations

import pytest

from card_guess.event_presentation import list_visible_choices, strip_event_bbcode
from card_guess.events import EventChoice, EventRecord, get_event
from card_guess.qq import bot, event_sessions, sessions


def make_choice(
    choice_id="CHOICE_A",
    text="选择甲",
    description="获得[green]6[/green]点最大生命。",
    *,
    result="结果甲：你感到一阵暖流。",
    locked=None,
):
    return EventChoice(
        id=choice_id,
        text_zh=text,
        description_zh=description,
        result_zh=result,
        locked_zh=locked,
        raw={"id": choice_id},
    )


def make_event(
    *,
    game="sts2",
    event_id="STS2_INTERACTIVE_FIXTURE",
    name="互动事件",
    act=1,
    pool="act_specific",
    choices=None,
    raw=None,
):
    return EventRecord(
        game=game,
        id=event_id,
        name_zh=name,
        name_en="Interactive Fixture",
        category="Event",
        act=act,
        pool=pool,
        description_zh="一段[red]事件[/red]正文。",
        choices=tuple(choices if choices is not None else (make_choice(),)),
        raw=raw or {},
    )


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()


def patch_pool(monkeypatch, event):
    """Make every random-event command return exactly ``event``."""
    monkeypatch.setattr(
        bot,
        "default_random_pool",
        lambda game: (event,),
        raising=False,
    )


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


class FixtureGuessGame:
    def __init__(self):
        self.ended = False
        self.card = {"name": "谜底"}
        self.inputs = []
        self.wrong_count = 0
        self.wrong_guesses = []
        self.total_guess_count = 0

    def handle_input(self, text):
        self.inputs.append(text)
        self.wrong_count += 1
        self.wrong_guesses.append(text)
        self.total_guess_count += 1
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


# 1-3: random command creates an interactive session only for STS2 -----------


def test_event2_random_sts2_event_creates_interaction_session(monkeypatch):
    event = make_event()
    patch_pool(monkeypatch, event)

    reply = bot.route_group_command(101, "事件2")

    assert reply is not None
    session = event_sessions.get(101)
    assert session is not None
    assert session.game == "sts2"
    assert session.event_id == event.id
    assert session.event_name_zh == event.name_zh
    assert tuple(session.visible_choices) == list_visible_choices(event)


def test_mixed_random_event_creating_session_when_sts2_wins(monkeypatch):
    def choose(items):
        if items == ("sts1", "sts2"):
            return "sts2"
        return items[0]

    event = make_event(event_id="STS2_WON")
    patch_pool(monkeypatch, event)
    monkeypatch.setattr(
        bot,
        "random",
        type("FixtureRandom", (), {"choice": staticmethod(choose)}),
        raising=False,
    )

    reply = bot.route_group_command(101, "事件")

    assert reply is not None
    assert event_sessions.get(101).event_id == "STS2_WON"


def test_mixed_random_event_does_not_create_session_when_sts1_wins(monkeypatch):
    def choose(items):
        if items == ("sts1", "sts2"):
            return "sts1"
        return items[0]

    event = make_event(game="sts1", event_id="STS1_STATIC")
    patch_pool(monkeypatch, event)
    monkeypatch.setattr(
        bot,
        "random",
        type("FixtureRandom", (), {"choice": staticmethod(choose)}),
        raising=False,
    )

    reply = bot.route_group_command(101, "事件")

    assert reply is not None
    assert event_sessions.get(101) is None
    assert 101 not in event_sessions.SESSIONS


# 4: direct name query stays a pure lookup ------------------------------------


def test_direct_event_name_query_does_not_create_session(monkeypatch):
    event = make_event(name="泉水")
    patch_query_sources(monkeypatch, events=(event,))

    reply = bot.route_group_command(101, "泉水")

    assert str(reply) == "event:sts2:泉水"
    assert event_sessions.get(101) is None


# 5-7: answerer semantics -----------------------------------------------------


def test_first_valid_group_answerer_wins_and_session_ends(monkeypatch):
    event = make_event(
        choices=(
            make_choice("A", "拿取苹果", result="苹果结果。"),
            make_choice("B", "拿取香蕉", result="香蕉结果。"),
        )
    )
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    reply = bot.route_group_command(101, "2", actor="小明")

    assert "小明选择了「拿取香蕉」" in str(reply)
    assert "香蕉结果。" in str(reply)
    assert "事件结束。" in str(reply)
    assert event_sessions.get(101) is None


def test_late_answer_after_session_cleanup_is_noop(monkeypatch):
    event = make_event()
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    bot.route_group_command(101, "1", actor="小明")

    late = bot.route_group_command(101, "1", actor="小红")

    assert "选择了" not in str(late)
    assert event_sessions.get(101) is None


def test_private_reply_uses_own_actor(monkeypatch):
    event = make_event(choices=(make_choice("A", "装瓶", result="装瓶结果。"),))
    patch_pool(monkeypatch, event)
    bot.route_group_command(202, "事件2")

    reply = bot.route_group_command(202, "1", actor="你")

    assert "你选择了「装瓶」" in str(reply)
    assert "装瓶结果。" in str(reply)
    assert "事件结束。" in str(reply)
    assert event_sessions.get(202) is None


# 8-9: invalid answers do not end the session --------------------------------


@pytest.mark.parametrize("bad_input", ["abc", "你好", "1.5", "  ", "事件"])
def test_non_numeric_input_keeps_session(monkeypatch, bad_input):
    event = make_event()
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    session = event_sessions.get(101)

    reply = bot.route_group_command(101, bad_input, actor="小明")

    assert "选择了" not in str(reply)
    assert event_sessions.get(101) is session
    assert "事件结束。" not in str(reply)


@pytest.mark.parametrize("bad_index", ["0", "-1", "3", "99"])
def test_out_of_range_index_keeps_session(monkeypatch, bad_index):
    event = make_event(
        choices=(
            make_choice("A", "选择甲", result="甲结果。"),
            make_choice("B", "选择乙", result="乙结果。"),
        )
    )
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    session = event_sessions.get(101)

    reply = bot.route_group_command(101, bad_index, actor="小明")

    assert "选择了" not in str(reply)
    assert event_sessions.get(101) is session
    assert "事件结束。" not in str(reply)


# 10: locked rows take no selectable index ------------------------------------


def test_locked_rows_do_not_take_a_selectable_index(monkeypatch):
    event = get_event("sts2", "WATERLOGGED_SCRIPTORIUM")
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    session = event_sessions.get(101)
    assert len(session.visible_choices) == 3

    out_of_range = bot.route_group_command(101, "4", actor="小明")
    assert "选择了" not in str(out_of_range)
    assert event_sessions.get(101) is session

    reply = bot.route_group_command(101, "1", actor="小明")
    choice = session.visible_choices[0]
    assert f"小明选择了「{choice.text_zh}」" in str(reply)
    assert strip_event_bbcode(choice.result_zh) in str(reply)
    assert "事件结束。" in str(reply)
    assert event_sessions.get(101) is None


# 11-13: outcome rendering ----------------------------------------------------


def test_choice_with_result_shows_official_result_then_end(monkeypatch):
    event = make_event(choices=(make_choice("A", "沐浴", result="沐浴结果：浑身舒畅。"),))
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    reply = str(bot.route_group_command(101, "1", actor="小明"))

    assert reply == "小明选择了「沐浴」\n\n沐浴结果：浑身舒畅。\n\n事件结束。"


def test_choice_without_result_ends_safely_without_fabrication(monkeypatch):
    event = make_event(
        choices=(
            make_choice(
                "A",
                "采集花蜜",
                description="获得35金币。",
                result=None,
            ),
        )
    )
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    reply = str(bot.route_group_command(101, "1", actor="小明"))

    assert "小明选择了「采集花蜜」" in reply
    assert "获得35金币。" in reply
    assert reply.endswith("事件结束。")
    assert "结果甲" not in reply


def test_result_bbcode_is_cleaned_before_display(monkeypatch):
    event = make_event(
        choices=(
            make_choice(
                "A",
                "打开宝箱",
                result="你获得了[gold]35[/gold][blue]金币[/blue]与[green]1[/green]瓶药水。",
            ),
        )
    )
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    reply = str(bot.route_group_command(101, "1", actor="小明"))

    assert "你获得了35金币与1瓶药水。" in reply
    assert "[gold]" not in reply
    assert "[/blue]" not in reply


# 14: first screen and outcome never expose pages / next ----------------------


def test_interactive_replies_never_expose_pages_or_next(monkeypatch):
    page_text = "不应暴露的后续页面正文。"
    event = make_event(
        choices=(make_choice("A", "深入", result="当前结果。"),),
        raw={"pages": [{"description": page_text}]},
    )
    patch_pool(monkeypatch, event)
    first = str(bot.route_group_command(101, "事件2"))
    session = event_sessions.get(101)

    assert page_text not in first
    assert "下一页" not in first

    reply = str(bot.route_group_command(101, "1", actor="小明"))

    assert page_text not in reply
    assert "下一页" not in reply
    assert "事件结束。" in reply
    assert not hasattr(session, "next_page")
    assert not hasattr(session, "transition")


# 16-17: cleanup and no-overwrite ---------------------------------------------


def test_session_is_cleaned_immediately_after_choice(monkeypatch):
    event = make_event(choices=(make_choice("A", "选择甲", result="结果。"),))
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    assert 101 in event_sessions.SESSIONS

    bot.route_group_command(101, "1", actor="小明")

    assert event_sessions.get(101) is None
    assert 101 not in event_sessions.SESSIONS


def test_new_random_event_does_not_overwrite_active_interaction(monkeypatch):
    first = make_event(
        event_id="FIRST_EVENT",
        choices=(make_choice("A", "选项一", result="结果一。"),),
    )
    patch_pool(monkeypatch, first)
    bot.route_group_command(101, "事件2")
    before = event_sessions.get(101)

    second = make_event(
        event_id="SECOND_EVENT",
        choices=(make_choice("B", "选项二", result="结果二。"),),
    )
    patch_pool(monkeypatch, second)
    reply = str(bot.route_group_command(101, "事件2"))

    assert event_sessions.get(101) is before
    assert before.event_id == "FIRST_EVENT"
    assert "互动事件进行中" in reply


# 18: 结束 ends an active interactive event -----------------------------------


def test_end_command_ends_active_interactive_event(monkeypatch):
    event = make_event()
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    assert event_sessions.get(101) is not None

    reply = bot.route_group_command(101, "结束")

    assert "互动事件已结束" in str(reply)
    assert event_sessions.get(101) is None


# 19-20: guess-card and static-query regressions ------------------------------


def test_guess_card_session_is_not_disturbed_by_interactive_event(monkeypatch):
    guess = FixtureGuessGame()
    sessions.SESSIONS[101] = guess
    event = make_event(choices=(make_choice("A", "选择甲", result="结果。"),))
    patch_pool(monkeypatch, event)

    bot.route_group_command(101, "事件2")
    assert sessions.get(101) is guess
    assert event_sessions.get(101) is not None

    bot.route_group_command(101, "1", actor="小明")
    assert event_sessions.get(101) is None
    assert sessions.get(101) is guess
    assert guess.inputs == []

    reply = str(bot.route_group_command(101, "试着猜一张牌"))
    assert "猜错" in reply or "本轮题目" in reply
    assert guess.inputs == ["试着猜一张牌"]


def test_static_queries_still_work_after_interaction(monkeypatch):
    event = make_event(choices=(make_choice("A", "选择甲", result="结果。"),))
    patch_pool(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    bot.route_group_command(101, "1", actor="小明")

    query_event = make_event(name="泉水", event_id="WELLSPRING_QUERY")
    patch_query_sources(monkeypatch, events=(query_event,))
    reply = bot.route_group_command(101, "泉水")

    assert str(reply) == "event:sts2:泉水"
    assert event_sessions.get(101) is None


# Real-catalog smoke ----------------------------------------------------------


def smoke_open(monkeypatch, event, key=101):
    patch_pool(monkeypatch, event)
    bot.route_group_command(key, "事件2")
    return event_sessions.get(key)


@pytest.mark.parametrize("index,text", [("1", "装瓶"), ("2", "沐浴")])
def test_smoke_wellspring_choices(monkeypatch, index, text):
    event = get_event("sts2", "WELLSPRING")
    session = smoke_open(monkeypatch, event)
    assert session is not None
    choice = session.visible_choices[int(index) - 1]
    assert choice.text_zh == text

    reply = str(bot.route_group_command(101, index, actor="群友甲"))

    assert f"群友甲选择了「{text}」" in reply
    assert strip_event_bbcode(choice.result_zh) in reply
    assert "事件结束。" in reply
    assert event_sessions.get(101) is None


def test_smoke_waterlogged_scriptorium_any_legal_option(monkeypatch):
    event = get_event("sts2", "WATERLOGGED_SCRIPTORIUM")
    session = smoke_open(monkeypatch, event)
    choice = session.visible_choices[1]

    reply = str(bot.route_group_command(101, "2", actor="群友甲"))

    assert f"群友甲选择了「{choice.text_zh}」" in reply
    assert strip_event_bbcode(choice.result_zh) in reply
    assert "事件结束。" in reply
    assert event_sessions.get(101) is None


def test_smoke_colossal_flower_deeper_choice_ends_without_next_page(monkeypatch):
    event = get_event("sts2", "COLOSSAL_FLOWER")
    session = smoke_open(monkeypatch, event)
    choice = session.visible_choices[1]
    assert choice.id == "REACH_DEEPER_1"
    page_texts = [
        page.get("description", "")
        for page in event.raw.get("pages", [])
        if isinstance(page, dict) and page.get("description")
    ]

    reply = str(bot.route_group_command(101, "2", actor="群友甲"))

    assert f"群友甲选择了「{choice.text_zh}」" in reply
    assert strip_event_bbcode(choice.result_zh) in reply
    assert "事件结束。" in reply
    assert event_sessions.get(101) is None
    for page_text in page_texts:
        assert page_text not in reply
    assert "LINGER" not in reply


def test_smoke_abyssal_baths_immerse_ends_without_linger(monkeypatch):
    event = get_event("sts2", "ABYSSAL_BATHS")
    session = smoke_open(monkeypatch, event)
    choice = session.visible_choices[0]
    assert choice.id == "IMMERSE"
    sequences = event.raw.get("flavor_sequences", {})

    reply = str(bot.route_group_command(101, "1", actor="群友甲"))

    assert f"群友甲选择了「{choice.text_zh}」" in reply
    assert strip_event_bbcode(choice.result_zh) in reply
    assert "事件结束。" in reply
    assert event_sessions.get(101) is None
    for texts in sequences.values():
        if isinstance(texts, list):
            for text in texts:
                assert text not in reply


def test_smoke_no_result_real_event_ends_safely(monkeypatch):
    event = get_event("sts2", "RELIC_TRADER")
    session = smoke_open(monkeypatch, event)
    assert session is not None
    choice = session.visible_choices[0]
    assert not (choice.result_zh or "").strip()

    reply = str(bot.route_group_command(101, "1", actor="群友甲"))

    assert f"群友甲选择了「{choice.text_zh}」" in reply
    assert "事件结束。" in reply
    assert event_sessions.get(101) is None

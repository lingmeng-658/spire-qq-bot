"""QQ interaction coverage for the whitelisted SLIPPERY_BRIDGE Level 2 flow."""

from __future__ import annotations

import pytest

from card_guess import event_level2
from card_guess.events import EventChoice, EventRecord
from card_guess.qq import bot, event_sessions, sessions


def _choice(choice_id: str, text: str, description: str, result: str) -> EventChoice:
    return EventChoice(
        id=choice_id,
        text_zh=text,
        description_zh=description,
        result_zh=result,
        locked_zh=None,
        raw={"id": choice_id},
    )


def slippery_bridge_fixture() -> EventRecord:
    pages = [
        {
            "id": "INITIAL",
            "description": "木桥在暴雨中摇晃。",
            "options": [
                {"id": "OVERCOME", "title": "跨越", "description": "移除一张随机卡牌。"},
                {"id": "HOLD_ON_0", "title": "再撑一会", "description": "失去[red]3[/red]点生命。"},
            ],
        }
    ]
    result_texts = {
        "HOLD_ON_0": "你正在坚持！",
        "HOLD_ON_1": "还在坚持！",
        "HOLD_ON_2": "风越来越大。",
        "HOLD_ON_3": "我能行！",
        "HOLD_ON_4": "不——",
        "HOLD_ON_5": "我在干什么？",
        "HOLD_ON_6": "暴雨没有停。",
        "HOLD_ON_LOOP": "已经没有额外的文本内容了。",
    }
    for index in range(6):
        state_id = f"HOLD_ON_{index}"
        next_id = f"HOLD_ON_{index + 1}"
        pages.append(
            {
                "id": state_id,
                "description": result_texts[state_id],
                "options": [
                    {
                        "id": next_id,
                        "title": "再撑一会",
                        "description": f"失去[red]{index + 4}[/red]点生命。",
                    }
                ],
            }
        )
    pages.extend(
        [
            {
                "id": "HOLD_ON_6",
                "description": result_texts["HOLD_ON_6"],
                "options": [
                    {"id": "HOLD_ON_LOOP", "title": "再撑一会", "description": "失去[red]10[/red]点生命。"}
                ],
            },
            {
                "id": "HOLD_ON_LOOP",
                "description": result_texts["HOLD_ON_LOOP"],
                "options": [
                    {"id": "HOLD_ON_LOOP", "title": "再撑一会", "description": "失去[red]11+[/red]点生命。"}
                ],
            },
            {"id": "OVERCOME", "description": "我恨桥。", "options": []},
        ]
    )
    return EventRecord(
        game="sts2",
        id="SLIPPERY_BRIDGE",
        name_zh="滑脚木桥",
        name_en="Slippery Bridge",
        category="Event",
        act=2,
        pool="act_specific",
        description_zh="木桥在暴雨中摇晃。",
        choices=(
            _choice("OVERCOME", "跨越", "移除一张随机卡牌。", "我恨桥。"),
            _choice("HOLD_ON_0", "再撑一会", "失去[red]3[/red]点生命。", "你正在坚持！"),
        ),
        raw={"pages": pages},
    )


def level1_fixture(event_id: str) -> EventRecord:
    return EventRecord(
        game="sts2",
        id=event_id,
        name_zh="单步事件",
        name_en="One Shot",
        category="Event",
        act=1,
        pool="act_specific",
        description_zh="单步事件。",
        choices=(_choice("ONLY", "离开", "离开。", "你离开了。"),),
        raw={},
    )


@pytest.fixture(autouse=True)
def clear_all_sessions():
    event_sessions.SESSIONS.clear()
    sessions.SESSIONS.clear()
    yield
    event_sessions.SESSIONS.clear()
    sessions.SESSIONS.clear()


def patch_event(monkeypatch, event: EventRecord) -> None:
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (event,))
    monkeypatch.setattr(bot, "get_event", lambda game, event_id: event, raising=False)


def test_initial_session_uses_initial_page_options(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)

    reply = str(bot.route_group_command(101, "事件2"))
    session = event_sessions.get(101)

    assert session is not None
    assert session.is_level2
    assert session.state_id == "INITIAL"
    assert session.step_count == 0
    assert [choice.id for choice in session.visible_choices] == ["OVERCOME", "HOLD_ON_0"]
    assert "1. 跨越" in reply
    assert "2. 再撑一会" in reply


def test_mixed_random_command_opens_level2_when_sts2_bridge_wins(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)

    def choose(items):
        if items == ("sts1", "sts2"):
            return "sts2"
        return items[0]

    monkeypatch.setattr(
        bot,
        "random",
        type("FixtureRandom", (), {"choice": staticmethod(choose)}),
    )

    bot.route_group_command(101, "事件")

    assert event_sessions.get(101).state_id == "INITIAL"


def test_overcome_is_terminal_and_clears_session(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    reply = str(bot.route_group_command(101, "1", actor="群友甲"))

    assert "群友甲选择了「跨越」" in reply
    assert "我恨桥。" in reply
    assert reply.endswith("事件结束。")
    assert event_sessions.get(101) is None


@pytest.mark.parametrize(
    ("state_id", "choice_id", "step_in", "next_state", "step_out"),
    [
        ("INITIAL", "HOLD_ON_0", 0, "HOLD_ON_0", 1),
        ("HOLD_ON_0", "HOLD_ON_1", 1, "HOLD_ON_1", 2),
        ("HOLD_ON_1", "HOLD_ON_2", 2, "HOLD_ON_2", 3),
        ("HOLD_ON_2", "HOLD_ON_3", 3, "HOLD_ON_3", 4),
        ("HOLD_ON_3", "HOLD_ON_4", 4, "HOLD_ON_4", 5),
        ("HOLD_ON_4", "HOLD_ON_5", 5, "HOLD_ON_5", 6),
        ("HOLD_ON_5", "HOLD_ON_6", 6, "HOLD_ON_6", 7),
        ("HOLD_ON_6", "HOLD_ON_LOOP", 7, "HOLD_ON_LOOP", 8),
        ("HOLD_ON_LOOP", "HOLD_ON_LOOP", 8, "HOLD_ON_LOOP", 9),
    ],
)
def test_audited_transition_chain(state_id, choice_id, step_in, next_state, step_out):
    transition = event_level2.transition(
        slippery_bridge_fixture(), state_id, choice_id, step_in
    )

    assert transition.next_state_id == next_state
    assert transition.next_step_count == step_out
    assert not transition.terminal


def test_each_state_exposes_only_its_real_page_options():
    event = slippery_bridge_fixture()

    assert [choice.id for choice in event_level2.visible_choices(event, "INITIAL", 0)] == [
        "OVERCOME",
        "HOLD_ON_0",
    ]
    assert [choice.id for choice in event_level2.visible_choices(event, "HOLD_ON_0", 1)] == [
        "HOLD_ON_1"
    ]
    assert [choice.id for choice in event_level2.visible_choices(event, "HOLD_ON_LOOP", 8)] == [
        "HOLD_ON_LOOP"
    ]


def test_hp_loss_schedule_is_three_plus_step_count():
    assert [event_level2.hp_loss_for_step(step) for step in range(10)] == list(range(3, 13))


def test_non_terminal_choices_keep_and_advance_session_with_different_actors(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)
    bot.route_group_command(101, "事件2")

    first = str(bot.route_group_command(101, "2", actor="群友甲"))
    after_first = event_sessions.get(101)
    second = str(bot.route_group_command(101, "1", actor="群友乙"))
    after_second = event_sessions.get(101)

    assert "群友甲选择了「再撑一会」" in first
    assert "失去3点生命" in first
    assert after_first.state_id == "HOLD_ON_0"
    assert after_first.step_count == 1
    assert "群友乙选择了「再撑一会」" in second
    assert "失去4点生命" in second
    assert after_second.state_id == "HOLD_ON_1"
    assert after_second.step_count == 2


@pytest.mark.parametrize("bad_input", ["abc", "0", "2", "99"])
def test_invalid_input_does_not_advance_or_clear(monkeypatch, bad_input):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    bot.route_group_command(101, "2", actor="群友甲")
    before = event_sessions.get(101)

    reply = str(bot.route_group_command(101, bad_input, actor="群友乙"))

    assert "选择了" not in reply
    assert event_sessions.get(101) == before


def test_end_immediately_clears_level2_session(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    bot.route_group_command(101, "2", actor="群友甲")

    reply = str(bot.route_group_command(101, "结束"))

    assert "互动事件已结束" in reply
    assert event_sessions.get(101) is None


@pytest.mark.parametrize("event_id", ["WELLSPRING", "AMALGAMATOR"])
def test_other_events_remain_level1(monkeypatch, event_id):
    event = level1_fixture(event_id)
    patch_event(monkeypatch, event)
    bot.route_group_command(101, "事件2")
    session = event_sessions.get(101)

    assert session is not None
    assert not session.is_level2

    reply = str(bot.route_group_command(101, "1", actor="群友甲"))
    assert reply.endswith("事件结束。")
    assert event_sessions.get(101) is None


def test_static_event_query_does_not_create_level2_session(monkeypatch):
    event = slippery_bridge_fixture()
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [])
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [])
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [])
    monkeypatch.setattr(bot, "_find_events_by_name", lambda name, generation=None: [event])

    reply = bot.route_group_command(101, "事件 滑脚木桥")

    assert reply is not None
    assert event_sessions.get(101) is None


def test_private_style_actor_still_resolves_level2(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)
    bot.route_group_command(202, "事件2", actor="你")

    reply = str(bot.route_group_command(202, "1", actor="你"))

    assert "你选择了「跨越」" in reply
    assert event_sessions.get(202) is None


def test_guess_card_session_is_not_disturbed(monkeypatch):
    class GuessFixture:
        ended = False

    guess = GuessFixture()
    sessions.SESSIONS[101] = guess
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)

    bot.route_group_command(101, "事件2")
    bot.route_group_command(101, "2", actor="群友甲")

    assert sessions.get(101) is guess
    assert event_sessions.get(101) is not None


def test_continuous_hold_on_smoke_reaches_dynamic_twelve(monkeypatch):
    event = slippery_bridge_fixture()
    patch_event(monkeypatch, event)

    outputs = [str(bot.route_group_command(101, "事件2"))]
    outputs.append(str(bot.route_group_command(101, "2", actor="群友甲")))
    for _ in range(9):
        outputs.append(str(bot.route_group_command(101, "1", actor="群友乙")))

    combined = "\n".join(outputs)
    for hp_loss in range(3, 13):
        assert f"失去{hp_loss}点生命" in combined
    session = event_sessions.get(101)
    assert session.state_id == "HOLD_ON_LOOP"
    assert session.step_count == 10

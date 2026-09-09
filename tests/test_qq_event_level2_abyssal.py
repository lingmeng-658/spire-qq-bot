from card_guess.event_level2 import is_level2_event, transition, visible_choices
from card_guess.events import get_event
from card_guess.qq import bot, event_sessions


def abyssal():
    return get_event("sts2", "ABYSSAL_BATHS")


def test_abyssal_initial_has_two_choices_and_is_level2():
    event = abyssal()
    assert is_level2_event(event)
    assert [choice.id for choice in visible_choices(event, "INITIAL", 0)] == [
        "IMMERSE",
        "ABSTAIN",
    ]


def test_abstain_is_terminal_and_immerse_enters_linger_flow():
    event = abyssal()
    abstain = transition(event, "INITIAL", "ABSTAIN", 0)
    assert abstain.terminal
    immerse = transition(event, "INITIAL", "IMMERSE", 0)
    assert immerse.next_state_id == "IMMERSE"
    assert not immerse.terminal
    assert "DEATH_WARNING" not in immerse.next_state_id


def test_abstain_interaction_cleans_session(monkeypatch):
    event_sessions.SESSIONS.clear()
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (abyssal(),))
    monkeypatch.setattr(bot.random, "choice", lambda pool: pool[0])
    monkeypatch.setattr(bot, "render_event", lambda event: "initial")
    bot.route_group_command(8, "事件2")
    reply = str(bot.route_group_command(8, "2", actor="甲"))
    assert "事件结束" in reply
    assert event_sessions.get(8) is None


def test_abyssal_linger_advances_counter_and_uses_catalog_damage_text():
    event = abyssal()
    first = transition(event, "IMMERSE", "LINGER", 0)
    second = transition(event, first.next_state_id, "LINGER", first.next_step_count)
    assert first.next_state_id == "LINGER1"
    assert second.next_state_id == "LINGER2"
    assert first.next_step_count == 1
    assert second.next_step_count == 2
    assert "5" in (visible_choices(event, "LINGER1", 1)[0].description_zh or "")
    assert "6" in (visible_choices(event, "LINGER2", 2)[0].description_zh or "")


def test_abyssal_exit_is_terminal_from_linger_without_death_warning():
    event = abyssal()
    resolved = transition(event, "LINGER3", "EXIT_BATHS", 3)
    assert resolved.next_state_id == "EXIT_BATHS"
    assert resolved.terminal
    assert "DEATH_WARNING" not in resolved.next_state_id


def test_abyssal_linger_text_exhaustion_loops_without_fabricating_death():
    event = abyssal()
    resolved = transition(event, "LINGER9", "LINGER", 9)
    assert resolved.next_state_id == "LINGER9"
    assert not resolved.terminal
    assert "DEATH_WARNING" not in resolved.next_state_id


def test_invalid_abyssal_choice_does_not_advance_session():
    event_sessions.SESSIONS.clear()
    session = event_sessions.open_if_idle(7, abyssal())
    before = session
    assert event_sessions.resolve_choice(session, "99") is None
    assert event_sessions.get(7) == before
    event_sessions.SESSIONS.clear()


def test_abyssal_group_smoke_enters_lingers_twice_then_exits(monkeypatch):
    event_sessions.SESSIONS.clear()
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (abyssal(),))
    monkeypatch.setattr(bot.random, "choice", lambda pool: pool[0])
    monkeypatch.setattr(bot, "render_event", lambda event: "initial")
    assert str(bot.route_group_command(7, "事件2")) == "initial"
    assert str(bot.route_group_command(7, "1", actor="甲"))
    assert event_sessions.get(7).state_id == "IMMERSE"
    bot.route_group_command(7, "1", actor="乙")
    assert event_sessions.get(7).state_id == "LINGER1"
    bot.route_group_command(7, "1", actor="丙")
    assert event_sessions.get(7).state_id == "LINGER2"
    bot.route_group_command(7, "2", actor="丁")
    assert event_sessions.get(7) is None

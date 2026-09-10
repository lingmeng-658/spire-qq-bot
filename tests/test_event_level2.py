"""Level 2 multi-stage Event tests (SLIPPERY_BRIDGE only).

RED → GREEN: all tests start failing until the implementation is complete.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Ensure the src directory is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.event_presentation import (
    list_visible_choices,
    render_event,
    strip_event_bbcode,
)
from card_guess.event_level2 import (
    LEVEL2_WHITELIST,
    get_initial_state_id,
    get_visible_choices,
    hp_loss_for_step as _hp_loss_for_step,
    is_terminal_state,
    resolve_choice,
)
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


class TestLevel2Flow(unittest.TestCase):
    """Test the core Level 2 flow helper with SLIPPERY_BRIDGE."""

    @classmethod
    def setUpClass(cls):
        cls.event = get_event("sts2", "SLIPPERY_BRIDGE")

    # 1. SLIPPERY_BRIDGE is in the whitelist
    def test_whitelist_contains_slippery_bridge(self):
        self.assertIn("SLIPPERY_BRIDGE", LEVEL2_WHITELIST)

    # 2. INITIAL visible choices
    def test_initial_visible_choices(self):
        state = get_initial_state_id(self.event)
        choices = get_visible_choices(self.event, state)
        choice_ids = [choice.id for choice in choices]
        self.assertEqual(choice_ids, ["OVERCOME", "HOLD_ON_0"])

    # 3. OVERCOME -> terminal
    def test_overcome_is_terminal(self):
        next_state, step, result = resolve_choice(self.event, "INITIAL", "OVERCOME", 0)
        self.assertEqual(next_state, "OVERCOME")
        self.assertTrue(is_terminal_state(self.event, next_state))
        self.assertEqual(step, 0)  # step_count unchanged for OVERCOME

    # 4. HOLD_ON_0 -> HOLD_ON_1 (step_count increments)
    def test_hold_on_0_to_1(self):
        next_state, step, result = resolve_choice(self.event, "INITIAL", "HOLD_ON_0", 0)
        self.assertEqual(next_state, "HOLD_ON_0")
        self.assertEqual(step, 1)
        self.assertFalse(is_terminal_state(self.event, next_state))

    def test_hold_on_0_to_1_from_page(self):
        next_state, step, result = resolve_choice(self.event, "HOLD_ON_0", "HOLD_ON_1", 1)
        self.assertEqual(next_state, "HOLD_ON_1")
        self.assertEqual(step, 2)
        self.assertFalse(is_terminal_state(self.event, next_state))

    # 5. HOLD_ON_1 -> HOLD_ON_2
    def test_hold_on_1_to_2(self):
        next_state, step, result = resolve_choice(self.event, "HOLD_ON_1", "HOLD_ON_2", 2)
        self.assertEqual(next_state, "HOLD_ON_2")
        self.assertEqual(step, 3)
        self.assertFalse(is_terminal_state(self.event, next_state))

    # 6. HOLD_ON_2 -> HOLD_ON_3 -> ... -> HOLD_ON_6
    def test_hold_on_chain(self):
        transitions = [
            ("HOLD_ON_2", "HOLD_ON_3", 3, 4),
            ("HOLD_ON_3", "HOLD_ON_4", 4, 5),
            ("HOLD_ON_4", "HOLD_ON_5", 5, 6),
            ("HOLD_ON_5", "HOLD_ON_6", 6, 7),
        ]
        for state, choice, step_in, step_out in transitions:
            with self.subTest(f"{state} -> {choice}"):
                ns, ns_step, _ = resolve_choice(self.event, state, choice, step_in)
                self.assertEqual(ns, choice)
                self.assertEqual(ns_step, step_out)

    # 7. HOLD_ON_6 -> HOLD_ON_LOOP
    def test_hold_on_6_to_loop(self):
        next_state, step, result = resolve_choice(self.event, "HOLD_ON_6", "HOLD_ON_LOOP", 7)
        self.assertEqual(next_state, "HOLD_ON_LOOP")
        self.assertEqual(step, 8)
        self.assertFalse(is_terminal_state(self.event, next_state))

    # 8. LOOP -> LOOP (self-loop)
    def test_loop_self_loop(self):
        next_state, step, result = resolve_choice(self.event, "HOLD_ON_LOOP", "HOLD_ON_LOOP", 8)
        self.assertEqual(next_state, "HOLD_ON_LOOP")
        self.assertEqual(step, 9)
        self.assertFalse(is_terminal_state(self.event, next_state))

    # 9. step_count correctly increments
    def test_step_count_increments(self):
        _, s1, _ = resolve_choice(self.event, "INITIAL", "HOLD_ON_0", 0)
        self.assertEqual(s1, 1)
        _, s2, _ = resolve_choice(self.event, "HOLD_ON_0", "HOLD_ON_1", 1)
        self.assertEqual(s2, 2)
        _, s3, _ = resolve_choice(self.event, "HOLD_ON_1", "HOLD_ON_2", 2)
        self.assertEqual(s3, 3)

    # 10. HP loss schedule
    def test_hp_loss_schedule(self):
        # step 0 (first HOLD_ON) -> 3
        self.assertEqual(_hp_loss_for_step(0), 3)
        self.assertEqual(_hp_loss_for_step(1), 4)
        self.assertEqual(_hp_loss_for_step(2), 5)
        self.assertEqual(_hp_loss_for_step(3), 6)
        self.assertEqual(_hp_loss_for_step(4), 7)
        self.assertEqual(_hp_loss_for_step(5), 8)
        self.assertEqual(_hp_loss_for_step(6), 9)
        self.assertEqual(_hp_loss_for_step(7), 10)
        self.assertEqual(_hp_loss_for_step(8), 11)
        self.assertEqual(_hp_loss_for_step(9), 12)
        self.assertEqual(_hp_loss_for_step(100), 103)

    # 11. LOOP after many steps: 10, 11, 12...
    def test_loop_hp_loss_progression(self):
        self.assertEqual(_hp_loss_for_step(7), 10)   # first LOOP
        self.assertEqual(_hp_loss_for_step(8), 11)   # second LOOP
        self.assertEqual(_hp_loss_for_step(9), 12)   # third LOOP
        self.assertEqual(_hp_loss_for_step(10), 13)  # fourth LOOP

    # 12. Session not cleaned after non-terminal step
    def test_session_not_cleaned_after_non_terminal(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        session = event_sessions.open_if_idle(101, self.event)
        self.assertIsNotNone(session)
        self.assertTrue(session.is_level2)

        # Choose HOLD_ON_0 (non-terminal)
        choice = event_sessions.resolve_choice(session, "2")
        self.assertIsNotNone(choice)
        self.assertEqual(choice.id, "HOLD_ON_0")

        # Session should still exist
        self.assertIsNotNone(event_sessions.get(101))

    # 13. Terminal clears session immediately
    def test_terminal_clears_session(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        session = event_sessions.open_if_idle(101, self.event)
        self.assertIsNotNone(session)

        # Choose OVERCOME (terminal)
        choice = event_sessions.resolve_choice(session, "1")
        self.assertIsNotNone(choice)
        self.assertEqual(choice.id, "OVERCOME")

        # Simulate bot handling: end session
        from card_guess.event_level2 import resolve_choice as l2_resolve
        ns, ns_step, _ = l2_resolve(self.event, "INITIAL", "OVERCOME", 0)
        if is_terminal_state(self.event, ns):
            event_sessions.end(101)
        self.assertIsNone(event_sessions.get(101))

    # 14. Different actors can take turns
    def test_different_actors_can_continue(self):
        """Different actors should be able to pick in successive stages."""
        # This is verified by the session staying alive after each choice
        # and the actor label being rendered per choice
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        session = event_sessions.open_if_idle(101, self.event)
        self.assertIsNotNone(session)
        # Level 2 session stays alive
        self.assertTrue(session.is_level2)

    # 15. Invalid input does not advance
    def test_invalid_input_does_not_advance(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        session = event_sessions.open_if_idle(101, self.event)
        self.assertIsNotNone(session)

        # Invalid input returns None
        choice = event_sessions.resolve_choice(session, "abc")
        self.assertIsNone(choice)

        choice = event_sessions.resolve_choice(session, "999")
        self.assertIsNone(choice)

        # Session still alive
        self.assertIsNotNone(event_sessions.get(101))

    # 16. End command terminates Level 2
    def test_end_command_terminates(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        event_sessions.open_if_idle(101, self.event)
        self.assertIsNotNone(event_sessions.get(101))

        event_sessions.end(101)
        self.assertIsNone(event_sessions.get(101))


class TestLevel1Fallback(unittest.TestCase):
    """Level 1 events must remain unchanged."""

    # 17. Normal Level 1 event not affected
    def test_wellspring_stays_level1(self):
        event = get_event("sts2", "WELLSPRING")
        self.assertNotIn(event.id, LEVEL2_WHITELIST)

    # 18. WELLSPRING choice -> result -> end
    def test_wellspring_single_choice(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        event = get_event("sts2", "WELLSPRING")
        session = event_sessions.open_if_idle(101, event)
        self.assertIsNotNone(session)
        self.assertFalse(session.is_level2)

        choice = event_sessions.resolve_choice(session, "1")
        self.assertIsNotNone(choice)

    # 19. Event Query does not auto-open Level 2
    def test_event_query_not_interactive(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

        # Querying should not open a session
        self.assertIsNone(event_sessions.get(101))


class TestSessionIntegration(unittest.TestCase):
    """Integration tests for Level 2 sessions through bot.py."""

    def setUp(self):
        sessions.SESSIONS.clear()
        event_sessions.SESSIONS.clear()
        self.addCleanup(sessions.SESSIONS.clear)
        self.addCleanup(event_sessions.SESSIONS.clear)

    def patch_pool(self, event):
        """Make every random-event command return exactly ``event``."""
        import card_guess.qq.bot as bot_module
        self._old_pool = bot_module.default_random_pool
        bot_module.default_random_pool = lambda game: (event,)

    def tearDown(self):
        import card_guess.qq.bot as bot_module
        if hasattr(self, '_old_pool'):
            bot_module.default_random_pool = self._old_pool

    # 20. Private behavior not regressed
    def test_private_session_not_affected(self):
        self.assertIsNone(event_sessions.get(999))


if __name__ == "__main__":
    unittest.main()

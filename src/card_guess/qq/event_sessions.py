"""Interactive Event sessions (Level 1 + Level 2).

Level 1 (the default): one-shot choice -> result -> end.
Level 2 (whitelist only): multi-stage flow with state machine transitions.
"""

from __future__ import annotations

from dataclasses import dataclass

from card_guess.event_presentation import list_visible_choices
from card_guess.event_interaction import EventInteractionKind, interaction_plan
from card_guess.events import EventChoice, EventRecord

from card_guess.event_level2 import (
    Level2Transition,
    get_initial_state_id,
    is_level2_event,
    transition,
    visible_choices,
)


@dataclass(frozen=True)
class EventInteractionSession:
    """One pending interactive STS2 event for a conversation key.

    Level 1 (single-stage):
        ``is_level2`` is ``False`` and only ``visible_choices`` is used.
        The session is removed after the first resolved choice.

    Level 2 (multi-stage):
        ``is_level2`` is ``True``, ``state_id`` tracks the current page,
        and ``step_count`` tracks how many HOLD_ON-like choices have been
        made.  The session stays alive until the player reaches a terminal
        page or explicitly sends ``结束``.
    """

    game: str
    event_id: str
    event_name_zh: str
    visible_choices: tuple[EventChoice, ...]
    state_id: str | None = None
    step_count: int = 0

    @property
    def is_level2(self) -> bool:
        return self.state_id is not None


SESSIONS: dict[object, EventInteractionSession] = {}


def get(key: object) -> EventInteractionSession | None:
    return SESSIONS.get(key)


def end(key: object) -> EventInteractionSession | None:
    return SESSIONS.pop(key, None)


def open_if_idle(
    key: object, event: EventRecord
) -> EventInteractionSession | None:
    """Create an interactive session for an STS2 event.

    Level 2 for whitelisted events; Level 1 for everything else.
    NEVER overwrites an existing interactive session.
    Returns ``None`` when no new session was created.
    """
    if key in SESSIONS:
        return SESSIONS[key]
    plan = interaction_plan(event)
    if plan.kind is EventInteractionKind.UNSUPPORTED:
        return None

    if plan.kind is EventInteractionKind.PAGE_FLOW:
        state_id = get_initial_state_id(event)
        visible = visible_choices(event, state_id, 0)
        if not visible:
            return None
        session = EventInteractionSession(
            game=event.game,
            event_id=event.id,
            event_name_zh=event.name_zh,
            visible_choices=visible,
            state_id=state_id,
            step_count=0,
        )
        SESSIONS[key] = session
        return session

    visible = list_visible_choices(event)
    if not visible:
        return None
    session = EventInteractionSession(
        game=event.game,
        event_id=event.id,
        event_name_zh=event.name_zh,
        visible_choices=visible,
    )
    SESSIONS[key] = session
    return session


def resolve_choice(
    session: EventInteractionSession, text: str
) -> EventChoice | None:
    """Return the visible choice for a valid 1-based number, else ``None``."""
    value = (text or "").strip()
    if not value.isdigit():
        return None
    index = int(value)
    if index < 1 or index > len(session.visible_choices):
        return None
    return session.visible_choices[index - 1]


def advance(
    key: object,
    event: EventRecord,
    choice: EventChoice,
) -> Level2Transition:
    """Advance and atomically replace or remove one Level 2 session."""

    session = SESSIONS.get(key)
    if session is None or session.state_id is None or choice.id is None:
        raise ValueError("no matching Level 2 session")
    resolved = transition(
        event,
        session.state_id,
        choice.id,
        session.step_count,
    )
    if resolved.terminal:
        end(key)
        return resolved

    next_choices = visible_choices(
        event,
        resolved.next_state_id,
        resolved.next_step_count,
    )
    SESSIONS[key] = EventInteractionSession(
        game=session.game,
        event_id=session.event_id,
        event_name_zh=session.event_name_zh,
        visible_choices=next_choices,
        state_id=resolved.next_state_id,
        step_count=resolved.next_step_count,
    )
    return resolved

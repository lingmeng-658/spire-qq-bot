"""Minimal one-shot interactive Event sessions (STS2, Level 1).

Owns only what an interactive round needs: the game, the event identity and
the visible choices in first-screen numbering order.  There is deliberately no
next page, transition, HP/gold/deck or vote state: a choice resolves once and
the session is removed immediately.
"""

from __future__ import annotations

from dataclasses import dataclass

from card_guess.event_presentation import list_visible_choices
from card_guess.events import EventChoice, EventRecord


@dataclass(frozen=True)
class EventInteractionSession:
    """One pending interactive STS2 event for a conversation key."""

    game: str
    event_id: str
    event_name_zh: str
    visible_choices: tuple[EventChoice, ...]


SESSIONS: dict[object, EventInteractionSession] = {}


def get(key: object) -> EventInteractionSession | None:
    return SESSIONS.get(key)


def end(key: object) -> EventInteractionSession | None:
    return SESSIONS.pop(key, None)


def open_if_idle(
    key: object, event: EventRecord
) -> EventInteractionSession | None:
    """Create an interactive session for an STS2 event with a real choice.

    Never overwrites an existing interactive session and never opens one for
    STS1 or for events without visible choices.  Returns ``None`` when no new
    session was created.
    """

    if key in SESSIONS:
        return SESSIONS[key]
    if event.game != "sts2":
        return None
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

"""Minimal Level 2 flow support for the audited STS2 slippery bridge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from card_guess.events import EventChoice, EventRecord


LEVEL2_EVENT_IDS = frozenset({"SLIPPERY_BRIDGE", "ABYSSAL_BATHS"})
FULL_QUERY_EVENT_IDS = frozenset({"SLIPPERY_BRIDGE", "ROUND_TEA_PARTY"})
# Frozen audit metadata: these events have additional pages, but no reliable
# complete static transition graph.  Query mode must say so instead of
# presenting the initial page as the whole event.
INCOMPLETE_QUERY_EVENT_IDS = frozenset(
    {
        "ABYSSAL_BATHS",
        "COLOSSAL_FLOWER",
        "TABLET_OF_TRUTH",
        "DENSE_VEGETATION",
        "PUNCH_OFF",
        "THE_LANTERN_KEY",
        "TINKER_TIME",
        "TRIAL",
        "DOLL_ROOM",
    }
)
LEVEL2_WHITELIST = LEVEL2_EVENT_IDS
INITIAL_STATE_ID = "INITIAL"


@dataclass(frozen=True)
class Level2Transition:
    """One validated transition from the current event page."""

    next_state_id: str
    next_step_count: int
    result_text: str | None
    terminal: bool


def is_level2_event(event: EventRecord) -> bool:
    return event.game == "sts2" and event.id in LEVEL2_EVENT_IDS


def is_full_query_event(event: EventRecord) -> bool:
    """Whether the audited page graph may be expanded in encyclopedia mode."""

    return event.game == "sts2" and event.id in FULL_QUERY_EVENT_IDS


def is_incomplete_query_event(event: EventRecord) -> bool:
    return event.game == "sts2" and event.id in INCOMPLETE_QUERY_EVENT_IDS


def get_initial_state_id(event: EventRecord) -> str:
    if not is_level2_event(event):
        raise ValueError(f"event {event.id!r} has no Level 2 flow")
    return INITIAL_STATE_ID


def _pages(event: EventRecord) -> tuple[Mapping[str, Any], ...]:
    pages = event.raw.get("pages", ())
    if not isinstance(pages, (list, tuple)):
        return ()
    return tuple(page for page in pages if isinstance(page, Mapping))


def _page(event: EventRecord, state_id: str) -> Mapping[str, Any] | None:
    return next((page for page in _pages(event) if page.get("id") == state_id), None)


def page_options(event: EventRecord, state_id: str) -> tuple[Mapping[str, Any], ...]:
    """Return only the options declared by the current audited page."""

    page = _page(event, state_id)
    if page is None:
        return ()
    options = page.get("options", ())
    if not isinstance(options, (list, tuple)):
        return ()
    return tuple(option for option in options if isinstance(option, Mapping))


def is_terminal_state(event: EventRecord, state_id: str) -> bool:
    page = _page(event, state_id)
    return page is not None and not page_options(event, state_id)


def hp_loss_for_step(step_count: int) -> int:
    """HP loss of the next HOLD_ON choice: 3, 4, ... without a cap."""

    return 3 + max(0, step_count)


def _normalized_initial_choice(
    event: EventRecord, option_id: str
) -> EventChoice | None:
    if option_id not in {"OVERCOME", "HOLD_ON_0", "IMMERSE", "ABSTAIN"}:
        return None
    return next((choice for choice in event.choices if choice.id == option_id), None)


def _choice_from_option(
    event: EventRecord,
    state_id: str,
    option: Mapping[str, Any],
    step_count: int,
) -> EventChoice:
    option_id = option.get("id")
    normalized = _normalized_initial_choice(event, option_id) if state_id == INITIAL_STATE_ID else None
    text = normalized.text_zh if normalized is not None else option.get("title")
    description = (
        normalized.description_zh if normalized is not None else option.get("description")
    )
    if state_id == "HOLD_ON_LOOP" and option_id == "HOLD_ON_LOOP":
        description = f"失去[red]{hp_loss_for_step(step_count)}[/red]点生命。重新随机上方选项中的卡牌。"
    return EventChoice(
        id=option_id if isinstance(option_id, str) else None,
        text_zh=text if isinstance(text, str) else None,
        description_zh=description if isinstance(description, str) else None,
        result_zh=normalized.result_zh if normalized is not None else None,
        locked_zh=None,
        raw=dict(option),
    )


def visible_choices(
    event: EventRecord, state_id: str, step_count: int
) -> tuple[EventChoice, ...]:
    """Build numbered choices from the current page's real options only."""

    return tuple(
        _choice_from_option(event, state_id, option, step_count)
        for option in page_options(event, state_id)
        if isinstance(option.get("id"), str) and option.get("id")
    )


def get_visible_choices(
    event: EventRecord, state_id: str, step_count: int = 0
) -> tuple[EventChoice, ...]:
    """Compatibility name for callers created during the Level 2 increment."""

    return visible_choices(event, state_id, step_count)


def transition(
    event: EventRecord,
    state_id: str,
    choice_id: str,
    step_count: int,
) -> Level2Transition:
    """Advance to the selected option's audited target page."""

    allowed_ids = {option.get("id") for option in page_options(event, state_id)}
    if choice_id not in allowed_ids:
        raise ValueError(f"choice {choice_id!r} is not available on page {state_id!r}")
    target_id = choice_id
    if event.id == "ABYSSAL_BATHS":
        if state_id in {"IMMERSE", "ALL"} and choice_id == "LINGER":
            target_id = "LINGER1"
        elif state_id.startswith("LINGER") and choice_id == "LINGER":
            try:
                current = int(state_id.removeprefix("LINGER"))
            except ValueError:
                current = 1
            target_id = f"LINGER{current + 1}" if current < 9 else "LINGER9"
    target = _page(event, target_id)
    if target is None:
        raise ValueError(f"target page {choice_id!r} is missing")
    next_step_count = step_count + (
        1
        if choice_id.startswith("HOLD_ON_")
        or (event.id == "ABYSSAL_BATHS" and choice_id == "LINGER")
        else 0
    )
    result_text = target.get("description")
    return Level2Transition(
        next_state_id=target_id,
        next_step_count=next_step_count,
        result_text=result_text if isinstance(result_text, str) else None,
        terminal=is_terminal_state(event, choice_id),
    )


def resolve_choice(
    event: EventRecord,
    state_id: str,
    choice_id: str,
    step_count: int,
) -> tuple[str, int, str | None]:
    """Compatibility tuple API for the original incremental unit tests."""

    resolved = transition(event, state_id, choice_id, step_count)
    return resolved.next_state_id, resolved.next_step_count, resolved.result_text

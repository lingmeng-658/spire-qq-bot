"""Pure QQ-friendly presentation helpers for Event catalog records."""

from __future__ import annotations

import re

from card_guess.events import EventChoice, EventRecord


DEFAULT_DESCRIPTION_LIMIT = 140
DESCRIPTION_BOUNDARY_START = 120

_BBCODE_RE = re.compile(
    r"\[/?(?:red|green|blue|gold|purple|aqua|sine|jitter|orange|b)\]",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARIES = "。！？!?\n"
_ACT_LABELS = {1: "第一层", 2: "第二层", 3: "第三层"}
_POOL_LABELS = {
    "shrine": "神龛",
    "shared": "共享事件",
    "ancient": "先古遗民",
}


def strip_event_bbcode(text: str | None) -> str:
    """Remove supported presentation tags while preserving their contents."""

    if not text:
        return ""
    return _BBCODE_RE.sub("", text)


def truncate_event_description(
    text: str | None,
    limit: int = DEFAULT_DESCRIPTION_LIMIT,
) -> str:
    """Strip Event BBCode and safely shorten long official zh descriptions."""

    cleaned = strip_event_bbcode(text).strip()
    if len(cleaned) <= limit:
        return cleaned

    visible = cleaned[:limit]
    boundary = max(visible.rfind(mark) for mark in _SENTENCE_BOUNDARIES)
    if boundary + 1 >= min(DESCRIPTION_BOUNDARY_START, limit):
        visible = visible[: boundary + 1]
    return visible.rstrip() + "……"


def _title_context(event: EventRecord) -> str | None:
    if event.act in _ACT_LABELS:
        return _ACT_LABELS[event.act]
    return _POOL_LABELS.get(event.pool)


def _plain_choice_text(choice: EventChoice) -> str:
    return strip_event_bbcode(choice.text_zh).strip()


def _plain_choice_description(choice: EventChoice) -> str:
    return strip_event_bbcode(choice.description_zh).strip()


def _plain_locked_text(choice: EventChoice) -> str:
    return strip_event_bbcode(choice.locked_zh).strip().rstrip("。！？!?；;，, ")


def list_visible_choices(event: EventRecord) -> tuple[EventChoice, ...]:
    """Choices that occupy a numbered slot in player-facing event output.

    ``_LOCKED`` rows are merged into their base row at render time and never
    take their own number, so they are excluded here too.  This is the single
    source of truth for both the first-screen numbering and interactive choice
    sessions.
    """

    return tuple(
        choice
        for choice in event.choices
        if not (choice.id or "").endswith("_LOCKED")
    )


def _visible_choices(event: EventRecord) -> list[tuple[EventChoice, str | None]]:
    """Pair locked rows to their unique base ID and omit orphan locked rows."""

    base_by_id: dict[str, list[EventChoice]] = {}
    for choice in event.choices:
        if not choice.id or choice.id.endswith("_LOCKED"):
            continue
        base_by_id.setdefault(choice.id, []).append(choice)

    locked_by_base: dict[str, str] = {}
    for choice in event.choices:
        if not choice.id or not choice.id.endswith("_LOCKED"):
            continue
        base_id = choice.id[: -len("_LOCKED")]
        if len(base_by_id.get(base_id, ())) != 1:
            continue
        locked_text = _plain_locked_text(choice)
        if locked_text:
            locked_by_base[base_id] = locked_text

    return [
        (choice, locked_by_base.get(choice.id or ""))
        for choice in list_visible_choices(event)
    ]


def render_event(event: EventRecord) -> str:
    """Render one Event catalog record as compact QQ plain text."""

    game_tag = event.game.upper()
    context = _title_context(event)
    title_suffix = f" · {context}" if context else ""
    sections = [f"【{event.name_zh}｜{game_tag}{title_suffix}】"]

    description = truncate_event_description(event.description_zh)
    if description:
        sections.append(description)

    choice_lines: list[str] = []
    for index, (choice, locked_text) in enumerate(_visible_choices(event), start=1):
        text = _plain_choice_text(choice)
        if not text:
            continue
        description = _plain_choice_description(choice)
        if locked_text:
            description = f"{description}（{locked_text}）" if description else f"（{locked_text}）"
        line = f"{index}. {text}"
        if description:
            line += f" —— {description}"
        choice_lines.append(line)

    if choice_lines:
        sections.append("选择：\n" + "\n".join(choice_lines))
    return "\n\n".join(sections)


def render_event_choice_outcome(choice: EventChoice, actor: str) -> str:
    """Render the one-shot outcome shown after an interactive choice.

    Uses the official zh option name and result only; when the result is empty
    the official effect description is reused as the factual outcome line.
    Nothing is invented and no next page is ever referenced.
    """

    option_name = strip_event_bbcode(choice.text_zh).strip() or "未知选项"
    sections = [f"{actor}选择了「{option_name}」"]

    result = strip_event_bbcode(choice.result_zh).strip()
    if result:
        sections.append(result)
    else:
        description = strip_event_bbcode(choice.description_zh).strip()
        if description:
            sections.append(description)

    sections.append("事件结束。")
    return "\n\n".join(sections)

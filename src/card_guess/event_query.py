"""Pure planning and QQ text rendering for Event encyclopedia queries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from card_guess.event_level2 import (
    INITIAL_STATE_ID,
    is_full_query_event,
    is_incomplete_query_event,
    transition,
    visible_choices,
)
from card_guess.event_presentation import (
    EventChoiceDisplay,
    EventDisplay,
    build_event_display,
    strip_event_bbcode,
)
from card_guess.events import EventRecord


@dataclass(frozen=True)
class EventQueryFlowLine:
    """One already-audited line in a static query flow summary."""

    depth: int
    text: str


@dataclass(frozen=True)
class EventQueryPlan:
    """Immutable inputs for one Event encyclopedia response."""

    event: EventRecord
    display: EventDisplay
    flow_lines: tuple[EventQueryFlowLine, ...] = ()
    incomplete_reason: str | None = None


def _choice_name(choice) -> str:
    return strip_event_bbcode(choice.text_zh).strip() or "未知选项"


def _choice_effect(event: EventRecord, state_id: str, choice) -> str:
    effect = strip_event_bbcode(choice.description_zh).strip()
    if (
        event.id == "SLIPPERY_BRIDGE"
        and state_id == "HOLD_ON_LOOP"
        and choice.id == "HOLD_ON_LOOP"
    ):
        effect = re.sub(r"失去(\d+)点生命", r"失去\1+点生命", effect, count=1)
    return effect


def _flow_branch(
    event: EventRecord,
    state_id: str,
    step_count: int,
    seen: frozenset[str],
    depth: int,
) -> tuple[EventQueryFlowLine, ...]:
    if state_id in seen:
        return (EventQueryFlowLine(depth, "→ 循环：后续代价继续增加"),)

    choices = visible_choices(event, state_id, step_count)
    if not choices:
        return (EventQueryFlowLine(depth, "→ 事件结束"),)

    lines: list[EventQueryFlowLine] = []
    next_seen = seen | {state_id}
    for choice in choices:
        if not choice.id:
            continue
        text = f"→ {_choice_name(choice)}"
        effect = _choice_effect(event, state_id, choice)
        if effect:
            text += f"：{effect}"
        lines.append(EventQueryFlowLine(depth, text))
        resolved = transition(event, state_id, choice.id, step_count)
        if resolved.terminal:
            lines.append(EventQueryFlowLine(depth + 1, "→ 事件结束"))
        else:
            lines.extend(
                _flow_branch(
                    event,
                    resolved.next_state_id,
                    resolved.next_step_count,
                    next_seen,
                    depth + 1,
                )
            )
    return tuple(lines)


def _full_flow_lines(event: EventRecord) -> tuple[EventQueryFlowLine, ...]:
    lines: list[EventQueryFlowLine] = []
    for choice in visible_choices(event, INITIAL_STATE_ID, 0):
        if not choice.id:
            continue
        lines.append(EventQueryFlowLine(0, f"• {_choice_name(choice)}"))
        resolved = transition(event, INITIAL_STATE_ID, choice.id, 0)
        if resolved.terminal:
            lines.append(EventQueryFlowLine(1, "→ 事件结束"))
        else:
            lines.extend(
                _flow_branch(
                    event,
                    resolved.next_state_id,
                    resolved.next_step_count,
                    frozenset({INITIAL_STATE_ID}),
                    1,
                )
            )
    return tuple(lines)


def plan_event_query(
    event: EventRecord, *, stats_snapshot: dict | None = None
) -> EventQueryPlan:
    """Build one side-effect-free encyclopedia plan from audited local data."""

    display = build_event_display(event, stats_snapshot=stats_snapshot)
    flow_lines = _full_flow_lines(event) if is_full_query_event(event) else ()
    incomplete_reason = (
        "该事件还有后续阶段，当前数据不足以可靠展开完整流程。"
        if is_incomplete_query_event(event)
        else None
    )
    return EventQueryPlan(
        event=event,
        display=display,
        flow_lines=flow_lines,
        incomplete_reason=incomplete_reason,
    )


def _render_query_choices(choices: tuple[EventChoiceDisplay, ...]) -> list[str]:
    lines: list[str] = []
    for index, choice in enumerate(choices, start=1):
        line = f"{index}. {choice.text}"
        if choice.description:
            line += f" —— {choice.description}"
        if choice.stats_text:
            line += f"\n    {choice.stats_text}"
        lines.append(line)
    return lines


def render_event_query(plan: EventQueryPlan) -> str:
    """Render an EventQueryPlan without creating or mutating any session."""

    display = plan.display
    title_suffix = f" · {display.context}" if display.context else ""
    sections = [
        f"【事件资料｜{plan.event.name_zh}｜{display.game_tag}{title_suffix}】"
    ]
    if display.description:
        sections.append(display.description)
    choice_lines = _render_query_choices(display.choices)
    if choice_lines:
        sections.append("可能的选择：\n" + "\n".join(choice_lines))
    if display.stats_footer:
        sections.append(display.stats_footer)
    if plan.flow_lines:
        lines = [
            f"{'   ' * line.depth}{line.text}"
            for line in plan.flow_lines
        ]
        sections.append("可靠后续：\n" + "\n".join(lines))
        sections.append("※ 多阶段事件；以上仅展开已验证的页面结构。")
    if plan.incomplete_reason:
        sections.append(f"※ {plan.incomplete_reason}")
    return "\n\n".join(sections)

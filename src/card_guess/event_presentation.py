"""Pure QQ-friendly presentation helpers for Event catalog records."""

from __future__ import annotations

from dataclasses import dataclass
import re

from card_guess.events import EventChoice, EventRecord
from card_guess.relics import load_relics
from card_guess.qq.relic_short_summary import short_relic_effect
from card_guess.sts1_event_stats import (
    build_cross_act_view,
    load_sts1_event_stats_snapshot,
)
from card_guess.sts1_event_stats_coverage import (
    display_slots,
    event_level_stats_only,
    mapped_keys,
)


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

# Only rewards whose concrete STS1 entity is audited in the recovery layer.
# The catalog remains the source of names and effect text.
_FIXED_STS1_EVENT_REWARDS = {
    "ACCURSED_BLACKSMITH": ("WARPEDTONGS",),
    "DRUG_DEALER": ("MUTAGENICSTRENGTH", "CIRCLET"),
    "N_LOTH": ("NLOTH_S_GIFT", "CIRCLET"),
    "TOMB_OF_LORD_RED_MASK": ("RED_MASK",),
}
_STS1_RELICS_BY_ID: dict[str, dict] | None = None

# STS2 audited fixed-relic rewards inside the playable random pool.  Each row
# maps a frozen event + visible choice to the catalog relic it grants, so the
# QQ first screen can show name + short effect before the player decides.
# Runtime/random rewards and unknown fixed entities stay categorical.
_FIXED_STS2_EVENT_REWARDS = {
    "DROWNING_BEACON": {"CLIMB": "FRESNEL_LENS"},
    "GRAVE_OF_THE_FORGOTTEN": {"ACCEPT": "FORGOTTEN_SOUL"},
    "ROOM_FULL_OF_CHEESE": {"SEARCH": "CHOSEN_CHEESE"},
    "SUNKEN_STATUE": {"GRAB_SWORD": "SWORD_OF_STONE"},
    "WAR_HISTORIAN_REPY": {"UNLOCK_CAGE": "HISTORY_COURSE"},
}
_STS2_RELICS_BY_ID: dict[str, dict] | None = None


def _fixed_sts2_reward_effects(
    event: EventRecord, choice: EventChoice
) -> str:
    """Return the audited fixed STS2 relic effect line for one choice row."""
    if event.game != "sts2":
        return ""
    relic_id = (_FIXED_STS2_EVENT_REWARDS.get(event.id) or {}).get(choice.id or "")
    if not relic_id:
        return ""
    global _STS2_RELICS_BY_ID
    if _STS2_RELICS_BY_ID is None:
        _STS2_RELICS_BY_ID = {r["id"]: r for r in load_relics("sts2")}
    relic = _STS2_RELICS_BY_ID.get(relic_id)
    if not relic:
        return ""
    name = str(relic.get("name") or "").strip()
    effect = short_relic_effect(
        relic.get("description"), relic_id=relic_id, game="sts2"
    )
    if name and effect:
        return f"遗物「{name}」\n效果：{effect}"
    return ""


def _fixed_reward_effects(event: EventRecord, choice: EventChoice) -> str:
    """Return catalog-backed effects for an audited fixed STS1 reward."""
    if event.game != "sts1" or event.id not in _FIXED_STS1_EVENT_REWARDS:
        return ""
    # Match the audited option by its stable raw English token, not display text.
    option = str((choice.raw or {}).get("option") or "")
    option_folded = option.casefold()
    if not option or not any(token in option_folded for token in (
        "obtain a special relic", "special reward", "obtain a relic."
    )):
        return ""
    global _STS1_RELICS_BY_ID
    if _STS1_RELICS_BY_ID is None:
        _STS1_RELICS_BY_ID = {r["id"]: r for r in load_relics("sts1")}
    lines = []
    for relic_id in _FIXED_STS1_EVENT_REWARDS[event.id]:
        relic = _STS1_RELICS_BY_ID.get(relic_id)
        if not relic:
            continue
        name = str(relic.get("name") or "").strip()
        effect = short_relic_effect(
            relic.get("description"), relic_id=relic_id, game="sts1"
        )
        if name and effect:
            lines.append(f"遗物「{name}」\n效果：{effect}")
    return "\n".join(lines)


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


# STS1 Event Stats are a QQ enhancement over the plain catalog first screen.
# The artifact is generated data with frozen aggregation semantics; this layer
# only loads it and attaches compact per-choice lines before a player decides.
_EVENT_STATS_LOADER = load_sts1_event_stats_snapshot
_EVENT_STATS_SNAPSHOT: dict | None = None


def _event_stats_snapshot() -> dict:
    """Load the validated STS1 Event Stats snapshot once (empty on failure)."""

    global _EVENT_STATS_SNAPSHOT
    if _EVENT_STATS_SNAPSHOT is None:
        _EVENT_STATS_SNAPSHOT = _EVENT_STATS_LOADER()
    return _EVENT_STATS_SNAPSHOT


_SHARE_LABEL = "选项占比"
_WIN_RATE_LABEL = "关联胜率"
_SAMPLE_FOOTER = "样本：{:,} 次遭遇"
_STATS_DISCLAIMER = "※ 选项占比不是“可选时选择率”；关联胜率仅表示历史关联，不代表因果。"

_STATS_ACT_KEYS = ("act_1", "act_2", "act_3")

def _event_stats_view(
    snapshot: dict, event: EventRecord
) -> tuple[dict | None, bool]:
    """Resolve the QQ stats view for one event.

    Returns ``(view, cross_act)``:
    - events with a concrete catalog act use that act bucket only;
    - act-less events with a single observed act keep that single bucket;
    - act-less events with several observed acts get a cross-act view whose
      percentages are recomputed from summed underlying counts.
    """

    if event.game != "sts1" or not isinstance(snapshot, dict):
        return None, False
    events = snapshot.get("events")
    if not isinstance(events, list):
        return None, False
    row = None
    for item in events:
        if isinstance(item, dict) and item.get("id") == event.id:
            row = item
            break
    if row is None:
        return None, False
    acts = row.get("acts")
    if not isinstance(acts, dict) or not acts:
        return None, False
    if event.act in (1, 2, 3):
        act_map = acts.get(f"act_{event.act}")
        return (act_map if isinstance(act_map, dict) else None), False
    present = [key for key in _STATS_ACT_KEYS if isinstance(acts.get(key), dict)]
    if len(present) == 1:
        return (acts[present[0]] if isinstance(acts[present[0]], dict) else None), False
    return build_cross_act_view(row), True


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _option_line_from_row(option: dict) -> str | None:
    """Render one pre-aggregated snapshot row to a compact stats line."""

    share = option.get("chosen_share")
    if not isinstance(share, dict):
        return None
    share_value = share.get("value")
    if not _number(share_value):
        return None
    text = f"{_SHARE_LABEL} {share_value:.1f}%"
    association = option.get("associated_win_rate")
    if isinstance(association, dict):
        win_value = association.get("value")
        if _number(win_value):
            text += f" · {_WIN_RATE_LABEL} {win_value:.1f}%"
    return text


def _option_line_merged(view: dict, options: list[dict]) -> str | None:
    """Merge several dump rows that describe the same visible decision."""

    share_rows = [o.get("chosen_share") for o in options]
    if not all(isinstance(row, dict) and _number(row.get("value")) for row in share_rows):
        return None
    encounters = view.get("encounters")
    if not _number(encounters) or encounters <= 0:
        return None
    numerator = sum(int(row.get("numerator", 0)) for row in share_rows)
    share_value = numerator / encounters * 100
    text = f"{_SHARE_LABEL} {share_value:.1f}%"
    association_rows = [
        o.get("associated_win_rate")
        for o in options
        if isinstance(o.get("associated_win_rate"), dict)
    ]
    wins = sum(int(a.get("numerator", 0)) for a in association_rows)
    cohort = sum(int(o.get("chosen_count", 0)) for o in options if isinstance(o.get("associated_win_rate"), dict))
    if association_rows and cohort > 0 and _number(wins):
        text += f" · {_WIN_RATE_LABEL} {wins / cohort * 100:.1f}%"
    return text


def _event_stats_choice_line(
    event: EventRecord, slot_index: int, view: dict
) -> str | None:
    """Compact one-line choice stats (None when slot is exempt/no data)."""

    keys = mapped_keys(event.id, slot_index)
    if not keys:
        return None
    options = view.get("options")
    if not isinstance(options, list):
        return None
    wanted = {key for key in keys}
    matches = [
        option
        for option in options
        if isinstance(option, dict) and option.get("choice_key") in wanted
    ]
    if not matches:
        return None
    if len(matches) == 1:
        return _option_line_from_row(matches[0])
    return _option_line_merged(view, matches)


def _event_stats_footer(
    view: dict, *, cross_act: bool = False, event_level: bool = False
) -> str | None:
    """Sample-size footer plus the once-only metric disclaimer."""

    encounters = view.get("encounters")
    if (
        not isinstance(encounters, int)
        or isinstance(encounters, bool)
        or encounters <= 0
    ):
        return None
    sample = _SAMPLE_FOOTER.format(encounters)
    markers = []
    if cross_act:
        markers.append("跨幕汇总")
    if event_level:
        markers.append("事件级")
    if markers:
        sample += "（" + " · ".join(markers) + "）"
    return f"{sample}\n{_STATS_DISCLAIMER}"


@dataclass(frozen=True)
class EventChoiceDisplay:
    """Shared enriched choice data for query and interaction presentation."""

    text: str
    description: str
    stats_text: str | None


@dataclass(frozen=True)
class EventDisplay:
    """Shared normalized Event data without query/interaction wording."""

    game_tag: str
    context: str | None
    description: str
    choices: tuple[EventChoiceDisplay, ...]
    stats_footer: str | None


def build_event_display(
    event: EventRecord, *, stats_snapshot: dict | None = None
) -> EventDisplay:
    """Enrich normalized choices once for both presentation modes."""

    snapshot = (
        stats_snapshot
        if stats_snapshot is not None
        else _event_stats_snapshot()
    )
    view, cross_act = _event_stats_view(snapshot, event)
    slot_index_by_choice = {
        id(choice): index
        for index, choice in enumerate(display_slots(event))
    }
    choices: list[EventChoiceDisplay] = []
    stats_shown = False
    for choice, locked_text in _visible_choices(event):
        text = _plain_choice_text(choice)
        if not text:
            continue
        description = _plain_choice_description(choice)
        reward_effects = _fixed_reward_effects(event, choice)
        if reward_effects:
            description = (
                f"{description}\n{reward_effects}" if description else reward_effects
            )
        sts2_effects = _fixed_sts2_reward_effects(event, choice)
        if sts2_effects:
            description = (
                f"{description}\n{sts2_effects}" if description else sts2_effects
            )
        if locked_text:
            description = (
                f"{description}（{locked_text}）"
                if description
                else f"（{locked_text}）"
            )
        slot_index = slot_index_by_choice.get(id(choice))
        stats_text = None
        if view is not None and slot_index is not None:
            stats_text = _event_stats_choice_line(event, slot_index, view)
        if stats_text:
            stats_shown = True
        choices.append(EventChoiceDisplay(text, description, stats_text))

    footer = None
    if view is not None:
        if stats_shown:
            footer = _event_stats_footer(
                view, cross_act=cross_act, event_level=False
            )
        elif (
            event.game == "sts1"
            and event_level_stats_only(event.id)
            and isinstance(view.get("encounters"), int)
            and view["encounters"] > 0
        ):
            footer = _event_stats_footer(
                view, cross_act=cross_act, event_level=True
            )
    return EventDisplay(
        game_tag=event.game.upper(),
        context=_title_context(event),
        description=truncate_event_description(event.description_zh),
        choices=tuple(choices),
        stats_footer=footer,
    )


def _render_display_choices(display: EventDisplay) -> list[str]:
    lines: list[str] = []
    for index, choice in enumerate(display.choices, start=1):
        line = f"{index}. {choice.text}"
        if choice.description:
            line += f" —— {choice.description}"
        if choice.stats_text:
            line += f"\n    {choice.stats_text}"
        lines.append(line)
    return lines


def render_event(
    event: EventRecord, *, stats_snapshot: dict | None = None
) -> str:
    """Render one Event catalog record as compact QQ plain text.

    ``stats_snapshot`` is an optional injected validated snapshot for callers
    that already hold one; the default loads the generated artifact through the
    safe loader (which degrades to no stats when unavailable).
    """

    display = build_event_display(event, stats_snapshot=stats_snapshot)
    title_suffix = f" · {display.context}" if display.context else ""
    sections = [f"【{event.name_zh}｜{display.game_tag}{title_suffix}】"]

    if display.description:
        sections.append(display.description)
    choice_lines = _render_display_choices(display)
    if choice_lines:
        sections.append("选择：\n" + "\n".join(choice_lines))
    if display.stats_footer:
        sections.append(display.stats_footer)
    return "\n\n".join(sections)

def render_event_unsupported(event: EventRecord, reason: str) -> str:
    """Render catalog information without suggesting that replies are accepted."""

    text = render_event(event).replace("选择：", "可能的选择：", 1)
    return text + f"\n\n※ {reason}"


def render_event_full_query(event: EventRecord) -> str:
    """Compatibility entry point for the separated encyclopedia renderer."""

    from card_guess.event_query import plan_event_query, render_event_query

    return render_event_query(plan_event_query(event))


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


def render_event_level2_outcome(
    choice: EventChoice,
    actor: str,
    result_text: str | None,
    next_choices: tuple[EventChoice, ...],
    *,
    terminal: bool,
) -> str:
    """Render one Level 2 result and, when present, the next page choices."""

    option_name = strip_event_bbcode(choice.text_zh).strip() or "未知选项"
    sections = [f"{actor}选择了「{option_name}」"]

    effect = strip_event_bbcode(choice.description_zh).strip()
    if effect:
        sections.append(effect)

    result = strip_event_bbcode(result_text).strip()
    if result and result != effect:
        sections.append(result)

    if next_choices:
        lines = []
        for index, next_choice in enumerate(next_choices, start=1):
            text = strip_event_bbcode(next_choice.text_zh).strip() or "未知选项"
            description = strip_event_bbcode(next_choice.description_zh).strip()
            line = f"{index}. {text}"
            if description:
                line += f" —— {description}"
            lines.append(line)
        sections.append("选择：\n" + "\n".join(lines))

    if terminal:
        sections.append("事件结束。")
    return "\n\n".join(sections)

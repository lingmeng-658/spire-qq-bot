"""STS1 Event Stats full-coverage registry (52 catalog events).

Every player-visible choice of every STS1 catalog event must be either mapped
to the audited official-dump ``player_choice`` string(s) that the same real
decision records, or explicitly exempted with a stable reason category.

``silent_missing = 0`` is an enforced invariant: the plan length must equal the
catalog's current display-slot count, so a catalog edit can never silently add
a visible choice without an explicit mapping or exemption.

This module is pure data + coverage bookkeeping.  It never reads raw run data
and never renders QQ text.
"""

from __future__ import annotations

import re

from card_guess.events import EventChoice

# Player-visible slot label is empty after removing supported BBCode.
_BBCODE_RE = re.compile(
    r"\[/?(?:red|green|blue|gold|purple|aqua|sine|jitter|orange|b)\]",
    re.IGNORECASE,
)

# Exemption reason categories (dev-facing; stable for reporting and tests).
PAGE_FLOW = "page_flow"  # intermediate next/continue page, not a parallel decision
NO_DUMP_CHOICE = "no_dump_choice"  # catalog visible row has no recorded dump counterpart
STAGE_AMBIGUOUS = "stage_ambiguous"  # terminal dump records merge stages; split unverifiable
OUTCOME_VARIANT = "outcome_variant"  # one action logs several outcome strings
DUPLICATE_ROW = "duplicate_catalog_row"  # catalog row duplicates another row's only string
NO_OCCURRENCE = "no_occurrence"  # event has no recorded event_choices in the audited dump

# Per event id, one descriptor per display slot, in display order.
#   "M:key1;key2"  -> audited mapping to dump player_choice string(s)
#   "E:<category>" -> explicit exemption
_PLANS: dict[str, tuple[str, ...]] = {
    "ACCURSED_BLACKSMITH": ("M:Forge", "M:Rummage", "E:no_dump_choice"),
    "ADDICT": ("M:Obtained Relic", "M:Stole Relic", "M:Ignored"),
    "BACK_TO_BASICS": ("M:Elegance", "M:Simplicity", "E:no_dump_choice"),
    "BEGGAR": ("M:Gave Gold", "E:page_flow", "M:Ignored"),
    "BIG_FISH": ("M:Banana", "M:Donut", "M:Box", "E:no_dump_choice"),
    "BONFIRE_ELEMENTALS": ("E:page_flow", "E:no_dump_choice", "E:outcome_variant"),
    "COLOSSEUM": ("E:stage_ambiguous",) * 4,
    "CURSED_TOME": (
        "E:page_flow",
        "E:page_flow",
        "E:page_flow",
        "E:page_flow",
        "M:Stopped",
        "M:Obtained Book",
        "M:Ignored",
    ),
    "DEAD_ADVENTURER": ("E:outcome_variant", "E:no_dump_choice"),
    "DESIGNER": (
        "M:Upgrade",
        "M:Single Remove",
        "M:Upgrade and Remove",
        "M:Punched",
    ),
    "DRUG_DEALER": (
        "M:Obtain J.A.X.",
        "M:Became Test Subject",
        "M:Inject Mutagens",
        "M:Ignored",
    ),
    "DUPLICATOR": ("M:Copied", "M:Ignored"),
    "FACETRADER": ("M:Touch", "M:Trade", "M:Leave", "E:page_flow"),
    "FALLING": ("M:Removed Skill", "M:Removed Power", "M:Removed Attack"),
    "FOUNTAIN_OF_CLEANSING": ("M:Removed Curses", "M:Ignored"),
    "GHOSTS": ("M:Became a Ghost", "M:Ignored"),
    "GOLDEN_SHRINE": ("M:Pray", "M:Desecrate", "M:Ignored"),
    "GOLDEN_WING": ("M:Card Removal", "M:Gained Gold", "M:Ignored"),
    "KNOWING_SKULL": (
        "E:page_flow",
        "E:stage_ambiguous",
        "E:stage_ambiguous",
        "E:stage_ambiguous",
        "E:stage_ambiguous",
        "E:stage_ambiguous",
        "E:stage_ambiguous",
    ),
    "LAB": ("M:Got Potions",),
    "LIARS_GAME": ("M:AGREE;agreed", "M:Ignored;disagreed"),
    "LIVING_WALL": ("M:Forget", "M:Change", "M:Grow", "E:no_dump_choice"),
    "MASKED_BANDITS": ("M:Paid Fearfully", "M:Fought Bandits", "E:page_flow", "E:no_dump_choice"),
    "MATCH_AND_KEEP": ("E:page_flow", "E:no_dump_choice", "E:outcome_variant"),
    "MINDBLOOM": ("M:Fight", "M:Gold", "M:Heal", "M:Upgrade", "E:no_dump_choice"),
    "MUSHROOMS": ("E:stage_ambiguous", "M:Healed and dodged fight", "M:Fought Mushrooms", "E:no_dump_choice"),
    "MYSTERIOUS_SPHERE": ("M:Fight", "M:Ignored;Ignore", "E:duplicate_catalog_row"),
    "N_LOTH": ("M:Traded Relic;Traded a Whetstone", "M:Ignored"),
    "NEST": ("E:stage_ambiguous", "E:stage_ambiguous"),
    "NOTEFORYOURSELF": ("E:page_flow", "M:Took Card", "M:Ignored", "E:duplicate_catalog_row"),
    "PURIFIER": ("M:Purged", "M:Ignored"),
    "SCRAP_OOZE": ("M:Success;success", "M:Fled"),
    "SECRETPORTAL": ("M:Took Portal;Took Portal.", "M:Ignored"),
    "SENSORYSTONE": ("M:Memory 1", "M:Memory 2", "M:Memory 3"),
    "SHINING_LIGHT": ("M:Entered Light", "M:Ignored"),
    "SPIRE_HEART": ("E:no_occurrence",),
    "THE_CLERIC": ("M:Healed", "M:Card Removal", "M:Leave"),
    "THE_JOUST": ("M:Bet on Owner", "M:Bet on Murderer", "E:no_dump_choice"),
    "THE_LIBRARY": ("M:Read", "M:Heal"),
    "THE_MAUSOLEUM": ("M:Opened", "M:Ignored"),
    "THE_MOAI_HEAD": ("M:Heal", "M:Gave Idol"),
    "THE_WOMAN_IN_BLUE": (
        "M:Bought 1 Potion",
        "M:Bought 2 Potions",
        "M:Bought 3 Potions",
        "M:Bought 0 Potions",
    ),
    "TOMB_OF_LORD_RED_MASK": ("M:Wore Mask", "M:Paid", "M:Ignored"),
    "TRANSMORGRIFIER": ("M:Transformed", "M:Ignored"),
    "UPGRADE_SHRINE": ("M:Upgraded", "M:Ignored"),
    "VAMPIRES": ("M:Became a vampire;Became a vampire (Vial)", "M:Ignored", "E:duplicate_catalog_row"),
    "WEMEETAGAIN": ("M:Gave Potion", "M:Paid Gold", "M:Gave Card", "E:stage_ambiguous"),
    "WHEEL_OF_CHANGE": ("E:outcome_variant",),
    "WINDING_HALLS": ("M:Max HP", "M:Embrace Madness", "M:Writhe"),
    "WORLD_OF_GOOP": ("M:Gather Gold", "M:Left Gold;Left"),
}

# Events whose dump terminal strings cannot be split into per-visible rows but
# that still have reliable occurrence data.  They show an event-level sample
# footer instead of per-choice lines (registered fallback, never silent).
EVENT_LEVEL_STATS_ONLY: frozenset[str] = frozenset(
    {
        "BONFIRE_ELEMENTALS",
        "COLOSSEUM",
        "DEAD_ADVENTURER",
        "KNOWING_SKULL",
        "MATCH_AND_KEEP",
        "NEST",
        "WHEEL_OF_CHANGE",
    }
)


def display_slots(event) -> tuple[EventChoice, ...]:
    """Choices that occupy a numbered slot in QQ output.

    Mirrors the first-screen rule: ``*_LOCKED`` rows are never numbered and a
    choice with no visible label occupies no slot.
    """

    slots = []
    for choice in event.choices:
        if (choice.id or "").endswith("_LOCKED"):
            continue
        label = _BBCODE_RE.sub("", choice.text_zh or "").strip()
        if label:
            slots.append(choice)
    return tuple(slots)


def slot_entry(event_id: str, index: int) -> tuple[str, tuple[str, ...]] | None:
    """Return ``("M", keys)`` / ``("E", category)`` for one display slot."""

    plan = _PLANS.get(event_id)
    if plan is None or not 0 <= index < len(plan):
        return None
    descriptor = plan[index]
    if descriptor.startswith("M:"):
        return ("M", tuple(key for key in descriptor[2:].split(";") if key))
    if descriptor.startswith("E:"):
        return ("E", (descriptor[2:],))
    raise ValueError(f"invalid coverage descriptor {descriptor!r} for {event_id}[{index}]")


def mapped_keys(event_id: str, index: int) -> tuple[str, ...] | None:
    entry = slot_entry(event_id, index)
    if entry is None or entry[0] != "M":
        return None
    return entry[1]


def exempt_category(event_id: str, index: int) -> str | None:
    entry = slot_entry(event_id, index)
    if entry is None or entry[0] != "E":
        return None
    return entry[1][0]


def event_level_stats_only(event_id: str) -> bool:
    return event_id in EVENT_LEVEL_STATS_ONLY

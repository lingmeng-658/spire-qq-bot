"""Small, explicit policy for Event interaction support.

STS1 and STS2 keep frozen audited eligibility lists.  A catalog event is
random-playable only when the QQ resolver can complete a meaningful
interaction today:

- Level-2 whitelisted events (SLIPPERY_BRIDGE, ABYSSAL_BATHS) advance through
  an implemented state machine;
- STS1/STS2 Level-1 events are single-decision events whose every visible
  choice ends in an audited terminal result.

All remaining catalog events (multi-stage flows without a resolver, combat or
mystery rewards with no terminal result, ancient catalog records without
interactive choices, ...) are unsupported for the random pool while remaining
fully queryable by exact name.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from card_guess.event_level2 import is_level2_event
from card_guess.events import EventRecord


class EventInteractionKind(str, Enum):
    TERMINAL = "terminal"
    PAGE_FLOW = "page_flow"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class EventInteractionPlan:
    kind: EventInteractionKind
    unsupported_reason: str | None = None

    @property
    def supported(self) -> bool:
        return self.kind is not EventInteractionKind.UNSUPPORTED


STS1_PLAYABLE_EVENT_IDS = frozenset(
    {
        "ADDICT", "FOUNTAIN_OF_CLEANSING", "GHOSTS", "GOLDEN_SHRINE",
        "N_LOTH", "NEST", "THE_MOAI_HEAD", "THE_WOMAN_IN_BLUE", "VAMPIRES",
        "WORLD_OF_GOOP", "BIG_FISH", "THE_MAUSOLEUM",
        "TOMB_OF_LORD_RED_MASK", "NOTEFORYOURSELF", "BACK_TO_BASICS",
        "DRUG_DEALER", "DESIGNER", "DUPLICATOR", "FACETRADER", "LIVING_WALL",
        "PURIFIER", "SECRETPORTAL", "SENSORYSTONE", "SHINING_LIGHT",
        "THE_CLERIC", "ACCURSED_BLACKSMITH", "BONFIRE_ELEMENTALS", "THE_LIBRARY",
        "GOLDEN_WING", "BEGGAR", "LAB", "TRANSMORGRIFIER", "UPGRADE_SHRINE",
    }
)
STS1_UNSUPPORTED_EVENT_IDS = frozenset(
    {
        "CURSED_TOME", "DEAD_ADVENTURER", "KNOWING_SKULL", "SCRAP_OOZE",
        "MATCH_AND_KEEP", "COLOSSEUM", "MASKED_BANDITS", "MYSTERIOUS_SPHERE",
        "SPIRE_HEART", "WHEEL_OF_CHANGE", "FALLING", "MINDBLOOM", "MUSHROOMS",
        "THE_JOUST", "WEMEETAGAIN", "WINDING_HALLS", "GOLDEN_IDOL",
        "FORGOTTEN_ALTAR", "LIARS_GAME",
    }
)

# STS2 audited v1: 40 playable / 26 unsupported, disjoint, full 66 coverage.
STS2_PLAYABLE_EVENT_IDS = frozenset(
    {
        "ABYSSAL_BATHS", "AMALGAMATOR", "AROMA_OF_CHAOS", "BRAIN_LEECH",
        "BUGSLAYER", "BYRDONIS_NEST", "CRYSTAL_SPHERE",
        "DOORS_OF_LIGHT_AND_DARK", "DROWNING_BEACON", "ENDLESS_CONVEYOR",
        "FIELD_OF_MAN_SIZED_HOLES", "GRAVE_OF_THE_FORGOTTEN",
        "HUNGRY_FOR_MUSHROOMS", "INFESTED_AUTOMATON",
        "JUNGLE_MAZE_ADVENTURE", "LOST_WISP", "LUMINOUS_CHOIR",
        "MORPHIC_GROVE", "POTION_COURIER", "RANWID_THE_ELDER",
        "REFLECTIONS", "ROOM_FULL_OF_CHEESE", "SAPPHIRE_SEED",
        "SELF_HELP_BOOK", "SLIPPERY_BRIDGE", "SPIRALING_WHIRLPOOL",
        "SPIRIT_GRAFTER", "STONE_OF_ALL_TIME", "SUNKEN_STATUE",
        "SUNKEN_TREASURY", "SYMBIOTE", "THE_LEGENDS_WERE_TRUE",
        "THIS_OR_THAT", "TRASH_HEAP", "UNREST_SITE", "WAR_HISTORIAN_REPY",
        "WATERLOGGED_SCRIPTORIUM", "WELLSPRING", "WHISPERING_HOLLOW",
        "WOOD_CARVINGS",
    }
)
STS2_UNSUPPORTED_EVENT_IDS = frozenset(
    {
        "BATTLEWORN_DUMMY", "COLORFUL_PHILOSOPHERS", "COLOSSAL_FLOWER",
        "DARV", "DENSE_VEGETATION", "DOLL_ROOM", "FAKE_MERCHANT", "NEOW",
        "NONUPEIPE", "OROBAS", "PAEL", "PUNCH_OFF", "RELIC_TRADER",
        "ROUND_TEA_PARTY", "TABLET_OF_TRUTH", "TANX", "TEA_MASTER",
        "TEZCATARA", "THE_ARCHITECT", "THE_FUTURE_OF_POTIONS",
        "THE_LANTERN_KEY", "TINKER_TIME", "TRIAL", "VAKUU",
        "WELCOME_TO_WONGOS", "ZEN_WEAVER",
    }
)


def interaction_plan(event: EventRecord) -> EventInteractionPlan:
    if is_level2_event(event):
        return EventInteractionPlan(EventInteractionKind.PAGE_FLOW)
    if event.game == "sts1" and event.id in STS1_PLAYABLE_EVENT_IDS:
        return EventInteractionPlan(EventInteractionKind.TERMINAL)
    if event.game == "sts2" and event.id in STS2_PLAYABLE_EVENT_IDS:
        return EventInteractionPlan(EventInteractionKind.TERMINAL)
    return EventInteractionPlan(
        EventInteractionKind.UNSUPPORTED,
        "该事件包含当前暂未支持的后续流程，仅展示事件资料。",
    )


def supported_interaction_events(
    events: Iterable[EventRecord],
) -> tuple[EventRecord, ...]:
    """Return events whose current interaction plan is player-playable."""
    return tuple(event for event in events if interaction_plan(event).supported)

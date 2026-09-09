"""STS2 Event random-pool eligibility tests (audited v1).

Only events the current implementation can complete meaningfully are
random-playable: the two Level-2 whitelisted multi-stage events plus
single-decision events where every visible choice has an audited terminal
result.  Everything else is query-only and must never be randomly drawn.
"""

from __future__ import annotations

import pytest

from card_guess.event_interaction import (
    STS2_PLAYABLE_EVENT_IDS,
    STS2_UNSUPPORTED_EVENT_IDS,
    EventInteractionKind,
    interaction_plan,
    supported_interaction_events,
)
from card_guess.event_level2 import LEVEL2_EVENT_IDS
from card_guess.events import default_random_pool, get_event, load_events


EXPECTED_PLAYABLE = frozenset(
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

EXPECTED_UNSUPPORTED = frozenset(
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


def _ids(events):
    return {event.id for event in events}


def _pages(event):
    pages = event.raw.get("pages") or ()
    if not isinstance(pages, (list, tuple)):
        return ()
    return tuple(page for page in pages if isinstance(page, dict))


def _visible_choices(event):
    return [
        choice
        for choice in event.choices
        if not (choice.id or "").endswith("_LOCKED")
    ]


def _terminal_page_exists(event, page_id):
    for page in _pages(event):
        if page.get("id") != page_id:
            continue
        options = page.get("options") or ()
        return not (isinstance(options, (list, tuple)) and options)
    return False


def test_sts2_playable_ids_are_40_real_catalog_ids():
    catalog_ids = _ids(load_events("sts2").events)

    assert STS2_PLAYABLE_EVENT_IDS == EXPECTED_PLAYABLE
    assert len(STS2_PLAYABLE_EVENT_IDS) == 40
    assert STS2_PLAYABLE_EVENT_IDS <= catalog_ids


def test_sts2_playable_and_unsupported_ids_partition_all_66_catalog_ids():
    catalog_ids = _ids(load_events("sts2").events)

    assert STS2_UNSUPPORTED_EVENT_IDS == EXPECTED_UNSUPPORTED
    assert len(STS2_UNSUPPORTED_EVENT_IDS) == 26
    assert STS2_PLAYABLE_EVENT_IDS.isdisjoint(STS2_UNSUPPORTED_EVENT_IDS)
    assert STS2_PLAYABLE_EVENT_IDS | STS2_UNSUPPORTED_EVENT_IDS == catalog_ids
    assert len(catalog_ids) == 66


def test_every_frozen_playable_id_has_a_working_interaction_plan():
    for event_id in STS2_PLAYABLE_EVENT_IDS:
        plan = interaction_plan(get_event("sts2", event_id))
        assert plan.supported
        if event_id in LEVEL2_EVENT_IDS:
            assert plan.kind is EventInteractionKind.PAGE_FLOW
        else:
            assert plan.kind is EventInteractionKind.TERMINAL


def test_every_frozen_unsupported_id_has_unsupported_interaction_plan():
    for event_id in STS2_UNSUPPORTED_EVENT_IDS:
        assert interaction_plan(get_event("sts2", event_id)).kind is (
            EventInteractionKind.UNSUPPORTED
        )


def test_slippery_bridge_and_abyssal_baths_stay_playable():
    for event_id in ("SLIPPERY_BRIDGE", "ABYSSAL_BATHS"):
        assert event_id in STS2_PLAYABLE_EVENT_IDS
        assert interaction_plan(get_event("sts2", event_id)).supported


def test_final_random_pool_is_exactly_the_40_playable_events():
    pool = supported_interaction_events(default_random_pool("sts2"))

    assert _ids(pool) == STS2_PLAYABLE_EVENT_IDS
    assert len(pool) == 40
    assert _ids(pool).isdisjoint(STS2_UNSUPPORTED_EVENT_IDS)


def test_known_unsupported_samples_are_never_in_the_random_pool():
    for event_id in (
        "COLOSSAL_FLOWER",
        "ROUND_TEA_PARTY",
        "RELIC_TRADER",
        "TRIAL",
        "TINKER_TIME",
        "DENSE_VEGETATION",
    ):
        assert event_id in STS2_UNSUPPORTED_EVENT_IDS
        assert event_id not in _ids(supported_interaction_events(default_random_pool("sts2")))


def test_unsupported_events_still_resolve_from_the_catalog_for_direct_queries():
    for event_id in ("COLOSSAL_FLOWER", "RELIC_TRADER", "ROUND_TEA_PARTY"):
        record = get_event("sts2", event_id)
        assert record.name_zh
        assert interaction_plan(record).kind is EventInteractionKind.UNSUPPORTED


def test_non_level2_playable_events_are_single_decision_complete():
    """Frozen playable rows must keep the audited one-shot structure."""

    for event_id in STS2_PLAYABLE_EVENT_IDS - LEVEL2_EVENT_IDS:
        event = get_event("sts2", event_id)
        visible = _visible_choices(event)
        assert visible, event_id
        for choice in visible:
            assert (choice.result_zh or "").strip(), (event_id, choice.id)
            assert _terminal_page_exists(event, choice.id or ""), (
                event_id,
                choice.id,
            )

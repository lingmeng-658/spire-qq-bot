"""Frozen Event interaction eligibility policy tests (STS1 + STS2)."""

from __future__ import annotations

from card_guess.event_interaction import (
    STS1_PLAYABLE_EVENT_IDS,
    STS1_UNSUPPORTED_EVENT_IDS,
    STS2_PLAYABLE_EVENT_IDS,
    STS2_UNSUPPORTED_EVENT_IDS,
    EventInteractionKind,
    interaction_plan,
    supported_interaction_events,
)
from card_guess.events import default_random_pool, get_event, load_events


def _ids(events):
    return {event.id for event in events}


def test_sts1_playable_ids_are_33_unique_real_catalog_ids_without_aliases():
    catalog_ids = _ids(load_events("sts1").events)

    assert isinstance(STS1_PLAYABLE_EVENT_IDS, frozenset)
    assert len(STS1_PLAYABLE_EVENT_IDS) == 33
    assert STS1_PLAYABLE_EVENT_IDS <= catalog_ids
    assert "GOOP_PUDDLE" not in STS1_PLAYABLE_EVENT_IDS
    assert {"TRANSMORGRIFIER", "UPGRADE_SHRINE"} <= STS1_PLAYABLE_EVENT_IDS


def test_sts1_playable_and_unsupported_ids_partition_the_real_catalog():
    catalog_ids = _ids(load_events("sts1").events)

    assert STS1_PLAYABLE_EVENT_IDS.isdisjoint(STS1_UNSUPPORTED_EVENT_IDS)
    assert STS1_PLAYABLE_EVENT_IDS | STS1_UNSUPPORTED_EVENT_IDS == catalog_ids
    assert all(
        interaction_plan(get_event("sts1", event_id)).kind
        is EventInteractionKind.UNSUPPORTED
        for event_id in STS1_UNSUPPORTED_EVENT_IDS
    )


def test_sts1_random_interaction_pool_contains_exactly_33_playable_events():
    pool = supported_interaction_events(default_random_pool("sts1"))

    assert len(pool) == 33
    assert _ids(pool) == STS1_PLAYABLE_EVENT_IDS
    assert {"MATCH_AND_KEEP", "MUSHROOMS", "FALLING"}.isdisjoint(_ids(pool))


def test_transmogrifier_and_upgrade_shrine_are_interaction_eligible():
    for event_id in ("TRANSMORGRIFIER", "UPGRADE_SHRINE"):
        assert interaction_plan(get_event("sts1", event_id)).supported


def test_sts2_playable_and_unsupported_ids_partition_the_real_catalog():
    catalog_ids = _ids(load_events("sts2").events)

    assert len(STS2_PLAYABLE_EVENT_IDS) == 40
    assert len(STS2_UNSUPPORTED_EVENT_IDS) == 26
    assert STS2_PLAYABLE_EVENT_IDS.isdisjoint(STS2_UNSUPPORTED_EVENT_IDS)
    assert STS2_PLAYABLE_EVENT_IDS | STS2_UNSUPPORTED_EVENT_IDS == catalog_ids
    assert all(
        interaction_plan(get_event("sts2", event_id)).kind
        is EventInteractionKind.UNSUPPORTED
        for event_id in STS2_UNSUPPORTED_EVENT_IDS
    )


def test_sts2_random_interaction_pool_is_exactly_the_40_playable_events():
    pool = supported_interaction_events(default_random_pool("sts2"))

    assert len(pool) == 40
    assert _ids(pool) == STS2_PLAYABLE_EVENT_IDS
    assert _ids(pool).isdisjoint(STS2_UNSUPPORTED_EVENT_IDS)


def test_sts2_level2_events_stay_playable_and_multistage_events_are_query_only():
    assert interaction_plan(get_event("sts2", "SLIPPERY_BRIDGE")).supported
    assert interaction_plan(get_event("sts2", "ABYSSAL_BATHS")).supported
    assert (
        interaction_plan(get_event("sts2", "ROUND_TEA_PARTY")).kind
        is EventInteractionKind.UNSUPPORTED
    )

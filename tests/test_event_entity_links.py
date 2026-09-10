"""Frozen Event <-> Card/Relic link snapshot tests."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


EXPECTED_LINKS = {
    ("sts1", "ACCURSED_BLACKSMITH", "relic", "WARPEDTONGS", "REWARD"),
    ("sts1", "DRUG_DEALER", "relic", "MUTAGENICSTRENGTH", "REWARD"),
    ("sts1", "DRUG_DEALER", "relic", "CIRCLET", "FALLBACK_REWARD"),
    ("sts1", "N_LOTH", "relic", "NLOTH_S_GIFT", "REWARD"),
    ("sts1", "N_LOTH", "relic", "CIRCLET", "FALLBACK_REWARD"),
    ("sts1", "TOMB_OF_LORD_RED_MASK", "relic", "RED_MASK", "REWARD"),
    ("sts1", "FORGOTTEN_ALTAR", "relic", "DARKSTONE_PERIAPT", "REWARD"),
    ("sts1", "GOLDEN_IDOL", "relic", "GOLDEN_IDOL", "REWARD"),
    ("sts1", "THE_MOAI_HEAD", "relic", "GOLDEN_IDOL", "REMOVE"),
    ("sts1", "DRUG_DEALER", "card", "J_A_X", "REWARD"),
    ("sts1", "VAMPIRES", "card", "BITE", "REWARD"),
    ("sts2", "DROWNING_BEACON", "relic", "FRESNEL_LENS", "REWARD"),
    ("sts2", "GRAVE_OF_THE_FORGOTTEN", "relic", "FORGOTTEN_SOUL", "REWARD"),
    ("sts2", "ROOM_FULL_OF_CHEESE", "relic", "CHOSEN_CHEESE", "REWARD"),
    ("sts2", "SUNKEN_STATUE", "relic", "SWORD_OF_STONE", "REWARD"),
    ("sts2", "WAR_HISTORIAN_REPY", "relic", "HISTORY_COURSE", "REWARD"),
}


def _links_module():
    try:
        return importlib.import_module("card_guess.event_entity_links")
    except ModuleNotFoundError:
        pytest.fail("event_entity_links data API has not been implemented")


def _identity(link):
    return (
        link.game,
        link.event_id,
        link.entity_type,
        link.entity_id,
        link.relation,
    )


def test_frozen_snapshot_exposes_exactly_the_sixteen_audited_links():
    module = _links_module()

    links = module.load_event_entity_links()

    assert {_identity(link) for link in links} == EXPECTED_LINKS
    assert len(links) == 16


def test_event_lookup_returns_relics_and_card_in_stable_order():
    module = _links_module()

    first = module.links_for_event("sts1", "DRUG_DEALER")
    second = module.links_for_event("sts1", "DRUG_DEALER")

    assert first == second
    assert [(link.entity_type, link.entity_id) for link in first] == [
        ("card", "J_A_X"),
        ("relic", "CIRCLET"),
        ("relic", "MUTAGENICSTRENGTH"),
    ]


def test_entity_lookup_returns_all_circlet_events_and_fallback_conditions():
    module = _links_module()

    links = module.links_for_entity("sts1", "relic", "CIRCLET")

    assert [link.event_id for link in links] == ["DRUG_DEALER", "N_LOTH"]
    assert [link.condition.fallback_text for link in links] == [
        "已拥有「突变之力」时",
        "已拥有「恩洛斯的礼物」时",
    ]
    assert all(link.relation == "FALLBACK_REWARD" for link in links)


def test_golden_idol_reverse_lookup_includes_gain_and_removal_events():
    module = _links_module()

    links = module.links_for_entity("sts1", "relic", "GOLDEN_IDOL")

    assert [(link.event_id, link.relation) for link in links] == [
        ("GOLDEN_IDOL", "REWARD"),
        ("THE_MOAI_HEAD", "REMOVE"),
    ]


def test_sts2_fixed_relic_links_use_exact_choice_ids():
    module = _links_module()
    expected = {
        "DROWNING_BEACON": ("FRESNEL_LENS", "CLIMB"),
        "GRAVE_OF_THE_FORGOTTEN": ("FORGOTTEN_SOUL", "ACCEPT"),
        "ROOM_FULL_OF_CHEESE": ("CHOSEN_CHEESE", "SEARCH"),
        "SUNKEN_STATUE": ("SWORD_OF_STONE", "GRAB_SWORD"),
        "WAR_HISTORIAN_REPY": ("HISTORY_COURSE", "UNLOCK_CAGE"),
    }

    actual = {}
    for event_id in expected:
        link, = module.links_for_event("sts2", event_id)
        actual[event_id] = (link.entity_id, link.condition.choice_id)

    assert actual == expected


def test_unresolved_and_random_entities_are_absent():
    module = _links_module()

    identities = {_identity(link) for link in module.load_event_entity_links()}

    assert not any(item[1] == "THE_LANTERN_KEY" for item in identities)
    assert not any(item[3] in {"APPARITION", "LANTERN_KEY"} for item in identities)
    assert not any("RANDOM" in item[3] for item in identities)


@pytest.mark.parametrize("contents", [None, "{broken", "{}"])
def test_missing_corrupt_or_invalid_snapshot_fails_safe(tmp_path: Path, contents):
    module = _links_module()
    path = tmp_path / "event_entity_links.json"
    if contents is not None:
        path.write_text(contents, encoding="utf-8")

    assert module.load_event_entity_links(path) == ()
    assert module.links_for_event("sts1", "DRUG_DEALER", path=path) == ()
    assert module.links_for_entity("sts1", "card", "J_A_X", path=path) == ()


def test_schema_rejects_ambiguous_choice_locator(tmp_path: Path):
    module = _links_module()
    payload = {
        "schema_version": "1.0",
        "links": [
            {
                "game": "sts2",
                "event_id": "SAMPLE_EVENT",
                "entity_type": "relic",
                "entity_id": "SAMPLE_RELIC",
                "relation": "REWARD",
                "condition": {
                    "choice_id": "TAKE",
                    "choice_index": 0,
                    "fallback_text": None,
                },
                "source": "fixture",
                "evidence": "fixture",
            }
        ],
    }
    path = tmp_path / "event_entity_links.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert module.load_event_entity_links(path) == ()

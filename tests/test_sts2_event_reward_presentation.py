"""STS2 fixed-relic reward expansion tests (audited playable pool)."""

from __future__ import annotations

from card_guess.event_presentation import render_event
from card_guess.events import get_event
from card_guess.qq.relic_short_summary import short_relic_effect
from card_guess.relics import load_relics


FIXED_RELICS = {
    "DROWNING_BEACON": {"CLIMB": "FRESNEL_LENS"},
    "GRAVE_OF_THE_FORGOTTEN": {"ACCEPT": "FORGOTTEN_SOUL"},
    "ROOM_FULL_OF_CHEESE": {"SEARCH": "CHOSEN_CHEESE"},
    "SUNKEN_STATUE": {"GRAB_SWORD": "SWORD_OF_STONE"},
    "WAR_HISTORIAN_REPY": {"UNLOCK_CAGE": "HISTORY_COURSE"},
}


def _relics():
    return {item["id"]: item for item in load_relics("sts2")}


def test_fixed_sts2_relic_choices_show_name_and_short_effect_before_choice():
    relics = _relics()
    for event_id, by_choice in FIXED_RELICS.items():
        reply = render_event(get_event("sts2", event_id))
        for choice_id, relic_id in by_choice.items():
            relic = relics[relic_id]
            effect = short_relic_effect(
                relic["description"], relic_id=relic_id, game="sts2"
            )
            assert f"遗物「{relic['name']}」" in reply
            assert f"效果：{effect}" in reply


def test_random_relic_and_potion_rewards_keep_official_categories():
    random_relic = render_event(get_event("sts2", "UNREST_SITE"))
    assert "随机遗物" in random_relic
    assert "效果：" not in random_relic

    random_potion = render_event(get_event("sts2", "WELLSPRING"))
    assert "随机药水" in random_potion
    assert "效果：" not in random_potion


def test_unsupported_multistage_event_is_not_reward_expanded():
    reply = render_event(get_event("sts2", "COLOSSAL_FLOWER"))
    assert "效果：" not in reply

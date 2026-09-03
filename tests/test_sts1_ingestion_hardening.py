"""Fictional regression tests for real official-dump ingestion schemas.

Covered hardening (bounded scope, no new product metrics):
1. iter_sts1_runs unwraps top-level {"event": <run>} and keeps direct runs.
2. Integral float floors (8.0) normalize to int; 8.5/NaN/Infinity stay invalid.
3. Card+N (N >= 1) splits to base id + upgrade level; plain "+" inside names untouched.
4. "Singing Bowl" is a non-card entity in card_choices: counted separately, never a card.
"""
import json

import pytest

from card_guess.sts1_card_stats import aggregate_sts1_runs, iter_sts1_runs


def _run(play_id, **overrides):
    run = {
        "play_id": play_id,
        "is_daily": False,
        "is_trial": False,
        "is_endless": False,
        "chose_seed": False,
        "is_beta": False,
        "special_seed": 0,
        "build_version": "V1",
        "character_chosen": "IRONCLAD",
        "ascension_level": 20,
        "victory": True,
        "card_choices": [],
        "master_deck": [],
        "campfire_choices": [],
    }
    run.update(overrides)
    return run


def _aggregate(runs, card_ids):
    return aggregate_sts1_runs(
        runs,
        card_ids=card_ids,
        collected_at="2030-01-02T03:04:05Z",
    )


def _source(result, card_id):
    return result["snapshot"]["cards"][card_id]["metrics"]["mega_crit_120k_november"]


# --- 1. official dump wrapper ---


def test_iter_sts1_runs_unwraps_event_wrapped_items_and_keeps_direct_runs(tmp_path):
    path = tmp_path / "wrapped_mixed.json"
    payload = [
        {"event": _run("one")},
        _run("two"),
        {"event": _run("three")},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert [run["play_id"] for run in iter_sts1_runs(path, chunk_size=13)] == [
        "one",
        "two",
        "three",
    ]


def test_iter_sts1_runs_keeps_invalid_event_wrappers_for_safe_reporting(tmp_path):
    path = tmp_path / "wrapped_invalid.json"
    payload = [{"event": 42}, _run("ok")]
    path.write_text(json.dumps(payload), encoding="utf-8")

    items = list(iter_sts1_runs(path))
    assert items[0] == {"event": 42}
    assert items[1]["play_id"] == "ok"


def test_aggregate_reports_invalid_event_wrapper_as_missing_play_id(tmp_path):
    path = tmp_path / "wrapped_invalid_agg.json"
    payload = [{"event": None}, _run("ok")]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = _aggregate(
        iter_sts1_runs(path),
        card_ids={"EMBER_CARD"},
    )
    report = result["report"]
    assert report["total_runs"] == 2
    assert report["valid_runs"] == 1
    assert report["filter_reasons"] == {"missing_play_id": 1}


# --- 2. integral float floors ---


def test_integral_float_floors_normalize_but_fractional_nan_inf_are_invalid():
    runs = [
        _run(
            "float-floors",
            card_choices=[
                {"floor": 1.0, "picked": "Ember Card", "not_picked": ["Tide"]},
                {"floor": 17.0, "picked": "SKIP", "not_picked": ["Ember Card"]},
                {"floor": 8.5, "picked": "Ember Card", "not_picked": []},
                {"floor": float("nan"), "picked": "Tide", "not_picked": []},
                {"floor": float("inf"), "picked": "Spark", "not_picked": []},
            ],
            campfire_choices=[
                {"floor": 6.0, "key": "SMITH", "data": "Ember Card"},
            ],
        ),
    ]
    result = _aggregate(runs, card_ids={"EMBER_CARD", "TIDE", "SPARK"})
    source = _source(result, "EMBER_CARD")

    assert source["offered_count"]["value"] == 2
    assert source["picked_count"]["value"] == 1
    assert source["skip_rate"]["value"] == 50.0
    assert source["act_pick_rate"]["act_2"]["denominator"] == 1
    assert source["campfire_upgrade_count"]["value"] == 1
    assert source["campfire_upgrade_floor_mean"]["value"] == 6.0

    report = result["report"]
    assert report["schema_observations"]["card_choices_missing_floor"] == 3
    assert report["ignored_records"] == {}


# --- 3. Card+N normalization ---


def test_card_plus_n_normalizes_base_and_terminal_stats(tmp_path):
    runs = [
        _run(
            "searing",
            card_choices=[
                {"floor": 5, "picked": "Searing Blow", "not_picked": []},
            ],
            master_deck=[
                "Searing Blow",
                "Searing Blow+1",
                "Searing Blow+3",
                "Searing Blow+58",
            ],
        ),
    ]
    result = _aggregate(runs, card_ids={"SEARING_BLOW"})
    source = _source(result, "SEARING_BLOW")

    assert source["final_deck_presence_rate"]["value"] == 100.0
    assert source["final_deck_presence_rate"]["numerator"] == 1
    assert source["final_deck_presence_rate"]["denominator"] == 1
    assert source["final_deck_copy_mean"]["value"] == 4.0
    assert source["final_upgrade_rate"]["value"] == 75.0

    report = result["report"]
    assert report["schema_observations"]["upgraded_master_deck_entries"] == 3
    assert report["unresolved_card_ids"] == {}


def test_plus_sign_inside_a_name_is_not_an_upgrade_suffix():
    runs = [
        _run(
            "plus-name",
            card_choices=[
                {"floor": 5, "picked": "Blade+Smith", "not_picked": []},
            ],
        ),
    ]
    result = _aggregate(runs, card_ids={"EMBER_CARD"})
    report = result["report"]
    assert report["unresolved_card_ids"] == {"Blade+Smith": 1}
    assert report["schema_observations"].get("upgraded_master_deck_entries", 0) == 0


def test_plain_card_plus_one_behavior_is_unchanged():
    runs = [
        _run(
            "plus-one",
            card_choices=[
                {"floor": 5, "picked": "Ember Card", "not_picked": []},
            ],
            master_deck=["Ember Card", "Ember Card+1"],
        ),
    ]
    result = _aggregate(runs, card_ids={"EMBER_CARD"})
    source = _source(result, "EMBER_CARD")
    assert source["final_deck_copy_mean"]["value"] == 2.0
    assert source["final_upgrade_rate"]["value"] == 50.0
    assert result["report"]["unresolved_card_ids"] == {}


# --- 4. Singing Bowl ---


def test_singing_bowl_is_a_non_card_entity_counted_separately():
    runs = [
        _run(
            "bowl",
            card_choices=[
                {
                    "floor": 5,
                    "picked": "Singing Bowl",
                    "not_picked": ["Ember Card", "Tide"],
                },
                {
                    "floor": 7,
                    "picked": "Ember Card",
                    "not_picked": ["Singing Bowl", "Spark"],
                },
            ],
        ),
    ]
    result = _aggregate(runs, card_ids={"EMBER_CARD", "TIDE", "SPARK"})
    source = _source(result, "EMBER_CARD")
    report = result["report"]

    # 事件1: Ember offered but not picked; 事件2: Ember picked.
    assert source["offered_count"]["value"] == 2
    assert source["picked_count"]["value"] == 1
    assert source["skip_rate"]["value"] == 0.0
    assert report["schema_observations"]["singing_bowl_picked"] == 1
    assert report["schema_observations"]["singing_bowl_in_not_picked"] == 1
    # 不进入 unresolved，也不映射成卡。
    assert report["unresolved_card_ids"] == {}
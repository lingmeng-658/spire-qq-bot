import json

import pytest

from card_guess.card_stats import validate_card_stats_snapshot
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


@pytest.fixture
def fictional_runs():
    first = _run(
        "run-1",
        is_prod=False,
        special_seed=None,
        card_choices=[
            {
                "floor": 0,
                "picked": "Ember Card",
                "not_picked": ["Tide", "Spark"],
            },
            {
                "floor": 1,
                "picked": "Ember Card",
                "not_picked": ["Tide", "Spark", "Mystery"],
            },
            {
                "floor": 5,
                "picked": "SKIP",
                "not_picked": ["Ember Card", "Tide", "Spark"],
            },
            {
                "floor": 17,
                "picked": "Ember Card",
                "not_picked": ["Tide", "Spark"],
            },
            {
                "floor": 34,
                "picked": "Tide",
                "not_picked": ["Ember Card", "Spark"],
            },
            {
                "floor": 51,
                "picked": "Ember Card",
                "not_picked": ["Tide", "Spark"],
            },
        ],
        master_deck=["Ember Card", "Ember Card+1", "Tide", "Unknown Card+1"],
        campfire_choices=[
            {"floor": 0, "key": "SMITH", "data": "Ember Card"},
            {"floor": 8, "key": "SMITH", "data": "Ember Card"},
            {"floor": 40, "key": "REST"},
            {"floor": 52, "key": "SMITH", "data": "Tide"},
        ],
    )
    second = _run(
        "run-2",
        build_version="V2",
        character_chosen="THE_SILENT",
        ascension_level=0,
        victory=False,
        card_choices=[
            {"floor": 1, "picked": "Tide", "not_picked": ["Ember Card"]},
            {
                "floor": 17,
                "picked": "SKIP",
                "not_picked": ["Ember Card", "Tide"],
            },
            {"floor": 34, "picked": "Ember Card"},
        ],
        master_deck=["Tide+1", "Spark"],
    )
    second.pop("campfire_choices")
    second.pop("is_trial")

    invalid = [
        _run("daily", is_daily=True),
        _run("trial", is_trial=True),
        _run("endless", is_endless=True),
        _run("chosen", chose_seed=True),
        _run("beta", is_beta=True),
        _run("special", special_seed=123),
    ]
    missing_id = _run("temporary")
    missing_id.pop("play_id")
    return [first, first.copy(), second, *invalid, missing_id]


@pytest.fixture
def aggregated(fictional_runs):
    return aggregate_sts1_runs(
        fictional_runs,
        card_ids={"EMBER_CARD", "TIDE", "SPARK"},
        collected_at="2030-01-02T03:04:05Z",
    )


def test_aggregate_filters_modes_special_seeds_and_duplicate_play_ids(aggregated):
    report = aggregated["report"]

    assert report["total_runs"] == 10
    assert report["valid_runs"] == 2
    assert report["duplicate_runs"] == 1
    assert report["filter_reasons"] == {
        "daily": 1,
        "trial": 1,
        "endless": 1,
        "chose_seed": 1,
        "beta": 1,
        "special_seed": 1,
        "missing_play_id": 1,
    }
    assert report["build_versions"] == {"V1": 1, "V2": 1}
    assert report["characters"] == {"IRONCLAD": 1, "THE_SILENT": 1}
    assert report["ascensions"] == {"0": 1, "20": 1}


def test_card_reward_metrics_exclude_floor_zero_and_outside_three_acts(aggregated):
    source = aggregated["snapshot"]["cards"]["EMBER_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]

    assert source["offered_count"]["value"] == 7
    assert source["picked_count"]["value"] == 3
    assert source["picked_run_count"]["value"] == 2
    assert source["skip_count"]["value"] == 2
    assert source["skip_rate"] == {
        "value": pytest.approx(2 / 7 * 100),
        "unit": "percent",
        "provenance": "computed",
        "numerator": 2,
        "denominator": 7,
        "sample_size": 7,
    }
    assert source["act_pick_rate"]["act_1"]["numerator"] == 1
    assert source["act_pick_rate"]["act_1"]["denominator"] == 3
    assert source["act_pick_rate"]["act_2"]["value"] == 50.0
    assert source["act_pick_rate"]["act_3"]["value"] == 50.0
    assert source["first_pick_floor_mean"]["value"] == 17.5
    assert source["first_pick_floor_mean"]["sample_size"] == 2
    assert source["repick_rate"]["numerator"] == 1
    assert source["repick_rate"]["denominator"] == 3
    assert source["pick_rate"] == {
        "value": pytest.approx(3 / 7 * 100),
        "unit": "percent",
        "provenance": "computed",
        "numerator": 3,
        "denominator": 7,
        "sample_size": 7,
    }


def test_win_delta_uses_run_level_picked_and_comparison_cohorts(aggregated):
    deltas = aggregated["snapshot"]["cards"]["EMBER_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]["act_win_delta"]

    assert deltas["act_1"] == {
        "value": 100.0,
        "unit": "percentage_points",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 1,
        "comparison_numerator": 0,
        "comparison_denominator": 1,
        "sample_size": 2,
    }
    assert deltas["act_2"]["value"] == 100.0
    assert deltas["act_3"]["value"] == -100.0
    assert deltas["act_3"]["numerator"] == 0
    assert deltas["act_3"]["comparison_numerator"] == 1


def test_global_pick_rate_spans_offers_across_all_three_acts(aggregated):
    spark = aggregated["snapshot"]["cards"]["SPARK"]["metrics"][
        "mega_crit_120k_november"
    ]
    # Spark was offered four times across acts 1-3 and never picked.
    assert spark["pick_rate"] == {
        "value": 0.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 0,
        "denominator": 4,
        "sample_size": 4,
    }


def _global_choice(floor, *, pick):
    if pick:
        return {"floor": floor, "picked": "Global Card", "not_picked": ["Other"]}
    return {"floor": floor, "picked": "SKIP", "not_picked": ["Global Card"]}


def test_global_win_delta_is_run_level_and_counts_each_run_once():
    picked_run = _run(
        "win-run",
        victory=True,
        card_choices=[_global_choice(floor, pick=True) for floor in (1, 17, 34)],
    )
    comparison_run = _run(
        "compare-run",
        victory=False,
        card_choices=[_global_choice(floor, pick=False) for floor in (1, 17, 34)],
    )
    result = aggregate_sts1_runs(
        [picked_run, comparison_run],
        card_ids={"GLOBAL_CARD", "OTHER"},
        collected_at="2030-01-02T03:04:05Z",
    )
    source = result["snapshot"]["cards"]["GLOBAL_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]

    # The card was offered in three acts per run, but each run must enter a
    # cohort exactly once (denominators stay 1, never 3).
    assert source["win_delta"] == {
        "value": 100.0,
        "unit": "percentage_points",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 1,
        "comparison_numerator": 0,
        "comparison_denominator": 1,
        "sample_size": 2,
    }
    assert source["pick_rate"]["numerator"] == 3
    assert source["pick_rate"]["denominator"] == 6


def test_global_win_delta_never_merges_act_cohorts():
    # The same card picked in act 1 of one run and never picked anywhere in
    # another run must produce a run-level delta, while act_win_delta keeps its
    # own per-act values (acts here are intentionally different floors).
    runs = [
        _run(
            "pick-act1",
            victory=True,
            card_choices=[
                {"floor": 1, "picked": "Global Card", "not_picked": []},
                {"floor": 17, "picked": "Other", "not_picked": ["Global Card"]},
            ],
        ),
        _run(
            "skip-all",
            victory=False,
            card_choices=[
                {"floor": 1, "picked": "SKIP", "not_picked": ["Global Card"]},
                {"floor": 17, "picked": "SKIP", "not_picked": ["Global Card"]},
            ],
        ),
    ]
    result = aggregate_sts1_runs(
        runs,
        card_ids={"GLOBAL_CARD", "OTHER"},
        collected_at="2030-01-02T03:04:05Z",
    )
    source = result["snapshot"]["cards"]["GLOBAL_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]
    assert source["win_delta"]["denominator"] == 1
    assert source["win_delta"]["comparison_denominator"] == 1
    assert source["win_delta"]["value"] == 100.0
    # act_win_delta stays act-scoped: run "skip-all" offers the card in both
    # acts, so act_1 has a real comparison run while act_2 has no picked run.
    # The whole-run pick of run "pick-act1" must not mark act_2 as picked.
    assert set(source["act_win_delta"]) == {"act_1"}


def test_terminal_deck_normalizes_plus_one_and_uses_field_coverage_denominator(
    aggregated,
):
    source = aggregated["snapshot"]["cards"]["EMBER_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]

    assert source["final_deck_presence_rate"]["value"] == 50.0
    assert source["final_deck_presence_rate"]["numerator"] == 1
    assert source["final_deck_presence_rate"]["denominator"] == 2
    assert source["final_deck_copy_mean"] == {
        "value": 2.0,
        "unit": "copies",
        "provenance": "computed",
        "sample_size": 1,
    }
    assert source["final_upgrade_rate"] == {
        "value": 50.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 2,
        "sample_size": 1,
    }


def test_campfire_metrics_ignore_floor_zero_but_keep_later_smith_actions(aggregated):
    ember = aggregated["snapshot"]["cards"]["EMBER_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]
    tide = aggregated["snapshot"]["cards"]["TIDE"]["metrics"][
        "mega_crit_120k_november"
    ]

    assert ember["campfire_upgrade_count"]["value"] == 1
    assert ember["campfire_upgrade_floor_mean"]["value"] == 8.0
    assert tide["campfire_upgrade_count"]["value"] == 1
    assert tide["campfire_upgrade_floor_mean"]["value"] == 52.0


def test_report_includes_field_coverage_missing_fields_and_unresolved_ids(aggregated):
    report = aggregated["report"]

    assert report["field_coverage"]["card_choices"] == {
        "present_runs": 2,
        "eligible_runs": 2,
        "rate_percent": 100.0,
    }
    assert report["field_coverage"]["master_deck"]["rate_percent"] == 100.0
    assert report["field_coverage"]["campfire_choices"]["rate_percent"] == 50.0
    assert report["missing_fields"]["is_trial"] == 1
    assert report["unresolved_card_ids"] == {
        "Mystery": 1,
        "Unknown Card": 1,
    }
    assert report["schema_observations"]["picked_skip_choices"] == 2
    assert report["schema_observations"]["upgraded_master_deck_entries"] == 3
    assert report["schema_observations"]["smith_choices_with_data"] == 3


def test_snapshot_validates_against_the_unified_contract(aggregated):
    snapshot = aggregated["snapshot"]
    source = snapshot["cards"]["EMBER_CARD"]["metrics"][
        "mega_crit_120k_november"
    ]

    assert source["scope"]["build_versions"] == ["V1", "V2"]
    assert source["scope"]["ascension_min"] == 0
    assert source["scope"]["ascension_max"] == 20
    assert validate_card_stats_snapshot(snapshot) is None


def test_iter_sts1_runs_streams_a_fictional_json_array(tmp_path):
    path = tmp_path / "fictional_runs.json"
    path.write_text(
        json.dumps([_run("one"), _run("two")]),
        encoding="utf-8",
    )

    assert [run["play_id"] for run in iter_sts1_runs(path, chunk_size=19)] == [
        "one",
        "two",
    ]


def test_iter_sts1_runs_rejects_a_non_array_top_level(tmp_path):
    path = tmp_path / "fictional_object.json"
    path.write_text(json.dumps({"runs": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="top-level JSON value must be an array"):
        list(iter_sts1_runs(path, chunk_size=7))


def _heart_run(
    play_id,
    *,
    victory=True,
    floor=55,
    ascension_level=20,
    master_deck=(),
):
    run = _run(
        play_id,
        victory=victory,
        ascension_level=ascension_level,
        master_deck=list(master_deck),
    )
    run["damage_taken"] = [{"damage": 5, "enemies": "The Heart", "floor": floor, "turns": 3}]
    return run


HEART_CARD_IDS = {"FANG", "CLAW", "BOLT"}


def _heart_aggregate(runs):
    return aggregate_sts1_runs(
        runs,
        card_ids=HEART_CARD_IDS,
        collected_at="2030-01-02T03:04:05Z",
    )


def _heart_source(result, card_id):
    return result["snapshot"]["cards"][card_id]["metrics"]["mega_crit_120k_november"]


def test_heart_win_deck_presence_rate_counts_runs_once_per_card():
    runs = [
        _heart_run("heart-1", master_deck=["Fang", "Fang+1"]),
        _heart_run("heart-2", master_deck=["Fang", "Claw"]),
        _heart_run("heart-3", master_deck=["Claw", "Bolt+1"]),
    ]
    result = _heart_aggregate(runs)

    report = result["report"]
    assert report["heart_encounter_runs"] == 3
    assert report["heart_win_runs"] == 3
    assert report["heart_win_deck_runs"] == 3

    fang = _heart_source(result, "FANG")["heart_win_deck_presence_rate"]
    assert fang["value"] == pytest.approx(2 / 3 * 100)
    assert fang["numerator"] == 2
    assert fang["denominator"] == 3
    assert fang["sample_size"] == 3

    claw = _heart_source(result, "CLAW")["heart_win_deck_presence_rate"]
    assert claw["numerator"] == 2
    assert claw["denominator"] == 3

    bolt = _heart_source(result, "BOLT")["heart_win_deck_presence_rate"]
    assert bolt["numerator"] == 1
    assert bolt["denominator"] == 3

    assert validate_card_stats_snapshot(result["snapshot"]) is None


def test_heart_metric_excludes_lost_runs_and_outlier_floors():
    runs = [
        _heart_run("lost", victory=False, master_deck=["Fang"]),
        _heart_run("low", floor=44, master_deck=["Fang"]),
        _heart_run("high", floor=106, master_deck=["Fang"]),
        _heart_run("string-win", victory="true", master_deck=["Fang"]),
        _run("no-heart", master_deck=["Fang"]),
    ]
    result = _heart_aggregate(runs)

    assert result["report"]["heart_encounter_runs"] == 2
    assert result["report"]["heart_win_runs"] == 0
    assert result["report"]["heart_win_deck_runs"] == 0
    assert "heart_win_deck_presence_rate" not in _heart_source(result, "FANG")


def test_heart_helpers_require_audited_encounter_and_native_victory():
    from card_guess.sts1_card_stats import heart_encounter_floor, is_heart_win_run

    assert heart_encounter_floor({}) is None
    assert heart_encounter_floor({"damage_taken": [{"enemies": "Lagavulin", "floor": 55}]}) is None
    assert heart_encounter_floor({"damage_taken": [{"enemies": "The Heart", "floor": 53}]}) is None
    assert heart_encounter_floor({"damage_taken": [{"enemies": "The Heart", "floor": 55.0}]}) == 55

    base = {"damage_taken": [{"enemies": "The Heart", "floor": 56}]}
    assert is_heart_win_run({**base, "victory": True}) is True
    assert is_heart_win_run({**base, "victory": False}) is False
    assert is_heart_win_run({**base, "victory": "true"}) is False
    assert is_heart_win_run({"victory": True, "floor_reached": 56}) is False
    assert is_heart_win_run({**base, "victory": True, "floor_reached": 55}) is True
    assert (
        is_heart_win_run(
            {
                "damage_taken": [
                    {"enemies": "The Heart", "floor": 105},
                    {"enemies": "The Heart", "floor": 55},
                ],
                "victory": True,
            }
        )
        is True
    )

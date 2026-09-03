"""Fictional tests for the STS1 cohort snapshot exporter.

The exporter only builds cohort-scoped sources and metadata; the aggregation
math itself is the already-verified aggregate_sts1_runs core.  Fixtures here
are entirely fictional: no real run data is committed.
"""
import json

import pytest

from card_guess.card_stats import validate_card_stats_snapshot
from card_guess.sts1_card_stats import SOURCE_ID
from card_guess.sts1_snapshot import (
    COHORT_ASC20,
    COHORT_ASC7PLUS,
    COHORT_OVERALL,
    DEFAULT_BUILD_VERSION,
    Sts1Cohort,
    build_sts1_snapshot,
    write_sts1_snapshot,
)

COLLECTED_AT = "2030-01-02T03:04:05Z"
BUILD = DEFAULT_BUILD_VERSION
OTHER_BUILD = "V1"


def _run(play_id, **overrides):
    run = {
        "play_id": play_id,
        "is_daily": False,
        "is_trial": False,
        "is_endless": False,
        "chose_seed": False,
        "is_beta": False,
        "special_seed": 0,
        "build_version": BUILD,
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
    runs = [
        _run(
            "run-1",
            ascension_level=20,
            victory=True,
            card_choices=[
                {"floor": 1, "picked": "Ember Card", "not_picked": ["Tide", "Spark"]},
                {"floor": 17, "picked": "SKIP", "not_picked": ["Ember Card"]},
                {"floor": 34, "picked": "Tide", "not_picked": ["Ember Card"]},
            ],
            master_deck=["Ember Card", "Ember Card+1", "Tide"],
            campfire_choices=[{"floor": 2, "key": "SMITH", "data": "Ember Card"}],
        ),
        _run(
            "run-2",
            ascension_level=7,
            victory=False,
            card_choices=[
                {"floor": 1, "picked": "Tide", "not_picked": ["Ember Card"]},
                {"floor": 18, "picked": "SKIP", "not_picked": ["Spark"]},
            ],
            master_deck=["Tide+1"],
        ),
        _run(
            "run-3",
            ascension_level=0,
            victory=True,
            card_choices=[
                {"floor": 1, "picked": "SKIP", "not_picked": ["Ember Card", "Spark"]},
            ],
            master_deck=["Spark"],
            campfire_choices=[{"floor": 3, "key": "SMITH", "data": "Spark"}],
        ),
        _run(
            "run-4",
            ascension_level=20,
            victory=False,
            card_choices=[
                {"floor": 2, "picked": "Spark", "not_picked": ["Ember Card"]},
            ],
            master_deck=["Spark+1"],
            campfire_choices=[{"floor": 5, "key": "SMITH", "data": "Tide"}],
        ),
        _run(
            "run-5",
            ascension_level=5,
            is_daily=True,
            card_choices=[{"floor": 1, "picked": "Ember Card", "not_picked": []}],
        ),
        _run(
            "run-6",
            ascension_level=5,
            special_seed=42,
            card_choices=[{"floor": 1, "picked": "Ember Card", "not_picked": []}],
        ),
        _run(
            "run-7",
            build_version=OTHER_BUILD,
            ascension_level=20,
            victory=True,
            card_choices=[{"floor": 1, "picked": "Tide", "not_picked": ["Ember Card"]}],
            master_deck=["Tide"],
        ),
        _run(
            "run-8",
            card_choices=[{"floor": 1, "picked": "Ember Card", "not_picked": ["Tide"]}],
        ),
        _run(
            "run-9",
            ascension_level=20,
            is_daily=True,
            card_choices=[{"floor": 1, "picked": "Spark", "not_picked": ["Ember Card"]}],
        ),
    ]
    # run-8 keeps the target build but has no ascension_level: it can never be
    # assigned to an ascension cohort and must be reported as excluded.
    runs[-2].pop("ascension_level")
    return runs


def _build(runs, **overrides):
    return build_sts1_snapshot(
        runs,
        card_ids={"EMBER_CARD", "TIDE", "SPARK"},
        collected_at=COLLECTED_AT,
        **overrides,
    )


def _source(result, cohort_key, card_id):
    source_id = f"{SOURCE_ID}_{cohort_key}"
    return result["snapshot"]["cards"][card_id]["metrics"][source_id]


def _cohort(result, key):
    return result["cohorts"][key]


def test_default_cohorts_are_asc7plus_and_asc20_with_suffixed_sources(fictional_runs):
    result = _build(fictional_runs)

    assert set(result["cohorts"]) == {"asc7plus", "asc20"}
    ember = result["snapshot"]["cards"]["EMBER_CARD"]["metrics"]
    assert set(ember) == {
        f"{SOURCE_ID}_asc7plus",
        f"{SOURCE_ID}_asc20",
    }

    asc7plus = _cohort(result, "asc7plus")
    assert asc7plus["ascension_min"] == 7
    assert asc7plus["ascension_max"] == 20
    assert asc7plus["scanned_runs"] == 9
    assert asc7plus["excluded_build_version"] == 1
    assert asc7plus["excluded_ascension"] == 4
    assert asc7plus["aggregated_runs"] == 4
    assert asc7plus["report"]["total_runs"] == 4
    assert asc7plus["report"]["valid_runs"] == 3
    assert asc7plus["report"]["filter_reasons"] == {"daily": 1}
    assert asc7plus["report"]["build_versions"] == {BUILD: 3}
    assert asc7plus["report"]["ascensions"] == {"7": 1, "20": 2}

    asc20 = _cohort(result, "asc20")
    assert asc20["excluded_ascension"] == 5
    assert asc20["aggregated_runs"] == 3
    assert asc20["report"]["total_runs"] == 3
    assert asc20["report"]["valid_runs"] == 2
    assert asc20["report"]["filter_reasons"] == {"daily": 1}


def test_build_version_filter_excludes_other_builds_and_counts_them(fictional_runs):
    result = _build(fictional_runs)

    asc7plus = _cohort(result, "asc7plus")
    assert asc7plus["excluded_build_version"] == 1
    assert asc7plus["report"]["build_versions"] == {BUILD: 3}

    tide_asc7plus = _source(result, "asc7plus", "TIDE")
    # run-7 (V1) offers Tide but must not contribute to the 2020-07-30 cohort.
    assert tide_asc7plus["offered_count"]["value"] == 3
    assert tide_asc7plus["picked_count"]["value"] == 2


def test_ascension_cohorts_partition_runs_and_metrics(fictional_runs):
    result = _build(fictional_runs)

    ember_asc20 = _source(result, "asc20", "EMBER_CARD")
    ember_asc7plus = _source(result, "asc7plus", "EMBER_CARD")

    assert ember_asc20["offered_count"]["value"] == 4
    assert ember_asc7plus["offered_count"]["value"] == 5
    assert ember_asc20["picked_count"]["value"] == 1
    assert ember_asc20["skip_count"]["value"] == 1
    assert ember_asc20["skip_rate"]["value"] == 25.0
    assert ember_asc7plus["skip_rate"]["value"] == pytest.approx(20.0)

    assert ember_asc20["act_pick_rate"]["act_1"] == {
        "value": 50.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 2,
        "sample_size": 2,
    }
    assert ember_asc7plus["act_pick_rate"]["act_1"]["denominator"] == 3
    assert ember_asc20["act_pick_rate"]["act_2"]["value"] == 0.0
    assert ember_asc20["first_pick_floor_mean"]["value"] == 1.0

    # ascension-0 run-3 and the ascension-5/missing runs never enter A7+ / A20.
    assert ember_asc20["final_deck_presence_rate"] == {
        "value": 50.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 2,
        "sample_size": 2,
    }

    spark_asc20 = _source(result, "asc20", "SPARK")
    spark_asc7plus = _source(result, "asc7plus", "SPARK")
    assert spark_asc20["offered_count"]["value"] == 2
    assert spark_asc20["picked_count"]["value"] == 1
    assert spark_asc20["skip_rate"]["value"] == 0.0
    assert spark_asc7plus["skip_rate"]["numerator"] == 1
    assert spark_asc7plus["skip_rate"]["denominator"] == 3


def test_win_deltas_stay_act_scoped_and_run_level(fictional_runs):
    result = _build(fictional_runs)

    ember_asc20 = _source(result, "asc20", "EMBER_CARD")
    # Only act_1 has both a picked and a comparison run for EMBER in A20.
    assert set(ember_asc20["act_win_delta"]) == {"act_1"}
    assert ember_asc20["act_win_delta"]["act_1"] == {
        "value": 100.0,
        "unit": "percentage_points",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 1,
        "comparison_numerator": 0,
        "comparison_denominator": 1,
        "sample_size": 2,
    }

    ember_asc7plus = _source(result, "asc7plus", "EMBER_CARD")
    assert ember_asc7plus["act_win_delta"]["act_1"]["comparison_denominator"] == 2
    assert ember_asc7plus["act_win_delta"]["act_1"]["sample_size"] == 3

    tide_asc20 = _source(result, "asc20", "TIDE")
    assert "act_win_delta" not in tide_asc20
    tide_asc7plus = _source(result, "asc7plus", "TIDE")
    assert set(tide_asc7plus["act_win_delta"]) == {"act_1"}
    assert tide_asc7plus["act_win_delta"]["act_1"]["value"] == -100.0
    assert tide_asc7plus["act_win_delta"]["act_1"]["numerator"] == 0
    assert tide_asc7plus["act_win_delta"]["act_1"]["comparison_numerator"] == 1


def test_missing_metrics_stay_missing_never_zero_filled(fictional_runs):
    result = _build(fictional_runs)

    spark_asc20 = _source(result, "asc20", "SPARK")
    # No SMITH action targeted Spark in A20: floor mean must stay absent even
    # though the per-cohort campfire count (sample_size context) exists.
    assert spark_asc20["campfire_upgrade_count"]["value"] == 0
    assert "campfire_upgrade_floor_mean" not in spark_asc20
    assert set(spark_asc20["act_pick_rate"]) == {"act_1"}

    tide_asc20 = _source(result, "asc20", "TIDE")
    assert "act_win_delta" not in tide_asc20


def test_source_metadata_records_scope_version_and_cohort_filters(fictional_runs):
    result = _build(fictional_runs)
    source = _source(result, "asc7plus", "EMBER_CARD")

    assert source["source"].endswith("november.7z?dl=0")
    assert source["scope"]["game"] == "sts1"
    assert source["scope"]["character_scope"] == "all_characters"
    assert source["scope"]["ascension_min"] == 7
    assert source["scope"]["ascension_max"] == 20
    assert source["scope"]["build_versions"] == [BUILD]
    assert "daily" in source["scope"]["excluded_modes"]
    assert source["scope"]["filters"]["play_id"] == "deduplicated"
    assert source["scope"]["filters"]["cohort"]["key"] == "asc7plus"
    assert source["scope"]["filters"]["cohort"]["ascension_level"] == [7, 20]
    assert source["scope"]["filters"]["cohort"]["build_version"] == BUILD

    version = source["version"]
    assert version["dataset"] == "official_120k_november_sample"
    assert "pre-v2.2" in version["historical_note"].lower()
    assert "not causal" in version["historical_note"]
    assert "November" in version["data_source_note"]
    assert source["collected_at"] == COLLECTED_AT

    assert set(source["metric_definitions"]) == set(source) - {
        "source",
        "scope",
        "version",
        "collected_at",
        "metric_definitions",
    }
    assert source["metric_definitions"]["skip_rate"]["unit"] == "percent"
    assert source["metric_definitions"]["act_win_delta"]["unit"] == "percentage_points"


def test_overall_cohort_is_available_and_partitions_correctly(fictional_runs):
    result = _build(fictional_runs, cohorts=(COHORT_OVERALL, COHORT_ASC7PLUS, COHORT_ASC20))

    overall = _cohort(result, "overall")
    assert overall["excluded_build_version"] == 1
    assert overall["excluded_ascension"] == 1  # run-8 has no ascension_level
    assert overall["aggregated_runs"] == 7
    assert overall["report"]["valid_runs"] == 4
    assert overall["report"]["filter_reasons"] == {"daily": 2, "special_seed": 1}

    ember = result["snapshot"]["cards"]["EMBER_CARD"]["metrics"]
    assert set(ember) == {
        f"{SOURCE_ID}_overall",
        f"{SOURCE_ID}_asc7plus",
        f"{SOURCE_ID}_asc20",
    }
    ember_overall = ember[f"{SOURCE_ID}_overall"]
    assert ember_overall["scope"]["ascension_min"] == 0
    assert ember_overall["scope"]["ascension_max"] == 20
    assert ember_overall["offered_count"]["value"] == 6
    assert ember_overall["skip_rate"]["numerator"] == 2
    assert ember_overall["final_deck_presence_rate"]["denominator"] == 4

    spark_overall = result["snapshot"]["cards"]["SPARK"]["metrics"][f"{SOURCE_ID}_overall"]
    assert spark_overall["final_deck_presence_rate"]["numerator"] == 2
    assert spark_overall["final_deck_copy_mean"]["value"] == 1.0
    assert spark_overall["final_upgrade_rate"]["value"] == 50.0


def test_empty_cohort_adds_no_sources_but_reports_scan_counts(fictional_runs):
    empty = Sts1Cohort(
        key="asc8_only",
        ascension_min=8,
        ascension_max=8,
        description="Fictional empty cohort on ascension 8",
    )
    result = _build(fictional_runs, cohorts=(COHORT_ASC20, empty))

    audit = _cohort(result, "asc8_only")
    assert audit["scanned_runs"] == 9
    assert audit["excluded_build_version"] == 1
    assert audit["excluded_ascension"] == 8
    assert audit["aggregated_runs"] == 0
    assert audit["report"]["valid_runs"] == 0

    for card in result["snapshot"]["cards"].values():
        assert set(card["metrics"]) == {f"{SOURCE_ID}_asc20"}
    assert validate_card_stats_snapshot(result["snapshot"]) is None


def test_invalid_cohort_configurations_are_rejected(fictional_runs):
    with pytest.raises(ValueError, match="ascension_min"):
        _build(
            fictional_runs,
            cohorts=(Sts1Cohort("bad", 7, 5, "min above max"),),
        )
    with pytest.raises(ValueError, match="ascension"):
        _build(fictional_runs, cohorts=(Sts1Cohort("low", -1, 20, "below zero"),))
    with pytest.raises(ValueError, match="ascension"):
        _build(fictional_runs, cohorts=(Sts1Cohort("high", 0, 21, "above 20"),))
    with pytest.raises(ValueError, match="duplicate cohort"):
        _build(
            fictional_runs,
            cohorts=(COHORT_ASC20, Sts1Cohort("asc20", 20, 20, "duplicate")),
        )
    with pytest.raises(ValueError, match="at least one cohort"):
        _build(fictional_runs, cohorts=())
    with pytest.raises(ValueError, match="build_version"):
        _build(fictional_runs, build_version="")


def test_snapshot_roundtrips_through_json_and_writer(fictional_runs, tmp_path):
    result = _build(fictional_runs)
    output = tmp_path / "sts1_snapshot.json"

    write_sts1_snapshot(result["snapshot"], output)
    raw = output.read_bytes()
    assert b"\r\n" not in raw

    loaded = json.loads(raw.decode("utf-8"))
    assert loaded == result["snapshot"]
    assert validate_card_stats_snapshot(loaded) is None


def test_path_input_matches_in_memory_list_input(fictional_runs, tmp_path):
    path = tmp_path / "fictional_runs.json"
    path.write_text(json.dumps(fictional_runs), encoding="utf-8")

    from_list = _build(fictional_runs)
    from_path = _build(path)

    assert from_path["snapshot"] == from_list["snapshot"]
    assert from_path["cohorts"] == from_list["cohorts"]


def test_card_names_are_attached_when_provided(fictional_runs):
    names = {"EMBER_CARD": "??", "TIDE": "??", "SPARK": "??"}
    result = _build(fictional_runs, card_names=names)

    assert result["snapshot"]["cards"]["EMBER_CARD"]["name"] == "??"
    assert result["snapshot"]["cards"]["TIDE"]["name"] == "??"
    assert result["snapshot"]["cards"]["SPARK"]["name"] == "??"
    assert "name" not in _source(result, "asc20", "EMBER_CARD")
    assert validate_card_stats_snapshot(result["snapshot"]) is None


def test_heart_win_metric_scopes_to_ascension_cohorts():
    runs = [
        _run(
            "heart-a7",
            ascension_level=7,
            victory=True,
            damage_taken=[{"enemies": "The Heart", "floor": 55, "damage": 1}],
            master_deck=["Ember Card"],
        ),
        _run(
            "heart-a15",
            ascension_level=15,
            victory=True,
            damage_taken=[{"enemies": "The Heart", "floor": 56, "damage": 1}],
            master_deck=["Tide", "Tide+1"],
        ),
        _run(
            "heart-a20",
            ascension_level=20,
            victory=True,
            damage_taken=[{"enemies": "The Heart", "floor": 55, "damage": 1}],
            master_deck=["Spark"],
        ),
    ]
    result = _build(runs)

    asc7_report = _cohort(result, "asc7plus")["report"]
    assert asc7_report["heart_encounter_runs"] == 3
    assert asc7_report["heart_win_runs"] == 3
    assert asc7_report["heart_win_deck_runs"] == 3
    ember = _source(result, "asc7plus", "EMBER_CARD")["heart_win_deck_presence_rate"]
    assert ember["numerator"] == 1
    assert ember["denominator"] == 3
    tide = _source(result, "asc7plus", "TIDE")["heart_win_deck_presence_rate"]
    assert tide["numerator"] == 1

    asc20_report = _cohort(result, "asc20")["report"]
    assert asc20_report["heart_win_runs"] == 1
    spark = _source(result, "asc20", "SPARK")["heart_win_deck_presence_rate"]
    assert spark["value"] == 100.0
    assert spark["numerator"] == 1
    assert spark["denominator"] == 1
    ember_asc20 = _source(result, "asc20", "EMBER_CARD")
    assert "heart_win_deck_presence_rate" not in ember_asc20
    assert validate_card_stats_snapshot(result["snapshot"]) is None

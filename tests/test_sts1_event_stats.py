"""STS1 Event Stats v1 draft tests (fictional run data only)."""
from __future__ import annotations

import pytest

from card_guess.event_interaction import (
    STS1_PLAYABLE_EVENT_IDS,
    STS1_UNSUPPORTED_EVENT_IDS,
)
from card_guess.sts1_event_stats import (
    EVENT_DUMP_NAMES,
    ID_BY_DUMP_NAME,
    SCHEMA_VERSION,
    aggregate_sts1_event_stats,
    act_for_floor,
    load_sts1_event_stats_snapshot,
    normalize_floor,
    validate_sts1_event_stats_snapshot,
)


def _run(play_id, asc=20, victory=True, choices=(), **overrides):
    run = {
        "play_id": play_id,
        "is_daily": False,
        "is_trial": False,
        "is_endless": False,
        "chose_seed": False,
        "is_beta": False,
        "special_seed": 0,
        "build_version": "2020-07-30",
        "character_chosen": "IRONCLAD",
        "ascension_level": asc,
        "victory": victory,
        "event_choices": list(choices),
    }
    run.update(overrides)
    return run


def _choice(event_name, choice, floor):
    return {"event_name": event_name, "player_choice": choice, "floor": floor}


def _aggregate(runs, **kwargs):
    return aggregate_sts1_event_stats(
        runs,
        collected_at="2030-01-02T03:04:05Z",
        **kwargs,
    )


def _event_row(snapshot, event_id):
    for row in snapshot["events"]:
        if row["id"] == event_id:
            return row
    raise KeyError(event_id)


def _act(row, act):
    return row["acts"].get(act)


# ---------------------------------------------------------------- mapping

# SPIRE_HEART has no recorded ``event_choices`` in the November dump, so it is
# the only catalog event without a dump-name row in the snapshot mapping.
def test_mapping_table_covers_every_event_with_dump_occurrences():
    expected = (STS1_PLAYABLE_EVENT_IDS | STS1_UNSUPPORTED_EVENT_IDS) - {"SPIRE_HEART"}
    assert set(EVENT_DUMP_NAMES) == expected
    assert len(EVENT_DUMP_NAMES) == 51


def test_mapping_dump_names_are_nonempty_and_unique_across_events():
    flattened = [name for names in EVENT_DUMP_NAMES.values() for name in names]
    assert all(isinstance(name, str) and name for name in flattened)
    assert len(flattened) == len(set(flattened)) == 51


def test_reverse_mapping_is_bijective_over_mapped_names():
    assert set(ID_BY_DUMP_NAME) == set(flattened_names())
    for event_id, names in EVENT_DUMP_NAMES.items():
        for name in names:
            assert ID_BY_DUMP_NAME[name] == event_id


def flattened_names():
    return [name for names in EVENT_DUMP_NAMES.values() for name in names]


def test_smoke_targets_have_expected_dump_names():
    assert EVENT_DUMP_NAMES["BIG_FISH"] == ("Big Fish",)
    assert EVENT_DUMP_NAMES["THE_CLERIC"] == ("The Cleric",)
    assert EVENT_DUMP_NAMES["DRUG_DEALER"] == ("Drug Dealer",)


# ---------------------------------------------------------------- hygiene

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (3, 3),
        (16, 16),
        (17, 17),
        (3.0, 3),
        (51.0, 51),
    ],
)
def test_normalize_floor_accepts_int_and_integral_float(raw, expected):
    assert normalize_floor(raw) == expected


@pytest.mark.parametrize("raw", [True, "3", None, 3.5, [], {}])
def test_normalize_floor_rejects_non_floor_values(raw):
    assert normalize_floor(raw) is None


@pytest.mark.parametrize(
    ("floor", "act"),
    [
        (1, "act_1"), (16, "act_1"),
        (17, "act_2"), (33, "act_2"),
        (34, "act_3"), (50, "act_3"),
    ],
)
def test_act_for_floor_boundaries(floor, act):
    assert act_for_floor(floor) == act


@pytest.mark.parametrize("floor", [0, 51, 65, -1])
def test_act_for_floor_rejects_outside_acts(floor):
    assert act_for_floor(floor) is None


def test_float_floor_decision_is_normalized_and_included():
    runs = [
        _run("r1", choices=[_choice("Big Fish", "Banana", 3.0)]),
    ]
    snapshot, report = _aggregate(runs)["snapshot"], _aggregate(runs)["report"]
    row = _event_row(snapshot, "BIG_FISH")
    act = _act(row, "act_1")
    assert act["encounters"] == 1
    assert report["float_floor_normalized"] == 1


def test_out_of_act_floors_are_excluded_and_counted():
    runs = [
        _run(
            "r1",
            choices=[
                _choice("Big Fish", "Donut", 0),
                _choice("Big Fish", "Box", 51),
                _choice("Big Fish", "Banana", 65),
                _choice("Big Fish", "Donut", 3),
            ],
        ),
    ]
    result = _aggregate(runs)
    snapshot, report = result["snapshot"], result["report"]
    row = _event_row(snapshot, "BIG_FISH")
    assert _act(row, "act_1")["encounters"] == 1
    assert report["ignored_records"]["out_of_act_floor"] == 3


def test_repeat_event_encounters_count_decisions_but_association_uses_once_only():
    runs = [
        _run(
            "r1",
            victory=True,
            choices=[
                _choice("Big Fish", "Donut", 3),
                _choice("Big Fish", "Donut", 7),
            ],
        ),
    ]
    result = _aggregate(runs)
    snapshot = result["snapshot"]
    row = _event_row(snapshot, "BIG_FISH")
    act = _act(row, "act_1")
    assert act["encounters"] == 2
    assert act["run_reached"] == 1
    assert row["repeat_runs"] == 1
    option = act["options"][0]
    assert option["chosen_count"] == 2
    assert option["associated_win_rate"] is None
    assert act["win_rate_baseline"] is None


def test_non_playable_event_names_are_ignored_and_reported():
    runs = [
        _run(
            "r1",
            choices=[
                _choice("Spire Heart", "Fight the Heart", 5),
                _choice("Big Fish", "Donut", 3),
                _choice("The Lab", "x", 4),
            ],
        ),
    ]
    result = _aggregate(runs)
    snapshot, report = result["snapshot"], result["report"]
    row = _event_row(snapshot, "BIG_FISH")
    assert _act(row, "act_1")["encounters"] == 1
    ignored = report["ignored_records"]["non_playable_event"]
    assert ignored["Spire Heart"] == 1
    assert ignored["The Lab"] == 1
    assert {row["id"] for row in snapshot["events"]} == set(EVENT_DUMP_NAMES)


def test_invalid_choice_values_are_skipped_and_reported():
    runs = [
        _run(
            "r1",
            choices=[
                _choice("Big Fish", None, 3),
                _choice("Big Fish", "", 4),
                _choice("Big Fish", "Donut", 5),
            ],
        ),
    ]
    result = _aggregate(runs)
    snapshot, report = result["snapshot"], result["report"]
    assert _act(_event_row(snapshot, "BIG_FISH"), "act_1")["encounters"] == 1
    assert report["ignored_records"]["invalid_choice"] == 2


# ---------------------------------------------------------------- filters

def test_mode_special_seed_and_ascension_filtering():
    runs = [
        _run("r1", choices=[_choice("Big Fish", "Donut", 3)]),
        _run("r2", asc=6, choices=[_choice("Big Fish", "Box", 4)]),
        _run("r3", asc=20, is_daily=True, choices=[_choice("Big Fish", "Box", 4)]),
        _run("r4", asc=20, special_seed=99, choices=[_choice("Big Fish", "Box", 4)]),
        _run("r1", asc=20, victory=False, choices=[_choice("Big Fish", "Box", 4)]),
        _run("r5", asc="high", choices=[_choice("Big Fish", "Banana", 4)]),
    ]
    result = _aggregate(runs)
    snapshot, report = result["snapshot"], result["report"]
    row = _event_row(snapshot, "BIG_FISH")
    act = _act(row, "act_1")
    assert act["encounters"] == 1
    assert act["options"][0]["choice_key"] == "Donut"
    assert report["total_runs"] == 6
    assert report["accepted_runs"] == 1
    assert report["run_filters"]["is_daily"] == 1
    assert report["run_filters"]["special_seed"] == 1
    assert report["run_filters"]["ascension_out_of_range"] == 2
    assert report["duplicate_runs"] == 1


# ---------------------------------------------------------------- metrics

def test_choice_counts_and_share_use_decision_denominator():
    runs = [
        _run("r1", victory=True, choices=[_choice("Big Fish", "Donut", 3)]),
        _run("r2", victory=False, choices=[_choice("Big Fish", "Box", 6)]),
        _run("r3", victory=True, choices=[_choice("Big Fish", "Donut", 7)]),
    ]
    result = _aggregate(runs, min_association_sample=1)
    snapshot = result["snapshot"]
    act = _act(_event_row(snapshot, "BIG_FISH"), "act_1")
    assert act["encounters"] == 3
    assert act["run_reached"] == 3
    by_key = {o["choice_key"]: o for o in act["options"]}
    donut = by_key["Donut"]
    assert donut["chosen_count"] == 2
    assert donut["chosen_share"]["value"] == pytest.approx(200.0 / 3)
    assert donut["chosen_share"]["denominator"] == 3
    assert donut["associated_win_rate"]["value"] == pytest.approx(100.0)
    box = by_key["Box"]
    assert box["chosen_share"]["value"] == pytest.approx(100.0 / 3)
    assert box["associated_win_rate"]["value"] == pytest.approx(0.0)
    assert act["win_rate_baseline"]["value"] == pytest.approx(200.0 / 3)


def test_associated_win_rate_is_null_below_min_sample():
    runs = [
        _run("r1", victory=True, choices=[_choice("The Cleric", "Healed", 8)]),
    ]
    snapshot = _aggregate(runs)["snapshot"]  # default min sample 50
    act = _act(_event_row(snapshot, "THE_CLERIC"), "act_1")
    assert act["encounters"] == 1
    option = act["options"][0]
    assert option["chosen_share"]["value"] == pytest.approx(100.0)
    assert option["associated_win_rate"] is None
    assert act["win_rate_baseline"] is None


def test_events_group_by_observed_act_from_floor():
    runs = [
        _run(
            "r1",
            choices=[
                _choice("Bonfire Elementals", "Heal", 5),
                _choice("Bonfire Elementals", "Heal", 20),
                _choice("Bonfire Elementals", "Upgrade", 40),
            ],
        ),
    ]
    snapshot = _aggregate(runs)["snapshot"]
    row = _event_row(snapshot, "BONFIRE_ELEMENTALS")
    assert _act(row, "act_1")["encounters"] == 1
    assert _act(row, "act_2")["encounters"] == 1
    assert _act(row, "act_3")["encounters"] == 1
    assert row["repeat_runs"] == 1


# ---------------------------------------------------------------- snapshot shape

def test_snapshot_has_required_metrics_and_passes_validation():
    runs = [
        _run("r1", victory=True, choices=[_choice("Big Fish", "Donut", 3)]),
        _run("r2", victory=False, choices=[_choice("Drug Dealer", "Inject Mutagens", 20)]),
    ]
    result = _aggregate(runs, min_association_sample=1)
    snapshot = result["snapshot"]
    validate_sts1_event_stats_snapshot(snapshot)
    assert snapshot["schema_version"] == SCHEMA_VERSION
    assert snapshot["game"] == "sts1"
    option = _act(_event_row(snapshot, "BIG_FISH"), "act_1")["options"][0]
    for field in (
        "choice_key",
        "encounters",
        "chosen_count",
        "chosen_share",
        "associated_win_rate",
        "sample_size",
    ):
        assert field in option or field in option.get("chosen_share", {})


def test_validator_rejects_tampered_snapshot():
    runs = [
        _run("r1", victory=True, choices=[_choice("Big Fish", "Donut", 3)]),
    ]
    snapshot = _aggregate(runs)["snapshot"]
    act = _act(_event_row(snapshot, "BIG_FISH"), "act_1")
    act["options"][0]["chosen_share"]["denominator"] = 999
    with pytest.raises(ValueError):
        validate_sts1_event_stats_snapshot(snapshot)


# ---------------------------------------------------------------- loader fallback

def test_loader_missing_file_degrades_to_empty_snapshot(tmp_path):
    snapshot = load_sts1_event_stats_snapshot(tmp_path / "does-not-exist.json")

    assert snapshot == {}


def test_loader_invalid_json_degrades_to_empty_snapshot(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")

    assert load_sts1_event_stats_snapshot(bad) == {}


def test_loader_invalid_schema_degrades_to_empty_snapshot(tmp_path):
    bad = tmp_path / "bad-shape.json"
    bad.write_text('{"events": "not-a-list"}', encoding="utf-8")

    assert load_sts1_event_stats_snapshot(bad) == {}

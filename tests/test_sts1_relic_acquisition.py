"""R5B: first-acquisition floor statistics for Common/Uncommon/Rare relics.

Tests the aggregator's ``first_acquisition`` snapshot section, the percentile
contract (stdlib ``statistics.quantiles(..., method="inclusive")``) and the
snapshot validator rules.  All data below is fictional.
"""

import json

import pytest

from card_guess.relic_stats import (
    FIRST_ACQUISITION_KEY,
    SCHEMA_VERSION,
    validate_relic_stats_snapshot,
)
from card_guess.sts1_relic_stats import aggregate_sts1_relics


FICTIONAL_CATALOG = [
    {"id": "AKABEKO", "name_en": "Akabeko", "tier": "Common", "color": None},
    {"id": "BLOOD_VIAL", "name_en": "Blood Vial", "tier": "Common", "color": None},
    {"id": "MOLTEN_EGG_2", "name_en": "Molten Egg 2", "tier": "Common", "color": None},
    {"id": "YANG", "name_en": "Duality", "tier": "Uncommon", "color": None},
    {"id": "CAPTAINSWHEEL", "name_en": "Captain's Wheel", "tier": "Rare", "color": None},
    {"id": "BURNING_BLOOD", "name_en": "Burning Blood", "tier": "Starter", "color": "ironclad"},
    {"id": "THE_COURIER", "name_en": "The Courier", "tier": "Shop", "color": None},
    {"id": "RUNIC_DOME", "name_en": "Runic Dome", "tier": "Boss", "color": None},
    {"id": "BLOODY_IDOL", "name_en": "Bloody Idol", "tier": "Special", "color": None},
]

COLLECTED_AT = "2030-01-02T03:04:05Z"


def _run(play_id, character, relics, obtained):
    return {
        "play_id": play_id,
        "is_beta": False,
        "character_chosen": character,
        "relics": relics,
        "relics_obtained": obtained,
    }


def _event(key, floor):
    return {"key": key, "floor": floor}


def fictional_runs():
    """Nine valid runs exercising multi-run, same-run duplicates and bad floors."""
    return [
        _run(
            "ic-1",
            "IRONCLAD",
            ["Burning Blood", "Akabeko", "Blood Vial"],
            [
                _event("Akabeko", 7),
                _event("Akabeko", 7),        # duplicate same floor -> min 7
                _event("Blood Vial", 12),
                _event("Burning Blood", 2),  # starter relic: legal but excluded
            ],
        ),
        _run(
            "ic-2",
            "IRONCLAD",
            ["Burning Blood", "Akabeko", "Captain's Wheel", "Molten Egg 2"],
            [
                _event("Akabeko", 7.0),      # integer-valued float accepted
                _event("Akabeko", 5),        # same-run min -> 5
                _event("Blood Vial", 15),
                _event("Captain's Wheel", 40),
            ],
        ),
        _run(
            "sil-1",
            "THE_SILENT",
            ["Akabeko", "Duality"],
            [
                _event("Akabeko", 0),        # floor 0 ignored
                _event("Akabeko", 9),
                _event("Duality", 6),
            ],
        ),
        _run(
            "sil-2",
            "THE_SILENT",
            ["Blood Vial", "Duality", "Captain's Wheel", "Molten Egg 2"],
            [
                _event("Blood Vial", 58),    # floor > 56 ignored
                _event("Blood Vial", 16.0),  # integer-valued float accepted
                _event("Duality", 17.5),     # non-integer float ignored
                _event("Duality", 18),
                _event("Captain's Wheel", 22),
            ],
        ),
        _run(
            "def-1",
            "DEFECT",
            ["Akabeko", "Captain's Wheel"],
            [
                _event("Akabeko", 30),
                _event("Captain's Wheel", 55),
            ],
        ),
        _run(
            "def-2",
            "DEFECT",
            ["Blood Vial", "The Courier"],
            [
                _event("Blood Vial", 3),
                _event("Blood Vial", "9"),   # string floor ignored
                _event("The Courier", 9),    # shop relic: legal but excluded
            ],
        ),
        _run(
            "wat-1",
            "WATCHER",
            ["Duality", "Blood Vial"],
            [_event("Duality", 35)],
        ),
        _run(
            "wat-2",
            "WATCHER",
            ["Blood Vial", "Duality"],
            [
                _event("Blood Vial", 6.5),   # non-integer float ignored
                _event("NoSuchRelic", 5),    # unresolved key ignored quietly
                _event(123, 5),              # non-string key ignored
            ],
        ),
        _run(
            "boss-run",
            "IRONCLAD",
            ["Burning Blood", "Runic Dome", "Bloody Idol"],
            [
                _event("Runic Dome", 17),    # boss relic: legal but excluded
                _event("Bloody Idol", 20),   # special relic: legal but excluded
            ],
        ),
    ]


@pytest.fixture
def aggregated():
    return aggregate_sts1_relics(
        fictional_runs(),
        relic_catalog=FICTIONAL_CATALOG,
        collected_at=COLLECTED_AT,
    )


@pytest.fixture
def snapshot(aggregated):
    return aggregated["snapshot"]


def _fa(snapshot, relic_id):
    return snapshot["relics"][relic_id][FIRST_ACQUISITION_KEY]


def _as_json(value):
    return json.loads(json.dumps(value))


def test_schema_version_stays_1_0_0(snapshot):
    assert snapshot["schema_version"] == SCHEMA_VERSION == "1.0.0"


def test_first_acquisition_fields_on_akabeko(snapshot):
    fa = _fa(snapshot, "AKABEKO")
    # ic-1(7), ic-2(5), sil-1(9), def-1(30) => legal first floors [5, 7, 9, 30]
    assert fa["sample_size"] == 4
    assert fa["final_presence_runs"] == 4
    assert fa["coverage_rate"]["value"] == pytest.approx(100.0)
    assert fa["coverage_rate"]["numerator"] == 4
    assert fa["coverage_rate"]["denominator"] == 4
    assert fa["p25_floor"] == 6.5
    assert fa["median_floor"] == 8.0
    assert fa["p75_floor"] == 14.25


def test_act_split_on_akabeko(snapshot):
    fa = _fa(snapshot, "AKABEKO")
    # floors 5/7/9 in act1, floor 30 in act2, none in act3
    assert fa["act1_rate"]["numerator"] == 3
    assert fa["act2_rate"]["numerator"] == 1
    assert fa["act3_rate"]["numerator"] == 0
    for act in ("act1_rate", "act2_rate", "act3_rate"):
        assert fa[act]["denominator"] == 4
        assert fa[act]["sample_size"] == 4
    assert fa["act1_rate"]["value"] == pytest.approx(75.0)
    assert fa["act2_rate"]["value"] == pytest.approx(25.0)
    assert fa["act3_rate"]["value"] == pytest.approx(0.0)


def test_multi_run_statistics_on_blood_vial(snapshot):
    fa = _fa(snapshot, "BLOOD_VIAL")
    # legal first floors: ic-1(12), ic-2(15), sil-2(16), def-2(3)
    assert fa["sample_size"] == 4
    # presence runs: ic-1, sil-2, def-2, wat-1, wat-2 = 5
    assert fa["final_presence_runs"] == 5
    assert fa["coverage_rate"]["value"] == pytest.approx(4 / 5 * 100)
    assert fa["p25_floor"] == 9.75
    assert fa["median_floor"] == 13.5
    assert fa["p75_floor"] == 15.25


def test_act_split_covers_all_three_acts(snapshot):
    fa = _fa(snapshot, "YANG")
    # floors 6 (act1), 18 (act2), 35 (act3)
    assert fa["sample_size"] == 3
    assert [fa[k]["numerator"] for k in ("act1_rate", "act2_rate", "act3_rate")] == [1, 1, 1]
    assert fa["median_floor"] == 18.0
    assert fa["coverage_rate"]["numerator"] == 3
    assert fa["coverage_rate"]["denominator"] == 4


def test_late_rare_relic_keeps_act_split(snapshot):
    fa = _fa(snapshot, "CAPTAINSWHEEL")
    # floors 22 (act2), 40 (act3), 55 (act3)
    assert fa["sample_size"] == 3
    assert [fa[k]["numerator"] for k in ("act1_rate", "act2_rate", "act3_rate")] == [0, 1, 2]
    assert fa["median_floor"] == 40.0


def test_quartiles_median_matches_statistics_median():
    # The inclusive definition must agree with statistics.median by contract.
    import statistics

    floors = [5, 7, 9, 30]
    assert statistics.quantiles(floors, n=4, method="inclusive")[1] == statistics.median(floors)


def test_excluded_tiers_never_emit_first_acquisition(snapshot):
    for relic_id in ("BURNING_BLOOD", "THE_COURIER", "RUNIC_DOME", "BLOODY_IDOL"):
        assert FIRST_ACQUISITION_KEY not in snapshot["relics"][relic_id]


def test_eligible_relic_without_any_record_has_no_field(snapshot):
    # Molten Egg 2 is held terminally but never appears in relics_obtained.
    entry = snapshot["relics"]["MOLTEN_EGG_2"]
    assert entry["total_hold_runs"] == 2
    assert FIRST_ACQUISITION_KEY not in entry


def test_validator_accepts_the_full_snapshot(snapshot):
    validate_relic_stats_snapshot(snapshot)


def test_validator_rejects_first_acquisition_on_starter(snapshot):
    relic = _as_json(snapshot["relics"]["BURNING_BLOOD"])
    relic[FIRST_ACQUISITION_KEY] = _as_json(_fa(snapshot, "AKABEKO"))
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "BURNING_BLOOD": relic}}
        )


def test_validator_rejects_sample_larger_than_presence(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["sample_size"] = 5
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )


def test_validator_rejects_coverage_numerator_mismatch(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["coverage_rate"]["numerator"] = 3
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )


def test_validator_rejects_coverage_denominator_mismatch(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["coverage_rate"]["denominator"] = 99
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )


def test_validator_rejects_act_denominator_not_equal_sample(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["act1_rate"]["denominator"] = 3
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )


def test_validator_rejects_act_numerators_not_summing_to_sample(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["act3_rate"]["numerator"] = 1
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )


def test_validator_rejects_out_of_range_median_floor(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["median_floor"] = 57.0
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )


def test_validator_rejects_inverted_percentile_order(snapshot):
    relic = _as_json(snapshot["relics"]["AKABEKO"])
    relic[FIRST_ACQUISITION_KEY]["p25_floor"] = 20.0
    with pytest.raises(ValueError):
        validate_relic_stats_snapshot(
            {**snapshot, "relics": {**snapshot["relics"], "AKABEKO": relic}}
        )

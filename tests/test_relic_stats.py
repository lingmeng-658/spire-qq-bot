"""Unit tests for the shared relic-rate snapshot helpers (policy C)."""

import copy

import pytest

from card_guess.relic_stats import (
    SCHEMA_VERSION,
    make_relic_rate_metric,
    relic_display_policy,
    validate_relic_stats_snapshot,
)


def _metric(numerator, denominator):
    return make_relic_rate_metric(numerator, denominator)


def _relic(**overrides):
    relic = {
        "name_en": "Burning Blood",
        "tier": "Starter",
        "catalog_color": "ironclad",
        "catalog_color_trusted": False,
        "observed_roles": {"IRONCLAD": 2},
        "supported_roles": ["IRONCLAD"],
        "display_mode": "per_character",
        "total_hold_runs": 2,
        "overall": _metric(2, 4),
        "per_character": {
            "IRONCLAD": _metric(2, 2),
            "THE_SILENT": _metric(0, 2),
        },
    }
    relic.update(overrides)
    return relic


def _snapshot(**relic_overrides):
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": {
            "source": "https://example.test/november.json",
            "collected_at": "2030-01-02T03:04:05Z",
            "display_policy": {"catalog_color_trusted": False},
            "filters": {"is_beta": "excluded"},
            "character_runs": {"IRONCLAD": 2, "THE_SILENT": 2},
        },
        "relics": {"BURNING_BLOOD": _relic(**relic_overrides)},
    }


def test_make_relic_rate_metric_shapes_and_values():
    metric = make_relic_rate_metric(1, 2)
    assert metric == {
        "value": 50.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 1,
        "denominator": 2,
        "sample_size": 2,
    }
    zero = make_relic_rate_metric(0, 5)
    assert zero["value"] == 0.0
    assert zero["numerator"] == 0
    assert zero["sample_size"] == 5


def test_make_relic_rate_metric_rejects_bad_inputs():
    with pytest.raises(ValueError):
        make_relic_rate_metric(3, 2)  # numerator exceeds denominator
    with pytest.raises(ValueError):
        make_relic_rate_metric(1, 0)  # empty denominator
    with pytest.raises(ValueError):
        make_relic_rate_metric(True, 2)


def _eligible():
    return {
        "IRONCLAD": 1000,
        "THE_SILENT": 1000,
        "DEFECT": 1000,
        "WATCHER": 1000,
    }


def test_relic_display_policy_modes_by_supported_count():
    eligible = _eligible()
    assert relic_display_policy({}, eligible) == ([], "none")
    assert relic_display_policy({"IRONCLAD": 500}, eligible) == (
        ["IRONCLAD"],
        "per_character",
    )
    assert relic_display_policy(
        {"IRONCLAD": 500, "THE_SILENT": 400}, eligible
    ) == (["IRONCLAD", "THE_SILENT"], "both")
    three = relic_display_policy(
        {"IRONCLAD": 500, "THE_SILENT": 400, "DEFECT": 300}, eligible
    )
    assert three == (["IRONCLAD", "THE_SILENT", "DEFECT"], "both")
    four = relic_display_policy(
        {"IRONCLAD": 500, "THE_SILENT": 400, "DEFECT": 300, "WATCHER": 200},
        eligible,
    )
    assert four == (list(("IRONCLAD", "THE_SILENT", "DEFECT", "WATCHER")), "overall")


def test_relic_display_policy_filters_stray_and_tiny_support():
    eligible = _eligible()
    assert relic_display_policy({"IRONCLAD": 1}, eligible) == ([], "none")
    tiny = {"IRONCLAD": 100000, "THE_SILENT": 100000}
    assert relic_display_policy({"IRONCLAD": 10}, tiny, min_hold_runs=1) == (
        [],
        "none",
    )
    assert relic_display_policy(
        {"IRONCLAD": 10}, tiny, min_hold_runs=1, min_share=0.00005
    ) == (["IRONCLAD"], "per_character")


def test_relic_display_policy_rejects_bad_parameters():
    eligible = _eligible()
    with pytest.raises(ValueError):
        relic_display_policy({"IRONCLAD": 1}, eligible, min_hold_runs=0)
    with pytest.raises(ValueError):
        relic_display_policy({"IRONCLAD": 1}, eligible, min_share=0.0)
    with pytest.raises(ValueError):
        relic_display_policy({"IRONCLAD": 1}, eligible, min_share=1.0)


def test_validate_relic_stats_snapshot_accepts_minimal_snapshot():
    validate_relic_stats_snapshot(_snapshot())


@pytest.mark.parametrize(
    "override,message",
    [
        ({"catalog_color_trusted": True}, "policy C forbids trusting catalog color"),
        ({"display_mode": "bogus"}, "must be one of"),
        ({"supported_roles": ["THE_SILENT"]}, "supported roles must be a subset"),
        ({"total_hold_runs": 3}, "must equal the sum of per-character hold runs"),
        (
            {
                "per_character": {
                    "IRONCLAD": _metric(2, 2),
                    "THE_SILENT": _metric(0, 3),
                }
            },
            "must equal the character run count in scope",
        ),
        (
            {
                "overall": _metric(2, 3),
                "per_character": {
                    "IRONCLAD": _metric(2, 2),
                    "THE_SILENT": _metric(0, 2),
                },
            },
            "denominator sum must equal the overall denominator",
        ),
    ],
)
def test_validate_relic_stats_snapshot_rejects_bad_relic(override, message):
    snapshot = _snapshot(**override)
    with pytest.raises(ValueError, match=message):
        validate_relic_stats_snapshot(snapshot)


def test_validate_rejects_unknown_relic_field():
    snapshot = _snapshot(extra_field="surprise")
    with pytest.raises(ValueError, match="unknown fields"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_rejects_per_character_coverage_mismatch():
    snapshot = _snapshot(
        per_character={"IRONCLAD": _metric(2, 2)},
    )
    with pytest.raises(ValueError, match="exactly cover"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_rejects_missing_scope_fields():
    snapshot = _snapshot()
    del snapshot["scope"]["collected_at"]
    with pytest.raises(ValueError, match="missing required field"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_rejects_unknown_root_field():
    snapshot = _snapshot()
    snapshot["extra"] = 1
    with pytest.raises(ValueError, match="unknown fields"):
        validate_relic_stats_snapshot(snapshot)

# ---------------------------------------------------------------------------
# R2A-2 schema tests (heart_win_presence_rate + boss_choice).
# These exercise the extended snapshot contract with fictional snapshots.
# ---------------------------------------------------------------------------


def _count(value, sample_size):
    return {
        "value": value,
        "unit": "count",
        "provenance": "computed",
        "sample_size": sample_size,
    }


def _rate(numerator, denominator):
    return make_relic_rate_metric(numerator, denominator)


def _boss_act(offered, picked, screens, *, picked_override=None):
    act = {
        "offered_count": _count(offered, screens),
        "picked_count": _count(picked_override if picked_override is not None else picked, screens),
    }
    if offered > 0:
        act["pick_rate"] = _rate(picked, offered)
    return act


def _r2_relic(**overrides):
    relic = _relic()
    relic["boss_choice"] = {
        "act1": _boss_act(offered=2, picked=1, screens=5),
        "act2": _boss_act(offered=0, picked=0, screens=3),
    }
    relic["heart_win_presence_rate"] = _rate(1, 2)
    relic.update(overrides)
    return relic


def _r2_snapshot(**relic_overrides):
    snapshot = _snapshot()
    snapshot["scope"]["heart_win_runs"] = 2
    snapshot["scope"]["boss_relic_screens"] = {"act1": 5, "act2": 3}
    snapshot["relics"]["BURNING_BLOOD"] = _r2_relic(**relic_overrides)
    return snapshot


def test_r2a2_snapshot_valid():
    validate_relic_stats_snapshot(_r2_snapshot())


def test_validate_heart_denominator_must_match_scope_heart_runs():
    snapshot = _r2_snapshot(heart_win_presence_rate=_rate(1, 3))
    with pytest.raises(ValueError, match="must equal the heart-win run count"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_heart_metric_required_when_heart_runs_present():
    relic = _r2_relic()
    del relic["heart_win_presence_rate"]
    snapshot = _r2_snapshot()
    snapshot["relics"]["BURNING_BLOOD"] = relic
    with pytest.raises(ValueError, match="missing required fields"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_boss_pick_rate_required_when_offered():
    relic = _r2_relic()
    del relic["boss_choice"]["act1"]["pick_rate"]
    snapshot = _r2_snapshot()
    snapshot["relics"]["BURNING_BLOOD"] = relic
    with pytest.raises(ValueError, match="requires pick_rate"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_boss_pick_rate_forbidden_when_never_offered():
    relic = _r2_relic()
    relic["boss_choice"]["act2"]["pick_rate"] = _rate(0, 0) if False else {
        "value": 0.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 0,
        "denominator": 0,
        "sample_size": 0,
    }
    snapshot = _r2_snapshot()
    snapshot["relics"]["BURNING_BLOOD"] = relic
    with pytest.raises(ValueError, match="forbids pick_rate"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_boss_count_sample_size_must_match_screens():
    relic = _r2_relic()
    relic["boss_choice"]["act1"]["offered_count"] = _count(2, 4)
    snapshot = _r2_snapshot()
    snapshot["relics"]["BURNING_BLOOD"] = relic
    with pytest.raises(ValueError, match="must equal the act1 boss screen count"):
        validate_relic_stats_snapshot(snapshot)


def test_validate_boss_acts_must_cover_acts_with_screens():
    relic = _r2_relic()
    del relic["boss_choice"]["act2"]
    snapshot = _r2_snapshot()
    snapshot["relics"]["BURNING_BLOOD"] = relic
    with pytest.raises(ValueError, match="must cover"):
        validate_relic_stats_snapshot(snapshot)
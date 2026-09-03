import copy
import json
from pathlib import Path

import pytest

from card_guess.card_stats import (
    adapt_sts2_snapshot,
    make_rate_metric,
    validate_card_stats_snapshot,
)


SCHEMA_PATH = Path(__file__).parents[1] / "data" / "stats" / "card_stats.schema.json"


def _source(**metrics):
    units = {
        "act_win_delta": "percentage_points",
        "win_delta": "percentage_points",
        "picked_count": "count",
        "picked_run_count": "count",
        "first_pick_floor_mean": "floor",
        "final_deck_copy_mean": "copies",
    }
    definitions = {
        name: {
            "description": f"Test definition for {name}",
            "unit": units.get(name, "percent"),
        }
        for name in metrics
    }
    return {
        "source": "Mega Crit run dump",
        "scope": {
            "game": "sts1",
            "character": "ironclad",
            "character_scope": "single_character",
            "ascension_min": 20,
            "ascension_max": 20,
            "date_start": "2020-07-01",
            "date_end": "2020-11-30",
            "build_versions": ["2020-11-30"],
            "excluded_modes": ["daily", "trial", "endless"],
            "filters": {"victory": "all"},
        },
        "version": {"dataset": "2020-07_to_2020-11"},
        "collected_at": "2030-01-02T03:04:05Z",
        "metric_definitions": definitions,
        **metrics,
    }


def _snapshot(**metrics):
    return {
        "schema_version": "1.0.0",
        "cards": {"BASH": {"metrics": {"mega_crit_2020": _source(**metrics)}}},
    }


def test_schema_declares_the_unified_card_source_shape():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    source_properties = schema["$defs"]["sourceMetrics"]["properties"]
    assert set(source_properties) >= {
        "source",
        "scope",
        "version",
        "collected_at",
        "metric_definitions",
        "act_pick_rate",
        "act_shop_buy_rate",
        "act_upgrade_rate",
        "act_win_delta",
        "pick_rate",
        "win_delta",
        "picked_count",
        "picked_run_count",
        "first_pick_floor_mean",
        "final_deck_presence_rate",
        "final_deck_copy_mean",
        "final_upgrade_rate",
        "repick_rate",
        "retention_rate",
    }


def test_make_rate_metric_requires_counts_for_computed_rates():
    metric = make_rate_metric(
        value=25.0,
        numerator=25,
        denominator=100,
        sample_size=100,
    )

    assert metric == {
        "value": 25.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 25,
        "denominator": 100,
        "sample_size": 100,
    }
    with pytest.raises(ValueError, match="computed rate requires numerator and denominator"):
        make_rate_metric(value=25.0, sample_size=100)


def test_make_rate_metric_does_not_infer_counts_for_reported_rates():
    metric = make_rate_metric(
        value=37.0,
        sample_size=8300,
        provenance="reported",
    )

    assert metric == {
        "value": 37.0,
        "unit": "percent",
        "provenance": "reported",
        "sample_size": 8300,
    }
    assert "numerator" not in metric
    assert "denominator" not in metric


def test_make_rate_metric_preserves_both_groups_for_computed_win_delta():
    metric = make_rate_metric(
        value=5.0,
        unit="percentage_points",
        numerator=30,
        denominator=50,
        comparison_numerator=55,
        comparison_denominator=100,
        sample_size=150,
    )

    assert metric["unit"] == "percentage_points"
    assert metric["numerator"] == 30
    assert metric["denominator"] == 50
    assert metric["comparison_numerator"] == 55
    assert metric["comparison_denominator"] == 100


def test_validator_accepts_all_supported_metrics_and_missing_metrics():
    rate = make_rate_metric(
        value=40.0,
        numerator=40,
        denominator=100,
        sample_size=100,
    )
    delta = {
        "value": 2.5,
        "unit": "percentage_points",
        "provenance": "computed",
        "sample_size": 100,
        "numerator": 30,
        "denominator": 50,
        "comparison_numerator": 55,
        "comparison_denominator": 100,
    }
    scalar = {
        "value": 12,
        "unit": "count",
        "provenance": "computed",
        "sample_size": 100,
    }
    snapshot = _snapshot(
        act_pick_rate={"act_1": rate},
        act_shop_buy_rate={"act_2": rate},
        act_upgrade_rate={"act_3": rate},
        act_win_delta={"act_1": delta},
        pick_rate=rate,
        win_delta=delta,
        picked_count=scalar,
        picked_run_count=scalar,
        first_pick_floor_mean={**scalar, "unit": "floor"},
        final_deck_presence_rate=rate,
        final_deck_copy_mean={**scalar, "unit": "copies"},
        final_upgrade_rate=rate,
        repick_rate=rate,
        retention_rate=rate,
    )

    assert validate_card_stats_snapshot(snapshot) is None

    del snapshot["cards"]["BASH"]["metrics"]["mega_crit_2020"][
        "retention_rate"
    ]
    del snapshot["cards"]["BASH"]["metrics"]["mega_crit_2020"][
        "metric_definitions"
    ]["retention_rate"]
    assert validate_card_stats_snapshot(snapshot) is None


def test_validator_rejects_invalid_source_metadata_and_rate_contracts():
    reported = make_rate_metric(
        value=40.0,
        sample_size=100,
        provenance="reported",
    )
    snapshot = _snapshot(act_pick_rate={"act_1": reported})
    source = snapshot["cards"]["BASH"]["metrics"]["mega_crit_2020"]

    del source["scope"]["character_scope"]
    with pytest.raises(ValueError, match="character_scope"):
        validate_card_stats_snapshot(snapshot)

    source["scope"]["character_scope"] = "single_character"
    source["act_pick_rate"]["act_1"]["provenance"] = "computed"
    with pytest.raises(ValueError, match="numerator and denominator"):
        validate_card_stats_snapshot(snapshot)


def test_validator_requires_percentage_points_for_win_delta():
    snapshot = _snapshot(
        act_win_delta={
            "act_1": make_rate_metric(
                value=2.0,
                sample_size=4000,
                provenance="reported",
            )
        }
    )

    with pytest.raises(ValueError, match="percentage_points"):
        validate_card_stats_snapshot(snapshot)


def test_validator_accepts_global_pick_rate_and_win_delta_as_single_metrics():
    snapshot = _snapshot(
        pick_rate=make_rate_metric(
            value=42.5,
            numerator=17,
            denominator=40,
            sample_size=40,
        ),
        win_delta=make_rate_metric(
            value=6.5,
            unit="percentage_points",
            numerator=10,
            denominator=20,
            comparison_numerator=5,
            comparison_denominator=30,
            sample_size=50,
        ),
    )
    source = snapshot["cards"]["BASH"]["metrics"]["mega_crit_2020"]
    assert validate_card_stats_snapshot(snapshot) is None
    assert source["pick_rate"]["denominator"] == 40
    assert source["win_delta"]["comparison_denominator"] == 30


def test_validator_requires_global_win_delta_to_follow_the_delta_contract():
    # A percent rate under the win_delta name must be rejected as a unit mismatch.
    snapshot = _snapshot(
        win_delta=make_rate_metric(
            value=2.0,
            numerator=2,
            denominator=100,
            sample_size=100,
        )
    )
    with pytest.raises(ValueError, match="percentage_points"):
        validate_card_stats_snapshot(snapshot)

    # A computed delta without comparison counts must be rejected.
    snapshot = _snapshot(
        win_delta=make_rate_metric(
            value=2.0,
            unit="percentage_points",
            numerator=2,
            denominator=100,
            comparison_numerator=1,
            comparison_denominator=50,
            sample_size=100,
        )
    )
    del snapshot["cards"]["BASH"]["metrics"]["mega_crit_2020"]["win_delta"][
        "comparison_numerator"
    ]
    del snapshot["cards"]["BASH"]["metrics"]["mega_crit_2020"]["win_delta"][
        "comparison_denominator"
    ]
    with pytest.raises(ValueError, match="comparison numerator and denominator"):
        validate_card_stats_snapshot(snapshot)


def test_adapt_sts2_snapshot_maps_supported_fields_without_inference():
    old = {
        "schema_version": "1.0.0",
        "game": "sts2",
        "collected_at": "2030-01-02T03:04:05Z",
        "sources": {
            "untapped": {
                "source": "https://sts2.untapped.gg",
                "scope": {
                    "players": "singleplayer",
                    "ascension": "7+",
                    "character": "card pool",
                    "grouping": "act 1/2/3",
                },
                "version": {"game_version": "v0.111.0", "is_beta": True},
                "collected_at": "2030-01-02T03:04:05Z",
            },
            "spire_codex": {
                "source": "https://spire-codex.com",
                "scope": {"versions": "all submitted runs", "total_runs": 1000},
                "version": {"api": "1.0.0"},
                "collected_at": "2030-01-02T03:04:05Z",
            },
        },
        "cards": {
            "BASH": {
                "id": "BASH",
                "name": "Bash",
                "pool": "ironclad",
                "untapped": {
                    "card_reward": {
                        "act_1": {
                            "pick_rate": {
                                "value": 42.0,
                                "unit": "percent",
                                "sample_size": 1200,
                            },
                            "run_win_rate_impact": {
                                "value": -2.0,
                                "unit": "percentage_points",
                                "sample_size": 1200,
                            },
                        }
                    },
                    "shop": {
                        "act_2": {
                            "purchase_rate": {
                                "value": 17.0,
                                "unit": "percent",
                                "sample_size": 800,
                            }
                        }
                    },
                    "smith": {
                        "act_3": {
                            "upgrade_rate": {
                                "value": 11.0,
                                "unit": "percent",
                                "sample_size": 700,
                            }
                        }
                    },
                },
                "spire_codex": {
                    "final_deck_presence_rate": {
                        "value": 25.0,
                        "unit": "percent",
                        "sample_size": 1000,
                        "numerator": 250,
                        "denominator": 1000,
                        "derived": True,
                    }
                },
            }
        },
    }
    before = copy.deepcopy(old)

    adapted = adapt_sts2_snapshot(old)

    assert old == before
    card = adapted["cards"]["BASH"]
    assert card["name"] == "Bash"
    assert card["character"] == "ironclad"

    untapped = card["metrics"]["untapped"]
    assert untapped["scope"] == {
        "game": "sts2",
        "character_scope": "card_pool",
        "ascension_min": 7,
        "build_versions": ["v0.111.0"],
        "filters": {
            "players": "singleplayer",
            "ascension": "7+",
            "character": "card pool",
            "grouping": "act 1/2/3",
        },
    }
    assert untapped["act_pick_rate"]["act_1"] == {
        "value": 42.0,
        "unit": "percent",
        "provenance": "reported",
        "sample_size": 1200,
    }
    assert untapped["act_shop_buy_rate"]["act_2"]["value"] == 17.0
    assert untapped["act_upgrade_rate"]["act_3"]["value"] == 11.0
    assert untapped["act_win_delta"]["act_1"]["unit"] == "percentage_points"
    assert "numerator" not in untapped["act_pick_rate"]["act_1"]
    assert "denominator" not in untapped["act_pick_rate"]["act_1"]

    codex = card["metrics"]["spire_codex"]
    assert codex["final_deck_presence_rate"] == {
        "value": 25.0,
        "unit": "percent",
        "provenance": "reported",
        "numerator": 250,
        "denominator": 1000,
        "sample_size": 1000,
    }
    assert "picked_count" not in untapped
    assert validate_card_stats_snapshot(adapted) is None


def test_adapter_omits_absent_sources_and_metrics():
    old = {
        "game": "sts2",
        "collected_at": "2030-01-02T03:04:05Z",
        "sources": {
            "untapped": {
                "source": "https://sts2.untapped.gg",
                "scope": {"character": "card pool"},
                "version": {"game_version": "v0.111.0"},
                "collected_at": "2030-01-02T03:04:05Z",
            }
        },
        "cards": {"BASH": {"id": "BASH", "name": "Bash", "pool": "ironclad"}},
    }

    adapted = adapt_sts2_snapshot(old)

    assert adapted == {
        "schema_version": "1.0.0",
        "cards": {
            "BASH": {"name": "Bash", "character": "ironclad", "metrics": {}}
        },
    }
    assert validate_card_stats_snapshot(adapted) is None


def test_repository_sts2_snapshot_adapts_and_validates():
    old = json.loads(
        (Path(__file__).parents[1] / "data" / "stats" / "sts2_card_stats.json")
        .read_text(encoding="utf-8")
    )

    adapted = adapt_sts2_snapshot(old)

    assert adapted["cards"]
    assert any(card["metrics"] for card in adapted["cards"].values())
    assert validate_card_stats_snapshot(adapted) is None

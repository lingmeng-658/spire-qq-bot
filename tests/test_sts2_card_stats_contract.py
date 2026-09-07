import json
from datetime import datetime
from pathlib import Path

import pytest


SNAPSHOT_PATH = (
    Path(__file__).parents[1] / "data" / "stats" / "sts2_card_stats.json"
)


@pytest.fixture(scope="module")
def snapshot():
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _metric_items(snapshot):
    for card_id, card in snapshot["cards"].items():
        for source_name in ("untapped", "spire_codex"):
            source = card.get(source_name)
            if not isinstance(source, dict):
                continue
            stack = [((source_name,), source)]
            while stack:
                path, value = stack.pop()
                if not isinstance(value, dict):
                    continue
                if "value" in value:
                    yield card_id, path, value
                    continue
                stack.extend((path + (key,), child) for key, child in value.items())


def test_percent_values_use_zero_to_one_hundred_scale(snapshot):
    percent_metrics = [
        (card_id, path, metric)
        for card_id, path, metric in _metric_items(snapshot)
        if metric.get("unit") == "percent"
    ]

    assert percent_metrics
    for card_id, path, metric in percent_metrics:
        assert 0 <= metric["value"] <= 100, (card_id, path, metric)


def test_every_rate_owns_the_sample_size_for_its_metric(snapshot):
    rate_metrics = [
        (card_id, path, metric)
        for card_id, path, metric in _metric_items(snapshot)
        if path[-1].endswith(("_rate", "_rate_impact"))
    ]

    assert rate_metrics
    for card_id, path, metric in rate_metrics:
        assert isinstance(metric.get("sample_size"), int), (card_id, path, metric)
        assert metric["sample_size"] > 0, (card_id, path, metric)

    for card_id, card in snapshot["cards"].items():
        untapped = card.get("untapped", {})
        for section in ("card_reward", "shop", "smith"):
            for act, metrics in untapped.get(section, {}).items():
                sample_sizes = {
                    metric["sample_size"]
                    for name, metric in metrics.items()
                    if name.endswith(("_rate", "_rate_impact"))
                }
                assert len(sample_sizes) == 1, (card_id, section, act, metrics)


def test_final_deck_presence_rate_is_internally_consistent(snapshot):
    checked = 0
    for card_id, card in snapshot["cards"].items():
        metric = card.get("spire_codex", {}).get("final_deck_presence_rate")
        if metric is None:
            continue
        checked += 1
        assert metric["sample_size"] == metric["denominator"], (card_id, metric)
        assert metric["numerator"] <= metric["denominator"], (card_id, metric)
        assert metric["value"] == pytest.approx(
            metric["numerator"] / metric["denominator"] * 100,
            abs=0.00005,
        ), (card_id, metric)

    assert checked


def test_missing_metrics_are_omitted_instead_of_filled_with_zero(snapshot):
    unsupported = {
        "acquisition_count",
        "average_acquisition_floor",
        "retention_after_acquisition_rate",
    }
    cards_without_untapped = 0

    for card in snapshot["cards"].values():
        assert not unsupported.intersection(card.get("spire_codex", {}))
        if "untapped" not in card:
            cards_without_untapped += 1
        else:
            assert card["untapped"]

    assert cards_without_untapped


def test_source_scope_metadata_is_complete(snapshot):
    collected_at = snapshot["collected_at"]
    assert datetime.fromisoformat(collected_at.replace("Z", "+00:00")).tzinfo

    assert set(snapshot["sources"]) == {"untapped", "spire_codex"}
    for source_name, metadata in snapshot["sources"].items():
        assert metadata["source"].startswith("https://"), source_name
        assert metadata["collected_at"] == collected_at, source_name
        assert isinstance(metadata["scope"], dict) and metadata["scope"], source_name
        assert isinstance(metadata["version"], dict) and metadata["version"], source_name

    assert set(snapshot["sources"]["untapped"]["scope"]) >= {
        "players",
        "ascension",
        "character",
        "grouping",
    }
    assert set(snapshot["sources"]["spire_codex"]["scope"]) >= {
        "bracket",
        "players",
        "game_modes",
        "versions",
        "total_runs",
    }


def test_no_partial_finegrained_overlay_in_formal_snapshot(snapshot):
    for card_id, card in snapshot["cards"].items():
        untapped = card.get("untapped")
        if not isinstance(untapped, dict):
            continue
        for section_key, section in untapped.items():
            if not isinstance(section, dict):
                continue
            for act_key, act_data in section.items():
                assert "finegrained" not in act_data, (
                    card_id,
                    section_key,
                    act_key,
                )

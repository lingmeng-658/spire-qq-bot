import json
from pathlib import Path

import requests

from scripts.sts2_card_stats import (
    HttpClient,
    build_snapshot,
    coverage_report,
    match_untapped_urls,
    parse_spire_codex_metrics,
    parse_untapped_card_html,
    parse_untapped_sitemap,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sts2_stats"


def test_untapped_parser_preserves_per_metric_samples_and_omits_missing_values():
    html = (FIXTURES / "untapped_card.html").read_text(encoding="utf-8")

    stats = parse_untapped_card_html(html)

    reward_1 = stats["card_reward"]["act_1"]
    assert reward_1["pick_rate"] == {
        "value": 42.0,
        "unit": "percent",
        "sample_size": 1200,
        "sample_size_display": "1,200",
    }
    assert reward_1["act_win_rate_impact"]["value"] == 3.0
    assert reward_1["run_win_rate_impact"]["value"] == -2.0
    assert "act_win_rate_impact" not in stats["card_reward"]["act_2"]
    assert "overall" not in stats["card_reward"]
    assert stats["shop"]["act_1"]["purchase_rate"]["value"] == 17.0
    assert stats["smith"]["act_1"]["upgrade_rate"]["sample_size"] == 1500


def test_sitemap_matching_uses_local_ids_and_reports_both_unresolved_directions():
    xml = (FIXTURES / "untapped_cards_sitemap.xml").read_text(encoding="utf-8")
    cards = [
        {"id": "EMBER_LANCE", "color": "ironclad"},
        {"id": "SHADOW_STEP", "color": "silent"},
        {"id": "LOCAL_ONLY", "color": "regent"},
    ]

    urls = parse_untapped_sitemap(xml)
    matched, unresolved = match_untapped_urls(cards, urls)

    assert matched == {
        "EMBER_LANCE": "https://sts2.untapped.gg/en/cards/ironclad/ember-lance",
        "SHADOW_STEP": "https://sts2.untapped.gg/en/cards/silent/shadow-step",
    }
    assert {item["reason"] for item in unresolved} == {
        "local_card_missing_from_source",
        "source_card_missing_from_local_catalog",
    }
    assert any(item.get("card_id") == "LOCAL_ONLY" for item in unresolved)
    assert any(item.get("source_url", "").endswith("/source-only") for item in unresolved)


def test_sitemap_matching_falls_back_to_unique_slug_when_local_color_is_event():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://sts2.untapped.gg/en/cards/silent/caltrops</loc></url>
  <url><loc>https://sts2.untapped.gg/en/cards/ironclad/clash</loc></url>
  <url><loc>https://sts2.untapped.gg/en/cards/defect/alpha</loc></url>
  <url><loc>https://sts2.untapped.gg/en/cards/ironclad/alpha</loc></url>
  <url><loc>https://sts2.untapped.gg/en/cards/event/mad-science-sapping</loc></url>
  <url><loc>https://sts2.untapped.gg/en/cards/event/mad-science-violence</loc></url>
</urlset>
"""
    cards = [
        {"id": "CALTROPS", "color": "event"},
        {"id": "CLASH", "color": "event"},
        {"id": "ALPHA", "color": "event"},
        {"id": "MAD_SCIENCE", "color": "event"},
    ]

    urls = parse_untapped_sitemap(xml)
    matched, unresolved = match_untapped_urls(cards, urls)

    assert matched == {
        "CALTROPS": "https://sts2.untapped.gg/en/cards/silent/caltrops",
        "CLASH": "https://sts2.untapped.gg/en/cards/ironclad/clash",
    }
    unresolved_ids = {
        item["card_id"]
        for item in unresolved
        if item.get("reason") == "local_card_missing_from_source"
    }
    assert {"ALPHA", "MAD_SCIENCE"} <= unresolved_ids


def test_spire_codex_parser_only_emits_supported_metrics_and_ignores_upgraded_rows():
    payload = json.loads((FIXTURES / "spire_codex_metrics.json").read_text(encoding="utf-8"))

    stats, unresolved = parse_spire_codex_metrics(payload, {"EMBER_LANCE"})

    assert stats == {
        "EMBER_LANCE": {
            "final_deck_runs": {"value": 250, "sample_size": 1000},
            "final_deck_presence_rate": {
                "value": 25.0,
                "unit": "percent",
                "sample_size": 1000,
                "numerator": 250,
                "denominator": 1000,
                "derived": True,
            },
        }
    }
    assert "acquisition_count" not in stats["EMBER_LANCE"]
    assert "average_acquisition_floor" not in stats["EMBER_LANCE"]
    assert "retention_after_acquisition_rate" not in stats["EMBER_LANCE"]
    assert unresolved == [
        {
            "source": "spire_codex",
            "reason": "source_card_missing_from_local_catalog",
            "card_id": "SOURCE_ONLY",
        }
    ]


def test_snapshot_is_keyed_by_every_local_card_and_reports_field_coverage():
    cards = [
        {"id": "EMBER_LANCE", "name": "余烬长枪", "color": "ironclad"},
        {"id": "LOCAL_ONLY", "name": "本地牌", "color": "regent"},
    ]
    untapped = {
        "EMBER_LANCE": {
            "card_reward": {
                "act_1": {
                    "pick_rate": {
                        "value": 42.0,
                        "unit": "percent",
                        "sample_size": 1200,
                        "sample_size_display": "1,200",
                    }
                }
            }
        }
    }
    codex = {
        "EMBER_LANCE": {
            "final_deck_runs": {"value": 250, "sample_size": 1000},
            "final_deck_presence_rate": {
                "value": 25.0,
                "unit": "percent",
                "sample_size": 1000,
                "numerator": 250,
                "denominator": 1000,
                "derived": True,
            },
        }
    }

    snapshot = build_snapshot(
        cards,
        untapped,
        codex,
        source_metadata={
            "untapped": {"source": "https://example.invalid/untapped"},
            "spire_codex": {"source": "https://example.invalid/codex"},
        },
        unresolved=[{"source": "untapped", "reason": "fictional"}],
        collected_at="2030-01-02T03:04:05Z",
    )

    assert snapshot["schema_version"] == "1.0.0"
    assert snapshot["collected_at"] == "2030-01-02T03:04:05Z"
    assert list(snapshot["cards"]) == ["EMBER_LANCE", "LOCAL_ONLY"]
    assert snapshot["cards"]["EMBER_LANCE"]["untapped"] == untapped["EMBER_LANCE"]
    assert "untapped" not in snapshot["cards"]["LOCAL_ONLY"]
    assert snapshot["unresolved"] == [{"source": "untapped", "reason": "fictional"}]

    coverage = coverage_report(snapshot)
    assert coverage["matched_cards"]["untapped"] == 1
    assert coverage["matched_cards"]["spire_codex"] == 1
    assert coverage["fields"]["untapped.card_reward.act_1.pick_rate"] == {
        "cards": 1,
        "coverage": 50.0,
    }
    assert coverage["fields"]["spire_codex.acquisition_count"] == {
        "cards": 0,
        "coverage": 0.0,
    }


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"fictional {self.status_code}", response=self
            )


def test_http_client_retries_a_transient_502_response():
    responses = iter(
        [_FakeResponse(502, "temporary"), _FakeResponse(200, "fictional payload")]
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return next(responses)

    client = HttpClient(timeout=7, retries=2, getter=fake_get, sleeper=lambda _: None)

    assert client.text("https://example.invalid/fixture") == "fictional payload"
    assert len(calls) == 2


def test_http_client_does_not_retry_a_permanent_404_response():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(404, "missing")

    client = HttpClient(timeout=7, retries=2, getter=fake_get, sleeper=lambda _: None)

    try:
        client.text("https://example.invalid/missing")
    except requests.HTTPError as exc:
        assert exc.response.status_code == 404
    else:
        raise AssertionError("404 should be raised")
    assert len(calls) == 1

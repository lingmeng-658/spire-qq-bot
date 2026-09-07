"""Tests for Untapped embedded (flight) stat payload decoding.

The real card pages embed one decision overlay per SSR page inside Next.js
flight script content.  The payload is JSON-string-escaped (one backslash
before each quote); this module decodes it and normalizes only the audited
decision fields with an explicit scope.  All fixtures are synthetic.
"""

import json

from scripts.untapped_embedded_stats import (
    CARD_STATS_FIELDS,
    card_decision_records,
    extract_embedded_stat_payloads,
    js_unescape,
    scope_from_tooltip,
)

REWARD_PAYLOAD = {
    "kind": "reward",
    "cardId": "ABRASIVE",
    "act": 2,
    "multiplayer": False,
    "sampleCount": 9636,
    "stats": {
        "times_offered": 16193,
        "times_picked": 9636,
        "pick_pct": 59.51,
        "pick_pct_delta": 29.01,
        "skip_pct": 2.01,
        "skip_pct_delta": -6.1,
        "win_ca_pct": 52.1,
        "win_ca_pct_delta": 2.75,
        "win_pct": 24.62,
        "win_pct_delta": 0.88,
        "pick_tier": "A",
        "skip_tier": "C",
        "win_ca_tier": "A",
        "win_tier": "B",
        "debug_badge_content": [{"text": "60%"}],
        "debug_tooltips": [
            {
                "header": "Card Stats",
                "text": "Scoped to: Not Upgraded, Act 2, SILENT",
                "rows": [["PR", "59.5", "+29.0", "A", "16.2k"]],
            }
        ],
    },
    "primaryPct": 59.51,
    "rateState": "ok",
    "winrateState": "ok",
}


def flight_wrap(payloads, prefix="prefix", suffix="suffix"):
    body = "".join(
        json.dumps(payload).replace("\\", "\\\\").replace('"', '\\"')
        for payload in payloads
    )
    return (
        "<script>self.__next_f.push([1,\""
        + prefix
        + body
        + suffix
        + '"])</script>'
    )


def test_js_unescape_resolves_common_escapes():
    assert js_unescape('a\\"b\\\\c\\nd\\u4e2d') == 'a"b\\c\nd中'


def test_extract_dedupes_repeated_flight_copies():
    html = flight_wrap([REWARD_PAYLOAD, REWARD_PAYLOAD])
    payloads = extract_embedded_stat_payloads(html)
    assert len(payloads) == 1
    assert payloads[0]["cardId"] == "ABRASIVE"
    assert payloads[0]["stats"]["times_offered"] == 16193


def test_card_decision_records_keep_only_audited_fields_and_scope():
    html = flight_wrap([REWARD_PAYLOAD])
    records = card_decision_records(html, "ABRASIVE")
    assert len(records) == 1
    record = records[0]
    assert record["kind"] == "reward"
    assert record["act"] == 2
    assert record["multiplayer"] is False
    assert record["sample_count"] == 9636
    assert record["stats"] == {
        key: REWARD_PAYLOAD["stats"][key] for key in CARD_STATS_FIELDS
    }
    assert record["scope"]["upgraded"] is False
    assert record["scope"]["character"] == "SILENT"
    assert "debug_tooltips" not in record["stats"]
    assert "primaryPct" not in record


def test_card_decision_records_ignore_promo_for_other_entities():
    promo = dict(REWARD_PAYLOAD)
    promo["cardId"] = "FASTEN"
    html = flight_wrap([REWARD_PAYLOAD, promo])
    records = card_decision_records(html, "ABRASIVE")
    assert [r["kind"] for r in records] == ["reward"]
    assert len(records) == 1


def test_card_decision_records_never_fill_missing_fields_with_zero():
    sparse = dict(REWARD_PAYLOAD)
    sparse["stats"] = {"times_offered": 100, "pick_pct": 80.0}
    html = flight_wrap([sparse])
    records = card_decision_records(html, "ABRASIVE")
    assert records[0]["stats"] == {"times_offered": 100, "pick_pct": 80.0}
    assert "times_picked" not in records[0]["stats"]
    assert "pick_pct_delta" not in records[0]["stats"]


def test_card_decision_records_ignore_unrelated_pages():
    html = "<html><body>no stats</body></html>"
    assert card_decision_records(html, "ABRASIVE") == []


def test_scope_from_tooltip_parses_upgraded_and_character():
    scope = scope_from_tooltip(REWARD_PAYLOAD["stats"])
    assert scope["upgraded"] is False
    assert scope["character"] == "SILENT"
    assert scope["source_text"] == "Scoped to: Not Upgraded, Act 2, SILENT"

"""STS2 relic stats snapshot aggregation tests (fixture data only).

The fixtures mirror the audited Spire Codex relic metrics schema
(``/api/runs/metrics/relics`` with and without ``character`` filter) using
fictional relic ids and counts.  No live API calls or real user data.
"""

from __future__ import annotations

import pytest

from card_guess.sts2_relic_stats import (
    STS2_CHARACTERS,
    build_sts2_relic_snapshot,
    validate_sts2_relic_snapshot,
)


def _row(relic_id, picks, wins, score=None, tier=None, upgraded=False):
    row = {
        "id": relic_id,
        "upgraded": upgraded,
        "picks": picks,
        "wins": wins,
        "losses": picks - wins,
        "win_rate": round(wins / picks * 100, 1) if picks else None,
        "score": score,
        "tier": tier,
        "elo": None,
    }
    if score is None:
        row.pop("score")
    if tier is None:
        row.pop("tier")
    return row


def _overall_payload(*rows, total_runs=40000, baseline=51.8, bracket="all"):
    return {
        "entity_type": "relics",
        "bracket": bracket,
        "total_runs": total_runs,
        "baseline_win_rate": baseline,
        "rows": list(rows),
    }


def _character_payload(character, *rows, character_runs=10000, character_wins=5000):
    return {
        "entity_type": "relics",
        "character": character,
        "bracket": "all",
        "total_runs": 40000,
        "character_runs": character_runs,
        "character_wins": character_wins,
        "baseline_win_rate": 51.8,
        "rows": list(rows),
    }


def _catalog():
    return [
        {"id": "RELIC_ONE", "name_en": "Fictional Relic One", "tier": "Uncommon", "color": "shared"},
        {"id": "RELIC_TWO", "name_en": "Fictional Relic Two", "tier": "Starter", "color": "ironclad"},
        {"id": "RELIC_THREE", "name_en": "Fictional Relic Three", "tier": "Rare", "color": "shared"},
    ]


def _character_payloads(picks_one=1200, wins_one=700):
    rows_by_character = {
        "IRONCLAD": (picks_one, wins_one),
        "SILENT": (picks_one - 200, wins_one - 120),
        "DEFECT": (picks_one - 300, wins_one - 160),
        "REGENT": (picks_one - 400, wins_one - 210),
        "NECROBINDER": (picks_one - 500, wins_one - 230),
    }
    return {
        character: _character_payload(
            character,
            _row("RELIC_ONE", picks, wins),
            _row("RELIC_TWO", picks // 2, wins // 2),
            character_runs=9000 + index * 1000,
            character_wins=4000 + index * 500,
        )
        for index, (character, (picks, wins)) in enumerate(rows_by_character.items())
    }


def _build(**kwargs):
    defaults = {
        "overall_payload": _overall_payload(
            _row("RELIC_ONE", 3000, 1700, score=64, tier="C"),
            _row("RELIC_TWO", 1500, 700, score=12, tier="F"),
        ),
        "character_payloads": _character_payloads(),
        "relic_catalog": _catalog(),
        "collected_at": "2026-09-05T00:00:00Z",
    }
    defaults.update(kwargs)
    return build_sts2_relic_snapshot(**defaults)


def _overall_metric(entry, key):
    return entry["overall"][key]


def test_build_snapshot_joins_catalog_and_derives_metrics():
    snapshot = _build()

    assert snapshot["schema_version"] == "1.0.0"
    assert snapshot["game"] == "sts2"
    assert snapshot["scope"]["total_runs"] == 40000
    assert snapshot["scope"]["baseline_win_rate"] == 51.8
    assert snapshot["scope"]["character_runs"]["IRONCLAD"] == 9000

    entry = snapshot["relics"]["RELIC_ONE"]
    assert entry["name_en"] == "Fictional Relic One"
    assert entry["tier"] == "Uncommon"
    assert entry["catalog_color"] == "shared"
    assert entry["catalog_color_trusted"] is False
    assert entry["source_score"] == 64
    assert entry["source_tier"] == "C"

    overall = entry["overall"]
    assert overall["picks"] == 3000
    assert overall["wins"] == 1700
    assert overall["losses"] == 1300
    win_rate = overall["win_rate"]
    assert win_rate["numerator"] == 1700
    assert win_rate["denominator"] == 3000
    assert win_rate["sample_size"] == 3000
    assert win_rate["value"] == pytest.approx(1700 / 3000 * 100)
    presence = overall["presence_rate"]
    assert presence["numerator"] == 3000
    assert presence["denominator"] == 40000
    assert presence["value"] == pytest.approx(3000 / 40000 * 100)

    per_character = entry["per_character"]
    assert set(per_character) == set(STS2_CHARACTERS)
    ironclad = per_character["IRONCLAD"]
    assert ironclad["picks"] == 1200
    assert ironclad["presence_rate"]["denominator"] == 9000
    assert ironclad["presence_rate"]["value"] == pytest.approx(1200 / 9000 * 100)
    assert ironclad["win_rate"]["denominator"] == 1200


def test_build_snapshot_requires_every_canonical_character_payload():
    payloads = _character_payloads()
    payloads.pop("REGENT")
    with pytest.raises(ValueError, match="REGENT"):
        _build(character_payloads=payloads)


def test_build_snapshot_requires_positive_global_total_runs():
    with pytest.raises(ValueError, match="total_runs"):
        _build(overall_payload=_overall_payload(_row("RELIC_ONE", 3000, 1700), total_runs=0))


def test_build_snapshot_requires_valid_count_consistency():
    bad = _character_payloads()
    bad["IRONCLAD"] = _character_payload("IRONCLAD", _row("RELIC_ONE", 9500, 5000), character_runs=9000)
    with pytest.raises(ValueError, match="character_runs"):
        _build(character_payloads=bad)


def test_build_snapshot_reports_missing_and_extra_relic_ids():
    payload = _overall_payload(
        _row("RELIC_ONE", 3000, 1700),
        _row("EXTRA_RELIC", 5, 2),
    )
    snapshot = _build(overall_payload=payload)
    reasons = {(item.get("relic_id"), item.get("reason")) for item in snapshot["unresolved"]}
    assert ("EXTRA_RELIC", "api_relic_missing_from_local_catalog") in reasons
    assert ("RELIC_THREE", "catalog_relic_missing_from_source") in reasons
    assert "EXTRA_RELIC" not in snapshot["relics"]
    assert "RELIC_THREE" not in snapshot["relics"]


def test_build_snapshot_skips_upgraded_rows_as_unresolved():
    payload = _overall_payload(
        _row("RELIC_ONE", 3000, 1700),
        _row("RELIC_TWO", 100, 40, upgraded=True),
    )
    snapshot = _build(overall_payload=payload)
    reasons = {(item.get("relic_id"), item.get("reason")) for item in snapshot["unresolved"]}
    assert ("RELIC_TWO", "upgraded_row") in reasons
    assert "RELIC_TWO" not in snapshot["relics"]


def test_validate_snapshot_accepts_built_snapshot():
    snapshot = _build()
    validate_sts2_relic_snapshot(snapshot)  # must not raise


def test_validate_snapshot_rejects_tampered_presence_denominator():
    snapshot = _build()
    entry = snapshot["relics"]["RELIC_ONE"]
    entry["overall"]["presence_rate"]["denominator"] = 9999
    with pytest.raises(ValueError):
        validate_sts2_relic_snapshot(snapshot)


def test_validate_snapshot_rejects_character_not_in_canonical_set():
    snapshot = _build()
    snapshot["relics"]["RELIC_ONE"]["per_character"]["MYSTERY"] = snapshot["relics"]["RELIC_ONE"]["per_character"]["IRONCLAD"]
    with pytest.raises(ValueError, match="MYSTERY"):
        validate_sts2_relic_snapshot(snapshot)

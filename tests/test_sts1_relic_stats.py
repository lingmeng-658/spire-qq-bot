"""Unit tests for the STS1 terminal-relic aggregator (policy C + R2A-2).

Covers the terminal-hold snapshot plus the R2A-2 additions:
``heart_win_presence_rate`` (reuse of the audited heart-win judgment) and
per-act ``boss_choice`` offer/pick statistics from ``boss_relics``.
"""

import json

import pytest

from card_guess.relic_stats import validate_relic_stats_snapshot
from card_guess.sts1_relic_stats import (
    RelicKeyResolver,
    aggregate_sts1_relics,
)

FICTIONAL_CATALOG = [
    {"id": "BURNING_BLOOD", "name_en": "Burning Blood", "tier": "Starter", "color": "ironclad"},
    {"id": "RED_SKULL", "name_en": "Red Skull", "tier": "Common", "color": None},
    {"id": "SNAKE_SKULL", "name_en": "Snecko Skull", "tier": "Common", "color": None},
    {"id": "RING_OF_THE_SNAKE", "name_en": "Ring of the Snake", "tier": "Starter", "color": "silent"},
    {"id": "PUREWATER", "name_en": "Pure Water", "tier": "Starter", "color": None},
    {"id": "YANG", "name_en": "Duality", "tier": "Uncommon", "color": None},
    {"id": "CAPTAINSWHEEL", "name_en": "Captain's Wheel", "tier": "Rare", "color": "watcher"},
    {"id": "UNOBSERVED_RELIC", "name_en": "Unobserved Relic", "tier": "Special", "color": None},
]

COLLECTED_AT = "2030-01-02T03:04:05Z"

HEART_DAMAGE = [{"enemies": "The Heart", "floor": 55}]


def _run(
    play_id,
    character,
    relics=None,
    *,
    is_beta=False,
    victory=None,
    damage_taken=None,
    boss_relics=None,
):
    run = {
        "play_id": play_id,
        "is_beta": is_beta,
        "character_chosen": character,
    }
    if relics is not None:
        run["relics"] = relics
    if victory is not None:
        run["victory"] = victory
    if damage_taken is not None:
        run["damage_taken"] = damage_taken
    if boss_relics is not None:
        run["boss_relics"] = boss_relics
    return run


@pytest.fixture
def fictional_runs():
    return [
        _run(
            "ic-1",
            "IRONCLAD",
            [
                "Burning Blood",
                "Red Skull",
                "Captain's Wheel",
                "Snake Skull",
                "Dodecahedron",
                42,
            ],
            boss_relics=[
                {
                    "picked": "Captain's Wheel",
                    "not_picked": ["Red Skull", "Pure Water"],
                }
            ],
        ),
        _run(
            "ic-2",
            "IRONCLAD",
            ["Burning Blood", "Red Skull", "Captain's Wheel", "Duality"],
            boss_relics=[
                {
                    "picked": "Red Skull",
                    "not_picked": ["Captain's Wheel", "Pure Water"],
                }
            ],
        ),
        _run(
            "sil-1",
            "THE_SILENT",
            ["Ring of the Snake", "Snake Skull", "Yang"],
            boss_relics=[
                {
                    "picked": None,
                    "not_picked": ["Captain's Wheel", 'Red Skull'],
                },
                {
                    "picked": 'Pure Water',
                    "not_picked": ["Captain's Wheel", 'Snake Skull'],
                },
            ],
        ),
        _run(
            "sil-2",
            "THE_SILENT",
            ["Ring of the Snake", "Snake Skull", "Captain's Wheel"],
        ),
        _run(
            "def-1",
            "DEFECT",
            ["Red Skull", "Captain's Wheel"],
            victory=True,
            damage_taken=HEART_DAMAGE,
            boss_relics=[
                {
                    "picked": "Captain's Wheel",
                    "not_picked": ['Pure Water', 'Red Skull'],
                },
                {
                    "picked": None,
                    "not_picked": ['Red Skull', 'Snake Skull'],
                },
            ],
        ),
        _run(
            "def-2",
            "DEFECT",
            ["Captain's Wheel", "Pure Water"],
        ),
        _run(
            "wat-1",
            "WATCHER",
            ["Pure Water", "Captain's Wheel"],
            victory=True,
            damage_taken=HEART_DAMAGE,
            boss_relics=[
                {
                    "picked": 'Pure Water',
                    "not_picked": ["Captain's Wheel", 'Red Skull'],
                },
                {
                    "picked": "Captain's Wheel",
                    "not_picked": ['Red Skull', 'Snake Skull'],
                },
            ],
        ),
        _run(
            "wat-2",
            "WATCHER",
            ["Pure Water", "Snake Skull"],
        ),
        _run("beta-1", "IRONCLAD", ["Burning Blood"], is_beta=True),
        _run("missing-relics", "IRONCLAD", relics=None),
        _run("bad-character", "THE_CURSED", ["Burning Blood"]),
    ]


@pytest.fixture
def aggregated(fictional_runs):
    return aggregate_sts1_relics(
        fictional_runs,
        relic_catalog=FICTIONAL_CATALOG,
        collected_at=COLLECTED_AT,
    )


def test_report_filters_and_counts(aggregated):
    report = aggregated["report"]
    assert report["total_runs"] == 11
    assert report["valid_runs"] == 8
    assert report["characters"] == {
        "IRONCLAD": 2,
        "THE_SILENT": 2,
        "DEFECT": 2,
        "WATCHER": 2,
    }
    assert report["filter_reasons"] == {
        "beta": 1,
        "missing_relics": 1,
        "non_standard_character": 1,
    }
    assert report["invalid_relic_entries"] == 1
    assert report["unresolved_relic_keys"] == {"Dodecahedron": 1}
    assert report["catalog_relic_count"] == 8
    assert report["observed_relic_count"] == 7
    assert report["unobserved_relic_ids"] == ["UNOBSERVED_RELIC"]


def test_snapshot_scope_denominators(aggregated):
    scope = aggregated["snapshot"]["scope"]
    assert scope["character_runs"] == {
        "IRONCLAD": 2,
        "THE_SILENT": 2,
        "DEFECT": 2,
        "WATCHER": 2,
    }
    assert scope["display_policy"]["catalog_color_trusted"] is False
    assert scope["display_policy"]["min_hold_runs"] == 2
    validate_relic_stats_snapshot(aggregated["snapshot"])


def test_starter_relic_single_character_rate(aggregated):
    relic = aggregated["snapshot"]["relics"]["BURNING_BLOOD"]
    assert relic["observed_roles"] == {"IRONCLAD": 2}
    assert relic["supported_roles"] == ["IRONCLAD"]
    assert relic["display_mode"] == "per_character"
    assert relic["total_hold_runs"] == 2
    assert relic["overall"]["numerator"] == 2
    assert relic["overall"]["denominator"] == 8
    assert relic["overall"]["value"] == pytest.approx(25.0)
    assert relic["per_character"]["IRONCLAD"] == {
        "value": 100.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 2,
        "denominator": 2,
        "sample_size": 2,
    }
    assert relic["per_character"]["THE_SILENT"]["numerator"] == 0


def test_catalog_color_never_decides_eligibility(aggregated):
    relic = aggregated["snapshot"]["relics"]["CAPTAINSWHEEL"]
    # The catalog marks Captain's Wheel as watcher, but the fictional runs only
    # support Ironclad and Defect; policy C must ignore the color field.
    assert relic["catalog_color"] == "watcher"
    assert relic["catalog_color_trusted"] is False
    assert relic["observed_roles"] == {
        "IRONCLAD": 2,
        "THE_SILENT": 1,
        "DEFECT": 2,
        "WATCHER": 1,
    }
    assert relic["supported_roles"] == ["IRONCLAD", "DEFECT"]
    assert relic["display_mode"] == "both"


def test_alias_and_name_resolution_share_one_relic(aggregated):
    relic = aggregated["snapshot"]["relics"]["YANG"]
    # "Duality" resolves via catalog name and "Yang" via the run-key alias.
    assert relic["observed_roles"] == {"IRONCLAD": 1, "THE_SILENT": 1}
    assert relic["supported_roles"] == []
    assert relic["display_mode"] == "none"
    assert relic["total_hold_runs"] == 2


def test_unobserved_catalog_relic_has_zero_rates(aggregated):
    relic = aggregated["snapshot"]["relics"]["UNOBSERVED_RELIC"]
    assert relic["observed_roles"] == {}
    assert relic["supported_roles"] == []
    assert relic["display_mode"] == "none"
    assert relic["total_hold_runs"] == 0
    assert relic["overall"]["value"] == 0.0
    assert all(
        relic["per_character"][role]["numerator"] == 0
        for role in relic["per_character"]
    )


def test_report_heart_and_boss_scope_counts(aggregated):
    report = aggregated["report"]
    assert report["heart_win_runs"] == 2
    assert report["boss_relic_screens"] == {"act1": 5, "act2": 3}
    scope = aggregated["snapshot"]["scope"]
    assert scope["heart_win_runs"] == 2
    assert scope["boss_relic_screens"] == {"act1": 5, "act2": 3}


def test_heart_win_presence_rate(aggregated):
    relics = aggregated["snapshot"]["relics"]
    heart_runs = 2
    # Captain's Wheel is held in both heart-win runs (def-1, wat-1).
    assert relics["CAPTAINSWHEEL"]["heart_win_presence_rate"] == {
        "value": 100.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 2,
        "denominator": 2,
        "sample_size": 2,
    }
    # Red Skull / Pure Water are held in exactly one heart-win run each.
    assert relics["RED_SKULL"]["heart_win_presence_rate"]["numerator"] == 1
    assert relics["PUREWATER"]["heart_win_presence_rate"]["numerator"] == 1
    assert relics["RED_SKULL"]["heart_win_presence_rate"]["value"] == pytest.approx(50.0)
    # Burning Blood never appears in a heart-win run; rate is 0 over heart runs.
    assert relics["BURNING_BLOOD"]["heart_win_presence_rate"] == {
        "value": 0.0,
        "unit": "percent",
        "provenance": "computed",
        "numerator": 0,
        "denominator": 2,
        "sample_size": 2,
    }
    # Every relic's heart denominator equals the heart-win run scope count.
    for relic in relics.values():
        metric = relic["heart_win_presence_rate"]
        assert metric["denominator"] == heart_runs
        assert metric["sample_size"] == heart_runs


def test_boss_choice_pick_rate_uses_offers_not_runs(aggregated):
    relic = aggregated["snapshot"]["relics"]["CAPTAINSWHEEL"]
    act1 = relic["boss_choice"]["act1"]
    assert act1["offered_count"]["value"] == 5
    assert act1["picked_count"]["value"] == 2
    assert act1["pick_rate"] == {
        "value": pytest.approx(40.0),
        "unit": "percent",
        "provenance": "computed",
        "numerator": 2,
        "denominator": 5,
        "sample_size": 5,
    }
    act2 = relic["boss_choice"]["act2"]
    assert act2["offered_count"]["value"] == 2
    assert act2["picked_count"]["value"] == 1
    assert act2["pick_rate"]["value"] == pytest.approx(50.0)


def test_boss_choice_offered_not_picked_and_picked_none(aggregated):
    relics = aggregated["snapshot"]["relics"]
    red_skull_act1 = relics["RED_SKULL"]["boss_choice"]["act1"]
    # Offered in every act1 screen (ic-1, ic-2 picked, sil-1, def-1, wat-1);
    # picked=None never counts as a pick, so picked_count is 1.
    assert red_skull_act1["offered_count"]["value"] == 5
    assert red_skull_act1["picked_count"]["value"] == 1
    assert red_skull_act1["pick_rate"]["value"] == pytest.approx(20.0)
    # Red Skull is offered in both act2 screens (def-1, wat-1) but never picked.
    red_skull_act2 = relics["RED_SKULL"]["boss_choice"]["act2"]
    assert red_skull_act2["offered_count"]["value"] == 2
    assert red_skull_act2["picked_count"]["value"] == 0
    assert red_skull_act2["pick_rate"]["value"] == 0.0


def test_boss_choice_never_offered_relic(aggregated):
    relics = aggregated["snapshot"]["relics"]
    for relic_id in ("YANG", "BURNING_BLOOD", "UNOBSERVED_RELIC"):
        for act in ("act1", "act2"):
            act_data = relics[relic_id]["boss_choice"][act]
            assert act_data["offered_count"]["value"] == 0
            assert act_data["picked_count"]["value"] == 0
            assert "pick_rate" not in act_data


def test_boss_scalar_sample_sizes_are_act_screens(aggregated):
    scope = aggregated["snapshot"]["scope"]
    relics = aggregated["snapshot"]["relics"]
    for relic in relics.values():
        for act, screens in scope["boss_relic_screens"].items():
            act_data = relic["boss_choice"][act]
            assert act_data["offered_count"]["sample_size"] == screens
            assert act_data["picked_count"]["sample_size"] == screens


def test_resolver_precedence_and_unresolved_keys():
    resolver = RelicKeyResolver(FICTIONAL_CATALOG)
    assert resolver.resolve("Snake Skull") == "SNAKE_SKULL"
    assert resolver.resolve("Snecko Skull") == "SNAKE_SKULL"
    assert resolver.resolve("PureWater") == "PUREWATER"
    assert resolver.resolve("Pure Water") == "PUREWATER"
    assert resolver.resolve("Duality") == "YANG"
    assert resolver.resolve("Yang") == "YANG"
    assert resolver.resolve("Dodecahedron") is None
    assert resolver.resolve(42) is None
    assert resolver.resolve("") is None


def test_resolver_rejects_invalid_catalog():
    with pytest.raises(ValueError, match="at least one relic"):
        RelicKeyResolver([])
    duplicate = [dict(FICTIONAL_CATALOG[0]), dict(FICTIONAL_CATALOG[0])]
    with pytest.raises(ValueError, match="duplicate relic catalog id"):
        RelicKeyResolver(duplicate)
    with pytest.raises(ValueError, match="ambiguous relic names"):
        RelicKeyResolver(
            [
                {"id": "ONE", "name_en": "Same Name", "tier": None, "color": None},
                {"id": "TWO", "name_en": "Same Name", "tier": None, "color": None},
            ]
        )


def test_resolver_partial_catalog_ignores_inactive_aliases():
    resolver = RelicKeyResolver([dict(FICTIONAL_CATALOG[0])])
    assert resolver.resolve("Burning Blood") == "BURNING_BLOOD"
    # "Paper Frog" is a real alias, but its target is absent from this small
    # catalog, so the alias is inactive rather than an error.
    assert resolver.resolve("Paper Frog") is None


def test_aggregate_accepts_a_json_path(tmp_path):
    runs = [
        _run("a", "IRONCLAD", ["Burning Blood"]),
        _run("b", "WATCHER", ["Pure Water"]),
    ]
    path = tmp_path / "runs.json"
    path.write_text(json.dumps(runs), encoding="utf-8")
    result = aggregate_sts1_relics(
        str(path),
        relic_catalog=FICTIONAL_CATALOG,
        collected_at=COLLECTED_AT,
    )
    assert result["report"]["valid_runs"] == 2
    assert result["snapshot"]["scope"]["character_runs"] == {
        "IRONCLAD": 1,
        "WATCHER": 1,
    }
    validate_relic_stats_snapshot(result["snapshot"])


def test_aggregate_requires_at_least_one_valid_run():
    runs = [_run("beta", "IRONCLAD", ["Burning Blood"], is_beta=True)]
    with pytest.raises(ValueError, match="at least one valid run"):
        aggregate_sts1_relics(
            runs,
            relic_catalog=FICTIONAL_CATALOG,
            collected_at=COLLECTED_AT,
        )
"""STS1 per-character Card Reward pick ranking: aggregation + ranking helpers.

Uses only fictional card IDs and fictional runs.  The snapshot format here is
the additive per-card ``character_pick_contexts`` container produced by the
STS1 aggregator when ``card_attributes`` are supplied.
"""

import pytest

from card_guess.card_stats import validate_card_stats_snapshot
from card_guess import sts1_card_stats as stats_mod
from card_guess.sts1_card_stats import (
    SINGING_BOWL_ENTITY,
    aggregate_sts1_runs,
)

SRC = "mega_crit_120k_november_asc7plus"

ATTRS = {
    "EMBER_CARD": ("ironclad", "Common"),
    "TIDE": ("silent", "Common"),
    "SPARK": ("silent", "Rare"),
    "GLOW": ("colorless", "Common"),
}

RUN_KEYS = {
    "EMBER_CARD": "Ember Card",
    "TIDE": "Tide",
    "SPARK": "Spark",
    "GLOW": "Glow",
}


def _run(play_id, *, character="IRONCLAD", choices=None):
    return {
        "play_id": play_id,
        "is_daily": False,
        "is_trial": False,
        "is_endless": False,
        "chose_seed": False,
        "is_beta": False,
        "special_seed": 0,
        "build_version": "V1",
        "character_chosen": character,
        "ascension_level": 20,
        "victory": True,
        "card_choices": choices or [],
        "master_deck": [],
        "campfire_choices": [],
    }


def _choice(floor, picked, not_picked=()):
    record = {"floor": floor, "picked": picked, "not_picked": list(not_picked)}
    if picked == "SKIP":
        record.pop("picked")
        record["picked"] = "SKIP"
    return record


def _aggregate(runs):
    return aggregate_sts1_runs(
        runs,
        card_ids=set(ATTRS),
        source_id=SRC,
        collected_at="2030-01-02T03:04:05Z",
        card_attributes=ATTRS,
    )


def _cell(snapshot, card_id, character, act):
    record = snapshot["cards"][card_id]["metrics"][SRC]
    return record["character_pick_contexts"][character][act]


# ---------------------------------------------------------------------------
# Aggregation: character + act grouping and offer/pick semantics.
# ---------------------------------------------------------------------------


def test_character_contexts_group_runs_by_character_chosen():
    ironclad = _run(
        "run-iron",
        choices=[
            _choice(3, "Ember Card", ["Tide", "Spark", SINGING_BOWL_ENTITY]),
            _choice(8, "SKIP", ["Ember Card", "Tide"]),
        ],
    )
    silent = _run(
        "run-silent",
        character="THE_SILENT",
        choices=[_choice(3, "Tide", ["Ember Card"])],
    )
    snapshot = _aggregate([ironclad, silent])["snapshot"]

    assert _cell(snapshot, "EMBER_CARD", "ironclad", "act_1") == {
        "offered_count": 2,
        "picked_count": 1,
    }
    assert _cell(snapshot, "EMBER_CARD", "silent", "act_1") == {
        "offered_count": 1,
        "picked_count": 0,
    }
    assert _cell(snapshot, "TIDE", "silent", "act_1") == {
        "offered_count": 1,
        "picked_count": 1,
    }
    # Singing Bowl is excluded from offers; a silent-color card offered inside
    # an ironclad run keeps its real cross-character distribution.
    assert _cell(snapshot, "SPARK", "ironclad", "act_1") == {
        "offered_count": 1,
        "picked_count": 0,
    }
    assert "act_2" not in snapshot["cards"]["EMBER_CARD"]["metrics"][SRC][
        "character_pick_contexts"
    ]["ironclad"]


def test_character_contexts_split_acts():
    runs = [
        _run(
            f"run-{floor}",
            choices=[_choice(floor, "Ember Card", ["Tide"])],
        )
        for floor in (5, 20, 40)
    ]
    snapshot = _aggregate(runs)["snapshot"]
    contexts = snapshot["cards"]["EMBER_CARD"]["metrics"][SRC][
        "character_pick_contexts"
    ]["ironclad"]
    assert {act: tuple(contexts[act].values()) for act in contexts} == {
        "act_1": (1, 1),
        "act_2": (1, 1),
        "act_3": (1, 1),
    }


def test_character_contexts_skip_unknown_character_and_floor_zero():
    runs = [
        _run("run-druld", character="DRUID", choices=[_choice(3, "Ember Card")]),
        _run("run-zero", choices=[_choice(0, "Ember Card", ["Tide"])]),
        _run("run-40", choices=[_choice(40, "Ember Card", ["Tide"])]),
    ]
    snapshot = _aggregate(runs)["snapshot"]
    contexts = snapshot["cards"]["EMBER_CARD"]["metrics"][SRC][
        "character_pick_contexts"
    ]
    assert set(contexts) == {"ironclad"}
    assert "act_1" not in contexts["ironclad"]


def test_card_attributes_attach_color_rarity_and_validate():
    runs = [
        _run("run-1", choices=[_choice(3, "Ember Card", ["Tide"])]),
        _run("run-2", character="THE_SILENT", choices=[_choice(3, "Spark", ["Glow"])]),
    ]
    snapshot = _aggregate(runs)["snapshot"]
    assert snapshot["cards"]["EMBER_CARD"]["color"] == "ironclad"
    assert snapshot["cards"]["EMBER_CARD"]["rarity"] == "Common"
    assert snapshot["cards"]["GLOW"]["color"] == "colorless"
    # The unified contract still accepts the additive container.
    validate_card_stats_snapshot(snapshot)


def test_character_contexts_are_opt_in_only():
    runs = [_run("run-1", choices=[_choice(3, "Ember Card", ["Tide"])])]
    plain = aggregate_sts1_runs(
        runs,
        card_ids={"EMBER_CARD", "TIDE"},
        collected_at="2030-01-02T03:04:05Z",
    )["snapshot"]
    record = plain["cards"]["EMBER_CARD"]["metrics"]["mega_crit_120k_november"]
    assert "character_pick_contexts" not in record
    assert "color" not in plain["cards"]["EMBER_CARD"]


# ---------------------------------------------------------------------------
# Ranking helper: same character x act x rarity cohorts.
# ---------------------------------------------------------------------------


def _entry(color, rarity, contexts):
    return {
        "color": color,
        "rarity": rarity,
        "metrics": {
            SRC: {
                "source": "fictional",
                "scope": {"game": "sts1", "character_scope": "all_characters"},
                "version": {"dataset": "fictional"},
                "collected_at": "2030-01-02T03:04:05Z",
                "character_pick_contexts": contexts,
            }
        },
    }


def _snapshot(*entries):
    return {"schema_version": "1.0.0", "cards": dict(entries)}


def _cell_ctx(offered, picked):
    return {"offered_count": offered, "picked_count": picked}


def test_rank_rows_group_by_character_act_and_rarity():
    cards = _snapshot(
        (
            "EMBER_CARD",
            _entry(
                "ironclad",
                "Common",
                {
                    "ironclad": {
                        "act_1": _cell_ctx(200, 100),
                        "act_2": _cell_ctx(100, 10),
                    }
                },
            ),
        ),
        (
            "TIDE",
            _entry(
                "silent",
                "Common",
                {"silent": {"act_1": _cell_ctx(200, 190)}},
            ),
        ),
        (
            "CLASH",
            _entry(
                "ironclad",
                "Common",
                {
                    "ironclad": {
                        "act_1": _cell_ctx(200, 180),
                        "act_2": _cell_ctx(200, 150),
                    }
                },
            ),
        ),
        (
            "SPARK",
            _entry(
                "ironclad",
                "Rare",
                {"ironclad": {"act_1": _cell_ctx(200, 199)}},
            ),
        ),
    )

    # EMBER act_1 competes only with the other ironclad Common (CLASH) on act_1.
    act1 = stats_mod.character_pick_act_rows(
        cards, source_id=SRC, character="ironclad", act="act_1", rarity="Common"
    )
    assert [(row["card_id"], row["rank"], row["cohort_size"]) for row in act1] == [
        ("CLASH", 1, 2),
        ("EMBER_CARD", 2, 2),
    ]
    # The silent common and the ironclad rare never enter the ironclad act_1
    # Common cohort.
    # EMBER act_2 uses the act_2 cohort only, not its act_1 position.
    act2 = {
        row["card_id"]: row
        for row in stats_mod.character_pick_act_rows(
            cards, source_id=SRC, character="ironclad", act="act_2", rarity="Common"
        )
    }
    assert act2["EMBER_CARD"]["rank"] == 2
    assert act2["EMBER_CARD"]["cohort_size"] == 2


def test_rank_contexts_respect_min_offered_threshold():
    cards = _snapshot(
        (
            "EMBER_CARD",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(10, 9)}},
            ),
        ),
        (
            "CLASH",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(100, 20)}},
            ),
        ),
    )
    contexts = stats_mod.character_pick_rank_contexts(
        cards, source_id=SRC, card_id="EMBER_CARD", character="ironclad"
    )
    assert contexts == []
    rows = stats_mod.character_pick_act_rows(
        cards, source_id=SRC, character="ironclad", act="act_1", rarity="Common"
    )
    assert [(row["card_id"], row["cohort_size"]) for row in rows] == [("CLASH", 1)]


def test_competition_ranks_tie_only_on_exact_real_rate():
    cards = _snapshot(
        (
            "A",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(2, 2)}},
            ),
        ),
        (
            "B",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(1, 1)}},
            ),
        ),
        (
            "C",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(2, 1)}},
            ),
        ),
        (
            "D",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(1000, 333)}},
            ),
        ),
        (
            "E",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(3, 1)}},
            ),
        ),
    )
    rows = stats_mod.character_pick_act_rows(
        cards,
        source_id=SRC,
        character="ironclad",
        act="act_1",
        rarity="Common",
        min_offered=0,
    )
    ranked = {row["card_id"]: row["rank"] for row in rows}
    # A (2/2) and B (1/1) share the true 100% rate: rank 1, next rate skips.
    assert ranked["A"] == 1
    assert ranked["B"] == 1
    # C (1/2 = 50%) is rank 3 after the tied top pair.
    assert ranked["C"] == 3
    # E (1/3 ~ 33.33%) and D (333/1000 = 33.30%) both display as 33.3% but
    # have different true rates, so they are NOT tied.
    assert ranked["E"] == 4
    assert ranked["D"] == 5
    assert [row["cohort_size"] for row in rows] == [5, 5, 5, 5, 5]


def test_colorless_cards_stay_out_of_character_cohorts():
    cards = _snapshot(
        (
            "EMBER_CARD",
            _entry(
                "ironclad",
                "Common",
                {"ironclad": {"act_1": _cell_ctx(100, 40)}},
            ),
        ),
        (
            "GLOW",
            _entry(
                "colorless",
                "Common",
                {
                    "ironclad": {"act_1": _cell_ctx(100, 99)},
                    "silent": {"act_1": _cell_ctx(100, 80)},
                },
            ),
        ),
    )
    rows = stats_mod.character_pick_act_rows(
        cards, source_id=SRC, character="ironclad", act="act_1", rarity="Common"
    )
    assert [row["card_id"] for row in rows] == ["EMBER_CARD"]
    # Real cross-character distribution is still stored for the colorless card.
    assert stats_mod.character_pick_rank_contexts(
        cards, source_id=SRC, card_id="GLOW", character=None
    ) == []
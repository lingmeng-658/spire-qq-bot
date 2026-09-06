"""STS1 snapshot exporter forwards per-card color/rarity and keeps the
per-character Card Reward pick contexts inside each cohort source record.

Uses only fictional runs; mirrors how the real ``data/stats`` rebuild calls
``build_sts1_snapshot`` with catalog-derived attributes.
"""
from card_guess.sts1_snapshot import build_sts1_snapshot

CATALOG_ATTRS = {
    "EMBER_CARD": ("ironclad", "Common"),
    "TIDE": ("silent", "Common"),
    "SPARK": ("silent", "Rare"),
    "GLOW": ("colorless", "Uncommon"),
}


def _run(play_id, *, character="IRONCLAD", choices=None, ascension=20):
    return {
        "play_id": play_id,
        "build_version": "2020-07-30",
        "character_chosen": character,
        "ascension_level": ascension,
        "victory": True,
        "card_choices": choices or [],
        "master_deck": [],
        "campfire_choices": [],
        "is_daily": False,
        "is_trial": False,
        "is_endless": False,
        "chose_seed": False,
        "is_beta": False,
        "special_seed": 0,
    }


def _choice(floor, picked, not_picked=()):
    return {"floor": floor, "picked": picked, "not_picked": list(not_picked)}


def _build(card_attributes):
    return build_sts1_snapshot(
        [
            _run(
                "run-iron",
                choices=[
                    _choice(3, "Ember Card", ["Tide", "Spark", "Glow"]),
                    _choice(8, "SKIP", ["Ember Card"]),
                ],
            ),
            _run(
                "run-silent",
                character="THE_SILENT",
                choices=[_choice(4, "Tide", ["Ember Card", "Glow"])],
            ),
        ],
        card_ids=list(CATALOG_ATTRS),
        card_attributes=card_attributes,
        card_names={cid: cid for cid in CATALOG_ATTRS},
    )["snapshot"]


def test_build_attaches_attributes_and_pick_contexts():
    snapshot = _build(CATALOG_ATTRS)
    entry = snapshot["cards"]["EMBER_CARD"]
    assert entry["color"] == "ironclad"
    assert entry["rarity"] == "Common"
    assert snapshot["cards"]["GLOW"]["color"] == "colorless"
    asc7 = entry["metrics"]["mega_crit_120k_november_asc7plus"]
    assert asc7["character_pick_contexts"]["ironclad"]["act_1"] == {
        "offered_count": 2,
        "picked_count": 1,
    }
    assert asc7["character_pick_contexts"]["silent"]["act_1"] == {
        "offered_count": 1,
        "picked_count": 0,
    }
    assert snapshot["cards"]["TIDE"]["metrics"]["mega_crit_120k_november_asc7plus"][
        "character_pick_contexts"
    ]["silent"]["act_1"] == {"offered_count": 1, "picked_count": 1}


def test_build_without_attributes_stays_plain():
    snapshot = _build(None)
    entry = snapshot["cards"]["EMBER_CARD"]
    assert "color" not in entry
    assert "rarity" not in entry
    assert "character_pick_contexts" not in entry["metrics"]["mega_crit_120k_november_asc7plus"]
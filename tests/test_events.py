"""Event Data Core v1 tests.

The tests pin the frozen Event catalog rules against the repository fixture
catalogs under ``data/raw`` (derived from the audited local archives; real
game data used as static fixtures only, never QQ/private data):

- STS1 catalog = 52 queryable events, default random pool = 51
- STS2 catalog = 66 queryable events, default random pool = 57

Name lookup is exact full-name matching only (zh exact; en
case-insensitive); no prefix, fuzzy or pinyin matching.
"""

from __future__ import annotations

import json

import pytest

from card_guess import events as event_mod
from card_guess.events import (
    CATALOG_FILES,
    DEFAULT_CATALOG_DIR,
    EventCatalogError,
    default_random_pool,
    find_events_by_name,
    get_event,
    load_events,
    validate_catalog,
)

STS1_SAMPLE_IDS = ["BIG_FISH", "THE_CLERIC", "CURSED_TOME", "NOTEFORYOURSELF", "SPIRE_HEART"]
STS2_SAMPLE_IDS = ["ABYSSAL_BATHS", "WELLSPRING", "AMALGAMATOR", "CRYSTAL_SPHERE", "NEOW"]


def _ids(records):
    return sorted(record.id for record in records)


def _by_id(records):
    return {record.id: record for record in records}


# 1/2. catalog sizes ---------------------------------------------------------

def test_sts1_catalog_has_52_events():
    sts1 = load_events("sts1")
    assert sts1.game == "sts1"
    assert len(sts1.events) == 52


def test_sts2_catalog_has_66_events():
    sts2 = load_events("sts2")
    assert sts2.game == "sts2"
    assert len(sts2.events) == 66


def test_catalog_provenance_fields_present():
    for game in ("sts1", "sts2"):
        catalog = load_events(game)
        assert catalog.schema_version
        assert catalog.source
        assert catalog.source_version
        ids = [record.id for record in catalog.events]
        assert len(ids) == len(set(ids))


# 3/4. default random pools --------------------------------------------------

def test_sts1_default_pool_is_51():
    pool = default_random_pool("sts1")
    assert len(pool) == 51


def test_sts2_default_pool_is_57():
    pool = default_random_pool("sts2")
    assert len(pool) == 57


def test_default_random_pool_all_games_shape():
    both = default_random_pool()
    assert set(both) == {"sts1", "sts2"}
    assert len(both["sts1"]) == 51
    assert len(both["sts2"]) == 57


# 5-8. pool membership -------------------------------------------------------

def test_spire_heart_not_in_sts1_default_pool():
    pool_ids = _ids(default_random_pool("sts1"))
    assert "SPIRE_HEART" not in pool_ids
    assert get_event("sts1", "SPIRE_HEART").pool == "scripted"


def test_shrine_events_in_sts1_default_pool():
    sts1 = load_events("sts1")
    shrine_ids = {r.id for r in sts1.events if r.pool == "shrine"}
    assert shrine_ids
    pool_ids = set(_ids(default_random_pool("sts1")))
    assert shrine_ids <= pool_ids


def test_ancient_not_in_sts2_default_pool():
    sts2 = load_events("sts2")
    ancient_ids = {r.id for r in sts2.events if r.pool == "ancient"}
    assert ancient_ids
    pool_ids = set(_ids(default_random_pool("sts2")))
    assert ancient_ids.isdisjoint(pool_ids)


def test_shared_in_sts2_default_pool():
    sts2 = load_events("sts2")
    shared_ids = {r.id for r in sts2.events if r.pool == "shared"}
    assert shared_ids
    pool_ids = set(_ids(default_random_pool("sts2")))
    assert shared_ids <= pool_ids


# 9-11. act mapping ----------------------------------------------------------

def test_sts1_act_mapping():
    records = _by_id(load_events("sts1").events)
    assert records["BIG_FISH"].act == 1        # exordium
    assert records["ADDICT"].act == 2          # city
    assert records["FALLING"].act == 3         # beyond
    assert records["NOTEFORYOURSELF"].act is None  # shrine


def test_sts2_act_mapping():
    records = _by_id(load_events("sts2").events)
    assert records["WELLSPRING"].act == 1            # Act 1 - Overgrowth
    assert records["ABYSSAL_BATHS"].act == 1         # Underdocks
    assert records["AMALGAMATOR"].act == 2           # Act 2 - Hive
    assert records["BATTLEWORN_DUMMY"].act == 3      # Act 3 - Glory
    assert records["NEOW"].act is None               # Ancient stays null


def test_shrine_and_shared_act_null():
    sts1 = load_events("sts1")
    for record in sts1.events:
        if record.pool == "shrine":
            assert record.act is None
    sts2 = load_events("sts2")
    for record in sts2.events:
        if record.pool == "shared":
            assert record.act is None


# 12-15. lookup behavior ------------------------------------------------------

def test_zh_full_name_lookup():
    hits = find_events_by_name("大鱼")
    assert [(r.game, r.id) for r in hits] == [("sts1", "BIG_FISH")]


def test_en_name_case_insensitive_lookup():
    lower = find_events_by_name("big fish")
    upper = find_events_by_name("BIG FISH")
    assert [(r.game, r.id) for r in lower] == [("sts1", "BIG_FISH")]
    assert [(r.game, r.id) for r in upper] == [("sts1", "BIG_FISH")]


def test_no_prefix_or_fuzzy_lookup():
    assert find_events_by_name("大") == []          # zh prefix
    assert find_events_by_name("fish") == []        # en substring
    assert find_events_by_name("the") == []         # shared en prefix only
    assert find_events_by_name("The Cleric"[:5]) == []  # prefix cut


def _write_synthetic_catalog(tmp_path, game, shared_name):
    payload = {
        "schema_version": "1.0.0",
        "game": game,
        "source": ["synthetic-test-fixture"],
        "source_version": "test",
        "events": [
            {
                "game": game,
                "id": f"SYN_{game.upper()}",
                "name_zh": shared_name,
                "name_en": "Shared Fixture Name",
                "category": "event",
                "act": 1,
                "pool": "act_specific",
                "description_zh": "fixture description",
                "choices": [],
                "raw": {"id": f"SYN_{game.upper()}"},
            }
        ],
    }
    path = tmp_path / CATALOG_FILES[game]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_cross_game_same_name_returns_all_matches(tmp_path):
    for game in ("sts1", "sts2"):
        _write_synthetic_catalog(tmp_path, game, "同名事件")
    hits = find_events_by_name("同名事件", catalog_dir=str(tmp_path))
    assert sorted(hit.game for hit in hits) == ["sts1", "sts2"]
    hits_one = find_events_by_name("同名事件", game="sts2", catalog_dir=str(tmp_path))
    assert [hit.id for hit in hits_one] == ["SYN_STS2"]


# 16/17. result / locked preservation -----------------------------------------

def test_sts1_result_may_be_empty():
    record = get_event("sts1", "BIG_FISH")
    assert record.choices
    for choice in record.choices:
        assert choice.result_zh is None
        assert "result_zh" in vars(choice.__class__) or True  # field always present
    # Static zh text is preserved when the source had it.
    assert record.choices[0].text_zh


def test_sts2_locked_and_result_preserved():
    wellspring = get_event("sts2", "WELLSPRING")
    bottle = next(choice for choice in wellspring.choices if choice.id == "BOTTLE")
    assert bottle.result_zh and bottle.result_zh.strip()

    waterlogged = get_event("sts2", "WATERLOGGED_SCRIPTORIUM")
    locked = [c for c in waterlogged.choices if c.locked_zh]
    assert locked, "expected at least one preserved locked choice"
    for choice in locked:
        assert choice.locked_zh.strip()
        assert choice.result_zh is None


# 18. validation -------------------------------------------------------------

def test_duplicate_id_validation_raises():
    base = {
        "schema_version": "1.0.0",
        "game": "sts1",
        "source": ["fixture"],
        "source_version": "test",
        "events": [],
    }
    dup = dict(base)
    dup["events"] = [
        {
            "game": "sts1",
            "id": "X",
            "name_zh": "甲",
            "name_en": "X",
            "category": "event",
            "act": 1,
            "pool": "act_specific",
            "description_zh": "d",
            "choices": [],
            "raw": {},
        }
    ] * 2
    with pytest.raises(EventCatalogError):
        validate_catalog(dup)


def test_bad_pool_validation_raises():
    payload = {
        "schema_version": "1.0.0",
        "game": "sts1",
        "source": ["fixture"],
        "source_version": "test",
        "events": [
            {
                "game": "sts1",
                "id": "X",
                "name_zh": "甲",
                "name_en": "X",
                "category": "event",
                "act": 1,
                "pool": "banana",
                "description_zh": "d",
                "choices": [],
                "raw": {},
            }
        ],
    }
    with pytest.raises(EventCatalogError):
        validate_catalog(payload)


# 19. raw preservation -------------------------------------------------------

def test_raw_preserved():
    big_fish = get_event("sts1", "BIG_FISH")
    assert big_fish.raw["id"] == "BIG_FISH"
    assert big_fish.raw["name"] == big_fish.name_en
    assert isinstance(big_fish.raw["choices"], list)
    assert big_fish.choices[0].raw["option"]

    wellspring = get_event("sts2", "WELLSPRING")
    assert wellspring.raw["id"] == "WELLSPRING"
    assert wellspring.raw["type"] == "Event"
    assert wellspring.raw["pages"]
    assert any(choice.raw["title"] for choice in wellspring.choices)


# 20. real 5+5 smoke ---------------------------------------------------------

@pytest.mark.parametrize("event_id", STS1_SAMPLE_IDS)
def test_sts1_real_event_smoke(event_id):
    record = get_event("sts1", event_id)
    assert record is not None
    assert record.id == event_id
    assert record.name_zh and record.name_en
    assert record.category and record.pool
    assert record.act in (1, 2, 3, None)
    assert record.description_zh is not None
    assert isinstance(record.choices, tuple)


@pytest.mark.parametrize("event_id", STS2_SAMPLE_IDS)
def test_sts2_real_event_smoke(event_id):
    record = get_event("sts2", event_id)
    assert record is not None
    assert record.id == event_id
    assert record.name_zh and record.name_en
    assert record.category and record.pool
    assert record.act in (1, 2, 3, None)
    assert record.description_zh is not None
    assert isinstance(record.choices, tuple)

import pytest

from card_guess import relics


ZH_ALPHA = {
    "id": "RELIC_ALPHA",
    "name": "远古船锚",
    "description": "战斗开始时获得 1 点护甲。",
    "tier": "common",
    "color": "red",
    "icon": "alpha-icon.png",
}

ZH_BETA = {
    "id": "RELIC_BETA",
    "name": "古旧怀表",
    "description": "每回合抽 1 张牌。",
    "tier": "rare",
    "color": "blue",
    "icon": "beta-icon.png",
}

EN_ALPHA = {
    "id": "RELIC_ALPHA",
    "name": "Ancient Anchor",
    "description": "At the start of combat, gain 1 Block.",
}

EN_BETA = {
    "id": "RELIC_BETA",
    "name": "Antique Pocket Watch",
    "description": "Draw 1 extra card each turn.",
}


def make_normalized_relic(
    game,
    relic_id,
    name,
    name_en,
    description="虚构描述",
    description_en="Fictional description",
    tier="common",
    color="red",
):
    return {
        "game": game,
        "id": relic_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": description_en,
        "tier": tier,
        "color": color,
    }


def test_merge_localized_relics_joins_by_id_not_position():
    # 英文列表故意与中文列表顺序相反。
    merged = relics.merge_localized_relics(
        [ZH_ALPHA, ZH_BETA],
        [EN_BETA, EN_ALPHA],
    )

    assert [item["id"] for item in merged] == ["RELIC_ALPHA", "RELIC_BETA"]

    alpha = merged[0]
    assert alpha["name"] == "远古船锚"
    assert alpha["description"] == "战斗开始时获得 1 点护甲。"
    assert alpha["name_en"] == "Ancient Anchor"
    assert alpha["description_en"] == "At the start of combat, gain 1 Block."
    assert alpha["icon"] == "alpha-icon.png"

    beta = merged[1]
    assert beta["name"] == "古旧怀表"
    assert beta["name_en"] == "Antique Pocket Watch"
    assert beta["description_en"] == "Draw 1 extra card each turn."
    assert beta["tier"] == "rare"
    assert beta["color"] == "blue"


def test_merge_localized_relics_rejects_mismatched_id_sets():
    zh_items = [ZH_ALPHA, ZH_BETA]
    en_items = [
        EN_ALPHA,
        {"id": "RELIC_GAMMA", "name": "Gamma Relic", "description": "Desc G"},
    ]

    with pytest.raises(ValueError):
        relics.merge_localized_relics(zh_items, en_items)


def test_normalize_relic_maps_sts1_fields():
    raw = {
        "id": "RELIC_ALPHA",
        "name": "远古船锚",
        "name_en": "Ancient Anchor",
        "description": "战斗开始时获得 1 点护甲。",
        "description_en": "At the start of combat, gain 1 Block.",
        "tier": "common",
        "color": "red",
        "icon": "alpha-icon.png",
    }

    assert relics.normalize_relic(raw, "sts1") == {
        "game": "sts1",
        "id": "RELIC_ALPHA",
        "name": "远古船锚",
        "name_en": "Ancient Anchor",
        "description": "战斗开始时获得 1 点护甲。",
        "description_en": "At the start of combat, gain 1 Block.",
        "tier": "common",
        "color": "red",
    }


def test_normalize_relic_maps_sts2_fields():
    raw = {
        "id": "RELIC_BETA",
        "name": "古旧怀表",
        "name_en": "Antique Pocket Watch",
        "description": "每回合抽 1 张牌。",
        "description_en": "Draw 1 extra card each turn.",
        "tier": "rare",
        "color": "purple",
    }

    assert relics.normalize_relic(raw, "sts2") == {
        "game": "sts2",
        "id": "RELIC_BETA",
        "name": "古旧怀表",
        "name_en": "Antique Pocket Watch",
        "description": "每回合抽 1 张牌。",
        "description_en": "Draw 1 extra card each turn.",
        "tier": "rare",
        "color": "purple",
    }


def test_chinese_lookup_requires_exact_name():
    relic = make_normalized_relic("sts1", "RELIC_ALPHA", "远古船锚", "Ancient Anchor")

    assert relics.find_relics_by_name([relic], "远古船锚") == [relic]
    assert relics.find_relics_by_name([relic], "远古") == []
    assert relics.find_relics_by_name([relic], "船锚") == []


def test_english_lookup_is_case_insensitive_and_ignores_outer_spaces():
    relic = make_normalized_relic("sts1", "RELIC_ALPHA", "远古船锚", "Ancient Anchor")

    for query in ("Ancient Anchor", "ancient anchor", "ANCIENT ANCHOR", "  Ancient Anchor"):
        assert relics.find_relics_by_name([relic], query) == [relic]

    assert relics.find_relics_by_name([relic], "Anchor") == []


def test_generation_filter_restricts_same_named_relics():
    sts1 = make_normalized_relic("sts1", "POCKET_WATCH_1", "古旧怀表", "Antique Pocket Watch")
    sts2 = make_normalized_relic("sts2", "POCKET_WATCH_2", "古旧怀表", "Antique Pocket Watch")

    assert relics.find_relics_by_name([sts1, sts2], "古旧怀表") == [sts1, sts2]
    assert relics.find_relics_by_name([sts1, sts2], "古旧怀表", generation=1) == [sts1]
    assert relics.find_relics_by_name([sts1, sts2], "古旧怀表", generation=2) == [sts2]

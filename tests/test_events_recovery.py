"""STS1 choice description_zh numeric/entity recovery tests.

Covers the pure recovery helper that fills static numbers/entities missing
from official Simplified Chinese event choice text using the paired English
raw token in the same catalog row.  All inputs are frozen catalog fixture
strings (real game localization used as static fixtures only, never QQ or
private user data).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from card_guess.events import get_event, load_events
from card_guess.events_recovery import recover_choice_description_zh


def _recover(zh, raw_option):
    return recover_choice_description_zh(zh, raw_option)


# Recovered rows: (description_zh, raw en option, expected description_zh)
RECOVERED_CASES = [
    # Fixed/small fixed reward entities verified against desktop-1.0.jar.
    (
        "获得一件特别遗物。 被诅咒——疼痛。",
        "[Rummage] Obtain a special Relic. Become Cursed - Pain.",
        "获得遗物「弯曲铁钳」。被诅咒——疼痛。",
    ),
    (
        "获得一件特殊遗物。",
        "[Ingest Mutagens] Obtain a special relic.",
        "获得遗物「突变之力」（已持有时获得「头环」）。",
    ),
    (
        "失去这件遗物。 获得一件特别的遗物。",
        "Exchange a Relic for a special reward.",
        "失去这件遗物。获得遗物「恩洛斯的礼物」（已持有时获得「头环」）。",
    ),
    (
        "失去所有金币。 获得遗物。",
        "[Offer: Gold] Lose all Gold. Obtain a Relic.",
        "失去所有金币。获得遗物「红面具」。",
    ),
    # BIG_FISH 香蕉 / 甜甜圈
    ("回复 生命。", "[Banana] Heal ⅓ Max HP.", "回复最大生命值的 1/3。"),
    ("最大生命值 + 。", "[Donut] Max HP +5.", "最大生命值 +5。"),
    # THE_CLERIC 治疗 / 净化
    ("35 金币 ： 回复 。", "[Heal] 35 Gold: Heal ⅓ Max HP.", "35 金币 ： 回复最大生命值的 1/3。"),
    ("金币 : 从你的牌组中 移除一张牌。", "[Purify] 50 Gold: Remove a card from your deck.", "50 金币 : 从你的牌组中 移除一张牌。"),
    # WORLD_OF_GOOP 收集金币
    ("获得 金币。 失去 生命。", "[Gather Gold] Gain 75 Gold. Take 11 damage.", "获得 75 金币。 失去 11 生命。"),
    # DESIGNER 小修一下 / 清洁一下 / 全套服务 / 一拳过去
    ("失去 金币。 升级一张牌。", "[Adjustments] Lose 40 Gold. Upgrade a card.", "失去 40 金币。 升级一张牌。"),
    ("失去 金币。 移除一张牌。", "[Clean Up] Lose 60 Gold. Remove a card.", "失去 60 金币。 移除一张牌。"),
    ("失去 金币。 移除一张牌，然后随机升级一张牌。", "[Full Service] Lose 90 Gold. Remove a card and upgrade a card.", "失去 90 金币。 移除一张牌，然后随机升级一张牌。"),
    ("失去 生命。", "[Punch] Lose 5 HP.", "失去 5 生命。"),
    # BEGGAR 给金币 / ADDICT 给他金币
    ("金币： 从你的牌组中移除一张牌。", "[Offer Gold] 75 Gold: Remove a card from your deck.", "75 金币： 从你的牌组中移除一张牌。"),
    ("金币： 获得一件遗物。", "[Offer Gold] 85 Gold: Obtain a Relic.", "85 金币： 获得一件遗物。"),
    # KNOWING_SKULL 财富？ / 我要怎么离开？
    ("获得 金币。 失去 生命。", "[Riches?] Gain 90 Gold. Lose HP.", "获得 90 金币。 失去 生命。"),
    ("失去 生命。", "[How do I leave?] Lose 6 HP.", "失去 6 生命。"),
    # LIARS_GAME 同意
    ("获得 金币。 被诅咒——疑虑。", "[Agree] Gain 150 Gold. Become Cursed - Doubt.", "获得 150 金币。 被诅咒——疑虑。"),
]


@pytest.mark.parametrize("zh,raw_en,expected", RECOVERED_CASES)
def test_recover_static_numbers(zh, raw_en, expected):
    assert _recover(zh, raw_en) == expected


# Already-complete zh text must be left byte-for-byte unchanged (returns None).
UNCHANGED_CASES = [
    ("获得一件遗物。 被诅咒——悔恨。", "[Box] Obtain a Relic. Become Cursed - Regret."),
    ("获得 275 金币。 被诅咒——悔恨。", "[Desecrate] Gain 275 Gold. Become Cursed - Regret."),
    ("失去 1 生命。", "[Continue] Lose 1 HP."),
    ("移除所有诅咒牌。", "[Drink] Remove all Curses from your deck."),
]


@pytest.mark.parametrize("zh,raw_en", UNCHANGED_CASES)
def test_complete_zh_unchanged(zh, raw_en):
    assert _recover(zh, raw_en) is None


# Rows that are NOT safe to recover stay unchanged (None), never index-mixed.
UNRESOLVED_CASES = [
    # zh/en rows misaligned at the archive source (NEST, THE_JOUST leftovers)
    ("获得 仪式匕首 。 失去 生命。", "[Smash and Grab] Gain 99 Gold. Obtain Ritual Dagger. Fight Nests."),
    ("赌 金币 —— 30%: 赢得 金币。", "[Bet on Murderer] 50 Gold: Win 250 Gold (risky)."),
    # official zh only exposes dynamic price/amount fragments
    ("金币 。", "[Buy 3 Potions] Lose 40 Gold. Obtain 3 Potions."),
    # dynamic / runtime-interpolated values must not be frozen
    ("移除所有 打击 牌。 获得5张 噬咬 牌。 失去 最大生命。", "[Accept] Remove all Strikes. Receive 5 Bites. Lose 30% Max HP."),
    ("从你的牌组中移除一张牌。 失去 生命。", "[Pray] Remove a card from your deck. Lose 25% HP."),
    ("随机升级 2 张牌。 失去 生命。", "[Enter] Upgrade 2 random cards. Take 20% Max HP damage."),
    ("在你的牌组中加入 2 张无色牌。 失去 点生命。", "[Recall (2)] Add 2 Colorless cards to your deck. Lose HP."),
    ("获得书。 失去 生命。", "[Take] Obtain the Book. Lose HP."),
    ("获得 ～ 金币。", "[Destroy] Gain 50-80 Gold."),
]


@pytest.mark.parametrize("zh,raw_en", UNRESOLVED_CASES)
def test_unresolved_rows_unchanged(zh, raw_en):
    assert _recover(zh, raw_en) is None


# The frozen catalog rows that recovery is allowed to touch, keyed by
# (event id, choice index) -> final description_zh.
PINNED_CATALOG_ROWS = {
    ("BIG_FISH", 0): "回复最大生命值的 1/3。",
    ("BIG_FISH", 1): "最大生命值 +5。",
    ("THE_CLERIC", 0): "35 金币 ： 回复最大生命值的 1/3。",
    ("THE_CLERIC", 1): "50 金币 : 从你的牌组中 移除一张牌。",
    ("WORLD_OF_GOOP", 0): "获得 75 金币。 失去 11 生命。",
    ("DESIGNER", 0): "失去 40 金币。 升级一张牌。",
    ("DESIGNER", 1): "失去 60 金币。 移除一张牌。",
    ("DESIGNER", 2): "失去 90 金币。 移除一张牌，然后随机升级一张牌。",
    ("DESIGNER", 3): "失去 5 生命。",
    ("BEGGAR", 0): "75 金币： 从你的牌组中移除一张牌。",
    ("ADDICT", 0): "85 金币： 获得一件遗物。",
    ("KNOWING_SKULL", 4): "获得 90 金币。 失去 生命。",
    ("KNOWING_SKULL", 5): "失去 6 生命。",
    ("LIARS_GAME", 0): "获得 150 金币。 被诅咒——疑虑。",
}


def test_frozen_catalog_rows_carry_pinned_final_text():
    for (event_id, index), expected in PINNED_CATALOG_ROWS.items():
        choice = get_event("sts1", event_id).choices[index]
        assert choice.description_zh == expected


# Full-catalog safety scan: the recovery helper must be idempotent over the
# frozen catalog (every safely recoverable hole is already filled; nothing
# else is ever modified by a later rebuild).
def test_full_catalog_scan_is_idempotent():
    payload = json.loads(Path("data/raw/sts1_events.json").read_text(encoding="utf-8"))
    touched = []
    for event in payload["events"]:
        for index, choice in enumerate(event["choices"]):
            raw_option = (choice.get("raw") or {}).get("option") or ""
            recovered = recover_choice_description_zh(choice.get("description_zh"), raw_option)
            if recovered is not None and recovered != choice.get("description_zh"):
                touched.append((event["id"], index))
    assert set(touched) == {
        ("ACCURSED_BLACKSMITH", 1),
        ("DRUG_DEALER", 2),
        ("FACETRADER", 0),
        ("FACETRADER", 3),
        ("MUSHROOMS", 1),
        ("N_LOTH", 0),
        ("FALLING", 0),
        ("FALLING", 1),
        ("FALLING", 2),
        ("THE_LIBRARY", 1),
        ("THE_MAUSOLEUM", 0),
        ("TOMB_OF_LORD_RED_MASK", 1),
        ("WEMEETAGAIN", 0),
        ("WEMEETAGAIN", 1),
        ("WEMEETAGAIN", 2),
        ("WORLD_OF_GOOP", 1),
        ("SCRAP_OOZE", 0),
    }


# Catalog reload must surface the final complete zh text to EventRecord.
def test_catalog_reload_has_final_complete_text():
    big_fish = get_event("sts1", "BIG_FISH")
    assert big_fish.choices[0].description_zh == "回复最大生命值的 1/3。"
    assert big_fish.choices[1].description_zh == "最大生命值 +5。"

    cleric = get_event("sts1", "THE_CLERIC")
    assert cleric.choices[0].description_zh == "35 金币 ： 回复最大生命值的 1/3。"
    assert cleric.choices[1].description_zh == "50 金币 : 从你的牌组中 移除一张牌。"

    goop = get_event("sts1", "WORLD_OF_GOOP")
    assert goop.choices[0].description_zh == "获得 75 金币。 失去 11 生命。"

    assert len(load_events("sts1").events) == 52


def test_player_facing_recovery_fixes_face_trader_and_mushrooms():
    face = get_event("sts1", "FACETRADER")
    rendered = " ".join(choice.description_zh or "" for choice in face.choices)
    assert "失去 金币" not in rendered
    assert "生命， 获得" not in rendered
    assert "最大生命值的10%" in rendered
    assert "50或75金币" in rendered
    assert "进入后续选择" in rendered

    mushrooms = get_event("sts1", "MUSHROOMS")
    eat = mushrooms.choices[1].description_zh
    assert "回复 点生命" not in eat
    assert "回复最大生命值的25%" in eat


def test_falling_runtime_card_names_degrade_to_card_types():
    falling = get_event("sts1", "FALLING")
    descriptions = [choice.description_zh for choice in falling.choices]
    assert descriptions == [
        "失去一张技能牌。",
        "失去一张能力牌。",
        "失去一张攻击牌。",
    ]


def test_recovery_preserves_original_raw_option():
    falling = get_event("sts1", "FALLING")
    assert falling.choices[0].raw["option"] == "[Land] Lose a Skill card."
    face = get_event("sts1", "FACETRADER")
    assert face.choices[0].raw["option"] == "[Touch] Lose Gold."


def test_remaining_sts1_fragments_are_safe_and_natural():
    assert get_event("sts1", "THE_LIBRARY").choices[1].description_zh == "回复最大生命值的 1/3。"
    assert get_event("sts1", "THE_MAUSOLEUM").choices[0].description_zh == "获得一件遗物。有50%几率被诅咒——苦恼。"
    assert get_event("sts1", "WEMEETAGAIN").choices[0].description_zh == "失去一瓶药水。获得一件遗物。"
    assert get_event("sts1", "WEMEETAGAIN").choices[1].description_zh == "失去金币。获得一件遗物。"
    assert get_event("sts1", "WEMEETAGAIN").choices[2].description_zh == "失去一张牌。获得一件遗物。"
    assert get_event("sts1", "WORLD_OF_GOOP").choices[1].description_zh == "失去部分金币。"
    assert get_event("sts1", "SCRAP_OOZE").choices[0].description_zh == "失去生命值，有机会找到一件遗物。"


def test_fixed_reward_entities_are_specific_in_player_facing_text():
    assert get_event("sts1", "ACCURSED_BLACKSMITH").choices[1].description_zh == (
        "获得遗物「弯曲铁钳」。被诅咒——疼痛。"
    )
    assert get_event("sts1", "DRUG_DEALER").choices[2].description_zh == (
        "获得遗物「突变之力」（已持有时获得「头环」）。"
    )
    assert get_event("sts1", "N_LOTH").choices[0].description_zh == (
        "失去这件遗物。获得遗物「恩洛斯的礼物」（已持有时获得「头环」）。"
    )
    assert get_event("sts1", "TOMB_OF_LORD_RED_MASK").choices[1].description_zh == (
        "失去所有金币。获得遗物「红面具」。"
    )


def test_random_and_runtime_reward_categories_remain_unexpanded():
    expected = {
        ("ADDICT", 0): "85 金币： 获得一件遗物。",
        ("ADDICT", 1): "获得一件遗物。 被诅咒——羞耻。",
        ("BIG_FISH", 2): "获得一件遗物。 被诅咒——悔恨。",
        ("BONFIRE_ELEMENTALS", 2): "根据献上的贡品获得相应的奖励。 选择一张牌献上。",
        ("LAB", 0): "找到一些药水！",
        ("NOTEFORYOURSELF", 1): "获得 然后存放一张牌。",
        ("THE_MAUSOLEUM", 0): "获得一件遗物。有50%几率被诅咒——苦恼。",
    }

    for (event_id, index), description in expected.items():
        assert get_event("sts1", event_id).choices[index].description_zh == description


def test_fixed_reward_recovery_preserves_raw_source_text():
    expected = {
        ("ACCURSED_BLACKSMITH", 1): (
            "[Rummage] Obtain a special Relic. Become Cursed - Pain."
        ),
        ("DRUG_DEALER", 2): "[Ingest Mutagens] Obtain a special relic.",
        ("N_LOTH", 0): "Exchange a Relic for a special reward.",
        ("TOMB_OF_LORD_RED_MASK", 1): (
            "[Offer: Gold] Lose all Gold. Obtain a Relic."
        ),
    }

    for (event_id, index), raw_option in expected.items():
        assert get_event("sts1", event_id).choices[index].raw["option"] == raw_option


def test_sts2_choice_descriptions_bypass_sts1_recovery():
    payload = json.loads(Path("data/raw/sts2_events.json").read_text(encoding="utf-8"))
    raw_by_id = {event["id"]: event for event in payload["events"]}

    for event in load_events("sts2").events:
        raw_event = raw_by_id[event.id]
        assert [choice.description_zh for choice in event.choices] == [
            choice["description_zh"] for choice in raw_event["choices"]
        ]

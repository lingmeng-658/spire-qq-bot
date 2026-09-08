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
    ("回复 点生命。", "[Sleep] Heal ⅓ Max HP."),
    # dynamic / runtime-interpolated values must not be frozen
    ("移除所有 打击 牌。 获得5张 噬咬 牌。 失去 最大生命。", "[Accept] Remove all Strikes. Receive 5 Bites. Lose 30% Max HP."),
    ("从你的牌组中移除一张牌。 失去 生命。", "[Pray] Remove a card from your deck. Lose 25% HP."),
    ("随机升级 2 张牌。 失去 生命。", "[Enter] Upgrade 2 random cards. Take 20% Max HP damage."),
    ("获得一件遗物。 %: 被诅咒——苦恼。", "[Open Coffin] Obtain a Relic. 50%: Become Cursed - Writhe."),
    ("失去 生命。 %: 找到一件遗物。", "[Reach Inside] Take damage. Chance to find a Relic."),
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
    assert touched == []


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

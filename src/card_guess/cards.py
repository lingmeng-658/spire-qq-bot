import json
import re
import unicodedata
from collections import Counter

STANDARD_POOLS = {
    "ironclad",
    "silent",
    "defect",
    "watcher",
    "necrobinder",
    "regent",
    "colorless",
    "curse",
    "status",
    "event",
}

def load_raw_cards(game):
    with open(f"data/raw/{game}_cards.json", "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_card(card, game):
    return {
        "game": game,
        "id": card["id"],
        "name": card["name"],
        "pool": card["color"],
        "type": card["type"],
        "rarity": card["rarity"],
        "cost": card["cost"],
        "description": card["description"],
        "image_url": card.get("image_url"),
        "vars": card.get("vars", {}),
        "star_cost": card.get("star_cost"),
        "exhaust": card.get("exhaust", False),
        "ethereal": card.get("ethereal", False),
        "innate": card.get("innate", False),
        "retain": card.get("retain", False),
        "self_retain": card.get("self_retain", False),
        "upgrade": card.get("upgrade", {}),
        "keywords": list(card.get("keywords", [])),
        "tags": list(card.get("tags", [])),
    }


TRAIT_PRIORITY = [
    "固有",
    "消耗",
    "保留",
    "虚无",
    "潜行",
    "永恒",
    "不能被打出",
]

TRAIT_MAP = {
    "exhaust": "消耗",
    "ethereal": "虚无",
    "innate": "固有",
    "retain": "保留",
    "self_retain": "保留",
    "Sly": "潜行",
    "Eternal": "永恒",
    "Unplayable": "不能被打出",
    "Exhaust": "消耗",
    "Ethereal": "虚无",
    "Innate": "固有",
    "Retain": "保留",
    "SelfRetain": "保留",
}

STS1_OVERRIDE = {
    "AFTER_IMAGE": {"固有": "upgrade"},
    "CHILL": {"固有": "upgrade"},
    "BATTLE_HYMN": {"固有": "upgrade"},
    "WORSHIP": {"保留": "upgrade"},
    "BLASPHEMY": {"保留": "base"},
    "ADRENALINE": {"消耗": "base"},
}


def _normalize_trait_text(value):
    if value is None:
        return ""
    return str(value).replace("\n", "").replace(" ", "")


def _trait_in_text(text, trait):
    if not trait:
        return False
    return trait in _normalize_trait_text(text)


def _card_trait_flags(card):
    if not isinstance(card, dict):
        return {}

    flags = {}
    if card.get("exhaust"):
        flags["消耗"] = True
    if card.get("ethereal"):
        flags["虚无"] = True
    if card.get("innate"):
        flags["固有"] = True
    if card.get("retain") or card.get("self_retain"):
        flags["保留"] = True
    return flags


def _sts1_visible_traits(card, upgraded=False):
    if not isinstance(card, dict):
        return []

    description = str(card.get("description") or "")
    upgrade = card.get("upgrade") or {}
    upgrade_description = str(upgrade.get("description") or "")
    card_id = str(card.get("id") or "")
    flags = _card_trait_flags(card)

    base_traits = []
    upgrade_traits = []
    seen = set()

    for trait in TRAIT_PRIORITY:
        if trait in ["固有", "消耗", "保留", "虚无"]:
            override = STS1_OVERRIDE.get(card_id, {}).get(trait)
            if override == "base":
                if trait not in seen:
                    base_traits.append(trait)
                    seen.add(trait)
                continue
            if override == "upgrade":
                if trait not in seen:
                    upgrade_traits.append(trait)
                    seen.add(trait)
                continue

            if _trait_in_text(description, trait):
                if trait not in seen:
                    base_traits.append(trait)
                    seen.add(trait)
            elif _trait_in_text(upgrade_description, trait):
                if trait not in seen:
                    upgrade_traits.append(trait)
                    seen.add(trait)
            elif flags.get(trait):
                if trait not in seen:
                    base_traits.append(trait)
                    seen.add(trait)

    combined = list(base_traits) + [trait for trait in upgrade_traits if trait not in base_traits]
    if upgraded:
        return [trait for trait in TRAIT_PRIORITY if trait in combined]
    return base_traits


def _sts2_visible_traits(card, upgraded=False):
    if not isinstance(card, dict):
        return []

    normalized = []
    keywords = card.get("keywords", [])
    upgrade = card.get("upgrade") or {}

    for keyword in keywords:
        trait = TRAIT_MAP.get(keyword)
        if trait is not None and trait not in normalized:
            normalized.append(trait)

    if not upgraded:
        return [trait for trait in TRAIT_PRIORITY if trait in normalized]

    add_keywords = upgrade.get("add_keywords", []) if isinstance(upgrade, dict) else []
    remove_keywords = upgrade.get("remove_keywords", []) if isinstance(upgrade, dict) else []
    final = list(normalized)

    for keyword in add_keywords:
        trait = TRAIT_MAP.get(keyword)
        if trait is not None and trait not in final:
            final.append(trait)

    for keyword in remove_keywords:
        trait = TRAIT_MAP.get(keyword)
        if trait in final:
            final.remove(trait)

    return [trait for trait in TRAIT_PRIORITY if trait in final]


def get_visible_traits(card, upgraded=False):
    if not isinstance(card, dict):
        return []

    if card.get("game") == "sts1" or card.get("id") in STS1_OVERRIDE or any(
        key in card for key in ("exhaust", "ethereal", "innate", "retain", "self_retain")
    ):
        return _sts1_visible_traits(card, upgraded=upgraded)

    if card.get("game") == "sts2" or "keywords" in card or (
        isinstance(card.get("upgrade"), dict)
        and (
            "add_keywords" in card.get("upgrade", {})
            or "remove_keywords" in card.get("upgrade", {})
        )
    ):
        return _sts2_visible_traits(card, upgraded=upgraded)

    description = str(card.get("description") or "")
    upgrade_description = str((card.get("upgrade") or {}).get("description") or "")

    traits = []
    for trait in TRAIT_PRIORITY:
        if _trait_in_text(description, trait) or _trait_in_text(upgrade_description, trait):
            if trait not in traits:
                traits.append(trait)
    return traits


def load_cards(game):
    raw_cards = load_raw_cards(game)
    return [normalize_card(card, game) for card in raw_cards]


def find_cards_by_exact_name(cards, name):
    return [
        card
        for card in cards
        if isinstance(card, dict) and card.get("name") == name
    ]


def format_cost(card):
    if card["cost"] == -1:
        return "X"
    elif card["cost"] == -2:
        return "-"
    elif card["cost"] is None:
        return "-"
    elif card["cost"] >= 3:
        return "3+"
    else:
        return str(card["cost"])

def format_star_cost(card):
    star_cost = card["star_cost"]

    if star_cost is None:
        return None

    return f"{star_cost}⭐"

def render_sts1_energy(description):
    pattern = r"(?:\[(?:R|G|B|W)\]\s*)+"

    def replace_energy(match):
        symbols = re.findall(r"\[(?:R|G|B|W)\]", match.group())
        return "⚡" * len(symbols)

    return re.sub(pattern, replace_energy, description)


def _apply_token_replacements(description, card):
    if not isinstance(card, dict):
        return str(description or "")

    text = str(description or "")
    if card.get("game") == "sts1":
        text = re.sub(r"\[(?:R|G|B|W)\]", "⚡", text)
        return text

    if card.get("game") == "sts2":
        energy = card.get("vars", {}).get("energy")
        if energy is not None:
            text = re.sub(r"\[E\]", "⚡" * energy, text)
        else:
            text = text.replace("[E]", "⚡")

        stars = card.get("vars", {}).get("stars_var")
        if stars is not None:
            text = re.sub(r"\[S\]", "⭐" * stars, text)
        else:
            text = text.replace("[S]", "⭐")

    return text


def build_display_description(card, upgraded=False):
    if not isinstance(card, dict):
        return ""

    description = _apply_token_replacements(card.get("description") or "", card)
    visible_traits = get_visible_traits(card, upgraded=upgraded)
    if not visible_traits and not description:
        return ""

    prefix_traits = []
    suffix_traits = []
    if card.get("game") == "sts1":
        prefix_order = ["固有", "保留", "虚无", "不能被打出"]
        suffix_order = ["消耗"]
    elif card.get("game") == "sts2":
        prefix_order = ["固有", "保留", "虚无", "不能被打出"]
        suffix_order = ["消耗", "潜行", "永恒"]
    else:
        prefix_order = []
        suffix_order = []

    for trait in prefix_order:
        if trait in visible_traits and not _trait_in_text(description, trait):
            prefix_traits.append(f"{trait}。")

    for trait in suffix_order:
        if trait in visible_traits and not _trait_in_text(description, trait):
            suffix_traits.append(f"{trait}。")

    parts = prefix_traits + ([description] if description else []) + suffix_traits
    return "\n".join(part for part in parts if part)


def render_description(card):
    if not isinstance(card, dict):
        return ""
    return build_display_description(card, upgraded=bool(card.get("upgraded", False)))


def is_standard_card(card):
    return card["pool"] in STANDARD_POOLS and card["description"].strip()

def load_standard_cards(game):
    cards = load_cards(game)
    return [card for card in cards if is_standard_card(card)]

def load_game_cards(mode):
    if mode == "sts1":
        return load_standard_cards("sts1")

    if mode == "sts2":
        return load_standard_cards("sts2")

    if mode == "mixed":
        return (
            load_standard_cards("sts1")
            + load_standard_cards("sts2")
        )

    raise ValueError(f"未知模式: {mode}")


if __name__ == "__main__":
    sts1_cards = load_game_cards("sts1")
    sts2_cards = load_game_cards("sts2")
    mixed_cards = load_game_cards("mixed")

    print("STS1 Standard Cards:", len(sts1_cards))
    print("STS2 Standard Cards:", len(sts2_cards))
    print("Mixed Cards:", len(mixed_cards))

    print(sts1_cards[0])
    print(sts2_cards[0])

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
    }

def load_cards(game):
    raw_cards = load_raw_cards(game)
    return [normalize_card(card, game) for card in raw_cards]


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


def render_description(card):
    description = card["description"]

    if card.get("game") == "sts1":
        description = render_sts1_energy(description)

    elif card.get("game") == "sts2":
        energy = card["vars"].get("energy")

        if energy is not None:
            description = description.replace("[E]", "⚡" * energy)
        else:
            description = description.replace("[E]", "⚡")

        stars = card["vars"].get("stars_var")

        if stars is not None:
            description = description.replace("[S]", "⭐" * stars)
        else:
            description = description.replace("[S]", "⭐")

    return description


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

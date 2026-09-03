import json


def load_raw_relics(game):
    with open(f"data/raw/{game}_relics.json", "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_relic(relic, game):
    return {
        "game": game,
        "id": relic["id"],
        "name": relic["name"],
        "name_en": relic["name_en"],
        "description": relic["description"],
        "description_en": relic["description_en"],
        "tier": relic.get("tier"),
        "color": relic.get("color"),
    }


def load_relics(game):
    raw_relics = load_raw_relics(game)
    return [normalize_relic(relic, game) for relic in raw_relics]


def merge_localized_relics(zh_items, en_items):
    zh_ids = {item["id"] for item in zh_items}
    en_ids = {item["id"] for item in en_items}

    if zh_ids != en_ids:
        raise ValueError(
            "zh/en relic id 集合不一致: "
            f"en 有而 zh 没有: {sorted(en_ids - zh_ids)}; "
            f"zh 有而 en 没有: {sorted(zh_ids - en_ids)}"
        )

    en_by_id = {item["id"]: item for item in en_items}

    merged = []
    for zh_item in zh_items:
        record = dict(zh_item)
        en_item = en_by_id[record["id"]]
        record["name_en"] = en_item["name"]
        record["description_en"] = en_item["description"]
        merged.append(record)

    return merged


def find_relics_by_name(relics, name, generation=None):
    if generation is None:
        target_game = None
    else:
        target_game = f"sts{generation}"

    normalized_query = name.strip().casefold()

    matches = []
    for relic in relics:
        if target_game is not None and relic.get("game") != target_game:
            continue

        if relic.get("name") == name:
            matches.append(relic)
            continue

        name_en = relic.get("name_en")
        if name_en and name_en.strip().casefold() == normalized_query:
            matches.append(relic)

    return matches

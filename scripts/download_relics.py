import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.relics import merge_localized_relics


API_URL = "https://spire-archive.com/api/{game}/relics"
PAGE_LIMIT = 400


def fetch_relics_page(game, lang, offset, fetcher):
    return fetcher(
        API_URL.format(game=game),
        params={"lang": lang, "limit": PAGE_LIMIT, "offset": offset},
    )


def fetch_all_relics(game, lang, fetcher):
    all_items = []
    offset = 0

    while True:
        data = fetch_relics_page(game, lang, offset, fetcher).json()
        page = data.get("items", [])
        all_items.extend(page)

        if not page or len(all_items) >= data.get("total", len(all_items)):
            break

        offset += len(page)

    return all_items


def download_relics(game, fetcher=requests.get, output_dir="data/raw"):
    zh_items = fetch_all_relics(game, "zh", fetcher)
    en_items = fetch_all_relics(game, "en", fetcher)
    merged = merge_localized_relics(zh_items, en_items)

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{game}_relics.json")
    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(merged, output_file, ensure_ascii=False, indent=4)

    return merged


def main():
    for game in ("sts1", "sts2"):
        merged = download_relics(game)
        has_zh_name = all(bool(item.get("name")) for item in merged)
        has_en_name = all(bool(item.get("name_en")) for item in merged)
        print(
            f"{game}: {len(merged)} relics, "
            f"zh_name={has_zh_name}, en_name={has_en_name}"
        )


if __name__ == "__main__":
    main()

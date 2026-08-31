from __future__ import annotations

import json
from pathlib import Path
from urllib import request

CARD_GAMES = ("sts1", "sts2")
PUBLIC_IMAGE_BASE = "https://www.spirecodex.com/images/cards"


def stable_card_id(card):
    for key in ("id", "slug", "key"):
        value = card.get(key)
        if value:
            return str(value).strip()

    name = str(card.get("name", "")).strip()
    if name:
        return name

    raise ValueError(f"卡牌缺少稳定标识: {card}")


def build_image_url(card):
    if card.get("image_url"):
        image_url = str(card["image_url"]).strip()
        if image_url.startswith("http://") or image_url.startswith("https://"):
            return image_url

    card_id = stable_card_id(card)
    return f"{PUBLIC_IMAGE_BASE}/{card_id}.webp"


def determine_local_output_path(output_root, card):
    game = str(card.get("game") or "unknown")
    card_id = stable_card_id(card)
    return Path(output_root) / game / f"{card_id}.webp"


def load_cards_by_game(base_dir=None):
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[1]

    cards_by_game = {}
    for game in CARD_GAMES:
        raw_path = Path(base_dir) / "data" / "raw" / f"{game}_cards.json"
        if not raw_path.exists():
            cards_by_game[game] = []
            continue

        with raw_path.open("r", encoding="utf-8") as handle:
            raw_cards = json.load(handle)

        normalized = []
        for card in raw_cards:
            if not isinstance(card, dict):
                continue
            card_copy = dict(card)
            card_copy["game"] = game
            normalized.append(card_copy)
        cards_by_game[game] = normalized

    return cards_by_game


def fetch_url_bytes(url):
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=30) as response:
        return response.read()


def download_card_images(cards_by_game=None, output_root=None, fetcher=None):
    if cards_by_game is None:
        cards_by_game = load_cards_by_game()

    if output_root is None:
        output_root = Path(__file__).resolve().parents[1] / "data" / "images"
    else:
        output_root = Path(output_root)

    if fetcher is None:
        fetcher = fetch_url_bytes

    summary = {
        "total": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "failed_cards": [],
    }

    for game in CARD_GAMES:
        for card in cards_by_game.get(game, []):
            summary["total"] += 1
            card_id = stable_card_id(card)
            dest_path = determine_local_output_path(output_root, card)

            if dest_path.exists():
                summary["skipped"] += 1
                continue

            try:
                payload = fetcher(build_image_url(card))
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(payload)
                summary["success"] += 1
            except Exception:
                summary["failed"] += 1
                summary["failed_cards"].append(f"{game}:{card_id}")

    return summary


def main():
    cards_by_game = load_cards_by_game()
    summary = download_card_images(cards_by_game)

    print(f"总卡数: {summary['total']}")
    print(f"成功下载: {summary['success']}")
    print(f"已存在跳过: {summary['skipped']}")
    print(f"失败数量: {summary['failed']}")
    if summary["failed_cards"]:
        print("失败卡牌标识: " + ", ".join(summary["failed_cards"]))
    else:
        print("失败卡牌标识: 无")


if __name__ == "__main__":
    main()

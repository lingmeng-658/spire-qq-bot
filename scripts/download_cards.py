import json
import requests

def download_cards(game):
    all_cards = []
    offset = 0
    url = f"https://spire-archive.com/api/{game}/cards"

    while True:
        response = requests.get(
            url,
            params={
                "lang": "zh",
                "limit": 400,
                "offset": offset,
            },
        )

        data = response.json()
        all_cards.extend(data["items"])

        if len(all_cards) >= data["total"]:
            break

        offset += len(data["items"])

    with open(f"data/raw/{game}_cards.json", "w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=4)

def main():
    download_cards("sts1")
    download_cards("sts2")

if __name__ == "__main__":
    main()

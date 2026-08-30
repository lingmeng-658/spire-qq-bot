import json
from pathlib import Path


def load_cards(game):
    with open(f"data/raw/{game}_cards.json", "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    sts1_cards = load_cards("sts1")
    sts2_cards = load_cards("sts2")

    sts1_by_name = {card["name"]: card for card in sts1_cards}
    sts2_by_name = {card["name"]: card for card in sts2_cards}

    duplicate_names = sorted(set(sts1_by_name) & set(sts2_by_name))

    lines = [
        "# STS1 / STS2 同名卡审计",
        "",
        f"- STS1 卡牌数：{len(sts1_cards)}",
        f"- STS2 卡牌数：{len(sts2_cards)}",
        f"- 同名卡数量：{len(duplicate_names)}",
        "",
    ]

    for name in duplicate_names:
        card1 = sts1_by_name[name]
        card2 = sts2_by_name[name]

        lines.extend([
            f"## {name}",
            "",
            "### STS1",
            f"- pool: `{card1['color']}`",
            f"- type: `{card1['type']}`",
            f"- rarity: `{card1['rarity']}`",
            f"- cost: `{card1['cost']}`",
            f"- description: {card1['description']}",
            "",
            "### STS2",
            f"- pool: `{card2['color']}`",
            f"- type: `{card2['type']}`",
            f"- rarity: `{card2['rarity']}`",
            f"- cost: `{card2['cost']}`",
            f"- description: {card2['description']}",
            "",
        ])

    output_path = Path("data/duplicate_cards_report.md")
    output_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"报告已生成：{output_path}")
    print(f"同名卡数量：{len(duplicate_names)}")


if __name__ == "__main__":
    main()
from card_guess.cards import load_game_cards, render_description


def find_card_name_conflicts(cards):
    card_names = {card["name"] for card in cards}
    conflicts = []

    for answer_card in cards:
        description = render_description(answer_card)

        for card_name in card_names:
            if card_name in description:
                conflicts.append({
                    "answer_name": answer_card["name"],
                    "answer_game": answer_card["game"],
                    "matched_name": card_name,
                    "is_self": card_name == answer_card["name"],
                    "description": description,
                })

    return conflicts


def print_report(title, cards):
    conflicts = find_card_name_conflicts(cards)

    self_conflicts = [
        conflict
        for conflict in conflicts
        if conflict["is_self"]
    ]

    other_conflicts = [
        conflict
        for conflict in conflicts
        if not conflict["is_self"]
    ]

    print()
    print("=" * 60)
    print(title)
    print("=" * 60)
    print(f"卡牌数量：{len(cards)}")
    print(f"全部冲突：{len(conflicts)}")
    print(f"描述包含自己的卡名：{len(self_conflicts)}")
    print(f"描述包含其他真实卡名：{len(other_conflicts)}")

    print()
    print("--- 描述包含自己的卡名 ---")

    for conflict in self_conflicts:
        print(
            f"[{conflict['answer_game']}] "
            f"{conflict['answer_name']} -> "
            f"{conflict['matched_name']}"
        )
        print(f"  {conflict['description']}")

    print()
    print("--- 描述包含其他真实卡名 ---")

    for conflict in other_conflicts:
        print(
            f"[{conflict['answer_game']}] "
            f"{conflict['answer_name']} -> "
            f"{conflict['matched_name']}"
        )
        print(f"  {conflict['description']}")


def main():
    sts1_cards = load_game_cards("sts1")
    sts2_cards = load_game_cards("sts2")
    mixed_cards = load_game_cards("mixed")

    print_report("STS1", sts1_cards)
    print_report("STS2", sts2_cards)
    print_report("MIXED", mixed_cards)


if __name__ == "__main__":
    main()
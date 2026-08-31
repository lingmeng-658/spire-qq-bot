from card_guess import cards


def make_card(name, game, card_id):
    return {
        "name": name,
        "game": game,
        "id": card_id,
    }


def test_find_cards_by_exact_name_returns_every_match_in_input_order():
    first = make_card("打击", "sts1", "STRIKE_RED")
    unrelated = make_card("打击波", "sts1", "POMMEL_STRIKE")
    second = make_card("打击", "sts2", "STRIKE_IRONCLAD")

    matches = cards.find_cards_by_exact_name(
        [first, unrelated, second],
        "打击",
    )

    assert matches == [first, second]


def test_find_cards_by_exact_name_does_not_match_name_fragments():
    card = make_card("机械降神", "sts1", "MACHINE_LEARNING")

    matches = cards.find_cards_by_exact_name([card], "机械")

    assert matches == []

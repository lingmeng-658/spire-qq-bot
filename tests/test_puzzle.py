from card_guess.puzzle import (
    find_opening_reveal_positions,
    mask_description,
)


def test_x_is_visible_in_masked_description():
    description = "造成X点伤害。"

    masked = mask_description(description)

    assert masked == "□□X□□□。"

def test_opening_reveals_unplayable_phrase():
    description = "不能被打出。\n当你抽到这张牌时，在你的手牌中加入2张奇迹，然后消耗。"

    positions = find_opening_reveal_positions(description)
    masked = mask_description(description, positions)

    assert masked.startswith("不能被打出。")
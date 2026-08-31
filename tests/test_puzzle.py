import pytest

from card_guess.puzzle import (
    find_opening_reveal_positions,
    format_rarity,
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


@pytest.mark.parametrize(
    ("rarity", "expected"),
    [
        ("Basic", "基础"),
        ("Common", "普通"),
        ("Uncommon", "罕见"),
        ("Rare", "稀有"),
        ("Curse", "诅咒"),
        ("Special", "特殊"),
        ("Ancient", "先古"),
        ("Event", "事件"),
        ("Quest", "任务"),
        ("Status", "状态"),
        ("Token", "衍生"),
    ],
)
def test_format_rarity_translates_real_values_without_mutating_card(rarity, expected):
    card = {"rarity": rarity}

    assert format_rarity(card) == expected
    assert card == {"rarity": rarity}

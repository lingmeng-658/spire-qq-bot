import random

from card_guess.cards import build_display_description, get_visible_traits, render_description
from card_guess.game import GameState, get_hint_type


def make_test_card():
    return {
        "game": "sts1",
        "id": "test_card",
        "name": "测试卡",
        "pool": "ironclad",
        "type": "Attack",
        "rarity": "Common",
        "cost": 1,
        "description": "造成18点伤害。",
        "image_url": None,
        "vars": {},
        "star_cost": None,
    }


def test_correct_card_name_wins():
    card = {"name": "杂技"}
    game = GameState(card)

    result = game.handle_input("杂技")

    assert result.status == "correct"
    assert game.ended is True


def test_wrong_card_name_counts_as_wrong():
    card = {"name": "杂技"}
    game = GameState(card)

    result = game.handle_input("精准")

    assert result.status == "wrong"
    assert game.wrong_count == 1


def test_build_display_description_merges_trait_lines_for_sts1():
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "造成8点伤害。",
        "innate": True,
        "exhaust": True,
    }

    result = build_display_description(card)

    assert "固有。" in result
    assert "造成8点伤害。" in result
    assert "消耗。" in result
    assert result.index("固有。") < result.index("造成8点伤害。") < result.index("消耗。")


def test_trait_name_is_matched_as_description_text():
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "造成8点伤害。",
        "exhaust": True,
    }
    game = GameState(card)

    result = game.handle_input("消耗")

    assert result.status == "revealed"
    assert result.reveal_target == "description"


def test_energy_token_replacements_are_idempotent_in_mixed_text():
    card = {"game": "sts2", "vars": {}, "description": "[E][E]"}

    assert render_description({**card, "description": "[E]"}) == "⚡"
    assert render_description({**card, "description": "[E][E]"}) == "⚡⚡"
    assert render_description({**card, "description": "⚡[E]"}) == "⚡⚡"
    assert render_description({**card, "description": "⚡"}) == "⚡"
    assert render_description({**card, "description": "获得⚡，然后获得[E]"}) == "获得⚡，然后获得⚡"


def test_display_description_orders_sts1_traits_before_and_after_text():
    card = {
        "game": "sts1",
        "id": "test_trait_card",
        "name": "测试卡",
        "description": "造成8点伤害。",
        "innate": True,
        "exhaust": True,
    }

    display = build_display_description(card)

    assert "固有。" in display
    assert "造成8点伤害。" in display
    assert "消耗。" in display
    assert display.index("固有。") < display.index("造成8点伤害。") < display.index("消耗。")


def test_display_description_respects_upgraded_trait_special_cases():
    after_image = {
        "game": "sts1",
        "id": "AFTER_IMAGE",
        "description": "造成8点伤害。",
        "upgrade": {"description": "固有。"},
    }
    worship = {
        "game": "sts1",
        "id": "WORSHIP",
        "description": "造成8点伤害。",
        "upgrade": {"description": "保留。"},
    }

    assert "固有。" not in build_display_description(after_image, upgraded=False)
    assert "固有。" in build_display_description(after_image, upgraded=True)
    assert "保留。" not in build_display_description(worship, upgraded=False)
    assert "保留。" in build_display_description(worship, upgraded=True)


def test_get_hint_type_schedule():
    assert get_hint_type(3) == "rarity"
    assert get_hint_type(4) is None
    assert get_hint_type(6) == "description"
    assert get_hint_type(9) == "description"
    assert get_hint_type(10) == "name"
    assert get_hint_type(11) is None
    assert get_hint_type(12) == "description"
    assert get_hint_type(14) == "name"
    assert get_hint_type(16) == "description"
    assert get_hint_type(18) == "name"
    assert get_hint_type(20) == "description"


def test_hint_schedule_has_no_four_step_rule():
    game = GameState({"name": "杂技"})

    for _ in range(3):
        game.handle_input("A")
    assert game.should_hint() is True
    assert game.rarity_revealed is True

    game = GameState({"name": "杂技"})
    for _ in range(4):
        game.handle_input("A")
    assert game.should_hint() is False


def test_end_game_returns_answer():
    card = {"name": "杂技"}
    game = GameState(card)

    answer = game.end()

    assert answer == "杂技"
    assert game.ended is True


def test_guess_description_phrase_reveals_matching_text():
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "造成18点伤害。",
    }

    game = GameState(card)

    result = game.guess_description_phrase("伤害")

    assert result.status == "revealed"
    assert result.revealed_count == 2
    assert game.revealed_positions == {5, 6}
    assert game.wrong_count == 0


def test_description_hint_ignores_already_revealed_tokens():
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "造成2点伤害。",
    }
    game = GameState(card)
    description = "造成2点伤害。"
    game.revealed_positions.update({i for i, _ in enumerate(description)})

    result = game.description_hint()

    assert result is None


def test_description_hint_prefers_tokens_that_reveal_two_or_more_chars(monkeypatch):
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "造成2点伤害。造成2点伤害。",
    }
    game = GameState(card)

    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    result = game.description_hint()

    assert result is not None
    assert result["kind"] == "description"
    assert result["revealed_count"] >= 2


def test_description_hint_can_fall_back_to_single_char_when_needed(monkeypatch):
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "A B C D",
    }
    game = GameState(card)
    game.revealed_positions = set(range(len(card["description"])))
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    result = game.description_hint()

    assert result is None


def test_name_hint_reveals_only_unrevealed_chars_and_avoids_duplicates(monkeypatch):
    card = {"game": "sts1", "name": "ABCD", "description": "造成伤害。"}
    game = GameState(card)
    game.revealed_name_positions = {0}
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])

    result = game.name_hint()

    assert result is not None
    assert result["kind"] == "name"
    assert result["revealed_count"] == 1
    assert 0 in game.revealed_name_positions
    assert 1 in game.revealed_name_positions or 2 in game.revealed_name_positions or 3 in game.revealed_name_positions


def test_name_hint_falls_back_to_description_when_too_few_chars_remain():
    card = {"game": "sts1", "name": "AB", "description": "造成伤害。"}
    game = GameState(card)
    game.revealed_name_positions = {0}

    result = game.name_hint()

    assert result is None


def test_fallback_to_name_when_description_has_no_candidate():
    card = {"game": "sts1", "name": "ABCD", "description": "X"}
    game = GameState(card)
    game.revealed_positions = {0, 1, 2, 3, 4}
    game.revealed_name_positions = {0, 1}

    result = game._apply_automatic_hint_for_count(10)

    assert result == "name"


def test_no_hint_when_no_reasonable_candidate_exists():
    card = {"game": "sts1", "name": "A", "description": "X"}
    game = GameState(card)
    game.revealed_name_positions = {0}
    game.revealed_positions = {0}

    result = game._apply_automatic_hint_for_count(12)

    assert result is None


def test_rarity_revealed_stays_on_after_three_wrong_guesses():
    game = GameState(make_test_card())

    game.handle_input("A")
    game.handle_input("B")
    game.handle_input("C")

    assert game.rarity_revealed is True
    assert game.wrong_count == 3
    assert game.build_puzzle()["rarity"] == "普通"


def test_handle_input_name_fragment_takes_priority_over_description():
    card = {
        "game": "sts1",
        "id": "mechanic",
        "name": "机械降神",
        "pool": "ironclad",
        "type": "Attack",
        "rarity": "Common",
        "cost": 1,
        "description": "获得能量。",
        "image_url": None,
        "vars": {},
        "star_cost": None,
    }
    game = GameState(card)

    result = game.handle_input("机械")

    assert result.status == "revealed"
    assert result.reveal_target == "name"
    assert game.revealed_name_positions == {0, 1}
    assert game.wrong_count == 0


def test_handle_input_prefers_name_match_over_description_match():
    card = {
        "game": "sts1",
        "id": "energy",
        "name": "能量护盾",
        "pool": "ironclad",
        "type": "Skill",
        "rarity": "Common",
        "cost": 1,
        "description": "获得能量。",
        "image_url": None,
        "vars": {},
        "star_cost": None,
    }
    game = GameState(card)

    result = game.handle_input("能量")

    assert result.status == "revealed"
    assert result.reveal_target == "name"
    assert game.revealed_name_positions == {0, 1}
    assert game.revealed_positions == set()
    assert game.wrong_count == 0


def test_handle_input_correct_card_name():
    game = GameState(make_test_card())

    result = game.handle_input("测试卡")

    assert result.status == "correct"
    assert game.ended is True


def test_name_phrase_reveal_of_full_name_ends_round_automatically():
    card = {"name": "机械降神", "description": "获得能量。"}
    game = GameState(card)

    result = game.guess_name_phrase("机械降神")

    assert result.status == "revealed"
    assert result.reveal_target == "name"
    assert game.ended is True
    assert game.revealed_name_positions == {0, 1, 2, 3}


def test_description_full_reveal_does_not_end_round_if_name_still_hidden():
    card = {"name": "机械降神", "description": "获得能量。"}
    game = GameState(card)

    for token in ["获得", "能量"]:
        result = game.handle_input(token)
        assert result.status == "revealed"
        assert game.ended is False


def test_auto_hint_exhaustion_ends_round():
    card = {"name": "A", "description": "X"}
    game = GameState(card)
    game.wrong_count = 12
    game.revealed_positions = {0}
    game.revealed_name_positions = {0}

    result = game._apply_automatic_hint_for_count(12)

    assert result is None
    assert game.ended is True


def test_ended_game_refuses_further_input():
    game = GameState({"name": "ABCD", "description": "A B C D"})
    game.ended = True

    result = game.handle_input("A")

    assert result.status == "ended"


def test_handle_input_reveals_description_phrase():
    game = GameState(make_test_card())

    result = game.handle_input("伤害")

    assert result.status == "revealed"
    assert result.revealed_count == 2
    assert game.revealed_positions == {5, 6}
    assert game.wrong_count == 0


def test_handle_input_allows_single_character_phrase():
    game = GameState(make_test_card())

    result = game.handle_input("伤")

    assert result.status == "revealed"
    assert result.revealed_count == 1
    assert game.revealed_positions == {5}


def test_handle_input_rejects_non_text_input():
    game = GameState(make_test_card())

    result = game.handle_input("18")

    assert result.status == "invalid"
    assert result.revealed_count == 0
    assert game.wrong_count == 0


def test_handle_input_wrong_guess():
    game = GameState(make_test_card())

    result = game.handle_input("格挡")

    assert result.status == "wrong"
    assert result.revealed_count == 0
    assert game.wrong_count == 1


def test_handle_input_already_revealed():
    game = GameState(make_test_card())

    first_result = game.handle_input("伤害")
    second_result = game.handle_input("伤害")

    assert first_result.status == "revealed"
    assert first_result.revealed_count == 2

    assert second_result.status == "already_revealed"
    assert second_result.revealed_count == 0


def test_description_reveal_count_only_counts_player_description_reveals():
    card = {
        "game": "sts1",
        "name": "机械降神",
        "description": "获得能量。",
    }
    game = GameState(card)

    result = game.handle_input("获得")

    assert result.status == "revealed"
    assert result.reveal_target == "description"
    assert game.description_reveal_count == 1
    assert game.total_guess_count == 1
    assert game.wrong_count == 0


def test_success_description_line_triggers_name_hint_on_schedule(monkeypatch):
    monkeypatch.setattr("random.choice", lambda seq: seq[0])

    for expected in [4, 7, 10, 13]:
        game = GameState({"name": "ABCD", "description": "A B C D E F G H I J K L"})
        game.description_reveal_count = expected - 1
        result = game._on_successful_description_reveal()
        assert result == "name"
        assert len(game.revealed_name_positions) == 1


def test_success_description_line_does_not_trigger_when_name_has_too_few_unknown_chars():
    card = {"name": "AB", "description": "A B C D"}
    game = GameState(card)
    game.revealed_name_positions = {0}
    game.description_reveal_count = 3

    result = game._on_successful_description_reveal()

    assert result is None
    assert game.revealed_name_positions == {0}


def test_name_reveal_does_not_increase_description_reveal_count():
    card = {"name": "ABCD", "description": "获得能量。"}
    game = GameState(card)

    result = game.handle_input("AB")

    assert result.status == "revealed"
    assert result.reveal_target == "name"
    assert game.description_reveal_count == 0
    assert game.total_guess_count == 1


def test_total_guess_count_counts_valid_player_inputs_only():
    game = GameState({"name": "ABCD", "description": "获得能量。"})
    assert game.total_guess_count == 0

    game.handle_input("AB")
    assert game.total_guess_count == 1

    game.handle_input("获得")
    assert game.total_guess_count == 2


def test_get_visible_traits_sts1_base_and_upgrade():
    card = {
        "game": "sts1",
        "description": "获得 [G] 。\n消耗 。",
        "exhaust": True,
        "ethereal": False,
        "innate": False,
        "retain": False,
        "self_retain": False,
        "upgrade": {"description": "固有 。\n获得 [G] 。\n消耗 。"},
    }

    assert get_visible_traits(card, upgraded=False) == ["消耗"]
    assert get_visible_traits(card, upgraded=True) == ["固有", "消耗"]


def test_get_visible_traits_sts1_special_cases():
    after_image = {
        "id": "AFTER_IMAGE",
        "game": "sts1",
        "description": "你每打出一张牌，都获得1点 格挡 。",
        "innate": True,
        "upgrade": {"description": "固有 。\n你每打出一张牌，都获得1点 格挡 。"},
    }
    assert get_visible_traits(after_image, upgraded=False) == []
    assert get_visible_traits(after_image, upgraded=True) == ["固有"]

    worship = {
        "id": "WORSHIP",
        "game": "sts1",
        "description": "每回合开始时获得 5 点 格挡 。",
        "self_retain": True,
        "upgrade": {"description": "保留 。\n每回合开始时获得 5 点 格挡 。"},
    }
    assert get_visible_traits(worship, upgraded=False) == []
    assert get_visible_traits(worship, upgraded=True) == ["保留"]

    blasphemy = {
        "id": "BLASPHEMY",
        "game": "sts1",
        "description": "获得 1 点 力量 。",
        "self_retain": True,
        "upgrade": {"description": "保留 。\n获得 1 点 力量 。"},
    }
    assert get_visible_traits(blasphemy, upgraded=False) == ["保留"]

    adrenaline = {
        "id": "ADRENALINE",
        "game": "sts1",
        "description": "获得 [G] 。\n抽2张牌。\n消耗 。",
        "exhaust": True,
    }
    assert get_visible_traits(adrenaline, upgraded=False) == ["消耗"]


def test_get_visible_traits_sts2_keywords():
    card = {
        "game": "sts2",
        "keywords": ["Exhaust"],
        "upgrade": {"add_keywords": ["Innate"], "remove_keywords": ["Exhaust"]},
    }

    assert get_visible_traits(card, upgraded=False) == ["消耗"]
    assert get_visible_traits(card, upgraded=True) == ["固有"]


def test_trait_guess_reveals_trait_without_wrong_count():
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "造成 5 点伤害。",
        "exhaust": True,
    }
    game = GameState(card)

    result = game.handle_input("消耗")

    assert result.status == "revealed"
    assert result.reveal_target == "description"
    assert game.wrong_count == 0


def test_description_takes_priority_over_trait_match():
    card = {
        "game": "sts1",
        "name": "测试卡",
        "description": "保留 。",
        "self_retain": True,
    }
    game = GameState(card)

    result = game.handle_input("保留")

    assert result.status == "revealed"
    assert result.reveal_target == "description"
    assert game.wrong_count == 0

    game.handle_input("ZZZ")
    assert game.total_guess_count == 2

    game.handle_input("18")
    assert game.total_guess_count == 2


def test_total_guess_count_increments_only_once_per_handle_input():
    game = GameState({"name": "ABCD", "description": "获得能量。"})
    result = game.handle_input("AB")

    assert result.status == "revealed"
    assert game.total_guess_count == 1


def test_wrong_guesses_record_only_failed_player_inputs_and_keep_order():
    game = GameState({"name": "ABCD", "description": "获得能量。"})

    game.handle_input("选择")
    game.handle_input("指控")
    game.handle_input("选择")
    game.handle_input("AB")
    game.handle_input("18")

    assert game.wrong_guesses == ["选择", "指控"]
    assert game.total_guess_count == 4


def test_auto_hints_do_not_count_toward_total_guess_count_or_wrong_guesses():
    game = GameState({"name": "ABCD", "description": "A B C D E F"})
    game.description_reveal_count = 3
    game._on_successful_description_reveal()
    game.wrong_count = 9
    game._apply_automatic_hint_for_count(9)

    assert game.total_guess_count == 0
    assert game.wrong_guesses == []

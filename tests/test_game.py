from card_guess.game import GameState

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

    assert game.guess("杂技") == "correct"
    assert game.ended is True


def test_wrong_card_name_counts_as_wrong():
    card = {"name": "杂技"}
    game = GameState(card)

    assert game.guess("精准") == "wrong"
    assert game.wrong_count == 1


def test_hint_every_four_wrong_guesses():
    card = {"name": "杂技"}
    game = GameState(card)

    game.guess("A")
    game.guess("B")
    game.guess("C")

    assert game.should_hint() is False

    game.guess("D")

    assert game.should_hint() is True


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

def test_handle_input_correct_card_name():
    game = GameState(make_test_card())

    result = game.handle_input("测试卡")

    assert result.status == "correct"
    assert game.ended is True


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

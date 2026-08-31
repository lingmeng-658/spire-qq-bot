from card_guess.qq.onebot import extract_mentioned_text


def test_extracts_text_when_bot_is_mentioned():
    event = {
        "post_type": "message",
        "message_type": "group",
        "self_id": 3671395251,
        "message": [
            {"type": "at", "data": {"qq": "3671395251"}},
            {"type": "text", "data": {"text": " ping"}},
        ],
    }

    result = extract_mentioned_text(event)

    assert result == "ping"

def test_returns_none_when_bot_is_not_mentioned():
    event = {
        "post_type": "message",
        "message_type": "group",
        "self_id": 3671395251,
        "message": [
            {"type": "text", "data": {"text": "Hello, world!"}},
        ],
    }

    result = extract_mentioned_text(event)

    assert result is None

def test_returns_none_for_private_message():
    event = {
        "post_type": "message",
        "message_type": "private",
        "self_id": 3671395251,
        "message": [
            {"type": "at", "data": {"qq": "3671395251"}},
            {"type": "text", "data": {"text": " ping"}},
        ],
    }

    result = extract_mentioned_text(event)

    assert result is None
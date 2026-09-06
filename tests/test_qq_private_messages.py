"""QQ private-message query entry tests.

These tests exercise only the QQ entry layer: private extraction, channel
dispatch, and the private send action.  Command responses use fictional
router-level fixtures so the tests never depend on real run data or QQ.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request

import pytest

from card_guess.qq import bot, onebot, sessions
from card_guess.qq.renderer import RenderedReply

SELF_ID = 12345
USER_ID = 67890
GROUP_ID = 99999


@pytest.fixture(autouse=True)
def idle_session(monkeypatch):
    sessions.SESSIONS.clear()
    monkeypatch.setattr(sessions, "get", lambda channel_id: None)
    yield
    sessions.SESSIONS.clear()


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def make_private_event(text="", message=None, user_id=USER_ID):
    if message is None:
        message = [{"type": "text", "data": {"text": text}}]
    return {
        "post_type": "message",
        "message_type": "private",
        "self_id": SELF_ID,
        "user_id": user_id,
        "message": message,
    }


def make_group_event(text, mentioned=True):
    message = []
    if mentioned:
        message.append({"type": "at", "data": {"qq": str(SELF_ID)}})
    message.append({"type": "text", "data": {"text": text}})
    return {
        "post_type": "message",
        "message_type": "group",
        "self_id": SELF_ID,
        "group_id": GROUP_ID,
        "message": message,
    }


def run_handle_event(event):
    websocket = FakeWebSocket()
    asyncio.run(bot.handle_event(websocket, event))
    return websocket


def message_texts(request):
    payload = request["params"]["message"]
    if isinstance(payload, str):
        return [payload]
    return [
        segment["data"]["text"]
        for segment in payload
        if segment.get("type") == "text"
    ]


def assert_private_reply(websocket, expected_substring):
    assert len(websocket.sent) == 1
    request = websocket.sent[0]
    assert request["action"] == "send_private_msg"
    assert request["params"]["user_id"] == USER_ID
    assert expected_substring in "".join(message_texts(request))
    assert all(item["action"] != "send_group_msg" for item in websocket.sent)


def test_extract_private_text_does_not_require_mention():
    event = make_private_event("白噪声2")

    assert onebot.extract_private_text(event) == "白噪声2"


def test_extract_private_text_safe_without_message_or_user_id():
    missing_message = make_private_event("白噪声2")
    del missing_message["message"]

    assert onebot.extract_private_text(missing_message) is None
    assert onebot.extract_private_text({"post_type": "message"}) is None


def test_private_card_query_routes_through_existing_router(monkeypatch):
    calls = []

    def fake_card_render(name, generation, role=None):
        calls.append((name, generation, role))
        return RenderedReply("card-query-ok")

    monkeypatch.setattr(bot, "_render_generation_query", fake_card_render)

    websocket = run_handle_event(make_private_event("白噪声2"))

    assert_private_reply(websocket, "card-query-ok")
    assert calls == [("白噪声", 2, None)]


def test_private_relic_query_routes_through_existing_router(monkeypatch):
    calls = []

    def no_card_render(name, generation, role=None):
        return None

    def fake_relic_render(name, generation, role=None):
        calls.append((name, generation, role))
        return RenderedReply("relic-query-ok")

    monkeypatch.setattr(bot, "_render_generation_query", no_card_render)
    monkeypatch.setattr(bot, "_render_relic_generation_query", fake_relic_render)

    websocket = run_handle_event(make_private_event("黑星2"))

    assert_private_reply(websocket, "relic-query-ok")
    assert calls == [("黑星", 2, None)]


def test_private_ancient_leaderboard_routes_through_existing_router(monkeypatch):
    calls = []

    def fake_ancient_render(command):
        calls.append(command)
        return RenderedReply("ancient-leaderboard-ok")

    monkeypatch.setattr(
        bot, "_render_ancient_choice_leaderboard_reply", fake_ancient_render
    )

    websocket = run_handle_event(make_private_event("达弗2"))

    assert_private_reply(websocket, "ancient-leaderboard-ok")
    assert calls == ["达弗2"]


def test_private_ancient_overview_command():
    websocket = run_handle_event(make_private_event("先古遗民"))

    assert_private_reply(websocket, "先古遗民")


def test_private_text_and_image_reply_uses_private_msg(monkeypatch, tmp_path):
    image_path = tmp_path / "card.png"
    image_path.write_bytes(b"fake-png")

    def fake_card_render(name, generation, role=None):
        return RenderedReply("card-with-image", image_path=image_path)

    def no_network(*args, **kwargs):
        raise AssertionError("private image reply must not go online")

    monkeypatch.setattr(bot, "_render_generation_query", fake_card_render)
    monkeypatch.setattr(urllib.request, "urlopen", no_network)

    websocket = run_handle_event(make_private_event("白噪声2"))

    assert len(websocket.sent) == 1
    request = websocket.sent[0]
    assert request["action"] == "send_private_msg"
    payload = request["params"]["message"]
    assert isinstance(payload, list)
    assert [seg["type"] for seg in payload] == ["text", "image"]
    assert payload[0]["data"]["text"] == "card-with-image"
    assert payload[1]["data"]["file"].replace("\\", "/").endswith("card.png")


def test_private_whitespace_normalization_matches_group(monkeypatch):
    compact = run_handle_event(make_private_event("先古遗民"))
    spaced = run_handle_event(make_private_event("先 古 遗 民"))

    assert message_texts(compact.sent[0]) == message_texts(spaced.sent[0])


def test_private_and_group_same_command_render_same_text():
    private_ws = run_handle_event(make_private_event("先古遗民"))
    group_ws = run_handle_event(make_group_event("先古遗民", mentioned=True))

    assert message_texts(private_ws.sent[0]) == message_texts(group_ws.sent[0])


def test_group_without_mention_is_still_ignored():
    websocket = run_handle_event(make_group_event("白噪声2", mentioned=False))

    assert websocket.sent == []


def test_group_mention_keeps_group_send_path_and_never_uses_private():
    websocket = run_handle_event(make_group_event("ping", mentioned=True))

    assert len(websocket.sent) == 1
    request = websocket.sent[0]
    assert request["action"] == "send_group_msg"
    assert request["params"]["group_id"] == GROUP_ID
    assert request["params"]["message"] == "pong"
    assert all(item["action"] != "send_private_msg" for item in websocket.sent)


def test_missing_private_user_id_is_ignored_safely():
    event = make_private_event("白噪声2")
    del event["user_id"]

    websocket = run_handle_event(event)

    assert websocket.sent == []


def test_private_non_text_segments_do_not_crash_and_do_not_trigger_send():
    event = make_private_event(
        message=[
            {"type": "image", "data": {"file": "local.png"}},
            {"type": "face", "data": {"id": "1"}},
        ]
    )

    websocket = run_handle_event(event)

    assert websocket.sent == []


def test_private_text_after_non_text_segments_still_routes(monkeypatch):
    def fake_card_render(name, generation, role=None):
        return RenderedReply("card-after-image")

    monkeypatch.setattr(bot, "_render_generation_query", fake_card_render)

    event = make_private_event(
        message=[
            {"type": "image", "data": {"file": "local.png"}},
            {"type": "face", "data": {"id": "1"}},
            {"type": "text", "data": {"text": "白噪声2"}},
        ]
    )

    websocket = run_handle_event(event)

    assert_private_reply(websocket, "card-after-image")

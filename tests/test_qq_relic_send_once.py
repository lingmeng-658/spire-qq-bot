import asyncio
import json

from card_guess.qq import bot, renderer
from card_guess.qq import sessions

SELF_ID = 3671395251
GROUP_ID = 456789


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(json.loads(payload))


def make_event(text):
    return {
        "post_type": "message",
        "message_type": "group",
        "self_id": SELF_ID,
        "group_id": GROUP_ID,
        "message": [
            {"type": "at", "data": {"qq": str(SELF_ID)}},
            {"type": "text", "data": {"text": " " + text}},
        ],
    }


def make_relic(name, relic_id, tier="Common"):
    return {
        "game": "sts1",
        "id": relic_id,
        "name": name,
        "name_en": relic_id,
        "description": f"{name} 的虚构效果描述。",
        "description_en": "fictional description",
        "tier": tier,
        "color": None,
    }


def rate(value, numerator=None, denominator=None):
    metric = {"value": value, "unit": "percent"}
    if numerator is not None:
        metric["numerator"] = numerator
    if denominator is not None:
        metric["denominator"] = denominator
    return metric


def count(value):
    return {"value": value, "unit": "count"}


def common_roles():
    return {
        "IRONCLAD": 3.24,
        "THE_SILENT": 2.94,
        "DEFECT": 3.41,
        "WATCHER": 5.68,
    }


def base_entry(roles=None):
    if roles is None:
        roles = common_roles()
    return {
        "overall": rate(3.58, 4216, 117728),
        "per_character": {role: rate(value) for role, value in roles.items()},
        "supported_roles": list(roles),
        "heart_win_presence_rate": rate(15.27, 369, 2416),
    }


def starter_entry():
    return {
        "overall": rate(29.21, 34389, 117728),
        "per_character": {"IRONCLAD": rate(86.19, 34389, 39880)},
        "supported_roles": ["IRONCLAD"],
        "heart_win_presence_rate": rate(25.08, 606, 2416),
    }


def boss_entry():
    return {
        "overall": rate(37.0, 4200, 11350),
        "per_character": {
            "IRONCLAD": rate(40.0),
            "THE_SILENT": rate(33.0),
            "DEFECT": rate(35.0),
            "WATCHER": rate(41.0),
        },
        "supported_roles": ["IRONCLAD", "THE_SILENT", "DEFECT", "WATCHER"],
        "heart_win_presence_rate": rate(20.0, 400, 2000),
        "boss_choice": {
            "act1": {"pick_rate": rate(37.87)},
            "act2": {"pick_rate": rate(33.69)},
        },
    }


def acquisition():
    return {
        "sample_size": 3206,
        "final_presence_runs": 4216,
        "coverage_rate": rate(76.0, 3206, 4216),
        "median_floor": 13.0,
        "p25_floor": 9.0,
        "p75_floor": 27.0,
        "act1_rate": rate(54.4),
        "act2_rate": rate(27.9),
        "act3_rate": rate(17.7),
    }


def snapshot(relic_id, entry):
    return {"relics": {relic_id: entry}}


def text_segments(payload):
    if isinstance(payload, str):
        return [payload]
    return [
        segment["data"]["text"]
        for segment in payload
        if segment.get("type") == "text"
    ]


def image_segments(payload):
    if isinstance(payload, str):
        return []
    return [
        segment["data"].get("file")
        for segment in payload
        if segment.get("type") == "image"
    ]


def query_once(monkeypatch, tmp_path, relic, stats):
    sessions.SESSIONS.clear()
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [])
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [relic])
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: stats)
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path, raising=False)

    ws = FakeWebSocket()
    asyncio.run(bot.handle_event(ws, make_event(relic["name"])))
    return ws


def assert_single_reply(ws, header, extra_text=None):
    # Exactly one user-visible send, containing exactly one text.
    assert len(ws.sent) == 1, f"expected 1 send, got {len(ws.sent)}"
    request = ws.sent[0]
    assert request["action"] == "send_group_msg"
    payload = request["params"]["message"]
    texts = text_segments(payload)
    assert len(texts) == 1, f"expected exactly 1 text segment, got {len(texts)}"
    assert texts[0].count(header) == 1
    if extra_text is not None:
        assert extra_text in texts[0]
    return payload


def test_common_relic_query_sends_text_once(monkeypatch, tmp_path):
    relic = make_relic("赤牛", "AKABEKO", tier="Common")
    ws = query_once(monkeypatch, tmp_path, relic, snapshot("AKABEKO", base_entry()))
    payload = assert_single_reply(ws, "=== 赤牛 · STS1 ===")
    assert image_segments(payload) == []


def test_image_relic_query_sends_text_and_image_together_once(monkeypatch, tmp_path):
    relic = make_relic("赤牛", "AKABEKO", tier="Common")
    image_path = (
        tmp_path / "data" / "images" / "relics" / "sts1" / "AKABEKO.png"
    )
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-png-bytes")
    ws = query_once(monkeypatch, tmp_path, relic, snapshot("AKABEKO", base_entry()))
    payload = assert_single_reply(ws, "=== 赤牛 · STS1 ===")
    images = image_segments(payload)
    assert len(images) == 1, f"expected 1 image segment, got {len(images)}"
    assert images[0].replace("\\", "/").endswith(
        "data/images/relics/sts1/AKABEKO.png"
    )


def test_first_acquisition_relic_query_sends_text_once(monkeypatch, tmp_path):
    relic = make_relic("赤牛", "AKABEKO", tier="Common")
    entry = base_entry()
    entry["first_acquisition"] = acquisition()
    ws = query_once(monkeypatch, tmp_path, relic, snapshot("AKABEKO", entry))
    payload = assert_single_reply(
        ws,
        "=== 赤牛 · STS1 ===",
        extra_text="通常在第13层左右拿到，",
    )
    assert image_segments(payload) == []


def test_boss_relic_query_sends_text_once(monkeypatch, tmp_path):
    relic = make_relic("添水", "SOZU", tier="Boss")
    ws = query_once(monkeypatch, tmp_path, relic, snapshot("SOZU", boss_entry()))
    payload = assert_single_reply(ws, "=== 添水 · STS1 ===")
    assert image_segments(payload) == []


def test_starter_relic_query_sends_text_once(monkeypatch, tmp_path):
    relic = make_relic("燃烧之血", "BURNING_BLOOD", tier="Starter")
    ws = query_once(
        monkeypatch,
        tmp_path,
        relic,
        snapshot("BURNING_BLOOD", starter_entry()),
    )
    payload = assert_single_reply(ws, "=== 燃烧之血 · STS1 ===")
    assert image_segments(payload) == []
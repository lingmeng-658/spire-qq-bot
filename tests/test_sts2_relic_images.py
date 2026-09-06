"""STS2 relic image tests: local resolution, QQ send, offline guarantee.

图片链路复用 STS1 的本地文件约定：data/images/relics/{game}/{id}.png。
QQ runtime 只读本地图片文件，任何查询路径都不得联网下载。
本文件全部使用虚构遗物数据（黑星 / 添水 / 诅咒珍珠为示例名）。
"""

import asyncio
import json
import urllib.request

import pytest

from card_guess.qq import bot, renderer, sessions
from card_guess.qq.renderer import RenderedReply

SELF_ID = 3671395251
GROUP_ID = 456789


def make_sts2_relic(
    name="黑星",
    relic_id="BLACK_STAR",
    name_en="Black Star",
    tier="Ancient",
    description="每击败一名精英敌人，获得2点最大生命。",
):
    return {
        "game": "sts2",
        "id": relic_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": "Gain 2 Max HP each time you defeat an Elite.",
        "tier": tier,
        "color": None,
    }


def make_image(root, rel_path, content=b"fake-png"):
    image = root / rel_path
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(content)
    return image


def patch_query_env(monkeypatch, relic):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [], raising=False)
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(
        bot, "_load_sts2_query_relics", lambda: [relic], raising=False
    )
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: {})


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data" / "images").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "REPO_ROOT", root)
    return root


@pytest.mark.parametrize(
    ("name", "relic_id"),
    [
        ("黑星", "BLACK_STAR"),
        ("添水", "SOZU"),
        ("诅咒珍珠", "CURSED_PEARL"),
    ],
)
def test_sts2_example_relic_ids_resolve_under_sts2_folder(fake_repo, name, relic_id):
    relic = make_sts2_relic(name=name, relic_id=relic_id)
    image = make_image(fake_repo, "data/images/relics/sts2/{relic_id}.png".format(relic_id=relic_id))

    assert renderer.resolve_local_relic_image(relic) == image


def test_missing_sts2_relic_image_resolves_to_none(fake_repo):
    assert renderer.resolve_local_relic_image(make_sts2_relic()) is None
    assert renderer.resolve_local_relic_image({}) is None
    assert renderer.resolve_local_relic_image(None) is None
    # 仅存在 STS1 图片时，STS2 解析不受影响
    make_image(fake_repo, "data/images/relics/sts1/AKABEKO.png")
    assert renderer.resolve_local_relic_image(make_sts2_relic()) is None


def test_sts2_relic_query_returns_text_plus_image_when_image_exists(
    fake_repo, monkeypatch
):
    relic = make_sts2_relic()
    image = make_image(fake_repo, "data/images/relics/sts2/BLACK_STAR.png")
    patch_query_env(monkeypatch, relic)

    reply = bot.route_group_command(101, "黑星2")

    assert isinstance(reply, RenderedReply)
    assert "=== 黑星 · STS2 ===" in reply
    assert "效果：" in reply
    assert reply.image_path == image
    assert reply.image_paths == (image,)


def test_sts2_relic_query_stays_text_only_when_image_missing(fake_repo, monkeypatch):
    relic = make_sts2_relic(name="诅咒珍珠", relic_id="CURSED_PEARL")
    patch_query_env(monkeypatch, relic)

    reply = bot.route_group_command(101, "诅咒珍珠2")

    assert isinstance(reply, RenderedReply)
    assert "=== 诅咒珍珠 · STS2 ===" in reply
    assert "效果：" in reply
    assert reply.image_path is None
    assert reply.image_paths == ()


def test_sts2_relic_query_does_not_trigger_network_downloads(fake_repo, monkeypatch):
    relic = make_sts2_relic()
    image = make_image(fake_repo, "data/images/relics/sts2/BLACK_STAR.png")
    patch_query_env(monkeypatch, relic)

    def boom(*args, **kwargs):
        raise AssertionError("QQ 查询过程中不应发起任何网络下载")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    reply = bot.route_group_command(101, "黑星2")

    assert isinstance(reply, RenderedReply)
    assert reply.image_path == image

    # 缺图时同样不联网、不报错
    patch_query_env(
        monkeypatch,
        make_sts2_relic(name="诅咒珍珠", relic_id="CURSED_PEARL"),
    )
    text_reply = bot.route_group_command(101, "诅咒珍珠2")
    assert text_reply.image_path is None
    assert "=== 诅咒珍珠 · STS2 ===" in text_reply


def test_sts1_relic_image_resolution_unchanged_when_sts2_images_present(fake_repo):
    sts1_relic = {
        "game": "sts1",
        "id": "AKABEKO",
        "name": "赤牛",
    }
    sts1_image = make_image(fake_repo, "data/images/relics/sts1/AKABEKO.png")
    make_image(fake_repo, "data/images/relics/sts2/BLACK_STAR.png")

    assert renderer.resolve_local_relic_image(sts1_relic) == sts1_image


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


def test_sts2_query_with_image_sends_text_and_image_together_once(
    monkeypatch, tmp_path
):
    sessions.SESSIONS.clear()
    relic = make_sts2_relic(name="添水", relic_id="SOZU", name_en="Sozu")
    image_path = tmp_path / "data" / "images" / "relics" / "sts2" / "SOZU.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-png-bytes")
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path)
    patch_query_env(monkeypatch, relic)

    ws = FakeWebSocket()
    asyncio.run(bot.handle_event(ws, make_event("添水2")))

    assert len(ws.sent) == 1, f"expected 1 send, got {len(ws.sent)}"
    request = ws.sent[0]
    assert request["action"] == "send_group_msg"
    payload = request["params"]["message"]
    texts = [
        segment["data"]["text"]
        for segment in payload
        if segment.get("type") == "text"
    ]
    images = [
        segment["data"].get("file")
        for segment in payload
        if segment.get("type") == "image"
    ]
    assert len(texts) == 1
    assert "=== 添水 · STS2 ===" in texts[0]
    assert len(images) == 1
    assert images[0].replace("\\", "/").endswith(
        "data/images/relics/sts2/SOZU.png"
    )
import urllib.request
from pathlib import Path

import pytest

from card_guess.qq import bot, renderer
from card_guess.qq.renderer import RenderedReply


def make_relic(
    name="赤牛",
    relic_id="AKABEKO",
    name_en="Akabeko",
    tier="Common",
    description="每场战斗的第一回合，额外造成 8 点伤害。",
):
    return {
        "game": "sts1",
        "id": relic_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": "At the start of each combat, deal 8 additional damage.",
        "tier": tier,
        "color": None,
    }


def make_card(name="打击", card_id="BASH", description="造成 6 点伤害。"):
    return {
        "game": "sts1",
        "id": card_id,
        "name": name,
        "pool": "ironclad",
        "type": "Attack",
        "cost": 1,
        "star_cost": None,
        "rarity": "Basic",
        "description": description,
        "vars": {},
    }


def make_image(root, rel_path, content=b"fake-png"):
    image = root / rel_path
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(content)
    return image


def patch_query_env(monkeypatch, relics=(), cards=()):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: list(cards), raising=False)
    monkeypatch.setattr(bot, "_load_query_relics", lambda: list(relics), raising=False)
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_relic_stats", lambda: {})


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """把图片根目录指向临时目录，避免依赖真实 data/images 资产。"""
    root = tmp_path / "repo"
    (root / "data" / "images").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "REPO_ROOT", root)
    return root


def relic_image_path(root):
    return root / "data" / "images" / "relics" / "sts1" / "AKABEKO.png"


def test_relic_id_resolves_to_expected_local_image_path(fake_repo):
    image = make_image(fake_repo, "data/images/relics/sts1/AKABEKO.png")

    assert renderer.resolve_local_relic_image(make_relic()) == image


def test_missing_relic_image_resolves_to_none(fake_repo):
    assert renderer.resolve_local_relic_image(make_relic()) is None
    assert renderer.resolve_local_relic_image({}) is None
    assert renderer.resolve_local_relic_image(None) is None
    # 仅存卡牌图片时，遗物解析不受影响
    make_image(fake_repo, "data/images/sts1/BASH.png")
    assert renderer.resolve_local_relic_image(make_relic()) is None


def test_relic_query_returns_text_plus_image_when_image_exists(fake_repo, monkeypatch):
    relic = make_relic()
    image = make_image(fake_repo, "data/images/relics/sts1/AKABEKO.png")
    patch_query_env(monkeypatch, relics=[relic])

    reply = bot.route_group_command(101, "赤牛")

    assert isinstance(reply, RenderedReply)
    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：" in reply
    assert reply.image_path == image
    assert reply.image_paths == (image,)


def test_relic_query_stays_text_only_when_image_missing(fake_repo, monkeypatch):
    relic = make_relic()
    patch_query_env(monkeypatch, relics=[relic])

    reply = bot.route_group_command(101, "赤牛")

    assert isinstance(reply, RenderedReply)
    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：\n每场战斗的第一回合，额外造成 8 点伤害。" in reply
    assert reply.image_path is None
    assert reply.image_paths == ()


def test_relic_query_does_not_trigger_network_downloads(fake_repo, monkeypatch):
    relic = make_relic()
    image = make_image(fake_repo, "data/images/relics/sts1/AKABEKO.png")
    patch_query_env(monkeypatch, relics=[relic])

    def boom(*args, **kwargs):
        raise AssertionError("QQ 查询过程中不应发起任何网络下载")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    reply = bot.route_group_command(101, "赤牛")

    assert isinstance(reply, RenderedReply)
    assert reply.image_path == image
    # 缺图时同样不联网、不报错
    patch_query_env(monkeypatch, relics=[make_relic(relic_id="SOZU", name="添水")])
    text_reply = bot.route_group_command(101, "添水")
    assert text_reply.image_path is None
    assert "=== 添水 · STS1 ===" in text_reply


def test_existing_card_image_query_untouched_by_relic_images(fake_repo, monkeypatch):
    relic = make_relic()
    card = make_card()
    card_image = make_image(fake_repo, "data/images/sts1/BASH.png")
    relic_image = make_image(fake_repo, "data/images/relics/sts1/AKABEKO.png")
    patch_query_env(monkeypatch, relics=[relic], cards=[card])

    card_reply = bot.route_group_command(101, "打击")

    assert isinstance(card_reply, RenderedReply)
    assert "=== 打击 · STS1 · 铁甲战士 ===" in card_reply
    assert card_reply.image_path == card_image
    assert card_reply.image_paths == (card_image,)

    relic_reply = bot.route_group_command(101, "赤牛")

    assert relic_reply.image_path == relic_image

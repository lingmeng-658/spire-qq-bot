"""QQ tests for STS2 Ancient NPC local images and overview command.

All NPC ids and relic names are fictional fixtures. Image resolution always
uses a temporary repo root so the tests never depend on real assets.
"""

from __future__ import annotations

import urllib.request

import pytest

from card_guess.qq import bot, renderer, sessions
from card_guess.qq.renderer import RenderedReply
from card_guess.sts2_ancient_choice import (
    OFFICIAL_ANCIENT_NPC_ZH,
    build_sts2_ancient_choice_snapshot,
)

NPC_IDS = [
    "DARV",
    "NEOW",
    "NONUPEIPE",
    "OROBAS",
    "PAEL",
    "TANX",
    "TEZCATARA",
    "VAKUU",
]
RELIC_ZH = {
    "F_A": "虚构遗物甲",
    "F_B": "虚构遗物乙",
    "F_C": "虚构遗物丙",
    "F_D": "虚构遗物丁",
}


def _row(relic_id, npc_id, act, offered, picked):
    return {
        "relic_id": relic_id,
        "npc_id": npc_id,
        "act": act,
        "offered_count": offered,
        "picked_rate": picked,
    }


def _darv_snapshot():
    return build_sts2_ancient_choice_snapshot(
        [
            _row("F_A", "DARV", 2, 18000, 58),
            _row("F_B", "DARV", 2, 18000, 53),
            _row("F_C", "DARV", 3, 4400, 54),
            _row("F_D", "DARV", 3, 4500, 53),
        ],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=RELIC_ZH,
        npc_names_zh={"DARV": "达弗"},
    )


def _neow_snapshot():
    return build_sts2_ancient_choice_snapshot(
        [_row("F_A", "NEOW", 1, 120000, 76)],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh=RELIC_ZH,
        npc_names_zh={"NEOW": "涅奥"},
    )


def make_image(root, rel_path, content=b"fake-png"):
    image = root / rel_path
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(content)
    return image


@pytest.fixture(autouse=True)
def idle_session(monkeypatch):
    monkeypatch.setattr(sessions, "get", lambda group_id: None)


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "data" / "images").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(renderer, "REPO_ROOT", root)
    return root


def patch_snapshot(monkeypatch, snapshot):
    monkeypatch.setattr(
        renderer, "load_sts2_ancient_choice_stats", lambda: snapshot
    )


def test_eight_official_ancient_npc_mapping_is_stable():
    assert list(OFFICIAL_ANCIENT_NPC_ZH) == NPC_IDS
    assert list(OFFICIAL_ANCIENT_NPC_ZH.values()) == [
        "达弗",
        "涅奥",
        "诺奴佩普",
        "欧洛巴斯",
        "佩尔",
        "坦克斯",
        "特兹卡塔拉",
        "瓦库",
    ]


def test_eight_npc_ids_resolve_to_local_sts2_image_slots(fake_repo):
    for npc_id in NPC_IDS:
        image = make_image(
            fake_repo, "data/images/ancients/sts2/{}.png".format(npc_id)
        )
        assert renderer.resolve_local_ancient_npc_image(npc_id) == image


def test_missing_unknown_or_invalid_image_resolves_to_none(fake_repo):
    assert renderer.resolve_local_ancient_npc_image("NEOW") is None
    assert renderer.resolve_local_ancient_npc_image("") is None
    assert renderer.resolve_local_ancient_npc_image(None) is None
    assert renderer.resolve_local_ancient_npc_image("NOT_AN_ANCIENT") is None
    make_image(fake_repo, "data/images/ancients/sts1/DARV.png")
    assert renderer.resolve_local_ancient_npc_image("DARV") is None


def test_overview_command_lists_eight_official_zh_names():
    reply = bot.route_group_command(101, "先古遗民")

    assert isinstance(reply, RenderedReply)
    expected = (
        "先古遗民\n\n"
        + "\n".join(OFFICIAL_ANCIENT_NPC_ZH.values())
        + "\n\n发送名字可查看对应图片与可查询层。"
    )
    assert str(reply) == expected
    for banned in NPC_IDS:
        assert banned not in reply


def test_bare_darv_reply_keeps_layer_hint_and_adds_image(
    fake_repo, monkeypatch
):
    patch_snapshot(monkeypatch, _darv_snapshot())
    image = make_image(fake_repo, "data/images/ancients/sts2/DARV.png")

    reply = bot.route_group_command(101, "达弗")

    assert isinstance(reply, RenderedReply)
    assert str(reply) == "达弗有多个可查询层：\n达弗2\n达弗3"
    assert reply.image_path == image
    assert reply.image_paths == (image,)


def test_bare_neow_reply_keeps_full_board_and_adds_image(
    fake_repo, monkeypatch
):
    patch_snapshot(monkeypatch, _neow_snapshot())
    image = make_image(fake_repo, "data/images/ancients/sts2/NEOW.png")

    reply = bot.route_group_command(101, "涅奥")

    assert isinstance(reply, RenderedReply)
    assert "涅奥 · 第一层 Ancient 遗物选择率排行" in reply
    assert "1. 虚构遗物甲 —— 76%" in reply
    assert reply.image_path == image
    assert reply.image_paths == (image,)


def test_explicit_layer_board_does_not_repeat_npc_image(
    fake_repo, monkeypatch
):
    patch_snapshot(monkeypatch, _darv_snapshot())
    make_image(fake_repo, "data/images/ancients/sts2/DARV.png")

    reply = bot.route_group_command(101, "达弗2")

    assert isinstance(reply, RenderedReply)
    assert "达弗 · 第二层 Ancient 遗物选择率排行" in reply
    assert reply.image_path is None
    assert reply.image_paths == ()


def test_missing_npc_image_keeps_text_only_reply(fake_repo, monkeypatch):
    patch_snapshot(monkeypatch, _darv_snapshot())
    darv_reply = bot.route_group_command(101, "达弗")

    patch_snapshot(monkeypatch, _neow_snapshot())
    neow_reply = bot.route_group_command(101, "涅奥")

    assert str(darv_reply) == "达弗有多个可查询层：\n达弗2\n达弗3"
    assert "涅奥 · 第一层 Ancient 遗物选择率排行" in str(neow_reply)
    assert darv_reply.image_path is None
    assert darv_reply.image_paths == ()
    assert neow_reply.image_path is None
    assert neow_reply.image_paths == ()


def test_ancient_queries_do_not_trigger_network_downloads(
    fake_repo, monkeypatch
):
    patch_snapshot(monkeypatch, _darv_snapshot())
    image = make_image(fake_repo, "data/images/ancients/sts2/DARV.png")

    def boom(*args, **kwargs):
        raise AssertionError("Ancient query must stay offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)

    reply = bot.route_group_command(101, "达弗")
    assert reply.image_path == image


def test_overview_and_bare_npc_spacing_normalizes(fake_repo, monkeypatch):
    patch_snapshot(monkeypatch, _darv_snapshot())

    assert str(bot.route_group_command(101, "先 古 遗 民")) == str(
        bot.route_group_command(101, "先古遗民")
    )
    assert str(bot.route_group_command(101, "达 弗")) == str(
        bot.route_group_command(101, "达弗")
    )


def test_card_and_relic_generation_routes_are_not_swallowed(monkeypatch):
    calls = []

    def fake_card_render(name, generation, role=None):
        if name == "虚构牌":
            calls.append(("card", name, generation))
            return RenderedReply("card-reply")
        return None

    def fake_relic_render(name, generation, role=None):
        calls.append(("relic", name, generation))
        return RenderedReply("relic-reply")

    monkeypatch.setattr(bot, "_render_generation_query", fake_card_render)
    monkeypatch.setattr(
        bot, "_render_relic_generation_query", fake_relic_render
    )

    card_reply = bot.route_group_command(101, "虚构牌2")
    relic_reply = bot.route_group_command(101, "虚构遗物2")

    assert str(card_reply) == "card-reply"
    assert str(relic_reply) == "relic-reply"
    assert ("card", "虚构牌", 2) in calls
    assert ("relic", "虚构遗物", 2) in calls

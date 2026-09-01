import asyncio
import json
from pathlib import Path

from card_guess.qq import bot
from card_guess.qq.onebot import build_message_segments
from card_guess.qq.renderer import RenderedReply, render_card_query_reply


def make_card(name="磨蚀", card_id="ABRASIVE", game="sts2"):
    return {
        "name": name,
        "game": game,
        "id": card_id,
        "pool": "silent",
        "type": "Power",
        "cost": 3,
        "star_cost": None,
        "rarity": "Rare",
        "description": "获得1点敏捷。",
        "vars": {},
    }


def metric(value, unit="percent"):
    return {"value": value, "unit": unit, "sample_size": 100}


def make_full_snapshot(card_id="ABRASIVE"):
    return {
        "cards": {
            card_id: {
                "id": card_id,
                "untapped": {
                    "card_reward": {
                        "act_1": {
                            "pick_rate": metric(52.0),
                            "run_win_rate_impact": metric(2.0, "percentage_points"),
                        },
                        "act_2": {
                            "pick_rate": metric(60.0),
                            "run_win_rate_impact": metric(1.0, "percentage_points"),
                        },
                        "act_3": {
                            "pick_rate": metric(55.0),
                            "run_win_rate_impact": metric(-2.0, "percentage_points"),
                        },
                    },
                    "shop": {
                        "act_1": {"purchase_rate": metric(37.0)},
                        "act_2": {"purchase_rate": metric(44.0)},
                        "act_3": {"purchase_rate": metric(44.0)},
                    },
                    "smith": {
                        "act_1": {"upgrade_rate": metric(25.0)},
                        "act_2": {"upgrade_rate": metric(14.0)},
                        "act_3": {"upgrade_rate": metric(10.0)},
                    },
                },
                "spire_codex": {
                    "final_deck_presence_rate": metric(3.028),
                },
            }
        }
    }


def test_sts2_single_card_query_includes_compact_stats(monkeypatch):
    card = make_card()
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda queried_card: Path("/tmp/ABRASIVE.png"),
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_upgraded_card_image",
        lambda queried_card: Path("/tmp/upgraded/ABRASIVE.png"),
    )

    reply = render_card_query_reply([card])

    assert isinstance(reply, RenderedReply)
    assert "=== 卡牌资料 ===" in reply
    assert "卡名：磨蚀" in reply
    assert "=== 二代统计 ===" in reply
    assert "第一/二/三幕抓取率\n52% / 60% / 55%" in reply
    assert "第一/二/三幕商店购买率\n37% / 44% / 44%" in reply
    assert "第一/二/三幕升级率\n25% / 14% / 10%" in reply
    assert "第一/二/三幕胜率差\n+2.0 / +1.0 / -2.0 个百分点" in reply
    assert "终局卡组出现率：3.03%" in reply
    assert reply.image_path == Path("/tmp/ABRASIVE.png")
    assert reply.image_paths == (
        Path("/tmp/ABRASIVE.png"),
        Path("/tmp/upgraded/ABRASIVE.png"),
    )


def test_sts2_stats_missing_acts_show_dash_never_zero(monkeypatch):
    snapshot = {
        "cards": {
            "ABRASIVE": {
                "id": "ABRASIVE",
                "untapped": {
                    "card_reward": {
                        "act_1": {
                            "pick_rate": metric(52.0),
                            "run_win_rate_impact": metric(2.0, "percentage_points"),
                        },
                        "act_3": {"pick_rate": metric(55.0)},
                    },
                    "shop": {
                        "act_1": {"purchase_rate": metric(37.0)},
                        "act_2": {"purchase_rate": metric(44.0)},
                    },
                },
                "spire_codex": {},
            }
        }
    }
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([make_card()])

    assert "第一/二/三幕抓取率\n52% / - / 55%" in reply
    assert "第一/二/三幕胜率差\n+2.0 / - / - 个百分点" in reply
    assert "第一/二/三幕商店购买率\n37% / 44% / -" in reply
    assert "第一/二/三幕升级率" not in reply
    assert "终局卡组出现率" not in reply
    assert "0% / 0% / 0%" not in reply


def test_sts2_query_without_any_stats_still_renders_card(monkeypatch):
    card = make_card(name="疯狂科学", card_id="MAD_SCIENCE")
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda c: Path("/tmp/MAD_SCIENCE.png"),
    )
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([card])

    assert "=== 卡牌资料 ===" in reply
    assert "二代统计" not in reply
    assert reply.image_path == Path("/tmp/MAD_SCIENCE.png")
    assert reply.image_paths == (Path("/tmp/MAD_SCIENCE.png"),)


def test_sts2_query_missing_upgraded_image_falls_back_to_base(monkeypatch):
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda c: Path("/tmp/ABRASIVE.png"),
    )
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([make_card()])

    assert "=== 二代统计 ===" in reply
    assert reply.image_paths == (Path("/tmp/ABRASIVE.png"),)


def test_sts2_query_with_only_final_deck_presence_renders_that_row(monkeypatch):
    snapshot = {
        "cards": {
            "ABRASIVE": {
                "id": "ABRASIVE",
                "spire_codex": {
                    "final_deck_presence_rate": metric(3.028),
                },
            }
        }
    }
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([make_card()])

    assert "=== 二代统计 ===" in reply
    assert "终局卡组出现率：3.03%" in reply
    assert "第一/二/三幕" not in reply


def test_sts1_query_keeps_current_behavior_without_stats(monkeypatch):
    card = make_card(name="痛击", card_id="BASH", game="sts1")
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: Path("/tmp/BASH.png"))

    def fail_if_called(*args):
        raise AssertionError("STS1 不应解析升级图")

    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", fail_if_called)

    reply = render_card_query_reply([card])

    assert "=== 二代统计 ===" not in reply
    assert "第一/二/三幕" not in reply
    assert reply.image_path == Path("/tmp/BASH.png")
    assert reply.image_paths == (Path("/tmp/BASH.png"),)


def test_sts2_stats_missing_snapshot_or_malformed_entry_is_safe(monkeypatch):
    for bad_snapshot in [None, [], {"cards": None}, {"cards": {"ABRASIVE": None}}]:
        monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: bad_snapshot)
        monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
        monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

        reply = render_card_query_reply([make_card()])

        assert "=== 卡牌资料 ===" in reply
        assert "二代统计" not in reply
        assert reply.image_paths == ()


def test_build_message_segments_supports_multiple_images():
    segments = build_message_segments(
        "text",
        image_paths=[Path("/tmp/ABRASIVE.png"), Path("/tmp/upgraded/ABRASIVE.png")],
    )

    assert segments == [
        {"type": "text", "data": {"text": "text"}},
        {"type": "image", "data": {"file": "/tmp/ABRASIVE.png"}},
        {"type": "image", "data": {"file": "/tmp/upgraded/ABRASIVE.png"}},
    ]


def test_build_message_segments_keeps_single_image_behavior():
    segments = build_message_segments("text", image_path=Path("/tmp/BASH.png"))

    assert segments == [
        {"type": "text", "data": {"text": "text"}},
        {"type": "image", "data": {"file": "/tmp/BASH.png"}},
    ]


def test_send_group_reply_sends_text_and_both_images_in_one_message():
    sent = []

    class FakeWebSocket:
        async def send(self, payload):
            sent.append(json.loads(payload))

    reply = RenderedReply(
        "text",
        image_path=Path("/tmp/ABRASIVE.png"),
        image_paths=[Path("/tmp/ABRASIVE.png"), Path("/tmp/upgraded/ABRASIVE.png")],
    )

    async def run():
        await bot._send_group_reply(FakeWebSocket(), 101, reply)

    asyncio.run(run())

    assert len(sent) == 1
    message = sent[0]["params"]["message"]
    assert [segment["type"] for segment in message] == ["text", "image", "image"]


def test_send_group_reply_sends_text_only_rendered_reply():
    sent = []

    class FakeWebSocket:
        async def send(self, payload):
            sent.append(json.loads(payload))

    reply = RenderedReply("=== 本轮题目 ===\n牌名：□□□□")

    async def run():
        await bot._send_group_reply(FakeWebSocket(), 101, reply)

    asyncio.run(run())

    assert len(sent) == 1
    assert sent[0]["params"]["message"] == "=== 本轮题目 ===\n牌名：□□□□"


def test_send_group_reply_sends_single_image_rendered_reply():
    sent = []

    class FakeWebSocket:
        async def send(self, payload):
            sent.append(json.loads(payload))

    reply = RenderedReply("text", image_path=Path("/tmp/BASH.png"))

    async def run():
        await bot._send_group_reply(FakeWebSocket(), 101, reply)

    asyncio.run(run())

    assert len(sent) == 1
    message = sent[0]["params"]["message"]
    assert [segment["type"] for segment in message] == ["text", "image"]
    assert message[1]["data"]["file"] == "/tmp/BASH.png"


def test_send_group_reply_sends_plain_string_reply():
    sent = []

    class FakeWebSocket:
        async def send(self, payload):
            sent.append(json.loads(payload))

    async def run():
        await bot._send_group_reply(FakeWebSocket(), 101, "普通文本回复")

    asyncio.run(run())

    assert len(sent) == 1
    assert sent[0]["params"]["message"] == "普通文本回复"


def test_route_group_command_sts2_suffix_query_includes_stats(monkeypatch):
    sts1_card = {
        **make_card(name="白噪声", card_id="WHITE_NOISE"),
        "game": "sts1",
        "pool": "defect",
    }
    sts2_card = {
        **make_card(name="白噪声", card_id="WHITE_NOISE_2"),
        "game": "sts2",
        "pool": "defect",
    }
    monkeypatch.setattr(
        bot,
        "_load_query_cards",
        lambda: [sts1_card, sts2_card],
        raising=False,
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.load_sts2_card_stats",
        lambda: make_full_snapshot("WHITE_NOISE_2"),
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda c: Path("/tmp/WHITE_NOISE_2.png"),
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_upgraded_card_image",
        lambda c: Path("/tmp/upgraded/WHITE_NOISE_2.png"),
    )

    reply = bot.route_group_command(101, "白噪声2")

    assert "=== 卡牌资料 ===" in reply
    assert "=== 二代统计 ===" in reply
    assert "终局卡组出现率：3.03%" in reply
    assert reply.image_paths == (
        Path("/tmp/WHITE_NOISE_2.png"),
        Path("/tmp/upgraded/WHITE_NOISE_2.png"),
    )

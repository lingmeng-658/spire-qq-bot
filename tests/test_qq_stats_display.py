import asyncio
import json
from pathlib import Path

from card_guess.qq import bot
from card_guess.qq.onebot import build_message_segments
from card_guess.qq.renderer import (
    RenderedReply,
    STS1_ASC7PLUS_SOURCE_ID,
    render_card_query_reply,
)


def make_card(name="磨蚀", card_id="ABRASIVE", game="sts2", pool="silent"):
    return {
        "name": name,
        "game": game,
        "id": card_id,
        "pool": pool,
        "type": "Power",
        "cost": 3,
        "star_cost": None,
        "rarity": "Rare",
        "description": "获得1点敏捷。",
        "vars": {},
    }


def metric(value, unit="percent", sample_size=100):
    payload = {"value": value, "unit": unit}
    if sample_size is not None:
        payload["sample_size"] = sample_size
    return payload


def metric_without_sample(value, unit="percent"):
    """A metric-like dict without a sample_size field (unreliable sample)."""
    return {"value": value, "unit": unit}


def win_metric(value, denominator, comparison_denominator):
    return {
        "value": value,
        "unit": "percentage_points",
        "numerator": max(0, int(denominator / 2)),
        "denominator": denominator,
        "comparison_numerator": 0,
        "comparison_denominator": comparison_denominator,
        "sample_size": denominator + comparison_denominator,
    }


def make_full_snapshot(card_id="ABRASIVE"):
    return {
        "cards": {
            card_id: {
                "id": card_id,
                "untapped": {
                    "card_reward": {
                        "act_1": {
                            "pick_rate": metric(86.0, sample_size=4000),
                            "run_win_rate_impact": metric(2.0, "percentage_points"),
                        },
                        "act_2": {
                            "pick_rate": metric(60.0, sample_size=15000),
                            "run_win_rate_impact": metric(1.0, "percentage_points"),
                        },
                        "act_3": {
                            "pick_rate": metric(55.0, sample_size=7400),
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


def make_sts1_snapshot(card_id="BASH"):
    source = {
        "act_pick_rate": {
            "act_1": metric(52.1),
            "act_2": metric(60.0),
            "act_3": metric(55.0),
        },
        "act_win_delta": {
            "act_1": win_metric(2.5, 30, 30),
            "act_2": win_metric(1.0, 30, 30),
            "act_3": win_metric(-2.0, 30, 30),
        },
        "first_pick_floor_mean": metric(8.7, "floor"),
        "repick_rate": metric(19.1),
        "final_deck_presence_rate": metric(2.9),
        "final_deck_copy_mean": metric(1.33, "copies"),
        "final_upgrade_rate": metric(42.8),
    }
    return {
        "cards": {
            card_id: {
                "metrics": {
                    STS1_ASC7PLUS_SOURCE_ID: source,
                }
            }
        }
    }


def _render_sts1_default(monkeypatch, source):
    snapshot = {"cards": {"CARNAGE": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)
    card = make_card(name="残杀", card_id="CARNAGE", game="sts1", pool="ironclad")
    return str(render_card_query_reply([card]))


def test_sts1_default_shows_first_pick_and_repick_but_hides_terminal_fields(monkeypatch):
    source = dict(
        make_sts1_snapshot("CARNAGE")["cards"]["CARNAGE"]["metrics"][
            STS1_ASC7PLUS_SOURCE_ID
        ]
    )
    source["heart_win_deck_presence_rate"] = metric(3.3333)

    reply = _render_sts1_default(monkeypatch, source)

    assert "对局结束时持有率" not in reply
    assert "结束时平均持有" not in reply
    assert "结束时升级比例" not in reply
    assert "心脏胜利卡组出现率" not in reply
    assert "第一次选择：平均第9层左右" in reply
    assert "再遇到：约19%会再拿一张" in reply


def test_sts1_default_keeps_act_pick_rate_and_win_delta(monkeypatch):
    source = make_sts1_snapshot("CARNAGE")["cards"]["CARNAGE"]["metrics"][
        STS1_ASC7PLUS_SOURCE_ID
    ]

    reply = _render_sts1_default(monkeypatch, source)

    assert "卡牌奖励：第一/二/三层 52.1% / 60.0% / 55.0% 会选" in reply
    assert "胜率关联：+2.5 / +1.0 / -2.0 个百分点" in reply
    assert "第一次选择：平均第9层左右" in reply
    assert "再遇到：约19%会再拿一张" in reply
    assert "幕" not in reply
    assert "胜率差仅代表统计关联。" not in reply


def test_sts2_default_hides_ending_presence(monkeypatch):
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = str(render_card_query_reply([make_card()]))

    assert "对局结束时持有率" not in reply


def test_sts2_default_shows_compact_stat_block(monkeypatch):
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = str(render_card_query_reply([make_card()]))

    assert "卡牌奖励：第一/二/三层 86% / 60% / 55% 会选" in reply
    assert "商店：37% / 44% / 44% 会买" in reply
    assert "休息时：25% / 14% / 10% 会敲牌" in reply
    assert "胜率关联：+2 / +1 / -2 个百分点" in reply
    assert "样本：第一/二/三层 4k / 15k / 7.4k 次" in reply
    assert "数据来源：Untapped" not in reply
    assert "幕" not in reply
    assert "Act" not in reply and "Run" not in reply
    assert "商店购买率" not in reply
    assert "升级率" not in reply
    assert "胜率差" not in reply
    assert "对局结束时持有率" not in reply


def test_sts1_single_card_query_includes_identity_and_stats(monkeypatch):
    card = make_card(name="残杀", card_id="CARNAGE", game="sts1", pool="ironclad")
    monkeypatch.setattr(
        "card_guess.qq.renderer.load_sts1_card_stats",
        lambda: make_sts1_snapshot("CARNAGE"),
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda queried_card: Path("/tmp/CARNAGE.png"),
    )
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_upgraded_card_image",
        lambda queried_card: None,
    )

    reply = render_card_query_reply([card])

    assert "=== 残杀 · STS1 · 铁甲战士 ===" in reply
    assert "=== 一代统计 ===" not in reply
    assert "卡牌奖励：第一/二/三层 52.1% / 60.0% / 55.0% 会选" in reply
    assert "胜率关联：+2.5 / +1.0 / -2.0 个百分点" in reply
    assert "第一次选择：平均第9层左右" in reply
    assert "再遇到：约19%会再拿一张" in reply
    assert "幕" not in reply
    assert "对局结束时持有率" not in reply
    assert "结束时平均持有" not in reply
    assert "结束时升级比例" not in reply
    assert "=== 二代统计 ===" not in reply
    assert "=== 卡牌资料 ===" not in reply
    assert "描述：" not in reply
    assert "费用：" not in reply
    assert "类型：" not in reply
    assert "稀有度：" not in reply
    assert "二代统计" not in reply
    assert reply.image_path == Path("/tmp/CARNAGE.png")


def test_sts1_missing_act_and_metric_show_dash_never_zero(monkeypatch):
    source = {
        "act_pick_rate": {
            "act_1": metric(52.1),
            "act_3": metric(55.0),
        },
        "act_win_delta": {
            "act_1": win_metric(2.5, 30, 30),
        },
        "final_deck_presence_rate": metric(3.2),
    }
    snapshot = {"cards": {"CARNAGE": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply(
        [make_card(name="残杀", card_id="CARNAGE", game="sts1", pool="ironclad")]
    )

    assert "卡牌奖励：第一/二/三层 52.1% / - / 55.0% 会选" in reply
    assert "胜率关联：+2.5 / - / - 个百分点" in reply
    assert "第一次选择" not in reply
    assert "再遇到" not in reply
    assert "对局结束时持有率" not in reply
    assert "结束时平均持有" not in reply
    assert "结束时升级比例" not in reply
    assert "0% / 0% / 0%" not in reply
    assert "0.0 / 0.0 / 0.0" not in reply
    assert "幕" not in reply


def test_sts1_win_delta_guard_hides_small_cohort_acts(monkeypatch):
    source = {
        "act_win_delta": {
            "act_1": win_metric(35.1, 2, 74),  # picked cohort too small
            "act_2": win_metric(4.9, 30, 300),
            "act_3": win_metric(1.2, 120, 25),  # comparison cohort too small
        },
    }
    snapshot = {"cards": {"CARNAGE": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply(
        [make_card(name="残杀", card_id="CARNAGE", game="sts1", pool="ironclad")]
    )

    assert "胜率关联：- / +4.9 / - 个百分点" in reply
    assert "35.1" not in reply
    assert "1.2" not in reply


def test_sts1_query_without_any_stats_still_renders_header_and_image(monkeypatch):
    card = make_card(name="疼痛", card_id="PAIN", game="sts1", pool="curse")
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda c: Path("/tmp/PAIN.png"),
    )
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([card])

    assert "=== 疼痛 · STS1 · 诅咒 ===" in reply
    assert "一代统计" not in reply
    assert "描述：" not in reply
    assert "费用：" not in reply
    assert reply.image_path == Path("/tmp/PAIN.png")


def test_sts1_stats_missing_snapshot_or_malformed_entry_is_safe(monkeypatch):
    card = make_card(name="残杀", card_id="CARNAGE", game="sts1", pool="ironclad")
    for bad_snapshot in [None, [], {"cards": None}, {"cards": {"CARNAGE": None}}]:
        monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: bad_snapshot)
        monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
        monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

        reply = render_card_query_reply([card])

        assert "=== 残杀 · STS1 · 铁甲战士 ===" in reply
        assert "一代统计" not in reply
        assert reply.image_paths == ()


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
    assert "=== 磨蚀 · STS2 · 静默猎手 ===" in reply
    assert "=== 二代统计 ===" not in reply
    assert "卡牌奖励：第一/二/三层 86% / 60% / 55% 会选" in reply
    assert "商店：37% / 44% / 44% 会买" in reply
    assert "休息时：25% / 14% / 10% 会敲牌" in reply
    assert "胜率关联：+2 / +1 / -2 个百分点" in reply
    assert "样本：第一/二/三层 4k / 15k / 7.4k 次" in reply
    assert "数据来源：Untapped" not in reply
    assert "幕" not in reply
    assert "对局结束时持有率" not in reply
    assert "描述：" not in reply
    assert "费用：" not in reply
    assert "类型：" not in reply
    assert "稀有度：" not in reply
    assert "=== 卡牌资料 ===" not in reply
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
                            "pick_rate": metric(86.0, sample_size=4000),
                            "run_win_rate_impact": metric(2.0, "percentage_points"),
                        },
                        "act_3": {"pick_rate": metric(55.0, sample_size=7400)},
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

    assert "=== 磨蚀 · STS2 · 静默猎手 ===" in reply
    assert "卡牌奖励：第一/二/三层 86% / - / 55% 会选" in reply
    assert "商店：37% / 44% / - 会买" in reply
    assert "铁匠铺" not in reply
    assert "胜率关联：+2 / - / - 个百分点" in reply
    assert "样本：第一/二/三层 4k / - / 7.4k 次" in reply
    assert "对局结束时持有率" not in reply
    assert "0% / 0% / 0%" not in reply
    assert "幕" not in reply


def test_sts2_query_without_any_stats_still_renders_card(monkeypatch):
    card = make_card(name="疯狂科学", card_id="MAD_SCIENCE")
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_card_image",
        lambda c: Path("/tmp/MAD_SCIENCE.png"),
    )
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([card])

    assert "=== 疯狂科学 · STS2 · 静默猎手 ===" in reply
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

    assert "=== 二代统计 ===" not in reply
    assert reply.image_paths == (Path("/tmp/ABRASIVE.png"),)


def test_sts2_query_with_only_final_deck_presence_hides_stats(monkeypatch):
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

    assert "=== 二代统计 ===" not in reply
    assert "对局结束时持有率" not in reply
    assert "第一/二/三幕" not in reply


def test_sts1_query_without_stats_shows_identity_only(monkeypatch):
    card = make_card(name="痛击", card_id="BASH", game="sts1", pool="ironclad")
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: {"cards": {}})
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: Path("/tmp/BASH.png"))

    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = render_card_query_reply([card])

    assert "=== 痛击 · STS1 · 铁甲战士 ===" in reply
    assert "=== 二代统计 ===" not in reply
    assert "第一/二/三幕" not in reply
    assert "一代统计" not in reply
    assert reply.image_path == Path("/tmp/BASH.png")
    assert reply.image_paths == (Path("/tmp/BASH.png"),)


def test_sts2_stats_missing_snapshot_or_malformed_entry_is_safe(monkeypatch):
    for bad_snapshot in [None, [], {"cards": None}, {"cards": {"ABRASIVE": None}}]:
        monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: bad_snapshot)
        monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
        monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

        reply = render_card_query_reply([make_card()])

        assert "=== 磨蚀 · STS2 · 静默猎手 ===" in reply
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


def test_route_group_command_sts2_suffix_query_hides_ending_presence(monkeypatch):
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

    assert "=== 白噪声 · STS2 · 故障机器人 ===" in reply
    assert "=== 二代统计 ===" not in reply
    assert "对局结束时持有率" not in reply
    assert reply.image_paths == (
        Path("/tmp/WHITE_NOISE_2.png"),
        Path("/tmp/upgraded/WHITE_NOISE_2.png"),
    )


def _render_sts1_query(monkeypatch, card_id, snapshot):
    card = make_card(name="残杀", card_id=card_id, game="sts1", pool="ironclad")
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)
    return str(render_card_query_reply([card]))


def test_sts1_default_hides_heart_presence_line(monkeypatch):
    source = {
        "act_pick_rate": {
            "act_1": metric(52.1),
            "act_2": metric(60.0),
            "act_3": metric(55.0),
        },
        "act_win_delta": {
            "act_1": win_metric(2.5, 30, 30),
            "act_2": win_metric(1.0, 30, 30),
            "act_3": win_metric(-2.0, 30, 30),
        },
        "first_pick_floor_mean": metric(8.7, "floor"),
        "repick_rate": metric(19.1),
        "final_deck_presence_rate": metric(2.9),
        "final_deck_copy_mean": metric(1.33, "copies"),
        "final_upgrade_rate": metric(42.8),
        "heart_win_deck_presence_rate": metric(3.3333),
    }
    snapshot = {"cards": {"CARNAGE": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    reply = _render_sts1_query(monkeypatch, "CARNAGE", snapshot)

    assert "卡牌奖励：第一/二/三层 52.1% / 60.0% / 55.0% 会选" in reply
    assert "胜率关联：+2.5 / +1.0 / -2.0 个百分点" in reply
    assert "心脏胜利卡组出现率" not in reply
    assert "对局结束时持有率" not in reply
    assert "第一次选择：平均第9层左右" in reply
    assert "再遇到：约19%会再拿一张" in reply


def test_sts1_heart_missing_stays_hidden(monkeypatch):
    source = {"final_deck_presence_rate": metric(2.9)}
    snapshot = {"cards": {"CARNAGE": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    reply = _render_sts1_query(monkeypatch, "CARNAGE", snapshot)

    assert "心脏胜利卡组出现率" not in reply
    assert "0.00%" not in reply


def test_sts2_reply_never_includes_heart_line(monkeypatch):
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: make_full_snapshot())
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = str(render_card_query_reply([make_card()]))

    assert "对局结束时持有率" not in reply
    assert "心脏" not in reply


def test_sts1_starter_card_heart_metric_stays_hidden(monkeypatch):
    card = make_card(name="打击", card_id="STRIKE_R", game="sts1", pool="ironclad")
    card["rarity"] = "Basic"
    source = {
        "final_deck_presence_rate": metric(9.0),
        "heart_win_deck_presence_rate": metric(2.25),
    }
    snapshot = {"cards": {"STRIKE_R": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)
    reply = str(render_card_query_reply([card]))
    assert "心脏胜利卡组出现率" not in reply
    assert "对局结束时持有率" not in reply



def test_sts1_repick_rate_hidden_below_sample_guard(monkeypatch):
    source = {
        "act_pick_rate": {
            act: metric(50.0)
            for act in ("act_1", "act_2", "act_3")
        },
        "repick_rate": metric(67.0, sample_size=50),
    }
    snapshot = {"cards": {"CARNAGE": {"metrics": {STS1_ASC7PLUS_SOURCE_ID: source}}}}
    reply = _render_sts1_query(monkeypatch, "CARNAGE", snapshot)
    assert "再遇到" not in reply
    assert "约67%" not in reply

    source["repick_rate"] = metric(67.0, sample_size=146)
    reply = _render_sts1_query(monkeypatch, "CARNAGE", snapshot)
    assert "再遇到：约67%会再拿一张" in reply


def test_sts2_sample_row_uses_compact_k(monkeypatch):
    snapshot = {
        "cards": {
            "ABRASIVE": {
                "id": "ABRASIVE",
                "untapped": {
                    "card_reward": {
                        "act_1": {"pick_rate": metric(86.0, sample_size=12500)},
                        "act_2": {"pick_rate": metric(60.0, sample_size=860)},
                        "act_3": {"pick_rate": metric(55.0, sample_size=999)},
                    }
                },
                "spire_codex": {},
            }
        }
    }
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = str(render_card_query_reply([make_card()]))

    assert "样本：第一/二/三层 12.5k / 860 / 999 次" in reply
    assert "12500" not in reply


def test_sts2_sample_row_hidden_without_sample_sizes(monkeypatch):
    snapshot = {
        "cards": {
            "ABRASIVE": {
                "id": "ABRASIVE",
                "untapped": {
                    "card_reward": {
                        act: {"pick_rate": metric_without_sample(86.0)}
                        for act in ("act_1", "act_2", "act_3")
                    }
                },
                "spire_codex": {},
            }
        }
    }
    monkeypatch.setattr("card_guess.qq.renderer.load_sts2_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None)

    reply = str(render_card_query_reply([make_card()]))

    assert "卡牌奖励：第一/二/三层 86% / 86% / 86% 会选" in reply
    assert "样本" not in reply

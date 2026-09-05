"""STS2 relic QQ query tests (ancient-choice snapshot).

The STS2 QQ relic path renders offer -> pick choice contexts from the
ancient_choice snapshot; the old same-tier presence-rank display is gone.
All relic/NPC ids and Chinese names in this file are fictional fixtures.
"""

from card_guess.qq import bot, renderer
from card_guess.qq.renderer import RenderedReply
from card_guess.sts2_ancient_choice import build_sts2_ancient_choice_snapshot


def make_sts2_relic(
    name="赤牛",
    relic_id="AKABEKO",
    name_en="Akabeko",
    tier="Uncommon",
    description="在每场战斗开始时获得[E]。",
):
    return {
        "game": "sts2",
        "id": relic_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": "At the start of each combat, gain 1 Energy.",
        "tier": tier,
        "color": None,
    }


def choice_row(relic_id, npc_id, act, offered, picked):
    return {
        "relic_id": relic_id,
        "npc_id": npc_id,
        "act": act,
        "offered_count": offered,
        "picked_rate": picked,
    }


def make_ancient_choice_snapshot():
    """Fictional ancient-choice snapshot around 量子回路 (QUANTUM_LOOP)."""
    return build_sts2_ancient_choice_snapshot(
        [
            choice_row("QUANTUM_LOOP", "TESTNPC", 2, 12000, 77),
            choice_row("PEER_RELIC", "TESTNPC", 2, 11000, 61),
        ],
        collected_at="2026-09-05T00:00:00Z",
        relic_names_zh={
            "QUANTUM_LOOP": "量子回路",
            "PEER_RELIC": "对照遗物",
        },
        npc_names_zh={"TESTNPC": "幻灵"},
    )


def patch_query_env(monkeypatch, relic, snapshot):
    monkeypatch.setattr(bot, "_load_query_cards", lambda: [], raising=False)
    monkeypatch.setattr(bot, "_load_query_relics", lambda: [], raising=False)
    monkeypatch.setattr(
        bot, "_load_sts2_query_relics", lambda: [relic], raising=False
    )
    monkeypatch.setattr(
        renderer, "load_sts2_ancient_choice_stats", lambda: snapshot
    )


# STS2 遗物统计：Ancient offer -> pick（不再展示同 tier 携带率排名） -----------


def test_sts2_ancient_choice_line_shows_rate_and_rank():
    relic = make_sts2_relic(
        name="量子回路", relic_id="QUANTUM_LOOP", tier="Ancient"
    )
    body = renderer.render_sts2_ancient_choice_stats(
        relic, make_ancient_choice_snapshot()
    )
    assert "幻灵 · 第二幕：出现时约77%会选，选择率第1 / 2。" in body
    for banned in ["同级遗物携带率", "携带率", "picks", "presence"]:
        assert banned not in body


def test_sts2_ancient_choice_stats_empty_without_context():
    relic = make_sts2_relic(
        name="未知遗物", relic_id="NO_CONTEXT", tier="Ancient"
    )
    body = renderer.render_sts2_ancient_choice_stats(
        relic, make_ancient_choice_snapshot()
    )
    assert body == ""


def test_sts2_ancient_choice_stats_empty_for_non_ancient_relic():
    relic = make_sts2_relic()
    body = renderer.render_sts2_ancient_choice_stats(
        relic, make_ancient_choice_snapshot()
    )
    assert body == ""


# QQ 闭环：遗物名2 渲染二代遗物（Ancient choice 段落） ------------------------


def test_generation_suffix_2_renders_sts2_ancient_choice(monkeypatch, tmp_path):
    relic = make_sts2_relic(
        name="量子回路",
        relic_id="QUANTUM_LOOP",
        name_en="Quantum Loop",
        tier="Ancient",
        description="在每回合开始时，获得[E]。",
    )
    snapshot = make_ancient_choice_snapshot()
    patch_query_env(monkeypatch, relic, snapshot)
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path / "empty-repo")

    reply = bot.route_group_command(101, "量子回路2")

    assert isinstance(reply, RenderedReply)
    assert "=== 量子回路 · STS2 ===" in reply
    assert "效果：\n在每回合开始时，获得⚡。" in reply
    assert "\n先古遗物\n" in reply
    assert "幻灵 · 第二幕：出现时约77%会选，选择率第1 / 2。" in reply
    for banned in [
        "同级遗物携带率",
        "携带率",
        "胜率",
        "终局",
        "picks",
        "denominator",
        "sample_size",
    ]:
        assert banned not in reply
    assert reply.image_path is None


def test_sts2_relic_without_tier_hides_blank_tier_line(monkeypatch):
    relic = make_sts2_relic(
        name="头环",
        relic_id="CIRCLET",
        name_en="Circlet",
        tier="None",
        description="这是一个头环。",
    )
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})

    reply = renderer.render_relic_query_reply([relic])

    assert "=== 头环 · STS2 ===" in reply
    assert "效果：\n这是一个头环。" in reply
    assert "None" not in reply
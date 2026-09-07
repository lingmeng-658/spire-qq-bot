"""QQ STS2 relic shop-stat display tests.

Non-Ancient STS2 relics with a real Shop Stats snapshot render a compact
bought-rate / run-impact / sample block.  All relic ids and Chinese names
below are fictional fixtures; no QQ message or private user data is used.
"""

from card_guess.qq import renderer
from card_guess.qq.renderer import RenderedReply


def make_relic(relic_id="BELT_BUCKLE", name="腰带扣", name_en="Belt Buckle", tier="Shop"):
    return {
        "game": "sts2",
        "id": relic_id,
        "name": name,
        "name_en": name_en,
        "description": "在商店出现时更容易被注意到。",
        "description_en": "Shown more often in shops.",
        "tier": tier,
        "color": None,
    }


def metric(value, unit="percent"):
    return {"value": value, "unit": unit}


def shop_snapshot(belt_rows=None):
    relics = {}
    if belt_rows is not None:
        relics["BELT_BUCKLE"] = {
            "id": "BELT_BUCKLE",
            "name_en": "Belt Buckle",
            "tier": "Shop",
            "shop": belt_rows,
        }
    return {
        "schema_version": "1.0.0",
        "game": "sts2",
        "source": "untapped",
        "relics": relics,
    }


FULL_SHOP = {
    "act_1": {
        "offered": 34000,
        "purchase_rate": metric(5.0),
        "act_win_rate_impact": metric(2.0, "percentage_points"),
        "run_win_rate_impact": metric(4.0, "percentage_points"),
    },
    "act_2": {
        "offered": 21000,
        "purchase_rate": metric(10.0),
        "act_win_rate_impact": metric(3.0, "percentage_points"),
        "run_win_rate_impact": metric(3.0, "percentage_points"),
    },
    "act_3": {
        "offered": 11000,
        "purchase_rate": metric(22.0),
        "act_win_rate_impact": metric(-1.0, "percentage_points"),
        "run_win_rate_impact": metric(2.0, "percentage_points"),
    },
}


def test_shop_block_renders_compact_rows_in_order():
    relic = make_relic()
    body = renderer.render_sts2_relic_shop_stats(relic, shop_snapshot(FULL_SHOP))
    assert body == (
        "商店：第一/二/三层 5% / 10% / 22% 会买\n"
        "胜率关联：+4 / +3 / +2 个百分点\n"
        "样本：第一/二/三层 34k / 21k / 11k 次"
    )


def test_shop_block_uses_only_run_impact_for_win_row():
    rows = {
        "act_1": {
            "offered": 500,
            "purchase_rate": metric(37.0),
            "act_win_rate_impact": metric(99.0, "percentage_points"),
            "run_win_rate_impact": metric(-2.0, "percentage_points"),
        }
    }
    body = renderer.render_sts2_relic_shop_stats(make_relic(), shop_snapshot(rows))
    assert "胜率关联：-2 / - / - 个百分点" in body
    assert "99" not in body


def test_shop_block_shows_dash_for_missing_act():
    rows = {"act_1": {"offered": 4000, "purchase_rate": metric(37.0)}}
    body = renderer.render_sts2_relic_shop_stats(make_relic(), shop_snapshot(rows))
    assert body == (
        "商店：第一/二/三层 37% / - / - 会买\n"
        "样本：第一/二/三层 4k / - / - 次"
    )


def test_shop_block_empty_when_no_rendered_act_data():
    assert renderer.render_sts2_relic_shop_stats(make_relic(), shop_snapshot({})) == ""
    assert renderer.render_sts2_relic_shop_stats(make_relic(), shop_snapshot(None)) == ""
    assert (
        renderer.render_sts2_relic_shop_stats(
            make_relic(), shop_snapshot({"act_1": {"offered": 0}})
        )
        == ""
    )


def test_full_reply_appends_shop_block_for_shop_relic(monkeypatch):
    relic = make_relic()
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})
    monkeypatch.setattr(
        renderer,
        "load_sts2_relic_shop_stats",
        lambda: shop_snapshot(FULL_SHOP),
    )
    reply = renderer.render_relic_query_reply([relic])
    assert isinstance(reply, RenderedReply)
    assert "=== 腰带扣 · STS2 ===" in reply.text
    assert "商店：第一/二/三层 5% / 10% / 22% 会买" in reply.text
    assert "胜率关联：+4 / +3 / +2 个百分点" in reply.text
    assert "样本：第一/二/三层 34k / 21k / 11k 次" in reply.text
    for banned in ("数据来源", "Act", "Run", "强度"):
        assert banned not in reply.text


def test_full_reply_keeps_basic_copy_when_no_shop_data(monkeypatch):
    relic = make_relic()
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})
    monkeypatch.setattr(renderer, "load_sts2_relic_shop_stats", lambda: shop_snapshot(None))
    reply = renderer.render_relic_query_reply([relic])
    assert "商店：" not in reply.text
    assert "效果：" in reply.text
    assert "商店遗物" in reply.text


def test_ancient_relic_never_queries_shop_snapshot(monkeypatch):
    relic = make_relic(relic_id="QUANTUM_LOOP", name="量子回路", tier="Ancient")

    def boom():
        raise AssertionError("ancient relic must not load shop stats")

    monkeypatch.setattr(renderer, "load_sts2_relic_shop_stats", boom)
    monkeypatch.setattr(
        renderer,
        "load_sts2_ancient_choice_stats",
        lambda: {
            "ancient_choice": {
                "contexts": [
                    {
                        "relic_id": "QUANTUM_LOOP",
                        "npc_id": "TESTNPC",
                        "npc_name_zh": "幻灵",
                        "act": 2,
                        "picked_rate": 77.0,
                        "rank": 1,
                        "cohort_size": 2,
                    }
                ]
            }
        },
    )
    reply = renderer.render_relic_query_reply([relic])
    assert "幻灵 · 第二层" in reply.text
    assert "商店：" not in reply.text


def test_full_reply_renders_when_snapshot_carries_unresolved_statuses(monkeypatch):
    snapshot = shop_snapshot(FULL_SHOP)
    snapshot["shop_eligible_ids"] = ["BELT_BUCKLE"]
    snapshot["unresolved"] = [
        {"id": "AKABEKO", "status": "insufficient"},
        {"id": "AMETHYST_AUBERGINE", "status": "no_shop_stats"},
    ]
    relic = make_relic()
    monkeypatch.setattr(renderer, "load_sts2_ancient_choice_stats", lambda: {})
    monkeypatch.setattr(renderer, "load_sts2_relic_shop_stats", lambda: snapshot)
    reply = renderer.render_relic_query_reply([relic])
    assert "商店：第一/二/三层 5% / 10% / 22% 会买" in reply.text
    assert "样本：第一/二/三层 34k / 21k / 11k 次" in reply.text


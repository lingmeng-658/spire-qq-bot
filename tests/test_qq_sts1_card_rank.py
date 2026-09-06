"""STS1 single-card QQ default output: same-rarity pick-rank row.

The row only renders for character-pool cards in rankable rarities
(Common/Uncommon/Rare) that met the recorded-offer sample floor in at least
one act.  Acts without a valid rank render ``-``.
"""

from card_guess.qq.renderer import (
    STS1_ASC7PLUS_SOURCE_ID,
    render_card_query_reply,
)

SRC = STS1_ASC7PLUS_SOURCE_ID


def make_card(name="残杀", card_id="CARNAGE", game="sts1", pool="ironclad", rarity="Common"):
    return {
        "name": name,
        "game": game,
        "id": card_id,
        "pool": pool,
        "type": "Attack",
        "cost": 2,
        "star_cost": None,
        "rarity": rarity,
        "description": "造成 6 点伤害。",
        "vars": {},
    }


def metric(value, unit="percent"):
    return {"value": value, "unit": unit, "sample_size": 100}


def cell(offered, picked):
    return {"offered_count": offered, "picked_count": picked}


def _source(pick_acts, win_delta_acts, contexts):
    return {
        "act_pick_rate": {act: metric(pick) for act, pick in pick_acts.items()},
        "act_win_delta": {
            act: {
                "value": delta,
                "unit": "percentage_points",
                "numerator": 5,
                "denominator": 20,
                "comparison_numerator": 0,
                "comparison_denominator": 20,
                "sample_size": 40,
            }
            for act, delta in win_delta_acts.items()
        },
        "character_pick_contexts": contexts,
    }


def _card_entry(color, rarity, source):
    return {"color": color, "rarity": rarity, "metrics": {SRC: source}}


def _render(monkeypatch, card, snapshot):
    monkeypatch.setattr("card_guess.qq.renderer.load_sts1_card_stats", lambda: snapshot)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda c: None)
    monkeypatch.setattr(
        "card_guess.qq.renderer.resolve_local_upgraded_card_image", lambda c: None
    )
    return str(render_card_query_reply([card]))


def _cohort_snapshot():
    """Two ironclad Common cards; CARNAGE is below CLASH in act_1."""
    return {
        "cards": {
            "CARNAGE": _card_entry(
                "ironclad",
                "Common",
                _source(
                    {"act_1": 60.0, "act_2": 25.0},
                    {"act_1": 2.5, "act_2": 1.0},
                    {
                        "ironclad": {
                            "act_1": cell(200, 120),
                            "act_2": cell(160, 40),
                        }
                    },
                ),
            ),
            "CLASH": _card_entry(
                "ironclad",
                "Common",
                _source(
                    {"act_1": 90.0},
                    {"act_1": 3.0},
                    {"ironclad": {"act_1": cell(200, 180)}},
                ),
            ),
        }
    }


def test_sts1_default_adds_same_rarity_rank_row_under_pick_line(monkeypatch):
    reply = _render(monkeypatch, make_card(), _cohort_snapshot())

    assert (
        "卡牌奖励出现时：\n第一/二/三幕：60.0% / 25.0% / - 会选\n\n"
        "同稀有度选择率排名：\n第一/二/三幕：2/2 · 1/1 · -" in reply
    )
    # The rank row sits below the pick line and above the win-delta note.
    assert reply.index("同稀有度选择率排名") > reply.index("卡牌奖励出现时")
    assert reply.index("胜率关联") > reply.index("同稀有度选择率排名")


def test_sts1_rank_row_hides_entirely_without_any_rankable_act(monkeypatch):
    snapshot = {
        "cards": {
            "CARNAGE": _card_entry(
                "ironclad",
                "Common",
                _source(
                    {"act_1": 60.0},
                    {"act_1": 2.5},
                    {"ironclad": {"act_1": cell(10, 6)}},
                ),
            )
        }
    }
    reply = _render(monkeypatch, make_card(), snapshot)
    assert "卡牌奖励出现时" in reply
    assert "同稀有度选择率排名" not in reply


def test_sts1_colorless_and_basic_cards_never_render_rank_row(monkeypatch):
    colorless_card = make_card(name="发现", card_id="DISCOVERY", pool="colorless", rarity="Uncommon")
    colorless_snapshot = {
        "cards": {
            "DISCOVERY": _card_entry(
                "colorless",
                "Uncommon",
                _source(
                    {"act_1": 90.0},
                    {"act_1": 3.0},
                    {
                        "ironclad": {"act_1": cell(200, 180)},
                        "silent": {"act_1": cell(200, 160)},
                    },
                ),
            )
        }
    }
    reply = _render(monkeypatch, colorless_card, colorless_snapshot)
    assert "同稀有度选择率排名" not in reply

    starter_card = make_card(name="打击", card_id="STRIKE_R", rarity="Basic")
    starter_snapshot = {
        "cards": {
            "STRIKE_R": _card_entry(
                "ironclad",
                "Basic",
                _source({"act_1": 50.0}, {"act_1": 1.0}, {"ironclad": {"act_1": cell(200, 100)}}),
            )
        }
    }
    reply = _render(monkeypatch, starter_card, starter_snapshot)
    assert "同稀有度选择率排名" not in reply
    assert "卡牌奖励出现时" in reply
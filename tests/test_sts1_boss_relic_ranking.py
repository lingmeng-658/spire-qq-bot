# -*- coding: utf-8 -*-
"""STS1 Boss relic choice: per-act competition ranking (RED targets).

Ranks only compare one act's boss-reward cohort.  Every fixture below uses
fictional snapshot data so no real QQ message or private user data is needed.
"""

from card_guess.qq import renderer
from card_guess.relic_stats import (
    boss_choice_act_rows,
    boss_choice_rank_contexts,
)

ALL_ROLES = {
    "IRONCLAD": 30.0,
    "THE_SILENT": 30.0,
    "DEFECT": 30.0,
    "WATCHER": 30.0,
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


def boss_act(offered, picked):
    return {
        "offered_count": count(offered),
        "picked_count": count(picked),
        "pick_rate": rate(picked / offered * 100.0, picked, offered),
    }


def boss_choice_snapshot(act_offers):
    """Build a relic snapshot from ``{relic_id: {act: (offered, picked)}}``."""
    relics = {}
    for relic_id, acts in act_offers.items():
        entry = {
            "overall": rate(40.0, 4000, 10000),
            "per_character": {
                role: rate(value) for role, value in ALL_ROLES.items()
            },
            "supported_roles": list(ALL_ROLES),
        }
        choice = {}
        for act_key in ("act1", "act2"):
            if act_key in acts:
                offered, picked = acts[act_key]
                choice[act_key] = boss_act(offered, picked)
        if choice:
            entry["boss_choice"] = choice
        relics[relic_id] = entry
    return {"relics": relics}


def make_boss_relic(relic_id="SOZU", name="添水", tier="Boss"):
    return {
        "game": "sts1",
        "id": relic_id,
        "name": name,
        "name_en": relic_id,
        "description": "每场战斗开始时获得 1 点能量。",
        "description_en": "fictional description",
        "tier": tier,
        "color": None,
    }


# --- Data layer: ranks stay inside one act cohort --------------------------


def test_boss_choice_ranks_each_act_without_merging():
    snapshot = boss_choice_snapshot({
        "SOZU": {"act1": (3000, 1200), "act2": (1100, 220)},      # 40% / 20%
        "CALLING_BELL": {"act1": (2000, 1000), "act2": (3000, 2700)},  # 50% / 90%
        "SLAVERS_COLLAR": {"act1": (9000, 2700), "act2": (2500, 250)},  # 30% / 10%
    })
    contexts = boss_choice_rank_contexts(snapshot, "SOZU")
    by_act = {context["act"]: context for context in contexts}

    # Act 1 cohort: CALLING_BELL 50 > SOZU 40 > SLAVERS_COLLAR 30.
    assert by_act["act1"]["rank"] == 2
    assert by_act["act1"]["cohort_size"] == 3
    # Act 2 cohort: CALLING_BELL 90 > SOZU 20 > SLAVERS_COLLAR 10; rank/cohort
    # numbers are act-local, proving the two acts never share one cohort.
    assert by_act["act2"]["rank"] == 2
    assert by_act["act2"]["cohort_size"] == 3


def test_boss_choice_competition_rank_ties_keep_same_rank():
    snapshot = boss_choice_snapshot({
        "SOZU": {"act1": (3000, 1200)},          # 40%
        "CALLING_BELL": {"act1": (9000, 3600)},  # 40% ties SOZU
        "SLAVERS_COLLAR": {"act1": (2000, 1000)},  # 50%
        "ECTOPLASM": {"act1": (1500, 450)},      # 30%
    })
    rows = {row["relic_id"]: row for row in boss_choice_act_rows(snapshot, "act1")}

    assert rows["SLAVERS_COLLAR"]["rank"] == 1
    assert rows["SOZU"]["rank"] == rows["CALLING_BELL"]["rank"] == 2
    assert rows["ECTOPLASM"]["rank"] == 4  # competition ranking leaves the gap
    assert rows["SOZU"]["cohort_size"] == 4


def test_boss_choice_display_rounding_does_not_tie_distinct_rates():
    # 40.033...% and 39.956...% both display as 40.0%, but their real
    # picked_count / offered_count ratios differ, so ranks must differ.
    snapshot = boss_choice_snapshot({
        "SOZU": {"act1": (3000, 1201)},          # 40.033...%
        "CALLING_BELL": {"act1": (9000, 3596)},  # 39.956...%
        "SLAVERS_COLLAR": {"act1": (2000, 1000)},  # 50%
        "ECTOPLASM": {"act1": (1500, 450)},      # 30%
    })
    rows = {row["relic_id"]: row for row in boss_choice_act_rows(snapshot, "act1")}

    # Same 1-decimal display (40.0%) must not create a tie on real rates.
    assert rows["SLAVERS_COLLAR"]["rank"] == 1
    assert rows["SOZU"]["rank"] == 2
    assert rows["CALLING_BELL"]["rank"] == 3
    assert rows["ECTOPLASM"]["rank"] == 4


def test_boss_choice_low_sample_relics_never_enter_cohort():
    # ECTOPLASM has a tiny offer sample: it must not rank, must not inflate
    # cohort_size, and its own low-sample act returns no context.
    snapshot = boss_choice_snapshot({
        "SOZU": {"act1": (3000, 1200), "act2": (3000, 300)},
        "ECTOPLASM": {"act1": (4, 1), "act2": (900, 810)},
    })
    act1_rows = boss_choice_act_rows(snapshot, "act1")
    assert len(act1_rows) == 1
    assert act1_rows[0]["relic_id"] == "SOZU"
    assert act1_rows[0]["cohort_size"] == 1

    contexts = boss_choice_rank_contexts(snapshot, "ECTOPLASM")
    assert contexts == []


# --- QQ layer: Boss reply shows choice rate + same-act rank -----------------


def test_boss_relic_query_shows_per_act_choice_rate_and_rank(monkeypatch):
    snapshot = boss_choice_snapshot({
        "SOZU": {"act1": (3000, 1200), "act2": (3000, 300)},   # 40% / 10%
        "CALLING_BELL": {"act1": (9000, 5400), "act2": (9000, 7200)},  # 60%/80%
        "SLAVERS_COLLAR": {"act1": (2000, 1000), "act2": (2000, 200)},  # 50%/10%
        "RING_OF_THE_SERPENT": {"act1": (5000, 1000), "act2": (999, 900)},  # low sample
    })
    monkeypatch.setattr(
        "card_guess.qq.renderer.load_sts1_relic_stats", lambda: snapshot
    )
    reply = str(renderer.render_relic_query_reply([make_boss_relic()]))

    assert "=== 添水 · STS1 ===" in reply
    assert "\nBoss 遗物\n" in reply
    # Act 1 ranks SOZU 3rd of 4 rankable relics.
    assert "第一层 Boss 奖励：\n约40.0%会选，选择率第 3 / 4。" in reply
    # Act 2 ranks SOZU joint 2nd of 3 (10% ties SLAVERS_COLLAR; RING excluded).
    assert "第二层 Boss 奖励：\n约10.0%会选，选择率第 2 / 3。" in reply
    assert "Boss奖励出现时：" not in reply
    # Presence / heart copy stays out of the default Boss display.
    assert "带着它。" not in reply


def test_boss_relic_query_hides_low_sample_act_entirely(monkeypatch):
    snapshot = boss_choice_snapshot({
        "ECTOPLASM": {"act1": (4, 1), "act2": (3000, 2700)},  # 25% / 90%
    })
    monkeypatch.setattr(
        "card_guess.qq.renderer.load_sts1_relic_stats", lambda: snapshot
    )
    relic = make_boss_relic(relic_id="ECTOPLASM", name="LowSample")
    reply = str(renderer.render_relic_query_reply([relic]))

    assert "第一层 Boss 奖励：" not in reply
    assert "第二层 Boss 奖励：\n约90.0%会选，选择率第 1 / 1。" in reply

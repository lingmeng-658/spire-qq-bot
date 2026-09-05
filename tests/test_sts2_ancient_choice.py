"""STS2 Ancient choice snapshot core tests (fictional data only).

The fixtures use fictional NPC ids (FOO/BAR), fictional relic ids and
fictional official-style Chinese names so the tests never depend on live
Untapped pages or real run data.
"""

from __future__ import annotations

import pytest

from card_guess.sts2_ancient_choice import (
    ANCIENT_CHOICE_MIN_OFFERED,
    ACT_ZH,
    audit_ancient_pool_mapping,
    build_sts2_ancient_choice_snapshot,
    leaderboard_contexts,
    leaderboard_npc_acts,
    npc_name_zh_for,
    parse_pool_act_restrictions,
    parse_untapped_ancient_choice_page,
    rankable_contexts_for_relic,
    validate_sts2_ancient_choice_snapshot,
)

RELIC_ZH = {
    "REL_A": "幻想遗物甲",
    "REL_B": "幻想遗物乙",
    "REL_C": "幻想遗物丙",
    "REL_D": "幻想遗物丁",
    "REL_E": "幻想遗物戊",
    "REL_F": "幻想遗物己",
}
NPC_ZH = {"FOO": "幻灵", "BAR": "幻影"}


def _row(relic_id, npc_id, act, offered, picked):
    return {
        "relic_id": relic_id,
        "npc_id": npc_id,
        "act": act,
        "offered_count": offered,
        "picked_rate": picked,
    }


def _build(rows=None, **kwargs):
    defaults = {
        "rows": [
            _row("REL_A", "FOO", 2, 4000, 60),
            _row("REL_B", "FOO", 2, 3000, 40),
            _row("REL_C", "FOO", 2, 2000, 35),
        ],
        "collected_at": "2026-09-05T00:00:00Z",
        "relic_names_zh": RELIC_ZH,
        "npc_names_zh": NPC_ZH,
    }
    if rows is not None:
        defaults["rows"] = rows
    defaults.update(kwargs)
    return build_sts2_ancient_choice_snapshot(**defaults)


# Ancient pool mapping -------------------------------------------------------

def _pools():
    return [
        {
            "id": "FOO",
            "name": "Foo",
            "pools": [
                {
                    "name": "Relic Pool",
                    "relics": [
                        {"id": "REL_A", "condition": None},
                        {"id": "REL_B", "condition": "Act 2 only"},
                        {"id": "REL_X", "condition": None},
                    ],
                }
            ],
        },
        {
            "id": "BAR",
            "name": "Bar",
            "pools": [
                {
                    "name": "Relic Pool",
                    "relics": [
                        {"id": "REL_C", "condition": None},
                        {"id": "REL_X", "condition": "50% chance (vs REL_A)"},
                    ],
                }
            ],
        },
    ]


def test_audit_pool_mapping_reports_multinpc_and_unresolved():
    audit = audit_ancient_pool_mapping(
        _pools(),
        ancient_relic_ids={"REL_A", "REL_B", "REL_C", "REL_D"},
    )
    assert audit["total_pool_relic_ids"] == 4
    assert audit["npc_count"] == 2
    assert audit["multi_npc"] == ["REL_X"]
    assert audit["missing_from_pools"] == ["REL_D"]
    assert audit["unresolved_relic_ids"] == []
    assert audit["npc_localization_unresolved"] == ["FOO", "BAR"]


def test_audit_pool_mapping_resolves_official_npc_names():
    audit = audit_ancient_pool_mapping(
        _pools(),
        ancient_relic_ids={"REL_A", "REL_B", "REL_C", "REL_X"},
        npc_name_zh=NPC_ZH,
    )
    assert audit["npc_localization_unresolved"] == []
    assert audit["relic_to_npc"]["REL_A"] == "FOO"
    assert audit["relic_to_npc"]["REL_B"] == "FOO"
    assert audit["relic_to_npc"]["REL_C"] == "BAR"


def test_parse_pool_act_restrictions():
    assert parse_pool_act_restrictions(None) is None
    assert parse_pool_act_restrictions("Act 2 only") == frozenset({2})
    assert parse_pool_act_restrictions("Act 2 only; 50% chance (vs Sozu)") == frozenset({2})
    assert parse_pool_act_restrictions("Act 1-2 only") == frozenset({1, 2})
    assert parse_pool_act_restrictions("Act 1\u20132 only") == frozenset({1, 2})
    assert parse_pool_act_restrictions("Act 2+") == frozenset({2, 3})
    assert parse_pool_act_restrictions("Excluded with Draft modifier") is None
    assert parse_pool_act_restrictions("Single player only") is None


# Snapshot building & ranking ------------------------------------------------

def test_build_snapshot_ranks_within_npc_act_cohort():
    snapshot = _build()
    contexts = snapshot["ancient_choice"]["contexts"]
    by_id = {ctx["relic_id"]: ctx for ctx in contexts}
    assert by_id["REL_A"]["rank"] == 1
    assert by_id["REL_B"]["rank"] == 2
    assert by_id["REL_C"]["rank"] == 3
    assert by_id["REL_A"]["cohort_size"] == 3
    assert by_id["REL_A"]["invalid_for_ranking"] is False
    assert snapshot["schema_version"] == "1.0.0"
    assert snapshot["game"] == "sts2"
    assert snapshot["ancient_choice"]["contexts"]
    assert snapshot["sample_policy"]["minimum_offered"] == ANCIENT_CHOICE_MIN_OFFERED


def test_build_snapshot_tie_breaks_by_offered_then_relic_id():
    rows = [
        _row("REL_A", "FOO", 2, 1000, 60),
        _row("REL_B", "FOO", 2, 4000, 60),
        _row("REL_C", "FOO", 2, 1000, 40),
    ]
    contexts = _build(rows=rows)["ancient_choice"]["contexts"]
    order = [ctx["relic_id"] for ctx in contexts]
    assert order == ["REL_B", "REL_A", "REL_C"]
    ranks = {ctx["relic_id"]: ctx["rank"] for ctx in contexts}
    assert ranks == {"REL_A": 1, "REL_B": 1, "REL_C": 3}


def test_build_snapshot_tie_breaks_by_relic_id_when_equal():
    rows = [
        _row("REL_B", "FOO", 2, 3000, 60),
        _row("REL_A", "FOO", 2, 3000, 60),
    ]
    contexts = _build(rows=rows)["ancient_choice"]["contexts"]
    assert [ctx["relic_id"] for ctx in contexts] == ["REL_A", "REL_B"]
    ranks = {ctx["relic_id"]: ctx["rank"] for ctx in contexts}
    assert ranks == {"REL_A": 1, "REL_B": 1}


def test_build_snapshot_multiact_contexts_rank_separately():
    rows = [
        _row("REL_A", "FOO", 2, 4000, 60),
        _row("REL_B", "FOO", 2, 3000, 40),
        _row("REL_A", "FOO", 3, 5000, 30),
        _row("REL_C", "FOO", 3, 9000, 55),
    ]
    snapshot = _build(rows=rows)
    by_id = {(ctx["relic_id"], ctx["act"]): ctx for ctx in snapshot["ancient_choice"]["contexts"]}
    assert by_id[("REL_A", 2)]["rank"] == 1
    assert by_id[("REL_A", 2)]["cohort_size"] == 2
    assert by_id[("REL_A", 3)]["rank"] == 2
    assert by_id[("REL_A", 3)]["cohort_size"] == 2
    assert by_id[("REL_C", 3)]["rank"] == 1
    relic_rows = rankable_contexts_for_relic(snapshot, "REL_A")
    assert [(ctx["act"], ctx["rank"]) for ctx in relic_rows] == [(2, 1), (3, 2)]


def test_low_sample_rows_are_marked_and_excluded_from_ranking():
    rows = [
        _row("REL_A", "FOO", 2, 5000, 60),
        _row("REL_B", "FOO", 2, 500, 90),
    ]
    snapshot = _build(rows=rows)
    contexts = {ctx["relic_id"]: ctx for ctx in snapshot["ancient_choice"]["contexts"]}
    assert contexts["REL_A"]["rank"] == 1
    assert contexts["REL_A"]["cohort_size"] == 1
    assert contexts["REL_B"]["rank"] is None
    assert contexts["REL_B"]["invalid_for_ranking"] is True
    assert contexts["REL_B"]["cohort_size"] == 1
    assert [ctx["relic_id"] for ctx in leaderboard_contexts(snapshot, "FOO", 2)] == ["REL_A"]
    assert rankable_contexts_for_relic(snapshot, "REL_B") == []


def test_leaderboard_contexts_never_mix_acts():
    rows = [
        _row("REL_A", "FOO", 2, 4000, 60),
        _row("REL_B", "FOO", 2, 3000, 40),
        _row("REL_A", "FOO", 3, 5000, 30),
    ]
    snapshot = _build(rows=rows)
    act2 = leaderboard_contexts(snapshot, "FOO", 2)
    act3 = leaderboard_contexts(snapshot, "FOO", 3)
    assert {ctx["relic_id"] for ctx in act2} == {"REL_A", "REL_B"}
    assert {ctx["relic_id"] for ctx in act3} == {"REL_A"}
    assert leaderboard_npc_acts(snapshot, "FOO") == (2, 3)
    assert npc_name_zh_for(snapshot, "FOO") == "幻灵"


def test_build_snapshot_duplicate_context_raises():
    rows = [
        _row("REL_A", "FOO", 2, 4000, 60),
        _row("REL_A", "FOO", 2, 4000, 60),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        _build(rows=rows)


def test_build_snapshot_requires_official_zh_relic_name():
    rows = [_row("REL_MISSING", "FOO", 2, 4000, 60)]
    with pytest.raises(ValueError, match="REL_MISSING"):
        _build(rows=rows)


def test_build_snapshot_keeps_unresolved_npc_localization_explicit():
    rows = [_row("REL_A", "ZZZ", 2, 4000, 60)]
    snapshot = _build(rows=rows)
    ctx = snapshot["ancient_choice"]["contexts"][0]
    assert ctx["npc_name_zh"] is None
    assert snapshot["unresolved_localization"] == [
        {"npc_id": "ZZZ", "reason": "npc_zh_name_unresolved"}
    ]
    assert npc_name_zh_for(snapshot, "ZZZ") is None
    validate_sts2_ancient_choice_snapshot(snapshot)


def test_build_snapshot_rejects_invalid_act():
    rows = [_row("REL_A", "FOO", 4, 4000, 60)]
    with pytest.raises(ValueError, match="act"):
        _build(rows=rows)


def test_build_snapshot_competition_ranking_skips_numbers():
    rates = [58, 53, 45, 34, 33, 29, 29, 19, 16, 16]
    rows = [
        _row(f"REL_{index:02d}", "FOO", 2, 4000 - index * 100, rate)
        for index, rate in enumerate(rates, start=1)
    ]
    fixture_zh_names = list(RELIC_ZH.values())
    relic_names_zh = {
        **RELIC_ZH,
        **{
            f"REL_{index:02d}": fixture_zh_names[(index - 1) % len(fixture_zh_names)]
            for index in range(1, len(rates) + 1)
        },
    }
    snapshot = _build(rows=rows, relic_names_zh=relic_names_zh)
    contexts = snapshot["ancient_choice"]["contexts"]
    ranks = [ctx["rank"] for ctx in contexts]
    assert ranks == [1, 2, 3, 4, 5, 6, 6, 8, 9, 9]



def test_validate_snapshot_rejects_tampered_rank():
    snapshot = _build()
    snapshot["ancient_choice"]["contexts"][0]["rank"] = None
    with pytest.raises(ValueError):
        validate_sts2_ancient_choice_snapshot(snapshot)


def test_validate_snapshot_rejects_rank_out_of_cohort_range():
    snapshot = _build()
    snapshot["ancient_choice"]["contexts"][0]["rank"] = 99
    with pytest.raises(ValueError):
        validate_sts2_ancient_choice_snapshot(snapshot)


def test_rankable_contexts_for_relic_empty_when_unknown():
    snapshot = _build()
    assert rankable_contexts_for_relic(snapshot, "NO_SUCH_RELIC") == []


def test_act_zh_labels_are_official_style():
    assert ACT_ZH == {1: "第一幕", 2: "第二幕", 3: "第三幕"}


# Untapped page parsing -------------------------------------------------------

_HTML_FIXTURE = """
<div hidden id="S:1"><section><h2>Fictional Relic <span>Ancient Choice</span> Stats</h2>
<div class="StatsSection-module-scss-module__container">
<div class="StatCell-module-scss-module__cell"><div class="StatCell-module-scss-module__header">
<span class="StatCell-module-scss-module__label">In Act 1</span></div>
<div class="StatCell-module-scss-module__content">
<div class="StatCell-module-scss-module__lowData">—</div></div></div>
<div class="StatCell-module-scss-module__cell" style="--gradient:#a9792c">
<div class="StatCell-module-scss-module__header">
<span class="StatCell-module-scss-module__label">In Act 2</span>
<span class="StatCell-module-scss-module__offered">offered 11,000 times</span></div>
<div class="StatCell-module-scss-module__content">
<div class="StatsSection-module-scss-module__dataRow">
<div class="StatsSection-module-scss-module__pickRate"><span>Picked</span><strong>19<!-- -->%</strong></div>
</div></div></div>
<div class="StatCell-module-scss-module__cell"><div class="StatCell-module-scss-module__header">
<span class="StatCell-module-scss-module__label">In Act 3</span></div>
<div class="StatCell-module-scss-module__content">
<div class="StatCell-module-scss-module__lowData">—</div></div></div>
</div></section></div>
"""


def test_parse_untapped_page_extracts_choice_rows():
    rows = parse_untapped_ancient_choice_page(_HTML_FIXTURE)
    assert rows == [
        {"act": 1, "offered_count": None, "picked_rate": None, "low_data": True},
        {"act": 2, "offered_count": 11000, "picked_rate": 19, "low_data": False},
        {"act": 3, "offered_count": None, "picked_rate": None, "low_data": True},
    ]


def test_parse_untapped_page_returns_empty_without_choice_section():
    assert parse_untapped_ancient_choice_page("<html><body>nothing</body></html>") == []
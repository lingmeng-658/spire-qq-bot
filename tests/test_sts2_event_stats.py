"""STS2 Event Stats v1 aggregation tests (fictional runs only).

The fixtures mirror the audited raw dump shape: each run has
``map_point_history`` of map points, an event encounter is a map-point room
with ``room_type == "event"`` and ``model_id == "EVENT.<id>"``, and recorded
choices live under that map point's ``player_stats[].event_choices[]`` with a
localization ``title`` key such as
``WELLSPRING.pages.INITIAL.options.BATHE.title``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from card_guess.sts2_event_stats import (
    aggregate_sts2_event_stats,
    load_sts2_event_stats_snapshot,
    parse_event_choice_key,
)


REAL_SNAPSHOT = Path("data/stats/sts2_event_stats.json")


def _choice(key: str, *, table: str = "events") -> dict:
    return {"title": {"table": table, "key": key}}


def _map_point(event_id: str, choices=(), *, extra_models=()) -> dict:
    rooms = [
        {"model_id": f"EVENT.{event_id}", "room_type": "event", "turns_taken": 0}
    ]
    rooms.extend(
        {"model_id": f"EVENT.{model}", "room_type": "event", "turns_taken": 0}
        for model in extra_models
    )
    player_stats = [{"player_id": 1, "event_choices": list(choices)}]
    return {
        "map_point_type": "unknown",
        "rooms": rooms,
        "player_stats": player_stats,
    }


def _run(
    run_id: str,
    *,
    win: bool = False,
    game_mode: str = "standard",
    ascension: int = 7,
    cheated: bool = False,
    abandoned: bool = False,
    build_id: str = "v0.100.0",
    schema_version: int = 9,
    map_points=(),
) -> dict:
    return {
        "_serverId": run_id,
        "game_mode": game_mode,
        "ascension": ascension,
        "win": win,
        "_isCheated": cheated,
        "was_abandoned": abandoned,
        "build_id": build_id,
        "schema_version": schema_version,
        "map_point_history": [list(map_points)],
    }


def _aggregate(runs, **kwargs) -> dict:
    params = {
        "collected_at": "2026-01-01T00:00:00Z",
        "source_sha256": "fictional-sha256",
        "min_association_sample": 1,
    }
    params.update(kwargs)
    return aggregate_sts2_event_stats(runs, **params)


def _wellspring_run(run_id: str, *, choice_key: str, win: bool = False) -> dict:
    return _run(
        run_id,
        win=win,
        map_points=(_map_point("WELLSPRING", [_choice(choice_key)]),),
    )


def test_standard_a7_plus_non_cheated_non_abandoned_is_the_only_cohort():
    excluded = [
        _run("daily", game_mode="daily"),
        _run("custom", game_mode="custom"),
        _run("a6", ascension=6),
        _run("a0", ascension=0),
        _run("cheated", cheated=True),
        _run("abandoned", abandoned=True),
    ]
    result = _aggregate([_run("accepted"), *excluded])

    report = result["report"]
    assert report["accepted_runs"] == 1
    assert report["run_count_total"] == 7
    assert report["run_filters"]["non_standard_mode"] == 2
    assert report["run_filters"]["ascension_below_7"] == 2
    assert report["run_filters"]["cheated"] == 1
    assert report["run_filters"]["abandoned"] == 1


def test_cheated_runs_are_excluded():
    good = _wellspring_run(
        "r1", choice_key="WELLSPRING.pages.INITIAL.options.BATHE.title"
    )
    cheated = _wellspring_run(
        "r2", choice_key="WELLSPRING.pages.INITIAL.options.BOTTLE.title"
    )
    cheated["_isCheated"] = True

    result = _aggregate([good, cheated])

    report = result["report"]
    assert report["accepted_runs"] == 1
    assert report["run_filters"]["cheated"] == 1
    snapshot = result["snapshot"]
    wellspring = snapshot["events"]["WELLSPRING"]
    assert wellspring["encounter_count"] == 1
    assert "WELLSPRING.pages.INITIAL.options.BATHE.title" in wellspring["choices"]
    assert "WELLSPRING.pages.INITIAL.options.BOTTLE.title" not in wellspring["choices"]


def test_daily_and_custom_runs_are_excluded():
    runs = [
        _wellspring_run(
            "daily-1", choice_key="WELLSPRING.pages.INITIAL.options.BATHE.title"
        ),
        _wellspring_run(
            "custom-1", choice_key="WELLSPRING.pages.INITIAL.options.BOTTLE.title"
        ),
    ]
    runs[0]["game_mode"] = "daily"
    runs[1]["game_mode"] = "custom"

    report = _aggregate(runs)["report"]

    assert report["accepted_runs"] == 0
    assert report["run_filters"]["non_standard_mode"] == 2


def test_ascensions_below_seven_are_excluded():
    runs = [
        _run("a0", ascension=0),
        _run("a6", ascension=6),
        _run("a7", ascension=7),
        _run("a20", ascension=20),
    ]

    report = _aggregate(runs)["report"]

    assert report["accepted_runs"] == 2
    assert report["run_filters"]["ascension_below_7"] == 2


def test_abandoned_runs_are_excluded():
    abandoned = _wellspring_run(
        "abandoned", choice_key="WELLSPRING.pages.INITIAL.options.BATHE.title"
    )
    abandoned["was_abandoned"] = True

    result = _aggregate(
        [
            abandoned,
            _wellspring_run("ok", choice_key="WELLSPRING.pages.INITIAL.options.BATHE.title"),
        ]
    )

    assert result["report"]["accepted_runs"] == 1
    assert result["report"]["run_filters"]["abandoned"] == 1
    assert result["snapshot"]["events"]["WELLSPRING"]["encounter_count"] == 1


def test_event_encounter_count_uses_map_point_occurrences_not_run_dedupe():
    first = _map_point(
        "WELLSPRING", [_choice("WELLSPRING.pages.INITIAL.options.BATHE.title")]
    )
    second = _map_point(
        "WELLSPRING", [_choice("WELLSPRING.pages.INITIAL.options.BATHE.title")]
    )

    result = _aggregate([_run("r1", map_points=(first, second))])

    event = result["snapshot"]["events"]["WELLSPRING"]
    assert event["encounter_count"] == 2


def test_choice_occurrence_count_counts_each_record():
    key = "WELLSPRING.pages.INITIAL.options.BATHE.title"
    result = _aggregate(
        [
            _run(
                "r1",
                map_points=(_map_point("WELLSPRING", [_choice(key), _choice(key)]),),
            )
        ]
    )

    choice = result["snapshot"]["events"]["WELLSPRING"]["choices"][key]

    assert choice["occurrence_count"] == 2


def test_repeated_choice_occurrence_share_can_exceed_one():
    key = "ABYSSAL_BATHS.pages.ALL.options.LINGER.title"
    first_run = _run(
        "r1",
        map_points=(_map_point("ABYSSAL_BATHS", [_choice(key), _choice(key)]),),
    )
    second_run = _run(
        "r2", map_points=(_map_point("ABYSSAL_BATHS", [_choice(key)]),)
    )

    result = _aggregate([first_run, second_run])

    event = result["snapshot"]["events"]["ABYSSAL_BATHS"]
    choice = event["choices"][key]
    assert event["encounter_count"] == 2
    assert choice["occurrence_count"] == 3
    assert choice["occurrence_share"]["value"] == pytest.approx(150.0)


def test_run_associated_counts_deduplicate_the_same_run():
    key = "WELLSPRING.pages.INITIAL.options.BATHE.title"
    result = _aggregate(
        [
            _run(
                "r1",
                map_points=(_map_point("WELLSPRING", [_choice(key), _choice(key)]),),
            ),
            _run("r2", map_points=(_map_point("WELLSPRING", [_choice(key)]),)),
            _run("r3", map_points=(_map_point("WELLSPRING", [_choice(key)]),)),
        ]
    )

    choice = result["snapshot"]["events"]["WELLSPRING"]["choices"][key]

    assert choice["occurrence_count"] == 4
    assert choice["associated_run_count"] == 3


def test_occurrence_weighted_and_run_weighted_win_rates_differ():
    key = "WELLSPRING.pages.INITIAL.options.BATHE.title"
    result = _aggregate(
        [
            _run(
                "win-twice",
                win=True,
                map_points=(_map_point("WELLSPRING", [_choice(key), _choice(key)]),),
            ),
            _run(
                "loss", win=False, map_points=(_map_point("WELLSPRING", [_choice(key)]),)
            ),
            _run(
                "win-once", win=True, map_points=(_map_point("WELLSPRING", [_choice(key)]),)
            ),
        ]
    )

    choice = result["snapshot"]["events"]["WELLSPRING"]["choices"][key]

    assert choice["associated_occurrence_wins"] == 3
    assert choice["associated_occurrence_win_rate"]["value"] == pytest.approx(75.0)
    assert choice["associated_run_wins"] == 2
    assert choice["associated_run_win_rate"]["value"] == pytest.approx(2 / 3 * 100)


def test_low_sample_win_rates_stay_blank_like_sts1():
    key = "WELLSPRING.pages.INITIAL.options.BATHE.title"
    result = _aggregate(
        [
            _run(
                "r1",
                win=True,
                map_points=(_map_point("WELLSPRING", [_choice(key)]),),
            )
        ],
        min_association_sample=5,
    )

    choice = result["snapshot"]["events"]["WELLSPRING"]["choices"][key]

    assert choice["associated_occurrence_win_rate"] is None
    assert choice["associated_run_win_rate"] is None
    assert choice["associated_occurrence_wins"] == 1
    assert choice["associated_run_wins"] == 1


def test_choice_localization_key_parser():
    parsed = parse_event_choice_key(
        "SLIPPERY_BRIDGE.pages.INITIAL.options.HOLD_ON_0.title"
    )

    assert parsed is not None
    assert parsed.event_id == "SLIPPERY_BRIDGE"
    assert parsed.page_id == "INITIAL"
    assert parsed.option_id == "HOLD_ON_0"
    assert parse_event_choice_key("not.a.choice.key") is None
    assert parse_event_choice_key("WELLSPRING.pages.INITIAL.options.BATHE") is None


def test_event_id_mismatch_fails_closed():
    key = "OTHER_EVENT.pages.INITIAL.options.SOMETHING.title"
    result = _aggregate(
        [_run("r1", map_points=(_map_point("WELLSPRING", [_choice(key)]),))]
    )

    event = result["snapshot"]["events"]["WELLSPRING"]
    assert event["encounter_count"] == 1
    assert event["choices"] == {}
    assert result["report"]["event_id_mismatches"] == 1


def test_non_event_table_choices_are_counted_but_never_parsed():
    run = _run(
        "r1",
        map_points=(
            _map_point(
                "WELLSPRING",
                [
                    _choice("RELIC.ANY_RELIC.title", table="relics"),
                    _choice("SOME.MODIFIER.title", table="modifiers"),
                ],
            ),
        ),
    )

    result = _aggregate([run])

    event = result["snapshot"]["events"]["WELLSPRING"]
    assert event["encounter_count"] == 1
    assert event["choices"] == {}
    assert result["report"]["non_event_table_choices"] == 2


def test_metadata_carries_source_sha256_builds_schema_and_run_counts():
    runs = [
        _run("r1", build_id="v0.99.0", schema_version=8),
        _run("r2", build_id="v0.105.5", schema_version=9),
    ]
    result = _aggregate(runs)

    snapshot = result["snapshot"]
    assert snapshot["collected_at"] == "2026-01-01T00:00:00Z"
    source = snapshot["source"]
    assert source["source_url"] == "https://sts2runs.com/downloads"
    assert source["source_file"] == "runs-all-before-2026-06.json.gz"
    assert source["source_sha256"] == "fictional-sha256"
    assert source["source_build_min"] == "v0.99.0"
    assert source["source_build_max"] == "v0.105.5"
    assert source["source_schema_versions"] == [8, 9]
    scope = snapshot["scope"]
    assert scope["run_count_total"] == 2
    assert scope["run_count_accepted"] == 2
    assert scope["filters"]["game_mode"] == "standard"
    assert scope["filters"]["ascension_min"] == 7


@pytest.mark.skipif(not REAL_SNAPSHOT.exists(), reason="STS2 snapshot not present")
def test_real_snapshot_smoke_events_are_rebuilt_from_the_dump():
    """No numbers are hardcoded; assertions describe the frozen v1 facts."""

    snapshot = load_sts2_event_stats_snapshot(REAL_SNAPSHOT)
    events = snapshot["events"]

    wellspring = events["WELLSPRING"]
    bathe = wellspring["choices"][
        "WELLSPRING.pages.INITIAL.options.BATHE.title"
    ]
    bottle = wellspring["choices"][
        "WELLSPRING.pages.INITIAL.options.BOTTLE.title"
    ]
    assert wellspring["encounter_count"] > 0
    assert bathe["occurrence_count"] > bottle["occurrence_count"]
    assert bathe["associated_run_count"] == bathe["occurrence_count"]
    assert bathe["associated_run_win_rate"]["value"] > 0

    slippery = events["SLIPPERY_BRIDGE"]
    hold0 = slippery["choices"][
        "SLIPPERY_BRIDGE.pages.INITIAL.options.HOLD_ON_0.title"
    ]
    hold1 = slippery["choices"][
        "SLIPPERY_BRIDGE.pages.HOLD_ON_0.options.HOLD_ON_1.title"
    ]
    assert hold0["occurrence_count"] > 0
    assert hold1["occurrence_count"] > 0
    assert hold1["occurrence_share"]["value"] <= 100
    assert 0 < hold1["associated_run_count"] <= hold1["occurrence_count"]

    abyssal = events["ABYSSAL_BATHS"]
    linger = abyssal["choices"]["ABYSSAL_BATHS.pages.ALL.options.LINGER.title"]
    assert linger["occurrence_count"] > abyssal["encounter_count"]
    assert linger["occurrence_share"]["value"] > 100
    assert linger["associated_occurrence_win_rate"] is not None
    assert linger["associated_run_win_rate"] is not None
    assert "ABYSSAL_BATHS.pages.ALL.options.EXIT_BATHS.title" in abyssal["choices"]

    assert "SELF_HELP_BOOK" in events
    assert "ROOM_FULL_OF_CHEESE" in events

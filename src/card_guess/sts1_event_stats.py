"""STS1 Event Stats v1 draft aggregation (read side, no QQ).

Event Choice Stats audit v1 found that official STS1 run dumps record
``event_choices`` (chosen option, floor, per-record effects) but never the
*offered* options of an event screen.  Therefore this module never produces a
"choice rate" (选择率); the only share it computes is the share of event
*decisions* that picked each recorded option string (选项占比), and every
win-rate comparison is explicitly association-only (关联统计).

Cohort mirrors the audited STS1 card snapshot leaderboard population: A7-20,
no daily/trial/endless/chosen-seed/beta/special-seed, play_id deduplicated,
floors inside acts 1-3 (1-50).  Repeat encounters of the same event inside one
run count as separate decisions for the share denominator, but win
associations are restricted to runs that met the event exactly once so a
single choice can be attributed to the run outcome.
"""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

from card_guess.event_interaction import STS1_PLAYABLE_EVENT_IDS

SCHEMA_VERSION = "1.0.0"
GAME = "sts1"

SOURCE_ID = "mega_crit_120k_november"
SOURCE_URL = "https://www.dropbox.com/s/k9zjn8pgyq24llu/november.7z?dl=0"
DATASET_ID = "official_120k_november_sample"
DATASET_FILE = "november.json"

ACT_KEYS = ("act_1", "act_2", "act_3")
ACT_FLOOR_RANGES = {"act_1": (1, 16), "act_2": (17, 33), "act_3": (34, 50)}
ACT_RANGE_LOOKUP = {
    floor: act
    for act, (low, high) in ACT_FLOOR_RANGES.items()
    for floor in range(low, high + 1)
}

# Excluded run modes shared with the STS1 card snapshot cohort.
MODE_FIELDS = ("is_daily", "is_trial", "is_endless", "chose_seed", "is_beta")

# Ascension-7+ is the audited STS1 leaderboard/ranking cohort used by the card
# snapshot; Event Stats v1 mirrors that cohort.
DEFAULT_ASCENSION_MIN = 7
DEFAULT_ASCENSION_MAX = 20

# Minimum exactly-once-encounter runs before an associated win rate is shown.
# Below this the value would be noise, so it is left blank (never guessed).
DEFAULT_MIN_ASSOCIATION_SAMPLE = 50

# Audited event_id -> official-dump ``event_name`` strings for every STS1
# catalog event that has observable occurrences in the official run dump.
# Dump names are the in-game screen names and differ from the journal-style
# catalog ``name_en`` for several events (e.g. DRUG_DEALER logs as ``Drug
# Dealer`` while the catalog lists ``Augmenter``).  Every name below was
# observed in the real November dump (A7-20 cohort).  SPIRE_HEART has no
# recorded event_choices in that dump, so it is intentionally not listed and
# its catalog rows carry an explicit no-data exemption at the coverage layer.
EVENT_DUMP_NAMES: dict[str, tuple[str, ...]] = {
    "ACCURSED_BLACKSMITH": ("Accursed Blacksmith",),
    "ADDICT": ("Addict",),
    "BACK_TO_BASICS": ("Back to Basics",),
    "BEGGAR": ("Beggar",),
    "BIG_FISH": ("Big Fish",),
    "BONFIRE_ELEMENTALS": ("Bonfire Elementals",),
    "COLOSSEUM": ("Colosseum",),
    "CURSED_TOME": ("Cursed Tome",),
    "DEAD_ADVENTURER": ("Dead Adventurer",),
    "DESIGNER": ("Designer",),
    "DRUG_DEALER": ("Drug Dealer",),
    "DUPLICATOR": ("Duplicator",),
    "FACETRADER": ("FaceTrader",),
    "FALLING": ("Falling",),
    "FORGOTTEN_ALTAR": ("Forgotten Altar",),
    "FOUNTAIN_OF_CLEANSING": ("Fountain of Cleansing",),
    "GHOSTS": ("Ghosts",),
    "GOLDEN_IDOL": ("Golden Idol",),
    "GOLDEN_SHRINE": ("Golden Shrine",),
    "GOLDEN_WING": ("Golden Wing",),
    "KNOWING_SKULL": ("Knowing Skull",),
    "LAB": ("Lab",),
    "LIARS_GAME": ("Liars Game",),
    "LIVING_WALL": ("Living Wall",),
    "MASKED_BANDITS": ("Masked Bandits",),
    "MATCH_AND_KEEP": ("Match and Keep!",),
    "MINDBLOOM": ("MindBloom",),
    "MUSHROOMS": ("Mushrooms",),
    "MYSTERIOUS_SPHERE": ("Mysterious Sphere",),
    "N_LOTH": ("N'loth",),
    "NEST": ("Nest",),
    "NOTEFORYOURSELF": ("NoteForYourself",),
    "PURIFIER": ("Purifier",),
    "SCRAP_OOZE": ("Scrap Ooze",),
    "SECRETPORTAL": ("SecretPortal",),
    "SENSORYSTONE": ("SensoryStone",),
    "SHINING_LIGHT": ("Shining Light",),
    "THE_CLERIC": ("The Cleric",),
    "THE_JOUST": ("The Joust",),
    "THE_LIBRARY": ("The Library",),
    "THE_MAUSOLEUM": ("The Mausoleum",),
    "THE_MOAI_HEAD": ("The Moai Head",),
    "THE_WOMAN_IN_BLUE": ("The Woman in Blue",),
    "TOMB_OF_LORD_RED_MASK": ("Tomb of Lord Red Mask",),
    "TRANSMORGRIFIER": ("Transmorgrifier",),
    "UPGRADE_SHRINE": ("Upgrade Shrine",),
    "VAMPIRES": ("Vampires",),
    "WEMEETAGAIN": ("WeMeetAgain",),
    "WHEEL_OF_CHANGE": ("Wheel of Change",),
    "WINDING_HALLS": ("Winding Halls",),
    "WORLD_OF_GOOP": ("World of Goop",),
}

ID_BY_DUMP_NAME: dict[str, str] = {
    name: event_id
    for event_id, names in EVENT_DUMP_NAMES.items()
    for name in names
}

# Player-facing metric naming contract: choice-count shares are never called
# "choice rates" (no offer denominator exists); win-rate comparisons are always
# labeled as associations, never as causal win-rate impact.
METRIC_DEFINITIONS = {
    "chosen_share": {
        "label_zh": "选项占比",
        "description_zh": (
            "选项占比：选择该选项的遭遇决策数，占该事件该幕全部遭遇决策数的比例。"
            "官方 run 数据不记录选项展示/offer，因此这不是选择率。"
        ),
        "unit": "percent",
    },
    "associated_win_rate": {
        "label_zh": "关联胜率",
        "description_zh": (
            "关联胜率（关联统计）：该事件在整局只被遭遇一次的 runs 中，选择该选项者的胜率。"
            "仅为关联统计，不代表该选项提升或降低胜率。"
        ),
        "unit": "percent",
    },
    "win_rate_baseline": {
        "label_zh": "基线胜率（关联）",
        "description_zh": (
            "基线胜率（关联统计）：该事件该幕中只被遭遇一次的 runs 的胜率，"
            "作为各选项关联胜率的对照基线。"
        ),
        "unit": "percent",
    },
}


class EventStatsError(ValueError):
    """Raised when an STS1 event-stat snapshot violates its contract."""


def normalize_floor(value: Any) -> int | None:
    """Normalize an official-dump floor (int or integer-valued float)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
    return None


def act_for_floor(floor: int) -> str | None:
    """Map a run floor to its act key inside floors 1-50; None outside."""
    return ACT_RANGE_LOOKUP.get(floor)


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventStatsError(f"{path} must be an integer")
    if value < minimum:
        raise EventStatsError(f"{path} must be >= {minimum}")
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EventStatsError(f"{path} must be an object")
    return value


def make_share_metric(numerator: int, denominator: int) -> dict[str, Any]:
    """Percent share of decisions picking one option (decision cohort)."""
    _integer(numerator, "share.numerator")
    _integer(denominator, "share.denominator", minimum=1)
    if numerator > denominator:
        raise EventStatsError("share numerator must not exceed denominator")
    return {
        "value": numerator / denominator * 100,
        "unit": "percent",
        "provenance": "computed",
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
    }


def make_win_rate_metric(wins: int, runs: int) -> dict[str, Any]:
    """Percent win rate among a set of runs (association or baseline)."""
    _integer(wins, "win_rate.wins")
    _integer(runs, "win_rate.runs", minimum=1)
    if wins > runs:
        raise EventStatsError("win_rate wins must not exceed runs")
    return {
        "value": wins / runs * 100,
        "unit": "percent",
        "provenance": "computed",
        "numerator": wins,
        "denominator": runs,
        "sample_size": runs,
    }


def build_cross_act_view(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """Merge an event row's act buckets into one cross-act display view.

    Only used for events whose catalog act is unknown (``act=None``) and whose
    snapshot row has more than one act bucket.  Percentages are always recomputed
    from summed underlying counts (never by averaging per-act percentages):

    - encounters      = sum(act encounters)
    - chosen_count    = sum(act chosen_count)
    - 选项占比          = chosen_count / encounters
    - wins            = sum(act association numerators)
    - 关联胜率          = wins / chosen_count over the same acts (acts whose
      association bucket is missing are excluded from both numerator and
      denominator and suppress the association, never guessed as zero)

    Returns ``None`` when there is nothing to merge (single-act buckets stay in
    their original form so single-act semantics are untouched).
    """

    acts = row.get("acts")
    if not isinstance(acts, Mapping):
        return None
    present = [act for act in ACT_KEYS if isinstance(acts.get(act), Mapping)]
    if len(present) < 2:
        return None
    encounters_total = 0
    merged: dict[str, dict[str, Any]] = {}
    for act in present:
        act_map = acts[act]
        if not isinstance(act_map.get("encounters"), int):
            continue
        encounters_total += int(act_map["encounters"])
        options = act_map.get("options")
        if not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, Mapping):
                continue
            key = option.get("choice_key")
            if not isinstance(key, str) or not key:
                continue
            bucket = merged.setdefault(
                key,
                {
                    "choice_key": key,
                    "chosen_count": 0,
                    "wins": 0,
                    "runs": 0,
                    "assoc_acts": 0,
                    "missing_assoc_acts": 0,
                },
            )
            chosen = option.get("chosen_count")
            if isinstance(chosen, int) and not isinstance(chosen, bool):
                bucket["chosen_count"] += chosen
            association = option.get("associated_win_rate")
            if isinstance(association, Mapping):
                wins = association.get("numerator")
                runs = association.get("denominator")
                if isinstance(wins, int) and isinstance(runs, int):
                    bucket["wins"] += wins
                    bucket["runs"] += runs
                    bucket["assoc_acts"] += 1
            else:
                bucket["missing_assoc_acts"] += 1
    if encounters_total <= 0:
        return None
    options: list[dict[str, Any]] = []
    for key in sorted(merged):
        bucket = merged[key]
        if bucket["chosen_count"] <= 0:
            continue
        share = make_share_metric(bucket["chosen_count"], encounters_total)
        association = None
        if bucket["assoc_acts"] and bucket["missing_assoc_acts"] == 0:
            wins = bucket["wins"]
            cohort = bucket["chosen_count"]
            if wins >= 0 and cohort > 0 and wins <= cohort:
                association = {
                    "value": wins / cohort * 100,
                    "unit": "percent",
                    "provenance": "computed",
                    "numerator": wins,
                    "denominator": cohort,
                    "sample_size": bucket["runs"],
                }
        options.append(
            {
                "choice_key": key,
                "encounters": encounters_total,
                "chosen_count": bucket["chosen_count"],
                "chosen_share": share,
                "associated_win_rate": association,
                "sample_size": (
                    bucket["runs"] if association is not None else None
                ),
            }
        )
    options.sort(key=lambda item: (-item["chosen_count"], item["choice_key"]))
    return {
        "encounters": encounters_total,
        "options": options,
        "win_rate_baseline": None,
        "cross_act": True,
    }


def _new_report() -> dict[str, Any]:
    return {
        "total_runs": 0,
        "accepted_runs": 0,
        "duplicate_runs": 0,
        "run_filters": Counter(),
        "event_records_scanned": 0,
        "decisions_in_scope": 0,
        "float_floor_normalized": 0,
        "ignored_records": {
            "out_of_act_floor": 0,
            "invalid_floor": 0,
            "invalid_choice": 0,
            "non_playable_event": Counter(),
        },
    }


def _excluded_mode(run: Mapping[str, Any]) -> str | None:
    for field_name in MODE_FIELDS:
        if run.get(field_name) is True:
            return field_name
    if run.get("special_seed") not in (None, 0, "", "0"):
        return "special_seed"
    return None


def _accumulate_run(
    run: Mapping[str, Any],
    *,
    decisions: dict[str, dict[tuple[str, str], int]],
    runs_by_act: dict[str, dict[str, set[str]]],
    run_events: dict[str, dict[str, list[tuple[str, str]]]],
    repeat_runs_by_event: dict[str, set[str]],
    single_attrib: dict[str, dict[tuple[str, str], dict[str, int]]],
    victory: bool,
    report: dict[str, Any],
) -> None:
    """Fold one accepted run's event decisions into the accumulators."""
    records = run.get("event_choices")
    if not isinstance(records, list):
        return
    play_id = run["play_id"]

    for record in records:
        if not isinstance(record, Mapping):
            report["ignored_records"]["invalid_choice"] += 1
            continue
        event_name = record.get("event_name")
        if not isinstance(event_name, str) or not event_name:
            report["ignored_records"]["invalid_choice"] += 1
            continue
        report["event_records_scanned"] += 1
        event_id = ID_BY_DUMP_NAME.get(event_name)
        if event_id is None:
            report["ignored_records"]["non_playable_event"][event_name] += 1
            continue
        choice = record.get("player_choice")
        if not isinstance(choice, str) or not choice.strip():
            report["ignored_records"]["invalid_choice"] += 1
            continue
        floor = record.get("floor")
        if isinstance(floor, float) and not isinstance(floor, bool):
            normalized = normalize_floor(floor)
            if normalized is not None:
                report["float_floor_normalized"] += 1
                floor = normalized
        if isinstance(floor, bool) or not isinstance(floor, int):
            report["ignored_records"]["invalid_floor"] += 1
            continue
        act = act_for_floor(floor)
        if act is None:
            report["ignored_records"]["out_of_act_floor"] += 1
            continue
        key = (act, choice)
        decisions[event_id][key] = decisions[event_id].get(key, 0) + 1
        runs_by_act[event_id].setdefault(act, set()).add(play_id)
        run_events[event_id].setdefault(play_id, []).append(key)
        report["decisions_in_scope"] += 1

    # Per-event per-run grouping for repeat/single attribution.
    for event_id, per_run in run_events.items():
        entries = per_run.pop(play_id, None)
        if entries is None:
            continue
        if len(entries) > 1:
            repeat_runs_by_event[event_id].add(play_id)
            continue
        (act, choice), = entries
        bucket = single_attrib[event_id].setdefault(
            (act, choice), {"runs": 0, "wins": 0}
        )
        bucket["runs"] += 1
        if victory:
            bucket["wins"] += 1


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Convert Counters to stable plain dicts for JSON serialization."""
    return {
        "total_runs": report["total_runs"],
        "accepted_runs": report["accepted_runs"],
        "duplicate_runs": report["duplicate_runs"],
        "run_filters": dict(sorted(report["run_filters"].items())),
        "event_records_scanned": report["event_records_scanned"],
        "decisions_in_scope": report["decisions_in_scope"],
        "float_floor_normalized": report["float_floor_normalized"],
        "ignored_records": {
            "out_of_act_floor": report["ignored_records"]["out_of_act_floor"],
            "invalid_floor": report["ignored_records"]["invalid_floor"],
            "invalid_choice": report["ignored_records"]["invalid_choice"],
            "non_playable_event": dict(
                sorted(report["ignored_records"]["non_playable_event"].items())
            ),
        },
    }


def _build_options(
    act_choices: Mapping[str, int],
    *,
    encounters: int,
    event_id: str,
    act: str,
    single_attrib: Mapping[str, Mapping[tuple[str, str], Mapping[str, int]]],
    min_association_sample: int,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for choice, count in act_choices.items():
        association = None
        bucket = single_attrib[event_id].get((act, choice))
        if bucket is not None and bucket["runs"] >= min_association_sample:
            association = make_win_rate_metric(bucket["wins"], bucket["runs"])
        options.append(
            {
                "choice_key": choice,
                "encounters": encounters,
                "chosen_count": count,
                "chosen_share": make_share_metric(count, encounters),
                "associated_win_rate": association,
                "sample_size": (
                    association["sample_size"] if association is not None else None
                ),
            }
        )
    options.sort(key=lambda item: (-item["chosen_count"], item["choice_key"]))
    return options


def aggregate_sts1_event_stats(
    runs: Iterable[Mapping[str, Any]],
    *,
    collected_at: str,
    ascension_min: int = DEFAULT_ASCENSION_MIN,
    ascension_max: int = DEFAULT_ASCENSION_MAX,
    min_association_sample: int = DEFAULT_MIN_ASSOCIATION_SAMPLE,
    catalog_events: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate one STS1 Event Stats v1 draft snapshot + acceptance report.

    ``runs`` is an iterable of official-dump run mappings (already unwrapped);
    the caller streams them from ``iter_sts1_runs`` for the real dump.
    """
    if not isinstance(collected_at, str) or not collected_at:
        raise EventStatsError("collected_at must be a non-empty string")
    _integer(ascension_min, "ascension_min")
    _integer(ascension_max, "ascension_max", minimum=ascension_min)
    _integer(min_association_sample, "min_association_sample", minimum=1)

    decisions: dict[str, dict[tuple[str, str], int]] = {
        e: {} for e in EVENT_DUMP_NAMES
    }
    runs_by_act: dict[str, dict[str, set[str]]] = {e: {} for e in EVENT_DUMP_NAMES}
    run_events: dict[str, dict[str, list[tuple[str, str]]]] = {
        e: {} for e in EVENT_DUMP_NAMES
    }
    repeat_runs_by_event: dict[str, set[str]] = {e: set() for e in EVENT_DUMP_NAMES}
    single_attrib: dict[str, dict[tuple[str, str], dict[str, int]]] = {
        e: {} for e in EVENT_DUMP_NAMES
    }
    report = _new_report()
    seen_play_ids: set[str] = set()

    for raw_run in runs:
        report["total_runs"] += 1
        if not isinstance(raw_run, Mapping):
            report["run_filters"]["invalid_run"] += 1
            continue
        play_id = raw_run.get("play_id")
        if not isinstance(play_id, str) or not play_id:
            report["run_filters"]["missing_play_id"] += 1
            continue
        if play_id in seen_play_ids:
            report["duplicate_runs"] += 1
            continue
        seen_play_ids.add(play_id)
        reason = _excluded_mode(raw_run)
        if reason is not None:
            report["run_filters"][reason] += 1
            continue
        ascension = raw_run.get("ascension_level")
        if isinstance(ascension, bool) or not isinstance(ascension, int):
            report["run_filters"]["ascension_out_of_range"] += 1
            continue
        if not ascension_min <= ascension <= ascension_max:
            report["run_filters"]["ascension_out_of_range"] += 1
            continue
        report["accepted_runs"] += 1
        _accumulate_run(
            raw_run,
            decisions=decisions,
            runs_by_act=runs_by_act,
            run_events=run_events,
            repeat_runs_by_event=repeat_runs_by_event,
            single_attrib=single_attrib,
            victory=bool(raw_run.get("victory")),
            report=report,
        )

    snapshot = _build_snapshot(
        decisions=decisions,
        runs_by_act=runs_by_act,
        repeat_runs_by_event=repeat_runs_by_event,
        single_attrib=single_attrib,
        collected_at=collected_at,
        ascension_min=ascension_min,
        ascension_max=ascension_max,
        min_association_sample=min_association_sample,
        catalog_events=catalog_events,
    )
    validate_sts1_event_stats_snapshot(snapshot)
    return {"snapshot": snapshot, "report": _finalize_report(report)}


def _build_snapshot(
    *,
    decisions: dict[str, dict[tuple[str, str], int]],
    runs_by_act: dict[str, dict[str, set[str]]],
    repeat_runs_by_event: dict[str, set[str]],
    single_attrib: dict[str, dict[tuple[str, str], dict[str, int]]],
    collected_at: str,
    ascension_min: int,
    ascension_max: int,
    min_association_sample: int,
    catalog_events: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for event_id in sorted(EVENT_DUMP_NAMES):
        acts: dict[str, dict[str, Any]] = {}
        for act in ACT_KEYS:
            act_runs = runs_by_act[event_id].get(act, set())
            act_choices = {
                choice: count
                for (act_key, choice), count in decisions[event_id].items()
                if act_key == act
            }
            encounters = sum(act_choices.values())
            if encounters == 0 and not act_runs:
                continue
            options = _build_options(
                act_choices,
                encounters=encounters,
                event_id=event_id,
                act=act,
                single_attrib=single_attrib,
                min_association_sample=min_association_sample,
            )
            single_runs = sum(
                bucket["runs"]
                for (act_key, _choice), bucket in single_attrib[event_id].items()
                if act_key == act
            )
            single_wins = sum(
                bucket["wins"]
                for (act_key, _choice), bucket in single_attrib[event_id].items()
                if act_key == act
            )
            baseline = None
            if single_runs >= min_association_sample:
                baseline = make_win_rate_metric(single_wins, single_runs)
            acts[act] = {
                "encounters": encounters,
                "run_reached": len(act_runs),
                "options": options,
                "win_rate_baseline": baseline,
            }
        catalog = (catalog_events or {}).get(event_id) or {}
        events.append(
            {
                "id": event_id,
                "dump_names": list(EVENT_DUMP_NAMES[event_id]),
                "name_en": catalog.get("name_en"),
                "name_zh": catalog.get("name_zh"),
                "pool": catalog.get("pool"),
                "catalog_act": catalog.get("act"),
                "repeat_runs": len(repeat_runs_by_event[event_id]),
                "acts": acts,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "game": GAME,
        "kind": "event_choice_stats_draft_v1",
        "collected_at": collected_at,
        "source": {
            "source_id": SOURCE_ID,
            "source": SOURCE_URL,
            "dataset": {"id": DATASET_ID, "file": DATASET_FILE},
        },
        "scope": {
            "ascension_min": ascension_min,
            "ascension_max": ascension_max,
            "excluded_modes": list(MODE_FIELDS) + ["special_seed"],
            "min_association_sample": min_association_sample,
            "filters": {
                "play_id": "deduplicated_first_occurrence_wins",
                "act_floor_ranges": ACT_FLOOR_RANGES,
                "floor_type": "int_or_integer_valued_float_normalized",
                "event_scope": "51_mapped_sts1_events_with_run_evidence",
                "choice_identity": "recorded_player_choice_strings_no_offer_log",
                "win_association": "association_only_single_encounter_runs",
            },
        },
        "metric_definitions": METRIC_DEFINITIONS,
        "mapping": {eid: list(names) for eid, names in EVENT_DUMP_NAMES.items()},
        "events": events,
    }


def validate_sts1_event_stats_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Validate the STS1 event-stat snapshot contract (raises ValueError)."""
    root = _mapping(snapshot, "snapshot")
    for field in (
        "schema_version",
        "game",
        "kind",
        "collected_at",
        "source",
        "scope",
        "metric_definitions",
        "mapping",
        "events",
    ):
        if field not in root:
            raise EventStatsError(f"snapshot.{field} is missing")
    if root["schema_version"] != SCHEMA_VERSION:
        raise EventStatsError("snapshot.schema_version mismatch")
    if root["game"] != GAME:
        raise EventStatsError("snapshot.game must be 'sts1'")
    if root["kind"] != "event_choice_stats_draft_v1":
        raise EventStatsError("snapshot.kind mismatch")

    scope = _mapping(root["scope"], "snapshot.scope")
    _integer(scope.get("ascension_min"), "snapshot.scope.ascension_min")
    _integer(scope.get("ascension_max"), "snapshot.scope.ascension_max")
    _integer(
        scope.get("min_association_sample"),
        "snapshot.scope.min_association_sample",
        minimum=1,
    )

    events = root["events"]
    if not isinstance(events, list):
        raise EventStatsError("snapshot.events must be a list")
    seen_ids: set[str] = set()
    for event in events:
        event_map = _mapping(event, "snapshot.events[]")
        event_id = event_map.get("id")
        if event_id not in EVENT_DUMP_NAMES:
            raise EventStatsError(f"unknown event id {event_id!r}")
        if event_id in seen_ids:
            raise EventStatsError(f"duplicate event id {event_id!r}")
        seen_ids.add(event_id)
        if list(event_map.get("dump_names", ())) != list(EVENT_DUMP_NAMES[event_id]):
            raise EventStatsError(f"dump_names mismatch for {event_id!r}")
        _integer(event_map.get("repeat_runs"), f"events[{event_id}].repeat_runs")
        _validate_act_bucket(event_map, event_id)
    missing = set(EVENT_DUMP_NAMES) - seen_ids
    if missing:
        raise EventStatsError(f"snapshot misses events: {sorted(missing)}")


def _validate_act_bucket(event_map: Mapping[str, Any], event_id: str) -> None:
    acts = _mapping(event_map.get("acts"), f"events[{event_id}].acts")
    for act, raw_act in acts.items():
        if act not in ACT_KEYS:
            raise EventStatsError(f"events[{event_id}].acts key {act!r} invalid")
        act_map = _mapping(raw_act, f"events[{event_id}].acts[{act}]")
        encounters = _integer(
            act_map.get("encounters"), f"events[{event_id}].acts[{act}].encounters"
        )
        _integer(act_map.get("run_reached"), f"events[{event_id}].acts[{act}].run_reached")
        if act_map["run_reached"] > encounters and encounters > 0:
            raise EventStatsError(
                f"events[{event_id}].acts[{act}] run_reached exceeds encounters"
            )
        options = act_map.get("options")
        if not isinstance(options, list):
            raise EventStatsError(f"events[{event_id}].acts[{act}].options must be list")
        total_chosen = 0
        for option in options:
            option_map = _mapping(option, f"events[{event_id}].acts[{act}].options[]")
            choice = option_map.get("choice_key")
            if not isinstance(choice, str) or not choice:
                raise EventStatsError("option choice_key must be non-empty string")
            _integer(
                option_map.get("chosen_count"),
                f"option {choice!r} chosen_count",
            )
            share = _mapping(
                option_map.get("chosen_share"), f"option {choice!r} chosen_share"
            )
            numerator = share.get("numerator")
            denominator = share.get("denominator")
            if not isinstance(numerator, int) or isinstance(numerator, bool):
                raise EventStatsError(f"option {choice!r} share numerator invalid")
            if not isinstance(denominator, int) or isinstance(denominator, bool):
                raise EventStatsError(f"option {choice!r} share denominator invalid")
            if not 0 <= numerator <= denominator:
                raise EventStatsError(f"option {choice!r} share bounds violated")
            if share.get("sample_size") != denominator:
                raise EventStatsError(f"option {choice!r} share sample_size mismatch")
            if share.get("unit") != "percent":
                raise EventStatsError(f"option {choice!r} share unit must be percent")
            if share.get("sample_size") != encounters:
                raise EventStatsError(f"option {choice!r} share cohort must equal encounters")
            total_chosen += numerator
            association = option_map.get("associated_win_rate")
            if association is not None:
                assoc = _mapping(association, f"option {choice!r} associated_win_rate")
                wins = assoc.get("numerator")
                assoc_runs = assoc.get("denominator")
                if not isinstance(wins, int) or isinstance(wins, bool):
                    raise EventStatsError(f"option {choice!r} assoc wins invalid")
                if not isinstance(assoc_runs, int) or isinstance(assoc_runs, bool):
                    raise EventStatsError(f"option {choice!r} assoc runs invalid")
                if not 0 <= wins <= assoc_runs:
                    raise EventStatsError(f"option {choice!r} assoc bounds violated")
                if assoc.get("sample_size") != assoc_runs:
                    raise EventStatsError(f"option {choice!r} assoc sample_size mismatch")
                if assoc.get("unit") != "percent":
                    raise EventStatsError(f"option {choice!r} assoc unit must be percent")
                if option_map.get("sample_size") != assoc_runs:
                    raise EventStatsError(f"option {choice!r} sample_size mismatch")
            elif option_map.get("sample_size") is not None:
                raise EventStatsError(f"option {choice!r} sample_size must be null without assoc")
        if encounters > 0 and not options:
            raise EventStatsError(f"events[{event_id}].acts[{act}] empty options")
        if total_chosen != encounters:
            raise EventStatsError(
                f"events[{event_id}].acts[{act}] option counts must sum to encounters"
            )
        baseline = act_map.get("win_rate_baseline")
        if baseline is not None:
            baseline_map = _mapping(baseline, f"events[{event_id}].acts[{act}].baseline")
            if baseline_map.get("unit") != "percent":
                raise EventStatsError("baseline unit must be percent")
            _validate_win_metric(baseline_map, f"events[{event_id}].acts[{act}].baseline")


def _validate_win_metric(metric: Mapping[str, Any], path: str) -> None:
    wins = metric.get("numerator")
    runs = metric.get("denominator")
    if not isinstance(wins, int) or isinstance(wins, bool):
        raise EventStatsError(f"{path} wins invalid")
    if not isinstance(runs, int) or isinstance(runs, bool):
        raise EventStatsError(f"{path} runs invalid")
    if not 0 <= wins <= runs:
        raise EventStatsError(f"{path} win bounds violated")
    if metric.get("sample_size") != runs:
        raise EventStatsError(f"{path} sample_size mismatch")


DEFAULT_SNAPSHOT_PATH = Path("data/stats/sts1_event_stats_draft.json")


def load_sts1_event_stats_snapshot(
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and validate the persisted STS1 Event Stats draft artifact.

    Runtime consumers must read this generated snapshot only (never the
    aggregation sources).  A missing, unreadable or invalid artifact degrades
    to an empty dict so the QQ enhancement can fall back to plain catalog
    display without raising.
    """
    path = Path(snapshot_path) if snapshot_path is not None else DEFAULT_SNAPSHOT_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        validate_sts1_event_stats_snapshot(payload)
    except EventStatsError:
        return {}
    return payload

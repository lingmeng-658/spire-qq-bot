"""STS2 Event Stats v1 aggregation (read side, no QQ).

The audited STS2 raw dump stores every event encounter as a map point whose
``rooms`` contain ``room_type == "event"`` and ``model_id == "EVENT.<id>"``.
Recorded choices live in the same map point's
``player_stats[].event_choices[]``; for ``title.table == "events"`` the title
key is a localization key of the form
``<event_id>.pages.<page_id>.options.<option_id>.title``.

Raw data has no offer log, so this module never produces a choice/pick rate.
It computes event-level occurrence shares and association-only win rates:

- occurrence share can exceed 100% when one encounter offers the same choice
  on multiple pages (repeated paths are kept as distinct full choice keys);
- the occurrence-weighted win rate counts each recorded occurrence;
- the run-weighted win rate deduplicates runs that chose the key at least
  once and is the v1 QQ default because it is easier to explain.

Runtime/bot code consumes the generated snapshot through the safe loader and
never reads raw runs.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "1.0.0"
GAME = "sts2"
KIND = "event_occurrence_stats_v1"

SOURCE_URL = "https://sts2runs.com/downloads"
SOURCE_FILE = "runs-all-before-2026-06.json.gz"

DEFAULT_ASCENSION_MIN = 7
DEFAULT_MIN_ASSOCIATION_SAMPLE = 50
DEFAULT_SNAPSHOT_PATH = Path("data/stats/sts2_event_stats.json")

_EVENT_MODEL_PREFIX = "EVENT."


class EventStatsError(ValueError):
    """Raised when an STS2 event-stat snapshot violates its contract."""


@dataclass(frozen=True)
class ParsedChoiceKey:
    """One parsed events-table choice localization key."""

    event_id: str
    page_id: str
    option_id: str


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EventStatsError(f"{path} must be an object")
    return value


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EventStatsError(f"{path} must be a non-empty string")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventStatsError(f"{path} must be an integer")
    if value < minimum:
        raise EventStatsError(f"{path} must be >= {minimum}")
    return value


def _schema_versions(versions: Iterable[Any]) -> list[int]:
    normalized: set[int] = set()
    for value in versions:
        if isinstance(value, bool):
            continue
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(normalized)


def _version_tuple(build_id: str) -> tuple[int, ...]:
    text = build_id.strip().removeprefix("v").removeprefix("V")
    try:
        return tuple(int(part) for part in text.split("."))
    except ValueError:
        return (0,)


def _min_max_build(builds: Iterable[str]) -> tuple[str | None, str | None]:
    values = sorted(set(builds), key=_version_tuple)
    if not values:
        return None, None
    return values[0], values[-1]


def parse_event_choice_key(value: Any) -> ParsedChoiceKey | None:
    """Parse an events-table title key; None when the grammar does not match."""

    if not isinstance(value, str) or not value:
        return None
    parts = value.split(".")
    if len(parts) != 6:
        return None
    event_id, pages, page_id, options, option_id, title = parts
    if (
        pages != "pages"
        or options != "options"
        or title != "title"
        or not event_id
        or not page_id
        or not option_id
    ):
        return None
    return ParsedChoiceKey(
        event_id=event_id,
        page_id=page_id,
        option_id=option_id,
    )


def _choice_title(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """Return ``(table, key)`` for one event_choice record."""

    title = record.get("title")
    if not isinstance(title, Mapping):
        return None
    table = title.get("table")
    key = title.get("key")
    if not isinstance(table, str) or not isinstance(key, str):
        return None
    return table, key


def _event_model_ids(rooms: Any) -> list[str]:
    if not isinstance(rooms, list):
        return []
    ids: list[str] = []
    for room in rooms:
        if not isinstance(room, Mapping):
            continue
        if room.get("room_type") != "event":
            continue
        model = room.get("model_id")
        if not isinstance(model, str):
            continue
        if model.startswith(_EVENT_MODEL_PREFIX):
            event_id = model[len(_EVENT_MODEL_PREFIX):]
            if event_id:
                ids.append(event_id)
    return ids


def _filter_reason(raw_run: Any) -> str | None:
    if not isinstance(raw_run, Mapping):
        return "invalid_run"
    if raw_run.get("game_mode") != "standard":
        return "non_standard_mode"
    ascension = raw_run.get("ascension")
    if (
        isinstance(ascension, bool)
        or not isinstance(ascension, int)
        or ascension < DEFAULT_ASCENSION_MIN
    ):
        return "ascension_below_7"
    if raw_run.get("_isCheated") is True:
        return "cheated"
    if raw_run.get("was_abandoned") is True:
        return "abandoned"
    return None


def _new_report() -> dict[str, Any]:
    return {
        "total_runs": 0,
        "accepted_runs": 0,
        "run_filters": Counter(),
        "non_event_table_choices": 0,
        "malformed_events_table_key": 0,
        "event_id_mismatches": 0,
        "invalid_choice_records": 0,
    }


def _percent_metric(numerator: int, denominator: int) -> dict[str, Any]:
    if numerator < 0 or denominator < 1 or numerator > denominator:
        raise EventStatsError("metric numerator/denominator are inconsistent")
    return {
        "value": numerator / denominator * 100,
        "unit": "percent",
        "provenance": "computed",
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
    }


def _share_metric(numerator: int, denominator: int) -> dict[str, Any]:
    """Percent occurrence share; numerator may exceed one denominator."""

    if numerator < 0 or denominator < 1:
        raise EventStatsError("share numerator/denominator are inconsistent")
    return {
        "value": numerator / denominator * 100,
        "unit": "percent",
        "provenance": "computed",
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
    }


def _choice_row(
    *,
    key: ParsedChoiceKey,
    occurrence_count: int,
    encounter_count: int,
    occurrence_wins: int,
    run_count: int,
    run_wins: int,
    min_association_sample: int,
) -> dict[str, Any]:
    occurrence_rate = (
        _percent_metric(occurrence_wins, occurrence_count)
        if occurrence_count >= min_association_sample
        else None
    )
    run_rate = (
        _percent_metric(run_wins, run_count)
        if run_count >= min_association_sample
        else None
    )
    return {
        "page_id": key.page_id,
        "option_id": key.option_id,
        "occurrence_count": occurrence_count,
        "occurrence_share": _share_metric(occurrence_count, encounter_count),
        "associated_occurrence_wins": occurrence_wins,
        "associated_occurrence_win_rate": occurrence_rate,
        "associated_run_count": run_count,
        "associated_run_wins": run_wins,
        "associated_run_win_rate": run_rate,
    }


def aggregate_sts2_event_stats(
    runs: Iterable[Mapping[str, Any]],
    *,
    collected_at: str,
    source_sha256: str | None = None,
    min_association_sample: int = DEFAULT_MIN_ASSOCIATION_SAMPLE,
) -> dict[str, Any]:
    """Aggregate one STS2 Event occurrence snapshot + acceptance report.

    ``runs`` is an iterable of raw STS2 run mappings (already JSON-decoded);
    real dumps are streamed from the offline gzip builder.
    """
    _string(collected_at, "collected_at")
    if source_sha256 is not None:
        _string(source_sha256, "source_sha256")
    _integer(
        min_association_sample,
        "min_association_sample",
        minimum=1,
    )

    report = _new_report()
    encounter_counts: Counter[str] = Counter()
    occurrence_counts: dict[str, Counter[str]] = defaultdict(Counter)
    occurrence_wins: dict[str, Counter[str]] = defaultdict(Counter)
    run_sets: dict[str, dict[str, set[str]]] = defaultdict(dict)
    win_run_sets: dict[str, dict[str, set[str]]] = defaultdict(dict)
    build_ids: set[str] = set()
    schema_values: set[Any] = set()

    for raw_run in runs:
        report["total_runs"] += 1
        if not isinstance(raw_run, Mapping):
            report["run_filters"]["invalid_run"] += 1
            continue
        build_id = raw_run.get("build_id")
        if isinstance(build_id, str) and build_id.strip():
            build_ids.add(build_id.strip())
        schema_values.add(raw_run.get("schema_version"))

        reason = _filter_reason(raw_run)
        if reason is not None:
            report["run_filters"][reason] += 1
            continue
        report["accepted_runs"] += 1

        server_id = raw_run.get("_serverId")
        run_id = (
            f"row:{report['total_runs']}"
            if not isinstance(server_id, str) or not server_id
            else server_id
        )
        win = bool(raw_run.get("win"))

        map_history = raw_run.get("map_point_history")
        if not isinstance(map_history, list):
            continue
        for act in map_history:
            if not isinstance(act, list):
                continue
            for map_point in act:
                if not isinstance(map_point, Mapping):
                    continue
                event_ids = _event_model_ids(map_point.get("rooms"))
                for event_id in event_ids:
                    encounter_counts[event_id] += 1
                event_id_set = set(event_ids)
                _fold_map_point_choices(
                    map_point,
                    run_id=run_id,
                    win=win,
                    event_id_set=event_id_set,
                    occurrence_counts=occurrence_counts,
                    occurrence_wins=occurrence_wins,
                    run_sets=run_sets,
                    win_run_sets=win_run_sets,
                    report=report,
                )

    source = {
        "source": SOURCE_URL,
        "source_url": SOURCE_URL,
        "source_file": SOURCE_FILE,
        "source_sha256": source_sha256,
        "source_build_min": _min_max_build(build_ids)[0],
        "source_build_max": _min_max_build(build_ids)[1],
        "source_schema_versions": _schema_versions(schema_values),
    }
    scope = {
        "filters": {
            "game_mode": "standard",
            "ascension_min": DEFAULT_ASCENSION_MIN,
            "cheated": "excluded",
            "abandoned": "excluded",
            "losses": "included",
            "modifiers": "not_used_as_exclusion",
        },
        "run_count_total": report["total_runs"],
        "run_count_accepted": report["accepted_runs"],
        "min_association_sample": min_association_sample,
    }
    events = _build_events(
        encounter_counts=encounter_counts,
        occurrence_counts=occurrence_counts,
        occurrence_wins=occurrence_wins,
        run_sets=run_sets,
        win_run_sets=win_run_sets,
        min_association_sample=min_association_sample,
    )
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "game": GAME,
        "kind": KIND,
        "collected_at": collected_at,
        "source": source,
        "scope": scope,
        "events": events,
    }
    validate_sts2_event_stats_snapshot(snapshot)
    return {"snapshot": snapshot, "report": _finalize_report(report)}


def _build_events(
    *,
    encounter_counts: Mapping[str, int],
    occurrence_counts: Mapping[str, Mapping[str, int]],
    occurrence_wins: Mapping[str, Mapping[str, int]],
    run_sets: Mapping[str, Mapping[str, set[str]]],
    win_run_sets: Mapping[str, Mapping[str, set[str]]],
    min_association_sample: int,
) -> dict[str, dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for event_id in sorted(encounter_counts):
        encounters = encounter_counts[event_id]
        choices: dict[str, dict[str, Any]] = {}
        for full_key in sorted(occurrence_counts.get(event_id, {})):
            parsed = parse_event_choice_key(full_key)
            if parsed is None or parsed.event_id != event_id:
                continue
            choices[full_key] = _choice_row(
                key=parsed,
                occurrence_count=occurrence_counts[event_id][full_key],
                encounter_count=encounters,
                occurrence_wins=occurrence_wins.get(event_id, {}).get(full_key, 0),
                run_count=len(run_sets.get(event_id, {}).get(full_key, ())),
                run_wins=len(win_run_sets.get(event_id, {}).get(full_key, ())),
                min_association_sample=min_association_sample,
            )
        events[event_id] = {
            "encounter_count": encounters,
            "choices": choices,
        }
    return events


def _fold_map_point_choices(
    map_point: Mapping[str, Any],
    *,
    run_id: str,
    win: bool,
    event_id_set: set[str],
    occurrence_counts: dict[str, Counter[str]],
    occurrence_wins: dict[str, Counter[str]],
    run_sets: dict[str, dict[str, set[str]]],
    win_run_sets: dict[str, dict[str, set[str]]],
    report: dict[str, Any],
) -> None:
    player_stats = map_point.get("player_stats")
    if not isinstance(player_stats, list):
        return
    for player_stat in player_stats:
        if not isinstance(player_stat, Mapping):
            continue
        choices = player_stat.get("event_choices")
        if not isinstance(choices, list):
            continue
        for record in choices:
            if not isinstance(record, Mapping):
                report["invalid_choice_records"] += 1
                continue
            parsed_title = _choice_title(record)
            if parsed_title is None:
                report["invalid_choice_records"] += 1
                continue
            table, key = parsed_title
            if table != "events":
                report["non_event_table_choices"] += 1
                continue
            parsed = parse_event_choice_key(key)
            if parsed is None:
                report["malformed_events_table_key"] += 1
                continue
            if parsed.event_id not in event_id_set:
                report["event_id_mismatches"] += 1
                continue
            event_id = parsed.event_id
            occurrence_counts[event_id][key] += 1
            if win:
                occurrence_wins[event_id][key] += 1
            run_sets[event_id].setdefault(key, set()).add(run_id)
            if win:
                win_run_sets[event_id].setdefault(key, set()).add(run_id)


def _finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_runs": report["total_runs"],
        "run_count_total": report["total_runs"],
        "accepted_runs": report["accepted_runs"],
        "run_filters": dict(sorted(report["run_filters"].items())),
        "non_event_table_choices": report["non_event_table_choices"],
        "malformed_events_table_key": report["malformed_events_table_key"],
        "event_id_mismatches": report["event_id_mismatches"],
        "invalid_choice_records": report["invalid_choice_records"],
    }


def validate_sts2_event_stats_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Validate the persisted STS2 snapshot contract (raises ValueError)."""

    root = _mapping(snapshot, "snapshot")
    for field in (
        "schema_version",
        "game",
        "kind",
        "collected_at",
        "source",
        "scope",
        "events",
    ):
        if field not in root:
            raise EventStatsError(f"snapshot.{field} is missing")
    if root["schema_version"] != SCHEMA_VERSION:
        raise EventStatsError("snapshot.schema_version mismatch")
    if root["game"] != GAME:
        raise EventStatsError("snapshot.game must be 'sts2'")
    if root["kind"] != KIND:
        raise EventStatsError("snapshot.kind mismatch")
    _string(root["collected_at"], "snapshot.collected_at")

    source = _mapping(root["source"], "snapshot.source")
    for field in (
        "source",
        "source_url",
        "source_file",
        "source_sha256",
        "source_build_min",
        "source_build_max",
        "source_schema_versions",
    ):
        if field not in source:
            raise EventStatsError(f"snapshot.source.{field} is missing")
    if source["source_sha256"] is not None:
        _string(source["source_sha256"], "snapshot.source.source_sha256")
    schema_versions = source["source_schema_versions"]
    if not isinstance(schema_versions, list) or not schema_versions:
        raise EventStatsError("snapshot.source.source_schema_versions must be a list")

    scope = _mapping(root["scope"], "snapshot.scope")
    _integer(scope.get("run_count_total"), "snapshot.scope.run_count_total")
    _integer(scope.get("run_count_accepted"), "snapshot.scope.run_count_accepted", minimum=0)
    if scope["run_count_accepted"] > scope["run_count_total"]:
        raise EventStatsError("accepted runs must not exceed total runs")
    _integer(
        scope.get("min_association_sample"),
        "snapshot.scope.min_association_sample",
        minimum=1,
    )
    filters = _mapping(scope.get("filters"), "snapshot.scope.filters")
    if filters.get("game_mode") != "standard":
        raise EventStatsError("snapshot.scope.filters.game_mode mismatch")
    if filters.get("ascension_min") != DEFAULT_ASCENSION_MIN:
        raise EventStatsError("snapshot.scope.filters.ascension_min mismatch")

    events = _mapping(root["events"], "snapshot.events")
    for event_id, raw_row in events.items():
        _string(event_id, "snapshot.events key")
        row = _mapping(raw_row, f"snapshot.events[{event_id}]")
        encounters = _integer(
            row.get("encounter_count"),
            f"snapshot.events[{event_id}].encounter_count",
            minimum=1,
        )
        choices = _mapping(row.get("choices"), f"snapshot.events[{event_id}].choices")
        for full_key, raw_choice in choices.items():
            choice = _mapping(
                raw_choice, f"snapshot.events[{event_id}].choices[{full_key}]"
            )
            parsed = parse_event_choice_key(full_key)
            if parsed is None or parsed.event_id != event_id:
                raise EventStatsError(
                    f"snapshot.events[{event_id}] choice key mismatch: {full_key!r}"
                )
            if choice.get("page_id") != parsed.page_id:
                raise EventStatsError(f"choice {full_key!r} page_id mismatch")
            if choice.get("option_id") != parsed.option_id:
                raise EventStatsError(f"choice {full_key!r} option_id mismatch")
            occurrence_count = _integer(
                choice.get("occurrence_count"),
                f"choice {full_key!r} occurrence_count",
                minimum=1,
            )
            share = _mapping(
                choice.get("occurrence_share"), f"choice {full_key!r} occurrence_share"
            )
            if share.get("unit") != "percent":
                raise EventStatsError(f"choice {full_key!r} share unit mismatch")
            if (
                share.get("numerator") != occurrence_count
                or share.get("denominator") != encounters
                or share.get("sample_size") != encounters
            ):
                raise EventStatsError(f"choice {full_key!r} share counts mismatch")
            if not math.isclose(
                float(share["value"]),
                occurrence_count / encounters * 100,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise EventStatsError(f"choice {full_key!r} share value mismatch")

            occurrence_wins = _integer(
                choice.get("associated_occurrence_wins"),
                f"choice {full_key!r} associated_occurrence_wins",
            )
            if occurrence_wins > occurrence_count:
                raise EventStatsError(f"choice {full_key!r} occurrence wins overflow")
            min_sample = scope["min_association_sample"]
            occurrence_rate = choice.get("associated_occurrence_win_rate")
            _validate_optional_rate(
                occurrence_rate,
                occurrence_wins,
                occurrence_count,
                f"choice {full_key!r} associated_occurrence_win_rate",
            )
            if (occurrence_count >= min_sample) != (occurrence_rate is not None):
                raise EventStatsError(
                    f"choice {full_key!r} occurrence rate sample policy mismatch"
                )

            run_count = _integer(
                choice.get("associated_run_count"),
                f"choice {full_key!r} associated_run_count",
                minimum=1,
            )
            if run_count > occurrence_count:
                raise EventStatsError(
                    f"choice {full_key!r} run count exceeds occurrence count"
                )
            run_wins = _integer(
                choice.get("associated_run_wins"),
                f"choice {full_key!r} associated_run_wins",
            )
            if run_wins > run_count:
                raise EventStatsError(f"choice {full_key!r} run wins overflow")
            run_rate = choice.get("associated_run_win_rate")
            _validate_optional_rate(
                run_rate,
                run_wins,
                run_count,
                f"choice {full_key!r} associated_run_win_rate",
            )
            if (run_count >= min_sample) != (run_rate is not None):
                raise EventStatsError(
                    f"choice {full_key!r} run rate sample policy mismatch"
                )


def _validate_optional_rate(
    rate: Any,
    numerator: int,
    denominator: int,
    path: str,
) -> None:
    if rate is None:
        return
    metric = _mapping(rate, path)
    if metric.get("unit") != "percent":
        raise EventStatsError(f"{path} unit must be percent")
    if (
        metric.get("numerator") != numerator
        or metric.get("denominator") != denominator
        or metric.get("sample_size") != denominator
    ):
        raise EventStatsError(f"{path} counts mismatch")
    if numerator > denominator:
        raise EventStatsError(f"{path} numerator exceeds denominator")
    if not math.isclose(
        float(metric["value"]),
        numerator / denominator * 100,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise EventStatsError(f"{path} value mismatch")


def load_sts2_event_stats_snapshot(
    snapshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and validate the persisted STS2 Event Stats artifact.

    Runtime consumers read this generated snapshot only.  A missing,
    unreadable or invalid artifact degrades to an empty dict so presentation
    falls back to plain catalog display without raising.
    """
    path = Path(snapshot_path) if snapshot_path is not None else DEFAULT_SNAPSHOT_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        validate_sts2_event_stats_snapshot(payload)
    except EventStatsError:
        return {}
    return payload

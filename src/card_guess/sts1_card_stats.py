"""Streaming, source-scoped STS1 card-statistics aggregation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import gzip
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Iterator, Mapping

from card_guess.card_stats import make_rate_metric, validate_card_stats_snapshot


SOURCE_ID = "mega_crit_120k_november"
SOURCE_URL = "https://www.dropbox.com/s/k9zjn8pgyq24llu/november.7z?dl=0"
ACTS = ("act_1", "act_2", "act_3")
EXPECTED_FIELDS = (
    "is_daily",
    "is_trial",
    "is_endless",
    "chose_seed",
    "is_beta",
    "special_seed",
    "build_version",
    "character_chosen",
    "ascension_level",
    "victory",
    "card_choices",
    "master_deck",
    "campfire_choices",
)
MODE_FILTERS = (
    ("is_daily", "daily"),
    ("is_trial", "trial"),
    ("is_endless", "endless"),
    ("chose_seed", "chose_seed"),
    ("is_beta", "beta"),
)

# Official 120k dump top-level element format: {"event": <run>}. Direct runs stay supported.
EVENT_WRAP_KEY = "event"

# Non-card entity that appears inside card_choices (relic reward option string).
SINGING_BOWL_ENTITY = "Singing Bowl"

# Card+N (N >= 1) upgrade suffix; only a trailing "+<digits>" counts as an upgrade.
CARD_UPGRADE_RE = re.compile(r"^(?P<base>.+)\+(?P<level>[1-9][0-9]*)$")

# Official-dump Heart guard: damage_taken[].enemies == "The Heart" records
# live on floors 55/56. Stray 42-54 / 105-106 records in the sample are not
# the real Heart fight and are excluded by this audited floor range.
HEART_ENEMY_NAME = "The Heart"
HEART_ENCOUNTER_FLOORS = frozenset({55, 56})

METRIC_DEFINITIONS = {
    "offered_count": {
        "description": "Card-reward events in floors 1-50 where the card was offered.",
        "unit": "count",
    },
    "picked_count": {
        "description": "Card-reward picks in floors 1-50.",
        "unit": "count",
    },
    "picked_run_count": {
        "description": "Runs with at least one card-reward pick of the card in floors 1-50.",
        "unit": "count",
    },
    "skip_count": {
        "description": "Offers of the card on reward screens whose recorded choice was SKIP.",
        "unit": "count",
    },
    "skip_rate": {
        "description": "skip_count divided by offered_count.",
        "unit": "percent",
        "formula": "skip_count / offered_count * 100",
    },
    "act_pick_rate": {
        "description": "Card-reward picks divided by offers, grouped by act floor range.",
        "unit": "percent",
        "formula": "picked offer events / offered events * 100",
    },
    "first_pick_floor_mean": {
        "description": "Mean run-level floor of the first card-reward pick.",
        "unit": "floor",
    },
    "repick_rate": {
        "description": "Pick rate on offers after an earlier reward pick in the same run.",
        "unit": "percent",
        "formula": "later picks / later offers after first reward pick * 100",
    },
    "act_win_delta": {
        "description": (
            "Observed run win-rate difference between runs that picked the card and "
            "runs that were offered it but never picked it in the same act; not causal."
        ),
        "unit": "percentage_points",
        "formula": "picked cohort win rate - comparison cohort win rate",
    },
    "pick_rate": {
        "description": (
            "Card-reward picks divided by offers across all floors 1-50 "
            "(global, run-length offers)."
        ),
        "unit": "percent",
        "formula": "picked_count / offered_count * 100",
    },
    "win_delta": {
        "description": (
            "Observed run win-rate difference between runs that picked the card "
            "anywhere in floors 1-50 and runs offered the card but never picked it "
            "in the same run; statistical association only, not causal."
        ),
        "unit": "percentage_points",
        "formula": "picked cohort win rate - comparison cohort win rate",
    },
    "final_deck_presence_rate": {
        "description": "Share of runs with a recorded final deck containing the card.",
        "unit": "percent",
        "formula": "runs containing card / runs with master_deck * 100",
    },
    "final_deck_copy_mean": {
        "description": "Mean final copies among runs whose final deck contains the card.",
        "unit": "copies",
    },
    "final_upgrade_rate": {
        "description": "Upgraded final copies divided by all final copies of the card.",
        "unit": "percent",
        "formula": "upgraded final copies / all final copies * 100",
    },
    "heart_win_deck_presence_rate": {
        "description": (
            "Share of heart-win runs (audited The Heart damage encounter at a "
            "plausible floor with a native boolean victory) whose recorded "
            "final master deck contains the card."
        ),
        "unit": "percent",
        "formula": "heart-win deck runs containing card / heart-win runs with a recorded master deck * 100",
    },
    "campfire_upgrade_count": {
        "description": "Recorded SMITH actions for the card on floors above zero.",
        "unit": "count",
    },
    "campfire_upgrade_floor_mean": {
        "description": "Mean floor of recorded SMITH actions for the card above floor zero.",
        "unit": "floor",
    },
}


@dataclass
class _CardAccumulator:
    offered: int = 0
    picked: int = 0
    picked_runs: int = 0
    skipped: int = 0
    first_pick_floor_sum: int = 0
    repick_numerator: int = 0
    repick_denominator: int = 0
    act_offered: Counter[str] = field(default_factory=Counter)
    act_picked: Counter[str] = field(default_factory=Counter)
    picked_wins: Counter[str] = field(default_factory=Counter)
    picked_cohort: Counter[str] = field(default_factory=Counter)
    comparison_wins: Counter[str] = field(default_factory=Counter)
    comparison_cohort: Counter[str] = field(default_factory=Counter)
    # Whole-run (floors 1-50) cohorts for the global win_delta metric: a run is
    # 'picked' when the card was picked at least once, otherwise 'comparison'
    # when it was offered but never picked anywhere in the run.
    run_picked_cohort: int = 0
    run_picked_wins: int = 0
    run_comparison_cohort: int = 0
    run_comparison_wins: int = 0
    final_runs: int = 0
    final_copies: int = 0
    final_upgraded_copies: int = 0
    campfire_upgrades: int = 0
    campfire_floor_sum: int = 0
    # Heart-win runs (valid cohort runs that beat The Heart) whose final
    # master deck contains this card; a card counts at most once per run.
    heart_deck_runs: int = 0


def iter_sts1_runs(path: str | Path, *, chunk_size: int = 1024 * 1024) -> Iterator[Mapping[str, Any]]:
    """Stream run objects from a top-level JSON array without loading the full file.

    Native ingestion support: elements may be direct run objects or the official
    dump wrapper ``{"event": <run>}``.  A wrapper whose value is not a mapping is
    passed through unchanged so downstream aggregation reports it (for example as
    ``missing_play_id``) instead of guessing at the structure.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    input_path = Path(path)
    opener = gzip.open if input_path.suffix.lower() == ".gz" else open
    decoder = json.JSONDecoder()

    with opener(input_path, "rt", encoding="utf-8-sig") as handle:
        buffer = ""
        started = False
        need_value = True
        eof = False
        while True:
            if not eof:
                chunk = handle.read(chunk_size)
                if chunk:
                    buffer += chunk
                else:
                    eof = True

            while True:
                buffer = buffer.lstrip()
                if not started:
                    if not buffer:
                        break
                    if buffer[0] != "[":
                        raise ValueError("top-level JSON value must be an array")
                    buffer = buffer[1:]
                    started = True
                    continue

                buffer = buffer.lstrip()
                if need_value:
                    if buffer.startswith("]"):
                        trailing = buffer[1:] + handle.read()
                        if trailing.strip():
                            raise ValueError("unexpected data after top-level JSON array")
                        return
                    if not buffer:
                        break
                    try:
                        value, end = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        break
                    if not isinstance(value, Mapping):
                        raise ValueError("every run in the top-level array must be an object")
                    if set(value) == {EVENT_WRAP_KEY}:
                        inner = value.get(EVENT_WRAP_KEY)
                        if isinstance(inner, Mapping):
                            value = inner
                    yield value
                    buffer = buffer[end:]
                    need_value = False
                    continue

                if not buffer:
                    break
                if buffer[0] == ",":
                    buffer = buffer[1:]
                    need_value = True
                    continue
                if buffer[0] == "]":
                    trailing = buffer[1:] + handle.read()
                    if trailing.strip():
                        raise ValueError("unexpected data after top-level JSON array")
                    return
                raise ValueError("expected ',' or ']' after run object")

            if eof:
                if not started:
                    raise ValueError("top-level JSON value must be an array")
                raise ValueError("incomplete top-level JSON array")


def aggregate_sts1_runs(
    runs: Iterable[Mapping[str, Any]],
    *,
    card_ids: Iterable[str],
    collected_at: str,
    source_id: str = SOURCE_ID,
    source: str = SOURCE_URL,
) -> dict[str, Any]:
    """Aggregate STS1 card statistics and an acceptance report in one pass."""
    resolver = _make_card_resolver(card_ids)
    accumulators = {card_id: _CardAccumulator() for card_id in resolver.values()}
    report = _new_report()
    seen_play_ids: set[str] = set()

    for raw_run in runs:
        report["total_runs"] += 1
        if not isinstance(raw_run, Mapping):
            report["filter_reasons"]["invalid_run"] += 1
            continue
        play_id = raw_run.get("play_id")
        if not isinstance(play_id, str) or not play_id:
            report["filter_reasons"]["missing_play_id"] += 1
            continue
        if play_id in seen_play_ids:
            report["duplicate_runs"] += 1
            continue
        seen_play_ids.add(play_id)
        reason = _filter_reason(raw_run)
        if reason is not None:
            report["filter_reasons"][reason] += 1
            continue

        report["valid_runs"] += 1
        _normalize_run_floors(raw_run)
        _record_run_metadata(raw_run, report)
        _record_card_choices(raw_run, resolver, accumulators, report)
        _record_terminal_deck(raw_run, resolver, accumulators, report)
        _record_campfire_choices(raw_run, resolver, accumulators, report)
        if heart_encounter_floor(raw_run) is not None:
            report["heart_encounter_runs"] += 1
        if is_heart_win_run(raw_run):
            report["heart_win_runs"] += 1
            _record_heart_win_deck(raw_run, resolver, accumulators, report)

    snapshot = _build_snapshot(
        accumulators,
        report,
        collected_at=collected_at,
        source_id=source_id,
        source=source,
    )
    clean_report = _finalize_report(report)
    validate_card_stats_snapshot(snapshot)
    return {"snapshot": snapshot, "report": clean_report}


def _new_report() -> dict[str, Any]:
    return {
        "total_runs": 0,
        "valid_runs": 0,
        "duplicate_runs": 0,
        "filter_reasons": Counter(),
        "build_versions": Counter(),
        "characters": Counter(),
        "ascensions": Counter(),
        "missing_fields": Counter(),
        "invalid_fields": Counter(),
        "field_present": Counter(),
        "unresolved_card_ids": Counter(),
        "ignored_records": Counter(),
        "schema_observations": Counter(),
        "heart_encounter_runs": 0,
        "heart_win_runs": 0,
        "heart_win_deck_runs": 0,
    }


def _filter_reason(run: Mapping[str, Any]) -> str | None:
    for field_name, reason in MODE_FILTERS:
        if run.get(field_name) is True:
            return reason
    special_seed = run.get("special_seed")
    if special_seed not in (None, 0, "", "0"):
        return "special_seed"
    return None


def _record_run_metadata(run: Mapping[str, Any], report: dict[str, Any]) -> None:
    for name in EXPECTED_FIELDS:
        if name not in run:
            report["missing_fields"][name] += 1

    build = run.get("build_version")
    if isinstance(build, str) and build:
        report["build_versions"][build] += 1
    character = run.get("character_chosen")
    if isinstance(character, str) and character:
        report["characters"][character] += 1
    ascension = run.get("ascension_level")
    if isinstance(ascension, int) and not isinstance(ascension, bool):
        report["ascensions"][str(ascension)] += 1


def _record_card_choices(
    run: Mapping[str, Any],
    resolver: Mapping[str, str],
    accumulators: Mapping[str, _CardAccumulator],
    report: dict[str, Any],
) -> None:
    choices = run.get("card_choices")
    if not isinstance(choices, list):
        if "card_choices" in run:
            report["invalid_fields"]["card_choices"] += 1
        return
    report["field_present"]["card_choices"] += 1
    history: set[str] = set()
    picked_this_run: dict[str, int] = {}
    offered_by_act = {act: set() for act in ACTS}
    picked_by_act = {act: set() for act in ACTS}

    indexed_choices = list(enumerate(choices))
    indexed_choices.sort(key=lambda item: (_floor_sort_key(item[1]), item[0]))
    for _, raw_choice in indexed_choices:
        if not isinstance(raw_choice, Mapping):
            report["invalid_fields"]["card_choices.item"] += 1
            continue
        floor = raw_choice.get("floor")
        if not _is_int(floor):
            report["schema_observations"]["card_choices_missing_floor"] += 1
            continue
        if floor <= 0:
            report["ignored_records"]["card_choices_floor_zero"] += 1
            continue
        act = _act_for_floor(floor)
        if act is None:
            report["ignored_records"]["card_choices_outside_acts_1_to_3"] += 1
            continue

        raw_not_picked = raw_choice.get("not_picked")
        if isinstance(raw_not_picked, list):
            report["schema_observations"]["not_picked_choices"] += 1
            not_picked = raw_not_picked
        else:
            report["schema_observations"]["missing_not_picked_choices"] += 1
            not_picked = []

        offered: set[str] = set()
        for raw_card in not_picked:
            if raw_card == SINGING_BOWL_ENTITY:
                report["schema_observations"]["singing_bowl_in_not_picked"] += 1
                continue
            card_id = _resolve_card(raw_card, resolver, report)
            if card_id is not None:
                offered.add(card_id)

        picked_raw = raw_choice.get("picked")
        picked_id = None
        if picked_raw == "SKIP":
            report["schema_observations"]["picked_skip_choices"] += 1
        elif picked_raw == SINGING_BOWL_ENTITY:
            report["schema_observations"]["singing_bowl_picked"] += 1
        else:
            picked_id = _resolve_card(picked_raw, resolver, report)
            if picked_id is not None:
                offered.add(picked_id)

        for card_id in offered:
            card = accumulators[card_id]
            card.offered += 1
            card.act_offered[act] += 1
            offered_by_act[act].add(card_id)
            if card_id in history:
                card.repick_denominator += 1
                if card_id == picked_id:
                    card.repick_numerator += 1
            if picked_raw == "SKIP":
                card.skipped += 1

        if picked_id is not None:
            card = accumulators[picked_id]
            card.picked += 1
            card.act_picked[act] += 1
            picked_by_act[act].add(picked_id)
            picked_this_run.setdefault(picked_id, floor)
            history.add(picked_id)

    for card_id, first_floor in picked_this_run.items():
        accumulators[card_id].picked_runs += 1
        accumulators[card_id].first_pick_floor_sum += first_floor

    victory = run.get("victory")
    if not isinstance(victory, bool):
        return
    for act in ACTS:
        for card_id in offered_by_act[act]:
            card = accumulators[card_id]
            if card_id in picked_by_act[act]:
                card.picked_cohort[act] += 1
                card.picked_wins[act] += int(victory)
            else:
                card.comparison_cohort[act] += 1
                card.comparison_wins[act] += int(victory)

    # Whole-run cohorts over floors 1-50: each card is counted at most once per
    # run.  Picked anywhere in the run -> picked cohort; offered but never picked
    # -> comparison cohort.
    any_offered = set().union(*offered_by_act.values())
    for card_id in any_offered:
        card = accumulators[card_id]
        if card_id in picked_this_run:
            card.run_picked_cohort += 1
            card.run_picked_wins += int(victory)
        else:
            card.run_comparison_cohort += 1
            card.run_comparison_wins += int(victory)


def _record_terminal_deck(
    run: Mapping[str, Any],
    resolver: Mapping[str, str],
    accumulators: Mapping[str, _CardAccumulator],
    report: dict[str, Any],
) -> None:
    deck = run.get("master_deck")
    if not isinstance(deck, list):
        if "master_deck" in run:
            report["invalid_fields"]["master_deck"] += 1
        return
    report["field_present"]["master_deck"] += 1
    copies: Counter[str] = Counter()
    upgrades: Counter[str] = Counter()
    for raw_card in deck:
        base_name, upgrade_level = _split_card_name(raw_card)
        if upgrade_level >= 1:
            report["schema_observations"]["upgraded_master_deck_entries"] += 1
        card_id = _resolve_card(base_name, resolver, report, already_split=True)
        if card_id is None:
            continue
        copies[card_id] += 1
        upgrades[card_id] += int(upgrade_level >= 1)
    for card_id, count in copies.items():
        card = accumulators[card_id]
        card.final_runs += 1
        card.final_copies += count
        card.final_upgraded_copies += upgrades[card_id]


def _record_campfire_choices(
    run: Mapping[str, Any],
    resolver: Mapping[str, str],
    accumulators: Mapping[str, _CardAccumulator],
    report: dict[str, Any],
) -> None:
    choices = run.get("campfire_choices")
    if not isinstance(choices, list):
        if "campfire_choices" in run:
            report["invalid_fields"]["campfire_choices"] += 1
        return
    report["field_present"]["campfire_choices"] += 1
    for choice in choices:
        if not isinstance(choice, Mapping) or choice.get("key") != "SMITH":
            continue
        raw_card = choice.get("data")
        if isinstance(raw_card, str) and raw_card:
            report["schema_observations"]["smith_choices_with_data"] += 1
        floor = choice.get("floor")
        if not _is_int(floor):
            report["schema_observations"]["smith_choices_missing_floor"] += 1
            continue
        if floor <= 0:
            report["ignored_records"]["campfire_choices_floor_zero"] += 1
            continue
        card_id = _resolve_card(raw_card, resolver, report)
        if card_id is None:
            continue
        card = accumulators[card_id]
        card.campfire_upgrades += 1
        card.campfire_floor_sum += floor


def heart_encounter_floor(run: Any) -> int | None:
    """Return the audited Heart-fight floor of a run, or None.

    A Heart encounter is a ``damage_taken`` record whose ``enemies`` is
    ``"The Heart"`` on an audited 55/56 floor.  Stray 42-54 / 105-106
    records in the official sample are clearly not the Heart fight and never
    count, so ``victory`` or ``floor_reached`` alone can never qualify a run.
    """
    if not isinstance(run, Mapping):
        return None
    records = run.get("damage_taken")
    if not isinstance(records, list):
        return None
    for record in records:
        if not isinstance(record, Mapping) or record.get("enemies") != HEART_ENEMY_NAME:
            continue
        floor = _normalize_floor(record.get("floor"))
        if floor is not None and floor in HEART_ENCOUNTER_FLOORS:
            return floor
    return None


def is_heart_win_run(run: Any) -> bool:
    """True only for an audited Heart encounter with a native ``victory is True``.

    The strict boolean matches the rest of the ingestion pipeline; a ``"true"``
    string or a ``floor_reached`` proxy never counts as a heart win.
    """
    return heart_encounter_floor(run) is not None and run.get("victory") is True


def _record_heart_win_deck(
    run: Mapping[str, Any],
    resolver: Mapping[str, str],
    accumulators: Mapping[str, _CardAccumulator],
    report: dict[str, Any],
) -> None:
    """Record master-deck presence for one heart-win run.

    Only runs with a legal ``master_deck`` list enter the heart denominator;
    ``Card+N`` entries are normalised to the base card, and a card counts at
    most once per run.  Report side effects are kept out so heart runs do not
    double-count deck schema observations already recorded by the terminal
    deck pass.
    """
    deck = run.get("master_deck")
    if not isinstance(deck, list):
        return
    report["heart_win_deck_runs"] += 1
    scratch_report: dict[str, Any] = {"unresolved_card_ids": Counter()}
    seen: set[str] = set()
    for raw_card in deck:
        base_name, _upgrade_level = _split_card_name(raw_card)
        card_id = _resolve_card(base_name, resolver, scratch_report, already_split=True)
        if card_id is None or card_id in seen:
            continue
        seen.add(card_id)
        accumulators[card_id].heart_deck_runs += 1


def _build_snapshot(
    accumulators: Mapping[str, _CardAccumulator],
    report: Mapping[str, Any],
    *,
    collected_at: str,
    source_id: str,
    source: str,
) -> dict[str, Any]:
    builds = sorted(report["build_versions"])
    ascensions = sorted(int(value) for value in report["ascensions"])
    scope: dict[str, Any] = {
        "game": "sts1",
        "character_scope": "all_characters",
        "excluded_modes": ["daily", "trial", "endless", "chosen_seed", "beta", "special_seed"],
        "filters": {
            "play_id": "deduplicated",
            "special_seed": "missing_or_zero",
            "floor_zero": "excluded_from_floor_based_metrics",
            "act_floor_ranges": {"act_1": [1, 16], "act_2": [17, 33], "act_3": [34, 50]},
            "is_prod": "not_used",
        },
    }
    if builds:
        scope["build_versions"] = builds
    if ascensions:
        scope["ascension_min"] = ascensions[0]
        scope["ascension_max"] = ascensions[-1]

    snapshot: dict[str, Any] = {"schema_version": "1.0.0", "cards": {}}
    for card_id in sorted(accumulators):
        metrics = _card_metrics(
            accumulators[card_id],
            card_choice_runs=report["field_present"]["card_choices"],
            master_deck_runs=report["field_present"]["master_deck"],
            campfire_runs=report["field_present"]["campfire_choices"],
            heart_win_deck_runs=report["heart_win_deck_runs"],
        )
        if not metrics:
            continue
        source_metrics = {
            "source": source,
            "scope": scope,
            "version": {
                "dataset": "official_120k_november_sample",
                "build_versions": builds,
            },
            "collected_at": collected_at,
            "metric_definitions": {
                name: METRIC_DEFINITIONS[name] for name in metrics
            },
            **metrics,
        }
        snapshot["cards"][card_id] = {"metrics": {source_id: source_metrics}}
    return snapshot


def _card_metrics(
    card: _CardAccumulator,
    *,
    card_choice_runs: int,
    master_deck_runs: int,
    campfire_runs: int,
    heart_win_deck_runs: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if card_choice_runs:
        metrics["offered_count"] = _scalar(card.offered, "count", card_choice_runs)
        metrics["picked_count"] = _scalar(card.picked, "count", card_choice_runs)
        metrics["picked_run_count"] = _scalar(card.picked_runs, "count", card_choice_runs)
        metrics["skip_count"] = _scalar(card.skipped, "count", card_choice_runs)
    if card.offered:
        metrics["pick_rate"] = _rate(card.picked, card.offered, card.offered)
        metrics["skip_rate"] = _rate(card.skipped, card.offered, card.offered)
        act_rates = {
            act: _rate(card.act_picked[act], card.act_offered[act], card.act_offered[act])
            for act in ACTS
            if card.act_offered[act]
        }
        if act_rates:
            metrics["act_pick_rate"] = act_rates
    if card.picked_runs:
        metrics["first_pick_floor_mean"] = _scalar(
            card.first_pick_floor_sum / card.picked_runs,
            "floor",
            card.picked_runs,
        )
    if card.repick_denominator:
        metrics["repick_rate"] = _rate(
            card.repick_numerator,
            card.repick_denominator,
            card.repick_denominator,
        )

    deltas = {}
    for act in ACTS:
        picked_n = card.picked_cohort[act]
        comparison_n = card.comparison_cohort[act]
        if not picked_n or not comparison_n:
            continue
        value = (
            card.picked_wins[act] / picked_n
            - card.comparison_wins[act] / comparison_n
        ) * 100
        deltas[act] = make_rate_metric(
            value=value,
            unit="percentage_points",
            numerator=card.picked_wins[act],
            denominator=picked_n,
            comparison_numerator=card.comparison_wins[act],
            comparison_denominator=comparison_n,
            sample_size=picked_n + comparison_n,
        )
    if deltas:
        metrics["act_win_delta"] = deltas

    if card.run_picked_cohort and card.run_comparison_cohort:
        metrics["win_delta"] = make_rate_metric(
            value=(
                card.run_picked_wins / card.run_picked_cohort
                - card.run_comparison_wins / card.run_comparison_cohort
            )
            * 100,
            unit="percentage_points",
            numerator=card.run_picked_wins,
            denominator=card.run_picked_cohort,
            comparison_numerator=card.run_comparison_wins,
            comparison_denominator=card.run_comparison_cohort,
            sample_size=card.run_picked_cohort + card.run_comparison_cohort,
        )

    if master_deck_runs:
        metrics["final_deck_presence_rate"] = _rate(
            card.final_runs,
            master_deck_runs,
            master_deck_runs,
        )
    if card.final_runs:
        metrics["final_deck_copy_mean"] = _scalar(
            card.final_copies / card.final_runs,
            "copies",
            card.final_runs,
        )
    if card.final_copies:
        metrics["final_upgrade_rate"] = _rate(
            card.final_upgraded_copies,
            card.final_copies,
            card.final_runs,
        )
    if campfire_runs:
        metrics["campfire_upgrade_count"] = _scalar(
            card.campfire_upgrades,
            "count",
            campfire_runs,
        )
    if card.campfire_upgrades:
        metrics["campfire_upgrade_floor_mean"] = _scalar(
            card.campfire_floor_sum / card.campfire_upgrades,
            "floor",
            card.campfire_upgrades,
        )
    if heart_win_deck_runs and card.heart_deck_runs:
        metrics["heart_win_deck_presence_rate"] = _rate(
            card.heart_deck_runs,
            heart_win_deck_runs,
            heart_win_deck_runs,
        )
    return metrics


def _rate(numerator: int, denominator: int, sample_size: int) -> dict[str, Any]:
    return make_rate_metric(
        value=numerator / denominator * 100,
        numerator=numerator,
        denominator=denominator,
        sample_size=sample_size,
    )


def _scalar(value: int | float, unit: str, sample_size: int) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "provenance": "computed",
        "sample_size": sample_size,
    }


def _make_card_resolver(card_ids: Iterable[str]) -> dict[str, str]:
    resolver: dict[str, str] = {}
    for card_id in card_ids:
        if not isinstance(card_id, str) or not card_id:
            raise ValueError("card_ids must contain non-empty strings")
        key = _canonical_card_name(card_id)
        existing = resolver.get(key)
        if existing is not None and existing != card_id:
            raise ValueError(f"ambiguous canonical card IDs: {existing!r} and {card_id!r}")
        resolver[key] = card_id
    return resolver


def _resolve_card(
    raw_card: Any,
    resolver: Mapping[str, str],
    report: dict[str, Any],
    *,
    already_split: bool = False,
) -> str | None:
    if not isinstance(raw_card, str) or not raw_card:
        return None
    base_name = raw_card if already_split else _split_card_name(raw_card)[0]
    card_id = resolver.get(_canonical_card_name(base_name))
    if card_id is None:
        report["unresolved_card_ids"][base_name] += 1
    return card_id


def _split_card_name(raw_card: Any) -> tuple[str, int]:
    """Split ``Card+N`` (N >= 1) into (base name, upgrade level).

    ``Card+1`` keeps its previous behavior; a ``+`` that is not a trailing
    ``+digits`` upgrade suffix (for example ``Blade+Smith``) stays unsplit so a
    plain ``+`` inside a name is never mistaken for an upgrade.
    """
    if not isinstance(raw_card, str):
        return "", 0
    match = CARD_UPGRADE_RE.fullmatch(raw_card)
    if match is not None:
        return match.group("base"), int(match.group("level"))
    return raw_card, 0


def _normalize_floor(value: Any) -> int | None:
    """Return an int floor, or None when the value is not a valid integer floor.

    Finite, mathematically integral floats (``8.0`` -> ``8``) are accepted;
    fractional floats, NaN, Infinity, strings and booleans are rejected.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _normalize_run_floors(run: Mapping[str, Any]) -> None:
    """Normalize integral float floors in place for this run's choice records."""
    for field_name in ("card_choices", "campfire_choices"):
        records = run.get(field_name)
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, Mapping) and "floor" in record:
                normalized = _normalize_floor(record["floor"])
                if normalized is not None or not isinstance(record["floor"], (int, float)):
                    record["floor"] = normalized


def _canonical_card_name(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def _act_for_floor(floor: int) -> str | None:
    if 1 <= floor <= 16:
        return "act_1"
    if 17 <= floor <= 33:
        return "act_2"
    if 34 <= floor <= 50:
        return "act_3"
    return None


def _floor_sort_key(raw_choice: Any) -> int:
    if isinstance(raw_choice, Mapping) and _is_int(raw_choice.get("floor")):
        return raw_choice["floor"]
    return 10**9


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _coverage(present: int, eligible: int) -> dict[str, int | float]:
    return {
        "present_runs": present,
        "eligible_runs": eligible,
        "rate_percent": present / eligible * 100 if eligible else 0.0,
    }


def _finalize_report(report: Mapping[str, Any]) -> dict[str, Any]:
    valid_runs = report["valid_runs"]
    return {
        "total_runs": report["total_runs"],
        "valid_runs": valid_runs,
        "duplicate_runs": report["duplicate_runs"],
        "filter_reasons": _sorted_counter(report["filter_reasons"]),
        "build_versions": _sorted_counter(report["build_versions"]),
        "characters": _sorted_counter(report["characters"]),
        "ascensions": _sorted_counter(report["ascensions"], numeric=True),
        "field_coverage": {
            name: _coverage(report["field_present"][name], valid_runs)
            for name in ("card_choices", "master_deck", "campfire_choices")
        },
        "missing_fields": _sorted_counter(report["missing_fields"]),
        "invalid_fields": _sorted_counter(report["invalid_fields"]),
        "unresolved_card_ids": _sorted_counter(report["unresolved_card_ids"]),
        "ignored_records": _sorted_counter(report["ignored_records"]),
        "heart_encounter_runs": report["heart_encounter_runs"],
        "heart_win_runs": report["heart_win_runs"],
        "heart_win_deck_runs": report["heart_win_deck_runs"],
        "schema_observations": _sorted_counter(report["schema_observations"]),
    }


def _sorted_counter(counter: Mapping[str, int], *, numeric: bool = False) -> dict[str, int]:
    key = (lambda item: int(item[0])) if numeric else (lambda item: item[0])
    return dict(sorted(counter.items(), key=key))

"""Cohort-scoped STS1 snapshot exporter.

Bounded pipeline stage: this module reuses the validated
``aggregate_sts1_runs`` core unchanged.  It only decides cohort membership
(build_version + ascension range), merges the per-cohort sources into one
unified snapshot, attaches metadata, and reports filter bookkeeping.  It adds
no second statistics implementation and never invents metrics the core did
not produce.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from card_guess.card_stats import SOURCE_METADATA_FIELDS, validate_card_stats_snapshot
from card_guess.sts1_card_stats import SOURCE_ID, SOURCE_URL, aggregate_sts1_runs, iter_sts1_runs

DATASET_ID = "official_120k_november_sample"
DATASET_FILE = "november.json"
DEFAULT_BUILD_VERSION = "2020-07-30"

BASE_EXCLUDED_MODES = ("daily", "trial", "endless", "chosen_seed", "beta", "special_seed")
BASE_SCOPE_FILTERS = {
    "play_id": "deduplicated",
    "special_seed": "missing_or_zero",
    "floor_zero": "excluded_from_floor_based_metrics",
    "act_floor_ranges": {"act_1": [1, 16], "act_2": [17, 33], "act_3": [34, 50]},
    "is_prod": "not_used",
}


@dataclass(frozen=True)
class Sts1Cohort:
    """An ascension-range cohort definition used by the snapshot exporter."""

    key: str
    ascension_min: int
    ascension_max: int
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("cohort key must be a non-empty string")
        for name, value in (
            ("ascension_min", self.ascension_min),
            ("ascension_max", self.ascension_max),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 20:
                raise ValueError(f"cohort {name} must be an integer between 0 and 20")
        if self.ascension_min > self.ascension_max:
            raise ValueError("cohort ascension_min must not exceed ascension_max")
        if not isinstance(self.description, str) or not self.description:
            raise ValueError("cohort description must be a non-empty string")


COHORT_OVERALL = Sts1Cohort(
    key="overall",
    ascension_min=0,
    ascension_max=20,
    description="All ascensions 0-20 (build-filtered overall)",
)
COHORT_ASC7PLUS = Sts1Cohort(
    key="asc7plus",
    ascension_min=7,
    ascension_max=20,
    description="Ascension 7 to 20 (A7+)",
)
COHORT_ASC20 = Sts1Cohort(
    key="asc20",
    ascension_min=20,
    ascension_max=20,
    description="Ascension 20 only (A20)",
)
DEFAULT_COHORTS = (COHORT_ASC7PLUS, COHORT_ASC20)


@dataclass
class _PassCounts:
    scanned_runs: int = 0
    excluded_build_version: int = 0
    excluded_ascension: int = 0


def build_sts1_snapshot(
    runs: str | Path | Iterable[Mapping[str, Any]],
    *,
    card_ids: Iterable[str],
    collected_at: str | None = None,
    cohorts: Sequence[Sts1Cohort] = DEFAULT_COHORTS,
    build_version: str = DEFAULT_BUILD_VERSION,
    source_id: str = SOURCE_ID,
    source: str = SOURCE_URL,
    card_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build one unified snapshot with one scoped source per cohort.

    ``runs`` may be a path to the raw JSON array (opened fresh for every
    cohort, so the real multi-hundred-MB file is never held in memory) or any
    re-iterable in-memory collection of run mappings (materialized once).

    Every cohort only sees runs whose ``build_version`` equals ``build_version``
    and whose ``ascension_level`` lies inside the cohort range; runs excluded
    here are counted in the returned audit but never reach the aggregator.
    """
    if not isinstance(build_version, str) or not build_version:
        raise ValueError("build_version must be a non-empty string")
    cohort_list = list(cohorts)
    if not cohort_list:
        raise ValueError("cohorts must contain at least one cohort")
    cohort_keys = [cohort.key for cohort in cohort_list]
    if len(cohort_keys) != len(set(cohort_keys)):
        raise ValueError("duplicate cohort keys are not allowed")

    card_id_list = list(card_ids)
    if collected_at is None:
        collected_at = _utc_now()
    _validate_collected_at(collected_at)

    names = _validated_card_names(card_names)

    snapshot: dict[str, Any] = {"schema_version": "1.0.0", "cards": {}}
    cohort_reports: dict[str, Any] = {}
    materialized: list[Any] | None = None
    if not isinstance(runs, (str, Path)):
        materialized = list(runs)

    for cohort in cohort_list:
        counts = _PassCounts()
        source_for_cohort = _cohort_source_id(source_id, cohort.key)
        run_source = materialized if materialized is not None else runs
        result = aggregate_sts1_runs(
            _iter_cohort_runs(
                run_source,
                cohort=cohort,
                build_version=build_version,
                counts=counts,
            ),
            card_ids=card_id_list,
            collected_at=collected_at,
            source_id=source_for_cohort,
            source=source,
        )
        for card_id, card in result["snapshot"]["cards"].items():
            record = card["metrics"][source_for_cohort]
            final_record = _source_record_for_cohort(
                record,
                cohort=cohort,
                build_version=build_version,
                source=source,
                collected_at=collected_at,
            )
            output_card = snapshot["cards"].get(card_id)
            if output_card is None:
                output_card = {"metrics": {}}
                if card_id in names:
                    output_card["name"] = names[card_id]
                snapshot["cards"][card_id] = output_card
            output_card["metrics"][source_for_cohort] = final_record

        excluded_total = counts.excluded_build_version + counts.excluded_ascension
        cohort_reports[cohort.key] = {
            "source_id": source_for_cohort,
            "description": cohort.description,
            "ascension_min": cohort.ascension_min,
            "ascension_max": cohort.ascension_max,
            "build_version": build_version,
            "scanned_runs": counts.scanned_runs,
            "excluded_build_version": counts.excluded_build_version,
            "excluded_ascension": counts.excluded_ascension,
            "aggregated_runs": counts.scanned_runs - excluded_total,
            "report": result["report"],
        }

    validate_card_stats_snapshot(snapshot)
    return {"snapshot": snapshot, "cohorts": cohort_reports}


def write_sts1_snapshot(snapshot: Mapping[str, Any], path: str | Path) -> None:
    """Write a snapshot as UTF-8 JSON with LF line endings."""
    output = Path(path)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _iter_cohort_runs(
    runs: str | Path | Iterable[Mapping[str, Any]],
    *,
    cohort: Sts1Cohort,
    build_version: str,
    counts: _PassCounts,
) -> Iterable[Mapping[str, Any]]:
    iterator = iter_sts1_runs(runs) if isinstance(runs, (str, Path)) else iter(runs)
    for raw_run in iterator:
        counts.scanned_runs += 1
        if not isinstance(raw_run, Mapping):
            counts.excluded_build_version += 1
            continue
        if raw_run.get("build_version") != build_version:
            counts.excluded_build_version += 1
            continue
        ascension = raw_run.get("ascension_level")
        if (
            isinstance(ascension, bool)
            or not isinstance(ascension, int)
            or not cohort.ascension_min <= ascension <= cohort.ascension_max
        ):
            # Runs whose ascension cannot be classified (missing or non-int)
            # are conservatively excluded from every range-based cohort.
            counts.excluded_ascension += 1
            continue
        yield raw_run


def _source_record_for_cohort(
    record: Mapping[str, Any],
    *,
    cohort: Sts1Cohort,
    build_version: str,
    source: str,
    collected_at: str,
) -> dict[str, Any]:
    """Rewrite aggregate metadata while passing every metric through unchanged."""
    output: dict[str, Any] = {
        "source": source,
        "scope": _scope_for_cohort(cohort, build_version),
        "version": _version_for(build_version),
        "collected_at": collected_at,
        "metric_definitions": record["metric_definitions"],
    }
    for name, value in record.items():
        if name not in SOURCE_METADATA_FIELDS:
            output[name] = value
    return output


def _scope_for_cohort(cohort: Sts1Cohort, build_version: str) -> dict[str, Any]:
    filters = dict(BASE_SCOPE_FILTERS)
    filters["cohort"] = {
        "key": cohort.key,
        "description": cohort.description,
        "ascension_level": [cohort.ascension_min, cohort.ascension_max],
        "build_version": build_version,
    }
    return {
        "game": "sts1",
        "character_scope": "all_characters",
        "ascension_min": cohort.ascension_min,
        "ascension_max": cohort.ascension_max,
        "build_versions": [build_version],
        "excluded_modes": list(BASE_EXCLUDED_MODES),
        "filters": filters,
    }


def _version_for(build_version: str) -> dict[str, Any]:
    return {
        "dataset": DATASET_ID,
        "file": DATASET_FILE,
        "build_versions": [build_version],
        "data_source_note": (
            "Source: official Mega Crit November 2020 STS1 run sample "
            "(~123k runs, data/raw/november.json). This snapshot is scoped to "
            "that sample only: it is NOT the complete November 2020 dump and "
            "is NOT an Oct+Nov combined set. Per-run recording dates were not "
            "validated, so scope date_start/date_end are omitted."
        ),
        "historical_note": (
            f"Pre-V2.2-era STS1 statistics recorded on game build "
            f"{build_version} (the only build kept in this official snapshot; "
            "other builds are filtered out and counted in the cohort audit). "
            "act_win_delta is a run-level statistical association only and is "
            "not causal."
        ),
    }


def _cohort_source_id(base_source_id: str, cohort_key: str) -> str:
    return f"{base_source_id}_{cohort_key}"


def _validated_card_names(
    card_names: Mapping[str, str] | None,
) -> dict[str, str]:
    if card_names is None:
        return {}
    output: dict[str, str] = {}
    for card_id, name in card_names.items():
        if not isinstance(card_id, str) or not card_id:
            raise ValueError("card_names keys must be non-empty strings")
        if not isinstance(name, str) or not name:
            raise ValueError("card_names values must be non-empty strings")
        output[card_id] = name
    return output


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_collected_at(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("collected_at must be an ISO date-time with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("collected_at must be an ISO date-time with timezone") from None
    if parsed.tzinfo is None:
        raise ValueError("collected_at must include a timezone")

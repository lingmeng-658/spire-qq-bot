"""STS1 terminal-relic hold-rate aggregation over valid runs.

Implements policy C for relic rates: the catalog ``color`` field never decides a
relic's eligible characters.  For every catalog relic the snapshot records a
per-character hold rate (denominator = eligible runs of that character) and an
overall hold rate (denominator = all eligible valid runs).  A display policy
labels which metric is meaningful from the character support actually observed
in the run data.

R2A-2 keeps the scope narrow: terminal ``relics`` presence per run, the
heart-win presence rate (reusing the audited heart-win judgment) and per-act
``boss_choice`` offer/pick counts from ``boss_relics`` (index 0 = act1,
index 1 = act2).

R5B adds a ``first_acquisition`` section for Common / Uncommon / Rare relics
only, sourced from ``relics_obtained`` events: per run the legal first
recorded floor (1..56, integer or integer-valued float, earliest event wins)
feeds sample/percentile/act summaries.  The logs are incomplete, so coverage
against terminal presence is stored but never treated as a universal
acquisition log.  Shop purchases and STS2 statistics remain out of scope.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
import statistics
from typing import Any, Iterable, Iterator, Mapping

from card_guess.relic_stats import (
    BOSS_ACT_KEYS,
    BOSS_CHOICE_KEY,
    ACQUISITION_FLOOR_MAX,
    ACQUISITION_TIER_SET,
    CHARACTERS,
    DEFAULT_SUPPORT_MIN_HOLD_RUNS,
    DEFAULT_SUPPORT_MIN_SHARE,
    FIRST_ACQUISITION_KEY,
    HEART_WIN_KEY,
    SCHEMA_VERSION,
    is_character,
    make_relic_count_metric,
    make_relic_rate_metric,
    relic_display_policy,
    validate_relic_stats_snapshot,
)
from card_guess.sts1_card_stats import is_heart_win_run, iter_sts1_runs

SOURCE_ID = "mega_crit_120k_november"
SOURCE_URL = "https://www.dropbox.com/s/k9zjn8pgyq24llu/november.7z?dl=0"
DATASET_ID = "official_120k_november_sample"
DATASET_FILE = "november.json"

# Raw relic keys seen in the official dump that do not match the catalog id or
# the catalog ``name_en`` after alphanumeric normalization.  Each key maps to
# the catalog relic id it represents.
RELIC_RUN_KEY_ALIASES = {
    "Snake Skull": "SNAKE_SKULL",
    "Paper Frog": "PAPER_FROG",
    "Molten Egg 2": "MOLTEN_EGG_2",
    "Frozen Egg 2": "FROZEN_EGG_2",
    "Toxic Egg 2": "TOXIC_EGG_2",
    "Boot": "BOOT",
    "Sling": "SLING",
    "Cables": "CABLES",
    "Yang": "YANG",
    "NeowsBlessing": "NEOWSBLESSING",
    "CultistMask": "CULTISTMASK",
    "GremlinMask": "GREMLINMASK",
    "NlothsMask": "NLOTHSMASK",
    "Paper Crane": "PAPER_CRANE",
    "WingedGreaves": "WINGEDGREAVES",
}

# ``boss_relics`` list position maps to the boss relic act screen.
_BOSS_ACT_BY_INDEX = dict(enumerate(BOSS_ACT_KEYS))

# R5B: recorded-acquisition floor act boundaries (locked by tests).
ACT1_MAX_FLOOR = 16
ACT2_MAX_FLOOR = 33


def acquisition_floor_quartiles(floors):
    """Return ``(p25, median, p75)`` from stdlib inclusive quantiles.

    The project has no percentile helper; this locks the Python standard
    library definition ``statistics.quantiles(..., n=4, method="inclusive")``
    so the median always equals ``statistics.median`` and results are
    deterministic.  Quartiles are returned as floats (integer input floors
    give exact quarter-step values).
    """
    ordered = sorted(floors)
    if not ordered:
        raise ValueError("floors must not be empty")
    p25, median, p75 = statistics.quantiles(ordered, n=4, method="inclusive")
    return p25, median, p75


def _canonical_relic_key(value: str) -> str:
    """Normalize a relic name to an alphanumeric uppercase key."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


class RelicKeyResolver:
    """Resolve raw run relic keys to catalog relic ids.

    Lookup order: exact alias key, catalog id (uppercase match), then a unique
    alphanumeric match against catalog ``name_en``.  Anything else is left to
    the caller as an unresolved key.
    """

    def __init__(self, relic_catalog: Iterable[Mapping[str, Any]]) -> None:
        records = list(relic_catalog)
        if not records:
            raise ValueError("relic_catalog must contain at least one relic")
        by_id: dict[str, Mapping[str, Any]] = {}
        normalized: dict[str, str] = {}
        for record in records:
            relic_id = record.get("id")
            if not isinstance(relic_id, str) or not relic_id:
                raise ValueError("relic_catalog ids must be non-empty strings")
            if relic_id in by_id:
                raise ValueError(f"duplicate relic catalog id: {relic_id!r}")
            name_en = record.get("name_en")
            if not isinstance(name_en, str) or not name_en:
                raise ValueError(f"relic {relic_id!r} must have a non-empty name_en")
            by_id[relic_id] = record
            normalized_key = _canonical_relic_key(name_en)
            existing = normalized.get(normalized_key)
            if existing is not None and existing != relic_id:
                raise ValueError(
                    f"ambiguous relic names resolve to the same key: "
                    f"{existing!r} and {relic_id!r}"
                )
            normalized[normalized_key] = relic_id
        # Only aliases whose target actually exists in this catalog are active;
        # partial catalogs (tests) may omit alias targets.  For the full STS1
        # catalog every alias target is present, so a missing target would show
        # up as an unresolved run key in the acceptance report instead.
        self.catalog = by_id
        self._ids = frozenset(by_id)
        self._normalized = normalized
        self._aliases = {
            raw_key: relic_id
            for raw_key, relic_id in RELIC_RUN_KEY_ALIASES.items()
            if relic_id in by_id
        }

    def resolve(self, raw_key: Any) -> str | None:
        """Return the catalog id for ``raw_key`` or None when unresolvable."""
        if not isinstance(raw_key, str) or not raw_key:
            return None
        alias_id = self._aliases.get(raw_key)
        if alias_id is not None:
            return alias_id
        upper = raw_key.upper()
        if upper in self._ids:
            return upper
        return self._normalized.get(_canonical_relic_key(raw_key))


def _new_report() -> dict[str, Any]:
    return {
        "total_runs": 0,
        "valid_runs": 0,
        "filter_reasons": Counter(),
        "characters": Counter(),
        "invalid_relic_entries": 0,
        "unresolved_relic_keys": Counter(),
        "heart_win_runs": 0,
        "boss_relic_screens": Counter(),
    }


def aggregate_sts1_relics(
    runs: str | Path | Iterable[Mapping[str, Any]],
    *,
    relic_catalog: Iterable[Mapping[str, Any]],
    collected_at: str,
    source_id: str = SOURCE_ID,
    source: str = SOURCE_URL,
    min_hold_runs: int = DEFAULT_SUPPORT_MIN_HOLD_RUNS,
    min_share: float = DEFAULT_SUPPORT_MIN_SHARE,
) -> dict[str, Any]:
    """Aggregate STS1 terminal relic holds and an acceptance report in one pass.

    ``runs`` may be a path to the raw JSON array (streamed, so the large dump is
    never held in memory) or an in-memory iterable of run mappings.  A run is
    valid when it is not a beta run, chooses one of the four canonical
    characters, and records a ``relics`` list; the eligible denominator is the
    count of those runs per character.
    """
    if not isinstance(collected_at, str) or not collected_at:
        raise ValueError("collected_at must be a non-empty string")

    resolver = RelicKeyResolver(relic_catalog)
    catalog_ids = sorted(resolver.catalog)
    hold_runs = {relic_id: Counter() for relic_id in catalog_ids}
    acquisition_floors: dict[str, list[int]] = {
        relic_id: [] for relic_id in catalog_ids
    }
    acquisition_ids = frozenset(
        relic_id
        for relic_id in catalog_ids
        if resolver.catalog[relic_id].get("tier") in ACQUISITION_TIER_SET
    )
    character_runs: Counter[str] = Counter()
    heart_holds: Counter[str] = Counter()
    boss_offered: dict[str, Counter[str]] = {
        act: Counter() for act in BOSS_ACT_KEYS
    }
    boss_picked: dict[str, Counter[str]] = {
        act: Counter() for act in BOSS_ACT_KEYS
    }
    report = _new_report()

    if isinstance(runs, (str, Path)):
        run_iterator: Iterable[Mapping[str, Any]] = iter_sts1_runs(runs)
    else:
        run_iterator = runs

    for raw_run in run_iterator:
        report["total_runs"] += 1
        if not isinstance(raw_run, Mapping):
            report["filter_reasons"]["invalid_run"] += 1
            continue
        if raw_run.get("is_beta") is True:
            report["filter_reasons"]["beta"] += 1
            continue
        character = raw_run.get("character_chosen")
        if not is_character(character):
            report["filter_reasons"]["non_standard_character"] += 1
            continue
        relics = raw_run.get("relics")
        if not isinstance(relics, list):
            if "relics" in raw_run:
                report["filter_reasons"]["invalid_relics"] += 1
            else:
                report["filter_reasons"]["missing_relics"] += 1
            continue
        report["valid_runs"] += 1
        report["characters"][character] += 1
        character_runs[character] += 1

        # Heart-win presence is judged on the same audited encounter used by
        # the card snapshot (damage_taken enemy + victory), only counted here
        # within the valid non-beta run cohort.
        heart_win = is_heart_win_run(raw_run)
        if heart_win:
            report["heart_win_runs"] += 1

        seen: set[str] = set()
        for raw_relic in relics:
            if not isinstance(raw_relic, str) or not raw_relic:
                report["invalid_relic_entries"] += 1
                continue
            relic_id = resolver.resolve(raw_relic)
            if relic_id is None:
                report["unresolved_relic_keys"][raw_relic] += 1
                continue
            if relic_id in seen:
                # A terminal relic counts at most once per run.
                continue
            seen.add(relic_id)
            hold_runs[relic_id][character] += 1
            if heart_win:
                heart_holds[relic_id] += 1

        # R5B: first recorded legal acquisition floor per eligible relic.
        # ``relics_obtained`` is an incomplete log, so these runs only feed
        # the acquisition sample; terminal presence is counted separately.
        run_first_floor: dict[str, int] = {}
        obtained = raw_run.get("relics_obtained")
        if isinstance(obtained, list):
            for event in obtained:
                if not isinstance(event, Mapping):
                    continue
                floor = event.get("floor")
                if isinstance(floor, bool) or not isinstance(floor, (int, float)):
                    continue
                if isinstance(floor, float) and not floor.is_integer():
                    continue
                floor_int = int(floor)
                if floor_int < 1 or floor_int > ACQUISITION_FLOOR_MAX:
                    continue
                raw_key = event.get("key")
                if not isinstance(raw_key, str) or not raw_key:
                    continue
                relic_id = resolver.resolve(raw_key)
                if relic_id is None or relic_id not in acquisition_ids:
                    continue
                prior = run_first_floor.get(relic_id)
                if prior is None or floor_int < prior:
                    run_first_floor[relic_id] = floor_int
        for relic_id, floor_int in run_first_floor.items():
            acquisition_floors[relic_id].append(floor_int)

        boss_relics = raw_run.get("boss_relics")
        if isinstance(boss_relics, list):
            for act_index, screen in enumerate(boss_relics):
                act = _BOSS_ACT_BY_INDEX.get(act_index)
                if act is None or not isinstance(screen, Mapping):
                    continue
                report["boss_relic_screens"][act] += 1
                picked_raw = screen.get("picked")
                picked_id = (
                    resolver.resolve(picked_raw)
                    if isinstance(picked_raw, str) and picked_raw
                    else None
                )
                offered_raw: list[Any] = []
                if isinstance(picked_raw, str) and picked_raw:
                    offered_raw.append(picked_raw)
                not_picked = screen.get("not_picked")
                if isinstance(not_picked, list):
                    offered_raw.extend(
                        raw for raw in not_picked if isinstance(raw, str) and raw
                    )
                seen_screen: set[str] = set()
                for raw in offered_raw:
                    relic_id = resolver.resolve(raw)
                    if relic_id is None:
                        report["unresolved_relic_keys"][raw] += 1
                        continue
                    if relic_id in seen_screen:
                        continue
                    seen_screen.add(relic_id)
                    boss_offered[act][relic_id] += 1
                    if relic_id == picked_id:
                        boss_picked[act][relic_id] += 1

    if report["valid_runs"] < 1:
        raise ValueError("aggregate_sts1_relics requires at least one valid run")

    snapshot = _build_snapshot(
        resolver,
        hold_runs,
        acquisition_floors,
        character_runs,
        report,
        heart_holds,
        boss_offered,
        boss_picked,
        collected_at=collected_at,
        source_id=source_id,
        source=source,
        min_hold_runs=min_hold_runs,
        min_share=min_share,
    )
    validate_relic_stats_snapshot(snapshot)
    clean_report = _finalize_report(report, hold_runs, resolver)
    return {"snapshot": snapshot, "report": clean_report}


def _build_snapshot(
    resolver: RelicKeyResolver,
    hold_runs: Mapping[str, Counter[str]],
    acquisition_floors: Mapping[str, list[int]],
    character_runs: Mapping[str, int],
    report: Mapping[str, Any],
    heart_holds: Mapping[str, int],
    boss_offered: Mapping[str, Mapping[str, int]],
    boss_picked: Mapping[str, Mapping[str, int]],
    *,
    collected_at: str,
    source_id: str,
    source: str,
    min_hold_runs: int,
    min_share: float,
) -> dict[str, Any]:
    valid_runs = report["valid_runs"]
    heart_win_runs = report["heart_win_runs"]
    present_roles = [
        role for role in CHARACTERS if character_runs.get(role, 0) > 0
    ]
    character_scope = {role: character_runs[role] for role in present_roles}
    scope: dict[str, Any] = {
        "game": "sts1",
        "source_id": source_id,
        "source": source,
        "dataset": {"id": DATASET_ID, "file": DATASET_FILE},
        "collected_at": collected_at,
        "filters": {
            "is_beta": "excluded",
            "play_id": "not_deduplicated",
            "characters": "four_canonical_roles",
            "terminal_relics": "recorded_relics_list_required",
            "terminal_hold": "at_most_once_per_run",
            "catalog_color": "ignored_for_eligibility",
            "acquisition_timing": "relics_obtained_first_legal_floor_1_to_56",
        },
        "display_policy": {
            "basis": "observed_terminal_holds",
            "supported_requires": (
                "hold_runs >= min_hold_runs and "
                "hold_runs / character_runs >= min_share"
            ),
            "min_hold_runs": min_hold_runs,
            "min_share": min_share,
            "catalog_color_trusted": False,
        },
        "character_runs": character_scope,
    }
    if heart_win_runs > 0:
        scope["heart_win_runs"] = heart_win_runs
    boss_screens = {
        act: report["boss_relic_screens"].get(act, 0)
        for act in BOSS_ACT_KEYS
        if report["boss_relic_screens"].get(act, 0) > 0
    }
    if boss_screens:
        scope["boss_relic_screens"] = boss_screens

    relics: dict[str, Any] = {}
    for relic_id in sorted(hold_runs):
        record = resolver.catalog[relic_id]
        role_counts = {
            role: hold_runs[relic_id].get(role, 0) for role in present_roles
        }
        total_holds = sum(role_counts.values())
        observed = {
            role: role_counts[role] for role in present_roles if role_counts[role] > 0
        }
        supported, mode = relic_display_policy(
            observed,
            character_scope,
            min_hold_runs=min_hold_runs,
            min_share=min_share,
        )
        relic: dict[str, Any] = {
            "name_en": record["name_en"],
            "tier": record.get("tier"),
            "catalog_color": record.get("color"),
            "catalog_color_trusted": False,
            "observed_roles": {
                role: observed[role] for role in CHARACTERS if role in observed
            },
            "supported_roles": supported,
            "display_mode": mode,
            "total_hold_runs": total_holds,
            "overall": make_relic_rate_metric(total_holds, valid_runs),
            "per_character": {
                role: make_relic_rate_metric(role_counts[role], character_runs[role])
                for role in present_roles
            },
        }
        floors = acquisition_floors.get(relic_id, ())
        if record.get("tier") in ACQUISITION_TIER_SET and floors and total_holds > 0:
            act1 = sum(1 for floor in floors if floor <= ACT1_MAX_FLOOR)
            act3 = sum(1 for floor in floors if floor > ACT2_MAX_FLOOR)
            act2 = len(floors) - act1 - act3
            p25, median, p75 = acquisition_floor_quartiles(floors)
            relic[FIRST_ACQUISITION_KEY] = {
                "sample_size": len(floors),
                "final_presence_runs": total_holds,
                "coverage_rate": make_relic_rate_metric(len(floors), total_holds),
                "median_floor": median,
                "p25_floor": p25,
                "p75_floor": p75,
                "act1_rate": make_relic_rate_metric(act1, len(floors)),
                "act2_rate": make_relic_rate_metric(act2, len(floors)),
                "act3_rate": make_relic_rate_metric(act3, len(floors)),
            }
        if heart_win_runs > 0:
            relic[HEART_WIN_KEY] = make_relic_rate_metric(
                heart_holds.get(relic_id, 0),
                heart_win_runs,
            )
        if boss_screens:
            choice: dict[str, Any] = {}
            for act in boss_screens:
                screens = boss_screens[act]
                offered = boss_offered[act].get(relic_id, 0)
                picked = boss_picked[act].get(relic_id, 0)
                act_data: dict[str, Any] = {
                    "offered_count": make_relic_count_metric(offered, screens),
                    "picked_count": make_relic_count_metric(picked, screens),
                }
                if offered > 0:
                    act_data["pick_rate"] = make_relic_rate_metric(picked, offered)
                choice[act] = act_data
            relic[BOSS_CHOICE_KEY] = choice
        relics[relic_id] = relic
    return {"schema_version": SCHEMA_VERSION, "scope": scope, "relics": relics}


def _finalize_report(
    report: Mapping[str, Any],
    hold_runs: Mapping[str, Counter[str]],
    resolver: RelicKeyResolver,
) -> dict[str, Any]:
    observed_ids = [
        relic_id
        for relic_id in sorted(hold_runs)
        if sum(hold_runs[relic_id].values()) > 0
    ]
    unobserved_ids = sorted(set(resolver.catalog) - set(observed_ids))
    return {
        "total_runs": report["total_runs"],
        "valid_runs": report["valid_runs"],
        "filter_reasons": dict(sorted(report["filter_reasons"].items())),
        "characters": dict(sorted(report["characters"].items())),
        "invalid_relic_entries": report["invalid_relic_entries"],
        "unresolved_relic_keys": dict(sorted(report["unresolved_relic_keys"].items())),
        "catalog_relic_count": len(resolver.catalog),
        "observed_relic_count": len(observed_ids),
        "unobserved_relic_ids": unobserved_ids,
        "heart_win_runs": report["heart_win_runs"],
        "boss_relic_screens": {
            act: report["boss_relic_screens"].get(act, 0)
            for act in BOSS_ACT_KEYS
            if report["boss_relic_screens"].get(act, 0) > 0
        },
    }
"""Shared relic-rate snapshot helpers behind the STS1 relic snapshot.

Policy C for relic rates: never infer character eligibility from the catalog
``color`` field.  Every relic snapshot carries both a per-character hold rate
(denominator = eligible runs of that character) and an overall hold rate
(denominator = all eligible runs).  A small display policy layer chooses which
metric to surface based on the character coverage actually observed in the run
data (single-character relics default to the per-character rate, universal
four-character relics default to the overall rate).

Scope note: these helpers only back the audited STS1 terminal-hold snapshot.
They do not compute acquisition sources, floors, or STS2 statistics.
R2A-2 adds the heart-win presence rate and per-act boss choice counts for STS1.
R5B adds the optional per-relic ``first_acquisition`` section for Common /
Uncommon / Rare relics only (never Boss / Starter / Shop / Special).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"

# Canonical Slay the Spire character keys used by run records.
CHARACTERS = ("IRONCLAD", "THE_SILENT", "DEFECT", "WATCHER")
CHARACTER_SET = frozenset(CHARACTERS)

# Display modes a consumer may rely on.  ``both`` means per-character and
# overall are comparable and either may be shown.
DISPLAY_MODES = ("none", "per_character", "both", "overall")

DEFAULT_SUPPORT_MIN_HOLD_RUNS = 2
DEFAULT_SUPPORT_MIN_SHARE = 0.0005  # 0.05% of the character's eligible runs

# R2A-2 metric keys and the two STS1 boss relic acts recorded in the dump.
HEART_WIN_KEY = "heart_win_presence_rate"
BOSS_CHOICE_KEY = "boss_choice"
BOSS_ACT_KEYS = ("act1", "act2")

# R5B: optional per-relic ``first_acquisition`` timing for Common/Uncommon/Rare
# relics, sourced from ``relics_obtained`` events with a legal recorded floor.
FIRST_ACQUISITION_KEY = "first_acquisition"
ACQUISITION_TIERS = ("Common", "Uncommon", "Rare")
ACQUISITION_TIER_SET = frozenset(ACQUISITION_TIERS)
ACQUISITION_FLOOR_MIN = 1
ACQUISITION_FLOOR_MAX = 56
ACQUISITION_ACT_RATE_KEYS = ("act1_rate", "act2_rate", "act3_rate")


def is_character(value: Any) -> bool:
    """Return whether ``value`` is one of the four canonical characters."""
    return isinstance(value, str) and value in CHARACTER_SET


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string with ``Z`` suffix."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def make_relic_rate_metric(numerator: int, denominator: int) -> dict[str, Any]:
    """Build a percent hold-rate metric from count source values."""
    _integer(numerator, "metric.numerator", minimum=0)
    _integer(denominator, "metric.denominator", minimum=1)
    if numerator > denominator:
        _fail("metric", "numerator must not exceed denominator")
    metric: dict[str, Any] = {
        "value": numerator / denominator * 100,
        "unit": "percent",
        "provenance": "computed",
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
    }
    _validate_rate_metric(metric, "metric")
    return metric


def make_relic_count_metric(value: int, sample_size: int) -> dict[str, Any]:
    """Build a plain count metric (no numerator/denominator) with its sample size."""
    _integer(value, "metric.value", minimum=0)
    _integer(sample_size, "metric.sample_size", minimum=1)
    if value > sample_size:
        _fail("metric", "value must not exceed sample_size")
    metric: dict[str, Any] = {
        "value": value,
        "unit": "count",
        "provenance": "computed",
        "sample_size": sample_size,
    }
    _validate_count_metric(metric, "metric")
    return metric


def relic_display_policy(
    hold_runs: Mapping[str, int],
    eligible_runs: Mapping[str, int],
    *,
    min_hold_runs: int = DEFAULT_SUPPORT_MIN_HOLD_RUNS,
    min_share: float = DEFAULT_SUPPORT_MIN_SHARE,
) -> tuple[list[str], str]:
    """Derive supported characters and the display mode from observed holds.

    A character is *supported* when it has at least ``min_hold_runs`` terminal
    holds and those holds cover at least ``min_share`` of the character's
    eligible runs.  One- or two-run cross-character strays therefore never make
    a relic look universal.  Supported characters are returned in canonical
    character order.
    """
    if min_hold_runs < 1:
        raise ValueError("min_hold_runs must be at least 1")
    if not 0 < min_share < 1:
        raise ValueError("min_share must be between 0 and 1")

    supported: list[str] = []
    for role in CHARACTERS:
        eligible = eligible_runs.get(role, 0)
        holds = hold_runs.get(role, 0)
        if eligible < 1 or holds < min_hold_runs:
            continue
        if holds / eligible >= min_share:
            supported.append(role)

    count = len(supported)
    if count == 0:
        mode = "none"
    elif count == 1:
        mode = "per_character"
    elif count == len(CHARACTERS):
        mode = "overall"
    else:
        mode = "both"
    return supported, mode


def validate_relic_stats_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Validate the relic snapshot contract, raising ``ValueError`` on failure."""
    root = _mapping(snapshot, "snapshot")
    _exact_keys(root, {"schema_version", "relics", "scope"}, "snapshot")
    if root.get("schema_version") != SCHEMA_VERSION:
        _fail("snapshot.schema_version", f"must be {SCHEMA_VERSION!r}")

    scope = _mapping(root.get("scope"), "snapshot.scope")
    for required in ("source", "collected_at", "display_policy", "filters", "character_runs"):
        if required not in scope:
            _fail(f"snapshot.scope.{required}", "missing required field")
    character_runs = _integer_map(scope["character_runs"], "snapshot.scope.character_runs")

    heart_win_runs = 0
    if "heart_win_runs" in scope:
        _integer(scope["heart_win_runs"], "snapshot.scope.heart_win_runs", minimum=0)
        heart_win_runs = scope["heart_win_runs"]
    boss_screens: dict[str, int] = {}
    if "boss_relic_screens" in scope:
        raw_screens = _mapping(
            scope["boss_relic_screens"], "snapshot.scope.boss_relic_screens"
        )
        for act, count in raw_screens.items():
            if act not in BOSS_ACT_KEYS:
                _fail(
                    "snapshot.scope.boss_relic_screens",
                    f"keys must be one of {sorted(BOSS_ACT_KEYS)!r}",
                )
            _integer(count, f"snapshot.scope.boss_relic_screens[{act!r}]", minimum=0)
        boss_screens = {
            act: raw_screens[act]
            for act in BOSS_ACT_KEYS
            if raw_screens.get(act, 0) > 0
        }

    relics = _mapping(root.get("relics"), "snapshot.relics")
    for relic_id, raw_relic in relics.items():
        if not isinstance(relic_id, str) or not relic_id:
            _fail("snapshot.relics", "relic IDs must be non-empty strings")
        path = f"snapshot.relics[{relic_id!r}]"
        relic = _mapping(raw_relic, path)
        required_relic_fields = {
            "name_en",
            "tier",
            "catalog_color",
            "catalog_color_trusted",
            "observed_roles",
            "supported_roles",
            "display_mode",
            "total_hold_runs",
            "overall",
            "per_character",
        }
        if heart_win_runs > 0:
            required_relic_fields.add(HEART_WIN_KEY)
        if boss_screens:
            required_relic_fields.add(BOSS_CHOICE_KEY)
        if FIRST_ACQUISITION_KEY in relic:
            required_relic_fields.add(FIRST_ACQUISITION_KEY)
        _exact_keys(relic, required_relic_fields, path)
        if not isinstance(relic["name_en"], str) or not relic["name_en"]:
            _fail(f"{path}.name_en", "must be a non-empty string")
        for field_name in ("tier", "catalog_color"):
            value = relic[field_name]
            if value is not None and (not isinstance(value, str) or not value):
                _fail(f"{path}.{field_name}", "must be a non-empty string or null")
        if not isinstance(relic["catalog_color_trusted"], bool):
            _fail(f"{path}.catalog_color_trusted", "must be a boolean")
        if relic["catalog_color_trusted"] is True:
            _fail(f"{path}.catalog_color_trusted", "policy C forbids trusting catalog color")
        if relic["display_mode"] not in DISPLAY_MODES:
            _fail(f"{path}.display_mode", f"must be one of {sorted(DISPLAY_MODES)!r}")

        observed = _role_map(relic["observed_roles"], f"{path}.observed_roles")
        supported = _role_list(relic["supported_roles"], f"{path}.supported_roles")
        if not set(supported) <= set(observed):
            _fail(f"{path}.supported_roles", "supported roles must be a subset of observed roles")
        expected_mode = _display_mode_for_count(len(supported))
        if relic["display_mode"] != expected_mode:
            _fail(
                f"{path}.display_mode",
                f"must be {expected_mode!r} for {len(supported)} supported roles",
            )
        _integer(relic["total_hold_runs"], f"{path}.total_hold_runs", minimum=0)
        if relic["total_hold_runs"] != sum(observed.values()):
            _fail(f"{path}.total_hold_runs", "must equal the sum of per-character hold runs")

        overall = _mapping(relic["overall"], f"{path}.overall")
        _validate_rate_metric(overall, f"{path}.overall")
        if overall["numerator"] != relic["total_hold_runs"]:
            _fail(f"{path}.overall.numerator", "must equal total_hold_runs")

        characters = _mapping(relic["per_character"], f"{path}.per_character")
        expected_roles = {
            role for role in CHARACTERS if character_runs.get(role, 0) > 0
        }
        if set(characters) != expected_roles:
            _fail(
                f"{path}.per_character",
                "keys must exactly cover the characters with eligible runs",
            )
        denominator_sum = 0
        numerator_sum = 0
        for role, raw_metric in characters.items():
            metric = _mapping(raw_metric, f"{path}.per_character[{role!r}]")
            _validate_rate_metric(metric, f"{path}.per_character[{role!r}]")
            if metric["denominator"] != character_runs[role]:
                _fail(
                    f"{path}.per_character[{role!r}].denominator",
                    "must equal the character run count in scope",
                )
            numerator_sum += metric["numerator"]
            denominator_sum += metric["denominator"]
        if numerator_sum != relic["total_hold_runs"]:
            _fail(f"{path}.per_character", "numerator sum must equal total_hold_runs")
        if denominator_sum != overall["denominator"]:
            _fail(f"{path}.per_character", "denominator sum must equal the overall denominator")

        if FIRST_ACQUISITION_KEY in relic:
            _validate_first_acquisition(relic, path)

        if HEART_WIN_KEY in relic:
            heart_metric = _mapping(relic[HEART_WIN_KEY], f"{path}.{HEART_WIN_KEY}")
            _validate_rate_metric(heart_metric, f"{path}.{HEART_WIN_KEY}")
            if heart_metric["denominator"] != heart_win_runs:
                _fail(
                    f"{path}.{HEART_WIN_KEY}.denominator",
                    "must equal the heart-win run count in scope",
                )

        if BOSS_CHOICE_KEY in relic:
            choice = _mapping(relic[BOSS_CHOICE_KEY], f"{path}.{BOSS_CHOICE_KEY}")
            if set(choice) != set(boss_screens):
                _fail(
                    f"{path}.{BOSS_CHOICE_KEY}",
                    "must cover the same acts as snapshot.scope.boss_relic_screens",
                )
            for act in BOSS_ACT_KEYS:
                if act not in boss_screens:
                    continue
                act_path = f"{path}.{BOSS_CHOICE_KEY}.{act}"
                act_data = _mapping(choice[act], act_path)
                missing = {"offered_count", "picked_count"} - set(act_data)
                if missing:
                    _fail(act_path, f"missing required fields: {sorted(missing)!r}")
                unknown = set(act_data) - {"offered_count", "picked_count", "pick_rate"}
                if unknown:
                    _fail(act_path, f"contains unknown fields: {sorted(unknown)!r}")
                offered_metric = _mapping(
                    act_data["offered_count"], f"{act_path}.offered_count"
                )
                picked_metric = _mapping(
                    act_data["picked_count"], f"{act_path}.picked_count"
                )
                _validate_count_metric(offered_metric, f"{act_path}.offered_count")
                _validate_count_metric(picked_metric, f"{act_path}.picked_count")
                for field, metric in (
                    ("offered_count", offered_metric),
                    ("picked_count", picked_metric),
                ):
                    if metric["sample_size"] != boss_screens[act]:
                        _fail(
                            f"{act_path}.{field}.sample_size",
                            f"must equal the {act} boss screen count",
                        )
                offered = offered_metric["value"]
                picked = picked_metric["value"]
                if picked > offered:
                    _fail(f"{act_path}.picked_count", "must not exceed offered_count")
                if offered > 0:
                    if "pick_rate" not in act_data:
                        _fail(
                            f"{act_path}.pick_rate",
                            "requires pick_rate when the relic was offered",
                        )
                    pick_rate = _mapping(act_data["pick_rate"], f"{act_path}.pick_rate")
                    _validate_rate_metric(pick_rate, f"{act_path}.pick_rate")
                    if pick_rate["numerator"] != picked:
                        _fail(f"{act_path}.pick_rate.numerator", "must equal picked_count")
                    if pick_rate["denominator"] != offered:
                        _fail(f"{act_path}.pick_rate.denominator", "must equal offered_count")
                elif "pick_rate" in act_data:
                    _fail(
                        f"{act_path}.pick_rate",
                        "forbids pick_rate when the relic was never offered",
                    )


def _validate_first_acquisition(relic: Mapping[str, Any], path: str) -> None:
    """Validate the optional R5B per-relic first_acquisition section."""
    fa_path = f"{path}.{FIRST_ACQUISITION_KEY}"
    fa = _mapping(relic[FIRST_ACQUISITION_KEY], fa_path)
    if relic.get("tier") not in ACQUISITION_TIER_SET:
        _fail(
            fa_path,
            "only Common/Uncommon/Rare relics may carry first_acquisition",
        )
    _exact_keys(
        fa,
        {
            "sample_size",
            "final_presence_runs",
            "coverage_rate",
            "median_floor",
            "p25_floor",
            "p75_floor",
            *ACQUISITION_ACT_RATE_KEYS,
        },
        fa_path,
    )
    sample_size = fa["sample_size"]
    _integer(sample_size, f"{fa_path}.sample_size", minimum=1)
    presence = fa["final_presence_runs"]
    _integer(presence, f"{fa_path}.final_presence_runs", minimum=1)
    if sample_size > presence:
        _fail(f"{fa_path}.sample_size", "must not exceed final_presence_runs")
    total_holds = relic.get("total_hold_runs")
    if (
        isinstance(total_holds, int)
        and not isinstance(total_holds, bool)
        and presence != total_holds
    ):
        _fail(
            f"{fa_path}.final_presence_runs",
            "must equal total_hold_runs",
        )
    coverage = _mapping(fa["coverage_rate"], f"{fa_path}.coverage_rate")
    _validate_rate_metric(coverage, f"{fa_path}.coverage_rate")
    if coverage["numerator"] != sample_size:
        _fail(f"{fa_path}.coverage_rate.numerator", "must equal sample_size")
    if coverage["denominator"] != presence:
        _fail(
            f"{fa_path}.coverage_rate.denominator",
            "must equal final_presence_runs",
        )
    p25 = _floor_number(fa["p25_floor"], f"{fa_path}.p25_floor")
    median = _floor_number(fa["median_floor"], f"{fa_path}.median_floor")
    p75 = _floor_number(fa["p75_floor"], f"{fa_path}.p75_floor")
    for label, value in (("p25_floor", p25), ("median_floor", median), ("p75_floor", p75)):
        if not ACQUISITION_FLOOR_MIN <= value <= ACQUISITION_FLOOR_MAX:
            _fail(
                f"{fa_path}.{label}",
                f"must be between {ACQUISITION_FLOOR_MIN} and {ACQUISITION_FLOOR_MAX}",
            )
    if not p25 <= median <= p75:
        _fail(fa_path, "percentiles must satisfy p25_floor <= median_floor <= p75_floor")
    act_total = 0
    for act in ACQUISITION_ACT_RATE_KEYS:
        metric = _mapping(fa[act], f"{fa_path}.{act}")
        _validate_rate_metric(metric, f"{fa_path}.{act}")
        if metric["denominator"] != sample_size:
            _fail(f"{fa_path}.{act}.denominator", "must equal sample_size")
        act_total += metric["numerator"]
    if act_total != sample_size:
        _fail(fa_path, "act numerators must sum to sample_size")


def _floor_number(value: Any, path: str) -> float:
    """Return a numeric floor value, rejecting booleans and non-numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, "must be a number")
    return float(value)


def _validate_count_metric(metric: Mapping[str, Any], path: str) -> None:
    _exact_keys(metric, {"value", "unit", "provenance", "sample_size"}, path)
    _integer(metric["value"], f"{path}.value", minimum=0)
    if metric["unit"] != "count":
        _fail(f"{path}.unit", "must be 'count'")
    if metric["provenance"] != "computed":
        _fail(f"{path}.provenance", "must be 'computed'")
    _integer(metric["sample_size"], f"{path}.sample_size", minimum=1)
    if metric["value"] > metric["sample_size"]:
        _fail(path, "value must not exceed sample_size")


def _validate_rate_metric(metric: Mapping[str, Any], path: str) -> None:
    _exact_keys(
        metric,
        {"value", "unit", "provenance", "numerator", "denominator", "sample_size"},
        path,
    )
    value = metric["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{path}.value", "must be a number")
    if not 0 <= value <= 100:
        _fail(f"{path}.value", "must be between 0 and 100")
    if metric["unit"] != "percent":
        _fail(f"{path}.unit", "must be 'percent'")
    if metric["provenance"] != "computed":
        _fail(f"{path}.provenance", "must be 'computed'")
    _integer(metric["numerator"], f"{path}.numerator", minimum=0)
    _integer(metric["denominator"], f"{path}.denominator", minimum=1)
    _integer(metric["sample_size"], f"{path}.sample_size", minimum=1)
    if metric["numerator"] > metric["denominator"]:
        _fail(path, "numerator must not exceed denominator")
    if metric["sample_size"] != metric["denominator"]:
        _fail(f"{path}.sample_size", "must equal denominator")


def _display_mode_for_count(count: int) -> str:
    if count == 0:
        return "none"
    if count == 1:
        return "per_character"
    if count == len(CHARACTERS):
        return "overall"
    return "both"


def _role_list(value: Any, path: str) -> list[str]:
    """Validate a canonical-character role list and return it as a list."""
    if not isinstance(value, list):
        _fail(path, "must be a list of canonical characters")
    output: list[str] = []
    for role in value:
        if not is_character(role):
            _fail(path, "must contain only canonical characters")
        output.append(role)
    if len(output) != len(set(output)):
        _fail(path, "must not contain duplicates")
    return output


def _role_map(value: Any, path: str) -> dict[str, int]:
    """Validate a role-keyed integer mapping and return it as a dict."""
    mapping = _mapping(value, path)
    output: dict[str, int] = {}
    for role, count in mapping.items():
        if not is_character(role):
            _fail(path, "keys must be canonical characters")
        _integer(count, f"{path}[{role!r}]", minimum=0)
        output[role] = count
    return output


def _integer_map(value: Any, path: str) -> dict[str, int]:
    mapping = _mapping(value, path)
    output: dict[str, int] = {}
    for key, count in mapping.items():
        if not is_character(key):
            _fail(path, "keys must be canonical characters")
        _integer(count, f"{path}[{key!r}]", minimum=0)
        output[key] = count
    return output


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    path: str,
) -> None:
    missing = required - set(value)
    if missing:
        _fail(path, f"missing required fields: {sorted(missing)!r}")
    unknown = set(value) - required
    if unknown:
        _fail(path, f"contains unknown fields: {sorted(unknown)!r}")


def _integer(value: Any, path: str, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(path, f"must be an integer greater than or equal to {minimum}")


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")



# R9B: per-act boss-reward ranking for the STS1 relic snapshot.
#
# Each act forms its own cohort; ranks never merge the two boss acts.  A relic
# joins a cohort only after it has been offered enough times (STS1 keeps its
# own independent 1000-offer sample floor).  Rows are ranked by the real
# picked_count / offered_count ratio with competition ties: only relics whose
# real ratios match keep the same rank, and the next distinct ratio leaves the
# gap.  Display rounding never influences rank; offered_count and relic_id only
# stabilise the output order.
BOSS_CHOICE_MIN_OFFERED = 1000


def _metric_value(metric):
    """Return a numeric metric value, or None when unusable."""
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _boss_act_row(relic_id, act_data):
    """Return one rankable boss-choice row for an act, or None."""
    if not isinstance(act_data, dict):
        return None
    offered = _metric_value(act_data.get("offered_count"))
    picked = _metric_value(act_data.get("picked_count"))
    if not isinstance(offered, int) or not isinstance(picked, int):
        return None
    if offered < BOSS_CHOICE_MIN_OFFERED:
        return None
    rate = _metric_value(act_data.get("pick_rate"))
    if not isinstance(rate, (int, float)):
        rate = picked / offered * 100.0
    return {
        "relic_id": relic_id,
        "offered_count": offered,
        "picked_count": picked,
        "pick_rate": float(rate),
    }


def boss_choice_act_rows(snapshot, act):
    """Return one act's boss-choice cohort ranked by pick rate (top first)."""
    if act not in BOSS_ACT_KEYS:
        return []
    relic_stats = snapshot.get("relics") if isinstance(snapshot, dict) else None
    if not isinstance(relic_stats, dict):
        return []
    rows = []
    for relic_id, entry in relic_stats.items():
        if not isinstance(entry, dict):
            continue
        choice = entry.get(BOSS_CHOICE_KEY)
        if not isinstance(choice, dict):
            continue
        row = _boss_act_row(str(relic_id), choice.get(act))
        if row is not None:
            rows.append(row)
    rows.sort(
        key=lambda row: (
            -(row["picked_count"] / row["offered_count"]),
            -row["offered_count"],
            row["relic_id"],
        )
    )
    previous_ratio = None
    rank_by_id = {}
    for index, row in enumerate(rows, start=1):
        ratio = row["picked_count"] / row["offered_count"]
        if ratio != previous_ratio:
            previous_ratio = ratio
            expected_rank = index
        rank_by_id[row["relic_id"]] = expected_rank
    cohort_size = len(rows)
    ranked = []
    for row in rows:
        ranked.append(
            {
                "relic_id": row["relic_id"],
                "offered_count": row["offered_count"],
                "picked_count": row["picked_count"],
                "pick_rate": row["pick_rate"],
                "rank": rank_by_id[row["relic_id"]],
                "cohort_size": cohort_size,
            }
        )
    return ranked


def boss_choice_rank_contexts(snapshot, relic_id):
    """Return per-act ranked choice contexts for one relic.

    A context exists only for acts where the relic itself meets the offer
    floor, so the QQ layer never shows a misleading rank for low samples.
    """
    relic_id = str(relic_id or "")
    if not relic_id:
        return []
    contexts = []
    for act in BOSS_ACT_KEYS:
        row = next(
            (
                item
                for item in boss_choice_act_rows(snapshot, act)
                if item["relic_id"] == relic_id
            ),
            None,
        )
        if row is None:
            continue
        contexts.append(
            {
                "act": act,
                "pick_rate": row["pick_rate"],
                "rank": row["rank"],
                "cohort_size": row["cohort_size"],
            }
        )
    return contexts

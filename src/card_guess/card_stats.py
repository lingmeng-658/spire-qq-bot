"""Unified card-statistics snapshot helpers for STS1 and STS2."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from math import isfinite
import re
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"
ACT_KEYS = ("act_1", "act_2", "act_3")
ACT_RATE_FIELDS = {"act_pick_rate", "act_shop_buy_rate", "act_upgrade_rate"}
ACT_DELTA_FIELDS = {"act_win_delta"}
RATE_FIELDS = {
    "pick_rate",
    "skip_rate",
    "final_deck_presence_rate",
    "final_upgrade_rate",
    "repick_rate",
    "retention_rate",
    "heart_win_deck_presence_rate",
}
# Single-value (whole-run / whole-board) win-rate deltas, e.g. the STS1
# global win_delta over floors 1-50.  Shape matches act_win_delta entries.
DELTA_FIELDS = {"win_delta"}
SCALAR_UNITS = {
    "offered_count": "count",
    "picked_count": "count",
    "picked_run_count": "count",
    "skip_count": "count",
    "first_pick_floor_mean": "floor",
    "final_deck_copy_mean": "copies",
    "campfire_upgrade_count": "count",
    "campfire_upgrade_floor_mean": "floor",
}
METRIC_FIELDS = (
    ACT_RATE_FIELDS | ACT_DELTA_FIELDS | RATE_FIELDS | DELTA_FIELDS | set(SCALAR_UNITS)
)
SOURCE_METADATA_FIELDS = {
    "source",
    "scope",
    "version",
    "collected_at",
    "metric_definitions",
}
SCOPE_FIELDS = {
    "game",
    "character",
    "character_scope",
    "ascension_min",
    "ascension_max",
    "date_start",
    "date_end",
    "build_versions",
    "excluded_modes",
    "filters",
}

STS2_DEFINITIONS = {
    "act_pick_rate": {
        "description": "Published card-reward pick rate grouped by act.",
        "unit": "percent",
    },
    "act_shop_buy_rate": {
        "description": "Published shop purchase rate grouped by act.",
        "unit": "percent",
    },
    "act_upgrade_rate": {
        "description": "Published smith upgrade rate grouped by act.",
        "unit": "percent",
    },
    "act_win_delta": {
        "description": "Published run win-rate impact grouped by act.",
        "unit": "percentage_points",
    },
    "final_deck_presence_rate": {
        "description": "Published share of runs whose final deck contains the card.",
        "unit": "percent",
    },
}


def make_rate_metric(
    value: float,
    *,
    sample_size: int,
    numerator: int | None = None,
    denominator: int | None = None,
    comparison_numerator: int | None = None,
    comparison_denominator: int | None = None,
    provenance: str = "computed",
    unit: str = "percent",
) -> dict[str, Any]:
    """Build a rate metric without deriving missing source counts."""
    if unit not in {"percent", "percentage_points"}:
        raise ValueError("metric.unit: must be 'percent' or 'percentage_points'")
    metric: dict[str, Any] = {
        "value": value,
        "unit": unit,
        "provenance": provenance,
    }
    if numerator is not None:
        metric["numerator"] = numerator
    if denominator is not None:
        metric["denominator"] = denominator
    if comparison_numerator is not None:
        metric["comparison_numerator"] = comparison_numerator
    if comparison_denominator is not None:
        metric["comparison_denominator"] = comparison_denominator
    metric["sample_size"] = sample_size
    _validate_rate_metric(
        metric,
        "metric",
        expected_unit=unit,
        is_delta=unit == "percentage_points",
    )
    return metric


def validate_card_stats_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Validate the unified snapshot contract, raising ``ValueError`` on failure."""
    root = _mapping(snapshot, "snapshot")
    _exact_keys(root, {"schema_version", "cards"}, "snapshot")
    if root.get("schema_version") != SCHEMA_VERSION:
        _fail("snapshot.schema_version", f"must be {SCHEMA_VERSION!r}")

    cards = _mapping(root.get("cards"), "snapshot.cards")
    for card_id, raw_card in cards.items():
        if not isinstance(card_id, str) or not card_id:
            _fail("snapshot.cards", "card IDs must be non-empty strings")
        card_path = f"snapshot.cards[{card_id!r}]"
        card = _mapping(raw_card, card_path)
        _exact_keys(card, {"metrics"}, card_path, optional={"name", "character"})
        for optional_name in ("name", "character"):
            if optional_name in card and not isinstance(card[optional_name], str):
                _fail(f"{card_path}.{optional_name}", "must be a string")

        sources = _mapping(card.get("metrics"), f"{card_path}.metrics")
        for source_id, raw_source in sources.items():
            if not isinstance(source_id, str) or not source_id:
                _fail(f"{card_path}.metrics", "source IDs must be non-empty strings")
            _validate_source_metrics(
                raw_source,
                f"{card_path}.metrics[{source_id!r}]",
            )


def adapt_sts2_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the existing STS2 snapshot in memory without rewriting it."""
    old = _mapping(snapshot, "sts2_snapshot")
    if old.get("game") != "sts2":
        _fail("sts2_snapshot.game", "must be 'sts2'")
    cards = _mapping(old.get("cards"), "sts2_snapshot.cards")
    source_metadata = _mapping(old.get("sources"), "sts2_snapshot.sources")

    adapted: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "cards": {}}
    for card_id, raw_card in cards.items():
        card = _mapping(raw_card, f"sts2_snapshot.cards[{card_id!r}]")
        output_card: dict[str, Any] = {"metrics": {}}
        if isinstance(card.get("name"), str):
            output_card["name"] = card["name"]
        if isinstance(card.get("pool"), str):
            output_card["character"] = card["pool"]

        untapped_metrics = _adapt_untapped(card.get("untapped"))
        if untapped_metrics:
            output_card["metrics"]["untapped"] = _source_record(
                source_metadata,
                "untapped",
                untapped_metrics,
            )

        codex_metrics = _adapt_spire_codex(card.get("spire_codex"))
        if codex_metrics:
            output_card["metrics"]["spire_codex"] = _source_record(
                source_metadata,
                "spire_codex",
                codex_metrics,
            )

        adapted["cards"][card_id] = output_card

    validate_card_stats_snapshot(adapted)
    return adapted


def _adapt_untapped(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    source = _mapping(raw, "untapped")
    result: dict[str, Any] = {}
    mappings = (
        ("act_pick_rate", "card_reward", "pick_rate", "percent"),
        ("act_shop_buy_rate", "shop", "purchase_rate", "percent"),
        ("act_upgrade_rate", "smith", "upgrade_rate", "percent"),
        (
            "act_win_delta",
            "card_reward",
            "run_win_rate_impact",
            "percentage_points",
        ),
    )
    for target, section_name, metric_name, unit in mappings:
        section = source.get(section_name)
        if not isinstance(section, Mapping):
            continue
        acts: dict[str, Any] = {}
        for act in ACT_KEYS:
            act_data = section.get(act)
            if not isinstance(act_data, Mapping) or metric_name not in act_data:
                continue
            acts[act] = _reported_metric(act_data[metric_name], unit)
        if acts:
            result[target] = acts
    return result


def _adapt_spire_codex(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    source = _mapping(raw, "spire_codex")
    metric = source.get("final_deck_presence_rate")
    if metric is None:
        return {}
    return {"final_deck_presence_rate": _reported_metric(metric, "percent")}


def _reported_metric(raw: Any, expected_unit: str) -> dict[str, Any]:
    source = _mapping(raw, "reported_metric")
    if "value" not in source or "sample_size" not in source:
        _fail("reported_metric", "requires value and sample_size")
    return make_rate_metric(
        value=source["value"],
        sample_size=source["sample_size"],
        numerator=source.get("numerator"),
        denominator=source.get("denominator"),
        provenance="reported",
        unit=source.get("unit", expected_unit),
    )


def _source_record(
    all_metadata: Mapping[str, Any],
    source_id: str,
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _mapping(
        all_metadata.get(source_id),
        f"sts2_snapshot.sources[{source_id!r}]",
    )
    source_scope = _mapping(metadata.get("scope"), f"{source_id}.scope")
    version = _mapping(metadata.get("version"), f"{source_id}.version")
    scope: dict[str, Any] = {
        "game": "sts2",
        "character_scope": (
            "card_pool" if source_scope.get("character") == "card pool" else "all"
        ),
    }

    ascension = source_scope.get("ascension")
    if isinstance(ascension, str) and (match := re.fullmatch(r"(\d+)\+", ascension)):
        scope["ascension_min"] = int(match.group(1))

    game_version = version.get("game_version")
    if isinstance(game_version, str) and game_version:
        scope["build_versions"] = [game_version]
    if source_scope:
        scope["filters"] = deepcopy(dict(source_scope))

    collected_at = metadata.get("collected_at")
    record: dict[str, Any] = {
        "source": metadata.get("source"),
        "scope": scope,
        "version": deepcopy(dict(version)),
        "collected_at": collected_at,
        "metric_definitions": {
            name: deepcopy(STS2_DEFINITIONS[name]) for name in metrics
        },
    }
    record.update(deepcopy(dict(metrics)))
    return record


def _validate_source_metrics(raw: Any, path: str) -> None:
    source = _mapping(raw, path)
    _exact_keys(
        source,
        SOURCE_METADATA_FIELDS,
        path,
        optional=METRIC_FIELDS,
    )
    if not isinstance(source.get("source"), str) or not source["source"]:
        _fail(f"{path}.source", "must be a non-empty string")
    _validate_scope(source.get("scope"), f"{path}.scope")
    version = _mapping(source.get("version"), f"{path}.version")
    if not version:
        _fail(f"{path}.version", "must not be empty")
    _validate_datetime(source.get("collected_at"), f"{path}.collected_at")

    present_metrics = set(source) & METRIC_FIELDS
    if not present_metrics:
        _fail(path, "must contain at least one metric")
    definitions = _mapping(source.get("metric_definitions"), f"{path}.metric_definitions")
    if set(definitions) != present_metrics:
        _fail(
            f"{path}.metric_definitions",
            "must define exactly the metrics present in this source",
        )

    for name in sorted(present_metrics):
        expected_unit = _metric_unit(name)
        _validate_definition(
            definitions[name],
            f"{path}.metric_definitions[{name!r}]",
            expected_unit,
        )
        if name in ACT_RATE_FIELDS:
            _validate_acts(source[name], f"{path}.{name}", expected_unit="percent")
        elif name in ACT_DELTA_FIELDS:
            _validate_acts(
                source[name],
                f"{path}.{name}",
                expected_unit="percentage_points",
                is_delta=True,
            )
        elif name in RATE_FIELDS:
            _validate_rate_metric(source[name], f"{path}.{name}", expected_unit="percent")
        elif name in DELTA_FIELDS:
            _validate_rate_metric(
                source[name],
                f"{path}.{name}",
                expected_unit="percentage_points",
                is_delta=True,
            )
        else:
            _validate_scalar_metric(
                source[name],
                f"{path}.{name}",
                expected_unit=SCALAR_UNITS[name],
            )


def _validate_scope(raw: Any, path: str) -> None:
    scope = _mapping(raw, path)
    _exact_keys(scope, {"game", "character_scope"}, path, optional=SCOPE_FIELDS - {"game", "character_scope"})
    if scope.get("game") not in {"sts1", "sts2"}:
        _fail(f"{path}.game", "must be 'sts1' or 'sts2'")
    if not isinstance(scope.get("character_scope"), str) or not scope["character_scope"]:
        _fail(f"{path}.character_scope", "must be a non-empty string")
    if "character" in scope and (
        not isinstance(scope["character"], str) or not scope["character"]
    ):
        _fail(f"{path}.character", "must be a non-empty string")
    for name in ("ascension_min", "ascension_max"):
        if name in scope:
            _positive_integer(scope[name], f"{path}.{name}", allow_zero=True)
    if (
        "ascension_min" in scope
        and "ascension_max" in scope
        and scope["ascension_min"] > scope["ascension_max"]
    ):
        _fail(path, "ascension_min must not exceed ascension_max")
    for name in ("date_start", "date_end"):
        if name in scope:
            _validate_date(scope[name], f"{path}.{name}")
    if (
        "date_start" in scope
        and "date_end" in scope
        and scope["date_start"] > scope["date_end"]
    ):
        _fail(path, "date_start must not exceed date_end")
    for name in ("build_versions", "excluded_modes"):
        if name in scope:
            _string_list(scope[name], f"{path}.{name}")
    if "filters" in scope:
        _mapping(scope["filters"], f"{path}.filters")


def _validate_definition(raw: Any, path: str, expected_unit: str) -> None:
    definition = _mapping(raw, path)
    _exact_keys(definition, {"description", "unit"}, path, optional={"formula"})
    if not isinstance(definition.get("description"), str) or not definition["description"]:
        _fail(f"{path}.description", "must be a non-empty string")
    if definition.get("unit") != expected_unit:
        _fail(f"{path}.unit", f"must be {expected_unit!r}")
    if "formula" in definition and (
        not isinstance(definition["formula"], str) or not definition["formula"]
    ):
        _fail(f"{path}.formula", "must be a non-empty string")


def _validate_acts(raw: Any, path: str, *, expected_unit: str, is_delta: bool = False) -> None:
    acts = _mapping(raw, path)
    if not acts:
        _fail(path, "must contain at least one act")
    unknown = set(acts) - set(ACT_KEYS)
    if unknown:
        _fail(path, f"contains unsupported acts: {sorted(unknown)!r}")
    for act, metric in acts.items():
        _validate_rate_metric(
            metric,
            f"{path}.{act}",
            expected_unit=expected_unit,
            is_delta=is_delta,
        )


def _validate_rate_metric(
    raw: Any,
    path: str,
    *,
    expected_unit: str,
    is_delta: bool = False,
) -> None:
    metric = _mapping(raw, path)
    optional = {"numerator", "denominator"}
    if is_delta:
        optional |= {"comparison_numerator", "comparison_denominator"}
    _exact_keys(
        metric,
        {"value", "unit", "provenance", "sample_size"},
        path,
        optional=optional,
    )
    value = metric.get("value")
    if not _number(value) or not isfinite(value):
        _fail(f"{path}.value", "must be a finite number")
    lower, upper = (-100, 100) if is_delta else (0, 100)
    if not lower <= value <= upper:
        _fail(f"{path}.value", f"must be between {lower} and {upper}")
    if metric.get("unit") != expected_unit:
        _fail(f"{path}.unit", f"must be {expected_unit!r}")
    if metric.get("provenance") not in {"computed", "reported"}:
        _fail(f"{path}.provenance", "must be 'computed' or 'reported'")
    _positive_integer(metric.get("sample_size"), f"{path}.sample_size")
    _validate_count_pair(metric, path, "numerator", "denominator")
    if is_delta:
        _validate_count_pair(
            metric,
            path,
            "comparison_numerator",
            "comparison_denominator",
        )
    if metric["provenance"] == "computed":
        if "numerator" not in metric or "denominator" not in metric:
            _fail(path, "computed rate requires numerator and denominator")
        if is_delta and (
            "comparison_numerator" not in metric
            or "comparison_denominator" not in metric
        ):
            _fail(path, "computed delta requires comparison numerator and denominator")


def _validate_count_pair(
    metric: Mapping[str, Any],
    path: str,
    numerator_name: str,
    denominator_name: str,
) -> None:
    has_numerator = numerator_name in metric
    has_denominator = denominator_name in metric
    if has_numerator != has_denominator:
        _fail(path, f"{numerator_name} and {denominator_name} must appear together")
    if not has_numerator:
        return
    _positive_integer(metric[numerator_name], f"{path}.{numerator_name}", allow_zero=True)
    _positive_integer(metric[denominator_name], f"{path}.{denominator_name}")
    if metric[numerator_name] > metric[denominator_name]:
        _fail(path, f"{numerator_name} must not exceed {denominator_name}")


def _validate_scalar_metric(raw: Any, path: str, *, expected_unit: str) -> None:
    metric = _mapping(raw, path)
    _exact_keys(metric, {"value", "unit", "provenance", "sample_size"}, path)
    value = metric.get("value")
    if not _number(value) or not isfinite(value) or value < 0:
        _fail(f"{path}.value", "must be a finite non-negative number")
    if expected_unit == "count" and not isinstance(value, int):
        _fail(f"{path}.value", "must be an integer for count metrics")
    if metric.get("unit") != expected_unit:
        _fail(f"{path}.unit", f"must be {expected_unit!r}")
    if metric.get("provenance") not in {"computed", "reported"}:
        _fail(f"{path}.provenance", "must be 'computed' or 'reported'")
    _positive_integer(metric.get("sample_size"), f"{path}.sample_size")


def _metric_unit(name: str) -> str:
    if name in ACT_DELTA_FIELDS or name in DELTA_FIELDS:
        return "percentage_points"
    if name in ACT_RATE_FIELDS or name in RATE_FIELDS:
        return "percent"
    return SCALAR_UNITS[name]


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    required: set[str],
    path: str,
    *,
    optional: set[str] | None = None,
) -> None:
    missing = required - set(value)
    if missing:
        _fail(path, f"missing required fields: {sorted(missing)!r}")
    unknown = set(value) - required - (optional or set())
    if unknown:
        _fail(path, f"contains unknown fields: {sorted(unknown)!r}")


def _positive_integer(value: Any, path: str, *, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _fail(path, f"must be an integer greater than or equal to {minimum}")


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _string_list(value: Any, path: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        _fail(path, "must be a list of non-empty strings")
    if len(value) != len(set(value)):
        _fail(path, "must not contain duplicates")


def _validate_date(value: Any, path: str) -> None:
    if not isinstance(value, str):
        _fail(path, "must be an ISO date string")
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail(path, "must be an ISO date string")


def _validate_datetime(value: Any, path: str) -> None:
    if not isinstance(value, str):
        _fail(path, "must be an ISO date-time with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail(path, "must be an ISO date-time with timezone")
    if parsed.tzinfo is None:
        _fail(path, "must include a timezone")


def _fail(path: str, message: str) -> None:
    raise ValueError(f"{path}: {message}")

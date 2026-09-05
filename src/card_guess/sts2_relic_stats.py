"""STS2 relic run-presence snapshot aggregation from Spire Codex relic metrics.

Development-time data layer.  The builder turns the audited Spire Codex
``/api/runs/metrics/relics`` payloads (one unfiltered call plus one call per
canonical character) into a local snapshot consumed by runtime/bot code; the
bot never calls the source directly.

Audit notes encoded in this module:

- Relic rows carry no offer semantics: ``offered`` / ``picked`` /
  ``pick_rate`` are 0/null for relics.  ``picks`` is the number of runs where
  the relic is present in the terminal relic set; the source guarantees
  ``wins + losses == picks`` and ``win_rate == wins / picks``.
- ``total_runs`` (bracket level) is the only overall denominator.  Per
  character the source exposes ``character_runs`` / ``character_wins``; those
  are the per-character denominators.  All-character denominators are never
  used for character-specific reads.
- ``by_character``/character-filtered rows are run-participant breakouts: a
  co-op run counts under each participating character, so a party relic can
  appear under several characters.  Character rows therefore never prove
  ownership; the catalog ``color`` field is stored but never trusted for
  eligibility (policy C, mirrored from STS1).

Rates are stored with explicit numerator/denominator and are never inferred
where the source provides no valid denominator.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Canonical Slay the Spire 2 character keys used by Spire Codex run records.
STS2_CHARACTERS = ("IRONCLAD", "SILENT", "DEFECT", "REGENT", "NECROBINDER")
STS2_CHARACTER_SET = frozenset(STS2_CHARACTERS)

SCHEMA_VERSION = "1.0.0"

SOURCE_NAME = "spire-codex"
DATASET_ID = "spire_codex_relic_metrics"
SPIRE_CODEX_BASE_URL = "https://spire-codex.com"
SPIRE_CODEX_METRICS_URL = f"{SPIRE_CODEX_BASE_URL}/api/runs/metrics/relics"

COLLECTED_FROM = (
    "https://spire-codex.com/api/runs/metrics/relics",
    "https://spire-codex.com/api/runs/metrics/relics?character=IRONCLAD",
    "https://spire-codex.com/api/runs/metrics/relics?character=SILENT",
    "https://spire-codex.com/api/runs/metrics/relics?character=DEFECT",
    "https://spire-codex.com/api/runs/metrics/relics?character=REGENT",
    "https://spire-codex.com/api/runs/metrics/relics?character=NECROBINDER",
)


def _fail(message: str) -> None:
    raise ValueError(message)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{path} must be a mapping")
    return dict(value)


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{path} must be a non-empty string")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{path} must be an integer")
    if value < minimum:
        _fail(f"{path} must be at least {minimum}")
    return value


def _number(value: Any, path: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{path} must be a number or null")
    return float(value)


def _count_metric(
    value: float, numerator: int, denominator: int, sample_size: int
) -> dict[str, Any]:
    if numerator < 0 or denominator < 1 or numerator > denominator:
        _fail("count metric requires 0 <= numerator <= denominator")
    return {
        "value": value,
        "unit": "percent",
        "provenance": "computed",
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": sample_size,
    }


def _win_rate_metric(wins: int, picks: int) -> dict[str, Any] | None:
    if picks < 1:
        return None
    return _count_metric(wins / picks * 100, wins, picks, picks)


def _presence_metric(picks: int, denominator: int) -> dict[str, Any]:
    return _count_metric(picks / denominator * 100, picks, denominator, denominator)


def _parse_row_counts(
    row: Mapping[str, Any], relic_id: str, path: str
) -> tuple[int, int, int]:
    picks = _integer(row.get("picks"), f"{path}.picks")
    wins = _integer(row.get("wins"), f"{path}.wins")
    losses = _integer(row.get("losses"), f"{path}.losses")
    if wins > picks or losses > picks:
        _fail(f"{path} counts exceed picks for relic {relic_id!r}")
    if picks > 0 and losses != picks - wins:
        _fail(
            f"{path} losses must equal picks - wins for relic {relic_id!r}"
        )
    return picks, wins, losses


def _iter_valid_rows(
    payload: Mapping[str, Any],
    *,
    path: str,
    unresolved: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        _fail(f"{path}.rows must be a list")
    result: dict[str, dict[str, Any]] = {}
    for index, raw_row in enumerate(rows):
        row_path = f"{path}.rows[{index}]"
        row = _mapping(raw_row, row_path)
        relic_id = row.get("id")
        if not isinstance(relic_id, str) or not relic_id:
            unresolved.append(
                {"source": SOURCE_NAME, "reason": "invalid_row", "relic_id": ""}
            )
            continue
        normalized_id = relic_id.upper()
        if row.get("upgraded") is True:
            unresolved.append(
                {
                    "source": SOURCE_NAME,
                    "reason": "upgraded_row",
                    "relic_id": normalized_id,
                }
            )
            continue
        _parse_row_counts(row, normalized_id, row_path)
        result[normalized_id] = dict(row)
    return result


def _build_relic_entry(
    relic_id: str,
    catalog_record: Mapping[str, Any],
    overall_row: Mapping[str, Any],
    per_character_rows: Mapping[str, Mapping[str, Any]],
    character_runs: Mapping[str, int],
    total_runs: int,
) -> dict[str, Any]:
    overall_picks, overall_wins, overall_losses = _parse_row_counts(
        overall_row, relic_id, f"overall row {relic_id!r}"
    )
    overall: dict[str, Any] = {
        "picks": overall_picks,
        "wins": overall_wins,
        "losses": overall_losses,
        "win_rate": _win_rate_metric(overall_wins, overall_picks),
        "presence_rate": _presence_metric(overall_picks, total_runs),
    }
    per_character: dict[str, Any] = {}
    for character in STS2_CHARACTERS:
        row = per_character_rows.get(character, {}).get(relic_id)
        if row is None:
            continue
        picks, wins, losses = _parse_row_counts(
            row, relic_id, f"character row {character} {relic_id!r}"
        )
        eligible = character_runs.get(character, 0)
        if eligible < 1:
            _fail(
                f"character_runs[{character!r}] must be positive for relic {relic_id!r}"
            )
        if picks > eligible:
            _fail(
                f"character row picks exceed character_runs for relic {relic_id!r} "
                f"({character})"
            )
        per_character[character] = {
            "picks": picks,
            "wins": wins,
            "losses": losses,
            "win_rate": _win_rate_metric(wins, picks),
            "presence_rate": _presence_metric(picks, eligible),
        }
    return {
        "name_en": catalog_record.get("name_en"),
        "tier": catalog_record.get("tier"),
        "catalog_color": catalog_record.get("color"),
        "catalog_color_trusted": False,
        "source_score": overall_row.get("score"),
        "source_tier": overall_row.get("tier"),
        "overall": overall,
        "per_character": per_character,
    }


def build_sts2_relic_snapshot(
    *,
    overall_payload: Mapping[str, Any],
    character_payloads: Mapping[str, Mapping[str, Any]],
    relic_catalog: Iterable[Mapping[str, Any]],
    collected_at: str,
    collected_from: Iterable[str] = COLLECTED_FROM,
    dataset_id: str = DATASET_ID,
) -> dict[str, Any]:
    """Build the STS2 relic snapshot from Spire Codex metrics payloads.

    ``overall_payload`` is the unfiltered relic metrics response and
    ``character_payloads`` maps each canonical STS2 character to its
    character-filtered relic metrics response.  Every canonical character must
    be present so per-character denominators are never silently dropped.
    """
    _string(collected_at, "collected_at")
    overall = _mapping(overall_payload, "overall_payload")
    total_runs = _integer(overall.get("total_runs"), "total_runs", minimum=1)
    baseline_win_rate = _number(
        overall.get("baseline_win_rate"), "baseline_win_rate"
    )

    if not isinstance(character_payloads, Mapping):
        _fail("character_payloads must be a mapping")
    provided = {str(key).upper() for key in character_payloads}
    missing = STS2_CHARACTER_SET - provided
    if missing:
        _fail(f"character_payloads must cover every canonical character; missing: {sorted(missing)}")
    unknown = provided - STS2_CHARACTER_SET
    if unknown:
        _fail(f"character_payloads contains unknown characters: {sorted(unknown)}")

    unresolved: list[dict[str, Any]] = []
    overall_rows = _iter_valid_rows(
        overall, path="overall_payload", unresolved=unresolved
    )

    character_rows: dict[str, dict[str, Any]] = {}
    character_runs: dict[str, int] = {}
    character_wins: dict[str, int] = {}
    for character in STS2_CHARACTERS:
        payload = _mapping(
            character_payloads[character],
            f"character_payloads[{character!r}]",
        )
        runs = _integer(
            payload.get("character_runs"),
            f"character_payloads[{character!r}].character_runs",
            minimum=1,
        )
        wins = _integer(
            payload.get("character_wins"),
            f"character_payloads[{character!r}].character_wins",
        )
        if wins > runs:
            _fail(f"character_wins must not exceed character_runs ({character})")
        character_runs[character] = runs
        character_wins[character] = wins
        character_rows[character] = _iter_valid_rows(
            payload,
            path=f"character_payloads[{character!r}]",
            unresolved=unresolved,
        )

    catalog: dict[str, dict[str, Any]] = {}
    for record in relic_catalog:
        record = _mapping(record, "relic_catalog")
        relic_id = record.get("id")
        if not isinstance(relic_id, str) or not relic_id:
            _fail("relic_catalog ids must be non-empty strings")
        normalized_id = relic_id.upper()
        if normalized_id in catalog:
            _fail(f"duplicate relic catalog id: {relic_id!r}")
        catalog[normalized_id] = dict(record)

    relics: dict[str, Any] = {}
    for relic_id in sorted(set(overall_rows) & set(catalog)):
        relics[relic_id] = _build_relic_entry(
            relic_id,
            catalog[relic_id],
            overall_rows[relic_id],
            character_rows,
            character_runs,
            total_runs,
        )

    for relic_id in sorted(set(overall_rows) - set(catalog)):
        unresolved.append(
            {
                "source": SOURCE_NAME,
                "reason": "api_relic_missing_from_local_catalog",
                "relic_id": relic_id,
            }
        )
    for relic_id in sorted(set(catalog) - set(overall_rows)):
        unresolved.append(
            {
                "source": "local_catalog",
                "reason": "catalog_relic_missing_from_source",
                "relic_id": relic_id,
            }
        )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "game": "sts2",
        "scope": {
            "game": "sts2",
            "source": SOURCE_NAME,
            "dataset": {"id": dataset_id, "bracket": "all"},
            "collected_from": sorted(str(url) for url in collected_from),
            "collected_at": collected_at,
            "filters": {
                "players": "solo_and_coop",
                "per_character_unit": (
                    "run participant character: co-op submissions are counted "
                    "per participant, so party relic presence can appear under "
                    "several characters and never proves ownership"
                ),
                "catalog_color": "ignored_for_eligibility",
                "upgraded_rows": "excluded",
            },
            "total_runs": total_runs,
            "baseline_win_rate": baseline_win_rate,
            "character_runs": character_runs,
            "character_wins": character_wins,
        },
        "relics": relics,
        "unresolved": unresolved,
    }
    validate_sts2_relic_snapshot(snapshot)
    return snapshot


_METRIC_KEYS = frozenset(
    {"value", "unit", "provenance", "numerator", "denominator", "sample_size"}
)


def _validate_metric(
    metric: Any, path: str, *, numerator: int, denominator: int
) -> None:
    metric = _mapping(metric, path)
    if set(metric) != _METRIC_KEYS:
        _fail(f"{path} keys must be {sorted(_METRIC_KEYS)!r}")
    value = _number(metric.get("value"), f"{path}.value")
    if value is None or value < 0:
        _fail(f"{path}.value must be a non-negative number")
    if metric.get("unit") != "percent":
        _fail(f"{path}.unit must be 'percent'")
    if metric.get("provenance") != "computed":
        _fail(f"{path}.provenance must be 'computed'")
    metric_numerator = _integer(
        metric.get("numerator"), f"{path}.numerator"
    )
    metric_denominator = _integer(
        metric.get("denominator"), f"{path}.denominator"
    )
    if metric_numerator != numerator:
        _fail(f"{path}.numerator must equal {numerator}")
    if metric_denominator != denominator:
        _fail(f"{path}.denominator must equal {denominator}")
    if metric_numerator > metric_denominator:
        _fail(f"{path} numerator must not exceed denominator")
    if _integer(metric.get("sample_size"), f"{path}.sample_size") != denominator:
        _fail(f"{path}.sample_size must equal {denominator}")


def _validate_counts_block(
    block: Any,
    path: str,
    *,
    presence_denominator: int,
    expected_keys: frozenset[str],
) -> None:
    block = _mapping(block, path)
    if set(block) != expected_keys:
        _fail(f"{path} keys must be {sorted(expected_keys)!r}")
    block_picks = _integer(block.get("picks"), f"{path}.picks")
    wins = _integer(block.get("wins"), f"{path}.wins")
    losses = _integer(block.get("losses"), f"{path}.losses")
    if wins > block_picks or losses > block_picks:
        _fail(f"{path} counts must not exceed picks")
    if block_picks > 0 and losses != block_picks - wins:
        _fail(f"{path}.losses must equal picks - wins")
    win_rate = block.get("win_rate")
    if block_picks > 0:
        _validate_metric(win_rate, f"{path}.win_rate", numerator=wins, denominator=block_picks)
    elif win_rate is not None:
        _fail(f"{path}.win_rate must be null when picks is zero")
    _validate_metric(
        block.get("presence_rate"),
        f"{path}.presence_rate",
        numerator=block_picks,
        denominator=presence_denominator,
    )


def validate_sts2_relic_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Validate the STS2 relic snapshot contract, raising ``ValueError``."""
    root = _mapping(snapshot, "snapshot")
    if set(root) != {"schema_version", "game", "scope", "relics", "unresolved"}:
        _fail("snapshot keys must be schema_version/game/scope/relics/unresolved")
    if root.get("schema_version") != SCHEMA_VERSION:
        _fail(f"snapshot.schema_version must be {SCHEMA_VERSION!r}")
    if root.get("game") != "sts2":
        _fail("snapshot.game must be 'sts2'")

    scope = _mapping(root.get("scope"), "snapshot.scope")
    expected_scope_keys = {
        "game",
        "source",
        "dataset",
        "collected_from",
        "collected_at",
        "filters",
        "total_runs",
        "baseline_win_rate",
        "character_runs",
        "character_wins",
    }
    if set(scope) != expected_scope_keys:
        _fail(f"snapshot.scope keys must be {sorted(expected_scope_keys)!r}")
    if scope.get("game") != "sts2":
        _fail("snapshot.scope.game must be 'sts2'")
    _string(scope.get("source"), "snapshot.scope.source")
    dataset = _mapping(scope.get("dataset"), "snapshot.scope.dataset")
    if set(dataset) != {"id", "bracket"}:
        _fail("snapshot.scope.dataset keys must be id/bracket")
    _string(dataset.get("id"), "snapshot.scope.dataset.id")
    _string(dataset.get("bracket"), "snapshot.scope.dataset.bracket")
    collected_from = scope.get("collected_from")
    if not isinstance(collected_from, list) or not collected_from:
        _fail("snapshot.scope.collected_from must be a non-empty list")
    for url in collected_from:
        _string(url, "snapshot.scope.collected_from")
    _string(scope.get("collected_at"), "snapshot.scope.collected_at")
    filters = _mapping(scope.get("filters"), "snapshot.scope.filters")
    for key, value in filters.items():
        _string(value, f"snapshot.scope.filters[{key!r}]")

    total_runs = _integer(scope.get("total_runs"), "snapshot.scope.total_runs", minimum=1)
    _number(scope.get("baseline_win_rate"), "snapshot.scope.baseline_win_rate")

    character_runs_raw = _mapping(
        scope.get("character_runs"), "snapshot.scope.character_runs"
    )
    character_wins_raw = _mapping(
        scope.get("character_wins"), "snapshot.scope.character_wins"
    )
    if set(character_runs_raw) != STS2_CHARACTER_SET:
        _fail(
            "snapshot.scope.character_runs must cover exactly "
            f"{sorted(STS2_CHARACTERS)!r}"
        )
    character_runs = {
        character: _integer(
            character_runs_raw[character],
            f"snapshot.scope.character_runs[{character!r}]",
            minimum=1,
        )
        for character in STS2_CHARACTERS
    }
    if set(character_wins_raw) != STS2_CHARACTER_SET:
        _fail("snapshot.scope.character_wins must cover exactly every character")
    for character in STS2_CHARACTERS:
        wins = _integer(
            character_wins_raw[character],
            f"snapshot.scope.character_wins[{character!r}]",
        )
        if wins > character_runs[character]:
            _fail(
                f"snapshot.scope.character_wins[{character!r}] "
                "must not exceed character_runs"
            )

    relics = _mapping(root.get("relics"), "snapshot.relics")
    block_keys = frozenset({"picks", "wins", "losses", "win_rate", "presence_rate"})
    for relic_id, raw_relic in relics.items():
        if not isinstance(relic_id, str) or not relic_id:
            _fail("snapshot.relics relic IDs must be non-empty strings")
        path = f"snapshot.relics[{relic_id!r}]"
        relic = _mapping(raw_relic, path)
        expected_relic_keys = {
            "name_en",
            "tier",
            "catalog_color",
            "catalog_color_trusted",
            "source_score",
            "source_tier",
            "overall",
            "per_character",
        }
        if set(relic) != expected_relic_keys:
            _fail(f"{path} keys must be {sorted(expected_relic_keys)!r}")
        _string(relic.get("name_en"), f"{path}.name_en")
        for field_name in ("tier", "catalog_color"):
            value = relic.get(field_name)
            if value is not None and (not isinstance(value, str) or not value):
                _fail(f"{path}.{field_name} must be a non-empty string or null")
        if relic.get("catalog_color_trusted") is not False:
            _fail(f"{path}.catalog_color_trusted policy C forbids trusting color")
        source_score = relic.get("source_score")
        if source_score is not None:
            _integer(source_score, f"{path}.source_score")
        source_tier = relic.get("source_tier")
        if source_tier is not None and (
            not isinstance(source_tier, str) or not source_tier
        ):
            _fail(f"{path}.source_tier must be a non-empty string or null")

        overall = relic.get("overall")
        _validate_counts_block(
            overall,
            f"{path}.overall",
            presence_denominator=total_runs,
            expected_keys=block_keys,
        )

        per_character = _mapping(relic.get("per_character"), f"{path}.per_character")
        if not per_character:
            _fail(f"{path}.per_character must not be empty")
        for character, raw_block in per_character.items():
            if character not in STS2_CHARACTER_SET:
                _fail(f"{path}.per_character contains unknown character {character!r}")
            block = _mapping(raw_block, f"{path}.per_character[{character!r}]")
            _validate_counts_block(
                block,
                f"{path}.per_character[{character!r}]",
                presence_denominator=character_runs[character],
                expected_keys=block_keys,
            )

    unresolved = root.get("unresolved")
    if not isinstance(unresolved, list):
        _fail("snapshot.unresolved must be a list")
    for index, raw_item in enumerate(unresolved):
        path = f"snapshot.unresolved[{index}]"
        item = _mapping(raw_item, path)
        if set(item) != {"source", "reason", "relic_id"}:
            _fail(f"{path} keys must be source/reason/relic_id")
        _string(item.get("source"), f"{path}.source")
        _string(item.get("reason"), f"{path}.reason")
        relic_id = item.get("relic_id")
        if not isinstance(relic_id, str):
            _fail(f"{path}.relic_id must be a string")

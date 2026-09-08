"""Event Data Core v1.

Frozen Event catalogs under ``data/raw`` (STS1 = 52, STS2 = 66) plus the
small read-side API used by the rest of the bot:

- ``load_events`` loads one (or both) validated catalog(s).
- ``find_events_by_name`` is an exact full-name lookup (zh exact, en
  case-insensitive) with no prefix, fuzzy or pinyin matching.
- ``default_random_pool`` returns only the default random-eligible events
  (no ``random.choice`` happens here; the caller decides).
- ``get_event`` resolves one event by exact game + id.

No QQ logic and no third-party dependencies live in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Mapping


CATALOG_FILES = {
    "sts1": "sts1_events.json",
    "sts2": "sts2_events.json",
}
DEFAULT_CATALOG_DIR = Path("data/raw")

_VALID_GAMES = frozenset(CATALOG_FILES)
_GAME_ORDER = ("sts1", "sts2")

_STS1_POOLS = frozenset({"act_specific", "shrine", "scripted"})
_STS2_POOLS = frozenset({"act_specific", "shared", "ancient"})

# Frozen default random eligibility:
# STS1 -> act_specific + shrine (scripted/SPIRE_HEART excluded) = 51
# STS2 -> act_specific + shared (ancient excluded) = 57
_DEFAULT_POOL_ALLOWED = {
    "sts1": frozenset({"act_specific", "shrine"}),
    "sts2": frozenset({"act_specific", "shared"}),
}

_VALID_ACTS = (1, 2, 3, None)


class EventCatalogError(Exception):
    """Raised when an Event catalog is missing, invalid or unreadable."""


@dataclass(frozen=True)
class EventChoice:
    """One static option of an event (fields always exist; null when unknown)."""

    id: str | None
    text_zh: str | None
    description_zh: str | None
    result_zh: str | None
    locked_zh: str | None
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class EventRecord:
    """One event with normalized common fields plus its original raw record."""

    game: str
    id: str
    name_zh: str
    name_en: str
    category: str
    act: int | None
    pool: str
    description_zh: str | None
    choices: tuple[EventChoice, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class EventCatalog:
    """Validated in-memory view of one frozen Event catalog file."""

    game: str
    schema_version: str
    source: tuple[str, ...]
    source_version: str
    events: tuple[EventRecord, ...]
    features: Mapping[str, Any] = field(default_factory=dict)


_CATALOG_CACHE: dict[tuple[str, str], EventCatalog] = {}


def _raise(message: str) -> None:
    raise EventCatalogError(message)


def _validate_choice(choice: Any, event_id: str, index: int) -> None:
    if not isinstance(choice, Mapping):
        _raise(f"event {event_id!r} choice {index} must be an object")
    for key in ("id", "text_zh", "description_zh", "result_zh", "locked_zh"):
        if key not in choice:
            _raise(f"event {event_id!r} choice {index} misses field {key!r}")
        value = choice[key]
        if value is not None and not isinstance(value, str):
            _raise(f"event {event_id!r} choice {index} field {key!r} must be str or null")
    if not isinstance(choice.get("raw"), Mapping):
        _raise(f"event {event_id!r} choice {index} raw must be an object")


def validate_catalog(payload: Mapping[str, Any]) -> None:
    """Validate one catalog payload, raising ``EventCatalogError`` on problems."""

    if not isinstance(payload, Mapping):
        _raise("catalog payload must be an object")
    game = payload.get("game")
    if game not in _VALID_GAMES:
        _raise(f"catalog game must be one of {sorted(_VALID_GAMES)}")

    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str) or not schema_version:
        _raise("catalog schema_version must be a non-empty string")
    source = payload.get("source")
    if not isinstance(source, (list, tuple)) or not source:
        _raise("catalog source must be a non-empty list")
    if not all(isinstance(item, str) and item for item in source):
        _raise("catalog source entries must be non-empty strings")
    source_version = payload.get("source_version")
    if not isinstance(source_version, str) or not source_version:
        _raise("catalog source_version must be a non-empty string")

    events = payload.get("events")
    if not isinstance(events, list):
        _raise("catalog events must be a list")

    allowed_pools = _STS1_POOLS if game == "sts1" else _STS2_POOLS
    seen_ids: set[str] = set()
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            _raise(f"event {index} must be an object")
        if event.get("game") != game:
            _raise(f"event {index} game does not match catalog game {game!r}")
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            _raise(f"event {index} id must be a non-empty string")
        if event_id in seen_ids:
            _raise(f"duplicate event id {event_id!r} in {game} catalog")
        seen_ids.add(event_id)

        for field_name in ("name_zh", "name_en", "category", "pool"):
            value = event.get(field_name)
            if not isinstance(value, str) or not value:
                _raise(f"event {event_id!r} {field_name} must be a non-empty string")
        if event.get("pool") not in allowed_pools:
            _raise(
                f"event {event_id!r} pool {event.get('pool')!r} is not valid "
                f"for {game}"
            )
        act = event.get("act")
        if act not in _VALID_ACTS:
            _raise(f"event {event_id!r} act must be one of 1, 2, 3 or null")
        if not isinstance(event.get("description_zh"), str):
            _raise(f"event {event_id!r} description_zh must be a string")
        if not isinstance(event.get("raw"), Mapping):
            _raise(f"event {event_id!r} raw must be an object")

        choices = event.get("choices")
        if not isinstance(choices, list):
            _raise(f"event {event_id!r} choices must be a list")
        for choice_index, choice in enumerate(choices):
            _validate_choice(choice, event_id, choice_index)


def _event_record(event: Mapping[str, Any]) -> EventRecord:
    choices = tuple(
        EventChoice(
            id=choice["id"],
            text_zh=choice["text_zh"],
            description_zh=choice["description_zh"],
            result_zh=choice["result_zh"],
            locked_zh=choice["locked_zh"],
            raw=choice["raw"],
        )
        for choice in event["choices"]
    )
    return EventRecord(
        game=event["game"],
        id=event["id"],
        name_zh=event["name_zh"],
        name_en=event["name_en"],
        category=event["category"],
        act=event["act"],
        pool=event["pool"],
        description_zh=event["description_zh"],
        choices=choices,
        raw=event["raw"],
    )


def _load_catalog(game: str, catalog_dir: str | Path) -> EventCatalog:
    if game not in _VALID_GAMES:
        _raise(f"unknown game {game!r}; expected one of {sorted(_VALID_GAMES)}")
    key = (str(Path(catalog_dir)), game)
    cached = _CATALOG_CACHE.get(key)
    if cached is not None:
        return cached
    path = Path(catalog_dir) / CATALOG_FILES[game]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _raise(f"event catalog not found: {path}")
    validate_catalog(payload)
    events = tuple(_event_record(event) for event in payload["events"])
    catalog = EventCatalog(
        game=game,
        schema_version=payload["schema_version"],
        source=tuple(payload["source"]),
        source_version=payload["source_version"],
        events=events,
    )
    _CATALOG_CACHE[key] = catalog
    return catalog


def load_events(
    game: str | None = None, catalog_dir: str | Path = DEFAULT_CATALOG_DIR
) -> EventCatalog | dict[str, EventCatalog]:
    """Load one catalog (``game`` given) or both (``game=None``)."""

    if game is None:
        return {name: _load_catalog(name, catalog_dir) for name in _GAME_ORDER}
    return _load_catalog(game, catalog_dir)


def get_event(
    game: str, event_id: str, catalog_dir: str | Path = DEFAULT_CATALOG_DIR
) -> EventRecord:
    """Return the event with the exact ``event_id`` for ``game``."""

    catalog = _load_catalog(game, catalog_dir)
    for record in catalog.events:
        if record.id == event_id:
            return record
    _raise(f"event {event_id!r} not found in {game} catalog")


def find_events_by_name(
    name: str,
    game: str | None = None,
    catalog_dir: str | Path = DEFAULT_CATALOG_DIR,
) -> list[EventRecord]:
    """Exact full-name lookup across (optionally one) game catalog.

    Matches the official zh full name exactly, or the en full name ignoring
    case.  Prefix, substring, fuzzy and pinyin matching are intentionally
    unsupported.
    """

    if not isinstance(name, str) or not name.strip():
        return []
    query_zh = name.strip()
    query_en = query_zh.casefold()
    matches: list[EventRecord] = []
    for game_name in _GAME_ORDER:
        if game is not None and game_name != game:
            continue
        for record in _load_catalog(game_name, catalog_dir).events:
            if record.name_zh.strip() == query_zh:
                matches.append(record)
                continue
            if record.name_en.strip().casefold() == query_en:
                matches.append(record)
    return sorted(matches, key=lambda record: (record.game, record.id))


def default_random_pool(
    game: str | None = None, catalog_dir: str | Path = DEFAULT_CATALOG_DIR
) -> tuple[EventRecord, ...] | dict[str, tuple[EventRecord, ...]]:
    """Return the default random-eligible events for ``game`` (or both)."""

    if game is None:
        return {
            name: default_random_pool(name, catalog_dir)
            for name in _GAME_ORDER
        }
    if game not in _VALID_GAMES:
        _raise(f"unknown game {game!r}; expected one of {sorted(_VALID_GAMES)}")
    allowed = _DEFAULT_POOL_ALLOWED[game]
    catalog = _load_catalog(game, catalog_dir)
    return tuple(record for record in catalog.events if record.pool in allowed)
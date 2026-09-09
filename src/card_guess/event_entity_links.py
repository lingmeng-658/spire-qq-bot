"""Validated read-side API for frozen Event <-> Card/Relic links."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SNAPSHOT_PATH = Path("data/stats/event_entity_links.json")
VALID_ENTITY_TYPES = frozenset({"card", "relic"})
VALID_RELATIONS = frozenset(
    {
        "REWARD",
        "FALLBACK_REWARD",
        "REQUIRED",
        "REMOVE",
        "TRANSFORM",
        "UPGRADE",
        "TRADE",
        "REFERENCE",
    }
)
_VALID_GAMES = frozenset({"sts1", "sts2"})
_LINK_FIELDS = frozenset(
    {
        "game",
        "event_id",
        "entity_type",
        "entity_id",
        "relation",
        "condition",
        "source",
        "evidence",
    }
)
_CONDITION_FIELDS = frozenset({"choice_id", "choice_index", "fallback_text"})


@dataclass(frozen=True)
class EventEntityLinkCondition:
    choice_id: str | None
    choice_index: int | None
    fallback_text: str | None


@dataclass(frozen=True)
class EventEntityLink:
    game: str
    event_id: str
    entity_type: str
    entity_id: str
    relation: str
    condition: EventEntityLinkCondition
    source: str
    evidence: str


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _condition(payload: Any, game: str, relation: str) -> EventEntityLinkCondition:
    if not isinstance(payload, Mapping) or frozenset(payload) != _CONDITION_FIELDS:
        raise ValueError("invalid link condition fields")
    choice_id = payload.get("choice_id")
    choice_index = payload.get("choice_index")
    fallback_text = payload.get("fallback_text")
    if choice_id is not None and not _nonempty_string(choice_id):
        raise ValueError("choice_id must be null or a non-empty string")
    if (
        choice_index is not None
        and (isinstance(choice_index, bool) or not isinstance(choice_index, int) or choice_index < 0)
    ):
        raise ValueError("choice_index must be null or a non-negative integer")
    if fallback_text is not None and not _nonempty_string(fallback_text):
        raise ValueError("fallback_text must be null or a non-empty string")
    if game == "sts1" and (choice_index is None or choice_id is not None):
        raise ValueError("STS1 links require only choice_index")
    if game == "sts2" and (choice_id is None or choice_index is not None):
        raise ValueError("STS2 links require only choice_id")
    if relation == "FALLBACK_REWARD" and fallback_text is None:
        raise ValueError("fallback rewards require fallback_text")
    if relation != "FALLBACK_REWARD" and fallback_text is not None:
        raise ValueError("fallback_text is only valid for fallback rewards")
    return EventEntityLinkCondition(choice_id, choice_index, fallback_text)


def _link(payload: Any) -> EventEntityLink:
    if not isinstance(payload, Mapping) or frozenset(payload) != _LINK_FIELDS:
        raise ValueError("invalid link fields")
    game = payload.get("game")
    entity_type = payload.get("entity_type")
    relation = payload.get("relation")
    if game not in _VALID_GAMES:
        raise ValueError("invalid link game")
    if entity_type not in VALID_ENTITY_TYPES:
        raise ValueError("invalid link entity_type")
    if relation not in VALID_RELATIONS:
        raise ValueError("invalid link relation")
    for field in ("event_id", "entity_id", "source", "evidence"):
        if not _nonempty_string(payload.get(field)):
            raise ValueError(f"invalid link {field}")
    return EventEntityLink(
        game=game,
        event_id=payload["event_id"],
        entity_type=entity_type,
        entity_id=payload["entity_id"],
        relation=relation,
        condition=_condition(payload.get("condition"), game, relation),
        source=payload["source"],
        evidence=payload["evidence"],
    )


def _sort_key(link: EventEntityLink) -> tuple[str, ...]:
    return (
        link.game,
        link.event_id,
        link.entity_type,
        link.entity_id,
        link.relation,
    )


def load_event_entity_links(
    path: str | Path | None = None,
) -> tuple[EventEntityLink, ...]:
    """Load and validate the frozen snapshot, returning empty on any failure."""

    snapshot_path = DEFAULT_SNAPSHOT_PATH if path is None else Path(path)
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("snapshot must be an object")
        if payload.get("schema_version") != "1.0" or frozenset(payload) != {
            "schema_version",
            "links",
        }:
            raise ValueError("invalid snapshot envelope")
        rows = payload.get("links")
        if not isinstance(rows, list):
            raise ValueError("snapshot links must be a list")
        links = tuple(sorted((_link(row) for row in rows), key=_sort_key))
        identities = {_sort_key(link) for link in links}
        if len(identities) != len(links):
            raise ValueError("duplicate event entity link")
        return links
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return ()


def links_for_event(
    game: str,
    event_id: str,
    *,
    path: str | Path | None = None,
) -> tuple[EventEntityLink, ...]:
    """Return all concrete entity links for one exact game + Event ID."""

    return tuple(
        link
        for link in load_event_entity_links(path)
        if link.game == game and link.event_id == event_id
    )


def links_for_entity(
    game: str,
    entity_type: str,
    entity_id: str,
    *,
    path: str | Path | None = None,
) -> tuple[EventEntityLink, ...]:
    """Return all Event links for one exact concrete Card or Relic ID."""

    return tuple(
        link
        for link in load_event_entity_links(path)
        if link.game == game
        and link.entity_type == entity_type
        and link.entity_id == entity_id
    )

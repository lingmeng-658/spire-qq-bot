"""Pure STS2 event catalog text merge helpers.

These helpers are used only while rebuilding the frozen ``sts2_events.json``
catalog.  They prefer already-parsed official zh archive fields for the
player-visible fields and always leave ``raw`` payloads untouched.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping


_TITLE_BBCODE_RE = re.compile(r"\[/?[a-z]+\]", re.IGNORECASE)
_UNRESOLVED_MARKERS = (
    "{",
    "}",
    "占位符",
    "% Max",
    "[AromaPrinciple]",
    "[EntrantNumber]",
    "[Monologue]",
)
_DYNAMIC_X_RE = re.compile(r"(?<![A-Za-z.])X(?![A-Za-z])")
_DYNAMIC_ZERO_RE = re.compile(r"(?<![0-9.])0(?=[\u4e00-\u9fff ])")
_LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_MAX_HP_PERCENT_RE = re.compile(r"回复(?P<value>\d+)% Max点生命")


def _clean_title(value: str | None) -> str:
    if not value:
        return ""
    return _TITLE_BBCODE_RE.sub("", value).strip()


def _options(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    options = event.get("options")
    if isinstance(options, list):
        return options
    pages = event.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if page.get("id") == "INITIAL" and isinstance(page.get("options"), list):
                return page["options"]
    return []


def is_adoptable_text(value: Any) -> bool:
    """Return whether archive text is fully resolved enough to expose to QQ.

    Runtime placeholders, ``% Max`` and archive-only ``X``/``0`` dynamic
    stand-ins are intentionally left in the catalog rather than guessed.
    """

    if not isinstance(value, str) or not value.strip():
        return False
    if any(marker in value for marker in _UNRESOLVED_MARKERS):
        return False
    if _DYNAMIC_X_RE.search(value) or _DYNAMIC_ZERO_RE.search(value):
        return False
    if _LATIN_WORD_RE.search(value):
        return False
    return True


def normalize_max_hp_percent(value: Any) -> Any:
    """Turn the raw ``回复N% Max点生命`` pattern into natural Chinese.

    The original zh localization leaves an English ``Max`` fragment inside an
    otherwise Chinese sentence.  This generic rule only fires on that exact
    pattern and keeps every other text byte-for-byte unchanged.
    """

    if not isinstance(value, str) or "% Max" not in value:
        return value
    cleaned = _TITLE_BBCODE_RE.sub("", value)
    return _MAX_HP_PERCENT_RE.sub(r"回复最大生命值的\g<value>%", cleaned)


def build_choice_archive_map(
    *,
    catalog_event: Mapping[str, Any],
    raw_en_event: Mapping[str, Any],
    archive_en_event: Mapping[str, Any],
    archive_zh_event: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    """Map archive zh choice rows to catalog choice IDs.

    The archive zh output does not carry IDs.  We therefore align the archive
    en/zh rows (same deterministic parser order) and recover the raw option ID
    by an exact, unambiguous English title match.  Ambiguous or missing IDs are
    never guessed.
    """

    catalog_choices = (
        catalog_event.get("choices")
        if isinstance(catalog_event, Mapping)
        else getattr(catalog_event, "choices", ())
    )
    regular_ids = set()
    for choice in catalog_choices or ():
        if isinstance(choice, Mapping):
            choice_id = choice.get("id")
        else:
            choice_id = getattr(choice, "id", None)
        if (
            choice_id
            and not choice_id.endswith("_LOCKED")
            and choice_id != "LOCKED"
        ):
            regular_ids.add(choice_id)
    raw_en_by_title: dict[str, list[str]] = {}
    for option in _options(raw_en_event):
        option_id = option.get("id")
        title = _clean_title(option.get("title"))
        if option_id and title:
            raw_en_by_title.setdefault(title, []).append(option_id)

    en_choices = archive_en_event.get("choices") or []
    zh_choices = archive_zh_event.get("choices") or []
    result: dict[str, Mapping[str, Any]] = {}
    for en_row, zh_row in zip(en_choices, zh_choices):
        title = _clean_title(en_row.get("name"))
        matches = raw_en_by_title.get(title, [])
        if len(matches) == 1 and matches[0] in regular_ids:
            result[matches[0]] = zh_row
    return result


def polish_catalog_text(
    catalog_payload: Mapping[str, Any],
    *,
    raw_en_events: list[Mapping[str, Any]],
    archive_en_events: list[Mapping[str, Any]],
    archive_zh_events: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Return a copy of the catalog with archive zh text adopted.

    Only player-visible fields are changed.  The ``raw`` event payload and
    every ``choice.raw`` payload remain byte-for-byte unchanged.
    """

    polished = deepcopy(dict(catalog_payload))
    raw_en_by_id = {event["id"]: event for event in raw_en_events}
    archive_en_by_id = {event["id"]: event for event in archive_en_events}
    unresolved: list[str] = []

    for event in polished["events"]:
        event_id = event["id"]
        archive_event = archive_zh_events.get(event_id)
        if not archive_event:
            unresolved.append(f"{event_id}:event:no_archive_zh")
            continue

        if is_adoptable_text(archive_event.get("name")):
            event["name_zh"] = archive_event["name"]

        archive_description = archive_event.get("description")
        if is_adoptable_text(archive_description):
            event["description_zh"] = archive_description
        elif archive_description is not None:
            unresolved.append(f"{event_id}:event:description_unresolved")

        choice_map = build_choice_archive_map(
            catalog_event=event,
            raw_en_event=raw_en_by_id.get(event_id, {}),
            archive_en_event=archive_en_by_id.get(event_id, {}),
            archive_zh_event=archive_event,
        )

        for choice in event["choices"]:
            choice_id = choice.get("id")
            if not choice_id:
                continue

            if choice_id.endswith("_LOCKED"):
                base_id = choice_id[: -len("_LOCKED")]
                row = choice_map.get(base_id)
                if row is None:
                    continue
                locked_text = row.get("locked")
                if is_adoptable_text(locked_text):
                    choice["locked_zh"] = locked_text
                elif locked_text is not None:
                    unresolved.append(f"{event_id}:{choice_id}:locked_unresolved")
                continue

            row = choice_map.get(choice_id)
            if row is None:
                if archive_event.get("choices"):
                    unresolved.append(f"{event_id}:{choice_id}:no_stable_archive_row")
                continue

            name = row.get("name")
            if is_adoptable_text(name):
                choice["text_zh"] = name
            elif name is not None:
                unresolved.append(f"{event_id}:{choice_id}:text_unresolved")

            description = row.get("description")
            if is_adoptable_text(description):
                choice["description_zh"] = description
            elif description is not None:
                unresolved.append(f"{event_id}:{choice_id}:description_unresolved")
            else:
                unresolved.append(f"{event_id}:{choice_id}:description_missing")

            outcome = row.get("outcome")
            if choice.get("result_zh") and outcome is not None:
                if is_adoptable_text(outcome):
                    choice["result_zh"] = outcome
                else:
                    unresolved.append(f"{event_id}:{choice_id}:result_unresolved")
            elif choice.get("result_zh") and outcome is None:
                unresolved.append(f"{event_id}:{choice_id}:result_missing")

        for choice in event["choices"]:
            if choice.get("description_zh") is not None:
                choice["description_zh"] = normalize_max_hp_percent(
                    choice["description_zh"]
                )

    return polished, unresolved

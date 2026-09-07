# -*- coding: ascii -*-
"""Decode Untapped embedded decision overlays for STS2 cards.

STS2 card pages embed a React Server Component payload in <script> bodies.
One SSR page carries one decision overlay object with a "kind"
(reward / shop / smith), the audited numeric fields, and an explicit scope
(act, character, upgraded state, multiplayer).  This module unescapes that
payload and normalizes only the audited decision fields so snapshots can
store the full context without mixing it with Spire Codex numbers.

This is a development-time utility; bot/runtime code consumes JSON snapshots.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable

CARD_STATS_FIELDS = (
    "times_offered",
    "times_picked",
    "pick_pct",
    "pick_pct_delta",
    "skip_pct",
    "skip_pct_delta",
    "win_ca_pct",
    "win_ca_pct_delta",
    "win_pct",
    "win_pct_delta",
    "pick_tier",
    "skip_tier",
    "win_ca_tier",
    "win_tier",
)

CARD_DECISION_KINDS = ("reward", "shop", "smith")

KIND_SECTION_KEYS = {
    "reward": "card_reward",
    "shop": "shop",
    "smith": "smith",
}


def js_unescape(text: str) -> str:
    """Decode one level of JavaScript string escapes used in flight payloads."""
    out: list[str] = []
    simple = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "b": "\b",
        "f": "\f",
        "v": "\v",
        "0": "\0",
        '"': '"',
        "\\": "\\",
        "'": "'",
    }
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            if nxt == "u" and index + 5 < len(text):
                try:
                    out.append(chr(int(text[index + 2 : index + 6], 16)))
                    index += 6
                    continue
                except ValueError:
                    pass
            if nxt in simple:
                out.append(simple[nxt])
                index += 2
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _script_bodies(html: str) -> list[str]:
    return [
        m.group(1)
        for m in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.S | re.I)
    ]


def extract_embedded_stat_payloads(html: str) -> list[dict[str, Any]]:
    """Return deduplicated embedded decision payload dicts from card HTML.

    The payload literal appears inside flight script text as
    {"kind":"reward", ...}; one decode pass restores the plain quotes.
    """
    seen = set()
    payloads: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    needle = re.compile(r'\{"kind"\s*:\s*"')
    for body in _script_bodies(html):
        text = js_unescape(body)
        cursor = 0
        while True:
            match = needle.search(text, cursor)
            if match is None:
                break
            index = match.start()
            try:
                payload, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                cursor = index + 1
                continue
            if isinstance(payload, dict):
                key = json.dumps(payload, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    payloads.append(payload)
            cursor = end
    return payloads


def scope_from_tooltip(stats: dict[str, Any]) -> dict[str, Any]:
    """Extract the audited scope from the overlay tooltip text when present.

    Tooltip text has the shape: "Scoped to: Not Upgraded, Act 2, SILENT".
    """
    empty = {"upgraded": None, "character": None, "source_text": None}
    if not isinstance(stats, dict):
        return empty
    tooltips = stats.get("debug_tooltips")
    if not isinstance(tooltips, list):
        return empty
    source_text = None
    for tooltip in tooltips:
        if not isinstance(tooltip, dict):
            continue
        text = tooltip.get("text")
        if isinstance(text, str) and "Scoped to:" in text:
            source_text = text
            break
    if source_text is None:
        return empty

    upgraded: bool | None = None
    character: str | None = None
    segments = [segment.strip() for segment in source_text.split(",")]
    for segment in segments:
        low = segment.lower()
        if "not upgraded" in low:
            upgraded = False
        elif low == "upgraded" or segment.lower().startswith("upgraded"):
            upgraded = True
    character_segments = [
        segment
        for segment in segments
        if segment
        and not segment.lower().startswith(("act ", "scoped"))
        and "upgraded" not in segment.lower()
        and not segment.lower().startswith("singleplayer")
        and not segment.lower().startswith("multiplayer")
    ]
    if character_segments:
        character = character_segments[-1].upper()
    return {"upgraded": upgraded, "character": character, "source_text": source_text}


def card_decision_records(html: str, card_id: str) -> list[dict[str, Any]]:
    """Return normalized decision records for one card from its page HTML.

    Only audited CARD_STATS_FIELDS are kept, nothing is zero-filled, and the
    record carries the raw scope (character / upgraded) plus multiplayer and
    act.  Payloads for other entities (e.g. FASTEN promos) are ignored.
    """
    wanted = str(card_id or "").strip().upper()
    records: list[dict[str, Any]] = []
    for payload in extract_embedded_stat_payloads(html):
        payload_card = str(payload.get("cardId") or "").strip().upper()
        if payload_card != wanted:
            continue
        kind = str(payload.get("kind") or "")
        if kind not in CARD_DECISION_KINDS:
            continue
        stats = payload.get("stats")
        if not isinstance(stats, dict):
            continue
        audited = {key: stats[key] for key in CARD_STATS_FIELDS if key in stats}
        if not audited:
            continue
        record: dict[str, Any] = {
            "kind": kind,
            "stats": audited,
            "scope": scope_from_tooltip(stats),
        }
        act = payload.get("act")
        if isinstance(act, int) and not isinstance(act, bool):
            record["act"] = act
        multiplayer = payload.get("multiplayer")
        if isinstance(multiplayer, bool):
            record["multiplayer"] = multiplayer
        sample_count = payload.get("sampleCount")
        if isinstance(sample_count, int) and not isinstance(sample_count, bool):
            record["sample_count"] = sample_count
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Snapshot merge helpers (additive fine-grained context).
# ---------------------------------------------------------------------------


def merge_card_finegrained(
    snapshot: dict[str, Any],
    html_by_card: dict[str, str],
) -> dict[str, Any]:
    """Merge embedded decision records into cards.*.untapped.<section>.act_N.

    Every record is stored under "finegrained" as a sibling of the existing
    aggregated metrics.  Existing metric values are never modified.
    """
    cards = snapshot.get("cards")
    if not isinstance(cards, dict):
        return snapshot
    for card_id, html in html_by_card.items():
        entry = cards.get(str(card_id))
        if not isinstance(entry, dict):
            continue
        records = card_decision_records(html, str(card_id))
        if not records:
            continue
        untapped = entry.get("untapped")
        if not isinstance(untapped, dict):
            untapped = {}
            entry["untapped"] = untapped
        for record in records:
            section_key = KIND_SECTION_KEYS.get(record.get("kind"))
            act = record.get("act")
            if not section_key or not isinstance(act, int):
                continue
            act_key = f"act_{act}"
            section = untapped.setdefault(section_key, {})
            act_data = section.setdefault(act_key, {})
            act_data.setdefault("finegrained", record)
    return snapshot


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as temporary:
        json.dump(snapshot, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def card_id_from_filename(filename: str) -> str | None:
    match = re.match(r"^card_([A-Z0-9_]+)\.html$", filename)
    return match.group(1) if match else None
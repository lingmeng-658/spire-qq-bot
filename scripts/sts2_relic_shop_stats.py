# -*- coding: ascii -*-
"""STS2 relic "Shop Stats" parser and snapshot builder (Untapped).

Development-time utility.  Bot/runtime code consumes only the generated JSON.

A relic page can carry the Shop Stats section in two forms:

1. Plain server-rendered StatCell markup (used by the unit fixtures and by
   pages that already hydrated the section).
2. A Next.js React Server Component payload embedded in a <script>.  The
   cached pages we collect are server HTML where the panel is a Suspense
   skeleton, so the real cell data lives in the RSC flight text instead.

Both forms decode to the same normalized act rows, keyed act_1/act_2/act_3.
Only rows whose source cell reports dataState == "ok" are kept as data;
insufficient cells become empty rows so they never look like real stats.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

import requests

SHOP_EXCLUDED_TIERS = {"ancient", "starter", "event", "none"}

_ACT_RE = re.compile(r"In Act ([1-3])\b", re.IGNORECASE)
_OFFERED_RE = re.compile(
    r"(?:offered|seen)\s+([\d,]+(?:\.[\d]+)?)\s+times", re.IGNORECASE
)
_BOUGHT_RE = re.compile(r"Bought\s*([+-]?\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_ACT_WIN_RE = re.compile(r"Act Winrate\s*([+-]?\d+(?:\.\d+)?)\s*%", re.IGNORECASE)
_RUN_WIN_RE = re.compile(r"Run Winrate\s*([+-]?\d+(?:\.\d+)?)\s*%", re.IGNORECASE)

_USER_AGENT = "card-guess-bot-stats-snapshot/1.0"
SITEMAP_URL = "https://sts2.untapped.gg/sitemap/relics.xml"
DEFAULT_DELAY_SECONDS = 0.4


# ---------------------------------------------------------------------------
# JSON escaping helpers (shared with the embedded card payload decoder).
# ---------------------------------------------------------------------------


def _js_unescape(text: str) -> str:
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


def _decoded_script_texts(html: str) -> list[str]:
    return [_js_unescape(body) for body in _script_bodies(html) if body]


def _json_objects_containing(text: str, pattern: str, back_scan: int = 60000):
    """Yield decoded JSON dicts whose serialized form matches *pattern*."""
    regex = re.compile(pattern)
    seen = set()
    decoder = json.JSONDecoder()
    cursor = 0
    while True:
        match = regex.search(text, cursor)
        if match is None:
            return
        index = match.start()
        best: Any = None
        for pos in range(index, max(-1, index - back_scan), -1):
            if text[pos] != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(text, pos)
            except json.JSONDecodeError:
                continue
            if not isinstance(candidate, dict):
                continue
            serialized = json.dumps(candidate, sort_keys=True)
            if regex.search(serialized) is None:
                continue
            key = serialized
            if key in seen:
                break
            seen.add(key)
            best = candidate
            break
        if best is None:
            cursor = index + 1
            continue
        yield best
        cursor = index + 1


# ---------------------------------------------------------------------------
# Cell normalization shared by markup and flight paths.
# ---------------------------------------------------------------------------


def _percent_value(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    return float(match.group(1).replace(",", ""))


def _offered_value(match: re.Match[str] | None) -> int | None:
    if match is None:
        return None
    return int(round(float(match.group(1).replace(",", ""))))


def _normalize_row(cell_text: str) -> dict[str, Any]:
    """Parse one flattened StatCell text into a metric row (no zero fill)."""
    row: dict[str, Any] = {}
    offered = _offered_value(_OFFERED_RE.search(cell_text))
    if offered is not None:
        row["offered"] = offered
    bought = _percent_value(_BOUGHT_RE.search(cell_text))
    if bought is not None:
        row["purchase_rate"] = {"value": bought, "unit": "percent"}
    act_win = _percent_value(_ACT_WIN_RE.search(cell_text))
    if act_win is not None:
        row["act_win_rate_impact"] = {"value": act_win, "unit": "percentage_points"}
    run_win = _percent_value(_RUN_WIN_RE.search(cell_text))
    if run_win is not None:
        row["run_win_rate_impact"] = {"value": run_win, "unit": "percentage_points"}
    return row


def _store_cell(result: dict[str, Any], cell_text: str) -> None:
    act_match = _ACT_RE.search(cell_text)
    if not act_match:
        return
    result[f"act_{act_match.group(1)}"] = _normalize_row(cell_text)


# ---------------------------------------------------------------------------
# Markup path: server-rendered StatCell section.
# ---------------------------------------------------------------------------


class _ShopMarkupParser(HTMLParser):
    """Capture only the Shop Stats section cells from plain HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.seen_shop_h2 = False
        self.title_parts: list[str] = []
        self.cell_depth: int | None = None
        self.cell_parts: list[str] = []
        self.cells: list[str] = []
        self.low_flags: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        css = dict(attrs).get("class") or ""
        if tag == "h2":
            self.title_parts = []
        elif tag == "div" and self.seen_shop_h2 and "StatCell" in css and "__cell" in css:
            if self.cell_depth is None:
                self.cell_depth = self.depth
                self.cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self.title_parts is not None:
            title = " ".join("".join(self.title_parts).split()).lower()
            if "shop" in title and "stats" in title:
                self.seen_shop_h2 = True
        if tag == "div" and self.cell_depth == self.depth:
            raw = " ".join(self.cell_parts)
            text = " ".join(raw.split())
            if text:
                self.cells.append(text)
                self.low_flags.append("insufficient data" in raw.lower())
            self.cell_depth = None
            self.cell_parts = []
        self.depth = max(0, self.depth - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if not self.seen_shop_h2:
            if self.title_parts is not None:
                self.title_parts.append(data)
        elif self.cell_depth is not None:
            self.cell_parts.append(data)


def _parse_markup_cells(html: str) -> dict[str, Any]:
    parser = _ShopMarkupParser()
    parser.feed(html)
    result: dict[str, Any] = {}
    for cell_text in parser.cells:
        _store_cell(result, cell_text)
    return result


def _parse_markup_page(html: str) -> dict[str, Any]:
    """Classify a plain-markup Shop Stats page (no RSC flight payload).

    Server-rendered shop cells carry either real numbers (state ok) or an
    "Insufficient Data" marker (state insufficient); skeleton cells carry no
    usable content and are ignored.  A page whose shop section only renders
    skeletons therefore reports panel False (no confirmable stats).
    """
    parser = _ShopMarkupParser()
    parser.feed(html)
    rows: dict[str, Any] = {}
    states: dict[str, str] = {}
    for cell_text, low in zip(parser.cells, parser.low_flags):
        act_match = _ACT_RE.search(cell_text)
        if not act_match:
            continue
        act_key = f"act_{act_match.group(1)}"
        if low:
            states[act_key] = "insufficient"
            rows.setdefault(act_key, {})
            continue
        row = _normalize_row(cell_text)
        if row:
            states[act_key] = "ok"
            rows[act_key] = row
            continue
        rows.setdefault(act_key, {})
    clean = {act_key: row for act_key, row in rows.items() if row}
    return {"panel": bool(states) or bool(clean), "states": states, "rows": clean}




# ---------------------------------------------------------------------------
# Flight path: RSC payload embedded in <script> bodies.
# ---------------------------------------------------------------------------


def _flatten_rsc(node: Any, parts: list[str]) -> None:
    if isinstance(node, str):
        parts.append(node)
        return
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        parts.append(f"{node:g}")
        return
    if isinstance(node, list):
        if node and node[0] == "$":
            props: Any = None
            if len(node) > 3 and isinstance(node[3], dict):
                props = node[3]
            elif len(node) > 2 and isinstance(node[2], dict):
                props = node[2]
            if props is not None:
                label = props.get("label")
                delta = props.get("delta")
                if (
                    isinstance(label, str)
                    and isinstance(delta, (int, float))
                    and label in ("Act Winrate", "Run Winrate")
                ):
                    sign = "+" if delta > 0 else ""
                    parts.append(f"{label}{sign}{delta:g}%")
                    return
                children = props.get("children")
                if children is not None:
                    _flatten_rsc(children, parts)
            return
        for item in node:
            _flatten_rsc(item, parts)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("className", "style"):
                continue
            _flatten_rsc(value, parts)


def _cell_text_from_props(props: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("label", "offered"):
        value = props.get(key)
        if isinstance(value, str) and value != "$undefined":
            parts.append(value)
    children = props.get("children")
    if children is not None:
        _flatten_rsc(children, parts)
    return " ".join(" ".join(parts).split())


def _parse_flight_page(html: str) -> dict[str, Any] | None:
    """Decode the Shop Stats RSC flight payload into a per-act classification.

    Returns None when the page has no decodable flight payload (so callers can
    fall back to plain markup).  Otherwise returns::

        {"panel": bool,
         "states": {"act_1": "ok" | "insufficient", ...},
         "rows": {"act_1": {...row...} | {}, ...}}

    "panel" reports whether any Bought shop cell was found; Starter / Event /
    Ancient and non-shop panels therefore yield panel False with no rows.
    Rows hold numbers only for dataState == "ok" cells; insufficient or
    skeleton cells become empty rows so they never look like real stats.
    """
    texts = _decoded_script_texts(html)
    if not texts:
        return None

    rows: dict[str, Any] = {}
    states: dict[str, str] = {}
    saw_bought_cell = False
    for text in texts:
        for props in _json_objects_containing(text, r'"label"\s*:\s*"In Act'):
            label = str(props.get("label") or "")
            act_match = _ACT_RE.search(label)
            if not act_match:
                continue
            act_key = f"act_{act_match.group(1)}"
            cell_text = _cell_text_from_props(props)
            if "Bought" not in cell_text:
                # Skeleton copies carry no data; insufficient cells may only
                # render a low-data message with no Bought text at all.
                if str(props.get("dataState") or "").strip() != "ok":
                    states.setdefault(act_key, "insufficient")
                rows.setdefault(act_key, {})
                continue
            saw_bought_cell = True
            data_state = str(props.get("dataState") or "").strip()
            if data_state != "ok":
                states[act_key] = "insufficient"
                rows.setdefault(act_key, {})
                continue
            states[act_key] = "ok"
            rows[act_key] = _normalize_row(cell_text)
    if not saw_bought_cell:
        return {"panel": False, "states": {}, "rows": {}}
    return {"panel": True, "states": states, "rows": rows}


def _parse_flight_cells(html: str) -> dict[str, Any] | None:
    """Rows-only view of the flight Shop Stats payload (see _parse_flight_page)."""
    page = _parse_flight_page(html)
    return None if page is None else page["rows"]


def _parse_markup_cells(html: str) -> dict[str, Any]:
    parser = _ShopMarkupParser()
    parser.feed(html)
    result: dict[str, Any] = {}
    for cell_text in parser.cells:
        _store_cell(result, cell_text)
    return result


# ---------------------------------------------------------------------------
# Flight path: RSC payload embedded in <script> bodies.
# ---------------------------------------------------------------------------


def _flatten_rsc(node: Any, parts: list[str]) -> None:
    if isinstance(node, str):
        parts.append(node)
        return
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        parts.append(f"{node:g}")
        return
    if isinstance(node, list):
        if node and node[0] == "$":
            props: Any = None
            if len(node) > 3 and isinstance(node[3], dict):
                props = node[3]
            elif len(node) > 2 and isinstance(node[2], dict):
                props = node[2]
            if props is not None:
                label = props.get("label")
                delta = props.get("delta")
                if (
                    isinstance(label, str)
                    and isinstance(delta, (int, float))
                    and label in ("Act Winrate", "Run Winrate")
                ):
                    sign = "+" if delta > 0 else ""
                    parts.append(f"{label}{sign}{delta:g}%")
                    return
                children = props.get("children")
                if children is not None:
                    _flatten_rsc(children, parts)
            return
        for item in node:
            _flatten_rsc(item, parts)
        return
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("className", "style"):
                continue
            _flatten_rsc(value, parts)


def _cell_text_from_props(props: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("label", "offered"):
        value = props.get(key)
        if isinstance(value, str) and value != "$undefined":
            parts.append(value)
    children = props.get("children")
    if children is not None:
        _flatten_rsc(children, parts)
    return " ".join(" ".join(parts).split())


def _parse_flight_cells(html: str) -> dict[str, Any] | None:
    """Parse Shop Stats cells out of the RSC flight payload.

    Returns None when the page has no decodable flight payload (so callers can
    fall back to plain markup), {} when the payload contains no Bought shop
    cells (Starter / Event / Ancient or non-shop panels), otherwise rows.
    """
    texts = _decoded_script_texts(html)
    if not texts:
        return None

    result: dict[str, Any] = {}
    saw_bought_cell = False
    for text in texts:
        for props in _json_objects_containing(text, r'"label"\s*:\s*"In Act'):
            label = str(props.get("label") or "")
            act_match = _ACT_RE.search(label)
            if not act_match:
                continue
            act_key = f"act_{act_match.group(1)}"
            cell_text = _cell_text_from_props(props)
            if "Bought" not in cell_text:
                # Skeleton / fallback copies carry no decision data.
                if act_key not in result:
                    result[act_key] = {}
                continue
            saw_bought_cell = True
            data_state = str(props.get("dataState") or "").strip()
            if data_state != "ok":
                result.setdefault(act_key, {})
                continue
            result[act_key] = _normalize_row(cell_text)
    if not saw_bought_cell:
        return {}
    return result


# ---------------------------------------------------------------------------
# Public parser.
# ---------------------------------------------------------------------------


def parse_relic_shop_html(html: str) -> dict[str, Any]:
    """Parse one Untapped relic page into act_1/2/3 shop rows.

    Event / Starter / Ancient pages (which have no Bought shop section)
    return {}.  Missing values are omitted, never zero-filled.  Acts whose
    source data state is not "ok" yield empty dicts.
    """
    flight = _parse_flight_cells(html)
    if flight is not None:
        if not flight:
            return {}
        return flight
    return _parse_markup_cells(html)
def parse_relic_shop_page(html: str) -> dict[str, Any]:
    """Classify one Untapped relic page for the Shop Stats snapshot.

    Prefers the RSC flight payload because it carries the precise per-act
    dataState flags; falls back to server-rendered markup only when no
    decodable flight payload exists.  Returns::

        {"panel": bool,
         "states": {"act_1": "ok" | "insufficient", ...},
         "rows": {"act_1": {...row...}, ...}}

    rows holds only usable per-act metrics (empty acts are dropped), while
    states remembers acts whose source panel exists but has too little data.
    """
    flight = _parse_flight_page(html)
    if flight is not None:
        return {
            "panel": flight["panel"],
            "states": flight["states"],
            "rows": {
                act_key: row
                for act_key, row in flight["rows"].items()
                if isinstance(row, dict) and row
            },
        }
    return _parse_markup_page(html)




# ---------------------------------------------------------------------------
# Snapshot builder.
# ---------------------------------------------------------------------------


def _is_shop_eligible(tier: Any) -> bool:
    return str(tier or "").strip().lower() not in SHOP_EXCLUDED_TIERS


SHOP_STATUS_VALID = "valid"
SHOP_STATUS_INSUFFICIENT = "insufficient"
SHOP_STATUS_NO_SHOP_STATS = "no_shop_stats"
SHOP_STATUS_FETCH_OR_PARSE_ERROR = "fetch_or_parse_error"
SHOP_STATUS_MISSING_FROM_CATALOG = "parsed_relic_missing_from_local_catalog"

ELIGIBLE_STATUSES = {
    SHOP_STATUS_INSUFFICIENT,
    SHOP_STATUS_NO_SHOP_STATS,
    SHOP_STATUS_FETCH_OR_PARSE_ERROR,
}
ALL_SHOP_STATUSES = ELIGIBLE_STATUSES | {SHOP_STATUS_MISSING_FROM_CATALOG}


def validate_relic_shop_snapshot(snapshot: dict[str, Any]) -> None:
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dict")
    if snapshot.get("schema_version") != "1.0.0":
        raise ValueError("snapshot.schema_version must be 1.0.0")
    if snapshot.get("game") != "sts2":
        raise ValueError("snapshot.game must be sts2")
    relics = snapshot.get("relics")
    if not isinstance(relics, dict):
        raise ValueError("snapshot.relics must be a dict")
    for relic_id, entry in relics.items():
        if not isinstance(entry, dict):
            raise ValueError(f"relic {relic_id}: entry must be a dict")
        if entry.get("id") != relic_id:
            raise ValueError(f"relic {relic_id}: entry.id mismatch")
        shop = entry.get("shop")
        if not isinstance(shop, dict) or not shop:
            raise ValueError(f"relic {relic_id}: entry.shop must be a non-empty dict")
        for act_key, row in shop.items():
            if not act_key.startswith("act_"):
                raise ValueError(f"relic {relic_id}: unexpected act key {act_key}")
            if not isinstance(row, dict):
                raise ValueError(f"relic {relic_id}: {act_key} must be a dict")
            for key in ("purchase_rate", "act_win_rate_impact", "run_win_rate_impact"):
                metric = row.get(key)
                if metric is None:
                    continue
                value = metric.get("value") if isinstance(metric, dict) else None
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"relic {relic_id}: {act_key}.{key} needs a numeric value")
                if key == "purchase_rate" and not (0 <= value <= 100):
                    raise ValueError(f"relic {relic_id}: {act_key}.{key} outside 0..100")
    unresolved = snapshot.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("snapshot.unresolved must be a list")
    for entry in unresolved:
        if not isinstance(entry, dict):
            raise ValueError("snapshot.unresolved entries must be dicts")
        relic_id = str(entry.get("id") or "")
        if not relic_id:
            raise ValueError("snapshot.unresolved entry needs an id")
        status = entry.get("status")
        if status not in ALL_SHOP_STATUSES:
            raise ValueError(
                f"unresolved relic {relic_id}: unexpected status {status!r}"
            )
        reason = entry.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError(f"unresolved relic {relic_id}: reason must be a string")


def _normalize_page_outcome(value: Any) -> dict[str, Any]:
    """Accept page classifications and legacy act-keyed row dicts alike."""
    if isinstance(value, dict) and any(
        key in value for key in ("panel", "states", "rows", "error")
    ):
        return value
    if isinstance(value, dict):
        return {"panel": True, "states": {}, "rows": value}
    return {"error": "unparsable outcome"}


def build_relic_shop_snapshot(
    relic_catalog: Iterable[dict[str, Any]],
    page_outcomes: dict[str, Any],
    *,
    collected_at: str,
) -> dict[str, Any]:
    """Build a Shop Stats snapshot keyed by relic id.

    page_outcomes maps a relic id to a page classification produced by
    parse_relic_shop_page (panel/states/rows) or to {"error": reason} for
    pages that could not be fetched or parsed.  Plain act-keyed row dicts
    (the historical parser output) remain accepted and count as valid.

    Every shop-eligible relic id ends up either in relics (status valid) or
    in unresolved with one explicit status: insufficient / no_shop_stats /
    fetch_or_parse_error.  An eligible id with no recorded outcome is kept as
    fetch_or_parse_error rather than silently treated as "no data".
    """
    catalog = {
        str(relic.get("id") or "").strip(): relic
        for relic in relic_catalog
        if str(relic.get("id") or "").strip()
    }
    eligible: list[str] = []
    for relic_id in sorted(catalog):
        if _is_shop_eligible(catalog[relic_id].get("tier")):
            eligible.append(relic_id)
    eligible_set = set(eligible)

    relics: dict[str, Any] = {}
    unresolved: list[dict[str, Any]] = []
    seen_eligible: set[str] = set()

    for raw_id, raw_outcome in page_outcomes.items():
        relic_id = str(raw_id or "").strip()
        if not relic_id:
            continue
        outcome = _normalize_page_outcome(raw_outcome)
        if relic_id not in catalog:
            unresolved.append(
                {
                    "id": relic_id,
                    "status": SHOP_STATUS_MISSING_FROM_CATALOG,
                    "reason": "outcome references a relic id missing from the local relic catalog",
                }
            )
            continue
        if relic_id in eligible_set:
            seen_eligible.add(relic_id)
        error = outcome.get("error")
        if not isinstance(outcome, dict) or error:
            entry: dict[str, Any] = {
                "id": relic_id,
                "status": SHOP_STATUS_FETCH_OR_PARSE_ERROR,
            }
            reason = str(error) if error else "unparsable page outcome"
            entry["reason"] = reason
            unresolved.append(entry)
            continue

        rows = {
            act_key: row
            for act_key, row in (outcome.get("rows") or {}).items()
            if isinstance(row, dict) and row
        }
        if rows:
            source = catalog[relic_id]
            relics[relic_id] = {
                "id": relic_id,
                "name_en": source.get("name_en"),
                "tier": source.get("tier"),
                "shop": rows,
            }
            continue

        status = (
            SHOP_STATUS_INSUFFICIENT
            if outcome.get("panel")
            else SHOP_STATUS_NO_SHOP_STATS
        )
        unresolved.append({"id": relic_id, "status": status})

    for relic_id in eligible:
        if relic_id not in seen_eligible:
            unresolved.append(
                {
                    "id": relic_id,
                    "status": SHOP_STATUS_FETCH_OR_PARSE_ERROR,
                    "reason": "no page outcome recorded",
                }
            )

    unresolved.sort(
        key=lambda entry: (str(entry.get("id") or ""), str(entry.get("status") or ""))
    )
    snapshot = {
        "schema_version": "1.0.0",
        "game": "sts2",
        "source": "untapped",
        "collected_at": collected_at,
        "shop_eligible_ids": eligible,
        "relics": relics,
        "unresolved": unresolved,
    }
    validate_relic_shop_snapshot(snapshot)
    return snapshot


def shop_completion_counts(snapshot: dict[str, Any]) -> dict[str, int]:
    """Count how every shop-eligible id was resolved in a snapshot."""
    counts: dict[str, int] = {
        SHOP_STATUS_VALID: len(snapshot.get("relics") or {}),
    }
    for entry in snapshot.get("unresolved") or []:
        status = entry.get("status")
        if status in ELIGIBLE_STATUSES:
            counts[status] = counts.get(status, 0) + 1
    return counts


def completion_ledger_complete(snapshot: dict[str, Any]) -> bool:
    """True when relics + eligible unresolved statuses cover every eligible id."""
    counts = shop_completion_counts(snapshot)
    covered = sum(counts.values())
    return covered == len(snapshot.get("shop_eligible_ids") or [])


def sample_distribution(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Report offered-sample spread and how many relics currently render rows."""
    samples: list[int] = []
    relics = snapshot.get("relics") or {}
    for entry in relics.values():
        for act_key, row in (entry.get("shop") or {}).items():
            offered = row.get("offered")
            if isinstance(offered, int) and offered > 0:
                samples.append(offered)
    eligible = snapshot.get("shop_eligible_ids") or []
    ordered_samples = list(samples)
    sorted_samples = sorted(ordered_samples)
    if sorted_samples:
        middle = len(sorted_samples) // 2
        if len(sorted_samples) % 2 == 0:
            median = (sorted_samples[middle - 1] + sorted_samples[middle]) / 2.0
        else:
            median = float(sorted_samples[middle])
    else:
        median = None
    return {
        "act_samples": ordered_samples,
        "min": sorted_samples[0] if sorted_samples else None,
        "median": median,
        "max": sorted_samples[-1] if sorted_samples else None,
        "shop_eligible": len(eligible),
        "entries_with_data": len(relics),
        "entries_without_rendered_data": len(eligible) - len(relics),
    }


def completion_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Real coverage report over a fully classified shop snapshot."""
    counts = shop_completion_counts(snapshot)
    error_rows = [
        {"id": entry.get("id"), "reason": entry.get("reason")}
        for entry in snapshot.get("unresolved") or []
        if entry.get("status") == SHOP_STATUS_FETCH_OR_PARSE_ERROR
    ]
    samples_by_act: dict[str, Any] = {}
    relics = snapshot.get("relics") or {}
    relics_with_any_act = len(relics)
    relics_with_all_three = 0
    for entry in relics.values():
        shop = entry.get("shop") or {}
        if all(isinstance(shop.get(key), dict) and shop[key] for key in ("act_1", "act_2", "act_3")):
            relics_with_all_three += 1
    for act_key in ("act_1", "act_2", "act_3"):
        samples: list[int] = []
        for entry in relics.values():
            row = (entry.get("shop") or {}).get(act_key) or {}
            offered = row.get("offered")
            if isinstance(offered, int) and offered > 0:
                samples.append(offered)
        ordered = sorted(samples)
        if ordered:
            middle = len(ordered) // 2
            median = (
                (ordered[middle - 1] + ordered[middle]) / 2.0
                if len(ordered) % 2 == 0
                else float(ordered[middle])
            )
        else:
            median = None
        samples_by_act[act_key] = {
            "with_data": len(ordered),
            "min": ordered[0] if ordered else None,
            "median": median,
            "max": ordered[-1] if ordered else None,
        }
    return {
        "shop_eligible": len(snapshot.get("shop_eligible_ids") or []),
        "valid": counts.get(SHOP_STATUS_VALID, 0),
        "insufficient": counts.get(SHOP_STATUS_INSUFFICIENT, 0),
        "no_shop_stats": counts.get(SHOP_STATUS_NO_SHOP_STATS, 0),
        "fetch_or_parse_error": counts.get(SHOP_STATUS_FETCH_OR_PARSE_ERROR, 0),
        "fetch_or_parse_errors": error_rows,
        "relics_with_any_act_data": relics_with_any_act,
        "relics_with_all_three_act_data": relics_with_all_three,
        "offered_by_act": samples_by_act,
        "ledger_complete": completion_ledger_complete(snapshot),
    }


# ---------------------------------------------------------------------------
# Snapshot writing / offline collection.
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as temporary:
        json.dump(snapshot, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def load_relic_catalog(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    raise ValueError(f"relic catalog must be a JSON list: {path}")


def relic_id_from_filename(filename: str) -> str | None:
    match = re.match(
        r"^relic_(?:ancient_|starter_|event_)?([A-Z0-9_]+)\.html$", filename
    )
    return match.group(1) if match else None


def collect_shop_stats_from_pages(
    relic_catalog: list[dict[str, Any]],
    html_files: Iterable[Path],
    *,
    collected_at: str,
) -> dict[str, Any]:
    parsed: dict[str, dict[str, Any]] = {}
    for path in html_files:
        relic_id = relic_id_from_filename(path.name)
        if relic_id is None:
            continue
        html = path.read_text(encoding="utf-8", errors="replace")
        rows = parse_relic_shop_html(html)
        if rows:
            parsed[relic_id] = rows
    return build_relic_shop_snapshot(
        relic_catalog, parsed, collected_at=collected_at
    )


def slugify_name_en(name_en: str) -> str:
    """Turn an English relic name into the site's URL slug."""
    lowered = str(name_en or "").lower().replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")


def parse_relic_sitemap_urls(xml_text: str) -> dict[str, str]:
    """Return {slug: absolute page URL} for /en/relics/ sitemap entries."""
    urls: dict[str, str] = {}
    for url in re.findall(r"<loc>(.*?)</loc>", xml_text, re.S):
        marker = "/en/relics/"
        if marker not in url:
            continue
        tail = url.split(marker, 1)[1]
        if "/" not in tail:
            continue
        _section, slug = tail.split("/", 1)
        slug = slug.strip()
        if slug and slug not in urls:
            urls[slug] = url.strip()
    return urls


def _http_session() -> "requests.Session":
    session = requests.Session()
    session.headers["User-Agent"] = _USER_AGENT
    return session


def ensure_relic_sitemap(sitemap_path: Path, session: "requests.Session") -> None:
    """Keep a local copy of the relic sitemap (fetches only when missing)."""
    if sitemap_path.is_file() and sitemap_path.stat().st_size > 0:
        return
    sitemap_path.parent.mkdir(parents=True, exist_ok=True)
    response = session.get(SITEMAP_URL, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"sitemap fetch failed: http_{response.status_code}")
    sitemap_path.write_text(response.text, encoding="utf-8")


def map_eligible_relic_pages(
    relic_catalog: list[dict[str, Any]], sitemap_urls: dict[str, str]
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Map every shop-eligible relic id to its Untapped page URL by slug."""
    page_by_id: dict[str, str] = {}
    unmatched: list[tuple[str, str]] = []
    for relic in relic_catalog:
        relic_id = str(relic.get("id") or "").strip()
        if not relic_id or not _is_shop_eligible(relic.get("tier")):
            continue
        slug = slugify_name_en(str(relic.get("name_en") or ""))
        url = sitemap_urls.get(slug)
        if url:
            page_by_id[relic_id] = url
        else:
            unmatched.append((relic_id, slug))
    return page_by_id, unmatched


def fetch_relic_page(
    relic_id: str, url: str, html_dir: Path, session: "requests.Session"
) -> str | None:
    """Download one relic page into html_dir/relic_{id}.html.

    Returns None on success or a short error token such as http_404.
    """
    response = session.get(url, timeout=30)
    if response.status_code != 200:
        return f"http_{response.status_code}"
    html_dir.mkdir(parents=True, exist_ok=True)
    target = html_dir / f"relic_{relic_id}.html"
    target.write_text(response.text, encoding="utf-8")
    return None


def run_shop_completion(
    relic_catalog: list[dict[str, Any]],
    html_dir: Path,
    sitemap_path: Path,
    *,
    session: "requests.Session | None" = None,
    delay: float = DEFAULT_DELAY_SECONDS,
    offline: bool = False,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """Check every shop-eligible relic page and classify it for the snapshot.

    Reuses any already cached page; downloads missing pages one at a time
    with a polite delay and caches each success.  Fetch/parse problems are
    preserved as fetch_or_parse_error entries instead of being dropped.
    """
    session = session if session is not None else _http_session()
    if not offline:
        ensure_relic_sitemap(sitemap_path, session)
    xml_text = sitemap_path.read_text(encoding="utf-8", errors="replace")
    sitemap_urls = parse_relic_sitemap_urls(xml_text)
    page_by_id, unmatched = map_eligible_relic_pages(relic_catalog, sitemap_urls)

    outcomes: dict[str, Any] = {}
    blocked = False
    for relic_id in sorted(page_by_id):
        cache_path = html_dir / f"relic_{relic_id}.html"
        error: str | None = None
        if not (cache_path.is_file() and cache_path.stat().st_size > 0):
            if blocked:
                error = "blocked_by_earlier_http_error"
            elif offline:
                error = "page_not_cached_offline"
            else:
                try:
                    error = fetch_relic_page(
                        relic_id, page_by_id[relic_id], html_dir, session
                    )
                    if error in ("http_403", "http_429"):
                        blocked = True
                        error = f"{error}_stopped"
                    if error is None and delay:
                        time.sleep(delay)
                except requests.RequestException as exc:
                    error = f"request_exception_{type(exc).__name__}"
        if error:
            outcomes[relic_id] = {"error": error}
            continue
        try:
            html = cache_path.read_text(encoding="utf-8", errors="replace")
            outcomes[relic_id] = parse_relic_shop_page(html)
        except Exception as exc:  # noqa: BLE001 - preserve parse failures
            outcomes[relic_id] = {"error": f"parse_exception_{type(exc).__name__}"}

    for relic_id, _slug in unmatched:
        outcomes[relic_id] = {"error": "relic_missing_from_sitemap"}

    snapshot = build_relic_shop_snapshot(
        relic_catalog, outcomes, collected_at=collected_at or _utc_now()
    )
    if not completion_ledger_complete(snapshot):
        raise RuntimeError("shop completion ledger is incomplete")
    return snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("completion", "cache"),
        default="completion",
        help="completion checks every shop-eligible id; cache only scans local pages",
    )
    parser.add_argument(
        "--html-dir",
        type=Path,
        default=Path.home() / "AppData" / "Local" / "Temp" / "sts2_pages",
    )
    parser.add_argument("--relics", type=Path, default=Path("data/raw/sts2_relics.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/stats/sts2_relic_shop_stats.json")
    )
    parser.add_argument(
        "--sitemap",
        type=Path,
        default=Path.home()
        / "AppData"
        / "Local"
        / "Temp"
        / "sts2_pages"
        / "relics_sitemap.xml",
    )
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="never fetch; uncached pages become fetch_or_parse_error",
    )
    parser.add_argument("--collected-at", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    catalog = load_relic_catalog(args.relics)
    collected_at = args.collected_at or _utc_now()

    if args.mode == "cache":
        html_dir = args.html_dir
        files = sorted(html_dir.glob("relic_*.html")) if html_dir.is_dir() else []
        snapshot = collect_shop_stats_from_pages(
            catalog, files, collected_at=collected_at
        )
        write_snapshot(args.output, snapshot)
        print(json.dumps(sample_distribution(snapshot), ensure_ascii=False, indent=2))
        print(f"relic entries: {len(snapshot['relics'])}")
        print(f"unresolved: {len(snapshot['unresolved'])}")
        print(f"wrote: {args.output}")
        return 0

    session = None if args.offline else _http_session()
    snapshot = run_shop_completion(
        catalog,
        args.html_dir,
        args.sitemap,
        session=session,
        delay=args.delay,
        offline=args.offline,
        collected_at=collected_at,
    )
    write_snapshot(args.output, snapshot)
    report = completion_report(snapshot)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    counts = shop_completion_counts(snapshot)
    print(
        "checked: "
        f"{report['shop_eligible']} | valid: {report['valid']} | "
        f"insufficient: {report['insufficient']} | "
        f"no_shop_stats: {report['no_shop_stats']} | "
        f"fetch/parse error: {report['fetch_or_parse_error']}"
    )
    print(f"wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

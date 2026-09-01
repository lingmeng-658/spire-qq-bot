"""Build a local-only STS2 card statistics snapshot from public sources.

This is a development-time utility. Bot/runtime code must only consume the
generated JSON and must never call these sources directly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests


UNTAPPED_BASE_URL = "https://sts2.untapped.gg"
UNTAPPED_CARDS_URL = f"{UNTAPPED_BASE_URL}/en/cards"
UNTAPPED_SITEMAP_URL = f"{UNTAPPED_BASE_URL}/sitemap/cards.xml"
SPIRE_CODEX_BASE_URL = "https://spire-codex.com"
SPIRE_CODEX_METRICS_URL = f"{SPIRE_CODEX_BASE_URL}/api/runs/metrics/cards"
SPIRE_CODEX_RUN_VERSIONS_URL = f"{SPIRE_CODEX_BASE_URL}/api/runs/versions"
SPIRE_CODEX_OPENAPI_URL = f"{SPIRE_CODEX_BASE_URL}/openapi.json"
USER_AGENT = "card-guess-bot-stats-snapshot/1.0"


Metric = dict[str, Any]
FetchText = Callable[[str], str]
FetchJson = Callable[[str], Any]


def _classes(attrs: list[tuple[str, str | None]]) -> str:
    return dict(attrs).get("class") or ""


class _UntappedStatsParser(HTMLParser):
    """Stream only the small stats subset out of a large Next.js page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.section_depth: int | None = None
        self.section_title = ""
        self.section_cells: list[dict[str, str]] = []
        self.cell_depth: int | None = None
        self.cell: dict[str, str] | None = None
        self.captures: list[dict[str, Any]] = []
        self.sections: list[tuple[str, list[dict[str, str]]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.depth += 1
        css = _classes(attrs)

        if tag == "section" and self.section_depth is None:
            self.section_depth = self.depth
            self.section_title = ""
            self.section_cells = []
            return

        if self.section_depth is None:
            return

        if tag == "h2":
            self._capture("title", tag)
        elif tag == "div" and "StatCell" in css and "__cell" in css:
            self.cell_depth = self.depth
            self.cell = {}
        elif self.cell is not None:
            if tag == "span" and "__act" in css:
                self._capture("act", tag)
            elif tag == "span" and "__offered" in css:
                self._capture("sample", tag)
            elif tag == "div" and "__pickRate" in css:
                self._capture("primary_rate", tag)
            elif tag == "div" and "__winRate" in css:
                self._capture("win_rate", tag)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        for capture in self.captures:
            capture["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        finishing = [
            capture
            for capture in self.captures
            if capture["tag"] == tag and capture["depth"] == self.depth
        ]
        for capture in finishing:
            text = " ".join("".join(capture["text"]).split())
            kind = capture["kind"]
            if kind == "title":
                self.section_title = text
            elif self.cell is not None:
                if kind == "win_rate":
                    previous = self.cell.get(kind)
                    self.cell[kind] = f"{previous}|{text}" if previous else text
                else:
                    self.cell[kind] = text
            self.captures.remove(capture)

        if tag == "div" and self.cell_depth == self.depth and self.cell is not None:
            self.section_cells.append(self.cell)
            self.cell = None
            self.cell_depth = None

        if tag == "section" and self.section_depth == self.depth:
            self.sections.append((self.section_title, self.section_cells))
            self.section_depth = None
            self.section_title = ""
            self.section_cells = []
            self.cell = None
            self.cell_depth = None
            self.captures.clear()

        self.depth = max(0, self.depth - 1)

    def _capture(self, kind: str, tag: str) -> None:
        self.captures.append(
            {"kind": kind, "tag": tag, "depth": self.depth, "text": []}
        )


def _parse_percent(text: str) -> float | None:
    match = re.search(r"([+-]?\d+(?:\.\d+)?)\s*%", text)
    return float(match.group(1)) if match else None


def _parse_sample(text: str) -> tuple[int | None, str | None]:
    match = re.search(
        r"(?:offered|seen)\s+([\d,.]+\s*[KMB]?)\s+times", text, re.IGNORECASE
    )
    if not match:
        return None, None
    display = re.sub(r"\s+", "", match.group(1))
    suffix = display[-1:].upper()
    multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
        suffix, 1
    )
    number = display[:-1] if multiplier != 1 else display
    try:
        return int(round(float(number.replace(",", "")) * multiplier)), display
    except ValueError:
        return None, display


def _metric(
    value: float,
    unit: str,
    sample_size: int | None,
    sample_display: str | None,
) -> Metric:
    result: Metric = {"value": value, "unit": unit}
    if sample_size is not None:
        result["sample_size"] = sample_size
    if sample_display is not None:
        result["sample_size_display"] = sample_display
    return result


def parse_untapped_card_html(html: str) -> dict[str, Any]:
    parser = _UntappedStatsParser()
    parser.feed(html)
    result: dict[str, Any] = {}

    for title, cells in parser.sections:
        if "Card Reward" in title:
            section_key = "card_reward"
            primary_label = "Picked"
            primary_key = "pick_rate"
        elif "Shop" in title:
            section_key = "shop"
            primary_label = "Bought"
            primary_key = "purchase_rate"
        elif "Smith" in title:
            section_key = "smith"
            primary_label = "Upgraded"
            primary_key = "upgrade_rate"
        else:
            continue

        section: dict[str, Any] = {}
        for cell in cells:
            act_match = re.search(r"Act\s+(\d+)", cell.get("act", ""), re.IGNORECASE)
            if not act_match:
                continue
            act_key = f"act_{act_match.group(1)}"
            sample_size, sample_display = _parse_sample(cell.get("sample", ""))
            values: dict[str, Any] = {}

            primary = cell.get("primary_rate", "")
            primary_value = _parse_percent(primary)
            if primary_label.lower() in primary.lower() and primary_value is not None:
                values[primary_key] = _metric(
                    primary_value, "percent", sample_size, sample_display
                )

            for win_rate in cell.get("win_rate", "").split("|"):
                value = _parse_percent(win_rate)
                if value is None:
                    continue
                if "Act Winrate" in win_rate:
                    key = "act_win_rate_impact"
                elif "Run Winrate" in win_rate:
                    key = "run_win_rate_impact"
                else:
                    continue
                values[key] = _metric(
                    value, "percentage_points", sample_size, sample_display
                )

            if values:
                section[act_key] = values
        if section:
            result[section_key] = section

    return result


def parse_untapped_sitemap(xml: str) -> list[str]:
    root = ElementTree.fromstring(xml)
    urls = []
    for element in root.iter():
        if not element.tag.endswith("loc") or not element.text:
            continue
        url = element.text.strip()
        path = urlparse(url).path
        if path.startswith("/en/cards/") and len(path.strip("/").split("/")) == 4:
            urls.append(url)
    return sorted(set(urls))


def _untapped_path(card: dict[str, Any]) -> str:
    card_id = str(card.get("id") or "").strip().lower().replace("_", "-")
    color = str(card.get("color") or "").strip().lower()
    return f"/en/cards/{color}/{card_id}"


def match_untapped_urls(
    cards: Iterable[dict[str, Any]], urls: Iterable[str]
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    local_cards = list(cards)
    url_by_path = {urlparse(url).path: url for url in urls}
    paths_by_slug: dict[str, list[str]] = {}
    for path in url_by_path:
        paths_by_slug.setdefault(path.rstrip("/").split("/")[-1], []).append(path)
    matched: dict[str, str] = {}
    used_paths: set[str] = set()
    unresolved: list[dict[str, Any]] = []

    for card in local_cards:
        card_id = str(card.get("id") or "").strip()
        path = _untapped_path(card)
        if card_id and path in url_by_path:
            matched[card_id] = url_by_path[path]
            used_paths.add(path)
        elif card_id:
            slug_paths = paths_by_slug.get(card_id.lower().replace("_", "-"), [])
            if len(slug_paths) == 1:
                fallback_path = slug_paths[0]
                matched[card_id] = url_by_path[fallback_path]
                used_paths.add(fallback_path)
            else:
                unresolved.append(
                    {
                        "source": "untapped",
                        "reason": "local_card_missing_from_source",
                        "card_id": card_id,
                        "expected_path": path,
                    }
                )

    for path, url in sorted(url_by_path.items()):
        if path not in used_paths:
            unresolved.append(
                {
                    "source": "untapped",
                    "reason": "source_card_missing_from_local_catalog",
                    "source_url": url,
                }
            )

    return matched, unresolved


def parse_spire_codex_metrics(
    payload: dict[str, Any],
    local_ids: set[str],
    *,
    report_missing_local: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    total_runs = payload.get("total_runs")
    if not isinstance(total_runs, int) or total_runs <= 0:
        raise ValueError("Spire Codex metrics response has no positive total_runs")

    result: dict[str, Any] = {}
    unresolved: list[dict[str, Any]] = []
    for row in payload.get("rows") or []:
        if not isinstance(row, dict) or row.get("upgraded") is not False:
            continue
        card_id = str(row.get("id") or "").strip().upper()
        if not card_id:
            continue
        if card_id not in local_ids:
            unresolved.append(
                {
                    "source": "spire_codex",
                    "reason": "source_card_missing_from_local_catalog",
                    "card_id": card_id,
                }
            )
            continue
        final_deck_runs = row.get("picks")
        if not isinstance(final_deck_runs, int) or final_deck_runs < 0:
            continue
        result[card_id] = {
            "final_deck_runs": {
                "value": final_deck_runs,
                "sample_size": total_runs,
            },
            "final_deck_presence_rate": {
                "value": round(final_deck_runs / total_runs * 100, 4),
                "unit": "percent",
                "sample_size": total_runs,
                "numerator": final_deck_runs,
                "denominator": total_runs,
                "derived": True,
            },
        }

    if report_missing_local:
        for card_id in sorted(local_ids - result.keys()):
            unresolved.append(
                {
                    "source": "spire_codex",
                    "reason": "local_card_missing_from_source",
                    "card_id": card_id,
                }
            )
    return result, unresolved


def _get_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _coverage_paths() -> list[str]:
    paths = ["untapped.card_reward.overall.pick_rate"]
    for act in (1, 2, 3):
        paths.extend(
            [
                f"untapped.card_reward.act_{act}.pick_rate",
                f"untapped.card_reward.act_{act}.act_win_rate_impact",
                f"untapped.card_reward.act_{act}.run_win_rate_impact",
                f"untapped.shop.act_{act}.purchase_rate",
                f"untapped.shop.act_{act}.act_win_rate_impact",
                f"untapped.shop.act_{act}.run_win_rate_impact",
                f"untapped.smith.act_{act}.upgrade_rate",
                f"untapped.smith.act_{act}.act_win_rate_impact",
                f"untapped.smith.act_{act}.run_win_rate_impact",
            ]
        )
    paths.extend(
        [
            "spire_codex.acquisition_count",
            "spire_codex.average_acquisition_floor",
            "spire_codex.final_deck_presence_rate",
            "spire_codex.retention_after_acquisition_rate",
        ]
    )
    return paths


def coverage_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    cards = snapshot.get("cards") or {}
    total = len(cards)
    report: dict[str, Any] = {
        "local_cards": total,
        "matched_cards": {
            source: sum(1 for card in cards.values() if source in card)
            for source in ("untapped", "spire_codex")
        },
        "fields": {},
    }
    for path in _coverage_paths():
        count = sum(1 for card in cards.values() if _get_path(card, path) is not None)
        report["fields"][path] = {
            "cards": count,
            "coverage": round(count / total * 100, 2) if total else 0.0,
        }
    return report


def build_snapshot(
    cards: Iterable[dict[str, Any]],
    untapped_stats: dict[str, Any],
    spire_codex_stats: dict[str, Any],
    *,
    source_metadata: dict[str, Any],
    unresolved: list[dict[str, Any]],
    collected_at: str,
) -> dict[str, Any]:
    aligned: dict[str, Any] = {}
    for card in cards:
        card_id = str(card.get("id") or "").strip()
        if not card_id:
            continue
        entry: dict[str, Any] = {
            "id": card_id,
            "name": card.get("name"),
            "pool": card.get("color"),
        }
        if card_id in untapped_stats:
            entry["untapped"] = untapped_stats[card_id]
        if card_id in spire_codex_stats:
            entry["spire_codex"] = spire_codex_stats[card_id]
        aligned[card_id] = entry

    snapshot: dict[str, Any] = {
        "schema_version": "1.0.0",
        "game": "sts2",
        "collected_at": collected_at,
        "sources": source_metadata,
        "cards": aligned,
        "unresolved": unresolved,
    }
    snapshot["coverage"] = coverage_report(snapshot)
    return snapshot


def _extract_untapped_version(html: str) -> dict[str, Any]:
    version_match = re.search(r"version\\?\":\\?\"(v0\.\d+\.\d+)", html)
    beta_match = re.search(r"isBeta\\?\":(true|false)", html)
    result: dict[str, Any] = {}
    if version_match:
        result["game_version"] = version_match.group(1)
    if beta_match:
        result["is_beta"] = beta_match.group(1) == "true"
    return result


class HttpClient:
    _TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        timeout: float = 30.0,
        retries: int = 2,
        *,
        getter: Callable[..., Any] = requests.get,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.getter = getter
        self.sleeper = sleeper

    def text(self, url: str) -> str:
        for attempt in range(self.retries + 1):
            try:
                response = self.getter(
                    url, headers={"User-Agent": USER_AGENT}, timeout=self.timeout
                )
                if (
                    response.status_code in self._TRANSIENT_STATUS_CODES
                    and attempt < self.retries
                ):
                    self.sleeper(0.5 * (2**attempt))
                    continue
                response.raise_for_status()
                return response.text
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= self.retries:
                    raise
                self.sleeper(0.5 * (2**attempt))
        raise RuntimeError("unreachable HTTP retry state")

    def json(self, url: str) -> Any:
        return json.loads(self.text(url))


def collect_untapped(
    cards: list[dict[str, Any]],
    fetch_text: FetchText,
    *,
    workers: int = 8,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    sitemap_xml = fetch_text(UNTAPPED_SITEMAP_URL)
    urls = parse_untapped_sitemap(sitemap_xml)
    matched_urls, unresolved = match_untapped_urls(cards, urls)
    stats: dict[str, Any] = {}

    def fetch_card(card_id: str, url: str) -> tuple[str, dict[str, Any]]:
        return card_id, parse_untapped_card_html(fetch_text(url))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(fetch_card, card_id, url): (card_id, url)
            for card_id, url in matched_urls.items()
        }
        for future in as_completed(futures):
            card_id, url = futures[future]
            try:
                parsed_id, parsed = future.result()
            except Exception as exc:
                unresolved.append(
                    {
                        "source": "untapped",
                        "reason": "fetch_or_parse_failed",
                        "card_id": card_id,
                        "source_url": url,
                        "error": str(exc),
                    }
                )
                continue
            if parsed:
                stats[parsed_id] = parsed

    cards_page = fetch_text(UNTAPPED_CARDS_URL)
    metadata = {
        "source": UNTAPPED_BASE_URL,
        "collected_from": [UNTAPPED_SITEMAP_URL, "individual English card pages"],
        "scope": {
            "players": "singleplayer",
            "ascension": "7+",
            "character": "card pool",
            "grouping": "act 1/2/3",
        },
        "version": _extract_untapped_version(cards_page),
    }
    return stats, metadata, unresolved


def collect_spire_codex(
    local_ids: set[str], fetch_json: FetchJson
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    metrics_payload = fetch_json(SPIRE_CODEX_METRICS_URL)
    stats, unresolved = parse_spire_codex_metrics(
        metrics_payload, local_ids, report_missing_local=True
    )
    versions = fetch_json(SPIRE_CODEX_RUN_VERSIONS_URL)
    openapi = fetch_json(SPIRE_CODEX_OPENAPI_URL)
    metadata = {
        "source": SPIRE_CODEX_BASE_URL,
        "collected_from": [
            SPIRE_CODEX_METRICS_URL,
            SPIRE_CODEX_RUN_VERSIONS_URL,
            SPIRE_CODEX_OPENAPI_URL,
        ],
        "scope": {
            "bracket": metrics_payload.get("bracket", "all"),
            "players": "all",
            "game_modes": "all",
            "versions": "all submitted runs",
            "total_runs": metrics_payload.get("total_runs"),
        },
        "version": {
            "api": (openapi.get("info") or {}).get("version"),
            "latest_stat_version": (versions.get("stat_versions") or [None])[0],
        },
    }
    return stats, metadata, unresolved


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as temporary:
        json.dump(snapshot, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def generate_snapshot(
    cards_path: Path,
    output_path: Path,
    *,
    workers: int = 8,
    timeout: float = 30.0,
) -> dict[str, Any]:
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    client = HttpClient(timeout=timeout)
    collected_at = _utc_now()
    untapped, untapped_meta, untapped_unresolved = collect_untapped(
        cards, client.text, workers=workers
    )
    local_ids = {str(card.get("id") or "").strip() for card in cards}
    codex, codex_meta, codex_unresolved = collect_spire_codex(local_ids, client.json)
    for metadata in (untapped_meta, codex_meta):
        metadata["collected_at"] = collected_at
    snapshot = build_snapshot(
        cards,
        untapped,
        codex,
        source_metadata={"untapped": untapped_meta, "spire_codex": codex_meta},
        unresolved=untapped_unresolved + codex_unresolved,
        collected_at=collected_at,
    )
    write_snapshot(output_path, snapshot)
    return snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cards", type=Path, default=Path("data/raw/sts2_cards.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/stats/sts2_card_stats.json")
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    snapshot = generate_snapshot(
        args.cards,
        args.output,
        workers=args.workers,
        timeout=args.timeout,
    )
    print(json.dumps(snapshot["coverage"], ensure_ascii=False, indent=2))
    print(f"unresolved: {len(snapshot['unresolved'])}")
    print(f"wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

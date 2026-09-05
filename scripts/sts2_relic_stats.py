"""Build the local STS2 relic run-presence snapshot artifact.

Development-time utility that regenerates ``data/stats/sts2_relic_stats.json``
from Spire Codex relic metrics.  Runtime/bot code must only consume the
generated JSON and must never call the source directly.

The source is polled sequentially with pacing and retries (the site returns
transient 502/520 responses under bursts).  One unfiltered call provides the
overall rows and one call per canonical STS2 character provides per-character
rows plus the ``character_runs`` / ``character_wins`` denominators.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.sts2_relic_stats import (  # noqa: E402
    COLLECTED_FROM,
    DATASET_ID,
    SPIRE_CODEX_BASE_URL,
    SPIRE_CODEX_METRICS_URL,
    STS2_CHARACTERS,
    build_sts2_relic_snapshot,
    validate_sts2_relic_snapshot,
)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504, 520, 524}

DEFAULT_CATALOG_PATH = Path("data/raw/sts2_relics.json")
DEFAULT_OUTPUT_PATH = Path("data/stats/sts2_relic_stats.json")


def fetch_json(
    url: str,
    *,
    timeout: float = 60.0,
    attempts: int = 5,
    sleeper: Callable[[float], None] = time.sleep,
) -> Any:
    """GET a JSON payload with retries/backoff for transient site errors."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": BROWSER_USER_AGENT},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts - 1:
                sleeper(8.0 + attempt * 4.0)
                continue
            raise
        if response.status_code in TRANSIENT_STATUS_CODES:
            if attempt < attempts - 1:
                sleeper(8.0 + attempt * 4.0)
                continue
            response.raise_for_status()
        response.raise_for_status()
        return response.json()
    assert last_error is not None
    raise last_error


def collect_payloads(
    *,
    character_url: Callable[[str], str],
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Fetch the overall and per-character relic metrics payloads sequentially."""
    overall = fetch_json(SPIRE_CODEX_METRICS_URL)
    sleeper(6.0)
    per_character: dict[str, dict[str, Any]] = {}
    for index, character in enumerate(STS2_CHARACTERS):
        per_character[character] = fetch_json(character_url(character))
        if index < len(STS2_CHARACTERS) - 1:
            sleeper(6.0)
    return overall, per_character


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


def character_url(character: str) -> str:
    return f"{SPIRE_CODEX_METRICS_URL}?character={character}"


def generate_snapshot(
    catalog_path: Path,
    output_path: Path,
    *,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    overall_payload, character_payloads = collect_payloads(
        character_url=character_url, sleeper=sleeper
    )
    snapshot = build_sts2_relic_snapshot(
        overall_payload=overall_payload,
        character_payloads=character_payloads,
        relic_catalog=catalog,
        collected_at=_utc_now(),
        collected_from=COLLECTED_FROM,
        dataset_id=DATASET_ID,
    )
    validate_sts2_relic_snapshot(snapshot)
    write_snapshot(output_path, snapshot)
    return snapshot


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=DEFAULT_CATALOG_PATH
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.catalog.exists():
        raise SystemExit(f"relic catalog not found: {args.catalog}")
    snapshot = generate_snapshot(args.catalog, args.output)
    scope = snapshot["scope"]
    print(
        "relics={} total_runs={} baseline_win_rate={} unresolved={}".format(
            len(snapshot["relics"]),
            scope["total_runs"],
            scope["baseline_win_rate"],
            len(snapshot["unresolved"]),
        )
    )
    print(f"collected_at={scope['collected_at']}")
    print(f"wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

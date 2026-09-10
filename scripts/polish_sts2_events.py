"""Rebuild STS2 event player-visible text from parsed archive zh output.

The frozen catalog keeps every ``raw`` payload byte-for-byte; this script only
replaces the player-visible fields with official archive zh text when a
stable, unambiguous choice key exists and the text is fully localized.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.event_text_polish import polish_catalog_text  # noqa: E402


DEFAULT_CATALOG = Path("data/raw/sts2_events.json")
DEFAULT_RAW_DIR = Path(os.environ.get("TEMP", ".")) / "sts2_loc"
DEFAULT_ARCHIVE_DIR = Path(r"D:\Projects\spire-archive\data\sts2")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--raw-en", type=Path, default=DEFAULT_RAW_DIR / "data__eng__events.json")
    parser.add_argument("--archive-en", type=Path, default=DEFAULT_ARCHIVE_DIR / "events.json")
    parser.add_argument(
        "--archive-zh",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR / "localization" / "zh.json",
    )
    args = parser.parse_args(argv)

    catalog = _load(args.catalog)
    raw_en = _load(args.raw_en)
    archive_en = _load(args.archive_en)
    archive_zh_payload = _load(args.archive_zh)
    archive_zh = archive_zh_payload["events"]

    polished, unresolved = polish_catalog_text(
        catalog,
        raw_en_events=raw_en,
        archive_en_events=archive_en,
        archive_zh_events=archive_zh,
    )

    provenance = [
        "spire-archive parsed zh events (player-visible zh text)",
        "spire-archive parsed en events (stable choice key alignment)",
    ]
    for item in provenance:
        if item not in polished["source"]:
            polished["source"].append(item)

    args.catalog.write_text(
        json.dumps(polished, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"wrote {args.catalog}")
    print(f"unresolved fields: {len(unresolved)}")
    for item in unresolved:
        print(f"  {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

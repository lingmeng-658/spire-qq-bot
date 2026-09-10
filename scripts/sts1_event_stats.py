"""Build the STS1 Event Stats v1 draft snapshot artifact.

Development-time utility that streams the official November run dump, maps
each playable event's recorded ``event_choices`` through the audited
event_id <-> dump event_name table, applies the A7+ decision cohort and the
data-hygiene filters (float floors, per-run dedupe, act 1-3 floors), and
writes ``data/stats/sts1_event_stats_draft.json``.  Runtime/bot code must only
consume generated JSON snapshots and must never call these sources directly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.events import load_events  # noqa: E402
from card_guess.relic_stats import utc_now  # noqa: E402
from card_guess.sts1_card_stats import iter_sts1_runs  # noqa: E402
from card_guess.sts1_event_stats import (  # noqa: E402
    DEFAULT_ASCENSION_MAX,
    DEFAULT_ASCENSION_MIN,
    DEFAULT_MIN_ASSOCIATION_SAMPLE,
    aggregate_sts1_event_stats,
)

DEFAULT_RUNS_PATH = Path("data/raw/november.json")
DEFAULT_OUTPUT_PATH = Path("data/stats/sts1_event_stats_draft.json")


def build_snapshot(
    runs_path: Path,
    *,
    out_path: Path,
    ascension_min: int = DEFAULT_ASCENSION_MIN,
    ascension_max: int = DEFAULT_ASCENSION_MAX,
    min_association_sample: int = DEFAULT_MIN_ASSOCIATION_SAMPLE,
) -> dict[str, object]:
    if not runs_path.exists():
        raise SystemExit(f"run dump not found: {runs_path}")
    catalog = {
        event.id: {
            "name_en": event.name_en,
            "name_zh": event.name_zh,
            "pool": event.pool,
            "act": event.act,
        }
        for event in load_events("sts1").events
    }
    result = aggregate_sts1_event_stats(
        iter_sts1_runs(str(runs_path)),
        collected_at=utc_now(),
        ascension_min=ascension_min,
        ascension_max=ascension_max,
        min_association_sample=min_association_sample,
        catalog_events=catalog,
    )
    snapshot = result["snapshot"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=out_path.parent, delete=False, newline="\n"
    ) as temporary:
        json.dump(snapshot, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, out_path)
    return {"snapshot": snapshot, "report": result["report"]}


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--ascension-min", type=int, default=DEFAULT_ASCENSION_MIN)
    parser.add_argument("--ascension-max", type=int, default=DEFAULT_ASCENSION_MAX)
    parser.add_argument(
        "--min-association-sample", type=int, default=DEFAULT_MIN_ASSOCIATION_SAMPLE
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    result = build_snapshot(
        args.runs,
        out_path=args.out,
        ascension_min=args.ascension_min,
        ascension_max=args.ascension_max,
        min_association_sample=args.min_association_sample,
    )
    report = result["report"]
    print(f"wrote {args.out}")
    print(
        "total_runs={} accepted_runs={} duplicate_runs={} decisions_in_scope={} "
        "float_floor_normalized={} ignored_out_of_act={}".format(
            report["total_runs"],
            report["accepted_runs"],
            report["duplicate_runs"],
            report["decisions_in_scope"],
            report["float_floor_normalized"],
            report["ignored_records"]["out_of_act_floor"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

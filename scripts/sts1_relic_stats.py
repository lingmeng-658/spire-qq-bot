"""Build the STS1 terminal-relic snapshot artifact (policy C).

Development-time utility: regenerates ``data/stats/sts1_relic_stats.json`` from
the official November run dump and the STS1 relic catalog.  Runtime/bot code
must only consume the generated JSON and must never call these sources
directly.

R2A-2 scope: the snapshot covers terminal ``relics`` presence, heart-win
presence, and per-act boss choices.  R5B adds first-acquisition floor timing
for Common / Uncommon / Rare relics from recorded ``relics_obtained`` events.
It still does not compute shop purchases or STS2 statistics.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
import sys

from card_guess.relic_stats import utc_now
from card_guess.sts1_relic_stats import aggregate_sts1_relics

DEFAULT_RUNS_PATH = Path("data/raw/november.json")
DEFAULT_RELIC_CATALOG_PATH = Path("data/raw/sts1_relics.json")
DEFAULT_OUT_PATH = Path("data/stats/sts1_relic_stats.json")


def build_snapshot(
    runs_path: Path,
    relic_catalog_path: Path,
    *,
    out_path: Path,
    report_path: Path | None = None,
) -> dict[str, object]:
    """Run the full aggregation and write the snapshot artifact."""
    if not runs_path.exists():
        raise SystemExit(f"run dump not found: {runs_path}")
    if not relic_catalog_path.exists():
        raise SystemExit(f"relic catalog not found: {relic_catalog_path}")
    with relic_catalog_path.open("r", encoding="utf-8") as handle:
        relic_catalog = json.load(handle)
    result = aggregate_sts1_relics(
        str(runs_path),
        relic_catalog=relic_catalog,
        collected_at=utc_now(),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result["snapshot"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result["report"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS_PATH)
    parser.add_argument("--relic-catalog", type=Path, default=DEFAULT_RELIC_CATALOG_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--report-out", type=Path, default=None)
    args = parser.parse_args(argv)

    result = build_snapshot(
        args.runs,
        args.relic_catalog,
        out_path=args.out,
        report_path=args.report_out,
    )
    report = result["report"]
    print(f"wrote {args.out}")
    print(
        "valid_runs={} total_runs={} catalog_relics={} observed_relics={} "
        "unresolved_relic_keys={} invalid_relic_entries={}".format(
            report["valid_runs"],
            report["total_runs"],
            report["catalog_relic_count"],
            report["observed_relic_count"],
            report["unresolved_relic_keys"],
            report["invalid_relic_entries"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
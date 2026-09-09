"""Build the local STS2 Event Stats v1 snapshot artifact.

Development-time utility that streams the audited STS2 Runs gzip NDJSON dump
and writes the aggregated, validated ``data/stats/sts2_event_stats.json``.
The raw dump is never committed and runtime/bot code never reads it.

Usage:
    python scripts/sts2_event_stats.py \
        --runs <local runs-all-before-2026-06.json.gz> \
        --out data/stats/sts2_event_stats.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.relic_stats import utc_now  # noqa: E402
from card_guess.sts2_event_stats import (  # noqa: E402
    DEFAULT_MIN_ASSOCIATION_SAMPLE,
    aggregate_sts2_event_stats,
)

DEFAULT_OUTPUT_PATH = Path("data/stats/sts2_event_stats.json")


def iter_sts2_runs(runs_path: str | Path) -> Iterator[dict[str, Any]]:
    """Stream one raw run mapping per gzip NDJSON line."""

    with gzip.open(runs_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            yield json.loads(line)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as temporary:
        json.dump(snapshot, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def build_snapshot(
    runs_path: Path,
    *,
    out_path: Path = DEFAULT_OUTPUT_PATH,
    min_association_sample: int = DEFAULT_MIN_ASSOCIATION_SAMPLE,
) -> dict[str, Any]:
    if not runs_path.exists():
        raise SystemExit(f"run dump not found: {runs_path}")
    result = aggregate_sts2_event_stats(
        iter_sts2_runs(runs_path),
        collected_at=utc_now(),
        source_sha256=sha256_file(runs_path),
        min_association_sample=min_association_sample,
    )
    write_snapshot(out_path, result["snapshot"])
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument(
        "--min-association-sample",
        type=int,
        default=DEFAULT_MIN_ASSOCIATION_SAMPLE,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_snapshot(
        args.runs,
        out_path=args.out,
        min_association_sample=args.min_association_sample,
    )
    snapshot = result["snapshot"]
    report = result["report"]
    print(f"wrote {args.out}")
    print(
        "total_runs={} accepted_runs={} events={} choice_keys={} "
        "non_event_table_choices={} mismatches={}".format(
            report["run_count_total"],
            report["accepted_runs"],
            len(snapshot["events"]),
            sum(
                len(event["choices"])
                for event in snapshot["events"].values()
            ),
            report["non_event_table_choices"],
            report["event_id_mismatches"],
        )
    )
    print(
        "sha256={} builds={}..{} schema_versions={}".format(
            snapshot["source"]["source_sha256"],
            snapshot["source"]["source_build_min"],
            snapshot["source"]["source_build_max"],
            snapshot["source"]["source_schema_versions"],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

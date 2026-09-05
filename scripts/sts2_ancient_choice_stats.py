"""Build the STS2 Ancient offer-to-pick statistics snapshot artifact.

Development-time utility that regenerates
``data/stats/sts2_ancient_choice.json`` from local caches only (offline; no
network, no ``requests``).  Runtime/bot code must only consume the generated
JSON and must never call the sources directly.

Inputs (all captured during the earlier mapping audit):

- ``data__ancient_pools.json``  Spire Codex ``/api/ancient-pools`` payload:
  the 8 Ancient NPCs, their relic pools and per-relic act conditions.
- ``choice_rows.json``          One row per mapped (relic, NPC, act) context
  with offered counts and picked percentages taken from Untapped pages.
- ``parsed_pages.json``         Previously parsed per-act cells per slug.
- ``pages/*.html``              Cached Untapped relic pages ("Ancient Choice
  Stats" act cells).
- ``loc_report.json``           Localization audit record for the 8 NPCs.
- ``data/raw/sts2_relics.json`` Official zh relic catalog (in-repo).

Before building, every mapped row is re-verified against a fresh parse of its
cached page, relic zh names are checked against the catalog, and the relic ->
NPC / act pool mapping audit must stay clean (no multi-NPC relic, no Ancient
relic missing from the pools, no unresolved NPC zh name).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from card_guess.sts2_ancient_choice import (  # noqa: E402
    OFFICIAL_ANCIENT_NPC_ZH,
    SPIRE_CODEX_ANCIENT_POOLS_URL,
    audit_ancient_pool_mapping,
    build_sts2_ancient_choice_snapshot,
    parse_untapped_ancient_choice_page,
    validate_sts2_ancient_choice_snapshot,
)

UNTAPPED_PAGE_URL = "https://sts2.untapped.gg/en/relics/ancient/{slug}"
DEFAULT_CACHE_DIR = Path(os.environ.get("TEMP", ".")) / "sts2_loc"
DEFAULT_CATALOG_PATH = Path("data/raw/sts2_relics.json")
DEFAULT_OUTPUT_PATH = Path("data/stats/sts2_ancient_choice.json")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
        help="directory with the local audit caches (defaults to %%TEMP%%\\sts2_loc)",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args(argv)


def generate_snapshot(
    cache_dir: Path,
    catalog_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Verify local caches and write the validated ancient_choice snapshot."""
    if not cache_dir.is_dir():
        raise SystemExit(f"cache directory not found: {cache_dir}")
    if not catalog_path.exists():
        raise SystemExit(f"relic catalog not found: {catalog_path}")

    catalog = _load_json(catalog_path)
    catalog_by_id = {str(entry.get("id")): entry for entry in catalog}
    pools = _load_json(cache_dir / "data__ancient_pools.json")
    rows = _load_json(cache_dir / "choice_rows.json")
    parsed_cache = _load_json(cache_dir / "parsed_pages.json")
    loc_report = _load_json(cache_dir / "loc_report.json")
    pages_dir = cache_dir / "pages"

    # 1) NPC localization must be pinned and match the audit record.
    recorded_zh = (loc_report or {}).get("npc_zh") or {}
    npc_ids: list[str] = []
    for npc in pools:
        npc_id = str(npc.get("id") or "").strip()
        if not npc_id:
            raise ValueError("ancient pool NPC without id")
        npc_ids.append(npc_id)
        pinned = OFFICIAL_ANCIENT_NPC_ZH.get(npc_id)
        if not pinned:
            raise ValueError(f"NPC zh name not pinned for {npc_id}")
        recorded = (recorded_zh.get(npc_id) or {}).get("name")
        if recorded is not None and recorded != pinned:
            raise ValueError(
                f"NPC zh mismatch for {npc_id}: recorded {recorded!r} vs {pinned!r}"
            )
    npc_names_zh = dict(OFFICIAL_ANCIENT_NPC_ZH)

    # 2) The relic -> NPC mapping audit must stay clean.
    ancient_entries = [
        entry for entry in catalog if entry.get("tier") == "Ancient"
    ]
    audit = audit_ancient_pool_mapping(
        pools, [entry["id"] for entry in ancient_entries], npc_names_zh
    )
    if (
        audit["multi_npc"]
        or audit["missing_from_pools"]
        or audit["unresolved_relic_ids"]
        or audit["npc_localization_unresolved"]
    ):
        raise ValueError(
            "ancient mapping audit is not clean: "
            + json.dumps(audit, ensure_ascii=False)
        )
    owner_by_relic = audit["relic_to_npc"]

    # 3) Every mapped row: catalog zh + single pool owner + fresh page cell.
    normalized: list[dict[str, Any]] = []
    used_slugs: list[str] = []
    for row in rows:
        slug = str(row.get("slug") or "").strip()
        relic_id = str(row.get("relic_id") or "").strip()
        npc_id = str(row.get("npc") or "").strip()
        act = row.get("act")
        offered = row.get("offered")
        picked = row.get("picked")
        entry = catalog_by_id.get(relic_id)
        if not entry or entry.get("tier") != "Ancient":
            raise ValueError(f"row relic not an Ancient catalog relic: {relic_id}")
        if row.get("zh") != entry.get("name"):
            raise ValueError(
                f"row zh mismatch for {relic_id}: {row.get('zh')!r} vs "
                f"{entry.get('name')!r}"
            )
        if owner_by_relic.get(relic_id) != npc_id:
            raise ValueError(
                f"row npc mismatch for {relic_id}: {npc_id!r} owner "
                f"{owner_by_relic.get(relic_id)!r}"
            )
        page_path = pages_dir / f"{slug}.html"
        if not page_path.exists():
            raise ValueError(f"missing cached page: {page_path}")
        fresh = {
            cell["act"]: cell
            for cell in parse_untapped_ancient_choice_page(
                page_path.read_text(encoding="utf-8")
            )
        }
        cell = fresh.get(act)
        if cell is None or cell.get("low_data"):
            raise ValueError(f"fresh parse lacks data for {slug} act {act}")
        if cell["offered_count"] != offered or cell["picked_rate"] != picked:
            raise ValueError(
                f"fresh parse mismatch for {slug} act {act}: page says "
                f"{cell['offered_count']}/{cell['picked_rate']} but row says "
                f"{offered}/{picked}"
            )
        cached_cells = {
            cached["act"]: cached
            for cached in (parsed_cache.get(slug) or {}).get("rows") or []
        }
        cached = cached_cells.get(act)
        if (
            cached is None
            or cached.get("offered") != offered
            or cached.get("picked_pct") != picked
        ):
            raise ValueError(
                f"parsed cache mismatch for {slug} act {act}: "
                f"{json.dumps(cached, ensure_ascii=False)}"
            )
        normalized.append(
            {
                "relic_id": relic_id,
                "npc_id": npc_id,
                "act": int(act),
                "offered_count": int(offered),
                "picked_rate": int(picked),
            }
        )
        if slug not in used_slugs:
            used_slugs.append(slug)

    relic_names_zh = {
        str(entry["id"]): str(entry["name"]) for entry in catalog
    }
    collected_from = [SPIRE_CODEX_ANCIENT_POOLS_URL] + [
        UNTAPPED_PAGE_URL.format(slug=slug) for slug in sorted(used_slugs)
    ]
    snapshot = build_sts2_ancient_choice_snapshot(
        normalized,
        collected_at=_utc_now(),
        relic_names_zh=relic_names_zh,
        npc_names_zh=npc_names_zh,
        collected_from=collected_from,
    )
    validate_sts2_ancient_choice_snapshot(snapshot)
    write_snapshot(output_path, snapshot)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    snapshot = generate_snapshot(args.cache_dir, args.catalog, args.output)
    choice = snapshot["ancient_choice"]
    contexts = choice["contexts"]
    offers = sorted(context["offered_count"] for context in contexts)
    cohorts: dict[tuple[str, int], int] = {}
    for context in contexts:
        key = (context["npc_id"], context["act"])
        cohorts[key] = cohorts.get(key, 0) + 1
    print("contexts={} rankable={} invalid={}".format(
        len(contexts),
        snapshot["scope"]["rankable_contexts"],
        sum(1 for c in contexts if c["invalid_for_ranking"]),
    ))
    print("offered min={} median={} max={}".format(
        offers[0], statistics.median(offers), offers[-1]
    ))
    for npc_id, act in sorted(cohorts, key=lambda item: (item[1], item[0])):
        zh = choice["npc_names_zh"].get(npc_id)
        print(f"cohort {npc_id} ({zh}) x act {act}: {cohorts[(npc_id, act)]}")
    print("npc_localization_unresolved={}".format(
        len(snapshot.get("unresolved_localization") or [])
    ))
    print(f"collected_at={snapshot['collected_at']}")
    print(f"wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
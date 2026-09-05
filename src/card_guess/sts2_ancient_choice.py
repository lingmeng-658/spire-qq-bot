"""STS2 Ancient offer-to-pick decision statistics (core data layer).

Development-time aggregation that turns two local assets into a runtime
snapshot:

- Spire Codex ``/api/ancient-pools`` payloads define the Ancient NPCs, their
  relic pools and per-relic conditions.  Pools are the source for the
  ``relic -> NPC`` mapping (multi-NPC relics are reported by the audit, never
  guessed).
- Untapped relic pages ("Ancient Choice Stats") provide per-act ``offered``
  counts and picked percentages for each pool relic.  Pages are parsed into
  act cells; cells with no data (``low_data``) mean "no usable decision
  data", which is recorded as absence, never as a 0% rate.

Comparison cohort policy (mirrors AGENTS.md):

- A ranking cohort is exactly one ``(npc_id, act)`` context set.  Acts are
  never mixed inside one cohort or one leaderboard.
- Rows sort by ``picked_rate`` descending; equal rates break on the larger
  ``offered_count`` and finally on ``relic_id`` for a stable total order.
- Rank is a competition rank over ``picked_rate`` only: equal rates share
  the same rank and later ranks skip the consumed numbers.  The offered /
  relic_id tie-break only stabilizes output order, it never changes ranks.
- ``offered_count`` below ``ANCIENT_CHOICE_MIN_OFFERED`` is a low-sample row:
  the context is kept with ``invalid_for_ranking`` and ``rank: null`` and is
  excluded from public boards.  The threshold is locked by tests and was
  chosen after measuring the real offered distribution (observed min ~3000,
  median ~32000; see sample_policy in the generated artifact).

Localization policy:

- NPC display names and relic display names are the official Simplified
  Chinese names from the official game text dump.  When an NPC zh name is not
  resolved the data layer keeps the English ``npc_id`` and flags the context
  with ``unresolved_localization``; renderers must never invent or leak a
  translated name.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# Low-sample guard for public ranking.  Data basis: every real choice row
# observed so far has offered_count >= 3000 (min 3000 / median 32000 / max
# 130000), so 1000 leaves a wide margin for Untapped rounding while still
# excluding genuinely tiny cohorts (test fixture uses 500).
ANCIENT_CHOICE_MIN_OFFERED = 1000

SCHEMA_VERSION = "1.0.0"
GAME = "sts2"
SOURCE_NAME = "untapped.gg"
DATASET_ID = "sts2_ancient_choice"
SPIRE_CODEX_ANCIENT_POOLS_URL = "https://spire-codex.com/api/ancient-pools"

ACT_ZH = {1: "第一幕", 2: "第二幕", 3: "第三幕"}
_VALID_ACTS = frozenset(ACT_ZH)

# Official Simplified Chinese names from the official STS2 zh text dump
# (audited against spire-archive; see scripts/sts2_ancient_choice_stats.py).
OFFICIAL_ANCIENT_NPC_ZH = {
    "DARV": "达弗",
    "NEOW": "涅奥",
    "NONUPEIPE": "诺奴佩普",
    "OROBAS": "欧洛巴斯",
    "PAEL": "佩尔",
    "TANX": "坦克斯",
    "TEZCATARA": "特兹卡塔拉",
    "VAKUU": "瓦库",
}


def _fail(message: str) -> None:
    raise ValueError(message)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{path} must be a mapping")
    return dict(value)


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{path} must be a non-empty string")
    return value


def parse_pool_act_restrictions(condition: str | None) -> frozenset[int] | None:
    """Return the act set implied by a pool condition, or ``None``.

    Understands the act-restriction idioms found in Spire Codex ancient pool
    conditions ("Act 2 only", "Act 1-2 only", "Act 2+"); modifiers such as
    "50% chance (vs ...)" or "Excluded with Draft modifier" are ignored and
    return ``None`` when they carry no act restriction.
    """
    if not isinstance(condition, str) or not condition.strip():
        return None
    text = re.sub(r"\s+", " ", condition.strip())
    lowered = text.lower()
    match = re.search(r"\bact\s*(\d)\s*[-–—]\s*(\d)\b", lowered)
    if match is not None:
        start, end = int(match.group(1)), int(match.group(2))
        if start < 1 or end > 3 or start > end:
            return None
        return frozenset(range(start, end + 1))
    match = re.search(r"\bact\s*(\d)\s*\+", lowered)
    if match is not None:
        start = int(match.group(1))
        if start < 1 or start > 3:
            return None
        return frozenset(range(start, 4))
    match = re.search(r"\bact\s*(\d)\b", lowered)
    if match is None:
        return None
    act = int(match.group(1))
    if act not in _VALID_ACTS:
        return None
    return frozenset({act})


_CELL_DIV_OPENING = re.compile(
    r'(?=<div\b[^>]*\bclass="[^"]*__cell[^"]*"[^>]*>)'
)
_CELL_AT_START = re.compile(r'^<div\b[^>]*\bclass="[^"]*__cell[^"]*"[^>]*>')
_LABEL_ACT = re.compile(r"in\s+act\s*([123])", re.IGNORECASE)
_OFFERED_COUNT = re.compile(r"offered\s+([\d,]+)\s+times", re.IGNORECASE)
_PICKED_RATE = re.compile(r"Picked</span>\s*<strong[^>]*>\s*(\d{1,3})\s*%", re.IGNORECASE)


def _strip_html_comments(segment: str) -> str:
    return re.sub(r"<!--.*?-->", "", segment, flags=re.DOTALL)


def parse_untapped_ancient_choice_page(html: str) -> list[dict[str, Any]]:
    """Parse the "Ancient Choice" act cells out of an Untapped relic page.

    Returns one dict per act cell, in document order, with keys ``act``,
    ``offered_count``, ``picked_rate`` and ``low_data``.  Skeleton/loading
    cells (``__skeleton``) are ignored; a cell that exists but carries no
    numbers is reported with ``low_data: True`` and null counts so callers
    can distinguish "no data" from 0%.
    """
    if not isinstance(html, str):
        return []
    rows: list[dict[str, Any]] = []
    seen_acts: set[int] = set()
    sections = re.finditer(r"(?is)<section[^>]*>(.*?)</section>", html)
    for section in sections:
        body = section.group(1)
        if "ancient choice" not in body[:2000].lower():
            continue
        for piece in _CELL_DIV_OPENING.split(body):
            if _CELL_AT_START.match(piece) is None:
                continue
            opening = piece[:200]
            if "__skeleton" in opening:
                continue
            label = _LABEL_ACT.search(piece)
            if label is None:
                continue
            act = int(label.group(1))
            if act in seen_acts:
                continue
            cleaned = _strip_html_comments(piece)
            offered_match = _OFFERED_COUNT.search(cleaned)
            rate_match = _PICKED_RATE.search(cleaned)
            if offered_match is not None and rate_match is not None:
                seen_acts.add(act)
                rows.append(
                    {
                        "act": act,
                        "offered_count": int(offered_match.group(1).replace(",", "")),
                        "picked_rate": int(rate_match.group(1)),
                        "low_data": False,
                    }
                )
                continue
            if "__lowData" in piece:
                seen_acts.add(act)
                rows.append(
                    {
                        "act": act,
                        "offered_count": None,
                        "picked_rate": None,
                        "low_data": True,
                    }
                )
    return rows


def _pool_npc_ids(pools: Iterable[Mapping[str, Any]]) -> list[str]:
    npc_ids: list[str] = []
    for npc in pools:
        npc_id = str(npc.get("id") or "").strip()
        if npc_id:
            npc_ids.append(npc_id)
    return npc_ids


def audit_ancient_pool_mapping(
    pools: Iterable[Mapping[str, Any]],
    ancient_relic_ids: Iterable[str],
    npc_name_zh: Mapping[str, str | None] | None = None,
) -> dict[str, Any]:
    """Audit relic -> NPC / act mapping quality over ancient pools.

    Reports how many pool relic ids exist, how many Ancient relics map to a
    single NPC, and separates multi-NPC relics, relics missing from the pools
    and unresolved NPC localizations.  All id lists are sorted for stable
    output.  If the mapping were widely ambiguous this audit is the signal to
    stop building leaderboards.
    """
    zh_names = dict(npc_name_zh or {})
    per_npc: dict[str, set[str]] = {}
    npc_ids: list[str] = []
    for npc in pools:
        npc_id = str(npc.get("id") or "").strip()
        if not npc_id:
            continue
        if npc_id not in per_npc:
            npc_ids.append(npc_id)
        holder = per_npc.setdefault(npc_id, set())
        for pool in npc.get("pools") or []:
            for relic in pool.get("relics") or []:
                relic_id = str(relic.get("id") or "").strip()
                if relic_id:
                    holder.add(relic_id)

    pool_ids = {relic_id for holder in per_npc.values() for relic_id in holder}
    ancient = {str(relic_id).strip() for relic_id in ancient_relic_ids}
    ancient.discard("")

    multi_npc = sorted(
        relic_id
        for relic_id in pool_ids
        if sum(relic_id in holder for holder in per_npc.values()) > 1
    )
    relic_to_npc: dict[str, str] = {}
    for relic_id in sorted(ancient & pool_ids):
        owners = [
            npc_id for npc_id, holder in per_npc.items() if relic_id in holder
        ]
        if len(owners) == 1:
            relic_to_npc[relic_id] = owners[0]
    localization_unresolved = [
        npc_id for npc_id in npc_ids if not zh_names.get(npc_id)
    ]
    return {
        "total_pool_relic_ids": len(pool_ids),
        "npc_count": len(npc_ids),
        "relic_to_npc": relic_to_npc,
        "multi_npc": multi_npc,
        "missing_from_pools": sorted(ancient - pool_ids),
        "unresolved_relic_ids": sorted(
            relic_id
            for relic_id in ancient & pool_ids
            if relic_id not in relic_to_npc and relic_id not in multi_npc
        ),
        "npc_localization_unresolved": localization_unresolved,
    }


def _row_context(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        _fail("choice row must be a mapping")
    relic_id = str(row.get("relic_id") or "").strip()
    if not relic_id:
        _fail("choice row requires relic_id")
    npc_id = str(row.get("npc_id") or "").strip()
    if not npc_id:
        _fail(f"choice row for {relic_id} requires npc_id")
    act = row.get("act")
    if isinstance(act, bool) or not isinstance(act, int) or act not in _VALID_ACTS:
        _fail(f"invalid act {act!r} for {relic_id}")
    offered = row.get("offered_count")
    if isinstance(offered, bool) or not isinstance(offered, int) or offered < 0:
        _fail(f"offered_count must be a non-negative integer for {relic_id}")
    picked = row.get("picked_rate")
    if isinstance(picked, bool) or not isinstance(picked, int):
        _fail(f"picked_rate must be an integer for {relic_id}")
    if picked < 0 or picked > 100:
        _fail(f"picked_rate out of range for {relic_id}")
    return {
        "relic_id": relic_id,
        "npc_id": npc_id,
        "act": act,
        "offered_count": offered,
        "picked_rate": picked,
    }


def _rank_key(context: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        -int(context["picked_rate"]),
        -int(context["offered_count"]),
        str(context["relic_id"]),
    )


def build_sts2_ancient_choice_snapshot(
    rows: Iterable[Mapping[str, Any]],
    *,
    collected_at: str,
    relic_names_zh: Mapping[str, str],
    npc_names_zh: Mapping[str, str | None] | None = None,
    collected_from: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the runtime ``ancient_choice`` snapshot.

    ``rows`` are choice contexts (relic id, NPC id, act, offered count and
    picked percent).  Ranking happens per ``(npc_id, act)`` cohort; duplicate
    contexts raise, every relic must have an official zh name, and NPCs
    without a resolved zh name stay flagged instead of guessed.
    """
    relic_zh = {str(key): str(value) for key, value in dict(relic_names_zh).items()}
    npc_zh_input = dict(npc_names_zh or {})

    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    npc_order: list[str] = []
    for row in rows:
        context = _row_context(row)
        key = (context["relic_id"], context["npc_id"], context["act"])
        if key in seen:
            _fail(f"duplicate context for {context['relic_id']} / {context['npc_id']} act {context['act']}")
        seen.add(key)
        relic_id = context["relic_id"]
        if relic_id not in relic_zh or not relic_zh[relic_id]:
            _fail(f"relic zh name unresolved for {relic_id}")
        if context["npc_id"] not in npc_order:
            npc_order.append(context["npc_id"])
        normalized.append(context)

    cohorts: dict[tuple[str, int], list[dict[str, Any]]] = {}
    cohort_order: list[tuple[str, int]] = []
    for context in normalized:
        key = (context["npc_id"], context["act"])
        if key not in cohorts:
            cohort_order.append(key)
        cohorts.setdefault(key, []).append(context)

    unresolved: list[dict[str, str]] = []
    contexts: list[dict[str, Any]] = []
    for key in cohort_order:
        cohort = sorted(cohorts[key], key=_rank_key)
        rankable = [
            item
            for item in cohort
            if item["offered_count"] >= ANCIENT_CHOICE_MIN_OFFERED
        ]
        cohort_size = len(rankable)
        rank_by_id: dict[str, int] = {}
        previous_rate: int | None = None
        for index, item in enumerate(rankable, start=1):
            rate = int(item["picked_rate"])
            if rate != previous_rate:
                previous_rate = rate
                expected_rank = index
            rank_by_id[item["relic_id"]] = expected_rank
        for item in sorted(cohort, key=_rank_key):
            npc_id = item["npc_id"]
            zh_value = npc_zh_input.get(npc_id)
            npc_zh_name = zh_value if isinstance(zh_value, str) and zh_value else None
            if npc_zh_name is None:
                entry = {"npc_id": npc_id, "reason": "npc_zh_name_unresolved"}
                if entry not in unresolved:
                    unresolved.append(entry)
            rank = rank_by_id.get(item["relic_id"])
            contexts.append(
                {
                    "relic_id": item["relic_id"],
                    "npc_id": npc_id,
                    "npc_name_zh": npc_zh_name,
                    "act": item["act"],
                    "offered_count": item["offered_count"],
                    "picked_rate": item["picked_rate"],
                    "rank": rank,
                    "cohort_size": cohort_size,
                    "invalid_for_ranking": rank is None,
                }
            )

    npc_names_zh: dict[str, str | None] = {}
    for npc_id in npc_order:
        zh_value = npc_zh_input.get(npc_id)
        npc_names_zh[npc_id] = zh_value if isinstance(zh_value, str) and zh_value else None

    used_relics = {
        context["relic_id"] for context in contexts
    }
    relic_names_zh_out = {
        relic_id: relic_zh[relic_id]
        for relic_id in sorted(used_relics)
        if relic_zh.get(relic_id)
    }
    scope_npc_acts: dict[str, list[int]] = {}
    for npc_id, act in cohort_order:
        scope_npc_acts.setdefault(npc_id, []).append(act)

    return {
        "schema_version": SCHEMA_VERSION,
        "game": GAME,
        "collected_at": collected_at,
        "source": SOURCE_NAME,
        "dataset": {"id": DATASET_ID},
        "collected_from": sorted(collected_from),
        "sample_policy": {
            "minimum_offered": ANCIENT_CHOICE_MIN_OFFERED,
        },
        "scope": {
            "total_contexts": len(contexts),
            "rankable_contexts": sum(1 for c in contexts if not c["invalid_for_ranking"]),
            "npc_acts": {
                npc_id: sorted(acts) for npc_id, acts in scope_npc_acts.items()
            },
        },
        "ancient_choice": {
            "contexts": contexts,
            "npc_names_zh": npc_names_zh,
            "relic_names_zh": relic_names_zh_out,
        },
        "unresolved_localization": unresolved,
    }


def _snapshot_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{path} must be a mapping")
    return value


def validate_sts2_ancient_choice_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Validate a built or persisted ancient_choice snapshot."""
    if not isinstance(snapshot, Mapping):
        _fail("snapshot must be a mapping")
    if snapshot.get("game") != GAME:
        _fail("snapshot game must be sts2")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        _fail("snapshot schema_version mismatch")
    choice = snapshot.get("ancient_choice")
    choice = _snapshot_mapping(choice, "ancient_choice")
    contexts = choice.get("contexts")
    if not isinstance(contexts, list):
        _fail("ancient_choice.contexts must be a list")

    cohort_counts: dict[tuple[str, int], int] = {}
    seen: set[tuple[str, str, int]] = set()
    for context in contexts:
        if not isinstance(context, Mapping):
            _fail("ancient_choice context must be a mapping")
        relic_id = _string(context.get("relic_id"), "context.relic_id")
        npc_id = _string(context.get("npc_id"), "context.npc_id")
        act = context.get("act")
        if isinstance(act, bool) or not isinstance(act, int) or act not in _VALID_ACTS:
            _fail(f"invalid act {act!r} in context for {relic_id}")
        key = (relic_id, npc_id, act)
        if key in seen:
            _fail(f"duplicate context in snapshot for {relic_id}")
        seen.add(key)
        offered = context.get("offered_count")
        if isinstance(offered, bool) or not isinstance(offered, int) or offered < 0:
            _fail(f"invalid offered_count for {relic_id}")
        invalid = bool(context.get("invalid_for_ranking"))
        rank = context.get("rank")
        cohort_counts[(npc_id, act)] = cohort_counts.get((npc_id, act), 0) + 1
        if invalid:
            if rank is not None:
                _fail(f"invalid_for_ranking context must have null rank: {relic_id}")
        else:
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
                _fail(f"rankable context requires a positive rank: {relic_id}")

    # Per cohort: cohort_size on every member must equal the rankable count
    # and stored ranks must match competition ranking over picked_rate:
    # equal rates share the earlier rank, later ranks skip used numbers.
    cohort_rankable: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for context in contexts:
        npc_id, act = context["npc_id"], context["act"]
        key = (npc_id, act)
        if not context.get("invalid_for_ranking"):
            cohort_rankable.setdefault(key, []).append(context)
        cohort_size = context.get("cohort_size")
        if isinstance(cohort_size, bool) or not isinstance(cohort_size, int):
            _fail(f"invalid cohort_size for {context['relic_id']}")
    for key, rankable in cohort_rankable.items():
        previous_rate: int | None = None
        for index, item in enumerate(sorted(rankable, key=_rank_key), start=1):
            rate = int(item["picked_rate"])
            if rate != previous_rate:
                previous_rate = rate
                expected_rank = index
            if int(item["rank"]) != expected_rank:
                _fail(
                    f"rank {item['rank']} does not match competition ranking "
                    f"for {item['relic_id']} in cohort {key}"
                )
    for context in contexts:
        key = (context["npc_id"], context["act"])
        rankable_count = len(cohort_rankable.get(key, []))
        if context.get("cohort_size") != rankable_count:
            _fail(f"cohort_size mismatch for {context['relic_id']}")


def leaderboard_contexts(
    snapshot: Mapping[str, Any], npc_id: str, act: int
) -> list[dict[str, Any]]:
    """Return the rankable contexts of one NPC x act cohort, by rank."""
    if not isinstance(snapshot, Mapping):
        return []
    choice = snapshot.get("ancient_choice")
    if not isinstance(choice, Mapping):
        return []
    result = [
        context
        for context in choice.get("contexts") or []
        if isinstance(context, Mapping)
        and context.get("npc_id") == npc_id
        and context.get("act") == act
        and not context.get("invalid_for_ranking")
    ]
    return sorted(result, key=lambda context: int(context["rank"]))


def leaderboard_npc_acts(snapshot: Mapping[str, Any], npc_id: str) -> tuple[int, ...]:
    """Return the acts that have rankable contexts for ``npc_id``."""
    if not isinstance(snapshot, Mapping):
        return ()
    choice = snapshot.get("ancient_choice")
    if not isinstance(choice, Mapping):
        return ()
    acts = {
        int(context["act"])
        for context in choice.get("contexts") or []
        if isinstance(context, Mapping)
        and context.get("npc_id") == npc_id
        and not context.get("invalid_for_ranking")
    }
    return tuple(sorted(acts))


def npc_name_zh_for(snapshot: Mapping[str, Any], npc_id: str) -> str | None:
    """Return the official zh NPC name, or None when unresolved/unknown."""
    if not isinstance(snapshot, Mapping):
        return None
    choice = snapshot.get("ancient_choice")
    if not isinstance(choice, Mapping):
        return None
    names = choice.get("npc_names_zh")
    if not isinstance(names, Mapping):
        return None
    value = names.get(npc_id)
    if isinstance(value, str) and value:
        return value
    return None


def rankable_contexts_for_relic(
    snapshot: Mapping[str, Any], relic_id: str
) -> list[dict[str, Any]]:
    """Return rankable choice contexts for one relic, ordered by act."""
    if not isinstance(snapshot, Mapping):
        return []
    choice = snapshot.get("ancient_choice")
    if not isinstance(choice, Mapping):
        return []
    result = [
        context
        for context in choice.get("contexts") or []
        if isinstance(context, Mapping)
        and context.get("relic_id") == relic_id
        and not context.get("invalid_for_ranking")
    ]
    return sorted(
        result,
        key=lambda context: (str(context.get("npc_id") or ""), int(context["act"])),
    )
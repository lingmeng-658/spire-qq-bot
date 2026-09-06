"""STS1/STS2 Top-10 leaderboards (pick-rate and win-delta boards only).

Two metrics are supported: 抓取 (pick rate) and 胜率 (win delta), each either
global (``act=None``) or act-scoped (1/2/3).  STS1 has validated whole-run
global statistics (``pick_rate`` / ``win_delta`` over floors 1-50); STS2 has
no reliable global scope, so global boards are only reachable for STS1.
Terminal-deck (终局) leaderboards are retired on both generations, while the
underlying final-deck data in the snapshots is untouched.

Ranking/sorting logic is independent from QQ copy; missing values are
skipped, never zero-filled.  STS2 snapshots are normalised through the
existing ``card_stats.adapt_sts2_snapshot`` adapter instead of re-parsing the
legacy shape.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from card_guess.card_stats import adapt_sts2_snapshot
from card_guess.cards import load_cards
from card_guess.puzzle import POOL_NAMES
from card_guess.qq.sessions import resolve_character
from card_guess.sts1_card_stats import SOURCE_ID as STS1_SOURCE_ID, character_pick_act_rows
from card_guess.sts1_snapshot import COHORT_ASC7PLUS

REPO_ROOT = Path(__file__).resolve().parents[2]
STS1_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts1_card_stats.json"
STS2_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_card_stats.json"

STS1_ASC7PLUS_SOURCE_ID = f"{STS1_SOURCE_ID}_{COHORT_ASC7PLUS.key}"
STS2_MAIN_SOURCE_ID = "untapped"

GAME_LABELS = {"sts1": "STS1", "sts2": "STS2"}
TOP_LIMIT = 10
WIN_DELTA_MIN_COHORT = 30

LEADERBOARD_KEYWORDS = ("抓取", "胜率", "心脏")
# keyword -> (whole-run metric name, per-act metric name)
METRIC_NAMES = {
    "抓取": ("pick_rate", "act_pick_rate"),
    "胜率": ("win_delta", "act_win_delta"),
    "心脏": ("heart_win_deck_presence_rate", None),
}
ACT_LABELS = {
    1: "第一幕",
    2: "第二幕",
    3: "第三幕",
}
STS2_GLOBAL_NOTICE = "STS2 暂无可靠的全局统计口径，请指定 1/2/3 幕。"

CHARACTER_POOLS = {
    "sts1": ("ironclad", "silent", "defect", "watcher"),
    "sts2": ("ironclad", "silent", "defect", "necrobinder", "regent"),
}


def pool_generations(pool: str) -> tuple[str, ...]:
    """Generations whose character pool contains ``pool`` (order sts1, sts2)."""
    return tuple(
        game for game, pools in CHARACTER_POOLS.items() if pool in pools
    )


def keyword_heading(keyword: str, act: int | None = None) -> str:
    """Heading metric label: 全局 for ``act=None``, otherwise per-act."""
    if keyword not in LEADERBOARD_KEYWORDS:
        raise ValueError(f"unsupported leaderboard keyword: {keyword!r}")
    if keyword == "心脏":
        if act is not None:
            raise ValueError("heart board has no act scope")
        return "心脏胜利卡组"
    suffix = "抓取率" if keyword == "抓取" else "胜率差"
    if act in ACT_LABELS:
        return f"{ACT_LABELS[act]}{suffix}"
    return f"全局{suffix}"


def parse_leaderboard_keyword(keyword) -> tuple[str, int | None] | None:
    """Parse a leaderboard keyword.

    A bare 抓取/胜率 means the global board (``act=None``); an explicit
    1/2/3 suffix means the per-act board.  终局 and anything else are no
    longer supported and return ``None``.
    """
    if not isinstance(keyword, str):
        return None
    match = re.fullmatch(r"(抓取|胜率)([123])?", keyword)
    if match is None:
        return None
    suffix = match.group(2)
    return (match.group(1), int(suffix) if suffix else None)


def is_win_delta_eligible(metric) -> bool:
    """STS1 win-delta reliability filter (renderer + win leaderboard).

    A board value may only be shown when both run-level cohorts are large
    enough: ``denominator >= WIN_DELTA_MIN_COHORT`` and
    ``comparison_denominator >= WIN_DELTA_MIN_COHORT``.  The total
    ``sample_size`` is never a substitute for the two cohort denominators.
    """
    if not isinstance(metric, dict):
        return False
    picked = metric.get("denominator")
    comparison = metric.get("comparison_denominator")
    if isinstance(picked, bool) or not isinstance(picked, int) or picked < WIN_DELTA_MIN_COHORT:
        return False
    if (
        isinstance(comparison, bool)
        or not isinstance(comparison, int)
        or comparison < WIN_DELTA_MIN_COHORT
    ):
        return False
    return True


@dataclass(frozen=True)
class RankedCard:
    rank: int
    card_id: str
    name: str
    pool: str
    value: float


def _load_unified_snapshot(game: str) -> dict[str, Any]:
    """Load a unified snapshot for one game (``{}`` on any failure)."""
    if game == "sts1":
        try:
            with open(STS1_STATS_SNAPSHOT, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}
    if game == "sts2":
        try:
            with open(STS2_STATS_SNAPSHOT, encoding="utf-8") as handle:
                raw = json.load(handle)
            return adapt_sts2_snapshot(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            return {}
    return {}


def _source_id(game: str) -> str:
    if game == "sts1":
        return STS1_ASC7PLUS_SOURCE_ID
    return STS2_MAIN_SOURCE_ID


def _metric_number(metric: Any) -> float | None:
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _card_value(
    entry: Mapping[str, Any],
    game: str,
    keyword: str,
    act: int | None,
) -> float | None:
    metrics = entry.get("metrics")
    if not isinstance(metrics, dict):
        return None
    source = metrics.get(_source_id(game))
    if not isinstance(source, dict):
        return None
    if act is None:
        metric = source.get(METRIC_NAMES[keyword][0])
        if keyword == "胜率" and game == "sts1" and not is_win_delta_eligible(metric):
            return None
        return _metric_number(metric)
    acts = source.get(METRIC_NAMES[keyword][1])
    if not isinstance(acts, dict):
        return None
    act_key = f"act_{act}"
    if keyword == "胜率" and game == "sts1":
        if not is_win_delta_eligible(acts.get(act_key)):
            return None
    return _metric_number(acts.get(act_key))


def build_rankings(
    game: str,
    keyword: str,
    *,
    role_pool: str | None = None,
    cards: Iterable[Mapping[str, Any]] | None = None,
    unified: Mapping[str, Any] | None = None,
    limit: int = TOP_LIMIT,
    act: int | None = None,
) -> list[RankedCard]:
    """Rank cards descending by the requested metric; missing values skipped.

    ``act=None`` requests the whole-run global board (STS1 only); STS2 has no
    reliable global metric and raises for ``act=None``.
    """
    if game not in GAME_LABELS:
        raise ValueError(f"unsupported game: {game!r}")
    if keyword not in LEADERBOARD_KEYWORDS:
        raise ValueError(f"unsupported leaderboard keyword: {keyword!r}")
    if keyword == "心脏" and act is not None:
        raise ValueError("heart board has no act scope")
    if limit < 1:
        raise ValueError("limit must be positive")
    if act is not None:
        if isinstance(act, bool) or not isinstance(act, int) or act not in ACT_LABELS:
            raise ValueError("act must be one of 1, 2, 3 or None for pick/win boards")
    if act is None and game == "sts2":
        raise ValueError(STS2_GLOBAL_NOTICE)

    if cards is None:
        cards = load_cards(game)
    if unified is None:
        unified = _load_unified_snapshot(game)

    card_stats = unified.get("cards")
    if not isinstance(card_stats, dict):
        card_stats = {}

    allowed_pools = CHARACTER_POOLS[game]
    scored: list[tuple[float, str, str, str]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        pool = card.get("pool")
        if pool not in allowed_pools:
            continue
        if role_pool is not None and pool != role_pool:
            continue
        if keyword == "心脏" and card.get("rarity") == "Basic":
            # Heart board ranks post-starter builds; starter cards (rarity
            # "Basic") stay fully in the snapshot and single-card stats.
            continue
        entry = card_stats.get(str(card.get("id") or ""))
        if not isinstance(entry, dict):
            continue
        value = _card_value(entry, game, keyword, act)
        if value is None:
            continue
        scored.append(
            (
                value,
                str(card.get("id") or ""),
                str(card.get("name") or ""),
                str(pool),
            )
        )

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        RankedCard(
            rank=index,
            card_id=card_id,
            name=name,
            pool=pool,
            value=value,
        )
        for index, (value, card_id, name, pool) in enumerate(scored[:limit], start=1)
    ]


def _value_text(keyword: str, value: float) -> str:
    if keyword == "抓取":
        return f"{value:.1f}%"
    if keyword == "心脏":
        return f"{value:.2f}%"
    return f"{value:+.1f} 个百分点"


def format_leaderboard_text(
    game: str,
    keyword: str,
    rows: Sequence[RankedCard],
    *,
    role_pool: str | None = None,
    act: int | None = None,
) -> str:
    """Render leaderboard copy; callers decide pool display separately."""
    pool_label = POOL_NAMES.get(role_pool, "") if role_pool else "全部角色"
    heading_label = keyword_heading(keyword, act)
    heading = (
        f"=== {GAME_LABELS[game]} · {pool_label} · "
        f"{heading_label} Top {TOP_LIMIT} ==="
    )
    if not rows:
        return f"{heading}\n（该范围暂无可排名卡牌）"
    lines = [
        f"{row.rank}. {row.name}  {_value_text(keyword, row.value)}"
        for row in rows
    ]
    text = f"{heading}\n" + "\n".join(lines)
    if keyword == "胜率":
        text += f"\n\n注：{heading_label}仅为统计关联，不代表因果关系。"
    return text


def build_leaderboard_reply(
    game_tag: str,
    keyword: str,
    role: str | None = None,
) -> str:
    """Assemble one leaderboard reply (text only) for a QQ command."""
    game = {"1": "sts1", "2": "sts2"}.get(str(game_tag))
    if game is None:
        return "榜单语法：榜单1/2 [角色] 抓取|胜率（可加 1/2/3 幕）\n示例：榜单1 抓取 / 榜单2 猎宝 胜率2"
    if keyword == "终局":
        return "该榜单已取消，请使用抓取/胜率排行。"
    if keyword == "心脏":
        if game == "sts2":
            return "STS2 暂无心脏统计。"
        role_pool = None
        if role:
            try:
                role_pool = resolve_character(role)
            except ValueError:
                return f"无法识别角色“{role}”。"
            if role_pool not in CHARACTER_POOLS[game]:
                return f"榜单暂不支持角色池“{role_pool}”。"
        rows = build_rankings(game, "心脏", role_pool=role_pool)
        return format_leaderboard_text(game, "心脏", rows, role_pool=role_pool)
    parsed = parse_leaderboard_keyword(keyword)
    if parsed is None:
        return (
            "榜单指标需为：抓取 / 胜率（可加 1/2/3 幕）。\n"
            "示例：榜单1 抓取 / 榜单2 猎宝 胜率2"
        )
    board_kind, act = parsed
    if game == "sts2" and act is None:
        return STS2_GLOBAL_NOTICE

    role_pool = None
    if role:
        try:
            role_pool = resolve_character(role)
        except ValueError:
            return f"无法识别角色“{role}”。"
        if role_pool not in CHARACTER_POOLS[game]:
            return f"榜单暂不支持角色池“{role_pool}”。"

    rows = build_rankings(game, board_kind, role_pool=role_pool, act=act)
    return format_leaderboard_text(
        game,
        board_kind,
        rows,
        role_pool=role_pool,
        act=act,
    )
# ---------------------------------------------------------------------------
# STS1 character x layer x rarity card cohort board (main Card rank entry)
# ---------------------------------------------------------------------------
# Fair cohort: character x act(layer) x rarity Card Reward pick decisions.
# Complete cohort only - never a Top N / Bottom N truncation.  Low-sample
# cards are excluded by the shared character_pick_act_rows floor.

CARD_COHORT_ACT_ZH = {1: "第一层", 2: "第二层", 3: "第三层"}
CARD_COHORT_ACT_KEY = {1: "act_1", 2: "act_2", 3: "act_3"}
CARD_COHORT_RARITY_ZH = {"普通": "Common", "罕见": "Uncommon", "稀有": "Rare"}
CARD_COHORT_STS1_CHARACTERS = CHARACTER_POOLS["sts1"]
STS2_CARD_COHORT_NOTICE = "二代目前暂无可靠的同类卡牌排行榜。"


def _card_cohort_character_zh(pool: str) -> str:
    return POOL_NAMES.get(pool, pool or "")


def _card_cohort_rows(
    snapshot: Mapping[str, Any],
    *,
    character: str,
    act: int,
    rarity: str,
) -> list[dict[str, Any]]:
    """Full one-cohort rows decorated with the snapshot's official zh names."""
    rows = character_pick_act_rows(
        snapshot,
        source_id=STS1_ASC7PLUS_SOURCE_ID,
        character=character,
        act=CARD_COHORT_ACT_KEY[act],
        rarity=rarity,
    )
    card_entries = snapshot.get("cards") if isinstance(snapshot, Mapping) else None
    named: list[dict[str, Any]] = []
    for row in rows:
        entry = card_entries.get(row["card_id"]) if isinstance(card_entries, Mapping) else None
        name = entry.get("name") if isinstance(entry, Mapping) else None
        if not isinstance(name, str) or not name.strip():
            continue
        named.append({**row, "name": name.strip()})
    return named


def render_card_layer_prompt(pool: str, act: int) -> str:
    """Layer prompt without guessing a rarity; never returns a mixed board."""
    pool_zh = _card_cohort_character_zh(pool)
    options = "\n".join(f"{pool_zh}{act}{zh}" for zh in ("普通", "罕见", "稀有"))
    return f"{pool_zh} · {CARD_COHORT_ACT_ZH[act]}\n\n请选择稀有度：\n{options}"


def format_card_cohort_board(
    pool: str,
    act: int,
    rarity_zh: str,
    rows: Sequence[Mapping[str, Any]],
) -> str:
    """Render the complete cohort board (real ranks, player-facing copy)."""
    heading = (
        f"{_card_cohort_character_zh(pool)} · {CARD_COHORT_ACT_ZH[act]}"
        f" · {rarity_zh}卡选择率排行"
    )
    if not rows:
        return f"{heading}\n（该范围暂无可排名的卡牌）"
    lines = "\n".join(
        f"{row['rank']}. {row['name']} —— {row['pick_rate'] * 100:.1f}%"
        for row in rows
    )
    return f"{heading}\n{lines}"


def render_card_layer_cohort_board(alias: str, act: int, rarity_zh: str | None = None) -> str:
    """One reply for the 角色+层+稀有度 Card cohort entry (STS1 main board).

    STS2-only pools and special pools never fabricate a ranking; unknown
    rarities fall back to the layer rarity prompt.
    """
    try:
        pool = resolve_character(alias)
    except ValueError:
        return f"无法识别角色“{alias}”。"
    if pool in CHARACTER_POOLS["sts2"] and pool not in CARD_COHORT_STS1_CHARACTERS:
        return STS2_CARD_COHORT_NOTICE
    if pool not in CARD_COHORT_STS1_CHARACTERS:
        return f"{_card_cohort_character_zh(pool)}暂不参与卡牌同稀有度排行。"
    if rarity_zh is None or rarity_zh not in CARD_COHORT_RARITY_ZH:
        return render_card_layer_prompt(pool, act)
    rarity = CARD_COHORT_RARITY_ZH[rarity_zh]
    snapshot = _load_unified_snapshot("sts1")
    rows = _card_cohort_rows(snapshot, character=pool, act=act, rarity=rarity)
    return format_card_cohort_board(pool, act, rarity_zh, rows)

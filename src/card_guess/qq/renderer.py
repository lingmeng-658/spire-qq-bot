from __future__ import annotations

import json
import math
import re
from pathlib import Path

from card_guess.cards import (
    format_cost,
    format_star_cost,
    render_description,
    render_sts1_energy,
)
from card_guess.event_entity_links import EventEntityLink, links_for_entity
from card_guess.event_presentation import strip_event_bbcode
from card_guess.events import EventCatalogError, EventRecord, get_event
from card_guess.leaderboard import is_win_delta_eligible
from card_guess.puzzle import format_pool, format_rarity, format_type
from card_guess.relics import load_relics
from card_guess.relic_stats import boss_choice_act_rows, boss_choice_rank_contexts
from card_guess.sts1_card_stats import (
    SOURCE_ID as STS1_SOURCE_ID,
    character_pick_rank_contexts,
)
from card_guess.sts1_snapshot import COHORT_ASC7PLUS
from card_guess.sts2_ancient_choice import (
    OFFICIAL_ANCIENT_NPC_ZH,
    leaderboard_contexts,
    leaderboard_npc_acts,
    rankable_contexts_for_relic,
)
from card_guess.qq.relic_short_summary import short_relic_effect

REPO_ROOT = Path(__file__).resolve().parents[3]
STS1_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts1_card_stats.json"
STS2_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_card_stats.json"
STS1_RELIC_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts1_relic_stats.json"
STS2_RELIC_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_relic_stats.json"
STS2_ANCIENT_CHOICE_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_ancient_choice.json"
STS2_RELIC_SHOP_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_relic_shop_stats.json"
GAME_NAMES = {
    "sts1": "杀戮尖塔 1",
    "sts2": "杀戮尖塔 2",
}
GAME_TAGS = {
    "sts1": "STS1",
    "sts2": "STS2",
}

_sts1_card_stats_cache = None
_sts2_card_stats_cache = None
_sts1_relic_stats_cache = None
_sts2_relic_stats_cache = None
_sts2_ancient_choice_cache = None
_sts2_relic_shop_cache = None

STS1_ASC7PLUS_SOURCE_ID = f"{STS1_SOURCE_ID}_{COHORT_ASC7PLUS.key}"


class RenderedReply(str):
    def __new__(cls, text: str, image_path: Path | None = None, image_paths=None):
        obj = str.__new__(cls, text)
        obj.text = text
        obj.image_path = image_path
        if image_paths is not None:
            obj.image_paths = tuple(image_paths)
        elif image_path is not None:
            obj.image_paths = (image_path,)
        else:
            obj.image_paths = ()
        return obj


def resolve_local_card_image(card):
    if not isinstance(card, dict):
        return None

    game = str(card.get("game") or "").strip()
    card_id = str(card.get("id") or "").strip()

    if not game or not card_id:
        return None

    image_path = REPO_ROOT / "data" / "images" / game / f"{card_id}.png"
    if image_path.exists():
        return image_path

    return None


def resolve_local_upgraded_card_image(card):
    if not isinstance(card, dict):
        return None

    game = str(card.get("game") or "").strip()
    card_id = str(card.get("id") or "").strip()

    if not game or not card_id:
        return None

    image_path = REPO_ROOT / "data" / "images" / game / "upgraded" / f"{card_id}.png"
    if image_path.exists():
        return image_path

    return None


def resolve_local_relic_image(relic):
    """返回遗物本地图片路径；本地无图时返回 None（不触发任何下载）。"""
    if not isinstance(relic, dict):
        return None

    game = str(relic.get("game") or "").strip()
    relic_id = str(relic.get("id") or "").strip()

    if not game or not relic_id:
        return None

    image_path = REPO_ROOT / "data" / "images" / "relics" / game / f"{relic_id}.png"
    if image_path.exists():
        return image_path

    return None


def resolve_local_ancient_npc_image(npc_id):
    """Return the local STS2 Ancient NPC image path or None."""
    key = str(npc_id or "").strip()
    if key not in OFFICIAL_ANCIENT_NPC_ZH:
        return None
    image_path = REPO_ROOT / "data" / "images" / "ancients" / "sts2" / f"{key}.png"
    if image_path.exists():
        return image_path
    return None


def resolve_local_ancient_overview_image():
    """Return the local 8-NPC overview collage path or None."""
    image_path = (
        REPO_ROOT
        / "data"
        / "images"
        / "ancients"
        / "sts2"
        / "ancient_overview.png"
    )
    return image_path if image_path.exists() else None


def render_ancient_npc_overview():
    """Render the concise official-ZH overview of all 8 Ancient NPCs."""
    lines = [name for name in OFFICIAL_ANCIENT_NPC_ZH.values() if name]
    body = "\n".join(lines)
    return (
        "先古遗民\n\n"
        f"{body}\n\n"
        "发送名字可查看对应图片与可查询层。"
    )


def load_sts2_card_stats():
    global _sts2_card_stats_cache
    if _sts2_card_stats_cache is None:
        try:
            with open(STS2_STATS_SNAPSHOT, encoding="utf-8") as f:
                _sts2_card_stats_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts2_card_stats_cache = {}
    return _sts2_card_stats_cache


def load_sts1_card_stats():
    global _sts1_card_stats_cache
    if _sts1_card_stats_cache is None:
        try:
            with open(STS1_STATS_SNAPSHOT, encoding="utf-8") as f:
                _sts1_card_stats_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts1_card_stats_cache = {}
    return _sts1_card_stats_cache


def load_sts1_relic_stats():
    global _sts1_relic_stats_cache
    if _sts1_relic_stats_cache is None:
        try:
            with open(STS1_RELIC_STATS_SNAPSHOT, encoding="utf-8") as f:
                _sts1_relic_stats_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts1_relic_stats_cache = {}
    return _sts1_relic_stats_cache


def load_sts2_relic_stats():
    global _sts2_relic_stats_cache
    if _sts2_relic_stats_cache is None:
        try:
            with open(STS2_RELIC_STATS_SNAPSHOT, encoding="utf-8") as f:
                _sts2_relic_stats_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts2_relic_stats_cache = {}
    return _sts2_relic_stats_cache


def load_sts2_ancient_choice_stats():
    global _sts2_ancient_choice_cache
    if _sts2_ancient_choice_cache is None:
        try:
            with open(STS2_ANCIENT_CHOICE_SNAPSHOT, encoding="utf-8") as f:
                _sts2_ancient_choice_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts2_ancient_choice_cache = {}
    return _sts2_ancient_choice_cache


def load_sts2_relic_shop_stats():
    global _sts2_relic_shop_cache
    if _sts2_relic_shop_cache is None:
        try:
            with open(STS2_RELIC_SHOP_SNAPSHOT, encoding="utf-8") as f:
                _sts2_relic_shop_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts2_relic_shop_cache = {}
    return _sts2_relic_shop_cache


_ACTS = ("act_1", "act_2", "act_3")


def _metric_value(act_data, key):
    if not isinstance(act_data, dict):
        return None
    metric = act_data.get(key)
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value


def _format_metric_row(acts, key, formatter):
    if not isinstance(acts, dict):
        return None
    values = [_metric_value(acts.get(act), key) for act in _ACTS]
    if not any(value is not None for value in values):
        return None
    return " / ".join(formatter(value) if value is not None else "-" for value in values)


def _format_compact_sample_count(value):
    """Compact sample-size text (4000 -> 4k, 7400 -> 7.4k, 860 -> 860)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    if count < 1000:
        return str(count)
    if count % 1000 == 0:
        return f"{count // 1000}k"
    return f"{count / 1000:.1f}k"


def _sts2_win_impact_row(reward):
    """Run-level win-rate impact per act; only card-reward data is used."""
    if not isinstance(reward, dict):
        return None
    cells = []
    for act in _ACTS:
        value = _metric_value(reward.get(act), "run_win_rate_impact")
        if value is None:
            cells.append("-")
        elif value > 0:
            cells.append(f"+{value:.0f}")
        elif value < 0:
            cells.append(f"{value:.0f}")
        else:
            cells.append("0")
    if all(cell == "-" for cell in cells):
        return None
    return f"胜率关联：{' / '.join(cells)} 个百分点"


def _sts2_sample_row(reward):
    """Sample-size row from card-reward pick data; hides when all acts miss."""
    if not isinstance(reward, dict):
        return None
    cells = []
    for act in _ACTS:
        act_data = reward.get(act)
        sample = None
        if isinstance(act_data, dict):
            pick = act_data.get("pick_rate")
            if isinstance(pick, dict):
                sample = _format_compact_sample_count(pick.get("sample_size"))
        cells.append(sample)
    if not any(cell is not None for cell in cells):
        return None
    parts = " / ".join(cell if cell is not None else "-" for cell in cells)
    return f"样本：第一/二/三层 {parts} 次"


def render_sts2_stats(card, snapshot):
    """STS2 default stat rows: reward / shop / smith / run impact / sample."""
    if not isinstance(snapshot, dict):
        return ""
    card_stats = snapshot.get("cards")
    if not isinstance(card_stats, dict):
        return ""
    entry = card_stats.get(str(card.get("id") or ""))
    if not isinstance(entry, dict):
        return ""

    untapped = entry.get("untapped")
    if not isinstance(untapped, dict):
        return ""
    reward = untapped.get("card_reward")
    shop = untapped.get("shop")
    smith = untapped.get("smith")

    rows = []
    pick_row = _format_metric_row(reward, "pick_rate", lambda v: f"{v:.0f}%")
    if pick_row is not None:
        rows.append(f"卡牌奖励：第一/二/三层 {pick_row} 会选")

    purchase_row = _format_metric_row(shop, "purchase_rate", lambda v: f"{v:.0f}%")
    if purchase_row is not None:
        rows.append(f"商店：{purchase_row} 会买")

    upgrade_row = _format_metric_row(smith, "upgrade_rate", lambda v: f"{v:.0f}%")
    if upgrade_row is not None:
        rows.append(f"休息时：{upgrade_row} 会敲牌")

    impact_row = _sts2_win_impact_row(reward)
    if impact_row is not None:
        rows.append(impact_row)

    sample_row = _sts2_sample_row(reward)
    if sample_row is not None:
        rows.append(sample_row)

    return "\n".join(rows)

def _act_row_value(source, name, formatter):
    acts = source.get(name)
    if not isinstance(acts, dict):
        return None
    cells = []
    for act in _ACTS:
        metric = acts.get(act)
        value = None
        if isinstance(metric, dict):
            raw = metric.get("value")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                value = raw
        cells.append(formatter(value) if value is not None else "-")
    return " / ".join(cells)


def _sts1_win_delta_row(source):
    """Act win deltas guarded by the STS1 cohort-size reliability rule."""
    acts = source.get("act_win_delta")
    if not isinstance(acts, dict):
        return None
    cells = []
    for act in _ACTS:
        metric = acts.get(act)
        if not is_win_delta_eligible(metric):
            cells.append("-")
            continue
        raw = metric.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            cells.append("-")
            continue
        cells.append(f"{raw:+.1f}")
    return " / ".join(cells)


def _sts1_same_rarity_rank_row(snapshot, card):
    """Same-rarity selection-rate rank row (rank/cohort per act) or None."""
    if not isinstance(snapshot, dict):
        return None
    card_id = str(card.get("id") or "")
    if not card_id:
        return None
    contexts = character_pick_rank_contexts(
        snapshot,
        source_id=STS1_ASC7PLUS_SOURCE_ID,
        card_id=card_id,
    )
    by_act = {context["act"]: context for context in contexts}
    if not by_act:
        return None
    cells = []
    for act in _ACTS:
        context = by_act.get(act)
        if context is None:
            cells.append("-")
            continue
        cells.append(f"{context['rank']}/{context['cohort_size']}")
    return " · ".join(cells)


_REPICK_MIN_SAMPLE_SIZE = 100


def _scalar_metric_value(source, key):
    """Numeric value from a scalar metric dict, or None."""
    if not isinstance(source, dict):
        return None
    metric = source.get(key)
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _repick_row(source):
    """Second-encounter re-pick sentence, hidden below the sample guard."""
    if not isinstance(source, dict):
        return None
    metric = source.get("repick_rate")
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    sample = metric.get("sample_size")
    if isinstance(sample, bool) or not isinstance(sample, (int, float)):
        return None
    if int(sample) < _REPICK_MIN_SAMPLE_SIZE:
        return None
    return f"再遇到：约{value:.0f}%会再拿一张"


def render_sts1_stats(card, snapshot):
    """STS1 default stat rows for the asc7plus cohort.

    Rows answer decision and descriptive questions players actually ask:
    reward pick rate, same-cohort rank, act win delta, first-choice floor and
    second-encounter re-pick rate.  Terminal / Heart presence stays hidden.
    """
    if not isinstance(snapshot, dict):
        return ""
    card_stats = snapshot.get("cards")
    if not isinstance(card_stats, dict):
        return ""
    entry = card_stats.get(str(card.get("id") or ""))
    if not isinstance(entry, dict):
        return ""
    source = entry.get("metrics", {}).get(STS1_ASC7PLUS_SOURCE_ID)
    if not isinstance(source, dict):
        return ""

    rows = []
    pick_row = _act_row_value(source, "act_pick_rate", lambda v: f"{v:.1f}%")
    if pick_row is not None:
        rows.append(f"卡牌奖励：第一/二/三层 {pick_row} 会选")

    rank_row = _sts1_same_rarity_rank_row(snapshot, card)
    if rank_row is not None:
        rows.append(f"同类排名：{rank_row}")

    delta_row = _sts1_win_delta_row(source)
    if delta_row is not None:
        rows.append(f"胜率关联：{delta_row} 个百分点")

    first_floor = _scalar_metric_value(source, "first_pick_floor_mean")
    if first_floor is not None:
        floor = int(math.floor(float(first_floor) + 0.5))
        rows.append(f"第一次选择：平均第{floor}层左右")

    repick_row = _repick_row(source)
    if repick_row is not None:
        rows.append(repick_row)

    return "\n".join(rows)


STS1_RELIC_ROLE_LABELS = {
    "IRONCLAD": "铁甲",
    "THE_SILENT": "静默",
    "DEFECT": "机器人",
    "WATCHER": "观者",
}

_RELIC_TIER_LABELS = {
    "starter": "初始遗物",
    "common": "普通遗物",
    "uncommon": "罕见遗物",
    "rare": "稀有遗物",
    "boss": "Boss 遗物",
    "shop": "商店遗物",
    "special": "特殊遗物",
    "ancient": "先古遗物",
    "event": "事件遗物",
}


def _relic_tier_display(relic):
    tier = str(relic.get("tier") or "").strip()
    if not tier or tier.lower() == "none":
        return ""
    return _RELIC_TIER_LABELS.get(tier.lower(), tier)


RELIC_ACT_LABELS = (("act1", "第一层"), ("act2", "第二层"))

RELIC_COHORT_ACT_ZH = {1: "第一层", 2: "第二层", 3: "第三层"}


def load_sts1_relic_zh_names():
    """Map every STS1 relic id to its official Chinese catalog name."""
    names = {}
    for relic in load_relics("sts1"):
        relic_id = str(relic.get("id") or "").strip()
        name = str(relic.get("name") or "").strip()
        if relic_id and name:
            names[relic_id] = name
    return names


def _relic_short_summary_map(game):
    """Map local relic ids to short summaries for one game's boards."""
    summaries = {}
    for relic in load_relics(game):
        relic_id = str(relic.get("id") or "").strip()
        description = str(relic.get("description") or "").strip()
        if not relic_id or not description:
            continue
        summary = short_relic_effect(
            description,
            relic_id=relic_id,
            game=game,
        )
        if summary:
            summaries[relic_id] = summary
    return summaries


_LEADERBOARD_ONE_LINE_MAX = 44


def _append_leaderboard_line(lines, base_line, summary):
    """Keep boards scannable by folding only overlong summaries to next line."""
    if not summary:
        lines.append(base_line)
        return
    inline = f"{base_line}｜{summary}"
    if len(inline) <= _LEADERBOARD_ONE_LINE_MAX:
        lines.append(inline)
    else:
        lines.append(base_line)
        lines.append(f"  {summary}")


def render_sts1_boss_leaderboard(act, snapshot=None):
    """Render one STS1 act's complete Boss-relic choice-rate board.

    Reuses ``boss_choice_act_rows`` (competition ranks, low-sample floor, no
    Top N truncation) and never exposes denominator or sample fields.
    """
    if snapshot is None:
        snapshot = load_sts1_relic_stats()
    act_key = {1: "act1", 2: "act2"}.get(act)
    if act_key is None:
        return None
    act_zh = {1: "第一层", 2: "第二层"}[act]
    rows = boss_choice_act_rows(snapshot, act_key)
    names = load_sts1_relic_zh_names()
    summaries = _relic_short_summary_map("sts1")
    lines = [f"{act_zh} Boss 遗物选择率排行"]
    for row in rows:
        name = names.get(str(row.get("relic_id") or ""))
        if not name:
            continue
        summary = summaries.get(str(row.get("relic_id") or ""))
        _append_leaderboard_line(
            lines,
            f"{row['rank']}. {name} —— {row['pick_rate']:.1f}%",
            summary,
        )
    if len(lines) == 1:
        lines.append("（该层暂无可排名的 Boss 遗物）")
    return "\n".join(lines)


def _boss_act_choice_paragraph(context, act_label):
    """Format one rankable act's choice rate together with its same-act rank."""
    return (
        f"{act_label} Boss 奖励：\n"
        f"约{context['pick_rate']:.1f}%会选，"
        f"选择率第 {context['rank']} / {context['cohort_size']}。"
    )


RELIC_DESCRIPTIVE_TIERS = ("common", "uncommon", "rare")
RELIC_ACQUISITION_MIN_COVERAGE_PERCENT = 60.0


def _relic_metric_value(metric):
    """Return a numeric rate value from a snapshot metric dict, or None."""
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _format_relic_percent(value):
    return f"{value:.1f}%"


def _display_floor(value):
    """Round a recorded floor to the nearest integer, half-up (locked by tests)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(math.floor(float(value) + 0.5))


def _final_presence_row(entry):
    """Per-character final-presence sentence in the project role order."""
    supported = entry.get("supported_roles")
    if not isinstance(supported, list):
        return None
    per_character = entry.get("per_character")
    if not isinstance(per_character, dict):
        return None
    cells = []
    for role, label in STS1_RELIC_ROLE_LABELS.items():
        if role not in supported:
            continue
        value = _relic_metric_value(per_character.get(role))
        if value is None:
            continue
        cells.append(f"{label}{_format_relic_percent(value)}")
    if not cells:
        return None
    return "最终携带：" + " · ".join(cells)


def _first_acquisition_row(relic, entry):
    """First-acquisition timing row; requires reliable recorded coverage."""
    tier = str(relic.get("tier") or "").strip().lower()
    if tier not in RELIC_DESCRIPTIVE_TIERS:
        return None
    fa = entry.get("first_acquisition")
    if not isinstance(fa, dict):
        return None
    coverage = _relic_metric_value(fa.get("coverage_rate"))
    if coverage is None or coverage < RELIC_ACQUISITION_MIN_COVERAGE_PERCENT:
        return None
    median = _display_floor(fa.get("median_floor"))
    p25 = _display_floor(fa.get("p25_floor"))
    p75 = _display_floor(fa.get("p75_floor"))
    if median is None or p25 is None or p75 is None:
        return None
    return f"首次获得：通常第{median}层左右，约一半在第{p25}～{p75}层"


def render_relic_stats(relic, snapshot):
    """Render audited STS1 relic stats as natural-language sentences.

    Default QQ output keeps only decision or descriptive value:
    - Boss relics show each act's choice rate together with its same-act rank;
    - Common/Uncommon/Rare relics add first-acquisition timing (when recorded
      coverage is reliable) and per-character final presence;
    - single-role relics keep a plain role-restriction identity note;
    - overall / Heart presence and act-distribution noise stay hidden.
    """
    if not isinstance(snapshot, dict):
        return ""
    relic_stats = snapshot.get("relics")
    if not isinstance(relic_stats, dict):
        return ""
    relic_id = str(relic.get("id") or "")
    entry = relic_stats.get(relic_id)
    if not isinstance(entry, dict):
        return ""

    tier = str(relic.get("tier") or "").strip().lower()
    supported = entry.get("supported_roles")
    supported = (
        [role for role in supported if isinstance(role, str)]
        if isinstance(supported, list)
        else []
    )

    paragraphs = []
    if len(supported) == 1:
        role_label = STS1_RELIC_ROLE_LABELS.get(supported[0])
        if role_label is not None:
            if tier == "starter":
                paragraphs.append(
                    f"{role_label}的初始遗物。\n"
                    "部分路线会将它替换。"
                )
            else:
                paragraphs.append(f"{role_label}专属遗物。")

    if tier == "boss":
        act_labels = dict(RELIC_ACT_LABELS)
        for context in boss_choice_rank_contexts(snapshot, relic_id):
            act_label = act_labels.get(context["act"])
            if act_label is None:
                continue
            paragraphs.append(_boss_act_choice_paragraph(context, act_label))

    if tier in RELIC_DESCRIPTIVE_TIERS:
        rows = []
        acquisition_row = _first_acquisition_row(relic, entry)
        if acquisition_row is not None:
            rows.append(acquisition_row)
        presence_row = _final_presence_row(entry)
        if presence_row is not None:
            rows.append(presence_row)
        if rows:
            paragraphs.append("\n".join(rows))

    return "\n\n".join(paragraphs)



# STS2 Ancient choice (offer -> pick) display.
#
# The supported STS2 decision metric is the offer-to-pick rate recorded on
# Untapped "Ancient Choice" relic pages.  Ranks only ever compare one
# (NPC x act) cohort; end-of-run relic presence is deliberately not shown
# as a default statistic.



def _ancient_choice_block(snapshot):
    if not isinstance(snapshot, dict):
        return None
    choice = snapshot.get("ancient_choice")
    if not isinstance(choice, dict):
        return None
    return choice


def _resolve_ancient_npc_id(snapshot, npc_name_or_zh):
    """Resolve an NPC code or its official zh name inside the snapshot."""
    choice = _ancient_choice_block(snapshot)
    if choice is None:
        return None
    names = choice.get("npc_names_zh")
    if not isinstance(names, dict):
        return None
    key = str(npc_name_or_zh or "").strip()
    if not key:
        return None
    if key in names:
        return key
    for npc_id, zh in names.items():
        if isinstance(zh, str) and zh == key:
            return str(npc_id)
    return None


def _ancient_available_layers_text(npc_zh, acts):
    """Short valid-layer hint for bare or invalid NPC+layer Ancient entries."""
    if len(acts) == 1:
        act = acts[0]
        return (
            f"{npc_zh}目前只有{RELIC_COHORT_ACT_ZH[act]}的数据。\n"
            f"可发送：{npc_zh}"
        )
    options = "\n".join(f"{npc_zh}{act}" for act in sorted(acts))
    return f"{npc_zh}有多个可查询层：\n{options}"


def render_ancient_choice_leaderboard(npc_name_or_zh, act, kind="full", snapshot=None):
    """Render one NPC's full Ancient choice-rate board (layer wording).

    A bare NPC resolves automatically when it has exactly one rankable act;
    multi-act NPCs without a valid requested act receive a short layer hint.
    """
    if snapshot is None:
        snapshot = load_sts2_ancient_choice_stats()
    choice = _ancient_choice_block(snapshot)
    if choice is None:
        return None
    npc_id = _resolve_ancient_npc_id(snapshot, npc_name_or_zh)
    if npc_id is None:
        return None
    names = choice.get("npc_names_zh")
    npc_zh = names.get(npc_id) if isinstance(names, dict) else None
    if not isinstance(npc_zh, str) or not npc_zh:
        return None
    acts = leaderboard_npc_acts(snapshot, npc_id)
    if not acts:
        return None
    if act is None:
        if len(acts) == 1:
            act = acts[0]
        else:
            return _ancient_available_layers_text(npc_zh, acts)
    if act not in acts:
        return _ancient_available_layers_text(npc_zh, acts)
    contexts = leaderboard_contexts(snapshot, npc_id, act)
    if not contexts:
        return None
    relic_names = choice.get("relic_names_zh")
    relic_names = relic_names if isinstance(relic_names, dict) else {}
    act_label = RELIC_COHORT_ACT_ZH[act]
    summaries = _relic_short_summary_map("sts2")
    header = f"{npc_zh} · {act_label} Ancient 遗物选择率排行"
    body = []
    for context in contexts:
        relic_zh = relic_names.get(context.get("relic_id"))
        if not isinstance(relic_zh, str) or not relic_zh:
            continue
        summary = summaries.get(str(context.get("relic_id") or ""))
        _append_leaderboard_line(
            body,
            f"{context['rank']}. {relic_zh} —— {context['picked_rate']}%",
            summary,
        )
    if not body:
        return None
    return "\n".join([header] + body)


def render_sts2_ancient_choice_stats(relic, snapshot):
    """Render per-(NPC, act) choice contexts for one Ancient relic."""
    if not isinstance(relic, dict) or not isinstance(snapshot, dict):
        return ""
    if str(relic.get("tier") or "").strip().lower() != "ancient":
        return ""
    relic_id = str(relic.get("id") or "")
    if not relic_id:
        return ""
    lines = []
    for context in rankable_contexts_for_relic(snapshot, relic_id):
        npc_zh = context.get("npc_name_zh")
        if not isinstance(npc_zh, str) or not npc_zh:
            continue
        act = context.get("act")
        act_label = RELIC_COHORT_ACT_ZH.get(act, "") if isinstance(act, int) else ""
        if not act_label:
            continue
        lines.append(
            f"{npc_zh} · {act_label}：约{context['picked_rate']}%会选，"
            f"选择率第{context['rank']} / {context['cohort_size']}。"
        )
    return "\n".join(lines)


def render_relic_candidates(name, relics):
    lines = [f"找到 {len(relics)} 个同名遗物“{name}”："]
    for relic in relics:
        lines.append(f"- {_format_game(relic)}｜{_relic_tier_display(relic)}")
    return "\n".join(lines)


def _render_relic_description(relic):
    """Render a relic description into player-facing token text."""
    if not isinstance(relic, dict):
        return ""
    text = str(relic.get("description") or "")
    game = str(relic.get("game") or "")

    if game == "sts1":
        def energy_phrase(match):
            count = len(re.findall(r"\[E\]", match.group(0)))
            return f"{count}点能量" if count > 1 else "1点能量"

        text = re.sub(r"(?:\[E\]\s*)+", energy_phrase, text)
        text = render_sts1_energy(text)
    elif game == "sts2":
        # STS2 spells out icons in card/relic text; mirror the card rendering.
        text = text.replace("[E]", "⚡").replace("[S]", "⭐")
    else:
        return text

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([，。？！、：；])", r"\1", text)
    return text.strip()



def _sts2_shop_metric_value(row, key):
    metric = row.get(key) if isinstance(row, dict) else None
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value


def _sts2_shop_percent_cell(value):
    return f"{round(value)}%" if value is not None else "-"


def _sts2_shop_impact_cell(value):
    if value is None:
        return "-"
    rounded = round(value)
    if rounded == 0:
        return "0"
    return f"+{rounded}" if rounded > 0 else f"{rounded}"


def _sts2_shop_sample_cell(row):
    if not isinstance(row, dict):
        return "-"
    offered = row.get("offered")
    if isinstance(offered, bool) or not isinstance(offered, (int, float)):
        return "-"
    formatted = _format_compact_sample_count(offered)
    return formatted if formatted is not None else "-"


def render_sts2_relic_shop_stats(relic, snapshot):
    """Render one compact Shop Stats block for a non-Ancient STS2 relic.

    Decision data (bought rate per act) comes first, then run-level
    win-rate impact and the offered sample.  Acts without data render "-",
    and the whole group is hidden when no act has a purchase decision.
    """
    if not isinstance(relic, dict) or not isinstance(snapshot, dict):
        return ""
    if str(relic.get("tier") or "").strip().lower() == "ancient":
        return ""
    relic_id = str(relic.get("id") or "").strip()
    if not relic_id:
        return ""
    entry = (snapshot.get("relics") or {}).get(relic_id)
    if not isinstance(entry, dict):
        return ""
    shop = entry.get("shop")
    if not isinstance(shop, dict):
        return ""
    purchase_cells = []
    impact_cells = []
    sample_cells = []
    for act_key in _ACTS:
        row = shop.get(act_key)
        purchase_cells.append(
            _sts2_shop_percent_cell(_sts2_shop_metric_value(row, "purchase_rate"))
        )
        impact_cells.append(
            _sts2_shop_impact_cell(_sts2_shop_metric_value(row, "run_win_rate_impact"))
        )
        sample_cells.append(_sts2_shop_sample_cell(row))
    if all(cell == "-" for cell in purchase_cells):
        return ""
    lines = []
    if any(cell != "-" for cell in purchase_cells):
        lines.append(f"\u5546\u5e97\uff1a\u7b2c\u4e00/\u4e8c/\u4e09\u5c42 {' / '.join(purchase_cells)} \u4f1a\u4e70")
    if any(cell != "-" for cell in impact_cells):
        lines.append(f"\u80dc\u7387\u5173\u8054\uff1a{' / '.join(impact_cells)} \u4e2a\u767e\u5206\u70b9")
    if any(cell != "-" for cell in sample_cells):
        lines.append(f"\u6837\u672c\uff1a\u7b2c\u4e00/\u4e8c/\u4e09\u5c42 {' / '.join(sample_cells)} \u6b21")
    return "\n".join(lines)


def _linked_event_choice(event: EventRecord, link: EventEntityLink):
    if event.game == "sts1":
        index = link.condition.choice_index
        if index is None or index >= len(event.choices):
            return None
        return event.choices[index]
    return next(
        (
            choice
            for choice in event.choices
            if choice.id == link.condition.choice_id
        ),
        None,
    )


def _event_association_summary(
    event: EventRecord, link: EventEntityLink, entity_name: str
) -> str:
    if link.relation == "FALLBACK_REWARD":
        return f"{link.condition.fallback_text}改为获得"
    if link.relation == "REMOVE":
        return f"可献上「{entity_name}」"
    if link.relation == "REWARD" and link.entity_type == "card" and link.entity_id == "BITE":
        return "移除所有打击后获得 5 张"
    choice = _linked_event_choice(event, link)
    choice_text = strip_event_bbcode(
        getattr(choice, "text_zh", None)
    ).strip().rstrip("：:")
    if link.relation == "REWARD":
        return f"选择「{choice_text}」可获得" if choice_text else "可获得"
    return "有关联"


def render_event_associations(entity, entity_type: str) -> str:
    """Render a compact reverse Event-link section for one concrete entity."""

    if not isinstance(entity, dict):
        return ""
    game = str(entity.get("game") or "").strip()
    entity_id = str(entity.get("id") or "").strip()
    entity_name = str(entity.get("name") or "").strip()
    if not game or not entity_id or entity_type not in {"card", "relic"}:
        return ""
    lines = []
    for link in links_for_entity(game, entity_type, entity_id):
        try:
            event = get_event(game, link.event_id)
        except EventCatalogError:
            continue
        summary = _event_association_summary(event, link, entity_name)
        lines.append(f"- {event.name_zh}：{summary}")
    if not lines:
        return ""
    visible = lines[:3]
    if len(lines) > 3:
        visible.append(f"- 另有 {len(lines) - 3} 个事件关联")
    return "\n".join(["事件关联：", *visible])


def render_relic_query_reply(relics):
    if len(relics) == 1:
        relic = relics[0]
        game = str(relic.get("game") or "")
        tag = GAME_TAGS.get(game, game)
        name = str(relic.get("name") or "")
        parts = [
            f"=== {name} · {tag} ===",
            f"效果：\n{_render_relic_description(relic)}",
        ]
        tier_text = _relic_tier_display(relic)
        if tier_text:
            parts.append(tier_text)
        association_body = render_event_associations(relic, "relic")
        if association_body:
            parts.append(association_body)
        if game == "sts1":
            stats_body = render_relic_stats(relic, load_sts1_relic_stats())
            if stats_body:
                parts.append(stats_body)
        elif game == "sts2":
            stats_body = render_sts2_ancient_choice_stats(
                relic, load_sts2_ancient_choice_stats()
            )
            if stats_body:
                parts.append(stats_body)
            if str(relic.get("tier") or "").strip().lower() != "ancient":
                shop_body = render_sts2_relic_shop_stats(
                    relic, load_sts2_relic_shop_stats()
                )
                if shop_body:
                    parts.append(shop_body)
        text = "\n\n".join(parts)
        return RenderedReply(text, image_path=resolve_local_relic_image(relic))

    return RenderedReply(
        render_relic_candidates(relics[0].get("name", ""), relics),
        image_path=None,
    )

def _format_game(card):
    game = card.get("game", "")
    return GAME_NAMES.get(game, game)


def _query_identity_header(card):
    game = str(card.get("game") or "")
    tag = GAME_TAGS.get(game, game)
    name = str(card.get("name") or "")
    pool = card.get("pool")
    role = format_pool(card) if isinstance(pool, str) else ""
    return f"=== {name} · {tag} · {role} ==="


def render_card_details(card, include_name=True):
    lines = []
    if include_name:
        lines.append(f"卡名：{card.get('name', '')}")
    lines.extend([
        f"代际：{_format_game(card)}",
        f"来源：{format_pool(card)}",
        f"类型：{format_type(card)}",
        f"稀有度：{format_rarity(card)}",
        f"费用：{format_cost(card)}",
    ])

    star_cost = format_star_cost(card)
    if star_cost is not None:
        lines.append(f"辉星费用：{star_cost}")

    lines.extend(["描述：", render_description(card)])
    return "\n".join(lines)


def render_card_candidates(name, cards):
    lines = [f"找到 {len(cards)} 张同名卡牌“{name}”："]
    for card in cards:
        lines.append(
            "- "
            f"{_format_game(card)}｜{format_pool(card)}｜"
            f"{format_type(card)}｜{format_rarity(card)}"
        )
    return "\n".join(lines)


def render_card_query_reply(cards):
    if len(cards) == 1:
        card = cards[0]
        parts = [_query_identity_header(card)]
        association_body = render_event_associations(card, "card")
        if association_body:
            parts.append(association_body)
        image_path = resolve_local_card_image(card)
        image_paths = None
        if card.get("game") == "sts1":
            stats_text = render_sts1_stats(card, load_sts1_card_stats())
            if stats_text:
                parts.append(stats_text)
        elif card.get("game") == "sts2":
            stats_text = render_sts2_stats(card, load_sts2_card_stats())
            if stats_text:
                parts.append(stats_text)
        text = "\n\n".join(parts)
        upgraded_path = resolve_local_upgraded_card_image(card)
        if upgraded_path is not None:
            image_paths = tuple(p for p in (image_path, upgraded_path) if p is not None)
        return RenderedReply(text, image_path=image_path, image_paths=image_paths)

    return RenderedReply(
        render_card_candidates(cards[0].get("name", ""), cards),
        image_path=None,
    )


def render_wrong_card_guess_reply(game, feedback_text, cards):
    guessed_name = cards[0].get("name", "")
    if len(cards) == 1:
        card_text = render_card_details(cards[0], include_name=False)
        image_path = resolve_local_card_image(cards[0])
    else:
        card_text = render_card_candidates(guessed_name, cards)
        image_path = None

    text = (
        f"❌ 不是这张\n"
        f"你猜的是：{guessed_name}\n"
        f"{card_text}\n\n"
        f"{feedback_text}\n\n"
        f"{render_starting_puzzle(game)}"
    )
    return RenderedReply(text, image_path=image_path)


def render_starting_puzzle(game):
    if hasattr(game, "build_puzzle"):
        puzzle = game.build_puzzle()
    else:
        puzzle = {
            "masked_name": "",
            "pool": "",
            "type": "",
            "cost": "",
            "star_cost": None,
            "masked_description": "",
            "rarity": None,
        }

    wrong_text = "暂无" if not getattr(game, "wrong_guesses", []) else "、".join(game.wrong_guesses)
    lines = [
        "=== 本轮题目 ===",
        f"牌名：{puzzle.get('masked_name', '')}",
        f"来源：{puzzle.get('pool', '')}",
        f"类型：{puzzle.get('type', '')}",
        f"费用：{puzzle.get('cost', '')}",
    ]

    if puzzle.get("star_cost") is not None:
        lines.append(f"辉星费用：{puzzle['star_cost']}")

    if puzzle.get("rarity") is not None:
        lines.append(f"稀有度：{puzzle['rarity']}")

    lines.extend([
        "描述：",
        puzzle.get("masked_description", ""),
        "",
        f"已猜错：{wrong_text}",
        f"累计猜测：{getattr(game, 'total_guess_count', 0)} 次",
    ])

    return "\n".join(lines)


def render_in_progress_reply(game, feedback_text):
    return RenderedReply(f"{feedback_text}\n\n{render_starting_puzzle(game)}")


def render_terminal_reply(game, result, text: str):
    if not getattr(game, "ended", False):
        return RenderedReply(text, image_path=None)

    image_path = resolve_local_card_image(getattr(game, "card", None))
    return RenderedReply(text, image_path=image_path)

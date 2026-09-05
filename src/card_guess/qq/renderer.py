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
from card_guess.leaderboard import is_win_delta_eligible
from card_guess.puzzle import format_pool, format_rarity, format_type
from card_guess.sts1_card_stats import SOURCE_ID as STS1_SOURCE_ID
from card_guess.sts1_snapshot import COHORT_ASC7PLUS

REPO_ROOT = Path(__file__).resolve().parents[3]
STS1_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts1_card_stats.json"
STS2_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_card_stats.json"
STS1_RELIC_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts1_relic_stats.json"
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


def render_sts2_stats(card, snapshot):
    if not isinstance(snapshot, dict):
        return ""
    card_stats = snapshot.get("cards")
    if not isinstance(card_stats, dict):
        return ""
    entry = card_stats.get(str(card.get("id") or ""))
    if not isinstance(entry, dict):
        return ""

    untapped = entry.get("untapped")
    reward = untapped.get("card_reward") if isinstance(untapped, dict) else None
    shop = untapped.get("shop") if isinstance(untapped, dict) else None
    smith = untapped.get("smith") if isinstance(untapped, dict) else None

    sections = []

    pick_row = _format_metric_row(reward, "pick_rate", lambda v: f"{v:.0f}%")
    if pick_row is not None:
        sections.append(("第一/二/三幕抓取率", pick_row))

    purchase_row = _format_metric_row(shop, "purchase_rate", lambda v: f"{v:.0f}%")
    if purchase_row is not None:
        sections.append(("第一/二/三幕商店购买率", purchase_row))

    upgrade_row = _format_metric_row(smith, "upgrade_rate", lambda v: f"{v:.0f}%")
    if upgrade_row is not None:
        sections.append(("第一/二/三幕升级率", upgrade_row))

    delta_row = _format_metric_row(reward, "run_win_rate_impact", lambda v: f"{v:+.1f}")
    if delta_row is not None:
        sections.append(("第一/二/三幕胜率差", f"{delta_row} 个百分点"))

    spire_codex = entry.get("spire_codex")
    presence_line = None
    if isinstance(spire_codex, dict):
        presence = _metric_value(spire_codex, "final_deck_presence_rate")
        if presence is not None:
            presence_line = f"对局结束时持有率：{presence:.2f}%"

    if not sections and presence_line is None:
        return ""
    parts = [f"{label}\n{line}" for label, line in sections]
    if presence_line is not None:
        parts.append(presence_line)
    body = "\n\n".join(parts)
    return body


def _scalar_metric_value(source, name):
    metric = source.get(name)
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return value


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


def render_sts1_stats(card, snapshot):
    """STS1 stats for the default asc7plus cohort; missing values render '-'."""
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

    pick_row = _act_row_value(source, "act_pick_rate", lambda v: f"{v:.1f}%")
    delta_row = _sts1_win_delta_row(source)
    if delta_row is not None:
        delta_row = f"{delta_row} 个百分点"
    first_floor = _scalar_metric_value(source, "first_pick_floor_mean")
    repick = _scalar_metric_value(source, "repick_rate")
    presence = _scalar_metric_value(source, "final_deck_presence_rate")
    copy_mean = _scalar_metric_value(source, "final_deck_copy_mean")
    upgrade = _scalar_metric_value(source, "final_upgrade_rate")
    heart_presence = _scalar_metric_value(source, "heart_win_deck_presence_rate")

    lines = [
        f"第一/二/三幕抓取率\n{pick_row if pick_row is not None else '-'}",
        f"第一/二/三幕胜率差\n{delta_row if delta_row is not None else '-'}",
    ]

    def inline(stem: str, value: float | None, formatter) -> str:
        if value is None:
            return f"{stem}：-"
        return f"{stem}：{formatter(value)}"

    if first_floor is None:
        lines.append("第一次拿到：-")
    else:
        lines.append(f"第一次拿到：平均第 {first_floor:.1f} 层")
    lines.append(inline("再次选择率", repick, lambda v: f"{v:.1f}%"))
    lines.append(inline("对局结束时持有率", presence, lambda v: f"{v:.2f}%"))
    lines.append(inline("结束时平均持有", copy_mean, lambda v: f"{v:.2f} 张"))
    lines.append(inline("结束时升级比例", upgrade, lambda v: f"{v:.1f}%"))
    lines.append(inline("心脏胜利卡组出现率", heart_presence, lambda v: f"{v:.2f}%"))
    body = "\n\n".join(lines)
    return body


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
}


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


def _relic_tier_display(relic):
    tier = str(relic.get("tier") or "").strip()
    if not tier:
        return ""
    return _RELIC_TIER_LABELS.get(tier.lower(), tier)


RELIC_ACT_LABELS = (("act1", "第一幕"), ("act2", "第二幕"))
RELIC_SPREAD_MIN_RATIO = 2.0
RELIC_SPREAD_MIN_GAP = 1.0

# R5B acquisition-timing display policy.  The coverage floor is grounded in the
# real C/U/R audit (observed minimum ~62%, per relic), leaving a small guard
# band; relics whose recorded-acquisition coverage is lower never show timing.
RELIC_ACQUISITION_MIN_COVERAGE_PERCENT = 60.0
RELIC_ACQUISITION_DOMINANT_SHARE = 50.0
RELIC_ACQUISITION_ACTS = (
    ("act1_rate", "第一幕"),
    ("act2_rate", "第二幕"),
    ("act3_rate", "第三幕"),
)


def _metric_count(metric, key):
    """Return an integer count field from a metric dict, or None."""
    if not isinstance(metric, dict):
        return None
    value = metric.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _overall_hold_sentence(metric):
    """Explain how many runs ended while still carrying the relic."""
    value = _relic_metric_value(metric)
    numerator = _metric_count(metric, "numerator")
    denominator = _metric_count(metric, "denominator")
    if value is None or numerator is None or denominator is None or numerator < 1:
        return None
    return f"约{_format_relic_percent(value)}的对局最后带着它。"


def _heart_hold_sentence(metric):
    """Explain heart-win presence with an explicit beaten-heart denominator."""
    value = _relic_metric_value(metric)
    numerator = _metric_count(metric, "numerator")
    denominator = _metric_count(metric, "denominator")
    if value is None or numerator is None or denominator is None or numerator < 1:
        return None
    return f"击败心脏的对局中约{_format_relic_percent(value)}带着它。"


def _single_role_hold_sentence(role_label, per_character_metric):
    """Explain the hold rate for a relic that only one character supports."""
    value = _relic_metric_value(per_character_metric)
    if value is None:
        return None
    return (
        f"它几乎只出现在{role_label}对局，约"
        f"{_format_relic_percent(value)}会带着它。"
    )


def _role_spread_sentence(role_rates):
    """Summarize per-character spread, or state that no preference stands out."""
    values = [value for _, value in role_rates]
    if len(values) < 2:
        return None
    low = min(values)
    high = max(values)
    if low <= 0:
        return "各职业使用比例接近。"
    if high >= low * RELIC_SPREAD_MIN_RATIO and high - low >= RELIC_SPREAD_MIN_GAP:
        label, _ = max(role_rates, key=lambda item: item[1])
        return (
            f"{label}使用比例最高（{_format_relic_percent(high)}），"
            f"职业差异比较明显。"
        )
    return "各职业使用比例接近。"


def _boss_choice_paragraph(entry):
    """Explain boss-relic three-choice offers and act pick rates."""
    boss_choice = entry.get("boss_choice")
    if not isinstance(boss_choice, dict):
        return None
    lines = []
    for act_key, act_label in RELIC_ACT_LABELS:
        act_data = boss_choice.get(act_key)
        value = (
            _relic_metric_value(act_data.get("pick_rate"))
            if isinstance(act_data, dict)
            else None
        )
        if value is not None:
            lines.append(f"{act_label}约{_format_relic_percent(value)}会选")
    if not lines:
        return None
    return "\n".join(["Boss奖励出现时："] + lines)


def _starter_explanation(role_label):
    """Explain starter-relic persistence without inventing replacement stats."""
    return (
        f"作为初始遗物，它通常会陪伴{role_label}走完全程。\n"
        "部分路线会替换初始遗物，所以不会达到100%。"
    )


def _display_floor(value):
    """Round a recorded floor to the nearest integer, half-up (locked by tests)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(math.floor(float(value) + 0.5))


def _first_acquisition_paragraph(relic, entry):
    """Explain recorded first-acquisition timing in natural language.

    Returns None when the relic tier is ineligible, the snapshot has no
    ``first_acquisition`` section, the coverage is below the locked floor, or
    any numeric field is unusable.
    """
    tier = str(relic.get("tier") or "").strip().lower()
    if tier not in ("common", "uncommon", "rare"):
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
    lines = [f"通常在第{median}层左右拿到，"]
    dominant_act = None
    for act_key, act_label in RELIC_ACQUISITION_ACTS:
        act_value = _relic_metric_value(fa.get(act_key))
        if act_value is not None and act_value > RELIC_ACQUISITION_DOMINANT_SHARE:
            dominant_act = act_label
            break
    if dominant_act is not None:
        lines.append(
            f"约一半集中在第{p25}～{p75}层，超过一半来自{dominant_act}。"
        )
    else:
        lines.append(f"约一半集中在第{p25}～{p75}层。")
        lines.append("获取时间比较分散，三幕都有不少记录。")
    return "\n".join(lines)


def render_relic_stats(relic, snapshot):
    """Render audited STS1 relic stats as natural-language sentences."""
    if not isinstance(snapshot, dict):
        return ""
    relic_stats = snapshot.get("relics")
    if not isinstance(relic_stats, dict):
        return ""
    entry = relic_stats.get(str(relic.get("id") or ""))
    if not isinstance(entry, dict):
        return ""

    tier = str(relic.get("tier") or "").strip().lower()
    supported = entry.get("supported_roles")
    supported = (
        [role for role in supported if isinstance(role, str)]
        if isinstance(supported, list)
        else []
    )
    per_character = entry.get("per_character")
    if not isinstance(per_character, dict):
        per_character = {}
    overall_metric = entry.get("overall")
    if not isinstance(overall_metric, dict):
        overall_metric = None

    role_rates = []
    for role in supported:
        label = STS1_RELIC_ROLE_LABELS.get(role)
        metric = per_character.get(role)
        value = _relic_metric_value(metric)
        if label is None or value is None:
            continue
        role_rates.append((label, value))

    paragraphs = []
    if tier == "boss":
        boss_paragraph = _boss_choice_paragraph(entry)
        if boss_paragraph is not None:
            paragraphs.append(boss_paragraph)

    if len(role_rates) == 1:
        label, value = role_rates[0]
        sentence = _single_role_hold_sentence(
            label, per_character.get(supported[0])
        )
        if sentence is not None:
            paragraphs.append(sentence)
        if tier == "starter" and value < 100:
            paragraphs.append(_starter_explanation(label))
    else:
        overall_sentence = _overall_hold_sentence(overall_metric)
        if overall_sentence is not None:
            paragraphs.append(overall_sentence)
        if len(role_rates) >= 2 and tier != "boss":
            spread_sentence = _role_spread_sentence(role_rates)
            if spread_sentence is not None:
                paragraphs.append(spread_sentence)

    heart_metric = entry.get("heart_win_presence_rate")
    if isinstance(heart_metric, dict):
        heart_sentence = _heart_hold_sentence(heart_metric)
        if heart_sentence is not None:
            paragraphs.append(heart_sentence)

    acquisition_paragraph = _first_acquisition_paragraph(relic, entry)
    if acquisition_paragraph is not None:
        paragraphs.append(acquisition_paragraph)

    return "\n\n".join(paragraphs)


def render_relic_candidates(name, relics):
    lines = [f"找到 {len(relics)} 个同名遗物“{name}”："]
    for relic in relics:
        lines.append(f"- {_format_game(relic)}｜{_relic_tier_display(relic)}")
    return "\n".join(lines)


def _render_relic_description(relic):
    """Render an STS1 relic description into player-facing token text."""
    if not isinstance(relic, dict):
        return ""
    text = str(relic.get("description") or "")
    if str(relic.get("game") or "") != "sts1":
        return text

    def energy_phrase(match):
        count = len(re.findall(r"\[E\]", match.group(0)))
        return f"{count}点能量" if count > 1 else "1点能量"

    text = re.sub(r"(?:\[E\]\s*)+", energy_phrase, text)
    text = render_sts1_energy(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([，。？！、：；])", r"\1", text)
    return text.strip()


def render_relic_query_reply(relics):
    if len(relics) == 1:
        relic = relics[0]
        game = str(relic.get("game") or "")
        tag = GAME_TAGS.get(game, game)
        name = str(relic.get("name") or "")
        parts = [
            f"=== {name} · {tag} ===",
            f"效果：\n{_render_relic_description(relic)}",
            _relic_tier_display(relic),
        ]
        if game == "sts1":
            stats_body = render_relic_stats(relic, load_sts1_relic_stats())
            if stats_body:
                parts.append(stats_body)
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
        text = _query_identity_header(card)
        image_path = resolve_local_card_image(card)
        image_paths = None
        if card.get("game") == "sts1":
            stats_text = render_sts1_stats(card, load_sts1_card_stats())
            if stats_text:
                text = f"{text}\n\n{stats_text}"
        elif card.get("game") == "sts2":
            stats_text = render_sts2_stats(card, load_sts2_card_stats())
            if stats_text:
                text = f"{text}\n\n{stats_text}"
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

from __future__ import annotations

import json
from pathlib import Path

from card_guess.cards import format_cost, format_star_cost, render_description
from card_guess.puzzle import format_pool, format_rarity, format_type

REPO_ROOT = Path(__file__).resolve().parents[3]
STS2_STATS_SNAPSHOT = REPO_ROOT / "data" / "stats" / "sts2_card_stats.json"
GAME_NAMES = {
    "sts1": "杀戮尖塔 1",
    "sts2": "杀戮尖塔 2",
}

_sts2_card_stats_cache = None


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


def load_sts2_card_stats():
    global _sts2_card_stats_cache
    if _sts2_card_stats_cache is None:
        try:
            with open(STS2_STATS_SNAPSHOT, encoding="utf-8") as f:
                _sts2_card_stats_cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            _sts2_card_stats_cache = {}
    return _sts2_card_stats_cache


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
            presence_line = f"终局卡组出现率：{presence:.2f}%"

    if not sections and presence_line is None:
        return ""
    parts = [f"{label}\n{line}" for label, line in sections]
    if presence_line is not None:
        parts.append(presence_line)
    body = "\n\n".join(parts)
    return f"=== 二代统计 ===\n{body}"


def _format_game(card):
    game = card.get("game", "")
    return GAME_NAMES.get(game, game)


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
        text = f"=== 卡牌资料 ===\n{render_card_details(card)}"
        image_path = resolve_local_card_image(card)
        image_paths = None
        if card.get("game") == "sts2":
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

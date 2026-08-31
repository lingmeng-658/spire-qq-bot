from __future__ import annotations

from pathlib import Path

from card_guess.cards import format_cost, format_star_cost, render_description
from card_guess.puzzle import format_pool, format_rarity, format_type

REPO_ROOT = Path(__file__).resolve().parents[3]
GAME_NAMES = {
    "sts1": "杀戮尖塔 1",
    "sts2": "杀戮尖塔 2",
}


class RenderedReply(str):
    def __new__(cls, text: str, image_path: Path | None = None):
        obj = str.__new__(cls, text)
        obj.text = text
        obj.image_path = image_path
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
        return RenderedReply(
            f"=== 卡牌资料 ===\n{render_card_details(card)}",
            image_path=resolve_local_card_image(card),
        )

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

import random

from card_guess.cards import load_all_standard_cards, load_game_cards, render_description
from card_guess.game import GameState
from card_guess.puzzle import find_opening_reveal_positions

VALID_MODES = {"mixed", "sts1", "sts2"}
CHARACTER_ALIASES = {
    "铁甲战士": "ironclad",
    "战士": "ironclad",
    "战士哥": "ironclad",
    "静默猎手": "silent",
    "猎宝": "silent",
    "猎豹": "silent",
    "故障机器人": "defect",
    "鸡煲": "defect",
    "机宝": "defect",
    "观者": "watcher",
    "紫皮": "watcher",
    "死灵契约师": "necrobinder",
    "亡灵契约师": "necrobinder",
    "骨妹": "necrobinder",
    "摄政王": "regent",
    "储君": "regent",
    "无色牌": "colorless",
    "无色": "colorless",
    "诅咒": "curse",
    "状态": "status",
    "事件牌": "event",
    "事件": "event",
    "任务牌": "quest",
    "任务": "quest",
    "衍生牌": "token",
    "衍生": "token",
}
CHARACTER_DISPLAY = {value: key for key, value in CHARACTER_ALIASES.items()}
SESSIONS = {}


def resolve_character(character):
    if character is None:
        return None

    normalized = str(character).strip()
    if not normalized:
        raise ValueError("角色名不能为空")

    if normalized in CHARACTER_ALIASES:
        return CHARACTER_ALIASES[normalized]

    if normalized in CHARACTER_ALIASES.values():
        return normalized

    raise ValueError(f"角色 '{character}' 不存在")


def _create_game_state_for_mode(mode, cards=None):
    if cards is None:
        cards = load_game_cards(mode)

    if not cards:
        raise ValueError(f"模式 {mode} 下没有可用卡牌")

    card = random.choice(cards)

    game = GameState(card)
    game.revealed_positions.update(
        find_opening_reveal_positions(render_description(card))
    )
    return game


def start(group_id, mode, character=None):
    if mode not in VALID_MODES:
        raise ValueError(f"unsupported mode: {mode}")

    existing = SESSIONS.get(group_id)
    if existing is not None:
        return existing

    resolved_character = None
    if character is not None:
        resolved_character = resolve_character(character)

    if resolved_character is not None:
        cards = [
            card
            for card in load_all_standard_cards(mode)
            if card.get("pool") == resolved_character
        ]
        if not cards:
            raise ValueError("当前版本没有可用的该类题库")
    else:
        cards = load_game_cards(mode)

    game = _create_game_state_for_mode(mode, cards=cards)
    SESSIONS[group_id] = game
    return game


def get(group_id):
    return SESSIONS.get(group_id)


def end(group_id):
    return SESSIONS.pop(group_id, None)

from card_guess.cards import (
    format_cost,
    format_star_cost,
    get_visible_traits,
    render_description,
)
import unicodedata
import jieba

POOL_NAMES = {
    "ironclad": "铁甲战士",
    "silent": "静默猎手",
    "defect": "故障机器人",
    "watcher": "观者",
    "necrobinder": "死灵契约师",
    "regent": "储君",
    "colorless": "无色",
    "curse": "诅咒",
    "status": "状态",
    "event": "事件",
    "token": "衍生",
    "quest": "任务",
}


TYPE_NAMES = {
    "Attack": "攻击牌",
    "Skill": "技能牌",
    "Power": "能力牌",
    "Curse": "诅咒牌",
    "Status": "状态牌",
    "Quest": "任务牌",
}

RARITY_NAMES = {
    "Basic": "基础",
    "Common": "普通",
    "Uncommon": "罕见",
    "Rare": "稀有",
    "Curse": "诅咒",
    "Special": "特殊",
    "Ancient": "先古",
    "Event": "事件",
    "Quest": "任务",
    "Status": "状态",
    "Token": "衍生",
}

OPENING_REVEAL_TOKENS = {
    "点",
    "的",
    "你",
    "在",
    "中",
    "时",
    "将",
    "每",
    "对",
    "这",
    "被",
    "本",
    "个",
    "就",
    "则",
    "内",
    "其",
    "从",
    "有",
    "到",
    "这个",
    "过",
    "会",
    "一",
    "并",
    "为",
    "是",
    "该",
    "一张",
    "张",
    "次",

    # 句子骨架
    "当",
    "每当",
    "如果",
    "然后",
    "这张牌",
    "你的",
    "之前",
}

OPENING_REVEAL_PHRASES = {
    "不能被打出",
}

def format_pool(card):
    pool = card["pool"]
    return POOL_NAMES.get(pool, pool)

def format_type(card):
    card_type = card["type"]
    return TYPE_NAMES.get(card_type, card_type)

def format_rarity(card):
    rarity = card["rarity"]
    return RARITY_NAMES.get(rarity, rarity)

def find_opening_reveal_positions(description):
    positions = set()

    for token, start, end in jieba.tokenize(description):
        if token in OPENING_REVEAL_TOKENS:
            positions.update(range(start, end))

    for phrase in OPENING_REVEAL_PHRASES:
        positions.update(find_phrase_positions(description, phrase))

    return positions

def mask_description(description, revealed_positions=None):
    if revealed_positions is None:
        revealed_positions = set()

    result = ""

    for index, char in enumerate(description):
        if (
            index in revealed_positions
            or char.isdigit()
            or char in {"⚡", "⭐", "X"}
            or char.isspace()
            or unicodedata.category(char).startswith("P")
        ):
            result += char
        else:
            result += "□"

    return result

def mask_name(name, revealed_positions=None):
    if revealed_positions is None:
        revealed_positions = set()

    return "".join(
        char if index in revealed_positions else "□"
        for index, char in enumerate(name)
    )


def find_phrase_positions(description, phrase):
    positions = set()

    start = 0

    while True:
        index = description.find(phrase, start)

        if index == -1:
            break

        positions.update(range(index, index + len(phrase)))
        start = index + 1

    return positions

def count_effective_chars(text):
    return sum(
        1
        for char in text
        if char.isalpha()
    )

def build_puzzle(
    card,
    revealed_positions=None,
    revealed_name_positions=None,
    rarity_revealed=False,
    revealed_traits=None,
):
    description = render_description(card)

    masked_description = mask_description(
        description,
        revealed_positions,
    )

    masked_name = mask_name(
        card["name"],
        revealed_name_positions,
    )

    visible_traits = get_visible_traits(
        card,
        upgraded=bool(card.get("upgraded", False)),
    )
    active_traits = []
    for trait in dict.fromkeys(visible_traits):
        if not any(trait in part for part in (card.get("description", ""), description)):
            active_traits.append(trait)

    revealed_traits = set(revealed_traits or [])

    result = {
        "masked_name": masked_name,
        "pool": format_pool(card),
        "type": format_type(card),
        "cost": format_cost(card),
        "star_cost": format_star_cost(card),
        "masked_description": masked_description,
        "rarity": format_rarity(card) if rarity_revealed else None,
        "traits": active_traits,
        "revealed_traits": sorted(revealed_traits),
        "trait_line": None,
    }
    return result

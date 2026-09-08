import asyncio
import json
import logging
import random
import re

from card_guess.cards import load_cards
from card_guess.event_presentation import render_event, render_event_choice_outcome
from card_guess.events import default_random_pool, find_events_by_name
from card_guess.relics import find_relics_by_name, load_relics
from card_guess import leaderboard as lb
from card_guess.puzzle import POOL_NAMES, format_rarity
from card_guess.qq import event_sessions
from card_guess.qq import sessions
from card_guess.qq import renderer as qq_renderer
from card_guess.qq.onebot import (
    build_friend_add_request_action,
    build_group_add_request_action,
    build_message_segments,
    extract_mentioned_text,
    extract_private_text,
    send_action,
)
from card_guess.qq.renderer import (
    RenderedReply,
    render_card_query_reply,
    render_in_progress_reply,
    render_relic_query_reply,
    render_starting_puzzle,
    render_terminal_reply,
)

logger = logging.getLogger("card_guess.qq.bot")

START_WORDS = {"开始"}
ANCIENT_OVERVIEW_COMMAND = "先古遗民"
ANCIENT_OVERVIEW_COMMANDS = frozenset({"先古遗民", "先古之民"})
START_SUFFIX_MODES = {"": "mixed", "1": "sts1", "2": "sts2"}
END_COMMANDS = {"结束"}
RANDOM_EVENT_COMMANDS = {"事件": None, "事件1": 1, "事件2": 2}
TYPED_QUERY_LABELS = {"卡牌": "card", "遗物": "relic", "事件": "event"}
EVENT_SESSION_BUSY_REPLY = "当前已有互动事件进行中，回复选项数字即可参与；发送「结束」可结束互动事件。"
EVENT_SESSION_INVALID_REPLY = "互动事件进行中，请回复选项对应的数字。"
EVENT_SESSION_ENDED_REPLY = "互动事件已结束。"
HELP_TEXT = """=== 帮助 ===

直接发送名字即可查询卡牌 / 遗物 / 事件
例：白噪声 / 赤牛

随机事件：事件 / 事件1 / 事件2

也可查询卡牌或遗物在特定场景下的排行
例：观者1普通 / Boss1 / 达弗2
注：上面的数字均表示第几层。

发送「先古遗民」
可查看所有先古遗民的名字与对应图片

猜卡：开始
可限制代际、角色和卡池
例：开始2 骨妹

更多：
帮助 查询 · 帮助 猜卡 · 帮助 排行

两代同名时，在名字最后加 1 / 2 指定代际。
群聊请 @我，私聊直接发送。"""
HELP_COMMANDS = {"帮助", "help", "功能"}
UNKNOWN_COMMAND_REPLY = "没找到对应命令，发送「帮助」查看用法。"


HELP_SUBCOMMANDS = {
    "猜卡": """=== 帮助 猜卡 ===

正式命令：
开始 / 结束

开始可限制代际、角色和卡池
例：开始2 骨妹
其它示例：开始 / 开始1 无色

猜卡进行中：
普通输入只作为猜测
想强制查询时用 卡名1 / 卡名2""",
    "查询": """=== 帮助 查询 ===

直接发卡名、遗物名或事件名即可查询
无后缀时自动判断代际：
只在某一代存在 → 直接查询
两代同名 → 提示加 1 / 2

显式写法永远允许：
名字1 / 名字2
空格可以忽略
不讲拼音 / 模糊匹配""",
    "排行": """=== 帮助 排行 ===

Card：
观者1
观者1普通
观者1罕见
观者1稀有

Boss：
Boss1
Boss2

Ancient：
先古遗民
达弗
达弗2
达弗3
涅奥

上面的数字均表示第几层。""",
}


def render_help(text):
    parts = (text or "").strip().split(None, 1)
    if len(parts) == 1:
        return HELP_TEXT
    sub = parts[1].strip()
    if sub in HELP_SUBCOMMANDS:
        return HELP_SUBCOMMANDS[sub]
    return "没有子帮助“{}”。\n可用：帮助 {}".format(
        sub, " / 帮助 ".join(HELP_SUBCOMMANDS)
    )


def _card_layer_alias_pattern():
    pattern = getattr(_card_layer_alias_pattern, "pattern", None)
    if pattern is None:
        aliases = sorted(sessions.CHARACTER_ALIASES, key=len, reverse=True)
        pattern = "|".join(re.escape(alias) for alias in aliases)
        _card_layer_alias_pattern.pattern = pattern
    return pattern


def _parse_card_layer_rarity_request(command):
    """Parse 角色+层(+稀有度) Card cohort syntax with arbitrary spacing.

    Grammar: <character alias><1|2|3> or <alias><1|2|3><普通|罕见|稀有>;
    whitespace anywhere is ignored.  Returns a request dict or ``None``.
    """
    text = (command or "").strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text)
    match = re.fullmatch(
        rf"({_card_layer_alias_pattern()})([123])(普通|罕见|稀有)?",
        compact,
    )
    if match is None:
        return None
    alias, act, rarity_zh = match.groups()
    return {"alias": alias, "act": int(act), "rarity_zh": rarity_zh}


def _render_card_layer_board_reply(command):
    """Full-match Card cohort command -> reply text; not a board -> None."""
    request = _parse_card_layer_rarity_request(command)
    if request is None:
        return None
    return lb.render_card_layer_cohort_board(
        request["alias"], request["act"], request["rarity_zh"]
    )

_BOSS_BOARD_RE = re.compile(r"^boss([123])$", re.IGNORECASE)


def _parse_boss_board_request(command):
    """Parse STS1 Boss board entries: Boss1 / Boss2 / Boss3.

    Spaces are handled by the global whitespace normalization, so parsing
    only matches the compact spelling and adds no whitespace regex of its own.
    """
    if not isinstance(command, str):
        return None
    match = _BOSS_BOARD_RE.fullmatch(command.strip())
    if match is None:
        return None
    return {"act": int(match.group(1))}


def _render_boss_board_reply(command):
    """Render an STS1 Boss choice-rate board command or ``None``."""
    request = _parse_boss_board_request(command)
    if request is None:
        return None
    if request["act"] == 3:
        return "Boss 遗物目前只有第一层和第二层的排行数据。"
    board = qq_renderer.render_sts1_boss_leaderboard(request["act"])
    return board or "Boss 遗物排行暂时没有可用的数据。"


def _ancient_choice_npc_zh(snapshot):
    """Map official zh NPC names in the snapshot back to NPC ids."""
    if not isinstance(snapshot, dict):
        return {}
    choice = snapshot.get("ancient_choice")
    if not isinstance(choice, dict):
        return {}
    names = choice.get("npc_names_zh")
    if not isinstance(names, dict):
        return {}
    mapping = {}
    for npc_id, zh in names.items():
        if isinstance(zh, str) and zh.strip():
            mapping[zh.strip()] = str(npc_id)
    return mapping


def _parse_ancient_choice_request(snapshot, command):
    """Parse official-zh-NPC Ancient board commands.

    Main entries are NPC + layer (达弗2) or a bare NPC (涅奥). 排行/最高/最低
    forms are no longer board routes.  Returns a request dict or None.
    """
    if not command:
        return None
    zh_to_id = _ancient_choice_npc_zh(snapshot)
    if not zh_to_id:
        return None
    npc_pattern = "|".join(re.escape(zh) for zh in sorted(zh_to_id, key=len, reverse=True))
    board_form = re.compile(rf"^(?P<npc>{npc_pattern})(?P<suffix>[123])?$")
    match = board_form.fullmatch(command.strip())
    if match is None:
        return None
    suffix = match.group("suffix")
    return {
        "npc_id": zh_to_id[match.group("npc")],
        "npc_zh": match.group("npc"),
        "act": int(suffix) if suffix else None,
    }


def _render_ancient_choice_leaderboard_reply(command):
    """Render an official-NPC Ancient choice leaderboard command or None."""
    snapshot = qq_renderer.load_sts2_ancient_choice_stats()
    request = _parse_ancient_choice_request(snapshot, (command or "").strip())
    if request is None:
        return None
    board = qq_renderer.render_ancient_choice_leaderboard(
        request["npc_id"],
        request["act"],
        snapshot=snapshot,
    )
    if board is None:
        board = f"{request['npc_zh']}还没有可用的选择数据。"
    image_path = None
    if request["act"] is None:
        image_path = qq_renderer.resolve_local_ancient_npc_image(
            request["npc_id"]
        )
    return RenderedReply(board, image_path=image_path)

def _load_query_cards():
    return load_cards("sts1") + load_cards("sts2")


def _answer_name(game):
    if isinstance(game.card, dict):
        return game.card.get("name", "未知卡牌")
    return "未知卡牌"


def _format_game_result(game, result):
    answer_name = _answer_name(game)

    if getattr(result, "terminal_reason", None) == "hint_exhausted":
        return f"提示耗尽，本局结束\n正确答案：{answer_name}"

    if result.status == "correct":
        return f"🎉 恭喜猜出！\n正确答案：{answer_name}"

    if result.status == "revealed":
        if result.reveal_target == "name":
            if game.ended:
                return f"🎉 恭喜猜出！\n正确答案：{answer_name}"
            return f"🎯 牌名命中！揭开 {result.revealed_count} 个新字符！"

        feedback = f"🎯 描述命中！揭开 {result.revealed_count} 个新字符！"
        if result.hint_type == "name":
            feedback += "\n额外提示：揭开了一个牌名字符。"
        return feedback

    if result.status == "already_revealed":
        return "这部分已经揭开了，换个地方猜吧。"

    if result.status == "invalid":
        return "这个输入没有可猜的文字。"

    if result.status == "wrong":
        base = "猜错了"
        if result.hint_type == "rarity":
            return f"{base}，提示：稀有度为 {format_rarity(game.card)}"
        if result.hint_type == "description":
            return f"{base}，提示：揭开了新的描述内容。"
        if result.hint_type == "name":
            return f"{base}，提示：揭开了一个牌名字符。"
        return f"{base}。"

    if result.status == "ended":
        return f"本局游戏结束\n正确答案：{answer_name}"

    return str(result.status)


def _parse_start_request(text):
    command = (text or "").strip()
    if not command:
        return None, None

    for word in sorted(START_WORDS, key=len, reverse=True):
        if command == word:
            return START_SUFFIX_MODES[""], None

        if not command.startswith(word):
            continue

        remainder = command[len(word):]

        if word == "开始":
            compact = re.sub(r"\s+", "", remainder)
            if compact and compact[0] in START_SUFFIX_MODES:
                return START_SUFFIX_MODES[compact[0]], compact[1:] or None

            if command.startswith(word + " "):
                return START_SUFFIX_MODES[""], compact or None
            continue

        if command.startswith(word + " "):
            tail = remainder.strip()
            return START_SUFFIX_MODES[""], tail or None

        if not remainder:
            continue

        suffix = remainder[0]
        if suffix not in START_SUFFIX_MODES:
            continue

        tail = remainder[1:]
        if not tail:
            return START_SUFFIX_MODES[suffix], None
        if tail.startswith(" "):
            name = tail.strip()
            return START_SUFFIX_MODES[suffix], name or None

    return None, None


def _parse_generation_selector(text):
    command = (text or "").strip()
    if not command:
        return None, None, None

    match = re.fullmatch(r"(.+?)(?:\s*([12]))?(?:\s+(\S+))?", command)
    if match is None:
        return command, None, None

    name, suffix, role = match.groups()
    if not name:
        return command, None, None

    generation = int(suffix) if suffix else None
    if role is not None and generation is None:
        # 仅支持“卡名1/2 角色名”顺序；角色在前或无代际后缀时不作为查卡语法
        return command, None, None
    return name, generation, role


def _find_cards_by_name(name, generation=None):
    matches = [
        card
        for card in _load_query_cards()
        if isinstance(card, dict) and card.get("name") == name
    ]
    if generation is None:
        return matches
    return [
        card for card in matches
        if str(card.get("game", "")).strip() == f"sts{generation}"
    ]


def _load_query_relics():
    return load_relics("sts1") + load_relics("sts2")


def _load_sts2_query_relics():
    return load_relics("sts2")


def _find_relics_by_name(name, generation=None):
    return find_relics_by_name(_load_query_relics(), name, generation=generation)


def _find_sts2_relics_by_name(name):
    return find_relics_by_name(_load_sts2_query_relics(), name, generation=2)


def _find_generation_relics_by_name(name, generation):
    if generation == 2:
        return _find_sts2_relics_by_name(name)
    return _find_relics_by_name(name, generation=1)


def _find_events_by_name(name, generation=None):
    game = f"sts{generation}" if generation is not None else None
    return find_events_by_name(name, game=game)


def _render_relic_generation_query(name, generation, role=None):
    """显式遗物查询（遗物名+1/2）。

    一代只查 STS1 遗物并渲染一代资料；二代查 STS2 遗物并
    渲染二代资料。 STS2 中无同名遗物时给出提示；
    角色名仅用于卡牌消歧，遗物不支持角色参数；无命中返回 None 交给原流程。
    """
    if role is not None:
        return None

    if generation == 2:
        sts2_matches = _find_sts2_relics_by_name(name)
        if sts2_matches:
            return render_relic_query_reply(sts2_matches)
        if _find_relics_by_name(name, generation=1):
            return RenderedReply(
                f"“{name}2”没有对应的二代遗物。\n"
                f"可发送：\n{name}1 —— 查看一代遗物"
            )
        return None

    sts1_matches = _find_relics_by_name(name, generation=1)
    if not sts1_matches:
        return None
    return render_relic_query_reply(sts1_matches)


def _display_pool(pool):
    return POOL_NAMES.get(pool, pool or "")


def _render_generation_query(name, generation, role=None):
    """显式查卡：卡名1/2 [角色名]。名称+代际无匹配时返回 None（交给普通猜测）。"""
    matches = _find_cards_by_name(name, generation)
    if not matches:
        return None

    if role is None:
        reply = render_card_query_reply(matches)
        if len(matches) > 1:
            hint = (
                f"提示：有 {len(matches)} 张同名卡，可加角色名消歧，例如：\n"
                f"{name}{generation} 角色名"
            )
            reply = RenderedReply(f"{reply.text}\n\n{hint}")
        return reply

    try:
        pool = sessions.resolve_character(role)
    except ValueError:
        valid = "、".join(_display_pool(m.get("pool")) for m in matches)
        return RenderedReply(
            f"无法识别角色“{role}”。\n"
            f"“{name}{generation}”可选角色：{valid}"
        )

    filtered = [m for m in matches if m.get("pool") == pool]
    if not filtered:
        return RenderedReply(
            f"“{name}{generation}”没有角色“{_display_pool(pool)}”的卡牌。"
        )
    return render_card_query_reply(filtered)







_ROUTE_WS_RE = re.compile(r"\s+")


def _parse_typed_query(text):
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r"(卡牌|遗物|事件)\s+(.+)", text.strip())
    if match is None:
        return None
    return TYPED_QUERY_LABELS[match.group(1)], match.group(2).strip()


def _games_for_cards(matches):
    return {
        str(item.get("game", "")).strip()
        for item in matches
        if isinstance(item, dict)
    }


def _games_for_events(matches):
    return {event.game for event in matches}


def _render_event_matches(name, matches):
    if not matches:
        return None
    if {"sts1", "sts2"}.issubset(_games_for_events(matches)):
        return RenderedReply(_cross_generation_hint(name))
    return RenderedReply(render_event(matches[0]))


def _render_typed_query(command):
    parsed = _parse_typed_query(command)
    if parsed is None:
        return None
    entity_type, query = parsed
    name, generation, role = _parse_generation_selector(query)
    if not name:
        return RenderedReply(UNKNOWN_COMMAND_REPLY)

    if entity_type == "card":
        if generation is not None:
            return _render_generation_query(name, generation, role) or RenderedReply(
                UNKNOWN_COMMAND_REPLY
            )
        matches = _find_cards_by_name(name)
        if {"sts1", "sts2"}.issubset(_games_for_cards(matches)):
            return RenderedReply(_cross_generation_hint(name))
        return render_card_query_reply(matches) if matches else RenderedReply(UNKNOWN_COMMAND_REPLY)

    if role is not None:
        return RenderedReply(UNKNOWN_COMMAND_REPLY)
    if entity_type == "relic":
        matches = (
            _find_relics_by_name(name)
            if generation is None
            else _find_generation_relics_by_name(name, generation)
        )
        if {"sts1", "sts2"}.issubset(_games_for_cards(matches)):
            return RenderedReply(_cross_generation_hint(name))
        if generation is not None:
            return _render_relic_generation_query(name, generation) or RenderedReply(
                UNKNOWN_COMMAND_REPLY
            )
        return render_relic_query_reply(matches) if matches else RenderedReply(UNKNOWN_COMMAND_REPLY)

    matches = _find_events_by_name(name, generation)
    return _render_event_matches(name, matches) or RenderedReply(UNKNOWN_COMMAND_REPLY)


def _actor_label(actor):
    label = (actor or "").strip()
    return label or "群友"


def _active_event_session_reply(group_id, command, actor=None):
    """Route a message while an interactive event round is pending."""

    session = event_sessions.get(group_id)
    if session is None:
        return None
    if command in END_COMMANDS:
        event_sessions.end(group_id)
        return RenderedReply(EVENT_SESSION_ENDED_REPLY)
    if command in RANDOM_EVENT_COMMANDS:
        return RenderedReply(EVENT_SESSION_BUSY_REPLY)
    choice = event_sessions.resolve_choice(session, command)
    if choice is None:
        return RenderedReply(EVENT_SESSION_INVALID_REPLY)
    event_sessions.end(group_id)
    return RenderedReply(render_event_choice_outcome(choice, _actor_label(actor)))


def _render_random_event_reply(command, group_id=None):
    if command not in RANDOM_EVENT_COMMANDS:
        return None
    generation = RANDOM_EVENT_COMMANDS[command]
    game = f"sts{generation}" if generation is not None else random.choice(("sts1", "sts2"))
    event = random.choice(default_random_pool(game))
    reply = RenderedReply(render_event(event))
    if group_id is not None and game == "sts2":
        event_sessions.open_if_idle(group_id, event)
    return reply


def _entity_disambiguation(name, typed_matches):
    labels = {"card": "卡牌", "relic": "遗物", "event": "事件"}
    available = [kind for kind in ("card", "relic", "event") if typed_matches[kind]]
    if len(available) < 2:
        return None
    label_text = " / ".join(labels[kind] for kind in available)
    choices = " / ".join(f"{labels[kind]} {name}" for kind in available)
    return RenderedReply(f"“{name}”同时是{label_text}。\n请选择：{choices}")


def _query_matches(name, generation=None):
    return {
        "card": _find_cards_by_name(name, generation),
        "relic": (
            _find_relics_by_name(name)
            if generation is None
            else _find_generation_relics_by_name(name, generation)
        ),
        "event": _find_events_by_name(name, generation),
    }


def _render_untyped_query(name, generation=None, role=None):
    if role is not None:
        if generation is None:
            return None
        return _render_generation_query(name, generation, role)

    matches = _query_matches(name, generation)
    display_name = f"{name}{generation}" if generation is not None else name
    ambiguity = _entity_disambiguation(display_name, matches)
    if ambiguity is not None:
        return ambiguity

    if matches["card"]:
        if generation is not None:
            return _render_generation_query(name, generation)
        if generation is None and {"sts1", "sts2"}.issubset(
            _games_for_cards(matches["card"])
        ):
            return RenderedReply(_cross_generation_hint(name))
        return render_card_query_reply(matches["card"])
    if matches["relic"]:
        if generation is not None:
            return _render_relic_generation_query(name, generation)
        if generation is None and {"sts1", "sts2"}.issubset(
            _games_for_cards(matches["relic"])
        ):
            return RenderedReply(_cross_generation_hint(name))
        return render_relic_query_reply(matches["relic"])
    event_reply = _render_event_matches(name, matches["event"])
    if event_reply is not None:
        return event_reply
    if generation is not None:
        card_reply = _render_generation_query(name, generation)
        if card_reply is not None:
            return card_reply
        return _render_relic_generation_query(name, generation)
    return None


def _ancient_board_shape(text):
    snapshot = qq_renderer.load_sts2_ancient_choice_stats()
    return _parse_ancient_choice_request(snapshot, text) is not None


def _command_kind(text):
    """Recognized-command priority used for whitespace normalization.

    2 = pre-game families that own the reply (help / ancient overview /
    card layer boards / Boss boards / ancient boards / start / end);
    1 = generic name+generation query shape (idle unknown fallback);
    0 = not a command.
    """
    if not isinstance(text, str) or not text.strip():
        return 0
    if text.split(None, 1)[0].lower() in HELP_COMMANDS:
        return 2
    if text in ANCIENT_OVERVIEW_COMMANDS:
        return 2
    if _parse_boss_board_request(text) is not None:
        return 2
    if _parse_card_layer_rarity_request(text) is not None:
        return 2
    if _ancient_board_shape(text):
        return 2
    if _parse_start_request(text)[0] is not None:
        return 2
    if text in END_COMMANDS:
        return 2
    if text in RANDOM_EVENT_COMMANDS:
        return 2
    if _parse_typed_query(text) is not None:
        return 2
    _name, generation, _role = _parse_generation_selector(text)
    return 1 if generation is not None else 0


def _route_command_text(text):
    """Whitespace-normalised command text before the existing parser/router.

    Choose the highest-priority recognised spelling; on a tie the original
    text wins so bodies that rely on spaces (help subcommands, name+role
    queries) keep their exact behaviour.  When removing whitespace still
    hits a legal command, that compact spelling is treated as equivalent.
    """
    command = (text or "").strip()
    compact = _ROUTE_WS_RE.sub("", command)
    if compact == command:
        return command
    if compact in RANDOM_EVENT_COMMANDS:
        return compact
    if _command_kind(compact) > _command_kind(command):
        return compact
    return command

def _cross_generation_hint(name):
    return f"找到两代同名内容：\n{name}1\n{name}2"


def route_group_command(group_id, text, actor=None):
    command = _route_command_text(text)
    if command and command.split(None, 1)[0].lower() in HELP_COMMANDS:
        return render_help(command)

    active_event_reply = _active_event_session_reply(group_id, command, actor)
    if active_event_reply is not None:
        return active_event_reply

    typed_query = _render_typed_query(command)
    if typed_query is not None:
        return typed_query

    random_event = _render_random_event_reply(command, group_id)
    if random_event is not None:
        return random_event

    if command in ANCIENT_OVERVIEW_COMMANDS:
        return RenderedReply(
            qq_renderer.render_ancient_npc_overview(),
            image_path=qq_renderer.resolve_local_ancient_overview_image(),
        )

    boss_board = _render_boss_board_reply(command)
    if boss_board is not None:
        return RenderedReply(boss_board)

    layer_board = _render_card_layer_board_reply(command)
    if layer_board is not None:
        return RenderedReply(layer_board)

    ancient_board = _render_ancient_choice_leaderboard_reply(command)
    if ancient_board is not None:
        return ancient_board

    start_mode, start_character = _parse_start_request(command)

    if start_mode is not None:
        if sessions.get(group_id) is not None:
            return RenderedReply("当前会话已有一局")

        try:
            if start_character is None:
                game = sessions.start(group_id, start_mode)
                return RenderedReply(render_starting_puzzle(game))

            resolved_character = sessions.resolve_character(start_character)
            display = sessions.CHARACTER_DISPLAY.get(resolved_character, resolved_character)
            game = sessions.start(group_id, start_mode, character=resolved_character)
            return RenderedReply(render_starting_puzzle(game))
        except ValueError as exc:
            return RenderedReply(str(exc))

    if command in END_COMMANDS:
        game = sessions.get(group_id)
        if game is None:
            return RenderedReply("当前没有进行中的游戏")
        game.end()
        reply = render_terminal_reply(
            game,
            None,
            f"本局游戏结束\n正确答案：{_answer_name(game)}",
        )
        sessions.end(group_id)
        return reply

    game = sessions.get(group_id)
    if game is None:
        parsed_name, generation, role = _parse_generation_selector(command)
        if parsed_name is not None and generation is not None:
            reply = _render_untyped_query(parsed_name, generation, role)
            if reply is not None:
                return reply
            return RenderedReply(UNKNOWN_COMMAND_REPLY)

        if parsed_name is not None:
            reply = _render_untyped_query(parsed_name)
            if reply is not None:
                return reply
            return RenderedReply(UNKNOWN_COMMAND_REPLY)

        return RenderedReply(UNKNOWN_COMMAND_REPLY)

    parsed_name, generation, role = _parse_generation_selector(command)
    if parsed_name is not None and generation is not None:
        reply = _render_untyped_query(parsed_name, generation, role)
        if reply is not None:
            return reply

    result = game.handle_input(command)
    reply_text = _format_game_result(game, result)

    if game.ended:
        reply = render_terminal_reply(game, result, reply_text)
        sessions.end(group_id)
        return reply

    if result.status == "invalid":
        return RenderedReply(reply_text)

    return render_in_progress_reply(game, reply_text)


async def send_group_message(websocket, group_id: int, payload):
    from card_guess.qq import runtime

    request = {
        "action": "send_group_msg",
        "params": {
            "group_id": group_id,
            "message": payload,
        },
        "echo": "ping-reply",
    }

    timeout = getattr(runtime, "WS_SEND_TIMEOUT_SECONDS", 10.0)
    try:
        await asyncio.wait_for(websocket.send(json.dumps(request)), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("group message send timeout: %.1f seconds", timeout)
        raise


async def _send_group_reply(websocket, group_id: int, reply):
    if isinstance(reply, RenderedReply):
        image_paths = getattr(reply, "image_paths", None)
        if image_paths:
            await send_group_message(
                websocket,
                group_id,
                build_message_segments(reply.text, image_paths=image_paths),
            )
            return
        if reply.image_path is not None:
            await send_group_message(websocket, group_id, build_message_segments(reply.text, reply.image_path))
            return
    await send_group_message(websocket, group_id, str(reply))


async def send_private_message(websocket, user_id: int, payload):
    from card_guess.qq import runtime

    request = {
        "action": "send_private_msg",
        "params": {
            "user_id": user_id,
            "message": payload,
        },
        "echo": "ping-reply",
    }

    timeout = getattr(runtime, "WS_SEND_TIMEOUT_SECONDS", 10.0)
    try:
        await asyncio.wait_for(websocket.send(json.dumps(request)), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("private message send timeout: %.1f seconds", timeout)
        raise


async def _send_private_reply(websocket, user_id: int, reply):
    if isinstance(reply, RenderedReply):
        image_paths = getattr(reply, "image_paths", None)
        if image_paths:
            await send_private_message(
                websocket,
                user_id,
                build_message_segments(reply.text, image_paths=image_paths),
            )
            return
        if reply.image_path is not None:
            await send_private_message(
                websocket, user_id, build_message_segments(reply.text, reply.image_path)
            )
            return
    await send_private_message(websocket, user_id, str(reply))


async def handle_event(websocket, event: dict):
    if event.get("post_type") == "request":
        request_type = event.get("request_type")
        if request_type == "friend":
            flag = event.get("flag")
            if not flag:
                return
            await send_action(websocket, build_friend_add_request_action(flag, approve=True))
            print("accepted friend request")
            return

        if request_type == "group" and event.get("sub_type") == "invite":
            flag = event.get("flag")
            if not flag:
                return
            await send_action(websocket, build_group_add_request_action(flag, approve=True))
            print("accepted group invite")
            return

        return

    message_type = event.get("message_type")
    actor = None
    if message_type == "group":
        text = extract_mentioned_text(event)
        if text is None:
            return
        target_id = event["group_id"]
        send_message = send_group_message
        send_reply = _send_group_reply
        sender = event.get("sender")
        if isinstance(sender, dict):
            actor = sender.get("card") or sender.get("nickname")
    elif message_type == "private":
        text = extract_private_text(event)
        if text is None:
            return
        target_id = event.get("user_id")
        if target_id is None:
            return
        actor = "你"
        send_message = send_private_message
        send_reply = _send_private_reply
    else:
        return

    if text == "ping":
        await send_message(websocket, target_id, "pong")
        return

    reply = route_group_command(target_id, text, actor=actor)
    if reply:
        await send_reply(websocket, target_id, reply)

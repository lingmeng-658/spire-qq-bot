import asyncio
import json
import logging
import re

from card_guess.cards import find_cards_by_exact_name, load_cards
from card_guess.relics import find_relics_by_name, load_relics
from card_guess import leaderboard as lb
from card_guess.leaderboard import parse_leaderboard_keyword
from card_guess.puzzle import POOL_NAMES, format_rarity
from card_guess.qq import sessions
from card_guess.qq.onebot import (
    build_friend_add_request_action,
    build_group_add_request_action,
    build_message_segments,
    extract_mentioned_text,
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

START_WORDS = {"猜词", "猜谜", "开始", "开局", "开始游戏"}
START_SUFFIX_MODES = {"": "mixed", "1": "sts1", "2": "sts2"}
END_COMMANDS = {"结束", "end"}
HELP_TEXT = """=== 帮助 ===

开始猜卡：
开始 = 一二代混合
开始1 = 只猜一代    开始2 = 只猜二代

指定题库：
开始 猎宝    开始2 骨妹
开始 无色    开始1 事件

可指定：
角色：战士 / 猎宝 / 鸡煲 / 紫皮 / 骨妹 / 储君
特殊：无色 / 事件 / 任务 / 衍生

查卡：
直接发送完整卡名
跨代同名：卡名1 / 卡名2

榜单/数据排行：
猎宝1 抓取    猎宝1 抓取2
战士1 胜率3    骨妹2 抓取1
STS1 无数字 = 全局；STS2 仅 1/2/3 幕
心脏 = 打赢心脏的牌组出现率，仅 STS1（示例：猎宝1 心脏）

更多：
帮助 猜卡 / 帮助 查卡 / 帮助 题库 / 帮助 榜单"""
HELP_COMMANDS = {"帮助", "help"}


HELP_SUBCOMMANDS = {
    "猜卡": """=== 帮助 猜卡 ===

开始：
开始 = 一二代混合
开始1 = 只猜一代    开始2 = 只猜二代

指定题库：
开始 猎宝    开始2 骨妹
开始 无色    开始1 事件

猜测：直接发送卡名或描述片段
结束：发送 结束

提示：猜错累计后会自动揭示稀有度、描述、卡名等提示

猜卡进行中：
普通输入只作为猜测
完整卡名 + 1/2 可临时查卡""",
    "查卡": """=== 帮助 查卡 ===

直接发送完整卡名即可查卡

跨代同名：
愤怒 → 提示选择一代/二代
愤怒1 → 查一代    愤怒2 → 查二代

同代多版本：
打击2 → 列出二代各角色版本
打击2 铁甲战士 → 查对应角色版本

猜卡进行中：
普通卡名仍作为猜测
完整卡名 + 1/2（可加角色）才作为显式查卡

胜率差样本过少时不展示。""",
    "题库": """=== 帮助 题库 ===

不写1/2 = 一二代混合
写1/2 = 只使用对应代际

STS1：
铁甲战士（战士/战士哥）
静默猎手（猎宝/猎豹）
故障机器人（鸡煲/机宝）
观者（紫皮）

STS2：
铁甲战士（战士/战士哥）
静默猎手（猎宝/猎豹）
故障机器人（鸡煲/机宝）
死灵契约师（亡灵契约师/骨妹）
摄政王（储君）

特殊：
无色（无色牌） / 事件（事件牌）
任务（任务牌） / 衍生（衍生牌）

空格随意：
开始1猎宝 / 开始 1 猎宝 / 开始   2   无色""",
        "榜单": """=== 帮助 榜单 ===

数据排行（角色别名 + 版本 + 指标）：
猎宝1 抓取    猎宝1 抓取2
战士1 胜率3    骨妹2 抓取1
猎宝1 心脏

STS1：
抓取 / 胜率 = 全局（1-50 层全部奖励）
抓取1/2/3、胜率1/2/3 = 各幕
心脏 = 打赢心脏的牌组出现率（仅 STS1）
角色：战士 / 猎宝 / 鸡煲 / 观者

STS2：
抓取1/2/3、胜率1/2/3
暂不支持可靠全局口径（无数字会提示）
角色：战士 / 猎宝 / 鸡煲 / 骨妹 / 储君

不写角色 = 该代全部正常角色卡
胜率差样本过少时不展示。

旧命令（榜单1/2 …）仍兼容。""",
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





_ACT_PHRASE_NUMBERS = {"第一幕": 1, "第二幕": 2, "第三幕": 3}


def _act_number_in_text(text):
    if not isinstance(text, str):
        return None
    for phrase, number in _ACT_PHRASE_NUMBERS.items():
        if phrase in text:
            return number
    match = re.search(r"([123])\s*幕", text)
    if match is not None:
        return int(match.group(1))
    return None


def _leaderboard_metric_suffix_hint(example_prefix, metric_root, tail):
    """Copy when an act number was written as words or after the metric."""
    rest = tail[len(metric_root):]
    match = re.fullmatch(r"([0-9]*)(.*)", rest, re.S)
    digit_raw, junk = match.groups() if match is not None else ("", rest)
    if digit_raw and digit_raw not in {"1", "2", "3"}:
        return f"幕数仅支持 1/2/3。\n示例：{example_prefix} {metric_root}2"
    act_number = _act_number_in_text(junk)
    digit = int(digit_raw) if digit_raw in {"1", "2", "3"} else None
    target = digit if digit is not None else act_number
    if target is not None:
        return f"幕数请直接写在指标后：\n{example_prefix} {metric_root}{target}"
    return (
        f"榜单指标需为：{metric_root} 或 {metric_root}1/2/3。\n"
        f"示例：{example_prefix} {metric_root}2"
    )


def _short_leaderboard_regex():
    pattern = getattr(_short_leaderboard_regex, "pattern", None)
    if pattern is None:
        aliases = sorted(sessions.CHARACTER_ALIASES, key=len, reverse=True)
        pattern = "|".join(re.escape(alias) for alias in aliases)
        _short_leaderboard_regex.pattern = pattern
    return pattern


def _short_leaderboard_matchers():
    cached = getattr(_short_leaderboard_matchers, "cached", None)
    if cached is None:
        pattern = _short_leaderboard_regex()
        cached = (
            re.compile(rf"^({pattern})([12])\s*(抓取|胜率)([123]?)\s*$"),
            re.compile(rf"^({pattern})\s*((?:抓取|胜率)[123]?|心脏)\s*$"),
            re.compile(rf"^({pattern})([12])\s*(.+)$"),
        )
        _short_leaderboard_matchers.cached = cached
    return cached


def _render_short_leaderboard_reply(command):
    """Full-match short leaderboard commands (猎宝1 抓取 / 骨妹2 胜率3).

    Returns a reply string when the message is clearly a short leaderboard
    command, including near-misses like “猎宝2 胜率 第二幕” that must not be
    routed as a card guess; returns ``None`` otherwise.
    """
    full_re, no_gen_re, prefix_re = _short_leaderboard_matchers()
    full = full_re.fullmatch(command or "")
    if full is not None:
        alias, generation, metric, suffix = full.groups()
        keyword = f"{metric}{suffix or ''}"
        return lb.build_leaderboard_reply(generation, keyword, role=alias)
    no_gen = no_gen_re.fullmatch(command or "")
    if no_gen is not None:
        alias, keyword = no_gen.groups()
        try:
            pool = sessions.resolve_character(alias)
        except ValueError:
            return None
        generations = lb.pool_generations(pool)
        if not generations:
            return None
        if len(generations) > 1:
            return f"这个角色两代都有，请写 {alias}1 或 {alias}2。"
        generation = "1" if generations[0] == "sts1" else "2"
        return lb.build_leaderboard_reply(generation, keyword, role=alias)
    prefix = prefix_re.match(command or "")
    if prefix is None:
        return None
    alias, generation, tail = prefix.groups()
    tail = tail.strip()
    if tail == "心脏":
        return lb.build_leaderboard_reply(generation, "心脏", role=alias)
    metric_root = None
    for root in ("抓取", "胜率"):
        if tail.startswith(root):
            metric_root = root
            break
    if metric_root is None:
        return None
    return _leaderboard_metric_suffix_hint(f"{alias}{generation}", metric_root, tail)


def _render_leaderboard_reply(command):
    match = re.fullmatch(r"榜单([12])(?:\s+(.*))?", command)
    if match is None:
        return (
            "榜单语法：榜单1/2 [角色] 抓取|胜率（可加 1/2/3 幕）\n"
            "示例：榜单1 抓取 / 榜单2 猎宝 胜率2"
        )
    tag = match.group(1)
    rest = (match.group(2) or "").strip()
    if not rest:
        return "缺少榜单指标：抓取 / 胜率（可加 1/2/3 幕）\n示例：榜单1 抓取2"
    tokens = rest.split()
    keyword = tokens[-1]

    act_number = _act_number_in_text(rest)
    if act_number is not None:
        metric_token = next(
            (token for token in tokens if token in {"抓取", "胜率"}),
            None,
        )
        if metric_token is not None:
            others = [
                token
                for token in tokens
                if token not in {"抓取", "胜率"} and _act_number_in_text(token) is None
            ]
            prefix = " ".join(["榜单" + tag] + others)
            return f"幕数请直接写在指标后：\n{prefix} {metric_token}{act_number}"

    if keyword == "终局":
        role = " ".join(tokens[:-1]).strip() or None
        return lb.build_leaderboard_reply(tag, keyword, role)

    if keyword == "心脏":
        role = " ".join(tokens[:-1]).strip() or None
        return lb.build_leaderboard_reply(tag, keyword, role)

    if parse_leaderboard_keyword(keyword) is None:
        root = next(
            (
                root
                for root in ("抓取", "胜率")
                if keyword.startswith(root) and len(keyword) > len(root)
            ),
            None,
        )
        if root is not None:
            return (
                f"榜单仅支持 {root}1 / {root}2 / {root}3，不支持“{keyword}”。\n"
                f"示例：榜单{tag} {root}2"
            )
        return (
            "榜单指标需为：抓取 / 胜率（可加 1/2/3 幕）。\n"
            f"示例：榜单{tag} 抓取2 / 榜单{tag} 猎宝 胜率3"
        )
    role = " ".join(tokens[:-1]).strip() or None
    return lb.build_leaderboard_reply(tag, keyword, role)


def _load_query_cards():
    return load_cards("sts1") + load_cards("sts2")


def _find_exact_card_matches(name):
    return find_cards_by_exact_name(_load_query_cards(), name)


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
    return load_relics("sts1")


def _find_relics_by_name(name, generation=None):
    return find_relics_by_name(_load_query_relics(), name, generation=generation)


def _render_sts2_relic_unavailable(name):
    return (
        f"“{name}2”暂不可用：本阶段仅接入 STS1 遗物查询。\n"
        f"可发送：\n{name}1 —— 查看一代遗物"
    )


def _render_relic_generation_query(name, generation, role=None):
    """显式遗物查询（遗物名+1/2）。

    一代命中渲染遗物资料；二代命中且一代存在同名遗物时提示暂不可用。
    角色名仅用于卡牌消歧，遗物不支持角色参数；无命中返回 None 交给原流程。
    """
    if role is not None:
        return None

    sts1_matches = _find_relics_by_name(name, generation=1)
    if not sts1_matches:
        return None
    if generation == 2:
        return RenderedReply(_render_sts2_relic_unavailable(name))
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





def route_group_command(group_id, text):
    command = (text or "").strip()
    if command.split(None, 1)[0].lower() in HELP_COMMANDS:
        return render_help(command)

    if command.startswith("榜单"):
        return RenderedReply(_render_leaderboard_reply(command))

    short_board = _render_short_leaderboard_reply(command)
    if short_board is not None:
        return RenderedReply(short_board)

    start_mode, start_character = _parse_start_request(command)

    if start_mode is not None:
        if sessions.get(group_id) is not None:
            return RenderedReply("本群已有一局正在进行")

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

    if command in END_COMMANDS or command.lower() == "end":
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
            reply = _render_generation_query(parsed_name, generation, role)
            if reply is None:
                reply = _render_relic_generation_query(parsed_name, generation, role)
            if reply is not None:
                return reply
            return RenderedReply("当前没有进行中的游戏")

        if parsed_name is not None:
            all_matches = _find_cards_by_name(parsed_name)

            if len(all_matches) > 1:
                return RenderedReply(
                    f"“{parsed_name}”在杀戮尖塔 1 和 2 中都有对应卡牌。\n"
                    f"请发送：\n{parsed_name}1 —— 查看一代版本\n{parsed_name}2 —— 查看二代版本"
                )
            if all_matches:
                return render_card_query_reply(all_matches)

            relic_matches = _find_relics_by_name(parsed_name)
            if relic_matches:
                return render_relic_query_reply(relic_matches)
            return RenderedReply("当前没有进行中的游戏")

        matches = _find_exact_card_matches(command)
        if matches:
            if len(matches) > 1:
                return RenderedReply(
                    f"“{command}”在杀戮尖塔 1 和 2 中都有对应卡牌。\n"
                    f"请发送：\n{command}1 —— 查看一代版本\n{command}2 —— 查看二代版本"
                )
            return render_card_query_reply(matches)
        return RenderedReply("当前没有进行中的游戏")

    parsed_name, generation, role = _parse_generation_selector(command)
    if parsed_name is not None and generation is not None:
        reply = _render_generation_query(parsed_name, generation, role)
        if reply is None:
            reply = _render_relic_generation_query(parsed_name, generation, role)
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

    text = extract_mentioned_text(event)

    if text is None:
        return

    group_id = event["group_id"]

    if text == "ping":
        await send_group_message(websocket, group_id, "pong")
        return

    reply = route_group_command(group_id, text)
    if reply:
        await _send_group_reply(websocket, group_id, reply)

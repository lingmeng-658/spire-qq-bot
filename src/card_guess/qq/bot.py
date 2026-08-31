import json

from card_guess.cards import find_cards_by_exact_name, load_cards
from card_guess.puzzle import format_rarity
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
    render_starting_puzzle,
    render_terminal_reply,
    render_wrong_card_guess_reply,
)

START_WORDS = {"猜词", "猜谜", "开始", "开局", "开始游戏"}
START_SUFFIX_MODES = {"": "mixed", "1": "sts1", "2": "sts2"}
END_COMMANDS = {"结束", "end"}
HELP_TEXT = """故障机器人｜杀戮尖塔 1+2 猜卡

开局后会随机抽一张卡，并隐藏牌名和大部分描述。

@故障机器人 + 你想猜的内容
• 猜中描述 → 点亮对应内容
• 猜中牌名片段 → 揭开对应字符
• 猜错会累计，并自动获得提示
• 猜中完整牌名，或牌名全部揭开 → 获胜

【开局】
@故障机器人 猜词 / 猜词1 / 猜词2
→ 1+2混合 / 仅1 / 仅2

也可限定角色，原名或昵称都可以：
@故障机器人 猜词 鸡煲

一代：
铁甲战士/战士哥｜静默猎手/猎宝｜故障机器人/鸡煲｜观者/紫皮

二代：
铁甲战士｜静默猎手｜故障机器人｜摄政王/储君｜亡灵契约师/骨妹

@故障机器人 结束 → 结束当前游戏

现在可以 @故障机器人 猜词 开始游戏了。"""
HELP_COMMANDS = {"帮助", "help"}


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

        if command.startswith(word + " "):
            remainder = command[len(word):].strip()
            return START_SUFFIX_MODES[""], remainder or None

        rest = command[len(word):]
        if not rest:
            continue

        suffix = rest[0]
        if suffix not in START_SUFFIX_MODES:
            continue

        tail = rest[1:]
        if not tail:
            return START_SUFFIX_MODES[suffix], None
        if tail.startswith(" "):
            remainder = tail.strip()
            return START_SUFFIX_MODES[suffix], remainder or None

    return None, None


def route_group_command(group_id, text):
    command = (text or "").strip()
    if command in HELP_COMMANDS or command.lower() == "help":
        return HELP_TEXT

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
        matches = _find_exact_card_matches(command)
        if matches:
            return render_card_query_reply(matches)
        return RenderedReply("当前没有进行中的游戏")

    result = game.handle_input(command)
    reply_text = _format_game_result(game, result)

    if game.ended:
        reply = render_terminal_reply(game, result, reply_text)
        sessions.end(group_id)
        return reply

    if result.status == "invalid":
        return RenderedReply(reply_text)

    if result.status == "wrong":
        matches = _find_exact_card_matches(command)
        if matches:
            return render_wrong_card_guess_reply(game, reply_text, matches)

    return render_in_progress_reply(game, reply_text)


async def send_group_message(websocket, group_id: int, payload):
    request = {
        "action": "send_group_msg",
        "params": {
            "group_id": group_id,
            "message": payload,
        },
        "echo": "ping-reply",
    }

    await websocket.send(json.dumps(request))


async def _send_group_reply(websocket, group_id: int, reply):
    if isinstance(reply, RenderedReply) and reply.image_path is not None:
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

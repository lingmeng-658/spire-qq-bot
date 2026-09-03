from pathlib import Path

import pytest

from card_guess.game import GameState
from card_guess.qq import sessions


@pytest.fixture(autouse=True)
def clear_sessions():
    sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()


def make_card(name="Test Card", description="Deal 3 damage."):
    return {
        "name": name,
        "game": "sts1",
        "pool": "ironclad",
        "type": "Attack",
        "cost": 1,
        "star_cost": None,
        "rarity": "Common",
        "description": description,
        "vars": {},
    }


def test_start_creates_session_for_group_and_inits_from_cli_flow(monkeypatch):
    card = make_card("Strike")
    sentinel_positions = {1, 2, 3}

    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: [card])
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])
    monkeypatch.setattr(
        sessions,
        "find_opening_reveal_positions",
        lambda description: sentinel_positions,
    )

    game = sessions.start(101, "sts1")

    assert isinstance(game, GameState)
    assert sessions.get(101) is game
    assert game.card == card
    assert game.revealed_positions == sentinel_positions


def test_start_reuses_existing_session_for_same_group(monkeypatch):
    first_card = make_card("First Card")
    second_card = make_card("Second Card")

    def fake_cards(mode):
        return [first_card, second_card]

    monkeypatch.setattr(sessions, "load_game_cards", fake_cards)
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])
    monkeypatch.setattr(sessions, "find_opening_reveal_positions", lambda description: {9})

    first = sessions.start(42, "mixed")
    second = sessions.start(42, "sts2")

    assert second is first
    assert sessions.get(42) is first
    assert len(sessions.SESSIONS) == 1


def test_different_groups_have_independent_sessions(monkeypatch):
    card_a = make_card("A")
    card_b = make_card("B")

    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: [card_a] if mode == "sts1" else [card_b])
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])
    monkeypatch.setattr(sessions, "find_opening_reveal_positions", lambda description: {5})

    game_a = sessions.start(1, "sts1")
    game_b = sessions.start(2, "sts2")

    assert game_a is sessions.get(1)
    assert game_b is sessions.get(2)
    assert game_a is not game_b
    assert len(sessions.SESSIONS) == 2


def test_end_removes_session_for_group(monkeypatch):
    card = make_card("End Card")

    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: [card])
    monkeypatch.setattr(sessions.random, "choice", lambda cards: cards[0])
    monkeypatch.setattr(sessions, "find_opening_reveal_positions", lambda description: {4})

    game = sessions.start(7, "sts1")
    ended = sessions.end(7)

    assert ended is game
    assert sessions.get(7) is None
    assert 7 not in sessions.SESSIONS


def test_invalid_mode_raises_value_error():
    with pytest.raises(ValueError):
        sessions.start(9, "bad_mode")


def test_start_filters_cards_for_character(monkeypatch):
    cards = [
        {"name": "Ironclad Card", "pool": "ironclad", "game": "sts1", "description": "Deal 3 damage.", "vars": {}, "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common"},
        {"name": "Silent Card", "pool": "silent", "game": "sts1", "description": "Gain 5 block.", "vars": {}, "type": "Skill", "cost": 1, "star_cost": None, "rarity": "Common"},
    ]

    monkeypatch.setattr(sessions, "load_all_standard_cards", lambda mode: cards)
    monkeypatch.setattr(sessions.random, "choice", lambda items: items[0])
    monkeypatch.setattr(sessions, "find_opening_reveal_positions", lambda description: {1})

    game = sessions.start(20, "sts1", "铁甲战士")

    assert game.card["pool"] == "ironclad"
    assert game.card["name"] == "Ironclad Card"


def test_character_none_keeps_legacy_behavior(monkeypatch):
    cards = [
        {"name": "Mixed One", "pool": "ironclad", "game": "mixed", "description": "Deal 3 damage.", "vars": {}, "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common"},
        {"name": "Mixed Two", "pool": "silent", "game": "mixed", "description": "Gain 5 block.", "vars": {}, "type": "Skill", "cost": 1, "star_cost": None, "rarity": "Common"},
    ]

    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: cards)
    monkeypatch.setattr(sessions.random, "choice", lambda items: items[0])
    monkeypatch.setattr(sessions, "find_opening_reveal_positions", lambda description: {1})

    game = sessions.start(21, "mixed")

    assert game.card["name"] == "Mixed One"
    assert game.card["pool"] == "ironclad"


def test_start_raises_for_unknown_character_and_does_not_create_session(monkeypatch):
    monkeypatch.setattr(sessions, "load_game_cards", lambda mode: [{"name": "A", "pool": "ironclad", "game": "sts1", "description": "Deal 3 damage.", "vars": {}, "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common"}])

    with pytest.raises(ValueError):
        sessions.start(22, "sts1", "不存在的角色")

    assert sessions.get(22) is None


def test_resolve_character_accepts_original_names_and_aliases():
    assert sessions.resolve_character("铁甲战士") == "ironclad"
    assert sessions.resolve_character("战士哥") == "ironclad"
    assert sessions.resolve_character("静默猎手") == "silent"
    assert sessions.resolve_character("猎宝") == "silent"
    assert sessions.resolve_character("猎豹") == "silent"
    assert sessions.resolve_character("故障机器人") == "defect"
    assert sessions.resolve_character("鸡煲") == "defect"
    assert sessions.resolve_character("机宝") == "defect"
    assert sessions.resolve_character("观者") == "watcher"
    assert sessions.resolve_character("紫皮") == "watcher"
    assert sessions.resolve_character("摄政王") == "regent"
    assert sessions.resolve_character("储君") == "regent"
    assert sessions.resolve_character("亡灵契约师") == "necrobinder"
    assert sessions.resolve_character("骨妹") == "necrobinder"


def test_route_help_returns_fixed_text_and_does_not_change_active_session(monkeypatch):
    from card_guess.qq import bot

    fake_game = object()
    monkeypatch.setattr(sessions, "get", lambda group_id: fake_game)

    reply1 = bot.route_group_command(123, "帮助")
    reply2 = bot.route_group_command(123, "help")

    assert reply1 == bot.HELP_TEXT
    assert reply2 == bot.HELP_TEXT
    assert sessions.get(123) is fake_game


def test_route_help_guess_subcommand(monkeypatch):
    from card_guess.qq import bot

    reply = bot.route_group_command(123, "帮助 猜卡")

    assert "开始 = 一二代混合" in reply
    assert "开始1 = 只猜一代" in reply
    assert "开始2 = 只猜二代" in reply
    assert "指定题库" in reply
    assert "开始 猎宝" in reply
    assert "开始2 骨妹" in reply
    assert "猜测：直接发送卡名或描述片段" in reply
    assert "结束：发送 结束" in reply
    assert "提示：猜错累计后会自动揭示稀有度、描述、卡名等提示" in reply
    assert "猜卡进行中" in reply
    assert "普通输入只作为猜测" in reply
    assert "完整卡名 + 1/2 可临时查卡" in reply


def test_route_help_query_subcommand(monkeypatch):
    from card_guess.qq import bot

    reply = bot.route_group_command(123, "帮助 查卡")

    assert "直接发送完整卡名即可查卡" in reply
    assert "愤怒 → 提示选择一代/二代" in reply
    assert "愤怒1 → 查一代" in reply
    assert "愤怒2 → 查二代" in reply
    assert "打击2 → 列出二代各角色版本" in reply
    assert "打击2 铁甲战士 → 查对应角色版本" in reply
    assert "猜卡进行中" in reply
    assert "普通卡名仍作为猜测" in reply
    assert "完整卡名 + 1/2（可加角色）才作为显式查卡" in reply
    assert "胜率差样本过少时不展示。" in reply


def test_route_help_pools_subcommand(monkeypatch):
    from card_guess.qq import bot

    reply = bot.route_group_command(123, "帮助 题库")

    assert "不写1/2 = 一二代混合" in reply
    assert "写1/2 = 只使用对应代际" in reply
    assert "STS1：" in reply
    assert "铁甲战士（战士/战士哥）" in reply
    assert "静默猎手（猎宝/猎豹）" in reply
    assert "故障机器人（鸡煲/机宝）" in reply
    assert "观者（紫皮）" in reply
    assert "STS2：" in reply
    assert "死灵契约师（亡灵契约师/骨妹）" in reply
    assert "摄政王（储君）" in reply
    assert "无色（无色牌） / 事件（事件牌）" in reply
    assert "任务（任务牌） / 衍生（衍生牌）" in reply
    assert "开始1猎宝 / 开始 1 猎宝 / 开始   2   无色" in reply


def test_route_help_leaderboard_subcommand(monkeypatch):
    from card_guess.qq import bot

    reply = bot.route_group_command(123, "帮助 榜单")

    assert "=== 帮助 榜单 ===" in reply
    assert "猎宝1 抓取" in reply
    assert "猎宝1 抓取2" in reply
    assert "战士1 胜率3" in reply
    assert "骨妹2 抓取1" in reply
    assert "STS1：" in reply
    assert "抓取 / 胜率 = 全局（1-50 层全部奖励）" in reply
    assert "抓取1/2/3、胜率1/2/3 = 各幕" in reply
    assert "STS2：" in reply
    assert "暂不支持可靠全局口径（无数字会提示）" in reply
    assert "胜率差样本过少时不展示。" in reply
    assert "旧命令（榜单1/2 …）仍兼容。" in reply
    assert "终局" not in reply
    assert "榜单2 骨妹 终局" not in reply


def test_route_help_top_level_mentions_leaderboard(monkeypatch):
    from card_guess.qq import bot

    reply = bot.route_group_command(123, "帮助")

    assert "榜单/数据排行：" in reply
    assert "猎宝1 抓取" in reply
    assert "战士1 胜率3" in reply
    assert "骨妹2 抓取1" in reply
    assert "STS1 无数字 = 全局；STS2 仅 1/2/3 幕" in reply
    assert "帮助 榜单" in reply
    assert "终局" not in reply


def test_route_help_unknown_subcommand_lists_options(monkeypatch):
    from card_guess.qq import bot

    reply = bot.route_group_command(123, "\u5e2e\u52a9 abc")

    assert "abc" in reply
    assert "\u731c\u5361" in reply
    assert "\u67e5\u5361" in reply
    assert "\u9898\u5e93" in reply
    assert "\u699c\u5355" in reply


def test_route_replies_when_no_game_is_running(monkeypatch):
    monkeypatch.setattr(sessions, "get", lambda group_id: None)

    from card_guess.qq import bot

    reply = bot.route_group_command(123, "hello")

    assert reply == "当前没有进行中的游戏"


def test_route_rejects_duplicate_start_commands(monkeypatch):
    fake_game = object()
    monkeypatch.setattr(sessions, "get", lambda group_id: fake_game)

    from card_guess.qq import bot

    assert bot.route_group_command(123, "猜词") == "本群已有一局正在进行"
    assert bot.route_group_command(123, "猜词1") == "本群已有一局正在进行"
    assert bot.route_group_command(123, "猜词2") == "本群已有一局正在进行"


def test_route_delegates_guess_text_to_game_state(monkeypatch):
    class FakeResult:
        status = "wrong"
        hint_type = "description"

    fake_game = type("FakeGame", (), {"handle_input": lambda self, text: FakeResult(), "ended": False, "card": {"name": "Strike"}})()
    monkeypatch.setattr(sessions, "get", lambda group_id: fake_game)

    from card_guess.qq import bot

    reply = bot.route_group_command(321, "伤害")

    assert "提示" in reply or "伤害" in reply or "猜错" in reply


def test_route_starts_game_for_supported_modes(monkeypatch):
    from card_guess.qq import bot

    calls = []

    class FakeGame:
        def __init__(self):
            self.wrong_guesses = []
            self.total_guess_count = 0
            self.card = {"name": "Strike", "game": "sts1", "pool": "ironclad", "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common", "description": "Deal 3 damage."}

        def build_puzzle(self):
            return {"masked_name": "S□r□k□", "pool": "铁甲战士", "type": "攻击牌", "cost": "1", "star_cost": None, "masked_description": "Deal 3 damage.", "rarity": None}

    def fake_start(group_id, mode, character=None):
        calls.append((group_id, mode, character))
        return FakeGame()

    monkeypatch.setattr(sessions, "start", fake_start)
    monkeypatch.setattr(sessions, "get", lambda group_id: None)

    reply1 = bot.route_group_command(50, "猜词")
    reply2 = bot.route_group_command(50, "猜词1")
    reply3 = bot.route_group_command(50, "猜词2")
    reply4 = bot.route_group_command(50, "猜词1 铁甲战士")

    assert "牌名：" in reply1
    assert "牌名：" in reply2
    assert "牌名：" in reply3
    assert "牌名：" in reply4
    assert calls == [(50, "mixed", None), (50, "sts1", None), (50, "sts2", None), (50, "sts1", "ironclad")]


def test_route_reports_unknown_character_without_creating_session(monkeypatch):
    monkeypatch.setattr(sessions, "get", lambda group_id: None)

    from card_guess.qq import bot

    reply = bot.route_group_command(88, "猜词1 天外来客")

    assert "角色" in reply and "天外来客" in reply


def test_route_start_shows_initial_puzzle_and_status(monkeypatch):
    from card_guess.qq import bot

    class FakeGame:
        def __init__(self):
            self.card = {"name": "Strike", "game": "sts1", "pool": "ironclad", "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common", "description": "Deal 3 damage."}
            self.revealed_positions = set()
            self.revealed_name_positions = set()
            self.rarity_revealed = False
            self.wrong_guesses = []
            self.total_guess_count = 0
            self.wrong_count = 0
            self.ended = False

        def build_puzzle(self):
            return {
                "masked_name": "□t□i□k□e",
                "pool": "铁甲战士",
                "type": "攻击牌",
                "cost": "1",
                "star_cost": None,
                "masked_description": "□eal 3 damage.",
                "rarity": None,
            }

    fake_game = FakeGame()
    monkeypatch.setattr(sessions, "get", lambda group_id: None)
    monkeypatch.setattr(sessions, "start", lambda group_id, mode, character=None: fake_game)

    reply = bot.route_group_command(77, "猜词")

    assert "牌名：□t□i□k□e" in reply
    assert "来源：铁甲战士" in reply
    assert "已猜错：暂无" in reply
    assert "累计猜测：0 次" in reply
    assert "描述：" in reply


def test_route_start_keeps_wrong_and_total_guess_counts(monkeypatch):
    from card_guess.qq import bot

    class FakeGame:
        def __init__(self):
            self.card = {"name": "Strike", "game": "sts1", "pool": "ironclad", "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common", "description": "Deal 3 damage."}
            self.revealed_positions = set()
            self.revealed_name_positions = set()
            self.rarity_revealed = False
            self.wrong_guesses = ["oops"]
            self.total_guess_count = 9
            self.wrong_count = 1
            self.ended = False

        def build_puzzle(self):
            return {"masked_name": "S□r□k□", "pool": "铁甲战士", "type": "攻击牌", "cost": "1", "star_cost": None, "masked_description": "Deal 3 damage.", "rarity": None}

    fake_game = FakeGame()
    monkeypatch.setattr(sessions, "get", lambda group_id: None)
    monkeypatch.setattr(sessions, "start", lambda group_id, mode, character=None: fake_game)

    reply = bot.route_group_command(88, "猜词1")

    assert "已猜错：oops" in reply
    assert "累计猜测：9 次" in reply


def test_render_terminal_reply_uses_existing_card_image(monkeypatch):
    from card_guess.qq.renderer import RenderedReply, render_terminal_reply

    class FakeResult:
        status = "correct"

    game = type("Game", (), {"ended": True, "card": {"game": "sts1", "id": "STRIKE"}})()
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: Path("/tmp/STRIKE.png"))

    reply = render_terminal_reply(game, FakeResult(), "猜对了！答案就是：STRIKE")

    assert isinstance(reply, RenderedReply)
    assert reply == "猜对了！答案就是：STRIKE"
    assert reply.image_path == Path("/tmp/STRIKE.png")


def test_render_terminal_reply_missing_image_is_none(monkeypatch):
    from card_guess.qq.renderer import RenderedReply, render_terminal_reply

    class FakeResult:
        status = "wrong"

    game = type("Game", (), {"ended": True, "card": {"game": "sts2", "id": "MAD_SCIENCE"}})()
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: None)

    reply = render_terminal_reply(game, FakeResult(), "本轮结束，正确答案是：MAD_SCIENCE")

    assert isinstance(reply, RenderedReply)
    assert reply == "本轮结束，正确答案是：MAD_SCIENCE"
    assert reply.image_path is None


def test_render_non_terminal_reply_has_no_image():
    from card_guess.qq.renderer import RenderedReply, render_terminal_reply

    class FakeResult:
        status = "wrong"

    game = type("Game", (), {"ended": False, "card": {"game": "sts1", "id": "STRIKE"}})()

    reply = render_terminal_reply(game, FakeResult(), "猜错了")

    assert isinstance(reply, RenderedReply)
    assert reply == "猜错了"
    assert reply.image_path is None


def test_onebot_builds_image_message_segment():
    from card_guess.qq.onebot import build_message_segments

    message = build_message_segments("答案：STRIKE", Path("/tmp/STRIKE.png"))

    assert message == [
        {"type": "text", "data": {"text": "答案：STRIKE"}},
        {"type": "image", "data": {"file": "/tmp/STRIKE.png"}},
    ]


def test_terminal_reply_clears_session_even_without_image(monkeypatch):
    from card_guess.qq import bot
    from card_guess.qq.renderer import RenderedReply

    class FakeResult:
        status = "correct"

    fake_game = type("Game", (), {"handle_input": lambda self, text: FakeResult(), "ended": True, "card": {"game": "sts1", "id": "STRIKE", "name": "STRIKE"}})()
    sessions.SESSIONS[999] = fake_game
    monkeypatch.setattr(bot, "_send_group_reply", lambda websocket, group_id, reply: None)
    monkeypatch.setattr("card_guess.qq.renderer.resolve_local_card_image", lambda card: None)

    reply = bot.route_group_command(999, "STRIKE")

    assert isinstance(reply, RenderedReply)
    assert reply.image_path is None
    assert sessions.get(999) is None


def test_handle_event_accepts_friend_request(monkeypatch):
    import asyncio

    from card_guess.qq import bot

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

    websocket = FakeSocket()
    event = {
        "post_type": "request",
        "request_type": "friend",
        "flag": "friend-flag-1",
        "user_id": 42,
    }

    async def run():
        await bot.handle_event(websocket, event)

    asyncio.run(run())

    assert websocket.sent
    payload = websocket.sent[0]
    assert "set_friend_add_request" in payload
    assert "approve" in payload
    assert "friend-flag-1" in payload


def test_handle_event_accepts_group_invite(monkeypatch):
    import asyncio

    from card_guess.qq import bot

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

    websocket = FakeSocket()
    event = {
        "post_type": "request",
        "request_type": "group",
        "sub_type": "invite",
        "flag": "group-flag-2",
        "group_id": 77,
    }

    async def run():
        await bot.handle_event(websocket, event)

    asyncio.run(run())

    assert websocket.sent
    payload = websocket.sent[0]
    assert "set_group_add_request" in payload
    assert "approve" in payload
    assert "group-flag-2" in payload


def test_handle_event_ignores_group_add_requests():
    import asyncio

    from card_guess.qq import bot

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

    websocket = FakeSocket()
    event = {
        "post_type": "request",
        "request_type": "group",
        "sub_type": "add",
        "flag": "ignore-me",
        "group_id": 99,
    }

    async def run():
        await bot.handle_event(websocket, event)

    asyncio.run(run())

    assert websocket.sent == []


def test_handle_event_keeps_game_message_routing_unchanged(monkeypatch):
    import asyncio

    from card_guess.qq import bot

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

    websocket = FakeSocket()
    event = {
        "post_type": "message",
        "message_type": "group",
        "self_id": 3671395251,
        "group_id": 55,
        "message": [
            {"type": "at", "data": {"qq": "3671395251"}},
            {"type": "text", "data": {"text": " ping"}},
        ],
    }

    async def run():
        await bot.handle_event(websocket, event)

    asyncio.run(run())

    assert websocket.sent
    assert "pong" in websocket.sent[0]


def test_handle_event_ignores_malformed_request_event():
    import asyncio

    from card_guess.qq import bot

    class FakeSocket:
        def __init__(self):
            self.sent = []

        async def send(self, payload):
            self.sent.append(payload)

    websocket = FakeSocket()
    event = {"post_type": "request", "request_type": "friend"}

    async def run():
        await bot.handle_event(websocket, event)

    asyncio.run(run())

    assert websocket.sent == []


def test_resolve_character_accepts_special_pool_aliases():
    assert sessions.resolve_character("任务") == "quest"
    assert sessions.resolve_character("任务牌") == "quest"
    assert sessions.resolve_character("衍生") == "token"
    assert sessions.resolve_character("衍生牌") == "token"
    assert sessions.resolve_character("无色牌") == "colorless"
    assert sessions.resolve_character("事件牌") == "event"
    assert sessions.resolve_character("无色") == "colorless"
    assert sessions.resolve_character("事件") == "event"


def test_start_with_empty_pool_raises_no_fallback_message(monkeypatch):
    cards = [
        {"name": "Ironclad Card", "pool": "ironclad", "game": "sts1", "description": "Deal 3 damage.", "vars": {}, "type": "Attack", "cost": 1, "star_cost": None, "rarity": "Common"},
    ]

    monkeypatch.setattr(sessions, "load_all_standard_cards", lambda mode: cards)

    with pytest.raises(ValueError, match="当前版本没有可用的该类题库"):
        sessions.start(23, "sts1", "任务")

    assert sessions.get(23) is None

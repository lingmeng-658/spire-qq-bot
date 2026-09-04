from card_guess.qq import bot, renderer
from card_guess.qq.renderer import RenderedReply


def make_relic(
    name="赤牛",
    relic_id="AKABEKO",
    name_en="Akabeko",
    tier="Common",
    description="每场战斗的第一回合，额外造成 8 点伤害。",
):
    return {
        "game": "sts1",
        "id": relic_id,
        "name": name,
        "name_en": name_en,
        "description": description,
        "description_en": "At the start of each combat, deal 8 additional damage.",
        "tier": tier,
        "color": None,
    }


def rate(value, numerator=None, denominator=None):
    metric = {"value": value, "unit": "percent"}
    if numerator is not None:
        metric["numerator"] = numerator
    if denominator is not None:
        metric["denominator"] = denominator
    return metric


def count(value):
    return {"value": value, "unit": "count"}


def make_snapshot(
    relic_id="AKABEKO",
    *,
    overall=3.58,
    overall_numerator=4216,
    overall_denominator=117728,
    roles=None,
    heart=15.27,
    heart_numerator=369,
    heart_denominator=2416,
    boss=None,
    has_boss_choice=True,
):
    if roles is None:
        roles = {
            "IRONCLAD": 3.24,
            "THE_SILENT": 2.94,
            "DEFECT": 3.41,
            "WATCHER": 5.68,
        }
    supported = list(roles)
    if len(supported) == 4:
        display_mode = "overall"
    elif len(supported) == 1:
        display_mode = "per_character"
    else:
        display_mode = "both"
    entry = {
        "overall": rate(overall, overall_numerator, overall_denominator),
        "per_character": {role: rate(value) for role, value in roles.items()},
        "supported_roles": supported,
        "display_mode": display_mode,
    }
    if heart is not None:
        entry["heart_win_presence_rate"] = rate(
            heart, heart_numerator, heart_denominator
        )
    if has_boss_choice:
        if boss is None:
            entry["boss_choice"] = {
                "act1": {
                    "offered_count": count(0),
                    "picked_count": count(0),
                },
                "act2": {
                    "offered_count": count(0),
                    "picked_count": count(0),
                },
            }
        else:
            entry["boss_choice"] = {
                "act1": {"pick_rate": rate(boss[0])},
                "act2": {"pick_rate": rate(boss[1])},
            }
    return {"relics": {relic_id: entry}}


def make_starter_snapshot(relic_id="BURNING_BLOOD"):
    return make_snapshot(
        relic_id,
        overall=29.21,
        overall_numerator=34389,
        overall_denominator=117728,
        roles={"IRONCLAD": 86.19},
        heart=25.08,
        heart_numerator=606,
        heart_denominator=2416,
    )


def patch_loader(monkeypatch, snapshot):
    monkeypatch.setattr(
        "card_guess.qq.renderer.load_sts1_relic_stats",
        lambda: snapshot,
    )


def patch_query_env(monkeypatch, relic=None, snapshot=None):
    cards = []
    relics = [relic] if relic is not None else []
    monkeypatch.setattr(bot, "_load_query_cards", lambda: cards, raising=False)
    monkeypatch.setattr(bot, "_load_query_relics", lambda: relics, raising=False)
    patch_loader(monkeypatch, snapshot if snapshot is not None else {})


def render_one(monkeypatch, relic, snapshot):
    patch_loader(monkeypatch, snapshot)
    return str(renderer.render_relic_query_reply([relic]))


# 1) 普通遗物：用完整解释句，不再出现内部指标名或逐行百分比
def test_common_relic_query_renders_readable_stats(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)
    reply = bot.route_group_command(101, relic["name"])

    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：\n每场战斗的第一回合，额外造成 8 点伤害。" in reply
    assert "稀有度：\n普通遗物" in reply
    assert (
        "在本次117728场对局统计中，有4216场结束时仍然携带它（3.58%）。"
        in reply
    )
    assert "各职业携带比例接近，没有明显职业偏好。" in reply
    assert (
        "在本次统计中，共有2416场对局成功击败心脏。\n"
        "其中369场结束时携带它（15.27%）。"
        in reply
    )
    # 内部指标名与旧格式都不应出现
    for banned in [
        "终局",
        "终局记录",
        "终局持有率",
        "角色分布",
        "心脏胜局出现率",
        "心脏局携带",
        "带着它",
        "铁甲：",
        "静默：",
        "机器人：",
        "观者：",
        "选择率",
    ]:
        assert banned not in reply
    assert reply.image_path is None


# 2) Boss 遗物：解释三选一与第一/二幕来源，保留真正有用的数字
def test_boss_relic_query_explains_three_choice_and_acts(monkeypatch):
    relic = make_relic(
        name="添水",
        relic_id="SOZU",
        name_en="Sozu",
        tier="Boss",
        description="你无法再获得药水。每场战斗开始时获得 1 点能量。",
    )
    snapshot = make_snapshot(
        "SOZU",
        overall=4.5,
        overall_numerator=5303,
        overall_denominator=117728,
        boss=(37.87, 33.69),
    )
    reply = render_one(monkeypatch, relic, snapshot)

    assert "=== 添水 · STS1 ===" in reply
    assert "稀有度：\nBoss 遗物" in reply
    assert "Boss奖励：" in reply
    assert "第一幕 Boss 奖励出现它时，约37.87%的玩家会选择。" in reply
    assert "第二幕 Boss 奖励出现它时，约33.69%的玩家会选择。" in reply
    for banned in [
        "第一幕选择率",
        "第二幕选择率",
        "选中率",
        "击败每幕 Boss",
        "终局",
    ]:
        assert banned not in reply


# 3) 中文名直接查询走遗物路由
def test_chinese_name_query_routes_to_relic_reply(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)

    reply = bot.route_group_command(101, "赤牛")

    assert isinstance(reply, RenderedReply)
    assert "=== 赤牛 · STS1 ===" in reply
    assert "没有明显职业偏好" in reply
    assert "心脏" in reply
    assert reply.image_path is None


# 4) 赤牛1：代际查询
def test_generation_suffix_1_queries_sts1_relic(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)

    reply = bot.route_group_command(101, "赤牛1")

    assert isinstance(reply, RenderedReply)
    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：" in reply


# 未来预留：赤牛2 只提示暂不可用
def test_generation_suffix_2_reports_sts2_not_available(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)

    reply = bot.route_group_command(101, "赤牛2")

    assert isinstance(reply, RenderedReply)
    assert "暂不可用" in reply
    assert "STS1" in reply
    assert "赤牛1" in reply
    assert "心脏" not in reply


# 5) 不存在遗物：维持通用未命中回复
def test_unknown_relic_name_keeps_unknown_input_reply(monkeypatch):
    patch_query_env(monkeypatch, relic=None, snapshot=None)

    reply = bot.route_group_command(101, "不存在的遗物")

    assert reply == "当前没有进行中的游戏"


# 6) 普通遗物没有 boss_choice 时完全不显示 Boss 信息
def test_common_relic_without_boss_choice_hides_boss_info(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO", has_boss_choice=False)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "没有明显职业偏好" in reply
    for banned in ["三选一", "选中率", "Boss 遗物：击败", "终局"]:
        assert banned not in reply


# 普通遗物即使带 boss_choice（无人 offer）也不显示 Boss 信息
def test_common_relic_with_zero_offers_hides_boss_choice_lines(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    reply = render_one(monkeypatch, relic, snapshot)

    assert "三选一" not in reply
    assert "选中率" not in reply


# 5) 初始遗物：简短解释来源路线，不编造替换统计
def test_starter_relic_shows_persistent_note_without_made_up_stats(monkeypatch):
    relic = make_relic(
        name="燃烧之血",
        relic_id="BURNING_BLOOD",
        name_en="Burning Blood",
        tier="Starter",
        description="在战斗结束时回复 6 点生命。",
    )
    snapshot = make_starter_snapshot("BURNING_BLOOD")
    reply = render_one(monkeypatch, relic, snapshot)

    assert "它几乎只出现在铁甲对局" in reply
    assert "34389场结束时仍然携带它（86.19%）" in reply
    assert "作为初始遗物，它通常会陪伴铁甲走完全程。" in reply
    assert "部分路线会替换初始遗物，所以不会达到100%。" in reply
    assert "初始遗物" in reply
    for banned in [
        "13.81%",
        "为何不是 100%",
        "不是 100%",
        "角色分布",
        "铁甲：",
        "终局",
    ]:
        assert banned not in reply


# 角色差异明显时：只说最突出的职业，不逐行刷百分比
def test_skewed_role_spread_mentions_top_role_without_row_dump(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot(
        "AKABEKO",
        overall=4.5,
        roles={
            "IRONCLAD": 12.0,
            "THE_SILENT": 2.0,
            "DEFECT": 2.2,
            "WATCHER": 2.5,
        },
    )
    reply = render_one(monkeypatch, relic, snapshot)

    assert "职业差异比较明显" in reply
    assert "铁甲携带比例最高" in reply
    assert "12.00%" in reply
    assert "没有明显职业偏好" not in reply
    for banned in ["静默：", "机器人：", "观者：", "角色分布"]:
        assert banned not in reply


# 心脏数字注明来自本次样本，分两行说明
def test_heart_context_names_current_sample_in_two_lines(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO", heart=9.5, heart_numerator=229, heart_denominator=2416)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "在本次统计中，共有2416场对局成功击败心脏。" in reply
    assert "其中229场结束时携带它（9.50%）。" in reply
    for banned in ["终局记录", "心脏胜局出现率", "心脏局携带"]:
        assert banned not in reply


# 遗物描述中的 [E] 必须转换为玩家语言，不输出原始能量标记
def test_relic_description_energy_token_renders_as_energy_text(monkeypatch):
    relic = make_relic(
        name="添水",
        relic_id="SOZU",
        name_en="Sozu",
        tier="Boss",
        description="你无法再获得药水。 在每回合开始时获得 [E] 。",
    )
    snapshot = make_snapshot("SOZU", boss=(37.87, 33.69))
    reply = render_one(monkeypatch, relic, snapshot)

    assert "效果：\n" in reply
    assert "1点能量" in reply
    assert "[E]" not in reply


# 连续 [E] [E] 合并为数量文本
def test_relic_description_multiple_energy_tokens_render_counted_text(monkeypatch):
    relic = make_relic(
        name="日晷",
        relic_id="SUNDIAL",
        name_en="Sundial",
        tier="Uncommon",
        description="你每洗牌 3 次，获得 [E] [E] 。",
    )
    snapshot = make_snapshot("SUNDIAL")
    reply = render_one(monkeypatch, relic, snapshot)

    assert "2点能量" in reply
    assert "[E]" not in reply

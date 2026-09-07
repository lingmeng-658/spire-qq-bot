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
    first_acquisition=None,
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
    if first_acquisition is not None:
        entry["first_acquisition"] = first_acquisition
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


def boss_act_counts(offered, picked):
    return {
        "offered_count": count(offered),
        "picked_count": count(picked),
        "pick_rate": rate(picked / offered * 100.0, picked, offered),
    }


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
    # 显式“遗物名2”查询读取二代目录；无参默认按二代缺失处理，保持测试自洽。
    monkeypatch.setattr(bot, "_load_sts2_query_relics", lambda: [], raising=False)
    patch_loader(monkeypatch, snapshot if snapshot is not None else {})


def render_one(monkeypatch, relic, snapshot):
    patch_loader(monkeypatch, snapshot)
    return str(renderer.render_relic_query_reply([relic]))


def acquisition(
    sample_size=3206,
    final_presence_runs=4216,
    *,
    coverage=None,
    median=13.0,
    p25=9.0,
    p75=27.0,
    act1=54.4,
    act2=27.9,
    act3=17.7,
):
    if coverage is None:
        coverage = sample_size / final_presence_runs * 100
    return {
        "sample_size": sample_size,
        "final_presence_runs": final_presence_runs,
        "coverage_rate": rate(coverage, sample_size, final_presence_runs),
        "median_floor": median,
        "p25_floor": p25,
        "p75_floor": p75,
        "act1_rate": rate(act1),
        "act2_rate": rate(act2),
        "act3_rate": rate(act3),
    }


# R5D: 普通遗物文案压缩为快速资料卡 -------------------------------------------

def test_common_relic_query_renders_condensed_stats(monkeypatch, tmp_path):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO", first_acquisition=acquisition())
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)
    # 图片根目录指向空临时目录，保证“无本地图”断言与真实 assets 无关
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path / "empty-repo")
    reply = bot.route_group_command(101, relic["name"])

    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：\n每场战斗的第一回合，额外造成 8 点伤害。" in reply
    assert "\n\n普通遗物" in reply
    assert "首次获得：通常第13层左右，约一半在第9～27层" in reply
    assert "最终携带：铁甲3.2% · 静默2.9% · 机器人3.4% · 观者5.7%" in reply
    for hidden in [
        "约3.6%的对局最后带着它。",
        "各职业使用比例接近。",
        "击败心脏的对局中约15.3%带着它。",
        "铁甲：",
        "角色分布",
        "获取时间比较分散",
        "超过一半来自",
    ]:
        assert hidden not in reply
    # R5D：删掉的冗余口径与旧格式都不应出现
    for banned in [
        "统计：",
        "稀有度：",
        "在本次117728场对局统计中",
        "在本次统计中，共有2416场对局成功击败心脏",
        "其中369场结束时携带它",
        "（3.58%）",
        "在有获取记录的对局中",
        "终局",
        "终局记录",
        "终局持有率",
        "心脏胜局出现率",
        "心脏局携带",
        "携带比例接近",
        "静默：",
        "机器人：",
        "观者：",
        "选择率",
        "样本",
    ]:
        assert banned not in reply
    assert reply.image_path is None

def test_boss_relic_query_condensed(monkeypatch):
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
        boss=None,
        heart=10.1,
    )
    snapshot["relics"]["SOZU"]["boss_choice"] = {
        "act1": boss_act_counts(5000, 1894),
        "act2": boss_act_counts(5000, 1685),
    }
    reply = render_one(monkeypatch, relic, snapshot)

    assert "=== 添水 · STS1 ===" in reply
    assert "\n\nBoss 遗物\n\n" in reply
    assert "第一层 Boss 奖励：\n约37.9%会选，选择率第 1 / 1。" in reply
    assert "第二层 Boss 奖励：\n约33.7%会选，选择率第 1 / 1。" in reply
    assert "带着它。" not in reply
    assert "击败心脏" not in reply
    for banned in [
        "稀有度：",
        "统计：",
        "37.87",
        "33.69",
        "第一层选择率",
        "第二层选择率",
        "选中率",
        "击败每幕 Boss",
        "终局",
        "在有获取记录的对局中",
        "通常在第",
    ]:
        assert banned not in reply


def test_boss_relic_hides_first_acquisition_floor(monkeypatch):
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
        boss=None,
        heart=10.1,
        first_acquisition=acquisition(),
    )
    snapshot["relics"]["SOZU"]["boss_choice"] = {
        "act1": boss_act_counts(5000, 1894),
        "act2": boss_act_counts(5000, 1685),
    }
    reply = render_one(monkeypatch, relic, snapshot)

    assert "通常在第" not in reply
    assert "在有获取记录的对局中" not in reply
    assert "带着它。" not in reply
    assert "Boss奖励出现时：" not in reply
    assert "第一层 Boss 奖励：\n约37.9%会选，选择率第 1 / 1。" in reply
    assert "第二层 Boss 奖励：\n约33.7%会选，选择率第 1 / 1。" in reply


# 路由层：中文名直接查询走遗物路由 ---------------------------------------------

def test_chinese_name_query_routes_to_relic_reply(monkeypatch, tmp_path):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)
    monkeypatch.setattr(renderer, "REPO_ROOT", tmp_path / "empty-repo")

    reply = bot.route_group_command(101, "赤牛")

    assert isinstance(reply, RenderedReply)
    assert "=== 赤牛 · STS1 ===" in reply
    assert "各职业使用比例接近。" not in reply
    assert "心脏" not in reply
    assert "\n\n普通遗物" in reply
    assert reply.image_path is None


def test_generation_suffix_1_queries_sts1_relic(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)

    reply = bot.route_group_command(101, "赤牛1")

    assert isinstance(reply, RenderedReply)
    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：" in reply


def test_generation_suffix_2_falls_back_to_sts1_hint_when_sts2_missing(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    patch_query_env(monkeypatch, relic=relic, snapshot=snapshot)

    reply = bot.route_group_command(101, "赤牛2")

    assert isinstance(reply, RenderedReply)
    assert "“赤牛2”没有对应的二代遗物。" in reply
    assert "赤牛1" in reply
    assert "查看一代遗物" in reply
    assert "心脏" not in reply


def test_unknown_relic_name_keeps_unknown_input_reply(monkeypatch):
    patch_query_env(monkeypatch, relic=None, snapshot=None)

    reply = bot.route_group_command(101, "不存在的遗物")

    assert reply == bot.UNKNOWN_COMMAND_REPLY


# Boss 信息只在 Boss 遗物上有值且存在 offer 时展示 ------------------------------

def test_common_relic_without_boss_choice_hides_boss_info(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO", has_boss_choice=False)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "各职业使用比例接近。" not in reply
    assert "\n\n普通遗物" in reply
    for banned in ["Boss奖励出现时", "三选一", "选中率", "Boss 遗物：击败", "终局"]:
        assert banned not in reply


def test_common_relic_with_zero_offers_hides_boss_choice_lines(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    reply = render_one(monkeypatch, relic, snapshot)

    assert "Boss奖励出现时" not in reply
    assert "三选一" not in reply
    assert "选中率" not in reply


# 初始遗物：保留简短“为什么不是100%”解释 ---------------------------------------

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

    assert "\n\n初始遗物\n\n" in reply
    assert "铁甲的初始遗物。\n部分路线会将它替换。" in reply
    assert "带着它。" not in reply
    assert "击败心脏" not in reply
    assert "首次获得" not in reply
    assert "最终携带" not in reply
    assert "%" not in reply
    for banned in [
        "13.81%",
        "为何不是 100%",
        "不是 100%",
        "角色分布",
        "铁甲：",
        "终局",
        "统计：",
        "稀有度：",
        "34389场",
        "（86.19%）",
    ]:
        assert banned not in reply

def test_common_relic_presence_row_shows_skewed_values_without_spread_talk(monkeypatch):
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

    assert "最终携带：铁甲12.0% · 静默2.0% · 机器人2.2% · 观者2.5%" in reply
    assert "职业差异比较明显" not in reply
    assert "铁甲使用比例最高" not in reply
    assert "各职业使用比例接近。" not in reply
    assert "\n\n普通遗物" in reply
    for banned in ["静默：", "机器人：", "观者：", "角色分布"]:
        assert banned not in reply

def test_heart_hold_hidden_from_default_common_display(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot(
        "AKABEKO", heart=9.5, heart_numerator=229, heart_denominator=2416
    )
    reply = render_one(monkeypatch, relic, snapshot)

    assert "击败心脏的对局中约9.5%带着它。" not in reply
    assert "带着它。" not in reply
    assert "在本次统计中，共有2416场对局成功击败心脏。" not in reply
    assert "其中229场结束时携带它（9.50%）。" not in reply
    assert "\n\n普通遗物" in reply
    assert "最终携带：铁甲3.2% · 静默2.9% · 机器人3.4% · 观者5.7%" in reply
    for banned in ["终局记录", "心脏胜局出现率", "心脏局携带", "击败心脏"]:
        assert banned not in reply

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


# R5B/R5D：获取时机（仅 Common/Uncommon/Rare，coverage 达到门槛才展示）

def test_relic_query_shows_acquisition_timing_when_data_present(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO", first_acquisition=acquisition())
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得：通常第13层左右，约一半在第9～27层" in reply
    assert "\n\n普通遗物" in reply
    assert "最终携带：铁甲3.2% · 静默2.9% · 机器人3.4% · 观者5.7%" in reply
    for banned in [
        "在有获取记录的对局中",
        "约一半集中在第9～27层，超过一半来自第一幕。",
        "约一半的记录落在",
        "超过一半的获取记录发生在",
        "超过一半来自",
        "获取时间比较分散",
        "sample_size",
        "coverage",
        "获取率",
        "掉落率",
        "终局",
        "第一幕",
        "第二幕",
        "第三幕",
    ]:
        assert banned not in reply

def test_relic_query_rounds_fractional_percentiles_when_showing(monkeypatch):
    relic = make_relic()
    fa = acquisition(median=12.5, p25=9.0, p75=27.5)
    snapshot = make_snapshot("AKABEKO", first_acquisition=fa)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得：通常第13层左右，约一半在第9～28层" in reply
    assert "12.5" not in reply
    assert "27.5" not in reply

def test_relic_query_timing_ignores_act_spread_commentary(monkeypatch):
    relic = make_relic()
    fa = acquisition(act1=40.0, act2=30.0, act3=30.0)
    snapshot = make_snapshot("AKABEKO", first_acquisition=fa)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得：通常第13层左右，约一半在第9～27层" in reply
    assert "获取时间比较分散" not in reply
    assert "超过一半来自" not in reply
    assert "三幕都有不少记录" not in reply

def test_relic_query_hides_acquisition_when_no_data(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO")
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得" not in reply
    assert "通常第" not in reply
    assert "最终携带：铁甲3.2% · 静默2.9% · 机器人3.4% · 观者5.7%" in reply
    assert "=== 赤牛 · STS1 ===" in reply
    assert "效果：" in reply

def test_relic_query_hides_acquisition_below_coverage_threshold(monkeypatch):
    relic = make_relic()
    fa = acquisition(coverage=10.0)
    snapshot = make_snapshot("AKABEKO", first_acquisition=fa)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得" not in reply
    assert "通常第" not in reply
    assert "\n\n普通遗物" in reply
    assert "最终携带：铁甲3.2% · 静默2.9% · 机器人3.4% · 观者5.7%" in reply

def test_relic_query_shows_acquisition_at_sufficient_coverage(monkeypatch):
    relic = make_relic()
    fa = acquisition(coverage=90.0)
    snapshot = make_snapshot("AKABEKO", first_acquisition=fa)
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得：通常第13层左右，约一半在第9～27层" in reply
    assert "\n\n普通遗物" in reply
    assert "最终携带：铁甲3.2% · 静默2.9% · 机器人3.4% · 观者5.7%" in reply

def test_relic_query_never_shows_acquisition_for_non_eligible_tier(monkeypatch):
    relic = make_relic(tier="Starter", relic_id="BURNING_BLOOD", name="燃烧之血")
    fa = acquisition()
    snapshot = make_snapshot(
        "BURNING_BLOOD",
        first_acquisition=fa,
        roles={"IRONCLAD": 86.19},
    )
    reply = render_one(monkeypatch, relic, snapshot)

    assert "首次获得" not in reply
    assert "最终携带" not in reply
    assert "通常第" not in reply
    assert "%" not in reply
    assert "铁甲的初始遗物。\n部分路线会将它替换。" in reply
def test_common_relic_presence_row_lists_only_supported_roles(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot(
        "AKABEKO",
        roles={
            "IRONCLAD": 6.0,
            "THE_SILENT": 4.0,
        },
    )
    reply = render_one(monkeypatch, relic, snapshot)

    assert "最终携带：铁甲6.0% · 静默4.0%" in reply
    after = reply.split("最终携带", 1)[1]
    assert "机器人" not in after
    assert "观者" not in after


def test_common_relic_presence_row_hidden_when_no_role_metrics(monkeypatch):
    relic = make_relic()
    snapshot = make_snapshot("AKABEKO", roles={})
    reply = render_one(monkeypatch, relic, snapshot)

    assert "最终携带" not in reply
    assert "\n\n普通遗物" in reply

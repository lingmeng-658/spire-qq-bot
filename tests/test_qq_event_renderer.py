"""Event QQ presentation tests.

Synthetic records exercise formatting boundaries; the frozen catalog is used
only for the required integration examples already audited by Event Data Core.
"""

from __future__ import annotations

from card_guess.events import EventChoice, EventRecord, get_event


def make_choice(
    choice_id="TAKE",
    text="拿取",
    description="获得[green]6[/green]点最大生命。",
    *,
    result="不应显示的结果叙事",
    locked=None,
):
    return EventChoice(
        id=choice_id,
        text_zh=text,
        description_zh=description,
        result_zh=result,
        locked_zh=locked,
        raw={"id": choice_id},
    )


def make_event(
    *,
    game="sts2",
    event_id="FIXTURE_EVENT",
    name="虚构事件",
    pool="act_specific",
    act=1,
    description="带有[red]颜色[/red]的短正文。",
    choices=None,
    raw=None,
):
    return EventRecord(
        game=game,
        id=event_id,
        name_zh=name,
        name_en="Fixture Event",
        category="Event",
        act=act,
        pool=pool,
        description_zh=description,
        choices=tuple(choices if choices is not None else (make_choice(),)),
        raw=raw or {"pages": [{"description": "不应展开的后续页面"}]},
    )


def test_strip_bbcode_keeps_inner_text_numbers_and_punctuation():
    from card_guess.event_presentation import strip_event_bbcode

    text = "获得[green]6[/green]点生命，[jitter][red]小心！[/red][/jitter]"

    assert strip_event_bbcode(text) == "获得6点生命，小心！"


def test_short_event_description_is_not_truncated():
    from card_guess.event_presentation import truncate_event_description

    assert truncate_event_description("这是一段短正文。") == "这是一段短正文。"


def test_long_event_description_prefers_sentence_boundary_and_adds_ellipsis():
    from card_guess.event_presentation import truncate_event_description

    text = "甲" * 125 + "。" + "乙" * 40

    assert truncate_event_description(text) == "甲" * 125 + "。……"


def test_render_event_uses_player_facing_title_and_current_choices_only():
    from card_guess.event_presentation import render_event

    reply = render_event(make_event())

    assert reply.startswith("【虚构事件｜STS2 · 第一层】\n\n带有颜色的短正文。")
    assert "\n\n选择：\n1. 拿取 —— 获得6点最大生命。" in reply
    assert "结果叙事" not in reply
    assert "后续页面" not in reply
    assert "幕" not in reply


def test_render_event_maps_non_act_pools_without_inventing_a_layer():
    from card_guess.event_presentation import render_event

    shrine = render_event(make_event(game="sts1", pool="shrine", act=None))
    shared = render_event(make_event(pool="shared", act=None))
    ancient = render_event(make_event(pool="ancient", act=None, choices=[]))

    assert shrine.startswith("【虚构事件｜STS1 · 神龛】")
    assert shared.startswith("【虚构事件｜STS2 · 共享事件】")
    assert ancient.startswith("【虚构事件｜STS2 · 先古遗民】")
    assert "第一层" not in ancient


def test_locked_choice_merges_by_exact_id_without_taking_a_number():
    from card_guess.event_presentation import render_event

    event = make_event(
        choices=[
            make_choice("BASE", "主选项", "支付55金币。"),
            make_choice(
                "BASE_LOCKED",
                "锁定",
                None,
                result=None,
                locked="需要[blue]55[/blue]金币。",
            ),
            make_choice("OTHER", "另一项", None, result=None),
        ]
    )

    reply = render_event(event)

    assert "1. 主选项 —— 支付55金币。（需要55金币）" in reply
    assert "2. 另一项" in reply
    assert "3." not in reply
    assert "锁定" not in reply


def test_orphan_locked_choice_is_skipped_instead_of_mismerged():
    from card_guess.event_presentation import render_event

    event = make_event(
        choices=[
            make_choice("FIRST", "第一项", "效果甲。"),
            make_choice(
                "MISSING_LOCKED",
                "锁定",
                None,
                result=None,
                locked="需要99金币。",
            ),
            make_choice("SECOND", "第二项", "效果乙。"),
        ]
    )

    reply = render_event(event)

    assert "1. 第一项 —— 效果甲。" in reply
    assert "2. 第二项 —— 效果乙。" in reply
    assert "99金币" not in reply
    assert "锁定" not in reply


def test_event_without_choices_has_no_empty_choice_heading():
    from card_guess.event_presentation import render_event

    reply = render_event(make_event(pool="ancient", act=None, choices=[]))

    assert "选择：" not in reply


def test_big_fish_renders_recovered_static_values():
    from card_guess.event_presentation import render_event

    reply = render_event(get_event("sts1", "BIG_FISH"))

    assert "回复最大生命值的 1/3" in reply
    assert "最大生命值 +5" in reply


def test_waterlogged_scriptorium_merges_real_locked_rows():
    from card_guess.event_presentation import render_event

    reply = render_event(get_event("sts2", "WATERLOGGED_SCRIPTORIUM"))

    assert "触手羽毛笔" in reply and "（需要55金币）" in reply
    assert "扎手海绵" in reply and "（需要99金币）" in reply
    assert "2. 锁定" not in reply
    assert "4. 锁定" not in reply


def test_sts2_result_and_pages_are_not_rendered():
    from card_guess.event_presentation import render_event

    event = get_event("sts2", "COLOSSAL_FLOWER")
    reply = render_event(event)

    assert event.choices[1].result_zh not in reply
    assert event.raw["pages"][0]["description"] not in reply


def test_fixed_sts1_event_rewards_show_catalog_effects_on_first_screen():
    from card_guess.event_presentation import render_event
    from card_guess.relics import load_relics
    from card_guess.qq.relic_short_summary import short_relic_effect

    relics = {item["id"]: item for item in load_relics("sts1")}
    cases = {
        "DRUG_DEALER": ("MUTAGENICSTRENGTH", "CIRCLET"),
        "N_LOTH": ("NLOTH_S_GIFT", "CIRCLET"),
        "ACCURSED_BLACKSMITH": ("WARPEDTONGS",),
        "TOMB_OF_LORD_RED_MASK": ("RED_MASK",),
    }
    for event_id, reward_ids in cases.items():
        reply = render_event(get_event("sts1", event_id))
        for relic_id in reward_ids:
            relic = relics[relic_id]
            assert relic["name"] in reply
            assert short_relic_effect(
                relic["description"], relic_id=relic_id, game="sts1"
            ) in reply


def test_random_relic_rewards_are_not_expanded_and_other_games_unchanged():
    from card_guess.event_presentation import render_event

    random_reply = render_event(get_event("sts1", "THE_MAUSOLEUM"))
    assert "获得一件遗物" in random_reply
    assert "红面具" not in random_reply
    assert "突变之力" not in random_reply

    ordinary = make_event(game="sts1", event_id="ORDINARY")
    assert "效果：" not in render_event(ordinary)

    sts2_reply = render_event(get_event("sts2", "COLOSSAL_FLOWER"))
    assert "突变之力" not in sts2_reply

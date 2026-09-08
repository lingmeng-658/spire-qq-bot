"""Event Text Polish v1 regression tests.

The frozen STS2 catalog is used only for the required text-quality smoke
examples; every behavioral/merge test uses fixture records.
"""

from __future__ import annotations

from card_guess.event_presentation import (
    render_event,
    render_event_choice_outcome,
    strip_event_bbcode,
)
from card_guess.event_text_polish import (
    build_choice_archive_map,
    normalize_max_hp_percent,
)
from card_guess.events import EventChoice, EventRecord, get_event, load_events


KNOWN_EVENT_TAGS = (
    "aqua",
    "b",
    "blue",
    "gold",
    "green",
    "jitter",
    "orange",
    "purple",
    "red",
    "sine",
)


def make_event(
    *,
    event_id="FIXTURE",
    description="正文",
    choices=(),
) -> EventRecord:
    return EventRecord(
        game="sts2",
        id=event_id,
        name_zh="虚构事件",
        name_en="Fixture Event",
        category="Event",
        act=None,
        pool="shared",
        description_zh=description,
        choices=tuple(choices),
        raw={"id": event_id, "options": []},
    )


# Cleaner: b / orange / inner text / runtime tokens ---------------------------


def test_cleaner_strips_b_and_orange_preserving_inner_text():
    text = "获得[b]2[/b]点生命，[orange]火焰[/orange]升起。"

    assert strip_event_bbcode(text) == "获得2点生命，火焰升起。"


def test_cleaner_does_not_delete_runtime_square_bracket_tokens():
    text = "[AromaPrinciple]\n[EntrantNumber]\n[Monologue]"

    assert strip_event_bbcode(text) == text


def test_max_hp_percent_normalization_is_generic_and_targeted():
    assert (
        normalize_max_hp_percent(
            "回复[green]30% Max[/green]点生命。[red]进入战斗[/red]。"
        )
        == "回复最大生命值的30%。进入战斗。"
    )
    assert normalize_max_hp_percent("回复[green]33% Max[/green]点生命。") == (
        "回复最大生命值的33%。"
    )
    assert normalize_max_hp_percent("unrelated") == "unrelated"


# Frozen catalog: known markup can never reach QQ -----------------------------


def test_all_sts2_events_render_without_known_bbcode():
    catalog = load_events("sts2")

    for event in catalog.events:
        screens = [render_event(event)]
        for choice in event.choices:
            if (choice.id or "").endswith("_LOCKED"):
                continue
            screens.append(render_event_choice_outcome(choice, "测试"))
        for output in screens:
            for tag in KNOWN_EVENT_TAGS:
                assert f"[{tag}]" not in output
                assert f"[/{tag}]" not in output


# Real smoke: STONE_OF_ALL_TIME -----------------------------------------------


def test_stone_event_screen_and_results_no_longer_leak_raw_text():
    event = get_event("sts2", "STONE_OF_ALL_TIME")

    screen = render_event(event)
    assert "[b]" not in screen and "[/b]" not in screen
    assert "永恒之石" in screen
    assert "失去随机药水" in screen
    assert "a random Potion" not in screen
    assert "获得10最大生命" in screen  # official-zh unit issue is unresolved

    outcome = render_event_choice_outcome(event.choices[0], "群友甲")
    assert "a random Potion" not in outcome
    assert "随机药水" in outcome


def test_stone_raw_payload_is_preserved_untouched():
    event = get_event("sts2", "STONE_OF_ALL_TIME")
    raw_description = event.raw["description"]
    raw_choice = next(
        choice.raw
        for choice in event.choices
        if choice.id == "LIFT"
    )

    assert "[gold][b]永恒之石[/b][/gold]" in raw_description
    assert "a random Potion" in raw_choice["description"]
    assert "获得[blue]10[/blue]最大生命" in raw_choice["description"]


# Real smoke: official zh archive replacements ---------------------------------


def test_relic_trader_uses_archive_zh_without_english_fragments():
    screen = render_event(get_event("sts2", "RELIC_TRADER"))

    assert "用你的遗物换新遗物" in screen
    assert "one of your Relics" not in screen
    assert "a random Relic" not in screen


def test_ranwid_uses_stable_choice_ids_not_archive_index_order():
    event = get_event("sts2", "RANWID_THE_ELDER")
    by_id = {choice.id: choice for choice in event.choices}

    assert by_id["POTION"].text_zh == "给他药水"
    assert by_id["POTION"].result_zh is not None
    assert "Potion" not in (by_id["POTION"].result_zh or "")
    assert by_id["RELIC"].text_zh == "给他遗物"
    assert "Relic" not in (by_id["RELIC"].result_zh or "")
    # GOLD has no archive zh row with a stable en title match; raw stays.
    assert by_id["GOLD"].text_zh == "给他100金币"


def test_future_of_potions_does_not_leak_common_or_commonskill():
    screen = render_event(get_event("sts2", "THE_FUTURE_OF_POTIONS"))

    assert "放入普通药水" in screen
    assert "CommonSkill" not in screen
    assert "a Potion" not in screen
    assert "Common" not in screen


# Known unresolved rows must be preserved, not guessed --------------------------


def test_percent_max_is_resolved_in_final_renderer_output():
    dense = render_event(get_event("sts2", "DENSE_VEGETATION"))
    spiral = render_event(get_event("sts2", "SPIRALING_WHIRLPOOL"))

    assert "回复最大生命值的30%" in dense
    assert "回复最大生命值的33%" in spiral
    assert "% Max" not in dense
    assert "% Max" not in spiral


def test_known_unresolved_text_is_not_auto_fixed():
    assert "Obtain" in render_event(get_event("sts2", "HUNGRY_FOR_MUSHROOMS"))
    assert "A suspicious merchant" in render_event(
        get_event("sts2", "FAKE_MERCHANT")
    )


def test_official_zh_unit_issues_stay_unchanged():
    sapphire = get_event("sts2", "SAPPHIRE_SEED").choices[0]
    assert "回复9生命" in sapphire.description_zh


# Stable archive mapping helper ------------------------------------------------


def test_choice_archive_map_uses_en_title_keys_not_catalog_index():
    fixture_event = EventRecord(
        game="sts2",
        id="RANWID_THE_ELDER",
        name_zh="兰伟德",
        name_en="Ranwid the Elder",
        category="Event",
        act=None,
        pool="shared",
        description_zh="",
        choices=(
            EventChoice(
                id="POTION",
                text_zh="给他Potion",
                description_zh=None,
                result_zh=None,
                locked_zh=None,
                raw={"id": "POTION"},
            ),
            EventChoice(
                id="GOLD",
                text_zh="给他100金币",
                description_zh=None,
                result_zh=None,
                locked_zh=None,
                raw={"id": "GOLD"},
            ),
            EventChoice(
                id="RELIC",
                text_zh="给他Relic",
                description_zh=None,
                result_zh=None,
                locked_zh=None,
                raw={"id": "RELIC"},
            ),
        ),
        raw={"id": "RANWID_THE_ELDER"},
    )
    raw_en_event = {
        "id": "RANWID_THE_ELDER",
        "options": [
            {"id": "POTION", "title": "Give Potion"},
            {"id": "GOLD", "title": "Give 100 Gold"},
            {"id": "RELIC", "title": "Give Relic"},
        ],
    }
    archive_en_event = {
        "id": "RANWID_THE_ELDER",
        "choices": [
            {"name": "Give X Gold", "description": "x"},
            {"name": "Give Potion", "description": "p"},
            {"name": "Give Relic", "description": "r"},
        ],
    }
    archive_zh_event = {
        "choices": [
            {"name": "给他X金币", "description": "x中文"},
            {"name": "给他药水", "description": "p中文"},
            {"name": "给他遗物", "description": "r中文"},
        ]
    }

    mapping = build_choice_archive_map(
        catalog_event=fixture_event,
        raw_en_event=raw_en_event,
        archive_en_event=archive_en_event,
        archive_zh_event=archive_zh_event,
    )

    assert mapping["POTION"]["description"] == "p中文"
    assert mapping["RELIC"]["description"] == "r中文"
    assert "GOLD" not in mapping


def test_choice_archive_map_refuses_ambiguous_en_titles():
    fixture_event = make_event(
        choices=(
            EventChoice(
                id="A",
                text_zh="A",
                description_zh=None,
                result_zh=None,
                locked_zh=None,
                raw={"id": "A"},
            ),
            EventChoice(
                id="B",
                text_zh="B",
                description_zh=None,
                result_zh=None,
                locked_zh=None,
                raw={"id": "B"},
            ),
        )
    )
    raw_en_event = {
        "options": [
            {"id": "A", "title": "Same"},
            {"id": "B", "title": "Same"},
        ]
    }
    archive_en_event = {
        "choices": [{"name": "Same"}, {"name": "Same"}]
    }
    archive_zh_event = {
        "choices": [{"name": "甲"}, {"name": "乙"}]
    }

    assert build_choice_archive_map(
        catalog_event=fixture_event,
        raw_en_event=raw_en_event,
        archive_en_event=archive_en_event,
        archive_zh_event=archive_zh_event,
    ) == {}

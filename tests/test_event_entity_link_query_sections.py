"""Card and Relic query sections for reverse Event links."""

from __future__ import annotations

from card_guess.cards import load_cards
from card_guess.event_entity_links import (
    EventEntityLink,
    EventEntityLinkCondition,
)
from card_guess.events import EventChoice, EventRecord
from card_guess.qq import renderer
from card_guess.relics import load_relics


def _entity(items, entity_id):
    return next(item for item in items if item["id"] == entity_id)


def _without_stats_or_images(monkeypatch):
    monkeypatch.setattr(renderer, "load_sts1_card_stats", lambda: {})
    monkeypatch.setattr(renderer, "load_sts1_relic_stats", lambda: {})
    monkeypatch.setattr(renderer, "resolve_local_card_image", lambda card: None)
    monkeypatch.setattr(renderer, "resolve_local_upgraded_card_image", lambda card: None)
    monkeypatch.setattr(renderer, "resolve_local_relic_image", lambda relic: None)


def test_circlet_relic_query_lists_both_fallback_events(monkeypatch):
    _without_stats_or_images(monkeypatch)
    circlet = _entity(load_relics("sts1"), "CIRCLET")

    reply = str(renderer.render_relic_query_reply([circlet]))

    assert "事件关联：" in reply
    assert "增益研究者：已拥有「突变之力」时改为获得" in reply
    assert "恩洛斯：已拥有「恩洛斯的礼物」时改为获得" in reply


def test_golden_idol_relic_query_lists_gain_and_offering_events(monkeypatch):
    _without_stats_or_images(monkeypatch)
    idol = _entity(load_relics("sts1"), "GOLDEN_IDOL")

    reply = str(renderer.render_relic_query_reply([idol]))

    assert "金神像：可获得" in reply
    assert "摩艾石像：可献上「金神像」" in reply


def test_event_linked_cards_get_compact_reverse_sections(monkeypatch):
    _without_stats_or_images(monkeypatch)
    cards = load_cards("sts1")

    jax_reply = str(
        renderer.render_card_query_reply([_entity(cards, "J_A_X")])
    )
    bite_reply = str(
        renderer.render_card_query_reply([_entity(cards, "BITE")])
    )

    assert "事件关联：\n- 增益研究者：选择「试一下J.A.X.」可获得" in jax_reply
    assert "事件关联：\n- 吸血鬼（？）：移除所有打击后获得 5 张" in bite_reply


def test_unlinked_card_and_relic_do_not_show_empty_event_section(monkeypatch):
    _without_stats_or_images(monkeypatch)
    bash = _entity(load_cards("sts1"), "BASH")
    akabeko = _entity(load_relics("sts1"), "AKABEKO")

    assert "事件关联" not in str(renderer.render_card_query_reply([bash]))
    assert "事件关联" not in str(renderer.render_relic_query_reply([akabeko]))


def _fixture_event(event_id: str) -> EventRecord:
    choice = EventChoice(
        id=None,
        text_zh="拿取",
        description_zh="获得测试遗物。",
        result_zh=None,
        locked_zh=None,
        raw={"option": "[Take]"},
    )
    return EventRecord(
        game="sts1",
        id=event_id,
        name_zh=f"测试事件{event_id[-1]}",
        name_en=event_id,
        category="Event",
        act=1,
        pool="act_specific",
        description_zh="测试正文。",
        choices=(choice,),
        raw={},
    )


def test_more_than_three_events_show_first_three_and_one_overflow_line(monkeypatch):
    links = tuple(
        EventEntityLink(
            game="sts1",
            event_id=f"EVENT_{index}",
            entity_type="relic",
            entity_id="TEST_RELIC",
            relation="REWARD",
            condition=EventEntityLinkCondition(None, 0, None),
            source="fixture",
            evidence="fixture",
        )
        for index in range(5)
    )
    monkeypatch.setattr(renderer, "links_for_entity", lambda *args: links)
    monkeypatch.setattr(
        renderer, "get_event", lambda game, event_id: _fixture_event(event_id)
    )

    section = renderer.render_event_associations(
        {"game": "sts1", "id": "TEST_RELIC", "name": "测试遗物"},
        "relic",
    )

    assert section.splitlines() == [
        "事件关联：",
        "- 测试事件0：选择「拿取」可获得",
        "- 测试事件1：选择「拿取」可获得",
        "- 测试事件2：选择「拿取」可获得",
        "- 另有 2 个事件关联",
    ]

"""Event first-screen presentation backed by frozen entity links."""

from __future__ import annotations

import pytest

from card_guess.event_presentation import render_event
from card_guess.events import get_event
from card_guess.qq import bot, event_sessions, sessions


def _segment(text: str, start: str, end: str | None = None) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index) if end is not None else len(text)
    return text[start_index:end_index]


@pytest.fixture(autouse=True)
def clean_sessions():
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()
    yield
    sessions.SESSIONS.clear()
    event_sessions.SESSIONS.clear()


def test_drug_dealer_query_enriches_card_primary_relic_and_fallback_relic():
    reply = render_event(get_event("sts1", "DRUG_DEALER"), stats_snapshot={})

    jax = _segment(reply, "1. 试一下J.A.X.", "2. 当一下实验对象")
    assert "获得卡牌「J.A.X.」" in jax
    mutagens = _segment(reply, "3. 喝一下突变剂", "4. 离开")
    assert "获得遗物「突变之力」" in mutagens
    assert "若已拥有「突变之力」时：获得遗物「头环」" in mutagens
    assert mutagens.count("效果：") == 2


def test_random_interaction_first_screen_keeps_link_enrichment(monkeypatch):
    event = get_event("sts1", "DRUG_DEALER")
    monkeypatch.setattr(bot, "default_random_pool", lambda game: (event,))
    monkeypatch.setattr(bot.random, "choice", lambda choices: choices[0])

    reply = bot.route_group_command(101, "事件1")

    assert reply is not None
    text = str(reply)
    assert "获得卡牌「J.A.X.」" in text
    assert "获得遗物「突变之力」" in text
    assert "若已拥有「突变之力」时：获得遗物「头环」" in text
    assert event_sessions.get(101) is not None


def test_sts2_fixed_relic_link_keeps_catalog_name_and_short_effect():
    reply = render_event(
        get_event("sts2", "ROOM_FULL_OF_CHEESE"), stats_snapshot={}
    )

    search = _segment(reply, "2. 仔细翻找")
    assert "获得遗物「天选芝士」" in search
    assert "效果：" in search


def test_random_relic_choice_is_not_expanded_as_a_concrete_entity():
    reply = render_event(get_event("sts2", "UNREST_SITE"), stats_snapshot={})

    assert "随机遗物" in reply
    assert "获得遗物「" not in reply
    assert "效果：" not in reply

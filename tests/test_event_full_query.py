from card_guess.event_level2 import is_full_query_event
from card_guess.event_presentation import render_event_full_query
from card_guess.events import get_event
from card_guess.qq import bot


def test_slippery_bridge_full_query_shows_complete_loop_and_costs():
    text = render_event_full_query(get_event("sts2", "SLIPPERY_BRIDGE"))
    assert "再撑一会" in text
    assert "3" in text and "4" in text and "5" in text
    assert "11+" in text
    assert "事件结束" in text
    assert "循环" in text


def test_round_tea_party_full_query_includes_follow_up_page():
    text = render_event_full_query(get_event("sts2", "ROUND_TEA_PARTY"))
    assert "挑事斗殴" in text
    assert "继续" in text
    assert "喝杯好茶" in text


def test_single_stage_query_keeps_compact_renderer():
    text = render_event_full_query(get_event("sts2", "WELLSPRING"))
    assert "装瓶" in text
    assert "沐浴" in text
    assert "完整流程" not in text


def test_unreliable_multistage_event_is_not_presented_as_complete():
    text = render_event_full_query(get_event("sts2", "ABYSSAL_BATHS"))
    assert "数据不足以可靠展开完整流程" in text
    assert "LINGER1" not in text


def test_only_two_events_are_full_query_graphs():
    assert is_full_query_event(get_event("sts2", "SLIPPERY_BRIDGE"))
    assert is_full_query_event(get_event("sts2", "ROUND_TEA_PARTY"))
    assert not is_full_query_event(get_event("sts2", "ABYSSAL_BATHS"))


def test_query_route_uses_full_renderer_but_random_event_keeps_interactive_renderer(monkeypatch):
    event = get_event("sts2", "SLIPPERY_BRIDGE")
    seen = []
    monkeypatch.setattr(bot, "_find_events_by_name", lambda name, generation=None: [event])
    monkeypatch.setattr(bot, "plan_event_query", lambda value: value)
    monkeypatch.setattr(bot, "render_event_query", lambda value: seen.append("query") or "full")
    assert str(bot.route_group_command(101, event.name_zh)) == "full"

    monkeypatch.setattr(bot, "default_random_pool", lambda game: (event,))
    monkeypatch.setattr(bot.random, "choice", lambda pool: pool[0])
    monkeypatch.setattr(bot, "render_event", lambda value: seen.append("interactive") or "first screen")
    assert str(bot.route_group_command(102, "事件2")) == "first screen"
    assert seen == ["query", "interactive"]

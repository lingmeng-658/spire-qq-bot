import asyncio
import importlib.util
import json
import logging
from pathlib import Path

import pytest

from card_guess.qq import runtime

REPO_ROOT = Path(__file__).resolve().parents[1]
SPIKE_SCRIPT = REPO_ROOT / "scripts" / "qq_ws_spike.py"


class FakeDisconnect(Exception):
    pass


class FakeWebSocket:
    def __init__(self, messages=None, disconnect=True):
        self.messages = list(messages or [])
        self.disconnect = disconnect
        self.closed = False

    async def recv(self):
        if self.messages:
            return self.messages.pop(0)
        if self.disconnect:
            raise FakeDisconnect()
        raise asyncio.CancelledError()

    async def close(self):
        self.closed = True


def make_config(token="test-token"):
    return runtime.load_config({"NAPCAT_TOKEN": token})


def test_default_ws_url():
    assert runtime.DEFAULT_WS_URL == "ws://127.0.0.1:3001"
    assert make_config()["ws_url"] == "ws://127.0.0.1:3001"


def test_ws_url_can_be_overridden():
    config = runtime.load_config({
        "NAPCAT_TOKEN": "x",
        "NAPCAT_WS_URL": "ws://127.0.0.1:4000",
    })

    assert config["ws_url"] == "ws://127.0.0.1:4000"


def test_missing_token_fails_fast_without_leaking_value():
    with pytest.raises(RuntimeError) as exc_info:
        runtime.load_config({"NAPCAT_WS_URL": "ws://127.0.0.1:4000"})

    message = str(exc_info.value)
    assert "NAPCAT_TOKEN" in message
    assert "Bearer" not in message
    assert "secret" not in message.lower()


def test_first_connect_failure_sleeps_then_retries():
    connect_calls = 0

    async def fake_connect(config):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            raise ConnectionError("napcat down")
        raise asyncio.CancelledError()

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert connect_calls == 2
    assert sleeps == [runtime.backoff_delay(1)]


def test_disconnect_enters_reconnect_flow():
    connect_calls = 0

    async def fake_connect(config):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            return FakeWebSocket([])
        raise asyncio.CancelledError()

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert connect_calls == 2
    assert sleeps == [runtime.backoff_delay(1)]


def test_backoff_resets_after_successful_connect():
    connect_calls = 0

    async def fake_connect(config):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls == 1:
            raise ConnectionError("napcat down")
        if connect_calls == 2:
            return FakeWebSocket([])
        raise asyncio.CancelledError()

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert sleeps == [runtime.backoff_delay(1), runtime.backoff_delay(1)]


def test_consecutive_failures_backoff_is_bounded():
    async def fake_connect(config):
        raise ConnectionError("napcat down")

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 6:
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert sleeps == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert max(sleeps) <= 30.0


def test_received_event_is_forwarded_to_handle():
    seen = []

    async def fake_handle(websocket, event):
        seen.append(event)
        raise FakeDisconnect()

    async def fake_connect(config):
        return FakeWebSocket([json.dumps({"post_type": "message", "group_id": 1})])

    async def fake_sleep(seconds):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            handle=fake_handle,
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert seen == [{"post_type": "message", "group_id": 1}]


def test_event_handler_timeout_reconnects(monkeypatch):
    monkeypatch.setattr(runtime, "EVENT_HANDLER_TIMEOUT_SECONDS", 0.01, raising=False)
    reconnect_started = {"value": False}

    async def fake_handle(websocket, event):
        await asyncio.sleep(999)

    async def fake_connect(config):
        return FakeWebSocket([json.dumps({"post_type": "message", "group_id": 1})], disconnect=False)

    async def fake_sleep(seconds):
        reconnect_started["value"] = True
        raise asyncio.CancelledError()

    async def runner():
        await runtime.run_forever(make_config(), handle=fake_handle, connect=fake_connect, sleep=fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(asyncio.wait_for(runner(), timeout=1.0))

    assert reconnect_started["value"] is True


def test_websocket_send_timeout_reconnects(monkeypatch):
    monkeypatch.setattr(runtime, "WS_SEND_TIMEOUT_SECONDS", 0.01, raising=False)
    reconnect_started = {"value": False}

    class SlowSendWebSocket(FakeWebSocket):
        async def send(self, payload):
            await asyncio.sleep(999)

    async def fake_handle(websocket, event):
        from card_guess.qq.bot import handle_event

        await handle_event(websocket, {
            "post_type": "message",
            "message_type": "group",
            "self_id": 123,
            "group_id": 456,
            "message": [
                {"type": "at", "data": {"qq": "123"}},
                {"type": "text", "data": {"text": " ping"}},
            ],
        })

    async def fake_connect(config):
        return SlowSendWebSocket([
            json.dumps({
                "post_type": "message",
                "message_type": "group",
                "self_id": 123,
                "group_id": 456,
                "message": [
                    {"type": "at", "data": {"qq": "123"}},
                    {"type": "text", "data": {"text": " ping"}},
                ],
            })
        ], disconnect=False)

    async def fake_sleep(seconds):
        reconnect_started["value"] = True
        raise asyncio.CancelledError()

    async def runner():
        await runtime.run_forever(make_config(), handle=fake_handle, connect=fake_connect, sleep=fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(asyncio.wait_for(runner(), timeout=1.0))

    assert reconnect_started["value"] is True


def test_normal_handler_keeps_serial_order(monkeypatch):
    seen = []

    async def fake_handle(websocket, event):
        seen.append(event["id"])
        await asyncio.sleep(0)

    async def fake_connect(config):
        return FakeWebSocket([
            json.dumps({"id": 1}),
            json.dumps({"id": 2}),
        ], disconnect=False)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            handle=fake_handle,
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert seen == [1, 2]


def test_handler_exception_does_not_kill_runtime(monkeypatch):
    seen = []

    async def fake_handle(websocket, event):
        if event["id"] == 1:
            raise ValueError("boom")
        seen.append(event["id"])

    async def fake_connect(config):
        return FakeWebSocket([
            json.dumps({"id": 1}),
            json.dumps({"id": 2}),
        ], disconnect=False)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            handle=fake_handle,
            connect=fake_connect,
            sleep=fake_sleep,
        ))

    assert seen == [2]


def test_main_configures_logging_in_stable_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "LOG_DIR", tmp_path / "stable-logs", raising=False)
    monkeypatch.setattr(runtime, "_logging_configured", False)
    monkeypatch.setattr(runtime, "load_config", lambda env=None: {"token": "test-token", "ws_url": "ws://127.0.0.1:3001"})

    async def fake_run_forever(config):
        return None

    monkeypatch.setattr(runtime, "run_forever", fake_run_forever)

    runtime.main()

    log_path = tmp_path / "stable-logs" / "bot.log"
    assert log_path.exists()
    assert "test-token" not in log_path.read_text(encoding="utf-8", errors="replace")


def test_runtime_defaults_to_existing_bot_handle_event():
    from card_guess.qq.bot import handle_event

    assert runtime.handle_event is handle_event


def test_cancellation_propagates():
    async def fake_connect(config):
        raise asyncio.CancelledError()

    async def fake_sleep(seconds):
        raise AssertionError("should not sleep after cancel")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(runtime.run_forever(
            make_config(),
            connect=fake_connect,
            sleep=fake_sleep,
        ))


def test_keyboard_interrupt_propagates():
    async def fake_connect(config):
        raise KeyboardInterrupt()

    async def fake_sleep(seconds):
        raise AssertionError("should not sleep after KeyboardInterrupt")

    with pytest.raises(KeyboardInterrupt):
        asyncio.run(runtime.run_forever(
            make_config(),
            connect=fake_connect,
            sleep=fake_sleep,
        ))


def test_spike_script_reuses_runtime_main():
    spec = importlib.util.spec_from_file_location("qq_ws_spike", SPIKE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main is runtime.main


def test_logging_does_not_include_token(caplog):
    config = runtime.load_config({"NAPCAT_TOKEN": "super-secret-token"})

    async def fake_connect(config):
        raise ConnectionError("napcat down")

    async def fake_sleep(seconds):
        raise asyncio.CancelledError()

    with caplog.at_level(logging.INFO):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(runtime.run_forever(
                config,
                connect=fake_connect,
                sleep=fake_sleep,
            ))

    assert "super-secret-token" not in caplog.text

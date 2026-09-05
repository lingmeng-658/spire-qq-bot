import asyncio
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

import websockets

from card_guess.qq.bot import handle_event

DEFAULT_WS_URL = "ws://127.0.0.1:3001"
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 30.0
EVENT_HANDLER_TIMEOUT_SECONDS = 10.0
WS_SEND_TIMEOUT_SECONDS = 10.0
WS_CONNECT_TIMEOUT_SECONDS = 10.0
LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
LOG_FILE_NAME = "bot.log"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
SINGLE_INSTANCE_LOCK_PATH = LOG_DIR / "bot.lock"

logger = logging.getLogger("card_guess.qq.runtime")
_logging_configured = False


def load_config(env=None):
    if env is None:
        env = os.environ

    token = (env.get("NAPCAT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("NAPCAT_TOKEN 未设置")

    ws_url = (env.get("NAPCAT_WS_URL") or "").strip() or DEFAULT_WS_URL
    return {"token": token, "ws_url": ws_url}


def auth_headers(config):
    return {"Authorization": f"Bearer {config['token']}"}


def backoff_delay(attempt):
    return min(BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), BACKOFF_MAX_SECONDS)


async def connect_napcat(config):
    return await asyncio.wait_for(
        websockets.connect(
            config["ws_url"],
            additional_headers=auth_headers(config),
        ),
        timeout=WS_CONNECT_TIMEOUT_SECONDS,
    )


async def _receive_loop(websocket, handle):
    while True:
        message = await websocket.recv()

        try:
            event = json.loads(message)
        except Exception:
            logger.exception("事件消息解析失败")
            continue

        try:
            await asyncio.wait_for(
                handle(websocket, event),
                timeout=EVENT_HANDLER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "事件处理超时，当前连接将关闭并重连，超时秒数=%.1f",
                EVENT_HANDLER_TIMEOUT_SECONDS,
            )
            raise
        except Exception:
            logger.exception("处理事件时发生未预期异常")


async def run_forever(config, handle=None, connect=None, sleep=None):
    if handle is None:
        handle = handle_event
    if connect is None:
        connect = connect_napcat
    if sleep is None:
        sleep = asyncio.sleep

    connected = False
    failed_attempts = 0

    while True:
        try:
            websocket = await connect(config)
            if connected:
                logger.info("重连成功")
            else:
                logger.info("成功连接 NapCat")
            connected = True
            failed_attempts = 0

            try:
                await _receive_loop(websocket, handle)
            finally:
                close = getattr(websocket, "close", None)
                if close is not None:
                    await close()
        except asyncio.CancelledError:
            logger.info("正常关闭")
            raise
        except Exception:
            failed_attempts += 1
            logger.warning("WS 连接失败，准备重试")
            delay = backoff_delay(failed_attempts)
            logger.warning("将在 %.1f 秒后重试", delay)
            try:
                await sleep(delay)
            except asyncio.CancelledError:
                logger.info("正常关闭")
                raise


def configure_logging(log_dir=None):
    global _logging_configured

    if _logging_configured:
        return

    target_dir = Path(log_dir) if log_dir is not None else LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        target_dir / LOG_FILE_NAME,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    _logging_configured = True


class SingleInstanceLock:
    """Exclusive OS file lock held by the running bot process.

    Two live bot instances would each answer the same QQ message, so every
    relic (and other) query would be replied to twice.  The second instance
    refuses to start while the first one still holds the lock.
    """

    def __init__(self, path):
        self._path = Path(path)
        self._handle = None

    def acquire(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+", encoding="utf-8")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write("\0")
                handle.flush()
            handle.seek(0)
            if msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            elif fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError(
                f"已有 bot 实例在运行（锁文件：{self._path}），本次启动退出。"
            ) from None
        self._handle = handle
        return self

    def release(self):
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if msvcrt is not None:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def acquire_single_instance_lock(path=None):
    if path is None:
        path = SINGLE_INSTANCE_LOCK_PATH
    lock = SingleInstanceLock(path)
    lock.acquire()
    return lock


def main():
    config = load_config()
    configure_logging()
    lock = acquire_single_instance_lock()
    try:
        logger.info("runtime 启动")
        asyncio.run(run_forever(config))
    finally:
        lock.release()


if __name__ == "__main__":
    main()

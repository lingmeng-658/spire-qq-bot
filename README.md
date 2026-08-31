# card-guess-bot

杀戮尖塔 1+2 猜卡 QQ 机器人（OneBot / NapCat）。

## 本地启动

PowerShell：

```powershell
cd D:\Projects\card-guess-bot
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "src"
$env:NAPCAT_TOKEN = "<NapCat OneBot 反代 WS 的 Token>"
python -m card_guess.qq
```

也可以显式运行 runtime 模块：

```powershell
python -m card_guess.qq.runtime
```

默认连接 `ws://127.0.0.1:3001`，可用 `NAPCAT_WS_URL` 覆盖，例如：

```powershell
$env:NAPCAT_WS_URL = "ws://127.0.0.1:4000"
```

## 兼容入口

旧 spike 脚本保留为薄兼容入口，内部调用同一个 runtime：

```powershell
python scripts\qq_ws_spike.py
```

## 日志

运行日志同时输出到控制台和 `logs/bot.log`（UTF-8，5 MB 轮转，保留 3 份）。
日志不会记录 Token、Authorization header 或聊天正文。

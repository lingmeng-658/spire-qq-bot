from __future__ import annotations

import json
from pathlib import Path
from urllib import request

# 本阶段只接入 STS1 遗物图片；STS2 遗物不在范围内。
RELIC_GAMES = ("sts1",)
RELIC_IMAGE_BASE = "https://spire-archive.com/images"


def stable_relic_id(relic):
    relic_id = str(relic.get("id") or "").strip()
    if relic_id:
        return relic_id
    raise ValueError(f"遗物缺少稳定标识: {relic}")


def relic_icon_file(relic):
    """从 catalog 读取稳定 icon 文件名（如 akabeko.png），缺失时退回 id。"""
    icon = str(relic.get("icon") or "").strip()
    if icon:
        return Path(icon).name
    return f"{stable_relic_id(relic)}.png"


def build_relic_image_url(relic):
    image_url = str(relic.get("image_url") or "").strip()
    if image_url.startswith(("http://", "https://")):
        return image_url

    game = str(relic.get("game") or "sts1").strip()
    icon = relic_icon_file(relic)
    return f"{RELIC_IMAGE_BASE}/{game}/relics/{icon}"


def determine_relic_image_output_path(output_root, relic):
    """本地文件名稳定使用 relic id，目录为 relics/{game}/{id}.png。"""
    game = str(relic.get("game") or "sts1").strip()
    relic_id = stable_relic_id(relic)
    return Path(output_root) / "relics" / game / f"{relic_id}.png"


def load_relics_for_images(base_dir=None):
    if base_dir is None:
        base_dir = Path(__file__).resolve().parents[1]

    relics = []
    for game in RELIC_GAMES:
        raw_path = Path(base_dir) / "data" / "raw" / f"{game}_relics.json"
        if not raw_path.exists():
            continue
        with raw_path.open("r", encoding="utf-8") as handle:
            for relic in json.load(handle):
                if not isinstance(relic, dict):
                    continue
                relic_copy = dict(relic)
                relic_copy.setdefault("game", game)
                relics.append(relic_copy)
    return relics


def fetch_url_bytes(url):
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=30) as response:
        return response.read()


def download_relic_images(relics=None, output_root=None, fetcher=None):
    """下载 STS1 遗物图标到本地；已存在跳过，单张失败不中断其余下载。

    下载逻辑与 QQ 运行时完全分离：bot 查询只读本地文件，不调用本函数。
    """
    if relics is None:
        relics = load_relics_for_images()

    if output_root is None:
        output_root = Path(__file__).resolve().parents[1] / "data" / "images"
    else:
        output_root = Path(output_root)

    if fetcher is None:
        fetcher = fetch_url_bytes

    summary = {
        "total": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "failed_relics": [],
    }

    for relic in relics:
        summary["total"] += 1
        relic_id = stable_relic_id(relic)
        dest_path = determine_relic_image_output_path(output_root, relic)

        if dest_path.exists():
            summary["skipped"] += 1
            continue

        try:
            payload = fetcher(build_relic_image_url(relic))
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(payload)
            summary["success"] += 1
        except Exception:
            summary["failed"] += 1
            game = str(relic.get("game") or "sts1").strip()
            summary["failed_relics"].append(f"{game}:{relic_id}")

    return summary


def main():
    summary = download_relic_images()

    print(f"总遗物数: {summary['total']}")
    print(f"成功下载: {summary['success']}")
    print(f"已存在跳过: {summary['skipped']}")
    print(f"失败数量: {summary['failed']}")
    if summary["failed_relics"]:
        print("失败遗物标识: " + ", ".join(summary["failed_relics"]))
    else:
        print("失败遗物标识: 无")


if __name__ == "__main__":
    main()

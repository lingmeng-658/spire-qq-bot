"""Build the offline 8-NPC STS2 Ancient overview collage.

Requires Pillow and all eight official local PNGs.  Never downloads anything.
Run from anywhere: ``python scripts/build_ancient_overview.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - environment dependency check
    raise SystemExit("需要 Pillow；先安装 Pillow 再运行本脚本") from exc


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "images" / "ancients" / "sts2"
OUTPUT = SRC_DIR / "ancient_overview.png"

IMAGE_SIZE = 85
COLUMNS = 4
ROWS = 2
MARGIN = 12
CELL_GAP_X = 8
ROW_GAP = 12
LABEL_SPACE = 24
FONT_SIZE = 16


def _font():
    candidates = [
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), FONT_SIZE)
    return ImageFont.load_default()


def build_overview(sources=SRC_DIR, output=OUTPUT):
    from card_guess.sts2_ancient_choice import OFFICIAL_ANCIENT_NPC_ZH

    npc_ids = list(OFFICIAL_ANCIENT_NPC_ZH)
    names = [OFFICIAL_ANCIENT_NPC_ZH[npc_id] for npc_id in npc_ids]
    missing = [npc_id for npc_id in npc_ids if not (sources / f"{npc_id}.png").exists()]
    if missing:
        raise RuntimeError(
            "缺少 Ancient NPC 源图片，已拒绝生成残缺总览："
            + ", ".join(missing)
        )

    canvas_w = MARGIN * 2 + COLUMNS * IMAGE_SIZE + (COLUMNS - 1) * CELL_GAP_X
    canvas_h = (
        MARGIN * 2
        + ROWS * IMAGE_SIZE
        + (ROWS - 1) * ROW_GAP
        + ROWS * LABEL_SPACE
    )
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (24, 28, 40, 255))
    draw = ImageDraw.Draw(canvas)
    font = _font()

    for index, (npc_id, name) in enumerate(zip(npc_ids, names)):
        row, col = divmod(index, COLUMNS)
        x = MARGIN + col * (IMAGE_SIZE + CELL_GAP_X)
        y = MARGIN + row * (IMAGE_SIZE + ROW_GAP + LABEL_SPACE)

        source = Image.open(sources / f"{npc_id}.png").convert("RGBA")
        canvas.paste(source, (x, y), source)
        source.close()

        cx = x + IMAGE_SIZE // 2
        text_y = y + IMAGE_SIZE + 4
        draw.text((cx, text_y), name, font=font, fill=(255, 255, 255, 255), anchor="ma")

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")
    return output


def main():
    sys.path.insert(0, str(ROOT / "src"))
    try:
        output = build_overview()
    except Exception as exc:  # missing source must never silently pass
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"已生成：{output}")


if __name__ == "__main__":
    main()

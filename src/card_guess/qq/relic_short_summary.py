"""Pure helpers that compress official Chinese relic effect text.

The rules only remove official wordiness and unstable icon markup; they never
truncate, rank, recommend, or add information beyond the source description.
"""

from __future__ import annotations

import re


# A few STS1 raw texts contain dump artifacts or duplicate UI captions that the
# generic cleaner cannot safely rebuild.  STS2 SILKEN_TRESS has a long but
# stable pickup sentence that reads far better as a one-line reminder.
RELIC_SHORT_SUMMARY_OVERRIDES = {
    ("sts1", "CALLING_BELL"): "拾起：获得1个独特诅咒和3件遗物",
    ("sts1", "MARK_OF_PAIN"): "回合开始获得1点能量；战斗开始时将2张伤口放入抽牌堆",
    ("sts1", "RING_OF_THE_SERPENT"): "替换蛇之戒指；回合开始额外抽1张牌",
    ("sts1", "ASTROLABE"): "拾起：选择3张牌进行变化并升级",
    ("sts1", "EMPTY_CAGE"): "拾起：从牌组中移除2张牌",
    ("sts1", "TINY_HOUSE"): "拾起：获得1瓶药水、金币、1张牌，最大生命值提升5并随机升级1张牌",
    ("sts1", "VELVET_CHOKER"): "回合开始获得能量；每回合最多打出6张牌",
    ("sts2", "SILKEN_TRESS"): "拾起：失去所有金币；首次卡牌奖励附魔华彩",
}

_WHITESPACE_RE = re.compile(r"\s+")
_TRIGGER_SUBSTITUTIONS = (
    (r"在每个回合开始时[，,]?", "回合开始"),
    (r"在每回合开始时[，,]?", "回合开始"),
    (r"每回合开始时[，,]?", "回合开始"),
    (r"在回合开始时[，,]?", "回合开始"),
    (r"回合开始时[，,]?", "回合开始"),
    (r"在每场战斗开始时[，,]?", "战斗开始时"),
    (r"在每场战斗的开始时[，,]?", "战斗开始时"),
    (r"每场战斗开始时[，,]?", "战斗开始时"),
    (r"在战斗开始时[，,]?", "战斗开始时"),
    (r"在每场战斗结束时[，,]?", "战斗结束时"),
    (r"每场战斗结束时[，,]?", "战斗结束时"),
    (r"在Boss战与精英战中[，,]?", "Boss战与精英战中"),
)
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+")
_TRAILING_PUNCT_RE = re.compile(r"^[。．.，,、；;：:]+|[。．.，,、；;：:]+$")
_FLAVOR_ELLIPSIS_RE = re.compile(r"……")


def _normalise_official_text(text: str) -> str:
    text = text.replace("[E]", "能量")
    text = text.replace("⚡", "能量")
    text = text.replace("[S]", "星星")
    text = text.replace("⭐", "星星")
    text = _WHITESPACE_RE.sub("", text)
    text = text.replace("“", "").replace("”", "")
    text = text.replace("一张", "1张")
    text = text.replace("你的", "")

    for pattern, replacement in _TRIGGER_SUBSTITUTIONS:
        text = re.sub(pattern, replacement, text)

    text = text.replace("拾起时，", "拾起：")
    text = text.replace("你", "")
    return text.strip()


def _clean_segments(text: str) -> list[str]:
    parts = []
    seen = ""
    for raw in _SENTENCE_SPLIT_RE.split(text):
        part = _TRAILING_PUNCT_RE.sub("", raw).strip()
        if not part:
            continue
        if _FLAVOR_ELLIPSIS_RE.search(part):
            continue
        if part in seen:
            continue
        if part.startswith(("小小的屋子", "我只能打出最多")):
            continue
        seen += part
        parts.append(part)
    return parts


def short_relic_effect(
    description: str | None,
    *,
    relic_id: str | None = None,
    game: str | None = None,
) -> str:
    """Return a compact player-facing reminder based on official zh text."""
    if game is not None and relic_id is not None:
        override = RELIC_SHORT_SUMMARY_OVERRIDES.get((game, relic_id))
        if override is not None:
            return override

    source = str(description or "").strip()
    if not source:
        return ""

    return "；".join(_clean_segments(_normalise_official_text(source)))

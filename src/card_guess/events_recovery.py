"""STS1 event choice zh-text static recovery helper.

Small, pure normalization used only when (re)building the frozen STS1 event
catalog: official Simplified Chinese choice text occasionally keeps the
official template but loses a static number that the English raw token of the
same catalog row still carries (e.g. ``获得 金币。`` next to ``Gain 75 Gold.``).

Rules are deliberately conservative and generic (never event-ID specific):

- Only fill a value when the zh text still names the same entity/verb and the
  en row carries a fixed literal token (``35 Gold``, ``+5``, ``Take 11
  damage``, ``Heal ⅓ Max HP``, ...).
- Percentages, runtime-interpolated amounts, ranged/random values and rows
  whose zh/en pairing is not trustworthy stay untouched (return ``None``).
- No whole-sentence machine translation and no invented entity names.

The returned string (or ``None`` when nothing should change) keeps the
original catalog zh spacing and punctuation.
"""

from __future__ import annotations

import re


_FRACTION_TO_TEXT = {
    "\u2153": "1/3",  # ⅓
    "\u00bd": "1/2",  # ½
    "\u2154": "2/3",  # ⅔
}


def _en_body(raw_option: str) -> str:
    """Strip a leading ``[Label]`` from the English option text."""
    if not raw_option:
        return ""
    return re.sub(r"^\[[^\]]*\]\s*", "", raw_option).strip()


def _fill_price_hole(zh: str, en_body: str) -> str | None:
    """Fill ``N 金币：`` style price holes (zh keeps ``金币 :`` or ``金币：``)."""
    match = re.search(r"\b(\d+)\s*Gold\s*[:：]", en_body)
    if not match:
        return None
    if re.search(r"\d\s*金币\s*[:：]", zh):
        return None  # already priced (e.g. 35 金币 ： ...)
    price_match = re.search(r"金币(?=\s*[:：])", zh)
    if not price_match:
        return None
    return zh[: price_match.start()] + f"{match.group(1)} 金币" + zh[price_match.end():]


def _fill_gain_gold(zh: str, en_body: str) -> str | None:
    """Fill ``获得 N 金币`` when the zh hole still reads ``获得 金币``."""
    match = re.search(r"\bGain\s+(\d+)\s+Gold\b", en_body)
    if not match:
        return None
    gain_match = re.search(r"获得\s*金币", zh)
    if not gain_match:
        return None
    return zh[: gain_match.start()] + f"获得 {match.group(1)} 金币" + zh[gain_match.end():]


def _fill_lose_gold(zh: str, en_body: str) -> str | None:
    """Fill ``失去 N 金币`` when the zh hole still reads ``失去 金币``."""
    match = re.search(r"\bLose\s+(\d+)\s+Gold\b", en_body)
    if not match:
        return None
    lose_match = re.search(r"失去\s*金币", zh)
    if not lose_match:
        return None
    return zh[: lose_match.start()] + f"失去 {match.group(1)} 金币" + zh[lose_match.end():]


def _fill_lose_hp(zh: str, en_body: str) -> str | None:
    """Fill ``失去 N 生命`` when the zh hole reads ``失去 生命`` and en has a
    fixed HP/damage literal. Percent and generic ``Lose HP`` rows never match."""
    match = re.search(r"\b(?:Lose\s+(\d+)\s+HP|Take\s+(\d+)\s+damage)\b", en_body)
    if not match:
        return None
    value = match.group(1) or match.group(2)
    hp_match = re.search(r"失去\s*生命", zh)
    if not hp_match:
        return None
    return zh[: hp_match.start()] + f"失去 {value} 生命" + zh[hp_match.end():]


def _fill_max_hp_bonus(zh: str, en_body: str) -> str | None:
    """Fill ``最大生命值 +5`` when the zh hole reads ``最大生命值 + 。``."""
    match = re.search(r"\bMax\s+HP\s*\+\s*(\d+)\b", en_body)
    if not match:
        return None
    bonus_match = re.search(r"(最大生命值\s*\+)\s*。", zh)
    if not bonus_match:
        return None
    return zh[: bonus_match.start()] + f"{bonus_match.group(1)}{match.group(1)}。" + zh[bonus_match.end():]


def _fill_heal_fraction(zh: str, en_body: str) -> str | None:
    """Recover ``回复最大生命值的 1/3`` style heal holes.

    Only applies when the official zh template carries no ``点`` unit (that
    form displays the runtime heal amount, which is not safely restorable from
    the catalog alone). The Big Fish banana and the Cleric heal rows keep the
    fraction that the paired en row already documents.
    """
    match = re.search(r"\bHeal\s+(\u2153|\u00bd|\u2154|1/3|1/2|2/3)\b", en_body)
    if not match:
        return None
    if "点" in zh:
        return None
    heal_match = re.search(r"回复\s*(?:生命)?\s*。", zh)
    if not heal_match:
        return None
    if re.search(r"\d", heal_match.group(0)):
        return None
    fraction = _FRACTION_TO_TEXT.get(match.group(1), match.group(1))
    return zh[: heal_match.start()] + f"回复最大生命值的 {fraction}。" + zh[heal_match.end():]


def recover_choice_description_zh(description_zh: str | None, raw_option: str) -> str | None:
    """Return the recovered ``description_zh`` or ``None`` when unchanged.

    ``raw_option`` is the frozen catalog choice ``raw.option`` (English text).
    None or empty zh text is never filled.
    """
    if not description_zh or not raw_option:
        return None
    body = _en_body(raw_option)
    if not body:
        return None

    changed = None
    for filler in (
        _fill_heal_fraction,
        _fill_max_hp_bonus,
        _fill_price_hole,
        _fill_gain_gold,
        _fill_lose_gold,
        _fill_lose_hp,
    ):
        candidate = filler(description_zh if changed is None else changed, body)
        if candidate is not None and candidate != (description_zh if changed is None else changed):
            changed = candidate
    return changed

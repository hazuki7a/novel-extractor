"""Generic chapter title detection.

Parses titles like 第一章 / 第一百二十三章 / 第123章 / 第12节 / 第九回 /
卷一 / 序章 / 终章 / 楔子 / 番外 / 后记 / Chapter 12 into a normalized
ChapterTitleMatch with a sortable order token, confidence and reason.

No site specific rules: everything is pattern + numeral knowledge.
"""

from __future__ import annotations

import re
from typing import Optional

from novel_extractor.models import ChapterTitleMatch

# ---------------------------------------------------------------------------
# Chinese numeral parsing
# ---------------------------------------------------------------------------

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000}
_CN_SECTIONS = {"万": 10000, "亿": 100000000}

_CN_NUMERAL_CHARS = set(_CN_DIGITS) | set(_CN_UNITS) | set(_CN_SECTIONS) | {"零", "〇"}


def chinese_numeral_to_int(text: str) -> Optional[int]:
    """Convert 第一百二十三 / 十五 / 一千零一 style numerals to int."""
    text = text.strip()
    if not text:
        return None
    total = 0
    section = 0
    number = 0
    consumed_any = False
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
            consumed_any = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if number == 0:
                number = 1  # 十五 starts with 十 meaning 1*10
            section += number * unit
            number = 0
            consumed_any = True
        elif ch in _CN_SECTIONS:
            if section == 0 and number == 0:
                section = 1
            total += (section + number) * _CN_SECTIONS[ch]
            section = 0
            number = 0
            consumed_any = True
        elif ch in ("零", "〇"):
            consumed_any = True
            continue
        else:
            return None
    result = total + section + number
    if not consumed_any or result <= 0:
        return None
    return result


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９．", "0123456789.")
_NUM_WORD = r"[0-9]+(?:\.[0-9]+)?"
_CN_NUM_WORD = "[" + "".join(_CN_NUMERAL_CHARS) + "]+"
_NUM_OR_CN = rf"(?:{_NUM_WORD}|{_CN_NUM_WORD})"

_NUMBERED_RE = re.compile(rf"^第\s*({_NUM_OR_CN})\s*(章|节|回|话|篇|卷|部)\s*[:：\-—_\s]*(.*)$")
_NUMBERED_LOOSE_RE = re.compile(rf"第\s*({_NUM_OR_CN})\s*(章|节|回|话|篇|卷|部)")
_VOLUME_PREFIX_RE = re.compile(rf"^(卷|部)\s*({_NUM_OR_CN})\s*[:：\-—_\s]*(.*)$")
_CHAPTER_EN_RE = re.compile(r"^chapter\s*([0-9]+(?:\.[0-9]+)?)\s*[:：\-—_.\s]*(.*)$", re.IGNORECASE)

_SPECIAL_TYPES = {
    "序章": "prologue", "序幕": "prologue", "序言": "prologue",
    "楔子": "prologue", "引言": "prologue", "序": "prologue",
    "终章": "epilogue", "尾声": "epilogue", "大结局": "epilogue", "结局": "epilogue",
    "后记": "afterword", "跋": "afterword",
    "番外": "extra", "番外篇": "extra", "外传": "extra", "特别篇": "extra",
    "间章": "interlude", "幕间": "interlude", "插章": "interlude",
}
_SPECIAL_RE = re.compile(
    r"^(" + "|".join(sorted(_SPECIAL_TYPES, key=len, reverse=True)) + r")\s*[:：\-—_\s]*(.*)$"
)

_STRIPPED_CHARS = " \t\r\n\u3000【】〔］[]「」『』《》〈〉\"'“”‘’（）()"


def _clean(text: str) -> str:
    return text.translate(_FULLWIDTH_DIGITS).strip(_STRIPPED_CHARS).strip()


def _to_number(raw: str) -> Optional[float]:
    if not raw:
        return None
    if any(ch in _CN_NUMERAL_CHARS for ch in raw):
        value = chinese_numeral_to_int(raw)
        return float(value) if value is not None else None
    try:
        return float(raw)
    except ValueError:
        return None


# Sub-numbering suffix: the WHOLE suffix is a bare number - "第6章 2" /
# "第6章：2" / "第六章(1)". A suffix like "5年后" is a chapter NAME, not a
# part number, and must not be mistaken for one.
_SUB_NUMBER_RE = re.compile(r"^[\s:：\-—_(（]*(\d{1,4})[)）\s:：\-—_]*$")

# Strips a trailing sub-number from a title: "第6章 2" -> "第6章",
# "第六章(1)" -> "第六章".
_STRIP_SUB_RE = re.compile(
    r"^(第\s*[0-9零〇一二两三四五六七八九十百千万]+\s*[章节回话篇])[\s:：\-—_(（]*\d{1,4}[)）\s:：\-—_]*$"
)


def strip_sub_number(title: str) -> str:
    match = _STRIP_SUB_RE.match(title.strip())
    return match.group(1) if match else title.strip()


def _match_confidence(cleaned: str, start: int, has_suffix: bool) -> tuple[float, str]:
    if start <= 0:
        if has_suffix:
            return 0.92, "anchored at start with title suffix"
        return 0.95, "anchored at start, pure title"
    return 0.55, "pattern found mid-text (weak)"


class ChapterTitleDetector:
    """Detect and normalize novel chapter titles."""

    def parse(self, text: str) -> Optional[ChapterTitleMatch]:
        cleaned = _clean(text)
        if not cleaned:
            return None

        match = _NUMBERED_RE.match(cleaned)
        if match:
            number = _to_number(match.group(1))
            if number is not None:
                unit = match.group(2)
                suffix = match.group(3).strip()
                chapter_type = "volume" if unit in ("卷", "部") else "normal"
                order_token = number
                sub_note = ""
                sub = _SUB_NUMBER_RE.match(suffix)
                sub_number: Optional[int] = None
                if sub and "." not in match.group(1):
                    # Per-part chapters: 第6章 2 sorts after 第6章 1. Encoded
                    # as a small fraction so main numbers stay dominant
                    # (sub/10000 never reaches the next main number).
                    sub_number = int(sub.group(1))
                    order_token = number + sub_number / 10000.0
                    sub_note = f"; sub={sub_number}"
                confidence, anchor_reason = _match_confidence(cleaned, 0, bool(suffix))
                reason = f"matched 第<number>{unit} pattern; number={number:g}{sub_note}; {anchor_reason}"
                return ChapterTitleMatch(
                    title=cleaned,
                    chapter_number=number,
                    chapter_type=chapter_type,
                    order_token=order_token,
                    confidence=confidence,
                    reason=reason,
                    sub_number=sub_number,
                )

        volume = _VOLUME_PREFIX_RE.match(cleaned)
        if volume:
            number = _to_number(volume.group(2))
            if number is not None:
                suffix = volume.group(3).strip()
                confidence, anchor_reason = _match_confidence(cleaned, 0, bool(suffix))
                return ChapterTitleMatch(
                    title=cleaned,
                    chapter_number=number,
                    chapter_type="volume",
                    order_token=number,
                    confidence=confidence,
                    reason=f"matched 卷<number> pattern; number={number:g}; {anchor_reason}",
                )

        english = _CHAPTER_EN_RE.match(cleaned)
        if english:
            number = float(english.group(1))
            suffix = english.group(2).strip()
            confidence, anchor_reason = _match_confidence(cleaned, 0, bool(suffix))
            return ChapterTitleMatch(
                title=cleaned,
                chapter_number=number,
                chapter_type="normal",
                order_token=number,
                confidence=confidence,
                reason=f"matched English Chapter pattern; number={number:g}; {anchor_reason}",
            )

        special = _SPECIAL_RE.match(cleaned)
        if special:
            keyword = special.group(1)
            chapter_type = _SPECIAL_TYPES[keyword]
            suffix = special.group(2).strip()
            number: Optional[float] = None
            if suffix:
                # e.g. 番外二 新春 / 番外 3
                embedded = re.match(rf"^({_NUM_OR_CN})\b", suffix)
                if embedded:
                    number = _to_number(embedded.group(1))
            confidence = 0.90 if not suffix else 0.85
            reason = f"matched special keyword {keyword} -> {chapter_type}"
            return ChapterTitleMatch(
                title=cleaned,
                chapter_number=number,
                chapter_type=chapter_type,
                order_token=number,
                confidence=confidence,
                reason=reason,
            )

        # Weak fallback: chapter marker embedded somewhere in longer text.
        loose = _NUMBERED_LOOSE_RE.search(cleaned)
        if loose:
            number = _to_number(loose.group(1))
            if number is not None:
                return ChapterTitleMatch(
                    title=cleaned,
                    chapter_number=number,
                    chapter_type="normal",
                    order_token=number,
                    confidence=0.55,
                    reason="chapter marker found mid-text (weak)",
                )
        return None

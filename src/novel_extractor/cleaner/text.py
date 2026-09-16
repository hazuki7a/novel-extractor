"""Conservative novel text cleaning.

Guide rules (text_cleaning):
- never aggressively merge broken lines; keeping an extra paragraph is
  always better than wrongly merging two real ones;
- when uncertain, preserve the original text;
- paragraphs get two full-width leading spaces, separated by a blank line.
"""

from __future__ import annotations

import html as html_module
import re
import unicodedata
from typing import Iterable, Optional

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.analyzer.pagination import strip_page_suffix

# Zero-width and invisible characters that pollute scraped text.
_INVISIBLE_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]")
# Control chars except \n (which is the paragraph separator at this stage).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAG_RE = re.compile(r"<[^<>]{1,200}>")

_NAV_TOKENS = {
    "上一章", "下一章", "目录", "返回目录", "章节目录", "全部章节", "章节列表",
    "上一页", "下一页", "上页", "下页", "上一节", "下一节", "上一回", "下一回",
    "首页", "书页", "书签", "加入书签", "保存书签", "阅读记录", "推荐票", "投推荐票", "求收藏",
    "返回书页", "回目录", "上一卷", "下一卷",
    "prev", "previous", "next", "contents", "table of contents", "chapter list",
}
_NAV_SPLIT_RE = re.compile(r"[\s→←\-—=~·、,，。;；:：|/\\»«‹›➤➜►▸★☆\[\]()（）【】\"'“”]+")
_NAV_SYMBOLS = "→←-—=~·、,，。;；:：|/\\»«‹›➤➜►▸★☆ []()（）【】\"'“”\t"
_PURE_NUMBER_LINE_RE = re.compile(r"^[\d\s/页第\-_（()）.]+$")

_SITE_PROMPT_RE = re.compile(
    r"点击?(下一页|继续阅读|下一章节?继续)"
    r"|请?记住(本站|本书|我们)(首发)?(域名|网址|地址)"
    r"|首发(网址|域名|地址)"
    r"|本站(网址|域名|地址)"
    r"|天才一秒记住"
    r"|最新章节.{0,8}(请到|就在|网址)"
    r"|手机(版?|阅读).{0,10}(访问|网址)"
    r"|举报(本章|章节)?错误"
    r"|章节错误.{0,6}(举报|联系)"
    r"|为您(提供|推荐)"
)
_PROMPT_LINE_MAX = 100


_SORTED_NAV_TOKENS = sorted(_NAV_TOKENS, key=len, reverse=True)


def _consumed_by_nav_words(line: str) -> bool:
    """True when the line is entirely nav words glued together with no
    separators (上一章章节目录保存书签阅读记录下一章) - link bars rendered
    without whitespace between anchors. Greedy longest-match consumption;
    prose containing one nav word always leaves residue and survives.
    """
    pos = 0
    lowered = line.lower()
    while pos < len(lowered):
        for word in _SORTED_NAV_TOKENS:
            if lowered.startswith(word, pos):
                pos += len(word)
                break
        else:
            return False
    return True


def _is_nav_line(line: str) -> bool:
    if not line or len(line) > 30:
        return False
    cleaned = line.strip(_NAV_SYMBOLS).strip()
    if cleaned in _NAV_TOKENS:
        return True
    if _consumed_by_nav_words(line):
        return True
    tokens = [t for t in _NAV_SPLIT_RE.split(line.lower()) if t]
    if tokens and all(token in _NAV_TOKENS for token in tokens):
        return True
    return False


def _is_site_prompt_line(line: str) -> bool:
    if not line or len(line) > _PROMPT_LINE_MAX:
        return False
    return bool(_SITE_PROMPT_RE.search(line))


def _is_pure_number_line(line: str) -> bool:
    if not line or len(line) > 12:
        return False
    return bool(_PURE_NUMBER_LINE_RE.match(line))


def _is_duplicate_title(line: str, title_variants: Iterable[str]) -> bool:
    line_norm = re.sub(r"\s+", "", line)
    line_stripped = re.sub(r"\s+", "", strip_page_suffix(line))
    if not line_norm:
        return False
    for variant in title_variants:
        if not variant:
            continue
        variants = {
            re.sub(r"\s+", "", variant),
            re.sub(r"\s+", "", strip_page_suffix(variant)),
        }
        if line_norm in variants or line_stripped in variants:
            return True
    return _same_chapter_identity(line, title_variants)


def _same_chapter_identity(line: str, title_variants: Iterable[str]) -> bool:
    """Structural equality: 第六章(1) / 第6章 1 are the same chapter.

    Sites render the heading differently from the catalog title; compare the
    parsed (number, sub_number) identity instead of raw strings.
    """
    line_match = _TITLE_DETECTOR.parse(line)
    if line_match is None or line_match.order_token is None:
        return False
    if line_match.confidence < 0.85:
        return False  # weak embedded references (他说第三章...) are prose
    for variant in title_variants:
        if not variant:
            continue
        variant_match = _TITLE_DETECTOR.parse(variant)
        if (
            variant_match is not None
            and variant_match.order_token is not None
            and variant_match.order_token == line_match.order_token
            and variant_match.sub_number == line_match.sub_number
        ):
            return True
    return False


_TITLE_DETECTOR = ChapterTitleDetector()


class TextCleaner:
    """Clean extracted chapter text conservatively."""

    def clean(self, text: str, chapter_title: Optional[str] = None) -> str:
        if not text:
            return ""

        # 1. HTML residue + entity decoding.
        text = html_module.unescape(text)
        text = _TAG_RE.sub("", text)

        # 2. Unicode normalization, line endings, invisible/control chars.
        text = unicodedata.normalize("NFC", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _INVISIBLE_RE.sub("", text)
        text = _CONTROL_RE.sub("", text)

        # 3. Line level filtering.
        title_variants = [chapter_title] if chapter_title else []
        paragraphs: list[str] = []
        for raw_line in text.split("\n"):
            line = raw_line.strip()
            if not line:
                paragraphs.append("")  # paragraph break candidate
                continue
            if _is_nav_line(line):
                continue
            if _is_site_prompt_line(line):
                continue
            if _is_pure_number_line(line):
                continue
            if _is_duplicate_title(line, title_variants):
                continue
            paragraphs.append(line)

        # 4. Drop empties (blank lines are paragraph separators, produced by
        # the join itself), then trim any leading/trailing leftovers.
        kept = [line for line in paragraphs if line]

        # 5. Uniform paragraph indent: two full-width spaces.
        formatted = []
        for paragraph in kept:
            if not paragraph.startswith("　"):
                paragraph = "　　" + paragraph.lstrip("　").lstrip()
            formatted.append(paragraph)

        return "\n\n".join(formatted)

"""Book metadata extraction.

Evidence priority (guide metadata_extraction):
- book_title: JSON-LD > OpenGraph (incl. og:novel:*) > detail h1 > title template
- author:     JSON-LD > meta author > explicit 作者:/Author: text label

The exporter never guesses metadata; it only consumes what this module returns.
Every rule below is generic (microdata conventions / label patterns); no site
specific selectors are used.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from novel_extractor.models import BookMetadata

# Generic marketing noise removed from title candidates. Not site names.
_TITLE_NOISE = [
    "最新章节列表", "最新章节", "章节列表", "全文阅读", "全文免费阅读",
    "免费阅读", "无弹窗广告", "无弹窗", "无广告", "txt下载", "txt全集下载",
    "小说在线阅读", "在线阅读", "正文",
]
_NOISE_RE = re.compile("|".join(map(re.escape, _TITLE_NOISE)), re.IGNORECASE)
_TITLE_SPLIT_RE = re.compile(r"[|｜_＿\-—－·,，;；\s]+")
# Chinese label: name ends at first whitespace/punctuation.
_AUTHOR_CN_RE = re.compile(r"(?:作者|作\s*者)\s*[:：]\s*([^\s，。；;，|\n]{1,30})")
# English label: name keeps inner spaces, ends at punctuation/line end.
_AUTHOR_EN_RE = re.compile(r"Author\s*[:：]\s*([^，。；;，|\n]{1,40})", re.IGNORECASE)
_BAD_TITLE_VALUES = {"首页", "官网", "首页-", "章节", "小说", "阅读"}


def _clean_title_value(value: str) -> Optional[str]:
    value = _NOISE_RE.sub("", value)
    value = value.strip(" |＿_-—·,，:：")
    if not value or value.lower() in _BAD_TITLE_VALUES:
        return None
    return value


def _clean_author_value(value: str) -> Optional[str]:
    value = value.strip(" \t:：，,。|")
    if not value or len(value) > 30:
        return None
    return value


def _as_name(obj: Any) -> Optional[str]:
    if isinstance(obj, str):
        return obj.strip() or None
    if isinstance(obj, list):
        for item in obj:
            name = _as_name(item)
            if name:
                return name
        return None
    if isinstance(obj, dict):
        name = obj.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


class MetadataExtractor:
    """Extract book metadata from a detail/catalog/chapter page."""

    def extract(self, html: str) -> BookMetadata:
        soup = BeautifulSoup(html, "lxml")

        title_candidates: list[tuple[float, str, str]] = []  # (confidence, value, source)
        author_candidates: list[tuple[float, str, str]] = []
        description: Optional[str] = None
        cover_url: Optional[str] = None
        volume_title: Optional[str] = None

        self._collect_json_ld(soup, title_candidates, author_candidates)
        self._collect_open_graph(
            soup, title_candidates, author_candidates,
        )
        description, cover_url, volume_title = self._collect_meta_extras(soup)

        h1 = soup.find("h1")
        if h1:
            value = _clean_title_value(h1.get_text(" ", strip=True))
            if value:
                title_candidates.append((0.65, value, "h1"))

        title_tag = soup.find("title")
        if title_tag:
            value = self._title_from_template(title_tag.get_text(strip=True))
            if value:
                title_candidates.append((0.45, value, "title_template"))

        text = soup.get_text(" ", strip=True)
        for regex, confidence, source in (
            (_AUTHOR_CN_RE, 0.80, "author_label_text"),
            (_AUTHOR_EN_RE, 0.75, "author_label_text_en"),
        ):
            match = regex.search(text)
            if match:
                value = _clean_author_value(match.group(1))
                if value:
                    author_candidates.append((confidence, value, source))
                    break

        book_title, title_conf, title_reason = self._best(title_candidates)
        author, author_conf, author_reason = self._best(author_candidates)

        return BookMetadata(
            book_title=book_title,
            author=author,
            description=description,
            cover_url=cover_url,
            volume_title=volume_title,
            title_confidence=title_conf,
            title_reason=title_reason,
            author_confidence=author_conf,
            author_reason=author_reason,
        )

    # -- collectors ---------------------------------------------------------

    def _collect_json_ld(
        self,
        soup: BeautifulSoup,
        title_candidates: list[tuple[float, str, str]],
        author_candidates: list[tuple[float, str, str]],
    ) -> None:
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            for obj in data if isinstance(data, list) else [data]:
                if not isinstance(obj, dict):
                    continue
                types = obj.get("@type", [])
                types = [types] if isinstance(types, str) else types
                lowered = {str(t).lower() for t in types}
                if "book" in lowered or "creativecontent" in lowered:
                    name = _as_name(obj.get("name"))
                    if name:
                        value = _clean_title_value(name)
                        if value:
                            title_candidates.append((0.90, value, "json_ld_book"))
                    author = _as_name(obj.get("author"))
                    if author:
                        value = _clean_author_value(author)
                        if value:
                            author_candidates.append((0.90, value, "json_ld_book"))

    def _collect_open_graph(
        self,
        soup: BeautifulSoup,
        title_candidates: list[tuple[float, str, str]],
        author_candidates: list[tuple[float, str, str]],
    ) -> None:
        og_novel_title = self._meta_content(soup, "property", "og:novel:book_name")
        if og_novel_title:
            value = _clean_title_value(og_novel_title)
            if value:
                title_candidates.append((0.85, value, "og_novel_book_name"))
        og_title = self._meta_content(soup, "property", "og:title")
        if og_title:
            value = _clean_title_value(og_title)
            if value:
                title_candidates.append((0.70, value, "og_title"))
        og_novel_author = self._meta_content(soup, "property", "og:novel:author")
        if og_novel_author:
            value = _clean_author_value(og_novel_author)
            if value:
                author_candidates.append((0.85, value, "og_novel_author"))
        meta_author = self._meta_content(soup, "name", "author")
        if meta_author:
            value = _clean_author_value(meta_author)
            if value:
                author_candidates.append((0.70, value, "meta_author"))

    def _collect_meta_extras(
        self, soup: BeautifulSoup
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        description = (
            self._meta_content(soup, "property", "og:description")
            or self._meta_content(soup, "name", "description")
        )
        if description:
            description = description.strip()[:300] or None
        cover_url = self._meta_content(soup, "property", "og:image")
        if not cover_url:
            link = soup.find("link", rel="image_src")
            cover_url = link.get("href") if link else None
        volume_title = self._meta_content(soup, "property", "og:novel:volume")
        return description, cover_url, volume_title

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _meta_content(soup: BeautifulSoup, attr: str, key: str) -> Optional[str]:
        meta = soup.find("meta", attrs={attr: key})
        if meta is None:
            return None
        content = meta.get("content")
        if content and content.strip():
            return content.strip()
        return None

    @staticmethod
    def _title_from_template(title: str) -> Optional[str]:
        """Best-effort book title from a page <title> template.

        Keeps the first distinct cleaned segment; multi-page template
        stabilization is the crawler's job (guide: 章节页可通过多页模板比较).
        """
        segments = [seg.strip() for seg in _TITLE_SPLIT_RE.split(title) if seg.strip()]
        seen: list[str] = []
        for segment in segments:
            cleaned = _clean_title_value(segment)
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        for candidate in seen:
            if candidate.lower() not in _BAD_TITLE_VALUES:
                return candidate
        return None

    @staticmethod
    def _best(
        candidates: list[tuple[float, str, str]],
    ) -> tuple[Optional[str], float, str]:
        if not candidates:
            return None, 0.0, ""
        candidates.sort(key=lambda item: item[0], reverse=True)
        confidence, value, source = candidates[0]
        return value, confidence, f"source={source}; value={value[:50]}"

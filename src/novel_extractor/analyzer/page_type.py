"""Page type classification: BOOK_PAGE / CATALOG_PAGE / CHAPTER_PAGE / UNKNOWN.

Scores are built from generic DOM/text features only: main content length,
chapter-title-like anchors, link density, nav markers, heading structure.
No site specific rules.
"""

from __future__ import annotations

from typing import Optional

from bs4 import Tag

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.analyzer.content import ContentExtractor
from novel_extractor.models import DetectionResult, PageType

_PREV_NEXT_WORDS = ("上一章", "下一章", "上一页", "下一页", "上一节", "下一节")
_CATALOG_WORD = "目录"
_INTRO_WORDS = ("简介", "内容简介", "作品简介")

_STRONG_TITLE_CONFIDENCE = 0.85


class PageTypeDetector:
    def __init__(
        self,
        chapter_detector: Optional[ChapterTitleDetector] = None,
        content_extractor: Optional[ContentExtractor] = None,
    ):
        self._chapter = chapter_detector or ChapterTitleDetector()
        self._content = content_extractor or ContentExtractor()

    def classify(self, html: str) -> DetectionResult[PageType]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        diagnostics = self._features(soup, html)

        chapter_score = self._chapter_score(diagnostics)
        catalog_score = self._catalog_score(diagnostics)
        book_score = self._book_score(diagnostics)

        diagnostics["chapter_score"] = round(chapter_score, 3)
        diagnostics["catalog_score"] = round(catalog_score, 3)
        diagnostics["book_score"] = round(book_score, 3)

        scores = [
            (chapter_score, PageType.CHAPTER_PAGE),
            (catalog_score, PageType.CATALOG_PAGE),
            (book_score, PageType.BOOK_PAGE),
        ]
        scores.sort(key=lambda item: item[0], reverse=True)
        best_score, best_type = scores[0]

        if best_score < 0.50 or scores[0][0] - scores[1][0] < 0.05:
            return DetectionResult(
                value=PageType.UNKNOWN,
                confidence=round(best_score, 3),
                reason=(
                    "no type reached threshold or top scores too close "
                    f"(chapter={chapter_score:.2f}, catalog={catalog_score:.2f}, book={book_score:.2f})"
                ),
                diagnostics=diagnostics,
            )

        reasons = {
            PageType.CHAPTER_PAGE: "long low-link content with chapter title / prev-next navigation",
            PageType.CATALOG_PAGE: "many chapter-title-like links clustered together",
            PageType.BOOK_PAGE: "heading + author + intro evidence with few chapter links",
        }
        return DetectionResult(
            value=best_type,
            confidence=round(best_score, 3),
            reason=reasons[best_type],
            diagnostics=diagnostics,
        )

    # -- features -----------------------------------------------------------

    def _features(self, soup, html: str) -> dict:
        total_text = soup.get_text(" ", strip=True)
        total_len = len(total_text)
        link_text_len = sum(len(a.get_text(strip=True)) for a in soup.find_all("a"))
        link_ratio = link_text_len / total_len if total_len else 0.0

        chapter_like = 0
        chapter_anchors: list[Tag] = []
        nav_markers = 0
        catalog_marker = False
        link_count = 0
        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            if not text:
                continue
            link_count += 1
            if any(word in text for word in _PREV_NEXT_WORDS):
                nav_markers += 1
            if _CATALOG_WORD in text:
                catalog_marker = True
            match = self._chapter.parse(text)
            if match and match.confidence >= _STRONG_TITLE_CONFIDENCE:
                chapter_like += 1
                chapter_anchors.append(a)

        # Cluster size per parent AND per grandparent: ``ul > li > a`` puts a
        # single anchor under each li, the real list container is the ul.
        parent_counts: dict[int, int] = {}
        grandparent_counts: dict[int, int] = {}
        for a in chapter_anchors:
            parent = a.parent
            parent_counts[id(parent)] = parent_counts.get(id(parent), 0) + 1
            grandparent = parent.parent if parent is not None else None
            grandparent_counts[id(grandparent)] = grandparent_counts.get(id(grandparent), 0) + 1
        same_parent_cluster = 0
        if parent_counts:
            same_parent_cluster = max(
                max(parent_counts.values()), max(grandparent_counts.values())
            )

        h1 = soup.find("h1")
        h1_text = h1.get_text(strip=True) if h1 else ""
        h1_is_chapter = False
        if h1_text:
            match = self._chapter.parse(h1_text)
            h1_is_chapter = bool(match and match.confidence >= _STRONG_TITLE_CONFIDENCE)

        meta_desc = soup.find("meta", attrs={"name": "description"})
        has_intro = bool(
            (meta_desc and meta_desc.get("content"))
            or any(word in total_text[:3000] for word in _INTRO_WORDS)
        )
        head = total_text[:5000]
        has_author_label = "作者：" in head or "作者:" in head or "作 者：" in head

        extraction = self._content.extract(html)
        content_len = len(extraction.text)

        return {
            "total_len": total_len,
            "link_ratio": link_ratio,
            "content_len": content_len,
            "content_confidence": extraction.confidence,
            "chapter_like_links": chapter_like,
            "chapter_like_ratio": (chapter_like / link_count) if link_count else 0.0,
            "same_parent_cluster": same_parent_cluster,
            "nav_markers": nav_markers,
            "catalog_marker": catalog_marker,
            "h1_text": h1_text,
            "h1_is_chapter": h1_is_chapter,
            "has_intro": has_intro,
            "has_author_label": has_author_label,
        }

    # -- scores -------------------------------------------------------------

    @staticmethod
    def _chapter_score(f: dict) -> float:
        score = 0.0
        if f["content_len"] >= 800:
            score += 0.35
        elif f["content_len"] >= 300:
            score += 0.22
        if f["content_confidence"] >= 0.7:
            score += 0.15
        if f["nav_markers"] >= 2:
            score += 0.20
        elif f["nav_markers"] == 1:
            score += 0.10
        if f["h1_is_chapter"]:
            score += 0.25
            if f["catalog_marker"]:
                # h1 chapter title plus a 目录 link is typical chapter furniture
                score += 0.10
            if 0 < f["content_len"] < 100:
                # Chapter-titled page with a truncated body (VIP/login stubs
                # keep the chapter heading); structure says chapter page, the
                # content status detector decides whether it is usable.
                score += 0.10
        if f["link_ratio"] < 0.30:
            score += 0.10
        if f["chapter_like_links"] >= 8:
            score -= 0.25
        return max(0.0, min(0.95, score))

    @staticmethod
    def _catalog_score(f: dict) -> float:
        score = 0.0
        if f["chapter_like_links"] >= 30:
            score += 0.50
        elif f["chapter_like_links"] >= 15:
            score += 0.40
        elif f["chapter_like_links"] >= 8:
            score += 0.30
        elif f["chapter_like_links"] >= 5:
            score += 0.20
        if f["same_parent_cluster"] >= 10:
            score += 0.15
        elif f["same_parent_cluster"] >= 5:
            score += 0.10
        if f["content_len"] < 1500:
            score += 0.10
        if f["catalog_marker"]:
            score += 0.10
        # A page where most anchors are chapter titles is catalog-like even
        # when the list is short (small/old sites).
        if f["chapter_like_links"] >= 5 and f["chapter_like_ratio"] >= 0.6:
            score += 0.15
        return max(0.0, min(0.95, score))

    @staticmethod
    def _book_score(f: dict) -> float:
        score = 0.0
        if f["h1_text"] and not f["h1_is_chapter"]:
            score += 0.30
        if f["has_author_label"]:
            score += 0.25
        if f["has_intro"]:
            score += 0.15
        if f["chapter_like_links"] <= 5:
            score += 0.10
        if 200 <= f["content_len"] <= 2500:
            score += 0.10
        return max(0.0, min(0.85, score))

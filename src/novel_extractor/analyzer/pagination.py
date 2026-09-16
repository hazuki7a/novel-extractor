"""Pagination detection (catalog pages and chapter content pages).

Strict separation required by the guide: catalog pagination, content
pagination and chapter hops are three different relations. This module only
owns the first two; chapter hops live in analyzer/navigation.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from novel_extractor.fetcher.http import FetchError, Fetcher
from novel_extractor.models import DetectionResult, FetchedPage

_NEXT_CATALOG_WORDS = ("下一页", "下页", "next page", "next", "»", "›")
_PREV_CATALOG_WORDS = ("上一页", "上页", "previous page", "prev page", "prev", "previous", "«", "‹")
_CHAPTER_HOP_WORDS = ("下一章", "上一章", "下一节", "上一节", "下一回", "上一回", "下一话", "上一话")

_PAGE_QUERY_KEYS = {"page", "p", "pg", "pageindex", "page_index", "pageno"}
_PAGE_FILENAME_RE = re.compile(r"[_-](\d{1,4})\.s?html?$", re.IGNORECASE)
_FIRST_PAGE_FILENAME_RE = re.compile(r"(?:index|list|catalog|default)\.s?html?$", re.IGNORECASE)

_MIN_CONFIDENCE = 0.60


def normalize_url(url: str) -> str:
    """Lower-friction comparable form of a URL (drop fragment)."""
    url = (url or "").strip()
    parsed = urlparse(url)
    return urlunparse(parsed._replace(fragment=""))


def page_number_of(url: str) -> Optional[int]:
    """Extract a pagination page number from a URL, or None.

    Only pagination-shaped URLs match: query params like ?page=2 or filenames
    like list_2.html. Plain numeric chapter filenames (…/456.html) do not.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    query = parsed.query or ""
    for key in _PAGE_QUERY_KEYS:
        match = re.search(rf"(?:^|&){key}=(\d{{1,4}})(?:&|$)", query, re.IGNORECASE)
        if match:
            return int(match.group(1))
    match = _PAGE_FILENAME_RE.search(parsed.path)
    if match:
        return int(match.group(1))
    if _FIRST_PAGE_FILENAME_RE.search(parsed.path):
        return 1
    return None


@dataclass
class CatalogPagination:
    previous_catalog_page: Optional[str]
    next_catalog_page: Optional[str]
    confidence: float
    reason: str


@dataclass
class ContentPagination:
    previous_content_page: Optional[str]
    next_content_page: Optional[str]
    confidence: float
    reason: str


class _BasePaginationDetector:
    """Shared anchor scanning for both pagination detectors."""

    def _find_keyword_targets(self, soup: BeautifulSoup, words: tuple[str, ...]):
        targets: list[tuple[str, str, str]] = []  # (href, text, word)
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            text = a.get_text(strip=True).lower()
            if not text or len(text) > 20:
                continue
            for word in words:
                if word in text:
                    targets.append((href, text, word))
                    break
        return targets

    @staticmethod
    def _same_directory(current: str, target: str) -> bool:
        try:
            return urlparse(current).path.rsplit("/", 1)[0] == urlparse(target).path.rsplit("/", 1)[0]
        except ValueError:
            return False

    def _score_target(
        self, current_url: str, target: str, word: str, direction: str
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        absolute = urljoin(current_url, target)
        # Keyword + staying in the same directory is already solid evidence.
        score = 0.62
        reasons.append(f"anchor text contains '{word}'")
        if not self._same_directory(current_url, absolute):
            return 0.0, ["target URL leaves the current directory"]
        if absolute.rstrip("/") == current_url.rstrip("/"):
            return 0.0, ["target equals current page"]
        current_no = page_number_of(current_url)
        target_no = page_number_of(absolute)
        if current_no is not None and target_no is not None:
            if direction == "next" and target_no == current_no + 1:
                score += 0.25
                reasons.append(f"page number {current_no}->{target_no}")
            elif direction == "prev" and target_no == current_no - 1:
                score += 0.25
                reasons.append(f"page number {current_no}->{target_no}")
            else:
                score -= 0.15
                reasons.append(f"non-adjacent page numbers {current_no}->{target_no}")
        return max(0.0, min(0.95, score)), reasons


class CatalogPaginationDetector(_BasePaginationDetector):
    """Find previous/next catalog page links on a catalog page.

    Chapter hops (下一章) are deliberately ignored here.
    """

    def detect(self, html: str, current_url: str) -> DetectionResult[CatalogPagination]:
        soup = BeautifulSoup(html, "lxml")
        diagnostics: dict[str, Any] = {}

        next_pick = self._best(soup, current_url, _NEXT_CATALOG_WORDS, "next", diagnostics)
        prev_pick = self._best(soup, current_url, _PREV_CATALOG_WORDS, "prev", diagnostics)

        confidence = max(next_pick[0] if next_pick else 0.0, prev_pick[0] if prev_pick else 0.0)
        reasons = []
        if next_pick:
            reasons.append(f"next: '{next_pick[2]}' -> {next_pick[1]}")
        if prev_pick:
            reasons.append(f"prev: '{prev_pick[2]}' -> {prev_pick[1]}")
        reason = "; ".join(reasons) if reasons else "no catalog pagination links found"

        result = CatalogPagination(
            previous_catalog_page=urljoin(current_url, prev_pick[1]) if prev_pick else None,
            next_catalog_page=urljoin(current_url, next_pick[1]) if next_pick else None,
            confidence=round(confidence, 3),
            reason=reason,
        )
        return DetectionResult(value=result, confidence=round(confidence, 3), reason=reason, diagnostics=diagnostics)

    def _best(self, soup, current_url, words, direction, diagnostics):
        candidates = []
        for href, text, word in self._find_keyword_targets(soup, words):
            score, reasons = self._score_target(current_url, href, word, direction)
            if score > 0:
                candidates.append((score, href, reasons))
        if not candidates:
            # Fallback for sites that paginate with bare numeric page links
            # (1 2 3 4) instead of 下一页/上一页 words.
            numeric = self._numeric_candidate(soup, current_url, direction)
            if numeric:
                candidates.append(numeric)
                diagnostics[f"{direction}_numeric_fallback"] = True
        if not candidates:
            if self._find_keyword_targets(soup, words):
                diagnostics[f"{direction}_rejected"] = "keyword anchor found but URL not pagination-shaped"
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, href, reasons = candidates[0]
        word = "page number link"
        for candidate_href, _text, matched_word in self._find_keyword_targets(soup, words):
            if candidate_href == href:
                word = matched_word
                break
        diagnostics[f"{direction}_candidates"] = len(candidates)
        return (round(score, 3), href, word)

    _NUMERIC_TEXT_RE = re.compile(r"^\d{1,4}$")

    def _numeric_candidate(self, soup, current_url: str, direction: str):
        current_no = page_number_of(current_url)
        if current_no is None:
            return None
        wanted = current_no + 1 if direction == "next" else current_no - 1
        if wanted < 1:
            return None
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            text = a.get_text(strip=True)
            if not self._NUMERIC_TEXT_RE.match(text):
                continue
            absolute = urljoin(current_url, href)
            if page_number_of(absolute) != wanted:
                continue
            if not self._same_directory(current_url, absolute):
                continue
            return (0.62, absolute, [f"numeric page link {text} adjacent to current {current_no}"])
        return None


class CatalogPaginationMerger:
    """Follow next-catalog-page links to assemble the full catalog page list."""

    def __init__(
        self,
        fetcher: Fetcher,
        detector: Optional[CatalogPaginationDetector] = None,
        max_pages: int = 20,
    ):
        self._fetcher = fetcher
        self._detector = detector or CatalogPaginationDetector()
        self._max_pages = max_pages

    def walk(self, start: FetchedPage) -> tuple[list[FetchedPage], dict[str, Any]]:
        pages = [start]
        diagnostics: dict[str, Any] = {"pages_visited": 1, "chain": [], "stopped_by": "no_next"}
        visited = {normalize_url(start.final_url)}
        current = start

        while len(pages) < self._max_pages:
            detection = self._detector.detect(current.html, current.final_url)
            if detection.value.next_catalog_page is None or detection.confidence < _MIN_CONFIDENCE:
                diagnostics["stopped_by"] = "no_next"
                break
            next_url = normalize_url(detection.value.next_catalog_page)
            if next_url in visited:
                diagnostics["stopped_by"] = "loop"
                break
            try:
                page = self._fetcher.fetch(next_url)
            except FetchError as exc:
                diagnostics["stopped_by"] = "fetch_error"
                diagnostics["error"] = str(exc)
                break
            visited.add(next_url)
            diagnostics["chain"].append(next_url)
            pages.append(page)
            diagnostics["pages_visited"] = len(pages)
            current = page

        if len(pages) >= self._max_pages:
            diagnostics["stopped_by"] = "max_pages"
        return pages, diagnostics


class ContentPaginationDetector(CatalogPaginationDetector):
    """Find previous/next content page links on a chapter page.

    A chapter split over several pages uses the same pagination vocabulary as
    a catalog (下一页/上一页/数字页码); which detector applies is decided by
    the caller from the page type. The detectors stay separate classes so the
    relation kinds are never conflated (guide page_relation_model).
    """

    def detect(self, html: str, current_url: str) -> DetectionResult[ContentPagination]:
        base = super().detect(html, current_url)
        catalog = base.value
        result = ContentPagination(
            previous_content_page=catalog.previous_catalog_page,
            next_content_page=catalog.next_catalog_page,
            confidence=catalog.confidence,
            reason=catalog.reason,
        )
        return DetectionResult(
            value=result,
            confidence=base.confidence,
            reason=base.reason,
            diagnostics=base.diagnostics,
        )


# Decorations sites append to chapter titles on continuation pages:
# 第一章 xxx(2/3) / (第2页) / （二） / _2 / -3
_PAGE_SUFFIX_RE = re.compile(
    r"[（(]\s*(?:第\s*\d+\s*页|\d+\s*/\s*\d+|\d+)\s*[)）]\s*$"
    r"|[_-]\d{1,3}$"
    r"|第\s*\d+\s*页$"
)


def has_page_marker(title: str) -> bool:
    """Explicit per-page index in the title: 第1章（第2页） / (2/3).

    This is the STRONG evidence required before a 下一章-labelled link may be
    treated as in-chapter pagination (guide: chapter hops and pagination are
    different relations; only a title-borne page marker justifies merging).
    Bracketed markers are searched anywhere in the title because sites append
    their own suffixes (第1章（第2页）_书名 - 某站). Bare trailing numbers are
    too weak for an anywhere search and are deliberately not accepted here.
    """
    return bool(_PAGE_MARKER_ANYWHERE_RE.search(title))


_PAGE_MARKER_ANYWHERE_RE = re.compile(
    r"[（(]\s*第\s*\d+\s*页\s*[)）]|[（(]\s*\d+\s*/\s*\d+\s*[)）]"
)


def strip_page_suffix(title: str) -> str:
    prev = None
    while prev != title:
        prev = title
        title = _PAGE_SUFFIX_RE.sub("", title).strip()
    return title


def page_title(html: str) -> str:
    """Return the strongest chapter-title candidate on the page.

    A page's first ``h1`` is not necessarily its chapter heading: many sites
    use an ``h1`` for the site logo and put the chapter title in ``h2``.  Scan
    the visible heading levels and prefer a candidate that the generic chapter
    title detector recognizes with high confidence.  Only fall back to the old
    h1/title behaviour when no structured chapter heading exists.
    """
    soup = BeautifulSoup(html, "lxml")
    headings = [
        node.get_text(strip=True)
        for node in soup.find_all(("h1", "h2", "h3"))
        if node.get_text(strip=True)
    ]

    from novel_extractor.analyzer.chapter import ChapterTitleDetector

    detector = ChapterTitleDetector()
    for candidate in headings:
        match = detector.parse(candidate)
        if match is not None and match.confidence >= 0.85:
            return candidate

    if headings:
        return headings[0]
    title = soup.find("title")
    return title.get_text(strip=True) if title else ""


class ContentPaginationMerger:
    """Follow next-content-page links and merge one logical chapter.

    Guard against swallowing the next chapter: a candidate page whose title
    parses to a different chapter number ends the walk. Merged text is the
    page contents joined in traversal order; title dedup happens in the
    cleaner (guide task 13), not here.
    """

    def __init__(
        self,
        fetcher: Fetcher,
        detector: Optional[ContentPaginationDetector] = None,
        chapter_detector: Optional["ChapterTitleDetector"] = None,
        max_pages: int = 10,
        content_extractor: Optional[Any] = None,
        navigation_detector: Optional[Any] = None,
    ):
        self._fetcher = fetcher
        self._detector = detector or ContentPaginationDetector()
        from novel_extractor.analyzer.chapter import ChapterTitleDetector

        self._chapter = chapter_detector or ChapterTitleDetector()
        self._max_pages = max_pages
        from novel_extractor.analyzer.content import ContentExtractor

        self._extractor = content_extractor or ContentExtractor()
        if navigation_detector is None:
            from novel_extractor.analyzer.navigation import ChapterNavigationDetector

            navigation_detector = ChapterNavigationDetector()
        self._navigation = navigation_detector

    def _page_title(self, html: str) -> str:
        return page_title(html)

    def _chapter_number_of(self, html: str) -> Optional[float]:
        match = self._chapter.parse(self._page_title(html))
        return match.order_token if match else None

    def walk(self, start: FetchedPage, fast: bool = False) -> tuple[list[FetchedPage], list[str], dict[str, Any]]:
        """Return (pages in order, content texts in order, diagnostics).

        fast=True skips the trafilatura baseline per page (inference-cache
        fast path); callers verify results and can retry with fast=False."""

        pages = [start]
        diagnostics: dict[str, Any] = {"pages_visited": 1, "chain": [], "stopped_by": "no_next"}
        visited = {normalize_url(start.final_url)}
        current = start
        start_number = self._chapter_number_of(start.html)
        start_title = strip_page_suffix(self._page_title(start.html))

        while len(pages) < self._max_pages:
            detection = self._detector.detect(current.html, current.final_url)
            next_url: Optional[str] = None
            hypothesis = False
            if detection.value.next_content_page and detection.confidence >= _MIN_CONFIDENCE:
                next_url = detection.value.next_content_page
            else:
                # Fallback hypothesis: some sites label in-chapter page turns
                # with chapter-hop words (下一章). The candidate is accepted
                # ONLY after the target title proves an explicit page marker
                # with the same main chapter number (verification below).
                nav = self._navigation.detect(current.html, current.final_url)
                if nav.confidence >= _MIN_CONFIDENCE:
                    candidate = nav.value.get("next_chapter")
                    if candidate:
                        next_url = candidate
                        hypothesis = True
            if next_url is None:
                diagnostics["stopped_by"] = "no_next"
                break
            next_url_norm = normalize_url(next_url)
            if next_url_norm in visited:
                diagnostics["stopped_by"] = "loop"
                break
            try:
                page = self._fetcher.fetch(next_url)
            except FetchError as exc:
                diagnostics["stopped_by"] = "fetch_error"
                diagnostics["error"] = str(exc)
                break

            next_title = self._page_title(page.html)
            next_number = self._chapter_number_of(page.html)

            # A 下一章-labelled link is only trusted as pagination when the
            # target title carries an explicit page marker on the SAME main
            # chapter (第1章（第2页）). Without that proof it stays a hop.
            if hypothesis and not has_page_marker(next_title):
                diagnostics["stopped_by"] = "no_page_marker"
                diagnostics["rejected_url"] = next_url
                break
            if (
                hypothesis
                and start_number is not None
                and next_number is not None
                and int(next_number) != int(start_number)
            ):
                diagnostics["stopped_by"] = "different_chapter"
                diagnostics["rejected_url"] = next_url
                break

            if (
                start_number is not None
                and next_number is not None
                and next_number != start_number
            ):
                diagnostics["stopped_by"] = "different_chapter"
                diagnostics["rejected_url"] = next_url
                break
            if start_number is None and next_number is not None:
                # Start page had no parseable number; accept the continuation
                # only when its de-suffixed title matches the start title.
                candidate_title = strip_page_suffix(next_title)
                if not (start_title and candidate_title == start_title):
                    diagnostics["stopped_by"] = "different_chapter"
                    diagnostics["rejected_url"] = next_url
                    break

            visited.add(next_url_norm)
            diagnostics["chain"].append(next_url)
            pages.append(page)
            diagnostics["pages_visited"] = len(pages)
            current = page

        if len(pages) >= self._max_pages:
            diagnostics["stopped_by"] = "max_pages"

        texts = [self._extractor.extract(p.html, fast=fast).text for p in pages]

        # A common extraction failure is selecting the same recommendation or
        # ranking block on every physical page.  Keep this site-agnostic: only
        # flag long, exactly repeated extracted texts, and let the crawler
        # refuse to report the logical chapter as healthy.
        occurrences: dict[str, list[int]] = {}
        for index, text in enumerate(texts, start=1):
            normalized = re.sub(r"\s+", "", text or "")
            if len(normalized) >= 300:
                occurrences.setdefault(normalized, []).append(index)
        duplicate_groups = [indexes for indexes in occurrences.values() if len(indexes) >= 2]
        if duplicate_groups:
            diagnostics["duplicate_content_pages"] = duplicate_groups

        return pages, texts, diagnostics

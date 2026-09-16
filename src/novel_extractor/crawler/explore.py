"""Local Site Exploration (guide task 24 / V2).

When a page yields no catalog and chapter-link traversal is impossible,
explore a small budget of high-value candidate links (目录/全部章节/开始阅读
style anchors, same host only) looking for a catalog page. Deterministic,
bounded, loop-free - and every visit is classified and recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from novel_extractor.analyzer.catalog import CatalogDetector
from novel_extractor.analyzer.page_type import PageTypeDetector
from novel_extractor.fetcher.http import FetchError, FetchedPage, Fetcher
from novel_extractor.models import PageType

_CANDIDATE_WORDS = (
    "目录", "章节目录", "全部章节", "章节列表", "查看目录", "开始阅读",
    "点击阅读", "正文", "返回书页", "作品主页",
)
_MAX_TEXT_LEN = 12


@dataclass
class ExplorationResult:
    visited: list[str] = field(default_factory=list)
    catalog_url: Optional[str] = None
    chapter_hints: list[tuple[str, str]] = field(default_factory=list)
    stop_reason: str = "no_candidates"
    map_summary: dict[str, str] = field(default_factory=dict)


class LocalSiteExplorer:
    def __init__(
        self,
        fetcher: Fetcher,
        allowed_host: str,
        page_type_detector: Optional[PageTypeDetector] = None,
        catalog_detector: Optional[CatalogDetector] = None,
        budget: int = 8,
        allowed: Optional[object] = None,
    ):
        self._fetcher = fetcher
        self._allowed_host = allowed_host
        self._page_type = page_type_detector or PageTypeDetector()
        self._catalog = catalog_detector or CatalogDetector()
        self.budget = budget
        self._allowed = allowed  # optional callable(url) -> bool (crawler domain guard)

    def explore(self, start: FetchedPage) -> ExplorationResult:
        result = ExplorationResult()
        visited: set[str] = {start.final_url}
        candidates = self._candidate_links(start.html, start.final_url)

        if not candidates:
            result.stop_reason = "no_candidates"
            return result
        for url in candidates:
            if len(result.visited) >= self.budget:
                result.stop_reason = "budget"
                break
            if url in visited:
                result.stop_reason = "cycle"
                continue
            if not self._url_allowed(url):
                continue
            try:
                page = self._fetcher.fetch(url)
            except FetchError:
                continue
            visited.add(url)
            result.visited.append(url)

            detected = self._page_type.classify(page.html)
            result.map_summary[url] = detected.value.value
            if detected.value is PageType.CATALOG_PAGE and detected.confidence >= 0.5:
                catalog = self._catalog.detect(page.html, base_url=page.final_url)
                if catalog.chapters:
                    result.catalog_url = page.final_url
                    result.chapter_hints = [(e.title, e.url) for e in catalog.chapters]
                    result.stop_reason = "catalog_found"
                    break
            # record chapter-like links seen along the way
            for title, href in self._chapter_links(page.html):
                absolute = urljoin(page.final_url, href)
                result.chapter_hints.append((title, absolute))
        if result.stop_reason == "no_candidates" and result.visited:
            result.stop_reason = "budget"
        return result

    # -- internals ----------------------------------------------------------

    def _url_allowed(self, url: str) -> bool:
        if self._allowed is not None:
            return bool(self._allowed(url))
        return urlparse(url).netloc.lower() == self._allowed_host

    @staticmethod
    def _candidate_links(html: str, base_url: str) -> list[str]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        out: list[str] = []
        seen: set[str] = set()
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            text = a.get_text(strip=True)
            if not text or len(text) > _MAX_TEXT_LEN:
                continue
            if not any(word in text for word in _CANDIDATE_WORDS):
                continue
            absolute = urljoin(base_url, href)
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        return out

    @staticmethod
    def _chapter_links(html: str) -> list[tuple[str, str]]:
        from novel_extractor.analyzer.chapter import ChapterTitleDetector
        from bs4 import BeautifulSoup

        detector = ChapterTitleDetector()
        soup = BeautifulSoup(html, "lxml")
        out: list[tuple[str, str]] = []
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            text = a.get_text(strip=True)
            if not text or len(text) > 60:
                continue
            match = detector.parse(text)
            if match and match.confidence >= 0.85:
                out.append((text, href))
        return out

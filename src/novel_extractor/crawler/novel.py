"""MVP NovelCrawler.

Orchestrates the whole pipeline: classify the start page, find and merge the
catalog (including catalog pagination), resolve reading direction, then
download chapter by chapter (merging in-chapter pagination), classify content
status, clean text conservatively and assemble LogicalChapters.

Safety rails (guide crawl_strategy.safety): URL dedupe, loop protection,
max chapter / pagination caps, request interval, limited retries,
cross-domain forbidden by default, abnormal jump detection. URL numbering is
never used to reconstruct chapters.
"""

from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from novel_extractor.analyzer.catalog import CatalogDetector
from novel_extractor.analyzer.catalog_order import CatalogOrderDetector, reorder_segmented
from novel_extractor.analyzer.chapter import ChapterTitleDetector, strip_sub_number
from novel_extractor.analyzer.collapsed_list import CollapsedListExpander, OnclickNavResolver
from novel_extractor.analyzer.content import ContentExtractor
from novel_extractor.analyzer.content_status import ContentStatusDetector
from novel_extractor.analyzer.local_deep_analysis import LocalDeepAnalyzer
from novel_extractor.analyzer.metadata import MetadataExtractor
from novel_extractor.analyzer.navigation import ChapterNavigationDetector
from novel_extractor.analyzer.page_type import PageTypeDetector
from novel_extractor.cache import InferenceCache
from novel_extractor.analyzer.pagination import (
    CatalogPaginationMerger,
    ContentPaginationDetector,
    ContentPaginationMerger,
    has_page_marker,
    normalize_url,
    page_title,
    strip_page_suffix,
)
from novel_extractor.cleaner.text import TextCleaner
from novel_extractor.fetcher.http import FetchError, Fetcher, HttpFetcher
from novel_extractor.crawler.explore import LocalSiteExplorer
from novel_extractor.graph import NovelGraph
from novel_extractor.models import (
    BookMetadata,
    CatalogDirection,
    CatalogEntry,
    CatalogResult,
    ContentStatus,
    FetchedPage,
    LogicalChapter,
    PageType,
    RelationType,
)

_STRONG_TITLE_CONFIDENCE = 0.85
_BOOK_CATALOG_LINK_WORDS = (
    "目录", "章节目录", "查看目录", "全部章节", "章节列表", "开始阅读", "点击阅读", "正文",
)
_MAX_CATALOG_LINK_TRIES = 3
_MAX_CONSECUTIVE_FAILURES = 5


@dataclass
class CrawlOptions:
    max_chapters: int = 2000
    max_catalog_pages: int = 20
    max_content_pages: int = 10
    # Request pace. With adaptive_interval the actual delay starts here,
    # backs off multiplicatively on empty/anti-bot shells or fetch errors,
    # and decays back toward this floor after a streak of healthy chapters.
    # With adaptive_interval=False this exact value is used for every request.
    request_interval: float = 0.0
    adaptive_interval: bool = True
    max_interval: float = 5.0
    backoff_factor: float = 2.0
    recover_after: int = 6
    recover_factor: float = 0.85
    max_retries: int = 2
    retry_backoff: float = 0.5
    cross_domain: bool = False
    # Upper bound for filling one catalog gap by following next-chapter links.
    max_gap_fill: int = 50
    # Merge consecutive per-part chapters (第6章 1 / 第6章 2 ...) of the same
    # main chapter into one LogicalChapter.
    merge_parts: bool = True
    # Local Site Exploration page budget (0 disables exploration).
    exploration_budget: int = 8
    # Transient empty/anti-bot shells get re-fetched this many times after a
    # polite pause before their status is accepted.
    status_retries: int = 2
    status_retry_delay: float = 8.0


@dataclass
class CrawlResult:
    metadata: BookMetadata = field(default_factory=BookMetadata)
    catalog: Optional[CatalogResult] = None
    direction: CatalogDirection = CatalogDirection.UNKNOWN
    direction_reason: str = ""
    chapters: list[LogicalChapter] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    graph: Optional["NovelGraph"] = None

    def export_txt(self, output_root: str | Any = "output", merged: bool = True):
        """Convenience wrapper (guide Python API example); the exporter is
        imported lazily to avoid a cycle."""
        from novel_extractor.exporter.txt import TxtExporter

        return TxtExporter(output_root=output_root).export(self, merged=merged)


class _CachingFetcher:
    """Fetcher wrapper adding URL dedupe, retries, pacing and same-domain guard.

    With adaptive pacing the delay starts at ``request_interval``, multiplies
    on shells/errors and decays back after a healthy streak: the site's own
    throttling signals drive the speed instead of a fixed compromise value.
    """

    def __init__(self, fetcher: Fetcher, options: CrawlOptions, allowed_host: str):
        self._fetcher = fetcher
        self._options = options
        self._allowed_host = allowed_host
        self.cache: dict[str, FetchedPage] = {}
        self.last_request_at = 0.0
        self.current_interval = max(0.0, options.request_interval)
        self._ok_streak = 0
        self.stats = {
            "fetched": 0, "cache_hits": 0, "retries": 0,
            "cross_domain_skipped": 0, "backoffs": 0,
        }

    def report_shell(self) -> None:
        """A fetched page turned out to be an empty/anti-bot shell."""
        if not self._options.adaptive_interval:
            return
        if self._options.request_interval <= 0:
            return  # pacing disabled altogether - nothing to adapt
        base = max(self.current_interval, self._options.request_interval)
        self.current_interval = min(self._options.max_interval, base * self._options.backoff_factor)
        self._ok_streak = 0
        self.stats["backoffs"] += 1

    def report_success(self) -> None:
        """A chapter processed cleanly - after a healthy streak, step back
        down one backoff notch (symmetric with the backoff ladder)."""
        if not self._options.adaptive_interval:
            return
        self._ok_streak += 1
        if self._ok_streak >= self._options.recover_after:
            self.current_interval = max(
                self._options.request_interval,
                self.current_interval / self._options.backoff_factor,
            )
            self._ok_streak = 0

    def allowed(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        if not host:
            return False
        return self._options.cross_domain or host == self._allowed_host

    def fetch(self, url: str, *, referer: Optional[str] = None, fresh: bool = False) -> FetchedPage:
        key = normalize_url(url)
        if not fresh and key in self.cache:
            self.stats["cache_hits"] += 1
            return self.cache[key]
        if not self.allowed(url):
            self.stats["cross_domain_skipped"] += 1
            raise FetchError(url, "cross-domain fetching disabled by default")
        if self.current_interval > 0:
            wait = self.current_interval - (time.monotonic() - self.last_request_at)
            if wait > 0:
                time.sleep(wait)
        last_error: Optional[Exception] = None
        for attempt in range(self._options.max_retries + 1):
            try:
                page = self._fetcher.fetch(url, referer=referer)
                self.last_request_at = time.monotonic()
                self.stats["fetched"] += 1
                self.cache[key] = page
                return page
            except FetchError as exc:
                last_error = exc
                self.stats["retries"] += 1
                self.report_shell()  # network trouble is a slowdown signal too
                if attempt < self._options.max_retries:
                    time.sleep(self._options.retry_backoff * (attempt + 1))
        raise last_error if last_error else FetchError(url, "unknown fetch failure")


class NovelCrawler:
    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        options: Optional[CrawlOptions] = None,
        page_type_detector: Optional[PageTypeDetector] = None,
        catalog_detector: Optional[CatalogDetector] = None,
        catalog_order_detector: Optional[CatalogOrderDetector] = None,
        navigation_detector: Optional[ChapterNavigationDetector] = None,
        content_extractor: Optional[ContentExtractor] = None,
        chapter_detector: Optional[ChapterTitleDetector] = None,
        metadata_extractor: Optional[MetadataExtractor] = None,
        content_status_detector: Optional[ContentStatusDetector] = None,
        cleaner: Optional[TextCleaner] = None,
        collapsed_expander: Optional[CollapsedListExpander] = None,
        progress: Optional[Any] = None,
        cache: Optional[InferenceCache] = None,
    ):
        self._options = options or CrawlOptions()
        self._fetcher = fetcher or HttpFetcher()
        self._page_type = page_type_detector or PageTypeDetector(
            content_extractor=content_extractor
        )
        self._catalog = catalog_detector or CatalogDetector(
            chapter_detector, onclick_resolver=OnclickNavResolver()
        )
        self._order = catalog_order_detector or CatalogOrderDetector(chapter_detector)
        self._navigation = navigation_detector or ChapterNavigationDetector()
        self._content = content_extractor or ContentExtractor()
        self._chapter = chapter_detector or ChapterTitleDetector()
        self._metadata = metadata_extractor or MetadataExtractor()
        self._status = content_status_detector or ContentStatusDetector()
        self._cleaner = cleaner or TextCleaner()
        self._deep = LocalDeepAnalyzer(self._chapter)
        self._expander = collapsed_expander or CollapsedListExpander(self._chapter)
        self._content_pagination = ContentPaginationDetector()
        self._progress = progress
        self._cache = cache

    # -- public API ---------------------------------------------------------

    def crawl(self, url: str) -> CrawlResult:
        start = self._fetcher.fetch(url)
        allowed_host = urlparse(start.final_url).netloc.lower()
        wrapped = _CachingFetcher(self._fetcher, self._options, allowed_host)
        self._wrapped = wrapped

        result = CrawlResult()
        graph: Optional[NovelGraph] = None
        stats: dict[str, Any] = {"start_url": url, "warnings": []}
        page_type = self._page_type.classify(start.html)
        stats["start_page_type"] = page_type.value.value

        metadata = self._metadata.extract(start.html)
        catalog, catalog_pages_visited = self._resolve_catalog(start, page_type, wrapped, stats)

        if metadata.book_title is None and catalog is not None and catalog.source_pages:
            catalog_page = wrapped.fetch(catalog.source_pages[0])
            refined = self._metadata.extract(catalog_page.html)
            if refined.book_title:
                metadata = refined

        chapters: list[LogicalChapter]
        # Last resort when the start page yields no catalog: explore a small
        # budget of candidate links looking for a catalog page (guide task 24).
        if (catalog is None or not catalog.chapters) and self._options.exploration_budget > 0:
            explorer = LocalSiteExplorer(
                wrapped,
                urlparse(start.final_url).netloc.lower(),
                page_type_detector=self._page_type,
                catalog_detector=self._catalog,
                budget=self._options.exploration_budget,
                allowed=wrapped.allowed,
            )
            exploration = explorer.explore(start)
            stats["exploration"] = {
                "visited": exploration.visited,
                "stop_reason": exploration.stop_reason,
                "catalog_url": exploration.catalog_url,
            }
            if exploration.catalog_url:
                stats["warnings"].append(
                    f"局部探索找到目录页：{exploration.catalog_url}（访问 {len(exploration.visited)} 页）"
                )
                try:
                    catalog_start = wrapped.fetch(exploration.catalog_url)
                    detected_type = self._page_type.classify(catalog_start.html)
                    catalog, _visited = self._resolve_catalog(
                        catalog_start, detected_type, wrapped, stats
                    )
                except FetchError as exc:
                    stats["warnings"].append(f"探索到的目录页抓取失败：{exc.cause}")

        if catalog is not None and catalog.chapters:
            direction = self._order.detect(catalog.chapters)
            result.direction = direction.value
            result.direction_reason = direction.reason
            entries = list(catalog.chapters)
            if direction.value is CatalogDirection.DESCENDING:
                entries.reverse()
            elif direction.value is CatalogDirection.UNKNOWN:
                stats["warnings"].append(
                    "catalog direction UNKNOWN; using DOM order without reversal"
                )
            segmented = reorder_segmented(entries, self._chapter)
            if segmented is not None:
                entries = segmented
                stats["warnings"].append(
                    "目录呈分段错位（两段各自正序、后段编号更小），已重排为编号升序"
                )
            entries = self._fill_gaps_via_navigation(entries, wrapped, stats)
            stats["warnings"].extend(self._detect_gaps(entries))
            chapters = self._download_by_catalog(entries, wrapped, stats)
            chapters = self._merge_part_chapters(chapters, stats)
            graph = NovelGraph(self._chapter)
            keys = [graph.add_chapter(c) for c in chapters]
            edge_confidence = 0.9 if direction.value is CatalogDirection.ASCENDING else 0.6
            for key_a, key_b in zip(keys, keys[1:]):
                graph.add_edge(
                    key_a, RelationType.NEXT_CHAPTER, key_b,
                    confidence=edge_confidence,
                    reason=f"catalog order ({direction.value})",
                )
        else:
            stats["warnings"].append("no catalog found; falling back to chapter-link traversal")
            if page_type.value not in (PageType.CHAPTER_PAGE, PageType.UNKNOWN):
                stats["warnings"].append(
                    f"traversal needs a chapter page but start page is {page_type.value.value}"
                )
            chapters, graph = self._traverse_without_catalog(start, wrapped, stats)

        self._remove_recurrent_boilerplate(chapters, stats)

        if self._cache is not None and chapters and chapters[0].source_pages:
            first = wrapped.cache.get(normalize_url(chapters[0].source_pages[0]))
            if first is not None:
                self._cache.put(self._cache.profile_from_page(first.html, first.final_url))
            stats["cache_enabled"] = True

        result.metadata = metadata
        result.catalog = catalog
        result.chapters = chapters
        if graph is not None:
            result.graph = graph
            diag = graph.diagnostics()
            if diag.cycle:
                stats["warnings"].append(f"章节关系图存在环：{diag.cycle}")
            for dup in diag.duplicates[:5]:
                stats["warnings"].append(f"重复章节节点：{dup}")
        result.stats = self._finalize_stats(stats, wrapped, chapters)
        return result

    @staticmethod
    def _remove_recurrent_boilerplate(chapters: list[LogicalChapter], stats: dict[str, Any]) -> None:
        """Remove long blocks repeated across many different chapters.

        Recommendation cards and ranking summaries are often injected without
        a stable heading or CSS class, so per-page keyword filters cannot
        reliably identify them. Exact long prose blocks recurring throughout
        a book are strong template evidence. Short phrases are deliberately
        excluded to preserve dialogue, refrains and ordinary repeated wording.
        """
        if len(chapters) < 3:
            return

        threshold = max(3, (len(chapters) + 9) // 10)
        chapter_blocks: list[list[tuple[str, str]]] = []
        seen_in_chapters: dict[str, set[int]] = {}

        for chapter_index, chapter in enumerate(chapters):
            blocks: list[tuple[str, str]] = []
            for block in re.split(r"\n\s*\n", chapter.content or ""):
                block = block.strip()
                if not block:
                    continue
                normalized = re.sub(r"\s+", "", block)
                blocks.append((block, normalized))
                if len(normalized) >= 60:
                    seen_in_chapters.setdefault(normalized, set()).add(chapter_index)
            chapter_blocks.append(blocks)

        recurrent = {
            normalized
            for normalized, chapter_indexes in seen_in_chapters.items()
            if len(chapter_indexes) >= threshold
        }
        if not recurrent:
            return

        affected = 0
        removed = 0
        emptied: list[str] = []
        for chapter, blocks in zip(chapters, chapter_blocks):
            kept = [block for block, normalized in blocks if normalized not in recurrent]
            chapter_removed = len(blocks) - len(kept)
            if not chapter_removed:
                continue
            affected += 1
            removed += chapter_removed
            chapter.content = "\n\n".join(kept).strip()
            if not chapter.content and chapter.content_status is ContentStatus.CONTENT_OK:
                chapter.content_status = ContentStatus.UNKNOWN_FAILURE
                chapter.confidence = min(chapter.confidence, 0.2)
                emptied.append(chapter.title)

        stats["recurrent_boilerplate"] = {
            "unique_blocks": len(recurrent),
            "removed_occurrences": removed,
            "chapters_affected": affected,
            "chapter_threshold": threshold,
        }
        stats["warnings"].append(
            f"已按跨章节重复模板清除 {len(recurrent)} 类长段落，"
            f"共 {removed} 处，涉及 {affected} 章"
        )
        if emptied:
            stats["warnings"].append(
                "清除重复模板后正文为空，已标记异常：" + "、".join(emptied[:10])
            )

    # -- catalog resolution -------------------------------------------------

    def _resolve_catalog(self, start, page_type, wrapped: _CachingFetcher, stats) -> tuple[Optional[CatalogResult], int]:
        candidate_pages: list[FetchedPage] = [start]

        if page_type.value in (PageType.CHAPTER_PAGE, PageType.BOOK_PAGE):
            extra = self._find_catalog_page(start, wrapped, stats)
            if extra is not None:
                candidate_pages.append(extra)

        all_entries: list[CatalogEntry] = []
        expansions: list[tuple[str, Optional[str], list[CatalogEntry]]] = []
        visited_pages: set[str] = set()
        source_pages: list[str] = []

        for page in candidate_pages:
            if normalize_url(page.final_url) in visited_pages:
                continue
            visited_pages.add(normalize_url(page.final_url))
            first_catalog = self._catalog.detect(page.html, base_url=page.final_url)
            if not first_catalog.chapters:
                continue
            if first_catalog.confidence < 0.5:
                stats["warnings"].append(
                    f"catalog on {page.final_url} has low confidence ({first_catalog.confidence})"
                )
            all_entries.extend(first_catalog.chapters)
            source_pages.append(page.final_url)
            self._expand_collapsed(page, wrapped, expansions, stats)
            merger = CatalogPaginationMerger(wrapped, max_pages=self._options.max_catalog_pages)
            pages, _diagnostics = merger.walk(page)
            for walked in pages[1:]:  # the start page is already collected
                if normalize_url(walked.final_url) in visited_pages:
                    continue
                visited_pages.add(normalize_url(walked.final_url))
                page_catalog = self._catalog.detect(walked.html, base_url=walked.final_url)
                for entry in page_catalog.chapters:
                    # Re-index across pages: each page numbers its own anchors
                    # from zero, so a global running index preserves walk order.
                    all_entries.append(
                        CatalogEntry(
                            title=entry.title,
                            url=entry.url,
                            source_page_url=entry.source_page_url,
                            dom_index=len(all_entries),
                        )
                    )
                source_pages.append(walked.final_url)
                self._expand_collapsed(walked, wrapped, expansions, stats)
                if self._options.max_chapters and len(all_entries) > self._options.max_chapters * 2:
                    break

        if not all_entries:
            return None, 0

        # Keep-last dedupe by URL: teaser blocks ("最新章节") repeat chapters
        # that also appear in the full list; the later occurrence wins and
        # keeps its position, so the main ordered list prevails.
        last_by_url: dict[str, tuple[int, CatalogEntry]] = {}
        for position, entry in enumerate(all_entries):
            last_by_url[normalize_url(entry.url)] = (position, entry)
        stats["duplicates_removed"] = len(all_entries) - len(last_by_url)
        ordered = [
            entry
            for _position, entry in sorted(last_by_url.values(), key=lambda pair: pair[0])
        ]
        ordered = self._splice_expansions(ordered, expansions)

        catalog = CatalogResult(
            chapters=ordered,
            direction=CatalogDirection.UNKNOWN,
            source_pages=source_pages,
            confidence=max(
                (self._catalog.detect(p.html, base_url=p.final_url).confidence for p in candidate_pages),
                default=0.0,
            ),
            reason=f"{len(ordered)} entries across {len(source_pages)} catalog page(s)",
        )
        return catalog, len(source_pages)

    def _expand_collapsed(self, page: FetchedPage, wrapped: _CachingFetcher,
                          expansions: list, stats: dict) -> None:
        """Expand a hidden middle segment (展开完整列表 style) if present."""
        if not self._expander.has_marker(page.html):
            return
        page_url = page.final_url

        def fetch_data(url: str) -> FetchedPage:
            return wrapped.fetch(url, referer=page_url)

        result = self._expander.expand(page.html, page_url, fetch_data)
        if result.value.entries and result.confidence >= 0.5:
            after = normalize_url(urljoin(page_url, result.value.after_href)) if result.value.after_href else None
            before = normalize_url(urljoin(page_url, result.value.before_href)) if result.value.before_href else None
            expansions.append((after, before, result.value.entries))
            stats["warnings"].append(f"已展开折叠目录段：{result.value.reason}")
        else:
            stats["warnings"].append(f"检测到折叠目录标记但未能展开：{result.reason}")

    @staticmethod
    def _splice_expansions(ordered: list[CatalogEntry],
                           expansions: list[tuple[str, Optional[str], list[CatalogEntry]]]) -> list[CatalogEntry]:
        for after_norm, before_norm, entries in expansions:
            mids = [
                CatalogEntry(title=e.title, url=e.url, source_page_url=e.source_page_url, dom_index=i)
                for i, e in enumerate(entries)
            ]
            idx_after = next(
                (i for i, e in enumerate(ordered) if normalize_url(e.url) == after_norm),
                None,
            )
            if idx_after is None:
                continue  # cannot place reliably; the gap warning covers this
            insert_at = idx_after + 1
            if before_norm:
                idx_before = next(
                    (i for i, e in enumerate(ordered) if normalize_url(e.url) == before_norm),
                    None,
                )
                if idx_before is not None and idx_before > idx_after:
                    insert_at = idx_before
            ordered[insert_at:insert_at] = mids
        return ordered

    def _detect_gaps(self, entries: list[CatalogEntry]) -> list[str]:
        """Report missing chapter numbers in the final reading order.

        Set-based on the integer chapter numbers: sub-numbered parts
        (第6章 1 / 第6章 2) all map to 6, so a fully absent main number is a
        precise missing-segment signal regardless of per-part counts.
        """
        seen: dict[int, str] = {}
        for entry in entries:
            match = self._chapter.parse(entry.title)
            if match is None or match.order_token is None:
                continue
            main = int(match.order_token)
            if main >= 1 and main not in seen:
                seen[main] = entry.title
        if not seen:
            return []
        low, high = min(seen), max(seen)
        missing = [n for n in range(low, high + 1) if n not in seen]
        if not missing:
            return []
        # Compress consecutive numbers into ranges for readable warnings.
        ranges: list[tuple[int, int]] = []
        for n in missing:
            if ranges and n == ranges[-1][1] + 1:
                ranges[-1] = (ranges[-1][0], n)
            else:
                ranges.append((n, n))
        parts = [f"第{a}章" if a == b else f"第{a}~{b}章" for a, b in ranges]
        return [f"目录疑似缺章：缺少 {', '.join(parts)}（编号 {low}~{high} 范围内）"]

    def _next_chapter_candidate(self, html: str, url: str) -> tuple[Optional[str], str]:
        """Best next-chapter candidate for a page.

        Explicit 下一章 navigation wins. Sites that label chapter hops as
        下一页 (common) yield their next-content-page as a *hypothesis*,
        which callers must verify against chapter titles before trusting.
        """
        nav = self._navigation.detect(html, url)
        nxt = nav.value.get("next_chapter")
        if nxt and nav.confidence >= 0.60:
            return urljoin(url, nxt), "nav"
        pag = self._content_pagination.detect(html, url)
        if pag.value.next_content_page and pag.confidence >= 0.60:
            return urljoin(url, pag.value.next_content_page), "pagination_word"
        return None, ""

    def _fill_gaps_via_navigation(self, entries: list[CatalogEntry],
                                  wrapped: _CachingFetcher, stats: dict) -> list[CatalogEntry]:
        """Fill numbering gaps by walking next-chapter links from the entry
        before the gap to the entry after it.

        Navigation semantics outrank URL and DOM evidence per the guide, but
        a 下一页-labelled hop is only a hypothesis: every step is verified by
        the target page's chapter title (token must move forward without
        overshooting the far end). The discovered chain is inserted only when
        it reaches the far end completely; otherwise the gap warning stays so
        nothing is silently invented.
        """
        result = list(entries)
        existing = {normalize_url(e.url) for e in result}
        i = 0
        while i < len(result) - 1:
            a, b = result[i], result[i + 1]
            match_a = self._chapter.parse(a.title)
            match_b = self._chapter.parse(b.title)
            if (
                match_a is None or match_b is None
                or match_a.order_token is None or match_b.order_token is None
                or int(match_b.order_token) - int(match_a.order_token) < 2
            ):
                i += 1
                continue

            b_token = match_b.order_token
            discovered: list[CatalogEntry] = []
            seen_tokens = {match_a.order_token}
            current_url = a.url
            current_token = match_a.order_token
            success = False
            for _ in range(self._options.max_gap_fill):
                try:
                    page = wrapped.fetch(current_url)
                except FetchError:
                    break
                candidate, _basis = self._next_chapter_candidate(page.html, page.final_url)
                if candidate is None:
                    break
                candidate_norm = normalize_url(candidate)
                if candidate_norm == normalize_url(b.url):
                    success = True
                    break
                if candidate_norm in existing:
                    break  # rejoined the catalog elsewhere or looping
                try:
                    target = wrapped.fetch(candidate)
                except FetchError:
                    break
                title = page_title(target.html)
                title_match = self._chapter.parse(title)
                token = title_match.order_token if title_match else None
                if token is None:
                    # The candidate may be a transient throttled shell; one
                    # polite fresh re-fetch before giving up on this step.
                    try:
                        target = wrapped.fetch(candidate, referer=page.final_url, fresh=True)
                    except FetchError:
                        break
                    title = page_title(target.html)
                    title_match = self._chapter.parse(title)
                    token = title_match.order_token if title_match else None
                    if token is None:
                        break  # cannot verify the step - do not guess
                if token == current_token:
                    current_url = candidate  # same chapter's next content page
                    continue
                if not (current_token < token <= b_token):
                    break  # diverged (wrong book / backwards) - do not guess
                if token not in seen_tokens:
                    discovered.append(
                        CatalogEntry(
                            title=title or candidate,
                            url=candidate,
                            source_page_url=target.final_url,
                            dom_index=0,
                        )
                    )
                    seen_tokens.add(token)
                existing.add(candidate_norm)
                current_url = candidate
                current_token = token

            if success and discovered:
                result[i + 1 : i + 1] = discovered
                stats["warnings"].append(
                    f"目录缺口已通过下一章链接补全 {len(discovered)} 章（'{a.title}' -> '{b.title}'）"
                )
                # stay on i: re-check the filled region pair by pair
            else:
                i += 1
        return result

    def _find_catalog_page(self, start: FetchedPage, wrapped: _CachingFetcher, stats) -> Optional[FetchedPage]:
        # Chapter pages expose an explicit 目录 link; book pages expose
        # 开始阅读/目录 style entries. Try the most promising ones in DOM order.
        candidates = self._catalog_link_candidates(start.html)
        for href in candidates[:_MAX_CATALOG_LINK_TRIES]:
            from urllib.parse import urljoin

            target = urljoin(start.final_url, href)
            if not wrapped.allowed(target):
                stats["warnings"].append(f"catalog link {target} skipped (cross-domain)")
                continue
            try:
                page = wrapped.fetch(target)
            except FetchError:
                continue
            detected = self._page_type.classify(page.html)
            if detected.value is PageType.CATALOG_PAGE and detected.confidence >= 0.5:
                return page
            catalog = self._catalog.detect(page.html, base_url=page.final_url)
            if catalog.chapters:
                return page
        return None

    @staticmethod
    def _catalog_link_candidates(html: str) -> list[str]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        hrefs: list[str] = []
        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            if not text or len(text) > 12:
                continue
            if any(word in text for word in _BOOK_CATALOG_LINK_WORDS):
                hrefs.append(href)
        return hrefs

    # -- chapter downloads --------------------------------------------------

    def _download_by_catalog(self, entries, wrapped: _CachingFetcher, stats) -> list[LogicalChapter]:
        chapters: list[LogicalChapter] = []
        neighbor_lengths: list[int] = []
        consecutive_failures = 0

        for position, entry in enumerate(entries):
            if self._options.max_chapters and position >= self._options.max_chapters:
                stats["warnings"].append(f"stopped at max_chapters={self._options.max_chapters}")
                break
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                stats["warnings"].append(
                    f"stopped after {consecutive_failures} consecutive restricted/failed chapters"
                )
                break

            try:
                page = wrapped.fetch(entry.url)
            except FetchError as exc:
                chapters.append(
                    LogicalChapter(
                        index=len(chapters) + 1, title=entry.title,
                        source_pages=[entry.url], content="",
                        content_status=ContentStatus.UNKNOWN_FAILURE,
                        confidence=0.0,
                    )
                )
                consecutive_failures += 1
                stats["warnings"].append(f"fetch failed for {entry.url}: {exc.cause}")
                continue

            chapter = self._process_chapter_with_retry(page, entry.title, neighbor_lengths, wrapped, stats)

            chapters.append(chapter)
            self._report_progress(len(chapters), len(entries), chapter.title, chapter.content_status.value)
            if chapter.content_status is ContentStatus.CONTENT_OK:
                consecutive_failures = 0
                neighbor_lengths.append(len(chapter.content))
            else:
                consecutive_failures += 1

        return chapters

    def _process_chapter_with_retry(self, page: FetchedPage, fallback_title: str,
                                    neighbor_lengths, wrapped: _CachingFetcher, stats) -> LogicalChapter:
        chapter = self._process_chapter_page(page, fallback_title, neighbor_lengths, wrapped, stats)

        # Transient throttling serves empty/anti-bot shells; retry politely
        # before accepting a failure status (guide: 解析失败返回结构化结果).
        had_shell = False
        for attempt in range(self._options.status_retries):
            if chapter.content_status is ContentStatus.CONTENT_OK:
                break
            had_shell = True
            wrapped.report_shell()  # the site is telling us to slow down
            time.sleep(self._options.status_retry_delay * (attempt + 1))
            try:
                page = wrapped.fetch(page.url, referer=page.final_url, fresh=True)
            except FetchError:
                break
            retried = self._process_chapter_page(page, fallback_title, neighbor_lengths, wrapped, stats)
            if retried.content_status is ContentStatus.CONTENT_OK:
                chapter = retried
        if chapter.content_status is ContentStatus.CONTENT_OK and not had_shell:
            wrapped.report_success()
        return chapter

    def _process_chapter_page(self, page: FetchedPage, fallback_title: str, neighbor_lengths, wrapped: _CachingFetcher, stats) -> LogicalChapter:
        # Inference-cache fast path: when a validated profile exists for this
        # host, skip the trafilatura baseline and extract density-only, then
        # verify the content container signature against the profile.
        fast = False
        profile = None
        host = urlparse(page.final_url).netloc.lower()
        if self._cache is not None:
            profile = self._cache.get(host)
            if profile is not None:
                light = self._cache.validate_light(page.final_url, page.html, profile)
                fast = light.ok

        merger = ContentPaginationMerger(
            wrapped, chapter_detector=self._chapter,
            max_pages=self._options.max_content_pages, content_extractor=self._content,
        )
        pages, texts, pagination_diagnostics = merger.walk(page, fast=fast)

        title = self._choose_title(page, fallback_title)
        raw_text = "\n".join(t for t in texts if t)
        extraction = self._content.extract(page.html, fast=fast)
        if fast and profile is not None and not self._cache.check_content_signature(profile, extraction.node):
            self._cache.invalidate(host)
            self._cache.record(profile, "invalidations")
            stats["warnings"].append(f"推理缓存验证失败，已失效并重新推断：{host}")
            extraction = self._content.extract(page.html, fast=False)

        # Local Deep Analysis: only when quick inference lacks confidence
        # (guide task 22; replaces any cloud-AI fallback).
        if extraction.confidence < 0.60:
            deep = self._deep.analyze_content(page.html, page.final_url, extraction)
            if deep.ok:
                extraction = deep.value
                stats.setdefault("deep_analysis_used", 0)
                stats["deep_analysis_used"] += 1

        median = int(statistics.median(neighbor_lengths)) if neighbor_lengths else None
        status_result = self._status.detect(page, extraction, neighbor_median_length=median)

        content = self._cleaner.clean(raw_text, chapter_title=title)
        content_status = status_result.value
        confidence = round(min(extraction.confidence, status_result.confidence), 3)
        duplicate_pages = pagination_diagnostics.get("duplicate_content_pages", [])
        if duplicate_pages:
            content_status = ContentStatus.UNKNOWN_FAILURE
            confidence = min(confidence, 0.2)
            warning = f"分页正文重复，疑似误提取推荐/排行区：{title}（分页 {duplicate_pages}）"
            if warning not in stats["warnings"]:
                stats["warnings"].append(warning)

        return LogicalChapter(
            index=0,  # assigned by caller
            title=title,
            source_pages=[p.final_url for p in pages],
            content=content,
            content_status=content_status,
            confidence=confidence,
        )

    def _choose_title(self, page: FetchedPage, fallback_title: str) -> str:
        on_page = page_title(page.html)
        # Pagination decorations identify a physical page, not the logical
        # chapter.  When the catalog supplied a title, keep that stable title
        # instead of exporting names such as "第1章（第1页）".
        if fallback_title and has_page_marker(on_page):
            return fallback_title
        match = self._chapter.parse(on_page) if on_page else None
        if match and match.confidence >= _STRONG_TITLE_CONFIDENCE:
            return on_page
        return fallback_title or on_page

    # -- no-catalog traversal ----------------------------------------------

    def _traverse_without_catalog(self, start: FetchedPage, wrapped: _CachingFetcher, stats) -> list[LogicalChapter]:
        # Only explicit PREVIOUS/NEXT_CHAPTER relations are followed; URL
        # numbering is never consulted (guide crawl_strategy.MVP_priority).
        pages_in_order, relations = self._collect_traversal_pages(start, wrapped, stats)

        chapters: list[LogicalChapter] = []
        neighbor_lengths: list[int] = []
        for position, page in enumerate(pages_in_order):
            if self._options.max_chapters and position >= self._options.max_chapters:
                stats["warnings"].append(f"stopped at max_chapters={self._options.max_chapters}")
                break
            entry_title = page_title(page.html) or f"第{position + 1}章"
            chapter = self._process_chapter_with_retry(page, entry_title, neighbor_lengths, wrapped, stats)
            chapter.index = len(chapters) + 1
            chapters.append(chapter)
            self._report_progress(len(chapters), None, chapter.title, chapter.content_status.value)
            if chapter.content_status is ContentStatus.CONTENT_OK:
                neighbor_lengths.append(len(chapter.content))
        merged = self._merge_part_chapters(chapters, stats)

        graph = NovelGraph(self._chapter)
        key_by_url = {normalize_url(c.source_pages[0]): graph.add_chapter(c) for c in merged if c.source_pages}
        for source_url, _rel, target_url, confidence in stats.get("traversal_relations", []):
            graph.add_edge(
                key_by_url.get(normalize_url(source_url), normalize_url(source_url)),
                RelationType.NEXT_CHAPTER,
                key_by_url.get(normalize_url(target_url), normalize_url(target_url)),
                confidence=confidence,
                reason="explicit next-chapter navigation",
            )
        stats["graph_built"] = True
        return merged, graph

    def _merge_part_chapters(self, chapters: list[LogicalChapter], stats: dict) -> list[LogicalChapter]:
        """Merge consecutive per-part chapters (第6章 1 / 第6章 2 / ...) of
        the same main chapter into one LogicalChapter (guide: 同一逻辑章节的
        多页正文必须先合并). Runs in reading order after direction handling.

        Grouping is conservative: every member must parse as a normal
        numbered chapter sharing the same integer main number with an
        explicit bare-number part index, strictly ascending. Anything else
        (12.5-style decimal mains, 番外, unnumbered titles) stays separate.
        """
        if not self._options.merge_parts:
            for i, chapter in enumerate(chapters):
                chapter.index = i + 1
            return chapters

        def part_key(chapter: LogicalChapter):
            match = self._chapter.parse(chapter.title)
            if match is None or match.order_token is None or match.chapter_type != "normal":
                return None
            if match.chapter_number is None or match.chapter_number != int(match.chapter_number):
                return None  # 12.5-style decimal main number: standalone
            return (int(match.order_token), match.sub_number)

        merged: list[LogicalChapter] = []
        i = 0
        while i < len(chapters):
            key = part_key(chapters[i])
            if key is None or key[1] is None:
                merged.append(chapters[i])
                i += 1
                continue
            j = i + 1
            while j < len(chapters):
                next_key = part_key(chapters[j])
                if next_key is None or next_key[0] != key[0] or next_key[1] is None:
                    break
                j += 1
            group = chapters[i:j]
            subs = [part_key(c)[1] for c in group]
            if len(group) >= 2 and all(subs[t] < subs[t + 1] for t in range(len(subs) - 1)):
                status = next(
                    (c.content_status for c in group if c.content_status is not ContentStatus.CONTENT_OK),
                    ContentStatus.CONTENT_OK,
                )
                texts = []
                for c in group:
                    if c.content_status is ContentStatus.CONTENT_OK:
                        texts.append(c.content)
                    else:
                        texts.append(f"【{c.title} 未能提取：{c.content_status.value}】")
                merged.append(
                    LogicalChapter(
                        index=0,
                        title=strip_sub_number(group[0].title),
                        source_pages=[p for c in group for p in c.source_pages],
                        content="\n\n".join(texts),
                        content_status=status,
                        confidence=min(c.confidence for c in group),
                    )
                )
                stats["warnings"].append(
                    f"已合并分页章节：{merged[-1].title}（{len(group)} 个分页）"
                )
                i = j
            else:
                merged.append(chapters[i])
                i += 1

        for i, chapter in enumerate(merged):
            chapter.index = i + 1
        return merged

    def _report_progress(self, done: int, total: Optional[int], title: str, status: str) -> None:
        if self._progress is not None:
            try:
                interval = getattr(self._wrapped, "current_interval", 0.0)
                self._progress(done, total, title, status, interval)
            except Exception:
                pass  # progress reporting must never break the crawl

    def _collect_traversal_pages(self, start: FetchedPage, wrapped: _CachingFetcher, stats):
        """Returns (pages in reading order, followed relations as
        (source_url, relation_type, target_url, confidence))."""
        from urllib.parse import urljoin

        visited: set[str] = {normalize_url(start.final_url)}
        backward: list[FetchedPage] = []

        # Walk to the head of the chapter chain first.
        current = start
        while len(backward) + 1 < self._options.max_chapters:
            nav = self._navigation.detect(current.html, current.final_url)
            prev_url = nav.value.get("previous_chapter")
            if not prev_url or nav.confidence < 0.60:
                break
            target = urljoin(current.final_url, prev_url)
            if normalize_url(target) in visited or not wrapped.allowed(target):
                stats["warnings"].append(f"traversal stopped at {target} (visited or cross-domain)")
                break
            try:
                page = wrapped.fetch(target)
            except FetchError as exc:
                stats["warnings"].append(f"traversal fetch failed: {exc.cause}")
                break
            detected = self._page_type.classify(page.html)
            if detected.value is PageType.CATALOG_PAGE:
                break
            visited.add(normalize_url(target))
            stats.setdefault("traversal_relations", []).append(
                (target, "NEXT_CHAPTER", current.final_url, round(nav.confidence, 3))
            )
            backward.append(page)
            current = page

        forward: list[FetchedPage] = []
        current = start
        while len(backward) + len(forward) + 1 < self._options.max_chapters:
            nav = self._navigation.detect(current.html, current.final_url)
            next_url = nav.value.get("next_chapter")
            if not next_url or nav.confidence < 0.60:
                break
            target = urljoin(current.final_url, next_url)
            if normalize_url(target) in visited or not wrapped.allowed(target):
                stats["warnings"].append(f"traversal stopped at {target} (visited or cross-domain)")
                break
            try:
                page = wrapped.fetch(target)
            except FetchError as exc:
                stats["warnings"].append(f"traversal fetch failed: {exc.cause}")
                break
            detected = self._page_type.classify(page.html)
            if detected.value is PageType.CATALOG_PAGE:
                break
            visited.add(normalize_url(target))
            stats.setdefault("traversal_relations", []).append(
                (current.final_url, "NEXT_CHAPTER", target, round(nav.confidence, 3))
            )
            forward.append(page)
            current = page

        pages = list(reversed(backward)) + [start] + forward
        stats["traversal_pages"] = len(pages)
        return pages, stats.get("traversal_relations", [])

    # -- stats --------------------------------------------------------------

    def _finalize_stats(self, stats, wrapped, chapters) -> dict[str, Any]:
        status_counts: dict[str, int] = {}
        for chapter in chapters:
            status_counts[chapter.content_status.value] = status_counts.get(chapter.content_status.value, 0) + 1
        for i, chapter in enumerate(chapters):
            chapter.index = i + 1
        stats.update(
            {
                "chapters_total": len(chapters),
                "status_counts": status_counts,
                "fetcher": dict(wrapped.stats),
                "adaptive": {
                    "final_interval": round(wrapped.current_interval, 3),
                    "backoffs": wrapped.stats["backoffs"],
                },
            }
        )
        return stats

"""Stable Python API (guide task 23 / V1).

The CLI, WebUI and third-party code all share this core entry point:

    from novel_extractor import NovelExtractor
    extractor = NovelExtractor()
    result = extractor.extract(url)
    result.export_txt('./output')

`analyze(url)` runs the single-page inference (page type, metadata, content
candidates, navigation) without downloading anything; `inspect`-level detail
is the same dict with the candidate records included.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from novel_extractor.analyzer.content import ContentExtractor
from novel_extractor.analyzer.metadata import MetadataExtractor
from novel_extractor.analyzer.navigation import ChapterNavigationDetector
from novel_extractor.analyzer.page_type import PageTypeDetector
from novel_extractor.cache import InferenceCache
from novel_extractor.crawler.novel import CrawlOptions, CrawlResult, NovelCrawler
from novel_extractor.exporter.txt import TxtExporter
from novel_extractor.fetcher.http import Fetcher, HttpFetcher


class NovelExtractor:
    """Core facade over the ruleless inference engine."""

    def __init__(
        self,
        output_root: str | Path = "output",
        options: Optional[CrawlOptions] = None,
        fetcher: Optional[Fetcher] = None,
        cache: Optional[InferenceCache] = None,
    ):
        self.output_root = str(output_root)
        self.options = options or CrawlOptions(request_interval=0.3)
        self.fetcher = fetcher or HttpFetcher()
        self.cache = cache if cache is not None else InferenceCache(
            cache_dir=Path(self.output_root) / ".cache"
        )

    # -- full extraction ------------------------------------------------------

    def extract(self, url: str, progress: Optional[Any] = None) -> CrawlResult:
        crawler = NovelCrawler(
            fetcher=self.fetcher, options=self.options, progress=progress, cache=self.cache
        )
        return crawler.crawl(url)

    def export_txt(self, result: CrawlResult, output_root: Optional[str] = None, merged: bool = True):
        exporter = TxtExporter(output_root=output_root or self.output_root)
        return exporter.export(result, merged=merged)

    # -- single-page analysis ---------------------------------------------------

    def analyze(self, url: str) -> dict[str, Any]:
        """Single-page inference with confidence/reasons/candidates.

        Reads exactly one page (no chapter downloads); the catalog preview
        only reflects what this page itself contains.
        """
        page = self.fetcher.fetch(url)
        page_type = PageTypeDetector().classify(page.html)
        metadata = MetadataExtractor().extract(page.html)
        extraction = ContentExtractor().extract(page.html)
        navigation = ChapterNavigationDetector().detect(page.html, page.final_url)

        catalog_info: dict[str, Any] = {"entries": 0, "titles": [], "confidence": 0.0, "reason": ""}
        if page_type.value.value == "CATALOG_PAGE":
            from novel_extractor.analyzer.catalog import CatalogDetector

            catalog = CatalogDetector().detect(page.html, base_url=page.final_url)
            catalog_info = {
                "entries": len(catalog.chapters),
                "titles": [c.title for c in catalog.chapters[:20]],
                "confidence": catalog.confidence,
                "reason": catalog.reason,
            }

        return {
            "url": url,
            "final_url": page.final_url,
            "http_status": page.status_code,
            "encoding": page.encoding,
            "page_type": page_type.value.value,
            "page_type_confidence": page_type.confidence,
            "page_type_reason": page_type.reason,
            "metadata": {
                "book_title": metadata.book_title,
                "author": metadata.author,
                "title_confidence": metadata.title_confidence,
                "author_confidence": metadata.author_confidence,
            },
            "content": {
                "text_length": len(extraction.text),
                "node_tag": extraction.node_tag,
                "confidence": extraction.confidence,
                "reason": extraction.reason,
                "preview": extraction.text[:300],
                "candidates": [
                    {
                        "candidate_id": c.candidate_id,
                        "score": c.score,
                        "confidence": c.confidence,
                        "positive_reasons": c.positive_reasons,
                        "penalties": c.penalties,
                        "key_features": c.key_features,
                    }
                    for c in extraction.candidates
                ],
            },
            "navigation": {
                "previous_chapter": navigation.value.get("previous_chapter"),
                "next_chapter": navigation.value.get("next_chapter"),
                "catalog_url": navigation.value.get("catalog_url"),
                "confidence": navigation.confidence,
                "reason": navigation.reason,
            },
            "catalog_preview": catalog_info,
            "diagnostics": {
                "encoding_source": page.encoding_source,
                "encoding_confidence": page.encoding_confidence,
                "page_diagnostics": page.diagnostics,
            },
        }

    # -- cache management ---------------------------------------------------

    def cache_list(self) -> list[dict[str, Any]]:
        out = []
        for host in self.cache.hosts():
            profile = self.cache.get(host)
            out.append(
                {
                    "host": host,
                    "generated_at": profile.generated_at if profile else None,
                    "confidence": profile.confidence if profile else None,
                    "validation_stats": profile.validation_stats if profile else {},
                }
            )
        return out

    def cache_clear(self, host: Optional[str] = None) -> int:
        hosts = [host] if host else self.cache.hosts()
        count = 0
        for name in hosts:
            if self.cache.get(name) is not None or (self.cache.cache_dir and (self.cache.cache_dir / f"{name}.json").exists()):
                self.cache.clear(name)
                count += 1
        return count

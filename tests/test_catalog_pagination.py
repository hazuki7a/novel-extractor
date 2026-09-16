"""Tests for catalog pagination detection and merging (guide task 8)."""

from __future__ import annotations

import pytest

from novel_extractor.analyzer.pagination import (
    CatalogPaginationDetector,
    CatalogPaginationMerger,
    normalize_url,
    page_number_of,
)
from novel_extractor.fetcher.http import FetchError
from novel_extractor.models import FetchedPage


def catalog_page(next_href=None, prev_href=None, page_links=""):
    next_a = f'<a href="{next_href}">下一页</a>' if next_href else ""
    prev_a = f'<a href="{prev_href}">上一页</a>' if prev_href else ""
    chapters = "".join(
        f'<li><a href="/book/1/{i}.html">第{i}章 测试章节{i}</a></li>' for i in range(1, 21)
    )
    return f"""
    <html><head><title>目录</title></head><body>
    <ul class="list">{chapters}</ul>
    <div class="pages">{page_links}{prev_a}{next_a}</div>
    </body></html>
    """


def make_page(url: str, html: str) -> FetchedPage:
    return FetchedPage(
        url=url, final_url=url, status_code=200, raw_bytes=html.encode("utf-8"),
        html=html, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
    )


class DictFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.fetched: list[str] = []

    def fetch(self, url: str, *, referer=None) -> FetchedPage:
        self.fetched.append(url)
        if url not in self.pages:
            raise FetchError(url, "missing page")
        return make_page(url, self.pages[url])


def test_page_number_extraction():
    assert page_number_of("http://e.com/list_2.html") == 2
    assert page_number_of("http://e.com/list-3.html") == 3
    assert page_number_of("http://e.com/catalog.html?page=4") == 4
    assert page_number_of("http://e.com/catalog.html?p=5") == 5
    assert page_number_of("http://e.com/index.html") == 1
    assert page_number_of("http://e.com/book/1/456.html") is None  # chapter URL
    assert page_number_of("http://e.com/book/1/456.html?page=2") == 2


def test_normalize_url_drops_fragment():
    assert normalize_url("http://e.com/a.html#top") == "http://e.com/a.html"


def test_next_catalog_page_detected():
    html = catalog_page(next_href="list_2.html")
    result = CatalogPaginationDetector().detect(html, "http://e.com/book/1/list.html")
    assert result.value.next_catalog_page == "http://e.com/book/1/list_2.html"
    assert result.value.previous_catalog_page is None
    assert result.confidence >= 0.70
    assert "下一页" in result.reason


def test_prev_and_next_both_detected():
    html = catalog_page(next_href="list_3.html", prev_href="list_1.html")
    result = CatalogPaginationDetector().detect(html, "http://e.com/book/1/list_2.html")
    assert result.value.next_catalog_page == "http://e.com/book/1/list_3.html"
    assert result.value.previous_catalog_page == "http://e.com/book/1/list_1.html"


def test_query_param_pagination():
    html = catalog_page(next_href="?page=2")
    result = CatalogPaginationDetector().detect(html, "http://e.com/catalog.html")
    assert result.value.next_catalog_page == "http://e.com/catalog.html?page=2"


def test_chapter_hop_word_ignored():
    # 下一章 must never be treated as catalog pagination.
    html = f"""
    <html><body>
    <ul>{''.join(f'<li><a href="/book/1/{i}.html">第{i}章 章节名{i}</a></li>' for i in range(1, 15))}</ul>
    <div><a href="/book/1/2.html">下一章</a></div>
    </body></html>
    """
    result = CatalogPaginationDetector().detect(html, "http://e.com/book/1/1.html")
    assert result.value.next_catalog_page is None


def test_target_outside_directory_rejected():
    html = catalog_page(next_href="http://other.com/elsewhere/list_2.html")
    result = CatalogPaginationDetector().detect(html, "http://e.com/book/1/list.html")
    assert result.value.next_catalog_page is None
    assert result.confidence < 0.6


def test_self_referential_link_rejected():
    html = catalog_page(next_href="list.html")
    result = CatalogPaginationDetector().detect(html, "http://e.com/book/1/list.html")
    assert result.value.next_catalog_page is None


def test_non_adjacent_page_number_lowers_confidence():
    html = catalog_page(next_href="list_9.html")
    result = CatalogPaginationDetector().detect(html, "http://e.com/book/1/list_2.html")
    assert result.confidence < 0.70


def test_merger_walks_full_chain():
    pages = {
        "http://e.com/list.html": catalog_page(next_href="list_2.html"),
        "http://e.com/list_2.html": catalog_page(next_href="list_3.html"),
        "http://e.com/list_3.html": catalog_page(),
    }
    fetcher = DictFetcher(pages)
    merger = CatalogPaginationMerger(fetcher)
    walked, diagnostics = merger.walk(make_page("http://e.com/list.html", pages["http://e.com/list.html"]))
    assert [p.final_url for p in walked] == [
        "http://e.com/list.html",
        "http://e.com/list_2.html",
        "http://e.com/list_3.html",
    ]
    assert diagnostics["stopped_by"] == "no_next"
    assert diagnostics["chain"] == ["http://e.com/list_2.html", "http://e.com/list_3.html"]


def test_merger_stops_on_loop():
    pages = {
        "http://e.com/a.html": catalog_page(next_href="b.html"),
        "http://e.com/b.html": catalog_page(next_href="a.html"),
    }
    merger = CatalogPaginationMerger(DictFetcher(pages))
    walked, diagnostics = merger.walk(make_page("http://e.com/a.html", pages["http://e.com/a.html"]))
    assert len(walked) == 2
    assert diagnostics["stopped_by"] == "loop"


def test_merger_respects_max_pages():
    pages = {f"http://e.com/list_{i}.html": catalog_page(next_href=f"list_{i + 1}.html") for i in range(1, 30)}
    pages["http://e.com/list.html"] = catalog_page(next_href="list_2.html")
    merger = CatalogPaginationMerger(DictFetcher(pages), max_pages=5)
    walked, diagnostics = merger.walk(make_page("http://e.com/list.html", pages["http://e.com/list.html"]))
    assert len(walked) == 5
    assert diagnostics["stopped_by"] == "max_pages"


def test_merger_survives_fetch_error():
    pages = {
        "http://e.com/list.html": catalog_page(next_href="missing.html"),
    }
    merger = CatalogPaginationMerger(DictFetcher(pages))
    walked, diagnostics = merger.walk(make_page("http://e.com/list.html", pages["http://e.com/list.html"]))
    assert len(walked) == 1
    assert diagnostics["stopped_by"] == "fetch_error"

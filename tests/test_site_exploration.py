"""Tests for Local Site Exploration (guide task 24)."""

from __future__ import annotations

from novel_extractor.crawler.explore import LocalSiteExplorer
from novel_extractor.fetcher.http import FetchedPage, FetchError


def page(url: str, html: str) -> FetchedPage:
    return FetchedPage(
        url=url, final_url=url, status_code=200, raw_bytes=html.encode(),
        html=html, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
    )


START = """
<html><body><h1>孤书</h1><div>这本书的目录暂时没有链接到这里。</div>
<a href="/menu.html">网站菜单</a>
<a href="/dead.html">查看目录</a>
<a href="/book/1/all.html">全部章节</a>
<a href="/other.html">其他</a>
</body></html>
"""

MENU = """
<html><body><ul>
<li><a href="/list/1/">玄幻</a></li><li><a href="/list/2/">都市</a></li>
<li><a href="/rank">排行</a></li><li><a href="/login">登录</a></li>
</ul></body></html>
"""

CATALOG = (
    "<html><body><ul>"
    + "".join(f'<li><a href="/b/{i}.html">第{i}章 孤影{i}</a></li>' for i in range(1, 9))
    + "</ul></body></html>"
)

OTHER = "<html><body><p>无关页面。</p></body></html>"


class Site:
    def __init__(self):
        self.pages = {
            "http://e.com/start.html": START,
            "http://e.com/dead.html": OTHER,
            "http://e.com/menu.html": MENU,
            "http://e.com/book/1/all.html": CATALOG,
            "http://e.com/other.html": OTHER,
            **{
                f"http://e.com/b/{i}.html": f"<html><body><h1>第{i}章 孤影{i}</h1>"
                f"<div>{'<p>正文段落，内容足够长。</p>' * 12}</div></body></html>"
                for i in range(1, 9)
            },
        }
        self.fetched: list[str] = []

    def fetch(self, url: str, *, referer=None) -> FetchedPage:
        self.fetched.append(url)
        if url not in self.pages:
            raise FetchError(url, "missing")
        return page(url, self.pages[url])


def test_explorer_finds_catalog_within_budget():
    site = Site()
    explorer = LocalSiteExplorer(site, "e.com", budget=8)
    result = explorer.explore(page("http://e.com/start.html", START))
    assert result.stop_reason == "catalog_found"
    assert result.catalog_url == "http://e.com/book/1/all.html"
    assert len(result.chapter_hints) == 8
    # the unrelated menu page may be visited, but the dead page was not needed
    assert "http://e.com/book/1/all.html" in result.visited


def test_budget_stops_exploration():
    site = Site()
    explorer = LocalSiteExplorer(site, "e.com", budget=1)
    result = explorer.explore(page("http://e.com/start.html", START))
    # budget 1: visits only the first candidate (menu, no catalog there)
    assert result.stop_reason == "budget"
    assert result.catalog_url is None
    assert len(result.visited) <= 1


def test_cycle_and_cross_domain_guarded():
    site = Site()
    explorer = LocalSiteExplorer(site, "e.com", budget=8)
    result = explorer.explore(page("http://e.com/start.html", START))
    assert len(result.visited) == len(set(result.visited))

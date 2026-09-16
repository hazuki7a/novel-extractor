"""Tests for collapsed catalog list expansion (展开完整列表) and gap warnings.

The fixture reproduces the generic pattern: head + tail chapter clusters in
the static HTML, the middle hidden behind a javascript onclick loader that
builds a JSONP data URL with a custom encoder. The expander must recover the
middle through a local JS sandbox - no host-specific logic anywhere.
"""

from __future__ import annotations

import json

import pytest

from novel_extractor.analyzer.collapsed_list import (
    CollapsedListExpander,
    _extract_html_fragment,
)
from novel_extractor.crawler.novel import CrawlOptions, NovelCrawler
from novel_extractor.fetcher.http import FetchError, FetchedPage
from tests.test_crawler import DictFetcher, chapter_page

try:
    import quickjs  # noqa: F401

    HAS_QUICKJS = True
except ImportError:  # pragma: no cover
    HAS_QUICKJS = False


BOOK_JS = """
function scramble(s){return 'P' + s.length + 'X';}
var callback='6ebc42';
function load_more(book){
  document.getElementById('detail').innerHTML='<div>[ loading... ]</div>';
  var head=document.getElementsByTagName('head').item(0);
  var el=document.createElement('script');
  el.src='/index.php?c=book&a=list&callback='+callback+'&book_id='+book+'&b='+scramble(callback);
  head.appendChild(el);
}
"""


def collapsed_catalog(data_url_query: str) -> str:
    head = "".join(
        f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in range(1, 7)
    )
    tail = "".join(
        f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in range(19, 25)
    )
    return f"""
    <html><head><title>测试小说目录</title>
    <script>{BOOK_JS}</script></head><body>
    <h1>测试小说</h1>
    <ul class="list3">{head}</ul>
    <div class="content_more"><div class="more">...
    <a href="javascript:void(0)" onclick="load_more('999')">[展开完整列表]</a> ...</div></div>
    <ul class="list3">{tail}</ul>
    </body></html>
    """


def jsonp_response() -> str:
    middle = "".join(
        f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in range(7, 19)
    )
    payload = json.dumps({"id": "999", "content": f'<ul class="list3">{middle}</ul>'})
    return f'd6ebc42({payload})'


class SiteFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch(self, url: str, *, referer=None) -> FetchedPage:
        if url not in self.pages:
            raise FetchError(url, "missing page")
        assert referer is None or referer.startswith("http")
        html = self.pages[url]
        return FetchedPage(
            url=url, final_url=url, status_code=200, raw_bytes=html.encode("utf-8"),
            html=html, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
        )


def make_pages() -> dict[str, str]:
    pages = {
        "http://e.com/catalog.html": collapsed_catalog("list"),
        "http://e.com/index.php?c=book&a=list&callback=6ebc42&book_id=999&b=P6X": jsonp_response(),
    }
    for i in list(range(1, 25)):
        if i in range(7, 19):
            continue  # hidden middle chapters come from the JSONP listing
        pages[f"http://e.com/x/{i}.html"] = chapter_page(f"第{i}章 风云{i}", f"章{i}")
    # middle chapter pages are also fetched once discovered
    for i in range(7, 19):
        pages[f"http://e.com/x/{i}.html"] = chapter_page(f"第{i}章 风云{i}", f"章{i}")
    return pages


def test_marker_detection():
    html = collapsed_catalog("list")
    expander = CollapsedListExpander()
    assert expander.has_marker(html)


def test_no_marker_on_plain_catalog():
    html = '<ul>' + ''.join(f'<li><a href="/x/{i}.html">第{i}章 名{i}</a></li>' for i in range(1, 9)) + '</ul>'
    assert not CollapsedListExpander().has_marker(html)


def test_jsonp_fragment_extraction():
    fragment = _extract_html_fragment(jsonp_response())
    assert fragment is not None and "第7章" in fragment and "content" not in fragment


def test_literal_resolver_simple_concat():
    expander = CollapsedListExpander()
    scripts = """
    var token='abc123';
    function load_more(book){
      var el=document.createElement('script');
      el.src='/data.php?token='+token+'&book='+book;
      document.getElementsByTagName('head').item(0).appendChild(el);
    }
    """
    url = expander._resolve_literal(scripts, "load_more", "42")
    assert url == "/data.php?token=abc123&book=42"


@pytest.mark.skipif(not HAS_QUICKJS, reason="quickjs not installed")
def test_js_sandbox_resolves_custom_encoder():
    expander = CollapsedListExpander()
    url = expander._resolve_via_js([BOOK_JS], "load_more", "999")
    assert url == "/index.php?c=book&a=list&callback=6ebc42&book_id=999&b=P6X"


@pytest.mark.skipif(not HAS_QUICKJS, reason="quickjs not installed")
def test_expander_full_flow():
    pages = make_pages()
    expander = CollapsedListExpander()
    result = expander.expand(
        pages["http://e.com/catalog.html"],
        "http://e.com/catalog.html",
        fetch=lambda url: SiteFetcher(pages).fetch(url),
    )
    assert result.confidence >= 0.7
    assert len(result.value.entries) == 12
    assert result.value.after_href == "/x/6.html"
    assert result.value.before_href == "/x/19.html"


@pytest.mark.skipif(not HAS_QUICKJS, reason="quickjs not installed")
def test_crawler_expands_collapsed_catalog():
    result = NovelCrawler(
        fetcher=SiteFetcher(make_pages()), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    assert len(result.chapters) == 24
    titles = [c.title for c in result.chapters]
    assert titles[0] == "第1章 风云1"
    assert titles[6] == "第7章 风云7"    # spliced middle in the right place
    assert titles[17] == "第18章 风云18"
    assert titles[-1] == "第24章 风云24"
    assert any("展开折叠目录" in w for w in result.stats["warnings"])
    # a complete book must not raise gap warnings
    assert not any("缺章" in w for w in result.stats["warnings"])


def test_gap_warning_when_middle_missing():
    # Same collapsed catalog, but expansion disabled (no quickjs path): the
    # crawler must warn about the numbering jump instead of staying silent.
    pages = {
        "http://e.com/catalog.html": collapsed_catalog("list"),
        **{
            f"http://e.com/x/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in list(range(1, 7)) + list(range(19, 25))
        },
    }
    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    if result.catalog and len(result.catalog.chapters) == 12:
        assert any("缺章" in w for w in result.stats["warnings"])


def test_no_gap_warning_for_continuous_catalog():
    pages = {
        "http://e.com/catalog.html": '<html><body><ul>' + ''.join(
            f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in range(1, 9)
        ) + '</ul></body></html>',
        **{
            f"http://e.com/x/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 9)
        },
    }
    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    assert not any("缺章" in w for w in result.stats["warnings"])


def test_gap_filled_via_next_chapter_links():
    # Catalog skips 第3/4章 entirely (no marker to expand); the crawler must
    # recover them by following explicit 下一章 links from 第2章 to 第5章.
    def simple_catalog(titles_ids):
        links = "".join(
            f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in titles_ids
        )
        return f'<html><body><ul>{links}</ul></body></html>'

    pages = {
        "http://e.com/catalog.html": simple_catalog([1, 2, 5, 6, 7]),
    }
    for i in range(1, 8):
        nxt = f"/x/{i + 1}.html" if i < 7 else None
        pages[f"http://e.com/x/{i}.html"] = chapter_page(
            f"第{i}章 风云{i}", f"章{i}", next_href=nxt
        )

    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    titles = [c.title for c in result.chapters]
    assert titles == [f"第{i}章 风云{i}" for i in range(1, 8)]
    assert any("补全" in w for w in result.stats["warnings"])
    assert not any("缺章" in w for w in result.stats["warnings"])


def test_gap_stays_reported_when_chain_broken():
    # 下一章 chain from 第2章 dead-ends (no way to reach 第5章): the gap must
    # remain an explicit warning, never silently filled or dropped.
    def simple_catalog(titles_ids):
        links = "".join(
            f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in titles_ids
        )
        return f'<html><body><ul>{links}</ul></body></html>'

    pages = {
        "http://e.com/catalog.html": simple_catalog([1, 2, 5, 6, 7]),
        "http://e.com/x/1.html": chapter_page("第1章 风云1", "章1", next_href="2.html"),
        "http://e.com/x/2.html": chapter_page("第2章 风云2", "章2"),  # dead end
        "http://e.com/x/5.html": chapter_page("第5章 风云5", "章5", next_href="6.html"),
        "http://e.com/x/6.html": chapter_page("第6章 风云6", "章6", next_href="7.html"),
        "http://e.com/x/7.html": chapter_page("第7章 风云7", "章7"),
    }
    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    assert any("缺章" in w for w in result.stats["warnings"])
    assert not any("补全" in w for w in result.stats["warnings"])


def test_gap_filled_via_pagination_word_with_title_verification():
    # quanben-style: chapter hops labelled 上一页/目录/下一页 instead of
    # 上一章/下一章. The 下一页 candidate must be verified by the target
    # page's chapter title before the gap is filled.
    def simple_catalog(ids):
        links = "".join(
            f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in ids
        )
        return f'<html><body><ul>{links}</ul></body></html>'

    pages = {
        "http://e.com/catalog.html": simple_catalog([1, 2, 5, 6, 7]),
    }
    for i in range(1, 8):
        prev = f"/x/{i - 1}.html" if i > 1 else None
        nxt = f"/x/{i + 1}.html" if i < 7 else None
        nav = "<div class='nav'>"
        if prev:
            nav += f'<a href="{prev}">上一页</a>'
        nav += '<a href="/catalog.html">目录</a>'
        if nxt:
            nav += f'<a href="{nxt}">下一页</a>'
        nav += "</div>"
        pages[f"http://e.com/x/{i}.html"] = f"""
        <html><head><title>第{i}章 风云{i}</title></head><body>
        <h1>第{i}章 风云{i}</h1>
        <div id="content">{''.join(f'<p>第{i}章正文第{j}段，山风吹过林梢，主角抬眼望向远方。</p>' for j in range(1, 13))}</div>
        {nav}</body></html>
        """

    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    titles = [c.title for c in result.chapters]
    assert titles == [f"第{i}章 风云{i}" for i in range(1, 8)]
    assert any("补全" in w for w in result.stats["warnings"])
    assert not any("缺章" in w for w in result.stats["warnings"])


def test_transient_empty_content_is_retried():
    # First response is a throttled empty shell, the second is real: the
    # crawler must retry instead of flagging the chapter.
    class FlakyFetcher:
        def __init__(self):
            self.calls = 0

        def fetch(self, url: str, *, referer=None) -> FetchedPage:
            self.calls += 1
            if self.calls % 2 == 1:
                html = "<html><body>loading</body></html>"
            else:
                html = chapter_page("第1章 风云1", "真实正文")
            return FetchedPage(
                url=url, final_url=url, status_code=200,
                raw_bytes=html.encode("utf-8"), html=html,
                encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
            )

    fetcher = FlakyFetcher()
    result = NovelCrawler(
        fetcher=fetcher,
        options=CrawlOptions(request_interval=0.0, status_retry_delay=0.0),
    ).crawl("http://e.com/x/1.html")
    # 1.html answered empty on its first fetch and was recovered on retry
    first = result.chapters[0]
    assert first.title == "第1章 风云1"
    assert first.content_status.value == "CONTENT_OK"
    assert "真实正文" in first.content


def test_gap_detection_and_fill_with_sub_numbered_chapters():
    # quanben-style per-part titles: 第N章 M. The catalog is missing all of
    # 第3章's parts; both detection and recovery must work at that granularity.
    def catalog_html(ids):
        links = "".join(
            f'<li><a href="/x/{i}.html">第{p[0]}章 {p[1]}</a></li>' for i, p in ids
        )
        return f'<html><body><ul>{links}</ul></body></html>'

    titles = {
        1: (1, 1), 2: (1, 2), 3: (2, 1), 4: (2, 2), 7: (4, 1), 8: (4, 2),
        5: (3, 1), 6: (3, 2),  # missing from the catalog, present via 下一章
    }
    catalog_ids = [1, 2, 3, 4, 7, 8]
    pages = {
        "http://e.com/catalog.html": catalog_html([(i, titles[i]) for i in catalog_ids]),
    }
    for i in range(1, 9):
        nxt = f"/x/{i + 1}.html" if i < 8 else None
        nav = "<div class='nav'>"
        if i > 1:
            nav += f'<a href="/x/{i - 1}.html">上一页</a>'
        nav += '<a href="/catalog.html">目录</a>'
        if nxt:
            nav += f'<a href="{nxt}">下一页</a>'
        nav += "</div>"
        main, sub = titles[i]
        pages[f"http://e.com/x/{i}.html"] = f"""
        <html><head><title>第{main}章 {sub}</title></head><body>
        <h1>第{main}章 {sub}</h1>
        <div id="content">{''.join(f'<p>第{main}-{sub}正文第{j}段，山风吹过林梢。</p>' for j in range(1, 13))}</div>
        {nav}</body></html>
        """

    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    titles = [c.title for c in result.chapters]
    assert titles == ["第1章", "第2章", "第3章", "第4章"]
    ch3 = result.chapters[2]
    assert "第3-1" in ch3.content and "第3-2" in ch3.content  # both parts recovered
    assert any("补全" in w for w in result.stats["warnings"])
    assert not any("缺章" in w for w in result.stats["warnings"])


def test_gap_warning_reports_missing_main_number():
    from tests.test_crawler import catalog_page, chapter_page

    links = []
    for i in [1, 2, 3, 5, 6, 7]:  # 第4章 completely absent
        links.append(f'<li><a href="/book/1/{i}.html">第{i}章 风云{i}</a></li>')
    catalog = f'<html><body><ul>{"".join(links)}</ul></body></html>'
    pages = {
        "http://e.com/catalog.html": catalog,
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in [1, 2, 3, 5, 6, 7]
        },
    }
    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    assert any("缺少 第4章" in w for w in result.stats["warnings"])


def test_part_chapters_merged_into_one():
    # quanben-style: 第N章 1/2/3 are pages of ONE logical chapter; they must
    # be merged into a single file titled 第N章.
    pages = {}
    for main in range(1, 4):
        for sub in range(1, 4):
            i = (main - 1) * 3 + sub
            pages[f"http://e.com/x/{i}.html"] = f"""
            <html><head><title>第{main}章 {sub}</title></head><body>
            <h1>第{main}章 {sub}</h1>
            <div id="content">{''.join(f'<p>第{main}章第{sub}部分第{j}段，山风吹过林梢。</p>' for j in range(1, 13))}</div>
            </body></html>
            """
    links = "".join(
        f'<li><a href="/x/{i}.html">第{m}章 {s}</a></li>'
        for i, (m, s) in enumerate([(m, s) for m in range(1, 4) for s in range(1, 4)], start=1)
    )
    pages["http://e.com/catalog.html"] = f'<html><body><ul>{links}</ul></body></html>'

    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    titles = [c.title for c in result.chapters]
    assert titles == ["第1章", "第2章", "第3章"]
    first = result.chapters[0]
    assert len(first.source_pages) == 3
    assert "第1章第1部分" in first.content and "第1章第3部分" in first.content
    assert first.content_status.value == "CONTENT_OK"
    assert any("已合并分页章节" in w for w in result.stats["warnings"])


def test_keep_parts_option_disables_merging():
    pages = {}
    for main in range(1, 3):
        for sub in range(1, 3):
            i = (main - 1) * 2 + sub
            pages[f"http://e.com/x/{i}.html"] = f"""
            <html><head><title>第{main}章 {sub}</title></head><body>
            <h1>第{main}章 {sub}</h1>
            <div id="content">{''.join(f'<p>第{main}-{sub}段{j}，山风吹过林梢。</p>' for j in range(1, 13))}</div>
            </body></html>
            """
    links = "".join(
        f'<li><a href="/x/{i}.html">第{m}章 {s}</a></li>'
        for i, (m, s) in enumerate(
            [(m, s) for m in range(1, 3) for s in range(1, 3)] + [(3, 1)], start=1
        )
    )
    pages["http://e.com/catalog.html"] = f'<html><body><ul>{links}</ul></body></html>'
    pages["http://e.com/x/5.html"] = f"""
    <html><head><title>第3章 1</title></head><body>
    <h1>第3章 1</h1>
    <div id="content">{''.join(f'<p>第3-1段{j}，山风吹过林梢。</p>' for j in range(1, 13))}</div>
    </body></html>
    """

    result = NovelCrawler(
        fetcher=SiteFetcher(pages),
        options=CrawlOptions(request_interval=0.0, merge_parts=False),
    ).crawl("http://e.com/catalog.html")
    assert [c.title for c in result.chapters] == ["第1章 1", "第1章 2", "第2章 1", "第2章 2", "第3章 1"]


def test_merged_mixed_status_keeps_good_parts_and_flags():
    from tests.test_crawler import chapter_page, vip_page

    pages = {
        "http://e.com/catalog.html": '<html><body><ul>'
        + '<li><a href="/x/1.html">第1章 1</a></li>'
        + '<li><a href="/x/2.html">第1章 2</a></li>'
        + '<li><a href="/x/3.html">第2章 1</a></li>'
        + '<li><a href="/x/4.html">第2章 2</a></li>'
        + '<li><a href="/x/5.html">第3章 1</a></li></ul></body></html>',
        "http://e.com/x/1.html": chapter_page("第1章 1", "第一部分"),
        "http://e.com/x/2.html": vip_page("第1章 2"),
        "http://e.com/x/3.html": chapter_page("第2章 1", "第二之一"),
        "http://e.com/x/4.html": chapter_page("第2章 2", "第二之二"),
        "http://e.com/x/5.html": chapter_page("第3章 1", "第三部分"),
    }
    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    first = result.chapters[0]
    assert first.title == "第1章"
    assert first.content_status.value == "PAYWALL"
    assert "第一部分" in first.content          # good part preserved
    assert "未能提取" in first.content          # missing part explicitly marked


def test_two_digit_part_numbers_merge_fully():
    # Regression: sub=10+ parts (frac 0.0010) were wrongly excluded from the
    # merge group by the decimal-main guard, leaving 第9章 11..16 separate.
    titles = [(1, s) for s in range(1, 17)]  # 第1章 1..16
    pages = {}
    links = ""
    for i, (main, sub) in enumerate(titles, start=1):
        links += f'<li><a href="/x/{i}.html">第{main}章 {sub}</a></li>'
        pages[f"http://e.com/x/{i}.html"] = f"""
        <html><head><title>第{main}章 {sub}</title></head><body>
        <h1>第{main}章 {sub}</h1>
        <div id="content">{''.join(f'<p>第{main}-{sub}部分第{j}段，山风吹过林梢。</p>' for j in range(1, 13))}</div>
        </body></html>
        """
    pages["http://e.com/catalog.html"] = f'<html><body><ul>{links}</ul></body></html>'

    result = NovelCrawler(
        fetcher=SiteFetcher(pages), options=CrawlOptions(request_interval=0.0)
    ).crawl("http://e.com/catalog.html")
    assert [c.title for c in result.chapters] == ["第1章"]
    assert len(result.chapters[0].source_pages) == 16


def test_adaptive_pacing_backs_off_and_recovers():
    from novel_extractor.crawler.novel import _CachingFetcher

    options = CrawlOptions(request_interval=0.3)
    fetcher = _CachingFetcher(DictFetcher({}), options, "e.com")
    assert fetcher.current_interval == 0.3

    for expected in (0.6, 1.2, 2.4):
        fetcher.report_shell()
        assert abs(fetcher.current_interval - expected) < 1e-9
    fetcher.report_shell()
    fetcher.report_shell()
    assert fetcher.current_interval == 5.0  # capped

    for _ in range(6):  # healthy streak decays toward the floor
        fetcher.report_success()
    assert fetcher.current_interval < 5.0
    for _ in range(60):
        fetcher.report_success()
    assert abs(fetcher.current_interval - 0.3) < 1e-9  # back at the floor


def test_adaptive_disabled_keeps_fixed_interval():
    from novel_extractor.crawler.novel import _CachingFetcher

    options = CrawlOptions(request_interval=1.0, adaptive_interval=False)
    fetcher = _CachingFetcher(DictFetcher({}), options, "e.com")
    fetcher.report_shell()
    fetcher.report_success()
    assert fetcher.current_interval == 1.0


def test_zero_interval_stays_zero():
    from novel_extractor.crawler.novel import _CachingFetcher

    options = CrawlOptions(request_interval=0.0)
    fetcher = _CachingFetcher(DictFetcher({}), options, "e.com")
    fetcher.report_shell()
    fetcher.report_success()
    assert fetcher.current_interval == 0.0  # tests / offline stay instant


def test_shell_triggers_backoff_in_stats():
    pages = {
        "http://e.com/catalog.html": '<html><body><ul>' + ''.join(
            f'<li><a href="/x/{i}.html">第{i}章 风云{i}</a></li>' for i in range(1, 7)
        ) + '</ul></body></html>',
        **{
            f"http://e.com/x/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 7)
        },
    }

    class ShellOnceFetcher:
        """Serves an empty shell for 第2章 on its first fetch."""

        def __init__(self):
            self.counts: dict[str, int] = {}

        def fetch(self, url: str, *, referer=None) -> FetchedPage:
            self.counts[url] = self.counts.get(url, 0) + 1
            if url.endswith("/x/2.html") and self.counts[url] == 1:
                html = "<html><body>loading</body></html>"
            else:
                html = pages[url]
            return FetchedPage(
                url=url, final_url=url, status_code=200,
                raw_bytes=html.encode("utf-8"), html=html,
                encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
            )

    fetcher = ShellOnceFetcher()
    result = NovelCrawler(
        fetcher=fetcher, options=CrawlOptions(request_interval=0.3, status_retry_delay=0.0)
    ).crawl("http://e.com/catalog.html")
    assert result.stats["adaptive"]["backoffs"] >= 1
    assert result.stats["adaptive"]["final_interval"] > 0.3
    assert len(result.chapters) == 6
    assert result.chapters[1].content_status.value == "CONTENT_OK"  # recovered

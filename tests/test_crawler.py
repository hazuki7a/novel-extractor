"""Integration tests for the MVP NovelCrawler (guide task 14).

A fake site is served from a dict via a stub Fetcher - no network access.
"""

from __future__ import annotations

import pytest

from novel_extractor.crawler.novel import CrawlOptions, NovelCrawler
from novel_extractor.fetcher.http import FetchError
from novel_extractor.models import ContentStatus, FetchedPage


def paragraphs(prefix, count=12):
    return "".join(
        f"<p>{prefix}第{i}段，山风吹过林梢，主角抬眼望向远方，远处的钟声一圈一圈荡开，惊起了几只飞鸟。</p>"
        for i in range(1, count + 1)
    )


def chapter_page(title, body_prefix, prev_href=None, next_href=None, catalog_href=None, next_page_href=None, extra=""):
    nav = "<div class='page-nav'>"
    if prev_href:
        nav += f'<a href="{prev_href}">上一章</a>'
    if catalog_href:
        nav += f'<a href="{catalog_href}">目录</a>'
    if next_href:
        nav += f'<a href="{next_href}">下一章</a>'
    nav += "</div>"
    pagination = f'<div class="pages"><a href="{next_page_href}">下一页</a></div>' if next_page_href else ""
    return f"""
    <html><head><title>{title}_小说阅读网</title></head><body>
    <h1>{title}</h1>
    <div id="content">{paragraphs(body_prefix)}{extra}</div>
    {pagination}{nav}
    </body></html>
    """


def vip_page(title, catalog_href=None):
    nav = f'<a href="{catalog_href}">目录</a>' if catalog_href else ""
    return f"""
    <html><head><title>{title}</title></head><body>
    <h1>{title}</h1>
    <div id="content">本章节为VIP章节，订阅后阅读。</div>
    <div class="page-nav">{nav}</div>
    </body></html>
    """


def catalog_page(entries, next_href=None, base="/book/1/"):
    links = "".join(f'<li><a href="{base}{i}.html">第{i}章 风云{i}</a></li>' for i in entries)
    pagination = f'<div class="pages"><a href="{next_href}">下一页</a></div>' if next_href else ""
    return f"""
    <html><head>
    <meta property="og:novel:book_name" content="测试小说">
    <meta property="og:novel:author" content="测试作者">
    <title>测试小说目录</title></head><body>
    <h1>测试小说</h1>
    <ul class="list">{links}</ul>
    {pagination}
    </body></html>
    """


def book_page(catalog_href="catalog.html"):
    return f"""
    <html><head><title>测试小说 - 详情</title></head><body>
    <h1>测试小说</h1>
    <div class="info">作者：测试作者 类型：玄幻</div>
    <div class="intro">内容简介：这是一个用来测试爬虫的虚构故事。</div>
    <div><a href="{catalog_href}">开始阅读</a></div>
    </body></html>
    """


class DictFetcher:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def fetch(self, url: str, *, referer=None) -> FetchedPage:
        if url not in self.pages:
            raise FetchError(url, "missing page")
        html = self.pages[url]
        return FetchedPage(
            url=url, final_url=url, status_code=200, raw_bytes=html.encode("utf-8"),
            html=html, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
        )


def make_crawler(pages, options=None) -> NovelCrawler:
    return NovelCrawler(fetcher=DictFetcher(pages), options=options or CrawlOptions())


def test_full_catalog_flow_ascending():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 11)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 11)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    assert result.metadata.book_title == "测试小说"
    assert result.metadata.author == "测试作者"
    assert result.direction.value == "ASCENDING"
    assert len(result.chapters) == 10
    assert result.chapters[0].title == "第1章 风云1"
    assert result.chapters[0].index == 1
    assert result.chapters[0].content_status == ContentStatus.CONTENT_OK
    assert "章1" in result.chapters[0].content
    assert result.stats["status_counts"].get("CONTENT_OK") == 10


def test_descending_catalog_is_reversed():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(list(range(10, 0, -1))),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 11)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    assert result.direction.value == "DESCENDING"
    assert result.chapters[0].title == "第1章 风云1"
    assert "DESCENDING" in result.direction_reason or "descend" in result.direction_reason


def test_catalog_pagination_merged():
    pages = {
        "http://e.com/book/1/list.html": catalog_page(range(1, 21), next_href="list_2.html"),
        "http://e.com/book/1/list_2.html": catalog_page(range(21, 31)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 31)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/list.html")
    assert len(result.chapters) == 30
    assert result.chapters[0].title == "第1章 风云1"
    assert result.chapters[-1].title == "第30章 风云30"


def test_content_pagination_merged_into_one_chapter():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 7)),
        "http://e.com/book/1/1.html": chapter_page(
            "第1章 风云1", "前半", catalog_href="catalog.html", next_page_href="1_2.html"
        ),
        "http://e.com/book/1/1_2.html": chapter_page("第1章 风云1", "后半"),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(2, 7)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    assert len(result.chapters) == 6
    first = result.chapters[0]
    assert len(first.source_pages) == 2
    assert "前半" in first.content and "后半" in first.content


def test_restricted_chapter_not_marked_ok():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 7)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 7)
        },
    }
    pages["http://e.com/book/1/2.html"] = vip_page("第2章 风云2")
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    statuses = [c.content_status for c in result.chapters]
    assert statuses[0] is ContentStatus.CONTENT_OK
    assert statuses[1] is ContentStatus.PAYWALL
    assert statuses[2] is ContentStatus.CONTENT_OK
    assert result.stats["status_counts"].get("PAYWALL") == 1


def test_repeated_content_pages_are_not_reported_as_ok():
    repeated_body = "重复推荐"
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 7)),
        "http://e.com/book/1/1.html": chapter_page(
            "第1章 风云1", repeated_body, next_page_href="1_2.html"
        ),
        "http://e.com/book/1/1_2.html": chapter_page("第1章 风云1", repeated_body),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(2, 7)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    assert result.chapters[0].content_status is ContentStatus.UNKNOWN_FAILURE
    assert any("分页正文重复" in warning for warning in result.stats["warnings"])


def test_recurrent_long_boilerplate_is_removed_across_chapters():
    repeated_ad = (
        "这是由页面模板反复注入的长篇作品推荐说明，包含其他作品的人物、情节与收藏提示，"
        "它会在许多不同章节里逐字重复，因此不应作为当前小说的正文保留下来。"
        "为了达到可靠识别所需的长度，这段模板文字还会继续描述无关作品的更新与阅读信息。"
    )
    rare_refrain = (
        "这是作者有意在少量章节中重复的长段回忆，只出现两次，不应被跨章节模板规则误删。"
        "它属于故事内容，需要完整保留，不能因为文字相同就被当作网站广告。"
    )
    pages = {"http://e.com/book/1/catalog.html": catalog_page(range(1, 11))}
    for i in range(1, 11):
        extra = ""
        if i in {1, 4, 6, 8}:
            extra += f"<p>{repeated_ad}</p>"
        if i in {2, 9}:
            extra += f"<p>{rare_refrain}</p>"
        pages[f"http://e.com/book/1/{i}.html"] = chapter_page(
            f"第{i}章 风云{i}", f"章{i}", extra=extra
        )

    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")

    assert all(repeated_ad not in chapter.content for chapter in result.chapters)
    assert rare_refrain in result.chapters[1].content
    assert rare_refrain in result.chapters[8].content
    assert result.stats["recurrent_boilerplate"] == {
        "unique_blocks": 1,
        "removed_occurrences": 4,
        "chapters_affected": 4,
        "chapter_threshold": 3,
    }


def test_start_from_chapter_page_finds_catalog():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 9)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 9)
        },
    }
    pages["http://e.com/book/1/5.html"] = chapter_page(
        "第5章 风云5", "章5", prev_href="4.html", next_href="6.html", catalog_href="catalog.html"
    )
    result = make_crawler(pages).crawl("http://e.com/book/1/5.html")
    assert result.catalog is not None
    assert len(result.chapters) == 8
    assert result.chapters[0].title == "第1章 风云1"


def test_start_from_book_page_finds_catalog():
    pages = {
        "http://e.com/book/1/": book_page(),
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 7)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 7)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/")
    assert len(result.chapters) == 6
    assert result.metadata.book_title == "测试小说"


def test_traversal_without_catalog():
    # Start at chapter 3; explicit prev/next links chain five chapters.
    links = {
        1: {"next_href": "2.html"},
        2: {"prev_href": "1.html", "next_href": "3.html"},
        3: {"prev_href": "2.html", "next_href": "4.html"},
        4: {"prev_href": "3.html", "next_href": "5.html"},
        5: {"prev_href": "4.html"},
    }
    pages = {
        f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}", **links[i])
        for i in links
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/3.html")
    assert [c.title for c in result.chapters] == [f"第{i}章 风云{i}" for i in range(1, 6)]
    assert "no catalog" in " ".join(result.stats["warnings"])


def test_cross_domain_chapter_is_marked_failed():
    # Catalog entry 2 points at a foreign host: the crawler must refuse to
    # fetch it and record the failure instead of silently skipping.
    links = "".join(
        f'<li><a href="{href}">第{i}章 风云{i}</a></li>'
        for i, href in enumerate(
            ["1.html", "http://other.com/2.html", "3.html", "4.html", "5.html", "6.html"], start=1
        )
    )
    catalog_html = f"""
    <html><head><title>测试小说目录</title></head><body>
    <ul class="list">{links}</ul>
    </body></html>
    """
    pages = {
        "http://e.com/book/1/catalog.html": catalog_html,
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 7)
        },
    }
    pages["http://other.com/2.html"] = chapter_page("第2章 风云2", "章2")
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    assert result.chapters[1].content_status == ContentStatus.UNKNOWN_FAILURE
    assert any("cross-domain" in w for w in result.stats["warnings"])


def test_max_chapters_cap():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 31)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 31)
        },
    }
    options = CrawlOptions(max_chapters=5)
    result = make_crawler(pages, options).crawl("http://e.com/book/1/catalog.html")
    assert len(result.chapters) == 5
    assert any("max_chapters" in w for w in result.stats["warnings"])


def test_catalog_self_pagination_loop_is_contained():
    pages = {
        "http://e.com/book/1/list.html": catalog_page(range(1, 21), next_href="list.html"),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 21)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/list.html")
    # The self-link must not spin; chapters still download once.
    assert len(result.chapters) == 20
    assert result.stats["fetcher"]["fetched"] <= 25


def test_chapter_title_prefers_on_page_h1():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 7)),
        # h1 title differs from the (deliberately sparse) catalog entry title
        "http://e.com/book/1/1.html": chapter_page("第1章 风云1", "章1"),
        "http://e.com/book/1/2.html": chapter_page("第2章 风云2", "章2"),
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    assert result.chapters[0].title == "第1章 风云1"


def test_stats_shape():
    pages = {
        "http://e.com/book/1/catalog.html": catalog_page(range(1, 7)),
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 7)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/catalog.html")
    for key in ("chapters_total", "status_counts", "fetcher", "start_page_type"):
        assert key in result.stats
    assert result.stats["chapters_total"] == 6


def test_exploration_recovers_catalog_from_book_page():
    # Book page WITHOUT a working 开始阅读 link, only a 全部章节 candidate:
    # Local Site Exploration must discover the catalog page (guide task 24).
    catalog = '<html><body><ul>' + ''.join(
        f'<li><a href="/book/1/{i}.html">第{i}章 风云{i}</a></li>' for i in range(1, 9)
    ) + '</ul></body></html>'
    # The first three catalog-word links dead-end or hold too few chapters
    # (beyond _find_catalog_page's 3-link try limit); only exploration finds
    # the real catalog as the fourth candidate.
    book = """
    <html><head><title>测试小说 - 详情</title></head><body>
    <h1>测试小说</h1>
    <div class="info">作者：测试作者 类型：玄幻</div>
    <div class="intro">内容简介：一个用于测试局部探索的虚构故事，情节简单。</div>
    <div>
      <a href="/book/1/gone.html">正文</a>
      <a href="/book/1/few.html">开始阅读</a>
      <a href="/book/1/few2.html">点击阅读</a>
      <a href="/book/1/all.html">全部章节</a>
    </div>
    </body></html>
    """
    few = '<html><body><ul><li><a href="/b/1.html">第1章 零星1</a></li><li><a href="/b/2.html">第2章 零星2</a></li></ul></body></html>'
    pages = {
        "http://e.com/book/1/": book,
        "http://e.com/book/1/all.html": catalog,
        "http://e.com/book/1/gone.html": "<html><body>404 页面不存在</body></html>",
        "http://e.com/book/1/few.html": few,
        "http://e.com/book/1/few2.html": few,
        **{
            f"http://e.com/book/1/{i}.html": chapter_page(f"第{i}章 风云{i}", f"章{i}")
            for i in range(1, 9)
        },
    }
    result = make_crawler(pages).crawl("http://e.com/book/1/")
    assert len(result.chapters) == 8
    assert result.stats["exploration"]["stop_reason"] == "catalog_found"
    assert any("局部探索找到目录页" in w for w in result.stats["warnings"])

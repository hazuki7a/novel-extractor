"""Tests for content pagination detection and merging (guide task 11)."""

from __future__ import annotations

from novel_extractor.analyzer.pagination import (
    ContentPaginationDetector,
    ContentPaginationMerger,
    strip_page_suffix,
)
from novel_extractor.fetcher.http import FetchError
from novel_extractor.models import FetchedPage
from tests.test_catalog_pagination import DictFetcher, make_page


def content_page(title: str, paragraphs: str, next_href=None, numeric_pages=""):
    next_a = f'<a href="{next_href}">下一页</a>' if next_href else ""
    return f"""
    <html><head><title>{title}</title></head><body>
    <h1>{title}</h1>
    <div id="content">{paragraphs}</div>
    <div class="page-nav">{numeric_pages}{next_a}</div>
    </body></html>
    """


def paragraphs(prefix, count=8):
    return "".join(f"<p>{prefix}第{i}段，山风吹过林梢，主角抬眼望向远方。</p>" for i in range(1, count + 1))


def test_content_pagination_detected_on_chapter_page():
    html = content_page("第一章 出山", paragraphs("前半"), next_href="1_2.html")
    result = ContentPaginationDetector().detect(html, "http://e.com/book/1/1.html")
    assert result.value.next_content_page == "http://e.com/book/1/1_2.html"
    assert result.confidence >= 0.60


def test_chapter_hop_word_is_not_content_pagination():
    html = content_page("第一章 出山", paragraphs("前半"))
    html = html.replace("</body>", '<div><a href="2.html">下一章</a></div></body>')
    result = ContentPaginationDetector().detect(html, "http://e.com/book/1/1.html")
    assert result.value.next_content_page is None


def test_numeric_page_links_fallback():
    # No 下一页 at all - just bare numeric page links.
    html = content_page(
        "第二章 风起",
        paragraphs("分页"),
        numeric_pages='<a href="2_1.html">1</a><a href="2_2.html">2</a><a href="2_3.html">3</a>',
    )
    result = ContentPaginationDetector().detect(html, "http://e.com/book/1/2_1.html")
    assert result.value.next_content_page == "http://e.com/book/1/2_2.html"


def test_merger_merges_same_chapter_pages():
    pages = {
        "http://e.com/book/1/1.html": content_page("第一章 出山", paragraphs("前半"), next_href="1_2.html"),
        "http://e.com/book/1/1_2.html": content_page("第一章 出山(2/3)", paragraphs("中段"), next_href="1_3.html"),
        "http://e.com/book/1/1_3.html": content_page("第一章 出山", paragraphs("后段")),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, texts, diagnostics = merger.walk(make_page("http://e.com/book/1/1.html", pages["http://e.com/book/1/1.html"]))
    assert len(walked) == 3
    assert diagnostics["stopped_by"] == "no_next"
    assert any("前半" in t for t in texts)
    assert any("中段" in t for t in texts)
    assert any("后段" in t for t in texts)


def test_merger_reports_repeated_long_extraction_across_pages():
    repeated = paragraphs("热门推荐", count=16)
    pages = {
        "http://e.com/book/1/1.html": content_page("第一章 出山", repeated, next_href="1_2.html"),
        "http://e.com/book/1/1_2.html": content_page("第一章 出山", repeated),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    _walked, _texts, diagnostics = merger.walk(
        make_page("http://e.com/book/1/1.html", pages["http://e.com/book/1/1.html"])
    )
    assert diagnostics["duplicate_content_pages"] == [[1, 2]]


def test_merger_stops_when_next_is_new_chapter():
    pages = {
        "http://e.com/book/1/1.html": content_page("第一章 出山", paragraphs("前半"), next_href="2.html"),
        "http://e.com/book/1/2.html": content_page("第二章 风起", paragraphs("下一章内容")),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, texts, diagnostics = merger.walk(make_page("http://e.com/book/1/1.html", pages["http://e.com/book/1/1.html"]))
    assert len(walked) == 1
    assert diagnostics["stopped_by"] == "different_chapter"
    assert diagnostics["rejected_url"] == "http://e.com/book/1/2.html"
    assert not any("下一章内容" in t for t in texts)


def test_merger_stops_on_loop():
    # Filenames without page-number shapes so the back-link keeps full
    # confidence and the walk actually reaches the visited-URL guard.
    pages = {
        "http://e.com/book/1/part_a.html": content_page("第一章 出山", paragraphs("a"), next_href="part_b.html"),
        "http://e.com/book/1/part_b.html": content_page("第一章 出山(2)", paragraphs("b"), next_href="part_a.html"),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, _texts, diagnostics = merger.walk(
        make_page("http://e.com/book/1/part_a.html", pages["http://e.com/book/1/part_a.html"])
    )
    assert len(walked) == 2
    assert diagnostics["stopped_by"] == "loop"


def test_merger_respects_max_pages():
    pages = {}
    for i in range(1, 15):
        nxt = f"1_{i + 1}.html" if i < 14 else None
        pages[f"http://e.com/book/1/1_{i}.html"] = content_page(
            f"第一章 出山({i})" if i > 1 else "第一章 出山",
            paragraphs(f"页{i}"), next_href=nxt,
        )
    merger = ContentPaginationMerger(DictFetcher(pages), max_pages=4)
    walked, _texts, diagnostics = merger.walk(
        make_page("http://e.com/book/1/1_1.html", pages["http://e.com/book/1/1_1.html"])
    )
    assert len(walked) == 4
    assert diagnostics["stopped_by"] == "max_pages"


def test_merger_survives_fetch_error():
    pages = {
        "http://e.com/book/1/1.html": content_page("第一章 出山", paragraphs("前半"), next_href="gone.html"),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, _texts, diagnostics = merger.walk(
        make_page("http://e.com/book/1/1.html", pages["http://e.com/book/1/1.html"])
    )
    assert len(walked) == 1
    assert diagnostics["stopped_by"] == "fetch_error"


def test_strip_page_suffix_variants():
    assert strip_page_suffix("第一章 出山(2/3)") == "第一章 出山"
    assert strip_page_suffix("第一章 出山(第2页)") == "第一章 出山"
    assert strip_page_suffix("第一章 出山_2") == "第一章 出山"
    assert strip_page_suffix("第一章 出山") == "第一章 出山"
    assert strip_page_suffix("第12章 出山(2)(3)") == "第12章 出山"


def test_start_without_number_accepts_same_title_continuation():
    # Start title unparseable as chapter, continuation repeats the same title.
    pages = {
        "http://e.com/x/a.html": content_page("出山", paragraphs("前半"), next_href="a2.html"),
        "http://e.com/x/a2.html": content_page("出山(2)", paragraphs("后段")),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, texts, diagnostics = merger.walk(make_page("http://e.com/x/a.html", pages["http://e.com/x/a.html"]))
    assert len(walked) == 2
    assert diagnostics["stopped_by"] == "no_next"
    assert any("后段" in t for t in texts)


def test_fetch_error_is_recorded_not_raised():
    class Boom:
        def fetch(self, url):
            raise FetchError(url, "boom")

    html = content_page("第三章 暗流", paragraphs("内容"), next_href="3_2.html")
    merger = ContentPaginationMerger(Boom())
    walked, _texts, diagnostics = merger.walk(make_page("http://e.com/book/1/3.html", html))
    assert diagnostics["stopped_by"] == "fetch_error"


def test_make_page_helper_import_works():
    page = make_page("http://e.com/x", "<html></html>")
    assert isinstance(page, FetchedPage)


def test_quanben_style_chapter_word_pagination_merged():
    # Real lingduxs pattern: in-chapter page turns labelled 下一章, titles
    # carrying explicit page markers 第1章（第2页）. The merger must accept
    # the hypothesis only through title-borne page-marker verification.
    def page(title, next_href=None, body="内容"):
        nav = f'<a href="{next_href}">下一章</a>' if next_href else ""
        return f"""
        <html><head><title>{title}_那么爱你为什么</title></head><body>
        <h1 class="site-title">零度小说网</h1>
        <h2 class="chapter-title">{title}</h2>
        <div id="content">{''.join(f'<p>{body}第{j}段，山风吹过林梢。</p>' for j in range(1, 13))}</div>
        <div class="read_btn"><a href="/b/">上一章</a><a href="/b/">章节目录</a>
        <a>保存书签</a><a>阅读记录</a>{nav}</div>
        </body></html>
        """

    pages = {
        "http://e.com/b/100.html": page("第1章（第1页）", next_href="100_1.html"),
        "http://e.com/b/100_1.html": page("第1章（第2页）", next_href="100_2.html"),
        "http://e.com/b/100_2.html": page("第1章（第3页）"),
        "http://e.com/b/200.html": page("第2章（第1页）"),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, texts, diagnostics = merger.walk(
        make_page("http://e.com/b/100.html", pages["http://e.com/b/100.html"])
    )
    assert len(walked) == 3
    assert diagnostics["stopped_by"] == "no_next"
    assert all("内容" in t for t in texts)


def test_page_title_prefers_chapter_h2_over_site_logo_h1():
    html = """
    <html><head><title>第1章第2页_示例小说免费阅读_示例网</title></head><body>
      <h1 class="site-title">示例小说网</h1>
      <h2 class="chapter-title">第1章（第2页）</h2>
    </body></html>
    """
    from novel_extractor.analyzer.pagination import page_title

    assert page_title(html) == "第1章（第2页）"


def test_chapter_word_without_page_marker_still_rejected():
    # No explicit page marker in the target title: the 下一章-labelled link
    # stays a chapter hop and must not be swallowed as pagination.
    pages = {
        "http://e.com/b/1.html": content_page("第1章 出山", paragraphs("前半"), next_href="2.html"),
        "http://e.com/b/2.html": content_page("第2章 风起", paragraphs("下一章内容")),
    }
    merger = ContentPaginationMerger(DictFetcher(pages))
    walked, texts, diagnostics = merger.walk(
        make_page("http://e.com/b/1.html", pages["http://e.com/b/1.html"])
    )
    assert len(walked) == 1
    # A 下一页-labelled candidate whose target is a different chapter title
    # is rejected as a chapter hop (different_chapter), never merged.
    assert diagnostics["stopped_by"] == "different_chapter"
    assert diagnostics["rejected_url"] == "http://e.com/b/2.html"

"""Tests for chapter navigation detection (guide task 10).

Key requirement: PREVIOUS_CHAPTER / NEXT_CHAPTER / CATALOG_LINK only.
"下一页" (content pagination) must never be reported as a chapter hop.
"""

from __future__ import annotations

from novel_extractor.analyzer.navigation import ChapterNavigationDetector


def make_chapter_page(nav: str) -> str:
    return f"""
    <html><head><title>第12章 出山</title></head><body>
    <h1>第12章 出山</h1>
    <div id="content">{'<p>正文段落，山风呼啸而过。</p>' * 10}</div>
    <div class="page-nav">{nav}</div>
    </body></html>
    """


def test_prev_next_catalog_all_detected():
    nav = """
    <a href="/book/1/11.html">上一章</a>
    <a href="/catalog.html">目录</a>
    <a href="/book/1/13.html">下一章</a>
    """
    result = ChapterNavigationDetector().detect(nav and make_chapter_page(nav), "http://e.com/book/1/12.html")
    assert result.value["previous_chapter"] == "http://e.com/book/1/11.html"
    assert result.value["next_chapter"] == "http://e.com/book/1/13.html"
    assert result.value["catalog_url"] == "http://e.com/catalog.html"
    assert result.confidence >= 0.70
    relations = {r["relation_type"] for r in result.value["relations"]}
    assert relations == {"PREVIOUS_CHAPTER", "NEXT_CHAPTER", "CATALOG_LINK"}


def test_content_pagination_word_not_a_chapter_hop():
    nav = """
    <a href="/book/1/12_1.html">上一页</a>
    <a href="/book/1/12_2.html">下一页</a>
    <a href="/catalog.html">目录</a>
    """
    result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book/1/12.html")
    assert result.value["next_chapter"] is None
    assert result.value["previous_chapter"] is None
    assert result.value["catalog_url"] == "http://e.com/catalog.html"


def test_english_next_page_not_chapter_hop():
    # "next" is in both vocabularies; "next page" belongs to pagination.
    nav = '<a href="/book/1/12_2.html">next page</a> <a href="/book/1/13.html">next chapter</a>'
    result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book/1/12.html")
    assert result.value["next_chapter"] == "http://e.com/book/1/13.html"
    # The shared-word anchor was skipped by longest-match ownership.
    assert result.diagnostics.get("NEXT_CHAPTER_skipped_pagination_words", 0) >= 1


def test_bare_next_is_chapter_hop():
    nav = '<a href="/book/1/13.html">next</a>'
    result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book/1/12.html")
    assert result.value["next_chapter"] == "http://e.com/book/1/13.html"


def test_cross_directory_next_chapter_still_detected():
    nav = '<a href="/book2/50.html">下一章</a>'
    result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book1/49.html")
    assert result.value["next_chapter"] == "http://e.com/book2/50.html"
    assert result.confidence >= 0.60


def test_catalog_word_variants():
    for word, href in [
        ("返回目录", "index.html"),
        ("章节目录", "/book/1/"),
        ("全部章节", "all.html"),
        ("contents", "toc.html"),
    ]:
        nav = f'<a href="{href}">{word}</a>'
        result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book/1/12.html")
        assert result.value["catalog_url"] is not None, word


def test_no_navigation_links():
    html = "<html><body><p>只有正文没有导航。</p></body></html>"
    result = ChapterNavigationDetector().detect(html, "http://e.com/book/1/12.html")
    assert result.value["next_chapter"] is None
    assert result.value["previous_chapter"] is None
    assert result.value["catalog_url"] is None
    assert result.confidence == 0.0


def test_self_link_rejected():
    nav = '<a href="/book/1/12.html">下一章</a>'
    result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book/1/12.html")
    assert result.value["next_chapter"] is None


def test_relative_hrefs_resolved():
    nav = '<a href="13.html">下一章</a>'
    result = ChapterNavigationDetector().detect(make_chapter_page(nav), "http://e.com/book/1/12.html")
    assert result.value["next_chapter"] == "http://e.com/book/1/13.html"


def test_numbered_url_increment_boosts_confidence():
    plain = ChapterNavigationDetector().detect(
        make_chapter_page('<a href="http://other-site.net/abc.html">下一章</a>'),
        "http://e.com/book/1/12.html",
    )
    numbered = ChapterNavigationDetector().detect(
        make_chapter_page('<a href="13.html">下一章</a>'),
        "http://e.com/book/1/12.html",
    )
    assert numbered.confidence > plain.confidence

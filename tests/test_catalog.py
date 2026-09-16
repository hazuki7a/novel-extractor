"""Tests for generic catalog detection (guide task 7)."""

from __future__ import annotations

from novel_extractor.analyzer.catalog import CatalogDetector


def make_catalog(links, wrapper="<ul class=\"list\">{}</ul>", joiner=""):
    return f"""
    <html><head><title>目录</title></head><body>
    <div class="nav"><a href="/">首页</a><a href="/sort/1">玄幻</a></div>
    <h1>正文卷</h1>
    {wrapper.format(joiner.join(links))}
    </body></html>
    """


def chapter_links(start=1, end=61):
    return [
        f'<li><a href="/book/1/{i}.html">第{i}章 大战{i}</a></li>'
        for i in range(start, end)
    ]


def test_basic_catalog_detected_in_dom_order():
    html = make_catalog(chapter_links())
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 60
    assert result.chapters[0].title == "第1章 大战1"
    assert result.chapters[-1].title == "第60章 大战60"
    assert result.chapters[0].dom_index < result.chapters[1].dom_index
    assert result.direction.value == "UNKNOWN"  # direction decided later
    assert result.confidence >= 0.70
    assert "clustered" in result.reason


def test_base_url_is_joined():
    html = make_catalog(chapter_links(1, 11))
    result = CatalogDetector().detect(html, base_url="http://example.com/book/1/")
    assert result.chapters[0].url == "http://example.com/book/1/1.html"


def test_absolute_hrefs_kept_without_base_url():
    html = make_catalog(chapter_links(1, 11))
    result = CatalogDetector().detect(html)
    assert result.chapters[0].url == "/book/1/1.html"


def test_volume_grouped_lists_are_merged():
    html = """
    <html><body>
    <h2>第一卷</h2>
    <ul><li><a href="/b/1/1.html">第1章 起</a></li><li><a href="/b/1/2.html">第2章 承</a></li>
    <li><a href="/b/1/3.html">第3章 转</a></li><li><a href="/b/1/4.html">第4章 合</a></li>
    <li><a href="/b/1/5.html">第5章 终</a></li></ul>
    <h2>第二卷</h2>
    <ul><li><a href="/b/1/6.html">第6章 又起</a></li><li><a href="/b/1/7.html">第7章 又承</a></li>
    <li><a href="/b/1/8.html">第8章 又转</a></li><li><a href="/b/1/9.html">第9章 又合</a></li>
    <li><a href="/b/1/10.html">第10章 又终</a></li></ul>
    </body></html>
    """
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 10
    assert result.chapters[0].title == "第1章 起"
    assert result.chapters[-1].title == "第10章 又终"


def test_chapter_page_does_not_produce_catalog():
    html = f"""
    <html><body>
    <h1>第12章 出山</h1>
    <div id="content">{'<p>正文内容一段又一段，写得非常长。</p>' * 12}</div>
    <div class="nav">
      <a href="/book/1/11.html">上一章</a>
      <a href="/catalog.html">目录</a>
      <a href="/book/1/13.html">下一章</a>
    </div></body></html>
    """
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 0
    assert result.confidence < 0.5


def test_non_chapter_links_rejected():
    html = """
    <html><body>
    <ul>
      <li><a href="/1">本站公告</a></li>
      <li><a href="/2">读者讨论区</a></li>
      <li><a href="/3">站长推荐</a></li>
      <li><a href="/4">友情链接</a></li>
      <li><a href="/5">联系我们</a></li>
      <li><a href="/6">隐私政策</a></li>
    </ul>
    </body></html>
    """
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 0


def test_weak_embedded_titles_not_counted():
    html = f"""
    <html><body>
    <div>{'<p>他说第三章写得很好看，主角终于突破了。</p>' * 10}</div>
    </body></html>
    """
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 0


def test_special_titles_recognized_in_catalog():
    links = [
        '<li><a href="/b/0.html">序章</a></li>',
        '<li><a href="/b/1.html">第一章 醒来</a></li>',
        '<li><a href="/b/2.html">第二章 出门</a></li>',
        '<li><a href="/b/3.html">第三章 回家</a></li>',
        '<li><a href="/b/4.html">第四章 睡觉</a></li>',
        '<li><a href="/b/5.html">番外 新年</a></li>',
    ]
    html = make_catalog(links)
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 6
    assert result.chapters[0].title == "序章"
    assert result.chapters[-1].title == "番外 新年"


def test_javascript_and_anchor_hrefs_skipped():
    links = [
        '<li><a href="javascript:void(0)">第1章 假的</a></li>',
        '<li><a href="#top">第2章 假的</a></li>',
    ]
    html = make_catalog(links)
    result = CatalogDetector().detect(html)
    assert len(result.chapters) == 0

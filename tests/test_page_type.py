"""Tests for page type classification (guide task 6)."""

from __future__ import annotations

from novel_extractor.models import PageType
from novel_extractor.analyzer.page_type import PageTypeDetector

CHAPTER_PARAGRAPHS = "".join(
    f"<p>这是第{i}段正文，主角沿着山路缓缓而行，远处的钟声一圈一圈荡开，惊起几只飞鸟，山谷里的雾气也随之散去。</p>"
    for i in range(1, 14)
)


def make_chapter_page() -> str:
    return f"""
    <html><head><title>第12章 出山</title></head><body>
    <div class="breadcrumb"><a href="/">首页</a> &gt; <a href="/book/1">小说</a></div>
    <h1>第12章 出山</h1>
    <div id="content">{CHAPTER_PARAGRAPHS}</div>
    <div class="page-nav">
      <a href="/book/1/11.html">上一章</a>
      <a href="/catalog.html">目录</a>
      <a href="/book/1/13.html">下一章</a>
    </div></body></html>
    """


def make_catalog_page() -> str:
    links = "".join(
        f'<li><a href="/book/1/{i}.html">第{i}章 大战{i}</a></li>' for i in range(1, 61)
    )
    return f"""
    <html><head><title>小说目录</title></head><body>
    <h1>正文卷</h1>
    <ul class="list">{links}</ul>
    </body></html>
    """


def make_book_page() -> str:
    return """
    <html><head><title>星辰变 - 小说详情</title>
    <meta name="description" content="这是一本讲述少年修炼的书籍简介内容，情节曲折动人，值得一看。">
    </head><body>
    <h1>星辰变</h1>
    <div class="info">作者：我吃西红柿 类型：玄幻 状态：完结</div>
    <div class="intro">内容简介：一名少年得到一块神秘流星泪，从此开启逆袭之路，最终问鼎巅峰。</div>
    <div class="latest">
      <a href="/book/1/100.html">第100章 大结局</a>
    </div>
    </body></html>
    """


def test_classify_chapter_page():
    result = PageTypeDetector().classify(make_chapter_page())
    assert result.value == PageType.CHAPTER_PAGE
    assert result.confidence >= 0.5
    assert result.diagnostics["chapter_score"] >= result.diagnostics["catalog_score"]


def test_classify_catalog_page():
    result = PageTypeDetector().classify(make_catalog_page())
    assert result.value == PageType.CATALOG_PAGE
    assert result.confidence >= 0.5
    assert result.diagnostics["chapter_like_links"] >= 30


def test_classify_book_page():
    result = PageTypeDetector().classify(make_book_page())
    assert result.value == PageType.BOOK_PAGE, result.diagnostics


def test_unknown_page():
    html = "<html><body><p>登录后才能继续访问本站内容。</p></body></html>"
    result = PageTypeDetector().classify(html)
    assert result.value == PageType.UNKNOWN


def test_diagnositcs_present():
    result = PageTypeDetector().classify(make_chapter_page())
    for key in ("chapter_score", "catalog_score", "book_score", "content_len"):
        assert key in result.diagnostics

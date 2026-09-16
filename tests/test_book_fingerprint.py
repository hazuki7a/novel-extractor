"""Tests for Book Fingerprint (guide task 17)."""

from __future__ import annotations

from novel_extractor.analyzer.book_fingerprint import BookFingerprinter, normalize_text

CHAPTER_A = """
<html><head><title>星辰变 第12章 - 零度小说网</title>
<script type="application/ld+json">
{"@type": "Book", "name": "星辰变", "author": "我吃西红柿"}
</script></head>
<body>
<nav><a href="/">首页</a><a href="/sort">分类</a><a href="/rank">排行</a><a href="/login">登录</a></nav>
<div class="breadcrumb"><a href="/">首页</a> &gt; <a href="/sort/1/">玄幻</a> &gt; <a href="/124/124181/">星辰变</a></div>
<h1>第12章 初入江湖</h1>
<div id="content">
<p>主角背起行囊走出了山村，第一次见到如此繁华的城镇。</p>
<p>他在人群中四处张望，寻找着传闻中的武馆。</p>
<p>夜色渐深，篝火明明灭灭，映着他清瘦的侧脸。</p>
<p>远处的城池灯火渐次亮起，像撒在黑绸上的碎金。</p>
<p>风穿过林梢，卷起几片落叶，又轻轻放下。</p>
<p>他握了握拳，继续向前走去。</p>
</div>
<footer><a href="/about">关于</a><a href="/contact">联系</a><a href="/map">地图</a></footer>
</body></html>
"""

CHAPTER_B = """
<html><head><title>星辰变 第37章 - 零度小说网</title>
<script type="application/ld+json">
{"@type": "Book", "name": "星辰变", "author": "我吃西红柿"}
</script></head>
<body>
<nav><a href="/">首页</a><a href="/sort">分类</a><a href="/rank">排行</a><a href="/login">登录</a></nav>
<div class="breadcrumb"><a href="/">首页</a> &gt; <a href="/sort/1/">玄幻</a> &gt; <a href="/124/124181/">星辰变</a></div>
<h1>第37章 峰回路转</h1>
<div id="content">
<p>山道在雾里若隐若现，主角握紧行囊继续向上。</p>
<p>钟声从谷底传来，一圈一圈荡开，惊起满树飞鸟。</p>
<p>夜色渐深，篝火明明灭灭，映着他清瘦的侧脸。</p>
<p>风穿过林梢，卷起几片落叶，又轻轻放下。</p>
<p>他记得师父说过，修行如逆水行舟。</p>
<p>天边的云层裂开一道缝隙。</p>
</div>
<footer><a href="/about">关于</a><a href="/contact">联系</a><a href="/map">地图</a></footer>
</body></html>
"""

OTHER_BOOK = CHAPTER_B.replace(
    "星辰变 第37章", "凡人修仙传 第900章"
).replace(
    '"name": "星辰变", "author": "我吃西红柿"', '"name": "凡人修仙传", "author": "忘语"'
).replace(
    "第37章 峰回路转", "第900章 灵界之乱"
).replace(
    "/124/124181/", "/77/77525/"
)


def test_normalize_text():
    assert normalize_text("《星辰变 》-我吃西红柿!") == "星辰变我吃西红柿"


def test_same_book_chapters_score_high():
    fp = BookFingerprinter()
    a = fp.fingerprint(CHAPTER_A, "https://www.xs.cc/124/124181/12.html")
    b = fp.fingerprint(CHAPTER_B, "https://www.xs.cc/124/124181/37.html")
    result = fp.compare(a, b)
    assert result.value >= 0.75, result.reason
    assert result.diagnostics["verdict"] == "same book"
    assert "book_title" in result.reason


def test_different_books_same_site_score_below_same_book():
    fp = BookFingerprinter()
    a = fp.fingerprint(CHAPTER_A, "https://www.xs.cc/124/124181/12.html")
    b = fp.fingerprint(OTHER_BOOK, "https://www.xs.cc/77/77525/900.html")
    result = fp.compare(a, b)
    assert result.value < 0.75
    assert result.diagnostics["verdict"] in ("different", "related / uncertain")


def test_domain_alone_never_asserts_same_book():
    fp = BookFingerprinter()
    # Only the domain matches (no titles, no structure).
    a = fp.fingerprint("<html><body>没有任何可提取特征</body></html>", "https://same.com/a")
    b = fp.fingerprint("<html><body>完全不同的另一页</body></html>", "https://same.com/b")
    result = fp.compare(a, b)
    assert result.diagnostics["verdict"] != "same book"  # domain is a weak feature
    assert result.confidence < 0.75  # thin coverage discounts it


def test_thin_evidence_discounts_confidence():
    fp = BookFingerprinter()
    a = fp.fingerprint(CHAPTER_A, "https://www.xs.cc/a")
    b = fp.fingerprint(CHAPTER_B, "https://other.org/b")
    full = fp.compare(a, b)
    # Strip everything but headings from one side to thin the evidence.
    from novel_extractor.analyzer.book_fingerprint import PageFingerprint

    thin_b = PageFingerprint(headings=b.headings)
    thin_a = PageFingerprint(headings=a.headings)
    thin = fp.compare(thin_a, thin_b)
    assert thin.diagnostics["coverage"] < 1.0
    assert thin.confidence <= full.value  # discounted vs full-coverage score


def test_empty_fingerprints_fail_safely():
    fp = BookFingerprinter()
    a = fp.fingerprint("<html></html>")
    b = fp.fingerprint("<html></html>")
    result = fp.compare(a, b)
    assert result.value == 0.0
    assert result.confidence == 0.0

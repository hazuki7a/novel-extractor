"""Tests for book metadata extraction (guide task 5)."""

from __future__ import annotations

from novel_extractor.analyzer.metadata import MetadataExtractor


def test_og_novel_convention_page():
    html = """
    <html><head>
      <meta property="og:novel:book_name" content="斗破苍穹最新章节列表">
      <meta property="og:novel:author" content="天蚕土豆">
      <meta property="og:novel:volume" content="第一卷">
      <meta property="og:description" content="这是一段书籍简介">
      <meta property="og:image" content="http://example.com/cover.jpg">
      <title>斗破苍穹最新章节列表_斗破苍穹无弹窗</title>
    </head><body><h1>斗破苍穹</h1></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.book_title == "斗破苍穹"
    assert meta.title_confidence >= 0.85
    assert "og_novel_book_name" in meta.title_reason
    assert meta.author == "天蚕土豆"
    assert meta.author_confidence >= 0.85
    assert meta.volume_title == "第一卷"
    assert meta.description == "这是一段书籍简介"
    assert meta.cover_url == "http://example.com/cover.jpg"


def test_json_ld_book_beats_everything():
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Book", "name": "诡秘之主", "author": {"name": "爱潜水的乌贼"}}
      </script>
      <meta property="og:novel:book_name" content="另一个标题">
    </head><body></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.book_title == "诡秘之主"
    assert meta.title_confidence >= 0.90
    assert "json_ld_book" in meta.title_reason
    assert meta.author == "爱潜水的乌贼"
    assert meta.author_confidence >= 0.90


def test_h1_and_author_label_fallback():
    html = """
    <html><head><title>凡人修仙传最新章节列表_凡人修仙传_小说网</title></head>
    <body>
      <h1>凡人修仙传</h1>
      <div class="info">作者：忘语 类型：仙侠 更新：2024-01-01</div>
    </body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.book_title == "凡人修仙传"
    assert meta.title_confidence >= 0.60
    assert meta.author == "忘语"
    assert meta.author_confidence >= 0.75
    assert "author_label_text" in meta.author_reason


def test_meta_author_tag():
    html = """
    <html><head><meta name="author" content="猫腻"></head>
    <body><h1>庆余年</h1></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.author == "猫腻"
    assert "meta_author" in meta.author_reason


def test_title_template_fallback_only():
    html = """
    <html><head><title>雪中悍刀行最新章节列表_雪中悍刀行无弹窗_某小说网</title></head>
    <body><div>没有h1也没有og</div></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.book_title == "雪中悍刀行"
    assert meta.title_confidence <= 0.50
    assert meta.author is None
    assert meta.author_confidence == 0.0


def test_english_author_label():
    html = """
    <html><body><h1>Reverend Insanity</h1>
    <div>Author: Gu Zhen Ren</div></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.book_title == "Reverend Insanity"
    assert meta.author == "Gu Zhen Ren"


def test_nothing_found_returns_empty_metadata():
    html = "<html><body><p>完全无关的内容</p></body></html>"
    meta = MetadataExtractor().extract(html)
    assert meta.book_title is None
    assert meta.author is None
    assert meta.title_confidence == 0.0
    assert meta.description is None


def test_broken_json_ld_ignored():
    html = """
    <html><head>
      <script type="application/ld+json">{"@type": "Book", "name": </script>
    </head><body><h1>残页标题</h1></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.book_title == "残页标题"


def test_author_label_does_not_match_prose():
    html = """
    <html><body><p>作者的话：今天开始两连更，感谢大家的支持。</p></body></html>
    """
    meta = MetadataExtractor().extract(html)
    assert meta.author is None

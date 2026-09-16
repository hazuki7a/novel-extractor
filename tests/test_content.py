"""Tests for main content extraction (guide task 4).

Candidates: trafilatura baseline + custom DOM text density. All tests use
inline HTML; none touch the network or hardcode any site structure.
"""

from __future__ import annotations

from novel_extractor.analyzer.content import ContentExtractor, extract_lines

NAV = """
<div class="nav">
  <a href="/">首页</a> <a href="/sort">分类</a> <a href="/rank">排行</a>
  <a href="/book/1">热门小说一</a> <a href="/book/2">热门小说二</a>
  <a href="/book/3">热门小说三</a> <a href="/book/4">热门小说四</a>
</div>
"""

PARAGRAPH_CONTENT = "".join(
    f"<p>这是第{i}段正文，主角在山间的小路上行走，远处的钟声一圈一圈荡开，惊起了几只飞鸟。</p>"
    for i in range(1, 12)
)


def _page(content_html: str, wrapper: str = "div") -> str:
    return f"<html><head><title>t</title></head><body>{NAV}<{wrapper}>{content_html}</{wrapper}></body></html>"


def test_paragraph_content_wins_over_nav():
    html = _page(PARAGRAPH_CONTENT)
    result = ContentExtractor().extract(html)
    assert result.confidence >= 0.7
    assert "第1段正文" in result.text
    assert "第11段正文" in result.text
    assert result.node_tag in ("div", "article", "main", "section", "trafilatura")
    assert result.diagnostics.get("link_ratio", 1) < 0.2 or result.node_tag == "trafilatura"


def test_br_separated_content_is_line_split():
    content = "<br>".join(
        f"第{i}行正文内容，山风吹过林梢。主角抬头看了看天色。" for i in range(1, 15)
    )
    html = _page(content)
    result = ContentExtractor().extract(html)
    lines = [line for line in result.text.splitlines() if line.strip()]
    assert len(lines) >= 12
    assert "第13行正文内容" in result.text


def test_script_and_style_excluded():
    html = _page(
        "<script>var tracking = '跟踪脚本内容';</script>"
        "<style>.x { color: red; }</style>" + PARAGRAPH_CONTENT
    )
    result = ContentExtractor().extract(html)
    assert "tracking" not in result.text
    assert "color: red" not in result.text
    assert "第1段正文" in result.text


def test_link_only_page_has_no_content():
    html = _page(
        "".join(f'<a href="/b/{i}">小说标题{i}</a>' for i in range(30))
    )
    result = ContentExtractor().extract(html)
    assert result.confidence < 0.6


def test_empty_page():
    result = ContentExtractor().extract("<html><body></body></html>")
    assert result.confidence == 0.0
    assert result.text == ""


def test_trafilatura_agreement_boosts_confidence():
    html = (
        "<html><body><article><h1>标题</h1>"
        + PARAGRAPH_CONTENT
        + "</article></body></html>"
    )
    result = ContentExtractor().extract(html)
    assert result.confidence >= 0.75
    assert "第1段正文" in result.text


def test_extract_lines_block_tags_break_lines():
    from bs4 import BeautifulSoup

    html = "<div>第一段<p>第二段</p>第三段<br>第四段<p>第五段</p></div>"
    lines = extract_lines(BeautifulSoup(html, "lxml").div)
    assert lines == ["第一段", "第二段", "第三段", "第四段", "第五段"]


def test_extract_lines_skips_script():
    from bs4 import BeautifulSoup

    html = "<div>正文<script>var a = 1;</script><p>段落</p></div>"
    lines = extract_lines(BeautifulSoup(html, "lxml").div)
    assert lines == ["正文", "段落"]


def test_density_returns_node_for_downstream():
    html = _page(PARAGRAPH_CONTENT)
    result = ContentExtractor().extract(html)
    if result.node_tag not in ("trafilatura", ""):
        assert result.node is not None
        assert result.node.name == result.node_tag


def test_explainable_candidates_recorded():
    # Guide task 21: every candidate carries positive reasons, penalties and
    # key features; agreement boosts the winner.
    html = (
        "<html><body><article><h1>标题</h1>"
        + PARAGRAPH_CONTENT
        + "</article></body></html>"
    )
    result = ContentExtractor().extract(html)
    ids = [c.candidate_id for c in result.candidates]
    assert "dom_density" in ids
    density = next(c for c in result.candidates if c.candidate_id == "dom_density")
    assert density.positive_reasons, "density candidate must explain itself"
    assert "连续段落数量较多" in density.positive_reasons
    assert "链接密度较低" in density.positive_reasons
    assert density.key_features["link_ratio"] < 0.2
    assert density.key_features["tag"] == "article"
    if len(result.candidates) > 1:
        tra = next(c for c in result.candidates if c.candidate_id == "trafilatura")
        assert tra.key_features.get("text_length", 0) > 0


def test_chapter_title_container_beats_dense_recommendation_block():
    chapter = "".join(
        f"<p>正文第{i}段，雨声落在窗外，人物继续讲述自己的经历。</p>"
        for i in range(1, 18)
    )
    recommendations = "".join(
        f"<section><h3><a href='/book/{i}'>热门作品{i}</a></h3>"
        f"<p>关于热门作品{i}的长篇推荐介绍，情节跌宕起伏，人物命运交错，"
        "欢迎收藏推荐并继续阅读后续内容。这段介绍故意写得比单段正文更长。</p></section>"
        for i in range(1, 8)
    )
    html = f"""
    <html><body>
      <h1>示例小说网</h1>
      <div class="chapter-shell">
        <h2>第3章（第1页）</h2>
        <div class="read-nav"><a href="prev">上一章</a><a href="next">下一章</a></div>
        {chapter}
      </div>
      <div class="recommendations"><h2>热门小说推荐</h2>{recommendations}</div>
    </body></html>
    """

    result = ContentExtractor().extract(html, fast=True)

    assert "正文第1段" in result.text
    assert "正文第17段" in result.text
    assert "热门作品1的长篇推荐介绍" not in result.text
    assert result.diagnostics["contains_chapter_title"] is True


def test_short_title_anchored_chapter_beats_outer_columns_and_long_trafilatura(monkeypatch):
    chapter = "".join(
        f"<p>短章第{i}段，人物回到旧居，发现熟悉的建筑已经消失。</p>"
        for i in range(1, 6)
    )
    rankings = "".join(
        f"<li><a href='/rank/{i}'>榜单作品{i}</a> 作者{i}</li>"
        for i in range(1, 80)
    )
    html = f"""
    <html><body><main class="page-layout">
      <div class="chapter-shell">
        <h2>第13章（第1页）</h2>
        {chapter}
      </div>
      <section><h2>月度榜单</h2><ul>{rankings}</ul></section>
      <section><h2>作品推荐</h2><ul>{rankings}</ul></section>
    </main></body></html>
    """
    monkeypatch.setattr(
        ContentExtractor,
        "_trafilatura_candidate",
        staticmethod(lambda _html: "页面外围栏目，" * 500),
    )

    result = ContentExtractor().extract(html)

    assert "短章第1段" in result.text
    assert "短章第5段" in result.text
    assert "榜单作品" not in result.text
    assert "页面外围栏目" not in result.text
    assert result.diagnostics["chapter_title_anchored"] is True

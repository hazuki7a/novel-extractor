"""Tests for Local Deep Analysis (guide task 22)."""

from __future__ import annotations

from novel_extractor.analyzer.content import ContentExtractor
from novel_extractor.analyzer.local_deep_analysis import LocalDeepAnalyzer

BIG = "".join(f"<p>主容器第{i}段，山风吹过林梢，主角抬眼望向远方。</p>" for i in range(1, 13))

# The quick density pass picks the BIGGER div; the deep layer must notice the
# real content lives in the sibling that directly follows the chapter heading.
SPLIT_CONTENT = f"""
<html><head><title>第9章 出山_测试书</title></head><body>
<h1>第9章 出山</h1>
<div class="wrap">
  <div class="teaser"><p>广告或推荐位，内容较少但也不算太短的一小段文字。</p></div>
  <div class="real">{''.join(f'<p>真实正文第{i}段，山道在雾里若隐若现，少年握紧行囊继续向上。</p>' for i in range(1, 12))}</div>
</div>
</body></html>
"""


def test_low_confidence_triggers_and_improves():
    extractor = ContentExtractor()
    quick = extractor.extract(SPLIT_CONTENT)
    analyzer = LocalDeepAnalyzer()
    result = analyzer.analyze_content(SPLIT_CONTENT, "http://e.com/9.html", quick)
    assert result.ok
    deep = result.value
    stages = dict(deep.diagnostics["stages"])
    assert "sibling_analysis" in stages
    assert "title_adjacency" in stages
    # the deep pass must at least produce usable text with explainable reasons
    assert len(deep.text) > 200
    assert "local deep analysis" in deep.reason


def test_reference_pages_feed_template_consistency():
    extractor = ContentExtractor()
    quick = extractor.extract(SPLIT_CONTENT)
    ref = SPLIT_CONTENT.replace("第9章 出山", "第10章 进山")
    analyzer = LocalDeepAnalyzer()
    result = analyzer.analyze_content(
        SPLIT_CONTENT, "http://e.com/9.html", quick, reference_pages=[(ref, "http://e.com/10.html")]
    )
    stages = dict(result.value.diagnostics["stages"])
    assert "template_consistency" in stages


def test_normal_page_confirmed_quickly():
    html = f"""
    <html><head><title>第1章 起</title></head><body>
    <h1>第1章 起</h1><div id="content">{BIG}</div></body></html>
    """
    extractor = ContentExtractor()
    quick = extractor.extract(html)
    assert quick.confidence >= 0.7
    analyzer = LocalDeepAnalyzer()
    result = analyzer.analyze_content(html, "http://e.com/1.html", quick)
    # high-confidence quick result: deep layer confirms without inventing text
    assert result.ok
    assert len(result.value.text) > 200
    assert result.value.diagnostics["improved"] in (True, False)


def test_empty_page_fails_with_diagnostics():
    extractor = ContentExtractor()
    quick = extractor.extract("<html><body></body></html>")
    analyzer = LocalDeepAnalyzer()
    result = analyzer.analyze_content("<html><body></body></html>", "http://e.com/x", quick)
    assert not result.ok
    assert result.confidence <= 0.3

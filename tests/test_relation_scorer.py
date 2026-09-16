"""Tests for multi-evidence chapter relation scoring (guide task 19)."""

from __future__ import annotations

from novel_extractor.analyzer.relation_scorer import (
    ChapterRelationScorer,
    RelationContext,
)
from novel_extractor.models import FetchedPage


def make_page(url: str, title: str, nav: str = "") -> FetchedPage:
    return FetchedPage(
        url=url, final_url=url, status_code=200, raw_bytes=b"", html=f"""
    <html><head><title>{title} 灵东传</title></head><body>
    <h1>{title}</h1>
    <div id="content">{''.join(f'<p>第{j}段，山风吹过林梢，主角抬眼望向远方。</p>' for j in range(1, 13))}</div>
    <div class="page-nav">{nav}</div>
    </body></html>
    """, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
    )


def test_reciprocal_navigation_scores_high():
    a = make_page(
        "http://e.com/b/5.html", "第5章 风云5",
        nav='<a href="/b/4.html">上一章</a><a href="/b/6.html">下一章</a>',
    )
    b = make_page(
        "http://e.com/b/6.html", "第6章 风云6",
        nav='<a href="/b/5.html">上一章</a><a href="/b/7.html">下一章</a>',
    )
    result = ChapterRelationScorer().score(a, "第5章 风云5", b, "第6章 风云6")
    assert result.value.score >= 0.8
    assert result.value.direction == "A_BEFORE_B"
    assert result.value.evidence["reciprocal"] is True
    assert "navigation_semantics" in result.reason


def test_prev_link_is_evidence_against():
    # A's previous points to B: B comes BEFORE A.
    a = make_page(
        "http://e.com/b/6.html", "第6章 风云6",
        nav='<a href="/b/5.html">上一章</a><a href="/b/7.html">下一章</a>',
    )
    b = make_page("http://e.com/b/5.html", "第5章 风云5")
    result = ChapterRelationScorer().score(a, "第6章 风云6", b, "第5章 风云5")
    assert result.value.direction == "B_BEFORE_A"
    assert result.value.evidence.get("a_prev_points_to_b") is True


def test_random_urls_without_navigation_stay_uncertain():
    a = make_page("http://e.com/x/zqk.html", "第5章 风云5")
    b = make_page("http://other.org/abc/def.html", "第6章 风云6")
    result = ChapterRelationScorer().score(a, "第5章 风云5", b, "第6章 风云6")
    # Only number continuity votes directionally (score 1.0), but with no
    # navigation/catalog evidence the confidence stays low.
    assert result.value.direction == "A_BEFORE_B"
    assert result.confidence < 0.5


def test_catalog_context_confirms_order():
    a = make_page("http://e.com/b/9a.html", "第5章 风云5")
    b = make_page("http://e.com/b/8f3.html", "第6章 风云6")
    context = RelationContext(
        catalog_position={
            "http://e.com/b/9a.html": 4,
            "http://e.com/b/8f3.html": 5,
        }
    )
    result = ChapterRelationScorer().score(a, "第5章 风云5", b, "第6章 风云6", context)
    assert result.value.evidence["catalog_positions"] == [4, 5]
    assert result.value.score >= 0.5


def test_number_decrease_is_a_penalty():
    a = make_page("http://e.com/b/6.html", "第6章 风云6")
    b = make_page("http://e.com/b/7.html", "第4章 风云4")
    result = ChapterRelationScorer().score(a, "第6章 风云6", b, "第4章 风云4")
    assert result.value.direction == "B_BEFORE_A"
    assert "number_continuity" in result.reason


def test_explainable_evidence_recorded():
    a = make_page(
        "http://e.com/b/5.html", "第5章 风云5",
        nav='<a href="/b/6.html">下一章</a>',
    )
    b = make_page("http://e.com/b/6.html", "第6章 风云6")
    result = ChapterRelationScorer().score(a, "第5章 风云5", b, "第6章 风云6")
    assert "fingerprint" in result.value.evidence
    assert "positives=" in result.reason

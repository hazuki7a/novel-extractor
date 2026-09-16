"""Tests for chapter content status detection (guide task 12)."""

from __future__ import annotations

from novel_extractor.analyzer.content_status import ContentStatusDetector
from novel_extractor.models import ContentExtraction, ContentStatus
from tests.test_catalog_pagination import make_page

LONG_PARAGRAPHS = "".join(
    "<p>这是正常的小说正文段落，主角在山中行走，远处钟声荡开，惊起飞鸟无数，雾气随之散去。</p>" * 20
)


def extract(text: str) -> ContentExtraction:
    return ContentExtraction(text=text, node_tag="div", confidence=0.85, reason="test")


def test_normal_long_chapter_is_content_ok():
    page = make_page("http://e.com/1.html", f"<html><body>{LONG_PARAGRAPHS}</body></html>")
    result = ContentStatusDetector().detect(page, extract("正文" * 400))
    assert result.value == ContentStatus.CONTENT_OK
    assert result.confidence >= 0.6


def test_http_404_is_not_found():
    page = make_page("http://e.com/1.html", "<html><body>not found</body></html>")
    page.status_code = 404
    result = ContentStatusDetector().detect(page, extract(""))
    assert result.value == ContentStatus.NOT_FOUND
    assert result.confidence >= 0.9


def test_http_403_with_cloudflare_marker_is_anti_bot():
    html = "<html><body>checking your browser before accessing</body></html>"
    page = make_page("http://e.com/1.html", html)
    page.status_code = 403
    result = ContentStatusDetector().detect(page, extract(""))
    assert result.value == ContentStatus.ANTI_BOT


def test_http_403_plain_is_access_restricted():
    page = make_page("http://e.com/1.html", "<html><body>denied</body></html>")
    page.status_code = 403
    result = ContentStatusDetector().detect(page, extract(""))
    assert result.value == ContentStatus.ACCESS_RESTRICTED


def test_login_required_phrase_in_short_content():
    html = "<html><body><div>请先登录后阅读本章节内容。</div><div class=nav><a href=/x>首页</a></div></body></html>"
    page = make_page("http://e.com/1.html", html)
    result = ContentStatusDetector().detect(page, extract("请先登录后阅读本章节内容。"))
    assert result.value == ContentStatus.LOGIN_REQUIRED


def test_paywall_phrase_in_short_content():
    html = "<html><body><div>本章节为VIP章节，订阅后阅读。</div></body></html>"
    page = make_page("http://e.com/1.html", html)
    result = ContentStatusDetector().detect(page, extract("本章节为VIP章节，订阅后阅读。"))
    assert result.value == ContentStatus.PAYWALL


def test_vip_phrase_ignored_when_content_is_long():
    # Recommendation sidebars often contain "VIP章节" on healthy chapters.
    html = (
        f"<html><body><div>{LONG_PARAGRAPHS}</div>"
        "<div class='sidebar'><a href=/vip>VIP章节推荐</a></div></body></html>"
    )
    page = make_page("http://e.com/1.html", html)
    result = ContentStatusDetector().detect(page, extract("正文" * 400))
    assert result.value == ContentStatus.CONTENT_OK


def test_empty_content_no_phrase():
    page = make_page("http://e.com/1.html", "<html><body><div></div></body></html>")
    result = ContentStatusDetector().detect(page, extract(""))
    assert result.value == ContentStatus.EMPTY_CONTENT
    assert result.confidence >= 0.8


def test_short_content_without_phrase_is_flagged():
    page = make_page("http://e.com/1.html", "<html><body><div>完</div></body></html>")
    result = ContentStatusDetector().detect(page, extract("完"))
    assert result.value == ContentStatus.EMPTY_CONTENT
    assert result.confidence < 0.8


def test_neighbor_median_comparison_flags_tiny_chapter():
    page = make_page("http://e.com/1.html", "<html><body><div>短短几行。</div></body></html>")
    result = ContentStatusDetector().detect(page, extract("短短几行。"), neighbor_median_length=2500)
    assert result.value == ContentStatus.EMPTY_CONTENT
    assert result.diagnostics.get("neighbor_median_length") == 2500


def test_neighbor_median_ignored_for_normal_chapters():
    page = make_page("http://e.com/1.html", f"<html><body>{LONG_PARAGRAPHS}</body></html>")
    result = ContentStatusDetector().detect(page, extract("正文" * 400), neighbor_median_length=2500)
    assert result.value == ContentStatus.CONTENT_OK


def test_anti_bot_phrase_on_200_page():
    html = "<html><body><div>请完成人机验证后继续访问。</div></body></html>"
    page = make_page("http://e.com/1.html", html)
    result = ContentStatusDetector().detect(page, extract("请完成人机验证后继续访问。"))
    assert result.value == ContentStatus.ANTI_BOT


def test_diagnostics_always_present():
    page = make_page("http://e.com/1.html", f"<html><body>{LONG_PARAGRAPHS}</body></html>")
    result = ContentStatusDetector().detect(page, extract("正文" * 400))
    assert "http_status" in result.diagnostics
    assert "content_length" in result.diagnostics

"""Tests for the Playwright fallback (guide task 26).

The browser binary itself is NOT downloaded on battery power; these tests
cover the escalation logic with a stubbed renderer and skip the real render
unless playwright is installed.
"""

from __future__ import annotations

import os

import pytest

from novel_extractor.fetcher.browser import DualFetcher, _looks_js_incomplete
from novel_extractor.fetcher.http import FetchedPage, HttpFetcher


def make_page(html: str, url: str = "http://e.com/x") -> FetchedPage:
    return FetchedPage(
        url=url, final_url=url, status_code=200, raw_bytes=html.encode(),
        html=html, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
    )


def test_js_incomplete_detection():
    assert _looks_js_incomplete(make_page("<html></html>"))  # tiny body
    assert _looks_js_incomplete(
        make_page('<html><body><div id="app"></div></body></html>' + "x" * 3000)
    )
    real = "<html><body>" + "<p>正文内容足够长，不是 JS 空壳页面。</p>" * 60 + "</body></html>"
    assert not _looks_js_incomplete(make_page(real))


def test_dual_fetcher_escalates_on_js_shell(monkeypatch):
    class StubPlaywright:
        def __init__(self):
            self.called = False

        def fetch(self, url: str, *, referer=None) -> FetchedPage:
            self.called = True
            return make_page(
                "<html><body><div id='content'>"
                + "<p>渲染后的完整正文，内容很多。</p>" * 30
                + "</div></body></html>"
            )

    shell = (
        '<html><body><div id="root"></div></body></html>'
    )
    import httpx

    response = httpx.Response(
        200, request=httpx.Request("GET", "http://e.com/x"),
        content=shell.encode(), headers={"content-type": "text/html"},
    )
    monkeypatch.setattr(
        HttpFetcher, "_get", lambda self, url, referer=None: response
    )
    dual = DualFetcher()
    stub = StubPlaywright()
    monkeypatch.setattr(dual, "_playwright", stub)
    monkeypatch.setattr(
        "novel_extractor.fetcher.browser.PlaywrightFetcher", lambda **kw: stub
    )
    page = dual.fetch("http://e.com/x")
    assert stub.called
    assert "渲染后的完整正文" in page.html
    assert page.diagnostics.get("http_fallback_reason") == "js-incomplete static response"


def test_dual_fetcher_keeps_static_when_renderer_missing(monkeypatch):
    import httpx

    response = httpx.Response(
        200, request=httpx.Request("GET", "http://e.com/x"),
        content=b'<html><body><div id="app"></div></body></html>',
        headers={"content-type": "text/html"},
    )
    monkeypatch.setattr(
        HttpFetcher, "_get", lambda self, url, referer=None: response
    )

    def boom(**kw):
        raise RuntimeError("playwright 未安装：请运行 pip install playwright")

    monkeypatch.setattr("novel_extractor.fetcher.browser.PlaywrightFetcher", boom)
    dual = DualFetcher()
    with pytest.raises(RuntimeError, match="playwright"):
        dual.fetch("http://e.com/x")


@pytest.mark.skipif(
    os.environ.get("NOVEL_EXTRACTOR_RUN_LIVE_TESTS") != "1",
    reason="live browser/network test is opt-in",
)
def test_real_render_skipped_without_playwright():
    pytest.importorskip("playwright")
    # Only reached when playwright is genuinely installed.
    fetcher = __import__("novel_extractor.fetcher.browser", fromlist=["PlaywrightFetcher"]).PlaywrightFetcher()
    page = fetcher.fetch("https://example.com")
    assert page.status_code == 200

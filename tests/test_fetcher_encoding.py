"""Tests for HTTP fetching and explicit encoding detection (guide task 2).

No test here touches the network: encoding logic is tested through pure
functions, HTTP behaviour through httpx.MockTransport.
"""

from __future__ import annotations

import httpx
import pytest

from novel_extractor.fetcher.http import (
    FetchError,
    HttpFetcher,
    decode_page_bytes,
    decide_encoding,
)

LONG_CHINESE = (
    "小说正文是一段比较长的中文文本，用来给统计式编码探测提供足够的证据。"
    "主角走进山门，看见石阶上落满黄叶，远处的钟声一圈一圈荡开。"
) * 6


class _NoSuggestion:
    def best(self):  # pragma: no cover - trivial stub
        return None


def test_bom_utf8_wins():
    raw = b"\xef\xbb\xbf" + "第一章 测试正文".encode("utf-8")
    html, decision = decode_page_bytes(raw)
    assert decision.source == "bom"
    assert decision.encoding == "utf-8-sig"
    assert decision.confidence >= 0.95
    assert "第一章 测试正文" in html


def test_bom_utf16_le():
    raw = b"\xff\xfe" + "正文内容".encode("utf-16-le")
    html, decision = decode_page_bytes(raw)
    assert decision.source == "bom"
    assert decision.encoding == "utf-16-le"
    assert "正文内容" in html


def test_http_header_gbk_decoded_as_gb18030():
    raw = f"<html><body><p>{LONG_CHINESE}</p></body></html>".encode("gbk")
    html, decision = decode_page_bytes(raw, http_charset="gbk")
    assert decision.source == "http_header"
    assert decision.encoding == "gb18030"  # superset of the declared gbk
    assert decision.diagnostics["declared_by_http_header"] == "gbk"
    assert LONG_CHINESE[:20] in html
    assert decision.confidence >= 0.85


def test_meta_charset_used_when_no_http_charset():
    raw = (
        '<html><head><meta charset="gbk"></head><body>'
        f"<p>{LONG_CHINESE}</p></body></html>"
    ).encode("gbk")
    html, decision = decode_page_bytes(raw)
    assert decision.source == "meta_charset"
    assert decision.encoding == "gb18030"
    assert decision.diagnostics["declared_by_meta"] == "gbk"
    assert LONG_CHINESE[:20] in html


def test_meta_http_equiv_used_when_no_http_charset():
    raw = (
        '<html><head><meta http-equiv="Content-Type" '
        'content="text/html; charset=gb2312"></head><body>'
        f"<p>{LONG_CHINESE}</p></body></html>"
    ).encode("gb2312", errors="ignore") or None
    assert raw  # gb2312 via gbk codec always encodes these chars
    html, decision = decode_page_bytes(raw)
    assert decision.source == "meta_http_equiv"
    assert decision.encoding == "gb18030"
    assert LONG_CHINESE[:20] in html


def test_http_header_wins_over_meta_and_conflict_recorded():
    # Declared UTF-8 over HTTP but meta says gbk; bytes really are UTF-8.
    raw = (
        '<html><head><meta charset="gbk"></head><body>'
        f"<p>{LONG_CHINESE}</p></body></html>"
    ).encode("utf-8")
    html, decision = decode_page_bytes(raw, http_charset="utf-8")
    assert decision.source == "http_header"
    assert decision.encoding == "utf-8"
    assert decision.diagnostics["conflict_http_vs_meta"] == ["utf-8", "gb18030"]
    assert decision.confidence < 0.90
    assert LONG_CHINESE[:20] in html


def test_charset_normalizer_fallback_detection():
    raw = f"<html><body><p>{LONG_CHINESE}</p></body></html>".encode("gb18030")
    html, decision = decode_page_bytes(raw)
    assert decision.source == "charset_normalizer"
    assert decision.encoding in ("gb18030", "gbk", "gb2312")
    assert LONG_CHINESE[:20] in html


def test_utf8_fallback_when_nothing_matches(monkeypatch):
    monkeypatch.setattr(
        "novel_extractor.fetcher.http.from_bytes", lambda raw: _NoSuggestion()
    )
    raw = b"<html><body>\xff\xfe\xfa broken \x81 bytes</body></html>"
    html, decision = decode_page_bytes(raw)
    assert decision.source == "utf8_fallback"
    assert decision.confidence <= 0.30
    assert "\ufffd" in html  # replaced, not silently dropped
    assert decision.diagnostics.get("replacement_char_ratio", 0) > 0


def test_http_header_beats_meta_when_both_valid():
    raw = (
        '<html><head><meta charset="gbk"></head><body>'
        f"<p>{LONG_CHINESE}</p></body></html>"
    ).encode("utf-8")
    decision = decide_encoding(raw, http_charset="utf-8")
    assert decision.source == "http_header"


def _make_fetcher(handler) -> HttpFetcher:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpFetcher(client=client)


def test_fetch_returns_fetched_page_with_decoding():
    raw = f"<html><body><p>{LONG_CHINESE}</p></body></html>".encode("gbk")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=gbk"},
            content=raw,
        )

    page = _make_fetcher(handler).fetch("http://example.com/book/1.html")
    assert page.url == "http://example.com/book/1.html"
    assert page.final_url == "http://example.com/book/1.html"
    assert page.status_code == 200
    assert page.encoding == "gb18030"
    assert page.encoding_source == "http_header"
    assert page.encoding_confidence >= 0.8
    assert LONG_CHINESE[:20] in page.html
    assert page.raw_bytes == raw
    assert "content-type" in page.headers


def test_fetch_records_charsetless_content_type():
    raw = f"<html><body><p>{LONG_CHINESE}</p></body></html>".encode("gb18030")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Type": "text/html"}, content=raw)

    page = _make_fetcher(handler).fetch("http://example.com/book/2.html")
    assert page.encoding_source == "charset_normalizer"
    assert LONG_CHINESE[:20] in page.html


def test_fetch_wraps_network_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(FetchError) as exc_info:
        _make_fetcher(handler).fetch("http://example.com/down.html")
    assert exc_info.value.url == "http://example.com/down.html"


def test_fetch_keeps_final_url_after_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/a":
            return httpx.Response(302, headers={"Location": "/b"})
        return httpx.Response(200, content="<html><body>ok</body></html>".encode())

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    page = HttpFetcher(client=client).fetch("http://example.com/a")
    assert page.final_url == "http://example.com/b"


def test_certificate_error_ladder(monkeypatch):
    """certifi fails -> OS trust store client is tried before giving up."""
    import httpx

    from novel_extractor.fetcher.http import HttpFetcher, _is_certificate_error

    assert _is_certificate_error(
        httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
    )
    assert not _is_certificate_error(httpx.ConnectError("connection refused"))

    class LadderTransport(httpx.BaseTransport):
        def __init__(self):
            self.calls = 0

        def handle_request(self, request):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError(
                    "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
                )
            return httpx.Response(200, content="<html><body>ok</body></html>".encode())

    transport = LadderTransport()
    fetcher = HttpFetcher(client=httpx.Client(transport=transport))
    # A custom client is injected, so the ladder is disabled and the
    # certificate error surfaces as FetchError.
    import pytest as _pytest

    from novel_extractor.fetcher.http import FetchError

    with _pytest.raises(FetchError):
        fetcher.fetch("https://example.com/x")

    # Without an injected client the ladder activates: first call fails on
    # the primary client, second succeeds via the system-trust retry.
    fetcher2 = HttpFetcher.__new__(HttpFetcher)
    fetcher2._timeout = 5.0
    fetcher2._headers = {"User-Agent": "test"}
    fetcher2._follow_redirects = True
    fetcher2._client = httpx.Client(transport=LadderTransport())
    fetcher2._injected_client = False
    # The direct-connection rung fails with a cert error too, exercising the
    # system-trust-store rung.
    fetcher2._direct_client = httpx.Client(transport=LadderTransport())
    fetcher2._system_client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content="<html><body>trusted</body></html>".encode())
    ))
    fetcher2._system_client_unavailable = False
    fetcher2._insecure_client = None
    page = fetcher2.fetch("https://example.com/x")
    assert "trusted" in page.html
    assert "tls_verification_skipped" not in page.diagnostics
    fetcher2.close()


def test_insecure_rung_is_recorded():
    import httpx

    from novel_extractor.fetcher.http import HttpFetcher

    def always_cert_error(request):
        raise httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"
        )

    def plain_ok(request):
        return httpx.Response(200, content="<html><body>insecure-ok</body></html>".encode())

    fetcher = HttpFetcher.__new__(HttpFetcher)
    fetcher._timeout = 5.0
    fetcher._headers = {"User-Agent": "test"}
    fetcher._follow_redirects = True
    fetcher._client = httpx.Client(transport=httpx.MockTransport(always_cert_error))
    fetcher._injected_client = False
    fetcher._direct_client = httpx.Client(transport=httpx.MockTransport(always_cert_error))
    fetcher._system_client_unavailable = True  # simulate truststore missing
    fetcher._system_client = None
    fetcher._insecure_client = httpx.Client(transport=httpx.MockTransport(plain_ok))
    page = fetcher.fetch("https://example.com/x")
    assert page.diagnostics.get("tls_verification_skipped") is True
    fetcher.close()

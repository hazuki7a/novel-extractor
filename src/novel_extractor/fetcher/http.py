"""HTTP fetcher with explicit character encoding detection.

The fetcher never trusts ``response.text``: it keeps the raw bytes and walks
the decision order required by the guide:

    BOM -> HTTP Content-Type charset -> <meta charset> ->
    <meta http-equiv=Content-Type> -> charset-normalizer -> UTF-8 fallback

GBK / GB2312 declarations are decoded with GB18030 (their superset).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

import httpx
from charset_normalizer import from_bytes

from novel_extractor.models import FetchedPage

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Declared label -> codec actually used for decoding. GB18030 is a superset of
# GBK/GB2312/CP936, so any of those declarations decode losslessly with it.
_CHARSET_ALIASES = {
    "gb2312": "gb18030",
    "gbk": "gb18030",
    "cp936": "gb18030",
    "gb_2312": "gb18030",
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "iso8859-1": "iso-8859-1",
    "latin1": "iso-8859-1",
    "windows-1252": "windows-1252",
    "cp1252": "windows-1252",
    "big5": "big5",
}

_META_CHARSET_RE = re.compile(
    rb"""<meta(?![^>]*http-equiv)[^>]*?charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""",
    re.IGNORECASE,
)
_META_HTTP_EQUIV_RE = re.compile(
    rb"""<meta[^>]+http-equiv\s*=\s*["']?content-type["']?[^>]*>""", re.IGNORECASE
)
_CONTENT_CHARSET_RE = re.compile(rb"""charset\s*=\s*["']?([a-zA-Z0-9_\-]+)""", re.IGNORECASE)
_HTTP_HEADER_CHARSET_RE = re.compile(r"""charset\s*=\s*"?([a-zA-Z0-9_\-]+)"?""", re.IGNORECASE)

# HTML5 says declarations live in the first 1024 bytes; be a bit lenient.
_META_SCAN_BYTES = 4096


class FetchError(Exception):
    """Raised when a page could not be fetched at all (network level)."""

    def __init__(self, url: str, cause: Exception | str):
        self.url = url
        self.cause = cause
        super().__init__(f"failed to fetch {url}: {cause}")


@dataclass
class EncodingDecision:
    encoding: str
    source: str  # bom | http_header | meta_charset | meta_http_equiv | charset_normalizer | utf8_fallback
    confidence: float
    diagnostics: dict[str, Any] = field(default_factory=dict)


def normalize_charset(label: str) -> Optional[str]:
    """Map a declared charset label to a real Python codec name."""
    key = label.strip().strip('"\'').lower()
    if key in _CHARSET_ALIASES:
        return _CHARSET_ALIASES[key]
    try:
        return codecs_lookup(key)
    except (LookupError, ValueError):
        return None


def codecs_lookup(name: str) -> str:
    import codecs

    codecs.lookup(name)
    return name


def _decode_label(raw_match: bytes) -> Optional[str]:
    try:
        label = raw_match.decode("ascii")
    except UnicodeDecodeError:
        return None
    return normalize_charset(label)


def _find_meta_charset(raw: bytes) -> tuple[Optional[str], Optional[str], bool]:
    """Return (codec, declared_label, is_http_equiv) from meta declarations."""
    head = raw[:_META_SCAN_BYTES]
    match = _META_CHARSET_RE.search(head)
    if match:
        codec = _decode_label(match.group(1))
        if codec:
            return codec, match.group(1).decode("ascii", "replace"), False
    for http_equiv in _META_HTTP_EQUIV_RE.finditer(head):
        inner = _CONTENT_CHARSET_RE.search(http_equiv.group(0))
        if inner:
            codec = _decode_label(inner.group(1))
            if codec:
                return codec, inner.group(1).decode("ascii", "replace"), True
    return None, None, False


def _bom_encoding(raw: bytes) -> Optional[str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe\x00\x00"):
        return "utf-32-le"
    if raw.startswith(b"\x00\x00\xfe\xff"):
        return "utf-32-be"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"
    return None


def _replacement_penalty(text: str) -> float:
    """Confidence penalty from U+FFFD replacement characters after decoding."""
    if not text:
        return 0.0
    ratio = text.count("\ufffd") / len(text)
    return min(0.6, ratio * 20.0)


def _finalize(decision: EncodingDecision, raw: bytes) -> tuple[str, EncodingDecision]:
    html = raw.decode(decision.encoding, errors="replace")
    penalty = _replacement_penalty(html)
    if penalty:
        decision.confidence = max(0.05, decision.confidence - penalty)
        decision.diagnostics["replacement_char_ratio"] = round(
            html.count("\ufffd") / max(1, len(html)), 6
        )
    return html, decision


def decide_encoding(raw: bytes, http_charset: Optional[str] = None) -> EncodingDecision:
    """Walk the encoding decision order and return the chosen codec.

    Meta declarations are always scanned for diagnostics, so an HTTP-vs-meta
    conflict is recorded even when the HTTP header wins.
    """
    diagnostics: dict[str, Any] = {}

    # 1. BOM
    bom_codec = _bom_encoding(raw)
    if bom_codec:
        diagnostics["bom"] = bom_codec
        return EncodingDecision(bom_codec, "bom", 0.99, diagnostics)

    # 2. HTTP Content-Type charset
    http_codec: Optional[str] = None
    if http_charset:
        http_codec = normalize_charset(http_charset)
        if http_codec:
            diagnostics["declared_by_http_header"] = http_charset
        else:
            diagnostics["unknown_declared_charset"] = http_charset

    # 3./4. HTML meta declarations (scanned for diagnostics regardless)
    meta_codec, meta_label, meta_is_http_equiv = _find_meta_charset(raw)
    if meta_label:
        diagnostics["declared_by_meta"] = meta_label
    conflict = bool(
        http_codec and meta_codec and http_codec != meta_codec
    )
    if conflict:
        diagnostics["conflict_http_vs_meta"] = [http_codec, meta_codec]

    if http_codec:
        confidence = 0.80 if conflict else 0.90
        return EncodingDecision(http_codec, "http_header", confidence, diagnostics)

    if meta_codec:
        source = "meta_http_equiv" if meta_is_http_equiv else "meta_charset"
        confidence = 0.80 if meta_is_http_equiv else 0.85
        return EncodingDecision(meta_codec, source, confidence, diagnostics)

    # 5. charset-normalizer statistical detection
    best = from_bytes(raw).best()
    if best is not None:
        codec = normalize_charset(best.encoding) or best.encoding
        diagnostics["normalizer_suggestion"] = best.encoding
        return EncodingDecision(codec, "charset_normalizer", 0.70, diagnostics)

    # 6. UTF-8 fallback
    return EncodingDecision("utf-8", "utf8_fallback", 0.30, diagnostics)


def decode_page_bytes(raw: bytes, http_charset: Optional[str] = None) -> tuple[str, EncodingDecision]:
    decision = decide_encoding(raw, http_charset)
    return _finalize(decision, raw)


class Fetcher(Protocol):
    """Anything that can turn a URL into a FetchedPage.

    referer is optional; expanders use it for same-page JSONP loaders.
    """

    def fetch(self, url: str, *, referer: Optional[str] = None) -> FetchedPage: ...


_CERT_ERROR_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "certificate verify failed",
    "self signed certificate",
    "SELF_SIGNED_CERT_IN_CHAIN",
    "unable to get local issuer certificate",
    "CERTIFICATE_VERIFY_FAILED]",
    # TLS handshake-level failures (flaky/old server TLS stacks): escalate to
    # the OS trust-store client, which negotiates via system TLS (Schannel/
    # Security.framework) and often succeeds where OpenSSL chokes.
    "eof occurred in violation of protocol",
    "ssl.c:",
    "wrong version number",
    "tlsv1 alert",
)


def _is_certificate_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _CERT_ERROR_MARKERS)


def _system_trust_client(timeout: float, headers: dict[str, str], follow_redirects: bool):
    """Client verifying against the OS trust store (Windows CryptoAPI /
    macOS Security / Linux trust path), which can complete chains that the
    static certifi bundle cannot (servers that omit intermediates)."""
    import ssl

    import truststore

    return httpx.Client(
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        trust_env=False,
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=headers,
    )


class HttpFetcher:
    """Default fetcher built on httpx.

    TLS ladder for sites with incomplete certificate chains (common on small
    novel hosts): certifi verification first, then the OS trust store via
    truststore, then - only if both fail - an unverified retry that is always
    recorded in page.diagnostics as ``tls_verification_skipped``.
    """

    def __init__(
        self,
        timeout: float = 20.0,
        headers: Optional[dict[str, str]] = None,
        client: Optional[httpx.Client] = None,
        follow_redirects: bool = True,
    ):
        self._timeout = timeout
        self._headers = {"User-Agent": DEFAULT_USER_AGENT, **(headers or {})}
        self._follow_redirects = follow_redirects
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers=self._headers,
        )
        self._injected_client = client is not None  # don't ladder custom clients
        self._direct_client: Optional[httpx.Client] = None
        self._system_client: Optional[httpx.Client] = None
        self._system_client_unavailable = False
        self._insecure_client: Optional[httpx.Client] = None

    def _get(self, url: str, referer: Optional[str]) -> httpx.Response:
        headers = {"Referer": referer} if referer else None
        cert_error: Optional[httpx.HTTPError] = None
        try:
            return self._client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            if self._injected_client or not _is_certificate_error(exc):
                raise
            cert_error = exc

        # Ladder 2: bypass the system/env proxy and connect directly (still
        # fully verified). Many TLS failures here are proxy-tunnel artifacts.
        if self._direct_client is None:
            self._direct_client = httpx.Client(
                trust_env=False,
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
                headers=self._headers,
            )
        try:
            return self._direct_client.get(url, headers=headers)
        except httpx.HTTPError as retry_exc:
            if not _is_certificate_error(retry_exc):
                raise retry_exc
            cert_error = retry_exc

        # Ladder 3: OS trust store (chain completion via system APIs).
        if self._system_client is None and not self._system_client_unavailable:
            try:
                self._system_client = _system_trust_client(
                    self._timeout, self._headers, self._follow_redirects
                )
            except ImportError:
                self._system_client_unavailable = True
        if self._system_client is not None:
            try:
                return self._system_client.get(url, headers=headers)
            except httpx.HTTPError as retry_exc:
                if not _is_certificate_error(retry_exc):
                    raise retry_exc
                cert_error = retry_exc

        # Ladder 4: unverified, recorded in diagnostics by fetch().
        if self._insecure_client is None:
            self._insecure_client = httpx.Client(
                verify=False,
                trust_env=False,
                timeout=self._timeout,
                follow_redirects=self._follow_redirects,
                headers=self._headers,
            )
        return self._insecure_client.get(url, headers=headers)

    def fetch(self, url: str, *, referer: Optional[str] = None) -> FetchedPage:
        tls_diagnostic: dict[str, Any] = {}
        try:
            response = self._get(url, referer)
        except httpx.HTTPError as exc:
            raise FetchError(url, exc) from exc
        if self._insecure_client is not None:
            # The ladder reached the unverified rung for at least one request.
            tls_diagnostic["tls_verification_skipped"] = True
            try:
                import warnings

                warnings.simplefilter("ignore")  # silence the verify=False warning
            except Exception:
                pass

        raw = response.content
        content_type = response.headers.get("content-type", "")
        header_match = _HTTP_HEADER_CHARSET_RE.search(content_type)
        http_charset = header_match.group(1) if header_match else None
        html, decision = decode_page_bytes(raw, http_charset)

        return FetchedPage(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            raw_bytes=raw,
            html=html,
            encoding=decision.encoding,
            encoding_source=decision.source,
            encoding_confidence=decision.confidence,
            headers=dict(response.headers),
            diagnostics={**decision.diagnostics, **tls_diagnostic},
        )

    def close(self) -> None:
        self._client.close()
        if self._direct_client is not None:
            self._direct_client.close()
        if self._system_client is not None:
            self._system_client.close()
        if self._insecure_client is not None:
            self._insecure_client.close()

    def __enter__(self) -> "HttpFetcher":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

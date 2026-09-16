"""Chapter content status detection.

Decides whether a fetched chapter page is really usable content
(CONTENT_OK) or a restricted/empty/failed page. Restricted pages must never
be silently exported as normal chapters (guide chapter_content_status).

The restriction vocabulary below is generic platform language
(订阅/登录/VIP/验证码...), not site specific rules. Phrases are only trusted
when the extracted content is short - long real chapters often contain
"VIP章节" etc. inside recommendation sidebars.
"""

from __future__ import annotations

from typing import Any, Optional

from bs4 import BeautifulSoup

from novel_extractor.models import ContentExtraction, ContentStatus, DetectionResult, FetchedPage

# Priority order when several phrase categories match.
_PHRASE_CATEGORIES: list[tuple[ContentStatus, float, tuple[str, ...]]] = [
    (
        ContentStatus.ANTI_BOT,
        0.80,
        (
            "请开启javascript", "请开启 javascript", "开启浏览器javascript",
            "人机验证", "安全验证", "验证码", "请完成验证",
            "cf-browser-verification", "challenge-platform", "checking your browser",
            "enable javascript and cookies",
        ),
    ),
    (
        ContentStatus.LOGIN_REQUIRED,
        0.80,
        (
            "请登录", "请先登录", "登录后阅读", "登录后查看", "登陆后阅读",
            "需要登录", "请登陆", "login to read", "sign in to read",
        ),
    ),
    (
        ContentStatus.PAYWALL,
        0.80,
        (
            "订阅后阅读", "订阅本章", "订阅后查看", "付费章节", "vip章节",
            "请购买本章", "解锁本章", "本章为付费", "充值后阅读", "购买后阅读",
            "subscribe to read", "premium chapter",
        ),
    ),
    (
        ContentStatus.ACCESS_RESTRICTED,
        0.75,
        (
            "权限不足", "无权访问", "禁止访问", "访问受限", "内容已被删除",
            "内容不存在", "已被删除", "该内容无法显示",
        ),
    ),
    (
        ContentStatus.NOT_FOUND,
        0.70,
        ("页面不存在", "网页不存在", "您访问的页面", "page not found", "404 not found"),
    ),
]

_PHRASE_SHORT_CONTENT_MAX = 500   # phrases only trusted below this length
_OK_CONTENT_MIN = 200
_SHORT_CONTENT_MAX = 200
_EMPTY_CONTENT_MAX = 0
_NEIGHBOR_SHORT_RATIO = 0.2
_NEIGHBOR_MIN_MEDIAN = 1000


class ContentStatusDetector:
    """Classify the content status of a fetched chapter page."""

    def detect(
        self,
        page: FetchedPage,
        content: ContentExtraction,
        neighbor_median_length: Optional[int] = None,
    ) -> DetectionResult[ContentStatus]:
        diagnostics: dict[str, Any] = {
            "http_status": page.status_code,
            "content_length": len(content.text.strip()),
        }

        # 1. HTTP level failures.
        http_verdict = self._from_http_status(page, diagnostics)
        if http_verdict is not None:
            status, confidence, reason = http_verdict
            return DetectionResult(status, confidence, reason, diagnostics)

        content_len = len(content.text.strip())
        page_text = self._page_text(page.html).lower()

        # 2. Restriction phrases, trusted only for short content.
        if content_len <= _PHRASE_SHORT_CONTENT_MAX:
            verdict = self._from_phrases(page_text, diagnostics)
            if verdict is not None:
                status, confidence, reason = verdict
                return DetectionResult(status, confidence, reason, diagnostics)

        # 3. Length heuristics.
        if content_len == _EMPTY_CONTENT_MAX:
            return DetectionResult(
                ContentStatus.EMPTY_CONTENT, 0.85,
                "extracted content is empty and no restriction phrase found",
                diagnostics,
            )
        if content_len < _SHORT_CONTENT_MAX:
            status, confidence, reason = ContentStatus.EMPTY_CONTENT, 0.60, (
                f"content suspiciously short ({content_len} chars) with no explicit restriction phrase"
            )
            if self._neighbor_says_restricted(content_len, neighbor_median_length, diagnostics):
                confidence = 0.70
                reason += "; much shorter than neighbor chapters"
            return DetectionResult(status, confidence, reason, diagnostics)

        # 4. Neighbor comparison for otherwise plausible content.
        if self._neighbor_says_restricted(content_len, neighbor_median_length, diagnostics):
            return DetectionResult(
                ContentStatus.EMPTY_CONTENT, 0.55,
                f"content only {content_len} chars vs neighbor median {neighbor_median_length}",
                diagnostics,
            )

        return DetectionResult(
            ContentStatus.CONTENT_OK,
            max(0.60, min(0.95, content.confidence)),
            f"content extracted normally ({content_len} chars)",
            diagnostics,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _page_text(html: str) -> str:
        try:
            return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
        except Exception:
            return html

    @staticmethod
    def _from_http_status(page: FetchedPage, diagnostics: dict[str, Any]):
        status_code = page.status_code
        if status_code in (404, 410):
            return ContentStatus.NOT_FOUND, 0.95, f"HTTP {status_code}"
        if status_code == 401:
            return ContentStatus.LOGIN_REQUIRED, 0.80, "HTTP 401 unauthorized"
        if status_code in (403, 429, 503):
            marker = ContentStatusDetector._anti_bot_marker(page, page.html.lower())
            diagnostics["anti_bot_marker"] = marker
            if marker:
                return ContentStatus.ANTI_BOT, 0.80, f"HTTP {status_code} with anti-bot marker '{marker}'"
            return ContentStatus.ACCESS_RESTRICTED, 0.70, f"HTTP {status_code} forbidden-ish"
        return None

    @staticmethod
    def _anti_bot_marker(page: FetchedPage, lowered_html: str) -> Optional[str]:
        server = page.headers.get("server", "").lower()
        if "cloudflare" in server and status_is_challenge(status_code := page.status_code):
            return f"server:{server}"
        for phrase in ("cf-browser-verification", "challenge-platform", "checking your browser", "jschl"):
            if phrase in lowered_html:
                return phrase
        return None

    @staticmethod
    def _from_phrases(page_text: str, diagnostics: dict[str, Any]):
        found: list[str] = []
        for status, confidence, phrases in _PHRASE_CATEGORIES:
            for phrase in phrases:
                if phrase in page_text:
                    found.append(f"{status.value}:{phrase}")
                    diagnostics["restriction_phrases"] = found
                    return status, confidence, f"restriction phrase '{phrase}' in short content"
        return None

    @staticmethod
    def _neighbor_says_restricted(
        content_len: int, neighbor_median_length: Optional[int], diagnostics: dict[str, Any]
    ) -> bool:
        if neighbor_median_length is None or neighbor_median_length < _NEIGHBOR_MIN_MEDIAN:
            return False
        restricted = content_len < _NEIGHBOR_SHORT_RATIO * neighbor_median_length
        if restricted:
            diagnostics["neighbor_median_length"] = neighbor_median_length
        return restricted


def status_is_challenge(status_code: int) -> bool:
    return status_code in (403, 429, 503)

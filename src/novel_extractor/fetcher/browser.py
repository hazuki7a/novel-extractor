"""PlaywrightFetcher (guide task 26 / V2).

Fallback fetcher for JS-rendered pages, plus a DualFetcher that tries plain
HTTP first and escalates only when the response looks JS-incomplete (tiny
body, empty content markers). Requires the optional ``playwright`` package
AND browser binaries (``playwright install chromium``); without them it
fails with a clear, actionable error instead of crashing obscurely.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from novel_extractor.fetcher.http import FetchedPage, HttpFetcher

_JS_INCOMPLETE_MARKERS = (
    "请开启javascript", "请开启 javascript", "enable javascript",
    "requires javascript", "id=\"app\"></div>", 'id="root"></div>',
)


def _looks_js_incomplete(page: FetchedPage) -> bool:
    if len(page.raw_bytes) < 3000:
        return True
    lowered = page.html.lower()
    return any(marker in lowered for marker in _JS_INCOMPLETE_MARKERS)


class PlaywrightFetcher:
    """Renders a page in headless Chromium and returns the resulting DOM."""

    def __init__(self, timeout: float = 30.0, headless: bool = True):
        self.timeout = timeout
        self.headless = headless

    def _render(self, url: str) -> tuple[str, str, int]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright 未安装：请运行 pip install playwright && playwright install chromium"
            ) from exc

        final_url = url
        status = 0
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            try:
                context = browser.new_context()
                page = context.new_page()
                response = page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass  # long-polling pages never settle; the DOM is ready
                html = page.content()
                final_url = page.url
                status = response.status if response else 0
                context.close()
            finally:
                browser.close()
        return html, final_url, status

    def fetch(self, url: str, *, referer: Optional[str] = None) -> FetchedPage:
        html, final_url, status = self._render(url)
        return FetchedPage(
            url=url,
            final_url=final_url,
            status_code=status or 200,
            raw_bytes=html.encode("utf-8"),
            html=html,
            encoding="utf-8",
            encoding_source="playwright",
            encoding_confidence=1.0,
            diagnostics={"rendered_by": "playwright"},
        )


class DualFetcher(HttpFetcher):
    """HTTP first; Playwright only when the static response looks broken."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._playwright: Optional[PlaywrightFetcher] = None

    def fetch(self, url: str, *, referer: Optional[str] = None) -> FetchedPage:
        page = super().fetch(url, referer=referer)
        if _looks_js_incomplete(page):
            if self._playwright is None:
                self._playwright = PlaywrightFetcher()
            try:
                rendered = self._playwright.fetch(url, referer=referer)
                rendered.diagnostics["http_fallback_reason"] = "js-incomplete static response"
                return rendered
            except RuntimeError:
                raise  # playwright missing: actionable error beats silent junk
            except Exception:
                return page  # renderer failed: keep the static response
        return page

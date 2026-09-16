"""Collapsed catalog list expansion.

Some sites render only the head and tail of the chapter list in the static
HTML and hide the middle behind a 展开完整列表 / load-more control powered by
inline JavaScript (frequently a JSONP loader). This module detects that
pattern generically and recovers the hidden segment:

1. find a marker anchor (展开/查看全部 style text, ``javascript:`` href,
   an ``onclick`` handler);
2. execute the page's own inline JS in a local QuickJS sandbox with a
   stubbed DOM to capture the data URL the loader builds - no browser, no
   network access from the sandbox. When quickjs is unavailable, fall back
   to a literal URL-template resolver (string concat + globals + standard
   base64) for simpler loaders;
3. fetch the data URL (Referer set to the page itself, standard HTTP
   behaviour), parse the JSONP/HTML response and return the chapter links
   that were hidden, plus their DOM insertion position.

Everything here is structural/textual - no host-specific logic. When the
pattern cannot be resolved the caller is told so it can warn about a
possible catalog gap instead of failing silently.
"""

from __future__ import annotations

import base64 as std_base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.fetcher.http import FetchError, FetchedPage
from novel_extractor.models import CatalogEntry, DetectionResult

_EXPAND_WORDS = (
    "展开完整列表", "展开列表", "展开全部", "展开所有章节", "查看完整列表",
    "查看全部", "查看所有章节", "显示全部", "展开",
)
_ONCLICK_RE = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*\(\s*['\"]?([^'\")]*)['\"]?\s*\)\s*;?\s*$")
_SCRIPT_RE = re.compile(r"<script[^>]*>(.*?)</script>", re.S | re.I)
_GLOBAL_VAR_RE = re.compile(r"var\s+([A-Za-z_$][\w$]*)\s*=\s*'([^']*)'")


class _JsUnavailable(Exception):
    pass


try:
    import quickjs  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    quickjs = None  # type: ignore


@dataclass
class CollapsedSegment:
    """A hidden catalog segment and where it belongs in the page order."""

    entries: list[CatalogEntry] = field(default_factory=list)
    after_href: Optional[str] = None  # last chapter anchor before the marker
    before_href: Optional[str] = None  # first chapter anchor after the marker
    reason: str = ""


class CollapsedListExpander:
    def __init__(self, chapter_detector: Optional[ChapterTitleDetector] = None):
        self._chapter = chapter_detector or ChapterTitleDetector()

    # -- public API ---------------------------------------------------------

    def has_marker(self, html: str) -> bool:
        return self._find_marker(html) is not None

    def expand(
        self,
        html: str,
        base_url: str,
        fetch: Callable[[str], FetchedPage],
    ) -> DetectionResult[CollapsedSegment]:
        """Try to expand the collapsed list. Low confidence / empty entries
        when anything fails - callers must treat that as "cannot expand",
        never as proof that the catalog is complete."""
        marker = self._find_marker(html)
        if marker is None:
            return DetectionResult(
                CollapsedSegment(), 0.0, "no collapsed-list marker found"
            )
        anchor, fn_name, arg = marker

        scripts = _SCRIPT_RE.findall(html)
        data_url: Optional[str] = None
        method = ""
        if quickjs is not None:
            data_url = self._resolve_via_js(scripts, fn_name, arg)
            method = "js_sandbox"
        if data_url is None:
            data_url = self._resolve_literal(scripts, fn_name, arg)
            method = method or "literal_template"
        if not data_url:
            return DetectionResult(
                CollapsedSegment(after_href=self._nearest_chapter_href(html, anchor, -1),
                                 before_href=self._nearest_chapter_href(html, anchor, +1)),
                0.2,
                f"collapsed marker found (onclick={fn_name}('{arg}')) but data URL could not be resolved "
                f"({'quickjs not installed' if quickjs is None else 'JS resolution failed'})",
            )

        absolute = urljoin(base_url, data_url)
        try:
            response = fetch(absolute)
        except FetchError as exc:
            return DetectionResult(
                CollapsedSegment(after_href=self._nearest_chapter_href(html, anchor, -1),
                                 before_href=self._nearest_chapter_href(html, anchor, +1)),
                0.2,
                f"data URL fetch failed ({exc})",
            )

        fragment = _extract_html_fragment(response.html)
        if not fragment:
            return DetectionResult(
                CollapsedSegment(after_href=self._nearest_chapter_href(html, anchor, -1),
                                 before_href=self._nearest_chapter_href(html, anchor, +1)),
                0.25,
                f"data URL responded without parseable HTML ({method})",
            )

        entries = self._parse_entries(fragment, base_url)
        if not entries:
            return DetectionResult(
                CollapsedSegment(after_href=self._nearest_chapter_href(html, anchor, -1),
                                 before_href=self._nearest_chapter_href(html, anchor, +1)),
                0.3,
                "expanded fragment contained no chapter links",
            )

        segment = CollapsedSegment(
            entries=entries,
            after_href=self._nearest_chapter_href(html, anchor, -1),
            before_href=self._nearest_chapter_href(html, anchor, +1),
            reason=f"{len(entries)} hidden entries via {method} ({fn_name}('{arg}'))",
        )
        confidence = 0.80 if method == "js_sandbox" else 0.70
        return DetectionResult(segment, confidence, segment.reason)

    # -- internals ----------------------------------------------------------

    def _find_marker(self, html: str) -> Optional[tuple[Tag, str, str]]:
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return None
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href.lower().startswith("javascript:"):
                continue
            text = a.get_text(strip=True)
            if not text or len(text) > 30:
                continue
            if not any(word in text for word in _EXPAND_WORDS):
                continue
            onclick = a.get("onclick") or ""
            parsed = _ONCLICK_RE.match(onclick)
            if parsed:
                return a, parsed.group(1), parsed.group(2)
        return None

    def _nearest_chapter_href(self, html: str, anchor: Tag, direction: int) -> Optional[str]:
        """Closest chapter-like anchor before (-1) / after (+1) the marker."""
        root = list(anchor.parents)[-1] if anchor.parents else None
        siblings = list(root.find_all("a")) if root is not None else []
        if not siblings:
            return None
        try:
            index = siblings.index(anchor)
        except ValueError:
            return None
        step = direction
        while 0 <= index + step < len(siblings):
            candidate = siblings[index + step]
            text = candidate.get_text(strip=True)
            if text and self._chapter.parse(text) is not None:
                return candidate.get("href")
            step += direction
        return None

    # -- JS sandbox ---------------------------------------------------------

    _JS_STUBS = (
        "var __captured = null;"
        "var document = {"
        "  getElementById: function(){ return { style: {}, innerHTML: '' }; },"
        "  getElementsByTagName: function(){ return { item: function(){ return {"
        "    appendChild: function(el){ __captured = el.src; } }; } }; },"
        "  createElement: function(){ return {}; },"
        "  body: {appendChild: function(){}}"
        "};"
    )

    def _resolve_via_js(self, scripts: list[str], fn_name: str, arg: str) -> Optional[str]:
        if quickjs is None:
            return None
        try:
            context = quickjs.Context()
            context.eval(self._JS_STUBS)
            for script in scripts:
                try:
                    context.eval(script)
                except Exception:
                    continue  # unrelated script errors are fine
            # Function must exist after loading the page scripts.
            if context.eval(f"typeof {fn_name}") != "function":
                return None
            context.eval(f"{fn_name}({json.dumps(arg)})")
            captured = context.eval("__captured")
            return captured if isinstance(captured, str) and captured else None
        except Exception:
            return None

    # -- literal fallback ---------------------------------------------------

    def _resolve_literal(self, scripts, fn_name: str, arg: str) -> Optional[str]:
        joined = scripts if isinstance(scripts, str) else "\n".join(scripts)
        body = self._function_body(joined, fn_name)
        if not body:
            return None
        param = self._function_param(body)
        globals_ = dict(_GLOBAL_VAR_RE.findall(joined))
        src_match = re.search(r"\.src\s*=\s*(.+?);", body, re.S)
        if not src_match:
            return None
        expression = src_match.group(1)
        parts = re.split(r"\+", expression)
        resolved: list[str] = []
        for raw in parts:
            piece = raw.strip()
            if not piece:
                continue
            if piece.startswith(("'", '"')) and piece.endswith(("'", '"')):
                resolved.append(piece[1:-1])
            elif piece == param:
                resolved.append(arg)
            elif piece in globals_:
                resolved.append(globals_[piece])
            elif re.fullmatch(r"base64\(\s*[\w$]+\s*\)", piece):
                inner = re.match(r"base64\(\s*([\w$]+)\s*\)", piece)
                value = arg if inner and inner.group(1) == param else globals_.get(inner.group(1), "")
                resolved.append(std_base64.b64encode(value.encode()).decode())
            elif piece == "base64(callback)" or piece.startswith("encodeURIComponent"):
                return None  # encoder we cannot evaluate without JS
            else:
                return None  # unknown token - do not guess
        url = "".join(resolved)
        return url if "?" in url or "/" in url else None

    @staticmethod
    def _function_body(scripts: str, fn_name: str) -> Optional[str]:
        match = re.search(
            r"function\s+" + re.escape(fn_name) + r"\s*\(", scripts
        )
        if not match:
            return None
        start = match.start()  # include the signature so the param is visible
        brace = scripts.index("{", match.end() - 1)
        depth = 0
        for i in range(brace, len(scripts)):
            if scripts[i] == "{":
                depth += 1
            elif scripts[i] == "}":
                depth -= 1
                if depth == 0:
                    return scripts[start : i + 1]
        return None

    @staticmethod
    def _function_param(body: str) -> str:
        match = re.match(r"function\s*[\w$]*\s*\(\s*([A-Za-z_$][\w$]*)", body)
        return match.group(1) if match else "__arg"

    # -- response parsing ---------------------------------------------------

    def _parse_entries(self, fragment: str, base_url: str) -> list[CatalogEntry]:
        from novel_extractor.analyzer.catalog import CatalogDetector

        catalog = CatalogDetector(self._chapter).detect(fragment, base_url=base_url)
        return catalog.chapters


class OnclickNavResolver:
    """Resolve anchors whose navigation lives in ``onclick="fn(id)"``.

    Some sites render chapter lists as ``<a onclick="read_tz(32752064)">``
    with no href at all; a page-level JS function builds the real URL from
    an id (string templates, .replace() chains, whatever) and navigates.
    This resolver executes the page's own inline JS in the local sandbox
    with a stubbed location/window that captures the target each call
    produces, so any URL-building shape works without being enumerated.

    Returns {arg: url}; empty when quickjs is unavailable or the page's
    scripts fail - callers must degrade gracefully.
    """

    _JS_STUBS = (
        "var __nav = null;"
        "var __location = {"
        "  set href(v){ __nav = v; },"
        "  get href(){ return ''; },"
        "  replace: function(u){ __nav = u; return __nav; },"
        "  assign: function(u){ __nav = u; return __nav; }"
        "};"
        "var location = __location;"
        "var window = { open: function(u, t){ __nav = u; }, location: __location };"
    )

    def resolve(self, html: str, fn_name: str, args: list[str]) -> dict[str, str]:
        if quickjs is None or not args:
            return {}
        try:
            context = quickjs.Context()
            context.eval(self._JS_STUBS)
            for script in _SCRIPT_RE.findall(html):
                try:
                    context.eval(script)
                except Exception:
                    continue
            if context.eval(f"typeof {fn_name}") != "function":
                return {}
            resolved: dict[str, str] = {}
            for arg in args:
                try:
                    context.eval("__nav = null;")
                    context.eval(f"{fn_name}({json.dumps(arg)})")
                    url = context.eval("__nav")
                    if isinstance(url, str) and url:
                        resolved[arg] = url
                except Exception:
                    continue
            return resolved
        except Exception:
            return {}


def _extract_html_fragment(text: str) -> Optional[str]:
    """Pull the HTML piece out of a JSONP envelope (or return raw HTML)."""
    text = text.strip()
    start = text.find("(")
    end = text.rfind(")")
    if start != -1 and end > start:
        candidate = text[start + 1 : end].strip().rstrip(";").strip()
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            data = None
        if isinstance(data, dict):
            best: Optional[str] = None
            best_links = 0
            for value in data.values():
                if isinstance(value, str) and "<a" in value.lower():
                    links = value.lower().count("<a")
                    if links > best_links:
                        best, best_links = value, links
            if best:
                return best
    if "<a" in text.lower():
        return text
    return None

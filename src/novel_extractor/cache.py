"""Inference Cache (guide task 20 / V1).

Automatic per-host profiles of *structural* features (title template,
content container tag signature, nav texts, chapter URL directory shape).
Built from a full inference, validated on every subsequent page before
being trusted, invalidated on mismatch and rebuilt after re-inference.

This is NOT a book-source file: nothing host-specific is stored, profiles
carry no CSS selectors or XPath, and every hit is re-verified against the
live page. The payoff is a fast extraction path (density-only, skipping the
expensive trafilatura baseline) while the profile holds.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from novel_extractor.analyzer.book_fingerprint import _content_signature
from novel_extractor.analyzer.content import ContentExtractor
from novel_extractor.models import DetectionResult, FetchedPage

CACHE_VERSION = 1


@dataclass
class SiteProfile:
    host: str
    generated_at: float
    version: int = CACHE_VERSION
    confidence: float = 0.0
    title_template: list[str] = field(default_factory=list)     # digit-free segments
    content_signature: list[list[Any]] = field(default_factory=list)  # [[tag, count], ...]
    nav_texts: list[str] = field(default_factory=list)
    chapter_dir: str = ""      # URL directory shape of chapter pages
    chapter_dirname_numeric: bool = False  # filename is (partly) numeric
    validation_stats: dict[str, int] = field(default_factory=lambda: {"hits": 0, "misses": 0, "invalidations": 0})


class InferenceCache:
    """Per-host profile store with light pre-extraction validation.

    ``cache_dir`` persistence is optional; an in-memory cache behaves the
    same within one crawl.
    """

    def __init__(self, cache_dir: Optional[Path | str] = None,
                 content_extractor: Optional[ContentExtractor] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._profiles: dict[str, SiteProfile] = {}
        self._content = content_extractor or ContentExtractor()

    # -- profile construction ----------------------------------------------

    def profile_from_page(self, html: str, url: str) -> SiteProfile:
        from novel_extractor.analyzer.book_fingerprint import _breadcrumb_chains
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        host = urlparse(url).netloc.lower()
        extraction = self._content.extract(html)
        signature = _content_signature(getattr(extraction, "node", None))

        title_tag = soup.find("title")
        title_template = []
        if title_tag:
            title_template = [
                s.strip() for s in re.split(r"[|｜_＿\-—·,，;；/\\]+", title_tag.get_text(strip=True)) if s.strip()
            ]

        nav_texts: list[str] = []
        for node in soup.find_all(["nav", "header", "footer"]):
            for a in node.find_all("a"):
                text = a.get_text(strip=True)
                if text:
                    nav_texts.append(text)

        parsed = urlparse(url)
        chapter_dir = parsed.path.rsplit("/", 1)[0] if "/" in parsed.path else ""
        filename = parsed.path.rsplit("/", 1)[-1]
        numeric = bool(re.search(r"\d", filename))

        return SiteProfile(
            host=host,
            generated_at=time.time(),
            confidence=extraction.confidence,
            title_template=title_template[:8],
            content_signature=[[tag, count] for tag, count in signature],
            nav_texts=nav_texts[:40],
            chapter_dir=chapter_dir,
            chapter_dirname_numeric=numeric,
        )

    # -- persistence ---------------------------------------------------------

    def get(self, host: str) -> Optional[SiteProfile]:
        if host in self._profiles:
            return self._profiles[host]
        if self.cache_dir is not None:
            path = self.cache_dir / f"{_safe_host(host)}.json"
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data.get("version") == CACHE_VERSION:
                        profile = SiteProfile(**data)
                        self._profiles[host] = profile
                        return profile
                    path.unlink()  # stale format: invalidate
                except (json.JSONDecodeError, TypeError, KeyError):
                    path.unlink(missing_ok=True)
        return None

    def put(self, profile: SiteProfile) -> None:
        self._profiles[profile.host] = profile
        if self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self.cache_dir / f"{_safe_host(profile.host)}.json"
            path.write_text(
                json.dumps(asdict(profile), ensure_ascii=False, indent=2),
                encoding="utf-8", newline="\n",
            )

    def invalidate(self, host: str) -> None:
        self._profiles.pop(host, None)
        if self.cache_dir is not None:
            path = self.cache_dir / f"{_safe_host(host)}.json"
            path.unlink(missing_ok=True)

    def hosts(self) -> list[str]:
        hosts = set(self._profiles)
        if self.cache_dir is not None and self.cache_dir.exists():
            for path in self.cache_dir.glob("*.json"):
                hosts.add(path.stem)
        return sorted(hosts)

    def clear(self, host: Optional[str] = None) -> None:
        if host:
            self.invalidate(host)
            return
        self._profiles.clear()
        if self.cache_dir is not None and self.cache_dir.exists():
            for path in self.cache_dir.glob("*.json"):
                path.unlink()

    # -- validation ------------------------------------------------------------

    def validate_light(self, url: str, html: str, profile: SiteProfile) -> DetectionResult[bool]:
        """Cheap pre-extraction check: title template + URL shape must still
        match the stored profile. Content-signature verification happens
        after extraction (see check_content_signature)."""
        checks = 0
        passed = 0

        soup_title = _page_title_text(html)
        if profile.title_template and soup_title:
            checks += 1
            page_segments = {
                s.strip() for s in re.split(r"[|｜_＿\-—·,，;；/\\]+", soup_title) if s.strip()
            }
            overlap = len(page_segments & set(profile.title_template))
            passed += 1 if overlap >= 1 else 0

        if profile.chapter_dir:
            checks += 1
            path = urlparse(url).path
            page_dir = path.rsplit("/", 1)[0] if "/" in path else ""
            passed += 1 if page_dir == profile.chapter_dir else 0

        if checks == 0:
            return DetectionResult(False, 0.3, "profile has no light-checkable features", {})

        ratio = passed / checks
        ok = ratio >= 0.5
        return DetectionResult(
            ok,
            round(ratio, 3),
            f"light validation {passed}/{checks} checks passed",
            {"checks": checks, "passed": passed},
        )

    def check_content_signature(self, profile: SiteProfile, node: Any) -> bool:
        """Post-extraction verification of the content container shape."""
        stored = {(tag, count) for tag, count in profile.content_signature}
        current = set(_content_signature(node))
        if not stored:
            return True
        common = len(stored & current)
        return common / len(stored) >= 0.5

    # -- validation stats ----------------------------------------------------

    def record(self, profile: SiteProfile, kind: str) -> None:
        if kind in profile.validation_stats:
            profile.validation_stats[kind] += 1


def _safe_host(host: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", host)


def _page_title_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        tag = BeautifulSoup(html, "lxml").find("title")
        return tag.get_text(strip=True) if tag else ""
    except Exception:
        return ""

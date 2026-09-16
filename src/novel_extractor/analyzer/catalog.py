"""Generic catalog detection.

Finds the chapter list of a page by clustering anchors whose text parses as
a chapter title, supported by URL similarity as auxiliary evidence.

The detector only reports candidates in original DOM order; it never decides
reading direction here (that is CatalogOrderDetector's job) and never relies
on class/id/站点专用 selector.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.analyzer.collapsed_list import OnclickNavResolver
from novel_extractor.models import CatalogDirection, CatalogEntry, CatalogResult

_STRONG_TITLE_CONFIDENCE = 0.85
_MIN_CLUSTER_SIZE = 5
_MAX_TITLE_LEN = 100
_MAX_MERGE_DISTANCE = 3  # ancestor levels considered when clustering


_ONCLICK_ARG_RE = re.compile(
    r"^\s*([A-Za-z_$][\w$]*)\s*\(\s*['\"]?(\d{1,12})['\"]?\s*\)\s*;?\s*$"
)


class CatalogDetector:
    def __init__(
        self,
        chapter_detector: Optional[ChapterTitleDetector] = None,
        onclick_resolver: Optional[OnclickNavResolver] = None,
    ):
        self._chapter = chapter_detector or ChapterTitleDetector()
        self._onclick_resolver = onclick_resolver

    def detect(self, html: str, base_url: str = "") -> CatalogResult:
        soup = BeautifulSoup(html, "lxml")
        self._augment_onclick_anchors(soup, html, base_url)
        items = self._collect_chapter_anchors(soup)
        if not items:
            return CatalogResult(
                direction=CatalogDirection.UNKNOWN,
                confidence=0.0,
                reason="no anchor text parses as a chapter title",
            )

        clusters = self._cluster_by_parent(items)
        if not clusters:
            return CatalogResult(
                direction=CatalogDirection.UNKNOWN,
                confidence=0.0,
                reason="chapter-like anchors exist but no DOM cluster found",
            )

        clusters.sort(key=lambda c: self._cluster_score(c), reverse=True)
        best = clusters[0]
        best_score = self._cluster_score(best)
        best_dir = self._dominant_dirname(best)

        # Volume-grouped catalogs split chapters across sibling lists; merge
        # neighbouring clusters that share the dominant URL directory.
        merged = list(best)
        for cluster in clusters[1:]:
            if self._cluster_score(cluster) < 0.20:
                continue
            # dirname equality includes the site-root case ("") so catalogs
            # built from bare relative links still merge their clusters.
            if self._dominant_dirname(cluster) == best_dir:
                merged.extend(cluster)

        merged.sort(key=lambda item: item[0])  # original DOM order
        size = len(merged)
        if size < _MIN_CLUSTER_SIZE:
            return CatalogResult(
                direction=CatalogDirection.UNKNOWN,
                confidence=min(0.3, best_score),
                reason=f"largest chapter-link cluster has only {size} anchors (< {_MIN_CLUSTER_SIZE})",
            )

        entries = [
            CatalogEntry(
                title=title,
                url=urljoin(base_url, href) if base_url else href,
                source_page_url=base_url,
                dom_index=dom_index,
            )
            for dom_index, title, href, _parent in merged
        ]
        strong_ratio = sum(
            1
            for _i, title, _href, _p in merged
            if (m := self._chapter.parse(title)) and m.confidence >= _STRONG_TITLE_CONFIDENCE
        ) / size
        confidence = min(0.95, best_score + 0.15 * strong_ratio)
        reason = (
            f"{size} chapter-like anchors clustered in DOM (strong_ratio={strong_ratio:.2f}, "
            f"url_dir={best_dir or 'n/a'})"
        )
        return CatalogResult(
            chapters=entries,
            direction=CatalogDirection.UNKNOWN,
            source_pages=[base_url] if base_url else [],
            confidence=round(confidence, 3),
            reason=reason,
        )

    # -- internals ----------------------------------------------------------

    def _augment_onclick_anchors(self, soup: BeautifulSoup, html: str, base_url: str) -> None:
        """Give href-less onclick="fn(id)" chapter anchors a real href.

        The page's own JS decides where each id navigates; the local sandbox
        executes it per id (any URL-building shape works). Without a resolver
        or quickjs the anchors stay href-less and are simply skipped, which
        is the pre-existing graceful degradation.
        """
        if self._onclick_resolver is None:
            return
        wanted: dict[str, list[tuple[Tag, str]]] = {}  # fn_name -> [(anchor, arg)]
        for a in soup.find_all("a"):
            if a.get("href"):
                continue
            onclick = a.get("onclick") or ""
            match = _ONCLICK_ARG_RE.match(onclick)
            if not match:
                continue
            text = a.get_text(strip=True)
            if not text or len(text) > _MAX_TITLE_LEN:
                continue
            if not (m := self._chapter.parse(text)) or m.confidence < _STRONG_TITLE_CONFIDENCE:
                continue
            wanted.setdefault(match.group(1), []).append((a, match.group(2)))
        if not wanted:
            return
        for fn_name, pairs in wanted.items():
            resolved = self._onclick_resolver.resolve(html, fn_name, [arg for _a, arg in pairs])
            for anchor, arg in pairs:
                url = resolved.get(arg)
                if url:
                    anchor["href"] = urljoin(base_url, url) if base_url else url

    def _collect_chapter_anchors(self, soup: BeautifulSoup):
        """[(dom_index, title, href, parent)] for anchors looking like chapters."""
        items = []
        for dom_index, a in enumerate(soup.find_all("a")):
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            title = a.get_text(strip=True)
            if not title or len(title) > _MAX_TITLE_LEN:
                continue
            match = self._chapter.parse(title)
            if match and match.confidence >= _STRONG_TITLE_CONFIDENCE:
                items.append((dom_index, title, href, a.parent))
        return items

    def _cluster_by_parent(self, items):
        """Group anchors per ancestor, merging sibling parents as one cluster.

        Uses the shallowest ancestor level that yields a cluster of at least
        _MIN_CLUSTER_SIZE anchors, so ``ul > li > a`` clusters at the ul while
        ``table > tr > td > a`` climbs to the table. Returns all clusters at
        the chosen level; volume lists stay separate until the URL-merge step.
        """
        for level in range(1, _MAX_MERGE_DISTANCE + 1):
            groups: dict[int, list] = {}
            roots: dict[int, Tag] = {}
            for item in items:
                ancestor = item[3]
                for _ in range(level - 1):
                    if ancestor is None or ancestor.parent is None:
                        break
                    ancestor = ancestor.parent
                if ancestor is None:
                    continue
                groups.setdefault(id(ancestor), []).append(item)
                roots[id(ancestor)] = ancestor
            # Sibling groups sharing the same grandparent belong together
            # (each <li> is its own parent inside one <ul>).
            merged_groups: dict[int, list] = {}
            for key, group in groups.items():
                grandparent = roots[key].parent
                gp_key = id(grandparent) if grandparent is not None else key
                merged_groups.setdefault(gp_key, []).extend(group)
            top = max(merged_groups.values(), key=len, default=[])
            if len(top) >= _MIN_CLUSTER_SIZE:
                return list(merged_groups.values())
        return [items]

    @staticmethod
    def _cluster_score(cluster) -> float:
        size = len(cluster)
        if size >= 30:
            score = 0.55
        elif size >= 15:
            score = 0.45
        elif size >= 8:
            score = 0.30
        elif size >= 5:
            score = 0.20
        else:
            score = 0.0
        dirname = CatalogDetector._dominant_dirname(cluster)
        if dirname:
            same = sum(
                1 for _i, _t, href, _p in cluster if CatalogDetector._dirname(href) == dirname
            )
            if size and same / size >= 0.8:
                score += 0.10
        return score

    @staticmethod
    def _dirname(href: str) -> str:
        try:
            parsed = urlparse(href)
            path = parsed.path or href
            if "/" not in path:
                return ""  # bare relative filename lives in the site root
            return path.rsplit("/", 1)[0]
        except ValueError:
            return ""

    @staticmethod
    def _dominant_dirname(cluster) -> str:
        dirnames = [CatalogDetector._dirname(href) for _i, _t, href, _p in cluster]
        if not dirnames:
            return ""
        dirname, _count = Counter(dirnames).most_common(1)[0]
        return dirname

"""Chapter navigation detection.

Identifies PREVIOUS_CHAPTER / NEXT_CHAPTER / CATALOG_LINK anchors on a page.
This detector must stay separate from the pagination detectors: "下一页" is a
pagination word and is deliberately NOT a chapter-hop keyword here.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from novel_extractor.analyzer.pagination import (
    _NEXT_CATALOG_WORDS,
    _PREV_CATALOG_WORDS,
    normalize_url,
    page_number_of,
)
from novel_extractor.models import DetectionResult, RelationType

_NEXT_CHAPTER_WORDS = (
    "下一章", "下一节", "下一回", "下一话", "next chapter", "next",
)
_PREV_CHAPTER_WORDS = (
    "上一章", "上一节", "上一回", "上一话", "previous chapter", "prev chapter",
    "prev", "previous",
)
_CATALOG_WORDS = (
    "目录", "返回目录", "章节目录", "全部章节", "章节列表", "查看目录",
    "contents", "table of contents",
)

# Words that mean "stay on this chapter" ("下一页", "next page", ...). They
# must never be treated as chapter hops even when they share a substring with
# the chapter vocabulary ("next" matches inside "next page").
_PAGINATION_WORDS = _NEXT_CATALOG_WORDS + _PREV_CATALOG_WORDS + ("下页", "上页")

_MIN_CONFIDENCE = 0.60
_MAX_TEXT_LEN = 30


class ChapterNavigationDetector:
    """Find previous-chapter / next-chapter / catalog links on a chapter page."""

    def detect(self, html: str, current_url: str) -> DetectionResult[dict]:
        """Returns DetectionResult with value dict:
        {previous_chapter, next_chapter, catalog_url, relations: [PageRelation-like dicts]}
        """
        soup = BeautifulSoup(html, "lxml")

        diagnostics: dict[str, Any] = {}
        next_pick = self._best(soup, current_url, _NEXT_CHAPTER_WORDS, RelationType.NEXT_CHAPTER, diagnostics)
        prev_pick = self._best(soup, current_url, _PREV_CHAPTER_WORDS, RelationType.PREVIOUS_CHAPTER, diagnostics)
        catalog_pick = self._best(soup, current_url, _CATALOG_WORDS, RelationType.CATALOG_LINK, diagnostics)

        values = {
            "previous_chapter": urljoin(current_url, prev_pick[1]) if prev_pick else None,
            "next_chapter": urljoin(current_url, next_pick[1]) if next_pick else None,
            "catalog_url": urljoin(current_url, catalog_pick[1]) if catalog_pick else None,
        }
        relations = []
        for pick, relation in (
            (prev_pick, RelationType.PREVIOUS_CHAPTER),
            (next_pick, RelationType.NEXT_CHAPTER),
            (catalog_pick, RelationType.CATALOG_LINK),
        ):
            if pick:
                relations.append(
                    {
                        "source_url": current_url,
                        "target_url": urljoin(current_url, pick[1]),
                        "relation_type": relation.value,
                        "confidence": pick[0],
                        "reason": pick[2],
                    }
                )
        values["relations"] = relations
        confidence = max(
            (pick[0] for pick in (prev_pick, next_pick, catalog_pick) if pick),
            default=0.0,
        )
        reasons = [pick[2] for pick in (prev_pick, next_pick, catalog_pick) if pick]
        reason = "; ".join(reasons) if reasons else "no chapter navigation anchors found"

        return DetectionResult(
            value=values,
            confidence=round(confidence, 3),
            reason=reason,
            diagnostics=diagnostics,
        )

    # -- internals ----------------------------------------------------------

    def _best(self, soup, current_url, words, relation, diagnostics):
        candidates = []
        rejected_pagination = 0
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href or href.startswith(("javascript:", "#", "mailto:")):
                continue
            text = a.get_text(strip=True)
            if not text or len(text) > _MAX_TEXT_LEN:
                continue
            lowered = text.lower()
            matched_word = next((w for w in words if w in lowered), None)
            if matched_word is None:
                continue
            # Longest-match ownership: "next page" matches the pagination
            # vocabulary more specifically than the chapter vocabulary, so it
            # is pagination; bare "next" stays a chapter hop.
            pag_match = max(
                (len(w) for w in _PAGINATION_WORDS if w in lowered), default=0
            )
            chap_match = max(
                (len(w) for w in words if w in lowered), default=0
            )
            if pag_match > chap_match:
                rejected_pagination += 1
                continue
            score, reasons = self._score(current_url, href, matched_word, relation)
            if score > 0:
                candidates.append((score, href, "; ".join(reasons)))

        if rejected_pagination:
            diagnostics[f"{relation.value}_skipped_pagination_words"] = rejected_pagination
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        score, href, reason = candidates[0]
        diagnostics[f"{relation.value}_candidates"] = len(candidates)
        return (round(score, 3), href, reason)

    @staticmethod
    def _score(current_url: str, href: str, word: str, relation) -> tuple[float, list[str]]:
        reasons = [f"anchor text '{word}' implies {relation.value}"]
        score = 0.62
        absolute = urljoin(current_url, href)
        if normalize_url(absolute) == normalize_url(current_url):
            return 0.0, ["target equals current page"]

        current_no = page_number_of(current_url)
        target_no = page_number_of(absolute)

        try:
            same_dir = (
                urlparse(current_url).path.rsplit("/", 1)[0]
                == urlparse(absolute).path.rsplit("/", 1)[0]
            )
        except ValueError:
            same_dir = False

        if same_dir:
            score += 0.10
            reasons.append("target stays in the same directory")
        # Chapter hops commonly leave the directory (volume paths, dated
        # paths); no penalty - keyword semantics carry the evidence.

        # A pagination-shaped URL (…_2.html / ?page=2) on a chapter-hop word
        # is suspicious: the anchor may be mislabelled pagination.
        if target_no is not None and current_no is not None:
            if relation is RelationType.NEXT_CHAPTER and target_no == current_no + 1:
                score += 0.15
                reasons.append(f"URL page number increments ({current_no}->{target_no})")
            elif relation is RelationType.PREVIOUS_CHAPTER and target_no == current_no - 1:
                score += 0.15
                reasons.append(f"URL page number decrements ({current_no}->{target_no})")
            else:
                score -= 0.10
                reasons.append("URL page numbers unrelated")
        elif target_no is not None and same_dir:
            score -= 0.10
            reasons.append("pagination-shaped URL in same directory (possible mislabelled pagination)")

        return max(0.0, min(0.95, score)), reasons

"""Multi-evidence chapter relation scoring (guide task 19 / V1).

Answers one directional question: is chapter A immediately before chapter
B? Evidence splits into two families:

- directional groups (explicit navigation, reciprocal links, catalog
  positions, number continuity) vote on the direction itself;
- non-directional groups (book fingerprint, title template, URL shape)
  only check whether both pages belong to the same book and therefore
  scale the confidence instead of voting.

Weights follow the guide's priority: navigation semantics and reciprocal
links highest, URL similarity only a low-weight auxiliary. Every group's
contribution is recorded so the score is explainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from novel_extractor.analyzer.book_fingerprint import BookFingerprinter, PageFingerprint
from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.analyzer.navigation import ChapterNavigationDetector
from novel_extractor.analyzer.pagination import normalize_url
from novel_extractor.models import DetectionResult, FetchedPage

# guide relationship_score_model weights (directional sum 0.8, same-book 0.2)
_W_NAVIGATION = 0.30
_W_RECIPROCAL = 0.20
_W_CATALOG = 0.15
_W_NUMBER = 0.15
_W_FINGERPRINT = 0.10
_W_TEMPLATE = 0.05
_W_URL = 0.05


@dataclass
class RelationContext:
    """Auxiliary evidence the caller may have (catalog order positions)."""

    catalog_position: Optional[dict[str, int]] = None  # normalized url -> index


@dataclass
class RelationScore:
    score: float                 # directional evidence strength in [0, 1]
    direction: str               # A_BEFORE_B | B_BEFORE_A | UNKNOWN
    evidence: dict[str, Any] = field(default_factory=dict)
    same_book: Optional[float] = None  # non-directional same-book check


class ChapterRelationScorer:
    def __init__(
        self,
        chapter_detector: Optional[ChapterTitleDetector] = None,
        navigation_detector: Optional[ChapterNavigationDetector] = None,
        fingerprinter: Optional[BookFingerprinter] = None,
    ):
        self._chapter = chapter_detector or ChapterTitleDetector()
        self._navigation = navigation_detector or ChapterNavigationDetector()
        self._fingerprinter = fingerprinter or BookFingerprinter()

    def score(
        self,
        page_a: FetchedPage,
        title_a: str,
        page_b: FetchedPage,
        title_b: str,
        context: Optional[RelationContext] = None,
    ) -> DetectionResult[RelationScore]:
        evidence: dict[str, Any] = {}
        directional: dict[str, tuple[float, Optional[float]]] = {}
        same_book_weights: dict[str, tuple[float, Optional[float]]] = {}

        url_a = normalize_url(page_a.final_url)
        url_b = normalize_url(page_b.final_url)
        token_a = self._token(title_a)
        token_b = self._token(title_b)

        # 1. Explicit navigation semantics on A (directional).
        nav_a = self._navigation.detect(page_a.html, page_a.final_url)
        next_a = nav_a.value.get("next_chapter")
        prev_a = nav_a.value.get("previous_chapter")
        if normalize_url(next_a or "") == url_b:
            directional["navigation_semantics"] = (_W_NAVIGATION, 1.0)
            evidence["a_next_points_to_b"] = True
        elif normalize_url(prev_a or "") == url_b:
            directional["navigation_semantics"] = (_W_NAVIGATION, 0.0)
            evidence["a_prev_points_to_b"] = True  # strong evidence AGAINST A->B
        else:
            directional["navigation_semantics"] = (_W_NAVIGATION, None)
            evidence["a_next_points_to_b"] = False

        # 2. Reciprocal link validation (A->B plus B back to A).
        nav_b = self._navigation.detect(page_b.html, page_b.final_url)
        prev_b = nav_b.value.get("previous_chapter")
        reciprocal = normalize_url(next_a or "") == url_b and normalize_url(prev_b or "") == url_a
        if reciprocal:
            directional["reciprocal_link"] = (_W_RECIPROCAL, 1.0)
            evidence["reciprocal"] = True
        else:
            directional["reciprocal_link"] = (_W_RECIPROCAL, None)
            evidence["reciprocal"] = False

        # 3. Catalog order positions (directional).
        if context and context.catalog_position:
            pos_a = context.catalog_position.get(url_a)
            pos_b = context.catalog_position.get(url_b)
            if pos_a is not None and pos_b is not None:
                directional["catalog_order"] = (_W_CATALOG, 1.0 if pos_a < pos_b else 0.0)
                evidence["catalog_positions"] = [pos_a, pos_b]
            else:
                directional["catalog_order"] = (_W_CATALOG, None)
        else:
            directional["catalog_order"] = (_W_CATALOG, None)

        # 4. Chapter number continuity (directional).
        if token_a is not None and token_b is not None:
            delta = token_b - token_a
            if 0 < delta <= 1:
                directional["number_continuity"] = (_W_NUMBER, 1.0)
            elif delta > 1:
                directional["number_continuity"] = (_W_NUMBER, 0.4)
                evidence["number_gap"] = delta
            elif delta == 0:
                directional["number_continuity"] = (_W_NUMBER, 0.1)
            else:
                directional["number_continuity"] = (_W_NUMBER, 0.0)
                evidence["number_gap"] = delta
        else:
            directional["number_continuity"] = (_W_NUMBER, None)

        # 5-7. Same-book checks (non-directional).
        fp_a: PageFingerprint = self._fingerprinter.fingerprint(page_a.html, page_a.final_url)
        fp_b: PageFingerprint = self._fingerprinter.fingerprint(page_b.html, page_b.final_url)
        compare = self._fingerprinter.compare(fp_a, fp_b)
        same_book_weights["book_fingerprint"] = (_W_FINGERPRINT, compare.value)
        evidence["fingerprint"] = {
            "similarity": compare.value,
            "verdict": compare.diagnostics.get("verdict"),
        }
        if fp_a.title_template and fp_b.title_template:
            inter = len(fp_a.title_template & fp_b.title_template)
            union = len(fp_a.title_template | fp_b.title_template)
            same_book_weights["title_template"] = (_W_TEMPLATE, inter / union if union else 0.0)
        else:
            same_book_weights["title_template"] = (_W_TEMPLATE, None)
        same_book_weights["url_similarity"] = (_W_URL, self._url_similarity(url_a, url_b))

        dir_available = sum(w for w, s in directional.values() if s is not None)
        dir_total = sum(w for w, _ in directional.values())
        if dir_available == 0:
            return DetectionResult(
                RelationScore(0.0, "UNKNOWN", evidence),
                0.0,
                "no directional evidence (explicit navigation, catalog positions or number continuity)",
                diagnostics={"weights": {**directional, **same_book_weights}},
            )
        dir_score = sum(w * s for w, s in directional.values() if s is not None) / dir_available
        dir_coverage = dir_available / dir_total
        direction = (
            "A_BEFORE_B" if dir_score >= 0.6
            else ("UNKNOWN" if dir_score >= 0.4 else "B_BEFORE_A")
        )

        same_available = sum(w for w, s in same_book_weights.values() if s is not None)
        same_book: Optional[float] = None
        if same_available:
            same_book = round(
                sum(w * s for w, s in same_book_weights.values() if s is not None) / same_available, 4
            )
        # Same-book checks cannot vote on direction; they scale confidence.
        same_factor = 0.5 if same_book is None else (0.6 + 0.4 * same_book)
        confidence = dir_score * (0.4 + 0.6 * dir_coverage) * same_factor

        positives = [k for k, (_w, s) in directional.items() if s is not None and s >= 0.7]
        penalties = [k for k, (_w, s) in directional.items() if s is not None and s <= 0.2]
        reason = (
            f"{direction}: positives={positives or 'none'}; penalties={penalties or 'none'}; "
            f"dir_coverage={dir_coverage:.2f}; same_book={same_book if same_book is not None else 'n/a'}"
        )
        return DetectionResult(
            RelationScore(round(dir_score, 4), direction, evidence, same_book),
            round(confidence, 4),
            reason,
            diagnostics={
                "weights": {**directional, **same_book_weights},
                "dir_coverage": round(dir_coverage, 3),
            },
        )

    # -- helpers ------------------------------------------------------------

    def _token(self, title: str) -> Optional[float]:
        match = self._chapter.parse(title)
        return match.order_token if match else None

    @staticmethod
    def _url_similarity(url_a: str, url_b: str) -> float:
        try:
            pa, pb = urlparse(url_a), urlparse(url_b)
        except ValueError:
            return 0.0
        dir_a = pa.path.rsplit("/", 1)[0]
        dir_b = pb.path.rsplit("/", 1)[0]
        same_dir = dir_a == dir_b
        num_a = re.findall(r"(\d+)", pa.path)
        num_b = re.findall(r"(\d+)", pb.path)
        if same_dir and num_a and num_b:
            try:
                delta = int(num_b[-1]) - int(num_a[-1])
            except ValueError:
                return 0.5
            if delta == 1:
                return 1.0
            return 0.5
        return 0.5 if same_dir else 0.0

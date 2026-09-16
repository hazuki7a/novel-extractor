"""Local Deep Analysis (guide task 22 / V1).

A purely local deep-analysis layer, triggered ONLY when the quick content
extraction came back with low confidence. It re-examines the page with
looser thresholds and structural cross-checks:

- candidate re-scan (smaller containers that quick scoring skipped);
- sibling node analysis (a sibling container competing for "content");
- chapter-title adjacency (content that follows the h1 is likely the body);
- cross-page template consistency (vs reference pages of the same book).

No cloud AI anywhere: everything is DOM/text heuristics with reasons.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import Tag

from novel_extractor.analyzer.book_fingerprint import BookFingerprinter
from novel_extractor.analyzer.content import (
    CANDIDATE_TAGS,
    _Features,
    _explain_density,
    _score,
    extract_lines,
)
from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.models import ContentExtraction, DetectionResult

_MIN_TEXT_LENGTH = 30
_MAX_DEEP_CANDIDATES = 8


@dataclass
class DeepStage:
    stage: str
    finding: str


class LocalDeepAnalyzer:
    def __init__(
        self,
        chapter_detector: Optional[ChapterTitleDetector] = None,
        fingerprinter: Optional[BookFingerprinter] = None,
    ):
        self._chapter = chapter_detector or ChapterTitleDetector()
        self._fingerprinter = fingerprinter or BookFingerprinter()

    def analyze_content(
        self,
        html: str,
        url: str,
        quick: ContentExtraction,
        reference_pages: Optional[list[tuple[str, str]]] = None,
    ) -> DetectionResult[ContentExtraction]:
        """reference_pages: [(html, url)] samples of sibling chapters from the
        same book, used for template-consistency evidence when provided."""
        stages: list[DeepStage] = []

        # Stage 1: candidate re-scan with looser thresholds.
        candidates = self._rescan_candidates(html)
        stages.append(DeepStage("candidate_rescan", f"{len(candidates)} containers rescanned"))
        if not candidates:
            quick.diagnostics["deep_analysis"] = {
                "triggered": True,
                "stages": [(s.stage, s.finding) for s in stages],
                "verdict": "no candidate at all",
            }
            return DetectionResult(
                quick, 0.2, "deep analysis: no content container found at any threshold",
                {"stages": [s.__dict__ for s in stages]},
            )

        candidates.sort(key=lambda c: c[0], reverse=True)
        best_score, best_node, best_features = candidates[0]

        # Stage 2: sibling competition for the leading candidate.
        sibling_penalty = False
        parent = best_node.parent if isinstance(best_node, Tag) else None
        if parent is not None:
            competing = 0
            for child in parent.find_all(["div", "section", "article"], recursive=False):
                if child is best_node:
                    continue
                text_len = len(child.get_text(strip=True))
                if text_len >= max(200, 0.5 * best_features.text_length):
                    competing += 1
            if competing:
                stages.append(DeepStage("sibling_analysis", f"{competing} sibling container(s) with comparable text"))
                sibling_penalty = True
            else:
                stages.append(DeepStage("sibling_analysis", "no competing sibling container"))

        # Stage 3: chapter-title adjacency.
        adjacency_bonus = False
        h1 = None
        for node in (best_node, *(best_node.parents if isinstance(best_node, Tag) else [])):
            if isinstance(node, Tag):
                h1 = node.find_previous("h1") or (node if node.name == "h1" else None)
                if h1:
                    break
        if h1 is not None:
            after = h1.find_all_next(["div", "article", "section", "p"])
            for node in after[:4]:
                if node is best_node or (isinstance(best_node, Tag) and node in best_node.descendants):
                    adjacency_bonus = True
                    stages.append(DeepStage("title_adjacency", "content directly follows the chapter heading"))
                    break
            if not adjacency_bonus:
                stages.append(DeepStage("title_adjacency", "content not adjacent to the chapter heading"))

        # Stage 4: cross-page template consistency.
        template_consistent: Optional[bool] = None
        if reference_pages:
            own_fp = self._fingerprinter.fingerprint(html, url)
            scores = []
            for ref_html, ref_url in reference_pages[:3]:
                ref_fp = self._fingerprinter.fingerprint(ref_html, ref_url)
                scores.append(self._fingerprinter.compare(own_fp, ref_fp).value)
            if scores:
                template_consistent = sum(scores) / len(scores) >= 0.6
                stages.append(
                    DeepStage("template_consistency", f"average cross-page similarity {sum(scores) / len(scores):.2f}")
                )

        # Verdict: build the extraction for the best candidate with bonuses.
        lines = extract_lines(best_node) if isinstance(best_node, Tag) else []
        text = "\n".join(lines)
        confidence = 0.35 + 0.5 * best_score
        positives, penalties, key_features = _explain_density(best_features, best_node.name.lower())
        if adjacency_bonus:
            confidence = min(0.95, confidence + 0.08)
        if sibling_penalty:
            confidence = max(0.3, confidence - 0.10)
            penalties.append("存在同层级竞争容器")
        if template_consistent is True:
            confidence = min(0.95, confidence + 0.05)
            positives.append("与同书章节模板一致")
        elif template_consistent is False:
            confidence = max(0.3, confidence - 0.05)
            penalties.append("与同书章节模板不一致")
        confidence = round(max(0.2, min(0.95, confidence)), 3)

        improved = confidence > quick.confidence
        winner = ContentExtraction(
            text=text,
            node_tag=best_node.name if isinstance(best_node, Tag) else "",
            confidence=confidence,
            reason="local deep analysis: " + "; ".join(f"{s.stage}: {s.finding}" for s in stages),
            diagnostics={
                "triggered": True,
                "stages": [(s.stage, s.finding) for s in stages],
                "quick_confidence": quick.confidence,
                "improved": improved,
            },
            node=best_node if isinstance(best_node, Tag) else None,
            candidates=quick.candidates,
        )
        return DetectionResult(
            winner,
            confidence,
            winner.reason,
            {"stages": [s.__dict__ for s in stages], "improved": improved},
        )

    def _rescan_candidates(self, html: str) -> list[tuple[float, Tag, _Features]]:
        """All container candidates above a looser text threshold."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        results: list[tuple[float, Tag, _Features]] = []
        for node in soup.find_all(CANDIDATE_TAGS):
            features = _Features(node)
            if features.text_length < _MIN_TEXT_LENGTH:
                continue
            score = _score(features, node.name.lower())
            if score <= 0.05:
                continue
            results.append((score, node, features))
            if len(results) > _MAX_DEEP_CANDIDATES * 4:
                break
        results.sort(key=lambda item: item[0], reverse=True)
        return results[:_MAX_DEEP_CANDIDATES]

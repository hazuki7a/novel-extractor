"""Main content extraction.

Two candidate sources, no site specific selectors:

1. Trafilatura baseline (plain text result).
2. A custom DOM text-density scorer over div/article/main/section nodes.

For the MVP the two candidates are compared simply: agreement boosts
confidence, disagreement is recorded in diagnostics. The full candidate
competition machinery is a V1 task (guide task 21).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

import trafilatura
from bs4 import NavigableString, Tag

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.models import ContentExtraction, ExtractionCandidate

CANDIDATE_TAGS = ["div", "article", "main", "section"]
_SKIP_TAGS = {"script", "style", "noscript", "template", "iframe", "svg", "head"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "ul", "ol", "table",
    "tr", "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6",
}

_PUNCT_RE = re.compile(r"[，。！？；：、（）《》“”‘’…—,.!?;:'\"()\[\]]")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# Feature weights for the density score. Deliberately simple and explainable.
_W_TEXT = 0.30
_W_PUNCT = 0.20
_W_PARA = 0.15
_W_LINK = 0.20
_W_CJK = 0.15

_MIN_TEXT_LENGTH = 50
_MAX_CANDIDATES = 400
_TITLE_CONTAINER_BONUS = 0.08
_TITLE_DETECTOR = ChapterTitleDetector()


def extract_lines(node: Tag) -> list[str]:
    """Text of a node as lines; <br> and block tags start a new line.

    Keeps <br>-separated novel paragraphs intact, unlike get_text().
    """
    lines: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        line = "".join(buf).strip()
        if line:
            lines.append(line)
        buf.clear()

    def visit(n: Any) -> None:
        if isinstance(n, NavigableString):
            buf.append(str(n))
            return
        if not isinstance(n, Tag):
            return
        name = n.name.lower() if n.name else ""
        if name in _SKIP_TAGS:
            return
        if name == "br":
            flush()
            return
        is_block = name in _BLOCK_TAGS
        if is_block:
            flush()
        for child in n.children:
            visit(child)
        if is_block:
            flush()

    visit(node)
    flush()
    return lines


class _Features:
    __slots__ = (
        "text_length", "punct_count", "link_text_length", "link_ratio",
        "paragraph_evidence", "child_count", "br_count", "chinese_ratio",
        "heading_count", "contains_chapter_title", "lines",
    )

    def __init__(self, node: Tag):
        self.lines = extract_lines(node)
        text = "\n".join(self.lines)
        self.text_length = len(text)
        self.punct_count = len(_PUNCT_RE.findall(text))
        cjk = len(_CJK_RE.findall(text))
        self.chinese_ratio = cjk / self.text_length if self.text_length else 0.0
        p_count = len(node.find_all("p"))
        self.br_count = len(node.find_all("br"))
        self.paragraph_evidence = p_count + self.br_count / 2.0
        self.link_text_length = 0
        for a in node.find_all("a"):
            self.link_text_length += len(a.get_text(strip=True))
        self.link_ratio = (
            self.link_text_length / self.text_length if self.text_length else 1.0
        )
        self.child_count = len(list(node.children))
        headings = node.find_all(("h1", "h2", "h3"))
        self.heading_count = len(headings)
        self.contains_chapter_title = False
        for heading in headings:
            match = _TITLE_DETECTOR.parse(heading.get_text(strip=True))
            if match is not None and match.confidence >= 0.85:
                self.contains_chapter_title = True
                break


def _explain_density(features, tag: str) -> tuple[list[str], list[str], dict[str, Any]]:
    """Explainable positives/penalties/key features (guide explainable_inference)."""
    positives: list[str] = []
    penalties: list[str] = []
    if features.text_length >= 500:
        positives.append("文本长度较高")
    elif features.text_length < 200:
        penalties.append("文本长度偏短")
    if features.paragraph_evidence >= 5:
        positives.append("连续段落数量较多")
    if features.link_ratio < 0.3:
        positives.append("链接密度较低")
    elif features.link_ratio > 0.5:
        penalties.append("链接密度过高")
    if features.chinese_ratio >= 0.5:
        positives.append("中文字符占比高")
    if features.punct_count >= 20:
        positives.append("中文标点密度较高")
    if tag in ("article", "main"):
        positives.append("语义容器标签 article/main")
    if features.contains_chapter_title:
        positives.append("容器包含高置信度章节标题")
    key_features = {
        "text_length": features.text_length,
        "punct_count": features.punct_count,
        "link_ratio": round(features.link_ratio, 3),
        "chinese_ratio": round(features.chinese_ratio, 3),
        "paragraph_evidence": round(features.paragraph_evidence, 1),
        "br_count": features.br_count,
        "heading_count": features.heading_count,
        "contains_chapter_title": features.contains_chapter_title,
        "tag": tag,
    }
    return positives, penalties, key_features


def _score(features: _Features, tag: str) -> float:
    if features.text_length == 0:
        return 0.0
    score = (
        _W_TEXT * min(1.0, features.text_length / 500.0)
        + _W_PUNCT * min(1.0, features.punct_count / 20.0)
        + _W_PARA * min(1.0, features.paragraph_evidence / 5.0)
        + _W_LINK * max(0.0, 1.0 - features.link_ratio * 2.0)
        + _W_CJK * features.chinese_ratio
    )
    if tag in ("article", "main"):
        score += 0.05
    # A dense recommendation block can look more prose-like than the actual
    # chapter.  Containing an explicit chapter heading is strong, generic DOM
    # evidence that the surrounding container owns the chapter paragraphs.
    if features.contains_chapter_title:
        score += _TITLE_CONTAINER_BONUS
    if features.link_ratio > 0.5:
        score -= 0.10
    return max(0.0, min(1.0, score))


class ContentExtractor:
    """Extract the main text of a chapter page."""

    def extract(self, html: str, fast: bool = False) -> ContentExtraction:
        """fast=True skips the expensive trafilatura baseline (inference-cache
        fast path); the caller must verify the result and fall back to the
        full extraction when it looks wrong."""
        density = self._density_candidate(html)
        trafilatura_text = None if fast else self._trafilatura_candidate(html)

        diagnostics: dict[str, Any] = {
            "trafilatura_len": len(trafilatura_text or ""),
            "density_len": len(density.text) if density else 0,
        }

        if density is None and trafilatura_text is None:
            return ContentExtraction(
                text="", node_tag="", confidence=0.0,
                reason="no content candidate found (empty or link-only page)",
                diagnostics=diagnostics,
            )

        if density is not None and trafilatura_text:
            agreement = self._agreement(density.text, trafilatura_text)
            diagnostics["agreement_ratio"] = round(agreement, 3)
            trafilatura_candidate = ExtractionCandidate(
                candidate_id="trafilatura",
                score=0.75,
                confidence=0.70,
                positive_reasons=["trafilatura baseline extract succeeded"],
                penalties=[],
                key_features={
                    "text_length": diagnostics["trafilatura_len"],
                    "agreement_ratio": round(agreement, 3),
                },
            )
            if agreement >= 0.7:
                density.confidence = min(0.99, density.confidence + 0.10)
                density.reason += f"; trafilatura agrees (ratio={agreement:.2f})"
                diagnostics["method"] = "density+trafilatura_agree"
            elif (
                not density.diagnostics.get("chapter_title_anchored", False)
                and diagnostics["trafilatura_len"] > max(300, 2 * diagnostics["density_len"])
            ):
                # The density node is clearly too small compared with what
                # trafilatura found; fall back to the trafilatura text.  A
                # structurally anchored chapter container is the exception:
                # short chapters are legitimately much smaller than the
                # surrounding rankings/recommendations that trafilatura may
                # collect from the whole page.
                trafilatura_candidate.positive_reasons.append(
                    "trafilatura candidate much longer than density candidate"
                )
                return ContentExtraction(
                    text=trafilatura_text,
                    node_tag="trafilatura",
                    confidence=0.70,
                    reason="trafilatura candidate much longer than density candidate",
                    diagnostics=diagnostics,
                    candidates=[
                        *(density.candidates or []),
                        trafilatura_candidate,
                    ],
                )
            else:
                diagnostics["method"] = "density"
            density.candidates.extend([*(density.candidates or []), trafilatura_candidate][len(density.candidates):])
            density.diagnostics.update(diagnostics)
            return density

        if density is not None:
            density.diagnostics.update(diagnostics)
            return density

        trafilatura_only = ExtractionCandidate(
            candidate_id="trafilatura",
            score=0.75,
            confidence=0.70,
            positive_reasons=["trafilatura baseline extract succeeded"],
            penalties=["no density candidate competed"],
            key_features={"text_length": diagnostics["trafilatura_len"]},
        )
        return ContentExtraction(
            text=trafilatura_text or "",
            node_tag="trafilatura",
            confidence=0.70,
            reason="trafilatura candidate (no density candidate)",
            diagnostics=diagnostics,
            candidates=[trafilatura_only],
        )

    @staticmethod
    def _agreement(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a[:5000], b[:5000]).ratio()

    @staticmethod
    def _trafilatura_candidate(html: str) -> Optional[str]:
        try:
            text = trafilatura.extract(html)
        except Exception:  # trafilatura occasionally chokes on odd HTML
            return None
        if text and text.strip():
            return text.strip()
        return None

    def _density_candidate(self, html: str) -> Optional[ContentExtraction]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        candidates: list[tuple[float, int, Tag, _Features]] = []
        nodes = soup.find_all(CANDIDATE_TAGS)
        for node in nodes:
            features = _Features(node)
            if features.text_length < _MIN_TEXT_LENGTH:
                continue
            score = _score(features, node.name.lower())
            if score <= 0.15:
                continue
            depth = 0
            parent = node
            while parent.parent is not None:
                depth += 1
                parent = parent.parent
            candidates.append((score, depth, node, features))
            if len(candidates) > _MAX_CANDIDATES * 2:
                break

        if not candidates:
            body = soup.body or soup
            features = _Features(body if isinstance(body, Tag) else soup)
            if features.text_length == 0:
                return None
            return ContentExtraction(
                text="\n".join(features.lines),
                node_tag="body",
                confidence=0.35,
                reason="no div/article/main/section candidate reached threshold; body fallback",
                diagnostics={"text_length": features.text_length},
                node=body,
            )

        # A chapter heading plus multiple prose paragraphs is a stronger
        # ownership signal than raw page-wide density. Prefer the deepest
        # qualifying title container, which excludes broader layout wrappers
        # that also contain rankings, recommendations or other columns.
        anchored = [
            item for item in candidates
            if item[3].contains_chapter_title
            and item[3].paragraph_evidence >= 2
            and item[3].punct_count >= 4
            and item[3].link_ratio <= 0.5
        ]
        chapter_title_anchored = bool(anchored)
        if anchored:
            best_score, best_depth, best_node, best_features = max(
                anchored,
                key=lambda item: (item[1], -item[3].heading_count, item[0]),
            )
        else:
            # Highest score wins; on a near tie prefer the deeper (more
            # specific) node.
            candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            best_score, best_depth, best_node, best_features = candidates[0]
            for score, depth, _node, _features in candidates[1:6]:
                if best_score - score <= 0.02 and depth > best_depth:
                    best_depth, best_node, best_features = depth, _node, _features

        confidence = 0.40 + 0.55 * best_score
        positives, penalties, key_features = _explain_density(best_features, best_node.name.lower())
        reason = (
            f"DOM density winner <{best_node.name}>: "
            f"text={best_features.text_length}, punct={best_features.punct_count}, "
            f"link_ratio={best_features.link_ratio:.2f}, "
            f"paragraphs={best_features.paragraph_evidence:.0f}"
        )
        candidate = ExtractionCandidate(
            candidate_id="dom_density",
            score=round(best_score, 3),
            confidence=round(confidence, 3),
            positive_reasons=positives,
            penalties=penalties,
            key_features=key_features,
        )
        return ContentExtraction(
            text="\n".join(best_features.lines),
            node_tag=best_node.name,
            confidence=round(confidence, 3),
            reason=reason,
            diagnostics={
                "text_length": best_features.text_length,
                "link_ratio": round(best_features.link_ratio, 3),
                "contains_chapter_title": best_features.contains_chapter_title,
                "chapter_title_anchored": chapter_title_anchored,
                "candidates_evaluated": len(candidates),
            },
            node=best_node,
            candidates=[candidate],
        )

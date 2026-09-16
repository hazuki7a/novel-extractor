"""Book Fingerprint (guide task 17 / V1).

Decides whether two pages belong to the same novel by comparing structural
and textual features, outputting a similarity plus reasons. No single field
is decisive, missing features are allowed (and discount confidence), and a
shared domain alone never means "same book".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import NavigableString, Tag

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.analyzer.content import ContentExtractor
from novel_extractor.analyzer.metadata import MetadataExtractor
from novel_extractor.models import DetectionResult

_TITLE_SPLIT_RE = re.compile(r"[|｜_＿\-—·,，;；/\\]+")


def normalize_text(text: str) -> str:
    """Comparable form of a name: no whitespace/punctuation, lowercase ASCII."""
    text = re.sub(r"[\s《》〈〉「」『』【】\[\]()（）·：:，,。.;；'\"’‘“”!！?？~～\-—_=+*&^%$#@]+", "", text)
    return text.lower()


def _digit_free(text: str) -> str:
    return re.sub(r"\d+", "#", text)


@dataclass
class PageFingerprint:
    book_title: Optional[str] = None
    author: Optional[str] = None
    title_template: frozenset[str] = frozenset()
    breadcrumb: tuple[str, ...] = ()
    headings: tuple[str, ...] = ()
    content_signature: tuple = ()
    nav_texts: frozenset[str] = frozenset()
    domain: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


def _breadcrumb_chains(soup) -> list[tuple[str, ...]]:
    """Generic breadcrumb detection: a container holding >=2 links whose
    combined text uses separator characters between them (书名 > 分类 > 站名)."""
    chains: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for container in soup.find_all(True):
        anchors = [c for c in container.children if isinstance(c, Tag) and c.name == "a"]
        if len(anchors) < 2:
            continue
        text = container.get_text(" ", strip=True)
        if not re.search(r"[>»›/\\|]", text):
            continue
        chain = tuple(normalize_text(a.get_text(strip=True)) for a in anchors)
        chain = tuple(t for t in chain if t)
        if len(chain) >= 2 and chain not in seen:
            seen.add(chain)
            chains.append(chain)
    return chains


def _content_signature(node: Optional[Tag]) -> tuple:
    if node is None:
        return ()
    counts = Counter(c.name for c in node.find_all(True) if c.name)
    return tuple(sorted(counts.items()))


def _signature_similarity(a: tuple, b: tuple) -> float:
    if not a or not b:
        return 0.0
    ca, cb = dict(a), dict(b)
    keys = set(ca) | set(cb)
    common = sum(min(ca.get(k, 0), cb.get(k, 0)) for k in keys)
    total = sum(max(ca.get(k, 0), cb.get(k, 0)) for k in keys)
    return common / total if total else 0.0


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class BookFingerprinter:
    def __init__(
        self,
        metadata_extractor: Optional[MetadataExtractor] = None,
        content_extractor: Optional[ContentExtractor] = None,
        chapter_detector: Optional[ChapterTitleDetector] = None,
    ):
        self._metadata = metadata_extractor or MetadataExtractor()
        self._content = content_extractor or ContentExtractor()
        self._chapter = chapter_detector or ChapterTitleDetector()

    def fingerprint(self, html: str, url: str = "") -> PageFingerprint:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        meta = self._metadata.extract(html)

        title_tag = soup.find("title")
        title_template = frozenset(
            _digit_free(seg.strip())
            for seg in _TITLE_SPLIT_RE.split(title_tag.get_text(strip=True))
            if seg.strip()
        ) if title_tag else frozenset()

        headings = tuple(
            _digit_free(h.get_text(strip=True))
            for h in soup.find_all(["h1", "h2", "h3"])[:6]
        )

        extraction = self._content.extract(html)
        content_signature = _content_signature(getattr(extraction, "node", None))

        nav_nodes = soup.find_all(["nav", "header", "footer"])
        nav_texts = frozenset(
            normalize_text(a.get_text(strip=True))
            for node in nav_nodes
            for a in node.find_all("a")
            if a.get_text(strip=True)
        )

        chains = _breadcrumb_chains(soup)
        breadcrumb = max(chains, key=len) if chains else ()

        domain = urlparse(url).netloc.lower() if url else ""

        return PageFingerprint(
            book_title=normalize_text(meta.book_title) if meta.book_title else None,
            author=normalize_text(meta.author) if meta.author else None,
            title_template=title_template,
            breadcrumb=breadcrumb,
            headings=tuple(_digit_free(h) for h in headings),
            content_signature=content_signature,
            nav_texts=nav_texts,
            domain=domain,
            diagnostics={
                "chains_found": len(chains),
                "content_confidence": extraction.confidence,
                "heading_count": len(headings),
            },
        )

    def compare(self, a: PageFingerprint, b: PageFingerprint) -> DetectionResult[float]:
        """Similarity in [0, 1] plus a reason trace.

        Each feature group carries a weight; groups missing on either side
        are dropped and the remaining weights renormalized, but thin evidence
        coverage discounts the final confidence so a single matching field
        can never assert "same book" on its own.
        """
        weights: dict[str, tuple[float, Optional[float]]] = {}

        title_present = bool(a.book_title and b.book_title)
        weights["book_title"] = (
            0.30,
            1.0 if a.book_title == b.book_title else 0.0,
        ) if title_present else (0.30, None)

        author_present = bool(a.author and b.author)
        weights["author"] = (0.15, 1.0 if a.author == b.author else 0.0) if author_present else (0.15, None)

        template_present = bool(a.title_template and b.title_template)
        weights["title_template"] = (
            0.15,
            _jaccard(a.title_template, b.title_template),
        ) if template_present else (0.15, None)

        breadcrumb_present = bool(a.breadcrumb and b.breadcrumb)
        if breadcrumb_present:
            set_a, set_b = set(a.breadcrumb), set(b.breadcrumb)
            overlap = len(set_a & set_b)
            title_in_breadcrumb = bool(
                (a.book_title and a.book_title in set_b)
                or (b.book_title and b.book_title in set_a)
            )
            score = max(
                overlap / max(len(set_a), len(set_b)),
                1.0 if title_in_breadcrumb else 0.0,
            )
            weights["breadcrumb"] = (0.15, min(1.0, score))
        else:
            weights["breadcrumb"] = (0.15, None)

        headings_present = bool(a.headings and b.headings)
        weights["headings"] = (
            0.10,
            _jaccard(frozenset(a.headings), frozenset(b.headings)),
        ) if headings_present else (0.10, None)

        content_present = bool(a.content_signature and b.content_signature)
        weights["content_structure"] = (
            0.10,
            _signature_similarity(a.content_signature, b.content_signature),
        ) if content_present else (0.10, None)

        nav_present = bool(a.nav_texts and b.nav_texts)
        weights["nav_structure"] = (
            0.10,
            _jaccard(a.nav_texts, b.nav_texts),
        ) if nav_present else (0.10, None)

        domain_present = bool(a.domain and b.domain)
        weights["domain"] = (0.05, 1.0 if a.domain == b.domain else 0.0) if domain_present else (0.05, None)

        available_weight = sum(w for w, score in weights.values() if score is not None)
        total_weight = sum(w for w, _ in weights.values())
        if available_weight == 0:
            return DetectionResult(
                0.0, 0.0, "no comparable features on either side",
                diagnostics={"weights": {k: w for k, (w, _) in weights.items()}},
            )

        raw_similarity = sum(
            w * score for w, score in weights.values() if score is not None
        ) / available_weight
        coverage = available_weight / total_weight
        adjusted = raw_similarity * (0.4 + 0.6 * coverage)
        confidence = adjusted

        matched = [k for k, (_w, s) in weights.items() if s is not None and s >= 0.7]
        partial = [k for k, (_w, s) in weights.items() if s is not None and 0.2 <= s < 0.7]
        absent = [k for k, (_w, s) in weights.items() if s is None]
        if adjusted >= 0.75:
            verdict = "same book"
        elif adjusted >= 0.45:
            verdict = "related / uncertain"
        else:
            verdict = "different"
        reason = (
            f"{verdict}; matched={matched or 'none'}; partial={partial or 'none'}; "
            f"missing={absent or 'none'}; coverage={coverage:.2f}"
        )
        return DetectionResult(
            round(raw_similarity, 4),
            round(confidence, 4),
            reason,
            diagnostics={"coverage": round(coverage, 3), "verdict": verdict},
        )

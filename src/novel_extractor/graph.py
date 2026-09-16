"""Novel Graph (guide task 18 / V1).

LogicalChapters - with in-chapter pages already merged - are the primary
nodes; chapter relations (NEXT_CHAPTER, PREVIOUS_CHAPTER, ...) are directed
edges. The graph supports cycle detection, duplicate node detection,
missing-number diagnostics and deriving a linear reading order from edges
when no catalog exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.models import LogicalChapter, RelationType
from novel_extractor.analyzer.pagination import normalize_url

_CHAIN_RELATIONS = (RelationType.NEXT_CHAPTER,)
# Relations that participate in directed cycle detection.
_DIRECTED_RELATIONS = (
    RelationType.NEXT_CHAPTER,
    RelationType.PREVIOUS_CHAPTER,
    RelationType.NEXT_CONTENT_PAGE,
    RelationType.PREVIOUS_CONTENT_PAGE,
)


@dataclass
class GraphEdge:
    source: str
    relation: RelationType
    target: str
    confidence: float = 1.0
    reason: str = ""


@dataclass
class GraphDiagnostics:
    duplicates: list[str] = field(default_factory=list)
    missing_main_numbers: list[int] = field(default_factory=list)
    cycle: Optional[list[str]] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    order_head: Optional[str] = None
    order_broken: bool = False


def missing_main_numbers(
    titles: Iterable[str], chapter_detector: ChapterTitleDetector
) -> list[int]:
    """Set-based missing main chapter numbers between min and max seen.

    Sub-numbered parts (第6章 1 / 第6章 2) all map to 6, so a fully absent
    main number is a precise missing-segment signal.
    """
    seen: set[int] = set()
    for title in titles:
        match = chapter_detector.parse(title)
        if match is None or match.order_token is None:
            continue
        main = int(match.order_token)
        if main >= 1:
            seen.add(main)
    if not seen:
        return []
    return [n for n in range(min(seen), max(seen) + 1) if n not in seen]


def compress_number_ranges(numbers: list[int]) -> str:
    if not numbers:
        return ""
    ranges: list[tuple[int, int]] = []
    for n in numbers:
        if ranges and n == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], n)
        else:
            ranges.append((n, n))
    return ", ".join(f"第{a}章" if a == b else f"第{a}~{b}章" for a, b in ranges)


class NovelGraph:
    def __init__(self, chapter_detector: Optional[ChapterTitleDetector] = None):
        self._chapter = chapter_detector or ChapterTitleDetector()
        self._chapters: dict[str, LogicalChapter] = {}
        self._edges: list[GraphEdge] = []
        self._out: dict[str, list[GraphEdge]] = {}
        self.duplicates: list[str] = []

    # -- construction -------------------------------------------------------

    def add_chapter(self, chapter: LogicalChapter) -> str:
        """Register a chapter; returns its node key (first source page).

        A chapter whose source pages overlap an existing node's is a
        duplicate: the existing node wins and the duplicate is recorded.
        """
        key = self._key_for(chapter)
        for existing_key, existing in self._chapters.items():
            overlap = set(existing.source_pages) & set(chapter.source_pages)
            if overlap or existing_key == key:
                self.duplicates.append(
                    f"{chapter.title} duplicates {existing.title} ({sorted(overlap)[:1] or 'same key'})"
                )
                return existing_key
        self._chapters[key] = chapter
        return key

    def add_edge(
        self,
        source: str,
        relation: RelationType,
        target: str,
        confidence: float = 1.0,
        reason: str = "",
    ) -> Optional[GraphEdge]:
        if source == target or source not in self._chapters or target not in self._chapters:
            return None
        edge = GraphEdge(source, relation, target, confidence, reason)
        self._edges.append(edge)
        self._out.setdefault(source, []).append(edge)
        return edge

    # -- queries ------------------------------------------------------------

    def chapters(self) -> dict[str, LogicalChapter]:
        return dict(self._chapters)

    def edges(self) -> list[GraphEdge]:
        return list(self._edges)

    def _key_for(self, chapter: LogicalChapter) -> str:
        if chapter.source_pages:
            return normalize_url(chapter.source_pages[0])
        return f"title:{chapter.title}"

    def next_edge_from(self, key: str) -> Optional[GraphEdge]:
        """The strongest NEXT_CHAPTER edge leaving a node."""
        candidates = [
            e for e in self._out.get(key, []) if e.relation is RelationType.NEXT_CHAPTER
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda e: e.confidence, reverse=True)
        return candidates[0]

    def has_cycle(self) -> Optional[list[str]]:
        """Directed cycle over chapter-hop edges, as a path (None if none)."""
        graph: dict[str, list[str]] = {}
        for edge in self._edges:
            if edge.relation in _DIRECTED_RELATIONS:
                graph.setdefault(edge.source, []).append(edge.target)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {key: WHITE for key in self._chapters}
        path: list[str] = []

        def dfs(node: str) -> Optional[list[str]]:
            color[node] = GRAY
            path.append(node)
            for nxt in graph.get(node, []):
                if nxt not in color:
                    continue
                if color.get(nxt) == GRAY:
                    idx = path.index(nxt)
                    return path[idx:] + [nxt]
                if color.get(nxt) == WHITE:
                    found = dfs(nxt)
                    if found:
                        return found
            path.pop()
            color[node] = BLACK
            return None

        for key in list(self._chapters):
            if color[key] == WHITE:
                found = dfs(key)
                if found:
                    return found
        return None

    def reading_order(self) -> tuple[list[str], bool]:
        """Linear order following NEXT_CHAPTER edges from the head.

        Head = the node with no incoming NEXT edge. Returns (order, broken);
        broken means the chain ended early (cycle or missing link) and the
        order only covers part of the graph.
        """
        incoming: set[str] = set()
        for edge in self._edges:
            if edge.relation is RelationType.NEXT_CHAPTER:
                incoming.add(edge.target)
        heads = [key for key in self._chapters if key not in incoming]
        if not heads:
            heads = [next(iter(self._chapters), None)]
        order: list[str] = []
        broken = False
        visited: set[str] = set()
        for head in heads:
            current: Optional[str] = head
            while current is not None and current not in visited:
                visited.add(current)
                order.append(current)
                edge = self.next_edge_from(current)
                nxt = edge.target if edge else None
                if nxt is not None and nxt in visited:
                    broken = True  # would loop; the cycle is reported separately
                    break
                current = nxt
        # Nodes the chain never reached (no NEXT edges connect them).
        for key in self._chapters:
            if key not in visited:
                order.append(key)
                broken = True
        if len(heads) > 1:
            # Multiple chains: the edges never established a single order.
            broken = True
        return order, broken

    # -- diagnostics --------------------------------------------------------

    def diagnostics(self) -> GraphDiagnostics:
        diag = GraphDiagnostics()
        diag.duplicates = list(self.duplicates)
        diag.missing_main_numbers = missing_main_numbers(
            (c.title for c in self._chapters.values()), self._chapter
        )
        diag.cycle = self.has_cycle()
        incoming_next: set[str] = set()
        outgoing_next: set[str] = set()
        for edge in self._edges:
            if edge.relation is RelationType.NEXT_CHAPTER:
                incoming_next.add(edge.target)
                outgoing_next.add(edge.source)
        diag.orphans = sorted(
            key
            for key in self._chapters
            if key not in incoming_next and key not in outgoing_next
        )
        order, broken = self.reading_order()
        diag.order_head = order[0] if order else None
        diag.order_broken = broken
        return diag

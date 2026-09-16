"""Tests for the Novel Graph (guide task 18)."""

from __future__ import annotations

from novel_extractor.graph import (
    GraphDiagnostics,
    NovelGraph,
    missing_main_numbers,
)
from novel_extractor.models import ContentStatus, LogicalChapter, RelationType
from novel_extractor.analyzer.chapter import ChapterTitleDetector


def chapter(index, title, source="http://e.com/x.html"):
    return LogicalChapter(
        index=index, title=title, source_pages=[f"{source}"],
        content="　　正文。", content_status=ContentStatus.CONTENT_OK, confidence=0.9,
    )


def build_chain(graph: NovelGraph, titles_ids):
    prev_key = None
    keys = []
    for title, sid in titles_ids:
        key = graph.add_chapter(chapter(0, title, f"http://e.com/{sid}.html"))
        keys.append(key)
        if prev_key is not None:
            graph.add_edge(prev_key, RelationType.NEXT_CHAPTER, key)
        prev_key = key
    return keys


def test_reading_order_follows_next_edges():
    graph = NovelGraph()
    keys = build_chain(graph, [("第1章", 1), ("第2章", 2), ("第3章", 3)])
    order, broken = graph.reading_order()
    assert order == keys
    assert not broken


def test_cycle_detection():
    graph = NovelGraph()
    keys = build_chain(graph, [("第1章", 1), ("第2章", 2)])
    graph.add_edge(keys[1], RelationType.NEXT_CHAPTER, keys[0])  # close the loop
    cycle = graph.has_cycle()
    assert cycle is not None
    assert set(cycle) == set(keys)


def test_duplicate_source_pages_detected():
    graph = NovelGraph()
    graph.add_chapter(chapter(1, "第1章", "http://e.com/1.html"))
    graph.add_chapter(chapter(2, "第1章(2/3)", "http://e.com/1.html"))
    assert len(graph.duplicates) == 1
    assert len(graph.chapters()) == 1  # existing node wins


def test_missing_main_numbers():
    det = ChapterTitleDetector()
    titles = [f"第{i}章 名{i}" for i in (1, 2, 5, 6)]
    assert missing_main_numbers(titles, det) == [3, 4]
    # sub-numbered parts all map to their main number
    titles_sub = ["第6章 1", "第6章 2", "第8章 1"]
    assert missing_main_numbers(titles_sub, det) == [7]


def test_diagnostics_reports_orphans_and_missing():
    graph = NovelGraph()
    keys = build_chain(graph, [("第1章", 1), ("第2章", 2), ("第5章", 5)])
    orphan_key = graph.add_chapter(chapter(4, "番外", "http://e.com/9.html"))
    diag = graph.diagnostics()
    assert diag.missing_main_numbers == [3, 4]
    assert orphan_key in diag.orphans
    assert diag.cycle is None
    assert diag.order_head == keys[0]
    # the orphan means no single NEXT-chain covers every node
    assert diag.order_broken


def test_broken_chain_flagged():
    graph = NovelGraph()
    k1 = graph.add_chapter(chapter(1, "第1章", "http://e.com/1.html"))
    k2 = graph.add_chapter(chapter(2, "第2章", "http://e.com/2.html"))
    # no edges at all: every node is an orphan, chain incomplete
    order, broken = graph.reading_order()
    assert set(order) == {k1, k2}
    assert broken


def test_compressed_ranges():
    from novel_extractor.graph import compress_number_ranges

    assert compress_number_ranges([3]) == "第3章"
    assert compress_number_ranges([3, 4, 5, 9]) == "第3~5章, 第9章"

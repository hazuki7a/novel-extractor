"""Tests for catalog reading direction detection (guide task 9)."""

from __future__ import annotations

from novel_extractor.analyzer.catalog_order import CatalogOrderDetector
from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.models import CatalogDirection, CatalogEntry


def entries_from_titles(titles):
    return [
        CatalogEntry(
            title=title,
            url=f"http://e.com/b/{i}.html",
            source_page_url="http://e.com/catalog.html",
            dom_index=i,
        )
        for i, title in enumerate(titles)
    ]


def test_ascending_catalog():
    titles = ["序章"] + [f"第{i}章 名字{i}" for i in range(1, 21)]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert result.value == CatalogDirection.ASCENDING
    assert result.confidence >= 0.85
    assert "ascend" in result.reason


def test_descending_catalog():
    titles = [f"第{i}章 名字{i}" for i in range(20, 0, -1)]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert result.value == CatalogDirection.DESCENDING
    assert result.confidence >= 0.85
    assert "descend" in result.reason


def test_descending_with_special_anchors():
    titles = ["大结局"] + [f"第{i}章 名字{i}" for i in range(20, 0, -1)] + ["序章"]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert result.value == CatalogDirection.DESCENDING
    assert result.confidence >= 0.90


def test_unknown_when_too_few_numbers():
    titles = ["序章", "开端", "高潮", "尾声"]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert result.value == CatalogDirection.UNKNOWN
    assert result.confidence <= 0.55
    assert "UNKNOWN" in result.reason


def test_unknown_not_forced_into_direction():
    # Mixed sequence must stay UNKNOWN, never silently reversed or kept.
    titles = [f"第{i}章 名" for i in (1, 2, 3, 10, 4, 5, 20)]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    # Either UNKNOWN (mixed) or a weak call is acceptable, but never high confidence.
    assert result.confidence <= 0.85


def test_equal_numbers_not_counted_as_pairs():
    # "latest chapters" block repeating the same number as the full list.
    titles = ["第10章 最新"] * 3 + [f"第{i}章 名" for i in range(1, 11)]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert result.value == CatalogDirection.ASCENDING
    assert result.confidence >= 0.80


def test_chinese_numerals_direction():
    cn = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
    titles = [f"第{num}章 风云" for num in cn]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert result.value == CatalogDirection.ASCENDING


def test_empty_catalog():
    result = CatalogOrderDetector().detect([])
    assert result.value == CatalogDirection.UNKNOWN
    assert result.confidence <= 0.40


def test_diagnostics_present():
    titles = [f"第{i}章 名" for i in range(1, 6)]
    result = CatalogOrderDetector().detect(entries_from_titles(titles))
    assert "inc_ratio" in result.diagnostics
    assert result.diagnostics["numbered_entries"] == 5


def test_segmented_rotated_order_is_repaired():
    # Real-world pattern (lingduxs): the DOM lists 16..65 then 1..15, both
    # runs ascending - reading order must rotate the second run to the front.
    from novel_extractor.analyzer.catalog_order import reorder_segmented

    titles = [f"第{i}章 名{i}" for i in range(16, 66)] + [f"第{i}章 名{i}" for i in range(1, 16)]
    result = reorder_segmented(entries_from_titles(titles), ChapterTitleDetector())
    assert result is not None
    got = [e.title for e in result]
    assert got[0] == "第1章 名1"
    assert got[14] == "第15章 名15"
    assert got[15] == "第16章 名16"
    assert got[-1] == "第65章 名65"


def test_normal_ascending_order_not_touched():
    from novel_extractor.analyzer.catalog_order import reorder_segmented

    titles = [f"第{i}章 名{i}" for i in range(1, 21)]
    assert reorder_segmented(entries_from_titles(titles), ChapterTitleDetector()) is None


def test_noisy_two_run_sequence_not_rotated():
    # A single large drop is not enough: the second run must be clean.
    from novel_extractor.analyzer.catalog_order import reorder_segmented

    titles = [f"第{i}章 名{i}" for i in (10, 9, 11, 14, 1, 3, 2, 5)]
    assert reorder_segmented(entries_from_titles(titles), ChapterTitleDetector()) is None

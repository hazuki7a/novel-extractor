"""Tests for TXT export (guide task 15)."""

from __future__ import annotations

from pathlib import Path

from novel_extractor.exporter.txt import TxtExporter, safe_filename
from novel_extractor.models import (
    BookMetadata,
    CatalogDirection,
    ContentStatus,
    LogicalChapter,
)


class FakeResult:
    """Duck-typed stand-in for CrawlResult (exporter must not need the crawler)."""

    def __init__(self, chapters, book_title="测试小说", author="作者甲", stats=None):
        self.metadata = BookMetadata(book_title=book_title, author=author)
        self.catalog = None
        self.direction = CatalogDirection.ASCENDING
        self.direction_reason = "chapter numbers ascend in DOM order"
        self.chapters = chapters
        self.stats = stats or {"warnings": [], "status_counts": {"CONTENT_OK": len(chapters)}}


def chapter(index, title, content="　　正文内容。", status=ContentStatus.CONTENT_OK):
    return LogicalChapter(
        index=index, title=title, source_pages=[f"http://e.com/{index}.html"],
        content=content, content_status=status, confidence=0.9,
    )


def test_chapter_files_written_in_order(tmp_path):
    chapters = [chapter(i, f"第{i}章 风云{i}") for i in range(1, 13)]
    export = TxtExporter(tmp_path).export(FakeResult(chapters))
    names = [p.name for p in export.chapter_files]
    assert names[0] == "0001 第1章 风云1.txt"
    assert names[11] == "0012 第12章 风云12.txt"
    assert all(p.exists() for p in export.chapter_files)


def test_merged_file_format(tmp_path):
    chapters = [
        chapter(1, "第一章 起", "　　正文一。"),
        chapter(2, "第二章 承", "　　正文二。"),
    ]
    export = TxtExporter(tmp_path).export(FakeResult(chapters))
    text = export.merged_file.read_text(encoding="utf-8")
    assert text.startswith("测试小说\n作者：作者甲")
    assert "第一章 起\n\n　　正文一。" in text
    assert "第二章 承\n\n　　正文二。" in text
    # order preserved
    assert text.index("第一章 起") < text.index("第二章 承")


def test_restricted_chapter_with_content_keeps_it_and_flags(tmp_path):
    # Merged part-chapters may carry extracted parts; the file keeps them but
    # the explicit note prevents the missing part from being silent.
    chapters = [
        chapter(1, "第1章 正常", "　　正常正文。"),
        chapter(2, "第2章 受限", content="　　已提取的一半。", status=ContentStatus.PAYWALL),
    ]
    export = TxtExporter(tmp_path).export(FakeResult(chapters))
    flagged = export.chapter_files[1].read_text(encoding="utf-8")
    assert "已提取的一半。" in flagged
    assert "PAYWALL" in flagged
    assert "未完整收录" in flagged
    merged = export.merged_file.read_text(encoding="utf-8")
    assert "未完整收录" in merged
    assert export.chapters_flagged == 1
    summary = export.summary_file.read_text(encoding="utf-8")
    assert "PAYWALL" in summary
    assert "第2章 受限" in summary


def test_restricted_chapter_without_content_gets_placeholder(tmp_path):
    chapters = [chapter(1, "第1章 受限", content="", status=ContentStatus.PAYWALL)]
    export = TxtExporter(tmp_path).export(FakeResult(chapters))
    flagged = export.chapter_files[0].read_text(encoding="utf-8")
    assert "PAYWALL" in flagged
    assert "未能正常提取" in flagged
    assert "源页面" in flagged


def test_windows_unsafe_filename_sanitized(tmp_path):
    chapters = [chapter(1, '第1章 题目含/斜杠:和"引号"')]
    export = TxtExporter(tmp_path).export(FakeResult(chapters))
    name = export.chapter_files[0].name
    assert "/" not in name and ":" not in name and '"' not in name
    assert name.startswith("0001 ")


def test_reserved_device_names_prefixed(tmp_path):
    assert safe_filename("CON").startswith("_")
    assert safe_filename("NUL.txt"[:3]) == "_NUL"


def test_trailing_dots_and_spaces_stripped(tmp_path):
    assert safe_filename("标题... ") == "标题"


def test_long_title_truncated(tmp_path):
    name = safe_filename("很" * 200)
    assert len(name) <= 80


def test_missing_metadata_falls_back(tmp_path):
    result = FakeResult([chapter(1, "第1章")], book_title=None, author=None)
    result.metadata = BookMetadata()
    export = TxtExporter(tmp_path).export(result)
    assert export.book_dir.name == "未命名小说"
    merged = export.merged_file.read_text(encoding="utf-8")
    assert merged.startswith("未命名小说\n")


def test_summary_contains_direction_and_counts(tmp_path):
    chapters = [chapter(i, f"第{i}章") for i in range(1, 4)]
    stats = {
        "warnings": ["catalog direction UNKNOWN"],
        "status_counts": {"CONTENT_OK": 3},
    }
    export = TxtExporter(tmp_path).export(FakeResult(chapters, stats=stats))
    summary = export.summary_file.read_text(encoding="utf-8")
    assert "ASCENDING" in summary
    assert "CONTENT_OK=3" in summary
    assert "catalog direction UNKNOWN" in summary
    assert "正常章节：3" in summary


def test_export_directory_structure(tmp_path):
    chapters = [chapter(1, "第1章 起")]
    export = TxtExporter(tmp_path).export(FakeResult(chapters))
    assert export.book_dir == tmp_path / "测试小说"
    assert export.book_dir.exists()
    assert (export.book_dir / "chapters").exists()
    assert export.merged_file == export.book_dir / "测试小说.txt"

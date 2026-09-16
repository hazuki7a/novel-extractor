"""Tests for EPUB export (guide task 28)."""

from __future__ import annotations

import zipfile

from novel_extractor.exporter.epub import EpubExporter, chapter_to_html
from novel_extractor.models import (
    BookMetadata,
    CatalogDirection,
    ContentStatus,
    LogicalChapter,
)


class FakeResult:
    def __init__(self, chapters, book_title="测试小说", author="作者甲"):
        self.metadata = BookMetadata(book_title=book_title, author=author)
        self.catalog = None
        self.direction = CatalogDirection.ASCENDING
        self.direction_reason = ""
        self.chapters = chapters
        self.stats = {"warnings": [], "status_counts": {}}


def chapter(index, title, content="　　正文内容。", status=ContentStatus.CONTENT_OK):
    return LogicalChapter(
        index=index, title=title, source_pages=[f"http://e.com/{index}.html"],
        content=content, content_status=status, confidence=0.9,
    )


def test_epub_file_is_valid_zip_with_chapters(tmp_path):
    chapters = [
        chapter(1, "第1章 起", "　　正文一。"),
        chapter(2, "第2章 承", "　　正文二。"),
    ]
    path = EpubExporter(tmp_path).export(FakeResult(chapters))
    assert path.name == "测试小说.epub"
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        assert "mimetype" in names
        body = "".join(zf.read(n).decode("utf-8", "replace") for n in names)
        assert "正文一" in body and "正文二" in body
        assert "第2章 承" in body


def test_restricted_chapter_marked_in_epub(tmp_path):
    chapters = [
        chapter(1, "第1章 正常"),
        chapter(2, "第2章 受限", content="", status=ContentStatus.PAYWALL),
    ]
    path = EpubExporter(tmp_path).export(FakeResult(chapters))
    with zipfile.ZipFile(path) as zf:
        body = "".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())
    assert "PAYWALL" in body
    assert "不会被当作正文静默保存" in body


def test_chapter_body_escaped_and_paragraphed():
    html = chapter_to_html(chapter(1, "第1章", "　　A<b> 与 B。"))
    assert "&lt;b&gt;" in html
    assert html.count("<p>") == 1


def test_author_recorded(tmp_path):
    path = EpubExporter(tmp_path).export(FakeResult([chapter(1, "第1章")], author="作者甲"))
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        opf_name = next(n for n in names if n.endswith(".opf"))
        opf = zf.read(opf_name).decode("utf-8", "replace")
    assert "作者甲" in opf

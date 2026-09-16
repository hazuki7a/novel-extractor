"""EPUB export (guide task 28 / V2).

Chapter order, metadata and restricted-chapter handling stay consistent with
the TXT exporter: LogicalChapter order is preserved verbatim, metadata comes
only from MetadataExtractor, and restricted chapters are exported as clearly
marked placeholder sections instead of silent normal text.
"""

from __future__ import annotations

import re
from pathlib import Path

from novel_extractor.exporter.txt import safe_filename
from novel_extractor.models import ContentStatus, LogicalChapter

_ILLEGAL_XML_RE = re.compile(r"[<>&]")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def chapter_to_html(chapter: LogicalChapter) -> str:
    """One chapter as simple XHTML paragraphs (or an explicit placeholder)."""
    if chapter.content_status is not ContentStatus.CONTENT_OK:
        return (
            f"<p><b>【本章未能正常提取】状态：{chapter.content_status.value}</b></p>"
            f"<p>源页面：{' , '.join(chapter.source_pages)}</p>"
            "<p>受限或异常页不会被当作正文静默保存。</p>"
        )
    paragraphs = [p.strip() for p in chapter.content.split("\n\n") if p.strip()]
    body = "".join(f"<p>{_xml_escape(p)}</p>" for p in paragraphs)
    return body or f"<p>（空章节）</p>"


class EpubExporter:
    def __init__(self, output_root: str | Path = "output"):
        self._output_root = Path(output_root)

    def export(self, result) -> Path:
        """Export a CrawlResult-shaped object to output/<书名>/<书名>.epub."""
        from ebooklib import epub

        book_title = (result.metadata.book_title or "未命名小说").strip() or "未命名小说"
        author = (result.metadata.author or "").strip()

        book = epub.EpubBook()
        book.set_identifier(f"novel-extractor-{safe_filename(book_title)}")
        book.set_title(book_title)
        book.set_language("zh")
        if author:
            book.add_author(author)

        chapters = []
        for chapter in result.chapters:
            item = epub.EpubHtml(
                title=chapter.title,
                file_name=f"ch_{chapter.index:04d}.xhtml",
                lang="zh",
            )
            heading = f"<h2>{_xml_escape(chapter.title)}</h2>"
            item.content = f"<html><body>{heading}{chapter_to_html(chapter)}</body></html>"
            book.add_item(item)
            chapters.append(item)

        book.toc = chapters
        book.spine = ["nav", *chapters]
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        book_dir = self._output_root / safe_filename(book_title)
        book_dir.mkdir(parents=True, exist_ok=True)
        path = book_dir / f"{safe_filename(book_title)}.epub"
        epub.write_epub(str(path), book)
        return path

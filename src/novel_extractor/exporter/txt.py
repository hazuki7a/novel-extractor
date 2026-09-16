"""TXT export.

Layout (guide output spec):
    output/<书名>/chapters/0001 第一章.txt
    output/<书名>/<书名>.txt
    output/<书名>/下载汇总.txt

Rules: UTF-8 only, Windows-safe filenames, chapter order is exactly the
crawler's final order, restricted chapters are never silently written as
normal text, and the exporter never invents metadata (it only consumes what
MetadataExtractor produced).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from novel_extractor.models import ContentStatus, LogicalChapter

_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_MAX_NAME_LEN = 80
_PLACEHOLDER_TITLE = "未命名小说"


def safe_filename(name: str) -> str:
    """Make a Windows-safe file name component."""
    cleaned = _ILLEGAL_RE.sub("_", name).strip().rstrip(". ")
    if len(cleaned) > _MAX_NAME_LEN:
        cleaned = cleaned[:_MAX_NAME_LEN].rstrip(". ")
    if not cleaned:
        return "_"
    if cleaned.upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned


@dataclass
class ExportResult:
    book_dir: Path
    chapter_files: list[Path] = field(default_factory=list)
    merged_file: Optional[Path] = None
    summary_file: Optional[Path] = None
    chapters_ok: int = 0
    chapters_flagged: int = 0


class TxtExporter:
    def __init__(self, output_root: str | Path = "output"):
        self._output_root = Path(output_root)

    def export(self, result, merged: bool = True) -> ExportResult:
        """Export a CrawlResult. Kept duck-typed to avoid a crawler import cycle."""
        book_title = (result.metadata.book_title or _PLACEHOLDER_TITLE).strip() or _PLACEHOLDER_TITLE
        book_dir = self._output_root / safe_filename(book_title)
        chapters_dir = book_dir / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)

        export = ExportResult(book_dir=book_dir)
        author = (result.metadata.author or "").strip()

        for chapter in result.chapters:
            path = self._write_chapter(chapters_dir, chapter)
            export.chapter_files.append(path)
            if chapter.content_status is ContentStatus.CONTENT_OK:
                export.chapters_ok += 1
            else:
                export.chapters_flagged += 1

        if merged:
            export.merged_file = self._write_merged(book_dir, book_title, author, result.chapters)
        export.summary_file = self._write_summary(book_dir, book_title, author, result, export)
        return export

    # -- writers ------------------------------------------------------------

    def _write_chapter(self, chapters_dir: Path, chapter: LogicalChapter) -> Path:
        name = f"{chapter.index:04d} {safe_filename(chapter.title)}".rstrip() or f"{chapter.index:04d}"
        path = chapters_dir / f"{name}.txt"
        path.write_text(self._render_body(chapter), encoding="utf-8", newline="\n")
        return path

    @staticmethod
    def _render_body(chapter: LogicalChapter) -> str:
        if chapter.content_status is ContentStatus.CONTENT_OK:
            return chapter.content
        note = f"【本章状态：{chapter.content_status.value}，未完整收录】"
        if chapter.content.strip():
            # Merged part-chapters keep the parts that did extract; the
            # explicit note keeps the missing ones from being silent.
            return chapter.content + "\n\n" + note
        return (
            f"【本章未能正常提取】状态：{chapter.content_status.value}\n"
            f"源页面：{' , '.join(chapter.source_pages)}\n"
            "（受限或异常页不会被当作正文静默保存）"
        )

    def _write_merged(self, book_dir: Path, book_title: str, author: str, chapters) -> Path:
        lines = [book_title]
        if author:
            lines.append(f"作者：{author}")
        lines.append("")
        for chapter in chapters:
            lines.append(chapter.title)
            lines.append("")
            body = self._render_body(chapter)
            lines.append(body)
            lines.append("")
        path = book_dir / f"{safe_filename(book_title)}.txt"
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8", newline="\n")
        return path

    def _write_summary(self, book_dir: Path, book_title: str, author: str, result, export: ExportResult) -> Path:
        stats = result.stats or {}
        counts = stats.get("status_counts", {})
        lines = [
            "下载汇总",
            f"书名：{book_title}",
            f"作者：{author or '（未提供）'}",
            f"目录方向：{result.direction.value}（{result.direction_reason or 'n/a'}）",
            f"章节总数：{len(result.chapters)}",
            f"正常章节：{export.chapters_ok}",
            f"受限/异常章节：{export.chapters_flagged}",
            "状态分布：" + (", ".join(f"{k}={v}" for k, v in counts.items()) or "n/a"),
        ]
        warnings = stats.get("warnings", [])
        if warnings:
            lines.append("警告：")
            lines.extend(f"  - {w}" for w in warnings)
        flagged = [c for c in result.chapters if c.content_status is not ContentStatus.CONTENT_OK]
        if flagged:
            lines.append("受限/异常章节列表：")
            lines.extend(f"  - [{c.content_status.value}] {c.title}" for c in flagged)
        path = book_dir / "下载汇总.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return path

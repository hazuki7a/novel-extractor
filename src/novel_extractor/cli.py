"""Command line entry point. The CLI only orchestrates the core library."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import novel_extractor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-extractor",
        description="Ruleless novel structure inference engine (no source rules, no API keys).",
    )
    parser.add_argument("--version", action="version", version=f"novel-extractor {novel_extractor.__version__}")
    subparsers = parser.add_subparsers(dest="command")
    download = subparsers.add_parser("download", help="Download a novel from a detail/catalog/chapter URL.")
    download.add_argument("url", help="Novel page URL (detail page, catalog page or chapter page).")
    download.add_argument("--output", default="output", help="Output root directory (default: output).")
    download.add_argument(
        "--interval", type=float, default=0.3,
        help="Start/floor interval in seconds for adaptive pacing (default 0.3); "
             "the fixed pace when --no-adaptive is given.",
    )
    download.add_argument(
        "--no-adaptive", action="store_true",
        help="Disable adaptive pacing; use --interval as a fixed delay.",
    )
    download.add_argument("--max-chapters", type=int, default=2000, help="Safety cap on chapter count.")
    download.add_argument(
        "--keep-parts", action="store_true",
        help="Keep per-part files (第6章 1/2/3) instead of merging into one chapter.",
    )
    download.add_argument(
        "--no-cache", action="store_true",
        help="Disable the automatic inference cache (structural profile per host).",
    )
    download.add_argument(
        "--epub", action="store_true",
        help="Also export an EPUB alongside the TXT files.",
    )
    download.add_argument(
        "--interactive", action="store_true",
        help="Ask the user to correct results the engine could not decide "
             "(e.g. unknown catalog direction, missing catalog).",
    )

    analyze = subparsers.add_parser("analyze", help="Analyze a single page (no downloads).")
    analyze.add_argument("url", help="Novel page URL.")

    inspect = subparsers.add_parser("inspect", help="Analyze with full candidate/relation detail.")
    inspect.add_argument("url", help="Novel page URL.")

    cache_cmd = subparsers.add_parser("cache", help="Manage the inference cache.")
    cache_sub = cache_cmd.add_subparsers(dest="cache_command")
    cache_sub.add_parser("list", help="List cached host profiles.")
    clear = cache_sub.add_parser("clear", help="Clear cached profiles.")
    clear.add_argument("--host", default=None, help="Clear only this host.")

    web = subparsers.add_parser("web", help="Start the local WebUI.")
    web.add_argument("--port", type=int, default=8765, help="Port (default 8765).")
    web.add_argument("--output", default="output", help="Output root directory.")
    return parser


def _progress(done: int, total, title: str, status: str, interval: float = 0.0) -> None:
    label = f"{done}/{total}" if total else str(done)
    print(f"\r  下载进度 {label} | {title} [{status}] @{interval:.1f}s" + " " * 6, end="", flush=True)


def _run_download(args) -> int:
    from novel_extractor.cache import InferenceCache
    from novel_extractor.crawler.novel import CrawlOptions, NovelCrawler
    from novel_extractor.exporter.txt import TxtExporter
    from novel_extractor.fetcher.http import HttpFetcher

    cache = None if args.no_cache else InferenceCache(cache_dir=Path(args.output) / ".cache")
    fetcher = HttpFetcher()
    try:
        crawler = NovelCrawler(
            fetcher=fetcher,
            options=CrawlOptions(
                request_interval=args.interval,
                adaptive_interval=not args.no_adaptive,
                max_chapters=args.max_chapters,
                merge_parts=not args.keep_parts,
            ),
            progress=_progress,
            cache=cache,
        )
        print(f"正在分析页面: {args.url}", flush=True)
        result = crawler.crawl(args.url)
    finally:
        fetcher.close()
    print()

    if result.catalog is None:
        print("未找到目录，使用章节链接遍历。", flush=True)
    else:
        print(f"目录: {len(result.catalog.chapters)} 章 | 方向: {result.direction.value}", flush=True)

    if args.interactive:
        from novel_extractor.correction import ask_direction
        from novel_extractor.models import CatalogDirection

        if result.direction is CatalogDirection.UNKNOWN and result.chapters:
            answer = ask_direction(result.direction)
            if answer is CatalogDirection.UNKNOWN:
                print("已中止导出。")
                return 2
            if answer is CatalogDirection.DESCENDING:
                result.chapters.reverse()
                for i, c in enumerate(result.chapters):
                    c.index = i + 1
                stats_direction = "DESCENDING (user-corrected)"
                print("已按用户选择反转章节顺序。")

    export = TxtExporter(output_root=args.output).export(result)
    epub_path = None
    if args.epub:
        from novel_extractor.exporter.epub import EpubExporter

        epub_path = EpubExporter(output_root=args.output).export(result)
    print(f"书名: {result.metadata.book_title or '未命名小说'}")
    print(f"作者: {result.metadata.author or '（未提供）'}")
    print(f"目录方向: {result.direction.value}")
    print(f"章节: {len(result.chapters)} (正常 {export.chapters_ok} / 受限或异常 {export.chapters_flagged})")
    print(f"输出目录: {export.book_dir}")
    if export.merged_file:
        print(f"合并文件: {export.merged_file}")
    if epub_path:
        print(f"EPUB: {epub_path}")
    print(f"下载汇总: {export.summary_file}")
    for warning in result.stats.get("warnings", []):
        print(f"警告: {warning}", file=sys.stderr)
    adaptive = result.stats.get("adaptive", {})
    if adaptive:
        print(
            f"自适应速率: 退避 {adaptive.get('backoffs', 0)} 次，"
            f"结束间隔 {adaptive.get('final_interval', 0)}s"
        )
    return 0 if export.chapters_flagged == 0 else 1


def _run_analyze(args, detail: bool) -> int:
    from novel_extractor.api import NovelExtractor

    extractor = NovelExtractor(output_root="output")
    analysis = extractor.analyze(args.url)
    print(f"URL: {analysis['final_url']} (HTTP {analysis['http_status']}, {analysis['encoding']})")
    print(f"页面类型: {analysis['page_type']} (confidence {analysis['page_type_confidence']})")
    print(f"  原因: {analysis['page_type_reason']}")
    meta = analysis["metadata"]
    print(f"书名: {meta['book_title']} ({meta['title_confidence']}) | 作者: {meta['author']} ({meta['author_confidence']})")
    content = analysis["content"]
    print(f"正文: {content['text_length']} 字符 @ <{content['node_tag']}> (confidence {content['confidence']})")
    print(f"  原因: {content['reason']}")
    nav = analysis["navigation"]
    print(f"导航: 上一章={nav['previous_chapter']} 下一章={nav['next_chapter']} 目录={nav['catalog_url']}")
    preview = analysis["catalog_preview"]
    if preview["entries"] or preview["confidence"]:
        print(f"目录预览: {preview['entries']} 条 (confidence {preview['confidence']})")
        if preview["titles"]:
            print(f"  前 5 条: {preview['titles'][:5]}")
    if detail:
        print("候选:")
        for c in content["candidates"]:
            print(
                f"  - {c['candidate_id']}: score={c['score']} confidence={c['confidence']} "
                f"positives={c['positive_reasons']} penalties={c['penalties']}"
            )
        print(f"诊断: {analysis['diagnostics']}")
    return 0


def _run_cache(args) -> int:
    from novel_extractor.api import NovelExtractor

    extractor = NovelExtractor(output_root="output")
    if args.cache_command == "list":
        entries = extractor.cache_list()
        if not entries:
            print("缓存为空")
        for entry in entries:
            print(f"  {entry['host']}: confidence={entry['confidence']} stats={entry['validation_stats']}")
        return 0
    if args.cache_command == "clear":
        count = extractor.cache_clear(args.host)
        print(f"已清除 {count} 个主机画像")
        return 0
    print("用法: novel-extractor cache list|clear [--host X]")
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "download":
        return _run_download(args)
    if args.command == "analyze":
        return _run_analyze(args, detail=False)
    if args.command == "inspect":
        return _run_analyze(args, detail=True)
    if args.command == "cache":
        return _run_cache(args)
    if args.command == "web":
        from novel_extractor.webui import serve

        serve(output_root=args.output, port=args.port)
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

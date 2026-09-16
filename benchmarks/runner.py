"""Benchmark runner (guide task 16).

Runs the full NovelCrawler pipeline against local fixture sites and scores
the result against each site's expected.json. Never touches the network.

Usage:
    python benchmarks/runner.py [--report-dir benchmarks/reports]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
SITES_DIR = ROOT / "sites"

sys.path.insert(0, str(ROOT.parent / "src"))

from novel_extractor.analyzer.navigation import ChapterNavigationDetector  # noqa: E402
from novel_extractor.analyzer.page_type import PageTypeDetector  # noqa: E402
from novel_extractor.crawler.novel import CrawlOptions, NovelCrawler  # noqa: E402
from novel_extractor.fetcher.http import FetchError, decode_page_bytes  # noqa: E402
from novel_extractor.models import FetchedPage  # noqa: E402


def _norm_title(title: str) -> str:
    return "".join(title.split())


class FixtureFetcher:
    """Serves the *.html files of one fixture site as URLs.

    Default URL for a file  foo.html  is  http://<site_id>/foo.html  unless
    expected.json's url_map re-maps a file stem to another URL shape (query
    strings etc.).
    """

    _SHELL_HTML = "<html><body>loading</body></html>"

    def __init__(self, site_dir: Path, site_id: str, url_map: dict[str, str] | None = None,
                 http_status: dict[str, int] | None = None,
                 shell_first_fetch: list[str] | None = None):
        self._site_dir = site_dir
        self._by_url: dict[str, Path] = {}
        self._http_status = http_status or {}
        self._shell_files = set(shell_first_fetch or [])
        self._served: set[str] = set()
        for html_file in sorted(site_dir.glob("*.html")):
            self._by_url[f"http://{site_id}/{html_file.name}"] = html_file
        for stem, mapped in (url_map or {}).items():
            self._by_url[f"http://{site_id}/{mapped}"] = site_dir / f"{stem}.html"

    def fetch(self, url: str, *, referer=None) -> FetchedPage:
        parsed = urlparse(url)
        path = parsed.path.lstrip("/")
        direct = self._site_dir / path
        page_file = self._by_url.get(url.rstrip("/")) or (
            direct if direct.exists() else None
        )
        if page_file is None or not page_file.exists():
            raise FetchError(url, f"fixture page not found for {url}")
        raw = page_file.read_bytes()
        html, _decision = decode_page_bytes(raw)
        # Throttling simulation: listed files serve an empty shell once.
        file_key = page_file.name
        if file_key in self._shell_files and file_key not in self._served:
            self._served.add(file_key)
            html = self._SHELL_HTML
        self._served.add(file_key)
        stem = page_file.stem
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=self._http_status.get(stem, 200),
            raw_bytes=raw,
            html=html,
            encoding="utf-8",
            encoding_source="fixture",
            encoding_confidence=1.0,
        )


def _match_navigation(detected: dict, expected: dict) -> bool:
    for key in ("previous", "next", "catalog"):
        want = expected.get(key)
        got = detected.get({"previous": "previous_chapter", "next": "next_chapter", "catalog": "catalog_url"}[key])
        if want is None:
            if got is not None:
                return False
        else:
            if got is None or not got.endswith(want):
                return False
    return True


def run_site(site_dir: Path) -> dict:
    expected = json.loads((site_dir / "expected.json").read_text(encoding="utf-8"))
    site_id = site_dir.name
    fetcher = FixtureFetcher(
        site_dir, site_id,
        url_map=expected.get("url_map"),
        http_status=expected.get("http_status"),
        shell_first_fetch=expected.get("shell_first_fetch"),
    )
    start_url = f"http://{site_id}/{expected['start']}"
    result = NovelCrawler(fetcher=fetcher, options=CrawlOptions(request_interval=0.0)).crawl(start_url)

    details: dict = {"site": site_id, "checks": {}, "failures": []}
    checks = details["checks"]

    # Collapsed-catalog expansion (only meaningful with the JS sandbox; the
    # fixture is designed to complete via gap-fill without quickjs too).
    if expected.get("expansion_required"):
        try:
            import quickjs  # noqa: F401

            has_quickjs = True
        except ImportError:
            has_quickjs = False
        if has_quickjs:
            expanded = any("已展开折叠目录段" in w for w in result.stats.get("warnings", []))
            checks["catalog_expansion"] = (1 if expanded else 0, 1)
            if not expanded:
                details["failures"].append("collapsed catalog was not expanded via JS sandbox")
        else:
            details["checks_skipped"] = ["catalog_expansion (quickjs not installed)"]

    # Page classification (detector level, on every mapped page).
    page_type_detector = PageTypeDetector()
    if "pages" in expected:
        total = passed = 0
        for file_name, want_type in expected["pages"].items():
            page = fetcher.fetch(f"http://{site_id}/{file_name}")
            got = page_type_detector.classify(page.html).value.value
            total += 1
            if got == want_type:
                passed += 1
            else:
                details["failures"].append(f"page_type {file_name}: want {want_type} got {got}")
        checks["page_classification"] = (passed, total)

    # Navigation (detector level).
    if "navigation" in expected:
        nav_detector = ChapterNavigationDetector()
        total = passed = 0
        for file_name, want in expected["navigation"].items():
            page = fetcher.fetch(f"http://{site_id}/{file_name}")
            got = nav_detector.detect(page.html, page.final_url).value
            total += 1
            if _match_navigation(got, want):
                passed += 1
            else:
                details["failures"].append(f"navigation {file_name}: want {want} got {got}")
        checks["navigation"] = (passed, total)

    # Metadata.
    if "metadata" in expected:
        meta = result.metadata
        want_title = (expected["metadata"].get("book_title") or "").strip()
        want_author = (expected["metadata"].get("author") or "").strip()
        ok = True
        if want_title and (meta.book_title or "").strip() != want_title:
            ok = False
            details["failures"].append(f"metadata title: want {want_title!r} got {meta.book_title!r}")
        if want_author and (meta.author or "").strip() != want_author:
            ok = False
            details["failures"].append(f"metadata author: want {want_author!r} got {meta.author!r}")
        checks["metadata"] = (1 if ok else 0, 1)

    # Catalog presence / false positive.
    if expected.get("catalog") is None:
        checks["catalog_false_positive"] = (0 if result.catalog else 1, 1)
        if result.catalog:
            details["failures"].append("catalog false positive on site without catalog")
    else:
        checks["catalog_detected"] = (1 if result.catalog and result.catalog.chapters else 0, 1)
        if not result.catalog:
            details["failures"].append("catalog not detected")

        # Direction.
        want_direction = expected["catalog"].get("direction")
        if want_direction:
            got_dir = result.direction.value
            checks["catalog_direction"] = (1 if got_dir == want_direction else 0, 1)
            if got_dir != want_direction:
                details["failures"].append(f"direction: want {want_direction} got {got_dir}")

        # Chapter link recall (by normalized title).
        want_titles = {_norm_title(t) for t in expected["catalog"]["titles"]}
        got_titles = {_norm_title(c.title) for c in (result.catalog.chapters if result.catalog else [])}
        recall_hits = len(want_titles & got_titles)
        checks["chapter_recall"] = (recall_hits, len(want_titles))
        missing = want_titles - got_titles
        if missing:
            details["failures"].append(f"catalog entries missing: {sorted(missing)[:5]}")

        # Catalog pagination merge total.
        if "catalog_total_entries" in expected:
            want_n = expected["catalog_total_entries"]
            got_n = len(result.catalog.chapters) if result.catalog else 0
            checks["catalog_pagination"] = (1 if got_n == want_n else 0, 1)
            if got_n != want_n:
                details["failures"].append(f"catalog total: want {want_n} got {got_n}")

    # Chapter order (post-direction final order).
    if "chapter_order" in expected:
        want_order = [_norm_title(t) for t in expected["chapter_order"]]
        got_order = [_norm_title(c.title) for c in result.chapters]
        checks["chapter_order"] = (1 if got_order == want_order else 0, 1)
        if got_order != want_order:
            details["failures"].append(f"chapter order: want {want_order} got {got_order}")

    # Content extraction success (must-contain sentences in cleaned content).
    if "content_must_contain" in expected or "content_must_not_contain" in expected:
        total = passed = 0
        for title, needles in expected.get("content_must_contain", {}).items():
            chapter = next((c for c in result.chapters if _norm_title(c.title) == _norm_title(title)), None)
            total += 1
            if chapter and all(needle in chapter.content for needle in needles):
                passed += 1
            else:
                details["failures"].append(f"content missing needles for {title}")
        for title, needles in expected.get("content_must_not_contain", {}).items():
            chapter = next((c for c in result.chapters if _norm_title(c.title) == _norm_title(title)), None)
            total += 1
            if chapter and all(needle not in chapter.content for needle in needles):
                passed += 1
            else:
                details["failures"].append(f"content contains forbidden needles for {title}")
        checks["content_success"] = (passed, total)

    # Content pagination merge.
    if "content_pagination" in expected:
        total = passed = 0
        for title, want_pages in expected["content_pagination"].items():
            chapter = next((c for c in result.chapters if _norm_title(c.title) == _norm_title(title)), None)
            got_pages = len(chapter.source_pages) if chapter else -1
            total += 1
            if got_pages == want_pages:
                passed += 1
            else:
                details["failures"].append(f"content pagination {title}: want {want_pages} pages got {got_pages}")
        checks["content_pagination"] = (passed, total)

    # Restricted / failed page statuses.
    if "content_statuses" in expected:
        total = passed = 0
        for title, want_status in expected["content_statuses"].items():
            chapter = next((c for c in result.chapters if _norm_title(c.title) == _norm_title(title)), None)
            got_status = chapter.content_status.value if chapter else "MISSING"
            total += 1
            if got_status == want_status:
                passed += 1
            else:
                details["failures"].append(f"status {title}: want {want_status} got {got_status}")
        checks["restricted_status"] = (passed, total)

    details["chapters_downloaded"] = len(result.chapters)
    return details


def _rate(checks: dict, key: str) -> tuple[float, int]:
    if key not in checks:
        return (1.0, 0)  # not applicable counts as pass with zero weight
    passed, total = checks[key]
    return (passed / total if total else 1.0, total)


def run_all(sites_dir: Path = SITES_DIR) -> dict:
    report: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sites": {},
        "metrics": {},
    }
    aggregates: dict[str, list[tuple[float, int]]] = {}

    for site_dir in sorted(p for p in sites_dir.iterdir() if p.is_dir()):
        details = run_site(site_dir)
        report["sites"][site_dir.name] = details
        for key in (
            "page_classification", "navigation", "metadata", "catalog_detected",
            "catalog_direction", "chapter_recall", "catalog_pagination",
            "chapter_order", "content_success", "content_pagination",
            "restricted_status", "catalog_false_positive", "catalog_expansion",
        ):
            if key in details["checks"]:
                aggregates.setdefault(key, []).append(_rate(details["checks"], key))

    for key, samples in aggregates.items():
        weighted_passed = sum(p * t for p, t in samples)
        weighted_total = sum(t for _p, t in samples)
        report["metrics"][key] = round(weighted_passed / weighted_total, 4) if weighted_total else 1.0
        report["metrics"][f"{key}_weight"] = weighted_total
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local benchmark suite.")
    parser.add_argument("--report-dir", default=str(ROOT / "reports"))
    args = parser.parse_args()

    report = run_all()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = report_dir / f"report-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print(f"benchmark report -> {out}")
    for site, details in report["sites"].items():
        status = "PASS" if not details["failures"] else "FAIL"
        print(f"  [{status}] {site} ({details['chapters_downloaded']} chapters)")
        for failure in details["failures"]:
            print(f"      - {failure}")
    print("metrics:")
    for key, value in report["metrics"].items():
        if not key.endswith("_weight"):
            print(f"  {key}: {value}")
    failures = sum(1 for d in report["sites"].values() if d["failures"])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

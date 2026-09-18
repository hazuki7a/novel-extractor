"""Contract-based offline benchmark runner.

Inference reads only ``case.json`` and saved inputs.  ``expected.json`` is
opened afterwards by the evaluator.  The legacy ``benchmarks/runner.py``
remains available as the historical synthetic regression gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
CASES_DIR = ROOT / "cases"
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from offline_contract import (  # noqa: E402
    CaseValidationError,
    OfflineCase,
    OfflineFixtureFetcher,
    load_case,
    load_expected,
)
from failure_diagnostics import (  # noqa: E402
    FAILURE_TAXONOMY,
    annotate_expected_catalog_group,
    diagnose_catalog_groups,
    diagnose_pagination_candidates,
    page_type_failure_category,
    sample_type_for,
)
from novel_extractor.analyzer.catalog import CatalogDetector  # noqa: E402
from novel_extractor.analyzer.content import ContentExtractor  # noqa: E402
from novel_extractor.analyzer.content_status import ContentStatusDetector  # noqa: E402
from novel_extractor.analyzer.metadata import MetadataExtractor  # noqa: E402
from novel_extractor.analyzer.navigation import ChapterNavigationDetector  # noqa: E402
from novel_extractor.analyzer.page_type import PageTypeDetector  # noqa: E402
from novel_extractor.crawler.novel import CrawlOptions, NovelCrawler  # noqa: E402


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    value = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return value.strip()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_reference(case: OfflineCase, relative: str | None) -> str | None:
    if not relative:
        return None
    return (case.case_dir / relative).read_text(encoding="utf-8")


def _prediction_for_case(case: OfflineCase) -> dict[str, Any]:
    """Run real project modules without opening expected.json."""

    fetcher = OfflineFixtureFetcher(case)
    page_type_detector = PageTypeDetector()
    metadata_extractor = MetadataExtractor()
    content_extractor = ContentExtractor()
    status_detector = ContentStatusDetector()
    navigation_detector = ChapterNavigationDetector()
    catalog_detector = CatalogDetector()
    pages: dict[str, dict[str, Any]] = {}

    for page_id, spec in case.pages_by_id.items():
        page = fetcher.fetch(spec["requested_url"])
        page_type = page_type_detector.classify(page.html)
        metadata = metadata_extractor.extract(page.html)
        content = content_extractor.extract(page.html)
        content_status = status_detector.detect(page, content)
        navigation = navigation_detector.detect(page.html, page.final_url)
        catalog = catalog_detector.detect(page.html, page.final_url)
        catalog_candidates = diagnose_catalog_groups(page.html, page.final_url, catalog)
        pagination_candidates = diagnose_pagination_candidates(
            page, page_type.value.value, fetcher
        )
        pages[page_id] = {
            "page_id": page_id,
            "requested_url": page.url,
            "final_url": page.final_url,
            "http_status": page.status_code,
            "input_kind": spec["input_kind"],
            "encoding": page.encoding,
            "encoding_source": page.encoding_source,
            "page_type": page_type.value.value,
            "page_type_confidence": page_type.confidence,
            "content_status": content_status.value.value,
            "content_status_confidence": content_status.confidence,
            "content": content.text,
            "exportable_content": content.text if content_status.value.value == "CONTENT_OK" else "",
            "content_confidence": content.confidence,
            "metadata": {
                "book_title": metadata.book_title,
                "author": metadata.author,
                "title_confidence": metadata.title_confidence,
                "author_confidence": metadata.author_confidence,
            },
            "navigation": navigation.value,
            "navigation_confidence": navigation.confidence,
            "navigation_reason": navigation.reason,
            "catalog": {
                "direction": catalog.direction.value,
                "confidence": catalog.confidence,
                "reason": catalog.reason,
                "entries": [
                    {"title": item.title, "target_url": item.url, "source_order": item.dom_index}
                    for item in catalog.chapters
                ],
            },
            "diagnostics": {
                "page_type": page_type.reason,
                "content": content.reason,
                "content_status": content_status.reason,
                "catalog_candidates": catalog_candidates,
                "pagination_candidates": pagination_candidates,
            },
        }

    crawl_prediction = None
    entry_page_id = case.data.get("entry_page_id")
    if entry_page_id:
        entry_url = case.pages_by_id[entry_page_id]["requested_url"]
        crawler = NovelCrawler(
            fetcher=fetcher,
            options=CrawlOptions(
                request_interval=0.0,
                adaptive_interval=False,
                retry_backoff=0.0,
                status_retries=0,
                status_retry_delay=0.0,
                exploration_budget=0,
            ),
        )
        result = crawler.crawl(entry_url)
        crawl_prediction = {
            "entry_page_id": entry_page_id,
            "book_title": result.metadata.book_title,
            "author": result.metadata.author,
            "direction": result.direction.value,
            "catalog_entries": [
                {"title": item.title, "target_url": item.url}
                for item in (result.catalog.chapters if result.catalog else [])
            ],
            "chapters": [
                {
                    "title": chapter.title,
                    "source_urls": chapter.source_pages,
                    "content": chapter.content,
                    "content_status": chapter.content_status.value,
                }
                for chapter in result.chapters
            ],
            "warnings": list(result.stats.get("warnings", [])),
        }

    return {
        "schema_version": "1.0.0",
        "document_type": "benchmark_prediction",
        "case_id": case.case_id,
        "pages": pages,
        "crawl": crawl_prediction,
    }


class Score:
    def __init__(self, case_id: str, sample_type: str) -> None:
        self.case_id = case_id
        self.sample_type = sample_type
        self.values: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
        self.failures: list[dict[str, Any]] = []
        self.page_type_pairs: list[dict[str, str]] = []
        self.catalog_failures: list[dict[str, Any]] = []
        self.pagination_failures: list[dict[str, Any]] = []
        self.abstentions = 0

    def add(
        self,
        metric: str,
        numerator: float,
        denominator: float,
        sample: str,
        failure: str | None = None,
        *,
        failure_category: str | None = None,
        expected: Any = None,
        actual: Any = None,
        confidence: float | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        self.values[metric].append((numerator, denominator, sample))
        if not failure or numerator >= denominator:
            return
        category = failure_category or "CONTENT_STATUS_WRONG"
        if category not in FAILURE_TAXONOMY:
            raise ValueError(f"unknown failure category: {category}")
        self.failures.append(
            {
                "case_id": self.case_id,
                "sample_type": self.sample_type,
                "sample_id": sample,
                "metric": metric,
                "expected_result": expected,
                "actual_result": actual,
                "confidence": confidence,
                "failure_category": category,
                "relevant_diagnostics": diagnostics or {},
                "message": failure,
            }
        )


def _compare_text(
    score: Score,
    sample: str,
    predicted: str,
    expected: str,
    *,
    confidence: float | None = None,
    diagnostics: dict[str, Any] | None = None,
    encoding_sensitive: bool = False,
) -> None:
    got = _normalize(predicted)
    want = _normalize(expected)
    matcher = SequenceMatcher(a=want, b=got, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    shared = {
        "expected": {"reference_length": len(want)},
        "actual": {"predicted_length": len(got), "matched_characters": matched},
        "confidence": confidence,
        "diagnostics": diagnostics,
    }
    score.add(
        "content_retained_chars", matched, len(want), sample,
        "expected body characters were missing",
        failure_category="ENCODING_ERROR" if encoding_sensitive else "CONTENT_TRUNCATED",
        expected=shared["expected"], actual=shared["actual"],
        confidence=confidence, diagnostics=diagnostics,
    )
    score.add(
        "content_precision_chars", matched, len(got), sample,
        "unexpected text was mixed into body",
        failure_category="ENCODING_ERROR" if encoding_sensitive else "CONTENT_NOISE_INCLUDED",
        expected=shared["expected"], actual=shared["actual"],
        confidence=confidence, diagnostics=diagnostics,
    )


def _evaluate(case: OfflineCase, prediction: dict[str, Any]) -> Score:
    """Open gold labels only after inference has completed."""

    expected = load_expected(case)
    score = Score(case.case_id, sample_type_for(case.data))
    encoding_sensitive = bool(
        set(case.data.get("scenario_tags") or [])
        & {"gbk_gb18030", "encoding_conflict", "shift_jis"}
    )
    labels = {item["page_id"]: item for item in expected.get("page_labels", [])}
    for page_id, label in labels.items():
        got = prediction["pages"].get(page_id)
        if got is None:
            score.add(
                "page_present", 0, 1, page_id, "page prediction missing",
                failure_category="FETCH_ERROR", expected="page prediction",
                actual=None, diagnostics={"page_id": page_id},
            )
            continue
        if label.get("page_type") is not None:
            ok = got["page_type"] == label["page_type"]
            score.page_type_pairs.append(
                {
                    "case_id": case.case_id,
                    "sample_id": page_id,
                    "expected": label["page_type"],
                    "predicted": got["page_type"],
                }
            )
            score.add(
                "page_type_accuracy", int(ok), 1, page_id,
                f"want {label['page_type']} got {got['page_type']}",
                failure_category=page_type_failure_category(label["page_type"], got["page_type"]),
                expected=label["page_type"], actual=got["page_type"],
                confidence=got["page_type_confidence"],
                diagnostics={"reason": got["diagnostics"]["page_type"]},
            )
        if label.get("content_status") is not None:
            ok = got["content_status"] == label["content_status"]
            score.add(
                "content_status_accuracy", int(ok), 1, page_id,
                f"want {label['content_status']} got {got['content_status']}",
                failure_category="CONTENT_STATUS_WRONG",
                expected=label["content_status"], actual=got["content_status"],
                confidence=got["content_status_confidence"],
                diagnostics={"reason": got["diagnostics"]["content_status"]},
            )
            if label["content_status"] == "CONTENT_OK" and got["content_status"] != "CONTENT_OK":
                score.abstentions += 1
        if label.get("access_status") is not None:
            status = got["content_status"]
            predicted_access = status if status in {
                "ACCESS_RESTRICTED", "PAYWALL", "LOGIN_REQUIRED", "ANTI_BOT", "NOT_FOUND"
            } else "OK"
            ok = predicted_access == label["access_status"]
            score.add(
                "access_status_accuracy", int(ok), 1, page_id,
                f"want {label['access_status']} got {predicted_access}",
                failure_category="ACCESS_PAGE_MISCLASSIFIED",
                expected=label["access_status"], actual=predicted_access,
                confidence=got["content_status_confidence"],
                diagnostics={"reason": got["diagnostics"]["content_status"]},
            )
        if label.get("should_extract_book_metadata") is False:
            emitted = {
                field: got["metadata"].get(field)
                for field in ("book_title", "author")
                if got["metadata"].get(field)
            }
            category = (
                "METADATA_WRONG_TITLE" if "book_title" in emitted
                else "METADATA_WRONG_AUTHOR"
            )
            confidence = max(
                (
                    got["metadata"].get("title_confidence", 0.0),
                    got["metadata"].get("author_confidence", 0.0),
                )
            )
            score.add(
                "metadata_suppression", int(not bool(emitted)), 1, page_id,
                "metadata emitted on a page marked unsafe for metadata",
                failure_category=category, expected={"book_title": None, "author": None},
                actual=emitted, confidence=confidence,
                diagnostics={"unsafe_for_metadata": True},
            )
        if label.get("book_title") is not None:
            ok = got["metadata"].get("book_title") == label["book_title"]
            score.add(
                "book_title_accuracy", int(ok), 1, page_id, "book title mismatch",
                failure_category="METADATA_WRONG_TITLE", expected=label["book_title"],
                actual=got["metadata"].get("book_title"),
                confidence=got["metadata"].get("title_confidence"),
            )
        if label.get("author") is not None:
            ok = got["metadata"].get("author") == label["author"]
            score.add(
                "author_accuracy", int(ok), 1, page_id, "author mismatch",
                failure_category="METADATA_WRONG_AUTHOR", expected=label["author"],
                actual=got["metadata"].get("author"),
                confidence=got["metadata"].get("author_confidence"),
            )
        if label.get("should_extract_content") is True and label.get("content_reference_path"):
            reference = _relative_reference(case, label["content_reference_path"]) or ""
            _compare_text(
                score, page_id, got["content"], reference,
                confidence=got["content_confidence"],
                diagnostics={"reason": got["diagnostics"]["content"]},
                encoding_sensitive=encoding_sensitive,
            )
        if label.get("should_extract_content") is False:
            safe = got["content_status"] != "CONTENT_OK"
            score.add(
                "unsafe_body_rejection", int(safe), 1, page_id,
                "non-body page was accepted as normal content",
                failure_category="CONTENT_FALSE_POSITIVE", expected="reject body",
                actual=got["content_status"], confidence=got["content_status_confidence"],
                diagnostics={"reason": got["diagnostics"]["content_status"]},
            )
        for forbidden in label.get("must_not_export_as_body", []):
            ok = forbidden not in got["exportable_content"]
            score.add(
                "body_noise_exclusion", int(ok), 1, page_id,
                f"forbidden text retained: {forbidden[:40]}",
                failure_category="CONTENT_NOISE_INCLUDED",
                expected={"forbidden_text": forbidden},
                actual={"included": not ok}, confidence=got["content_confidence"],
                diagnostics={"reason": got["diagnostics"]["content"]},
            )

        expected_entries = label.get("catalog_entries") or []
        if expected_entries:
            want = {(item.get("title"), item.get("target_url")) for item in expected_entries}
            actual = {(item.get("title"), item.get("target_url")) for item in got["catalog"]["entries"]}
            catalog_diagnostics = annotate_expected_catalog_group(
                got["diagnostics"]["catalog_candidates"], expected_entries
            )
            recall_ok = len(want & actual) == len(want)
            precision_ok = len(want & actual) == len(actual)
            score.add(
                "catalog_recall", len(want & actual), len(want), page_id,
                "catalog entries missing",
                failure_category="CATALOG_NOT_FOUND" if not actual else "CATALOG_WRONG_GROUP",
                expected=sorted(want), actual=sorted(actual),
                confidence=got["catalog"]["confidence"], diagnostics=catalog_diagnostics,
            )
            score.add(
                "catalog_precision", len(want & actual), len(actual), page_id,
                "unlabelled catalog entries emitted",
                failure_category="CATALOG_WRONG_GROUP",
                expected=sorted(want), actual=sorted(actual),
                confidence=got["catalog"]["confidence"], diagnostics=catalog_diagnostics,
            )
            if not recall_ok or not precision_ok:
                score.catalog_failures.append(
                    {
                        "case_id": case.case_id,
                        "sample_type": score.sample_type,
                        "page_id": page_id,
                        "expected_entries": expected_entries,
                        "actual_entries": got["catalog"]["entries"],
                        **catalog_diagnostics,
                    }
                )
        if label.get("catalog_direction") is not None:
            ok = got["catalog"]["direction"] == label["catalog_direction"]
            score.add(
                "catalog_direction_accuracy", int(ok), 1, page_id,
                "catalog direction mismatch",
                failure_category="CATALOG_WRONG_DIRECTION",
                expected=label["catalog_direction"], actual=got["catalog"]["direction"],
                confidence=got["catalog"]["confidence"],
                diagnostics=got["diagnostics"]["catalog_candidates"],
            )
            if not ok and not any(item["page_id"] == page_id for item in score.catalog_failures):
                score.catalog_failures.append(
                    {
                        "case_id": case.case_id,
                        "sample_type": score.sample_type,
                        "page_id": page_id,
                        "expected_direction": label["catalog_direction"],
                        "actual_direction": got["catalog"]["direction"],
                        **got["diagnostics"]["catalog_candidates"],
                    }
                )

        nav_targets = {
            "PREVIOUS_CHAPTER": got["navigation"].get("previous_chapter"),
            "NEXT_CHAPTER": got["navigation"].get("next_chapter"),
            "CATALOG_LINK": got["navigation"].get("catalog_url"),
        }
        for relation in label.get("relations") or []:
            relation_type = relation.get("type")
            if relation_type in nav_targets:
                ok = nav_targets[relation_type] == relation.get("target_url")
                category = (
                    "CONTENT_PAGINATION_MISSED" if relation_type == "NEXT_CONTENT_PAGE"
                    else "CATALOG_PAGINATION_MISSED" if relation_type == "NEXT_CATALOG_PAGE"
                    else "NAVIGATION_WRONG_RELATION"
                )
                score.add(
                    "navigation_accuracy", int(ok), 1, page_id,
                    f"{relation_type} mismatch", failure_category=category,
                    expected=relation, actual={"target_url": nav_targets[relation_type]},
                    confidence=got["navigation_confidence"],
                    diagnostics={
                        "reason": got["navigation_reason"],
                        "relation_candidates": got["diagnostics"]["pagination_candidates"],
                    },
                )
            elif relation_type in {"NEXT_CONTENT_PAGE", "NEXT_CATALOG_PAGE", "PREVIOUS_CATALOG_PAGE"}:
                candidates = got["diagnostics"]["pagination_candidates"]
                matching = next(
                    (
                        item for item in candidates
                        if item["target_url"] == relation.get("target_url")
                    ),
                    None,
                )
                ok = matching is not None and matching["predicted_relation"] == relation_type
                category = (
                    "CONTENT_PAGINATION_MISSED"
                    if relation_type == "NEXT_CONTENT_PAGE"
                    else "CATALOG_PAGINATION_MISSED"
                )
                score.add(
                    "pagination_relation_accuracy", int(ok), 1, page_id,
                    f"{relation_type} mismatch", failure_category=category,
                    expected=relation,
                    actual=matching or {"predicted_relation": None, "target_url": None},
                    confidence=matching.get("relation_confidence") if matching else None,
                    diagnostics={"relation_candidates": candidates},
                )
                if not ok:
                    score.pagination_failures.append(
                        {
                            "case_id": case.case_id,
                            "sample_type": score.sample_type,
                            "page_id": page_id,
                            "expected_relation": relation,
                            "parser_selected_relation": matching,
                            "candidates": candidates,
                        }
                    )

    logical = expected.get("logical_chapters") or []
    crawl = prediction.get("crawl")
    if logical and crawl is not None:
        predicted_chapters = crawl.get("chapters") or []
        for index, chapter in enumerate(logical):
            sample = chapter["chapter_id"]
            got = predicted_chapters[index] if index < len(predicted_chapters) else None
            if got is None:
                score.add(
                    "logical_chapter_presence", 0, 1, sample, "logical chapter missing",
                    failure_category="CHAPTER_MISSING", expected=chapter, actual=None,
                    diagnostics={"crawler_warnings": crawl.get("warnings", [])},
                )
                continue
            score.add("logical_chapter_presence", 1, 1, sample)
            expected_page_ids = chapter.get("source_page_ids") or []
            expected_urls = [case.pages_by_id[item]["requested_url"] for item in expected_page_ids]
            ok_pages = got.get("source_urls") == expected_urls
            actual_urls = got.get("source_urls") or []
            pagination_category = (
                "CONTENT_PAGINATION_OVERMERGED"
                if any(item not in expected_urls for item in actual_urls)
                else "CONTENT_PAGINATION_MISSED"
            )
            score.add(
                "pagination_merge_accuracy", int(ok_pages), 1, sample,
                f"want pages {expected_urls} got {got.get('source_urls')}",
                failure_category=pagination_category,
                expected={"source_urls": expected_urls}, actual={"source_urls": actual_urls},
                diagnostics={"crawler_warnings": crawl.get("warnings", [])},
            )
            if not ok_pages:
                score.pagination_failures.append(
                    {
                        "case_id": case.case_id,
                        "sample_type": score.sample_type,
                        "logical_chapter_id": sample,
                        "expected_source_urls": expected_urls,
                        "actual_source_urls": actual_urls,
                        "failure_category": pagination_category,
                        "candidates_by_page": {
                            page_item: prediction["pages"][page_item]["diagnostics"]["pagination_candidates"]
                            for page_item in expected_page_ids
                            if page_item in prediction["pages"]
                        },
                    }
                )
            if chapter.get("reference_text_path"):
                reference = _relative_reference(case, chapter["reference_text_path"]) or ""
                _compare_text(
                    score, f"logical:{sample}", got.get("content", ""), reference,
                    diagnostics={"source_urls": got.get("source_urls")},
                    encoding_sensitive=encoding_sensitive,
                )
        expected_order = expected.get("expected_reading_order") or []
        if expected_order:
            actual_count = min(len(predicted_chapters), len(logical))
            actual_order = [logical[index]["chapter_id"] for index in range(actual_count)]
            ok = actual_order == expected_order and len(predicted_chapters) == len(expected_order)
            score.add(
                "reading_chain_exact", int(ok), 1, case.case_id,
                "logical reading chain differs", failure_category="READING_ORDER_WRONG",
                expected=expected_order, actual=actual_order,
                diagnostics={"predicted_chapter_count": len(predicted_chapters)},
            )

    export_expectation = expected.get("expected_export") or {}
    if export_expectation.get("must_report_missing_chapters") is True:
        warnings = (crawl or {}).get("warnings", [])
        reported = any("failed" in item.lower() or "失败" in item or "missing" in item.lower() for item in warnings)
        score.add(
            "partial_failure_reported", int(reported), 1, case.case_id,
            "missing fixture was not reported",
            failure_category="EXPORT_INCOMPLETE_NOT_REPORTED",
            expected={"must_report_missing_chapters": True}, actual={"warnings": warnings},
        )
    return score


def _metric_payload(samples: list[tuple[float, float, str]], abstentions: int = 0) -> dict[str, Any]:
    numerator = sum(item[0] for item in samples)
    denominator = sum(item[1] for item in samples)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": round(numerator / denominator, 6) if denominator else None,
        "sample_count": len(samples),
        "abstention_count": abstentions,
    }


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_state() -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, check=True,
            capture_output=True, text=True,
        ).stdout.strip())
        return commit, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def _confusion_payload(pairs: list[dict[str, str]]) -> dict[str, Any]:
    labels = ("BOOK_PAGE", "CATALOG_PAGE", "CHAPTER_PAGE", "UNKNOWN")
    matrix = {expected: {predicted: 0 for predicted in labels} for expected in labels}
    misclassifications: list[dict[str, str]] = []
    for pair in pairs:
        expected = pair["expected"]
        predicted = pair["predicted"]
        if expected not in matrix:
            matrix[expected] = {item: 0 for item in labels}
        if predicted not in matrix[expected]:
            matrix[expected][predicted] = 0
        matrix[expected][predicted] += 1
        if expected != predicted:
            misclassifications.append(pair)
    return {
        "labels": list(labels),
        "matrix": matrix,
        "misclassifications": misclassifications,
        "misclassified_case_ids": sorted({item["case_id"] for item in misclassifications}),
    }


def run_all(
    cases_dir: Path = CASES_DIR,
    sample_types: set[str] | None = None,
) -> dict[str, Any]:
    case_paths = sorted(cases_dir.glob("*/case.json"))
    report_cases: dict[str, Any] = {}
    suite_metrics: dict[str, dict[str, list[tuple[float, float, str]]]] = defaultdict(lambda: defaultdict(list))
    site_metrics: dict[str, dict[str, list[tuple[float, float, str]]]] = defaultdict(lambda: defaultdict(list))
    sample_type_metrics: dict[str, dict[str, list[tuple[float, float, str]]]] = defaultdict(lambda: defaultdict(list))
    suite_abstentions: dict[str, int] = defaultdict(int)
    site_abstentions: dict[str, int] = defaultdict(int)
    sample_type_abstentions: dict[str, int] = defaultdict(int)
    total_abstentions = 0
    all_metrics: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    all_failures: list[dict[str, Any]] = []
    page_type_pairs: list[dict[str, str]] = []
    catalog_failures: list[dict[str, Any]] = []
    pagination_failures: list[dict[str, Any]] = []
    inventory_by_sample_type: dict[str, int] = defaultdict(int)
    inventory_by_provenance: dict[str, int] = defaultdict(int)
    invalid = 0
    executed = 0
    deferred = 0
    eligible = 0
    filtered_out = 0
    dataset_files: list[Path] = []

    for case_path in case_paths:
        case: OfflineCase | None = None
        try:
            case_header = _read_json(case_path)
        except (OSError, ValueError, TypeError) as exc:
            invalid += 1
            report_cases[case_path.parent.name] = {"status": "INVALID", "error": str(exc)}
            continue
        if case_header.get("annotation_status") != "READY":
            deferred += 1
            report_cases[case_path.parent.name] = {
                "status": "DEFERRED",
                "reason": f"annotation_status={case_header.get('annotation_status')}",
            }
            continue
        inventory_sample_type = sample_type_for(case_header)
        inventory_by_sample_type[inventory_sample_type] += 1
        inventory_by_provenance[case_header.get("source_type", "unknown")] += 1
        if sample_types is not None and inventory_sample_type not in sample_types:
            filtered_out += 1
            continue
        try:
            case = load_case(case_path)
        except CaseValidationError as exc:
            invalid += 1
            report_cases[case_path.parent.name] = {"status": "INVALID", "error": str(exc)}
            continue
        dataset_files.extend(path for path in case.case_dir.rglob("*") if path.is_file())
        dataset_files.extend(path for path in case.input_root.rglob("*") if path.is_file())
        try:
            prediction = _prediction_for_case(case)
            score = _evaluate(case, prediction)
            sample_type = sample_type_for(case.data)
            eligible += 1
            executed += 1
            status = "PASS" if not score.failures else "FAIL"
            report_cases[case.case_id] = {
                "status": status,
                "site_id": case.data["site_id"],
                "suite": case.data["suite"],
                "sample_type": sample_type,
                "source_provenance": case.data.get("source_type"),
                "input_modes": sorted({page["input_kind"] for page in case.pages_by_id.values()}),
                "page_count": len(case.pages_by_id),
                "metrics": {
                    name: _metric_payload(
                        values, score.abstentions if name.startswith("content_") else 0
                    )
                    for name, values in score.values.items()
                },
                "abstention_count": score.abstentions,
                "failures": score.failures,
                "prediction": prediction,
            }
            for name, values in score.values.items():
                all_metrics[name].extend(values)
                suite_metrics[case.data["suite"]][name].extend(values)
                site_metrics[case.data["site_id"]][name].extend(values)
                sample_type_metrics[sample_type][name].extend(values)
            total_abstentions += score.abstentions
            suite_abstentions[case.data["suite"]] += score.abstentions
            site_abstentions[case.data["site_id"]] += score.abstentions
            sample_type_abstentions[sample_type] += score.abstentions
            all_failures.extend(score.failures)
            page_type_pairs.extend(score.page_type_pairs)
            catalog_failures.extend(score.catalog_failures)
            pagination_failures.extend(score.pagination_failures)
        except CaseValidationError as exc:
            invalid += 1
            report_cases[case_path.parent.name] = {
                "status": "INVALID",
                "error": str(exc),
            }
        except Exception as exc:  # noqa: BLE001 - benchmark must record framework/runtime failures
            key = case.case_id if case is not None else case_path.parent.name
            report_cases[key] = {
                "status": "ERROR",
                "site_id": case.data["site_id"] if case is not None else None,
                "suite": case.data["suite"] if case is not None else None,
                "sample_type": sample_type_for(case.data) if case is not None else None,
                "error": f"{type(exc).__name__}: {exc}",
                "failures": [
                    {
                        "case_id": key,
                        "sample_type": sample_type_for(case.data) if case is not None else "unknown",
                        "sample_id": key,
                        "metric": "benchmark_execution",
                        "expected_result": "offline inference completes",
                        "actual_result": f"{type(exc).__name__}: {exc}",
                        "confidence": None,
                        "failure_category": "FETCH_ERROR",
                        "relevant_diagnostics": {},
                        "message": "benchmark case could not be executed",
                    }
                ],
            }
            all_failures.extend(report_cases[key]["failures"])

    commit, dirty = _git_state()
    suites = {}
    suite_names = (
        "CN_STATIC_CONTENT", "CN_ACCESS_STATE", "CN_DYNAMIC_INPUT", "CROSS_LANGUAGE",
        "NON_HTML_NEGATIVE", "ENCODING", "SYNTHETIC_REGRESSION",
    )
    for suite in suite_names:
        case_count = sum(1 for item in report_cases.values() if item.get("suite") == suite)
        suites[suite] = {
            "case_count": case_count,
            "metrics": {
                name: _metric_payload(
                    values, suite_abstentions[suite] if name.startswith("content_") else 0
                )
                for name, values in suite_metrics.get(suite, {}).items()
            } or None,
        }
    results_by_sample_type = {}
    for sample_type in ("synthetic", "real_fixture", "challenge", "dynamic"):
        case_count = sum(
            1 for item in report_cases.values() if item.get("sample_type") == sample_type
        )
        results_by_sample_type[sample_type] = {
            "case_count": case_count,
            "metrics": {
                name: _metric_payload(
                    values,
                    sample_type_abstentions[sample_type] if name.startswith("content_") else 0,
                )
                for name, values in sample_type_metrics.get(sample_type, {}).items()
            } or None,
        }
    failed = sum(1 for item in report_cases.values() if item.get("status") in {"FAIL", "ERROR"})
    if executed == 0 and invalid == 0:
        run_status = "NO_ELIGIBLE_CASES"
    elif not failed and not invalid:
        run_status = "PASS"
    else:
        run_status = "COMPLETED_WITH_FAILURES"
    taxonomy_distribution = {
        category: sum(1 for failure in all_failures if failure["failure_category"] == category)
        for category in FAILURE_TAXONOMY
    }
    taxonomy_case_ids = {
        category: sorted(
            {
                failure["case_id"]
                for failure in all_failures
                if failure["failure_category"] == category
            }
        )
        for category in FAILURE_TAXONOMY
    }
    return {
        "schema_version": "1.0.0",
        "document_type": "benchmark_report",
        "run_status": run_status,
        "run_id": datetime.now().strftime("offline-%Y%m%d-%H%M%S"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "code_commit": commit,
        "code_dirty": dirty,
        "dataset_version": "synthetic-contract-v1",
        "dataset_hash": _hash_files(list(dict.fromkeys(dataset_files))) if dataset_files else None,
        "dependency_lock_hash": None,
        "dependency_manifest_hash": _hash_files([PROJECT_ROOT / "pyproject.toml"]),
        "configuration_hash": hashlib.sha256(b"offline,cold-cache,no-network,v1").hexdigest(),
        "network_allowed": False,
        "input_mode": "case-declared mixed offline inputs",
        "cache_mode": "cold",
        "dataset_split": "development",
        "case_counts": {
            "eligible": eligible, "executed": executed, "invalid": invalid,
            "deferred": deferred, "filtered_out": filtered_out, "failed": failed,
        },
        "results_by_suite": suites,
        "results_by_sample_type": results_by_sample_type,
        "dataset_counts": {
            "synthetic_cases": inventory_by_sample_type.get("synthetic", 0),
            "real_fixture_cases": inventory_by_sample_type.get("real_fixture", 0),
            "challenge_cases": inventory_by_sample_type.get("challenge", 0),
            "dynamic_cases": inventory_by_sample_type.get("dynamic", 0),
            "source_provenance": dict(sorted(inventory_by_provenance.items())),
        },
        "metrics": {
            name: _metric_payload(
                values, total_abstentions if name.startswith("content_") else 0
            )
            for name, values in all_metrics.items()
        },
        "abstention_count": total_abstentions,
        "macro_by_site": {
            site_id: {
                name: _metric_payload(
                    values, site_abstentions[site_id] if name.startswith("content_") else 0
                )
                for name, values in metrics.items()
            }
            for site_id, metrics in site_metrics.items()
        },
        "micro_by_page": {
            name: _metric_payload(
                values, total_abstentions if name.startswith("content_") else 0
            )
            for name, values in all_metrics.items()
        },
        "page_type_confusion": _confusion_payload(page_type_pairs),
        "failure_taxonomy": {
            "definitions": list(FAILURE_TAXONOMY),
            "distribution": taxonomy_distribution,
            "case_ids_by_category": taxonomy_case_ids,
        },
        "per_case_failures": all_failures,
        "catalog_failure_analysis": catalog_failures,
        "pagination_failure_analysis": pagination_failures,
        "cases": report_cases,
        "limitations": [
            "Only project-authored synthetic cases were executed.",
            "No real website support or whole-book completeness is claimed.",
            "BROWSER_DOM and real HTTP capture groups currently have zero eligible cases.",
            "The repository has no dependency lock file; dependency_lock_hash is null and pyproject.toml is recorded separately.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run contract-based offline benchmark cases.")
    parser.add_argument("--cases-dir", type=Path, default=CASES_DIR)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "local")
    parser.add_argument("--report-file", type=Path, default=None)
    parser.add_argument(
        "--sample-type",
        action="append",
        choices=("synthetic", "real_fixture", "challenge", "dynamic"),
        help="Run only this exclusive reporting category; may be repeated.",
    )
    args = parser.parse_args()
    report = run_all(args.cases_dir, set(args.sample_type) if args.sample_type else None)
    if args.report_file is not None:
        out = args.report_file
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        out = args.report_dir / f"contract-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"offline benchmark report -> {out}")
    print(json.dumps(report["case_counts"], ensure_ascii=False))
    for case_id, item in report["cases"].items():
        print(f"  [{item['status']}] {case_id}")
        for failure in item.get("failures", []):
            print(
                f"      - {failure['failure_category']}: {failure['metric']}: "
                f"{failure['sample_id']}: {failure['message']}"
            )
        if item.get("error"):
            print(f"      - {item['error']}")
    return 0 if report["run_status"] in {"PASS", "NO_ELIGIBLE_CASES"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

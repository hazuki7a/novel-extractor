"""Contract and isolation tests for the offline benchmark framework."""

from __future__ import annotations

import json
import shutil
import socket
import sys
from pathlib import Path

import pytest


BENCHMARKS = Path(__file__).resolve().parent.parent / "benchmarks"
sys.path.insert(0, str(BENCHMARKS))

from offline_contract import (  # noqa: E402
    CaseValidationError,
    OfflineFixtureFetcher,
    load_case,
    load_expected,
)
import offline_runner  # noqa: E402
from offline_runner import run_all  # noqa: E402
from failure_diagnostics import FAILURE_TAXONOMY  # noqa: E402
from reporting import build_failure_analysis, render_failure_analysis_markdown  # noqa: E402


def _case_paths():
    return sorted((BENCHMARKS / "cases").glob("*/case.json"))


def test_ready_contract_cases_validate_and_templates_are_not_cases():
    paths = _case_paths()
    assert len(paths) == 8
    cases = [load_case(path) for path in paths]
    for case in cases:
        load_expected(case)
    assert all(case.data["source_type"] == "synthetic" for case in cases)
    assert all("templates" not in str(case.case_dir) for case in cases)


def test_http_bytes_use_saved_metadata_and_project_decoder():
    case = load_case(BENCHMARKS / "cases" / "syn_encoding_bytes" / "case.json")
    page = OfflineFixtureFetcher(case).fetch("https://synthetic.invalid/encoding/gb")
    assert "龘字编码正文" in page.html
    assert page.status_code == 200
    assert page.headers["content-type"] == "text/html; charset=gb18030"
    assert page.diagnostics["offline_input_kind"] == "HTTP_BYTES"


def test_fragment_urls_remain_distinct_while_reusing_one_document():
    case = load_case(BENCHMARKS / "cases" / "syn_fragment_identity" / "case.json")
    fetcher = OfflineFixtureFetcher(case)
    first = fetcher.fetch("https://synthetic.invalid/fragments/book#c1")
    second = fetcher.fetch("https://synthetic.invalid/fragments/book#c2")
    assert first.raw_bytes == second.raw_bytes
    assert first.final_url.endswith("#c1")
    assert second.final_url.endswith("#c2")


def test_missing_url_is_reported_and_never_fetched_from_network(monkeypatch):
    case = load_case(BENCHMARKS / "cases" / "syn_partial_failure" / "case.json")
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network used"))
    with pytest.raises(Exception, match="outside captured scope"):
        OfflineFixtureFetcher(case).fetch("https://synthetic.invalid/partial/missing-chapter")


def test_prediction_phase_does_not_open_expected_labels(monkeypatch):
    case = load_case(BENCHMARKS / "cases" / "syn_access_states" / "case.json")
    monkeypatch.setattr(
        offline_runner,
        "load_expected",
        lambda *_args, **_kwargs: pytest.fail("gold labels opened during inference"),
    )
    prediction = offline_runner._prediction_for_case(case)
    assert prediction["case_id"] == "syn_access_states"


def test_ready_validation_rejects_hash_mismatch(tmp_path):
    source_case = BENCHMARKS / "cases" / "syn_access_states"
    source_fixture = BENCHMARKS / "fixtures" / "synthetic" / "syn_access_states"
    case_dir = tmp_path / "cases" / "syn_access_states"
    fixture_dir = tmp_path / "fixtures" / "synthetic" / "syn_access_states"
    shutil.copytree(source_case, case_dir)
    shutil.copytree(source_fixture, fixture_dir)
    data = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    data["input_root"] = "../../fixtures/synthetic/syn_access_states"
    (case_dir / "case.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (fixture_dir / "challenge_403.bin").write_bytes(b"tampered")
    with pytest.raises(CaseValidationError, match="SHA-256 mismatch"):
        load_case(case_dir / "case.json")


def test_contract_runner_is_offline_and_reports_zero_denominators_as_na(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", lambda *args, **kwargs: pytest.fail("network used"))
    report = run_all(BENCHMARKS / "cases")
    assert report["network_allowed"] is False
    assert report["case_counts"]["eligible"] == 8
    assert report["case_counts"]["executed"] == 8
    assert report["case_counts"]["invalid"] == 0
    assert report["results_by_suite"]["CN_STATIC_CONTENT"]["case_count"] == 0
    assert report["results_by_suite"]["CN_STATIC_CONTENT"]["metrics"] is None
    assert report["results_by_suite"]["SYNTHETIC_REGRESSION"]["case_count"] == 8
    assert report["limitations"]


def test_failure_records_are_typed_and_include_required_diagnostics():
    report = run_all(BENCHMARKS / "cases")
    assert report["per_case_failures"]
    required = {
        "case_id", "sample_type", "expected_result", "actual_result", "confidence",
        "failure_category", "relevant_diagnostics",
    }
    for failure in report["per_case_failures"]:
        assert required <= failure.keys()
        assert failure["failure_category"] in FAILURE_TAXONOMY
    assert set(FAILURE_TAXONOMY) == set(report["failure_taxonomy"]["definitions"])


def test_page_type_confusion_and_sample_types_are_separate():
    report = run_all(BENCHMARKS / "cases")
    matrix = report["page_type_confusion"]
    assert sum(sum(row.values()) for row in matrix["matrix"].values()) == 23
    assert matrix["misclassifications"]
    assert report["results_by_sample_type"]["synthetic"]["case_count"] == 7
    assert report["results_by_sample_type"]["challenge"]["case_count"] == 1
    assert report["results_by_sample_type"]["real_fixture"]["case_count"] == 0
    assert report["results_by_sample_type"]["real_fixture"]["metrics"] is None


def test_catalog_and_pagination_failure_details_expose_candidates():
    report = run_all(BENCHMARKS / "cases")
    catalog = report["catalog_failure_analysis"]
    assert catalog
    assert any(item.get("candidates") for item in catalog)
    candidate = next(item["candidates"][0] for item in catalog if item.get("candidates"))
    assert {
        "candidate_id", "parent_dom_path", "link_count", "chapter_title_match_count",
        "chapter_title_match_ratio", "average_anchor_text_length", "link_text_ratio",
        "dom_depth", "url_similarity", "final_score", "positive_reasons", "penalties",
    } <= candidate.keys()
    pagination = report["pagination_failure_analysis"]
    assert pagination
    all_candidates = []
    for item in pagination:
        all_candidates.extend(item.get("candidates") or [])
        for candidates in (item.get("candidates_by_page") or {}).values():
            all_candidates.extend(candidates)
    assert all_candidates
    assert {
        "anchor_text", "target_url", "predicted_relation", "relation_confidence",
        "positive_reasons", "penalties",
    } <= all_candidates[0].keys()


def test_empty_real_fixture_run_is_na_not_a_synthetic_substitute():
    report = run_all(BENCHMARKS / "cases", {"real_fixture"})
    assert report["run_status"] == "NO_ELIGIBLE_CASES"
    assert report["case_counts"]["executed"] == 0
    assert report["results_by_sample_type"]["real_fixture"]["metrics"] is None
    assert report["metrics"] == {}


def test_failure_analysis_contains_required_sections():
    report = run_all(BENCHMARKS / "cases")
    analysis = build_failure_analysis(report)
    assert analysis["baseline_version"] == "baseline_v0"
    assert analysis["metric_counts"]
    assert analysis["catalog_failure_details"]
    assert analysis["pagination_failure_details"]
    assert analysis["uncovered_structure_types"]
    assert len(analysis["next_priority_problem_classes"]) == 3
    markdown = render_failure_analysis_markdown(analysis)
    assert "Page type confusion matrix" in markdown
    assert "Catalog failure details" in markdown
    assert "Pagination relation failure details" in markdown

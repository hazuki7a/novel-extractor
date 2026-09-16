"""Benchmark regression gate (guide task 16).

Runs the local benchmark suite in-process and fails when key metrics drop
below thresholds. The benchmark itself never touches the network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCHMARKS_DIR = Path(__file__).resolve().parent.parent / "benchmarks"
sys.path.insert(0, str(BENCHMARKS_DIR))

from runner import run_all  # noqa: E402

# Metric name -> minimum acceptable value. Tighten as fixtures grow; loosen
# only with an explanation in the commit message (guide regression_policy).
THRESHOLDS = {
    "page_classification": 0.95,
    "metadata": 0.95,
    "catalog_detected": 1.00,
    "catalog_direction": 1.00,
    "chapter_recall": 1.00,
    "catalog_pagination": 1.00,
    "chapter_order": 1.00,
    "content_success": 0.90,
    "content_pagination": 1.00,
    "restricted_status": 1.00,
    "navigation": 1.00,
    "catalog_false_positive": 1.00,
    "catalog_expansion": 1.00,
}

MIN_SITES = 12


@pytest.fixture(scope="module")
def benchmark_report():
    return run_all(BENCHMARKS_DIR / "sites")


def test_benchmark_sites_present(benchmark_report):
    assert len(benchmark_report["sites"]) >= MIN_SITES


@pytest.mark.parametrize("metric,minimum", sorted(THRESHOLDS.items()))
def test_metric_threshold(benchmark_report, metric, minimum):
    value = benchmark_report["metrics"].get(metric, 0.0)
    assert value >= minimum, (
        f"benchmark metric {metric}={value} < {minimum}; "
        f"see per-site failures in the report JSON"
    )

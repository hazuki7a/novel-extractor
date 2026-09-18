#!/usr/bin/env python3
"""Validate this collection plan only. No network requests or extraction tests."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def validate_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    sites = plan.get("sites")
    if not isinstance(sites, list):
        return ["sites must be a list"]
    if any(not isinstance(site, dict) for site in sites):
        return ["Each site entry must be an object"]
    sources = plan.get("sources", {})
    feature_definitions = plan.get("feature_definitions", {})
    ids = [s.get("id") for s in sites]
    if any(not isinstance(sid, str) or not sid for sid in ids):
        return ["Each site must have a nonempty string id"]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate site id")
    expected_count = plan.get("summary", {}).get("candidate_count")
    if expected_count != len(sites):
        errors.append("Candidate count does not match sites")
    pools = Counter(s.get("candidate_pool") for s in sites)
    if pools["CN_PRIMARY"] != plan.get("summary", {}).get("chinese_primary_candidates"):
        errors.append("Chinese candidate count mismatch")
    if pools["SPECIAL"] != plan.get("summary", {}).get("special_candidates"):
        errors.append("Special candidate count mismatch")

    known_ids = set(ids)
    for site in sites:
        label = str(site.get("id"))
        for field, url in [("entry_url", site.get("entry_url"))] + [
            ("seed_page", p.get("url")) for p in site.get("seed_pages", [])
        ]:
            parsed = urlsplit(url or "")
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                errors.append(f"{label}: invalid {field}")
        for ref in site.get("source_review", {}).get("source_ids", []):
            if ref not in sources:
                errors.append(f"{label}: unknown source {ref}")
        for feature in site.get("test_hypotheses", []):
            if feature not in feature_definitions:
                errors.append(f"{label}: missing feature definition {feature}")
        count = site.get("actual_fixture_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"{label}: invalid actual_fixture_count")
        if site.get("live_fetch", {}).get("enabled_by_default") is not False:
            errors.append(f"{label}: live fetching must be opt-in")
        # Source review is not a local extractor test.
        if site.get("source_review", {}).get("local_extractor_tested") and count == 0:
            errors.append(f"{label}: local test claim without fixtures")

    for item in plan.get("coverage_plan", []):
        for site_id in item.get("candidate_site_ids", []):
            if site_id not in known_ids:
                errors.append(f"Unknown site in coverage plan: {site_id}")
        if item.get("coverage_status") == "CONFIRMED" and not item.get("evidence_case_ids"):
            errors.append(f"Confirmed coverage lacks evidence: {item.get('feature')}")

    defaults = plan.get("global_defaults", {})
    for key in (
        "network_allowed_during_offline_tests",
        "automatically_crawl_site_entries",
        "site_hints_allowed_as_parser_input",
        "expected_labels_allowed_as_parser_input",
    ):
        if defaults.get(key) is not False:
            errors.append(f"{key} must be false")
    if plan.get("not_a_completed_dataset") is not True:
        errors.append("Collection-plan limitation must be explicit")
    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    try:
        plan = json.loads((root / "benchmark_sites.json").read_text(encoding="utf-8"))
        errors = validate_plan(plan)
        for name in ("case.template.json", "expected.template.json", "report.template.json"):
            item = json.loads((root / "templates" / name).read_text(encoding="utf-8"))
            if not str(item.get("document_type", "")).endswith("_template"):
                errors.append(f"{name}: template marker missing")
        for name in ("BENCHMARK_GUIDE.md", "CODEX_TASK.md"):
            if not (root / name).is_file():
                errors.append(f"Missing document: {name}")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"PLAN_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"PLAN_VALIDATION_OK: {len(plan['sites'])} candidate sources")
    print(f"Real captured HTML fixtures: {plan['summary']['collected_real_html_fixtures']}")
    print("No network access or extractor evaluation was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Render frozen benchmark and failure-analysis reports.

This module consumes an already evaluated report.  It never reads or writes
``expected.json`` and does not call the parser.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def _metric_rows(metrics: dict[str, Any] | None) -> list[str]:
    if not metrics:
        return ["| — | 0 | 0 | N/A | 0 |"]
    rows = []
    for name, item in sorted(metrics.items()):
        value = "N/A" if item["value"] is None else f"{item['value']:.6f}"
        rows.append(
            f"| `{name}` | {item['numerator']} | {item['denominator']} | "
            f"{value} | {item['sample_count']} |"
        )
    return rows


def _uncovered_structures(plan_path: Path) -> list[dict[str, Any]]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    return [
        {
            "feature": item["feature"],
            "suite": item["suite"],
            "phase": item["phase"],
            "candidate_site_ids": item.get("candidate_site_ids") or [],
            "coverage_status": item["coverage_status"],
            "action": item["action"],
        }
        for item in plan.get("coverage_plan", [])
        if item.get("coverage_status") != "CAPTURED"
    ]


def _priority_groups(report: dict[str, Any]) -> list[dict[str, Any]]:
    distribution = report["failure_taxonomy"]["distribution"]
    groups = [
        (
            "目录发现、分组、方向与目录分页",
            ("CATALOG_NOT_FOUND", "CATALOG_WRONG_GROUP", "CATALOG_WRONG_DIRECTION", "CATALOG_PAGINATION_MISSED"),
            "先用候选组诊断确认通用结构性缺口；不得加入 host/class/id 特例。",
        ),
        (
            "正文保留、噪声与章节内分页边界",
            ("CONTENT_TRUNCATED", "CONTENT_NOISE_INCLUDED", "CONTENT_PAGINATION_MISSED", "CONTENT_PAGINATION_OVERMERGED"),
            "优先检查跨页关系和正文边界是否可由通用证据区分。",
        ),
        (
            "访问页安全分类与元数据抑制",
            ("ACCESS_PAGE_MISCLASSIFIED", "CONTENT_STATUS_WRONG", "METADATA_WRONG_TITLE", "METADATA_WRONG_AUTHOR"),
            "安全失败会产生伪正文或伪书名，应在通用特征层处理。",
        ),
        (
            "编码冲突",
            ("ENCODING_ERROR",),
            "以人工确认文本为真值，编码名称本身不作为唯一成功标准。",
        ),
    ]
    ranked = []
    for title, categories, rationale in groups:
        count = sum(distribution.get(category, 0) for category in categories)
        if count:
            ranked.append(
                {
                    "problem": title,
                    "failure_count": count,
                    "categories": list(categories),
                    "rationale": rationale,
                }
            )
    ranked.sort(key=lambda item: (-item["failure_count"], item["problem"]))
    return ranked[:3]


def build_failure_analysis(
    baseline: dict[str, Any],
    plan_path: Path = ROOT / "benchmark_sites.json",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "document_type": "failure_analysis",
        "baseline_version": "baseline_v0",
        "baseline_run_id": baseline["run_id"],
        "generated_at": baseline["generated_at"],
        "network_allowed": baseline["network_allowed"],
        "baseline_metrics": baseline["metrics"],
        "metric_counts": {
            name: {
                "success": item["numerator"],
                "failure": item["denominator"] - item["numerator"],
                "denominator": item["denominator"],
                "sample_count": item["sample_count"],
                "abstention_count": item["abstention_count"],
            }
            for name, item in baseline["metrics"].items()
        },
        "results_by_suite": baseline["results_by_suite"],
        "results_by_sample_type": baseline["results_by_sample_type"],
        "dataset_counts": baseline["dataset_counts"],
        "page_type_confusion": baseline["page_type_confusion"],
        "failure_taxonomy": baseline["failure_taxonomy"],
        "per_case_failures": baseline["per_case_failures"],
        "catalog_failure_details": baseline["catalog_failure_analysis"],
        "pagination_failure_details": baseline["pagination_failure_analysis"],
        "uncovered_structure_types": _uncovered_structures(plan_path),
        "next_priority_problem_classes": _priority_groups(baseline),
        "limitations": baseline["limitations"],
        "guardrails": [
            "expected.json was treated as human ground truth and was not modified.",
            "Inference completed before the evaluator opened expected.json.",
            "No live network access was used.",
            "No parser weights or core recognition algorithms were changed.",
            "Synthetic, real_fixture, challenge, and dynamic results remain separate.",
        ],
    }


def render_baseline_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# baseline_v0",
        "",
        f"- Run status: `{report['run_status']}`",
        f"- Run id: `{report['run_id']}`",
        f"- Network allowed: `{str(report['network_allowed']).lower()}`",
        f"- Code commit: `{report['code_commit']}`",
        f"- Code dirty: `{report['code_dirty']}`",
        f"- Dataset hash: `{report['dataset_hash']}`",
        "",
        "## Dataset counts",
        "",
    ]
    for name, count in report["dataset_counts"].items():
        lines.append(f"- {name}: `{count}`")
    lines.extend(
        [
            "",
            "## Overall metrics",
            "",
            "| Metric | Success/numerator | Denominator | Value | Samples |",
            "|---|---:|---:|---:|---:|",
            *_metric_rows(report["metrics"]),
            "",
            "## Results by sample type",
            "",
        ]
    )
    for sample_type, payload in report["results_by_sample_type"].items():
        lines.extend(
            [
                f"### {sample_type}",
                "",
                f"Case count: `{payload['case_count']}`",
                "",
                "| Metric | Success/numerator | Denominator | Value | Samples |",
                "|---|---:|---:|---:|---:|",
                *_metric_rows(payload["metrics"]),
                "",
            ]
        )
    lines.extend(
        [
            "## Baseline policy",
            "",
            "This is the frozen comparison point for later algorithm changes. "
            "A zero denominator is N/A, not 100%. Categories are not merged into one success rate.",
            "",
        ]
    )
    return "\n".join(lines)

def _safe_cell(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text.replace("|", "\\|").replace("\n", " ")


def render_failure_analysis_markdown(analysis: dict[str, Any]) -> str:
    counts = analysis["dataset_counts"]
    lines = [
        "# Benchmark Failure Analysis",
        "",
        f"Baseline: `baseline_v0` (`{analysis['baseline_run_id']}`)",
        "",
        "The run was offline. Results below keep synthetic, real_fixture, challenge, and dynamic cases separate.",
        "",
        "## Dataset counts",
        "",
        f"- Synthetic: `{counts['synthetic_cases']}`",
        f"- Real fixture: `{counts['real_fixture_cases']}`",
        f"- Challenge: `{counts['challenge_cases']}`",
        f"- Dynamic: `{counts['dynamic_cases']}`",
        "",
        "The challenge case is synthetic by provenance but is excluded from the ordinary synthetic reporting bucket.",
        "",
        "## Baseline metric counts",
        "",
        "| Metric | Success | Failure | Denominator | Samples | Abstentions |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, item in sorted(analysis["metric_counts"].items()):
        lines.append(
            f"| `{name}` | {item['success']} | {item['failure']} | {item['denominator']} | "
            f"{item['sample_count']} | {item['abstention_count']} |"
        )

    confusion = analysis["page_type_confusion"]
    labels = confusion["labels"]
    lines.extend(
        [
            "",
            "## Page type confusion matrix",
            "",
            "Rows are expected labels; columns are predicted labels.",
            "",
            "| Expected \\ Predicted | " + " | ".join(labels) + " |",
            "|---|" + "---:|" * len(labels),
        ]
    )
    for expected in labels:
        lines.append(
            f"| {expected} | "
            + " | ".join(str(confusion["matrix"][expected].get(predicted, 0)) for predicted in labels)
            + " |"
        )
    lines.extend(["", "Misclassifications:", ""])
    if confusion["misclassifications"]:
        for item in confusion["misclassifications"]:
            lines.append(
                f"- `{item['case_id']} / {item['sample_id']}`: "
                f"{item['expected']} -> {item['predicted']}"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Failure taxonomy distribution",
            "",
            "| Category | Count | Case ids |",
            "|---|---:|---|",
        ]
    )
    taxonomy = analysis["failure_taxonomy"]
    for category in taxonomy["definitions"]:
        ids = ", ".join(f"`{item}`" for item in taxonomy["case_ids_by_category"][category]) or "—"
        lines.append(f"| `{category}` | {taxonomy['distribution'][category]} | {ids} |")

    lines.extend(["", "## Per-case failure diagnostics", ""])
    for failure in analysis["per_case_failures"]:
        lines.extend(
            [
                f"### {failure['case_id']} / {failure['sample_id']}",
                "",
                f"- Sample type: `{failure['sample_type']}`",
                f"- Metric: `{failure['metric']}`",
                f"- Failure category: `{failure['failure_category']}`",
                f"- Confidence: `{failure['confidence']}`",
                f"- Expected: `{_safe_cell(failure['expected_result'])}`",
                f"- Actual: `{_safe_cell(failure['actual_result'])}`",
                f"- Diagnostics: `{_safe_cell(failure['relevant_diagnostics'])}`",
                "",
            ]
        )

    lines.extend(["## Catalog failure details", ""])
    if not analysis["catalog_failure_details"]:
        lines.append("No catalog failures.")
    for detail in analysis["catalog_failure_details"]:
        lines.extend(
            [
                f"### {detail['case_id']} / {detail['page_id']}",
                "",
                f"- Parser selected group: `{detail.get('parser_selected_group')}`",
                f"- Expected group: `{detail.get('expected_group')}`",
                f"- Why expected group was not selected: {detail.get('expected_group_not_selected_reason', 'not applicable')}",
                "",
                "| Candidate | Parent DOM path | Links | Chapter matches | Match ratio | Avg text length | Link text ratio | Depth | URL similarity | Score | Positive reasons | Penalties |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
            ]
        )
        for candidate in detail.get("candidates", []):
            lines.append(
                "| "
                + " | ".join(
                    _safe_cell(value)
                    for value in (
                        candidate["candidate_id"], candidate["parent_dom_path"], candidate["link_count"],
                        candidate["chapter_title_match_count"], candidate["chapter_title_match_ratio"],
                        candidate["average_anchor_text_length"], candidate["link_text_ratio"],
                        candidate["dom_depth"], candidate["url_similarity"], candidate["final_score"],
                        candidate["positive_reasons"], candidate["penalties"],
                    )
                )
                + " |"
            )
        lines.append("")

    lines.extend(["## Pagination relation failure details", ""])
    if not analysis["pagination_failure_details"]:
        lines.append("No pagination relation failures.")
    for detail in analysis["pagination_failure_details"]:
        label = detail.get("page_id") or detail.get("logical_chapter_id")
        lines.extend(
            [
                f"### {detail['case_id']} / {label}",
                "",
                f"- Expected relation/pages: `{_safe_cell(detail.get('expected_relation') or detail.get('expected_source_urls'))}`",
                f"- Parser selection/pages: `{_safe_cell(detail.get('parser_selected_relation') or detail.get('actual_source_urls'))}`",
                "",
                "| Anchor text | Target URL | Predicted relation | Confidence | Positive reasons | Penalties |",
                "|---|---|---|---:|---|---|",
            ]
        )
        candidates = detail.get("candidates") or []
        if not candidates:
            for page_candidates in (detail.get("candidates_by_page") or {}).values():
                candidates.extend(page_candidates)
        for candidate in candidates:
            lines.append(
                "| "
                + " | ".join(
                    _safe_cell(value)
                    for value in (
                        candidate["anchor_text"], candidate["target_url"],
                        candidate["predicted_relation"], candidate["relation_confidence"],
                        candidate["positive_reasons"], candidate["penalties"],
                    )
                )
                + " |"
            )
        lines.append("")

    lines.extend(["## Uncovered structure types", ""])
    for item in analysis["uncovered_structure_types"]:
        lines.append(f"- `{item['feature']}` ({item['suite']}): {item['action']}")

    lines.extend(["", "## Next three priority problem classes", ""])
    for index, item in enumerate(analysis["next_priority_problem_classes"], start=1):
        lines.append(
            f"{index}. **{item['problem']}** — {item['failure_count']} failure records. "
            f"{item['rationale']}"
        )

    lines.extend(
        [
            "",
            "## Guardrails and limits",
            "",
            *[f"- {item}" for item in analysis["guardrails"]],
            *[f"- {item}" for item in analysis["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)

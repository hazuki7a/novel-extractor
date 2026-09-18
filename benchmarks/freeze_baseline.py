"""Freeze baseline_v0 and its failure-analysis companion reports."""

from __future__ import annotations

import json
from pathlib import Path

from offline_runner import CASES_DIR, run_all
from reporting import (
    build_failure_analysis,
    render_baseline_markdown,
    render_failure_analysis_markdown,
)


ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"


def freeze() -> dict[str, Path]:
    baseline = run_all(CASES_DIR)
    analysis = build_failure_analysis(baseline)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "baseline_json": REPORTS_DIR / "baseline_v0.json",
        "baseline_markdown": REPORTS_DIR / "baseline_v0.md",
        "analysis_json": REPORTS_DIR / "failure_analysis.json",
        "analysis_markdown": REPORTS_DIR / "failure_analysis.md",
    }
    outputs["baseline_json"].write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    outputs["baseline_markdown"].write_text(
        render_baseline_markdown(baseline), encoding="utf-8", newline="\n"
    )
    outputs["analysis_json"].write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    outputs["analysis_markdown"].write_text(
        render_failure_analysis_markdown(analysis), encoding="utf-8", newline="\n"
    )
    return outputs


def main() -> int:
    for name, path in freeze().items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

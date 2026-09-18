#!/usr/bin/env python3
"""Validate executable benchmark cases without running inference or network."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "src"))

from offline_contract import CaseValidationError, load_case, load_expected  # noqa: E402


def main() -> int:
    ready = deferred = invalid = 0
    for case_path in sorted((ROOT / "cases").glob("*/case.json")):
        try:
            header = json.loads(case_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            invalid += 1
            print(f"INVALID {case_path.parent.name}: {exc}", file=sys.stderr)
            continue
        if header.get("annotation_status") != "READY":
            deferred += 1
            print(f"DEFERRED {case_path.parent.name}: {header.get('annotation_status')}")
            continue
        try:
            case = load_case(case_path)
            load_expected(case)
            ready += 1
            print(f"READY {case_path.parent.name}")
        except CaseValidationError as exc:
            invalid += 1
            print(f"INVALID {case_path.parent.name}: {exc}", file=sys.stderr)
    print(f"CASE_VALIDATION: ready={ready} deferred={deferred} invalid={invalid}")
    print("No network access or extractor evaluation was performed.")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())

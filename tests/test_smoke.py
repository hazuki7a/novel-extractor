"""Smoke tests for the package skeleton (guide task 1)."""

from __future__ import annotations

import pytest

import novel_extractor
from novel_extractor.cli import main
from novel_extractor.models import ContentStatus, DetectionResult, PageType, RelationType


def test_version():
    assert novel_extractor.__version__


def test_models_importable():
    assert PageType.CHAPTER_PAGE.value == "CHAPTER_PAGE"
    assert ContentStatus.PAYWALL.value == "PAYWALL"
    assert RelationType.NEXT_CONTENT_PAGE.value == "NEXT_CONTENT_PAGE"


def test_detection_result_clamps_confidence():
    result: DetectionResult[str] = DetectionResult(value="x", confidence=5, reason="clamp")
    assert result.confidence == 1.0
    assert result.ok


def test_cli_help_and_version(capsys):
    assert main([]) == 0
    assert "novel-extractor" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    assert "novel-extractor 0.1.0" in capsys.readouterr().out

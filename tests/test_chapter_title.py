"""Tests for generic chapter title detection (guide task 3)."""

from __future__ import annotations

import pytest

from novel_extractor.analyzer.chapter import ChapterTitleDetector, chinese_numeral_to_int


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("十", 10),
        ("十五", 15),
        ("二十", 20),
        ("二十三", 23),
        ("一百", 100),
        ("一百零四", 104),
        ("一百二十三", 123),
        ("一千零一十", 1010),
        ("一万二千", 12000),
        ("两", 2),
    ],
)
def test_chinese_numerals(text, expected):
    assert chinese_numeral_to_int(text) == expected


@pytest.mark.parametrize(
    "text", ["", "零", "abc", "甲乙"],
)
def test_chinese_numerals_invalid(text):
    assert chinese_numeral_to_int(text) is None


@pytest.fixture()
def detector():
    return ChapterTitleDetector()


@pytest.mark.parametrize(
    ("title", "number", "ctype"),
    [
        ("第一章", 1.0, "normal"),
        ("第123章", 123.0, "normal"),
        ("第一百二十三章", 123.0, "normal"),
        ("第一百零八章", 108.0, "normal"),
        ("第12节", 12.0, "normal"),
        ("第九回", 9.0, "normal"),
        ("第1话", 1.0, "normal"),
        ("第３章", 3.0, "normal"),  # full-width digits
        ("第12.5章", 12.5, "normal"),
        ("卷一", 1.0, "volume"),
        ("第一卷", 1.0, "volume"),
        ("第三部", 3.0, "volume"),
        ("Chapter 12", 12.0, "normal"),
        ("chapter 99: the end", 99.0, "normal"),
    ],
)
def test_numbered_titles(detector, title, number, ctype):
    match = detector.parse(title)
    assert match is not None, title
    assert match.chapter_number == number, title
    assert match.chapter_type == ctype, title
    assert match.order_token == number, title
    assert match.confidence >= 0.90, title
    assert match.reason


@pytest.mark.parametrize(
    ("title", "ctype"),
    [
        ("序章", "prologue"),
        ("序幕", "prologue"),
        ("楔子", "prologue"),
        ("终章", "epilogue"),
        ("尾声", "epilogue"),
        ("大结局", "epilogue"),
        ("后记", "afterword"),
        ("番外", "extra"),
        ("外传", "extra"),
        ("间章", "interlude"),
    ],
)
def test_special_titles(detector, title, ctype):
    match = detector.parse(title)
    assert match is not None, title
    assert match.chapter_type == ctype, title
    assert match.chapter_number is None, title
    assert match.confidence >= 0.85, title


def test_numbered_title_with_suffix(detector):
    match = detector.parse("第12章 风起云涌")
    assert match.chapter_number == 12.0
    assert match.title == "第12章 风起云涌"
    assert 0.85 <= match.confidence < 0.95


def test_special_with_number_suffix(detector):
    match = detector.parse("番外二 新春特别篇")
    assert match.chapter_type == "extra"
    assert match.chapter_number == 2.0


def test_decorations_are_stripped(detector):
    match = detector.parse("【第一章】山村少年")
    assert match is not None
    assert match.chapter_number == 1.0
    assert not match.title.startswith("【")


def test_embedded_marker_is_weak(detector):
    match = detector.parse("他说第三章写得很好看")
    assert match is not None
    assert match.chapter_number == 3.0
    assert match.confidence < 0.60


def test_colon_between_number_and_suffix(detector):
    match = detector.parse("第一章：山村少年")
    assert match.chapter_number == 1.0
    assert "山村少年" in match.title


@pytest.mark.parametrize(
    "title",
    [
        "今天天气不错",
        "我的第一志愿",
        "两千个问题",
        "读者来信",
        "万象更新",
    ],
)
def test_non_titles_rejected(detector, title):
    assert detector.parse(title) is None, title


def test_empty_and_blank(detector):
    assert detector.parse("") is None
    assert detector.parse("   ") is None


def test_sub_numbered_chapters_get_distinct_tokens(detector):
    a = detector.parse("第6章 1")
    b = detector.parse("第6章 2")
    assert a.chapter_number == 6.0
    assert b.chapter_number == 6.0
    assert a.order_token == 6.0001
    assert b.order_token == 6.0002
    assert b.order_token < 7.0  # never reaches the next main number


def test_suffix_prose_does_not_become_sub_number(detector):
    m = detector.parse("第12章 风起云涌")
    assert m.order_token == 12.0


def test_bracketed_sub_number(detector):
    m = detector.parse("第六章(1)")
    assert m is not None
    assert m.chapter_number == 6.0
    assert m.sub_number == 1
    assert m.order_token == 6.0001
    # (2/3) is a pagination marker, not a part index
    m2 = detector.parse("第八章(2/3)")
    assert m2.sub_number is None


def test_strip_sub_number_variants():
    from novel_extractor.analyzer.chapter import strip_sub_number
    assert strip_sub_number("第6章 2") == "第6章"
    assert strip_sub_number("第六章(1)") == "第六章"
    assert strip_sub_number("第12章：3") == "第12章"
    assert strip_sub_number("第12章 5年后") == "第12章 5年后"  # prose name
    assert strip_sub_number("第12.5章") == "第12.5章"

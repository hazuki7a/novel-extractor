"""Tests for conservative text cleaning (guide task 13)."""

from __future__ import annotations

from novel_extractor.cleaner.text import TextCleaner

PROSE = "山风吹过林梢，主角抬起头，远处钟声一圈一圈荡开。"
PROSE2 = "他顺着石阶而下，雾气从谷底涌上来，打湿了衣角。"


def test_basic_prose_gets_full_width_indent():
    cleaned = TextCleaner().clean(PROSE)
    assert cleaned == "　　" + PROSE


def test_zero_width_chars_removed():
    text = "山风\u200b吹过林\u200c梢，钟声\ufeff荡开。"
    cleaned = TextCleaner().clean(text)
    assert "\u200b" not in cleaned and "\u200c" not in cleaned and "\ufeff" not in cleaned
    assert "山风吹过林梢" in cleaned


def test_line_endings_normalized():
    cleaned = TextCleaner().clean(PROSE + "\r\n" + PROSE2)
    assert "\r" not in cleaned
    assert PROSE in cleaned and PROSE2 in cleaned


def test_html_residue_removed():
    cleaned = TextCleaner().clean("<p>　　" + PROSE + "</p><br>&nbsp;" + PROSE2)
    assert "<p>" not in cleaned and "</p>" not in cleaned and "<br>" not in cleaned
    assert PROSE in cleaned and PROSE2 in cleaned


def test_existing_indent_not_doubled():
    cleaned = TextCleaner().clean("　　" + PROSE)
    assert cleaned == "　　" + PROSE


def test_navigation_lines_removed():
    nav_lines = ["上一章", "下一章", "目录", "上一章 目录 下一章", "next chapter", "上一页»"]
    text = "\n".join([PROSE] + nav_lines + [PROSE2])
    cleaned = TextCleaner().clean(text)
    assert "上一章" not in cleaned
    assert "下一章" not in cleaned
    assert "目录" not in cleaned
    assert PROSE in cleaned and PROSE2 in cleaned


def test_site_prompt_lines_removed():
    prompts = [
        "本章未完，点击下一页继续阅读",
        "请记住本书首发域名",
        "天才一秒记住本站地址",
        "最新章节请到官网下载",
        "发现章节错误，请举报",
    ]
    text = "\n".join([PROSE] + prompts + [PROSE2])
    cleaned = TextCleaner().clean(text)
    assert "点击下一页" not in cleaned
    assert "首发域名" not in cleaned
    assert "天才一秒" not in cleaned
    assert "举报" not in cleaned
    assert PROSE in cleaned and PROSE2 in cleaned


def test_chapter_title_removed_including_repeats():
    title = "第12章 出山"
    text = "\n".join([title, PROSE, "　　" + title, PROSE2])
    cleaned = TextCleaner().clean(text, chapter_title=title)
    assert "第12章 出山" not in cleaned
    assert PROSE in cleaned and PROSE2 in cleaned


def test_title_with_page_suffix_removed():
    title = "第12章 出山"
    text = "\n".join([PROSE, "第12章 出山(2/3)", PROSE2])
    cleaned = TextCleaner().clean(text, chapter_title=title)
    assert "(2/3)" not in cleaned


def test_pure_number_lines_removed():
    text = "\n".join([PROSE, "1/3", "第2页", PROSE2])
    cleaned = TextCleaner().clean(text)
    assert "1/3" not in cleaned
    assert "第2页" not in cleaned


def test_paragraphs_not_merged():
    # Two lines that look like one broken sentence must stay separate.
    text = "他顺着石阶而下\n雾气从谷底涌上来"
    cleaned = TextCleaner().clean(text)
    lines = cleaned.split("\n\n")
    assert len(lines) == 2
    assert lines[0].endswith("而下")
    assert lines[1].startswith("　　雾气")


def test_blank_runs_compressed():
    text = PROSE + "\n\n\n\n\n" + PROSE2 + "\n\n\n"
    cleaned = TextCleaner().clean(text)
    assert "\n\n\n" not in cleaned
    parts = cleaned.split("\n\n")
    assert len(parts) == 2


def test_prose_is_never_dropped():
    text = "\n".join(f"第{i}段，{PROSE}" for i in range(1, 20))
    cleaned = TextCleaner().clean(text)
    for i in range(1, 20):
        assert f"第{i}段" in cleaned


def test_empty_input():
    assert TextCleaner().clean("") == ""
    assert TextCleaner().clean("   \n  \n ") == ""


def test_nav_only_input_becomes_empty():
    assert TextCleaner().clean("上一章\n目录\n下一章") == ""


def test_structural_duplicate_title_removed_across_forms():
    # On-page heading 第六章(1) vs catalog title 第6章 1 - same chapter.
    text = "\n".join(["第六章(1)", PROSE, PROSE2])
    cleaned = TextCleaner().clean(text, chapter_title="第6章 1")
    assert "第六章" not in cleaned
    assert PROSE in cleaned


def test_weak_chapter_reference_in_prose_is_kept():
    text = "\n".join(["第1章 名字", PROSE, "他说第三章写得很好看", PROSE2])
    cleaned = TextCleaner().clean(text, chapter_title="第1章 名字")
    assert "他说第三章写得很好看" in cleaned


def test_glued_nav_bar_line_removed():
    # lingduxs pattern: link bar rendered without separators between anchors.
    text = "\n".join([
        "上一章章节目录保存书签阅读记录下一章",
        PROSE,
        "上一章|章节目录|保存书签|阅读记录|下一章",
    ])
    cleaned = TextCleaner().clean(text)
    assert "保存书签" not in cleaned
    assert "阅读记录" not in cleaned
    assert PROSE in cleaned


def test_prose_containing_nav_word_survives():
    # A prose line with one nav word must not be dropped by the glue rule.
    text = "\n".join([PROSE, "他说这个目录很有意思，值得收藏。"])
    cleaned = TextCleaner().clean(text)
    assert "这个目录很有意思" in cleaned

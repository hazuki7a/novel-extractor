"""Build the authored synthetic fixtures for the v1 offline contract.

All prose in these fixtures is project-authored test text.  The generated
files are deterministic and contain no captured third-party webpage content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases"
FIXTURES = ROOT / "fixtures" / "synthetic"


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write(path: Path, content: str | bytes, encoding: str = "utf-8") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode(encoding)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _body(seed: str, count: int = 12) -> str:
    return "\n".join(
        f"{seed}第{i}段，潮声绕过旧城墙，旅人把灯举高，确认石阶上的每一道刻痕都仍然清晰。"
        for i in range(1, count + 1)
    )


def _html(title: str, body: str, *, nav: str = "", extra: str = "") -> str:
    paragraphs = "".join(f"<p>{line}</p>" for line in body.splitlines())
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{title}</title></head><body><h1>{title}</h1>"
        f"<article id=\"content\">{paragraphs}</article>{extra}{nav}</body></html>"
    )


class CaseBuilder:
    def __init__(self, case_id: str, suite: str, tags: list[str], entry: str | None = None):
        self.case_id = case_id
        self.case_dir = CASES / case_id
        self.fixture_dir = FIXTURES / case_id
        self.pages: list[dict] = []
        self.labels: list[dict] = []
        self.case = {
            "schema_version": "1.0.0",
            "document_type": "benchmark_case",
            "annotation_status": "READY",
            "case_id": case_id,
            "site_id": "synthetic",
            "suite": suite,
            "scenario_tags": tags,
            "dataset_split": "development",
            "template_family": f"synthetic:{case_id}",
            "capture_scope": "sampled_subgraph",
            "source_type": "synthetic",
            "created_at": "2026-09-17T00:00:00+08:00",
            "reviewed_at": "2026-09-17T00:00:00+08:00",
            "input_root": f"../../fixtures/synthetic/{case_id}",
            "entry_page_id": entry,
            "pages": self.pages,
            "expected_path": "expected.json",
            "rights_and_privacy": {
                "publication_status": "PUBLIC_SYNTHETIC",
                "permission_or_license_reference": "project-authored synthetic fixture",
                "sensitive_fields_removed": True,
                "original_and_transformed_inputs_tracked_separately": True,
                "review_notes": ["No third-party webpage or novel text is included."],
            },
            "notes": ["Synthetic regression input; never count as a real-site fixture."],
        }
        self.expected = {
            "schema_version": "1.0.0",
            "document_type": "benchmark_expected",
            "annotation_status": "READY",
            "case_id": case_id,
            "normalization_profile": "NFC_LF_TRIM_OUTER_NO_REWRITE",
            "page_labels": self.labels,
            "logical_chapters": [],
            "expected_reading_order": [],
            "expected_export": {
                "required": False,
                "reference_path": None,
                "must_report_missing_chapters": None,
                "must_not_claim_complete_book": True,
            },
            "evaluation_scope": {
                "global_catalog_complete": False,
                "order_scope": "sampled_subgraph",
                "unknown_labels_are_skipped_fields_not_correct_predictions": True,
            },
            "review": {
                "method": "manual review of project-authored fixture",
                "reviewer_alias": "project",
                "reviewed_at": "2026-09-17T00:00:00+08:00",
                "notes": [],
            },
        }

    def page(
        self,
        page_id: str,
        url: str,
        content: str | bytes,
        *,
        input_kind: str = "SYNTHETIC_HTML",
        status: int = 200,
        headers: dict[str, str] | None = None,
        label: dict | None = None,
        input_name: str | None = None,
    ) -> None:
        suffix = ".bin" if input_kind == "HTTP_BYTES" else ".html"
        input_name = input_name or f"{page_id}{suffix}"
        input_hash = _write(self.fixture_dir / input_name, content)
        metadata_name = None
        if input_kind == "HTTP_BYTES":
            metadata_name = f"{page_id}_http.json"
            _dump(
                self.fixture_dir / metadata_name,
                {"requested_url": url, "final_url": url, "status": status, "headers": headers or {}},
            )
        self.pages.append(
            {
                "page_id": page_id,
                "requested_url": url,
                "final_url": url,
                "captured_at": "2026-09-17T00:00:00+08:00",
                "input_kind": input_kind,
                "input_path": input_name,
                "input_sha256": input_hash,
                "http_metadata_path": metadata_name,
                "http_status": status,
                "body_stage": "decompressed_before_character_decoding" if input_kind == "HTTP_BYTES" else "rendered_or_authored_utf8",
                "saved_file_encoding": None if input_kind == "HTTP_BYTES" else "utf-8",
                "declared_http_charset": None,
                "declared_meta_charset": None,
                "verified_source_encoding": None,
                "browser": None,
                "rendered_from_page_id": None,
                "notes": [],
            }
        )
        base_label = {
            "page_id": page_id,
            "page_type": None,
            "access_status": "OK",
            "content_status": None,
            "render_requirement": "NONE",
            "should_extract_content": None,
            "should_extract_book_metadata": None,
            "book_title": None,
            "author": None,
            "chapter_title": None,
            "content_reference_path": None,
            "content_regions": [],
            "exclude_regions": [],
            "catalog_direction": None,
            "catalog_entries": [],
            "relations": [],
            "must_not_export_as_body": [],
            "evidence_notes": [],
        }
        base_label.update(label or {})
        self.labels.append(base_label)

    def reference(self, name: str, text: str) -> str:
        relative = f"reference/{name}.txt"
        _write(self.fixture_dir / relative, text)
        return f"../../fixtures/synthetic/{self.case_id}/{relative}"

    def finish(self) -> None:
        _dump(self.case_dir / "case.json", self.case)
        _dump(self.case_dir / "expected.json", self.expected)


def build_text_structures() -> None:
    case = CaseBuilder(
        "syn_text_structures",
        "SYNTHETIC_REGRESSION",
        ["p_paragraphs", "br_paragraphs", "comments_ads", "short_prologue"],
    )
    p_text = _body("松港正文")
    p_ref = case.reference("p_chapter", p_text)
    case.page(
        "p_chapter", "https://synthetic.invalid/text/p", _html("第一章 松港", p_text),
        label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第一章 松港", "content_reference_path": p_ref},
    )
    br_text = _body("雾桥正文")
    br_ref = case.reference("br_chapter", br_text)
    br_html = f"<html><head><title>第二章 雾桥</title></head><body><h1>第二章 雾桥</h1><div id='content'>{'<br>'.join(br_text.splitlines())}</div></body></html>"
    case.page(
        "br_chapter", "https://synthetic.invalid/text/br", br_html,
        label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第二章 雾桥", "content_reference_path": br_ref},
    )
    main_text = _body("灯塔正文", 10)
    comment_text = _body("读者评论请勿进入正文", 22)
    comments_ref = case.reference("comments_chapter", main_text)
    comment_html = _html(
        "第三章 灯塔", main_text,
        extra=f"<section id='comments' class='comments'><h2>评论区</h2>{''.join(f'<p>{line}</p>' for line in comment_text.splitlines())}</section>",
    )
    case.page(
        "comments_chapter", "https://synthetic.invalid/text/comments", comment_html,
        label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第三章 灯塔", "content_reference_path": comments_ref, "must_not_export_as_body": ["读者评论请勿进入正文"]},
    )
    prologue = "雨停了。她推开门，看见多年未亮的站台灯忽然亮起。"
    prologue_ref = case.reference("short_prologue", prologue)
    case.page(
        "short_prologue", "https://synthetic.invalid/text/prologue", _html("序章 灯亮", prologue),
        label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "序章 灯亮", "content_reference_path": prologue_ref, "evidence_notes": ["Short but intentionally complete prose."]},
    )
    case.finish()


def build_access_states() -> None:
    case = CaseBuilder("syn_access_states", "SYNTHETIC_REGRESSION", ["anti_bot", "http_403", "http_200_challenge"])
    challenge = "<html><head><title>Just a moment...</title></head><body><main>Enable JavaScript and cookies to continue</main></body></html>"
    for page_id, status in (("challenge_403", 403), ("challenge_200", 200)):
        case.page(
            page_id,
            f"https://synthetic.invalid/access/{status}",
            challenge.encode("utf-8"),
            input_kind="HTTP_BYTES",
            status=status,
            headers={"content-type": "text/html; charset=utf-8", "server": "synthetic-gateway"},
            label={"page_type": "UNKNOWN", "access_status": "ANTI_BOT", "content_status": "ANTI_BOT", "should_extract_content": False, "should_extract_book_metadata": False, "must_not_export_as_body": ["Enable JavaScript and cookies to continue"]},
        )
    case.finish()


def build_encoding() -> None:
    case = CaseBuilder("syn_encoding_bytes", "SYNTHETIC_REGRESSION", ["gbk_gb18030", "encoding_conflict"])
    gb_text = _body("龘字编码正文", 8)
    gb_ref = case.reference("gb18030", gb_text)
    gb_html = _html("第一章 编码龘", gb_text).replace('charset="utf-8"', 'charset="gb18030"')
    case.page(
        "gb18030_page", "https://synthetic.invalid/encoding/gb", gb_html.encode("gb18030"),
        input_kind="HTTP_BYTES", headers={"content-type": "text/html; charset=gb18030"},
        label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第一章 编码龘", "content_reference_path": gb_ref},
    )
    conflict_text = _body("冲突声明正文", 8)
    conflict_ref = case.reference("conflict", conflict_text)
    conflict_html = _html("第二章 冲突声明", conflict_text)
    case.page(
        "conflict_page", "https://synthetic.invalid/encoding/conflict", conflict_html.encode("utf-8"),
        input_kind="HTTP_BYTES", headers={"content-type": "text/html; charset=gbk"},
        label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第二章 冲突声明", "content_reference_path": conflict_ref, "evidence_notes": ["HTTP declares GBK, bytes and meta are UTF-8."]},
    )
    case.finish()


def build_content_pagination() -> None:
    case = CaseBuilder("syn_content_pagination", "SYNTHETIC_REGRESSION", ["content_pagination", "mislabelled_next_chapter"], entry="chapter_1_page_1")
    part1 = _body("第一页正文", 7)
    part2 = _body("第二页正文", 7)
    chapter2 = _body("下一逻辑章正文", 10)
    nav1 = "<nav><a href='/pagination/ch1-2'>下一章</a></nav>"
    nav2 = "<nav><a href='/pagination/ch1-1'>上一章</a><a href='/pagination/ch2'>下一章</a></nav>"
    nav3 = "<nav><a href='/pagination/ch1-2'>上一章</a></nav>"
    case.page("chapter_1_page_1", "https://synthetic.invalid/pagination/ch1-1", _html("第1章 海路（第1页）", part1, nav=nav1), label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第1章 海路（第1页）", "content_reference_path": case.reference("chapter_1_page_1", part1), "relations": [{"type": "NEXT_CONTENT_PAGE", "target_page_id": "chapter_1_page_2", "target_url": "https://synthetic.invalid/pagination/ch1-2", "evidence": "same numbered chapter, explicit page marker"}]})
    case.page("chapter_1_page_2", "https://synthetic.invalid/pagination/ch1-2", _html("第1章 海路（第2页）", part2, nav=nav2), label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第1章 海路（第2页）", "content_reference_path": case.reference("chapter_1_page_2", part2), "relations": [{"type": "NEXT_CHAPTER", "target_page_id": "chapter_2", "target_url": "https://synthetic.invalid/pagination/ch2", "evidence": "next logical chapter"}]})
    case.page("chapter_2", "https://synthetic.invalid/pagination/ch2", _html("第2章 岛影", chapter2, nav=nav3), label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第2章 岛影", "content_reference_path": case.reference("chapter_2", chapter2)})
    case.expected["logical_chapters"] = [
        {"chapter_id": "ch1", "title": "第1章 海路", "source_page_ids": ["chapter_1_page_1", "chapter_1_page_2"], "reference_text_path": case.reference("logical_chapter_1", part1 + "\n" + part2), "complete_within_case": True},
        {"chapter_id": "ch2", "title": "第2章 岛影", "source_page_ids": ["chapter_2"], "reference_text_path": case.reference("logical_chapter_2", chapter2), "complete_within_case": True},
    ]
    case.expected["expected_reading_order"] = ["ch1", "ch2"]
    case.finish()


def build_catalog_pagination() -> None:
    case = CaseBuilder("syn_catalog_pagination", "SYNTHETIC_REGRESSION", ["catalog_pagination", "duplicate_boundary"], entry="catalog_1")
    links1 = "".join(f"<li><a href='/catalog/ch{i}'>第{i}章</a></li>" for i in range(1, 5))
    links2 = "".join(f"<li><a href='/catalog/ch{i}'>第{i}章</a></li>" for i in range(4, 7))
    catalog1 = f"<html><head><title>群岛记目录</title></head><body><h1>群岛记目录</h1><ul>{links1}</ul><a href='/catalog/list-2'>下一页</a></body></html>"
    catalog2 = f"<html><head><title>群岛记目录 第2页</title></head><body><h1>群岛记目录</h1><ul>{links2}</ul><a href='/catalog/list-1'>上一页</a></body></html>"
    entries = [{"chapter_id": f"ch{i}", "title": f"第{i}章", "volume": None, "page_id": f"chapter_{i}", "target_url": f"https://synthetic.invalid/catalog/ch{i}", "fragment": None, "source_order": i} for i in range(1, 7)]
    case.page("catalog_1", "https://synthetic.invalid/catalog/list-1", catalog1, label={"page_type": "CATALOG_PAGE", "should_extract_content": False, "catalog_direction": "ASCENDING", "catalog_entries": entries[:4], "relations": [{"type": "NEXT_CATALOG_PAGE", "target_page_id": "catalog_2", "target_url": "https://synthetic.invalid/catalog/list-2", "evidence": "next page link"}]})
    case.page("catalog_2", "https://synthetic.invalid/catalog/list-2", catalog2, label={"page_type": "CATALOG_PAGE", "should_extract_content": False, "catalog_direction": "ASCENDING", "catalog_entries": entries[3:], "relations": [{"type": "PREVIOUS_CATALOG_PAGE", "target_page_id": "catalog_1", "target_url": "https://synthetic.invalid/catalog/list-1", "evidence": "previous page link"}]})
    for i in range(1, 7):
        text = _body(f"目录分页第{i}章正文", 7)
        case.page(f"chapter_{i}", f"https://synthetic.invalid/catalog/ch{i}", _html(f"第{i}章", text), label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": f"第{i}章", "content_reference_path": case.reference(f"chapter_{i}", text)})
        case.expected["logical_chapters"].append({"chapter_id": f"ch{i}", "title": f"第{i}章", "source_page_ids": [f"chapter_{i}"], "reference_text_path": case.reference(f"logical_{i}", text), "complete_within_case": True})
    case.expected["expected_reading_order"] = [f"ch{i}" for i in range(1, 7)]
    case.expected["evaluation_scope"]["global_catalog_complete"] = True
    case.finish()


def build_fragments() -> None:
    case = CaseBuilder("syn_fragment_identity", "SYNTHETIC_REGRESSION", ["single_file_fragment_chapters", "multiple_chapters_one_page"])
    document = "<html><head><title>锚点之书</title></head><body><h1>锚点之书</h1><section id='c1'><h2>第一章</h2><p>第一章锚点正文。</p></section><section id='c2'><h2>第二章</h2><p>第二章锚点正文。</p></section></body></html>"
    shared_name = "whole_book.html"
    case.page("fragment_1", "https://synthetic.invalid/fragments/book#c1", document, input_name=shared_name, label={"page_type": "BOOK_PAGE", "should_extract_content": True, "chapter_title": "第一章"})
    case.page("fragment_2", "https://synthetic.invalid/fragments/book#c2", document, input_name=shared_name, label={"page_type": "BOOK_PAGE", "should_extract_content": True, "chapter_title": "第二章"})
    case.expected["logical_chapters"] = [
        {"chapter_id": "c1", "title": "第一章", "source_page_ids": ["fragment_1"], "reference_text_path": None, "complete_within_case": True},
        {"chapter_id": "c2", "title": "第二章", "source_page_ids": ["fragment_2"], "reference_text_path": None, "complete_within_case": True},
    ]
    case.expected["expected_reading_order"] = ["c1", "c2"]
    case.finish()


def build_volume_reset_table() -> None:
    case = CaseBuilder(
        "syn_volume_reset_table",
        "SYNTHETIC_REGRESSION",
        ["table_layout", "catalog_descending", "volume_number_reset", "mixed_catalog"],
    )
    rows = []
    entries = []
    source_order = 0
    for volume_id, volume_title in (("v1", "第一卷 潮汐"), ("v2", "第二卷 星火")):
        rows.append(f"<tr class='volume'><th colspan='2'>{volume_title}</th></tr>")
        for number in (4, 3, 2, 1):
            source_order += 1
            url = f"https://synthetic.invalid/volumes/{volume_id}-c{number}"
            rows.append(f"<tr><td>{number}</td><td><a href='/volumes/{volume_id}-c{number}'>第{number}章 {volume_title}</a></td></tr>")
            entries.append({"chapter_id": f"{volume_id}c{number}", "title": f"第{number}章 {volume_title}", "volume": volume_title, "page_id": None, "target_url": url, "fragment": None, "source_order": source_order})
    html = "<html><head><title>双卷目录</title></head><body><h1>双卷目录</h1><table>" + "".join(rows) + "</table></body></html>"
    case.page(
        "catalog",
        "https://synthetic.invalid/volumes/catalog",
        html,
        label={
            "page_type": "CATALOG_PAGE",
            "should_extract_content": False,
            "catalog_direction": "MIXED",
            "catalog_entries": entries,
            "evidence_notes": ["Each volume is descending; numbering resets in the second volume."],
        },
    )
    case.finish()


def build_partial_failure() -> None:
    case = CaseBuilder("syn_partial_failure", "SYNTHETIC_REGRESSION", ["partial_failure", "missing_fixture", "no_fake_body"], entry="chapter_1")
    text = _body("中断前正文", 8)
    nav = "<nav><a href='/partial/missing-chapter'>下一章</a></nav>"
    case.page("chapter_1", "https://synthetic.invalid/partial/chapter-1", _html("第一章 中断前", text, nav=nav), label={"page_type": "CHAPTER_PAGE", "content_status": "CONTENT_OK", "should_extract_content": True, "chapter_title": "第一章 中断前", "content_reference_path": case.reference("chapter_1", text), "relations": [{"type": "NEXT_CHAPTER", "target_page_id": None, "target_url": "https://synthetic.invalid/partial/missing-chapter", "evidence": "target deliberately outside captured scope"}]})
    case.expected["logical_chapters"] = [{"chapter_id": "ch1", "title": "第一章 中断前", "source_page_ids": ["chapter_1"], "reference_text_path": case.reference("logical_chapter_1", text), "complete_within_case": True}]
    case.expected["expected_reading_order"] = ["ch1"]
    case.expected["expected_export"]["must_report_missing_chapters"] = True
    case.finish()


def main() -> int:
    for builder in (
        build_text_structures,
        build_access_states,
        build_encoding,
        build_content_pagination,
        build_catalog_pagination,
        build_fragments,
        build_volume_reset_table,
        build_partial_failure,
    ):
        builder()
    print("BUILT_SYNTHETIC_CONTRACT_CASES: 8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

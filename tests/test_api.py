"""Tests for the stable Python API and CLI subcommands (guide task 23)."""

from __future__ import annotations

import pytest

from novel_extractor.api import NovelExtractor
from novel_extractor.fetcher.http import FetchError
from novel_extractor.models import FetchedPage


def chapter_html(i: int) -> str:
    return f"""
    <html><head><title>第{i}章 风云{i}</title></head><body>
    <h1>第{i}章 风云{i}</h1>
    <div id="content">{''.join(f'<p>第{i}章第{j}段，山风吹过林梢，主角抬眼望向远方，远处的钟声一圈一圈荡开。</p>' for j in range(1, 13))}</div>
    <div class="nav">
      <a href="{i - 1}.html">上一章</a><a href="catalog.html">目录</a><a href="{i + 1}.html">下一章</a>
    </div></body></html>
    """


def catalog_html() -> str:
    links = "".join(
        f'<li><a href="/book/1/{i}.html">第{i}章 风云{i}</a></li>' for i in range(1, 9)
    )
    return f"""
    <html><head><title>风云传目录</title>
    <meta property="og:novel:book_name" content="风云传">
    <meta property="og:novel:author" content="测试 作者"></head><body>
    <h1>风云传</h1><ul>{links}</ul></body></html>
    """


class FakeFetcher:
    def __init__(self):
        self.pages = {"http://e.com/book/1/catalog.html": catalog_html()}
        for i in range(1, 9):
            self.pages[f"http://e.com/book/1/{i}.html"] = chapter_html(i)

    def fetch(self, url: str, *, referer=None) -> FetchedPage:
        if url not in self.pages:
            raise FetchError(url, "missing page")
        html = self.pages[url]
        return FetchedPage(
            url=url, final_url=url, status_code=200, raw_bytes=html.encode(),
            html=html, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
        )


def test_python_api_extract_and_export(tmp_path):
    extractor = NovelExtractor(output_root=tmp_path, fetcher=FakeFetcher())
    result = extractor.extract("http://e.com/book/1/catalog.html")
    assert len(result.chapters) == 8
    assert result.metadata.book_title == "风云传"
    export = extractor.export_txt(result, output_root=tmp_path)
    assert export.merged_file is not None
    assert export.merged_file.exists()
    # guide example: result.export_txt('./output')
    export2 = result.export_txt(tmp_path / "again")
    assert export2.book_dir.exists()


def test_python_api_analyze_single_page():
    extractor = NovelExtractor(output_root="output", fetcher=FakeFetcher())
    analysis = extractor.analyze("http://e.com/book/1/catalog.html")
    assert analysis["page_type"] == "CATALOG_PAGE"
    assert analysis["metadata"]["book_title"] == "风云传"
    assert analysis["catalog_preview"]["entries"] == 8
    assert analysis["content"]["candidates"], "analyze must expose candidate records"


def test_cache_list_and_clear(tmp_path):
    from novel_extractor.cache import InferenceCache

    cache = InferenceCache(cache_dir=tmp_path / "cache")
    extractor = NovelExtractor(output_root=tmp_path, fetcher=FakeFetcher(), cache=cache)
    extractor.extract("http://e.com/book/1/catalog.html")
    entries = extractor.cache_list()
    assert entries and entries[0]["host"] == "e.com"
    assert extractor.cache_clear() == 1
    assert extractor.cache_list() == []


def test_cli_help_lists_v1_subcommands():
    from novel_extractor.cli import build_parser

    help_text = build_parser().format_help()
    for command in ("analyze", "inspect", "download", "cache"):
        assert command in help_text


def test_webui_analyze_and_download_job(tmp_path):
    import http.client
    import threading

    from novel_extractor.webui import WebUI

    webui = WebUI(output_root=tmp_path, fetcher=FakeFetcher())
    server = webui.make_server(port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        # index page
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        index = resp.read().decode("utf-8")
        assert "小说提取器" in index
        assert 'id="progressBar"' in index
        # analyze
        import json as _json

        conn.request(
            "POST", "/api/analyze", body=_json.dumps({"url": "http://e.com/book/1/catalog.html"}),
            headers={"Content-Type": "application/json"},
        )
        analysis = _json.loads(conn.getresponse().read())
        assert analysis["page_type"] == "CATALOG_PAGE"
        # download job
        conn.request(
            "POST", "/api/download", body=_json.dumps({"url": "http://e.com/book/1/catalog.html"}),
            headers={"Content-Type": "application/json"},
        )
        job = _json.loads(conn.getresponse().read())
        assert job["job_id"]
        for _ in range(100):
            conn.request("GET", f"/api/job/{job['job_id']}")
            state = _json.loads(conn.getresponse().read())
            if state["status"] != "running":
                break
            import time as _time

            _time.sleep(0.2)
        assert state["status"] == "done"
        assert state["chapters"] == 8
        assert state["chapters_ok"] == 8
        assert state["progress"]["phase"] == "done"
        assert state["progress"]["percent"] == 100.0
        conn.close()
    finally:
        server.shutdown()
        server.server_close()


def test_webui_running_job_reports_chapter_progress(tmp_path):
    import threading

    from novel_extractor.webui import WebUI

    reported = threading.Event()
    release = threading.Event()

    class BlockingExtractor:
        def extract(self, url, progress=None):
            assert progress is not None
            progress(2, 8, "第2章 测试进度", "CONTENT_OK", 0.4)
            reported.set()
            release.wait(timeout=5)
            raise RuntimeError("test finished")

    webui = WebUI(output_root=tmp_path, fetcher=FakeFetcher())
    webui.extractor = BlockingExtractor()
    job_id = webui.handle_download({"url": "http://e.com/book/1/catalog.html"})["job_id"]
    assert reported.wait(timeout=2)

    state = webui.handle_job(job_id)
    assert state["status"] == "running"
    assert state["progress"] == {
        "phase": "extracting",
        "done": 2,
        "total": 8,
        "title": "第2章 测试进度",
        "chapter_status": "CONTENT_OK",
        "interval": 0.4,
        "percent": 25.0,
        "message": "",
    }
    release.set()


def test_webui_recreates_default_network_client_for_each_task(tmp_path, monkeypatch):
    import novel_extractor.webui as webui_module

    created = []
    closed = []

    class RecordingFetcher:
        def __init__(self, instance_id):
            self.instance_id = instance_id

        def close(self):
            closed.append(self.instance_id)

    class RecordingExtractor:
        def __init__(self, output_root):
            self.instance_id = len(created) + 1
            self.fetcher = RecordingFetcher(self.instance_id)
            created.append((self.instance_id, output_root))

        def analyze(self, url):
            return {"instance_id": self.instance_id, "url": url}

    monkeypatch.setattr(webui_module, "NovelExtractor", RecordingExtractor)
    webui = webui_module.WebUI(output_root=tmp_path)

    first = webui.handle_analyze({"url": "https://example.com/first"})
    second = webui.handle_analyze({"url": "https://example.com/second"})

    assert first["instance_id"] == 1
    assert second["instance_id"] == 2
    assert [output_root for _, output_root in created] == [tmp_path, tmp_path]
    assert closed == [1, 2]

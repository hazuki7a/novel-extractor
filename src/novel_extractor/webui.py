"""Local WebUI (guide task 27 / V2).

A minimal stdlib-only web UI served by ``novel-extractor web``. It ONLY
calls the core API (NovelExtractor.analyze / extract / export_txt) - none of
the parsing logic lives here.

Endpoints:
    GET  /                 simple single-page UI
    POST /api/analyze      {"url": ...}          -> analysis JSON
    POST /api/download     {"url": ...}          -> {"job_id": ...}
    GET  /api/job/<id>                            -> job status / result

Downloads run in a background thread; polls return their state.
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from novel_extractor.api import NovelExtractor

_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><title>novel-extractor</title>
<style>
body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }
input[type=text] { width: 70%; padding: .4rem; }
button { padding: .4rem .8rem; }
pre { background: #f4f4f4; padding: .8rem; overflow-x: auto; }
.ok { color: #070; } .bad { color: #c00; }
</style></head><body>
<h1>novel-extractor</h1>
<p>无书源 · 无 API Key · 无云端 AI — 粘贴小说 URL 开始提取。</p>
<p><input type="text" id="url" placeholder="https://...">
<button onclick="doAnalyze()">分析页面</button>
<button onclick="doDownload()">开始下载</button></p>
<pre id="out">等待输入…</pre>
<script>
const out = document.getElementById('out');
function show(obj) { out.textContent = JSON.stringify(obj, null, 2); }
async function post(path, body) {
  const r = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  return r.json();
}
async function doAnalyze() {
  out.textContent = '分析中…';
  show(await post('/api/analyze', {url: document.getElementById('url').value}));
}
async function doDownload() {
  out.textContent = '任务已提交…';
  const job = await post('/api/download', {url: document.getElementById('url').value});
  poll(job.job_id);
}
async function poll(id) {
  const r = await fetch('/api/job/' + id);
  const state = await r.json();
  if (state.status === 'running') { setTimeout(() => poll(id), 1500); return; }
  show(state);
}
</script></body></html>"""


class _Jobs:
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"status": "running"}
        return job_id

    def finish(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id] = {"status": "done", **payload}

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            self._jobs[job_id] = {"status": "error", "error": error}

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._jobs.get(job_id)


class WebUI:
    def __init__(self, output_root: str = "output", fetcher: Optional[Any] = None):
        self.extractor = NovelExtractor(output_root=output_root, fetcher=fetcher)
        self.jobs = _Jobs()

    # -- request handling ---------------------------------------------------

    def handle_analyze(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.extractor.analyze(body["url"])

    def handle_download(self, body: dict[str, Any]) -> dict[str, Any]:
        job_id = self.jobs.create()
        url = body["url"]

        def run() -> None:
            try:
                result = self.extractor.extract(url)
                export = self.extractor.export_txt(result)
                ok = sum(1 for c in result.chapters if c.content_status.value == "CONTENT_OK")
                self.jobs.finish(
                    job_id,
                    {
                        "book_title": result.metadata.book_title,
                        "author": result.metadata.author,
                        "direction": result.direction.value,
                        "chapters": len(result.chapters),
                        "chapters_ok": ok,
                        "flagged": len(result.chapters) - ok,
                        "output_dir": str(export.book_dir),
                        "merged_file": str(export.merged_file) if export.merged_file else None,
                        "warnings": result.stats.get("warnings", [])[:10],
                    },
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the browser
                self.jobs.fail(job_id, f"{type(exc).__name__}: {exc}")

        threading.Thread(target=run, daemon=True).start()
        return {"job_id": job_id}

    def handle_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        return job or {"status": "unknown"}

    def make_server(self, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
        webui = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_json(self, code: int, payload: dict[str, Any]) -> None:
                self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self._send(200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif self.path.startswith("/api/job/"):
                    self._send_json(200, webui.handle_job(self.path.rsplit("/", 1)[-1]))
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid json"})
                    return
                try:
                    if self.path == "/api/analyze":
                        self._send_json(200, webui.handle_analyze(body))
                    elif self.path == "/api/download":
                        self._send_json(200, webui.handle_download(body))
                    else:
                        self._send_json(404, {"error": "not found"})
                except Exception as exc:  # noqa: BLE001
                    self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

        return ThreadingHTTPServer((host, port), Handler)


def serve(output_root: str = "output", host: str = "127.0.0.1", port: int = 8765,
          fetcher: Optional[Any] = None) -> None:
    server = WebUI(output_root=output_root, fetcher=fetcher).make_server(host, port)
    print(f"WebUI: http://{host}:{port}  (Ctrl+C 停止)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()

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
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>小说提取器</title>
<style>
:root { color-scheme: light; --ink:#172033; --muted:#687386; --line:#dce3ee; --panel:#fff; --brand:#4f46e5; --brand2:#7c3aed; --ok:#087a55; --bad:#c33b4a; }
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; font-family:Inter,"Segoe UI",system-ui,sans-serif; color:var(--ink); background:radial-gradient(circle at 12% 0,#e8e7ff 0,transparent 34%),#f5f7fb; }
.shell { width:min(920px,calc(100% - 32px)); margin:0 auto; padding:56px 0 72px; }
header { margin-bottom:28px; }
.eyebrow { display:inline-flex; align-items:center; gap:8px; color:var(--brand); font-size:.78rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }
.eyebrow::before { content:""; width:8px; height:8px; border-radius:50%; background:currentColor; box-shadow:0 0 0 5px #4f46e51a; }
h1 { margin:12px 0 8px; font-size:clamp(2rem,6vw,3.5rem); line-height:1; letter-spacing:-.05em; }
.lead { margin:0; max-width:650px; color:var(--muted); line-height:1.7; }
.card { background:#fffffff2; background:color-mix(in srgb,var(--panel) 92%,transparent); border:1px solid #ffffffb8; border-radius:22px; box-shadow:0 18px 50px #31405b17; backdrop-filter:blur(16px); }
.command { padding:22px; }
label { display:block; margin-bottom:9px; font-size:.86rem; font-weight:750; }
.actions { display:grid; grid-template-columns:minmax(0,1fr) auto auto; gap:10px; }
input { width:100%; min-width:0; padding:13px 15px; border:1px solid var(--line); border-radius:12px; background:#fff; color:var(--ink); font:inherit; outline:none; transition:.2s; }
input:focus { border-color:var(--brand); box-shadow:0 0 0 4px #4f46e51a; }
button { border:0; border-radius:12px; padding:0 18px; min-height:48px; font:inherit; font-weight:750; cursor:pointer; transition:transform .15s,opacity .15s,box-shadow .15s; }
button:hover:not(:disabled) { transform:translateY(-1px); }
button:disabled { cursor:not-allowed; opacity:.55; }
.secondary { color:#3c4659; background:#eef1f7; }
.primary { color:#fff; background:linear-gradient(135deg,var(--brand),var(--brand2)); box-shadow:0 8px 20px #4f46e533; }
.progress-card { margin-top:18px; padding:22px; }
.status-row { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.status-row h2 { margin:0 0 5px; font-size:1.08rem; }
.current { margin:0; color:var(--muted); min-height:1.5em; overflow-wrap:anywhere; }
.badge { flex:none; padding:6px 10px; border-radius:999px; color:#4f46e5; background:#ede9fe; font-size:.75rem; font-weight:800; }
.badge.done { color:var(--ok); background:#dff7ed; }
.badge.error { color:var(--bad); background:#ffe6e9; }
.track { height:10px; margin:20px 0 12px; overflow:hidden; border-radius:999px; background:#e7eaf1; }
.bar { width:0; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--brand),#9b5cf6); transition:width .35s ease; }
.track.indeterminate .bar { width:38%; animation:scan 1.25s ease-in-out infinite; }
@keyframes scan { from { transform:translateX(-110%); } to { transform:translateX(290%); } }
.meta { display:flex; flex-wrap:wrap; justify-content:space-between; gap:8px 18px; color:var(--muted); font-size:.84rem; }
.summary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:18px; }
[hidden] { display:none!important; }
.metric { padding:13px; border:1px solid var(--line); border-radius:13px; background:#f8f9fc; }
.metric span { display:block; color:var(--muted); font-size:.72rem; }
.metric strong { display:block; margin-top:4px; font-size:1.08rem; overflow-wrap:anywhere; }
details { margin-top:18px; }
summary { color:var(--muted); font-size:.82rem; cursor:pointer; }
pre { max-height:330px; margin:10px 0 0; padding:16px; overflow:auto; border-radius:14px; background:#111827; color:#dbeafe; font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace; white-space:pre-wrap; overflow-wrap:anywhere; }
.hint { margin:13px 2px 0; color:var(--muted); font-size:.78rem; }
@media (max-width:700px) { .shell{padding-top:32px}.actions{grid-template-columns:1fr 1fr}.actions input{grid-column:1/-1}.summary{grid-template-columns:1fr 1fr}button{padding:0 12px} }
@media (prefers-reduced-motion:reduce) { *{scroll-behavior:auto!important;animation-duration:.01ms!important;transition-duration:.01ms!important} }
</style></head><body><main class="shell">
<header><span class="eyebrow">Local extraction workspace</span><h1>小说提取器</h1><p class="lead">自动识别目录、章节顺序与分页关系。所有解析都在本机完成，无书源、无 API Key、无云端 AI。</p></header>
<section class="card command">
  <label for="url">小说或章节网址</label>
  <div class="actions"><input type="url" id="url" autocomplete="url" placeholder="https://example.com/book/123/">
    <button class="secondary" id="analyzeBtn" onclick="doAnalyze()">分析页面</button><button class="primary" id="downloadBtn" onclick="doDownload()">开始提取</button></div>
  <p class="hint">提取期间可以留在本页查看进度；关闭页面不会中止后台任务。</p>
</section>
<section class="card progress-card" id="progressCard" aria-live="polite">
  <div class="status-row"><div><h2 id="stageLabel">等待开始</h2><p class="current" id="currentTitle">输入网址后开始分析或提取。</p></div><span class="badge" id="statusBadge">待命</span></div>
  <div class="track" id="progressTrack" role="progressbar" aria-label="提取进度" aria-valuemin="0" aria-valuemax="100"><div class="bar" id="progressBar"></div></div>
  <div class="meta"><span id="countLabel">尚未提取章节</span><span id="intervalLabel">本地任务</span></div>
  <div class="summary" id="summary" hidden>
    <div class="metric"><span>作品</span><strong id="bookTitle">—</strong></div><div class="metric"><span>章节</span><strong id="chapters">—</strong></div>
    <div class="metric"><span>正常正文</span><strong id="chaptersOk">—</strong></div><div class="metric"><span>需检查</span><strong id="flagged">—</strong></div>
  </div>
  <details><summary>查看任务详情</summary><pre id="out">等待输入…</pre></details>
</section>
</main><script>
const byId = id => document.getElementById(id);
const out = byId('out'), track = byId('progressTrack'), bar = byId('progressBar');
const phases = {queued:'任务已排队',discovering:'正在分析目录',extracting:'正在提取正文',exporting:'正在生成文件',done:'提取完成',error:'提取失败'};
let pollToken = 0;
function show(obj) { out.textContent = JSON.stringify(obj, null, 2); }
function setBusy(busy) { byId('analyzeBtn').disabled=busy; byId('downloadBtn').disabled=busy; }
function getUrl() { const value=byId('url').value.trim(); if(!value){throw new Error('请先输入小说网址。')} return value; }
async function post(path, body) {
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const data=await r.json();
  if(!r.ok||data.error) throw new Error(data.error||('请求失败：HTTP '+r.status)); return data;
}
function renderProgress(state) {
  const p=state.progress||{}, done=Number(p.done||0), total=Number(p.total||0), finished=state.status==='done';
  const percent=finished?100:(Number.isFinite(p.percent)?p.percent:(total>0?Math.min(100,done/total*100):null));
  byId('stageLabel').textContent=phases[p.phase]||phases[state.status]||'正在处理';
  byId('currentTitle').textContent=state.error||p.message||p.title||'正在准备提取任务…';
  byId('statusBadge').textContent=finished?'已完成':state.status==='error'?'失败':'进行中';
  byId('statusBadge').className='badge '+(finished?'done':state.status==='error'?'error':'');
  track.classList.toggle('indeterminate',percent===null&&state.status==='running');
  bar.style.width=(percent===null?0:percent)+'%';
  if(percent===null)track.removeAttribute('aria-valuenow');else track.setAttribute('aria-valuenow',String(Math.round(percent)));
  byId('countLabel').textContent=total>0?`已处理 ${done} / ${total} 章`:(done>0?`已处理 ${done} 章`:'正在识别章节数量');
  byId('intervalLabel').textContent=p.interval?`请求间隔 ${Number(p.interval).toFixed(1)} 秒`:'本地后台任务';
  if(finished){ byId('summary').hidden=false; byId('bookTitle').textContent=state.book_title||'未识别'; byId('chapters').textContent=state.chapters??'—'; byId('chaptersOk').textContent=state.chapters_ok??'—'; byId('flagged').textContent=state.flagged??'—'; }
  show(state);
}
function renderError(error) { renderProgress({status:'error',error:error.message,progress:{phase:'error'}}); setBusy(false); }
async function doAnalyze() {
  pollToken++; setBusy(true); bar.style.width='0'; byId('statusBadge').textContent='进行中'; byId('statusBadge').className='badge'; byId('stageLabel').textContent='正在分析页面'; byId('currentTitle').textContent='识别页面类型、元数据与导航关系…'; track.classList.add('indeterminate');
  try { const data=await post('/api/analyze',{url:getUrl()}); show(data); byId('stageLabel').textContent='分析完成'; byId('currentTitle').textContent=data.book_title||data.title||'已生成分析结果，请展开任务详情查看。'; byId('statusBadge').textContent='已完成'; byId('statusBadge').className='badge done'; }
  catch(error){renderError(error)} finally { track.classList.remove('indeterminate'); setBusy(false); }
}
async function doDownload() {
  const token=++pollToken; setBusy(true); byId('summary').hidden=true;
  try { const job=await post('/api/download',{url:getUrl()}); renderProgress({status:'running',progress:{phase:'queued',message:'任务已提交，等待分析入口页面…'}}); poll(job.job_id,token); }
  catch(error){renderError(error)}
}
async function poll(id,token) {
  if(token!==pollToken)return;
  try { const r=await fetch('/api/job/'+encodeURIComponent(id)); const state=await r.json(); renderProgress(state); if(state.status==='running'){setTimeout(()=>poll(id,token),900)}else{setBusy(false)} }
  catch(error){renderError(error)}
}
</script></body></html>"""


class _Jobs:
    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {
                "status": "running",
                "progress": {
                    "phase": "queued", "done": 0, "total": None,
                    "title": "", "chapter_status": "", "interval": 0.0,
                    "percent": None, "message": "任务已排队",
                },
            }
        return job_id

    def progress(self, job_id: str, **payload: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.get("status") != "running":
                return
            job["progress"] = {**job.get("progress", {}), **payload}

    def finish(self, job_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._jobs[job_id] = {"status": "done", **payload}

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            previous = self._jobs.get(job_id, {})
            progress = {**previous.get("progress", {}), "phase": "error", "message": error}
            self._jobs[job_id] = {"status": "error", "error": error, "progress": progress}

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None


class WebUI:
    def __init__(self, output_root: str = "output", fetcher: Optional[Any] = None):
        self.output_root = output_root
        # Production WebUI tasks deliberately do not share a long-lived
        # HttpFetcher.  httpx resolves environment/system proxy settings when
        # its client is created, so a fresh extractor lets every task observe
        # proxy changes made while the WebUI server remains open.
        #
        # An explicitly injected fetcher is kept for tests and callers that
        # own the fetcher's lifecycle.
        self.extractor = (
            NovelExtractor(output_root=output_root, fetcher=fetcher)
            if fetcher is not None
            else None
        )
        self.jobs = _Jobs()

    def _task_extractor(self) -> tuple[NovelExtractor, bool]:
        if self.extractor is not None:
            return self.extractor, False
        return NovelExtractor(output_root=self.output_root), True

    @staticmethod
    def _close_task_extractor(extractor: NovelExtractor, owned: bool) -> None:
        if not owned:
            return
        close = getattr(extractor.fetcher, "close", None)
        if callable(close):
            close()

    # -- request handling ---------------------------------------------------

    def handle_analyze(self, body: dict[str, Any]) -> dict[str, Any]:
        extractor, owned = self._task_extractor()
        try:
            return extractor.analyze(body["url"])
        finally:
            self._close_task_extractor(extractor, owned)

    def handle_download(self, body: dict[str, Any]) -> dict[str, Any]:
        job_id = self.jobs.create()
        url = body["url"]

        def run() -> None:
            extractor, owned = self._task_extractor()
            try:
                self.jobs.progress(
                    job_id, phase="discovering", message="正在识别入口页面与章节目录…"
                )

                def report_progress(done, total, title, status, interval=0.0) -> None:
                    known_total = total if isinstance(total, int) and total > 0 else None
                    percent = round(min(100.0, done / known_total * 100), 1) if known_total else None
                    self.jobs.progress(
                        job_id, phase="extracting", done=done, total=known_total,
                        title=title, chapter_status=status, interval=interval,
                        percent=percent, message="",
                    )

                result = extractor.extract(url, progress=report_progress)
                chapter_count = len(result.chapters)
                self.jobs.progress(
                    job_id, phase="exporting", done=chapter_count, total=chapter_count,
                    percent=100.0, message="正文提取完成，正在写入输出文件…",
                )
                export = extractor.export_txt(result)
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
                        "progress": {
                            "phase": "done", "done": chapter_count, "total": chapter_count,
                            "percent": 100.0, "message": "文件已保存",
                        },
                    },
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the browser
                self.jobs.fail(job_id, f"{type(exc).__name__}: {exc}")
            finally:
                self._close_task_extractor(extractor, owned)

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

# novel-extractor

从陌生小说网页自动推断页面类型、目录、章节、分页、正文与章节关系，并导出 TXT/EPUB。核心解析不依赖站点专用选择器、API Key 或云端 AI。

> 当前状态：`0.1.0-alpha`。适合本地使用和参与开发，尚未承诺对所有网站稳定兼容。

## 主要能力

- 从详情页、目录页或章节页开始分析。
- 识别正序/倒序目录、目录分页、章内分页和章节导航。
- 合并多页章节，检测缺章、循环、跨域跳转和受限页面。
- 结合 DOM 密度、章节标题锚点和跨章节重复模板识别正文。
- 导出分章 TXT、合并 TXT、下载汇总，可选 EPUB。
- 提供 CLI、Python API 和本地 WebUI，三者共享同一核心库。

## 安装

需要 Python 3.10 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Linux/macOS 请将 `.\.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。

安装测试依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

可选开发依赖包含 EPUB、Playwright 和 QuickJS 支持：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m playwright install chromium
```

## 使用

```powershell
novel-extractor download <url> --output output --interval 0.3
novel-extractor analyze <url>
novel-extractor inspect <url>
novel-extractor cache list
novel-extractor web --port 8765 --output output
```

下载流程为：页面分类 → 目录发现与补全 → 阅读顺序判断 → 逐章下载与分页合并 → 正文清洗 → 导出。

结束返回码为 `1` 表示存在受限或异常章节。不要只看生成文件，应同时检查 `下载汇总.txt` 中的状态和警告。

Python API：

```python
from novel_extractor import NovelExtractor

extractor = NovelExtractor()
result = extractor.extract(url)
result.export_txt("./output")
analysis = extractor.analyze(url)
```

## 测试与基准

默认测试不访问互联网：

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe benchmarks\runner.py
```

真实 Playwright/网络测试是显式选择项：

```powershell
$env:NOVEL_EXTRACTOR_RUN_LIVE_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest tests\test_browser_fetcher.py
```

基准 fixture 为项目生成的离线测试页面，不包含下载小说正文。每种新兼容结构都应增加测试或 benchmark，禁止通过站点域名特判提高分数。

## 网络与安全说明

- 一些网站会拒绝境外网络、程序化请求或异常频率，请遵守网站规则并合理设置请求间隔。
- Clash 等代理的 Fake-IP/TUN 配置可能导致浏览器可访问、Python 无法连接；遇到 `WinError 10061` 时先检查 DNS 和代理链路。
- HTTPS 证书校验失败时，抓取器会依次尝试默认 CA、系统信任库，最后可能回退到未验证 TLS，并在页面 diagnostics 中记录 `tls_verification_skipped`。不要把它用于凭据、私密内容或其他敏感传输。
- 本工具不会绕过登录、付费墙或访问控制；受限页面会被标记而不是静默保存为正常正文。

## 合法使用

仅下载你有权访问和保存的内容，并遵守目标网站的服务条款、robots 约定及当地法律。`output/` 默认不会进入版本控制；不要向仓库提交下载的小说正文。

## 项目结构

- `src/novel_extractor/fetcher/`：HTTP、编码和可选浏览器抓取。
- `src/novel_extractor/analyzer/`：页面、目录、标题、正文、分页与导航推断。
- `src/novel_extractor/crawler/`：抓取编排、安全边界和结果汇总。
- `src/novel_extractor/cleaner/`：保守文本清洗。
- `src/novel_extractor/exporter/`：TXT/EPUB 导出。
- `tests/`：默认离线测试。
- `benchmarks/`：跨结构离线基准。

## License

源代码以 MIT License 发布，详见 `LICENSE`。第三方网站内容及下载文本不包含在本项目许可范围内。

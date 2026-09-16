# AGENTS.md — development rules

本文件供 AI agent 和协作者在修改项目时遵守。

## 核心边界

- 不得针对具体域名硬编码 CSS Selector、XPath 或特殊解析分支。
- 章节内分页、目录分页和章节跳转必须保持为不同关系。
- 目录 DOM 顺序必须经 `CatalogOrderDetector` 判断后才能作为阅读顺序。
- Fetcher 必须显式处理中文编码，不得无条件信任 `response.text`。
- VIP、登录、空正文和异常页面不得静默保存成正常正文。
- 证据不足时降低 confidence 或返回失败，不伪造元数据、章节或顺序。
- URL 形状只能作为辅助证据，不能单独决定章节关系。
- CLI、WebUI 和 Python API 必须共享核心库。
- 核心功能不得依赖 API Key 或云端 AI。

## 修改规则

- 优先最小、通用、可解释的修复，不堆叠站点特例。
- 新算法必须附带测试；兼容新页面结构时补 fixture/benchmark。
- 默认测试必须完全离线；真实浏览器或网络测试必须显式选择。
- 不提交 `.venv/`、`output/`、日志、缓存或下载正文。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe benchmarks\runner.py
```

发布前还要检查 `git status --short`，确认提交清单不含本地文件或版权内容。

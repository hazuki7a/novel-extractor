# benchmarks

本地基准测试：衡量结构规则并防止回归。**默认不访问互联网。**

这里有两条明确分开的基线：

- `runner.py` + `sites/`：历史 synthetic 回归门槛，保留原有 12 组结构样本。
- `offline_runner.py` + `cases/` + `fixtures/`：按 `CODEX_TASK.md` 建立的 v1 标注合同、输入适配器、独立评估器和分组报告。

两者都不是 20 个真实站点测试。`benchmark_sites.json` 中的真实 fixture 数仍为 0，所有候选站点继续保持 pending。

## 结构

```
benchmarks/
  build_contract_fixtures.py # 生成项目原创的 v1 synthetic 合同用例
  offline_contract.py        # 只读取 case.json/输入，绝不读取 expected.json
  offline_runner.py          # 先推断、后由评估器读取 expected.json
  failure_diagnostics.py     # 失败分类、目录候选和分页关系候选诊断
  reporting.py               # 由已完成的评测结果生成 Markdown/JSON 分析
  freeze_baseline.py         # 固化 baseline_v0 与 failure_analysis
  cases/                     # READY/DRAFT 用例合同与独立预期
  fixtures/synthetic/        # 项目原创的 HTML/字节/参考文本
  SYNTHETIC_COVERAGE.json    # synthetic 覆盖账本，不代表真实站点支持
  generate_fixtures.py   # 一次性生成 sites/（保留生成逻辑作为出处说明）
  runner.py              # Runner：跑完整 NovelCrawler 管线并按 expected.json 评分
  sites/siteXXX_*/       # 每个 fixture 站点：*.html + expected.json
  reports/               # run_all 输出的 JSON 报告（版本比较用）
```

覆盖结构（对应 guide benchmark.must_cover_structures）：

| 站点 | 结构 |
|---|---|
| site001 | `<p>` 正文、正序目录、og 元数据 |
| site002 | `<br>` 正文、倒序目录（需方向纠正） |
| site003 | GBK 编码（meta charset=gbk → GB18030 解码） |
| site004 | 章节内分页（“下一章”误标分页、章节标题校验、密集推荐区竞争） |
| site005 | 目录分页（两页目录合并，16 章） |
| site006 | 随机章节 URL（非连续 ID） |
| site007 | query 参数章节 URL |
| site008 | VIP / 登录 / 空正文受限页 |
| site009 | 无目录（仅上一章/下一章遍历） |
| site010 | 正文夹广告 + 从详情页开始 |
| site011 | 折叠目录、子编号章节、全书逻辑章节合并 |
| site012 | 仅 onclick 的目录链接 |

## 指标

Page Classification、Metadata、Catalog Detected/Direction/Recall/Pagination、
Chapter Order、Content Success/Pagination、Restricted Status、Navigation、
False Positive —— 全部按站点加权聚合。

## 运行

```bash
# 校验20站候选清单（不运行解析器）
.venv/Scripts/python benchmarks/tools/check_plan.py

# 校验 READY case 的文件、哈希、URL、引用和标签（不运行解析器）
.venv/Scripts/python benchmarks/tools/check_cases.py

# 运行全部 v1 离线合同；已知基线失败会返回非零退出码
.venv/Scripts/python benchmarks/offline_runner.py --report-dir benchmarks/reports/local

# 各类别必须分开运行；real_fixture 目前应得到 NO_ELIGIBLE_CASES/N/A
.venv/Scripts/python benchmarks/offline_runner.py --sample-type synthetic --report-file benchmarks/reports/local/synthetic.json
.venv/Scripts/python benchmarks/offline_runner.py --sample-type real_fixture --report-file benchmarks/reports/local/real_fixture.json
.venv/Scripts/python benchmarks/offline_runner.py --sample-type challenge --report-file benchmarks/reports/local/challenge.json

# 固化可比较基线与失败分析（不修改 fixture 或 expected.json）
.venv/Scripts/python benchmarks/freeze_baseline.py

# 重建 fixture（结构变更时）
.venv/Scripts/python benchmarks/generate_fixtures.py

# 跑 benchmark 并输出报告
.venv/Scripts/python benchmarks/runner.py
```

`build_contract_fixtures.py` 是 synthetic fixture 的一次性维护脚本，会重建
用例和预期；日常 Benchmark、基线冻结和失败分析不得调用它。人工审核后的
`expected.json` 是 ground truth，Runner 不会自动生成或覆盖它。

`tests/test_benchmark.py` 在 pytest 内跑同一 Runner 并断言指标门槛，
核心算法修改后必须全绿；指标下降需要在提交说明中记录原因。
禁止通过站点特例提高分数；修复某类结构时把对应 HTML 加入 sites/。

`tests/test_offline_benchmark.py` 验证新合同的离线隔离、HTTP 字节解码、
fragment 身份、哈希校验和 N/A 分母语义。新 Runner 的当前失败项是规则
baseline 的真实缺口，不得通过让评估器读取 gold selector 或 expected 标签消除。

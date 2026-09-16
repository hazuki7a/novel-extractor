# benchmarks

本地基准测试（guide task 16）：衡量跨站点泛化能力，防止回归。**默认不访问互联网。**

## 结构

```
benchmarks/
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
# 重建 fixture（结构变更时）
.venv/Scripts/python benchmarks/generate_fixtures.py

# 跑 benchmark 并输出报告
.venv/Scripts/python benchmarks/runner.py
```

`tests/test_benchmark.py` 在 pytest 内跑同一 Runner 并断言指标门槛，
核心算法修改后必须全绿；指标下降需要在提交说明中记录原因。
禁止通过站点特例提高分数；修复某类结构时把对应 HTML 加入 sites/。

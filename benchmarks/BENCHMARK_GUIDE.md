# 中文小说网页提取：Benchmark 建设指南

**版本：1.0.0 · 整理与来源核验日期：2026-09-16**

适用于“无需人工书源、以本地规则与结构分析提取中文小说”的项目。本指南用于建设测试集、标注预期结果、接入离线评测，并为以后引入机器学习保留可比较的基线。

> 这是一份 **20 个候选来源的采集计划**，不是已经完成的 20 站测试集。
> 本包未批量抓取小说，没有附带真实网页 HTML，也没有测出任何成功率。
> 所有站点的 `actual_fixture_count` 初始为 `0`。

## 0. 来源、假设与本次修正

沿用此前讨论的 **15 个中文主要候选来源 + 5 个专项来源**，不把它们都列为“静态解析必须成功”的网站。

本次对官方入口及部分示例页做了检索核验；这不等于使用你的 Fetcher 抓取，也不等于检查过完整原始 HTML。`benchmark_sites.json` 将 `source_review`、`test_hypotheses`、`validated_features` 分开保存。

需要特别注意以下核验结果：

- SF 轻小说示例中确实可见分卷、楔子及章节列表，可作为分卷目录的优先采样入口。[S06]
- 七猫示例能看到书名、作者和前后章导航，但检索文本没有证明完整正文已经取得。必须再比较原始响应与浏览器页面。[S04]
- 此前把纵横直接说成“已确认倒序目录测试站”不够严谨：本次示例检索未确认排序控件。保留为目录方向测试候选，实际方向由快照决定。[S02]
- 咪咕当前入口显示作者服务平台；先标记 `NEEDS_ENTRY_CONFIRMATION`，不能凑入“已找到可测试的小说阅读站”。[S13]
- 起点、飞卢、Standard Ebooks 的部分入口在本次检索中没有拿到可用内容。工具抓取失败不能等同于站点离线、403 或确定使用反爬。
- 99 藏书网的依据是此前用户提供的一次解析日志：HTTP 403，正文预览为 `Enable JavaScript and cookies to continue`。它能指导错误场景设计，但不是可直接回放的 HTML fixture。[S16]
- 青空文库图书卡对一个具体 XHTML 文件标注了 ShiftJIS；这不是所有页面编码的保证，更不能代替中文 GBK 专项测试。[S17]

**站点名称决定去哪里找样本，快照证据决定给样本贴什么标签。**

## 1. 文件怎么放进项目

将本包的 `benchmarks/` 合并到仓库。若已有同名文件，先查看差异，不直接覆盖。

```text
benchmarks/
├── BENCHMARK_GUIDE.md
├── benchmark_sites.json
├── CODEX_TASK.md
├── .gitignore
├── tools/
│   └── check_plan.py
├── templates/
│   ├── case.template.json
│   ├── expected.template.json
│   └── report.template.json
├── cases/                  # 人工审核通过的用例描述
├── fixtures/
│   ├── private/            # 未获公开许可的输入、私人采集结果
│   ├── public/             # 权限与隐私审核通过的样本
│   └── synthetic/          # 自制最小 HTML / 字节样本，单独统计
└── reports/                # 固定版本评测报告
```

`check_plan.py` 只校验清单和模板的一致性，不访问网络、不调用解析器，也不证明网站可抓取。

```bash
python benchmarks/tools/check_plan.py
```

项目的离线 Benchmark Runner 还需要按 `CODEX_TASK.md` 接入现有代码。本文中的字段是建议的评测合同，不表示仓库已经实现这些接口。

## 2. 测试必须分组

不要把“20 个来源”直接当成同一种分母。按实际采集到的输入分组：

| 测试组 | 输入 | 主要判断 |
|---|---|---|
| `CN_STATIC_CONTENT` | 响应中已存在中文目标正文/目录 | 提取、导航、分页、排序是否正确 |
| `CN_ACCESS_STATE` | 验证页、登录提示、付费提示、限流等 | 能否识别状态并避免导出伪正文 |
| `CN_DYNAMIC_INPUT` | 同 URL 的初始响应与浏览器 DOM | 是否正确区分输入来源；渲染后能否解析 |
| `ENCODING` | 解码前字节及采集元信息 | 是否得到正确中文，而不只是猜中编码名称 |
| `CROSS_LANGUAGE` | 日文/英文文本 | 单独观察泛化，不混进中文主指标 |
| `NON_HTML_NEGATIVE` | 扫描阅读器、营销页、非小说页面 | 不应声称完成小说正文提取 |
| `SYNTHETIC_REGRESSION` | 自制、可控的最小结构样本 | 回归逻辑正确性，不代表真实网站兼容率 |

一个站点可以同时提供不同组的样本。不能把长佩永久标为动态站，把起点永久标为付费页，也不能将 403 一律解释为反爬。

## 3. 20 个候选来源

P1/P2/P3 表示**建议采集顺序**，不是质量排名或已通过程度。表中的能力是“希望在该来源寻找的场景”，不是现成覆盖结论。

| # | 候选来源 / ID | 优先级 | 待验证测试场景 | 来源 |
|---|---|---|---|---|
| 1 | [起点中文网](https://www.qidian.com/) `qidian` | P2 | 分卷结构、中文章节标题、访问与权限状态、书名与作者 | [S01] |
| 2 | [纵横中文网](https://www.zongheng.com/) `zongheng` | P1 | 目录方向、目录链接分组、前后章导航、书名与作者 | [S02] |
| 3 | [17K小说网](https://www.17k.com/) `17k` | P1 | 目录链接分组、前后章导航、正文区域、书名与作者 | [S03] |
| 4 | [七猫中文网](https://www.qimao.com/) `qimao` | P1 | 书名与作者、前后章导航、正文是否实际存在于输入、原始响应与渲染 DOM | [S04] |
| 5 | [番茄小说](https://fanqienovel.com/) `fanqie` | P2 | 原始响应与渲染 DOM、正文区域、目录链接分组 | [S05] |
| 6 | [SF轻小说](https://book.sfacg.com/) `sfacg` | P1 | 分卷结构、楔子、番外等特殊章节、中文章节标题、目录链接分组 | [S06] |
| 7 | [刺猬猫](https://www.ciweimao.com/) `ciweimao` | P2 | 桌面与移动模板、访问与权限状态、前后章导航 | [S07] |
| 8 | [晋江文学城](https://www.jjwxc.net/) `jjwxc` | P2 | 楔子、番外等特殊章节、书名与作者、访问与权限状态、实际编码核验 | [S08] |
| 9 | [长佩文学](https://www.gongzicp.com/) `gongzicp` | P2 | 原始响应与渲染 DOM、访问与权限状态、目录链接分组 | [S09] |
| 10 | [豆瓣阅读](https://read.douban.com/) `douban_read` | P2 | 书名与作者、简介、试读与全文区分、访问与权限状态 | [S10] |
| 11 | [飞卢中文网](https://b.faloo.com/) `faloo` | P3 | 访问与权限状态、目录链接分组、书名与作者 | [S11] |
| 12 | [书旗中文网](https://www.shuqi.com/) `shuqi` | P2 | 阅读入口发现、桌面与移动模板、正文是否实际存在于输入 | [S12] |
| 13 | [咪咕文学](https://www.cmread.com/) `cmread` | P3 | 阅读入口发现、排除非阅读页面 | [S13] |
| 14 | [中文维基文库](https://zh.wikisource.org/) `wikisource_zh` | P1 | 古典“第X回”标题、简体与繁体、层级目录、前后章导航 | [S14] |
| 15 | [Project Gutenberg中文书库](https://www.gutenberg.org/browse/languages/zh) `gutenberg_zh` | P1 | 单文件整本书、页内章节锚点、书名与作者、头尾说明文字 | [S15] [S21] [S22] |
| 16 | [99藏书网](https://www.99csw.com/) `99csw` | P1 | 验证页识别与安全停止、不输出伪书名、异常输入限制正文评分 | [S16] |
| 17 | [青空文庫](https://www.aozora.gr.jp/) `aozora` | P2 | Shift-JIS字节解码、日文注音标记、跨语言泛化 | [S17] |
| 18 | [Royal Road](https://www.royalroad.com/) `royalroad` | P3 | 跨语言泛化、楔子、番外等特殊章节、目录链接分组 | [S18] |
| 19 | [Standard Ebooks](https://standardebooks.org/) `standardebooks` | P3 | 语义化 HTML 候选、单文件整本书、跨语言泛化 | [S19] |
| 20 | [Open Library](https://openlibrary.org/) `openlibrary` | P3 | 非普通 HTML 阅读器、扫描书输入、不适用输入识别 | [S20] |

前 15 项是中文主要候选池；后 5 项为专项池，其中 99 藏书网仍是中文场景。每个站点更具体的采样方法、示例入口和未确认事项见 `benchmark_sites.json`。

**这份清单仍缺少经过字节和 DOM 核验的中文旧式网站样本。** 不要因为列满 20 项，就宣布 GBK、table 布局、章节内分页等已经覆盖。

## 4. 从候选网站到可执行用例

### 第一步：选择小范围作品样本

每个普通来源先选一部可正常访问、适合采集的作品。建议保存作品页、目录页和 2～3 个相邻章节；若作品页与目录页是同一页，不重复计数。

特殊样本按需要增加：第二个目录页、同一章的第二页、特殊章节、实际出现的受限页。单文件整本书可以只采一个 HTML，再标注内部章节边界。

这是开发采样，不是整本批量下载。先完成少量可靠样本，再扩大范围。普通平台的公开可读页面不自动等于可以公开再分发；公开仓库优先采用自行创作、明确获授权或经核对可按许可发布的材料。

### 第二步：记录输入，而不是只保存程序的输出

一个用例建议包含：

```text
case_001/
├── case.json
├── expected.json
├── input/
│   ├── catalog_body.bin
│   ├── catalog_http.json
│   ├── chapter_01_body.bin
│   └── chapter_01_http.json
└── reference/
    ├── chapter_01.txt
    └── reading_order.json
```

用于编码测试的 `.bin` 应是**HTTP 内容解压后、字符解码前**的响应体字节，例如尚未调用文本解码的响应内容。不要先错误解码再存成 UTF-8。HTTPX 对文本的解码策略见官方文档。[S23]

最少记录：请求 URL、最终 URL、采集时间、HTTP 状态、Content-Type、输入类型、文件路径、SHA-256。没有取得某项数据就填 `null`；手动保存的网页没有响应头时，不伪造 `200` 或 `charset=utf-8`。

只保留必要且已检查的 HTTP 元信息，不把 Cookie、Set-Cookie、Authorization、账号信息或完整 HAR 默认收入仓库。

### 第三步：区分 HTTP 输入与浏览器输入

- `HTTP_BYTES`：适合测试获取后的解码及静态 HTML 解析。
- `BROWSER_DOM`：用户授权浏览器中的渲染 DOM 序列化结果。
- `SYNTHETIC_HTML`：自制回归样本，必须标为 synthetic。

浏览器保存成 UTF-8 的 DOM 不是服务器原始 GBK 字节，不能用于证明原始编码检测正确。原始响应没有正文、渲染后才有正文的情况，应保存两份关联输入，分别评测，不替换前者后声称 HttpFetcher 成功。

### 第四步：人工标注预期结果

复制 `case.template.json` 和 `expected.template.json`。至少完成：

- 页面类型、访问状态、是否应进行正常正文/书名提取；
- 已确认的书名、作者、章节标题；
- 正文参考文本与需要排除的区域；
- 目录项、卷归属、原始出现顺序及实际阅读顺序；
- 前后章、章节内分页、目录分页关系。

未知字段保留 `null`，并写明缺少证据。未标注字段不算“识别正确”。

人工标注可以记录正文 XPath 来定位真值，但 **该 XPath 只能给评估器看，不能给解析器看**。用例目录名、站点 ID、expected.json、真实正文标签都不能成为推断提示。

### 第五步：复核后才标为 READY

建议先手动看网页，再对照保存的输入核查一次，避免标注的是渲染后的页面、测试的却是初始响应。

只有输入文件存在、哈希正确、关键标签完整、阅读关系有证据、隐私检查完成后，才将用例标为 `READY`。没有形成有效正文样本的网站可以保留为待采集，不必强行凑数。

## 5. 标注规则：最容易出错的地方

### 章节、网页、目录不能一一等同

一章可以对应多个网页；一个网页也可以包含多章。记录 `logical_chapters` 与 `source_page_ids` 的映射，而不是“一 URL = 一章”。

区分三类边：

```text
NEXT_CONTENT_PAGE  —— 同一章节的下一页
NEXT_CATALOG_PAGE  —— 目录的下一页
NEXT_CHAPTER       —— 下一逻辑章节
```

“第1章（上）/（下）”可能是作者发布的独立章节，不应仅因为标题相似就自动合并。应结合目录条目、导航及正文边界标注。

单页作品的 `#chapter-1` 与 `#chapter-2` 可能是不同章节锚点：底层 HTTP 获取可以复用同一文件，但章节身份不能因 URL 去重而丢失 fragment。

### 目录方向按块判断

分别记录 DOM 原始顺序和阅读顺序。分卷编号可能重新从第一章开始；“最新章节”推荐块也可能出现在完整目录前面。

不要把整个链接列表反转一次就当作正确排序。标注 ASCENDING、DESCENDING、UNKNOWN；混合目录可用评测扩展标签 MIXED，随后标注各块实际顺序。现有解析器不支持 MIXED 时保留歧义，不要强行转换成已知方向。

### 正文真值不由解析器自己生成

人工整理参考正文时保留句子、标点和段落边界。清理导航、广告等必须有明确依据，不能删除所有链接文字，也不能仅因一行出现“下一章”就删掉小说对白。

为了降低重复标注成本，可以让工具预填，但必须人工复核。当前版本的提取结果不能直接作为 expected，再拿来证明当前版本正确。

### 编码比较以文本正确性为主

纯 ASCII 或某些兼容字符的字节无法唯一确定编码名称。标注可以同时记录“来源声明”和“解码结果经人工确认”。

对于存在等价正确结果的样本，不要仅因解析器选择了兼容编码名称就判失败。另用确实包含相关扩展字符的已知字节样本测试差异。保留 HTTP/meta 冲突，不先改正输入再测试。

### 访问异常与正文质量分开

HTTP 403 只是信号，要结合页面内容区分权限拒绝、验证挑战或其他异常。短正文也可能是真实序章，不能只按字数判为反爬。

对 99 藏书网此前那类验证页，预期应是识别挑战/受限状态、不输出小说名、不把提示语导出成正文。当前已有日志不足以回放，应补原始响应，或另建明确标为 synthetic 的等价回归例。

`confidence=0.9` 默认只是算法评分，不应直接解释成“90% 成功概率”。评测时用人工真值检查不同评分区间的错误分布，不靠任意权重相乘制造概率。

## 6. 必须跟踪的覆盖缺口

以下均是待采集的覆盖项目。空候选不是遗漏，而是明确告诉开发者：当前没有证据，不能声称支持。

| 特征 | 候选来源 | 下一步 |
|---|---|---|
| `p_paragraphs` | 17k、qimao、wikisource_zh | 需要真实快照；候选站点不等于已覆盖 |
| `br_paragraphs` | 待补真实来源 | 尚无本地已确认真实来源；可先自制最小 HTML |
| `table_layout` | 待补真实来源 | 补充中文旧式 table 布局；20站名单未保证覆盖 |
| `gbk_gb2312_gb18030` | 待补真实来源 | 必须保留解码前字节；老站身份不是编码证据 |
| `encoding_conflict` | 待补真实来源 | 先用自制字节样本构造 header/meta 冲突，另补真实案例 |
| `content_pagination` | 待补真实来源 | 需要同一章至少两页和下一章；不能从章节标题的上/下推定网页分页 |
| `catalog_pagination` | 待补真实来源 | 需要至少两个目录页及重叠边界；尚未采集 |
| `catalog_descending` | zongheng | 候选目标，需以具体快照及导航证据确认 |
| `volume_number_reset` | sfacg | 分卷文本已检索到；真实 DOM 和章节阅读序需本地标注 |
| `random_urls` | 待补真实来源 | 先构造可复现样例；需补真实非连续 URL 页面链 |
| `no_catalog` | 待补真实来源 | 记录明确 next/previous 链；没有链接不得编造整本顺序 |
| `comments_ads` | jjwxc、qidian | 候选干扰场景；保留真实段落结构 |
| `traditional_simplified` | wikisource_zh | 同模板繁简样本不能拆到开发集和最终测试集 |
| `single_file_fragment_chapters` | gutenberg_zh | 按具体作品确认；保留章节锚点身份 |
| `restricted_pages` | qidian、douban_read | 采集当次实际提示；不由站点名称强行打标签 |
| `anti_bot` | 99csw | 当前仅有用户日志，还缺对应 HTTP 响应体 |
| `dynamic_dom` | fanqie、gongzicp、qimao | 必须有原始响应/渲染 DOM 对照；不能用工具空输出断言 SPA |
| `shift_jis` | aozora | 文件有编码声明；编码正确性仍以字节和人工核对为准 |
| `non_html_reader` | openlibrary | BookReader 文档不是实际 fixture |

缺少真实 GBK、分页、随机 URL 等来源时，先写自制最小样本验证逻辑是合理的，但报告必须将“自制样本通过”与“真实站点通过”分开。

## 7. 离线测试如何接入项目

Benchmark Runner 应通过适配器调用现有 Core，不把站点兼容逻辑写入 Runner：

```text
读取 case.json 和输入快照
        ↓
FixtureFetcher / 输入适配器
        ↓
真实 Analyzer / Crawler / Cleaner / Exporter
        ↓
统一 prediction.json
        ↓
Evaluator 读取 expected.json
        ↓
按组生成报告
```

解析器不能读取 expected.json。离线运行不访问互联网；跨页关系通过用例中的 URL→快照映射回放。缺失关联快照时返回“测试输入缺失”或“超出采样范围”，不能偷偷上线获取。

建议区分两类测试：

1. **模块测试**：编码、正文、标题、目录方向等各自比较，不要求每次重跑下载。
2. **小型端到端测试**：用已保存的目录与 2～3 章页面回放，校验分页合并、顺序、文件名、TXT 和异常章节报告。

完整性判断只限于用例声明的范围。仅采集三章不能声称整本小说下载完整。

## 8. 指标与报告

主报告至少区分中文静态正文、访问状态、动态输入、自制样本及跨语言样本。不要输出一个混合的“20站通过率”。

| 指标 | 建议比较方式 |
|---|---|
| 页面类型 | 在已标注页面上计算准确率，并附混淆情况 |
| 正文提取 | 对规范化后的预测和人工正文做字符序列对齐，分别报告正文保留率与噪声混入；保留顺序检查 |
| 目录发现 | 真实章节项的 precision / recall，排除未标注范围 |
| 章节顺序 | 比较采样子图中的已确认前后关系，另报整条链完全正确率 |
| 分页合并 | 检查各页正文是否完整出现、顺序正确、无重复、未并入下一章 |
| 元数据 | 在已确认字段上计算准确率；缺失作者不要求猜出 |
| 异常页面 | 分别报告识别率、漏报、误报及错误导出正文次数 |
| TXT 导出 | UTF-8、合法文件名、章节顺序及失败报告是否符合预期 |

每项指标写清**分子、分母、样本量**。分母为零显示 N/A，而非 100%。同时保留按站点平均与按页面平均，避免一个拥有几百页的站点支配结果。

低置信度拒绝真实正文属于 abstention，不计为正文提取成功；安全拒绝验证页可以计为状态识别成功。两者不能混合成一个高成功率。

记录代码 commit、依赖锁文件、数据集版本、输入哈希、配置、运行模式、缓存状态。默认用冷缓存测未见站点；热缓存性能另报，不能让从测试集学来的缓存污染泛化结果。

## 9. 为机器学习保留独立测试

先建立可复现的规则 baseline，再训练模型。划分时按**网站与共享模板家族**分组，不能把同一作品的第1章放训练集、第2章放测试集。同模板镜像、同站桌面/移动页面也要审查是否需要归为一组。

建议用途：

- 开发集：写规则、训练模型、检查错误。
- 验证集：选择权重、阈值与模型；它会参与决策，不是最终独立证明。
- 测试集：冻结后不参与调参。
- 跨语言集：单独衡量领域外表现。

上述分组思路对应官方文档中按组隔离验证/测试的原则。[S24] 数据少时优先采用留站/留模板验证并如实报告样本量，不先承诺固定准确率。

`benchmark_sites.json` 默认 `dataset_split=unassigned`。等真正采集完、了解模板相似性后再分配，不能按域名数量随机凑比例。

## 10. 采集与公开仓库规则

这是本项目建议的保守采集策略，不是对任何网站的访问授权：

- 默认不自动访问清单内全部域名。逐站检查访问条件、官方获取说明和样本可用性。
- 小范围采集采用单站并发 1、至少 3 秒间隔、有限重试；即使请求很慢，也不意味着自动获得采集许可。
- 429 按站点反馈等待；持续验证或拒绝访问时记录状态，不轮换身份或无限重试。
- Project Gutenberg 明确区分普通网页访问与允许的自动化获取方式；采用其官方指定入口/方式或适当人工采样，不直接把主页和目录作为批量爬取目标。[S21][S22]
- 未确认再分发条件的商业小说输入保持私有。裁剪、脱敏或换掉小说正文，并不自动意味着整个网页快照可以随意公开。
- 优先在公开仓库使用自己创作的测试文本和最小 HTML。保留 source_type、来源、许可/授权依据和修改记录。
- 修改真实快照后重新计算哈希并重新标注。它属于转换后的输入，不能冒充原始响应；还应考虑文本统计已发生变化。
- 不发布登录会话、Cookie、访问令牌、用户评论中的个人信息及完整 HAR。

## 11. 第一轮执行建议

不用先凑满 20 站。建议按以下顺序推进：

**A. 建立标注流程**：从中文维基文库目录和 SF 分卷目录开始，实际选页、保存输入、人工确认顺序，先形成几个可回放用例。[S14][S06]

**B. 验证常见商业页面**：从 17K、纵横、七猫候选中选择能正常取得目标内容的页面；无法取得时转为状态样本或待确认，不强行算正例。

**C. 固化已发现的失败**：补存 99 藏书网那类验证响应，确保程序不会把提示语和验证页标题输出为小说内容。

**D. 补齐真实中文缺口**：重点寻找 GBK/GB18030 字节、br/table 正文、章节分页、目录分页；未找到前用明确标为自制的样本覆盖基本逻辑。

**E. 扩充动态与跨语言组**：核心闭环稳定后，再做浏览器 DOM 和外语样本，不让它们主导中文指标。

## 12. 什么才算这一阶段完成

不是“清单里出现 20 个名字”，而是：

- 有审核过的输入快照和独立人工预期；
- 能在不联网的情况下回放跨页流程；
- 主指标有明确分母，失败、拒绝和未覆盖项单列；
- 调整算法后可比较同一数据集版本的变化；
- 数据公开前完成权限与隐私检查。

暂未采集、尚未标注、功能未实现的样本要显示为 pending/deferred，不能显示 PASS。本包附带的结构校验报告也只证明文件自洽，不证明爬虫或正文算法可用。

---

## 参考入口与证据

表格引用指向官方入口或官方文档；部分只核验到入口，不代表取得了正文或原始 DOM。更详细的核验状态见 JSON 的 `sources` 与 `source_review`。

<a id="source-s16"></a>

[S16] 指此前用户上传的 99 藏书网解析 JSON 日志；本包不包含该原始日志或网站 HTML。

[S01]: https://www.qidian.com/book/1046540075/catalog/ "起点中文网：此前选定的目录入口"
[S02]: https://www.zongheng.com/detail/1415876?tabsName=catalogue "纵横中文网：作品入口"
[S03]: https://www.17k.com/ "17K 小说网"
[S04]: https://www.qimao.com/shuku/1924588-17384585090116/ "七猫：章节页示例"
[S05]: https://fanqienovel.com/ "番茄小说"
[S06]: https://book.sfacg.com/Novel/198140/MainIndex/ "SF 轻小说：归何处目录"
[S07]: https://wap.ciweimao.com/ "刺猬猫移动站"
[S08]: https://www.jjwxc.net/ "晋江文学城"
[S09]: https://www.gongzicp.com/ "长佩文学"
[S10]: https://read.douban.com/ "豆瓣阅读"
[S11]: https://b.faloo.com/ "飞卢中文网候选入口"
[S12]: https://www.shuqi.com/home "书旗中文网"
[S13]: https://www.cmread.com/index "咪咕文学"
[S14]: https://zh.wikisource.org/zh-hans/三國志演義 "中文维基文库：三国演义"
[S15]: https://www.gutenberg.org/browse/languages/zh "Project Gutenberg：中文书目"
[S17]: https://www.aozora.gr.jp/cards/000879/card1129.html "青空文库：霜夜图书卡"
[S18]: https://www.royalroad.com/home "Royal Road"
[S19]: https://standardebooks.org/ "Standard Ebooks 候选入口"
[S20]: https://openlibrary.org/dev/docs/bookreader "Open Library：BookReader 文档"
[S21]: https://www.gutenberg.org/policy/robot_access.html "Project Gutenberg：Robot Access"
[S22]: https://www.gutenberg.org/ebooks/offline_catalogs.html "Project Gutenberg：Offline Catalogs"
[S23]: https://www.python-httpx.org/advanced/text-encodings/ "HTTPX：Text Encodings"
[S24]: https://scikit-learn.org/stable/modules/cross_validation.html#cross-validation-iterators-for-grouped-data "scikit-learn：Grouped Cross-validation"

[S16]: #source-s16 "用户提供的单次分析日志；不是原始网页快照"

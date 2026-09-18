# 真实网页 Fixture 人工采集工作表

> 每个作品复制一份本文件。采集阶段保持 `DRAFT`；不要运行解析器后反向填写真值。
> 不要记录 Cookie、Set-Cookie、Authorization、账号、完整 HAR 或浏览器存储。

## A. 样本基本信息

| 字段 | 填写内容 |
|---|---|
| case_id | `real_<site_id>_<序号>` |
| 站点名称 |  |
| site_id |  |
| 作品名称 |  |
| 作品公开入口 |  |
| 采集日期和时区 |  |
| 采集人 |  |
| 测试组 | `CN_STATIC_CONTENT` / `CN_ACCESS_STATE` / `CN_DYNAMIC_INPUT` / `ENCODING` / `CROSS_LANGUAGE` / `NON_HTML_NEGATIVE` |
| 采集范围 | 例如：一个目录页、相邻三章、第一章第二页 |
| 权限或许可依据 |  |
| 是否只能保持私有 | 是 / 否 / 待确认 |
| 是否使用登录状态 | 必须填“否”；如确有必要则停止并另行确认 |

## B. 页面清单

每页一行。`page_id` 使用稳定、可读的名称，例如 `catalog_01`、`chapter_01_page_01`。

| page_id | 页面角色 | 请求 URL | 最终 URL | 状态码 | 输入类型 | 保存文件 | 采集时间 |
|---|---|---|---|---:|---|---|---|
|  | 作品/目录/章节/访问异常 |  |  |  | `HTTP_BYTES` / `BROWSER_DOM` |  |  |
|  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |

### 输入类型说明

- `HTTP_BYTES`：保存内容解压后、字符解码前的响应体字节，扩展名使用 `.bin`；必须同时填写 HTTP 元数据。
- `BROWSER_DOM`：保存浏览器渲染后的 `document.documentElement.outerHTML`，使用 UTF-8；不能用于证明服务器原始编码。
- 同一 URL 同时保存两种输入时，建立两个 `page_id`，并记录 DOM 由哪个 HTTP 页面渲染而来。

## C. 每页 HTTP 元数据

`HTTP_BYTES` 页面复制一份 `http_metadata.template.json`，只保留下列必要响应头：

- `content-type`
- `content-language`（若存在）
- `content-encoding`（若存在）
- `etag` 或 `last-modified`（可选）

不得保留 Cookie、Set-Cookie、Authorization、代理认证或账户信息。

| page_id | Content-Type | Content-Encoding | 声明字符集 | 页面 meta 字符集 | 人工确认编码 | SHA-256 |
|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |

## D. 人工页面标注

未知项留空或写 `null`，不要猜测。

| page_id | 页面类型 | 访问状态 | 正文状态 | 应提取正文 | 应提取书名/作者 | 书名 | 作者 | 章节标题 |
|---|---|---|---|---|---|---|---|---|
|  | `BOOK_PAGE` / `CATALOG_PAGE` / `CHAPTER_PAGE` / `UNKNOWN` | `OK` / `LOGIN_REQUIRED` / `PAYWALL` / `ANTI_BOT` / `RATE_LIMITED` / `NOT_FOUND` / `ACCESS_RESTRICTED` / `UNKNOWN` | `CONTENT_OK` / `EMPTY_CONTENT` / 其他状态 | 是/否/null | 是/否/null |  |  |  |
|  |  |  |  |  |  |  |  |  |

## E. 正文真值

每个应提取正文的页面，人工复制正文到独立 `.txt` 文件：

```text
reference/<page_id>.txt
```

要求：

- 保留原句、标点、段落顺序。
- 删除导航、菜单和广告时，在下面记录依据。
- 不得从当前解析器输出复制正文。
- 不确定是否属于正文的内容先保留，并标记“待复核”。

| page_id | 参考正文文件 | 明确排除的文字/区域 | 排除依据 | 待复核内容 |
|---|---|---|---|---|
|  |  |  |  |  |

## F. 目录真值

只标注本次采样范围内人工确认的条目；没有采完整目录时，不要声称全目录完整。

| source page_id | chapter_id | 卷名 | 章节标题 | 目标 URL | fragment | DOM 原始序号 | 阅读序号 |
|---|---|---|---|---|---|---:|---:|
|  |  |  |  |  |  |  |  |

目录方向：`ASCENDING` / `DESCENDING` / `MIXED` / `UNKNOWN`

判断依据：

```text

```

## G. 页面关系真值

必须区分章节内下一页、目录下一页和下一章。

| 起点 page_id | 关系类型 | 目标 page_id | 目标 URL | 人工证据 |
|---|---|---|---|---|
|  | `NEXT_CONTENT_PAGE` / `NEXT_CATALOG_PAGE` / `NEXT_CHAPTER` / `PREVIOUS_CONTENT_PAGE` / `PREVIOUS_CATALOG_PAGE` / `PREVIOUS_CHAPTER` / `CATALOG_LINK` |  |  |  |

## H. 逻辑章节

同一章多页时，把全部页面依次列出；不要仅凭标题“上/下”自动合并。

| chapter_id | 章节标题 | source_page_ids（按顺序） | 合并正文参考文件 | 在采样范围内是否完整 |
|---|---|---|---|---|
|  |  |  |  | 是/否/未知 |

预期阅读顺序：

```text
chapter_01 -> chapter_02 -> chapter_03
```

## I. 隐私、版权与完整性复核

- [ ] 没有 Cookie、Set-Cookie、Authorization、账号或浏览器存储。
- [ ] 没有把完整 HAR 放入仓库。
- [ ] 请求 URL、最终 URL、状态码和采集时间均有记录。
- [ ] 每个输入文件均计算 SHA-256。
- [ ] HTTP 字节与浏览器 DOM 分开保存。
- [ ] 正文真值由人工对照页面整理，不来自解析器输出。
- [ ] 未确认字段保持 `null`。
- [ ] 未采完整本书时明确标注 `sampled_subgraph`。
- [ ] 发布许可未确认时，fixture 保持在 `fixtures/private/`。
- [ ] 第二次人工复核已经完成。

## J. 推荐目录

```text
benchmarks/
├── cases/<case_id>/
│   ├── case.json
│   └── expected.json
└── fixtures/private/<case_id>/
    ├── <page_id>.bin
    ├── <page_id>_http.json
    ├── <page_id>_dom.html
    └── reference/
        ├── <page_id>.txt
        └── <logical_chapter_id>.txt
```

完成本工作表和文件采集后，先保持 `DRAFT`。将材料交给维护者转换为 `case.json` 和
`expected.json`，人工复核无误后才能改为 `READY`。

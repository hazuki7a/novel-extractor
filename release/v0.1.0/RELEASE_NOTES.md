# novel-extractor v0.1.0

本地规则驱动的网页小说结构识别与提取工具。本包不包含书源或任何真实小说正文。

## 本版内容

- 自动分析作品页、目录页、章节页及章节导航。
- 支持目录分页、章节内分页、编码检测、访问异常状态和 TXT/EPUB 导出。
- Web 页面显示后台提取进度；每次任务重新读取当前代理配置。
- 包含离线 synthetic 回归测试及合同式 Benchmark Runner。
- 冻结 `baseline_v0`，包含 failure taxonomy、页面类型混淆矩阵、目录候选诊断和分页关系诊断。
- 提供真实 fixture 的人工采集工作表；真实网页默认保存在 Git 忽略的 private 目录。

## 安装

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install novel_extractor-0.1.0-py3-none-any.whl
```

命令行运行：

```powershell
novel-extractor --help
```

## 使用本地 WebUI

安装完成后启动 WebUI：

```powershell
novel-extractor web --port 8765 --output output
```

然后在浏览器打开：

```text
http://127.0.0.1:8765/
```

WebUI 可以分析小说或章节网址、启动提取任务并显示后台提取进度。输出文件保存在
`--output` 指定的目录；默认只监听本机 `127.0.0.1`，不需要 API Key 或云端服务。

如果没有激活虚拟环境，也可以直接运行：

```powershell
.\.venv\Scripts\novel-extractor.exe web --port 8765 --output output
```

或者从源码安装：

```powershell
.\.venv\Scripts\python.exe -m pip install .
```

## 验证状态

- 完整 pytest：通过；一个需要真实浏览器/网络的测试按设计跳过。
- 历史 synthetic Benchmark：12/12 通过。
- 合同式 baseline：8 个 synthetic 来源用例离线执行，严格失败已保留在报告中。
- 真实网站 fixture：0；不得将候选站点清单解释为 20 站测试通过。

## 已知限制

- 不保证任意网站均可抓取，访问限制、地区网络和动态渲染仍可能阻止获取。
- 当前 failure analysis 显示目录识别、正文噪声/截断、分页边界和 challenge 页面分类仍需改进。
- `expected.json` 是人工 ground truth；不得由当前解析器输出自动生成或覆盖。
- Source archive 来自本次验证通过的工作区快照；构建过程不依赖 Git tag。

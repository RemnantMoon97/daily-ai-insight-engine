# 开发会话记录 — 2026-04-15

## 项目：AI 舆情分析日报系统 (Daily AI Insight Engine)

---

## 一、会话概览

本次会话主要完成了系统文档优化、Prompt 外部化、以及仓库首次推送到 GitHub 三大类工作。

---

## 二、完成的工作

### 2.1 Anthropic 风格架构图绘制

使用 `anthropic-diagram` skill，按照 Anthropic 博客的编辑风格（暖色画布 `#F2EFE8`、开放式箭头、语义化配色）绘制了两张 `.drawio` 架构图：

| 文件 | 内容 |
|:-----|:-----|
| `docs/architecture-overview.drawio` | 整体架构流程图：双数据源输入 → 合并 → 清洗 → 抽取 → 聚类 → 三路输出 |
| `docs/pipeline-9-steps.drawio` | 完整 9 步管道图：竖向排列，标注每步对应的源文件 |

**风格要点**：
- 画布背景 `#F2EFE8`（暖色），语义配色（橙色=起始、米色=主流程、薄荷绿=AI/LLM、绿色=输出）
- 所有箭头使用 `endArrow=open;endSize=14`（开放式箭头，非填充）
- 正交路由 `edgeStyle=orthogonalEdgeStyle`，圆角转弯

### 2.2 架构图嵌入 HTML 文档

将两张图嵌入 `docs/design_doc.html`：

- **问题**：最初使用 draw.io CDN viewer (`viewer-static.min.js`)，但在中国网络环境下无法加载
- **解决**：使用本地 draw.io CLI 导出为 SVG，改用 `<img>` 标签嵌入
  ```bash
  D:\software\draw.io\draw.io.exe --export --format svg --crop --output docs/architecture-overview.svg docs/architecture-overview.drawio
  D:\software\draw.io\draw.io.exe --export --format svg --crop --output docs/pipeline-9-steps.svg docs/pipeline-9-steps.drawio
  ```
- 生成了 `docs/architecture-overview.svg` 和 `docs/pipeline-9-steps.svg`

### 2.3 HTML 文档主题切换：深色 → 亮色

将 `docs/design_doc.html` 从深色科技风格切换为亮色主题：

- 主要 CSS 变量变更：
  ```css
  --bg: #f7f8fa;       /* 原: #0d1117 */
  --card: #ffffff;     /* 原: #161b22 */
  --border: #dfe1e6;   /* 原: #30363d */
  --accent: #0d9373;   /* 原: #58a6ff */
  --text: #1c2030;     /* 原: #c9d1d9 */
  ```
- 同步修改了约 15 个硬编码颜色值（代码块背景、表格边框、滚动条等）

### 2.4 项目树形结构显示修复

`design_doc.html` 中 Chapter 05 的项目结构树显示为扁平文本，原因是 `.tree` CSS 类缺少 `white-space:pre`：

- **修复**：为 `.tree` 类添加 `white-space:pre` 属性，保留换行和缩进

### 2.5 Prompt 外部化

#### 2.5.1 结构化抽取 Prompt → `prompt.txt`

- **原状态**：Prompt 硬编码在 `src/extractor.py` 中
- **变更**：
  - 创建 `prompt.txt` 作为外部模板，包含占位符 `{title}`、`{source}`、`{summary}`、`{SCHEMA_PROMPT_DESCRIPTION}`
  - `config.py` 新增 `PROMPT_TEMPLATE_PATH` 指向 `prompt.txt`
  - `src/extractor.py` 改为加载模板文件 + `str.replace()` 替换占位符
- **Prompt 内容**：角色设定（AI产业分析专家）+ 5步任务 + 8条约束规则 + 输出格式要求

#### 2.5.2 分析报告 Prompt → `prompt_analysis.txt`

- **原状态**：Prompt 硬编码在 `src/analyzer.py` 中
- **变更**：
  - 创建 `prompt_analysis.txt` 作为外部模板，包含占位符 `{total_events}`、`{events_text}`
  - `config.py` 新增 `PROMPT_ANALYSIS_PATH` 指向 `prompt_analysis.txt`
  - `src/analyzer.py` 改为加载模板文件 + 替换占位符
- **新版 Prompt 结构**（用户重新设计，从3部分升级为5部分）：
  - 角色：资深 AI 行业分析师
  - 三大分析原则：优先级判断、事实与判断分离、日报风格
  - 5部分输出：A.今日主要热点(Top 3-5)、B.关键事件深度总结、C.趋势判断(技术/应用/政策/资本)、D.风险与机会提示、E.今日结论摘要
  - 10条强约束规则（不得虚构、不得改写、合并同类、信号不足如实说明等）

#### 2.5.3 仍硬编码的 Prompt

`src/cleaner.py` 和 `src/cluster.py` 中还有 4 个硬编码 Prompt 未外部化：
- `cleaner.py:235` — 语义去重 Prompt
- `cleaner.py:304` — 噪声过滤 Prompt
- `cluster.py:151` — 聚类精细合并 Prompt
- `cluster.py:305` — 影响力打分 Prompt

用户已知晓但未要求处理。

### 2.6 文档同步

- `docs/design_doc.md` 与 `docs/design_doc.html` 内容同步更新：
  - Section 3.2（Prompt 设计）更新为外部化后的内容
  - 包含两个 Prompt 的完整内容展示

### 2.7 仓库推送到 GitHub

- **目标仓库**：https://github.com/RemnantMoon97/daily-ai-insight-engine
- **安全检查**：
  - 确认 `.env` 在 `.gitignore` 中（包含真实 API Key）
  - 确认源代码中无硬编码 Key
  - `.gitignore` 新增排除 `output/` 和 `data/processed/`
- **新建文件**：
  - `README.md` — 完整项目文档（功能概览、架构图、快速开始、项目结构、9步管道、技术栈）
  - `.env.example` — 环境变量模板（不含真实 Key）
- **Git 操作**：
  ```
  git config user.name "RemnantMoon97"
  git config user.email "RemnantMoon97@users.noreply.github.com"
  git add (30个文件)
  git commit -m "feat: init AI舆情分析日报系统"
  git branch -M main
  git remote add origin https://github.com/RemnantMoon97/daily-ai-insight-engine.git
  git push -u origin main
  ```
- 推送成功后清除远程 URL 中的 Token

---

## 三、遇到的问题与解决

| 问题 | 原因 | 解决方案 |
|:-----|:-----|:---------|
| draw.io CDN 无法加载 | 中国网络无法访问 `viewer.diagrams.net` | 用本地 draw.io CLI 导出 SVG，改用 `<img>` 标签 |
| CSS 重复注入 | `str.replace('</style>', ...)` 替换了所有 `</style>` 标签 | 手动编辑移除 TOC `<style>` 中的重复内容 |
| 树形结构不显示 | `.tree` 缺少 `white-space:pre` | 添加 CSS 属性 |
| Git 提交失败 | 未配置 user.name / user.email | 使用 `git config` 本地配置 |
| GitHub 认证 | 无 gh CLI，无 SSH key | 使用 Personal Access Token 认证推送 |

---

## 四、文件变更清单

| 文件 | 操作 | 说明 |
|:-----|:-----|:-----|
| `docs/architecture-overview.drawio` | 新建 | Anthropic 风格架构图 |
| `docs/architecture-overview.svg` | 新建 | 架构图 SVG 导出 |
| `docs/pipeline-9-steps.drawio` | 新建 | Anthropic 风格 9 步流程图 |
| `docs/pipeline-9-steps.svg` | 新建 | 流程图 SVG 导出 |
| `docs/design_doc.html` | 修改 | 深色→亮色主题、嵌入 SVG 图、修复树形显示、更新 Prompt 章节 |
| `docs/design_doc.md` | 修改 | 同步 HTML 的 Prompt 内容变更 |
| `prompt.txt` | 新建 | 结构化抽取 Prompt 外部模板 |
| `prompt_analysis.txt` | 新建 | 分析报告 Prompt 外部模板（5部分新版） |
| `config.py` | 修改 | 新增 `PROMPT_TEMPLATE_PATH`、`PROMPT_ANALYSIS_PATH` |
| `src/extractor.py` | 修改 | 从文件加载 Prompt 模板 |
| `src/analyzer.py` | 修改 | 从文件加载分析 Prompt 模板 |
| `.gitignore` | 修改 | 新增排除 `output/`、`data/processed/` |
| `.env.example` | 新建 | 环境变量模板 |
| `README.md` | 新建 | 项目说明文档 |

---

## 五、仓库最终状态

- **远程仓库**：https://github.com/RemnantMoon97/daily-ai-insight-engine
- **分支**：`main`（1 个提交）
- **提交**：`16a71b9` feat: init AI舆情分析日报系统 (Daily AI Insight Engine)
- **文件数**：30 个文件，5394 行代码
- **敏感信息**：API Key 仅存在于本地 `.env`（已 gitignore），未提交到远程

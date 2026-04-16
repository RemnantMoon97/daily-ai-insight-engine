# AI 舆情分析日报系统

Daily AI Insight Engine — 基于 LLM 的自动化 AI 行业舆情分析与投资情绪日报系统。

## 功能概览

- **多源数据采集**：Hacker News API + 中英文 RSS 订阅 + 中文科技媒体爬虫 + X/Twitter
- **按日期存储**：新闻自动按日期归档到 `data/daily/`，保留最近 7 天，自动清理过期数据
- **智能数据清洗**：规则 + LLM 混合去重、噪声过滤、标准化
- **LLM 结构化抽取**：逐条调用智谱 GLM API，提取话题、要点、影响分析、受影响公司、市场信号
- **事件聚类与热点排序**：并查集预分组 + LLM 精细合并，四维度热点打分
- **投资情绪分析**：基于 `investment-sentiment-news` SKILL Prompt，生成市场温度、公司信号面板、主题机会/风险、交易观察点
- **日报正文生成**：LLM 基于新闻 + 投资分析自动撰写完整日报文章，含标题、导语、正文段落、结语
- **侧边栏智能摘要**：LLM 自动为每天生成摘要（总判断、热度、风险、Top3 热点），与右侧分析对齐
- **交互式 Web 报告**：双栏布局（左侧日期导航 + 右侧日报），五大模块可折叠展开

## 系统架构

```
HN API ─────┐
RSS 订阅 ───┤
中文媒体 ────┤→ 按日期存储 → 增量清洗 → LLM抽取 → 事件聚类 ─┬→ 分析报告(MD)
X/Twitter ──┘                                            ├→ 投资分析(JSON)
                                                         ├→ 日报正文(MD)
                                                         └→ Web报告(HTML)
```

## Web 报告布局

```
┌──────────────┬───────────────────────────────────────┐
│  侧边栏 360px│  主内容区                               │
│              │                                       │
│ ┌──────────┐ │ ┌─ 投资情绪分析 ──────────── [▼折叠] ┐ │
│ │ 04/16 43 │ │ │ Hero Banner / 市场温度 / 机会&风险  │ │
│ │ 04/15 43 │ │ └──────────────────────────────────┘ │
│ │ 04/14 18 │ │ ┌─ 公司信号面板 ──────────── [▼折叠] ┐ │
│ │ 04/13  4 │ │ │ 利好/利空信号卡片网格              │ │
│ │ ...      │ │ └──────────────────────────────────┘ │
│ │          │ │ ┌─ 今日主要热点 ──────────── [▼折叠] ┐ │
│ │          │ │ │ 事件卡片（默认3个，可展开全部）     │ │
│ │          │ │ └──────────────────────────────────┘ │
│ │          │ │ ┌─ 数据来源与新闻证据 ───── [▼折叠] ─┐ │
│ │          │ │ │ 来源表格 + 新闻列表（默认3条展开）  │ │
│ │          │ │ └──────────────────────────────────┘ │
│ │          │ │ ┌─ 正文 ──────────────────── [▼折叠] ─┐ │
│ │          │ │ │ LLM 生成的日报正文文章              │ │
│ └──────────┘ │ └──────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────┘
```

- 仅最近 7 天且新闻 >= 20 条的日期显示完整日报，其余仅在侧边栏显示摘要
- 五大模块均可点击标题折叠/展开
- 新闻列表和热点事件默认显示 3 条，点击按钮展开全部

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

复制 `.env.example` 为 `.env`，填入你的智谱 API Key：

```bash
cp .env.example .env
```

或直接设置环境变量：

```bash
# Windows
set ZHIPU_API_KEY=your_key_here

# Linux/Mac
export ZHIPU_API_KEY=your_key_here
```

> 智谱 API Key 申请地址：https://open.bigmodel.cn/

### 3. 运行

```bash
# 完整流程（采集 + 清洗 + 抽取 + 聚类 + 分析 + 报告）
python main.py --refresh

# 使用已有数据，跳过采集
python main.py --skip-collect

# 指定日期生成日报
python main.py --date 2026-04-16

# 获取新数据（与历史去重后增量处理）
python main.py --fetch-new

# 每日定时采集（默认 08:00）
python main.py --schedule

# 查看所有选项
python main.py --help
```

## 输出文件

| 文件 | 说明 |
|:-----|:-----|
| `output/report.html` | Web 可视化报告（双栏交互式看板） |
| `output/report_YYYY-MM-DD.md` | 按日期生成的 Markdown 分析报告 |
| `output/investment_YYYY-MM-DD.json` | 按日期生成的投资情绪分析 JSON |
| `output/article_YYYY-MM-DD.md` | 按日期生成的日报正文（Markdown） |
| `output/charts/*.png` | matplotlib 静态图表 |
| `data/daily/YYYY-MM-DD.json` | 按日期存储的原始新闻数据（保留7天） |
| `data/processed/structured_news.json` | LLM 结构化抽取结果 |
| `data/processed/event_clusters.json` | 事件聚类与热点排序结果 |

## 项目结构

```
daily-ai-insight-engine/
├── main.py                        # 主流程入口（13 步管道编排）
├── config.py                      # 配置（API Key、模型、数据源、路径）
├── prompt/
│   ├── investment_analysis.txt    # 投资情绪分析 Prompt（SKILL）
│   ├── daily_article_body.txt     # 日报正文 Prompt
│   └── 侧边栏.txt                 # 侧边栏摘要 Prompt
├── prompt.txt                     # 结构化抽取 Prompt
├── prompt_analysis.txt            # 分析报告 Prompt
├── investment-sentiment-news/
│   └── SKILL.md                   # 投资情绪分析 Skill 定义
├── src/
│   ├── collector/
│   │   ├── hn_collector.py        # Hacker News API 采集
│   │   ├── rss_collector.py       # RSS 订阅采集（中英文）
│   │   ├── chinese_media_collector.py  # 中文科技媒体爬虫
│   │   ├── social_collector.py    # X/Twitter + 雪球采集
│   │   ├── daily_store.py         # 按日期存储 + 7天清理
│   │   ├── registry.py            # 新闻注册表（增量去重）
│   │   └── scheduler.py           # 定时采集调度
│   ├── schema.py                  # 结构化数据模型（含公司影响、市场信号）
│   ├── cleaner.py                 # 数据清洗
│   ├── extractor.py               # LLM 结构化抽取 + JSON 解析/修复
│   ├── cluster.py                 # 事件聚类 + 热点排序
│   ├── analyzer.py                # 分析报告生成
│   ├── investment_analyzer.py     # 投资情绪分析
│   ├── daily_article_generator.py # 日报正文生成
│   ├── visualizer.py              # matplotlib 静态图表
│   └── web_report.py              # Web 报告生成（双栏布局）
├── data/
│   ├── raw/                       # 原始数据（按来源）
│   ├── daily/                     # 按日期存储（自动清理 >7天）
│   └── processed/                 # 处理后数据
├── output/                        # 输出文件
└── docs/                          # 文档
```

## 数据源

| 数据源 | 类型 | 语言 |
|:-------|:-----|:-----|
| Hacker News | API | 英文 |
| TechCrunch, Wired, Ars Technica, VentureBeat, MarkTechPost, AI News | RSS | 英文 |
| 少数派, IT之家, 爱范儿 | RSS | 中文 |
| 量子位, 36氪 | 网页爬虫 | 中文 |
| X/Twitter (Sam Altman, Karpathy 等) | Nitter RSS | 英文 |

## 处理管道

| 步骤 | 模块 | 说明 |
|:-----|:-----|:-----|
| Step 1-4 | `collector/` | 多源数据采集（HN + RSS + 中文媒体 + 社交） |
| Step 5 | `collector/` | 合并去重 + 按日期存储 |
| Step 6 | `cleaner.py` | 数据清洗（标准化 → 补全 → 去重 → 噪声过滤） |
| Step 7 | `extractor.py` | LLM 结构化抽取（增量模式，含 429 退避） |
| Step 8 | `cluster.py` | 事件聚类 + 热点排序 |
| Step 9 | `analyzer.py` | 分析报告生成 |
| Step 10 | `investment_analyzer.py` | 投资情绪分析（SKILL Prompt） |
| Step 11 | `daily_article_generator.py` | 日报正文生成（新闻 + 投资分析 → 文章） |
| Step 12 | `visualizer.py` | 可视化图表 |
| Step 13 | `web_report.py` | Web 交互式报告 |

## 技术栈

- **语言**：Python 3.12+
- **LLM**：智谱 GLM-4-flash（结构化抽取、聚类、分析、投资分析、侧边栏摘要）
- **数据采集**：Hacker News API + feedparser (RSS) + requests + Nitter RSS
- **前端**：原生 HTML/CSS/JS（无框架，暗色主题，CSS 变量）
- **依赖管理**：uv + pyproject.toml

## Prompt 设计

Prompt 模板与代码解耦，存储在独立文件中：

- `prompt.txt` — 结构化抽取（角色设定 + 5 步任务 + Schema 约束）
- `prompt_analysis.txt` — 分析报告（5 部分输出结构 + 10 条强约束规则）
- `prompt/investment_analysis.txt` — 投资情绪分析（SKILL Prompt，含完整 JSON Schema）
- `prompt/daily_article_body.txt` — 日报正文（基于新闻 + 投资分析生成完整文章）
- `prompt/侧边栏.txt` — 侧边栏摘要（Top3 与右侧分析对齐）

## 许可证

MIT

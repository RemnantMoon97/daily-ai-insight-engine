# AI 舆情分析日报系统

Daily AI Insight Engine — 基于 LLM 的自动化 AI 行业舆情分析与日报生成系统。

## 功能概览

- **多源数据采集**：Hacker News API 自动采集 + 10 个中英文媒体手动整理
- **智能数据清洗**：规则 + LLM 混合去重、噪声过滤、标准化
- **LLM 结构化抽取**：逐条调用智谱 GLM API，提取话题、要点、影响分析
- **事件聚类与热点排序**：并查集预分组 + LLM 精细合并，四维度热点打分
- **分析报告自动生成**：5 部分结构化日报（热点 / 深度总结 / 趋势 / 风险 / 结论）
- **多格式输出**：Markdown 日报 + matplotlib 静态图表 + 交互式 HTML 仪表盘

## 系统架构

```
HN API ──┐
          ├→ 合并 → 数据清洗 → LLM抽取 → 事件聚类+排序 ─┬→ 分析报告(MD)
手动数据 ─┘                                                ├→ 可视化(PNG)
                                                           └→ Web报告(HTML)
```

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
# 使用已有数据，跳过 HN 采集
python main.py --skip-collect

# 完整流程（采集 + 清洗 + 抽取 + 聚类 + 报告）
python main.py --refresh

# 快速生成报告（跳过清洗和聚类，使用已有数据）
python main.py --skip-collect --skip-extract --skip-clean --skip-cluster

# 查看所有选项
python main.py --help
```

## 输出文件

| 文件 | 说明 |
|:-----|:-----|
| `output/report.md` | Markdown 格式完整日报 |
| `output/report.html` | Web 可视化报告（浏览器打开） |
| `output/charts/*.png` | matplotlib 静态图表 |
| `data/processed/cleaned_news.json` | 清洗后的数据 |
| `data/processed/structured_news.json` | 结构化抽取结果 |
| `data/processed/event_clusters.json` | 事件聚类与热点排序结果 |

## 项目结构

```
daily-ai-insight-engine/
├── main.py                    # 主流程入口（9 步管道编排）
├── config.py                  # 配置（API Key、模型、路径）
├── prompt.txt                 # 结构化抽取 Prompt 模板
├── prompt_analysis.txt        # 分析报告 Prompt 模板
├── requirements.txt           # Python 依赖
├── data/
│   ├── raw/                   # 原始数据（HN 采集 + 手动整理）
│   └── processed/             # 处理后数据（.gitignore 排除）
├── src/
│   ├── collector/
│   │   └── hn_collector.py    # HN API 数据采集器
│   ├── schema.py              # 结构化数据模型定义
│   ├── cleaner.py             # 数据清洗（标准化/去重/噪声过滤）
│   ├── extractor.py           # LLM 结构化抽取
│   ├── cluster.py             # 事件聚类 + 热点排序
│   ├── analyzer.py            # 分析报告生成
│   ├── visualizer.py          # matplotlib 静态图表
│   └── web_report.py          # HTML 可视化报告生成
├── output/                    # 输出文件（.gitignore 排除）
└── docs/
    ├── design_doc.md          # 系统说明文档
    ├── design_doc.html        # 说明文档网页版
    ├── architecture-overview.drawio  # 架构流程图（draw.io）
    ├── architecture-overview.svg     # 架构流程图（SVG）
    ├── pipeline-9-steps.drawio       # 9 步流程图（draw.io）
    └── pipeline-9-steps.svg          # 9 步流程图（SVG）
```

## 9 步处理管道

| 步骤 | 模块 | 说明 |
|:-----|:-----|:-----|
| Step 1-2 | `collector/` | 数据采集与加载（HN API + 手动数据） |
| Step 3 | — | 数据合并（按 ID 去重） |
| Step 4 | `cleaner.py` | 数据清洗（标准化 → 补全 → 去重 → 噪声过滤） |
| Step 5 | `extractor.py` | LLM 结构化抽取（智谱 GLM 逐条调用） |
| Step 6 | `cluster.py` | 事件聚类 + 热点排序 |
| Step 7 | `analyzer.py` | 分析报告生成（基于事件 cluster） |
| Step 8 | `visualizer.py` | 可视化图表（matplotlib） |
| Step 9 | `web_report.py` | Web 可视化报告（HTML Dashboard） |

## 技术栈

- **语言**：Python 3.12+
- **LLM**：智谱 GLM-4-flash（结构化抽取、聚类、分析报告）
- **数据采集**：Hacker News Firebase REST API
- **可视化**：matplotlib、Chart.js
- **依赖管理**：uv + pyproject.toml

## Prompt 设计

Prompt 模板与代码解耦，存储在独立文件中：

- `prompt.txt` — 结构化抽取 Prompt（角色设定 + 5 步任务 + 8 条约束规则）
- `prompt_analysis.txt` — 分析报告 Prompt（5 部分输出结构 + 10 条强约束规则）

## 许可证

MIT

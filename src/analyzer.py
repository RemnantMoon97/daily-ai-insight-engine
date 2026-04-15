"""
分析报告生成器

基于事件 cluster 数据，调用 LLM 生成 AI 日报分析报告。
报告结构：A. 主要热点  B. 关键事件深度总结  C. 趋势判断  D. 风险/机会提示
"""

import json
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, ".")

from config import ZHIPU_API_KEY, ZHIPU_MODEL, OUTPUT_DIR, PROMPT_ANALYSIS_PATH
from src.extractor import get_client, call_llm, parse_json_response


def _load_analysis_template() -> str:
    """从 prompt_analysis.txt 加载分析报告 Prompt 模板"""
    with open(PROMPT_ANALYSIS_PATH, "r", encoding="utf-8") as f:
        return f.read()


# 模块加载时缓存模板
_ANALYSIS_TEMPLATE = _load_analysis_template()


def build_analysis_prompt(clusters: list[dict]) -> str:
    """构建基于事件 cluster 的分析报告 Prompt（基于 prompt_analysis.txt 模板）"""
    events_summary = []
    for i, cl in enumerate(clusters):
        sources = ", ".join(art.get("source", "") for art in cl.get("articles", []))
        topics = ", ".join(cl.get("combined_topics", []))
        points = "\n      ".join(cl.get("combined_key_points", []))
        articles_count = len(cl.get("articles", []))

        entry = (
            f"### 事件 {i+1}: {cl.get('event_title', '')}\n"
            f"  来源({articles_count}条): {sources}\n"
            f"  话题: {topics}\n"
            f"  热点分数: {cl.get('hotspot_score', 0)}\n"
            f"  要点:\n      {points}\n"
            f"  影响: {cl.get('combined_impact', '')}"
        )
        events_summary.append(entry)

    events_text = "\n\n".join(events_summary)

    prompt = _ANALYSIS_TEMPLATE
    prompt = prompt.replace("{total_events}", str(len(clusters)))
    prompt = prompt.replace("{events_text}", events_text)
    return prompt


def generate_report(clusters: list[dict]) -> str:
    """
    生成基于事件 cluster 的分析报告

    Args:
        clusters: 事件聚类结果（已按热点分数排序）

    Returns:
        Markdown 格式的分析报告
    """
    client = get_client()
    prompt = build_analysis_prompt(clusters)

    print(f"\n[分析] 开始生成分析报告（基于 {len(clusters)} 个事件 cluster）...")

    response_text = call_llm(client, prompt)

    # 清理返回文本
    report_content = response_text.strip()
    if report_content.startswith("```markdown"):
        report_content = report_content[len("```markdown"):]
    if report_content.startswith("```"):
        report_content = report_content[3:]
    if report_content.endswith("```"):
        report_content = report_content[:-3]
    report_content = report_content.strip()

    print("[分析] 报告生成完成")
    return report_content


def format_full_report(clusters: list[dict], analysis_report: str) -> str:
    """组装完整的日报"""
    today = datetime.now().strftime("%Y年%m月%d日")

    # 统计
    total_articles = sum(len(cl.get("articles", [])) for cl in clusters)
    all_topics = []
    source_counter = Counter()
    for cl in clusters:
        all_topics.extend(cl.get("combined_topics", []))
        for art in cl.get("articles", []):
            source_counter[art.get("source", "未知")] += 1
    topic_counter = Counter(all_topics)

    report = f"""# AI 舆情分析日报

**日期**: {today}
**事件数**: {len(clusters)} 个事件（来自 {total_articles} 条新闻）
**数据来源**: Hacker News API + 手动收集中英文媒体

---

## 数据概览

### 新闻来源分布
| 来源 | 文章数 |
|:-----|:-------|
"""
    for src, count in source_counter.most_common():
        report += f"| {src} | {count} |\n"

    report += """
### 主要话题分布
| 话题 | 出现次数 |
|:-----|:---------|
"""
    for topic, count in topic_counter.most_common(15):
        report += f"| {topic} | {count} |\n"

    report += """
### 热点事件排名
| 排名 | 事件 | 热点分 | 来源数 |
|:=====|:=====|:=======|:=======|
"""
    for i, cl in enumerate(clusters[:10]):
        n_articles = len(cl.get("articles", []))
        report += f"| {i+1} | {cl['event_title'][:50]} | {cl.get('hotspot_score', 0):.1f} | {n_articles} |\n"

    report += """
---

## 事件详情

"""
    for i, cl in enumerate(clusters):
        topics = ", ".join(cl.get("combined_topics", []))
        points = "\n  - ".join(cl.get("combined_key_points", []))
        sources = ", ".join(
            art.get("source", "") for art in cl.get("articles", [])
        )

        report += f"### {i+1}. {cl.get('event_title', '')}\n\n"
        report += f"- **来源**: {sources}\n"
        report += f"- **话题**: {topics}\n"
        report += f"- **热点分**: {cl.get('hotspot_score', 0):.1f} "
        report += f"(影响:{cl.get('influence_score', 0):.1f} × "
        report += f"可信:{cl.get('credibility_score', 0):.2f} × "
        report += f"传播:{cl.get('spread_score', 0):.1f} × "
        report += f"新颖:{cl.get('novelty_score', 0):.2f})\n"
        report += f"- **影响**: {cl.get('combined_impact', '')}\n\n"
        report += f"**关键要点**:\n  - {points}\n\n"

        # 列出该事件的所有文章
        if len(cl.get("articles", [])) > 1:
            report += "**相关报道**:\n"
            for art in cl["articles"]:
                report += f"  - [{art.get('source', '')}] [{art.get('title', '')}]({art.get('url', '')})\n"
            report += "\n"

    report += """---

## 深度分析

"""
    report += analysis_report

    report += f"""

---

*本报告由 AI 舆情分析日报系统自动生成*
*生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
*分析模型: {ZHIPU_MODEL}*
"""

    return report


def save_report(report_text: str, filepath: str = None) -> str:
    """保存报告到文件"""
    if filepath is None:
        filepath = f"{OUTPUT_DIR}/report.md"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[分析] 报告已保存到 {filepath}")
    return filepath

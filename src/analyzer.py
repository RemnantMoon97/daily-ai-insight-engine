"""
分析报告生成器

基于事件 cluster 数据，调用 LLM 生成 AI 日报分析报告。
报告结构：A. 主要热点  B. 关键事件深度总结  C. 趋势判断  D. 风险/机会提示
支持按日期过滤新闻，生成指定日期的日报。
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, date

sys.path.insert(0, ".")

from config import ZHIPU_API_KEY, ZHIPU_MODEL, OUTPUT_DIR, DATA_PROCESSED_DIR, PROMPT_ANALYSIS_PATH
from src.extractor import get_client, call_llm, parse_json_response


def filter_news_by_date(news_list: list[dict], target_date: str = None) -> list[dict]:
    """
    按 publish_date 过滤新闻，只保留指定日期的新闻

    Args:
        news_list: 全部新闻列表
        target_date: 目标日期 "YYYY-MM-DD"，默认今天

    Returns:
        过滤后的新闻列表
    """
    if target_date is None:
        target_date = date.today().isoformat()

    filtered = []
    for item in news_list:
        pub_date = item.get("publish_date", "")
        if not pub_date:
            continue
        try:
            # 兼容多种日期格式: ISO, datetime string, timestamp
            if pub_date.startswith(target_date):
                filtered.append(item)
            elif "T" in pub_date:
                dt = datetime.fromisoformat(pub_date[:19])
                if dt.strftime("%Y-%m-%d") == target_date:
                    filtered.append(item)
        except (ValueError, TypeError):
            continue

    print(f"[日期过滤] 目标日期 {target_date}：{len(news_list)} 条 → {len(filtered)} 条")
    return filtered


def group_news_by_date(news_list: list[dict]) -> dict[str, list[dict]]:
    """
    将新闻按 publish_date 分组

    Returns:
        { "2026-04-16": [...], "2026-04-15": [...], ... }
    """
    groups = defaultdict(list)
    for item in news_list:
        pub_date = item.get("publish_date", "")
        day_str = "unknown"
        if pub_date:
            try:
                if "T" in pub_date:
                    dt = datetime.fromisoformat(pub_date[:19])
                    day_str = dt.strftime("%Y-%m-%d")
                elif len(pub_date) >= 10:
                    day_str = pub_date[:10]
            except (ValueError, TypeError):
                pass
        groups[day_str].append(item)

    print(f"[日期分组] 共 {len(groups)} 天的新闻数据:")
    for day in sorted(groups.keys(), reverse=True)[:10]:
        print(f"  {day}: {len(groups[day])} 条")
    return dict(groups)


def save_daily_report(report_text: str, target_date: str = None) -> str:
    """保存按日期命名的日报"""
    if target_date is None:
        target_date = date.today().isoformat()

    filepath = f"{OUTPUT_DIR}/report_{target_date}.md"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[分析] 日报已保存到 {filepath}")
    return filepath


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


def format_full_report(clusters: list[dict], analysis_report: str, target_date: str = None) -> str:
    """组装完整的日报"""
    if target_date is None:
        target_date = date.today().isoformat()

    display_date = target_date.replace("-", "年", 1).replace("-", "月", 1) + "日"

    # 统计
    total_articles = sum(len(cl.get("articles", [])) for cl in clusters)
    all_topics = []
    source_counter = Counter()
    # 收集所有受影响公司
    bullish_companies = Counter()
    bearish_companies = Counter()
    for cl in clusters:
        all_topics.extend(cl.get("combined_topics", []))
        for art in cl.get("articles", []):
            source_counter[art.get("source", "未知")] += 1
        # 从 combined 数据中收集公司影响
        for comp in cl.get("combined_affected_companies", []):
            name = comp.get("name", "")
            direction = comp.get("impact_direction", "中性")
            if name:
                if "利好" in direction:
                    bullish_companies[name] += 1
                elif "利空" in direction:
                    bearish_companies[name] += 1

    topic_counter = Counter(all_topics)

    report = f"""# AI 舆情分析日报

**日期**: {display_date}
**事件数**: {len(clusters)} 个事件（来自 {total_articles} 条新闻）
**数据来源**: HN + RSS + 中文媒体 + 社交媒体

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

    # 添加受影响公司概览
    if bullish_companies or bearish_companies:
        report += """
### 受影响公司概览
| 公司 | 利好次数 | 利空次数 | 净方向 |
|:-----|:---------|:---------|:-------|
"""
        all_companies = set(list(bullish_companies.keys()) + list(bearish_companies.keys()))
        for comp in sorted(all_companies):
            b = bullish_companies.get(comp, 0)
            n = bearish_companies.get(comp, 0)
            direction = "利好" if b > n else ("利空" if n > b else "中性")
            report += f"| {comp} | {b} | {n} | {direction} |\n"

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

        # 受影响公司
        affected = cl.get("combined_affected_companies", [])
        if affected:
            report += "**受影响公司**:\n"
            for comp in affected:
                direction = comp.get("impact_direction", "中性")
                reason = comp.get("reason", "")
                report += f"  - {comp.get('name', '?')} ({direction})：{reason}\n"
            report += "\n"

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
    """保存报告到文件（默认按日期命名）"""
    if filepath is None:
        today = date.today().isoformat()
        # 优先使用日期命名，同时保留通用文件名
        filepath = f"{OUTPUT_DIR}/report.md"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"[分析] 报告已保存到 {filepath}")
    return filepath

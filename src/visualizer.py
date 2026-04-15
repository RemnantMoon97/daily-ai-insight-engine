"""
可视化图表生成器

使用 matplotlib 生成多种分析图表。
支持两种输入：event cluster 数据或单条新闻数据。
"""

import json
import sys
from collections import Counter
from datetime import datetime

import matplotlib
matplotlib.use("Agg")  # 非交互式后端，无需 GUI
import matplotlib.pyplot as plt

sys.path.insert(0, ".")
from config import CHARTS_DIR

# 支持中文显示
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def _is_cluster_data(data: list[dict]) -> bool:
    """判断数据是 event cluster 还是单条新闻"""
    if not data:
        return False
    return "cluster_id" in data[0] or "hotspot_score" in data[0]


def _extract_topics(data: list[dict]) -> list[str]:
    """从 cluster 或新闻中提取话题"""
    all_topics = []
    for item in data:
        if _is_cluster_data([item]):
            all_topics.extend(item.get("combined_topics", []))
        else:
            all_topics.extend(item.get("main_topics", []))
    return all_topics


def _extract_sources(data: list[dict]) -> list[str]:
    """从 cluster 或新闻中提取来源"""
    sources = []
    for item in data:
        if _is_cluster_data([item]):
            for art in item.get("articles", []):
                sources.append(art.get("source", "未知"))
        else:
            sources.append(item.get("source", "未知"))
    return sources


def _extract_languages(data: list[dict]) -> list[str]:
    """从 cluster 或新闻中提取语言"""
    langs = []
    for item in data:
        if _is_cluster_data([item]):
            for art in item.get("articles", []):
                langs.append(art.get("language", "unknown"))
        else:
            langs.append(item.get("language", "unknown"))
    return langs


def plot_topics_distribution(data: list[dict]) -> str:
    """生成话题分布柱状图"""
    all_topics = _extract_topics(data)
    topic_counts = Counter(all_topics)
    top_topics = topic_counts.most_common(15)
    labels = [t[0] for t in top_topics]
    values = [t[1] for t in top_topics]

    fig, ax = plt.subplots(figsize=(12, max(6, len(labels) * 0.45)))
    bars = ax.barh(labels[::-1], values[::-1], color=plt.cm.Set3(range(len(labels))))

    ax.set_title("AI 新闻话题分布 Top 15", fontsize=16, fontweight="bold")
    ax.set_xlabel("出现次数", fontsize=12)

    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                str(val), ha="left", va="center", fontsize=11)

    plt.tight_layout()
    filepath = f"{CHARTS_DIR}/topics_distribution.png"
    fig.savefig(filepath, dpi=150)
    plt.close(fig)
    print(f"[可视化] 话题分布图已保存: {filepath}")
    return filepath


def plot_source_distribution(data: list[dict]) -> str:
    """生成新闻来源分布饼图"""
    sources = _extract_sources(data)
    source_counts = Counter(sources)
    labels = list(source_counts.keys())
    values = list(source_counts.values())

    fig, ax = plt.subplots(figsize=(9, 8))
    ax.pie(values, labels=labels, autopct="%1.1f%%", startangle=90,
           textprops={"fontsize": 11})
    ax.set_title("新闻来源分布", fontsize=16, fontweight="bold")

    plt.tight_layout()
    filepath = f"{CHARTS_DIR}/source_distribution.png"
    fig.savefig(filepath, dpi=150)
    plt.close(fig)
    print(f"[可视化] 来源分布图已保存: {filepath}")
    return filepath


def plot_language_distribution(data: list[dict]) -> str:
    """生成中英文新闻数量对比"""
    langs = _extract_languages(data)
    lang_map = {"zh": "中文", "en": "英文"}
    lang_counts = Counter(lang_map.get(l, l) for l in langs)
    labels = list(lang_counts.keys())
    values = list(lang_counts.values())

    colors = ["#4FC3F7", "#FF8A65"]
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors[:len(labels)])

    ax.set_title("中英文新闻数量对比", fontsize=16, fontweight="bold")
    ax.set_ylabel("数量", fontsize=12)

    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                str(val), ha="center", va="bottom", fontsize=13, fontweight="bold")

    plt.tight_layout()
    filepath = f"{CHARTS_DIR}/language_distribution.png"
    fig.savefig(filepath, dpi=150)
    plt.close(fig)
    print(f"[可视化] 语言分布图已保存: {filepath}")
    return filepath


def plot_hotspot_ranking(data: list[dict]) -> str:
    """生成热点事件排名图（仅 cluster 数据）"""
    if not _is_cluster_data(data):
        return ""

    # 取 Top 10
    top = sorted(data, key=lambda x: x.get("hotspot_score", 0), reverse=True)[:10]
    labels = [cl.get("event_title", "")[:30] for cl in top]
    scores = [cl.get("hotspot_score", 0) for cl in top]

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = plt.cm.YlOrRd([0.3 + 0.7 * (1 - i / max(len(top) - 1, 1)) for i in range(len(top))])
    bars = ax.barh(labels[::-1], scores[::-1], color=colors)

    ax.set_title("热点事件排名 Top 10", fontsize=16, fontweight="bold")
    ax.set_xlabel("热点分数", fontsize=12)

    for bar, val in zip(bars, scores[::-1]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}", ha="left", va="center", fontsize=11, fontweight="bold")

    plt.tight_layout()
    filepath = f"{CHARTS_DIR}/hotspot_ranking.png"
    fig.savefig(filepath, dpi=150)
    plt.close(fig)
    print(f"[可视化] 热点排名图已保存: {filepath}")
    return filepath


def plot_key_points_wordcloud(data: list[dict]) -> str:
    """基于 key_points 生成词云图"""
    try:
        from wordcloud import WordCloud
    except ImportError:
        print("[可视化] wordcloud 未安装，跳过词云生成")
        return ""

    all_points = []
    for item in data:
        if _is_cluster_data([item]):
            all_points.extend(item.get("combined_key_points", []))
            all_points.extend(item.get("combined_topics", []))
        else:
            all_points.extend(item.get("key_points", []))
            all_points.extend(item.get("main_topics", []))

    if not all_points:
        print("[可视化] 没有 key_points 数据，跳过词云生成")
        return ""

    keyword_freq = Counter(all_points)

    fig, ax = plt.subplots(figsize=(12, 8))

    wc = WordCloud(
        width=1200, height=800,
        background_color="white",
        max_words=50,
        colormap="viridis",
        font_path=None,
    )
    wc.generate_from_frequencies(keyword_freq)

    ax.imshow(wc, interpolation="bilinear")
    ax.set_title("AI 新闻关键词要点词云", fontsize=16, fontweight="bold")
    ax.axis("off")

    plt.tight_layout()
    filepath = f"{CHARTS_DIR}/key_points_wordcloud.png"
    fig.savefig(filepath, dpi=150)
    plt.close(fig)
    print(f"[可视化] 词云图已保存: {filepath}")
    return filepath


def generate_all_charts(data: list[dict]) -> list[str]:
    """生成所有可视化图表（兼容 cluster 和单条新闻数据）"""
    print(f"\n[可视化] 开始生成图表...")

    chart_files = []
    chart_files.append(plot_topics_distribution(data))
    chart_files.append(plot_source_distribution(data))
    chart_files.append(plot_language_distribution(data))

    # 热点排名图（仅 cluster 数据）
    hotspot_path = plot_hotspot_ranking(data)
    if hotspot_path:
        chart_files.append(hotspot_path)

    # 词云可选
    wc_path = plot_key_points_wordcloud(data)
    if wc_path:
        chart_files.append(wc_path)

    print(f"[可视化] 共生成 {len(chart_files)} 个图表")
    return chart_files

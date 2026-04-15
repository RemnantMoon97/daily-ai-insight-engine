"""
AI 舆情分析日报系统 - 主流程入口

完整管道：
1. 采集 Hacker News AI 新闻（或加载已有数据）
2. 加载手动整理的新闻数据
3. 合并、去重
4. 数据清洗（标准化 → 补全 → 语义去重 → 噪声过滤）
5. LLM 结构化抽取
6. 事件聚类 + 热点排序
7. 生成分析报告
8. 生成可视化图表
9. 生成 Web 可视化报告
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from config import DATA_RAW_DIR, DATA_PROCESSED_DIR, OUTPUT_DIR, CHARTS_DIR
from src.collector.hn_collector import collect_hn_news, save_hn_news, load_hn_news
from src.cleaner import clean_all
from src.extractor import extract_all, save_structured_news, load_structured_news
from src.cluster import cluster_and_rank
from src.analyzer import generate_report, format_full_report, save_report
from src.visualizer import generate_all_charts
from src.web_report import generate_web_report


def ensure_dirs():
    """确保所有输出目录存在"""
    for d in [DATA_RAW_DIR, DATA_PROCESSED_DIR, OUTPUT_DIR, CHARTS_DIR]:
        os.makedirs(d, exist_ok=True)


def step_collect_hn(force_refresh: bool = False) -> list[dict]:
    """Step 1: 采集 HN 数据（或加载已有）"""
    hn_path = f"{DATA_RAW_DIR}/hn_news.json"

    if not force_refresh and os.path.exists(hn_path):
        print("[跳过] HN 数据已存在，使用缓存（使用 --refresh 强制重新采集）")
        return load_hn_news(hn_path)

    print("\n" + "=" * 50)
    print("Step 1: 采集 Hacker News AI 新闻")
    print("=" * 50)
    news = collect_hn_news(max_results=15)
    save_hn_news(news, hn_path)
    return news


def step_load_manual() -> list[dict]:
    """Step 2: 加载手动整理的新闻数据"""
    manual_path = f"{DATA_RAW_DIR}/manual_chinese.json"
    print("\n" + "=" * 50)
    print("Step 2: 加载手动新闻数据")
    print("=" * 50)

    if not os.path.exists(manual_path):
        print(f"[警告] 数据文件不存在: {manual_path}")
        return []

    with open(manual_path, "r", encoding="utf-8") as f:
        news = json.load(f)

    # 过滤掉空条目
    news = [item for item in news if item.get("title")]
    print(f"[数据] 加载了 {len(news)} 条手动整理新闻")

    if len(news) == 0:
        print("[警告] 没有数据！请编辑 data/raw/manual_chinese.json")

    return news


def step_merge_news(hn_news: list[dict], manual_news: list[dict]) -> list[dict]:
    """Step 3: 合并和去重"""
    print("\n" + "=" * 50)
    print("Step 3: 合并新闻数据")
    print("=" * 50)

    all_news = hn_news + manual_news

    # 按 id 去重
    seen = set()
    unique_news = []
    for item in all_news:
        nid = item.get("id", "")
        if nid and nid not in seen:
            seen.add(nid)
            unique_news.append(item)

    print(f"[合并] HN: {len(hn_news)} 条 + 手动: {len(manual_news)} 条 = "
          f"总计: {len(unique_news)} 条（去重后）")

    return unique_news


def step_clean(all_news: list[dict]) -> list[dict]:
    """Step 4: 数据清洗"""
    print("\n" + "=" * 50)
    print("Step 4: 数据清洗")
    print("=" * 50)

    cleaned_path = f"{DATA_PROCESSED_DIR}/cleaned_news.json"

    return clean_all(all_news, save_path=cleaned_path)


def step_extract(all_news: list[dict], skip_extract: bool = False) -> list[dict]:
    """Step 5: LLM 结构化抽取"""
    structured_path = f"{DATA_PROCESSED_DIR}/structured_news.json"

    if skip_extract and os.path.exists(structured_path):
        print("\n[跳过] 结构化数据已存在，使用缓存（使用 --refresh 强制重新抽取）")
        return load_structured_news(structured_path)

    print("\n" + "=" * 50)
    print("Step 5: LLM 结构化抽取")
    print("=" * 50)

    structured = extract_all(all_news)
    save_structured_news(structured, structured_path)
    return structured


def step_cluster(structured_news: list[dict]) -> list[dict]:
    """Step 6: 事件聚类 + 热点排序"""
    print("\n" + "=" * 50)
    print("Step 6: 事件聚类 + 热点排序")
    print("=" * 50)

    clusters_path = f"{DATA_PROCESSED_DIR}/event_clusters.json"

    return cluster_and_rank(structured_news, save_path=clusters_path)


def step_analyze(clusters: list[dict]) -> tuple[str, str]:
    """Step 7: 生成分析报告"""
    print("\n" + "=" * 50)
    print("Step 7: 生成分析报告")
    print("=" * 50)

    analysis = generate_report(clusters)
    full_report = format_full_report(clusters, analysis)
    report_path = save_report(full_report)
    return report_path, analysis


def step_visualize(clusters: list[dict]) -> list[str]:
    """Step 8: 生成可视化图表"""
    print("\n" + "=" * 50)
    print("Step 8: 生成可视化图表")
    print("=" * 50)

    return generate_all_charts(clusters)


def step_web_report(clusters: list[dict], analysis_text: str) -> str:
    """Step 9: 生成 Web 可视化报告"""
    print("\n" + "=" * 50)
    print("Step 9: 生成 Web 可视化报告")
    print("=" * 50)

    return generate_web_report(clusters, analysis_text)


def main():
    parser = argparse.ArgumentParser(description="AI 舆情分析日报系统")
    parser.add_argument("--refresh", action="store_true",
                        help="强制重新采集和抽取")
    parser.add_argument("--skip-collect", action="store_true",
                        help="跳过 HN 数据采集，使用已有数据")
    parser.add_argument("--skip-extract", action="store_true",
                        help="跳过结构化抽取，使用已有数据")
    parser.add_argument("--skip-clean", action="store_true",
                        help="跳过数据清洗")
    parser.add_argument("--skip-cluster", action="store_true",
                        help="跳过事件聚类")
    parser.add_argument("--skip-visualize", action="store_true",
                        help="跳过可视化图表生成")
    args = parser.parse_args()

    ensure_dirs()

    print("=" * 50)
    print("   AI 舆情分析日报系统")
    print("   Daily AI Insight Engine")
    print("=" * 50)

    # Step 1: 采集 HN 数据
    if args.skip_collect:
        hn_news = load_hn_news()
        print(f"[跳过] 使用已有 HN 数据: {len(hn_news)} 条")
    else:
        hn_news = step_collect_hn(force_refresh=args.refresh)

    # Step 2: 加载手动数据
    manual_news = step_load_manual()

    # Step 3: 合并
    all_news = step_merge_news(hn_news, manual_news)

    if not all_news:
        print("\n[错误] 没有可用的新闻数据！")
        sys.exit(1)

    # Step 4: 数据清洗
    if args.skip_clean:
        print("\n[跳过] 数据清洗")
    else:
        all_news = step_clean(all_news)

    # Step 5: 结构化抽取
    structured = step_extract(all_news, skip_extract=args.skip_extract and not args.refresh)

    # Step 6: 事件聚类 + 热点排序
    if args.skip_cluster:
        clusters_path = f"{DATA_PROCESSED_DIR}/event_clusters.json"
        if os.path.exists(clusters_path):
            with open(clusters_path, "r", encoding="utf-8") as f:
                clusters = json.load(f)
            print(f"\n[跳过] 使用已有聚类数据: {len(clusters)} 个事件")
        else:
            print("[警告] 无已有聚类数据，将跳过聚类，直接使用结构化数据")
            clusters = structured
    else:
        clusters = step_cluster(structured)

    # Step 7: 分析报告
    report_path, analysis_text = step_analyze(clusters)

    # Step 8: 可视化
    if not args.skip_visualize:
        chart_files = step_visualize(clusters)

    # Step 9: Web 可视化报告
    web_path = step_web_report(clusters, analysis_text)

    # 完成
    print("\n" + "=" * 50)
    print("   处理完成！")
    print("=" * 50)
    print(f"\n输出文件：")
    print(f"  Markdown 报告: {report_path}")
    print(f"  Web 可视化报告: {web_path}")
    print(f"  事件聚类: {DATA_PROCESSED_DIR}/event_clusters.json")
    print(f"  结构化数据: {DATA_PROCESSED_DIR}/structured_news.json")
    if not args.skip_visualize:
        for cf in chart_files:
            print(f"  图表: {cf}")
    print()


if __name__ == "__main__":
    main()

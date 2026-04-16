"""
AI 舆情分析日报系统 - 主流程入口

完整管道：
1. 采集 Hacker News AI 新闻
2. 采集 RSS 数据源新闻
3. 采集中文科技媒体新闻
4. 加载手动整理的新闻数据
5. 合并、去重
6. 数据清洗（标准化 → 补全 → 语义去重 → 噪声过滤）
7. LLM 结构化抽取
8. 事件聚类 + 热点排序
9. 生成分析报告
10. 生成可视化图表
11. 生成 Web 可视化报告

特殊命令：
  --fetch-new          立即获取新数据，与历史数据去重后增量处理
  --fetch-after 30m    等待指定时间后获取新数据（支持 s/m/h/d 后缀）
  --schedule           每天定时获取（默认 08:00）
"""

import argparse
import json
import os
import re
import sys
import time as _time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from config import DATA_RAW_DIR, DATA_PROCESSED_DIR, OUTPUT_DIR, CHARTS_DIR, XUEQIU_COOKIE, DATA_DAILY_DIR
from src.collector.hn_collector import collect_hn_news, save_hn_news, load_hn_news
from src.collector.rss_collector import collect_all_rss, save_rss_news, load_rss_news
from src.collector.chinese_media_collector import collect_all_chinese, save_chinese_news, load_chinese_news
from src.collector.social_collector import collect_all_social, save_social_news, load_social_news
from src.collector.daily_store import save_to_daily, load_daily, list_available_dates, migrate_from_raw
from src.collector.registry import (
    load_registry, save_registry, register_news,
    filter_new_news, print_registry_stats,
)
from src.cleaner import clean_all
from src.extractor import extract_all, extract_incremental, save_structured_news, load_structured_news
from src.cluster import cluster_and_rank
from src.analyzer import generate_report, format_full_report, save_report, save_daily_report, filter_news_by_date, group_news_by_date
from src.visualizer import generate_all_charts
from src.web_report import generate_web_report


def ensure_dirs():
    """确保所有输出目录存在"""
    for d in [DATA_RAW_DIR, DATA_PROCESSED_DIR, OUTPUT_DIR, CHARTS_DIR, DATA_DAILY_DIR]:
        os.makedirs(d, exist_ok=True)


# ─── 数据采集步骤 ─────────────────────────────────────────


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


def step_collect_rss(force_refresh: bool = False) -> list[dict]:
    """Step 2: 采集 RSS 数据源新闻"""
    rss_path = f"{DATA_RAW_DIR}/rss_news.json"

    if not force_refresh and os.path.exists(rss_path):
        print("[跳过] RSS 数据已存在，使用缓存（使用 --refresh 强制重新采集）")
        return load_rss_news(rss_path)

    print("\n" + "=" * 50)
    print("Step 2: 采集 RSS 数据源新闻")
    print("=" * 50)
    news = collect_all_rss()
    save_rss_news(news, rss_path)
    return news


def step_collect_chinese(force_refresh: bool = False) -> list[dict]:
    """Step 3: 采集中文科技媒体新闻"""
    cn_path = f"{DATA_RAW_DIR}/chinese_news.json"

    if not force_refresh and os.path.exists(cn_path):
        print("[跳过] 中文媒体数据已存在，使用缓存（使用 --refresh 强制重新采集）")
        return load_chinese_news(cn_path)

    print("\n" + "=" * 50)
    print("Step 3: 采集中文科技媒体新闻")
    print("=" * 50)
    news = collect_all_chinese()
    save_chinese_news(news, cn_path)
    return news


def step_collect_social(force_refresh: bool = False) -> list[dict]:
    """Step 4: 采集社交媒体（X/Twitter + 雪球）"""
    social_path = f"{DATA_RAW_DIR}/social_news.json"

    if not force_refresh and os.path.exists(social_path):
        print("[跳过] 社交媒体数据已存在，使用缓存（使用 --refresh 强制重新采集）")
        return load_social_news(social_path)

    print("\n" + "=" * 50)
    print("Step 4: 采集社交媒体（X + 雪球）")
    print("=" * 50)
    news = collect_all_social(xueqiu_cookie=XUEQIU_COOKIE)
    save_social_news(news, social_path)
    return news


def step_load_manual() -> list[dict]:
    """Step 5: 加载手动整理的新闻数据（作为兜底数据源）"""
    manual_path = f"{DATA_RAW_DIR}/manual_chinese.json"
    print("\n" + "=" * 50)
    print("Step 5: 加载手动新闻数据（兜底）")
    print("=" * 50)

    if not os.path.exists(manual_path):
        print(f"[跳过] 数据文件不存在: {manual_path}")
        return []

    with open(manual_path, "r", encoding="utf-8") as f:
        news = json.load(f)

    news = [item for item in news if item.get("title")]
    print(f"[数据] 加载了 {len(news)} 条手动整理新闻")
    return news


def step_merge_news(
    hn_news: list[dict],
    rss_news: list[dict],
    cn_news: list[dict],
    social_news: list[dict],
    manual_news: list[dict],
) -> list[dict]:
    """Step 6: 合并和去重，并按日期存储"""
    print("\n" + "=" * 50)
    print("Step 6: 合并新闻数据")
    print("=" * 50)

    all_news = hn_news + rss_news + cn_news + social_news + manual_news

    # 按 id 去重
    seen = set()
    unique_news = []
    for item in all_news:
        nid = item.get("id", "")
        if nid and nid not in seen:
            seen.add(nid)
            unique_news.append(item)

    print(f"[合并] HN: {len(hn_news)} 条 + RSS: {len(rss_news)} 条 + "
          f"中文媒体: {len(cn_news)} 条 + 社交媒体: {len(social_news)} 条 + "
          f"手动: {len(manual_news)} 条 = "
          f"总计: {len(unique_news)} 条（去重后）")

    # 按日期存储
    if unique_news:
        save_to_daily(unique_news)

    return unique_news


# ─── 数据处理步骤 ─────────────────────────────────────────


def step_clean(all_news: list[dict], force_refresh: bool = False) -> list[dict]:
    """Step 7: 数据清洗（增量模式：复用已清洗数据）"""
    print("\n" + "=" * 50)
    print("Step 7: 数据清洗")
    print("=" * 50)

    cleaned_path = f"{DATA_PROCESSED_DIR}/cleaned_news.json"

    if not force_refresh and os.path.exists(cleaned_path):
        try:
            with open(cleaned_path, "r", encoding="utf-8") as f:
                existing_cleaned = json.load(f)
            existing_ids = {item.get("id", "") for item in existing_cleaned}
            new_items = [item for item in all_news if item.get("id", "") not in existing_ids]

            if not new_items:
                print(f"[清洗] 没有新增数据需要清洗，复用已有 {len(existing_cleaned)} 条")
                return existing_cleaned

            print(f"[清洗] 新增 {len(new_items)} 条需清洗（已有 {len(existing_cleaned)} 条）")
            newly_cleaned = clean_all(new_items, save_path=None)
            merged = existing_cleaned + newly_cleaned

            with open(cleaned_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)

            print(f"[清洗] 合并后共 {len(merged)} 条")
            return merged
        except (json.JSONDecodeError, IOError):
            pass

    return clean_all(all_news, save_path=cleaned_path)


def step_extract(all_news: list[dict], skip_extract: bool = False, force_refresh: bool = False) -> list[dict]:
    """Step 8: LLM 结构化抽取（默认增量模式）"""
    structured_path = f"{DATA_PROCESSED_DIR}/structured_news.json"

    if skip_extract and os.path.exists(structured_path):
        print("\n[跳过] 结构化数据已存在，使用缓存")
        return load_structured_news(structured_path)

    print("\n" + "=" * 50)
    if force_refresh:
        print("Step 8: LLM 结构化抽取（全量模式）")
        print("=" * 50)
        structured = extract_all(all_news)
    else:
        print("Step 8: LLM 结构化抽取（增量模式）")
        print("=" * 50)
        structured = extract_incremental(all_news, existing_path=structured_path)

    save_structured_news(structured, structured_path)
    return structured


def step_cluster(structured_news: list[dict]) -> list[dict]:
    """Step 9: 事件聚类 + 热点排序"""
    print("\n" + "=" * 50)
    print("Step 9: 事件聚类 + 热点排序")
    print("=" * 50)

    clusters_path = f"{DATA_PROCESSED_DIR}/event_clusters.json"
    return cluster_and_rank(structured_news, save_path=clusters_path)


def step_analyze(clusters: list[dict], target_date: str = None) -> tuple[str, str]:
    """Step 10: 生成分析报告"""
    print("\n" + "=" * 50)
    print("Step 10: 生成分析报告")
    print("=" * 50)

    analysis = generate_report(clusters)
    full_report = format_full_report(clusters, analysis, target_date=target_date)

    # 保存通用报告
    report_path = save_report(full_report)
    # 同时保存按日期命名的报告
    daily_path = save_daily_report(full_report, target_date=target_date)

    return report_path, analysis


def step_visualize(clusters: list[dict]) -> list[str]:
    """Step 11: 生成可视化图表"""
    print("\n" + "=" * 50)
    print("Step 11: 生成可视化图表")
    print("=" * 50)
    return generate_all_charts(clusters)


def step_web_report(clusters: list[dict], analysis_text: str, target_date: str = None) -> str:
    """Step 12: 生成 Web 可视化报告"""
    print("\n" + "=" * 50)
    print("Step 12: 生成 Web 可视化报告")
    print("=" * 50)
    return generate_web_report(clusters, analysis_text, target_date=target_date)


# ─── 获取新数据（与历史去重）─────────────────────────────


def fetch_new_data() -> list[dict]:
    """
    从所有数据源获取新闻，与注册表中的历史数据去重，
    只保留真正新增的条目。

    Returns:
        去重后的新增新闻列表
    """
    print("\n" + "=" * 60)
    print("  获取新数据（与历史去重）")
    print("=" * 60)

    # 1. 加载注册表
    registry = load_registry()
    print_registry_stats(registry)

    # 2. 从所有数据源采集
    print("\n[采集] 开始从所有数据源获取...")

    hn_news = collect_hn_news(max_results=15)
    _time.sleep(0.3)

    rss_news = collect_all_rss()
    _time.sleep(0.3)

    cn_news = collect_all_chinese()
    _time.sleep(0.3)

    social_news = collect_all_social(xueqiu_cookie=XUEQIU_COOKIE)

    # 3. 合并
    all_fetched = hn_news + rss_news + cn_news + social_news
    print(f"\n[采集] 本次共获取 {len(all_fetched)} 条原始数据")

    # 4. 与注册表去重
    new_news = filter_new_news(all_fetched, registry)
    duplicate_count = len(all_fetched) - len(new_news)

    print(f"[去重] 与历史数据对比：{duplicate_count} 条重复，{len(new_news)} 条新增")

    if not new_news:
        print("[去重] 没有发现新的新闻，跳过后续处理")
        return []

    # 5. 将新数据追加到原始数据文件（不覆盖）
    _append_to_raw_files(new_news)

    # 6. 更新注册表
    registered = register_news(new_news, registry)
    save_registry(registry)
    print(f"[注册表] 新注册 {registered} 条，总计 {registry['total_seen']} 条")

    # 7. 按日期存储新数据
    save_to_daily(new_news)

    # 打印新增条目摘要
    print(f"\n[新增] {len(new_news)} 条新新闻：")
    for item in new_news[:10]:
        print(f"  [{item.get('source', '')}] {item.get('title', '')[:50]}")
    if len(new_news) > 10:
        print(f"  ... 还有 {len(new_news) - 10} 条")

    return new_news


def _append_to_raw_files(new_news: list[dict]):
    """将新数据追加到对应的原始数据文件中（合并而非覆盖）"""

    # 按来源分组
    by_source = {
        "Hacker News": [],
        "rss": [],
        "chinese": [],
        "social": [],
    }
    for item in new_news:
        src = item.get("source", "")
        if src == "Hacker News":
            by_source["Hacker News"].append(item)
        elif src in ("量子位", "36氪"):
            by_source["chinese"].append(item)
        elif src.startswith("X/") or src.startswith("雪球/"):
            by_source["social"].append(item)
        else:
            by_source["rss"].append(item)

    # 追加到各文件
    file_map = {
        "Hacker News": f"{DATA_RAW_DIR}/hn_news.json",
        "rss": f"{DATA_RAW_DIR}/rss_news.json",
        "chinese": f"{DATA_RAW_DIR}/chinese_news.json",
        "social": f"{DATA_RAW_DIR}/social_news.json",
    }

    for key, filepath in file_map.items():
        new_items = by_source[key]
        if not new_items:
            continue

        existing = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []

        # 合并去重
        seen_ids = {item.get("id") for item in existing}
        for item in new_items:
            if item.get("id") not in seen_ids:
                existing.append(item)
                seen_ids.add(item.get("id"))

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        print(f"  [追加] {filepath}: +{len(new_items)} 条 → 共 {len(existing)} 条")


def run_incremental_pipeline(new_only: list[dict] = None):
    """
    运行增量管道：清洗 → 抽取 → 聚类 → 报告

    Args:
        new_only: 如果提供，只处理这些新数据；
                  如果为 None，从文件加载全部数据做增量处理
    """
    # 优先从 daily 目录加载
    all_news = load_daily()
    if not all_news:
        # 回退到按来源加载
        hn_news = load_hn_news() if os.path.exists(f"{DATA_RAW_DIR}/hn_news.json") else []
        rss_news = load_rss_news() if os.path.exists(f"{DATA_RAW_DIR}/rss_news.json") else []
        cn_news = load_chinese_news() if os.path.exists(f"{DATA_RAW_DIR}/chinese_news.json") else []
        social_news = load_social_news() if os.path.exists(f"{DATA_RAW_DIR}/social_news.json") else []
        manual_news = step_load_manual()
        all_news = hn_news + rss_news + cn_news + social_news + manual_news

        # 按 id 去重
        seen = set()
        unique = []
        for item in all_news:
            nid = item.get("id", "")
            if nid and nid not in seen:
                seen.add(nid)
                unique.append(item)
        all_news = unique
    else:
        manual_news = step_load_manual()
        if manual_news:
            all_news.extend(manual_news)

    if not all_news:
        print("\n[错误] 没有可用的新闻数据！")
        return

    # 增量清洗
    all_news = step_clean(all_news, force_refresh=False)

    # 增量抽取
    structured = step_extract(all_news, force_refresh=False)

    # 聚类
    clusters = step_cluster(structured)

    # 分析报告
    report_path, analysis_text = step_analyze(clusters)

    # 可视化
    chart_files = step_visualize(clusters)

    # Web 报告
    web_path = step_web_report(clusters, analysis_text)

    # 完成
    print("\n" + "=" * 60)
    print("   增量处理完成！")
    print("=" * 60)
    print(f"\n输出文件：")
    print(f"  Markdown 报告: {report_path}")
    print(f"  Web 可视化报告: {web_path}")
    print(f"  结构化数据: {DATA_PROCESSED_DIR}/structured_news.json")
    for cf in chart_files:
        print(f"  图表: {cf}")
    print()


# ─── 时间解析 ─────────────────────────────────────────────


def parse_duration(duration_str: str) -> timedelta:
    """
    解析时间字符串为 timedelta

    支持格式：
      30s  → 30 秒
      10m  → 10 分钟
      2h   → 2 小时
      1d   → 1 天
      90   → 90 秒（纯数字默认秒）
    """
    match = re.match(r"^(\d+(?:\.\d+)?)\s*([smhd]?)$", duration_str.strip().lower())
    if not match:
        raise ValueError(f"无法解析时间: {duration_str}（支持格式: 30s, 10m, 2h, 1d）")

    value = float(match.group(1))
    unit = match.group(2) or "s"

    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return timedelta(seconds=value * multipliers[unit])


# ─── 主入口 ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="AI 舆情分析日报系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  python main.py                    # 默认运行（使用缓存数据，增量处理）
  python main.py --refresh          # 强制全量重新采集和抽取
  python main.py --date 2026-04-16  # 生成指定日期的日报
  python main.py --fetch-new        # 立即获取新数据，与历史去重
  python main.py --fetch-after 30m  # 等待 30 分钟后获取新数据
  python main.py --fetch-after 2h   # 等待 2 小时后获取新数据
  python main.py --schedule          # 每天定时获取（默认 08:00）
  python main.py --schedule --time 09:30  # 每天定时 09:30 获取
        """,
    )

    # 运行模式
    parser.add_argument("--fetch-new", action="store_true",
                        help="立即获取新数据（与历史数据去重）")
    parser.add_argument("--fetch-after", type=str, default=None, metavar="DURATION",
                        help="等待指定时间后获取新数据（如 30m, 2h, 1d）")

    # 定时模式
    parser.add_argument("--schedule", action="store_true",
                        help="启动每日定时采集模式")
    parser.add_argument("--time", default=None,
                        help="定时执行时间 (HH:MM)，默认 08:00")

    # 标准管道选项
    parser.add_argument("--refresh", action="store_true",
                        help="强制重新采集和抽取")
    parser.add_argument("--date", type=str, default=None,
                        help="指定日期生成日报 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--skip-collect", action="store_true",
                        help="跳过所有数据采集，使用已有数据")
    parser.add_argument("--skip-extract", action="store_true",
                        help="跳过结构化抽取，使用已有数据")
    parser.add_argument("--skip-clean", action="store_true",
                        help="跳过数据清洗")
    parser.add_argument("--skip-cluster", action="store_true",
                        help="跳过事件聚类")
    parser.add_argument("--skip-visualize", action="store_true",
                        help="跳过可视化图表生成")

    args = parser.parse_args()

    # ─── 模式1: 等待指定时间后获取 ───
    if args.fetch_after:
        duration = parse_duration(args.fetch_after)
        target_time = datetime.now() + duration
        print("=" * 60)
        print(f"  延迟获取模式")
        print(f"  等待时间: {duration}")
        print(f"  预计执行: {target_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  按 Ctrl+C 取消")
        print("=" * 60)

        try:
            _time.sleep(duration.total_seconds())
        except KeyboardInterrupt:
            print("\n[取消] 延迟获取已取消")
            return

        new_news = fetch_new_data()
        if new_news:
            run_incremental_pipeline(new_news)
        return

    # ─── 模式2: 立即获取新数据 ───
    if args.fetch_new:
        ensure_dirs()
        new_news = fetch_new_data()
        if new_news:
            run_incremental_pipeline(new_news)
        return

    # ─── 模式3: 每日定时 ───
    if args.schedule:
        from src.collector.scheduler import start_scheduler
        start_scheduler(schedule_time=args.time)
        return

    # ─── 模式4: 标准管道 ───
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

    # Step 2: 采集 RSS 数据
    if args.skip_collect:
        rss_path = f"{DATA_RAW_DIR}/rss_news.json"
        if os.path.exists(rss_path):
            rss_news = load_rss_news()
            print(f"[跳过] 使用已有 RSS 数据: {len(rss_news)} 条")
        else:
            rss_news = []
    else:
        rss_news = step_collect_rss(force_refresh=args.refresh)

    # Step 3: 采集中文媒体数据
    if args.skip_collect:
        cn_path = f"{DATA_RAW_DIR}/chinese_news.json"
        if os.path.exists(cn_path):
            cn_news = load_chinese_news()
            print(f"[跳过] 使用已有中文媒体数据: {len(cn_news)} 条")
        else:
            cn_news = []
    else:
        cn_news = step_collect_chinese(force_refresh=args.refresh)

    # Step 4: 采集社交媒体数据（X + 雪球）
    if args.skip_collect:
        social_path = f"{DATA_RAW_DIR}/social_news.json"
        if os.path.exists(social_path):
            social_news = load_social_news()
            print(f"[跳过] 使用已有社交媒体数据: {len(social_news)} 条")
        else:
            social_news = []
    else:
        social_news = step_collect_social(force_refresh=args.refresh)

    # Step 5: 加载手动数据（兜底）
    manual_news = step_load_manual()

    # Step 6: 合并
    all_news = step_merge_news(hn_news, rss_news, cn_news, social_news, manual_news)

    if not all_news:
        print("\n[错误] 没有可用的新闻数据！")
        sys.exit(1)

    # Step 7: 数据清洗（增量模式）
    if args.skip_clean:
        print("\n[跳过] 数据清洗")
    else:
        all_news = step_clean(all_news, force_refresh=args.refresh)

    # Step 8: 结构化抽取（增量模式）
    structured = step_extract(
        all_news,
        skip_extract=args.skip_extract,
        force_refresh=args.refresh,
    )

    # Step 8.5: 按日期过滤（如果指定了 --date）
    target_date = args.date  # None 表示今天
    if structured:
        date_structured = filter_news_by_date(structured, target_date=target_date)
        if not date_structured:
            print(f"\n[警告] 指定日期 {target_date or '今天'} 无新闻数据，使用全部数据")
            date_structured = structured
    else:
        date_structured = structured

    # Step 9: 事件聚类 + 热点排序
    if args.skip_cluster:
        clusters_path = f"{DATA_PROCESSED_DIR}/event_clusters.json"
        if os.path.exists(clusters_path):
            with open(clusters_path, "r", encoding="utf-8") as f:
                clusters = json.load(f)
            print(f"\n[跳过] 使用已有聚类数据: {len(clusters)} 个事件")
        else:
            print("[警告] 无已有聚类数据，将跳过聚类，直接使用结构化数据")
            clusters = date_structured
    else:
        clusters = step_cluster(date_structured)

    # Step 10: 分析报告
    report_path, analysis_text = step_analyze(clusters, target_date=target_date)

    # Step 11: 可视化
    if not args.skip_visualize:
        chart_files = step_visualize(clusters)

    # Step 12: Web 可视化报告
    web_path = step_web_report(clusters, analysis_text, target_date=target_date)

    # 完成
    print("\n" + "=" * 50)
    print("   处理完成！")
    print("=" * 50)
    print(f"\n输出文件：")
    print(f"  Markdown 报告: {report_path}")
    print(f"  Web 可视化报告: {web_path}")
    print(f"  HN 数据: {DATA_RAW_DIR}/hn_news.json")
    print(f"  RSS 数据: {DATA_RAW_DIR}/rss_news.json")
    print(f"  中文媒体数据: {DATA_RAW_DIR}/chinese_news.json")
    print(f"  社交媒体数据: {DATA_RAW_DIR}/social_news.json")
    print(f"  事件聚类: {DATA_PROCESSED_DIR}/event_clusters.json")
    print(f"  结构化数据: {DATA_PROCESSED_DIR}/structured_news.json")
    if not args.skip_visualize:
        for cf in chart_files:
            print(f"  图表: {cf}")
    print()


if __name__ == "__main__":
    main()

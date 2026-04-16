"""
定时采集调度器

使用 schedule 库实现每天定时自动采集新闻数据。
支持配置采集时间，自动运行完整管道。

用法：
    python main.py --schedule          # 使用默认时间 (08:00)
    python main.py --schedule --time 09:30  # 指定时间
"""

import json
import os
import sys
import threading
import time
from datetime import datetime

import schedule

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import DATA_RAW_DIR, DATA_PROCESSED_DIR, OUTPUT_DIR, CHARTS_DIR, SCHEDULE_TIME
from src.analyzer import filter_news_by_date
from src.collector.daily_store import save_to_daily


def run_pipeline():
    """执行完整的采集+分析管道"""
    print(f"\n{'=' * 60}")
    print(f"  定时任务触发 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")

    try:
        # 动态导入避免循环依赖
        from src.collector.rss_collector import collect_all_rss, save_rss_news
        from src.collector.chinese_media_collector import collect_all_chinese, save_chinese_news
        from src.collector.hn_collector import collect_hn_news, save_hn_news
        from src.collector.social_collector import collect_all_social, save_social_news
        from src.cleaner import clean_all
        from src.extractor import extract_incremental, save_structured_news
        from src.cluster import cluster_and_rank
        from src.analyzer import generate_report, format_full_report, save_report
        from src.visualizer import generate_all_charts
        from src.web_report import generate_web_report
        from config import XUEQIU_COOKIE

        # 确保 id 去重
        seen_ids = set()
        def dedup(news_list):
            unique = []
            for item in news_list:
                nid = item.get("id", "")
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    unique.append(item)
            return unique

        # 1. 采集所有数据源
        print("\n[调度] Step 1/10: 采集 HN 新闻...")
        hn_news = collect_hn_news(max_results=15)
        save_hn_news(hn_news)

        print("\n[调度] Step 2/10: 采集 RSS 新闻...")
        rss_news = collect_all_rss()
        save_rss_news(rss_news)

        print("\n[调度] Step 3/10: 采集中文媒体新闻...")
        cn_news = collect_all_chinese()
        save_chinese_news(cn_news)

        print("\n[调度] Step 4/10: 采集社交媒体...")
        social_news = collect_all_social(xueqiu_cookie=XUEQIU_COOKIE)
        save_social_news(social_news)

        # 加载手动数据（如果存在）
        manual_news = []
        manual_path = f"{DATA_RAW_DIR}/manual_chinese.json"
        if os.path.exists(manual_path):
            with open(manual_path, "r", encoding="utf-8") as f:
                manual_news = [item for item in json.load(f) if item.get("title")]

        # 2. 合并去重
        print("\n[调度] Step 5/10: 合并数据...")
        all_news = dedup(hn_news + rss_news + cn_news + social_news + manual_news)
        print(f"[调度] 合并后共 {len(all_news)} 条新闻")

        # 2.5 按日期存储
        save_to_daily(all_news)

        if not all_news:
            print("[调度] 无可用数据，跳过本次执行")
            return

        # 3. 增量清洗
        print("\n[调度] Step 6/10: 数据清洗（增量）...")
        cleaned_path = f"{DATA_PROCESSED_DIR}/cleaned_news.json"

        # 增量清洗：只清洗新增数据
        if os.path.exists(cleaned_path):
            with open(cleaned_path, "r", encoding="utf-8") as f:
                existing_cleaned = json.load(f)
            existing_ids = {item.get("id", "") for item in existing_cleaned}
            new_items = [item for item in all_news if item.get("id", "") not in existing_ids]
            if new_items:
                print(f"  新增 {len(new_items)} 条需清洗（已有 {len(existing_cleaned)} 条）")
                newly_cleaned = clean_all(new_items, save_path=None)
                all_news = existing_cleaned + newly_cleaned
            else:
                print(f"  无新增数据，复用已有 {len(existing_cleaned)} 条")
                all_news = existing_cleaned
        else:
            all_news = clean_all(all_news, save_path=cleaned_path)

        # 4. 增量结构化抽取
        print("\n[调度] Step 7/10: 结构化抽取（增量）...")
        structured_path = f"{DATA_PROCESSED_DIR}/structured_news.json"
        structured = extract_incremental(all_news, existing_path=structured_path)
        save_structured_news(structured, structured_path)

        # 4.5 按当天日期过滤
        today = datetime.now().strftime("%Y-%m-%d")
        date_structured = filter_news_by_date(structured, target_date=today)
        if not date_structured:
            print(f"[调度] 今天 ({today}) 无新闻数据，使用全部数据")
            date_structured = structured

        # 5. 聚类
        print("\n[调度] Step 8/10: 事件聚类...")
        clusters_path = f"{DATA_PROCESSED_DIR}/event_clusters.json"
        clusters = cluster_and_rank(date_structured, save_path=clusters_path)

        # 6. 分析报告
        print("\n[调度] Step 9/10: 生成报告...")
        from src.analyzer import save_daily_report
        analysis = generate_report(clusters)
        full_report = format_full_report(clusters, analysis, target_date=today)
        save_report(full_report)
        save_daily_report(full_report, target_date=today)

        # 7. 可视化 + Web 报告
        print("\n[调度] Step 10/10: 生成可视化...")
        generate_all_charts(clusters)
        generate_web_report(clusters, analysis, target_date=today)

        print(f"\n{'=' * 60}")
        print(f"  定时任务完成 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'=' * 60}")

    except Exception as e:
        print(f"\n[调度错误] 管道执行失败: {e}")
        import traceback
        traceback.print_exc()


def start_scheduler(schedule_time: str = None):
    """
    启动定时调度器

    Args:
        schedule_time: 每天执行时间，格式 "HH:MM"，默认使用 config.SCHEDULE_TIME
    """
    if schedule_time is None:
        schedule_time = SCHEDULE_TIME

    print(f"\n{'=' * 60}")
    print(f"  AI 舆情分析日报系统 - 定时采集模式")
    print(f"  调度时间: 每天 {schedule_time}")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 60}")

    # 注册定时任务
    schedule.every().day.at(schedule_time).do(run_pipeline)

    # 首次启动时立即执行一次
    print("\n[调度] 首次启动，立即执行一次完整采集...")
    run_pipeline()

    print(f"\n[调度] 下次执行时间: {schedule_time}")
    print("[调度] 按 Ctrl+C 停止...\n")

    # 持续运行
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    except KeyboardInterrupt:
        print("\n[调度] 定时任务已停止")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 舆情分析定时采集器")
    parser.add_argument("--time", default=None, help="定时执行时间 (HH:MM)")
    args = parser.parse_args()
    start_scheduler(args.time)

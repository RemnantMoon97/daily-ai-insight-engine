"""
按日期存储新闻数据

将所有数据源的新闻按 publish_date 分组存储到 data/daily/ 目录下：
  data/daily/2026-04-16.json  - 2026-04-16 所有新闻
  data/daily/2026-04-15.json  - 2026-04-15 所有新闻

每个 JSON 文件结构：
{
    "date": "2026-04-16",
    "count": 42,
    "sources": {"Hacker News": 5, "TechCrunch": 8, ...},
    "news": [ {id, title, source, url, publish_date, ...}, ... ]
}
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import DATA_DAILY_DIR


def _extract_date(publish_date: str) -> str:
    """从 publish_date 字段提取日期字符串 YYYY-MM-DD"""
    if not publish_date:
        return "unknown"
    try:
        if "T" in publish_date:
            dt = datetime.fromisoformat(publish_date[:19])
            return dt.strftime("%Y-%m-%d")
        if len(publish_date) >= 10:
            return publish_date[:10]
    except (ValueError, TypeError):
        pass
    return "unknown"


def cleanup_old_daily(max_days: int = 7) -> int:
    """
    删除超过 max_days 天的本地日报文件

    Returns:
        删除的文件数
    """
    if not os.path.exists(DATA_DAILY_DIR):
        return 0

    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=max_days)).isoformat()

    deleted = 0
    for filename in os.listdir(DATA_DAILY_DIR):
        if not filename.endswith(".json"):
            continue
        day = filename[:-5]
        if day < cutoff:
            filepath = os.path.join(DATA_DAILY_DIR, filename)
            os.remove(filepath)
            deleted += 1

    if deleted:
        print(f"[日报存储] 清理 {deleted} 个超过 {max_days} 天的旧文件")
    return deleted


def save_to_daily(news_list: list[dict], target_date: str = None, max_days: int = 7) -> dict[str, int]:
    """
    将新闻列表按日期保存到 data/daily/ 目录

    Args:
        news_list: 新闻列表（可混合多个数据源）
        target_date: 如果指定，只保存该日期的新闻；None 则按 publish_date 自动分组

    Returns:
        { "2026-04-16": 42, "2026-04-15": 30, ... } 每个日期保存的条数
    """
    os.makedirs(DATA_DAILY_DIR, exist_ok=True)

    # 按日期分组
    groups = defaultdict(list)
    for item in news_list:
        if target_date:
            day = target_date
        else:
            day = _extract_date(item.get("publish_date", ""))
        if day != "unknown":
            groups[day].append(item)

    saved = {}
    from datetime import date as _date, timedelta as _td
    cutoff = (_date.today() - _td(days=max_days)).isoformat()

    for day, items in sorted(groups.items()):
        # 跳过超过 max_days 的旧日期
        if day < cutoff:
            continue
        filepath = os.path.join(DATA_DAILY_DIR, f"{day}.json")

        # 加载已有数据（追加模式）
        existing = []
        existing_ids = set()
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing = data.get("news", [])
                existing_ids = {item.get("id", "") for item in existing}
            except (json.JSONDecodeError, IOError):
                existing = []
                existing_ids = set()

        # 合并去重
        new_count = 0
        for item in items:
            if item.get("id", "") not in existing_ids:
                existing.append(item)
                existing_ids.add(item.get("id", ""))
                new_count += 1

        # 统计来源
        source_counter = Counter(item.get("source", "未知") for item in existing)

        daily_data = {
            "date": day,
            "count": len(existing),
            "sources": dict(source_counter.most_common()),
            "news": existing,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(daily_data, f, ensure_ascii=False, indent=2)

        saved[day] = new_count

    if saved:
        print(f"[日报存储] 保存 {len(saved)} 天的数据: " +
              ", ".join(f"{d}(+{c})" for d, c in sorted(saved.items())))
    else:
        print("[日报存储] 无有效日期的新闻")

    return saved


def load_daily(target_date: str = None) -> list[dict]:
    """
    加载指定日期或所有日期的新闻

    Args:
        target_date: "YYYY-MM-DD" 加载指定日期；None 加载所有日期

    Returns:
        新闻列表
    """
    if not os.path.exists(DATA_DAILY_DIR):
        return []

    if target_date:
        filepath = os.path.join(DATA_DAILY_DIR, f"{target_date}.json")
        if not os.path.exists(filepath):
            print(f"[日报存储] {target_date} 无数据")
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        news = data.get("news", [])
        print(f"[日报存储] 加载 {target_date}: {len(news)} 条")
        return news

    # 加载所有日期
    all_news = []
    for filename in sorted(os.listdir(DATA_DAILY_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(DATA_DAILY_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_news.extend(data.get("news", []))
        except (json.JSONDecodeError, IOError):
            continue

    print(f"[日报存储] 加载全部: {len(all_news)} 条")
    return all_news


def list_available_dates() -> list[str]:
    """列出所有有数据的日期，按时间倒序"""
    if not os.path.exists(DATA_DAILY_DIR):
        return []
    dates = []
    for filename in os.listdir(DATA_DAILY_DIR):
        if filename.endswith(".json"):
            dates.append(filename[:-5])  # 去掉 .json
    return sorted(dates, reverse=True)


def migrate_from_raw():
    """
    从旧的按来源分组的文件迁移到按日期存储
    读取 data/raw/ 下的 hn_news.json, rss_news.json 等，
    合并后按日期存储到 data/daily/
    """
    from config import DATA_RAW_DIR

    all_news = []
    raw_files = [
        os.path.join(DATA_RAW_DIR, "hn_news.json"),
        os.path.join(DATA_RAW_DIR, "rss_news.json"),
        os.path.join(DATA_RAW_DIR, "chinese_news.json"),
        os.path.join(DATA_RAW_DIR, "social_news.json"),
        os.path.join(DATA_RAW_DIR, "manual_chinese.json"),
    ]

    for fp in raw_files:
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    items = json.load(f)
                if isinstance(items, list):
                    all_news.extend(items)
                    print(f"  读取 {os.path.basename(fp)}: {len(items)} 条")
            except (json.JSONDecodeError, IOError) as e:
                print(f"  跳过 {os.path.basename(fp)}: {e}")

    if not all_news:
        print("[迁移] 无数据可迁移")
        return

    # 去重
    seen = set()
    unique = []
    for item in all_news:
        nid = item.get("id", "")
        if nid and nid not in seen:
            seen.add(nid)
            unique.append(item)

    print(f"\n[迁移] 共 {len(all_news)} 条，去重后 {len(unique)} 条")
    saved = save_to_daily(unique)
    print(f"[迁移] 完成，覆盖 {len(saved)} 天")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="按日期存储新闻数据")
    parser.add_argument("--migrate", action="store_true", help="从旧数据迁移")
    parser.add_argument("--list-dates", action="store_true", help="列出所有可用日期")
    parser.add_argument("--load", type=str, default=None, help="加载指定日期的数据")
    args = parser.parse_args()

    if args.migrate:
        migrate_from_raw()
    elif args.list_dates:
        dates = list_available_dates()
        print(f"共 {len(dates)} 天:")
        for d in dates:
            print(f"  {d}")
    elif args.load:
        news = load_daily(args.load)
        for item in news[:5]:
            print(f"  [{item.get('source', '')}] {item.get('title', '')[:50]}")
        if len(news) > 5:
            print(f"  ... 共 {len(news)} 条")

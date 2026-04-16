"""
数据采集注册表

持久化记录所有已采集过的新闻 URL 和 ID，用于跨运行去重。
确保同一数据源多次采集时不会产生重复数据。

注册表结构 (seen_registry.json):
{
    "last_updated": "2026-04-16T10:30:00",
    "total_seen": 150,
    "urls": {
        "https://www.jiqizhixin.com/articles/xxx": {"id": "cn_001", "source": "机器之心", "collected_at": "..."},
        ...
    }
}
"""

import json
import os
from datetime import datetime

from config import DATA_RAW_DIR

REGISTRY_PATH = os.path.join(DATA_RAW_DIR, "seen_registry.json")


def _default_registry() -> dict:
    """返回空的注册表结构"""
    return {
        "last_updated": datetime.now().isoformat(),
        "total_seen": 0,
        "urls": {},
    }


def load_registry(path: str = None) -> dict:
    """
    加载注册表，不存在则创建空表。

    首次使用时会自动从已有的原始数据文件中初始化注册表，
    确保后续 fetch-new 不会把这些旧数据当新数据处理。
    """
    if path is None:
        path = REGISTRY_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                registry = json.load(f)
                if registry.get("urls"):
                    return registry
        except (json.JSONDecodeError, IOError):
            pass

    # 新注册表：从已有原始数据文件中初始化
    registry = _default_registry()
    _seed_from_raw_files(registry)
    if registry["urls"]:
        save_registry(registry, path)
        print(f"[注册表] 从已有数据初始化，共 {registry['total_seen']} 条历史记录")
    return registry


def _seed_from_raw_files(registry: dict):
    """从已有的原始数据文件中初始化注册表"""
    raw_files = [
        os.path.join(DATA_RAW_DIR, "hn_news.json"),
        os.path.join(DATA_RAW_DIR, "rss_news.json"),
        os.path.join(DATA_RAW_DIR, "chinese_news.json"),
        os.path.join(DATA_RAW_DIR, "manual_chinese.json"),
    ]
    for filepath in raw_files:
        if not os.path.exists(filepath):
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                news_list = json.load(f)
            count = register_news(news_list, registry)
            if count:
                fname = os.path.basename(filepath)
                print(f"  [注册表] {fname}: 注册 {count} 条历史数据")
        except (json.JSONDecodeError, IOError):
            continue


def save_registry(registry: dict, path: str = None) -> str:
    """保存注册表"""
    if path is None:
        path = REGISTRY_PATH
    registry["last_updated"] = datetime.now().isoformat()
    registry["total_seen"] = len(registry.get("urls", {}))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    return path


def get_seen_urls(registry: dict) -> set[str]:
    """获取所有已采集过的 URL 集合"""
    return set(registry.get("urls", {}).keys())


def get_seen_ids(registry: dict) -> set[str]:
    """获取所有已采集过的 ID 集合"""
    return {v["id"] for v in registry.get("urls", {}).values()}


def register_news(news_list: list[dict], registry: dict) -> int:
    """
    将新闻列表中的条目注册到注册表中

    Returns:
        新注册的条目数量
    """
    urls = registry.setdefault("urls", {})
    new_count = 0
    for item in news_list:
        url = item.get("url", "")
        nid = item.get("id", "")
        if url and url not in urls:
            urls[url] = {
                "id": nid,
                "source": item.get("source", ""),
                "title": item.get("title", "")[:80],
                "collected_at": datetime.now().isoformat(),
            }
            new_count += 1
    return new_count


def filter_new_news(news_list: list[dict], registry: dict) -> list[dict]:
    """
    过滤出注册表中不存在的新新闻（按 URL 去重）

    Returns:
        真正新增的新闻列表
    """
    seen_urls = get_seen_urls(registry)
    return [item for item in news_list if item.get("url", "") not in seen_urls]


def print_registry_stats(registry: dict):
    """打印注册表统计信息"""
    urls = registry.get("urls", {})
    sources = {}
    for v in urls.values():
        src = v.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    print(f"[注册表] 共记录 {len(urls)} 条已采集新闻")
    if sources:
        for src, cnt in sorted(sources.items(), key=lambda x: -x[1]):
            print(f"  {src}: {cnt} 条")
    print(f"[注册表] 最后更新: {registry.get('last_updated', 'N/A')}")

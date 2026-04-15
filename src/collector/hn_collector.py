"""
Hacker News 数据采集器

通过 HN Firebase API 获取 AI 相关的 Top Stories。
API 文档: https://github.com/HackerNews/API

采集流程：
1. 获取 Top 100 Stories ID
2. 逐条获取 Story 详情
3. 通过标题关键词过滤 AI 相关帖子
4. 保存结构化数据
"""

import json
import re
import time
import requests
from datetime import datetime

from config import HN_TOP_STORIES_COUNT, HN_AI_KEYWORDS, DATA_RAW_DIR

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


def fetch_top_story_ids(count: int = HN_TOP_STORIES_COUNT) -> list[int]:
    """获取 HN Top Stories ID 列表"""
    url = f"{HN_API_BASE}/topstories.json"
    print(f"[HN] 获取 Top {count} Stories...")
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    ids = resp.json()
    print(f"[HN] 获取到 {len(ids)} 个 Story ID")
    return ids[:count]


def fetch_story_detail(item_id: int) -> dict | None:
    """获取单条 Story 详情"""
    url = f"{HN_API_BASE}/item/{item_id}.json"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, json.JSONDecodeError):
        return None


def is_ai_related(title: str) -> bool:
    """判断标题是否与 AI 相关（使用单词边界匹配，避免子串误判）"""
    if not title:
        return False
    title_lower = title.lower()
    for kw in HN_AI_KEYWORDS:
        # 使用单词边界匹配，避免 "ai" 匹配到 "air"、"available" 等
        if re.search(r'\b' + re.escape(kw) + r'\b', title_lower):
            return True
    return False


def collect_hn_news(max_results: int = 15) -> list[dict]:
    """
    采集 HN 上的 AI 相关新闻

    Args:
        max_results: 最多返回多少条 AI 相关新闻

    Returns:
        结构化的新闻列表
    """
    story_ids = fetch_top_story_ids()
    ai_news = []

    for i, sid in enumerate(story_ids):
        if len(ai_news) >= max_results:
            break

        story = fetch_story_detail(sid)
        if not story:
            continue

        # 只保留有 URL 的 story（排除 Ask HN 等）
        if story.get("type") != "story" or not story.get("url"):
            continue

        title = story.get("title", "")
        if not is_ai_related(title):
            continue

        news_item = {
            "id": f"hn_{sid}",
            "title": title,
            "source": "Hacker News",
            "url": story.get("url", ""),
            "publish_date": datetime.fromtimestamp(
                story.get("time", 0)
            ).isoformat(),
            "language": "en",
            "summary": title,  # HN 没有正文，用标题作为摘要
            "score": story.get("score", 0),
            "descendants": story.get("descendants", 0),
        }
        ai_news.append(news_item)
        print(f"  [{len(ai_news)}/{max_results}] {title[:60]}...")

        # 避免请求过快
        time.sleep(0.1)

    print(f"[HN] 共采集到 {len(ai_news)} 条 AI 相关新闻")
    return ai_news


def save_hn_news(news_list: list[dict], filepath: str = None) -> str:
    """保存 HN 新闻数据到 JSON 文件"""
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/hn_news.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"[HN] 数据已保存到 {filepath}")
    return filepath


def load_hn_news(filepath: str = None) -> list[dict]:
    """加载已保存的 HN 新闻数据"""
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/hn_news.json"

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    news = collect_hn_news()
    save_hn_news(news)

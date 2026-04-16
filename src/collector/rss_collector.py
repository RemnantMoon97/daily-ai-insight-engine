"""
RSS Feed 数据采集器

通过 RSS Feed 获取中英文科技媒体的 AI 相关新闻。
支持多个数据源，自动过滤 AI 相关内容。

采集流程：
1. 遍历配置的 RSS Feed 列表
2. 使用 feedparser 解析每个 Feed
3. 通过标题+摘要关键词过滤 AI 相关条目（中文源用中文关键词）
4. 输出统一结构化数据
"""

import hashlib
import json
import re
import time
from datetime import datetime

import feedparser
import requests

from config import (
    CN_AI_KEYWORDS,
    COLLECT_DELAY,
    COLLECT_MAX_PER_SOURCE,
    COLLECT_TIMEOUT,
    DATA_RAW_DIR,
    HN_AI_KEYWORDS,
    RSS_FEEDS,
)


def _generate_id(url: str) -> str:
    """根据 URL 生成唯一 ID"""
    short_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"rss_{short_hash}"


def _parse_date(entry) -> str:
    """解析 RSS 条目的发布日期，返回 ISO 格式字符串"""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                dt = datetime(*parsed[:6])
                return dt.isoformat()
            except (TypeError, ValueError):
                continue

    # 尝试从字符串字段解析
    for attr in ("published", "updated"):
        val = getattr(entry, attr, "")
        if val:
            try:
                from email.utils import parsedate_to_datetime

                dt = parsedate_to_datetime(val)
                return dt.isoformat()
            except Exception:
                continue

    return datetime.now().isoformat()


def _clean_summary(summary: str) -> str:
    """清理摘要中的 HTML 标签"""
    if not summary:
        return ""
    # 移除 HTML 标签
    clean = re.sub(r"<[^>]+>", "", summary)
    # 移除多余空白
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:500]  # 限制长度


def is_ai_related(title: str, summary: str = "", language: str = "en") -> bool:
    """判断新闻是否与 AI 相关，根据语言选择关键词"""
    text = f"{title} {summary}".lower()
    keywords = CN_AI_KEYWORDS if language == "zh" else HN_AI_KEYWORDS
    for kw in keywords:
        if language == "en":
            # 英文使用单词边界匹配
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return True
        else:
            # 中文直接子串匹配
            if kw.lower() in text:
                return True
    return False


def fetch_rss_feed(feed_url: str, timeout: int = COLLECT_TIMEOUT) -> dict:
    """获取并解析单个 RSS Feed"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(feed_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return feedparser.parse(resp.content)
    except requests.RequestException as e:
        print(f"  [RSS] 请求失败: {feed_url} - {e}")
        return feedparser.parse("")  # 返回空 feed


def collect_from_feed(feed_config: dict, max_results: int = COLLECT_MAX_PER_SOURCE) -> list[dict]:
    """
    从单个 RSS Feed 采集 AI 相关新闻

    Args:
        feed_config: 包含 name, url, language 的配置字典
        max_results: 最多返回多少条

    Returns:
        结构化新闻列表
    """
    source_name = feed_config["name"]
    feed_url = feed_config["url"]
    language = feed_config.get("language", "en")

    print(f"  [RSS] 正在采集 {source_name} ...")
    feed = fetch_rss_feed(feed_url)

    if not feed.entries:
        print(f"  [RSS] {source_name} 无可用条目")
        return []

    ai_news = []
    for entry in feed.entries:
        if len(ai_news) >= max_results:
            break

        title = entry.get("title", "").strip()
        url = entry.get("link", "").strip()
        if not title or not url:
            continue

        summary_raw = entry.get("summary", "") or entry.get("description", "")
        summary = _clean_summary(summary_raw)

        # AI 相关性过滤
        if not is_ai_related(title, summary, language):
            continue

        news_item = {
            "id": _generate_id(url),
            "title": title,
            "source": source_name,
            "url": url,
            "publish_date": _parse_date(entry),
            "language": language,
            "summary": summary or title,
        }
        ai_news.append(news_item)

    print(f"  [RSS] {source_name}: 采集到 {len(ai_news)} 条 AI 相关新闻")
    return ai_news


def collect_all_rss(feeds: list[dict] = None) -> list[dict]:
    """
    从所有 RSS 数据源采集新闻

    Args:
        feeds: RSS 配置列表，默认使用 config.RSS_FEEDS

    Returns:
        所有数据源的合并新闻列表
    """
    if feeds is None:
        feeds = RSS_FEEDS

    print(f"\n[RSS] 开始采集 {len(feeds)} 个 RSS 数据源...")
    all_news = []

    for feed_config in feeds:
        news = collect_from_feed(feed_config)
        all_news.extend(news)
        time.sleep(COLLECT_DELAY)

    print(f"[RSS] 共采集到 {len(all_news)} 条 AI 相关新闻")
    return all_news


def save_rss_news(news_list: list[dict], filepath: str = None) -> str:
    """保存 RSS 新闻数据到 JSON 文件"""
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/rss_news.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"[RSS] 数据已保存到 {filepath}")
    return filepath


def load_rss_news(filepath: str = None) -> list[dict]:
    """加载已保存的 RSS 新闻数据"""
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/rss_news.json"

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    news = collect_all_rss()
    save_rss_news(news)

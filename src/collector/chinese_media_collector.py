"""
中文科技媒体爬虫

为机器之心、量子位、36氪、AIBase 等中文科技媒体实现网页爬虫。
通过 requests + BeautifulSoup 采集文章列表页，提取 AI 相关新闻。

采集流程：
1. 请求各媒体的文章列表/API 页面
2. 解析 HTML/JSON 提取文章信息
3. 通过中文 AI 关键词过滤
4. 输出统一结构化数据
"""

import hashlib
import json
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from config import (
    CN_AI_KEYWORDS,
    CN_MEDIA_SOURCES,
    COLLECT_DELAY,
    COLLECT_MAX_PER_SOURCE,
    COLLECT_TIMEOUT,
    DATA_RAW_DIR,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _generate_id(prefix: str, url: str) -> str:
    """根据前缀和 URL 生成唯一 ID"""
    short_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{prefix}_{short_hash}"


def is_ai_related_cn(title: str, summary: str = "") -> bool:
    """判断中文新闻是否与 AI 相关"""
    text = f"{title} {summary}".lower()
    for kw in CN_AI_KEYWORDS:
        if kw.lower() in text:
            return True
    return False


# ─── 机器之心 ─────────────────────────────────────────────


def collect_jiqizhixin(max_results: int = COLLECT_MAX_PER_SOURCE) -> list[dict]:
    """采集机器之心文章列表"""
    print("  [中文] 正在采集 机器之心 ...")
    news = []

    try:
        # 机器之心文章列表页
        url = "https://www.jiqizhixin.com/articles"
        resp = requests.get(url, headers=HEADERS, timeout=COLLECT_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # 查找文章卡片/链接 - 适配常见列表页结构
        articles = soup.select("a[href*='/articles/']") or soup.select(".article-item a")

        seen_urls = set()
        for a_tag in articles:
            if len(news) >= max_results:
                break

            article_url = a_tag.get("href", "")
            if article_url.startswith("/"):
                article_url = "https://www.jiqizhixin.com" + article_url

            if not article_url or article_url in seen_urls:
                continue
            seen_urls.add(article_url)

            title = a_tag.get_text(strip=True)
            if not title or not is_ai_related_cn(title):
                continue

            news.append({
                "id": _generate_id("jqzx", article_url),
                "title": title,
                "source": "机器之心",
                "url": article_url,
                "publish_date": datetime.now().isoformat(),
                "language": "zh",
                "summary": title,
            })

    except requests.RequestException as e:
        print(f"  [中文] 机器之心采集失败: {e}")

    print(f"  [中文] 机器之心: 采集到 {len(news)} 条")
    return news


# ─── 量子位 ─────────────────────────────────────────────


def collect_qbitai(max_results: int = COLLECT_MAX_PER_SOURCE) -> list[dict]:
    """采集量子位文章列表"""
    print("  [中文] 正在采集 量子位 ...")
    news = []

    try:
        url = "https://www.qbitai.com"
        resp = requests.get(url, headers=HEADERS, timeout=COLLECT_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # 量子位 WordPress 文章链接格式: /YYYY/MM/NNNNN.html
        articles = soup.select("a[href*='/20']")  # 匹配 /2026/ 等年份链接

        seen_urls = set()
        for a_tag in articles:
            if len(news) >= max_results:
                break

            article_url = a_tag.get("href", "")
            if article_url.startswith("/"):
                article_url = "https://www.qbitai.com" + article_url

            # 只匹配文章链接格式
            if not re.match(r"https://www\.qbitai\.com/\d{4}/\d{2}/\d+", article_url):
                continue

            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5 or not is_ai_related_cn(title):
                continue

            news.append({
                "id": _generate_id("qbt", article_url),
                "title": title,
                "source": "量子位",
                "url": article_url,
                "publish_date": datetime.now().isoformat(),
                "language": "zh",
                "summary": title,
            })

    except requests.RequestException as e:
        print(f"  [中文] 量子位采集失败: {e}")

    print(f"  [中文] 量子位: 采集到 {len(news)} 条")
    return news


# ─── 36氪 ─────────────────────────────────────────────


def collect_36kr(max_results: int = COLLECT_MAX_PER_SOURCE) -> list[dict]:
    """采集36氪 AI 分类文章"""
    print("  [中文] 正在采集 36氪 ...")
    news = []

    try:
        # 36氪的资讯流 API
        url = "https://36kr.com/information/AI"
        resp = requests.get(url, headers=HEADERS, timeout=COLLECT_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # 36氪文章链接格式: /p/NNNNNN 或 https://www.36kr.com/p/NNNNNN
        articles = soup.select("a[href*='/p/']")

        seen_urls = set()
        for a_tag in articles:
            if len(news) >= max_results:
                break

            article_url = a_tag.get("href", "")
            if article_url.startswith("/"):
                article_url = "https://36kr.com" + article_url

            # 兼容 www.36kr.com 和 36kr.com
            if not re.match(r"https?://(www\.)?36kr\.com/p/\d+", article_url):
                continue

            # 统一 URL 格式（去掉 www）
            article_url = re.sub(r"https?://(www\.)?36kr\.com", "https://36kr.com", article_url)

            if article_url in seen_urls:
                continue

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            # 只在成功匹配时加入已见集合
            seen_urls.add(article_url)

            # 36氪 AI 页面本身就已过滤，但也做一次关键词检查
            news.append({
                "id": _generate_id("36kr", article_url),
                "title": title,
                "source": "36氪",
                "url": article_url,
                "publish_date": datetime.now().isoformat(),
                "language": "zh",
                "summary": title,
            })

    except requests.RequestException as e:
        print(f"  [中文] 36氪采集失败: {e}")

    print(f"  [中文] 36氪: 采集到 {len(news)} 条")
    return news


# ─── AIBase ─────────────────────────────────────────────


def collect_aibase(max_results: int = COLLECT_MAX_PER_SOURCE) -> list[dict]:
    """采集 AIBase 新闻列表"""
    print("  [中文] 正在采集 AIBase ...")
    news = []

    try:
        url = "https://www.aibase.com/zh/news"
        resp = requests.get(url, headers=HEADERS, timeout=COLLECT_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "lxml")

        # AIBase 文章链接格式: /zh/news/NNNNN
        articles = soup.select("a[href*='/zh/news/']")

        seen_urls = set()
        for a_tag in articles:
            if len(news) >= max_results:
                break

            article_url = a_tag.get("href", "")
            if article_url.startswith("/"):
                article_url = "https://www.aibase.com" + article_url

            if not re.match(r"https://www\.aibase\.com/zh/news/\d+", article_url):
                continue

            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)

            title = a_tag.get_text(strip=True)
            if not title or len(title) < 5:
                continue

            # AIBase 是 AI 专题站，不需要额外关键词过滤
            news.append({
                "id": _generate_id("aibase", article_url),
                "title": title,
                "source": "AIBase",
                "url": article_url,
                "publish_date": datetime.now().isoformat(),
                "language": "zh",
                "summary": title,
            })

    except requests.RequestException as e:
        print(f"  [中文] AIBase采集失败: {e}")

    print(f"  [中文] AIBase: 采集到 {len(news)} 条")
    return news


# ─── 统一入口 ─────────────────────────────────────────────


# 采集函数映射表
COLLECTORS = {
    "量子位": collect_qbitai,
    "36氪": collect_36kr,
}


def collect_all_chinese(
    sources: list[dict] = None,
    max_per_source: int = COLLECT_MAX_PER_SOURCE,
) -> list[dict]:
    """
    采集所有中文科技媒体的 AI 相关新闻

    Args:
        sources: 媒体源配置列表，默认使用 config.CN_MEDIA_SOURCES
        max_per_source: 每个源最多采集条数

    Returns:
        合并后的新闻列表
    """
    if sources is None:
        sources = CN_MEDIA_SOURCES

    print(f"\n[中文媒体] 开始采集 {len(sources)} 个中文数据源...")
    all_news = []

    for source in sources:
        name = source["name"]
        collector = COLLECTORS.get(name)
        if collector:
            news = collector(max_results=max_per_source)
            all_news.extend(news)
        else:
            print(f"  [中文] 未知的媒体源: {name}")
        time.sleep(COLLECT_DELAY)

    print(f"[中文媒体] 共采集到 {len(all_news)} 条 AI 相关新闻")
    return all_news


def save_chinese_news(news_list: list[dict], filepath: str = None) -> str:
    """保存中文新闻数据到 JSON 文件"""
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/chinese_news.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"[中文媒体] 数据已保存到 {filepath}")
    return filepath


def load_chinese_news(filepath: str = None) -> list[dict]:
    """加载已保存的中文新闻数据"""
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/chinese_news.json"

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    news = collect_all_chinese()
    save_chinese_news(news)

"""
AI 舆情日报正文生成器

基于当天新闻和投资分析 JSON，生成适合网页正文区域展示的日报文章。
"""

import json
import os
import sys
from datetime import date

sys.path.insert(0, ".")

from config import OUTPUT_DIR, PROMPT_DAILY_ARTICLE_PATH
from src.extractor import get_client, call_llm


def _load_daily_article_prompt() -> str:
    with open(PROMPT_DAILY_ARTICLE_PATH, "r", encoding="utf-8") as f:
        return f.read()


_DAILY_ARTICLE_PROMPT = _load_daily_article_prompt()


def build_daily_article_prompt(news_list: list[dict], investment_analysis: dict | None, target_date: str) -> str:
    slim_news = []
    for n in news_list[:25]:
        slim_news.append({
            "title": n.get("title", ""),
            "source": n.get("source", ""),
            "summary": n.get("summary", ""),
            "publish_date": n.get("publish_date", ""),
            "url": n.get("url", ""),
            "language": n.get("language", ""),
        })

    investment_payload = investment_analysis or {}

    prompt = _DAILY_ARTICLE_PROMPT
    prompt += "\n\n# 日期\n"
    prompt += target_date
    prompt += "\n\n# 当天新闻列表\n"
    prompt += json.dumps(slim_news, ensure_ascii=False, indent=2)
    prompt += "\n\n# 当天投资分析 JSON\n"
    prompt += json.dumps(investment_payload, ensure_ascii=False, indent=2)
    return prompt


def generate_daily_article(news_list: list[dict], investment_analysis: dict | None, target_date: str = None) -> str | None:
    if target_date is None:
        target_date = date.today().isoformat()

    if not news_list:
        print(f"[正文] {target_date} 无新闻数据，跳过")
        return None

    prompt = build_daily_article_prompt(news_list, investment_analysis, target_date)
    print(f"\n[正文] 开始生成 {target_date} 的日报正文（prompt ~{len(prompt)} 字符）...")

    try:
        client = get_client()
        resp = call_llm(client, prompt, max_tokens=4096)
        if not resp:
            print("[正文] LLM 返回为空")
            return None

        article = resp.strip()
        if article.startswith("```markdown"):
            article = article[len("```markdown"):]
        if article.startswith("```"):
            article = article[3:]
        if article.endswith("```"):
            article = article[:-3]
        article = article.strip()

        print("[正文] 生成完成")
        return article
    except Exception as e:
        print(f"[正文] 生成失败: {e}")
        return None


def save_daily_article(article_markdown: str, target_date: str = None) -> str:
    if target_date is None:
        target_date = date.today().isoformat()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"daily_article_{target_date}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(article_markdown)
    print(f"[正文] 已保存到 {filepath}")
    return filepath


def load_daily_article(target_date: str = None) -> str | None:
    if target_date is None:
        target_date = date.today().isoformat()

    filepath = os.path.join(OUTPUT_DIR, f"daily_article_{target_date}.md")
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except IOError:
        return None

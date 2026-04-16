"""
投资情绪分析器

使用 investment-sentiment-news SKILL 的 prompt，
将每日新闻转化为投资导向的结构化 JSON 分析。
"""

import json
import os
import sys
import time
from datetime import date

sys.path.insert(0, ".")

from config import ZHIPU_MODEL, OUTPUT_DIR, DATA_DAILY_DIR, PROMPT_INVESTMENT_PATH
from src.extractor import get_client, call_llm, parse_json_response


def _load_investment_prompt() -> str:
    """加载投资分析 prompt"""
    with open(PROMPT_INVESTMENT_PATH, "r", encoding="utf-8") as f:
        return f.read()


_INVESTMENT_PROMPT = _load_investment_prompt()


def generate_investment_analysis(news_list: list[dict], target_date: str = None) -> dict | None:
    """
    生成投资情绪分析（JSON 格式）

    Args:
        news_list: 当天的新闻列表
        target_date: 日期字符串

    Returns:
        投资分析 JSON dict 或 None
    """
    if target_date is None:
        target_date = date.today().isoformat()

    if not news_list:
        print(f"[投资分析] {target_date} 无新闻数据，跳过")
        return None

    # 精简新闻输入：只保留关键字段，减少 prompt 长度
    slim_news = []
    for n in news_list[:30]:  # 最多 30 条
        slim_news.append({
            "title": n.get("title", ""),
            "source": n.get("source", ""),
            "summary": n.get("summary", ""),
            "url": n.get("url", ""),
        })
    news_input = json.dumps(slim_news, ensure_ascii=False, indent=2)

    prompt = _INVESTMENT_PROMPT
    prompt += news_input

    print(f"\n[投资分析] 开始生成 {target_date} 的投资分析（{len(slim_news)} 条新闻，prompt ~{len(prompt)} 字符）...")

    try:
        client = get_client()
        resp = call_llm(client, prompt, max_tokens=8192)

        if not resp:
            print(f"[投资分析] LLM 返回为空")
            return None

        result = parse_json_response(resp)

        if result and result.get("date"):
            print(f"[投资分析] 生成完成: {result.get('core_hook', '')}")
            return result

        # 返回可能不完整 — 尝试修复常见截断问题
        if result and "top_events" not in result:
            print(f"[投资分析] 返回缺少 top_events，尝试补全...")
            # 如果 LLM 返回了一个事件对象而非完整 schema
            if "headline" in result and "rank" in result:
                print(f"[投资分析] LLM 只返回了单个事件，重新构造完整结构")
                return _build_minimal_investment(target_date, [result])
            return result

        if not result:
            print(f"[投资分析] 无法解析 LLM 返回的 JSON")
            # 打印前 200 字符帮助调试
            print(f"  LLM 原始返回前 200 字: {resp[:200]}")

        return result

    except Exception as e:
        print(f"[投资分析] 生成失败: {e}")
        return None


def _build_minimal_investment(target_date: str, events: list[dict]) -> dict:
    """当 LLM 返回不完整时，构造最小可用结构"""
    return {
        "date": target_date,
        "page_positioning": "首页AI板块",
        "market_temperature": "中",
        "core_hook": "AI板块动态更新",
        "sub_hook": "请查看事件详情",
        "daily_outlook": "当日AI板块有多条值得关注的事件，建议关注相关公司动态。",
        "top_events": events,
        "company_signal_board": [],
        "theme_opportunities": [],
        "theme_risks": [],
        "homepage_modules": {
            "hero_banner": {"title": "AI板块动态", "subtitle": "当日事件更新", "cta_text": "查看"},
            "fast_bullets": [],
            "watchlist_tags": [],
        },
    }


def save_investment_analysis(analysis: dict, target_date: str = None) -> str:
    """保存投资分析结果"""
    if target_date is None:
        target_date = date.today().isoformat()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filepath = os.path.join(OUTPUT_DIR, f"investment_{target_date}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    print(f"[投资分析] 已保存到 {filepath}")
    return filepath


def load_investment_analysis(target_date: str = None) -> dict | None:
    """加载已有的投资分析结果"""
    if target_date is None:
        target_date = date.today().isoformat()

    filepath = os.path.join(OUTPUT_DIR, f"investment_{target_date}.json")
    if not os.path.exists(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

"""
数据清洗模块

在 LLM 结构化抽取之前，对原始新闻数据进行清洗：
1. 标准化：统一时间格式、来源名称、语言标记
2. 内容补全：为缺少摘要的条目补充内容
3. 语义去重：规则粗筛 + LLM 精细合并（混合策略）
4. 噪声过滤：标记 AI 相关度低的条目（保留不删除）
"""

import json
import re
import sys
from datetime import datetime

sys.path.insert(0, ".")
from config import DATA_PROCESSED_DIR
from src.extractor import get_client, call_llm, parse_json_response

# ---- 来源名称标准化映射 ----
SOURCE_ALIASES = {
    "hacker news": "Hacker News",
    "hn": "Hacker News",
    "jiqizhixin": "机器之心",
    "机器之心": "机器之心",
    "qbitai": "量子位",
    "量子位": "量子位",
    "36kr": "36氪",
    "36氪": "36氪",
    "36k": "36氪",
    "aibase": "AIBase",
    "techcrunch": "TechCrunch",
    "artificial intelligence news": "AI News",
    "south china morning post": "南华早报",
    "scmp": "南华早报",
    "new york post": "New York Post",
    "nypost": "New York Post",
    "the times": "The Times",
    "neowin": "Neowin",
    "business insider": "Business Insider",
}


def normalize_date(date_str: str) -> str:
    """将各种日期格式统一为 ISO 8601"""
    if not date_str:
        return ""

    # 已经是标准格式
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, AttributeError):
        pass

    # 常见格式尝试
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue

    return date_str  # 无法解析，保留原样


def normalize_source(source: str) -> str:
    """标准化来源名称"""
    if not source:
        return "未知"
    return SOURCE_ALIASES.get(source.lower().strip(), source.strip())


def detect_language(text: str) -> str:
    """检测文本语言（通过中文字符比例）"""
    if not text:
        return "en"
    cn_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if cn_chars / max(len(text), 1) > 0.1 else "en"


def normalize_news(news_list: list[dict]) -> list[dict]:
    """标准化所有新闻条目"""
    for item in news_list:
        # 标准化时间
        item["publish_date"] = normalize_date(item.get("publish_date", ""))

        # 标准化来源
        item["source"] = normalize_source(item.get("source", ""))

        # 校验语言标记
        lang = item.get("language", "")
        if lang not in ("zh", "en"):
            item["language"] = detect_language(
                item.get("title", "") + " " + item.get("summary", "")
            )

    print(f"[清洗-标准化] 完成")
    return news_list


def complete_summaries(news_list: list[dict]) -> list[dict]:
    """补全缺失的摘要"""
    completed = 0
    for item in news_list:
        summary = item.get("summary", "").strip()
        title = item.get("title", "").strip()

        # 摘要为空或与标题完全相同 → 补全
        if not summary or summary == title:
            item["summary"] = title
            item["summary_auto"] = True  # 标记为自动补全
            completed += 1

    print(f"[清洗-补全] 补全了 {completed} 条摘要")
    return news_list


def _rule_based_similarity(a: dict, b: dict) -> float:
    """
    规则计算两条新闻的相似度（0-1）
    用于去重预筛选，高相似度的交给 LLM 二次确认
    """
    score = 0.0

    ta = a.get("title", "").lower()
    tb = b.get("title", "").lower()

    # 标题关键词重叠度
    words_a = set(re.findall(r"\w+", ta))
    words_b = set(re.findall(r"\w+", tb))
    if words_a and words_b:
        overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
        score += overlap * 0.5

    # 来源相同且标题有重叠
    if a.get("source") == b.get("source") and score > 0.3:
        score += 0.1

    # 摘要关键词重叠
    sa = a.get("summary", "").lower()
    sb = b.get("summary", "").lower()
    words_sa = set(re.findall(r"\w+", sa))
    words_sb = set(re.findall(r"\w+", sb))
    if words_sa and words_sb:
        overlap_s = len(words_sa & words_sb) / min(len(words_sa), len(words_sb))
        score += overlap_s * 0.3

    # 时间相近（2天内）
    try:
        da = datetime.fromisoformat(a.get("publish_date", "")[:19])
        db = datetime.fromisoformat(b.get("publish_date", "")[:19])
        days_diff = abs((da - db).total_seconds()) / 86400
        if days_diff <= 2:
            score += 0.1
    except (ValueError, TypeError):
        pass

    return min(score, 1.0)


def _find_rule_duplicates(news_list: list[dict], threshold: float = 0.4) -> list[list[int]]:
    """规则预筛选：找出可能重复的新闻对，返回分组"""
    n = len(news_list)
    # 用并查集做分组
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(n):
        for j in range(i + 1, n):
            sim = _rule_based_similarity(news_list[i], news_list[j])
            if sim >= threshold:
                union(i, j)

    # 收集分组
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(i)

    # 只返回有多个成员的组
    return [indices for indices in groups.values() if len(indices) > 1]


def deduplicate_news(news_list: list[dict]) -> list[dict]:
    """
    混合去重：规则预筛选 + LLM 精细判断

    规则先找出可能重复的分组，LLM 确认后合并。
    合并策略：保留信息最丰富的条目为主，其他作为 related_articles。
    """
    print(f"[清洗-去重] 开始混合去重（规则+LLM）...")

    # Step 1: 规则预筛选
    dup_groups = _find_rule_duplicates(news_list)

    if not dup_groups:
        print(f"[清洗-去重] 规则未发现重复，跳过 LLM 确认")
        return news_list

    print(f"[清洗-去重] 规则发现 {len(dup_groups)} 组疑似重复")

    # Step 2: LLM 精细确认每个分组
    merge_plan = {}  # {主条目index: [从条目index]}
    client = get_client()

    for group_indices in dup_groups:
        group_items = [news_list[i] for i in group_indices]
        titles = "\n".join(
            f"  [{i+1}] {item.get('title', '')} (来源: {item.get('source', '')})"
            for i, item in enumerate(group_items)
        )

        prompt = f"""判断以下新闻是否报道了同一事件。同一事件 = 核心事件相同，只是不同媒体的报道。

{titles}

返回 JSON 格式：
{{"same_event": true/false, "reason": "简短说明为什么是或不是同一事件"}}

只返回 JSON，不要其他文字。"""

        try:
            resp = call_llm(client, prompt)
            result = parse_json_response(resp)
            if result and result.get("same_event"):
                # 合并：选摘要最长的作为主条目
                best = max(group_indices, key=lambda i: len(news_list[i].get("summary", "")))
                others = [i for i in group_indices if i != best]
                merge_plan[best] = merge_plan.get(best, []) + others
                print(f"  [去重] 合并: {news_list[best]['title'][:40]} ← "
                      f"{len(others)} 条重复")
        except Exception as e:
            print(f"  [去重-LLM] 确认失败: {e}")

    # Step 3: 执行合并
    to_remove = set()
    for main_idx, other_indices in merge_plan.items():
        main = news_list[main_idx]
        related = []
        for oi in other_indices:
            other = news_list[oi]
            related.append({
                "id": other.get("id", ""),
                "title": other.get("title", ""),
                "source": other.get("source", ""),
                "url": other.get("url", ""),
            })
            to_remove.add(oi)

        main["related_articles"] = main.get("related_articles", []) + related
        # 取最早的时间
        dates = [main.get("publish_date", "")]
        dates += [news_list[oi].get("publish_date", "") for oi in other_indices]
        dates = [d for d in dates if d]
        if dates:
            main["publish_date"] = min(dates)

    result = [item for i, item in enumerate(news_list) if i not in to_remove]
    removed = len(to_remove)
    print(f"[清洗-去重] 完成，合并了 {removed} 条重复新闻")
    return result


def filter_noise(news_list: list[dict]) -> list[dict]:
    """
    噪声过滤：批量调用 LLM 为每条新闻打 AI 相关度分（1-5）
    低分条目标记但不删除
    """
    print(f"[清洗-过滤] 开始噪声过滤...")

    client = get_client()

    # 批量构建 prompt（一次调用处理全部）
    items_text = []
    for i, item in enumerate(news_list):
        items_text.append(
            f"[{i+1}] 标题: {item.get('title', '')}\n"
            f"    摘要: {item.get('summary', '')[:150]}"
        )
    all_items = "\n".join(items_text)

    prompt = f"""对以下每条新闻评估其与 AI（人工智能）核心领域的相关度，打 1-5 分：
- 5分: 直接关于 AI 技术/产品/政策的核心内容
- 4分: AI 相关的产业动态、投融资、人才变动
- 3分: 提及 AI 但非核心（如某公司顺便提到AI战略）
- 2分: 蹭 AI 概念的软文或仅一笔带过
- 1分: 与 AI 无关

{all_items}

返回 JSON 数组，每个元素是 {{"index": 序号, "score": 分数}}。只返回 JSON 数组。"""

    try:
        resp = call_llm(client, prompt)
        # 解析 JSON 数组
        scores = parse_json_response(resp)
        if isinstance(scores, dict):
            scores = scores.get("scores", [scores])
        if not isinstance(scores, list):
            scores = []

        score_map = {}
        for s in scores:
            if isinstance(s, dict):
                idx = s.get("index", 0) - 1
                sc = s.get("score", 3)
                if 0 <= idx < len(news_list):
                    score_map[idx] = int(sc)

        # 为每条新闻标记分数
        low_count = 0
        for i, item in enumerate(news_list):
            sc = score_map.get(i, 3)
            item["ai_relevance_score"] = sc
            if sc < 3:
                low_count += 1

        print(f"[清洗-过滤] 完成，{low_count} 条标记为低相关（分数<3）")

    except Exception as e:
        print(f"[清洗-过滤] LLM 打分失败: {e}，跳过过滤")
        for item in news_list:
            item.setdefault("ai_relevance_score", 3)

    return news_list


def clean_all(news_list: list[dict], save_path: str = None) -> list[dict]:
    """串联执行全部清洗步骤"""
    print(f"\n[清洗] 开始数据清洗，共 {len(news_list)} 条原始数据")

    # 1. 标准化
    news_list = normalize_news(news_list)

    # 2. 补全摘要
    news_list = complete_summaries(news_list)

    # 3. 语义去重
    news_list = deduplicate_news(news_list)

    # 4. 噪声过滤
    news_list = filter_noise(news_list)

    # 保存清洗结果
    if save_path is None:
        save_path = f"{DATA_PROCESSED_DIR}/cleaned_news.json"

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"[清洗] 完成，清洗后 {len(news_list)} 条，保存到 {save_path}")
    return news_list

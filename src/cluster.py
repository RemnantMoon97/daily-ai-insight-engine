"""
事件聚类 + 热点排序模块

基于结构化抽取后的数据，将多条新闻按事件聚类，并按热点分数排序。
两步聚类：规则预分组 → LLM 精细合并
热点打分：影响力 × 可信度 × 传播度 × 新颖度
"""

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime

sys.path.insert(0, ".")
from config import DATA_PROCESSED_DIR, ZHIPU_MODEL
from src.extractor import get_client, call_llm, parse_json_response

# ---- 来源可信度权重表 ----
SOURCE_CREDIBILITY = {
    # 官方渠道
    "arXiv": 1.0,
    "Official Blog": 1.0,
    "GitHub": 0.9,
    # 主流媒体
    "Reuters": 0.9,
    "Bloomberg": 0.9,
    "The New York Times": 0.9,
    "南华早报": 0.85,
    "TechCrunch": 0.8,
    "The Times": 0.8,
    "New York Post": 0.7,
    "Business Insider": 0.75,
    "Neowin": 0.7,
    # 科技媒体
    "机器之心": 0.8,
    "量子位": 0.8,
    "AIBase": 0.75,
    "AI News": 0.7,
    "36氪": 0.7,
    # 社区/博客
    "Hacker News": 0.65,
    "Reddit": 0.5,
    "Substack": 0.5,
}

# 默认可信度
DEFAULT_CREDIBILITY = 0.6

# ---- AI 头部公司关键词 ----
TOP_AI_COMPANIES = [
    "openai", "anthropic", "google", "deepmind", "meta", "microsoft",
    "apple", "nvidia", "amazon", "百度", "阿里", "腾讯", "字节跳动",
    "华为", "智谱", "zhipu", "deepseek", "moonshot", "百川",
]


def pre_cluster_by_rules(structured_news: list[dict]) -> list[list[dict]]:
    """
    规则预分组：按 main_topics 交集 + 共同关键词分组

    两条新闻分到同一组，如果满足以下任一：
    - main_topics 有交集（≥1个共同话题）
    - 标题中有相同公司/产品名
    """
    n = len(structured_news)
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
        topics_i = set(t.lower() for t in structured_news[i].get("main_topics", []))
        title_i = structured_news[i].get("title", "").lower()
        points_i = " ".join(structured_news[i].get("key_points", [])).lower()

        for j in range(i + 1, n):
            topics_j = set(t.lower() for t in structured_news[j].get("main_topics", []))

            # 规则1: 话题交集 ≥ 1
            if topics_i and topics_j and topics_i & topics_j:
                union(i, j)
                continue

            # 规则2: 标题或要点中有相同的头部公司名
            title_j = structured_news[j].get("title", "").lower()
            points_j = " ".join(structured_news[j].get("key_points", [])).lower()

            text_i = title_i + " " + points_i
            text_j = title_j + " " + points_j
            for company in TOP_AI_COMPANIES:
                if company in text_i and company in text_j:
                    union(i, j)
                    break

    # 收集分组
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(structured_news[i])

    result = list(groups.values())
    multi_groups = sum(1 for g in result if len(g) > 1)
    print(f"[聚类-预分组] {len(result)} 组，其中 {multi_groups} 组有多条新闻")
    return result


def refine_clusters_with_llm(cluster_groups: list[list[dict]]) -> list[dict]:
    """
    LLM 精细合并：对每组内的新闻，让 LLM 判断是否真的是同一事件
    返回 event cluster 列表
    """
    client = get_client()
    event_clusters = []
    evt_id = 0

    for group in cluster_groups:
        # 单条新闻直接成组
        if len(group) == 1:
            item = group[0]
            evt_id += 1
            event_clusters.append({
                "cluster_id": f"evt_{evt_id:03d}",
                "event_title": item.get("title", ""),
                "event_summary": item.get("summary", ""),
                "articles": [_article_meta(item)],
                "combined_topics": item.get("main_topics", []),
                "combined_key_points": item.get("key_points", []),
                "combined_impact": item.get("impact", ""),
                "combined_affected_companies": item.get("affected_companies", []),
                "max_ai_relevance": item.get("ai_relevance_score", 3),
            })
            continue

        # 多条新闻，让 LLM 判断
        items_text = "\n".join(
            f"  [{i+1}] {item.get('title', '')} (来源: {item.get('source', '')})\n"
            f"      要点: {'; '.join(item.get('key_points', [])[:3])}\n"
            f"      受影响公司: {'; '.join(c.get('name','') + '(' + c.get('impact_direction','') + ')' for c in item.get('affected_companies', [])[:3])}"
            for i, item in enumerate(group)
        )

        prompt = f"""以下 {len(group)} 条新闻可能涉及相同事件。请判断它们是否报道了同一个事件。

{items_text}

返回 JSON：
{{"same_event": true/false, "event_title": "统一的事件标题（如果同一事件）"}}

只返回 JSON。"""

        try:
            resp = call_llm(client, prompt)
            result = parse_json_response(resp)
            is_same = result and result.get("same_event")
        except Exception:
            is_same = False
        time.sleep(1)  # 避免连续调用触发限频

        if is_same:
            # 合并为一个事件
            evt_id += 1
            all_topics = []
            all_points = []
            all_companies = []
            for item in group:
                all_topics.extend(item.get("main_topics", []))
                all_points.extend(item.get("key_points", []))
                all_companies.extend(item.get("affected_companies", []))

            # 去重
            unique_topics = list(dict.fromkeys(all_topics))
            unique_points = list(dict.fromkeys(all_points))
            # 合并公司影响：同一公司取最强方向
            company_map = {}
            for comp in all_companies:
                name = comp.get("name", "")
                if not name:
                    continue
                if name not in company_map:
                    company_map[name] = comp
                else:
                    existing = company_map[name]
                    # 利好优先于中性，利空优先于中性
                    if comp.get("impact_direction", "中性") != "中性" and existing.get("impact_direction", "中性") == "中性":
                        company_map[name] = comp
            unique_companies = list(company_map.values())

            # 选最佳标题和摘要
            title = (result or {}).get("event_title") or group[0].get("title", "")
            best_summary = max(group, key=lambda x: len(x.get("summary", ""))).get("summary", "")
            best_impact = max(group, key=lambda x: len(x.get("impact", ""))).get("impact", "")
            max_relevance = max(item.get("ai_relevance_score", 3) for item in group)

            event_clusters.append({
                "cluster_id": f"evt_{evt_id:03d}",
                "event_title": title,
                "event_summary": best_summary,
                "articles": [_article_meta(item) for item in group],
                "combined_topics": unique_topics,
                "combined_key_points": unique_points,
                "combined_impact": best_impact,
                "combined_affected_companies": unique_companies,
                "max_ai_relevance": max_relevance,
            })
            print(f"  [聚类] 合并事件: {title[:40]}... ({len(group)} 条)")
        else:
            # 不合并，各自成独立事件
            for item in group:
                evt_id += 1
                event_clusters.append({
                    "cluster_id": f"evt_{evt_id:03d}",
                    "event_title": item.get("title", ""),
                    "event_summary": item.get("summary", ""),
                    "articles": [_article_meta(item)],
                    "combined_topics": item.get("main_topics", []),
                    "combined_key_points": item.get("key_points", []),
                    "combined_impact": item.get("impact", ""),
                    "combined_affected_companies": item.get("affected_companies", []),
                    "max_ai_relevance": item.get("ai_relevance_score", 3),
                })

    print(f"[聚类-精细合并] 最终 {len(event_clusters)} 个事件")
    return event_clusters


def _article_meta(item: dict) -> dict:
    """提取新闻的元信息用于 cluster 的 articles 列表"""
    return {
        "id": item.get("id", ""),
        "title": item.get("title", ""),
        "source": item.get("source", ""),
        "url": item.get("url", ""),
        "language": item.get("language", ""),
        "publish_date": item.get("publish_date", ""),
    }


def score_credibility(cluster: dict) -> float:
    """可信度：基于来源权重，取多条来源的最大值"""
    if not cluster.get("articles"):
        return DEFAULT_CREDIBILITY

    scores = []
    for art in cluster["articles"]:
        src = art.get("source", "")
        scores.append(SOURCE_CREDIBILITY.get(src, DEFAULT_CREDIBILITY))

    # 多来源取加权平均，偏向最高值
    if len(scores) == 1:
        return scores[0]
    return max(scores) * 0.6 + (sum(scores) / len(scores)) * 0.4


def score_spread(cluster: dict) -> float:
    """传播度：不同来源数 × 2 + 文章总数"""
    sources = set(art.get("source", "") for art in cluster.get("articles", []))
    unique_sources = len(sources)
    total_articles = len(cluster.get("articles", []))
    return min(unique_sources * 2.0 + total_articles, 10.0)


def score_novelty(cluster: dict) -> float:
    """新颖度：基于文章数量和发布时间分布"""
    articles = cluster.get("articles", [])
    if not articles:
        return 0.5

    if len(articles) == 1:
        return 1.0  # 单条报道，新颖度高

    # 多条报道，检查时间跨度
    dates = []
    for art in articles:
        try:
            dates.append(datetime.fromisoformat(art["publish_date"][:19]))
        except (ValueError, TypeError, KeyError):
            pass

    if len(dates) < 2:
        return 0.8

    # 时间跨度越大，说明有后续跟进，新颖度略低
    span_days = abs((max(dates) - min(dates)).total_seconds()) / 86400
    if span_days <= 1:
        return 0.9  # 同一天的多媒体报道，很新鲜
    elif span_days <= 3:
        return 0.7
    else:
        return 0.5


def score_influence_batch(clusters: list[dict]) -> list[float]:
    """
    批量计算影响力分数（调用 LLM 一次）
    返回每个 cluster 的分数列表 (0-10)
    """
    if not clusters:
        return []

    client = get_client()

    items_text = []
    for i, cl in enumerate(clusters):
        title = cl.get("event_title", "")
        points = "; ".join(cl.get("combined_key_points", [])[:3])
        topics = ", ".join(cl.get("combined_topics", []))
        items_text.append(
            f"[{i+1}] {title}\n"
            f"    话题: {topics}\n"
            f"    要点: {points}"
        )

    all_items = "\n".join(items_text)

    prompt = f"""对以下 AI 事件，评估每个事件对 AI 行业的影响力（0-10分）。

评分标准：
- 涉及头部 AI 公司（OpenAI/Google/Meta/Anthropic/阿里/百度等）: +3
- 影响行业基础设施（API、模型标准、开发工具）: +3
- 涉及政策/法规变化: +2
- 技术突破或新产品发布: +2
- 仅影响细分领域: +1

{all_items}

返回 JSON 数组: [{{"index": 序号, "influence": 分数}}]
只返回 JSON 数组。"""

    try:
        resp = call_llm(client, prompt)
        result = parse_json_response(resp)
        if isinstance(result, dict):
            result = result.get("scores", [result])
        if not isinstance(result, list):
            result = []
    except Exception as e:
        print(f"[打分-影响力] LLM 调用失败: {e}")
        result = []

    score_map = {}
    for s in result:
        if isinstance(s, dict):
            idx = s.get("index", 0) - 1
            sc = s.get("influence", 5)
            if 0 <= idx < len(clusters):
                score_map[idx] = float(sc)

    scores = []
    for i in range(len(clusters)):
        scores.append(score_map.get(i, 5.0))

    return scores


def compute_hotspot_scores(clusters: list[dict]) -> list[dict]:
    """计算所有 cluster 的热点分数并排序"""
    print(f"[打分] 开始热点排序...")

    # 批量计算影响力
    influence_scores = score_influence_batch(clusters)

    for i, cl in enumerate(clusters):
        influence = influence_scores[i]
        credibility = score_credibility(cl)
        spread = score_spread(cl)
        novelty = score_novelty(cl)

        cl["influence_score"] = round(influence, 2)
        cl["credibility_score"] = round(credibility, 2)
        cl["spread_score"] = round(spread, 2)
        cl["novelty_score"] = round(novelty, 2)

        cl["hotspot_score"] = round(influence * credibility * spread * novelty, 2)

    # 按热点分数降序排序
    clusters.sort(key=lambda x: x["hotspot_score"], reverse=True)

    print(f"[打分] 完成，热点排名:")
    for i, cl in enumerate(clusters[:10]):
        print(f"  #{i+1} [{cl['hotspot_score']:.1f}] {cl['event_title'][:45]}...")

    return clusters


def cluster_and_rank(structured_news: list[dict], save_path: str = None) -> list[dict]:
    """串联执行聚类 + 排序"""
    print(f"\n[聚类] 开始事件聚类，共 {len(structured_news)} 条结构化数据")

    # 1. 规则预分组
    groups = pre_cluster_by_rules(structured_news)

    # 2. LLM 精细合并
    clusters = refine_clusters_with_llm(groups)

    # 3. 热点打分排序
    clusters = compute_hotspot_scores(clusters)

    # 保存结果
    if save_path is None:
        save_path = f"{DATA_PROCESSED_DIR}/event_clusters.json"

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(clusters, f, ensure_ascii=False, indent=2)

    print(f"[聚类] 结果已保存到 {save_path}")
    return clusters

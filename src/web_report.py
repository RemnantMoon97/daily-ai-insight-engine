"""
Web Report Generator - 双栏日期导航日报看板

布局：左侧侧边栏日期列表 + 右侧完整日报
- 左侧：按天列出每日摘要卡（含 LLM 生成的摘要），最新在上面
- 右侧上方：深度分析（LLM 报告）
- 右侧下方：数据来源、具体新闻、引用证据
"""

import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, date

sys.path.insert(0, ".")
from config import OUTPUT_DIR, DATA_DAILY_DIR, ZHIPU_MODEL
from src.investment_analyzer import generate_investment_analysis, load_investment_analysis, save_investment_analysis
from src.daily_article_generator import generate_daily_article, load_daily_article, save_daily_article
from src.collector.daily_store import cleanup_old_daily

CHART_COLORS = [
    "#00ffc8", "#7c4dff", "#ffb347", "#ff6b6b",
    "#26c6da", "#66bb6a", "#ff7043", "#ab47bc",
    "#29b6f6", "#ffd54f", "#00e676", "#ff4081",
]

# 报告显示阈值
_MAX_DAYS = 7        # 只保留最近 N 天
_MIN_ARTICLES = 20   # 低于此数量的日期只在侧边栏显示摘要

# 侧边栏摘要 prompt 路径
_SIDEBAR_PROMPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "prompt", "侧边栏.txt"
)


def markdown_to_html(text: str) -> str:
    """将基础 Markdown 转换为 HTML（支持表格）"""
    lines = text.split("\n")
    html = []
    in_list = False
    in_table = False
    in_blockquote = False

    def close_list():
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    def close_table():
        nonlocal in_table
        if in_table:
            html.append("</tbody></table>")
            in_table = False

    def close_blockquote():
        nonlocal in_blockquote
        if in_blockquote:
            html.append("</blockquote>")
            in_blockquote = False

    def inline_format(s):
        s = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank">\1</a>', s)
        return s

    for line in lines:
        s = line.strip()

        # 表格行
        if '|' in s and s.startswith('|'):
            close_list()
            close_blockquote()
            cells = [c.strip() for c in s.strip('|').split('|')]
            # 分隔行 |---|---| 跳过
            if all(re.match(r'^[-:]+$', c) for c in cells):
                continue
            if not in_table:
                html.append('<table class="md-table"><thead><tr>')
                for c in cells:
                    html.append(f'<th>{inline_format(c)}</th>')
                html.append('</tr></thead><tbody>')
                in_table = True
            else:
                html.append('<tr>')
                for c in cells:
                    html.append(f'<td>{inline_format(c)}</td>')
                html.append('</tr>')
            continue
        else:
            close_table()

        if s.startswith("> "):
            close_list()
            close_table()
            if not in_blockquote:
                html.append('<blockquote>')
                in_blockquote = True
            html.append(f'<p>{inline_format(s[2:])}</p>')
        elif s.startswith("#### "):
            close_list()
            close_blockquote()
            html.append(f'<h4>{s[5:]}</h4>')
        elif s.startswith("### "):
            close_list()
            close_blockquote()
            html.append(f'<h3>{s[4:]}</h3>')
        elif s.startswith("## "):
            close_list()
            close_blockquote()
            html.append(f'<h2>{s[3:]}</h2>')
        elif s.startswith("# "):
            close_list()
            close_blockquote()
            html.append(f'<h1>{s[2:]}</h1>')
        elif s.startswith("- "):
            close_blockquote()
            if not in_list:
                html.append('<ul>')
                in_list = True
            html.append(f'<li>{inline_format(s[2:])}</li>')
        elif s.startswith("---"):
            close_list()
            close_blockquote()
            html.append('<hr>')
        elif s == "":
            close_list()
            close_blockquote()
        else:
            close_list()
            close_blockquote()
            html.append(f'<p>{inline_format(s)}</p>')

    close_list()
    close_table()
    close_blockquote()
    return "\n".join(html)


# ===== 侧边栏摘要生成 =====


def _load_sidebar_prompt() -> str:
    """加载侧边栏摘要 prompt"""
    with open(_SIDEBAR_PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _extract_hotspots_from_report(report_md: str) -> list[str]:
    """
    从分析报告中提取 A 部分的热点名称

    匹配格式: ### 热点名称：XXX 或 ## A... ### 热点名称：XXX
    """
    if not report_md:
        return []

    hotspots = []
    # 匹配 "### 热点名称：XXX"
    for m in re.finditer(r"###\s*热点名称[：:]\s*(.+)", report_md):
        name = m.group(1).strip()
        if name:
            hotspots.append(name)

    # 也匹配 "### 1. XXX" 或 "### 2. XXX" 格式（B 部分深度总结）
    if not hotspots:
        section_b = re.search(r"##\s*B[\.、]\s*", report_md)
        if section_b:
            b_text = report_md[section_b.start():]
            for m in re.finditer(r"###\s*\d+[\.、]\s*(.+)", b_text):
                name = m.group(1).strip()
                if name:
                    hotspots.append(name)
                if len(hotspots) >= 5:
                    break

    return hotspots[:5]


def _generate_sidebar_summary(
    news_list: list[dict],
    day_str: str,
    report_hotspots: list[str] = None,
) -> dict | None:
    """
    调用 LLM 为某一天的新闻生成侧边栏摘要

    Args:
        news_list: 该天的新闻列表
        day_str: 日期字符串 "YYYY-MM-DD"
        report_hotspots: 右侧分析报告的热点名称列表（用于对齐 Top3）

    Returns:
        摘要 dict 或 None（失败时）
    """
    from src.extractor import get_client, call_llm, parse_json_response

    if not news_list:
        return None

    # 构造输入：标题 + 来源列表
    items_text = []
    for n in news_list:
        items_text.append(
            f"- [{n.get('source', '')}] {n.get('title', '')}"
        )
    news_text = "\n".join(items_text)

    prompt_template = _load_sidebar_prompt()
    prompt = prompt_template + "\n\n## 输入数据\n"
    prompt += f"日期: {day_str}\n"
    prompt += f"新闻数量: {len(news_list)}\n"

    # 如果有右侧分析报告的热点，作为参考热点传入
    if report_hotspots:
        prompt += "\n## 参考热点（右侧日报的主要热点，top3_events 必须从此列表选取）\n"
        for i, h in enumerate(report_hotspots, 1):
            prompt += f"{i}. {h}\n"

    prompt += f"\n新闻列表:\n{news_text}"

    try:
        client = get_client()
        resp = call_llm(client, prompt)
        result = parse_json_response(resp)
        if result and result.get("date"):
            return result
    except Exception as e:
        print(f"  [侧边栏摘要] {day_str} 生成失败: {e}")
    return None


def _generate_sidebar_summaries(all_summaries: list[dict], max_days: int = 30) -> dict:
    """
    为没有摘要的日期批量生成侧边栏摘要

    Args:
        all_summaries: 所有日期摘要列表
        max_days: 最多处理最近多少天

    Returns:
        { "2026-04-16": {summary_dict}, ... }
    """
    sidebar_map = {}
    to_generate = []

    # 检查哪些日期已有摘要
    for s in all_summaries[:max_days]:
        day = s["date"]
        filepath = os.path.join(DATA_DAILY_DIR, f"{day}.json")
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("sidebar_summary"):
                sidebar_map[day] = data["sidebar_summary"]
            else:
                to_generate.append((day, data.get("news", [])))
        except (json.JSONDecodeError, IOError):
            to_generate.append((day, []))

    if not to_generate:
        print(f"[侧边栏摘要] 所有 {len(all_summaries[:max_days])} 天已有摘要")
        return sidebar_map

    print(f"[侧边栏摘要] 需生成 {len(to_generate)} 天的摘要...")
    for day, news in to_generate:
        if not news:
            # 从文件加载
            filepath = os.path.join(DATA_DAILY_DIR, f"{day}.json")
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                news = data.get("news", [])
            except Exception:
                continue

        # 尝试从分析报告中提取热点名称，用于对齐 Top3
        report_hotspots = None
        report_path = os.path.join(OUTPUT_DIR, f"report_{day}.md")
        if os.path.exists(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    report_md = f.read()
                report_hotspots = _extract_hotspots_from_report(report_md)
                if report_hotspots:
                    print(f"  [侧边栏] {day}: 从报告中提取到 {len(report_hotspots)} 个热点")
            except IOError:
                pass

        summary = _generate_sidebar_summary(news, day, report_hotspots=report_hotspots)
        if summary:
            sidebar_map[day] = summary
            # 缓存回 daily 文件
            try:
                filepath = os.path.join(DATA_DAILY_DIR, f"{day}.json")
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["sidebar_summary"] = summary
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            print(f"  [侧边栏] {day}: {summary.get('overall_judgment', '')}")
        time.sleep(1.5)  # 避免 API 限频

    print(f"[侧边栏摘要] 完成，共 {len(sidebar_map)} 天有摘要")
    return sidebar_map


def _load_all_daily_summaries() -> list[dict]:
    """从 data/daily/ 加载所有日期的摘要信息"""
    summaries = []
    if not os.path.exists(DATA_DAILY_DIR):
        return summaries

    for filename in os.listdir(DATA_DAILY_DIR):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(DATA_DAILY_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            day = data.get("date", filename[:-5])
            count = data.get("count", len(data.get("news", [])))
            sources = data.get("sources", {})
            news = data.get("news", [])

            # Top 3 sources
            top_sources = list(sources.keys())[:3]

            # 语言分布
            cn = sum(1 for n in news if n.get("language") == "zh")
            en = count - cn

            summaries.append({
                "date": day,
                "count": count,
                "top_sources": top_sources,
                "sources": sources,
                "cn": cn,
                "en": en,
                "sidebar_summary": data.get("sidebar_summary"),
            })
        except (json.JSONDecodeError, IOError):
            continue

    # 按日期倒序（最新在上面）
    summaries.sort(key=lambda x: x["date"], reverse=True)
    return summaries


def _load_daily_news(target_date: str) -> list[dict]:
    """加载指定日期的原始新闻"""
    filepath = os.path.join(DATA_DAILY_DIR, f"{target_date}.json")
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("news", [])
    except (json.JSONDecodeError, IOError):
        return []


def _load_analysis_report(target_date: str) -> str:
    """尝试加载指定日期的分析报告 markdown"""
    candidates = [
        os.path.join(OUTPUT_DIR, f"report_{target_date}.md"),
        os.path.join(OUTPUT_DIR, "report.md"),
    ]
    for fp in candidates:
        if os.path.exists(fp):
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    content = f.read()
                # 检查文件是否包含该日期的内容
                if target_date in content or fp.endswith("report.md"):
                    return content
            except IOError:
                continue
    return ""


def generate_web_report(
    clusters: list[dict],
    analysis_report: str,
    target_date: str = None,
    output_path: str = None,
) -> str:
    """
    生成双栏日期导航 HTML 日报看板

    Args:
        clusters: 事件聚类数据
        analysis_report: LLM 分析报告（Markdown）
        target_date: 目标日期 "YYYY-MM-DD"，默认今天
        output_path: 输出路径
    """
    if target_date is None:
        target_date = date.today().isoformat()
    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "report.html")

    # 0. 清理超过 _MAX_DAYS 天的旧文件
    cleanup_old_daily(max_days=_MAX_DAYS)

    # 1. 加载所有日期摘要（只保留最近 _MAX_DAYS 天）
    all_summaries = _load_all_daily_summaries()

    # 标记哪些日期有资格显示完整日报（>20条）
    full_report_dates = set()
    sidebar_only_dates = set()
    for s in all_summaries:
        if s["count"] >= _MIN_ARTICLES:
            full_report_dates.add(s["date"])
        else:
            sidebar_only_dates.add(s["date"])

    available_dates = [s["date"] for s in all_summaries]

    # 1.5 为缺少摘要的日期生成侧边栏摘要（LLM）
    sidebar_map = _generate_sidebar_summaries(all_summaries, max_days=_MAX_DAYS)
    # 合并到 summaries 中
    for s in all_summaries:
        if s["date"] in sidebar_map and not s.get("sidebar_summary"):
            s["sidebar_summary"] = sidebar_map[s["date"]]

    # 2. 加载所有日期的新闻数据（用于前端切换）
    all_daily_news = {}
    for s in all_summaries:
        news = _load_daily_news(s["date"])
        all_daily_news[s["date"]] = news

    # 3. 当天聚类数据中的统计
    total_articles = sum(len(cl.get("articles", [])) for cl in clusters)
    source_counter = Counter()
    all_topics = []
    for cl in clusters:
        all_topics.extend(cl.get("combined_topics", []))
        for art in cl.get("articles", []):
            source_counter[art.get("source", "未知")] += 1
    topic_counter = Counter(all_topics)

    stats = {
        "total": total_articles,
        "events": len(clusters),
        "topic_counts": topic_counter.most_common(20),
        "source_counts": source_counter.most_common(),
    }

    # 4. 当天分析报告 HTML
    analysis_html = markdown_to_html(analysis_report)

    # 5. 加载历史分析报告（仅加载有专属报告文件的日期）
    analysis_map = {}
    for s in all_summaries:
        report_path = os.path.join(OUTPUT_DIR, f"report_{s['date']}.md")
        if os.path.exists(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    report_md = f.read()
                analysis_map[s["date"]] = markdown_to_html(report_md)
            except IOError:
                pass
    # 确保当天分析报告包含在内（仅对有资格的日期）
    if analysis_html and target_date not in analysis_map and target_date in full_report_dates:
        analysis_map[target_date] = analysis_html

    # 6. 星期名映射
    weekday_names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]

    # 7. 生成投资情绪分析（仅对有资格显示完整日报的日期）
    #    尝试加载已有结果，否则实时生成
    investment_map = {}
    article_map = {}
    for s in all_summaries:
        day = s["date"]
        if day not in full_report_dates:
            continue
        inv = load_investment_analysis(day)
        if not inv:
            day_news = all_daily_news.get(day, [])
            if day_news:
                inv = generate_investment_analysis(day_news, target_date=day)
                if inv:
                    save_investment_analysis(inv, target_date=day)
                    time.sleep(1.5)
        if inv:
            investment_map[day] = inv

        article_md = load_daily_article(day)
        if not article_md:
            day_news = all_daily_news.get(day, [])
            if day_news:
                article_md = generate_daily_article(day_news, inv, target_date=day)
                if article_md:
                    save_daily_article(article_md, target_date=day)
                    time.sleep(1.5)
        if article_md:
            article_map[day] = markdown_to_html(article_md)

    # 8. 构建 HTML
    html = _HTML_TEMPLATE
    html = html.replace("__ALL_SUMMARIES_JSON__", json.dumps(all_summaries, ensure_ascii=False))
    html = html.replace("__ALL_DAILY_NEWS_JSON__", json.dumps(all_daily_news, ensure_ascii=False))
    html = html.replace("__ANALYSIS_MAP_JSON__", json.dumps(analysis_map, ensure_ascii=False))
    html = html.replace("__INVESTMENT_MAP_JSON__", json.dumps(investment_map, ensure_ascii=False))
    html = html.replace("__ARTICLE_MAP_JSON__", json.dumps(article_map, ensure_ascii=False))
    html = html.replace("__CLUSTERS_JSON__", json.dumps(clusters, ensure_ascii=False))
    html = html.replace("__STATS_JSON__", json.dumps(stats, ensure_ascii=False))
    html = html.replace("__TARGET_DATE__", target_date)
    html = html.replace("__WEEKDAY_MAP__", json.dumps(weekday_names, ensure_ascii=False))
    html = html.replace("__FULL_REPORT_DATES__", json.dumps(list(full_report_dates), ensure_ascii=False))
    html = html.replace("__MIN_ARTICLES_JS__", str(_MIN_ARTICLES))
    html = html.replace("__TIME__", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    html = html.replace("__MODEL__", ZHIPU_MODEL)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[Web] HTML 报告已保存到 {output_path}")
    return output_path


# ======================================================================
# HTML 模板
# ======================================================================
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI 舆情分析日报</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg-primary:#060b18;
  --bg-secondary:#0d1321;
  --bg-card:rgba(255,255,255,0.025);
  --border-card:rgba(255,255,255,0.06);
  --accent:#00ffc8;
  --accent-dim:rgba(0,255,200,0.12);
  --accent-purple:#7c4dff;
  --accent-amber:#ffb347;
  --accent-red:#ff4757;
  --text-primary:#e8edf5;
  --text-secondary:#8892a4;
  --text-muted:#5a6478;
  --font-display:'Syne',sans-serif;
  --font-mono:'IBM Plex Mono',monospace;
  --font-body:'Outfit',sans-serif;
  --radius:14px;
  --radius-sm:8px;
  --sidebar-w:360px;
}
html{scroll-behavior:smooth}
body{
  background:var(--bg-primary);
  color:var(--text-primary);
  font-family:var(--font-body);
  font-weight:400;
  line-height:1.6;
  min-height:100vh;
  -webkit-font-smoothing:antialiased;
  display:flex;
}

/* ===== Background ===== */
body::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse at 15% 30%,rgba(0,255,200,0.04) 0%,transparent 50%),
    radial-gradient(ellipse at 85% 15%,rgba(124,77,255,0.04) 0%,transparent 50%);
}

/* ===== LEFT SIDEBAR ===== */
.sidebar{
  position:fixed;left:0;top:0;bottom:0;
  width:var(--sidebar-w);
  background:var(--bg-secondary);
  border-right:1px solid var(--border-card);
  display:flex;flex-direction:column;
  z-index:10;
}
.sidebar-header{
  padding:24px 20px 16px;
  border-bottom:1px solid var(--border-card);
}
.sidebar-header h1{
  font-family:var(--font-display);font-size:18px;font-weight:800;
  color:#fff;letter-spacing:-0.01em;
}
.sidebar-header .sub{
  font-family:var(--font-mono);font-size:11px;color:var(--text-muted);
  margin-top:4px;letter-spacing:0.05em;
}
.sidebar-list{
  flex:1;overflow-y:auto;padding:8px 0;
}
.sidebar-list::-webkit-scrollbar{width:4px}
.sidebar-list::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.06);border-radius:2px}

.day-card{
  padding:12px 16px;cursor:pointer;
  border-left:3px solid transparent;
  transition:all 0.2s;
}
.day-card:hover{
  background:rgba(255,255,255,0.02);
  border-left-color:rgba(0,255,200,0.3);
}
.day-card.active{
  background:var(--accent-dim);
  border-left-color:var(--accent);
}
.day-card .day-top{display:flex;align-items:center;justify-content:space-between}
.day-card .day-date{
  font-family:var(--font-mono);font-size:13px;font-weight:600;
  color:var(--text-primary);
}
.day-card.active .day-date{color:var(--accent)}
.day-card .day-weekday{
  font-size:11px;color:var(--text-muted);margin-left:4px;
}
.day-card .day-count{
  font-family:var(--font-mono);font-size:14px;font-weight:600;
  color:var(--accent);line-height:1;
}
.day-card .day-judgment{
  font-size:13px;font-weight:600;color:var(--text-primary);
  margin-top:4px;
}
.day-card .day-badges{
  display:flex;gap:4px;margin-top:4px;align-items:center;
}
.day-card .badge-heat{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  padding:2px 6px;border-radius:6px;
}
.badge-heat.high{background:rgba(255,71,87,0.15);color:#ff4757}
.badge-heat.mid{background:rgba(255,179,71,0.15);color:#ffb347}
.badge-heat.low{background:rgba(0,255,200,0.1);color:var(--accent)}
.day-card .badge-risk{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  padding:2px 6px;border-radius:6px;
}
.badge-risk.high{background:rgba(255,71,87,0.15);color:#ff4757}
.badge-risk.mid{background:rgba(255,179,71,0.15);color:#ffb347}
.badge-risk.low{background:rgba(102,187,106,0.12);color:#66bb6a}
.day-card .signal-dot{
  display:inline-block;width:8px;height:8px;border-radius:50%;
  margin-left:auto;
}
.signal-dot.red{background:#ff4757}
.signal-dot.yellow{background:#ffb347}
.signal-dot.green{background:#00ffc8}
.day-card .day-topics{
  display:flex;flex-wrap:wrap;gap:3px;margin-top:4px;
}
.day-card .day-topic-tag{
  font-size:10px;font-weight:500;
  padding:1px 5px;border-radius:4px;
  background:rgba(124,77,255,0.1);color:var(--accent-purple);
}
.day-card .day-events{
  margin-top:4px;
}
.day-card .day-event{
  font-size:11px;color:var(--text-secondary);
  padding-left:8px;position:relative;
  line-height:1.4;
}
.day-card .day-event::before{
  content:'';position:absolute;left:0;top:6px;
  width:4px;height:4px;border-radius:50%;
  background:var(--accent);opacity:0.5;
}
.day-card .day-nav{
  font-size:11px;color:var(--text-muted);
  margin-top:4px;font-style:italic;
}
.day-card .day-sources{
  display:flex;flex-wrap:wrap;gap:3px;margin-top:4px;
}
.day-card .day-src-tag{
  font-family:var(--font-mono);font-size:9px;font-weight:500;
  padding:1px 5px;border-radius:6px;
  background:rgba(255,255,255,0.04);color:var(--text-muted);
}
.day-card .day-mini-badge{
  font-family:var(--font-mono);font-size:9px;font-weight:600;
  padding:1px 5px;border-radius:4px;margin-left:4px;
  background:rgba(255,179,71,0.1);color:#ffb347;
}

/* ===== RIGHT MAIN CONTENT ===== */
.main-content{
  margin-left:var(--sidebar-w);
  flex:1;
  position:relative;z-index:1;
  min-height:100vh;
}
.page-inner{
  max-width:1100px;
  margin:0 auto;
  padding:0 40px 60px;
}

/* ===== HEADER ===== */
.header{
  padding:40px 0 32px;
  border-bottom:1px solid var(--border-card);
  margin-bottom:36px;
}
.header-row{display:flex;align-items:center;justify-content:space-between;gap:16px}
.header h1{
  font-family:var(--font-display);font-weight:800;
  font-size:clamp(24px,3.5vw,36px);
  letter-spacing:-0.02em;color:#fff;
}
.header .date-badge{
  font-family:var(--font-mono);font-size:13px;font-weight:500;
  color:var(--accent);background:var(--accent-dim);
  padding:6px 14px;border-radius:20px;white-space:nowrap;
}

/* ===== Stats Bar ===== */
.stats-grid{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:12px;margin-top:24px;
}
.stat-card{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius-sm);padding:16px 20px;
  transition:border-color 0.3s;
}
.stat-card:hover{border-color:rgba(0,255,200,0.2)}
.stat-card .stat-value{
  font-family:var(--font-mono);font-size:28px;font-weight:600;
  color:var(--accent);line-height:1;
}
.stat-card .stat-label{
  font-size:12px;color:var(--text-secondary);margin-top:4px;font-weight:500;
}

/* ===== Section ===== */
.section{margin-top:40px;animation:fadeUp 0.5s ease-out both}
.section-title{
  font-family:var(--font-display);font-size:20px;font-weight:700;
  color:#fff;margin-bottom:20px;
  display:flex;align-items:center;gap:10px;
}
.section-title::before{
  content:'';display:inline-block;width:3px;height:20px;
  background:var(--accent);border-radius:2px;
}

/* Collapsible sections */
.section-collapsible .section-toggle{cursor:pointer;user-select:none}
.section-collapsible .toggle-icon{
  margin-left:auto;font-size:14px;color:var(--text-muted);
  transition:transform 0.25s;
}
.section-collapsible .section-toggle:hover .toggle-icon{color:var(--accent)}
.section-collapsible.collapsed .toggle-icon{transform:rotate(-90deg)}
.section-collapsible.collapsed .section-body{display:none}
.section-body{transition:all 0.3s ease}

/* ===== Analysis ===== */
.analysis-content{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius);padding:32px 36px;
}
.analysis-content h1{
  font-family:var(--font-display);font-size:24px;font-weight:700;
  color:#fff;margin:28px 0 14px;
}
.analysis-content h1:first-child{margin-top:0}
.analysis-content h2{
  font-family:var(--font-display);font-size:20px;font-weight:700;
  color:#fff;margin:24px 0 12px;padding-bottom:6px;
  border-bottom:1px solid var(--border-card);
}
.analysis-content h3{
  font-family:var(--font-display);font-size:16px;font-weight:600;
  color:var(--text-primary);margin:20px 0 8px;
}
.analysis-content h4{
  font-family:var(--font-display);font-size:14px;font-weight:600;
  color:var(--accent);margin:16px 0 6px;
}
.analysis-content p{color:var(--text-secondary);line-height:1.75;margin-bottom:10px}
.analysis-content strong{color:var(--text-primary);font-weight:600}
.analysis-content ul{margin:8px 0 14px 4px}
.analysis-content li{color:var(--text-secondary);line-height:1.7;margin-bottom:3px;padding-left:6px}
.analysis-content a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(0,255,200,0.3)}
.analysis-content a:hover{border-color:var(--accent)}
.analysis-content hr{border:none;border-top:1px solid var(--border-card);margin:24px 0}
.analysis-content .md-table{
  width:100%;border-collapse:collapse;margin:12px 0 18px;font-size:13px;
}
.analysis-content .md-table th{
  text-align:left;font-family:var(--font-mono);font-size:11px;
  color:var(--text-muted);padding:8px 12px;
  border-bottom:1px solid var(--border-card);
  text-transform:uppercase;letter-spacing:0.06em;
}
.analysis-content .md-table td{
  padding:6px 12px;border-bottom:1px solid rgba(255,255,255,0.03);
  color:var(--text-secondary);
}
.daily-article{
  background:linear-gradient(180deg,rgba(255,255,255,0.03) 0%,rgba(255,255,255,0.015) 100%);
  border:1px solid var(--border-card);
  border-radius:calc(var(--radius) + 4px);
  overflow:hidden;
  box-shadow:0 18px 50px rgba(0,0,0,0.22);
}
.daily-article-header{
  padding:34px 38px 24px;
  border-bottom:1px solid rgba(255,255,255,0.05);
  background:
    linear-gradient(135deg,rgba(0,255,200,0.08) 0%,rgba(124,77,255,0.06) 55%,rgba(255,179,71,0.05) 100%);
}
.daily-article-kicker{
  display:inline-flex;align-items:center;gap:8px;
  font-family:var(--font-mono);font-size:11px;font-weight:600;
  letter-spacing:0.08em;text-transform:uppercase;
  color:var(--accent);margin-bottom:12px;
}
.daily-article-kicker::before{
  content:'';width:22px;height:1px;background:var(--accent);opacity:0.8;
}
.daily-article-title{
  font-family:var(--font-display);font-size:clamp(28px,3.4vw,40px);font-weight:800;
  line-height:1.15;letter-spacing:-0.03em;color:#fff;max-width:14ch;
}
.daily-article-deck{
  margin-top:14px;max-width:820px;
  font-size:16px;line-height:1.85;color:var(--text-secondary);
}
.daily-article-meta{
  display:flex;flex-wrap:wrap;gap:10px;margin-top:18px;
}
.daily-meta-chip{
  font-family:var(--font-mono);font-size:11px;font-weight:500;
  color:var(--text-muted);padding:5px 10px;border-radius:999px;
  border:1px solid rgba(255,255,255,0.06);background:rgba(6,11,24,0.35);
}
.daily-article-body{
  padding:34px 38px 38px;
}
.daily-article-layout{
  display:grid;
  grid-template-columns:minmax(0,1.7fr) minmax(240px,0.72fr);
  gap:30px;
  align-items:start;
}
.daily-article-main{
  min-width:0;
}
.daily-article-side{
  position:sticky;top:24px;
  display:flex;flex-direction:column;gap:14px;
}
.daily-side-card{
  background:rgba(255,255,255,0.02);
  border:1px solid rgba(255,255,255,0.05);
  border-radius:16px;
  padding:16px 16px 14px;
}
.daily-side-label{
  font-family:var(--font-mono);font-size:11px;font-weight:600;
  letter-spacing:0.08em;text-transform:uppercase;
  color:var(--accent);margin-bottom:10px;
}
.daily-side-text{
  font-size:13px;line-height:1.75;color:var(--text-secondary);
}
.daily-chip-list,.daily-bullet-list{
  display:flex;flex-wrap:wrap;gap:8px;
}
.daily-side-chip{
  font-family:var(--font-mono);font-size:10px;font-weight:500;
  padding:4px 8px;border-radius:999px;
  color:var(--text-secondary);
  background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.04);
}
.daily-side-bullet{
  display:block;width:100%;
  font-size:12px;line-height:1.55;color:var(--text-secondary);
  padding-left:12px;position:relative;
}
.daily-side-bullet::before{
  content:'';position:absolute;left:0;top:7px;
  width:4px;height:4px;border-radius:50%;background:var(--accent);
}
.daily-article-body .analysis-content{
  background:transparent;border:none;border-radius:0;padding:0;
}
.daily-article-body .analysis-content h1{
  font-size:28px;margin:0 0 18px;
}
.daily-article-body .analysis-content h2{
  font-size:23px;margin:36px 0 14px;padding-bottom:10px;
  position:relative;
}
.daily-article-body .analysis-content h3{
  font-size:18px;margin:24px 0 10px;
}
.daily-article-body .analysis-content p{
  font-size:15px;line-height:2;margin-bottom:16px;
  color:#cfd7e4;
}
.daily-article-body .analysis-content ul{
  margin:10px 0 16px 2px;
}
.daily-article-body .analysis-content li{
  font-size:14px;line-height:1.8;margin-bottom:6px;
}
.daily-article-body .analysis-content blockquote{
  margin:0 0 24px;
  padding:16px 18px 16px 20px;
  border-left:3px solid var(--accent);
  background:rgba(0,255,200,0.05);
  border-radius:0 14px 14px 0;
}
.daily-article-body .analysis-content blockquote p{
  margin:0;
  font-size:15px;
  line-height:1.8;
  color:#e8edf5;
}
.daily-article-body .analysis-content hr{
  margin:28px 0;
}
.daily-article-body .analysis-content .md-table{
  margin:16px 0 20px;
}
.daily-article-body .analysis-content > *:first-child{
  margin-top:0;
}
.daily-article-body .analysis-content > p:first-of-type::first-letter{
  float:left;
  font-family:var(--font-display);
  font-size:54px;
  line-height:0.85;
  padding-right:8px;
  padding-top:6px;
  color:#fff;
}
.no-analysis{
  text-align:center;padding:48px 20px;color:var(--text-muted);
  font-size:14px;
}

/* ===== Source Table ===== */
.source-table{
  width:100%;border-collapse:collapse;margin-bottom:24px;
  font-size:13px;
}
.source-table th{
  text-align:left;font-family:var(--font-mono);font-size:11px;
  color:var(--text-muted);padding:8px 12px;
  border-bottom:1px solid var(--border-card);
  text-transform:uppercase;letter-spacing:0.06em;
}
.source-table td{
  padding:8px 12px;border-bottom:1px solid rgba(255,255,255,0.02);
  color:var(--text-secondary);
}
.source-table tr:hover td{color:var(--text-primary);background:rgba(255,255,255,0.01)}
.source-table .count{
  font-family:var(--font-mono);font-weight:600;color:var(--accent);
}

/* ===== News Cards ===== */
.news-list{display:flex;flex-direction:column;gap:14px}
.news-item{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius-sm);padding:18px 22px;
  transition:all 0.2s;display:flex;gap:16px;
}
.news-item:hover{
  border-color:rgba(0,255,200,0.15);
  transform:translateX(2px);
}
.news-item .news-main{flex:1;min-width:0}
.news-item .news-source{
  font-family:var(--font-mono);font-size:11px;font-weight:500;
  padding:2px 8px;border-radius:10px;display:inline-block;
  background:rgba(124,77,255,0.1);color:var(--accent-purple);
  margin-bottom:6px;
}
.news-item .news-title{
  font-family:var(--font-display);font-size:15px;font-weight:700;
  color:#fff;line-height:1.35;margin-bottom:6px;
}
.news-item .news-title a{color:inherit;text-decoration:none}
.news-item .news-title a:hover{color:var(--accent)}
.news-item .news-summary{
  font-size:13px;color:var(--text-secondary);line-height:1.5;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
}
.news-item .news-meta{
  font-size:11px;color:var(--text-muted);margin-top:6px;
}
.news-item .news-lang{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  padding:2px 6px;border-radius:8px;text-transform:uppercase;
}
.news-lang.zh{background:rgba(0,255,200,0.08);color:var(--accent)}
.news-lang.en{background:rgba(255,179,71,0.1);color:var(--accent-amber)}

/* ===== Charts ===== */
/* (removed — no longer used) */

/* ===== Footer ===== */
.footer{
  margin-top:48px;padding:20px 0;
  border-top:1px solid var(--border-card);
  text-align:center;
}
.footer p{
  font-family:var(--font-mono);font-size:11px;
  color:var(--text-muted);letter-spacing:0.02em;
}
.footer span{color:var(--accent)}

/* ===== Animations ===== */
@keyframes fadeUp{
  from{opacity:0;transform:translateY(16px)}
  to{opacity:1;transform:translateY(0)}
}

/* ===== Scrollbar ===== */
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:var(--bg-primary)}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.06);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.12)}

/* ===== Investment Sentiment Analysis ===== */
.inv-hero{
  background:linear-gradient(135deg,rgba(0,255,200,0.08) 0%,rgba(124,77,255,0.08) 100%);
  border:1px solid rgba(0,255,200,0.15);border-radius:var(--radius);
  padding:28px 32px;margin-bottom:20px;text-align:center;
}
.inv-hero-title{
  font-family:var(--font-display);font-size:22px;font-weight:800;
  color:#fff;margin-bottom:8px;letter-spacing:-0.01em;
}
.inv-hero-sub{
  font-size:14px;color:var(--text-secondary);line-height:1.5;
}

.inv-overview{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius);padding:24px 28px;margin-bottom:24px;
}
.inv-temp-bar{display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap}
.inv-temp-badge{
  font-family:var(--font-mono);font-size:11px;font-weight:600;
  padding:4px 10px;border-radius:8px;white-space:nowrap;
}
.inv-temp-badge.hot{background:rgba(255,71,87,0.15);color:#ff4757}
.inv-temp-badge.warm{background:rgba(255,179,71,0.15);color:#ffb347}
.inv-temp-badge.cool{background:rgba(0,255,200,0.1);color:var(--accent)}
.inv-hook{
  font-family:var(--font-display);font-size:16px;font-weight:700;
  color:#fff;letter-spacing:-0.01em;
}
.inv-outlook{
  font-size:13px;color:var(--text-secondary);line-height:1.7;
  margin-bottom:12px;padding-left:12px;
  border-left:2px solid var(--accent);
}
.inv-bullets{display:flex;flex-wrap:wrap;gap:8px}
.inv-bullet{
  font-size:12px;font-weight:500;color:var(--text-secondary);
  background:rgba(255,255,255,0.03);padding:4px 10px;
  border-radius:6px;border:1px solid rgba(255,255,255,0.04);
}

/* --- Event Cards --- */
.inv-events{display:flex;flex-direction:column;gap:16px;margin-bottom:28px}
.inv-event-card{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius);padding:22px 26px;
  transition:border-color 0.2s;
}
.inv-event-card:hover{border-color:rgba(0,255,200,0.15)}
.inv-event-head{
  display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap;
}
.inv-event-rank{
  font-family:var(--font-mono);font-size:13px;font-weight:700;
  color:var(--accent);background:var(--accent-dim);
  padding:2px 8px;border-radius:6px;
}
.inv-event-title{
  font-family:var(--font-display);font-size:16px;font-weight:700;
  color:#fff;flex:1;
}
.inv-sent-badge{
  font-family:var(--font-mono);font-size:11px;font-weight:600;
  padding:3px 8px;border-radius:6px;white-space:nowrap;
}
.inv-sent-badge.bull{background:rgba(0,255,200,0.12);color:var(--accent)}
.inv-sent-badge.bear{background:rgba(255,71,87,0.12);color:#ff4757}
.inv-sent-badge.neutral{background:rgba(255,179,71,0.1);color:#ffb347}

.inv-event-body p{font-size:13px;color:var(--text-secondary);line-height:1.7;margin-bottom:8px}
.inv-event-body strong{color:var(--text-primary);font-weight:600}

/* Company Groups */
.inv-company-group{
  display:flex;flex-wrap:wrap;gap:6px;align-items:center;
  margin-bottom:8px;padding:8px 10px;border-radius:8px;
}
.inv-company-group.bull{background:rgba(0,255,200,0.04)}
.inv-company-group.bear{background:rgba(255,71,87,0.04)}
.inv-group-label{
  font-family:var(--font-mono);font-size:10px;font-weight:700;
  text-transform:uppercase;letter-spacing:0.05em;
  padding:2px 6px;border-radius:4px;margin-right:4px;
}
.inv-company-group.bull .inv-group-label{background:rgba(0,255,200,0.12);color:var(--accent)}
.inv-company-group.bear .inv-group-label{background:rgba(255,71,87,0.12);color:#ff4757}
.inv-company-tag{
  font-size:12px;font-weight:500;padding:3px 8px;border-radius:6px;
  display:inline-flex;align-items:center;gap:4px;
}
.inv-company-tag.bull{background:rgba(0,255,200,0.08);color:var(--accent)}
.inv-company-tag.bear{background:rgba(255,71,87,0.08);color:#ff6b6b}
.inv-company-tag small{font-size:10px;color:var(--text-muted);font-weight:400}

/* Peer Readthroughs */
.inv-peer{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.inv-peer-tag{
  font-size:11px;color:var(--text-secondary);background:rgba(255,255,255,0.03);
  padding:4px 8px;border-radius:6px;line-height:1.4;
  border:1px solid rgba(255,255,255,0.04);
}

/* Trade Angles & Risks */
.inv-angles,.inv-risks{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.inv-angle{
  font-size:11px;font-weight:500;color:var(--accent);
  background:rgba(0,255,200,0.06);padding:3px 8px;border-radius:6px;
}
.inv-risk{
  font-size:11px;font-weight:500;color:#ffb347;
  background:rgba(255,179,71,0.08);padding:3px 8px;border-radius:6px;
}

/* Source Evidence */
.inv-sources{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;padding-top:8px;border-top:1px solid var(--border-card)}
.inv-src{font-size:11px;color:var(--text-muted)}
.inv-src a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(0,255,200,0.2)}
.inv-src a:hover{border-color:var(--accent)}

/* --- Signal Board --- */
.inv-signal-board{margin-bottom:28px}
.inv-board-title{
  font-family:var(--font-display);font-size:16px;font-weight:700;
  color:#fff;margin-bottom:14px;
}
.inv-board-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.inv-signal-card{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius-sm);padding:16px 18px;
  transition:border-color 0.2s;
}
.inv-signal-card.bull{border-left:3px solid var(--accent)}
.inv-signal-card.bear{border-left:3px solid #ff4757}
.inv-signal-card.neutral{border-left:3px solid #ffb347}
.inv-sig-company{
  font-family:var(--font-display);font-size:15px;font-weight:700;
  color:#fff;margin-bottom:4px;
}
.inv-sig-view{
  font-family:var(--font-mono);font-size:11px;font-weight:600;
  display:inline-block;padding:2px 8px;border-radius:6px;margin-bottom:6px;
}
.inv-sig-view.bull{background:rgba(0,255,200,0.12);color:var(--accent)}
.inv-sig-view.bear{background:rgba(255,71,87,0.12);color:#ff4757}
.inv-sig-view.neutral{background:rgba(255,179,71,0.1);color:#ffb347}
.inv-sig-summary{font-size:12px;color:var(--text-secondary);margin-bottom:8px;line-height:1.5}
.inv-sig-drivers{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}
.inv-sig-drivers span{
  font-size:10px;padding:2px 6px;border-radius:4px;
}
.inv-sig-drivers.bull span{background:rgba(0,255,200,0.06);color:var(--accent)}
.inv-sig-drivers.bear span{background:rgba(255,71,87,0.06);color:#ff6b6b}

/* --- Themes --- */
.inv-themes{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:16px}
.inv-theme-section{
  background:var(--bg-card);border:1px solid var(--border-card);
  border-radius:var(--radius-sm);padding:18px 20px;
}
.inv-theme-label{
  font-family:var(--font-display);font-size:13px;font-weight:700;
  text-transform:uppercase;letter-spacing:0.04em;margin-bottom:12px;
  padding-bottom:8px;border-bottom:1px solid var(--border-card);
}
.inv-theme-label.opp{color:var(--accent)}
.inv-theme-label.risk{color:#ff4757}
.inv-theme-item{margin-bottom:12px}
.inv-theme-item:last-child{margin-bottom:0}
.inv-theme-item strong{font-size:13px;color:#fff;font-weight:600}
.inv-dir{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  color:var(--accent);background:rgba(0,255,200,0.08);
  padding:2px 6px;border-radius:4px;margin-left:6px;
}
.inv-risk-level{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  padding:2px 6px;border-radius:4px;margin-left:6px;
}
.inv-risk-level.high{background:rgba(255,71,87,0.12);color:#ff4757}
.inv-risk-level.mid{background:rgba(255,179,71,0.1);color:#ffb347}
.inv-risk-level.low{background:rgba(102,187,106,0.1);color:#66bb6a}
.inv-theme-item p{
  font-size:12px;color:var(--text-secondary);line-height:1.6;margin-top:4px;
}

/* --- Expand Button --- */
.inv-expand-bar{text-align:center;margin-top:12px}
.inv-expand-btn{
  font-family:var(--font-mono);font-size:13px;font-weight:600;
  color:var(--accent);background:var(--accent-dim);
  border:1px solid rgba(0,255,200,0.2);border-radius:8px;
  padding:10px 28px;cursor:pointer;transition:all 0.2s;
}
.inv-expand-btn:hover{background:rgba(0,255,200,0.18);border-color:var(--accent)}

/* --- Event Type Badge --- */
.inv-event-type{
  font-family:var(--font-mono);font-size:10px;font-weight:600;
  color:var(--accent-purple);background:rgba(124,77,255,0.1);
  padding:2px 8px;border-radius:4px;margin-bottom:8px;display:inline-block;
}

/* --- Signal Peer Impact --- */
.inv-sig-peer{
  font-size:11px;color:var(--text-muted);margin-top:6px;
  padding-top:6px;border-top:1px solid var(--border-card);line-height:1.4;
}

/* ===== Responsive ===== */
@media(max-width:900px){
  .sidebar{width:280px}
  .main-content{margin-left:280px}
  .page-inner{padding:0 20px 40px}
  .inv-themes{grid-template-columns:1fr}
  .inv-board-grid{grid-template-columns:1fr}
  .daily-article-header,.daily-article-body{padding:24px 22px}
  .daily-article-layout{grid-template-columns:1fr;gap:18px}
  .daily-article-side{position:static}
  .daily-article-title{max-width:none}
}
</style>
</head>
<body>

<!-- ===== LEFT SIDEBAR ===== -->
<aside class="sidebar">
  <div class="sidebar-header">
    <h1>AI 舆情日报</h1>
    <div class="sub">Daily AI Insight</div>
  </div>
  <div class="sidebar-list" id="sidebarList"></div>
</aside>

<!-- ===== RIGHT MAIN ===== -->
<main class="main-content">
  <div class="page-inner" id="pageContent">
    <!-- 动态渲染 -->
  </div>
</main>

<script>
// ===== Embedded Data =====
var allSummaries = __ALL_SUMMARIES_JSON__;
var allDailyNews = __ALL_DAILY_NEWS_JSON__;
var analysisMap = __ANALYSIS_MAP_JSON__;
var investmentMap = __INVESTMENT_MAP_JSON__;
var articleMap = __ARTICLE_MAP_JSON__;
var clusterData = __CLUSTERS_JSON__;
var statsData = __STATS_JSON__;
var targetDate = '__TARGET_DATE__';
var weekdayNames = __WEEKDAY_MAP__;
var fullReportDates = __FULL_REPORT_DATES__;
var MIN_ARTICLES = __MIN_ARTICLES_JS__;

var CHART_COLORS = [
  '#00ffc8','#7c4dff','#ffb347','#ff6b6b','#26c6da',
  '#66bb6a','#ff7043','#ab47bc','#29b6f6','#ffd54f',
  '#00e676','#ff4081','#448aff','#69f0ae','#ffab40','#e040fb'
];

var currentDate = targetDate;

// ===== Render Sidebar =====
function heatClass(level) {
  if (level === '高') return 'high';
  if (level === '中') return 'mid';
  return 'low';
}

function renderSidebar() {
  var list = document.getElementById('sidebarList');
  list.innerHTML = '';
  allSummaries.forEach(function(s) {
    var d = new Date(s.date + 'T00:00:00');
    var wk = weekdayNames[d.getDay()] || '';
    var card = document.createElement('div');
    card.className = 'day-card' + (s.date === currentDate ? ' active' : '');
    card.onclick = function() { switchDate(s.date); };

    var html = '';
    // Line 1: date + weekday + count
    html += '<div class="day-top">';
    html += '<span><span class="day-date">' + s.date.slice(5) + '</span><span class="day-weekday">' + wk + '</span></span>';
    html += '<span class="day-count">' + s.count + '条</span>';
    if (fullReportDates.indexOf(s.date) < 0) {
      html += '<span class="day-mini-badge">摘要</span>';
    }
    html += '</div>';

    var sb = s.sidebar_summary;
    if (sb) {
      // Overall judgment
      if (sb.overall_judgment) {
        html += '<div class="day-judgment">' + sb.overall_judgment + '</div>';
      }
      // Badges: heat + risk + signal dot
      html += '<div class="day-badges">';
      if (sb.heat_level) {
        html += '<span class="badge-heat ' + heatClass(sb.heat_level) + '">热度' + sb.heat_level + '</span>';
      }
      if (sb.risk_level) {
        html += '<span class="badge-risk ' + heatClass(sb.risk_level) + '">风险' + sb.risk_level + '</span>';
      }
      if (sb.signal_color) {
        html += '<span class="signal-dot ' + sb.signal_color + '"></span>';
      }
      html += '</div>';
      // Topics
      if (sb.topics && sb.topics.length > 0) {
        html += '<div class="day-topics">';
        sb.topics.slice(0, 3).forEach(function(t) {
          html += '<span class="day-topic-tag">' + t + '</span>';
        });
        html += '</div>';
      }
      // Top3 events
      if (sb.top3_events && sb.top3_events.length > 0) {
        html += '<div class="day-events">';
        sb.top3_events.forEach(function(e) {
          html += '<div class="day-event">' + e + '</div>';
        });
        html += '</div>';
      }
      // Nav text
      if (sb.nav_text) {
        html += '<div class="day-nav">' + sb.nav_text + '</div>';
      }
    } else {
      // Fallback: show sources
      var srcHtml = (s.top_sources || []).map(function(src) {
        return '<span class="day-src-tag">' + src + '</span>';
      }).join('');
      html += '<div class="day-sources">' + srcHtml + '</div>';
    }

    card.innerHTML = html;
    list.appendChild(card);
  });
}

// ===== Switch Date =====
function switchDate(dateStr) {
  currentDate = dateStr;
  renderSidebar();
  renderContent();
  window.scrollTo(0, 0);
}

// ===== Get Weekday =====
function getWeekday(dateStr) {
  var d = new Date(dateStr + 'T00:00:00');
  return weekdayNames[d.getDay()] || '';
}

function extractPlainLead(html) {
  if (!html) return '';
  var match = html.match(/<p>(.*?)<\/p>/i);
  if (!match) return '';
  var text = match[1]
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return text.slice(0, 120);
}

function buildDailyArticle(analysis, dateStr, articleCount, sourceCount, inv) {
  var lead = extractPlainLead(analysis);
  var articleHtml = '';
  articleHtml += '<article class="daily-article">';
  articleHtml += '<div class="daily-article-header">';
  articleHtml += '<div class="daily-article-kicker">Daily Brief</div>';
  articleHtml += '<div class="daily-article-title">AI 舆情日报正文</div>';
  if (lead) {
    articleHtml += '<div class="daily-article-deck">' + lead + '</div>';
  }
  articleHtml += '<div class="daily-article-meta">';
  articleHtml += '<span class="daily-meta-chip">' + dateStr + ' ' + getWeekday(dateStr) + '</span>';
  articleHtml += '<span class="daily-meta-chip">' + articleCount + ' 条新闻</span>';
  articleHtml += '<span class="daily-meta-chip">' + sourceCount + ' 个来源</span>';
  articleHtml += '</div></div>';
  articleHtml += '<div class="daily-article-body"><div class="daily-article-layout">';
  articleHtml += '<div class="daily-article-main"><div class="analysis-content">' + analysis + '</div></div>';
  articleHtml += '<aside class="daily-article-side">';
  if (inv && inv.daily_outlook) {
    articleHtml += '<div class="daily-side-card"><div class="daily-side-label">市场主线</div><div class="daily-side-text">' + inv.daily_outlook + '</div></div>';
  }
  if (inv && inv.homepage_modules && inv.homepage_modules.fast_bullets && inv.homepage_modules.fast_bullets.length) {
    articleHtml += '<div class="daily-side-card"><div class="daily-side-label">快速抓手</div><div class="daily-bullet-list">';
    inv.homepage_modules.fast_bullets.slice(0, 4).forEach(function(b) {
      articleHtml += '<span class="daily-side-bullet">' + b + '</span>';
    });
    articleHtml += '</div></div>';
  }
  if (inv && inv.homepage_modules && inv.homepage_modules.watchlist_tags && inv.homepage_modules.watchlist_tags.length) {
    articleHtml += '<div class="daily-side-card"><div class="daily-side-label">观察对象</div><div class="daily-chip-list">';
    inv.homepage_modules.watchlist_tags.slice(0, 8).forEach(function(tag) {
      articleHtml += '<span class="daily-side-chip">' + tag + '</span>';
    });
    articleHtml += '</div></div>';
  }
  articleHtml += '</aside></div></div>';
  articleHtml += '</article>';
  return articleHtml;
}

// ===== Render Main Content =====
function renderContent() {
  var container = document.getElementById('pageContent');
  var news = allDailyNews[currentDate] || [];
  var analysis = analysisMap[currentDate] || '';
  var articleContent = articleMap[currentDate] || '';
  var hasClusterData = false;

  // Check if cluster data is for this date
  var clForDate = [];
  if (currentDate === targetDate) {
    clForDate = clusterData;
    hasClusterData = true;
  }

  // Stats
  var srcMap = {};
  var cnCount = 0;
  news.forEach(function(n) {
    var src = n.source || '未知';
    srcMap[src] = (srcMap[src] || 0) + 1;
    if (n.language === 'zh') cnCount++;
  });
  var enCount = news.length - cnCount;
  var srcList = Object.keys(srcMap).map(function(k) {
    return [k, srcMap[k]];
  }).sort(function(a, b) { return b[1] - a[1]; });

  // Topic counts
  var topicMap = {};
  clForDate.forEach(function(cl) {
    (cl.combined_topics || []).forEach(function(t) {
      topicMap[t] = (topicMap[t] || 0) + 1;
    });
  });
  var topicList = Object.keys(topicMap).map(function(k) {
    return [k, topicMap[k]];
  }).sort(function(a, b) { return b[1] - a[1]; });

  // Build HTML
  var html = '';

  // Header
  html += '<header class="header">';
  html += '<div class="header-row">';
  html += '<h1>AI 舆情分析日报</h1>';
  html += '<div class="date-badge">' + currentDate + ' ' + getWeekday(currentDate) + '</div>';
  html += '</div>';
  html += '<div class="stats-grid">';
  html += '<div class="stat-card"><div class="stat-value">' + news.length + '</div><div class="stat-label">新闻总数</div></div>';
  html += '<div class="stat-card"><div class="stat-value">' + cnCount + '</div><div class="stat-label">中文</div></div>';
  html += '<div class="stat-card"><div class="stat-value">' + enCount + '</div><div class="stat-label">英文</div></div>';
  html += '<div class="stat-card"><div class="stat-value">' + Object.keys(srcMap).length + '</div><div class="stat-label">来源</div></div>';
  if (hasClusterData) {
    html += '<div class="stat-card"><div class="stat-value">' + clForDate.length + '</div><div class="stat-label">事件</div></div>';
  }
  html += '</div></header>';

  // Check if this date qualifies for full report
  var isFullReport = fullReportDates.indexOf(currentDate) >= 0;

  if (!isFullReport) {
    // Sidebar-only: show minimal view
    html += '<section class="section">';
    html += '<h2 class="section-title">数据摘要</h2>';
    html += '<div class="analysis-content no-analysis">';
    html += '<p>该日期新闻量不足 ' + MIN_ARTICLES + ' 条（当前 ' + news.length + ' 条），仅显示侧边栏摘要</p>';
    if (news.length > 0) {
      html += '<div class="news-list" style="margin-top:16px">';
      news.forEach(function(n, i) {
        var lang = n.language || 'en';
        var langClass = lang === 'zh' ? 'zh' : 'en';
        var langLabel = lang === 'zh' ? '中文' : 'EN';
        html += '<div class="news-item" style="animation-delay:' + (i * 0.03) + 's">';
        html += '<div class="news-main">';
        html += '<span class="news-source">' + (n.source || '') + '</span> ';
        html += '<span class="news-lang ' + langClass + '">' + langLabel + '</span>';
        html += '<div class="news-title">';
        if (n.url) {
          html += '<a href="' + n.url + '" target="_blank">' + (n.title || '无标题') + '</a>';
        } else {
          html += (n.title || '无标题');
        }
        html += '</div></div></div>';
      });
      html += '</div>';
    }
    html += '</div></section>';
  } else {
  // === Full report starts ===

  // Helper: collapsible section
  function collapsible(id, title, bodyHtml) {
    var s = '';
    s += '<section class="section section-collapsible">';
    s += '<h2 class="section-title section-toggle" data-target="' + id + '" onclick="toggleSection(\'' + id + '\')">';
    s += title + '<span class="toggle-icon" id="icon-' + id + '">▼</span></h2>';
    s += '<div class="section-body" id="' + id + '">' + bodyHtml + '</div>';
    s += '</section>';
    return s;
  }

  // --- Section 1: Investment Sentiment Analysis (top) ---
  var inv = investmentMap[currentDate];
  if (inv) {
    var invBody = '';
    // Hero banner
    if (inv.homepage_modules && inv.homepage_modules.hero_banner) {
      var hero = inv.homepage_modules.hero_banner;
      invBody += '<div class="inv-hero">';
      invBody += '<div class="inv-hero-title">' + (hero.title || '') + '</div>';
      invBody += '<div class="inv-hero-sub">' + (hero.subtitle || '') + '</div>';
      invBody += '</div>';
    }
    // Market temperature + core hook
    invBody += '<div class="inv-overview">';
    invBody += '<div class="inv-temp-bar">';
    invBody += '<span class="inv-temp-badge ' + (inv.market_temperature === '高' ? 'hot' : (inv.market_temperature === '中' ? 'warm' : 'cool')) + '">市场温度 ' + (inv.market_temperature || '-') + '</span>';
    invBody += '<span class="inv-hook">' + (inv.core_hook || '') + '</span>';
    invBody += '</div>';
    if (inv.daily_outlook) {
      invBody += '<p class="inv-outlook">' + inv.daily_outlook + '</p>';
    }
    if (inv.homepage_modules && inv.homepage_modules.fast_bullets) {
      invBody += '<div class="inv-bullets">';
      inv.homepage_modules.fast_bullets.forEach(function(b) {
        invBody += '<span class="inv-bullet">▸ ' + b + '</span>';
      });
      invBody += '</div>';
    }
    invBody += '</div>';
    // Theme opportunities & risks
    invBody += '<div class="inv-themes">';
    if (inv.theme_opportunities && inv.theme_opportunities.length > 0) {
      invBody += '<div class="inv-theme-section"><div class="inv-theme-label opp">机会方向</div>';
      inv.theme_opportunities.forEach(function(t) {
        invBody += '<div class="inv-theme-item"><strong>' + t.theme + '</strong> <span class="inv-dir">' + t.direction + '</span><p>' + (t.reason || '') + '</p></div>';
      });
      invBody += '</div>';
    }
    if (inv.theme_risks && inv.theme_risks.length > 0) {
      invBody += '<div class="inv-theme-section"><div class="inv-theme-label risk">风险提示</div>';
      inv.theme_risks.forEach(function(t) {
        var rl = t.risk_level === '高' ? 'high' : (t.risk_level === '中' ? 'mid' : 'low');
        invBody += '<div class="inv-theme-item"><strong>' + t.theme + '</strong> <span class="inv-risk-level ' + rl + '">' + (t.risk_level || '') + '</span><p>' + (t.reason || '') + '</p></div>';
      });
      invBody += '</div>';
    }
    invBody += '</div>';
    html += collapsible('sec-invest', '投资情绪分析', invBody);
  }

  // --- Section 2: Company Signal Board ---
  if (inv && inv.company_signal_board && inv.company_signal_board.length > 0) {
    var sigBody = '<div class="inv-signal-board"><div class="inv-board-grid">';
    inv.company_signal_board.forEach(function(c) {
      var viewClass = (c.overall_view || '').indexOf('利') >= 0 && (c.overall_view || '').indexOf('利空') < 0 ? 'bull' : ((c.overall_view || '').indexOf('利空') >= 0 ? 'bear' : 'neutral');
      sigBody += '<div class="inv-signal-card ' + viewClass + '">';
      sigBody += '<div class="inv-sig-company">' + (c.company || '') + '</div>';
      sigBody += '<div class="inv-sig-view ' + viewClass + '">' + (c.overall_view || '') + '</div>';
      sigBody += '<div class="inv-sig-summary">' + (c.signal_summary || '') + '</div>';
      if (c.bullish_drivers && c.bullish_drivers.length > 0) {
        sigBody += '<div class="inv-sig-drivers bull">';
        c.bullish_drivers.forEach(function(d) { sigBody += '<span>+' + d + '</span>'; });
        sigBody += '</div>';
      }
      if (c.bearish_drivers && c.bearish_drivers.length > 0) {
        sigBody += '<div class="inv-sig-drivers bear">';
        c.bearish_drivers.forEach(function(d) { sigBody += '<span>-' + d + '</span>'; });
        sigBody += '</div>';
      }
      if (c.peer_impact) sigBody += '<div class="inv-sig-peer">' + c.peer_impact + '</div>';
      sigBody += '</div>';
    });
    sigBody += '</div></div>';
    html += collapsible('sec-signal', '公司信号面板', sigBody);
  }

  // --- Section 3: Top Events (show 3, expandable) ---
  if (inv && inv.top_events && inv.top_events.length > 0) {
    var evts = inv.top_events;
    var showCount = 3;
    var evtBody = '<div class="inv-events" id="invEventsList">';
    evts.forEach(function(evt, idx) {
      var sentClass = (evt.sentiment_level || '').indexOf('利空') >= 0 ? 'bear' : (evt.sentiment_level || '').indexOf('利好') >= 0 ? 'bull' : 'neutral';
      var hidden = idx >= showCount ? ' style="display:none"' : '';
      evtBody += '<div class="inv-event-card inv-event-expandable" data-idx="' + idx + '"' + hidden + '>';
      evtBody += '<div class="inv-event-head">';
      evtBody += '<span class="inv-event-rank">#' + evt.rank + '</span>';
      evtBody += '<span class="inv-event-title">' + (evt.headline || '') + '</span>';
      evtBody += '<span class="inv-sent-badge ' + sentClass + '">' + (evt.sentiment_level || '') + '</span>';
      evtBody += '</div>';
      evtBody += '<div class="inv-event-body">';
      if (evt.event_type) evtBody += '<span class="inv-event-type">' + evt.event_type + '</span>';
      if (evt.fact_summary) evtBody += '<p><strong>事件：</strong>' + evt.fact_summary + '</p>';
      if (evt.market_why) evtBody += '<p><strong>市场关注：</strong>' + evt.market_why + '</p>';
      if (evt.direct_beneficiaries && evt.direct_beneficiaries.length > 0) {
        evtBody += '<div class="inv-company-group bull"><span class="inv-group-label">利好</span>';
        evt.direct_beneficiaries.forEach(function(b) {
          evtBody += '<span class="inv-company-tag bull">' + b.company + ' <small>' + (b.reason || '') + '</small></span>';
        });
        evtBody += '</div>';
      }
      if (evt.direct_pressure && evt.direct_pressure.length > 0) {
        evtBody += '<div class="inv-company-group bear"><span class="inv-group-label">利空</span>';
        evt.direct_pressure.forEach(function(p) {
          evtBody += '<span class="inv-company-tag bear">' + p.company + ' <small>' + (p.reason || '') + '</small></span>';
        });
        evtBody += '</div>';
      }
      if (evt.peer_readthroughs && evt.peer_readthroughs.length > 0) {
        evtBody += '<div class="inv-peer">';
        evt.peer_readthroughs.forEach(function(p) {
          var dir = p.direction === '利好' ? '▲' : (p.direction === '利空' ? '▼' : '◆');
          evtBody += '<span class="inv-peer-tag">' + dir + ' ' + p.peer_group + ': ' + (p.logic || '') + '</span>';
        });
        evtBody += '</div>';
      }
      if (evt.trade_angles && evt.trade_angles.length > 0) {
        evtBody += '<div class="inv-angles">';
        evt.trade_angles.forEach(function(a) { evtBody += '<span class="inv-angle">💰 ' + a + '</span>'; });
        evtBody += '</div>';
      }
      if (evt.risk_flags && evt.risk_flags.length > 0) {
        evtBody += '<div class="inv-risks">';
        evt.risk_flags.forEach(function(r) { evtBody += '<span class="inv-risk">⚠ ' + r + '</span>'; });
        evtBody += '</div>';
      }
      if (evt.source_evidence && evt.source_evidence.length > 0) {
        evtBody += '<div class="inv-sources">';
        evt.source_evidence.forEach(function(e) {
          evtBody += '<span class="inv-src">[' + (e.source || '') + '] ';
          if (e.url) evtBody += '<a href="' + e.url + '" target="_blank">' + (e.title || '') + '</a>';
          else evtBody += (e.title || '');
          evtBody += '</span>';
        });
        evtBody += '</div>';
      }
      evtBody += '</div></div>';
    });
    evtBody += '</div>';
    if (evts.length > showCount) {
      evtBody += '<div class="inv-expand-bar"><button class="inv-expand-btn" onclick="toggleInvEvents()">展开全部 ' + evts.length + ' 个热点 ▼</button></div>';
    }
    html += collapsible('sec-hotspots', '今日主要热点', evtBody);
  }

  // --- Section 4: Data Sources & News Evidence ---
  var dataBody = '';
  // Source table
  dataBody += '<table class="source-table"><thead><tr><th>来源</th><th>文章数</th><th>占比</th></tr></thead><tbody>';
  srcList.forEach(function(s) {
    var pct = news.length > 0 ? (s[1] / news.length * 100).toFixed(0) : 0;
    dataBody += '<tr><td>' + s[0] + '</td><td class="count">' + s[1] + '</td><td>' + pct + '%</td></tr>';
  });
  dataBody += '</tbody></table>';
  // News list (show 3, expandable)
  var newsShowCount = 3;
  dataBody += '<div class="news-list" id="newsList">';
  news.forEach(function(n, i) {
    var lang = n.language || 'en';
    var langClass = lang === 'zh' ? 'zh' : 'en';
    var langLabel = lang === 'zh' ? '中文' : 'EN';
    var summary = n.summary || '';
    if (summary.length > 120) summary = summary.slice(0, 120) + '...';
    var hidden = i >= newsShowCount ? ' style="display:none"' : '';
    dataBody += '<div class="news-item news-expandable" data-news-idx="' + i + '"' + hidden + '>';
    dataBody += '<div class="news-main">';
    dataBody += '<span class="news-source">' + (n.source || '') + '</span> ';
    dataBody += '<span class="news-lang ' + langClass + '">' + langLabel + '</span>';
    dataBody += '<div class="news-title">';
    if (n.url) {
      dataBody += '<a href="' + n.url + '" target="_blank">' + (n.title || '无标题') + '</a>';
    } else {
      dataBody += (n.title || '无标题');
    }
    dataBody += '</div>';
    if (summary) dataBody += '<div class="news-summary">' + summary + '</div>';
    dataBody += '<div class="news-meta">' + (n.publish_date || '').slice(0, 16) + '</div>';
    dataBody += '</div></div>';
  });
  dataBody += '</div>';
  if (news.length > newsShowCount) {
    dataBody += '<div class="inv-expand-bar"><button class="inv-expand-btn" onclick="toggleNewsList()">展开全部 ' + news.length + ' 条新闻 ▼</button></div>';
  }
  html += collapsible('sec-datasource', '数据来源与新闻证据', dataBody);

  // --- Section 5: Event Overview (LLM report) ---
  if (articleContent) {
    html += collapsible('sec-overview', '今日日报', buildDailyArticle(articleContent, currentDate, news.length, Object.keys(srcMap).length, inv));
  } else {
    var noReport = '<div class="analysis-content no-analysis">';
    noReport += '<p>' + currentDate + ' 暂未生成日报正文</p>';
    noReport += '<p style="margin-top:8px;font-size:12px;">运行 <code style="color:var(--accent);background:var(--accent-dim);padding:2px 6px;border-radius:4px;">python main.py --date ' + currentDate + '</code> 重新生成</p>';
    noReport += '</div>';
    html += collapsible('sec-overview', '今日日报', noReport);
  }

  } // end else (isFullReport)

  // Footer
  html += '<div class="footer">';
  html += '<p><span>AI 舆情分析日报系统</span> &middot; 生成时间: __TIME__ &middot; 模型: __MODEL__</p>';
  html += '</div>';

  container.innerHTML = html;
}

// ===== Toggle Collapsible Sections =====
function toggleSection(id) {
  var body = document.getElementById(id);
  var icon = document.getElementById('icon-' + id);
  var section = body.parentElement;
  if (section.classList.contains('collapsed')) {
    section.classList.remove('collapsed');
  } else {
    section.classList.add('collapsed');
  }
}

// ===== Toggle Expand Events =====
var invEventsExpanded = false;
function toggleInvEvents() {
  invEventsExpanded = !invEventsExpanded;
  var cards = document.querySelectorAll('.inv-event-expandable');
  cards.forEach(function(c) {
    if (parseInt(c.getAttribute('data-idx')) >= 3) {
      c.style.display = invEventsExpanded ? '' : 'none';
    }
  });
  var btn = document.querySelector('#sec-hotspots .inv-expand-btn');
  if (btn) {
    btn.textContent = invEventsExpanded ? '收起热点 ▲' : ('展开全部 ' + cards.length + ' 个热点 ▼');
  }
}

// ===== Toggle Expand News =====
var newsExpanded = false;
function toggleNewsList() {
  newsExpanded = !newsExpanded;
  var items = document.querySelectorAll('.news-expandable');
  items.forEach(function(item) {
    if (parseInt(item.getAttribute('data-news-idx')) >= 3) {
      item.style.display = newsExpanded ? '' : 'none';
    }
  });
  var btn = document.querySelector('#sec-datasource .inv-expand-btn');
  if (btn) {
    btn.textContent = newsExpanded ? '收起新闻 ▲' : ('展开全部 ' + items.length + ' 条新闻 ▼');
  }
}

// ===== Init =====
renderSidebar();
renderContent();
</script>
</body>
</html>"""

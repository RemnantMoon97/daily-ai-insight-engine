"""
Web Report Generator - 生成精美的 HTML 可视化日报

设计风格：Dark Intelligence Briefing
- 深色背景 + 电光青色主色调
- 玻璃拟态卡片
- Chart.js 交互式图表
- 入场动画 + 悬停效果
"""

import json
import re
import os
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, ".")
from config import OUTPUT_DIR, ZHIPU_MODEL

# ---- 话题标签配色方案 ----
TOPIC_PALETTE = [
    "#00ffc8", "#00bcd4", "#7c4dff", "#ffb347",
    "#ff6b6b", "#26c6da", "#66bb6a", "#ff7043",
    "#ab47bc", "#29b6f6", "#ffd54f", "#ef5350",
    "#00e676", "#ff4081", "#448aff", "#69f0ae",
]

CHART_COLORS = [
    "#00ffc8", "#7c4dff", "#ffb347", "#ff6b6b",
    "#26c6da", "#66bb6a", "#ff7043", "#ab47bc",
    "#29b6f6", "#ffd54f", "#00e676", "#ff4081",
]


def markdown_to_html(text: str) -> str:
    """将基础 Markdown 转换为 HTML"""
    lines = text.split("\n")
    html = []
    in_list = False

    for line in lines:
        s = line.strip()
        if s.startswith("#### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f'<h4>{s[5:]}</h4>')
        elif s.startswith("### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f'<h3>{s[4:]}</h3>')
        elif s.startswith("## "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f'<h2>{s[3:]}</h2>')
        elif s.startswith("# "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f'<h1>{s[2:]}</h1>')
        elif s.startswith("- "):
            if not in_list:
                html.append('<ul>')
                in_list = True
            content = s[2:]
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content)
            content = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank">\1</a>', content)
            html.append(f'<li>{content}</li>')
        elif s.startswith("---"):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append('<hr>')
        elif s == "":
            if in_list:
                html.append("</ul>")
                in_list = False
        else:
            if in_list:
                html.append("</ul>")
                in_list = False
            content = s
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', content)
            content = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2" target="_blank">\1</a>', content)
            html.append(f'<p>{content}</p>')

    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def generate_web_report(
    clusters: list[dict],
    analysis_report: str,
    output_path: str = None,
) -> str:
    """生成完整的 HTML 可视化报告（基于事件 cluster）"""

    if output_path is None:
        output_path = os.path.join(OUTPUT_DIR, "report.html")

    # ---- 统计计算 ----
    total_articles = sum(len(cl.get("articles", [])) for cl in clusters)
    cn_count = sum(
        1 for cl in clusters for art in cl.get("articles", [])
        if art.get("language") == "zh"
    )
    en_count = total_articles - cn_count

    all_topics = []
    source_counter = Counter()
    for cl in clusters:
        all_topics.extend(cl.get("combined_topics", []))
        for art in cl.get("articles", []):
            source_counter[art.get("source", "未知")] += 1
    topic_counter = Counter(all_topics)
    unique_topics = len(topic_counter)

    stats = {
        "total": total_articles,
        "events": len(clusters),
        "cn": cn_count,
        "en": en_count,
        "topics": unique_topics,
        "sources": len(source_counter),
        "topic_counts": topic_counter.most_common(20),
        "source_counts": source_counter.most_common(),
    }

    analysis_html = markdown_to_html(analysis_report)
    today_str = datetime.now().strftime("%Y年%m月%d日")
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 构建 HTML ----
    html = _HTML_TEMPLATE
    html = html.replace("__NEWS_JSON__", json.dumps(clusters, ensure_ascii=False))
    html = html.replace("__STATS_JSON__", json.dumps(stats, ensure_ascii=False))
    html = html.replace("__ANALYSIS_HTML__", analysis_html)
    html = html.replace("__DATE__", today_str)
    html = html.replace("__TIME__", time_str)
    html = html.replace("__MODEL__", ZHIPU_MODEL)
    html = html.replace("__STATS_TOTAL__", str(total_articles))
    html = html.replace("__STATS_CN__", str(cn_count))
    html = html.replace("__STATS_EN__", str(en_count))
    html = html.replace("__STATS_TOPICS__", str(unique_topics))
    html = html.replace("__STATS_SOURCES__", str(len(source_counter)))

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
<title>AI 舆情分析日报 - __DATE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
/* ===== Reset & Variables ===== */
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
}

/* ===== Background atmosphere ===== */
body::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse at 15% 30%,rgba(0,255,200,0.04) 0%,transparent 50%),
    radial-gradient(ellipse at 85% 15%,rgba(124,77,255,0.04) 0%,transparent 50%),
    radial-gradient(ellipse at 50% 80%,rgba(0,188,212,0.03) 0%,transparent 50%);
}
.page-wrapper{position:relative;z-index:1;max-width:1280px;margin:0 auto;padding:0 24px 60px}

/* ===== Header ===== */
.header{
  padding:48px 0 40px;
  border-bottom:1px solid var(--border-card);
  margin-bottom:40px;
  position:relative;
}
.header::after{
  content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent 0%,var(--accent) 30%,var(--accent-purple) 70%,transparent 100%);
  opacity:0.6;
}
.header-top{display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:16px}
.header h1{
  font-family:var(--font-display);font-weight:800;font-size:clamp(28px,4vw,42px);
  letter-spacing:-0.02em;color:#fff;
}
.header .subtitle{
  font-family:var(--font-mono);font-size:13px;color:var(--text-muted);
  letter-spacing:0.08em;text-transform:uppercase;margin-top:6px;
}
.header .date-badge{
  font-family:var(--font-mono);font-size:13px;font-weight:500;
  color:var(--accent);background:var(--accent-dim);
  padding:6px 14px;border-radius:20px;letter-spacing:0.02em;
  white-space:nowrap;
}

/* ===== Stats Bar ===== */
.stats-grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:16px;margin-top:28px;
}
.stat-card{
  background:var(--bg-card);
  border:1px solid var(--border-card);
  border-radius:var(--radius);
  padding:20px 24px;
  position:relative;overflow:hidden;
  transition:border-color 0.3s;
}
.stat-card:hover{border-color:rgba(0,255,200,0.2)}
.stat-card .stat-value{
  font-family:var(--font-mono);font-size:32px;font-weight:600;
  color:var(--accent);line-height:1;
}
.stat-card .stat-label{
  font-size:13px;color:var(--text-secondary);margin-top:6px;
  font-weight:500;
}
.stat-card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,var(--accent),transparent);
  opacity:0;
  transition:opacity 0.3s;
}
.stat-card:hover::before{opacity:1}

/* ===== Section Layout ===== */
.section{
  margin-top:48px;
  animation:fadeUp 0.6s ease-out both;
}
.section-title{
  font-family:var(--font-display);font-size:22px;font-weight:700;
  color:#fff;margin-bottom:24px;
  display:flex;align-items:center;gap:12px;
}
.section-title::before{
  content:'';display:inline-block;width:4px;height:22px;
  background:var(--accent);border-radius:2px;
}

/* ===== Charts Grid ===== */
.charts-grid{
  display:grid;
  grid-template-columns:1.4fr 1fr;
  gap:20px;
}
@media(max-width:800px){
  .charts-grid{grid-template-columns:1fr}
}
.chart-card{
  background:var(--bg-card);
  border:1px solid var(--border-card);
  border-radius:var(--radius);
  padding:24px;
  position:relative;
}
.chart-card h3{
  font-family:var(--font-display);font-size:15px;font-weight:600;
  color:var(--text-secondary);margin-bottom:16px;
  text-transform:uppercase;letter-spacing:0.06em;
}

/* ===== Topic Filter Bar ===== */
.filter-bar{
  display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;
}
.filter-btn{
  font-family:var(--font-body);font-size:12px;font-weight:500;
  padding:6px 14px;border-radius:20px;border:1px solid var(--border-card);
  background:transparent;color:var(--text-secondary);
  cursor:pointer;transition:all 0.2s;
}
.filter-btn:hover{border-color:var(--accent);color:var(--accent)}
.filter-btn.active{
  background:var(--accent-dim);border-color:var(--accent);
  color:var(--accent);
}

/* ===== News Cards ===== */
.news-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(360px,1fr));
  gap:20px;
}
@media(max-width:500px){
  .news-grid{grid-template-columns:1fr}
}
.news-card{
  background:var(--bg-card);
  border:1px solid var(--border-card);
  border-radius:var(--radius);
  padding:24px;
  transition:all 0.3s ease;
  display:flex;flex-direction:column;
  animation:fadeUp 0.5s ease-out both;
}
.news-card:hover{
  border-color:rgba(0,255,200,0.15);
  transform:translateY(-2px);
  box-shadow:0 8px 32px rgba(0,255,200,0.06);
}
.news-card .card-meta{
  display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  margin-bottom:10px;
}
.news-card .source-badge{
  font-family:var(--font-mono);font-size:11px;font-weight:500;
  padding:3px 10px;border-radius:12px;
  background:rgba(124,77,255,0.12);color:var(--accent-purple);
}
.news-card .lang-badge{
  font-family:var(--font-mono);font-size:11px;font-weight:600;
  padding:3px 8px;border-radius:12px;
  text-transform:uppercase;letter-spacing:0.05em;
}
.lang-badge.zh{background:rgba(0,255,200,0.1);color:var(--accent)}
.lang-badge.en{background:rgba(255,179,71,0.12);color:var(--accent-amber)}
.news-card .card-date{
  font-size:12px;color:var(--text-muted);
}
.news-card h3{
  font-family:var(--font-display);font-size:17px;font-weight:700;
  color:#fff;line-height:1.35;margin-bottom:12px;
}
.news-card h3 a{
  color:inherit;text-decoration:none;
  transition:color 0.2s;
}
.news-card h3 a:hover{color:var(--accent)}
.topic-pills{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.topic-pill{
  font-family:var(--font-mono);font-size:11px;font-weight:500;
  padding:3px 10px;border-radius:12px;
}
.key-points{
  margin-bottom:14px;flex:1;
}
.key-points li{
  font-size:13px;color:var(--text-secondary);line-height:1.5;
  margin-bottom:4px;list-style:none;
  padding-left:16px;position:relative;
}
.key-points li::before{
  content:'';position:absolute;left:0;top:8px;
  width:6px;height:6px;border-radius:50%;
  background:var(--accent);opacity:0.6;
}
.impact-box{
  font-size:13px;color:var(--text-secondary);
  padding:12px 14px;border-radius:var(--radius-sm);
  background:rgba(0,255,200,0.04);
  border-left:3px solid var(--accent);
  line-height:1.55;margin-top:auto;
}
.impact-box strong{
  color:var(--accent);font-weight:600;
}

/* ===== Analysis Section ===== */
.analysis-content{
  background:var(--bg-card);
  border:1px solid var(--border-card);
  border-radius:var(--radius);
  padding:36px 40px;
  max-width:860px;
}
.analysis-content h1{
  font-family:var(--font-display);font-size:26px;font-weight:700;
  color:#fff;margin:32px 0 16px;
}
.analysis-content h1:first-child{margin-top:0}
.analysis-content h2{
  font-family:var(--font-display);font-size:22px;font-weight:700;
  color:#fff;margin:28px 0 14px;
  padding-bottom:8px;
  border-bottom:1px solid var(--border-card);
}
.analysis-content h3{
  font-family:var(--font-display);font-size:18px;font-weight:600;
  color:var(--text-primary);margin:24px 0 10px;
}
.analysis-content h4{
  font-family:var(--font-display);font-size:15px;font-weight:600;
  color:var(--accent);margin:18px 0 8px;
}
.analysis-content p{
  color:var(--text-secondary);line-height:1.75;margin-bottom:12px;
}
.analysis-content strong{color:var(--text-primary);font-weight:600}
.analysis-content ul{margin:10px 0 16px 4px}
.analysis-content li{
  color:var(--text-secondary);line-height:1.7;
  margin-bottom:4px;padding-left:8px;
}
.analysis-content a{
  color:var(--accent);text-decoration:none;
  border-bottom:1px solid rgba(0,255,200,0.3);
  transition:border-color 0.2s;
}
.analysis-content a:hover{border-color:var(--accent)}
.analysis-content hr{
  border:none;border-top:1px solid var(--border-card);
  margin:28px 0;
}

/* ===== Footer ===== */
.footer{
  margin-top:60px;padding:24px 0;
  border-top:1px solid var(--border-card);
  text-align:center;
}
.footer p{
  font-family:var(--font-mono);font-size:12px;
  color:var(--text-muted);letter-spacing:0.02em;
}
.footer span{color:var(--accent)}

/* ===== Animations ===== */
@keyframes fadeUp{
  from{opacity:0;transform:translateY(20px)}
  to{opacity:1;transform:translateY(0)}
}
@keyframes pulse{
  0%,100%{opacity:1}
  50%{opacity:0.4}
}
.pulse-dot{
  display:inline-block;width:6px;height:6px;border-radius:50%;
  background:var(--accent);margin-right:8px;
  animation:pulse 2s ease-in-out infinite;
}

/* ===== Scrollbar ===== */
::-webkit-scrollbar{width:8px}
::-webkit-scrollbar-track{background:var(--bg-primary)}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.08);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,0.14)}
</style>
</head>
<body>

<div class="page-wrapper">

  <!-- ===== HEADER ===== -->
  <header class="header">
    <div class="header-top">
      <div>
        <h1>AI 舆情分析日报</h1>
        <div class="subtitle"><span class="pulse-dot"></span>Daily AI Insight Report</div>
      </div>
      <div class="date-badge">__DATE__</div>
    </div>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-value" data-count="__STATS_TOTAL__">0</div>
        <div class="stat-label">新闻总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" data-count="__STATS_CN__">0</div>
        <div class="stat-label">中文</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" data-count="__STATS_EN__">0</div>
        <div class="stat-label">英文</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" data-count="__STATS_TOPICS__">0</div>
        <div class="stat-label">话题</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" data-count="__STATS_SOURCES__">0</div>
        <div class="stat-label">来源</div>
      </div>
    </div>
  </header>

  <!-- ===== CHARTS ===== -->
  <section class="section">
    <h2 class="section-title">数据概览</h2>
    <div class="charts-grid">
      <div class="chart-card">
        <h3>话题分布</h3>
        <canvas id="topicsChart"></canvas>
      </div>
      <div class="chart-card">
        <h3>新闻来源</h3>
        <canvas id="sourcesChart"></canvas>
      </div>
    </div>
  </section>

  <!-- ===== NEWS LIST ===== -->
  <section class="section">
    <h2 class="section-title">事件列表</h2>
    <div class="filter-bar" id="filterBar"></div>
    <div class="news-grid" id="newsGrid"></div>
  </section>

  <!-- ===== DEEP ANALYSIS ===== -->
  <section class="section">
    <h2 class="section-title">深度分析</h2>
    <div class="analysis-content">
      __ANALYSIS_HTML__
    </div>
  </section>

  <!-- ===== FOOTER ===== -->
  <div class="footer">
    <p><span>AI 舆情分析日报系统</span> &middot; 生成时间: __TIME__ &middot; 模型: __MODEL__</p>
  </div>

</div>

<script>
// ===== Data (event clusters) =====
const clusterData = __NEWS_JSON__;
const stats = __STATS_JSON__;

const CHART_COLORS = [
  '#00ffc8','#7c4dff','#ffb347','#ff6b6b','#26c6da',
  '#66bb6a','#ff7043','#ab47bc','#29b6f6','#ffd54f',
  '#00e676','#ff4081','#448aff','#69f0ae','#ffab40',
  '#e040fb'
];

const TOPIC_PALETTE = CHART_COLORS;

// ===== Animated Counters =====
document.querySelectorAll('[data-count]').forEach(function(el) {
  var target = parseInt(el.dataset.count);
  var dur = 1200;
  var start = performance.now();
  function tick(now) {
    var p = Math.min((now - start) / dur, 1);
    var ease = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(target * ease);
    if (p < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
});

// ===== Charts =====
// Topics horizontal bar
(function() {
  var tc = stats.topic_counts;
  var labels = tc.map(function(x){return x[0]});
  var values = tc.map(function(x){return x[1]});
  var colors = tc.map(function(_,i){return CHART_COLORS[i % CHART_COLORS.length]});

  new Chart(document.getElementById('topicsChart'), {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: colors.map(function(c){return c + '33'}),
        borderColor: colors,
        borderWidth: 1,
        borderRadius: 4,
        barThickness: 22,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.04)' },
          ticks: { color: '#5a6478', font: { family: "'IBM Plex Mono'" } }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#8892a4', font: { family: "'Outfit'", size: 12 } }
        }
      }
    }
  });
  document.getElementById('topicsChart').parentElement.style.height = Math.max(250, tc.length * 34 + 40) + 'px';
})();

// Sources donut
(function() {
  var sc = stats.source_counts;
  var labels = sc.map(function(x){return x[0]});
  var values = sc.map(function(x){return x[1]});
  var colors = sc.map(function(_,i){return CHART_COLORS[i % CHART_COLORS.length]});

  new Chart(document.getElementById('sourcesChart'), {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: colors.map(function(c){return c + '55'}),
        borderColor: colors,
        borderWidth: 2,
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true,
      cutout: '55%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            color: '#8892a4',
            font: { family: "'Outfit'", size: 12 },
            padding: 14,
            usePointStyle: true,
            pointStyleWidth: 10,
          }
        }
      }
    }
  });
})();

// ===== Topic Filter Bar =====
var allTopics = [];
clusterData.forEach(function(cl) {
  (cl.combined_topics || []).forEach(function(t) {
    if (allTopics.indexOf(t) === -1) allTopics.push(t);
  });
});
allTopics.sort();

var activeFilter = '__ALL__';
var filterBar = document.getElementById('filterBar');

function makeBtn(label, value) {
  var btn = document.createElement('button');
  btn.className = 'filter-btn' + (value === activeFilter ? ' active' : '');
  btn.textContent = label;
  btn.onclick = function() {
    activeFilter = value;
    document.querySelectorAll('.filter-btn').forEach(function(b){b.classList.remove('active')});
    btn.classList.add('active');
    renderNews();
  };
  filterBar.appendChild(btn);
}
makeBtn('全部', '__ALL__');
allTopics.forEach(function(t) { makeBtn(t, t); });

// ===== Render Event Cards =====
function getTopicColor(topic) {
  var idx = allTopics.indexOf(topic);
  return idx >= 0 ? TOPIC_PALETTE[idx % TOPIC_PALETTE.length] : '#00ffc8';
}

function renderNews() {
  var grid = document.getElementById('newsGrid');
  grid.innerHTML = '';
  var filtered = activeFilter === '__ALL__'
    ? clusterData
    : clusterData.filter(function(cl) {
        return (cl.combined_topics || []).indexOf(activeFilter) >= 0;
      });

  filtered.forEach(function(cl, i) {
    var card = document.createElement('div');
    card.className = 'news-card';
    card.style.animationDelay = (i * 0.04) + 's';

    // Source badges from all articles
    var sourceSet = {};
    (cl.articles || []).forEach(function(a) {
      sourceSet[a.source] = (sourceSet[a.source] || 0) + 1;
    });
    var sourceBadges = Object.keys(sourceSet).map(function(s) {
      return '<span class="source-badge">' + s + (sourceSet[s] > 1 ? ' ×' + sourceSet[s] : '') + '</span>';
    }).join(' ');

    // Topic pills
    var topics = (cl.combined_topics || []).map(function(t) {
      var c = getTopicColor(t);
      return '<span class="topic-pill" style="background:' + c + '18;color:' + c + '">' + t + '</span>';
    }).join('');

    // Key points
    var points = (cl.combined_key_points || []).map(function(p) {
      return '<li>' + p + '</li>';
    }).join('');

    // Hotspot score badge
    var scoreHtml = '';
    if (cl.hotspot_score) {
      scoreHtml = '<span class="lang-badge zh" style="background:rgba(0,255,200,0.1);color:var(--accent);font-size:12px;">热点 ' + cl.hotspot_score.toFixed(1) + '</span>';
    }

    // Related articles list
    var relatedHtml = '';
    if ((cl.articles || []).length > 1) {
      relatedHtml = '<div style="margin-top:8px;padding-top:8px;border-top:1px solid var(--border-card);">';
      relatedHtml += '<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px;">相关报道 (' + cl.articles.length + ')</div>';
      cl.articles.forEach(function(a) {
        relatedHtml += '<div style="font-size:12px;color:var(--text-secondary);padding:2px 0;">';
        relatedHtml += '<span style="color:var(--accent-purple);">▸</span> ';
        relatedHtml += (a.url ? '<a href="' + a.url + '" target="_blank" style="color:var(--text-secondary);text-decoration:none;">' + a.title + '</a>' : a.title);
        relatedHtml += ' <span style="color:var(--text-muted);">— ' + a.source + '</span>';
        relatedHtml += '</div>';
      });
      relatedHtml += '</div>';
    }

    card.innerHTML =
      '<div class="card-meta">' +
        sourceBadges + ' ' + scoreHtml +
      '</div>' +
      '<h3>' + cl.event_title + '</h3>' +
      '<div class="topic-pills">' + topics + '</div>' +
      '<ul class="key-points">' + points + '</ul>' +
      (cl.combined_impact ? '<div class="impact-box"><strong>影响：</strong>' + cl.combined_impact + '</div>' : '') +
      relatedHtml;

    grid.appendChild(card);
  });
}
renderNews();

// ===== Staggered entrance =====
var observer = new IntersectionObserver(function(entries) {
  entries.forEach(function(e) {
    if (e.isIntersecting) {
      e.target.style.animationPlayState = 'running';
      observer.unobserve(e.target);
    }
  });
}, { threshold: 0.1 });

document.querySelectorAll('.section').forEach(function(s) {
  s.style.animationPlayState = 'paused';
  observer.observe(s);
});
</script>
</body>
</html>"""

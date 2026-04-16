"""
X (Twitter) 和雪球数据采集器

X/Twitter: 通过 Nitter RSS 获取 AI 领域关键博主的推文
雪球: 通过 API 获取 AI 领域博主动态（需要配置 Cookie）

数据源配置在 config.py 的 X_ACCOUNTS 和 XUEQIU_ACCOUNTS 中。
"""

import hashlib
import json
import re
import time
from datetime import datetime

import requests
import feedparser

from config import (
    COLLECT_DELAY,
    COLLECT_MAX_PER_SOURCE,
    COLLECT_TIMEOUT,
    DATA_RAW_DIR,
    X_ACCOUNTS,
    XUEQIU_ACCOUNTS,
)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _generate_id(prefix: str, url: str) -> str:
    short_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{prefix}_{short_hash}"


def _clean_html(text: str) -> str:
    """清理 HTML 标签和多余空白"""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:500]


def _parse_nitter_date(date_str: str) -> str:
    """解析 Nitter RSS 的日期格式"""
    if not date_str:
        return datetime.now().isoformat()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        return dt.isoformat()
    except Exception:
        pass
    return datetime.now().isoformat()


# ─── X / Twitter (via Nitter RSS) ───────────────────────


def collect_x_account(username: str, max_results: int = COLLECT_MAX_PER_SOURCE) -> list[dict]:
    """通过 Nitter RSS 获取单个 X 用户的推文"""
    clean_name = username.lstrip("@")
    print(f"  [X] 正在采集 @{clean_name} ...")

    news = []
    try:
        url = f"https://nitter.net/{clean_name}/rss"
        resp = requests.get(url, headers=HEADERS, timeout=COLLECT_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)

        for entry in feed.entries:
            if len(news) >= max_results:
                break

            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # 跳过纯转发（以 "RT by @" 或 "RT @" 开头的）
            if title.startswith("RT by @") or title.startswith("RT @"):
                continue

            # 清理标题中的 "R to @xxx: " 前缀（回复推文）
            display_title = re.sub(r"^R to @\w+:\s*", "", title)
            if not display_title:
                display_title = title

            summary = _clean_html(entry.get("summary", ""))

            news.append({
                "id": _generate_id("x", link),
                "title": display_title,
                "source": f"X/@{clean_name}",
                "url": link,
                "publish_date": _parse_nitter_date(entry.get("published", "")),
                "language": "en",
                "summary": summary or display_title,
            })

    except requests.RequestException as e:
        print(f"  [X] @{clean_name} 采集失败: {e}")

    print(f"  [X] @{clean_name}: 采集到 {len(news)} 条推文")
    return news


def collect_all_x(accounts: list[dict] = None) -> list[dict]:
    """采集所有 X 账户的推文"""
    if accounts is None:
        accounts = X_ACCOUNTS

    print(f"\n[X] 开始采集 {len(accounts)} 个 X 账户...")
    all_news = []

    for account in accounts:
        username = account["username"]
        news = collect_x_account(username)
        all_news.extend(news)
        time.sleep(COLLECT_DELAY)

    print(f"[X] 共采集到 {len(all_news)} 条推文")
    return all_news


# ─── 雪球 (Xueqiu) ─────────────────────────────────────


def _get_xueqiu_session(cookie: str = None) -> requests.Session:
    """创建带认证的雪球 Session"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    })

    # 先访问首页获取基础 cookies
    session.get("https://xueqiu.com/", timeout=COLLECT_TIMEOUT)

    # 如果提供了自定义 cookie，设置上去
    if cookie:
        for item in cookie.split(";"):
            item = item.strip()
            if "=" in item:
                key, val = item.split("=", 1)
                session.cookies.set(key.strip(), val.strip(), domain="xueqiu.com")

    return session


def _find_user_id(session: requests.Session, screen_name: str) -> str | None:
    """通过用户昵称查找雪球用户 ID（使用 /query/v1/search/user.json 接口）"""
    import urllib.parse
    try:
        encoded = urllib.parse.quote(screen_name)
        url = f"https://xueqiu.com/query/v1/search/user.json?q={encoded}&count=10"
        resp = session.get(url, timeout=COLLECT_TIMEOUT)
        data = resp.json()
        for user in data.get("list", []):
            if user.get("screen_name") == screen_name:
                return str(user.get("id", ""))
    except Exception:
        pass
    return None


def collect_xueqiu_account(account: dict, session: requests.Session, max_results: int = 10) -> list[dict]:
    """获取单个雪球用户的动态"""
    screen_name = account["screen_name"]
    user_id = account.get("user_id", "")
    print(f"  [雪球] 正在采集 {screen_name} ...")

    news = []

    # 如果没有 user_id，尝试查找
    if not user_id:
        user_id = _find_user_id(session, screen_name)

    if not user_id:
        print(f"  [雪球] {screen_name}: 无法获取用户 ID，跳过")
        return []

    try:
        url = f"https://xueqiu.com/statuses/original/show.json?user_id={user_id}&page=1&size={max_results}"
        resp = session.get(url, timeout=COLLECT_TIMEOUT)

        # 检测 WAF 拦截（返回 HTML 而非 JSON）
        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type or resp.text.strip().startswith("<"):
            print(f"  [雪球] {screen_name}: 接口被 WAF 拦截，跳过（需浏览器环境）")
            return []

        data = resp.json()

        for item in data.get("list", []):
            title = item.get("title", "") or item.get("text", "")[:80]
            text = _clean_html(item.get("text", ""))
            item_id = item.get("id", "")
            created_at = item.get("created_at", 0)

            if not title:
                continue

            # 简单的 AI 关键词过滤
            from config import CN_AI_KEYWORDS
            full_text = f"{title} {text}".lower()
            ai_related = any(kw.lower() in full_text for kw in CN_AI_KEYWORDS)
            if not ai_related:
                continue

            pub_date = datetime.now().isoformat()
            if created_at:
                try:
                    pub_date = datetime.fromtimestamp(created_at / 1000).isoformat()
                except (ValueError, TypeError, OSError):
                    pass

            news.append({
                "id": _generate_id("xq", str(item_id)),
                "title": title,
                "source": f"雪球/{screen_name}",
                "url": f"https://xueqiu.com/{item_id}",
                "publish_date": pub_date,
                "language": "zh",
                "summary": text or title,
            })

    except requests.RequestException as e:
        print(f"  [雪球] {screen_name} 采集失败: {e}")

    print(f"  [雪球] {screen_name}: 采集到 {len(news)} 条")
    return news


def collect_all_xueqiu(accounts: list[dict] = None, cookie: str = None) -> list[dict]:
    """
    采集所有雪球账户的动态

    Args:
        accounts: 账户配置列表
        cookie: 雪球登录 Cookie（从浏览器复制），不提供则只能获取有限数据
    """
    if accounts is None:
        accounts = XUEQIU_ACCOUNTS

    if not accounts:
        return []

    print(f"\n[雪球] 开始采集 {len(accounts)} 个雪球账户...")

    if not cookie:
        print("[雪球] 未配置 Cookie，部分数据可能无法获取")
        print("[雪球] 配置方法: 在 .env 中添加 XUEQIU_COOKIE=你的cookie")

    session = _get_xueqiu_session(cookie)
    all_news = []

    for account in accounts:
        news = collect_xueqiu_account(account, session)
        all_news.extend(news)
        time.sleep(COLLECT_DELAY)

    print(f"[雪球] 共采集到 {len(all_news)} 条动态")
    return all_news


# ─── 统一入口 ─────────────────────────────────────────────


def collect_all_social(
    x_accounts: list[dict] = None,
    xueqiu_accounts: list[dict] = None,
    xueqiu_cookie: str = None,
) -> list[dict]:
    """采集所有社交媒体数据（X + 雪球）"""
    all_news = []

    # X/Twitter
    x_news = collect_all_x(x_accounts)
    all_news.extend(x_news)

    time.sleep(COLLECT_DELAY)

    # 雪球
    xq_news = collect_all_xueqiu(xueqiu_accounts, cookie=xueqiu_cookie)
    all_news.extend(xq_news)

    return all_news


def save_social_news(news_list: list[dict], filepath: str = None) -> str:
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/social_news.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)
    print(f"[社交媒体] 数据已保存到 {filepath}")
    return filepath


def load_social_news(filepath: str = None) -> list[dict]:
    if filepath is None:
        filepath = f"{DATA_RAW_DIR}/social_news.json"
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    # 单独测试 X
    x_news = collect_all_x()
    save_social_news(x_news)

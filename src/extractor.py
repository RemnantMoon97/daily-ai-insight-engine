"""
LLM 结构化抽取器

使用智谱 GLM API 对每条新闻进行分批结构化抽取。
符合限制条件：不一次性将所有数据丢给 AI，而是逐条处理。

处理流程：
1. 加载原始新闻数据（HN + 手动收集）
2. 逐条调用 LLM API，按 Schema 抽取结构化信息
3. 校验返回结果是否符合 Schema
4. 保存结构化数据
"""

import json
import os
import re
import time
import sys

sys.path.insert(0, ".")

from config import ZHIPU_API_KEY, ZHIPU_MODEL, DATA_RAW_DIR, DATA_PROCESSED_DIR, PROMPT_TEMPLATE_PATH
from src.schema import SCHEMA_PROMPT_DESCRIPTION


def get_client():
    """获取智谱 API 客户端"""
    from zhipuai import ZhipuAI
    if not ZHIPU_API_KEY:
        raise ValueError(
            "请设置环境变量 ZHIPU_API_KEY\n"
            "  Windows: set ZHIPU_API_KEY=your_key\n"
            "  Linux/Mac: export ZHIPU_API_KEY=your_key"
        )
    return ZhipuAI(api_key=ZHIPU_API_KEY)


def _load_prompt_template() -> str:
    """从 prompt.txt 加载 Prompt 模板"""
    with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


# 模块加载时缓存模板
_PROMPT_TEMPLATE = _load_prompt_template()


def build_extraction_prompt(news_item: dict) -> str:
    """构建结构化抽取的 Prompt（基于 prompt.txt 模板）"""
    prompt = _PROMPT_TEMPLATE
    prompt = prompt.replace("{title}", news_item.get("title", ""))
    prompt = prompt.replace("{source}", news_item.get("source", ""))
    prompt = prompt.replace("{summary}", news_item.get("summary", ""))
    prompt = prompt.replace("{SCHEMA_PROMPT_DESCRIPTION}", SCHEMA_PROMPT_DESCRIPTION)
    return prompt


def call_llm(client, prompt: str, max_retries: int = 3, max_tokens: int = 4096) -> str:
    """调用智谱 API，含重试机制和 429 专用退避"""
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=ZHIPU_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            err_str = str(e)
            is_rate_limit = "429" in err_str or "速率限制" in err_str or "Rate" in err_str

            if is_rate_limit:
                # 429 限频：较长退避（10s, 30s, 60s）
                wait = 10 * (3 ** attempt)
                print(f"  [限频] 触发速率限制，等待 {wait}s 后重试 ({attempt+1}/{max_retries})...")
            else:
                # 其他错误：常规退避
                wait = 3 * (2 ** attempt)

            print(f"  [重试 {attempt+1}/{max_retries}] API 调用失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(wait)
            else:
                raise


def parse_json_response(response_text: str) -> dict | None:
    """从 LLM 返回的文本中解析 JSON"""
    if not response_text:
        return None

    # 尝试直接解析
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取第一个完整的 JSON 对象（支持多层嵌套）
    brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # 尝试找到顶层 { 并匹配到对应的 }（处理深层嵌套）
    first_brace = response_text.find('{')
    if first_brace >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(first_brace, len(response_text)):
            ch = response_text[i]
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = response_text[first_brace:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # 尝试修复常见的截断：补全未闭合的括号
                        return _try_fix_truncated_json(candidate)

    return None


def _try_fix_truncated_json(text: str) -> dict | None:
    """尝试修复被截断的 JSON（补全缺失的括号）"""
    # 统计未闭合的括号
    open_braces = 0
    open_brackets = 0
    in_string = False
    escape = False

    for ch in text:
        if escape:
            escape = False
            continue
        if ch == '\\':
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            open_braces += 1
        elif ch == '}':
            open_braces -= 1
        elif ch == '[':
            open_brackets += 1
        elif ch == ']':
            open_brackets -= 1

    # 补全缺失的闭合符号
    fixed = text
    # 如果在字符串中被截断，先闭合字符串
    if in_string:
        fixed += '"'
    # 补全括号
    for _ in range(max(0, open_brackets)):
        fixed += ']'
    for _ in range(max(0, open_braces)):
        fixed += '}'

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        return None


def validate_extracted(data: dict) -> dict:
    """校验并修正 LLM 返回的结构化数据"""
    # 确保 main_topics 是列表
    if not isinstance(data.get("main_topics"), list):
        data["main_topics"] = []
    data["main_topics"] = [str(t) for t in data["main_topics"]]

    # 确保 key_points 是列表
    if not isinstance(data.get("key_points"), list):
        data["key_points"] = []
    data["key_points"] = [str(p) for p in data["key_points"]]

    # 确保 impact 是字符串
    if not isinstance(data.get("impact"), str) or not data["impact"].strip():
        data["impact"] = "影响待评估"

    # 确保 affected_companies 是列表
    if not isinstance(data.get("affected_companies"), list):
        data["affected_companies"] = []
    for i, comp in enumerate(data["affected_companies"]):
        if not isinstance(comp, dict):
            data["affected_companies"][i] = {
                "name": str(comp), "impact_direction": "中性", "reason": ""
            }
        else:
            comp.setdefault("name", "")
            comp.setdefault("impact_direction", "中性")
            comp.setdefault("reason", "")

    # 确保 market_signal 是字典
    if not isinstance(data.get("market_signal"), dict):
        data["market_signal"] = {
            "risk_level": "无", "opportunity_type": "无", "investment_hint": ""
        }
    ms = data["market_signal"]
    ms.setdefault("risk_level", "无")
    ms.setdefault("opportunity_type", "无")
    ms.setdefault("investment_hint", "")

    return data


# 抽取失败时的默认值
FALLBACK_EXTRACTION = {
    "main_topics": [],
    "key_points": [],
    "impact": "影响待评估",
    "affected_companies": [],
    "market_signal": {"risk_level": "无", "opportunity_type": "无", "investment_hint": ""},
}


def extract_single_news(client, news_item: dict) -> dict:
    """对单条新闻进行结构化抽取"""
    prompt = build_extraction_prompt(news_item)
    response_text = call_llm(client, prompt)
    extracted = parse_json_response(response_text)

    if extracted is None:
        print(f"  [警告] 无法解析 LLM 返回结果: {news_item.get('title', '')[:40]}")
        extracted = dict(FALLBACK_EXTRACTION)

    # 校验
    extracted = validate_extracted(extracted)

    # 合并原始数据和抽取结果
    return {**news_item, **extracted}


def extract_all(news_list: list[dict], batch_delay: float = 2.0) -> list[dict]:
    """
    分批对所有新闻进行结构化抽取

    Args:
        news_list: 原始新闻列表
        batch_delay: 每次调用之间的延迟（秒），避免 API 限流

    Returns:
        结构化抽取后的新闻列表
    """
    client = get_client()
    results = []

    total = len(news_list)
    print(f"\n[抽取] 开始结构化抽取，共 {total} 条新闻")

    for i, news in enumerate(news_list):
        print(f"  [{i+1}/{total}] 处理: {news.get('title', '')[:50]}...")

        try:
            structured = extract_single_news(client, news)
            results.append(structured)
            print(f"    -> 话题: {', '.join(structured['main_topics'][:3])}")
            print(f"       要点: {structured['key_points'][0][:50] if structured['key_points'] else '无'}...")
        except Exception as e:
            print(f"    [错误] 处理失败: {e}")
            # 保留原始数据，标注为抽取失败
            results.append({
                **news,
                **FALLBACK_EXTRACTION,
                "extraction_error": str(e),
            })

        # 分批延迟，避免 API 限流
        if i < total - 1:
            time.sleep(batch_delay)

    print(f"[抽取] 完成，成功处理 {len(results)} 条")
    return results


def extract_incremental(news_list: list[dict], existing_path: str = None, batch_delay: float = 1.0) -> list[dict]:
    """
    增量抽取：只对新增新闻调用 LLM，已抽取的直接复用

    通过新闻 ID 判断是否已处理过，避免重复调用 API。

    Args:
        news_list: 当前全部新闻列表
        existing_path: 已有结构化数据文件路径
        batch_delay: 每次调用之间的延迟（秒）

    Returns:
        合并后的完整结构化新闻列表
    """
    # 加载已有数据
    existing_structured = []
    existing_ids = set()

    if existing_path and os.path.exists(existing_path):
        try:
            with open(existing_path, "r", encoding="utf-8") as f:
                existing_structured = json.load(f)
            existing_ids = {item.get("id", "") for item in existing_structured}
            print(f"[增量抽取] 已有 {len(existing_structured)} 条结构化数据")
        except (json.JSONDecodeError, IOError) as e:
            print(f"[增量抽取] 读取已有数据失败: {e}，将全量抽取")
            existing_structured = []
            existing_ids = set()

    # 找出新增条目
    new_items = [item for item in news_list if item.get("id", "") not in existing_ids]

    if not new_items:
        print(f"[增量抽取] 没有新增数据，跳过抽取")
        return existing_structured

    print(f"[增量抽取] 发现 {len(new_items)} 条新增新闻（已有 {len(existing_ids)} 条）")

    # 只对新增条目调用 LLM
    new_structured = extract_all(new_items, batch_delay=batch_delay)

    # 合并：已有数据 + 新抽取数据
    merged = existing_structured + new_structured
    print(f"[增量抽取] 合并后共 {len(merged)} 条结构化数据")
    return merged


def save_structured_news(news_list: list[dict], filepath: str = None) -> str:
    """保存结构化数据"""
    if filepath is None:
        filepath = f"{DATA_PROCESSED_DIR}/structured_news.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)

    print(f"[抽取] 结构化数据已保存到 {filepath}")
    return filepath


def load_structured_news(filepath: str = None) -> list[dict]:
    """加载已有的结构化数据"""
    if filepath is None:
        filepath = f"{DATA_PROCESSED_DIR}/structured_news.json"

    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

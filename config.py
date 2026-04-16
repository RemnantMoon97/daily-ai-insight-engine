"""项目配置文件"""
import os
from dotenv import load_dotenv

load_dotenv()

# 智谱 API 配置
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
ZHIPU_MODEL = os.environ.get("ZHIPU_MODEL", "glm-4-flash")

# 数据采集配置
HN_TOP_STORIES_COUNT = 100  # 获取 HN Top Stories 数量
HN_AI_KEYWORDS = [
    "ai", "gpt", "llm", "claude", "openai", "gemini", "deepseek",
    "machine learning", "neural", "transformer", "diffusion",
    "anthropic", "copilot", "chatbot", "agi", "reasoning",
    "language model", "generative", "multimodal", "agent",
]

# 中文 AI 关键词（用于中文媒体过滤）
CN_AI_KEYWORDS = [
    "ai", "人工智能", "大模型", "gpt", "llm", "大语言模型",
    "claude", "openai", "gemini", "deepseek", "深度学习",
    "机器学习", "神经网络", "智能体", "agent", "多模态",
    "生成式", "chatgpt", "自动驾驶", "机器人",
]

# RSS 数据源配置（英文 + 中文统一管理）
RSS_FEEDS = [
    # 英文 RSS
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "language": "en"},
    {"name": "Wired AI", "url": "https://www.wired.com/feed/tag/ai/latest/rss", "language": "en"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "language": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "language": "en"},
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "language": "en"},
    {"name": "AI News", "url": "https://www.artificialintelligence-news.com/feed/rss/", "language": "en"},
    # 中文 RSS
    {"name": "少数派", "url": "https://sspai.com/feed", "language": "zh"},
    {"name": "IT之家", "url": "https://www.ithome.com/rss/", "language": "zh"},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "language": "zh"},
]

# 中文科技媒体网页爬虫配置（仅限可静态抓取的源）
CN_MEDIA_SOURCES = [
    {
        "name": "量子位",
        "id_prefix": "qbt",
        "list_url": "https://www.qbitai.com",
        "language": "zh",
    },
    {
        "name": "36氪",
        "id_prefix": "36kr",
        "list_url": "https://36kr.com/information/AI",
        "language": "zh",
    },
]

# X (Twitter) 账户配置 - AI 领域关键博主
X_ACCOUNTS = [
    {"username": "sama", "name": "Sam Altman"},
    {"username": "karpathy", "name": "Andrej Karpathy"},
    {"username": "emollick", "name": "Ethan Mollick"},
    {"username": "simonw", "name": "Simon Willison"},
    {"username": "DarioAmodei", "name": "Dario Amodei"},
    {"username": "polynoamial", "name": "Polynoamial"},
    {"username": "ylecun", "name": "Yann LeCun"},
    {"username": "geoffreyhinton", "name": "Geoffrey Hinton"},
]

# 雪球账户配置 - AI 领域博主
# user_id 需要通过雪球页面或 API 获取，如不确定可留空
XUEQIU_ACCOUNTS = [
    {"screen_name": "智能纪元AGI", "user_id": ""},
    {"screen_name": "AGENT橘", "user_id": ""},
    {"screen_name": "烟雨与萤火虫", "user_id": ""},
    {"screen_name": "雪球号直通车", "user_id": "1776261263"},
]

# 雪球 Cookie（从浏览器登录后复制，可选）
XUEQIU_COOKIE = os.environ.get("XUEQIU_COOKIE", "")

# 采集参数
COLLECT_TIMEOUT = 15          # HTTP 请求超时（秒）
COLLECT_DELAY = 0.5           # 请求间隔（秒），避免被封
COLLECT_MAX_PER_SOURCE = 15   # 每个数据源最多采集条数
SCHEDULE_TIME = "08:00"       # 定时采集时间（每天）

# Prompt 模板
PROMPT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "prompt.txt")
PROMPT_ANALYSIS_PATH = os.path.join(os.path.dirname(__file__), "prompt_analysis.txt")
PROMPT_INVESTMENT_PATH = os.path.join(os.path.dirname(__file__), "prompt", "investment_analysis.txt")

# 输出配置
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
DATA_RAW_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
DATA_DAILY_DIR = os.path.join(os.path.dirname(__file__), "data", "daily")
DATA_PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "data", "processed")
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")

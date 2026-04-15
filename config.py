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

# Prompt 模板
PROMPT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "prompt.txt")
PROMPT_ANALYSIS_PATH = os.path.join(os.path.dirname(__file__), "prompt_analysis.txt")

# 输出配置
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
DATA_RAW_DIR = os.path.join(os.path.dirname(__file__), "data", "raw")
DATA_PROCESSED_DIR = os.path.join(os.path.dirname(__file__), "data", "processed")
CHARTS_DIR = os.path.join(OUTPUT_DIR, "charts")

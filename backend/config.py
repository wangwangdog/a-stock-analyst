import os
from pathlib import Path

# 数据库配置 — 统一指向 chanlun_klines.sqlite（主页面同源）
DB_PATH = Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite'

# 请求间隔（秒）
REQUEST_INTERVAL = 0.1

# 数据验证配置
VALIDATION_TOLERANCE = {
    "open": 0.001,
    "high": 0.001,
    "low": 0.001,
    "close": 0.001,
    "volume": 0.02,
}  # K 线数据验证容差（各字段）

# API 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# OpenAlice 配置（本地 Docker 部署）
OPENALICE_MCP_URL = os.getenv("OPENALICE_MCP_URL", "http://127.0.0.1:47332")
OPENALICE_UTA_URL = os.getenv("OPENALICE_UTA_URL", "http://127.0.0.1:47333")
OPENALICE_WEB_URL = os.getenv("OPENALICE_WEB_URL", "http://127.0.0.1:47331")

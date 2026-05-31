import os
from pathlib import Path

# 数据库配置
DB_PATH = Path(__file__).parent / 'stock.db'

# 请求间隔（秒）
REQUEST_INTERVAL = 0.1

# 数据验证配置
VALIDATION_TOLERANCE = 0.001  # K 线数据验证容差

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

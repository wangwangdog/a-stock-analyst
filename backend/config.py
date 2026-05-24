"""全局配置"""
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 数据库（合并到 chanlun-pro 的统一数据库）
DB_PATH = Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"

# 数据源优先级: akshare > baostock
DATA_SOURCES = ["akshare", "baostock"]

# 校验容差
VALIDATION_TOLERANCE = {
    "open": 0.02,   # 开盘价 ±2%
    "close": 0.02,  # 收盘价 ±2%
    "high": 0.03,   # 最高价 ±3%
    "low": 0.03,    # 最低价 ±3%
    "volume": 0.05, # 成交量 ±5%
}

# 请求间隔(秒)，避免被封
REQUEST_INTERVAL = 0.5

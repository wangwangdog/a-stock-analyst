"""全局配置 - 适配合并数据库"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"
DATA_SOURCES = ["akshare", "baostock"]
VALIDATION_TOLERANCE = {"open": 0.02, "close": 0.02, "high": 0.03, "low": 0.03, "volume": 0.05}
REQUEST_INTERVAL = 0.5

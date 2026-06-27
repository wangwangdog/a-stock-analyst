"""a-stock-analyst 后端 uvicorn 入口 (独立进程 :9901)"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent / "a_stock_backend"
sys.path.insert(0, str(BACKEND_DIR))

from main import app

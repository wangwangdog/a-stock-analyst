"""Baostock 数据获取（备用/校验源）"""
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from config import REQUEST_INTERVAL

try:
    import baostock as bs
    _BS_AVAILABLE = True
except ImportError:
    _BS_AVAILABLE = False

# 连接管理
_BS_LOGGED_IN = False


def _ensure_login():
    """确保已登录 Baostock"""
    global _BS_AVAILABLE, _BS_LOGGED_IN
    if not _BS_AVAILABLE:
        return False
    if not _BS_LOGGED_IN:
        try:
            lg = bs.login()
            if lg.error_code == '0':
                _BS_LOGGED_IN = True
            else:
                logger.warning(f"[Baostock] 登录失败: {lg.error_msg}")
                return False
        except Exception as e:
            logger.warning(f"[Baostock] 登录异常: {e}")
            return False
    return True


def _logout():
    global _BS_LOGGED_IN
    if _BS_AVAILABLE and _BS_LOGGED_IN:
        try:
            bs.logout()
        except Exception:
            pass
        _BS_LOGGED_IN = False


def available() -> bool:
    return _BS_AVAILABLE


def _to_bs_code(symbol: str) -> str:
    """转换为 Baostock 代码格式: 600000 → sh.600000"""
    if symbol.startswith(("sh.", "sz.", "bj.")):
        return symbol
    if symbol.startswith(("6", "9")):
        return f"sh.{symbol}"
    elif symbol.startswith(("0", "3")):
        return f"sz.{symbol}"
    elif symbol.startswith(("8", "4")):
        return f"bj.{symbol}"
    return symbol


def _from_bs_code(bs_code: str) -> str:
    """从 Baostock 代码转回原始代码"""
    return bs_code.split(".")[-1]


def get_daily_kline(symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """获取日K线（后复权）"""
    if not _ensure_login():
        return None
    try:
        bs_code = _to_bs_code(symbol)
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            fields="date,open,high,low,close,volume,amount,adjustflag",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="1"  # 前复权（与 AKShare 保持一致）
        )
        if rs.error_code != '0':
            logger.warning(f"[Baostock] 查询失败 {symbol}: {rs.error_msg}")
            return None

        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[1] == "":
                continue
            rows.append({
                "trade_date": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]) if row[5] else 0,
                "amount": float(row[6]) if row[6] else 0,
            })

        return pd.DataFrame(rows) if rows else None
    except Exception as e:
        logger.warning(f"[Baostock] 获取 {symbol} K线失败: {e}")
        return None


def get_stock_list() -> pd.DataFrame:
    """获取股票列表"""
    if not _ensure_login():
        return pd.DataFrame()
    try:
        rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
        rows = []
        while rs.next():
            row = rs.get_row_data()
            status = row[2]
            if status == "1":  # 仅上市
                code = _from_bs_code(row[0])
                rows.append({"symbol": code, "code_name": row[1], "status": status})
        return pd.DataFrame(rows)
    except Exception as e:
        logger.warning(f"[Baostock] 获取股票列表失败: {e}")
    return pd.DataFrame()


# 程序退出时登出
import atexit
atexit.register(_logout)

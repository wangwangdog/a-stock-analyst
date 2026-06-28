"""SQLite 数据缓存层"""
import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import Optional
from pathlib import Path

import pandas as pd
from loguru import logger

from config import DB_PATH


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """初始化数据库表"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kline_cache (
                symbol TEXT NOT NULL,
                source TEXT NOT NULL,
                period TEXT NOT NULL DEFAULT 'daily',
                trade_date TEXT NOT NULL,
                open REAL,
                close REAL,
                high REAL,
                low REAL,
                volume REAL,
                amount REAL,
                PRIMARY KEY (symbol, source, period, trade_date)
            );

            CREATE TABLE IF NOT EXISTS kline_check_log (
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                akshare_open REAL,
                baostock_open REAL,
                diff_pct REAL,
                passed INTEGER,
                checked_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (symbol, trade_date)
            );

            CREATE TABLE IF NOT EXISTS fundamentals_cache (
                symbol TEXT NOT NULL,
                data_type TEXT NOT NULL,
                data_json TEXT,
                fetched_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (symbol, data_type)
            );

            CREATE INDEX IF NOT EXISTS idx_kline_symbol_date ON kline_cache(symbol, trade_date);
            CREATE INDEX IF NOT EXISTS idx_check_log_date ON kline_check_log(checked_at);

            CREATE TABLE IF NOT EXISTS stock_cr_indicator (
                symbol TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                cr REAL,
                cr_ma1 REAL,
                cr_ma2 REAL,
                cr_ma3 REAL,
                PRIMARY KEY (symbol, trade_date)
            );

            CREATE INDEX IF NOT EXISTS idx_cr_symbol_date ON stock_cr_indicator(symbol, trade_date);
        """)
        conn.commit()
    finally:
        conn.close()


def _migrate_v1_to_v2():
    """迁移旧表（无 period 列）到新 schema"""
    conn = _get_conn()
    try:
        # 检查是否已有 period 列
        cursor = conn.execute("PRAGMA table_info(kline_cache)")
        cols = [row[1] for row in cursor.fetchall()]
        if "period" not in cols:
            logger.info("[缓存] 检测到旧表结构，执行迁移...")
            conn.executescript("""
                ALTER TABLE kline_cache RENAME TO kline_cache_old;
                CREATE TABLE kline_cache (
                    symbol TEXT NOT NULL,
                    source TEXT NOT NULL,
                    period TEXT NOT NULL DEFAULT 'daily',
                    trade_date TEXT NOT NULL,
                    open REAL,
                    close REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    amount REAL,
                    PRIMARY KEY (symbol, source, period, trade_date)
                );
                INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)
                    SELECT symbol, source, 'daily', trade_date, open, close, high, low, volume, amount
                    FROM kline_cache_old;
                DROP TABLE kline_cache_old;
            """)
            conn.commit()
            logger.info("[缓存] 表结构迁移完成")
    except Exception as e:
        logger.warning(f"[缓存] 表迁移失败 (可能已迁移): {e}")
    finally:
        conn.close()


def _normalize_symbol(symbol: str) -> str:
    """统一A股代码格式为 SH.XXXXXX / SZ.XXXXXX / BJ.XXXXXX"""
    if "." in symbol:
        return symbol  # 已含前缀
    if len(symbol) != 6:
        return symbol  # 非标准6位码，不动
    prefixes = {
        "5": "SH", "6": "SH", "9": "SH",
        "0": "SZ", "2": "SZ", "3": "SZ",
        "4": "BJ", "8": "BJ",
    }
    first = symbol[0]
    pre = prefixes.get(first, "SZ")
    return f"{pre}.{symbol}"


def save_kline(symbol: str, source: str, df: pd.DataFrame, period: str = "daily"):
    """批量保存K线数据，自动归一化symbol为全码"""
    if df is None or df.empty:
        return
    symbol = _normalize_symbol(symbol)
    if df is None or df.empty:
        return
    conn = _get_conn()
    try:
        # 确保列名统一
        rename_map = {
            "日期": "trade_date", "date": "trade_date",
            "开盘": "open", "open": "open",
            "收盘": "close", "close": "close",
            "最高": "high", "high": "high",
            "最低": "low", "low": "low",
            "成交量": "volume", "volume": "volume",
            "成交额": "amount", "amount": "amount",
        }
        df = df.rename(columns=rename_map)
        required = ["trade_date", "open", "close", "high", "low"]
        if not all(c in df.columns for c in required):
            return

        rows = []
        for _, row in df.iterrows():
            td = str(row["trade_date"]).strip()[:10] if period == "daily" else str(row["trade_date"]).strip()[:19]
            rows.append((
                symbol, source, period, td,
                float(row.get("open", 0)), float(row.get("close", 0)),
                float(row.get("high", 0)), float(row.get("low", 0)),
                float(row.get("volume", 0)), float(row.get("amount", 0)),
            ))

        conn.executemany("""
            INSERT OR REPLACE INTO kline_cache
            (symbol, source, period, trade_date, open, close, high, low, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
    finally:
        conn.close()


def get_kline(symbol: str, source: str, start_date: str = None, end_date: str = None, period: str = None) -> pd.DataFrame:
    """读取缓存K线"""
    conn = _get_conn()
    try:
        sql = "SELECT * FROM kline_cache WHERE symbol=? AND source=?"
        params = [symbol, source]
        if period:
            sql += " AND period=?"
            params.append(period)
        if start_date:
            sql += " AND DATE(trade_date)>=?"
            params.append(start_date)
        if end_date:
            sql += " AND DATE(trade_date)<=?"
            params.append(end_date)
        sql += " ORDER BY trade_date ASC"
        df = pd.read_sql(sql, conn, params=params)
        if not df.empty:
            df["trade_date"] = pd.to_datetime(df["trade_date"], format='mixed')
        return df
    finally:
        conn.close()


def is_cache_fresh(symbol: str, source: str, max_days: int = 1, period: str = "daily") -> bool:
    """检查缓存是否新鲜（max_days 内的数据）"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND source=? AND period=?",
            (symbol, source, period)
        )
        row = cursor.fetchone()
        if row and row[0]:
            last_str = row[0][:10]  # 截取前10位兼容 "2026-04-20" 或 "2026-04-20 09:45:00"
            last_date = datetime.strptime(last_str, "%Y-%m-%d")
            return (datetime.now() - last_date).days <= max_days
        return False
    finally:
        conn.close()


def log_check(symbol: str, trade_date: str, akshare_open: float, baostock_open: float,
              diff_pct: float, passed: bool):
    """记录数据校验日志"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO kline_check_log
            (symbol, trade_date, akshare_open, baostock_open, diff_pct, passed)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (symbol, trade_date, akshare_open, baostock_open, diff_pct, int(passed)))
        conn.commit()
    finally:
        conn.close()


def save_fundamentals(symbol: str, data_type: str, data: dict):
    """缓存基本面数据"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO fundamentals_cache (symbol, data_type, data_json, fetched_at)
            VALUES (?, ?, ?, datetime('now','localtime'))
        """, (symbol, data_type, json.dumps(data, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def get_fundamentals(symbol: str, data_type: str) -> Optional[dict]:
    """读取基本面缓存"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "SELECT data_json, fetched_at FROM fundamentals_cache WHERE symbol=? AND data_type=?",
            (symbol, data_type)
        )
        row = cursor.fetchone()
        if row:
            return {"data": json.loads(row[0]), "fetched_at": row[1]}
        return None
    finally:
        conn.close()


# 启动时初始化
init_db()
_migrate_v1_to_v2()

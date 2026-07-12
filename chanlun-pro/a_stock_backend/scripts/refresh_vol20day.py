#!/usr/bin/env python3
"""
独立的 vol20day 刷新脚本
- 从 kline_cache 读取日线数据（不限数据源，baostock/akshare均可）
- 计算 N 日涨幅（默认 20 日）
- 写入 vol20day 表

比 sequoia_engine 的 SQL 方式更省内存（逐只处理）
"""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from loguru import logger

DB_PATH = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
N_DAYS = 20  # 计算 N 日涨幅


def get_all_cached_stocks():
    """从 kline_cache 获取有日线数据的股票列表"""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' "
            "AND (symbol LIKE '0%' OR symbol LIKE '6%') "
            "ORDER BY symbol"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def get_latest_20(symbol: str):
    """获取某只股票最近 21 条日线（最新日期在前）"""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT DISTINCT trade_date, close FROM kline_cache "
            "WHERE symbol=? AND period='daily' AND close > 0 "
            "ORDER BY trade_date DESC LIMIT ?",
            (symbol, N_DAYS + 1)
        ).fetchall()
        return rows  # [(trade_date, close), ...]
    finally:
        conn.close()


def build_name_map(symbols: list[str]) -> dict:
    """一次性从 baostock 获取所有股票名称"""
    name_map = {}
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == "0":
            try:
                # 获取全市场股票基本信息
                rs = bs.query_all_stock('2026-01-01')
                if rs.error_code == "0":
                    logger.info(f"  从 baostock 获取股票名称...")
                    while rs.next():
                        row = rs.get_row_data()
                        raw_code = row[0]  # 'sh.600000' 或 'sz.000001'
                        name = row[2]      # 股票名称
                        code = raw_code[3:]  # 去掉 sz./sh. 前缀
                        name_map[code] = name
            finally:
                bs.logout()
    except Exception as e:
        logger.warning(f"  baostock 名称获取失败: {e}")
    
    # 补充：从 hzeveryday 查漏
    conn = sqlite3.connect(DB_PATH)
    try:
        for sym in symbols:
            if sym not in name_map or not name_map[sym]:
                r = conn.execute("SELECT 股票名称 FROM hzeveryday WHERE 股票代码=? LIMIT 1", (sym,)).fetchone()
                if r and r[0]:
                    name_map[sym] = r[0]
                else:
                    r = conn.execute("SELECT 股票名称 FROM stock_records WHERE 股票代码=? LIMIT 1", (sym,)).fetchone()
                    if r and r[0]:
                        name_map[sym] = r[0]
    finally:
        conn.close()
    return name_map


def refresh():
    """主刷新函数"""
    logger.info(f"🚀 刷新 vol20day 表（{N_DAYS}日涨幅计算）...")

    symbols = get_all_cached_stocks()
    logger.info(f"共 {len(symbols)} 只股票待处理")

    conn = sqlite3.connect(DB_PATH)
    try:
        # 清空旧表
        conn.execute("DELETE FROM vol20day")

        # 确保 name 列存在
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vol20day)").fetchall()]
        if 'name' not in cols:
            conn.execute("ALTER TABLE vol20day ADD COLUMN name TEXT DEFAULT ''")
        conn.commit()

        results = []  # [(symbol, name, latest_date, latest_close, date_20d, close_20d, return_pct)]
        total = len(symbols)
        for idx, symbol in enumerate(symbols):
            rows = get_latest_20(symbol)
            if len(rows) < N_DAYS + 1:
                continue  # 不足 N+1 条数据，跳过

            # rows[0] = 最新, rows[20] = N 日前
            latest_date, latest_close = rows[0]
            date_20d, close_20d = rows[N_DAYS]
            if not latest_close or not close_20d:
                continue

            return_pct = (latest_close - close_20d) / close_20d * 100.0
            results.append((symbol, latest_date, latest_close, date_20d, close_20d, return_pct))

            if (idx + 1) % 100 == 0:
                logger.info(f"  处理中: {idx+1}/{total}")

        # 按涨幅降序排列
        results.sort(key=lambda x: x[5], reverse=True)

        # 批量获取名称
        logger.info(f"  获取股票名称（共 {len(results)} 只）...")
        name_map = build_name_map([r[0] for r in results])
        logger.info(f"  已获取 {len(name_map)} 只股票名称")

        # 写入数据库
        for rank, r in enumerate(results, 1):
            symbol = r[0]
            sname = name_map.get(symbol, "")
            conn.execute(
                "INSERT OR REPLACE INTO vol20day (symbol, name, latest_date, latest_close, date_20d, close_20d, return_20d, rank_20d) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (symbol, sname or "", r[1], r[2], r[3], r[4], round(r[5], 4), rank)
            )
            if (rank + 1) % 500 == 0:
                conn.commit()
        conn.commit()

        conn.commit()
        logger.info(f"✅ vol20day 刷新完成: {len(results)} 只股票")
        return {"status": "ok", "total": len(results)}

    except Exception as e:
        conn.rollback()
        logger.error(f"❌ 刷新失败: {e}")
        return {"status": "failed", "error": str(e)}
    finally:
        conn.close()


if __name__ == "__main__":
    result = refresh()
    print(result)

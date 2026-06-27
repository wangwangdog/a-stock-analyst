#!/usr/bin/env python3
"""
把 5m K线数据聚合成 15m/30m/60m，写入 kline_cache。
只写入比已有数据更新的部分（增量）。

用法: .venv/bin/python3 aggregate_5m_to_higher.py
"""
import sys, os, time
from pathlib import Path
from collections import defaultdict

import pandas as pd

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

TARGET_PERIODS = {"15m": 3, "30m": 6, "60m": 12}  # period -> 5m candle count


def get_db():
    import sqlite3
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def get_stocks_with_5m(conn, limit=None):
    """获取 kline_cache 中有 5m 数据的所有股票代码"""
    sql = "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' ORDER BY symbol"
    if limit:
        sql += f" LIMIT {limit}"
    return [r[0] for r in conn.execute(sql).fetchall()]


def get_max_date(conn, symbol, period):
    """获取某股票某周期的最大日期"""
    r = conn.execute(
        "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period=?",
        (symbol, period)
    ).fetchone()[0]
    return r  # str or None


def get_5m_data(conn, symbol, since):
    """获取5m数据（since之后的）"""
    if since:
        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
            "WHERE symbol=? AND period='5m' AND trade_date>? ORDER BY trade_date",
            (symbol, since)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
            "WHERE symbol=? AND period='5m' ORDER BY trade_date",
            (symbol,)
        ).fetchall()
    return rows


def aggregate_5m_to(rows, n):
    """
    将5m rows（list of tuple）聚合为 n 根5m合一的高级周期数据。
    返回 [(trade_date, open, close, high, low, volume, amount), ...]
    """
    result = []
    for i in range(0, len(rows), n):
        chunk = rows[i:i + n]
        if len(chunk) < n:
            break  # 不足n根的不写（防止不完整K线）
        trade_date = chunk[-1][0]     # 取最后一根的时间
        open_ = chunk[0][1]           # 第一根的开盘
        close = chunk[-1][2]          # 最后一根的收盘
        high = max(r[3] for r in chunk)  # 区间最高
        low = min(r[4] for r in chunk)   # 区间最低
        volume = sum(r[5] for r in chunk)  # 累计成交量
        amount = sum(r[6] for r in chunk)  # 累计成交额
        result.append((trade_date, open_, close, high, low, volume, amount))
    return result


def save_period(conn, symbol, period, rows):
    """批量写入，INSERT OR IGNORE"""
    data = [(symbol, 'tdx', period, r[0], r[1], r[2], r[3], r[4], r[5], r[6])
            for r in rows]
    conn.executemany(
        "INSERT OR IGNORE INTO kline_cache "
        "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        data
    )
    conn.commit()
    return len(data)


def main():
    t0 = time.time()
    conn = get_db()

    stocks = get_stocks_with_5m(conn)
    print(f"有5m数据的股票: {len(stocks)} 只")

    total_inserted = 0
    total_processed = 0

    for idx, symbol in enumerate(stocks):
        total_processed += 1

        for period, n in TARGET_PERIODS.items():
            max_dt = get_max_date(conn, symbol, period)
            rows = get_5m_data(conn, symbol, max_dt)
            if len(rows) < n:
                continue  # 不够n根，跳过
            agg = aggregate_5m_to(rows, n)
            if agg:
                inserted = save_period(conn, symbol, period, agg)
                total_inserted += inserted

        if (idx + 1) % 500 == 0:
            elapsed = time.time() - t0
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            print(f"  [{idx+1}/{len(stocks)}] +{total_inserted}行, {elapsed:.0f}s")

    conn.close()
    elapsed = time.time() - t0
    print(f"\n完成! 处理{total_processed}只, 新增{total_inserted}行, 耗时{elapsed:.1f}s")


if __name__ == '__main__':
    main()

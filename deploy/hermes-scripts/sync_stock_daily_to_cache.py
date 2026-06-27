#!/usr/bin/env python3
"""stock_daily → kline_cache 同步（daily_sync_full.sh Step 2 的独立脚本）

读取 stock_daily 表的今日数据，写入 kline_cache（source='stock_daily', period='daily'）。
每天增量写入，不覆盖已有数据。
"""
import sqlite3
import os
import sys
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")
TODAY = datetime.now().strftime("%Y-%m-%d")

db = sqlite3.connect(DB_PATH, timeout=30)
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=30000")
c = db.cursor()

c.execute(
    "SELECT symbol, date, open, high, low, close, volume, turnover FROM stock_daily WHERE date=?",
    (TODAY,)
)
rows = c.fetchall()
print(f"  stock_daily {TODAY} 共 {len(rows)} 条")

# 清理今日旧数据
c.execute("DELETE FROM kline_cache WHERE source='stock_daily' AND period='daily' AND trade_date=?", (TODAY,))
deleted = c.rowcount
print(f"  清理 kline_cache 旧数据: {deleted} 条")

# 插入
inserted = 0
for row in rows:
    symbol, date, o, h, l, cl, volume, turnover = row
    prefix = "SH." if symbol.startswith("6") else "SZ."
    full_sym = prefix + symbol
    try:
        c.execute(
            "INSERT OR IGNORE INTO kline_cache "
            "(symbol, source, period, trade_date, open, close, high, low, volume, amount, name) "
            "VALUES (?, 'stock_daily', 'daily', ?, ?, ?, ?, ?, ?, ?, '')",
            (full_sym, date, o, cl, h, l, int(volume), int(turnover))
        )
        if c.rowcount > 0:
            inserted += 1
    except Exception as e:
        print(f"    错误: {full_sym}: {e}")

db.commit()
db.close()
print(f"  新增: {inserted} 条")

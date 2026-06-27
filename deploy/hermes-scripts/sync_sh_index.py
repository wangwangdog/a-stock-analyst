#!/usr/bin/env python3
"""同步上证指数 SH.000001 日线数据（daily_sync_full.sh Step 3 的独立脚本）"""
import sqlite3, os, sys
import akshare as ak
from datetime import datetime

DB = os.environ.get("DB_PATH", "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")
TODAY = datetime.now().strftime("%Y-%m-%d")

conn = sqlite3.connect(DB, timeout=30)
conn.execute("PRAGMA journal_mode=WAL")
c = conn.cursor()

# 检查今日是否已有数据
has = c.execute(
    "SELECT 1 FROM kline_cache WHERE symbol='SH.000001' AND period='daily' AND trade_date=?",
    (TODAY,)
).fetchone()

if has:
    print(f"  SH.000001 {TODAY} 已有数据，跳过")
    conn.close()
    sys.exit(0)

try:
    df = ak.stock_zh_index_daily(symbol="sh000001")
    last = df.iloc[-1]
    dt = str(last["date"])[:10]
    if dt == TODAY:
        o, h, l, cl = float(last["open"]), float(last["high"]), float(last["low"]), float(last["close"])
        v = int(last["volume"])
        c.execute(
            "INSERT OR REPLACE INTO kline_cache "
            "(symbol, source, period, trade_date, open, close, high, low, volume, amount, name) "
            "VALUES ('SH.000001', 'akshare', 'daily', ?, ?, ?, ?, ?, ?, 0, '上证指数')",
            (dt, o, cl, h, l, v)
        )
        conn.commit()
        print(f"  SH.000001 {dt} close={cl} ✅")
    else:
        print(f"  AKShare最新日期 {dt} != 今日 {TODAY}（可能非交易日），跳过")
except Exception as e:
    print(f"  [warn] SH.000001 增量失败: {e}")

conn.close()

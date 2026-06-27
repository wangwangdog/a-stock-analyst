#!/usr/bin/env python3
"""TDX补拉缺失日线"""
import os, sys, sqlite3, time
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.openclaw/workspace/cl-vendors/chanlun-pro/src'))
from chanlun.exchange.exchange_tdx import ExchangeTDX

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
TARGET_DAYS = ('2026-05-29', '2026-06-01', '2026-06-02')

ex = ExchangeTDX()
c = sqlite3.connect(DB, timeout=60)
c.execute("PRAGMA busy_timeout=60000")

# 从已有5m数据获取全部股票列表
symbols = [r[0] for r in c.execute(
    "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' AND trade_date LIKE '2026-05-28%'"
).fetchall()]
print(f"共 {len(symbols)} 只", flush=True)

total = 0
for i, sym in enumerate(symbols):
    code = sym.split('.')[-1]
    try:
        df = ex.klines(code, 'd')
    except:
        continue
    if df is None or df.empty:
        continue
    for _, row in df.iterrows():
        td = str(row['date'])[:10]
        if td not in TARGET_DAYS:
            continue
        vol_val = row.get('volume', 0) * 100000000 if row.get('volume', 0) < 1000000 else row.get('volume', 0)
        c.execute(
            "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sym, 'tdx', 'daily', td, float(row['open']), float(row['close']),
             float(row['high']), float(row['low']), float(row['volume']), float(row.get('amount', 0)))
        )
        total += 1
    if (i+1) % 500 == 0:
        c.commit()
        print(f"  [{i+1}/{len(symbols)}] +{total}行", flush=True)

c.commit()
c.close()
print(f"完成! +{total}行", flush=True)

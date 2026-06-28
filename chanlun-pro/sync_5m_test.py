#!/usr/bin/env python3
"""快测腾讯5m接口"""
import os, time, sqlite3, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"

def fetch_one(symbol):
    pref = "sh" if symbol.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{symbol},m5,,320"
    try:
        r = urllib.request.urlopen(url, timeout=8)
        data = json.loads(r.read())
    except Exception as e:
        return (symbol, [])
    klines = data.get("data", {}).get(f"{pref}{symbol}", {}).get("m5", [])
    if not klines:
        return (symbol, [])
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        if td < "2026-05-28":
            continue
        rows.append((symbol, "tencent", "5m", td,
                     float(item[1]), float(item[2]),
                     float(item[3]), float(item[4]),
                     float(item[5]), float(item[7]) if len(item) > 7 else 0.0))
    return (symbol, rows)

t0 = time.time()
c = sqlite3.connect(DB, timeout=30)
stale = [r[0] for r in c.execute(
    "SELECT symbol FROM kline_cache WHERE period='5m' "
    "GROUP BY symbol HAVING MAX(trade_date) < '2026-06-02' LIMIT 100"
).fetchall()]
c.close()
print(f"测试 {len(stale)} 只", flush=True)

total_rows = 0
with ThreadPoolExecutor(max_workers=8) as pool:
    for symbol, rows in pool.map(fetch_one, stale):
        if rows:
            c2 = sqlite3.connect(DB, timeout=30)
            c2.execute("PRAGMA busy_timeout=60000")
            c2.executemany(INS, rows)
            c2.commit()
            c2.close()
            total_rows += len(rows)
        print(f"  {symbol}: {len(rows)}行", flush=True)

el = time.time() - t0
print(f"完成 +{total_rows}行 {el:.1f}s", flush=True)

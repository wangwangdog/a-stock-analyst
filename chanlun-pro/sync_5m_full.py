#!/usr/bin/env python3
"""全量增量补5m - 腾讯API 8线程 + as_completed"""
import os, time, sqlite3, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"
CUTOFF = "2026-05-28"

def fetch_one(symbol):
    pref = "sh" if symbol.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{symbol},m5,,320"
    try:
        r = urllib.request.urlopen(url, timeout=8)
        data = json.loads(r.read())
    except:
        return (symbol, [])
    try:
        klines = data.get("data", {}).get(f"{pref}{symbol}", {}).get("m5", [])
    except AttributeError:
        return (symbol, [])
    if not isinstance(klines, list) or not klines:
        return (symbol, [])
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        if td < CUTOFF:
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
    "GROUP BY symbol HAVING MAX(trade_date) < '2026-06-02'"
).fetchall()]
c.close()
n = len(stale)
print(f"{n}只", flush=True)

all_rows = []
done = total_rows = 0
BATCH = 30000

with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(fetch_one, s): s for s in stale}
    for fut in as_completed(futures):
        done += 1
        symbol, rows = fut.result()
        if rows:
            all_rows.extend(rows)
            total_rows += len(rows)
        if len(all_rows) >= BATCH:
            c2 = sqlite3.connect(DB, timeout=60)
            c2.execute("PRAGMA busy_timeout=60000")
            c2.executemany(INS, all_rows)
            c2.commit()
            c2.close()
            all_rows = []
        if done % 300 == 0:
            el = time.time() - t0
            rate = done / el
            eta = (n - done) / rate if rate > 0 else 0
            print(f"[{done}/{n}] +{total_rows}行 {el:.0f}s ETA:{eta:.0f}s", flush=True)

if all_rows:
    c2 = sqlite3.connect(DB, timeout=60)
    c2.execute("PRAGMA busy_timeout=60000")
    c2.executemany(INS, all_rows)
    c2.commit()
    c2.close()

el = time.time() - t0
print(f"完成! {done}只 +{total_rows}行 {el:.0f}s ETA正", flush=True)

# 验证
c3 = sqlite3.connect(DB, timeout=30)
cnt = c3.execute("SELECT COUNT(*) FROM kline_cache WHERE period='5m' AND trade_date >= '2026-05-28'").fetchone()[0]
c3.close()
print(f"5m >= 05-28 共 {cnt} 行", flush=True)

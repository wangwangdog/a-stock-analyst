#!/usr/bin/env python3
"""
补齐 5m 分钟级数据中缺失的 2026-06-04、2026-06-05 交易日。
"""
import os, sys, sqlite3, json, urllib.request, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"
N_WORKERS = 4
TARGET_DAYS = ("2026-06-04", "2026-06-05")

def now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_missing_symbols(c):
    has_03 = set(r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' AND trade_date LIKE '2026-06-03%'"
    ).fetchall())
    has_04 = set(r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' AND trade_date LIKE '2026-06-04%'"
    ).fetchall())
    has_05 = set(r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' AND trade_date LIKE '2026-06-05%'"
    ).fetchall())
    missing_04 = sorted(has_03 - has_04)
    missing_05 = sorted(has_04 - has_05)
    print(f"06-03: {len(has_03)}  06-04: {len(has_04)}  06-05: {len(has_05)}", flush=True)
    print(f"缺06-04: {len(missing_04)}  缺06-05: {len(missing_05)}", flush=True)
    return missing_04 + missing_05

def fetch_tencent(symbol):
    raw_code = symbol.split(".")[-1]
    if symbol.startswith(("SH.", "sh.")): pref = "sh"
    elif symbol.startswith(("SZ.", "sz.")): pref = "sz"
    elif symbol.startswith(("BJ.", "bj.")): pref = "sz"
    else: pref = "sh" if raw_code.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},m5,,480"
    try:
        r = urllib.request.urlopen(url, timeout=10)
        data = json.loads(r.read())
    except:
        return (symbol, [])
    try:
        klines = data.get("data", {}).get(f"{pref}{raw_code}", {}).get("m5", [])
    except AttributeError:
        return (symbol, [])
    if not isinstance(klines, list) or not klines:
        return (symbol, [])
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        if td[:10] not in TARGET_DAYS:
            continue
        vol_val = float(item[7]) * 100_000_000 if len(item) > 7 else 0.0
        rows.append((symbol, "tencent", "5m", td,
                     float(item[1]), float(item[2]),
                     float(item[3]), float(item[4]),
                     vol_val, vol_val))
    return (symbol, rows)

def main():
    c = sqlite3.connect(DB, timeout=60)
    c.execute("PRAGMA busy_timeout=60000")
    symbols = get_missing_symbols(c)
    c.close()
    if not symbols:
        print("无需补齐"); return
    n = len(symbols)
    print(f"[{now_s()}] 开始补齐 {n} 只...", flush=True)
    all_rows = []; done = 0; total_rows = 0; t0 = time.time()
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(fetch_tencent, s): s for s in symbols}
        for fut in as_completed(futures):
            done += 1
            _, rows = fut.result()
            if rows:
                all_rows.extend(rows)
                total_rows += len(rows)
            if len(all_rows) >= 20000:
                c2 = sqlite3.connect(DB, timeout=60)
                c2.execute("PRAGMA busy_timeout=60000")
                c2.executemany(INS, all_rows); c2.commit(); c2.close()
                all_rows = []
            if done % 200 == 0:
                el = time.time() - t0
                eta = ((n - done) / (done / el)) if done > 0 else 0
                print(f"  [{done}/{n}] +{total_rows}行 {el:.0f}s ETA:{eta:.0f}s", flush=True)
    if all_rows:
        c2 = sqlite3.connect(DB, timeout=60)
        c2.execute("PRAGMA busy_timeout=60000")
        c2.executemany(INS, all_rows); c2.commit(); c2.close()
    el = time.time() - t0
    print(f"[{now_s()}] 完成: {n}只, +{total_rows}行 {el:.0f}s", flush=True)

if __name__ == '__main__':
    main()

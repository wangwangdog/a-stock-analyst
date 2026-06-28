#!/usr/bin/env python3
"""补拉5月26日、27日的5m数据（仅这两天，快速）"""
import os, time, sqlite3, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"
N_WORKERS = 10

# 只保留这两天的记录
TARGET_DAYS = ("2026-05-26", "2026-05-27")

def fetch_one(symbol):
    raw_code = symbol.split(".")[-1]
    if symbol.startswith(("SH.", "sh.")): pref = "sh"
    elif symbol.startswith(("SZ.", "sz.")): pref = "sz"
    else: pref = "sh" if raw_code.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},m5,,480"
    try:
        r = urllib.request.urlopen(url, timeout=6)
        data = json.loads(r.read())
        klines = data.get("data", {}).get(f"{pref}{raw_code}", {}).get("m5", [])
    except:
        return (symbol, 0)
    if not isinstance(klines, list) or not klines:
        return (symbol, 0)
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        day = td[:10]
        if day not in TARGET_DAYS:
            continue
        vol_val = float(item[7]) * 100_000_000 if len(item) > 7 else 0.0
        rows.append((symbol, "tencent", "5m", td,
                     float(item[1]), float(item[2]),
                     float(item[3]), float(item[4]),
                     vol_val, vol_val))
    if rows:
        c = sqlite3.connect(DB, timeout=30)
        c.execute("PRAGMA busy_timeout=60000")
        c.executemany(INS, rows)
        c.commit()
        c.close()
    return (symbol, len(rows))

def main():
    c = sqlite3.connect(DB, timeout=30)
    # 所有有5m数据的股票
    symbols = [r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m'"
    ).fetchall()]
    c.close()
    print(f"共 {len(symbols)} 只股票", flush=True)

    done = total = t0 = time.time()
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(fetch_one, s): s for s in symbols}
        for fut in as_completed(futures):
            done += 1
            sym, n = fut.result()
            total += n
            if done % 500 == 0:
                el = time.time() - t0
                print(f"  [{done}/{len(symbols)}] +{total}行 {el:.0f}s", flush=True)

    el = time.time() - t0
    print(f"完成! {done}只, +{total}行, {el:.1f}s", flush=True)

if __name__ == "__main__":
    main()

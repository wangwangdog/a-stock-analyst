#!/usr/bin/env python3
"""超快增量补5m - 腾讯API(urllib)+8线程并行"""
import sys, os, time, sqlite3, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"
N_WORKERS = 8

def get_stale():
    c = sqlite3.connect(DB, timeout=30)
    stale = [r[0] for r in c.execute(
        "SELECT symbol FROM kline_cache WHERE period='5m' "
        "GROUP BY symbol HAVING MAX(trade_date) < '2026-06-02'"
    ).fetchall()]
    c.close()
    return stale

def fetch_one(symbol):
    pref = "sh" if symbol.startswith(('6','688','900','7')) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{symbol},m5,,320"
    try:
        r = urllib.request.urlopen(url, timeout=8)
        data = json.loads(r.read())
    except:
        return []
    klines = data.get('data', {}).get(f"{pref}{symbol}", {}).get('m5', [])
    if not klines:
        return []
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        if td < '2026-05-28':
            continue
        rows.append((symbol, 'tencent', '5m', td,
                     float(item[1]), float(item[2]),
                     float(item[3]), float(item[4]),
                     float(item[5]), float(item[7]) if len(item) > 7 else 0.0))
    return rows

def main():
    t0 = time.time()
    stale = get_stale()
    print(f"需更新: {len(stale)}只", flush=True)
    all_rows = []
    done = total_rows = 0

    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(fetch_one, s): s for s in stale}
        for fut in as_completed(futures):
            rows = fut.result()
            done += 1
            if rows:
                all_rows.extend(rows)
                total_rows += len(rows)

            if len(all_rows) >= 20000:
                c = sqlite3.connect(DB, timeout=60)
                c.execute("PRAGMA busy_timeout=60000")
                try:
                    c.executemany(INS, all_rows)
                    c.commit()
                finally:
                    c.close()
                all_rows = []

            if done % 300 == 0:
                el = time.time() - t0
                rate = done / el
                eta = (len(stale) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(stale)}] +{total_rows}行 {el:.0f}s ETA:{eta:.0f}s", flush=True)

    if all_rows:
        c = sqlite3.connect(DB, timeout=60)
        c.execute("PRAGMA busy_timeout=60000")
        try:
            c.executemany(INS, all_rows)
            c.commit()
        finally:
            c.close()

    el = time.time() - t0
    print(f"完成! {done}/{len(stale)}只, +{total_rows}行, {el:.0f}s", flush=True)

if __name__ == '__main__':
    main()

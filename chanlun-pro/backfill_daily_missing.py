#!/usr/bin/env python3
"""补拉特定日期日线数据"""
import os, time, sqlite3, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"
N_WORKERS = 10

# 从05-28的已有数据获取需要补的股票列表
c = sqlite3.connect(DB, timeout=30)
symbols = [r[0] for r in c.execute(
    "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND trade_date='2026-05-28'"
).fetchall()]
c.close()
print(f"共 {len(symbols)} 只需要补日线", flush=True)

def fetch_daily(symbol):
    """腾讯API拉日线"""
    raw_code = symbol.split(".")[-1]
    if symbol.startswith(("SH.", "sh.")): pref = "sh"
    elif symbol.startswith(("SZ.", "sz.")): pref = "sz"
    else: pref = "sh" if raw_code.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},day,,480"
    try:
        r = urllib.request.urlopen(url, timeout=6)
        data = json.loads(r.read())
        klines = data.get("data", {}).get(f"{pref}{raw_code}", {}).get("day", [])
    except:
        return (symbol, 0)
    if not isinstance(klines, list) or not klines:
        return (symbol, 0)
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]}"
        # 只补缺失的日期
        if td not in ("2026-05-29", "2026-06-01", "2026-06-02"):
            continue
        vol_val = float(item[7]) * 100_000_000 if len(item) > 7 else 0.0
        rows.append((symbol, "tencent", "daily", td,
                     float(item[1]), float(item[2]),
                     float(item[3]), float(item[4]),
                     vol_val, vol_val))
    if rows:
        c2 = sqlite3.connect(DB, timeout=30)
        c2.execute("PRAGMA busy_timeout=60000")
        c2.executemany(INS, rows)
        c2.commit()
        c2.close()
    return (symbol, len(rows))

done = total = t0 = time.time()
with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
    futures = {pool.submit(fetch_daily, s): s for s in symbols}
    for fut in as_completed(futures):
        done += 1
        sym, n = fut.result()
        total += n
        if done % 500 == 0:
            el = time.time() - t0
            print(f"  [{done}/{len(symbols)}] +{total}行 {el:.0f}s", flush=True)

el = time.time() - t0
print(f"完成! {done}只, +{total}行, {el:.1f}s", flush=True)

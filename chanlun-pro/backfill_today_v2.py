#!/usr/bin/env python3
"""补齐今天日线数据（增量模式，使用 all_stock_info 获取股票列表）"""
import json, sqlite3, subprocess, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"
TODAY = "2026-06-10"
MAX_WORKERS = 20

def code_prefix(bare):
    if bare.startswith(("6","9","68")): return "SH"
    if bare.startswith(("0","3","002","200","300","301")): return "SZ"
    if bare.startswith(("8","4","920")): return "BJ"
    return ""

def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

conn = get_db()
stocks = conn.execute(
    "SELECT symbol FROM all_stock_info "
    "WHERE substr(symbol,1,1) IN ('0','3','6','9') "
    "ORDER BY symbol"
).fetchall()
conn.close()

stocks = [r[0] for r in stocks]
total = len(stocks)
print(f"📋 需补齐 {total} 只股票今天({TODAY})的数据...", flush=True)

def fetch_one(bare):
    prefix = code_prefix(bare)
    if not prefix:
        return (bare, False, "no_prefix")
    market = prefix.lower()
    tc = f"{market}{bare}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,,,5,qfq"
    try:
        ret = subprocess.run(["curl","-s",url], capture_output=True, text=True, timeout=15)
        d = json.loads(ret.stdout)
        sd = d.get("data",{}).get(tc,{})
        klines = sd.get("qfqday",[]) or sd.get("day",[])
        if not klines:
            return (bare, False, "no_data")
        today_k = None
        for k in klines:
            if k[0] == TODAY:
                today_k = k
                break
        if not today_k:
            return (bare, False, "no_today")
        o, c, h, l = float(today_k[1]), float(today_k[2]), float(today_k[3]), float(today_k[4])
        vh = float(today_k[5])
        vol_shares = int(vh * 100)
        qt = sd.get("qt",{}).get(tc,[])
        amt = 0
        for item in qt:
            if isinstance(item, str) and "/" in item and item.count("/") == 2:
                parts = item.split("/")
                try:
                    p, v, a = float(parts[0]), float(parts[1]), float(parts[2])
                    if abs(p - c) / max(c, 0.01) < 0.001:
                        amt = int(a)
                        break
                except: pass
        if amt == 0:
            amt = int(vh * 100 * ((o + c) / 2))
        return (bare, True, (prefix, TODAY, o, c, h, l, vol_shares, amt))
    except Exception as e:
        return (bare, False, str(e)[:50])

# 并发拉取
success = failed = 0
write_buffer = []
t_start = time.time()

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(fetch_one, code): code for code in stocks}
    for future in as_completed(futures):
        result = future.result()
        if result[1]:
            write_buffer.append(result)
            success += 1
        else:
            failed += 1

        # 批量写入 DB
        if len(write_buffer) >= 50:
            conn = get_db()
            for bare, ok, data in write_buffer:
                prefix = data[0]
                vals = data[1:]
                for sym in (bare, f"{prefix}.{bare}"):
                    conn.execute("DELETE FROM kline_cache WHERE symbol=? AND trade_date=? AND period='daily'", (sym, TODAY))
                    conn.execute(
                        "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                        "VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)",
                        (sym,) + vals
                    )
            conn.commit()
            conn.close()
            write_buffer = []

        done = success + failed
        if done % 500 == 0:
            elapsed = time.time() - t_start
            print(f"  [{done}/{total}] ✅{success} ❌{failed} 耗时{elapsed:.0f}s", flush=True)

# 最后一批
if write_buffer:
    conn = get_db()
    for bare, ok, data in write_buffer:
        prefix = data[0]
        vals = data[1:]
        for sym in (bare, f"{prefix}.{bare}"):
            conn.execute("DELETE FROM kline_cache WHERE symbol=? AND trade_date=? AND period='daily'", (sym, TODAY))
            conn.execute(
                "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)",
                (sym,) + vals
            )
    conn.commit()
    conn.close()

elapsed = time.time() - t_start
print(f"\n✅ 完成! 耗时{elapsed:.0f}s 成功:{success} 失败:{failed}", flush=True)

conn = get_db()
r = conn.execute("SELECT COUNT(*) FROM kline_cache WHERE trade_date=? AND period='daily'", (TODAY,)).fetchone()
print(f"验证: 今天({TODAY}) 共 {r[0]} 条记录", flush=True)
r = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE trade_date=? AND period='daily'", (TODAY,)).fetchone()
print(f"       {r[0]} 只股票", flush=True)
conn.close()

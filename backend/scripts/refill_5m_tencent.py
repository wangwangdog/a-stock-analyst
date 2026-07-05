#!/usr/bin/env python3
"""
批处理补齐历史 5m/15m/60m 数据
复用 cron_sync_minute_full.py 的核心逻辑，逐日回补
"""
import os, sys, time, json, sqlite3, urllib.request
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
N_WORKERS = 8
TARGET_DAYS = ["2026-06-08","2026-06-09","2026-06-10","2026-06-11","2026-06-12",
               "2026-06-15","2026-06-16","2026-06-17","2026-06-18",
               "2026-06-19","2026-06-22","2026-06-23","2026-06-24",
               "2026-06-25","2026-06-26","2026-06-29","2026-06-30"]
PERIOD_MAP = {"5m": "m5", "15m": "m15", "30m": "m30", "60m": "m60"}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_conn():
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-80000")
    return conn

def get_symbols(conn, trade_day):
    # 从全量 stock_daily 列表获取（不限定日期）
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol"
    ).fetchall()
    return [r[0] for r in rows]

def get_existing(conn, period, trade_day):
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE source='tencent' AND period=? AND trade_date LIKE ?||'%'",
        (period, trade_day)
    ).fetchall()
    return {r[0] for r in rows}

def fetch_one(symbol_raw, period, trade_day):
    raw_code = symbol_raw.split(".")[-1] if "." in symbol_raw else symbol_raw
    pref = "sh" if raw_code.startswith(("6","9")) else "sz"
    p = PERIOD_MAP[period]
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},{p},,480"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Accept":"*/*"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        klines = data.get("data",{}).get(f"{pref}{raw_code}",{}).get(p,[])
        if not klines:
            return []
        rows = []
        for item in klines:
            dt = str(item[0])
            td = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]} {dt[8:10]}:{dt[10:12]}:00"
            if not td.startswith(trade_day):
                continue
            v = float(item[7]) * 100_000_000 if len(item) > 7 else 0
            rows.append((symbol_raw,"tencent",period,td,float(item[1]),float(item[2]),float(item[3]),float(item[4]),v,v))
        return rows
    except:
        return []

def write_rows(conn, rows):
    if not rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()

def aggregate_5m_to(conn, symbols, trade_day, target_period, group_size):
    log(f"  5m→{target_period} 聚合...")
    done = 0
    for sym in symbols:
        rows = conn.execute(
            "SELECT trade_date,open,close,high,low,volume,amount FROM kline_cache "
            "WHERE symbol=? AND source='tencent' AND period='5m' AND trade_date>=? AND trade_date<? "
            "ORDER BY trade_date",
            (sym, trade_day, f"{trade_day}T23:59:59")
        ).fetchall()
        if not rows:
            continue
        agg = []
        for i in range(0, len(rows), group_size):
            chunk = rows[i:i+group_size]
            if len(chunk) < group_size:
                break
            agg.append((sym,"tencent",target_period,chunk[-1][0],
                        chunk[0][1],chunk[-1][2],
                        max(r[3] for r in chunk),min(r[4] for r in chunk),
                        sum(r[5] for r in chunk),sum(r[6] for r in chunk)))
        if agg:
            conn.executemany("INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)", agg)
        done += 1
        if done % 1000 == 0:
            conn.commit()
    conn.commit()
    log(f"  5m→{target_period}: {done}只 ✅")

def process_day(trade_day):
    log(f"\n{'='*50}")
    log(f"▶ {trade_day}")
    conn = get_conn()
    
    symbols = get_symbols(conn, trade_day)
    if not symbols:
        log(f"  stock_daily 无 {trade_day} 数据，跳过")
        conn.close()
        return
    log(f"  总股票: {len(symbols)}")
    
    # 5m
    existing = get_existing(conn, "5m", trade_day)
    missing = [s for s in symbols if s not in existing]
    log(f"  5m: 已有{len(existing)}, 缺{len(missing)}")
    
    if missing:
        all_rows = []
        done = 0
        with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
            futures = {pool.submit(fetch_one, s, "5m", trade_day): s for s in missing}
            for f in as_completed(futures):
                done += 1
                rows = f.result()
                if rows:
                    all_rows.extend(rows)
                if len(all_rows) >= 10000:
                    write_rows(conn, all_rows)
                    all_rows = []
                if done % 500 == 0:
                    log(f"  {trade_day} 5m: [{done}/{len(missing)}]")
        write_rows(conn, all_rows)
        
        after = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE source='tencent' AND period='5m' AND trade_date>=? AND trade_date<?",
            (trade_day, f"{trade_day}T23:59:59")
        ).fetchone()[0]
        log(f"  5m {trade_day}: {after}只 ✅")
    
    # 聚合 15m
    agg_symbols = get_symbols(conn, trade_day)
    aggregate_5m_to(conn, agg_symbols, trade_day, "15m", 3)
    
    # 聚合 60m
    aggregate_5m_to(conn, agg_symbols, trade_day, "60m", 12)
    
    conn.close()
    
    # 最终统计
    conn2 = get_conn()
    for p in ["5m","15m","60m"]:
        cnt = conn2.execute(
            "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE source='tencent' AND period=? AND trade_date>=? AND trade_date<?",
            (p, trade_day, f"{trade_day}T23:59:59")
        ).fetchone()[0]
        log(f"  {p}: {cnt}只")
    conn2.close()

def main():
    t0 = time.time()
    log(f"🚀 开始补齐 {len(TARGET_DAYS)} 天的 5m/15m/60m 数据")
    
    for day in TARGET_DAYS:
        process_day(day)
    
    log(f"\n🏁 全部完成! 耗时 {(time.time()-t0)/60:.1f}分")

if __name__ == "__main__":
    main()

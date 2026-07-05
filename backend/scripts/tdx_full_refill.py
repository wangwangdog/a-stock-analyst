#!/usr/bin/env python3
"""
全量 TDX 5m 数据获取 + 聚合 15m/30m/60m
每个线程独立 TDX 连接（线程安全），volume 手→股×100
"""
import sys, time, sqlite3
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pytdx.hq import TdxHq_API

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
N_WORKERS = 10
TDX_HOST = "180.153.18.170"
TDX_PORT = 7709

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_all_stocks():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol").fetchall()
    conn.close()
    return [str(r[0]).strip() for r in rows if r[0]]

def get_tdx_market(code):
    if code.startswith(('6','9')): return 1
    if code.startswith(('8','4')): return 2
    return 0

def fetch_one(code):
    """独立连接 TDX，拉取单只股票 5m 数据"""
    api = TdxHq_API()
    try:
        if not api.connect(TDX_HOST, TDX_PORT, time_out=10):
            return (code, [])
        market = get_tdx_market(code)
        all_bars = []
        for i in range(4):  # 4页，每页700条
            bars = api.get_security_bars(0, market, code, i * 700, 700)
            if not bars:
                break
            all_bars.extend(bars)
        api.disconnect()
        if not all_bars:
            return (code, [])
        rows = []
        for bar in all_bars:
            raw_dt = bar.get("datetime") or bar.get("time")
            if raw_dt is None:
                continue
            if hasattr(raw_dt, "strftime"):
                trade_date = raw_dt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                trade_date = str(raw_dt).strip()
            vol = float(bar.get("vol", 0) or 0) * 100  # 手→股
            amt = float(bar.get("amount", 0) or 0)
            rows.append((code, "tdx", "5m", trade_date,
                         float(bar.get("open", 0)),
                         float(bar.get("close", 0)),
                         float(bar.get("high", 0)),
                         float(bar.get("low", 0)),
                         vol, amt))
        return (code, rows)
    except:
        try:
            api.disconnect()
        except:
            pass
        return (code, [])

def save_batch(conn, rows):
    if not rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()

def aggregate(conn, period, group_size, t0):
    stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' AND source='tdx' ORDER BY symbol"
    ).fetchall()]
    log(f"5m→{period}: {len(stocks)} 只")
    done = 0
    for sym in stocks:
        rows = conn.execute(
            "SELECT trade_date,open,close,high,low,volume,amount FROM kline_cache "
            "WHERE symbol=? AND period='5m' AND source='tdx' ORDER BY trade_date",
            (sym,)
        ).fetchall()
        if not rows:
            continue
        agg = []
        for i in range(0, len(rows), group_size):
            chunk = rows[i:i+group_size]
            if len(chunk) < group_size:
                break
            agg.append((sym, "tdx", period, chunk[-1][0],
                        chunk[0][1], chunk[-1][2],
                        max(r[3] for r in chunk), min(r[4] for r in chunk),
                        sum(r[5] for r in chunk), sum(r[6] for r in chunk)))
        if agg:
            conn.executemany("INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)", agg)
        done += 1
        if done % 1000 == 0:
            conn.commit()
            log(f"  {period}: [{done}/{len(stocks)}]")
    conn.commit()
    log(f"✅ {period}: {done}只")

def main():
    all_stocks = get_all_stocks()
    log(f"📋 共 {len(all_stocks)} 只股票")
    t0 = time.time()

    # 1. 多线程拉取 5m（每个线程独立TDX连接）
    log("📊 开始拉取 5m（10线程，独立连接）...")
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=120000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    done, all_rows = 0, []
    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(fetch_one, c): c for c in all_stocks}
        for f in as_completed(futures):
            code, rows = f.result()
            done += 1
            if rows:
                all_rows.extend(rows)
            if len(all_rows) >= 20000:
                save_batch(conn, all_rows)
                all_rows = []
            if done % 200 == 0 or done == len(all_stocks):
                el = time.time() - t0
                log(f"  5m: [{done}/{len(all_stocks)}] {el:.0f}s")
    save_batch(conn, all_rows)

    el = time.time() - t0
    cnt = conn.execute("SELECT COUNT(*) FROM kline_cache WHERE period='5m' AND source='tdx'").fetchone()[0]
    stk = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period='5m' AND source='tdx'").fetchone()[0]
    log(f"✅ 5m 拉取完成! {el:.0f}s, {cnt}条, {stk}只")

    # 2. 聚合
    log("📊 开始聚合...")
    for p, g in [("15m", 3), ("30m", 6), ("60m", 12)]:
        aggregate(conn, p, g, t0)
    conn.close()

    # 3. 最终统计
    conn = sqlite3.connect(DB)
    for p in ["5m","15m","30m","60m"]:
        c = conn.execute("SELECT COUNT(*) FROM kline_cache WHERE period=? AND source='tdx'", (p,)).fetchone()[0]
        s = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period=? AND source='tdx'", (p,)).fetchone()[0]
        log(f"  {p}: {c}条, {s}只")
    conn.close()

    total = time.time() - t0
    log(f"\n🏁 全部完成! {total:.0f}s ({total/60:.1f}分)")

if __name__ == "__main__":
    main()

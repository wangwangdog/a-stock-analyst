#!/usr/bin/env python3
"""
TDX (通达信) 数据快速回填 v2

分两步：多线程拉取 → 单线程批量写入，避免 SQLite 锁冲突。

用法：
    python scripts/tdx_backfill.py
"""

import sys
import sqlite3
import argparse
import time as _time
from pathlib import Path
from datetime import datetime

# chanlun-pro 依赖
cl_site = Path.home() / ".openclaw" / "workspace" / "cl-vendors" / "chanlun-pro" / ".venv" / "lib" / "python3.11" / "site-packages"
cl_src = Path.home() / ".openclaw" / "workspace" / "cl-vendors" / "chanlun-pro" / "src"
for p in [str(cl_site), str(cl_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)

DB = str(Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite"))

MARKET_SH = 1
MARKET_SZ = 0
CAT_DAILY = 9
N_WORKERS = 8
BATCH = 200  # 每线程一次取多少只


def get_stocks() -> list:
    from chanlun.exchange.exchange_tdx import ExchangeTDX
    ex = ExchangeTDX()
    out = []
    for s in ex.all_stocks():
        if s.get("type") != "stock_cn":
            continue
        c = s["code"]
        if c.startswith("SH."):
            out.append((c[3:], MARKET_SH))
        elif c.startswith("SZ."):
            out.append((c[3:], MARKET_SZ))
    return out


def get_last_trading_date() -> str:
    from chanlun.exchange.exchange_tdx import ExchangeTDX
    ex = ExchangeTDX()
    k = ex.klines('SH.000001', 'd')
    if k is None or len(k) == 0:
        return ""
    return str(k["date"].iloc[-1])[:10]


def worker(stock_chunk, tgt):
    """线程：只拉取数据，不写库"""
    from pytdx.hq import TdxHq_API
    api = TdxHq_API(raise_exception=True, auto_retry=True)
    out = []
    ok = 0
    fail = 0
    for sym, mkt in stock_chunk:
        try:
            with api.connect("123.60.70.228", 7709, time_out=1.5):
                bars = api.get_security_bars(CAT_DAILY, mkt, sym, 0, 7)
                if bars is None:
                    fail += 1
                    continue
                df = api.to_df(bars)
                if df is None or df.empty:
                    fail += 1
                    continue
                for _, r in df.iterrows():
                    dt = str(r.get("datetime", ""))[:10]
                    if dt == tgt:
                        close = float(r.get("close", 0))
                        if close == 0.0:
                            break
                        out.append((
                            sym, dt,
                            float(r.get("open", 0)),
                            float(r.get("high", 0)),
                            float(r.get("low", 0)),
                            close,
                            float(r.get("vol", 0) or 0),
                            float(r.get("amount", 0) or 0),
                        ))
                        ok += 1
                        break
        except Exception:
            fail += 1
    return out, ok, fail


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--workers", type=int, default=N_WORKERS)
    parser.add_argument("--batch", type=int, default=BATCH)
    args = parser.parse_args()

    print(f"{'='*50}", flush=True)
    print(f"🚀 TDX 数据回填 v2", flush=True)

    stocks = get_stocks()
    print(f"📡 股票: {len(stocks)} 只", flush=True)

    tgt = args.date or get_last_trading_date()
    print(f"📅 目标: {tgt}", flush=True)

    # 状态模式
    if args.status:
        conn = sqlite3.connect(DB, timeout=10)
        sd = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", (tgt,)).fetchone()[0]
        kc = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE trade_date=? AND period='daily'", (tgt,)).fetchone()[0]
        conn.close()
        print(f"📊 stock_daily[{tgt}]: {sd}, kline_cache[{tgt}]: {kc}")
        return

    # 检查已有
    conn = sqlite3.connect(DB, timeout=10)
    existing = set(r[0] for r in conn.execute(
        "SELECT symbol FROM stock_daily WHERE date=?", (tgt,)).fetchall())
    conn.close()
    print(f"📦 已有: {len(existing)} / {len(stocks)}", flush=True)

    # 只取缺失的
    to_fetch = [(s, m) for s, m in stocks if s not in existing]
    print(f"📦 待补: {len(to_fetch)} 只", flush=True)

    if not to_fetch:
        print("✅ 全齐了", flush=True)
        return

    # 分片
    chunks = [to_fetch[i:i+args.batch] for i in range(0, len(to_fetch), args.batch)]
    print(f"📦 {len(chunks)} 分片, {args.workers} 线程", flush=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    t0 = _time.time()
    all_rows = []
    total_ok = 0
    total_fail = 0

    with ThreadPoolExecutor(max_workers=args.workers) as exe:
        futs = {exe.submit(worker, c, tgt): i for i, c in enumerate(chunks)}

        for f in as_completed(futs):
            rows, ok, fail = f.result()
            all_rows.extend(rows)
            total_ok += ok
            total_fail += fail
            if (len(all_rows) // 500) > 0 and len(all_rows) % 500 < 50:
                rate = len(all_rows) / (_time.time() - t0) if _time.time() > t0 else 0
                print(f"  已取 {len(all_rows)} 条 ({rate:.0f}/s), 失败 {total_fail}", flush=True)

    elapsed = _time.time() - t0
    print(f"\n✅ 拉取完成: {total_ok} 成功, {total_fail} 失败, {elapsed:.0f}s", flush=True)

    if not all_rows:
        print("❌ 没有数据可写入", flush=True)
        return

    # 批量写入
    print(f"\n📝 写入数据库...", flush=True)
    wconn = sqlite3.connect(DB, timeout=60)
    wconn.execute("PRAGMA synchronous=OFF")
    wconn.execute("PRAGMA journal_mode=WAL")
    wconn.execute("PRAGMA busy_timeout=30000")

    # stock_daily
    sd_data = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]) for r in all_rows]
    wconn.executemany(
        "INSERT OR IGNORE INTO stock_daily (symbol,date,open,high,low,close,volume,turnover) VALUES (?,?,?,?,?,?,?,?)",
        sd_data
    )
    # kline_cache
    kc_data = [(r[0], 'tdx', 'daily', r[1], r[2], r[5], r[3], r[4], r[6], r[7]) for r in all_rows]
    wconn.executemany(
        "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
        kc_data
    )
    wconn.commit()
    wconn.close()

    print(f"✅ 写入完成: {len(sd_data)} 条 (stock_daily + kline_cache)", flush=True)

    # 验证
    vconn = sqlite3.connect(DB, timeout=10)
    sd_final = vconn.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", (tgt,)).fetchone()[0]
    kc_final = vconn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE trade_date=? AND period='daily'", (tgt,)).fetchone()[0]
    vconn.close()
    print(f"📊 验证[{tgt}]: stock_daily={sd_final}, kline_cache={kc_final}", flush=True)


if __name__ == "__main__":
    main()

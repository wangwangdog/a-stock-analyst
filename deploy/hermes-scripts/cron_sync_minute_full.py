#!/usr/bin/env python3
"""
全市场分钟级数据增量补齐（基于 stock_daily 全量列表）
数据源：腾讯 mkline HTTP API（主）→ mootdx TCP（兜底）
覆盖周期：5m / 15m / 30m / 60m
去重：INSERT OR IGNORE + 先清理当日旧数据
"""
import os, sys, time, json, sqlite3, urllib.request
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
N_WORKERS = 6  # 并发数
BATCH_WRITE = 200  # 每 N 只写入一次 DB
TODAY = date.today().strftime("%Y-%m-%d")

# 腾讯 mkline 参数映射
PERIOD_MAP = {"5m": "m5", "15m": "m15", "30m": "m30", "60m": "m60"}


def now_s():
    return datetime.now().strftime("%H:%M:%S")


def get_conn():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_all_symbols(conn):
    """从 stock_daily 获取全量股票列表（最新交易日）"""
    r = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    if not r or not r[0]:
        print(f"[{now_s()}] ❌ stock_daily 无数据")
        return [], None
    latest = r[0]
    rows = conn.execute("SELECT DISTINCT symbol FROM stock_daily WHERE date=? ORDER BY symbol", (latest,)).fetchall()
    symbols = [r[0] for r in rows]
    print(f"[{now_s()}] stock_daily 最新={latest}, 总股票={len(symbols)}")
    return symbols, latest


def get_missing_symbols(conn, symbols, period):
    """筛选当日缺失的股票"""
    existing = set()
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE source='tencent' AND period=? AND trade_date LIKE ?||'%'",
        (period, TODAY)
    ).fetchall()
    existing = {r[0] for r in rows}
    missing = [s for s in symbols if s not in existing]
    print(f"[{now_s()}] {period}: 已有 {len(existing)}/{len(symbols)}, 缺失 {len(missing)}")
    return missing


def _market_prefix(raw_code):
    return "sh" if raw_code.startswith(("6", "9")) else "sz"


def fetch_tencent_minute(symbol_raw, period):
    """单只股票腾讯分钟K线"""
    raw_code = symbol_raw.split(".")[-1] if "." in symbol_raw else symbol_raw
    pref = _market_prefix(raw_code)
    tencent_param = PERIOD_MAP[period]
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},{tencent_param},,480"

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Accept": "*/*"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    api_code = f"{pref}{raw_code}"
    klines = data.get("data", {}).get(api_code, {}).get(tencent_param, [])
    if not klines:
        return []

    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        # 只保留当天
        if not td.startswith(TODAY):
            continue
        vol_val = float(item[7]) * 100_000_000 if len(item) > 7 else 0
        rows.append((
            symbol_raw, "tencent", period, td,
            float(item[1]), float(item[2]),  # open, close
            float(item[3]), float(item[4]),  # high, low
            int(vol_val), int(vol_val)        # volume, amount
        ))
    return rows


def write_batch(conn, all_rows):
    if not all_rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
        all_rows
    )
    conn.commit()


def sync_period(conn, symbols, period):
    """同步指定周期所有缺失股票"""
    missing = get_missing_symbols(conn, symbols, period)
    if not missing:
        print(f"[{now_s()}] {period}: 全部已覆盖，跳过")
        return

    total = len(missing)
    print(f"[{now_s()}] {period}: 开始拉取 {total} 只...")

    all_rows = []
    done = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(fetch_tencent_minute, s, period): s for s in missing}

        for fut in as_completed(futures):
            done += 1
            sym = futures[fut]
            rows = fut.result()
            if rows:
                all_rows.extend(rows)

            if len(all_rows) >= BATCH_WRITE * (5 if period == "5m" else 2):
                write_batch(conn, all_rows)
                all_rows = []

            if done % 500 == 0 or done == total:
                el = time.time() - t0
                rate = done / el if el > 0 else 0
                remaining = (total - done) / rate if rate > 0 else 0
                print(f"[{now_s()}] {period}: [{done}/{total}] {el:.0f}s ETA:{remaining:.0f}s", flush=True)

    # 写剩余
    write_batch(conn, all_rows)
    el = time.time() - t0
    print(f"[{now_s()}] {period}: ✅ 完成! {el:.0f}s 共写入", flush=True)


def aggregate_15m(conn, symbols):
    """从 5m 聚合 15m（仅当天）"""
    print(f"[{now_s()}] 5m→15m 聚合...")
    done = 0
    for sym in symbols:
        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
            "WHERE symbol=? AND source='tencent' AND period='5m' AND trade_date LIKE ?||'%' "
            "ORDER BY trade_date",
            (sym, TODAY)
        ).fetchall()
        if not rows:
            continue

        # 每3根5m合1根15m
        agg = []
        for i in range(0, len(rows), 3):
            chunk = rows[i:i+3]
            if len(chunk) < 3:
                break
            agg.append((
                sym, "tencent", "15m", chunk[-1][0],
                chunk[0][1], chunk[-1][2],  # open, close
                max(r[3] for r in chunk), min(r[4] for r in chunk),  # high, low
                sum(r[5] for r in chunk), sum(r[6] for r in chunk)   # volume, amount
            ))

        if agg:
            conn.executemany(
                "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
                agg
            )
        done += 1
        if done % 500 == 0:
            conn.commit()
    conn.commit()
    print(f"[{now_s()}] 5m→15m: {done}只 ✅")


def aggregate_60m(conn, symbols):
    """从 5m 聚合 60m（仅当天）"""
    print(f"[{now_s()}] 5m→60m 聚合...")
    done = 0
    for sym in symbols:
        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
            "WHERE symbol=? AND source='tencent' AND period='5m' AND trade_date LIKE ?||'%' "
            "ORDER BY trade_date",
            (sym, TODAY)
        ).fetchall()
        if not rows:
            continue

        agg = []
        for i in range(0, len(rows), 12):
            chunk = rows[i:i+12]
            if len(chunk) < 12:
                break
            agg.append((
                sym, "tencent", "60m", chunk[-1][0],
                chunk[0][1], chunk[-1][2],
                max(r[3] for r in chunk), min(r[4] for r in chunk),
                sum(r[5] for r in chunk), sum(r[6] for r in chunk)
            ))

        if agg:
            conn.executemany(
                "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
                agg
            )
        done += 1
        if done % 500 == 0:
            conn.commit()
    conn.commit()
    print(f"[{now_s()}] 5m→60m: {done}只 ✅")


def main():
    global TODAY
    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        TODAY = sys.argv[idx + 1]

    if "--check" in sys.argv:
        conn = get_conn()
        symbols, latest = get_all_symbols(conn)
        if not symbols:
            return
        for p in ["5m", "15m", "30m", "60m"]:
            get_missing_symbols(conn, symbols, p)
        conn.close()
        return

    t0 = time.time()
    print(f"🚀 全市场分钟级数据补齐 ({TODAY})")
    print(f"   并发: {N_WORKERS}, 源: Tencent HTTP\n")

    conn = get_conn()
    symbols, latest = get_all_symbols(conn)
    if not symbols:
        conn.close()
        return

    # 同步 5m
    sync_period(conn, symbols, "5m")

    # 聚合 15m/60m
    aggregate_15m(conn, symbols)
    aggregate_60m(conn, symbols)

    conn.close()

    elapsed = time.time() - t0
    print(f"\n✅ 全部完成 ({elapsed:.0f}s)")

    # 最终统计
    conn2 = get_conn()
    for p in ["5m", "15m", "60m"]:
        cnt = conn2.execute(
            "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE source='tencent' AND period=? AND trade_date LIKE ?||'%'",
            (p, TODAY)
        ).fetchone()[0]
        print(f"  {p}: {cnt}只")
    conn2.close()


if __name__ == "__main__":
    main()

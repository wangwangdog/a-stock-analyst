#!/usr/bin/env python3
"""
TDX 分钟线增量更新（替代 AKShare/Baostock）
盘后补齐 15min/30min/60min
盘中运行（5并发）只补当日数据
"""
import sys, sqlite3, time, socket
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pytdx.hq import TdxHq_API

socket.setdefaulttimeout(15)

DB_PATH = Path('/home/dogzi/sqlite-data/chanlun_klines.sqlite')
TDX_SERVERS = [
    ('180.153.18.170', 7709),
    ('180.153.18.171', 7709),
]

FREQ_CONFIG = {
    '5min':  {'cat': 0, 'bars_per_day': 48},
    '15min': {'cat': 1, 'bars_per_day': 16},
    '30min': {'cat': 2, 'bars_per_day': 8},
    '60min': {'cat': 3, 'bars_per_day': 4},
}


def get_stocks():
    conn = sqlite3.connect(str(DB_PATH))
    stocks = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()]
    conn.close()
    return stocks


def get_missing_dates(period, last_dates_set):
    """确定需要补充的交易日"""
    today = date.today()
    # 找全局最新
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT MAX(substr(trade_date,1,10)) FROM kline_cache WHERE period=?",
        (period,)
    ).fetchone()
    conn.close()

    # 如果返回列名字符串（无数据）或空，则使用默认日期
    last_date = row[0] if row[0] and row[0] != 'trade_date' else (today - timedelta(days=5)).strftime("%Y-%m-%d")
    last_d = date.fromisoformat(last_date)

    missing = []
    d = last_d + timedelta(days=1)
    while d <= today:
        if d.weekday() < 5:
            missing.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return missing


def fetch_minute(symbol, period, cat, target_dates, is_intraday, workers):
    """分钟线获取"""
    ip, port = TDX_SERVERS[0]
    market = 0 if symbol.startswith(('0', '3')) else 1
    try:
        api = TdxHq_API(multithread=True)
        if not api.connect(ip, port, time_out=8):
            return []
        # 盘中只拉少量，盘后拉多一些
        count = 200 if is_intraday else 400
        klines = api.get_security_bars(cat, market, symbol, 0, count)
        api.disconnect()
        rows = []
        if klines:
            for k in klines:
                dt = str(k['datetime'])
                date_part = dt[:10]
                if date_part in target_dates:
                    rows.append((
                        symbol, 'tdx', period, dt,
                        float(k['open']), float(k['close']),
                        float(k['high']), float(k['low']),
                        int(k['vol']), float(k['amount'])
                    ))
        return rows
    except:
        return []


def sync_period(period, cfg, stocks, is_intraday=False):
    """同步一个周期"""
    target_dates = get_missing_dates(period, set())
    if not target_dates:
        print(f"  {period}: ✅ 无需更新")
        return

    target_set = set(target_dates)
    workers = 5 if is_intraday else 10

    print(f"  {period}: 补充 {len(target_dates)} 个交易日 ({target_dates[0]}~{target_dates[-1]})")
    all_rows = []
    done = 0
    submitted = 0
    t0 = time.time()
    BATCH_INTERVAL = 0.3

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for sym in stocks:
            futures.append(pool.submit(fetch_minute, sym, period, cfg['cat'], target_set, is_intraday, 2))
            time.sleep(BATCH_INTERVAL)
            submitted += 1
            if submitted % 500 == 0:
                elapsed = time.time() - t0
                print(f"    [{submitted}/{len(stocks)}] 提交中 ({elapsed:.0f}s)")
        for f in as_completed(futures):
            rows = f.result()
            if rows:
                all_rows.extend(rows)
            done += 1
            if done % 1000 == 0:
                print(f"    [{done}/{len(stocks)}] 完成, found={len(all_rows)}")

    print(f"    {period}: 共 {len(all_rows)} 行 (耗时 {time.time()-t0:.0f}s)")

    if all_rows:
        conn = sqlite3.connect(str(DB_PATH))
        for d in target_dates:
            conn.execute("DELETE FROM kline_cache WHERE period=? AND trade_date LIKE ?",
                         (period, f"{d}%"))
        conn.executemany(
            "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            all_rows
        )
        conn.commit()
        conn.close()
        print(f"    ✅ {period} 写入 {len(all_rows)} 行")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='TDX 分钟线增量更新')
    parser.add_argument('--mode', choices=['intraday', 'afterhours'], default='afterhours',
                        help='intraday=盘中5并发, afterhours=盘后10并发')
    args = parser.parse_args()

    is_intraday = args.mode == 'intraday'
    t0 = time.time()
    print(f"[{date.today()}] TDX 分钟线增量更新 (mode={args.mode})")

    stocks = get_stocks()
    print(f"股票数: {len(stocks)}")

    for period, cfg in FREQ_CONFIG.items():
        sync_period(period, cfg, stocks, is_intraday)

    # 验证
    conn = sqlite3.connect(str(DB_PATH))
    for period in FREQ_CONFIG:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM kline_cache WHERE period=?",
            (period,)
        ).fetchone()[0]
        print(f"  {period} 总行数: {cnt}")
    conn.close()

    print(f"✅ 完成 (总耗时 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
TDX 日线增量更新（替代 AKShare/Baostock）
盘后运行，补全 stock_daily + kline_cache
"""
import sys, sqlite3, time, socket, random
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pytdx.hq import TdxHq_API
import pandas as pd

socket.setdefaulttimeout(15)

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

DB_PATH = Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite'
TDX_SERVERS = [
    ('180.153.18.170', 7709),
    ('180.153.18.171', 7709),
]


def get_stocks():
    conn = sqlite3.connect(str(DB_PATH))
    stocks = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()]
    conn.close()
    return stocks


def get_missing_dates(stock_last_dates):
    """计算需要补的交易日 (上次更新到昨天的所有工作日)"""
    today = date.today()
    # 取全局最新
    last = max(stock_last_dates.values()) if stock_last_dates else today - timedelta(days=5)
    last_d = date.fromisoformat(last)

    missing = []
    d = last_d + timedelta(days=1)
    while d <= today:
        if d.weekday() < 5:  # 工作日
            missing.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return missing


def fetch_stock_daily(symbol, target_dates, server_idx=0):
    """获取单只股票在指定日期的日线"""
    ip, port = TDX_SERVERS[server_idx % len(TDX_SERVERS)]
    market = 0 if symbol.startswith(('0', '3')) else 1
    try:
        api = TdxHq_API(multithread=True)
        if api.connect(ip, port, time_out=8):
            klines = api.get_security_bars(4, market, symbol, 0, 10)
            api.disconnect()
            rows = []
            if klines:
                for k in klines:
                    dt = str(k['datetime'])[:10]
                    if dt in target_dates:
                        rows.append([
                            symbol, dt,
                            float(k['open']), float(k['high']),
                            float(k['low']), float(k['close']),
                            int(k['vol']), float(k['amount'])
                        ])
            return rows
    except:
        pass
    return []


def main():
    t0 = time.time()
    print(f"[{date.today()}] TDX 日线增量更新开始")

    stocks = get_stocks()
    print(f"股票数: {len(stocks)}")

    # 获取最新日期
    conn = sqlite3.connect(str(DB_PATH))
    stock_last = dict(conn.execute(
        "SELECT symbol, MAX(date) FROM stock_daily GROUP BY symbol"
    ).fetchall())
    conn.close()

    target_dates = get_missing_dates(stock_last)
    if not target_dates:
        print("✅ 无需更新")
        return

    print(f"需补充: {len(target_dates)} 个交易日 ({target_dates[0]} ~ {target_dates[-1]})")
    target_set = set(target_dates)

    all_rows = []
    submitted = 0
    BATCH_INTERVAL = 0.3  # 每提交一只股票间隔 0.3 秒
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        for sym in stocks:
            futures.append(pool.submit(fetch_stock_daily, sym, target_set))
            time.sleep(BATCH_INTERVAL)
            submitted += 1
            if submitted % 500 == 0:
                elapsed = time.time() - t0
                print(f"  [{submitted}/{len(stocks)}] 提交中 ({elapsed:.0f}s)")
        for f in as_completed(futures):
            rows = f.result()
            if rows:
                all_rows.extend(rows)

    print(f"总计: {len(all_rows)} 行 (耗时 {time.time()-t0:.0f}s)")

    if not all_rows:
        print("⚠ 没有新数据")
        return

    df = pd.DataFrame(all_rows, columns=[
        'symbol', 'date', 'open', 'high', 'low', 'close', 'volume', 'turnover'
    ])

    conn = sqlite3.connect(str(DB_PATH))
    for d in df['date'].unique():
        conn.execute("DELETE FROM stock_daily WHERE date = ?", (d,))
    conn.execute("DELETE FROM kline_cache WHERE period='daily' AND source='tdx'")
    for i in range(0, len(df), 500):
        chunk = df.iloc[i:i+500]
        chunk.to_sql("stock_daily", conn, if_exists="append", index=False, method=None)
    # 同步到 kline_cache
    cache_rows = []
    for _, r in df.iterrows():
        cache_rows.append((
            r['symbol'], 'tdx', 'daily', r['date'],
            r['open'], r['close'], r['high'], r['low'],
            r['volume'], r['turnover']
        ))
    conn.executemany(
        "INSERT OR REPLACE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        cache_rows
    )
    conn.commit()
    conn.close()

    dates = df['date'].unique().tolist()
    print(f"✅ 写入完成, 共 {len(dates)} 个交易日")
    for d in sorted(dates):
        cnt = len(df[df['date'] == d])
        print(f"   {d}: {cnt} 只股票")


if __name__ == "__main__":
    main()

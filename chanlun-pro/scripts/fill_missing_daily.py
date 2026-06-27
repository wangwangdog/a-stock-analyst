#!/usr/bin/env python3
"""
补齐个股日线数据缺失的交易日 (2026-05-29 ~ 2026-06-04)。
从 TDX 拉取个股 daily K线，写入 kline_cache source='tdx'。
"""
import sys, os, sqlite3, re, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from chanlun.exchange.exchange_tdx import ExchangeTDX

DB_PATH = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

MISSING_DATES = ['2026-05-29', '2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04']

def get_missing_stocks(conn):
    """获取在 baostock 有数据但在指定日期缺失的个股列表"""
    # 取 baostock 05-28 的全部股票（作为有交易历史的基准）
    cur = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND trade_date='2026-05-28' AND source='baostock'"
    )
    all_stocks = [row[0] for row in cur.fetchall()]
    print(f"基准股票数 (baostock 05-28): {len(all_stocks)}")

    # 过滤出在 TDX 也缺失的（不包含指数）
    needs = []
    for stock in all_stocks:
        # 检查是否任一缺失日期已有数据
        cur = conn.execute(
            "SELECT 1 FROM kline_cache WHERE symbol=? AND period='daily' AND trade_date IN ('{}') LIMIT 1".format(
                "','".join(MISSING_DATES)),
            (stock,)
        )
        if cur.fetchone() is None:
            needs.append(stock)
    print(f"需补齐的股票数: {len(needs)}")
    return needs

def tdx_code_from_bare(bare):
    """裸代码转 TDX 带前缀代码"""
    if bare.startswith('6') or bare.startswith('688'):
        return f"SH.{bare}"
    elif bare.startswith('8') or bare.startswith('4'):
        return f"BJ.{bare}"
    else:
        return f"SZ.{bare}"

def main():
    ex = ExchangeTDX()
    conn = sqlite3.connect(DB_PATH)

    missing = get_missing_stocks(conn)
    if not missing:
        print("无缺失数据需要补齐")
        return

    ok, fail = 0, 0
    batch_rows = []
    BATCH_SIZE = 200

    for i, bare_code in enumerate(missing):
        tdx_code = tdx_code_from_bare(bare_code)
        try:
            klines = ex.klines(tdx_code, 'd')
            if klines is None or len(klines) < 5:
                fail += 1
                continue
        except Exception:
            fail += 1
            continue

        for _, r in klines.iterrows():
            trade_date = str(r['date'])[:10]
            if trade_date not in MISSING_DATES:
                continue
            # 检查是否已有 tdx 数据（避免重复，但用 INSERT OR REPLACE 也可以）
            batch_rows.append((
                bare_code, 'tdx', 'daily', trade_date,
                float(r['open']), float(r['close']), float(r['high']), float(r['low']),
                float(r['volume']), 0.0
            ))

        ok += 1

        if len(batch_rows) >= BATCH_SIZE:
            conn.executemany(
                "INSERT OR REPLACE INTO kline_cache "
                "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch_rows
            )
            conn.commit()
            print(f"  [{i+1}/{len(missing)}] batch written ({len(batch_rows)} rows) ok={ok} fail={fail}")
            batch_rows = []

        if (i + 1) % 100 == 0:
            print(f"  progress: [{i+1}/{len(missing)}] ok={ok} fail={fail}")

    # 最后一批
    if batch_rows:
        conn.executemany(
            "INSERT OR REPLACE INTO kline_cache "
            "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch_rows
        )
        conn.commit()

    conn.close()
    print(f"\n完成: 成功={ok}, 失败={fail}")

if __name__ == '__main__':
    main()

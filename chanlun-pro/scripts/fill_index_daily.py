#!/usr/bin/env python3
"""
补齐指数（SH.000xxx, SZ.399xxx）的日线数据到 kline_cache。
从 TDX 拉取，写入 period='daily'。
"""
import sys, os, sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from chanlun.exchange.exchange_tdx import ExchangeTDX

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

def main():
    ex = ExchangeTDX()
    all_stocks = ex.all_stocks()
    # 只处理指数代码
    index_codes = [
        s['code'] for s in all_stocks
        if s['code'].startswith('SH.000') or s['code'].startswith('SZ.399')
    ]
    print(f"共 {len(index_codes)} 只指数")

    conn = sqlite3.connect(DB_PATH)

    ok, fail, skip = 0, 0, 0
    for i, code in enumerate(index_codes):
        # 检查是否已有足够的 daily 数据（>=50行）
        cnt_cur = conn.execute(
            "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period='daily'",
            (code,)
        ).fetchone()[0]
        if cnt_cur >= 50:
            skip += 1
            continue

        try:
            klines = ex.klines(code, 'd')
            if klines is None or len(klines) == 0:
                fail += 1
                continue
        except Exception:
            fail += 1
            continue

        # 批量插入
        rows = []
        for _, r in klines.iterrows():
            trade_date = str(r['date'])[:10]
            rows.append((
                code, 'tdx', 'daily', trade_date,
                float(r['open']), float(r['close']), float(r['high']), float(r['low']),
                float(r['volume']), 0.0
            ))

        conn.executemany(
            "INSERT OR REPLACE INTO kline_cache "
            "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows
        )
        conn.commit()
        ok += 1
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(index_codes)}] ok={ok} fail={fail} skip={skip}")

    conn.close()
    print(f"\n完成: 成功={ok}, 失败={fail}, 已跳过={skip}")

if __name__ == '__main__':
    main()

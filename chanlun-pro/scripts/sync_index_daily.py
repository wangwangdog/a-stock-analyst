#!/usr/bin/env python3
"""补充 kline_cache 上证指数(SH.000001)日线数据，存入完整前缀代码"""
import sys, os, sqlite3
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

def store_symbol(symbol, period_map, source='tdx'):
    """从TDX获取指数/个股数据，存入kline_cache"""
    from chanlun.exchange.exchange_tdx import ExchangeTDX
    ex = ExchangeTDX()

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    total = 0
    for freq, period in period_map.items():
        klines = ex.klines(symbol, freq)
        if klines is None or len(klines) == 0:
            print(f"  {symbol} {freq}: 无数据")
            continue
        rows = []
        for _, r in klines.iterrows():
            d = r['date']
            if hasattr(d, 'strftime'):
                d = d.strftime('%Y-%m-%d')
            rows.append((symbol, source, period, str(d),
                         float(r['open']), float(r['close']),
                         float(r['high']), float(r['low']),
                         float(r.get('volume', 0)), float(r.get('amount', 0))))
        conn.executemany(
            "INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows)
        conn.commit()
        print(f"  {symbol} {freq}({period}): 插入 {len(rows)} 条")
        total += len(rows)
    conn.close()
    return total

if __name__ == '__main__':
    # 上证指数日线
    print("上证指数 SH.000001:")
    store_symbol("SH.000001", {"d": "daily"})
    
    # 深证成指
    print("\n深证成指 SZ.399001:")
    store_symbol("SZ.399001", {"d": "daily"})

    # 验证
    print("\n验证:")
    conn = sqlite3.connect(DB)
    for sym in ["SH.000001", "SZ.399001"]:
        cnt = conn.execute("SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period='daily'", (sym,)).fetchone()[0]
        latest = conn.execute("SELECT trade_date, close FROM kline_cache WHERE symbol=? AND period='daily' ORDER BY trade_date DESC LIMIT 1", (sym,)).fetchone()
        print(f"  {sym}: {cnt}条, 最新={latest}")
    conn.close()

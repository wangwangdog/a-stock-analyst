#!/usr/bin/env python3
#!/usr/bin/env python3
"""增量补5m数据：检查旧5m周期 max_date，只拉TDX最新页补充缺失"""
import sys, os, time, sqlite3
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))
os.environ['CHANLUN_PRO_PATH'] = os.path.expanduser("~/.chanlun_pro")

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
INS = """INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"""

def conn():
    c = sqlite3.connect(DB, timeout=120)
    c.execute("PRAGMA busy_timeout=60000")
    c.execute("PRAGMA journal_mode=WAL")
    return c

def get_stale_stocks(c):
    """找5m数据未到今天的股票"""
    today = "2026-06-02"
    rows = c.execute(
        "SELECT symbol, MAX(trade_date) FROM kline_cache WHERE period='5m' "
        "GROUP BY symbol HAVING MAX(trade_date) < ? ORDER BY symbol",
        (today,)
    ).fetchall()
    return [(r[0], r[1]) for r in rows]

def pref(code):
    """裸码转带前缀完整代码"""
    if '.' in code:
        return code
    # kline_cache 里是裸码
    if code.startswith(('6','688','900')):
        return f'SH.{code}'
    if code.startswith(('0','3','002','200','300','301')):
        return f'SZ.{code}'
    return code

def main():
    t0 = time.time()
    c = conn()
    stale = get_stale_stocks(c)
    print(f"数据未到今天的股票: {len(stale)}", flush=True)

    # 只处理 max_date < today 的
    done = 0
    total = len(stale)
    for idx, (symbol, max_dt) in enumerate(stale):
        # 带前缀获取TDX最新页
        full = pref(symbol)
        from chanlun.exchange.exchange_tdx import ExchangeTDX
        ex = ExchangeTDX()
        try:
            df = ex.klines(full, '5m', args={'pages': 1, 'use_cache': False})
        except Exception as e:
            print(f"  [{idx+1}/{total}] {symbol} TDX失败: {e}", flush=True)
            done += 1
            if done % 50 == 0 and done > 0:
                c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            continue
        if df is None or df.empty:
            done += 1
            continue

        # 只取比现有最大日期新的
        nd = df[df['date'] > max_dt] if max_dt else df
        if nd.empty:
            done += 1
            continue

        rows = []
        for _, r in nd.iterrows():
            d = r['date']
            if hasattr(d, 'strftime'):
                d = d.strftime('%Y-%m-%d %H:%M:%S')
            rows.append((
                symbol, 'tdx', '5m', str(d),
                float(r['open']), float(r['close']),
                float(r['high']), float(r['low']),
                float(r.get('volume', 0)), float(r.get('amount', 0))
            ))
        c.executemany(INS, rows)
        c.commit()
        done += 1

        if done % 10 == 0:
            el = time.time() - t0
            print(f"  [{idx+1}/{total}] {symbol}: +{len(rows)}行 {el:.0f}s", flush=True)

        if done % 50 == 0:
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    c.close()
    el = time.time() - t0
    print(f"完成! 处理{done}/{total}只 {el/60:.1f}min", flush=True)

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""快速增量补5m - 复用TDX连接 + 只补>=05-28的数据"""
import sys, os, time, sqlite3
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))
os.environ['CHANLUN_PRO_PATH'] = os.path.expanduser("~/.chanlun_pro")
from chanlun.exchange.exchange_tdx import ExchangeTDX

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
INS = "INSERT OR IGNORE INTO kline_cache VALUES (?,?,?,?,?,?,?,?,?,?)"

def main():
    t0 = time.time()
    c = sqlite3.connect(DB, timeout=120)
    c.execute("PRAGMA busy_timeout=60000")
    c.execute("PRAGMA journal_mode=WAL")

    # 只取max<06-02的
    stale = [r[0] for r in c.execute(
        "SELECT symbol FROM kline_cache WHERE period='5m' "
        "GROUP BY symbol HAVING MAX(trade_date) < ?", ("2026-06-02",)
    ).fetchall()]
    tot = len(stale)
    print(f"需更新: {tot}只", flush=True)

    ex = ExchangeTDX()
    done = rows_total = 0
    batch = []

    for idx, s in enumerate(stale):
        full = f"SH.{s}" if s.startswith(('6','688','900','7')) else f"SZ.{s}"
        try:
            df = ex.klines(full, '5m', args={'pages': 1, 'use_cache': False})
        except:
            done += 1
            continue
        if df is None or df.empty:
            done += 1
            continue
        nd = df[df['date'] >= '2026-05-28']
        if nd.empty:
            done += 1
            continue
        for _, r in nd.iterrows():
            d = r['date']
            if hasattr(d, 'strftime'): d = d.strftime('%Y-%m-%d %H:%M:%S')
            batch.append((s, 'tdx', '5m', str(d),
                          float(r['open']), float(r['close']),
                          float(r['high']), float(r['low']),
                          float(r.get('volume',0)), float(r.get('amount',0))))
        rows_total += len(nd)
        done += 1

        if len(batch) >= 10000:
            c.executemany(INS, batch)
            c.commit()
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            batch = []

        if done % 50 == 0:
            el = time.time() - t0
            print(f"  [{done}/{tot}] +{rows_total}行 {el:.0f}s", flush=True)

    if batch:
        c.executemany(INS, batch)
        c.commit()
    c.close()
    el = time.time() - t0
    print(f"完成! {done}/{tot}只 +{rows_total}行 {el:.0f}s", flush=True)

if __name__ == '__main__':
    main()

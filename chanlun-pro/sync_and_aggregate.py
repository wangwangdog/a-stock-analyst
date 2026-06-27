#!/usr/bin/env python3
"""增量补齐5m+聚合15m/30m/60m"""
import sys, os, time, sqlite3
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))
os.environ['CHANLUN_PRO_PATH'] = os.path.expanduser("~/.chanlun_pro")
from chanlun.exchange.exchange_tdx import ExchangeTDX

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
TARGET = {"15m": 3, "30m": 6, "60m": 12}
INS = """INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"""

def conn():
    c = sqlite3.connect(DB, timeout=120)
    c.execute("PRAGMA busy_timeout=60000")
    return c

def stocks(c):
    return [r[0] for r in c.execute(
        "SELECT DISTINCT 股票代码 FROM hzeveryday WHERE 股票代码 NOT LIKE '9%' AND 股票名称 NOT LIKE '%ST%' AND 股票名称 NOT LIKE '%退%'"
    ).fetchall()]

def fetch(code):
    try:
        ex = ExchangeTDX()
        full = f"SZ.{code}" if (code.startswith('0') or code.startswith('3')) else f"SH.{code}"
        return ex.klines(full, '5m', args={'pages': 1, 'use_cache': False})
    except:
        return None

def pref(s):
    if '.' in s: return s
    if s.startswith(('6', '688', '900')): return f'SH.{s}'
    if s.startswith(('0', '3', '002', '200', '300', '301')): return f'SZ.{s}'
    return s

def main():
    t0 = time.time()
    c = conn()
    ss = stocks(c)
    print(f"活跃股票: {len(ss)}", flush=True)
    i5 = ia = ok_ = fail_ = 0
    for idx, s in enumerate(ss):
        df = fetch(s)
        if df is None or df.empty:
            fail_ += 1
            continue
        ok_ += 1
        # --- save 5m ---
        n5 = 0
        for sym in set([s, pref(s)]):
            md = c.execute("SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period='5m'", (sym,)).fetchone()[0]
            nd = df[df['date'] > md].copy() if md else df.copy()
            if nd.empty:
                continue
            rows = []
            for _, r in nd.iterrows():
                d = r['date']
                if hasattr(d, 'strftime'): d = d.strftime('%Y-%m-%d %H:%M:%S')
                rows.append((sym, 'tdx', '5m', str(d), float(r['open']), float(r['close']), float(r['high']), float(r['low']), float(r.get('volume',0)), float(r.get('amount',0))))
            if rows:
                c.executemany(INS, rows)
                c.commit()
                n5 += len(rows)
                i5 += len(rows)
        if n5 == 0:
            continue
        # --- aggregate 5m -> 15m/30m/60m ---
        for p, n in TARGET.items():
            md = c.execute("SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period=?", (s, p)).fetchone()[0]
            if md:
                rws = c.execute(
                    "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
                    "WHERE symbol=? AND period='5m' AND trade_date>? ORDER BY trade_date", (s, md)
                ).fetchall()
            else:
                rws = c.execute(
                    "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
                    "WHERE symbol=? AND period='5m' ORDER BY trade_date", (s,)
                ).fetchall()
            if len(rws) < n:
                continue
            ag = []
            for i in range(0, len(rws), n):
                ch = rws[i:i+n]
                if len(ch) < n: continue
                ag.append((s, 'tdx', p, ch[-1][0], ch[0][1], ch[-1][2], max(r[3] for r in ch), min(r[4] for r in ch), sum(r[5] for r in ch), sum(r[6] for r in ch)))
            if ag:
                c.executemany(INS, ag)
                c.commit()
                ia += len(ag)
        if (idx+1) % 100 == 0:
            el = time.time() - t0
            print(f"  [{idx+1}/{len(ss)}] 5m+{i5} agg+{ia} fail{fail_} {el:.0f}s", flush=True)
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()
    el = time.time() - t0
    print(f"完成! 5m+{i5} agg+{ia} ok{ok_} fail{fail_} {el:.0f}s", flush=True)

if __name__ == '__main__':
    main()

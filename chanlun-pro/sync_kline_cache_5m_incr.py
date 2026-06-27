#!/usr/bin/env python3
"""
sync_kline_cache_5m_incr.py — 增量补齐 kline_cache 5分钟数据
已有数据的只拉最近1页(700条≈15天)，缺失的拉12页(8400条)
"""
import sys, os, time
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/cl-vendors/chanlun-pro/src"))
os.environ['CHANLUN_PRO_PATH'] = os.path.expanduser("~/.chanlun_pro")

import sqlite3
import pandas as pd
from chanlun.exchange.exchange_tdx import ExchangeTDX

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

def get_db():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def fetch_5m(code, pages=12):
    ex = ExchangeTDX()
    full_code = f"SZ.{code}" if (code.startswith('0') or code.startswith('3')) else f"SH.{code}"
    return ex.klines(full_code, '5m', args={'pages': pages, 'use_cache': False})

def _prefixed(code):
    """裸码转完整前缀代码"""
    if '.' in code: return code  # 已有前缀
    if code.startswith(('6', '688', '900')): return f'SH.{code}'
    if code.startswith(('0', '3', '002', '200', '300', '301')): return f'SZ.{code}'
    if code.startswith(('8', '4', '920')): return f'BJ.{code}'
    return code

def save_new(conn, code, df):
    """只插入 kline_cache 中没有的数据（同时存裸码和带前缀）"""
    full_codes = [code, _prefixed(code)]
    inserted = 0
    for sym in set(full_codes):
        max_dt = conn.execute(
            "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period='5m'", (sym,)
        ).fetchone()[0]
        if max_dt:
            df_new = df[df['date'] > max_dt].copy()
        else:
            df_new = df.copy()
        if df_new.empty:
            continue
        rows = []
        for _, row in df_new.iterrows():
            d = row['date']
            if hasattr(d, 'strftime'):
                d = d.strftime('%Y-%m-%d %H:%M:%S')
            rows.append((sym, 'tdx', '5m', str(d),
                         float(row['open']), float(row['close']),
                         float(row['high']), float(row['low']),
                         float(row.get('volume', 0)), float(row.get('amount', 0))))
        conn.executemany(
            "INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        inserted += len(rows)
    return inserted

def main():
    t_start = time.time()
    conn = get_db()
    
    # 全量股票
    all_stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE date='2026-05-25' ORDER BY symbol").fetchall()]
    
    # 分两类：已经有5m数据的 vs 没有的
    has_data = [s for s in all_stocks if conn.execute(
        "SELECT 1 FROM kline_cache WHERE symbol=? AND period='5m' LIMIT 1", (s,)).fetchone()]
    no_data = [s for s in all_stocks if s not in has_data]
    
    print(f"共 {len(all_stocks)} 只")
    print(f"  已有5m数据: {len(has_data)} 只（只补最近）")
    print(f"  无5m数据: {len(no_data)} 只（全量拉取）")
    
    success = fail = new_rows = 0
    
    # ── 先处理缺失的99只（pages=12 全量） ──
    if no_data:
        print(f"\n{'='*60}")
        print(f"第1阶段: 补全 {len(no_data)} 只缺失股票（pages=12）")
        print(f"{'='*60}")
        for idx, code in enumerate(no_data):
            t0 = time.time()
            try:
                df = fetch_5m(code, pages=12)
                if df is not None and not df.empty:
                    n = save_new(conn, code, df)
                    success += 1
                    new_rows += n
                    if success % 10 == 0:
                        print(f"  [{idx+1}/{len(no_data)}] {code}: {n}行 ({time.time()-t0:.1f}s)")
                else:
                    fail += 1
                    print(f"  [{idx+1}/{len(no_data)}] {code}: ❌ 空数据")
            except Exception as e:
                fail += 1
                print(f"  [{idx+1}/{len(no_data)}] {code}: ❌ {e}")
    
    # ── 再处理已有数据的（pages=1 只补最近） ──
    if has_data:
        print(f"\n{'='*60}")
        print(f"第2阶段: 补 {len(has_data)} 只已有数据的最近缺失（pages=1）")
        print(f"{'='*60}")
        for idx, code in enumerate(has_data):
            t0 = time.time()
            try:
                df = fetch_5m(code, pages=1)
                if df is not None and not df.empty:
                    n = save_new(conn, code, df)
                    if n > 0:
                        success += 1
                        new_rows += n
                        if success % 200 == 0:
                            print(f"  [{idx+1}/{len(has_data)}] {code}: +{n}行 ({time.time()-t0:.1f}s)")
                    else:
                        fail += 1  # Already up to date
                else:
                    fail += 1
            except Exception as e:
                fail += 1
            
            if (idx + 1) % 500 == 0:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                elapsed = time.time() - t_start
                print(f"  checkpoint [{idx+1}/{len(has_data)}] {elapsed/60:.1f}min")
    
    conn.close()
    total_t = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"完成! +{new_rows}行 成功:{success} 失败:{fail} 耗时:{total_t/60:.1f}min")

if __name__ == '__main__':
    main()

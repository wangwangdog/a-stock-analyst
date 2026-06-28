#!/usr/bin/env python3
"""
sync_5m_to_30m.py — 从正确的 5m 数据聚合出 30m 写入 kline_cache

策略：
  1. 读 kline_cache 中某只股票的全部 5m 数据
  2. 聚合成 30m K线（resample 30min）
  3. 删旧 30m 数据 → 写入新数据
  4. 每 500 只 checkpoint
"""
import sys, os, time, traceback
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))

import sqlite3
import pandas as pd

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
LOG_EVERY = 200
CP_EVERY = 500

def get_db():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def agg_5m_to_30m(df: pd.DataFrame) -> pd.DataFrame:
    """从 5m DataFrame 聚合成 30m"""
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['trade_date'], format='mixed')
    df = df.set_index('datetime').sort_index()
    
    # resample 30min
    ohlcv = df.resample('30min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'amount': 'sum'
    }).dropna()
    
    # 过滤掉成交量/金额为0的
    ohlcv = ohlcv[ohlcv['volume'] > 0]
    
    if ohlcv.empty:
        return None
    
    ohlcv = ohlcv.reset_index()
    ohlcv['trade_date'] = ohlcv['datetime'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return ohlcv[['trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount']]

def write_30m(conn, code: str, df_30m: pd.DataFrame, source: str = "tdx"):
    """先删后插"""
    conn.execute("DELETE FROM kline_cache WHERE symbol=? AND period='30m'", (code,))
    
    rows = []
    for _, r in df_30m.iterrows():
        rows.append((
            code, source, '30m', str(r['trade_date']),
            float(r['open']), float(r['close']),
            float(r['high']), float(r['low']),
            float(r['volume']), float(r['amount'])
        ))
    
    conn.executemany(
        "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    return len(rows)

def main():
    t_start = time.time()
    conn = get_db()
    
    # 取所有有 5m 数据的股票
    stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' ORDER BY symbol").fetchall()]
    total = len(stocks)
    print(f"待处理股票: {total} 只")
    
    success = fail = skip = total_rows = 0
    
    for idx, code in enumerate(stocks):
        t0 = time.time()
        try:
            # 读该股票全部 5m 数据
            df_5m = pd.read_sql(
                "SELECT trade_date, open, high, low, close, volume, amount "
                "FROM kline_cache WHERE symbol=? AND period='5m' ORDER BY trade_date ASC",
                conn, params=(code,))
            
            if df_5m.empty:
                skip += 1
                continue
            
            df_30m = agg_5m_to_30m(df_5m)
            if df_30m is None:
                skip += 1
                continue
            
            n = write_30m(conn, code, df_30m)
            success += 1
            total_rows += n
            
            if success % LOG_EVERY == 0:
                elapsed = time.time() - t_start
                rate = (idx + 1) / elapsed if elapsed > 0 else 0
                eta = (total - idx) / rate if rate > 0 else 0
                print(f"  [{idx+1}/{total}] {code}: {n}行 ({time.time()-t0:.1f}s) "
                      f"成功:{success} 失败:{fail} ETA:{eta/60:.0f}min")
            
            if (idx + 1) % CP_EVERY == 0:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                elapsed = time.time() - t_start
                print(f"  checkpoint [{idx+1}/{total}] {elapsed/60:.1f}min")
                
        except Exception as e:
            fail += 1
            print(f"  [{idx+1}/{total}] {code}: ❌ {e}")
            traceback.print_exc()
    
    conn.close()
    total_t = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"完成! 成功:{success} 失败:{fail} 跳过:{skip} +{total_rows}行 耗时:{total_t/60:.1f}min")

if __name__ == '__main__':
    main()

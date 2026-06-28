#!/usr/bin/env python3
"""
sync_kline_cache_5m.py — 用 TDX 同步 5分钟K线到 kline_cache

策略：
  1. 从 stock_daily 取全部股票代码
  2. 逐只从 TDX 拉取 5m 数据（~8400行/8个月）
  3. 写入 kline_cache，替换旧数据
  4. 每 100 只 PRAGMA wal_checkpoint
  5. 记录进度，支持断点续传

用法: python3 sync_kline_cache_5m.py [--resume]
"""
import sys, os, time, json, argparse, traceback
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))
os.environ['CHANLUN_PRO_PATH'] = os.path.expanduser("~/.chanlun_pro")

import sqlite3
import pandas as pd

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
PROGRESS_FILE = os.path.expanduser("~/.chanlun_pro/sync_5m_progress.json")
BATCH_SIZE = 100   # 每批后 checkpoint
LOG_EVERY = 50     # 每 50 只打日志

def get_db():
    conn = sqlite3.connect(DB, timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def get_stock_list(conn):
    """从 all_stock_info 取全部股票"""
    rows = conn.execute("SELECT symbol FROM all_stock_info ORDER BY symbol").fetchall()
    return [r[0] for r in rows]

def fetch_tdx_5m(code: str):
    """从 TDX 获取 5m 数据"""
    from chanlun.exchange.exchange_tdx import ExchangeTDX
    ex = ExchangeTDX()
    full_code = f"SZ.{code}" if code.startswith('0') or code.startswith('3') else f"SH.{code}"
    df = ex.klines(full_code, '5m', args={'pages': 12, 'use_cache': False})
    if df is None or df.empty:
        return None
    return df

def fetch_fallback_5m(code: str):
    """腾讯行情接口兜底（备用）"""
    import requests
    market = "sz" if code.startswith('0') or code.startswith('3') else "sh"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={market}{code},m5,,320"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        # 解析腾讯5分钟数据格式
        klines = data.get('data', {}).get(f'{market}{code}', {}).get('m5', None)
        if not klines:
            return None
        rows = []
        for item in klines:
            # 格式: "2025-11-26 10:55" "25.65" "25.65" "25.58" "25.58" 0
            if len(item) >= 6:
                rows.append({
                    'date': pd.to_datetime(item[0]),
                    'open': float(item[1]),
                    'close': float(item[2]),
                    'high': float(item[3]),
                    'low': float(item[4]),
                    'volume': float(item[5]),
                })
        if not rows:
            return None
        df = pd.DataFrame(rows)
        return df
    except Exception as e:
        print(f"    腾讯接口失败: {e}")
        return None

def save_to_cache(conn, code: str, df: pd.DataFrame, source: str = "tdx"):
    """写入 kline_cache，先删旧数据"""
    # 删旧数据
    conn.execute("DELETE FROM kline_cache WHERE symbol=? AND period='5m'", (code,))
    
    # 批量插入
    rows_data = []
    for _, row in df.iterrows():
        d = row['date']
        if hasattr(d, 'strftime'):
            d = d.strftime('%Y-%m-%d %H:%M:%S')
        rows_data.append((
            code, source, '5m', str(d),
            float(row['open']), float(row['close']),
            float(row['high']), float(row['low']),
            float(row.get('volume', 0)), float(row.get('amount', 0))
        ))
    
    conn.executemany(
        "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows_data
    )
    conn.commit()
    return len(rows_data)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed": [], "failed": [], "last_index": 0}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true', help='断点续传')
    parser.add_argument('--limit', type=int, default=0, help='限制处理数量（测试用）')
    args = parser.parse_args()
    
    print(f"连接数据库: {DB}")
    conn = get_db()
    stocks = get_stock_list(conn)
    print(f"待同步股票数: {len(stocks)}")
    
    if args.limit > 0:
        stocks = stocks[:args.limit]
        print(f"(限制模式: 只处理 {args.limit} 只)")
    
    progress = load_progress() if args.resume else {"completed": [], "failed": [], "last_index": 0}
    completed_set = set(progress["completed"])
    
    start_idx = progress["last_index"] if args.resume else 0
    total = len(stocks)
    t_start = time.time()
    success = 0
    fail = 0
    
    print(f"开始同步 ({'续传' if args.resume else '从头'})...")
    
    for idx in range(start_idx, total):
        code = stocks[idx]
        if code in completed_set:
            continue
        
        t0 = time.time()
        try:
            df = fetch_tdx_5m(code)
            source = "tdx"
            
            if df is None:
                # TDX 失败，尝试腾讯
                print(f"  TDX失败，尝试腾讯 {code}")
                df = fetch_fallback_5m(code)
                source = "tencent_5m"
            
            if df is not None and not df.empty:
                n = save_to_cache(conn, code, df, source)
                progress["completed"].append(code)
                success += 1
                elapsed = time.time() - t0
                if success % LOG_EVERY == 0:
                    rate = (idx - start_idx + 1) / (time.time() - t_start)
                    eta = (total - idx) / rate if rate > 0 else 0
                    print(f"  [{idx+1}/{total}] {code}: {n}行 {elapsed:.1f}s | 成功:{success} 失败:{fail} "
                          f"速率:{rate:.1f}/s ETA:{eta/60:.0f}min")
            else:
                progress["failed"].append(code)
                fail += 1
                print(f"  [{idx+1}/{total}] {code}: 获取失败 ❌")
        
        except Exception as e:
            progress["failed"].append(code)
            fail += 1
            print(f"  [{idx+1}/{total}] {code}: 异常 {e}")
            traceback.print_exc()
        
        progress["last_index"] = idx + 1
        
        # 每 100 只 checkpoint
        if (idx + 1) % BATCH_SIZE == 0:
            save_progress(progress)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            elapsed = time.time() - t_start
            rate = (idx - start_idx + 1) / elapsed
            eta = (total - idx) / rate if rate > 0 else 0
            print(f"  checkpoint [{idx+1}/{total}] {elapsed/60:.1f}min elapsed, ETA {eta/60:.0f}min")
    
    conn.close()
    save_progress(progress)
    total_time = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"完成! 成功:{success} 失败:{fail} 耗时:{total_time/60:.1f}min")
    if progress["failed"]:
        print(f"失败的股票: {progress['failed']}")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()

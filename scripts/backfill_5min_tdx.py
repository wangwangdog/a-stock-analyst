#!/usr/bin/env python3
"""
使用 pytdx (TDX 协议) 补齐 5 分钟 K 线数据
解决 mootdx 仅返回日线数据的问题
"""
import sys
import os
from pathlib import Path
from datetime import date, datetime
import sqlite3
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pytdx.hq import TdxHq_API

DB_PATH = Path('/mnt/disk990g/sqlite-data/chanlun_klines.sqlite')
TDX_SERVER = ('180.153.18.170', 7709)


def log(msg: str):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_stocks():
    """获取股票列表"""
    conn = sqlite3.connect(DB_PATH)
    stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE source='stock_daily' AND period='daily' ORDER BY symbol"
    ).fetchall()]
    conn.close()
    return stocks


def get_missing_5min_stocks():
    """获取缺少今日 5 分钟数据的股票"""
    conn = sqlite3.connect(DB_PATH)
    today = date.today().strftime("%Y-%m-%d")
    
    all_stocks = conn.execute("SELECT DISTINCT symbol FROM kline_cache WHERE source='stock_daily' AND period='daily'").fetchall()
    existing = conn.execute(
        f"SELECT DISTINCT symbol FROM kline_cache WHERE period='5min' AND trade_date LIKE '{today}%' AND source='tdx'"
    ).fetchall()
    
    conn.close()
    
    existing_set = set(e[0] for e in existing)
    missing = [s[0] for s in all_stocks if s[0] not in existing_set]
    return missing, today


def get_tdx_market(code: str) -> int:
    """返回 TDX 市场代码: 0=深圳，1=上海，2=北京"""
    code = str(code).strip()
    if code.startswith('6') or code.startswith('9'):
        return 1  # 上海
    if code.startswith('8') or code.startswith('4'):
        return 2  # 北京
    return 0  # 深圳 (0xxx, 3xxx)


def fetch_5min(symbol: str) -> list:
    """
    使用 pytdx 获取 5 分钟 K 线
    返回：[(trade_date, open, close, high, low, volume, amount), ...]
    """
    api = TdxHq_API()
    market = get_tdx_market(symbol)
    
    try:
        if not api.connect(TDX_SERVER[0], TDX_SERVER[1], time_out=10):
            return None
        
        # category=0 is 5-minute, fetch up to 800 bars (recent 10 days)
        klines = api.get_security_bars(0, market, symbol, 0, 800)
        
        if not klines:
            return None
        
        # Convert to list of tuples
        bars = []
        for k in klines:
            dt_str = str(k['datetime'])
            bars.append((
                dt_str,
                float(k['open']),
                float(k['close']),
                float(k['high']),
                float(k['low']),
                int(k['vol']),
                float(k['amount'])
            ))
        
        return bars
        
    except Exception as e:
        log(f"Error fetching {symbol}: {e}")
        return None
    finally:
        try:
            api.disconnect()
        except:
            pass


def save_5min(symbol: str, bars: list):
    """
    保存 5 分钟数据到 kline_cache
    """
    if not bars:
        return 0
    
    today = date.today().strftime("%Y-%m-%d")
    
    # Filter today's bars only
    today_bars = [b for b in bars if b[0].startswith(today)]
    if not today_bars:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Insert with REPLACE to handle unique constraint
        count = 0
        for bar in today_bars:
            cursor.execute(
                "INSERT OR REPLACE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'tdx', '5min', ?, ?, ?, ?, ?, ?, ?)",
                (symbol, bar[0], bar[1], bar[2], bar[3], bar[4], bar[5], bar[6])
            )
            count += 1
        
        conn.commit()
        return count
        
    except Exception as e:
        log(f"Error saving {symbol}: {e}")
        return 0
    finally:
        conn.close()


def process_stock(symbol: str):
    """处理单只股票"""
    bars = fetch_5min(symbol)
    if bars:
        count = save_5min(symbol, bars)
        if count > 0:
            return symbol, count
        else:
            return symbol, 0
    return symbol, -1


def main():
    parser = argparse.ArgumentParser(description="使用 TDX 协议补齐 5 分钟 K 线数据")
    parser.add_argument("--limit", type=int, default=0, help="最多处理的股票数（0=全部）")
    parser.add_argument("--symbol", type=str, action="append", default=None, help="指定股票（可多次使用）")
    parser.add_argument("--workers", type=int, default=20, help="并发 worker 数")
    args = parser.parse_args()
    
    if args.symbol:
        symbols = args.symbol
    else:
        symbols, today = get_missing_5min_stocks()
        if args.limit and 0 < args.limit < len(symbols):
            symbols = symbols[:args.limit]
        log(f"需要补全 5 分钟数据的股票：{len(symbols)} 只 ({date.today()})")
    
    if not symbols:
        log("✅ 所有股票今日 5 分钟数据已齐全")
        return
    
    # Process with thread pool
    success = 0
    failed = 0
    total_bars = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_stock, sym): sym for sym in symbols}
        
        for future in as_completed(futures):
            symbol, count = future.result()
            if count > 0:
                log(f"✅ {symbol}: 写入 {count} 条 5 分钟数据")
                success += 1
                total_bars += count
            elif count == 0:
                log(f"⚠️  {symbol}: 无今日数据")
                failed += 1
            else:
                log(f"❌ {symbol}: 获取失败")
                failed += 1
            
            if success % 100 == 0:
                log(f"进度：成功{success} 失败{failed}")
    
    # Verify
    conn = sqlite3.connect(DB_PATH)
    today = date.today().strftime("%Y-%m-%d")
    total_5min = conn.execute(
        f"SELECT COUNT(*) FROM kline_cache WHERE period='5min' AND trade_date LIKE '{today}%' AND source='tdx'"
    ).fetchone()[0]
    conn.close()
    
    log(f"\n{'='*50}")
    log(f"✅ 完成：成功{success} 失败{failed}")
    log(f"📊 今日 5 分钟数据总量：{total_5min} 条")
    log(f"{'='*50}")


if __name__ == "__main__":
    main()

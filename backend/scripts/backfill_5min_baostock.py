#!/usr/bin/env python3
"""
使用 Baostock 批量补齐历史 5 分钟 K 线数据
回补昨天及之前的历史数据（不包括今天）
"""
import sys
import os
from pathlib import Path
from datetime import date, datetime, timedelta
import sqlite3
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import baostock as bs

DB_PATH = Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite'


def log(msg: str):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_stocks_to_backfill():
    """获取需要回补的股票列表"""
    conn = sqlite3.connect(DB_PATH)
    
    # 获取所有股票
    all_stocks = conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()
    
    # 检查哪些股票缺少历史 5 分钟数据
    missing_stocks = []
    for stock in all_stocks:
        symbol = stock[0]
        # 检查该股票是否有历史 5 分钟数据（除了最近几天）
        count = conn.execute(
            "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period='5min'",
            (symbol,)
        ).fetchone()[0]
        if count < 100:  # 少于 100 条（约 2 个交易日）则认为缺少历史数据
            missing_stocks.append(symbol)
    
    conn.close()
    return missing_stocks


def get_bs_code(symbol: str) -> str:
    """转换股票代码为 Baostock 格式 (sh.600000)"""
    symbol = str(symbol).strip()
    if symbol.startswith('6') or symbol.startswith('9'):
        return f"sh.{symbol}"
    elif symbol.startswith('8') or symbol.startswith('4'):
        return f"bj.{symbol}"
    else:
        return f"sz.{symbol}"


def fetch_5min_baostock(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    使用 Baostock 获取 5 分钟 K 线
    """
    bs_code = get_bs_code(symbol)
    try:
        # 登录 bs
        lg = bs.login()
        if lg.error_code != '0':
            log(f"Baostock login failed: {lg.error_msg}")
            return None
        
        # 查询 5 分钟 K 线
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,time,open,high,low,close,preclose,volume,amount,adjustflag",
            start_date=start_date,
            end_date=end_date,
            frequency="5",
            adjustflag="3"  # 前复权
        )
        
        # 组装数据
        df = rs.get_data()
        
        # 登出 bs
        bs.logout()
        
        if df is None or len(df) == 0:
            return None
        
        # 格式化时间
        df['datetime'] = df['date'] + ' ' + df['time']
        df['datetime'] = pd.to_datetime(df['datetime'])
        
        return df
        
    except Exception as e:
        log(f"Error fetching {symbol}: {e}")
        return None


def save_5min_data(symbol: str, df: pd.DataFrame):
    """
    保存 5 分钟数据到 kline_cache
    """
    if df is None or len(df) == 0:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        count = 0
        for _, row in df.iterrows():
            cursor.execute(
                "INSERT OR REPLACE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'baostock', '5min', ?, ?, ?, ?, ?, ?, ?)",
                (
                    symbol,
                    row['datetime'].strftime("%Y-%m-%d %H:%M:%S"),
                    float(row['open']),
                    float(row['close']),
                    float(row['high']),
                    float(row['low']),
                    int(row['volume']),
                    float(row['amount'])
                )
            )
            count += 1
        
        conn.commit()
        return count
        
    except Exception as e:
        log(f"Error saving {symbol}: {e}")
        return 0
    finally:
        conn.close()


def process_stock(symbol: str, start_date: str, end_date: str):
    """处理单只股票"""
    df = fetch_5min_baostock(symbol, start_date, end_date)
    if df is not None and len(df) > 0:
        count = save_5min_data(symbol, df)
        if count > 0:
            return symbol, count, "success"
        else:
            return symbol, 0, "no_data"
    return symbol, -1, "failed"


def main():
    parser = argparse.ArgumentParser(description="使用 Baostock 批量补齐历史 5 分钟 K 线数据")
    parser.add_argument("--limit", type=int, default=0, help="最多处理的股票数（0=全部）")
    parser.add_argument("--symbol", type=str, action="append", default=None, help="指定股票（可多次使用）")
    parser.add_argument("--workers", type=int, default=5, help="并发 worker 数（Baostock 限流，建议 5）")
    parser.add_argument("--days", type=int, default=60, help="回补天数（默认 60 天）")
    args = parser.parse_args()
    
    # Calculate date range (exclude today)
    end_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = (end_date_obj := date.today() - timedelta(days=args.days + 1)).strftime("%Y-%m-%d")
    
    log(f"日期范围：{start_date} 至 {end_date}（不包括今天：{date.today()}）")
    
    if args.symbol:
        symbols = args.symbol
    else:
        symbols = get_stocks_to_backfill()
        if args.limit and 0 < args.limit < len(symbols):
            symbols = symbols[:args.limit]
        log(f"需要补全历史 5 分钟数据的股票：{len(symbols)} 只")
    
    if not symbols:
        log("✅ 所有股票历史 5 分钟数据已齐全")
        return
    
    # Process with thread pool (Baostock has rate limits)
    success = 0
    failed = 0
    total_bars = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_stock, sym, start_date, end_date): sym for sym in symbols}
        
        for future in as_completed(futures):
            symbol, count, status = future.result()
            if status == "success":
                log(f"✅ {symbol}: 写入 {count} 条 5 分钟数据")
                success += 1
                total_bars += count
            elif status == "no_data":
                log(f"⚠️  {symbol}: 无历史数据")
                failed += 1
            else:
                log(f"❌ {symbol}: 获取失败")
                failed += 1
            
            if success % 10 == 0:
                log(f"进度：成功{success} 失败{failed}")
    
    # Verify
    conn = sqlite3.connect(DB_PATH)
    total_5min = conn.execute(
        "SELECT COUNT(*) FROM kline_cache WHERE period='5min'"
    ).fetchone()[0]
    conn.close()
    
    log(f"\n{'='*50}")
    log(f"✅ 完成：成功{success} 失败{failed}")
    log(f"📊 5 分钟数据总量：{total_5min} 条")
    log(f"{'='*50}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
使用 mootdx 补齐 5 分钟 K 线数据
适用于：当日 5 分钟数据缺失时的补全
"""
import sys
import os
from pathlib import Path
from datetime import date
import sqlite3
import argparse

# 添加后端路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))

os.environ['MOOTDX_SERVER'] = '180.153.18.170:7709'

from data.mootdx_fetcher import get_klines_df, available

DB_PATH = Path('/mnt/disk990g/sqlite-data/chanlun_klines.sqlite')


def log(msg: str):
    ts = date.today().strftime("%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_stocks():
    """获取需要补全的股票列表"""
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
        f"SELECT DISTINCT symbol FROM kline_cache WHERE period='5min' AND trade_date LIKE '{today}%'"
    ).fetchall()
    
    conn.close()
    
    missing = [s[0] for s in all_stocks if s[0] not in [e[0] for e in existing]]
    return missing, today


def save_klines(symbol: str, df):
    """保存 5 分钟数据到 kline_cache"""
    if df is None or df.empty:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 先删除当日该股票的 5 分钟数据
    today = date.today().strftime("%Y-%m-%d")
    cursor.execute(
        "DELETE FROM kline_cache WHERE symbol=? AND period='5min' AND trade_date LIKE ?",
        (symbol, f"{today}%")
    )
    
    # 插入新数据
    count = 0
    for _, row in df.iterrows():
        # mootdx datetime 格式："2026-06-02 09:30"
        trade_date = str(row['datetime'])
        cursor.execute(
            "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
            "VALUES (?, 'mootdx', '5min', ?, ?, ?, ?, ?, ?, ?)",
            (symbol, trade_date, float(row['open']), float(row['close']), 
             float(row['high']), float(row['low']), int(row['vol']), float(row['amount']))
        )
        count += 1
    
    conn.commit()
    conn.close()
    return count


def main():
    parser = argparse.ArgumentParser(description="使用 mootdx 补齐 5 分钟 K 线数据")
    parser.add_argument("--limit", type=int, default=0, help="最多处理的股票数（0=全部）")
    parser.add_argument("--symbol", type=str, default=None, help="指定单只股票测试")
    args = parser.parse_args()
    
    log(f"mootdx available: {available()}")
    
    if args.symbol:
        symbols = [args.symbol]
    else:
        symbols, today = get_missing_5min_stocks()
        if args.limit and 0 < args.limit < len(symbols):
            symbols = symbols[:args.limit]
        log(f"需要补全 5 分钟数据的股票：{len(symbols)} 只 ({today})")
    
    if not symbols:
        log("✅ 所有股票今日 5 分钟数据已齐全")
        return
    
    success = 0
    failed = 0
    total_bars = 0
    
    for idx, symbol in enumerate(symbols):
        try:
            # 获取 5 分钟线 (category=0)，拉取最近 100 条
            df = get_klines_df(symbol, category=0, offset=100)
            
            if df is None or df.empty:
                log(f"❌ {symbol}: mootdx 返回空数据")
                failed += 1
                continue
            
            count = save_klines(symbol, df)
            if count > 0:
                log(f"✅ {symbol}: 写入 {count} 条 5 分钟数据")
                success += 1
                total_bars += count
            else:
                log(f"⚠️  {symbol}: 无数据可写入")
                failed += 1
                
        except Exception as e:
            log(f"❌ {symbol}: 异常 - {e}")
            failed += 1
        
        if (idx + 1) % 100 == 0:
            log(f"进度：{idx+1}/{len(symbols)} (✅{success} ❌{failed})")
    
    # 验证
    conn = sqlite3.connect(DB_PATH)
    today = date.today().strftime("%Y-%m-%d")
    total_5min = conn.execute(
        f"SELECT COUNT(*) FROM kline_cache WHERE period='5min' AND trade_date LIKE '{today}%'"
    ).fetchone()[0]
    conn.close()
    
    log(f"\n{'='*50}")
    log(f"✅ 完成：成功{success} 失败{failed}")
    log(f"📊 今日 5 分钟数据总量：{total_5min} 条")
    log(f"{'='*50}")


if __name__ == "__main__":
    main()

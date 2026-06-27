#!/usr/bin/env python3
"""
stock_daily 简单回补脚本（低并发，三源切换）
"""
import sys
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path('src')))
from chanlun.utils.trading_calendar import get_calendar

cal = get_calendar()
DB_PATH = './db/chanlun_klines.sqlite'

def get_missing_dates():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(date) FROM stock_daily')
    current_latest = cursor.fetchone()[0] or '2026-05-08'
    conn.close()
    
    missing = []
    current = datetime.strptime(current_latest, '%Y-%m-%d')
    while current < datetime.now():
        current += timedelta(days=1)
        d_str = current.strftime('%Y-%m-%d')
        if cal.is_trading_day(d_str):
            missing.append(d_str)
    return missing

def fetch_from_baostock(symbol, start_date, end_date):
    try:
        import baostock as bs
        bs.login()
        prefix = "sh" if symbol.startswith(("6", "68")) else "sz"
        bs_code = f"{prefix}.{symbol}"
        
        rs = bs.query_history_k_data_plus(
            bs_code, "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"
        )
        if rs.error_code != "0":
            bs.logout()
            return None
        rows = [row for row in rs.get_result()['data']]
        bs.logout()
        return rows
    except Exception as e:
        return None

def fetch_from_akshare(symbol, start_date, end_date):
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=f"{symbol}", period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust="qfq", timeout=5
        )
        if df.empty:
            return None
        return df[['日期', '开盘', '最高', '最低', '收盘', '成交量', '成交额']].values.tolist()
    except Exception as e:
        return None

def fetch_stock(symbol, start_date, end_date):
    """三源切换：Baostock -> AKShare -> 失败"""
    # 尝试 Baostock
    result = fetch_from_baostock(symbol, start_date, end_date)
    if result:
        return result
    
    # 尝试 AKShare
    result = fetch_from_akshare(symbol, start_date, end_date)
    if result:
        return result
    
    return None

def main():
    missing = get_missing_dates()
    if not missing:
        print("✅ 数据已是最新")
        return
    
    print(f"缺失交易日：{len(missing)} 天")
    for d in missing:
        print(f"  - {d}")
    
    start_date, end_date = missing[0], missing[-1]
    
    # 获取股票列表
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT symbol FROM stock_daily LIMIT 10')
    test_symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    print(f"\n测试数据源（前 10 只股票）...")
    success_count = 0
    
    for symbol in test_symbols:
        print(f"测试 {symbol}:", end=" ", flush=True)
        result = fetch_stock(symbol, start_date, end_date)
        if result:
            print(f"✅ 成功 ({len(result)}条)")
            success_count += 1
        else:
            print("❌ 失败")
        time.sleep(0.5)  # 避免过快请求被墙
    
    print(f"\n测试结果：{success_count}/{len(test_symbols)} 成功")
    
    if success_count == 0:
        print("\n⚠️ 所有数据源都不可用，可能是网络问题或 API 限制")
        print("建议：")
        print("  1. 检查网络连接")
        print("  2. 使用代理")
        print("  3. 检查是否在防火墙内")
        return

if __name__ == "__main__":
    main()

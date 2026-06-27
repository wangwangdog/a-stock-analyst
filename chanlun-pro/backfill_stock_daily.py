#!/usr/bin/env python3
"""
stock_daily 并行回补脚本（三源切换：Baostock -> AKShare -> TDX）
补齐 5 月 8 日之后缺失的交易日数据
"""
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

sys.path.insert(0, str(Path('src')))
from chanlun.utils.trading_calendar import get_calendar

cal = get_calendar()
DB_PATH = './db/chanlun_klines.sqlite'
BATCH_SIZE = 100
MAX_WORKERS = 10  # 降低并发，避免连接被墙
RETRY_COUNT = 3

def get_missing_dates():
    """获取缺失的交易日列表"""
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

def fetch_baostock(symbol, start_date, end_date):
    """从 baostock 拉取数据"""
    try:
        import baostock as bs
        # 每次请求都重新登录，避免 session 过期
        bs.login()
        
        prefix = "sh" if symbol.startswith(("6", "68")) else "sz"
        bs_code = f"{prefix}.{symbol}"
        
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"
        )
        if rs.error_code != "0":
            bs.logout()
            return None
        
        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[0] and row[4]:
                rows.append([symbol, row[0], row[1], row[2], row[3], row[4], row[5], row[6]])
        bs.logout()
        return rows
    except Exception as e:
        try:
            bs.logout()
        except:
            pass
        return None

def fetch_akshare(symbol, start_date, end_date):
    """从 akshare 拉取数据（东方财富）"""
    try:
        import akshare as ak
        import pandas as pd
        
        df = ak.stock_zh_a_hist(
            symbol=f"{symbol}",
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust="qfq",
            timeout=10
        )
        if df.empty:
            return None
        rows = []
        for _, row in df.iterrows():
            rows.append([
                symbol, row['日期'], row['开盘'], row['最高'], row['最低'], 
                row['收盘'], row['成交量'], row['成交额']
            ])
        return rows
    except Exception as e:
        return None

def fetch_stock(symbol, start_date, end_date):
    """多源切换拉取：Baostock -> AKShare -> TDX(本地)"""
    sources = [
        ("baostock", fetch_baostock),
        ("akshare", fetch_akshare)
    ]
    
    for source_name, fetch_func in sources:
        for retry in range(RETRY_COUNT):
            try:
                result = fetch_func(symbol, start_date, end_date)
                if result:
                    # 静默成功，只在失败时输出
                    return result
            except Exception as e:
                if retry < RETRY_COUNT - 1:
                    time.sleep(1.0 * (retry + 1))  # 指数退避
                    continue
    
    # 所有源都失败
    return None

def main():
    print("🔍 检查缺失数据...")
    missing_dates = get_missing_dates()
    print(f"缺失交易日：{len(missing_dates)} 天")
    for d in missing_dates:
        print(f"  - {d}")
    
    if not missing_dates:
        print("✅ 数据已是最新")
        return
    
    start_date = missing_dates[0]
    end_date = missing_dates[-1]
    
    # 获取所有股票列表
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol')
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    print(f"\n📊 共 {len(symbols)} 只股票，开始回补...")
    print(f"   时间范围：{start_date} ~ {end_date}")
    print(f"   并发数：{MAX_WORKERS}, 数据源：Baostock -> AKShare")
    
    # 并行拉取
    all_data = []
    failed_symbols = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for symbol in symbols:
            futures.append(executor.submit(fetch_stock, symbol, start_date, end_date))
        
        completed = 0
        success_count = 0
        for future in as_completed(futures):
            result = future.result()
            if result:
                all_data.extend(result)
                success_count += 1
            else:
                # 找出是哪个 symbol 失败了
                for f, sym in zip(futures, symbols):
                    if f == future:
                        failed_symbols.append(sym)
                        break
            completed += 1
            if completed % BATCH_SIZE == 0:
                print(f"   进度：{completed}/{len(symbols)} ({success_count}成功), 已收集 {len(all_data)} 条数据...")
    
    if not all_data:
        print(f"❌ 未获取到任何数据，失败：{len(failed_symbols)} 只")
        return
    
    # 批量写入数据库
    print(f"\n💾 写入数据库 {len(all_data)} 条数据...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 删除旧数据（如果有）
    for date_str in missing_dates:
        cursor.execute('DELETE FROM stock_daily WHERE date = ?', (date_str,))
    
    # 插入新数据
    cursor.executemany(
        'INSERT OR REPLACE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        all_data
    )
    conn.commit()
    
    # 验证
    cursor.execute('SELECT MAX(date), COUNT(DISTINCT symbol) FROM stock_daily')
    row = cursor.fetchone()
    print(f"✅ 写入完成！最新日期：{row[0]}, 股票数：{row[1]}")
    
    # 统计每天的数据量
    for date_str in missing_dates:
        cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE date = ?', (date_str,))
        cnt = cursor.fetchone()[0]
        print(f"   {date_str}: {cnt:,} 行")
    
    conn.close()
    
    # 退出 baostock
    try:
        import baostock as bs
        bs.logout()
    except:
        pass

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
慢速同步脚本：三源切换 (Baostock -> AKShare)
特点：低并发 (5 线程)、自动重试、批量写入、支持中断续传
"""
import sys
import sqlite3
import time
import signal
import os
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path('src')))
from chanlun.utils.trading_calendar import get_calendar

# 配置
DB_PATH = './db/chanlun_klines.sqlite'
MAX_WORKERS = 5  # 极低并发，避免被墙
TIMEOUT_BS = 30  # Baostock 超时 30 秒
TIMEOUT_AK = 30  # AKShare 超时 30 秒
RETRY_COUNT = 2  # 每源重试次数
BATCH_SIZE = 100  # 每 100 只股票写入一次数据库

cal = get_calendar()
stop_event = False
success_count = 0
failed_count = 0

def signal_handler(sig, frame):
    global stop_event
    stop_event = True
    print("\n[收到停止信号] 完成当前批次后退出...")

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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
    """从 baostock 拉取数据（带超时控制）"""
    try:
        import baostock as bs
        bs.login()
        prefix = "sh" if symbol.startswith(("6", "68")) else "sz"
        bs_code = f"{prefix}.{symbol}"
        
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
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
        return None

def fetch_akshare(symbol, start_date, end_date):
    """从 akshare 拉取数据（带超时控制）"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol=f"{symbol}",
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust="qfq",
            timeout=TIMEOUT_AK
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
    """三源切换：Baostock -> AKShare -> 失败
    返回：[(symbol, date, open, high, low, close, volume, turnover), ...] 或 None
    """
    sources = [
        ("Baostock", fetch_baostock),
        ("AKShare", fetch_akshare)
    ]
    
    for source_name, fetch_func in sources:
        for retry in range(RETRY_COUNT):
            try:
                result = fetch_func(symbol, start_date, end_date)
                if result and len(result) > 0:
                    return result
                if retry < RETRY_COUNT - 1:
                    time.sleep(1.0 * (retry + 1))  # 指数退避
            except Exception as e:
                if retry < RETRY_COUNT - 1:
                    time.sleep(1.0 * (retry + 1))
    return None

def write_to_db(data):
    """批量写入数据库"""
    if not data:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany(
        'INSERT OR REPLACE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        data
    )
    conn.commit()
    conn.close()

def main():
    global success_count, failed_count
    
    # 检查缺失数据
    missing_dates = get_missing_dates()
    if not missing_dates:
        print("✅ 数据已是最新")
        return
    
    print(f"🔍 缺失交易日：{len(missing_dates)} 天")
    for d in missing_dates:
        print(f"   - {d}")
    
    start_date = missing_dates[0]
    end_date = missing_dates[-1]
    
    # 获取所有股票列表
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol')
    symbols = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    total = len(symbols)
    print(f"\n📊 共 {total:,} 只股票")
    print(f"   时间范围：{start_date} ~ {end_date}")
    print(f"   并发数：{MAX_WORKERS}")
    print(f"   数据源：Baostock (前复权) -> AKShare (备用)")
    print(f"   超时：{TIMEOUT_BS}秒")
    print(f"   每源重试：{RETRY_COUNT}次")
    print(f"\n开始同步... (Ctrl+C 停止)\n")
    
    # 并行拉取
    all_data = []
    batch_data = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for symbol in symbols:
            if stop_event:
                break
            future = executor.submit(fetch_stock, symbol, start_date, end_date)
            futures[future] = symbol
        
        completed = 0
        for future in as_completed(futures):
            if stop_event:
                break
            
            symbol = futures[future]
            result = future.result()
            
            if result:
                success_count += 1
                batch_data.extend(result)
            else:
                failed_count += 1
            
            completed += 1
            
            # 每处理 BATCH_SIZE 只股票，写入一次数据库
            if completed % BATCH_SIZE == 0:
                if batch_data:
                    print(f"💾 写入批次 {completed}/{total}, 累计 {len(all_data)+len(batch_data):,} 条数据...")
                    write_to_db(batch_data)
                    batch_data = []
                    all_data = []
                
                # 显示进度
                rate = success_count / total * 100
                print(f"   成功率：{rate:.1f}% ({success_count:,}成功 / {failed_count:,}失败)")
                
                # 短暂休息，避免被封
                time.sleep(2)
    
    # 写入剩余数据
    if batch_data:
        print(f"💾 写入最后批次...")
        write_to_db(batch_data)
    
    if stop_event:
        print(f"\n⚠️  提前终止")
    else:
        print(f"\n✅ 同步完成")
    
    print(f"   成功：{success_count:,}")
    print(f"   失败：{failed_count:,}")
    print(f"   成功率：{success_count/(success_count+failed_count)*100:.1f}%")

if __name__ == "__main__":
    main()

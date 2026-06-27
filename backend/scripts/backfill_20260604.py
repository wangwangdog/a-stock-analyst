#!/usr/bin/env python3
"""
补齐 2026-06-04 日线数据
从 baostock 获取所有股票当日数据（优化版）
"""

import baostock as bs
import sqlite3
from pathlib import Path
from datetime import datetime

target_date = "2026-06-04"
DB = str(Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite')

print(f"开始补齐 {target_date} 日线数据...")

# 连接数据库
conn = sqlite3.connect(DB)
conn.execute("PRAGMA journal_mode = WAL")

count = 0
error_count = 0

# 获取所有股票列表
lg = bs.login()
if lg.error_code != "0":
    print(f"Baostock 登录失败：{lg.error_msg}")
    exit(1)

rs = bs.query_all_stock(day=target_date)
all_stocks = []
while rs.next():
    row = rs.get_row_data()
    symbol = row[0]
    stock_name = row[1]
    market = row[2]
    if stock_name == '' or symbol == '':
        continue
    
    if market == '1':  # 上交所
        prefix = 'sh'
    elif market == '0':  # 深交所
        prefix = 'sz'
    else:
        prefix = 'bj'
    
    all_stocks.append((symbol, stock_name, prefix))

print(f"共获取到 {len(all_stocks)} 只股票")

# 批量获取数据 - 优化版：只检查一次
for i, (symbol, name, prefix) in enumerate(all_stocks):
    if (i + 1) % 500 == 0:
        print(f"进度：{i+1}/{len(all_stocks)} 写入：{count}")
    
    try:
        rs = bs.query_history_k_data_plus(
            prefix + "." + symbol,
            "date,open,high,low,close,volume,amount,adjustflag",
            start_date=target_date,
            end_date=target_date,
            frequency="d",
            adjustflag="3"
        )
        
        while rs.next():
            row = rs.get_row_data()
            if row[1] != '' and float(row[1]) > 0:
                conn.execute('''
                    INSERT OR REPLACE INTO stock_daily 
                    (symbol, date, open, high, low, close, volume, turnover)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    symbol,
                    target_date,
                    float(row[1]),
                    float(row[2]),
                    float(row[3]),
                    float(row[4]),
                    int(row[5]),
                    float(row[6])
                ))
                count += 1
                break
                
    except Exception as e:
        error_count += 1
        if error_count <= 3:
            print(f"错误 {symbol}: {e}")

conn.commit()
print(f"\n完成！共写入 {count} 条记录，错误 {error_count} 个")

# 验证结果
cursor = conn.execute('''
    SELECT COUNT(*), COUNT(DISTINCT symbol) 
    FROM stock_daily WHERE date = ?
''', (target_date,))
row = cursor.fetchone()
print(f"验证：{target_date} 共 {row[0]} 条记录，{row[1]} 只股票")

conn.close()
bs.logout()

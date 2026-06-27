#!/usr/bin/env python3
"""低并发同步（单线程，避免被墙）"""
import sys, sqlite3, time
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path('src')))
from chanlun.utils.trading_calendar import get_calendar

cal = get_calendar()
DB_PATH = './db/chanlun_klines.sqlite'

# 获取缺失日期
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('SELECT MAX(date) FROM stock_daily')
latest = cursor.fetchone()[0] or '2026-05-08'
conn.close()

missing = []
current = datetime.strptime(latest, '%Y-%m-%d')
while current < datetime.now():
    current += timedelta(days=1)
    d = current.strftime('%Y-%m-%d')
    if cal.is_trading_day(d):
        missing.append(d)

if not missing:
    print("✅ 数据已是最新")
    sys.exit(0)

start_date, end_date = missing[0], missing[-1]
print(f"缺失：{len(missing)}天 ({start_date}~{end_date})")

# 获取股票列表
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute('SELECT DISTINCT symbol FROM stock_daily')
symbols = [row[0] for row in cursor.fetchall()]
conn.close()

print(f"股票数：{len(symbols)}")
print(f"数据源：Baostock (前复权)")

# 单线程同步
import baostock as bs
all_data = []
failed = []

for i, sym in enumerate(symbols):
    prefix = "sh" if sym.startswith(("6", "68")) else "sz"
    code = f"{prefix}.{sym}"
    
    # 登录
    bs.login()
    
    try:
        rs = bs.query_history_k_data_plus(
            code, "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"
        )
        if rs.error_code == "0":
            data = rs.get_result()['data']
            for row in data:
                all_data.append([sym, row[0], row[1], row[2], row[3], row[4], row[5], row[6]])
        else:
            failed.append((sym, rs.error_msg))
    except Exception as e:
        failed.append((sym, str(e)))
    finally:
        bs.logout()
    
    if (i + 1) % 500 == 0:
        print(f"进度：{i+1}/{len(symbols)}, 收集 {len(all_data)}条，失败 {len(failed)}")
    time.sleep(0.1)  # 避免过快请求

bs.logout()

if not all_data:
    print("❌ 无数据")
    sys.exit(1)

# 写入数据库
print(f"写入 {len(all_data)}条数据...")
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 删除旧数据
for d in missing:
    cursor.execute('DELETE FROM stock_daily WHERE date=?', (d,))

# 插入新数据
cursor.executemany(
    'INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?,?,?,?,?,?,?,?)',
    all_data
)
conn.commit()

# 验证
cursor.execute('SELECT MAX(date), COUNT(DISTINCT symbol) FROM stock_daily')
row = cursor.fetchone()
print(f"✅ 完成！最新：{row[0]}, 股票数：{row[1]}")

for d in missing:
    cursor.execute('SELECT COUNT(*) FROM stock_daily WHERE date=?', (d,))
    print(f"  {d}: {cursor.fetchone()[0]:,}行")

conn.close()
print(f"失败：{len(failed)}只")
for sym, err in failed[:5]:
    print(f"  {sym}: {err}")
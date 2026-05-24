#!/usr/bin/env bash
# 每日收盘后补齐当日 K 线数据
# 1. 同步交易日历
# 2. 判断今天是否是交易日
# 3. 是则补充 stock_daily + kline_cache 当日数据
set -euo pipefail

LOGFILE="/tmp/daily_update_$(date +%Y%m%d).log"
cd /home/dogzi/.openclaw/workspace/a-stock-analyst

echo "=== $(date) 开始每日更新 ===" >> "$LOGFILE"

# 1. 同步交易日历
echo "--- 交易日历同步 ---" >> "$LOGFILE"
python3 -c "
import sys, sqlite3
sys.path.insert(0, 'backend')
from pathlib import Path
import baostock as bs
DB = str(Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite')
bs.login()
rs = bs.query_trade_dates(start_date='2024-01-01', end_date='2028-12-31')
rows = []
while rs.next():
    r = rs.get_row_data()
    rows.append((r[0], int(r[1])))
bs.logout()
conn = sqlite3.connect(DB)
conn.executemany('INSERT OR REPLACE INTO trade_calendar (calendar_date, is_trading_day) VALUES (?, ?)', rows)
conn.commit()
conn.close()
print(f'trade_calendar 已同步: {len(rows)} 天')
" >> "$LOGFILE" 2>&1

# 2. 判断今天是否是交易日
TODAY=$(date +%Y-%m-%d)
echo "--- 检查交易日: $TODAY ---" >> "$LOGFILE"
IS_TRADING=$(python3 -c "
import sys, sqlite3
from pathlib import Path
DB = str(Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite')
conn = sqlite3.connect(DB)
r = conn.execute('SELECT is_trading_day FROM trade_calendar WHERE calendar_date=?', ('$TODAY',)).fetchone()
conn.close()
if r and r[0] == 1: print('1')
else: print('0')
" 2>/dev/null)

if [ "$IS_TRADING" != "1" ]; then
    echo "⏭️ $TODAY 非交易日，跳过数据同步" >> "$LOGFILE"
    echo "=== $(date) 完成 ===" >> "$LOGFILE"
    cat "$LOGFILE"
    exit 0
fi

echo "✅ $TODAY 是交易日，开始数据同步" >> "$LOGFILE"

# 3. 检查 baostock 今日数据是否就绪
echo "--- 检查 baostock 今日数据是否就绪 ---" >> "$LOGFILE"
DATA_READY=$(python3 -c "
import baostock as bs
import sys
# 将 baostock 的 stdout 重定向到 stderr（只保留 print(ok) 到 stdout）
bs.login()
rs = bs.query_history_k_data_plus('sh.600000', 'date,open,close', start_date='$TODAY', end_date='$TODAY', frequency='d', adjustflag='2')
ok = 0
while rs.next():
    r = rs.get_row_data()
    if r[0] and r[1] != '': ok = 1
bs.logout()
print(ok)
" 2>/dev/null | tail -1)

if [ "$DATA_READY" != "1" ]; then
    echo "⏸️ baostock 今日数据尚未就绪，跳过（通常 17:00 后可用）" >> "$LOGFILE"
    echo "=== $(date) 完成（数据未就绪）===" >> "$LOGFILE"
    cat "$LOGFILE"
    exit 0
fi

# 4. stock_daily 增量（baostock 前复权）- 优化版：分批查询，减少 sleep
echo "--- stock_daily 增量 ---" >> "$LOGFILE"
python3 -c "
import sys, sqlite3, time
sys.path.insert(0, 'backend')
from pathlib import Path
import baostock as bs
DB = str(Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite')

conn = sqlite3.connect(DB)
stocks = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM stock_daily').fetchall()]
conn.close()

print(f'需处理 {len(stocks)} 只股票', flush=True)

bs.login()

# 分批处理，每批 100 只后写一次 DB，避免长时间无输出
batch_size = 100
all_batch = []
total_ok = 0
total_fail = 0
total_has_data = 0

for idx, code in enumerate(stocks):
    prefix = 'sh' if code.startswith('6') or code.startswith('68') else 'sz'
    try:
        rs = bs.query_history_k_data_plus(
            f'{prefix}.{code}',
            'date,open,high,low,close,volume,amount',
            start_date='$TODAY', end_date='$TODAY',
            frequency='d', adjustflag='2'
        )
        while rs.next():
            r = rs.get_row_data()
            if r[0] and r[1] != '':
                all_batch.append({
                    'symbol': code, 'date': r[0],
                    'open': float(r[1]), 'high': float(r[2]),
                    'low': float(r[3]), 'close': float(r[4]),
                    'volume': float(r[5] or 0), 'turnover': float(r[6] or 0),
                })
                total_has_data += 1
        total_ok += 1
    except:
        total_fail += 1

    # 每批写入 + 进度
    if (idx + 1) % batch_size == 0:
        print(f'进度: {idx+1}/{len(stocks)} (OK:{total_ok} Fail:{total_fail} Data:{total_has_data})', flush=True)

    time.sleep(0.005)  # 5ms 就够了

if all_batch:
    import pandas as pd
    df = pd.DataFrame(all_batch)
    conn = sqlite3.connect(DB)
    # 逐条 upsert 避免主键冲突
    for _, row in df.iterrows():
        conn.execute('''
            INSERT OR REPLACE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover)
            VALUES (?,?,?,?,?,?,?,?)
        ''', (row['symbol'], row['date'], row['open'], row['high'],
              row['low'], row['close'], row['volume'], row['turnover']))
    conn.commit()
    conn.close()
    print(f'stock_daily 写入完成: {len(all_batch)} 条')
else:
    print(f'今日无新数据 (OK:{total_ok} Fail:{total_fail})')

bs.logout()
print('stock_daily 增量完成', flush=True)
" >> "$LOGFILE" 2>&1

# 5. kline_cache 增量（仅日线，分钟线凌晨单独跑）
echo "--- kline_cache 日线增量 ---" >> "$LOGFILE"
python3 backend/scripts/data_update.py --mode daily >> "$LOGFILE" 2>&1

echo "=== $(date) 完成 ===" >> "$LOGFILE"
cat "$LOGFILE"

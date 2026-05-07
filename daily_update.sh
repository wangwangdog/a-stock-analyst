#!/usr/bin/env bash
# 每日收盘后（17:00）补齐当日 K 线数据
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
from pathlib import Path
sys.path.insert(0, 'backend')
import baostock as bs
DB = 'backend/data/stock_cache.db'
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
DB = 'backend/data/stock_cache.db'
conn = sqlite3.connect(DB)
r = conn.execute('SELECT is_trading_day FROM trade_calendar WHERE calendar_date=?', ('$TODAY',)).fetchone()
conn.close()
if r and r[0] == 1:
    print('1')
else:
    print('0')
" 2>/dev/null)

if [ "$IS_TRADING" = "1" ]; then
    echo "✅ $TODAY 是交易日，开始数据同步" >> "$LOGFILE"

    # 3. stock_daily 增量（baostock 前复权）
    echo "--- stock_daily 增量 ---" >> "$LOGFILE"
    python3 -c "
import sys, sqlite3, time
from pathlib import Path
sys.path.insert(0, 'backend')
import baostock as bs
DB = 'backend/data/stock_cache.db'

conn = sqlite3.connect(DB)
# 获取已有05-06有数据但无今日数据的股票
today = '$TODAY'
stocks = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM stock_daily').fetchall()]
conn.close()

bs.login()
inserted = 0
failed = 0
batch = []
for code in stocks:
    prefix = 'sh' if code.startswith('6') or code.startswith('68') else 'sz'
    try:
        rs = bs.query_history_k_data_plus(
            f'{prefix}.{code}',
            'date,open,high,low,close,volume,amount',
            start_date=today, end_date=today,
            frequency='d', adjustflag='2'
        )
        while rs.next():
            r = rs.get_row_data()
            if r[0] and r[1] != '':
                batch.append({
                    'symbol': code, 'date': r[0],
                    'open': float(r[1]), 'high': float(r[2]),
                    'low': float(r[3]), 'close': float(r[4]),
                    'volume': float(r[5] or 0), 'turnover': float(r[6] or 0),
                })
        time.sleep(0.02)
        inserted += 1
    except:
        failed += 1

if batch:
    import pandas as pd
    df = pd.DataFrame(batch)
    conn = sqlite3.connect(DB)
    df.to_sql('stock_daily', conn, if_exists='append', index=False, method='multi')
    conn.commit()
    conn.close()
    print(f'stock_daily 新增 {len(batch)} 条 ({inserted} OK, {failed} fail)')
else:
    print(f'无新数据 ({inserted} OK, {failed} fail)')
bs.logout()
" >> "$LOGFILE" 2>&1

    # 4. kline_cache 增量
    echo "--- kline_cache 增量 ---" >> "$LOGFILE"
    python3 backend/scripts/data_update.py >> "$LOGFILE" 2>&1

else
    echo "⏭️ $TODAY 非交易日，跳过数据同步" >> "$LOGFILE"
fi

echo "=== $(date) 完成 ===" >> "$LOGFILE"

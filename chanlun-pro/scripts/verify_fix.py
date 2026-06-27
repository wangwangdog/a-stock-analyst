"""验证数据库365天数据的修复效果"""
import sys, os
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/cl-vendors/chanlun-pro/src')
from chanlun.cl2 import CD, SHOW_LAST_BI_MERGE
from chanlun.cl_utils import query_cl_chart_config
import pandas as pd
import sqlite3

print(f'SHOW_LAST_BI_MERGE = {SHOW_LAST_BI_MERGE}')

# 从数据库取数据（和后端一样，365天）
db_path = os.path.expanduser('~') + '/.chanlun_pro/db/chanlun_klines.sqlite'
conn = sqlite3.connect(db_path)
rows = conn.execute('''
    SELECT date, open, high, low, close, volume, turnover as amount
    FROM stock_daily WHERE symbol = ? ORDER BY date DESC LIMIT 365
''', ('000001',)).fetchall()
conn.close()
print(f'数据库: {len(rows)} 条')

df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

base_cfg = query_cl_chart_config('a', '000001') or {}
cd = CD('SH.000001', 'day', config=base_cfg)
cd.process_klines(df)

bis = cd.get_bis()
print(f'总BI数: {len(bis)}')
print()
print('全部BI:')
for b in bis:
    span = abs(b.end.k.index - b.start.k.index) + 1
    print(f'  BI#{b.index+1}(idx={b.index}) {b.type:>4s} | {str(b.start.k.date)[:10]}~{str(b.end.k.date)[:10]} | span={span}K')

same = [(i,bis[i-1].type,bis[i].type) for i in range(1,len(bis)) if bis[i-1].type==bis[i].type]
if same:
    print(f'\n同向 {len(same)} 处:')
    for i,t1,t2 in same:
        print(f'  ⚠ BI#{i}({t1})~BI#{i+1}({t2})')
else:
    print('\n全部交替 ✓')

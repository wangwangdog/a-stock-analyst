"""诊断 cl2.py 5笔中枢 — 看 bis 数据"""
import sys
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/chanlun-pro')
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/src')

import pandas as pd
import sqlite3
from chanlun.cl2 import CD, _five_bi_condition, _build_bi_zss, _check_middle_overlap

conn = sqlite3.connect('/home/dogzi/.chanlun_pro/db/chanlun_klines.sqlite')
df = pd.read_sql("SELECT date,open,high,low,close,volume,turnover FROM stock_daily WHERE symbol='000001' AND date>='2024-01-01' ORDER BY date", conn)
conn.close()
print(f'K线数: {len(df)}')

cd = CD('000001', 'd')
cd.process_klines(df)
bis = cd.get_bis()
print(f'笔数: {len(bis)}')
print(f'笔方向序列(最近20笔): {[b.type for b in bis[-20:]]}')
print(f'全部笔方向: {[b.type for b in bis]}')

# 检查5笔条件
found = 0
for i in range(len(bis) - 4):
    b1, b2, b3, b4, b5 = bis[i], bis[i+1], bis[i+2], bis[i+3], bis[i+4]
    # 方向条件
    if b1.type == b5.type and b1.type != b2.type and b4.type != b5.type and b2.type != b3.type and b3.type != b4.type:
        overlap = _check_middle_overlap(b2, b3, b4)
        has_ov = 'ZG>ZD' if overlap else 'NO'
        print(f'  #{i}: b1={b1.type} b2={b2.type} b3={b3.type} b4={b4.type} b5={b5.type} | OL={has_ov}')
        if overlap:
            zg, zd, gg, dd = overlap
            print(f'       ZG={zg:.2f} ZD={zd:.2f} | b2={b2.high:.2f}/{b2.low:.2f} b3={b3.high:.2f}/{b3.low:.2f} b4={b4.high:.2f}/{b4.low:.2f}')
            found += 1

print(f'\n方向匹配+重叠: {found}个')

zss = _build_bi_zss(bis)
print(f'最终中枢数: {len(zss)}')
for z in zss:
    print(f'  ZS: type={z.type} zg={z.zg:.2f} zd={z.zd:.2f} gg={z.gg:.2f} dd={z.dd:.2f} lines={z.line_num}')

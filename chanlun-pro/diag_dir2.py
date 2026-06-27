"""诊断 cl2.py — 5分钟K线，检查方向不匹配的中枢详情"""
import sys
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/src')

import pandas as pd
import sqlite3

DB_PATH = '/home/dogzi/.chanlun_pro/db/chanlun_klines.sqlite'

conn = sqlite3.connect(DB_PATH)
df = pd.read_sql(
    "SELECT dt as date, o as open, h as high, l as low, c as close, v as volume "
    "FROM a_klines_000001 WHERE code='000001' AND f='5m' "
    "ORDER BY dt",
    conn
)
conn.close()
print(f'K线数: {len(df)}')

from chanlun.cl2 import CD, _build_zss_from_bis

cd = CD('000001', '5m')
cd.process_klines(df)

bis = cd.get_bis()
print(f'笔总数: {len(bis)}')

zss = _build_zss_from_bis(bis)
print(f'\n中枢总数: {len(zss)}\n')

failed = []
for idx, zs in enumerate(zss):
    lines = zs.lines
    entry = lines[0]
    exit_pen = lines[-1]
    dir_ok = entry.type == exit_pen.type
    if not dir_ok:
        failed.append(idx)
        print(f'  ❌ ZS#{idx}: 笔数={len(lines)}')
        print(f'     进入笔: idx={entry.index} type={entry.type} start={entry.start.val:.2f} end={entry.end.val:.2f}')
        print(f'     离开笔: idx={exit_pen.index} type={exit_pen.type} start={exit_pen.start.val:.2f} end={exit_pen.end.val:.2f}')
        dirs = [b.type for b in lines]
        print(f'     所有笔方向: {dirs}')
        print(f'     入口笔索引: {lines[0].index}')
        print(f'     出口笔索引: {lines[-1].index}')
        print()

print(f'\n--- 总计 ---')
print(f'总中枢: {len(zss)}, 方向不匹配: {len(failed)}: {failed}')

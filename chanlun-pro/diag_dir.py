"""诊断 cl2.py — 5分钟K线检查每个中枢离开笔与进入笔同向"""
import sys
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/src')

import pandas as pd
import sqlite3

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

# ── 1. 取数据 ──
conn = sqlite3.connect(DB_PATH)
df = pd.read_sql(
    "SELECT dt as date, o as open, h as high, l as low, c as close, v as volume "
    "FROM a_klines_000001 WHERE code='000001' AND f='5m' "
    "ORDER BY dt",
    conn
)
conn.close()
print(f'K线数: {len(df)}')

# ── 2. 运行 cl2 引擎 ──
from chanlun.cl2 import CD, _build_zss_from_bis

cd = CD('000001', '5m')
cd.process_klines(df)

bis = cd.get_bis()
print(f'笔总数: {len(bis)}')
dir_seq = [b.type for b in bis]
print(f'笔方向序列: {dir_seq}')

# ── 3. 构建中枢 ──
zss = _build_zss_from_bis(bis)
print(f'\n中枢总数: {len(zss)}')
print()

# ── 4. 检查每个中枢 ──
failed = 0
for idx, zs in enumerate(zss):
    lines = zs.lines
    if len(lines) < 2:
        print(f'  ZS#{idx}: 笔数={len(lines)} 跳过')
        continue
    entry = lines[0]
    exit_pen = lines[-1]
    dir_ok = entry.type == exit_pen.type
    
    status = '✅' if dir_ok else '❌'
    if not dir_ok:
        failed += 1
    
    print(f'  {status} ZS#{idx}: '
          f'进入笔={entry.type} 离开笔={exit_pen.type} '
          f'笔数={zs.line_num} '
          f'ZG={zs.zg:.2f} ZD={zs.zd:.2f} '
          f'done={zs.done}')

print(f'\n--- 结论 ---')
print(f'总中枢: {len(zss)}, 方向不匹配: {failed}')
if failed == 0:
    print('✅ 所有中枢进入笔与离开笔同向')
else:
    print(f'❌ {failed} 个中枢方向不匹配')

"""诊断 cl2.py — 追踪中枢构建过程，检查方向逻辑"""
import sys
sys.path.insert(0, '/home/dogzi/.openclaw/workspace/cl-vendors/chanlun-pro/src')

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

from chanlun.cl2 import CD, _build_zss_from_bis
import types

cd = CD('000001', '5m')
cd.process_klines(df)
bis = cd.get_bis()

# ── Monkey-patch _build_zss_from_bis to add debug ──
_original = _build_zss_from_bis.__code__

# Run with debug: override the SHOW_ENTRY_EXIT_DIR_CHECK to add logging
# We'll intercept after the build and check the zs_lines

# First, let's build without the monkey patch to get results
zss = _build_zss_from_bis(bis)

# For failing zhongshus, trace back through the bis data
for idx, zs in enumerate(zss):
    lines = zs.lines
    entry = lines[0]
    exit_pen = lines[-1]
    if entry.type != exit_pen.type:
        print(f'\n═══ ZS#{idx} 方向不匹配 ═══')
        print(f'进入笔: idx={entry.index} type={entry.type} end={entry.end.val:.2f}')
        print(f'离开笔: idx={exit_pen.index} type={exit_pen.type} end={exit_pen.end.val:.2f}')
        print(f'笔数: {len(lines)}')
        
        # Check what the direction check should have seen
        # Find the building loop variable i (entry index)
        i = entry.index
        print(f'\n-- bis[{i}] to bis[{exit_pen.index}] ({exit_pen.index - i + 1} indices) --')
        
        # Check 5-pen initial setup
        if i + 4 < len(bis):
            b5th = bis[i+4]
            print(f'bis[{i+4}] (5th pen): type={b5th.type} start={b5th.start.val:.2f} end={b5th.end.val:.2f}')
            print(f'  方向检查(步4入口): {b5th.type == entry.type} → {"通过" if b5th.type == entry.type else "❌ 应跳过"}')
        
        # Find where exit is in terms of bis list
        exit_idx = exit_pen.index
        print(f'\n离开笔在bis中的索引: {exit_idx}')
        
        # Check which path: 5-pen or 3-pen
        if i + 4 < len(bis):
            print(f'路径: 5笔模式 (i+4={i+4} < len={len(bis)})')
        else:
            print(f'路径: 3笔模式 (i+4={i+4} >= len={len(bis)})')

print(f'\n总计: {len(zss)} 中枢, {sum(1 for zs in zss if zs.lines[0].type != zs.lines[-1].type)} 方向不匹配')

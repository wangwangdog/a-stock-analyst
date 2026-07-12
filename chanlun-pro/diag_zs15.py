#!/usr/bin/env python3
"""ZS15检查"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis, _bi_top, _bi_bottom
from chanlun.cl_utils import query_cl_chart_config

conn = sqlite3.connect(DB)
rows = conn.execute(
    "SELECT trade_date as date, open, high, low, close, volume, amount "
    "FROM kline_cache WHERE symbol='SH.000001' AND period='daily' ORDER BY trade_date"
).fetchall()
conn.close()
df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
df['date'] = pd.to_datetime(df['date'], format='mixed')

cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SH.000001", "daily", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)

for idx, zs in enumerate(zss):
    fn = idx + 1
    if fn not in [15, 16]: continue
    
    m = zs.lines[1:-1]
    zg = min(_bi_top(b) for b in m) if m else zs.zg
    zd = max(_bi_bottom(b) for b in m) if m else zs.zd
    
    print(f"\nZS{fn}: type={zs.type} lines={zs.line_num}")
    print(f"  zs.lines: {[b.index for b in zs.lines]}")
    print(f"  ZG={zg:.2f} ZD={zd:.2f} init_ZG={zs.zg:.2f} init_ZD={zs.zd:.2f}")
    print(f"  ext_ZG={getattr(zs,'ext_zg','?'):.2f} ext_ZD={getattr(zs,'ext_zd','?'):.2f}")
    
    enter_idx = zs.lines[0].index
    exit_idx = zs.lines[-1].index
    
    print(f"\n  进入笔→离开笔范围 b[{enter_idx}]~b[{exit_idx}] 全部笔:")
    for bi_idx in range(enter_idx, min(exit_idx + 1, len(bis))):
        b = bis[bi_idx]
        in_zs = b.index in {x.index for x in zs.lines}
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        both_out = s_out and e_out
        
        tag = ""
        if in_zs and b.index == enter_idx: tag = " [进入]"
        elif in_zs and b.index == exit_idx: tag = " [离开]"
        elif in_zs: tag = " ★中间"
        if both_out and not in_zs: tag += " ←两端在外"
        
        print(f"  b[{bi_idx:3d}] {b.type:5s} start={b.start.val:8.2f} end={b.end.val:8.2f}{tag}")
    
    # 检查在时间窗口内但不在 zs.lines 中的笔
    print(f"\n  范围内非中枢笔:")
    for bi_idx in range(enter_idx, min(exit_idx + 1, len(bis))):
        if bi_idx in {x.index for x in zs.lines}: continue
        b = bis[bi_idx]
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        both_out = s_out and e_out
        above = b.start.val > zg and b.end.val > zg
        below = b.start.val < zd and b.end.val < zd
        pos = "↑全部在ZG上" if above else ("↓全部在ZD下" if below else "区间内外混合")
        print(f"  b[{bi_idx:3d}] {b.type:5s} start={b.start.val:8.2f} end={b.end.val:8.2f} {pos}")

#!/usr/bin/env python3
"""ZS21 全范围笔"""

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

# Show ZS21
for idx, zs in enumerate(zss):
    if idx + 1 != 21: continue
    zs21 = zs
    break

m = zs21.lines[1:-1]
zg = min(_bi_top(b) for b in m) if m else zs21.zg
zd = max(_bi_bottom(b) for b in m) if m else zs21.zd
zs_indices = {b.index for b in zs21.lines}

print(f"ZS21: 区间 [{zd:.2f}, {zg:.2f}] 笔 {zs21.lines[0].index}~{zs21.lines[-1].index}")
print(f"zs.lines: {[b.index for b in zs21.lines]}")
print()

# Show all pens from show all
for bi_idx in range(630, min(670, len(bis))):
    b = bis[bi_idx]
    in_zs = b.index in zs_indices
    s_out = b.start.val < zd or b.start.val > zg
    e_out = b.end.val < zd or b.end.val > zg
    
    tag = ""
    if in_zs and b.index == zs21.lines[0].index: tag = " [进入]"
    elif in_zs and b.index == zs21.lines[-1].index: tag = " [离开]"
    elif in_zs: tag = " ★中间"
    
    if bi_idx == 661: tag += " ← BI661"
    if bi_idx == 653: tag += " ← BI653"
    
    print(f"b[{bi_idx:3d}] {b.type:5s} start={b.start.val:8.2f} end={b.end.val:8.2f} "
          f"start={'外' if s_out else '内'} end={'外' if e_out else '内'}{tag}")

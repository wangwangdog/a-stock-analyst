#!/usr/bin/env python3
"""ZS19 检查"""

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
    if idx + 1 != 19: continue
    fn = idx + 1
    
    m = zs.lines[1:-1]
    zg = min(_bi_top(b) for b in m) if m else zs.zg
    zd = max(_bi_bottom(b) for b in m) if m else zs.zd
    zs_indices = {b.index for b in zs.lines}
    
    print(f"ZS{fn}: type={zs.type} lines={zs.line_num}")
    print(f"  zs.lines: {[b.index for b in zs.lines]}")
    print(f"  ZG={zg:.4f} ZD={zd:.4f}")
    print(f"  init: ZG={zs.zg:.4f} ZD={zs.zd:.4f}")
    print(f"  ext: ZG={getattr(zs,'ext_zg','?'):.4f} ZD={getattr(zs,'ext_zd','?'):.4f}")
    
    print(f"\n  进入笔后至离开笔+5范围内:")
    for bi_idx in range(zs.lines[0].index, min(zs.lines[-1].index + 10, len(bis))):
        b = bis[bi_idx]
        in_zs = b.index in zs_indices
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        above = b.start.val > zg and b.end.val > zg
        below = b.start.val < zd and b.end.val < zd
        
        tag = ""
        if in_zs and b.index == zs.lines[0].index: tag = " [进入]"
        elif in_zs and b.index == zs.lines[-1].index: tag = " [离开]"
        elif in_zs: tag = " ★中间"
        
        loc = "↑上方" if above else ("↓下方" if below else "区间内")
        print(f"  b[{bi_idx:3d}] {b.type:5s} start={b.start.val:8.2f} end={b.end.val:8.2f} "
              f"{loc}{tag}")

    # Check the specific pens the user mentioned
    print(f"\n  b[616]~b[629] 与中枢关系:")
    for bi_idx in range(616, min(630, len(bis))):
        b = bis[bi_idx]
        above = b.start.val > zg and b.end.val > zg
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        print(f"  b[{bi_idx:3d}] {b.type:5s} start={b.start.val:8.2f} end={b.end.val:8.2f} "
              f"{'全部在ZG之上↑' if above else ''}")

#!/usr/bin/env python3
"""SH.000001 daily 全中枢 + BI595 跟踪"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis
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

def bi_top(b): return b.end.val if b.type == "up" else b.start.val
def bi_bottom(b): return b.end.val if b.type == "down" else b.start.val

# 检查BI595
print(f"=== BI595 ===")
if len(bis) > 595:
    b595 = bis[595]
    print(f"  b[595] type={b595.type} start={b595.start.val:.2f} end={b595.end.val:.2f} "
          f"high={b595.high:.2f} low={b595.low:.2f}")
else:
    print(f"  只有{len(bis)}笔，无BI595")
    sys.exit(0)

# 找到哪个中枢包含了BI595
print(f"\n=== 包含BI595的中枢 ===")
for idx, zs in enumerate(zss):
    first_idx = zs.lines[0].index
    last_idx = zs.lines[-1].index
    if first_idx <= 595 <= last_idx:
        zg, zd = zs.zg, zs.zd
        m = zs.lines[1:-1]
        if m:
            zg = min(bi_top(b) for b in m)
            zd = max(bi_bottom(b) for b in m)
        print(f"  ZS{idx+1}: b[{first_idx}]~b[{last_idx}] ZG={zg:.2f} ZD={zd:.2f}")
        
        b595_in_zs = b595.index in {b.index for b in zs.lines}
        print(f"  BI595 {'在zs.lines中' if b595_in_zs else '不在zs.lines中'}")

# 找到谁是ZS23  
for idx, zs in enumerate(zss):
    if idx + 1 != 23: continue
    first_idx = zs.lines[0].index
    last_idx = zs.lines[-1].index
    print(f"\n=== ZS23 b[{first_idx}]~b[{last_idx}] ===")
    
    # 检查BI595与ZS23的关系
    b595 = bis[595]
    zg, zd = zs.zg, zs.zd
    m = zs.lines[1:-1]
    if m:
        zg = min(bi_top(b) for b in m)
        zd = max(bi_bottom(b) for b in m)
    
    print(f"  中枢区间 ZG={zg:.2f} ZD={zd:.2f}")
    print(f"  BI595 start={b595.start.val:.2f} end={b595.end.val:.2f} range=[{b595.low:.2f},{b595.high:.2f}]")
    
    start_out = b595.start.val < zd or b595.start.val > zg
    end_out = b595.end.val < zd or b595.end.val > zg
    print(f"  起点在中枢外? {start_out}  终点在中枢外? {end_out}")
    print(f"  起点和终点都在中枢外? {start_out and end_out}")
    
    body_overlap = b595.high >= zd and b595.low <= zg
    print(f"  笔身与中枢有重叠? {body_overlap}")
    
    # Check if the visual span includes BI595
    # ZS box draws from enter pen to exit pen
    # If enter pen starts at b[651], then b[595] is before it
    # But if a previous ZS's exit is near b[595], the visual might overlap
    
    # Check all lines in ZS23
    print(f"\n  ZS23 zs.lines: {[b.index for b in zs.lines]}")
    print(f"  ZS23 时间窗口: b[{first_idx}] ~ b[{last_idx}]")
    print(f"  BI595(595) 在时间窗口内? {first_idx <= 595 <= last_idx}")
    
    if first_idx > 595:
        print(f"  → BI595 在 ZS23 时间窗口之前！")
        # Maybe the chart draws from ZS23.start (b[651].end) backwards?
        # Check ZS23.start time
        print(f"  ZS23.start (enter笔end): {zs.start.k.date}")
        print(f"  BI595 end: {bis[595].end.k.date}")

#!/usr/bin/env python3
"""ZS20 与 BI595 详细检查"""

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

# ZS20
for idx, zs in enumerate(zss):
    if idx + 1 != 20: continue
    
    print(f"ZS20: type={zs.type} lines={zs.line_num}")
    print(f"  zs.zg={zs.zg:.2f} zs.zd={zs.zd:.2f}")
    
    m = zs.lines[1:-1]
    zg = min(bi_top(b) for b in m) if m else zs.zg
    zd = max(bi_bottom(b) for b in m) if m else zs.zd
    print(f"  计算ZG={zg:.2f} 计算ZD={zd:.2f}")
    
    first_idx = zs.lines[0].index
    last_idx = zs.lines[-1].index
    zs_indices = {b.index for b in zs.lines}
    
    print(f"\n=== ZS20 时间窗口内所有笔 (b[{first_idx}]~b[{last_idx}]) ===")
    for bi_idx in range(first_idx, min(last_idx + 1, len(bis))):
        b = bis[bi_idx]
        in_zs = b.index in zs_indices
        top = bi_top(b); bottom = bi_bottom(b)
        overlap = (b.high >= zd and b.low <= zg)
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        both_out = s_out and e_out
        body_only = overlap and not (b.high >= zd and b.low <= zg and b.start.val >= zd and b.end.val >= zd)
        
        tag = ""
        if in_zs:
            if b.index == first_idx: tag = " [进入]"
            elif b.index == last_idx: tag = " [离开]"
            else: tag = " ★在ZS中"
        else:
            tag = " [跳过]"
        
        mark = ""
        if bi_idx == 595: mark = " ← BI595"
        
        s_pos = "外" if s_out else "内"
        e_pos = "外" if e_out else "内"
        print(f"  b[{bi_idx}] {b.type:5s} "
              f"start={b.start.val:8.2f}({s_pos}) end={b.end.val:8.2f}({e_pos}) "
              f"range=[{b.low:8.2f},{b.high:8.2f}]"
              f" 笔身{'有' if overlap else '无'}重叠"
              f" 端点{'全外' if both_out else ('部分外' if (s_out or e_out) else '全内')}"
              f"{tag}{mark}")
    
    # 所有笔的端点与中枢区间关系
    print(f"\n=== 端点全在外却在ZS中的笔 ===")
    for b in zs.lines:
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        if s_out and e_out:
            print(f"  b[{b.index}] {b.type} start={b.start.val:.2f} end={b.end.val:.2f}")
            print(f"    ZS范围=[{zd:.2f},{zg:.2f}], 笔身=[{b.low:.2f},{b.high:.2f}]")

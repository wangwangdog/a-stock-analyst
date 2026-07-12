#!/usr/bin/env python3
"""ZS23 全部笔与中枢归属检查"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

def fetch_all():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol='SH.000001' AND period='daily' ORDER BY trade_date"
    ).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    return df

df = fetch_all()
cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SH.000001", "daily", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)

def bi_top(b): return b.end.val if b.type == "up" else b.start.val
def bi_bottom(b): return b.end.val if b.type == "down" else b.start.val

# ZS23
for idx, zs in enumerate(zss):
    if idx + 1 != 23: continue
    
    m = zs.lines[1:-1]
    zg = min(bi_top(b) for b in m) if m else zs.zg
    zd = max(bi_bottom(b) for b in m) if m else zs.zd
    
    print(f"ZS23: 类型={zs.type} 笔数={zs.line_num}")
    print(f"  中枢区间 ZG={zg:.2f} ZD={zd:.2f}")
    print(f"  初始 ZG={zs.zg:.2f} ZD={zs.zd:.2f}")
    print(f"  时间范围: b[{zs.lines[0].index}] → b[{zs.lines[-1].index}]")
    
    # 列出ZS23范围内所有笔（b[651]到b[667]）
    first_idx = zs.lines[0].index
    last_idx = zs.lines[-1].index
    
    zs_indices = {b.index for b in zs.lines}
    
    print(f"\n=== ZS23 时间窗口内所有笔 (b[{first_idx}]~b[{last_idx}]) ===")
    for bi_idx in range(first_idx, min(last_idx + 1, len(bis))):
        b = bis[bi_idx]
        top = bi_top(b)
        bottom = bi_bottom(b)
        in_zs = b.index in zs_indices
        
        # 判断笔身是否与中枢区间重叠
        overlap = (b.high >= zd and b.low <= zg)
        
        # 判断起点终点
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        
        tag = ""
        if in_zs and (b.index == zs.lines[0].index): tag = " [进入笔]"
        elif in_zs and (b.index == zs.lines[-1].index): tag = " [离开笔]"
        elif in_zs: tag = " ★在ZS23中"
        else: tag = "  [非中枢笔]"
        
        print(f"  b[{bi_idx}] {b.type:5s} "
              f"start={b.start.val:8.2f} end={b.end.val:8.2f} "
              f"range=[{b.low:8.2f},{b.high:8.2f}]"
              f" 笔身{'有' if overlap else '无'}重叠"
              f"{tag}")
    
    # 用户特别提到的笔
    print(f"\n=== 用户提到的笔 ===")
    targets = [630, 631, 632, 633, 634, 635, 636, 637, 638, 639, 640, 641, 642, 643, 644, 645, 646, 647, 648, 655, 657, 664]
    for t in targets:
        if t < len(bis):
            b = bis[t]
            in_zs = b.index in zs_indices
            overlap = (b.high >= zd and b.low <= zg)
            print(f"  b[{t}] {b.type:5s} "
                  f"start={b.start.val:8.2f} end={b.end.val:8.2f} "
                  f"range=[{b.low:8.2f},{b.high:8.2f}]"
                  f" {'★在ZS中' if in_zs else '不在ZS中'} "
                  f"笔身{'有' if overlap else '无'}重叠")

    # ZS23 的完整笔列表（包括被skip的笔）
    print(f"\n=== ZS23 完整笔索引 ===")
    print(f"  zs.lines: {[b.index for b in zs.lines]}")
    
    # 检查哪些笔被skip了（算法流程中j跳过）
    # step3: zs_lines初始5笔 [i, i+1, i+2, i+3, i+4]
    # while扩展添加后续笔直到不满足条件
    # step5: 候选笔选出口，跳转到出口笔+1
    # 所以从扩展结束到出口笔之间的笔被skip了
    print(f"\n=== 被跳过(not in lines)笔 ===")
    for bi_idx in range(first_idx, min(last_idx + 1, len(bis))):
        if bi_idx not in zs_indices and bi_idx >= first_idx and bi_idx <= last_idx:
            b = bis[bi_idx]
            overlap = (b.high >= zd and b.low <= zg)
            print(f"  b[{bi_idx}] {b.type:5s} "
                  f"range=[{b.low:8.2f},{b.high:8.2f}] "
                  f"笔身{'有' if overlap else '无'}重叠")

#!/usr/bin/env python3
"""ZS22/ZS23 ZG/ZD 生成逻辑追踪"""

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

for tgt_name, tgt_idx in [("ZS22", 21), ("ZS23", 22)]:
    zs = zss[tgt_idx]
    print(f"\n{'='*70}")
    print(f"{tgt_name} — ZG/ZD 来源分析")
    print(f"{'='*70}")
    print(f"属性: type={zs.type} lines={zs.line_num}")
    print(f"  zs.zg={zs.zg:.4f}  zs.zd={zs.zd:.4f}")
    print(f"  zs.gg={zs.gg:.4f}  zs.dd={zs.dd:.4f}")
    print(f"  ext_zg={getattr(zs,'ext_zg','?'):.4f}  ext_zd={getattr(zs,'ext_zd','?'):.4f}")
    print(f"  zs.lines: {[b.index for b in zs.lines]}")
    
    # 进入笔 + 初始中间3笔
    first3mid = zs.lines[1:4] if len(zs.lines) >= 4 else zs.lines[1:-1]
    print(f"\n┌─ 步骤1: 进入笔 b[{zs.lines[0].index}]")
    print(f"│   enter_end = {zs.lines[0].end.val:.4f}")
    
    print(f"├─ 步骤2: 初始3中间笔 (决定 _init_zg/_init_zd)")
    for b in first3mid:
        t = _bi_top(b)
        bt = _bi_bottom(b)
        print(f"│   b[{b.index}] {b.type:5s} top={t:.4f} bottom={bt:.4f}")
    
    if first3mid:
        init_zg = min(_bi_top(b) for b in first3mid)
        init_zd = max(_bi_bottom(b) for b in first3mid)
        print(f"│   _init_zg = min(top) = {init_zg:.4f}")
        print(f"│   _init_zd = max(bottom) = {init_zd:.4f}")
        print(f"│   重叠? {init_zg > init_zd}")
    
    # 扩展笔
    ext_pens = zs.lines[4:-1] if len(zs.lines) > 5 else []
    if ext_pens:
        print(f"├─ 步骤4a: 延伸笔 ({len(ext_pens)}笔)")
        for b in ext_pens:
            t = _bi_top(b)
            bt = _bi_bottom(b)
            print(f"│   b[{b.index}] {b.type:5s} top={t:.4f} bottom={bt:.4f}")
    
    # 最终中间笔
    mids = zs.lines[1:-1]
    print(f"├─ 最终中间笔 ({len(mids)}笔)")
    for b in mids:
        t = _bi_top(b)
        bt = _bi_bottom(b)
        print(f"│   b[{b.index}] {b.type:5s} top={t:.4f} bottom={bt:.4f}")
    
    if mids:
        final_zg = min(_bi_top(b) for b in mids)
        final_zd = max(_bi_bottom(b) for b in mids)
        print(f"│   final_zg = min(top) = {final_zg:.4f}")
        print(f"│   final_zd = max(bottom) = {final_zd:.4f}")
    
    print(f"├─ 步骤4b: 赋值结果")
    print(f"│   ext_zg = {final_zg if mids else '?'} (延伸后范围)")
    print(f"│   ext_zd = {final_zd if mids else '?'}")
    print(f"│   zs.zg  = {zs.zg} (锁定为 _init_zg = {init_zg if first3mid else '?'})")
    print(f"│   zs.zd  = {zs.zd} (锁定为 _init_zd = {init_zd if first3mid else '?'})")
    
    # 离开笔
    exit_b = zs.lines[-1]
    print(f"└─ 离开笔 b[{exit_b.index}] {exit_b.type} high={exit_b.high:.4f}")
    print(f"   突破检查: exit.high({exit_b.high:.4f}) > zs.zg({zs.zg:.4f})? {exit_b.high > zs.zg}")
    ext_zg = getattr(zs, 'ext_zg', zs.zg)
    print(f"   (ext_zg: exit.high > {ext_zg:.4f}? {exit_b.high > ext_zg})")

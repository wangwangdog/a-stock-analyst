#!/usr/bin/env python3
"""ZS23 延伸终止验证"""

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

# ZS23
for idx, zs in enumerate(zss):
    if idx + 1 != 23: continue
    
    m = zs.lines[1:-1]
    zg = min(_bi_top(b) for b in m) if m else zs.zg
    zd = max(_bi_bottom(b) for b in m) if m else zs.zd
    
    enter_idx = zs.lines[0].index
    exit_idx = zs.lines[-1].index
    
    # 检查b[569]（第一个延伸候选）为什么被终止
    if enter_idx < 569 < exit_idx:
        b569 = bis[569]
        s_out = b569.start.val < zd or b569.start.val > zg
        e_out = b569.end.val < zd or b569.end.val > zg
        overlap = (b569.high >= zd and b569.low <= zg)
        print(f"b[569] (延伸候选): start={b569.start.val:.2f} end={b569.end.val:.2f}")
        print(f"  起点外={s_out} 终点外={e_out} 笔身重叠={overlap}")
        print(f"  终止条件触发: {s_out and e_out}")
    else:
        print(f"b[569] 不在 ZS23 范围内 (enter=b[{enter_idx}], exit=b[{exit_idx}])")
    
    # 列出进入笔后的所有延伸候选笔
    print(f"\nZS23 进入笔后所有连续笔:")
    for bi_idx in range(enter_idx + 1, min(enter_idx + 10, len(bis))):
        b = bis[bi_idx]
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        in_zs = b.index in {x.index for x in zs.lines}
        print(f"  b[{bi_idx}] {b.type:5s} "
              f"start={b.start.val:8.2f}({'外' if s_out else '内'}) "
              f"end={b.end.val:8.2f}({'外' if e_out else '内'})"
              f" {'★在ZS中' if in_zs else ''}")

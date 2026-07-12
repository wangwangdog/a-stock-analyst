#!/usr/bin/env python3
"""验证修复 — 仅关注ZS23"""

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

print(f"笔: {len(bis)}, 中枢: {len(zss)}")
for idx, zs in enumerate(zss):
    print(f"  ZS{idx+1} type={zs.type} lines={zs.line_num} "
          f"进入b[{zs.lines[0].index}] 离开b[{zs.lines[-1].index}]")

# 找ZS23
for idx, zs in enumerate(zss):
    if idx + 1 == 23:
        print(f"\n=== ZS23 ===")
        print(f"  类型: {zs.type}")
        print(f"  笔数: {zs.line_num}")
        print(f"  初始ZG={zs.zg:.2f} ZD={zs.zd:.2f}")
        m = zs.lines[1:-1]
        from chanlun.cl2 import _bi_top, _bi_bottom
        zg = min(_bi_top(b) for b in m) if m else zs.zg
        zd = max(_bi_bottom(b) for b in m) if m else zs.zd
        print(f"  计算ZG={zg:.2f} ZD={zd:.2f}")
        print(f"  zs.lines: {[b.index for b in zs.lines]}")
        
        for li, b in enumerate(zs.lines):
            tag = "[进]" if li == 0 else "[离]" if li == len(zs.lines)-1 else f"[{li}]"
            s_out = b.start.val < zd or b.start.val > zg
            e_out = b.end.val < zd or b.end.val > zg
            print(f"  {tag} b[{b.index}] {b.type:5s} "
                  f"start={b.start.val:8.2f}({'外' if s_out else '内'}) "
                  f"end={b.end.val:8.2f}({'外' if e_out else '内'})")

#!/usr/bin/env python3
"""ZS23 定位 — SZ.000001 5m"""

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
    "FROM kline_cache WHERE symbol='SZ.000001' AND period='5m' ORDER BY trade_date"
).fetchall()
conn.close()
df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
df['date'] = pd.to_datetime(df['date'], format='mixed')
print(f"K线: {len(df)}")

cfg = query_cl_chart_config("sz", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)
print(f"笔: {len(bis)}, 中枢: {len(zss)}")

# 列出所有中枢
for idx, zs in enumerate(zss):
    print(f"  ZS{idx+1} type={zs.type} lines={zs.line_num} "
          f"进入b[{zs.lines[0].index}] 离开b[{zs.lines[-1].index}] "
          f"ZG={zs.zg:.2f} ZD={zs.zd:.2f}")

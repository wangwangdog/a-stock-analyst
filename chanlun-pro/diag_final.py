#!/usr/bin/env python3
"""验证 — 只用2020年后数据"""

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
    "FROM kline_cache WHERE symbol='SH.000001' AND period='daily' "
    "AND trade_date > '2018-01-01' ORDER BY trade_date"
).fetchall()
conn.close()
print(f"K线: {len(rows)}")
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
    lines = [b.index for b in zs.lines]
    print(f"  ZS{idx+1} {zs.type} {zs.line_num}笔 b[{lines[0]}]~b[{lines[-1]}] {lines}")

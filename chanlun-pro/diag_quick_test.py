#!/usr/bin/env python3
"""快速验证 — 不会挂"""

import sys, os, time
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
from chanlun.cl_utils import query_cl_chart_config
from chanlun.exchange import get_exchange
from chanlun.base import Market

ex = get_exchange(Market.A)
klines = ex.klines("SH.000001", "d")
print(f"klines: {len(klines)}", flush=True)

cfg = query_cl_chart_config("a", "000001") or {}
from chanlun.cl2 import CD
cd = CD("SH.000001", "daily", config=cfg)

t0 = time.time()
cd.process_klines(klines)
print(f"process_klines: {time.time()-t0:.1f}s", flush=True)

bis = cd.get_bis()
print(f"bis: {len(bis)}", flush=True)
from chanlun.cl2 import _build_zss_from_bis
t0 = time.time()
zss = _build_zss_from_bis(bis, config=cfg)
print(f"_build_zss_from_bis: {time.time()-t0:.1f}s, zss={len(zss)}", flush=True)
for idx, zs in enumerate(zss):
    print(f"  ZS{idx+1} {zs.type} {zs.line_num}笔 b[{zs.lines[0].index}]~b[{zs.lines[-1].index}]", flush=True)

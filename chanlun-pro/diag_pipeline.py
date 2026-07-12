#!/usr/bin/env python3
"""逐步骤测试TV data pipeline"""

import sys, os, time
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

from chanlun.cl_utils import web_batch_get_cl_datas, cl_data_to_tv_chart, query_cl_chart_config
from chanlun.exchange import get_exchange
from chanlun.base import Market

ex = get_exchange(Market.A)
print("Fetching klines...", flush=True)
t0 = time.time()
klines = ex.klines("SH.000001", "d")
print(f"  {len(klines)} klines in {time.time()-t0:.1f}s", flush=True)

cfg = query_cl_chart_config("a", "000001") or {}
print(f"\nProcessing CD...", flush=True)
t0 = time.time()
cd = web_batch_get_cl_datas("a", "SH.000001", {"d": klines}, cfg, cl_engine="cl2")[0]
print(f"  CD done in {time.time()-t0:.1f}s", flush=True)

print(f"\nGetting bis...", flush=True)
t0 = time.time()
bis = cd.get_bis()
print(f"  {len(bis)} bis in {time.time()-t0:.1f}s", flush=True)

print(f"\nGetting bi_zss...", flush=True)
t0 = time.time()
zss = cd.get_bi_zss()
print(f"  {len(zss)} zss in {time.time()-t0:.1f}s", flush=True)

print(f"\nConverting to TV chart...", flush=True)
t0 = time.time()
chart = cl_data_to_tv_chart(cd, cfg)
print(f"  chart in {time.time()-t0:.1f}s", flush=True)
print(f"  bi_zss: {len(chart.get('bi_zss',[]))}", flush=True)

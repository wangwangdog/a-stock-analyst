#!/usr/bin/env python3
"""验证脚本 — 多品种双周期"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

def bi_top(b):
    return b.end.val if b.type == "up" else b.start.val
def bi_bottom(b):
    return b.end.val if b.type == "down" else b.start.val

def get_zgzd(zs):
    m = zs.lines[1:-1]
    if not m: return zs.zg, zs.zd
    return min(bi_top(b) for b in m), max(bi_bottom(b) for b in m)

cases = [
    ("SH.000001", "daily", "a"),
    ("SZ.000002", "5m", "sz"),
    ("SH.600000", "5m", "a"),
]

for full_sym, period, market in cases:
    bare = full_sym.split('.')[1]
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol=? AND period=? ORDER BY trade_date",
        (full_sym, period)
    ).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    
    cfg = query_cl_chart_config(market, bare) or {}
    cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})
    
    cd = CD(full_sym, period, config=cfg)
    cd.process_klines(df)
    bis = cd.get_bis()
    zss = _build_zss_from_bis(bis, config=cfg)
    
    invalid = 0
    for idx, zs in enumerate(zss):
        zg, zd = get_zgzd(zs)
        if zd > zg:
            invalid += 1
            print(f"❌ {full_sym} {period} ZS{idx+1}: ZD({zd:.2f})>ZG({zg:.2f})")
    
    status = "✅" if invalid == 0 else f"❌({invalid})"
    print(f"{status} {full_sym} {period}: {len(zss)}中枢 ({len(bis)}笔)")

#!/usr/bin/env python3
"""查找BI595以上的数据"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

def try_stock(symbol, market, period="5m"):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol=? AND period=? ORDER BY trade_date",
        (symbol, period)
    ).fetchall()
    conn.close()
    if len(rows) < 5000:
        return None, 0, 0
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    
    bare = symbol.split('.')[1]
    cfg = query_cl_chart_config(market, bare) or {}
    cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})
    
    cd = CD(symbol, period, config=cfg)
    cd.process_klines(df)
    bis = cd.get_bis()
    zss = _build_zss_from_bis(bis, config=cfg)
    return zss, len(bis), len(zss)

# Try SZ.000002 and SH.000001 daily
for sym, market in [("SZ.000002", "sz"), ("SH.000001", "a")]:
    for period in ["5m", "daily"]:
        zss, n_bi, n_zs = try_stock(sym, market, period)
        if zss is None:
            print(f"{sym} {period}: 数据不足")
        else:
            print(f"{sym} {period}: 笔={n_bi}, 中枢={n_zs}", end="")
            if n_zs >= 23 and n_bi >= 595:
                print(" ✅ 足够")
                # Show ZS23
                zs23 = zss[22]
                print(f"  ZS23: 进入b[{zs23.lines[0].index}] 离开b[{zs23.lines[-1].index}]")
                # Check BI595
                if n_bi > 595:
                    print(f"  有BI595")
            else:
                print(f" (需≥23中枢,≥595笔)")

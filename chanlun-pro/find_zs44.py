"""找所有中枢的进入笔"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
from pathlib import Path
HOME = str(Path.home())
DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

def fetch_5m():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT dt as date, o as open, h as high, l as low, c as close, v as volume, 0 as amount FROM a_klines_000001 WHERE f = '5m' ORDER BY dt DESC LIMIT 6000").fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)

from chanlun.cl2 import CD
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m()
cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})
cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = cd.get_bi_zss()

print(f"总中枢: {len(zss)}")
for zs_idx, zs in enumerate(zss):
    entry = zs.lines[0]
    exit_b = zs.lines[-1]
    entry_idx = next(bi_idx for bi_idx, bi in enumerate(bis) if bi is entry)
    exit_idx = next(bi_idx for bi_idx, bi in enumerate(bis) if bi is exit_b)
    print(f"ZS{zs_idx+1}: entry=bis[{entry_idx}] exit=bis[{exit_idx}] {zs.type} {zs.line_num}笔 ZG={zs.zg:.2f}")
    # 如果进入笔接近b324
    if abs(entry_idx - 324) < 5:
        print(f"  ← 接近原ZS44!")
        for zi, zb in enumerate(zs.lines):
            bi_idx = next(bi_idx for bi_idx, bi in enumerate(bis) if bi is zb)
            print(f"    [{zi}] bis[{bi_idx}] type={zb.type} high={zb.high:.2f} end={zb.end.val:.2f}")

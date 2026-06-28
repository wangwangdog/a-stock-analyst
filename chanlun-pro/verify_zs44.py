"""验证 ZS44 延伸到第9笔"""
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
print(f"笔{len(bis)}, 中枢{len(zss)}")

# 找ZS44
for zs_idx, zs in enumerate(zss):
    if zs_idx + 1 != 44:
        continue
    print(f"ZS44: {zs.type} {zs.line_num}笔 ZG={zs.zg:.4f} ZD={zs.zd:.4f}")
    entry_end = zs.lines[0].end.val
    print(f"进入笔末端: {entry_end:.4f}")
    for zi, zb in enumerate(zs.lines):
        i_pos = next((bi_idx for bi_idx, bi in enumerate(bis) if bi is zb), None)
        off = i_pos - (next(bi_idx for bi_idx, bi in enumerate(bis) if bi is zs.lines[0])) if i_pos is not None else '?'
        above_entry = f"end>entry?{zb.end.val > entry_end}" if zs.type == "up" else f"end<entry?{zb.end.val < entry_end}"
        print(f"  [{zi}] bis[{i_pos}] off={off} type={zb.type} high={zb.high:.4f} end={zb.end.val:.4f} {above_entry}")

# 所有中枢笔数分布
print(f"\n=== 笔数分布 ===")
for zs_idx, zs in enumerate(zss):
    print(f"  ZS{zs_idx+1}: {zs.type} {zs.line_num}笔 done={zs.done}")

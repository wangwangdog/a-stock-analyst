"""追踪 ZG 的中间笔来源和最终值"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd, json
from pathlib import Path
HOME = str(Path.home())
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

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

for zs_idx, zs in enumerate(zss):
    if zs_idx + 1 != 44:  # ZS44
        continue
    
    print(f"=== ZS44 zs属性 ===")
    print(f"zs.zg = {zs.zg}")
    print(f"zs.zd = {zs.zd}")
    print(f"zs.gg = {zs.gg}")
    print(f"zs.dd = {zs.dd}")
    print(f"zs.line_num = {zs.line_num}")
    
    m = zs.lines[1:-1]
    print(f"\n=== 中间笔({len(m)}笔) ===")
    for i, b in enumerate(m):
        print(f"  中间笔[{i}]: type={b.type}, high={b.high}, low={b.low}, end={b.end.val}")
    
    zg_computed = min(b.high for b in m)
    zd_computed = max(b.low for b in m)
    gg_computed = max(b.end.val for b in m)
    dd_computed = min(b.end.val for b in m)
    
    print(f"\n=== 计算值 vs zs属性 ===")
    print(f"ZG: zs.zg={zs.zg}, min(high)={zg_computed}, 一致? {abs(zs.zg - zg_computed) < 0.01}")
    print(f"ZD: zs.zd={zs.zd}, max(low)={zd_computed}, 一致? {abs(zs.zd - zd_computed) < 0.01}")
    print(f"GG: zs.gg={zs.gg}, max(end)={gg_computed}, 一致? {abs(zs.gg - gg_computed) < 0.01}")
    print(f"DD: zs.dd={zs.dd}, min(end)={dd_computed}, 一致? {abs(zs.dd - dd_computed) < 0.01}")
    
    # 原始3笔中间笔的ZG
    orig_mid = zs.lines[1:4]  # 前3笔中间笔
    zg_3 = min(b.high for b in orig_mid)
    zd_3 = max(b.low for b in orig_mid)
    print(f"\n=== 扩展前(仅3中间笔) vs 扩展后({len(m)}中间笔) ===")
    print(f"3笔ZG={zg_3}, {len(m)}笔ZG={zg_computed}, 差异={zg_3 - zg_computed}")
    print(f"3笔ZD={zd_3}, {len(m)}笔ZD={zd_computed}, 差异={zd_computed - zd_3}")
    
    # 哪个中间笔拉了ZG
    min_b = min(m, key=lambda b: b.high)
    print(f"\n=== ZG来源笔 ===")
    print(f"ZG={zg_computed} 来自 bis[idx={next((bi_idx for bi_idx,bi in enumerate(bis) if bi is min_b), '?')}]"
          f" type={min_b.type} high={min_b.high} low={min_b.low}")
    
    # 退出笔突破检查
    exit_pen = zs.lines[-1]
    print(f"\n=== 退出笔突破 ===")
    print(f"退出笔: type={exit_pen.type} high={exit_pen.high}")
    print(f"ZG={zg_computed}, 退出笔high > ZG? {exit_pen.high > zg_computed}")
    print(f"如果ZG用3笔值({zg_3}): 退出笔high > {zg_3}? {exit_pen.high > zg_3}")

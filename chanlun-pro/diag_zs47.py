"""诊断 ZS47 — 修复版"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3
import pandas as pd
from pathlib import Path

HOME = str(Path.home())
DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
SYM = "000001"

def fetch_5m_klines():
    conn = sqlite3.connect(DB)
    table = f"a_klines_{SYM}"
    sql = f"SELECT dt as date, o as open, h as high, l as low, c as close, v as volume, 0 as amount FROM {table} WHERE f = '5m' ORDER BY dt DESC LIMIT 5000"
    rows = conn.execute(sql).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)

from chanlun.cl2 import CD
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m_klines()
print(f"K线数量: {len(df)}")

cfg = query_cl_chart_config("a", SYM) or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = cd.get_bi_zss()
print(f"笔: {len(bis)}, 中枢: {len(zss)}")

# 显示最后10个中枢
print(f"\n=== 最后10个中枢 ===")
for idx in range(max(0, len(zss)-10), len(zss)):
    zs = zss[idx]
    m = zs.lines[1:-1]
    zg = min(b.high for b in m) if m else 0
    zd = max(b.low for b in m) if m else 0
    print(f"ZS{idx+1}: type={zs.type}, lines={zs.line_num}, ZG={zg:.2f}, ZD={zd:.2f}, done={zs.done}")

# 显示第45个中枢 (最后一个)
if len(zss) >= 1:
    zs = zss[-1]
    print(f"\n=== 最后一个中枢 ZS{len(zss)} ===")
    print(f"方向: {zs.type}, 笔数: {zs.line_num}, 完成: {zs.done}")
    print(f"ZG: {zs.zg:.2f}, ZD: {zs.zd:.2f}")
    for idx, bi in enumerate(zs.lines):
        print(f"  笔{idx}: type={bi.type}, end_time={bi.end.time}, end={bi.end.val:.2f}, high={bi.high:.2f}, low={bi.low:.2f}")

# 检查第7/9笔条件
print(f"\n=== 检查所有中枢的7/9笔延伸条件 ===")
for zs_idx in range(max(0, len(zss)-5), len(zss)):
    zs = zss[zs_idx]
    m = zs.lines[1:-1]
    zg = min(b.high for b in m) if m else 0
    zd = max(b.low for b in m) if m else 0
    
    if zs.line_num >= 5:
        bi5 = zs.lines[4]
        last_bi = zs.lines[-1]
        print(f"\nZS{zs_idx+1} (type={zs.type}, {zs.line_num}笔):")
        print(f"  ZG={zg:.2f}, ZD={zd:.2f}")
        if zs.type == "up":
            print(f"  第5笔high={bi5.high:.2f}, >ZG? {bi5.high > zg}")
            print(f"  当前离开笔(第{zs.line_num}笔) high={last_bi.high:.2f}, >ZG? {last_bi.high > zg}")
        else:
            print(f"  第5笔low={bi5.low:.2f}, <ZD? {bi5.low < zd}")
            print(f"  当前离开笔(第{zs.line_num}笔) low={last_bi.low:.2f}, <ZD? {last_bi.low < zd}")

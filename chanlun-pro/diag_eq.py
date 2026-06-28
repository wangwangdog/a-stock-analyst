"""精确追踪 5笔high=ZG 时的算法行为"""
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
    sql = f"SELECT dt as date, o as open, h as high, l as low, c as close, v as volume, 0 as amount FROM {table} WHERE f = '5m' ORDER BY dt DESC LIMIT 6000"
    rows = conn.execute(sql).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)

from chanlun.cl2 import CD
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m_klines()
cfg = query_cl_chart_config("a", SYM) or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})
cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = cd.get_bi_zss()

print(f"K线{len(df)}, 笔{len(bis)}, 中枢{len(zss)}")

for zs_idx, zs in enumerate(zss):
    if zs.type != "up" or zs.line_num < 5:
        continue
    m = zs.lines[1:-1]
    zg = min(b.high for b in m)
    bi5 = zs.lines[4]
    
    # 找进入笔在bis中的索引
    i_pos = next((bi_idx for bi_idx, bi in enumerate(bis) if bi is zs.lines[0]), None)
    if i_pos is None:
        continue
    
    exit_high = zs.lines[-1].high
    condition_triggered = exit_high < zg    # 当前代码条件
    condition_with_eq = exit_high <= zg     # 带等号条件
    
    flags = []
    if condition_with_eq:
        flags.append("等号触发")
    if condition_triggered:
        flags.append("当前已触发")
    if exit_high > zg:
        flags.append("已突破")
    
    # 检查7/9笔
    b7_data = "N/A"
    if i_pos + 6 < len(bis):
        b7 = bis[i_pos + 6]
        b7_data = f"type={b7.type}, high={b7.high:.2f} >ZG?{b7.high>zg}"
    b9_data = "N/A"
    if i_pos + 8 < len(bis):
        b9 = bis[i_pos + 8]
        b9_data = f"type={b9.type}, high={b9.high:.2f} >ZG?{b9.high>zg}"
    
    print(f"ZS{zs_idx+1} {zs.line_num}笔: "
          f"5th_high={bi5.high:.2f} ZG={zg:.2f} | "
          f"exit_high={exit_high:.2f} {'<=' if condition_with_eq else '>'}ZG | "
          f"{','.join(flags)} | "
          f"b7[{b7_data}] b9[{b9_data}]")

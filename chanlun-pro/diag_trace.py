"""追踪每个中枢的5→7→9笔完整流程"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3
import pandas as pd
from pathlib import Path

HOME = str(Path.home())
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
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
print(f"K线数量: {len(df)}")

cfg = query_cl_chart_config("a", SYM) or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = cd.get_bi_zss()
print(f"笔: {len(bis)}, 中枢: {len(zss)}")

# 检查每个up中枢: 第5笔没突破时, 第7/9笔是什么情况
for zs_idx, zs in enumerate(zss):
    if zs.type != "up" or zs.line_num < 5:
        continue
    m = zs.lines[1:-1]
    zg = min(b.high for b in m) if m else 0
    zd = max(b.low for b in m) if m else 0
    
    bi5 = zs.lines[4]
    bi_last = zs.lines[-1]
    
    # 找进入笔索引
    entry_bi = zs.lines[0]
    i_pos = None
    for bi_idx, bi in enumerate(bis):
        if bi is entry_bi:
            i_pos = bi_idx
            break
    
    if i_pos is None:
        continue
    
    bi5_break = bi5.high > zg
    
    if not bi5_break:
        # 5笔没突破 → 检查7/9笔
        print(f"\nZS{zs_idx+1} up {zs.line_num}笔: ZG={zg:.2f}")
        print(f"  第5笔(偏移4): high={bi5.high:.2f} >ZG?{bi5_break}, end={bi5.end.val:.2f} >ZG?{bi5.end.val>zg}, type={bi5.type}")
        
        # i+6
        if i_pos + 6 < len(bis):
            b7 = bis[i_pos + 6]
            b7_is_last = b7 is bi_last
            print(f"  第7笔(偏移6): high={b7.high:.2f} >ZG?{b7.high>zg}, end={b7.end.val:.2f}, type={b7.type}, 已经是离开笔?{b7_is_last}")
        
        if i_pos + 8 < len(bis):
            b9 = bis[i_pos + 8]
            b9_is_last = b9 is bi_last
            print(f"  第9笔(偏移8): high={b9.high:.2f} >ZG?{b9.high>zg}, end={b9.end.val:.2f}, type={b9.type}, 已经是离开笔?{b9_is_last}")
        
        # 额外看i+4之后的笔
        print(f"  延伸情况: 当前{zs.line_num}笔", end="")
        if zs.line_num > 5:
            extra_bis = zs.lines[5:]  # 5th index is the 6th pen
            for extra_idx, eb in enumerate(extra_bis):
                is_b7 = (i_pos + 6 < len(bis) and eb is bis[i_pos + 6])
                is_b8 = (i_pos + 7 < len(bis) and eb is bis[i_pos + 7])
                is_b9 = (i_pos + 8 < len(bis) and eb is bis[i_pos + 8])
                labels = []
                if is_b7: labels.append("=b7")
                if is_b8: labels.append("=b8")
                if is_b9: labels.append("=b9")
                lbl = f"({''.join(labels)})" if labels else ""
                print(f"  延伸笔{extra_idx}: high={eb.high:.2f} >ZG?{eb.high>zg}, end={eb.end.val:.2f}, type={eb.type}{lbl}")
        else:
            print(f" (未延伸, 5笔)")

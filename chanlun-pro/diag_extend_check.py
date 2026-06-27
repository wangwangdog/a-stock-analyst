"""诊断每个中枢的延伸条件"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3
import pandas as pd
from pathlib import Path

HOME = str(Path.home())
DB = HOME + "/.chanlun_pro/db/chanlun_klines.sqlite"
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

# 对每个中枢，检查延伸条件
for zs_idx, zs in enumerate(zss):
    m = zs.lines[1:-1]
    zg = min(b.high for b in m) if m else 0
    zd = max(b.low for b in m) if m else 0
    
    if zs.line_num >= 5:
        bi5 = zs.lines[4]
        bi_last = zs.lines[-1]
        
        # 找进入笔在bis中的索引
        entry_bi = zs.lines[0]
        i_pos = None
        for bi_idx, bi in enumerate(bis):
            if bi is entry_bi:
                i_pos = bi_idx
                break
        
        if i_pos is not None:
            check_str = f"  ZG={zg:.2f}"
            
            if zs.type == "up":
                bi5_ok = bi5.high > zg
                bi_last_ok = bi_last.high > zg
                
                # 检查第7、9笔
                b7_str = "N/A"
                if i_pos + 6 < len(bis):
                    b7 = bis[i_pos + 6]
                    b7_str = f"high={b7.high:.2f}, >ZG?{b7.high > zg}, type={b7.type}"
                
                b9_str = "N/A"
                if i_pos + 8 < len(bis):
                    b9 = bis[i_pos + 8]
                    b9_str = f"high={b9.high:.2f}, >ZG?{b9.high > zg}, type={b9.type}"
                
                need_ext = not bi5_ok
                got_ext = zs.line_num > 5
                should_ext = False
                if need_ext:
                    for off in [6, 8]:
                        idx = i_pos + off
                        if idx < len(bis):
                            bk = bis[idx]
                            if bk.type == zs.type and bk.high > zg:
                                should_ext = True
                                break
                
                print(f"ZS{zs_idx+1} up {zs.line_num}笔: 5bi_high={bi5.high:.2f}突破ZG?{bi5_ok}, "
                      f"last_high={bi_last.high:.2f}, need_ext={need_ext}, got_ext={got_ext}, should_ext={should_ext}")
                if need_ext and not got_ext:
                    print(f"  → 需要延伸但未延伸! b7({b7_str}) b9({b9_str})")
            else:
                bi5_ok = bi5.low < zd
                bi_last_ok = bi_last.low < zd
                
                b7_str = "N/A"
                if i_pos + 6 < len(bis):
                    b7 = bis[i_pos + 6]
                    b7_str = f"low={b7.low:.2f}, <ZD?{b7.low < zd}, type={b7.type}"
                
                b9_str = "N/A"
                if i_pos + 8 < len(bis):
                    b9 = bis[i_pos + 8]
                    b9_str = f"low={b9.low:.2f}, <ZD?{b9.low < zd}, type={b9.type}"
                
                need_ext = not bi5_ok
                got_ext = zs.line_num > 5
                should_ext = False
                if need_ext:
                    for off in [6, 8]:
                        idx = i_pos + off
                        if idx < len(bis):
                            bk = bis[idx]
                            if bk.type == zs.type and bk.low < zd:
                                should_ext = True
                                break
                
                print(f"ZS{zs_idx+1} down {zs.line_num}笔: 5bi_low={bi5.low:.2f}突破ZD?{bi5_ok}, "
                      f"last_low={bi_last.low:.2f}, need_ext={need_ext}, got_ext={got_ext}, should_ext={should_ext}")
                if need_ext and not got_ext:
                    print(f"  → 需要延伸但未延伸! b7({b7_str}) b9({b9_str})")
    else:
        print(f"ZS{zs_idx+1} {zs.type} {zs.line_num}笔: 不足5笔, done={zs.done}")

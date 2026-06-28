"""验证修复后: 第9笔延伸"""
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

print(f"\n=== 各中枢笔数分布 ===")
for zs_idx, zs in enumerate(zss):
    print(f"  ZS{zs_idx+1}: {zs.type} {zs.line_num}笔 done={zs.done}")

# 重点关注5笔以上中枢
print(f"\n=== 5笔以上中枢 ===")
multi_count = 0
for zs_idx, zs in enumerate(zss):
    m = zs.lines[1:-1]
    zg = min(b.high for b in m) if m else 0
    zd = max(b.low for b in m) if m else 0
    
    if zs.line_num > 5:
        multi_count += 1
        print(f"  ZS{zs_idx+1}: {zs.type} {zs.line_num}笔 ZG={zg:.2f} ZD={zd:.2f}")
        
        # 显示所有笔
        i_pos = next((bi_idx for bi_idx, bi in enumerate(bis) if bi is zs.lines[0]), None)
        if i_pos is not None:
            for zi, zb in enumerate(zs.lines):
                tag = ""
                for off in range(12):
                    if i_pos + off < len(bis) and bis[i_pos + off] is zb:
                        tag = f"(b{i_pos+off}, off={off})"
                        break
                print(f"    [{zi}]{tag} type={zb.type} high={zb.high:.2f} low={zb.low:.2f} end={zb.end.val:.2f}")
        
        # 离开笔突破检查
        last_bi = zs.lines[-1]
        entry_bi = zs.lines[0]
        i_entry = next(bi_idx for bi_idx, bi in enumerate(bis) if bi is entry_bi)
        
        if zs.type == "up":
            print(f"    离开笔high={last_bi.high:.2f} >ZG={zg:.2f}? {last_bi.high > zg}")
            # 检查第9笔是否存在
            if i_entry + 8 < len(bis):
                b9 = bis[i_entry + 8]
                print(f"    第9笔(offset 8) high={b9.high:.2f} >ZG?{b9.high > zg} type={b9.type}")
                if b9 is last_bi:
                    print(f"    ✅ 第9笔被选为离开笔!")
            if i_entry + 6 < len(bis):
                b7 = bis[i_entry + 6]
                print(f"    第7笔(offset 6) high={b7.high:.2f} >ZG?{b7.high > zg} type={b7.type}")
                if b7 is last_bi:
                    print(f"    ℹ️ 第7笔被选为离开笔")

print(f"\n共{multi_count}个5笔以上中枢")

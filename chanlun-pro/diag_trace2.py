"""Monkey-patch _build_zss_from_bis 追踪 ZS44/ZS38"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3
import pandas as pd
from pathlib import Path
from chanlun import cl2

HOME = str(Path.home())
DB = HOME + "/.chanlun_pro/db/chanlun_klines.sqlite"
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

from chanlun.cl_utils import query_cl_chart_config

# Monkey-patch the _build_zss_from_bis function to add per-zs debug
_original = cl2._build_zss_from_bis

def patched(bis, zs_type="bi", config=None):
    zss = _original(bis, zs_type, config)
    # Post-analysis: check the last few up hubs
    for zs_idx, zs in enumerate(zss):
        if zs.type != "up" or zs.line_num < 5:
            continue
        if zs_idx < len(zss) - 3:
            continue  # Only show last 3
        m = zs.lines[1:-1]
        zg = min(b.high for b in m) if m else 0
        
        i_pos = next((bi_idx for bi_idx, bi in enumerate(bis) if bi is zs.lines[0]), None)
        if i_pos is None:
            continue
        
        print(f"\n=== ZS{zs_idx+1} ({zs.line_num}笔) ZG={zg:.2f} ===")
        print(f"  中枢笔列表:")
        for bi_idx, bi in enumerate(zs.lines):
            off = None
            for o in range(12):
                if i_pos + o < len(bis) and bis[i_pos + o] is bi:
                    off = o
                    break
            print(f"    pen[{bi_idx}] bis[{'?' if off is None else i_pos+off}] type={bi.type} "
                  f"high={bi.high:.2f} low={bi.low:.2f} end={bi.end.val:.2f}")
        
        # Show i_pos附近所有笔
        print(f"  进入笔bis索引={i_pos}, 附近12笔:")
        for off in range(12):
            idx = i_pos + off
            if idx >= len(bis):
                break
            bi = bis[idx]
            marker = ""
            if off == 0: marker = " ←进入"
            for zi, zb in enumerate(zs.lines):
                if zb is bi:
                    marker += f" ←ZS笔{zi}"
            print(f"    bis[{idx}] off={off:2d} type={bi.type} high={bi.high:.2f} low={bi.low:.2f} end={bi.end.val:.2f}{marker}")

cl2._build_zss_from_bis = patched

df = fetch_5m_klines()
cfg = query_cl_chart_config("a", SYM) or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})
from chanlun.cl2 import CD
cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
print("\n=== 完成 ===")

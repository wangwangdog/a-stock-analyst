"""检查 ZS44 在当前 ZG=4215.756 下的延伸行为"""
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

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m()
cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})
cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)

for zs_idx, zs in enumerate(zss):
    if zs_idx + 1 != 44:
        continue
    print(f"ZS44: {zs.type}, {zs.line_num}笔, ZG={zs.zg}, ZD={zs.zd}")
    
    # 模拟算法流程：检查7/9笔
    m = zs.lines[1:-1]
    zg = min(b.high for b in m)
    zd = max(b.low for b in m)
    
    last_bi = zs.lines[-1]
    is_up = zs.type == "up"
    
    print(f"中间笔数={len(m)}, ZG={zg:.4f}, ZD={zd:.4f}")
    print(f"退出笔(第{zs.line_num}笔) high={last_bi.high:.4f}, low={last_bi.low:.4f}")
    if is_up:
        print(f"break? {last_bi.high} > {zg} = {last_bi.high > zg}")
    else:
        print(f"break? {last_bi.low} < {zd} = {last_bi.low < zd}")
    
    # 找进入笔索引
    i_pos = next((bi_idx for bi_idx, bi in enumerate(bis) if bi is zs.lines[0]), None)
    if i_pos is not None:
        print(f"\n7/9笔检查 (i_pos={i_pos}):")
        for off in [6, 8]:
            idx = i_pos + off
            if idx < len(bis):
                bk = bis[idx]
                type_ok = bk.type == zs.type
                if is_up:
                    brk = bk.high > zg
                    print(f"  off={off}(b{idx}): type={bk.type}({'✓' if type_ok else '✗'}), high={bk.high:.4f} > ZG? {brk}")
                else:
                    brk = bk.low < zd
                    print(f"  off={off}(b{idx}): type={bk.type}({'✓' if type_ok else '✗'}), low={bk.low:.4f} < ZD? {brk}")
            else:
                print(f"  off={off}: 超出范围")
    
    # 检查7/9检查是否进入
    print(f"\n7/9检查条件:")
    exit_high = zs.lines[-1].high
    exit_low = zs.lines[-1].low
    cond = (is_up and exit_high <= zg) or (not is_up and exit_low >= zd)
    print(f"  ({is_up} and {exit_high:.4f} <= {zg:.4f}) or ({not is_up} and {exit_low:.4f} >= {zd:.4f})")
    print(f"  是否进入7/9检查: {cond}")

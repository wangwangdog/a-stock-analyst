#!/usr/bin/env python3
"""ZS22 延伸终止条件追踪"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis, _bi_top, _bi_bottom
from chanlun.cl_utils import query_cl_chart_config

conn = sqlite3.connect(DB)
rows = conn.execute(
    "SELECT trade_date as date, open, high, low, close, volume, amount "
    "FROM kline_cache WHERE symbol='SH.000001' AND period='daily' ORDER BY trade_date"
).fetchall()
conn.close()
df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
df['date'] = pd.to_datetime(df['date'], format='mixed')

cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

# patch the module to add debug
import chanlun.cl2 as cl2
_orig_build = cl2._build_zss_from_bis

def debug_build(bis, zs_type="bi", config=None):
    config = config or {}
    if len(bis) < 3:
        return []
    zss = []
    zs_idx = 0
    i = 0
    while i < len(bis) - 2:
        h1, l1 = _bi_top(bis[i]), _bi_bottom(bis[i])
        h2, l2 = _bi_top(bis[i+1]), _bi_bottom(bis[i+1])
        h3, l3 = _bi_top(bis[i+2]), _bi_bottom(bis[i+2])
        zg = min(h1, h2, h3)
        zd = max(l1, l2, l3)
        if not (zg > zd):
            i += 1; continue
        entry_start = bis[i].start.val
        if zg >= entry_start >= zd:
            i += 1; continue
        zs_direction = "up" if bis[i].type == "up" else "down"
        if cl2.SHOW_BIS_EXTEND_BREAK and i + 4 < len(bis):
            zs_lines = [bis[i], bis[i+1], bis[i+2], bis[i+3], bis[i+4]]
            j = i + 5
            middle_pens = zs_lines[1:-1]
            zg = min(_bi_top(b) for b in middle_pens)
            zd = max(_bi_bottom(b) for b in middle_pens)
            gg = max(b.end.val for b in middle_pens)
            dd = min(b.end.val for b in middle_pens)
            if zd > zg:
                i += 1; continue
            entry_end = zs_lines[0].end.val
            exit_end = zs_lines[-1].end.val
            _init_zg = zg; _init_zd = zd
            
            # EXTENSION LOOP - ZS22 specific check
            while cl2.SHOW_BIS_EXTEND and config.get('zs_extend', 1) and j < len(bis):
                bh, bl = _bi_top(bis[j]), _bi_bottom(bis[j])
                if bh >= _init_zd and bl <= _init_zg:
                    # 检查b[555]和b[556]的终止条件
                    _before_sub = zs_lines[1:-1] + [bis[j]]
                    _temp_zg = min(_bi_top(b) for b in _before_sub)
                    _temp_zd = max(_bi_bottom(b) for b in _before_sub)
                    s_out = bis[j].start.val < _temp_zd or bis[j].start.val > _temp_zg
                    e_out = bis[j].end.val < _temp_zd or bis[j].end.val > _temp_zg
                    idx = bis[j].index
                    if idx in [555, 556]:
                        print(f"\n💡 b[{idx}] 终止条件检查:")
                        print(f"    start={bis[j].start.val:.4f} end={bis[j].end.val:.4f}")
                        print(f"    当前ZD={_temp_zd:.4f} ZG={_temp_zg:.4f}")
                        print(f"    start_out={s_out}  end_out={e_out}  both={s_out and e_out}")
                        print(f"    sub笔列表={[b.index for b in zs_lines[1:-1]]} + [{idx}]")
                        for b in zs_lines[1:-1]:
                            print(f"    b[{b.index}] top={_bi_top(b):.4f} bottom={_bi_bottom(b):.4f}")
                        print(f"    新笔b[{idx}]: top={_bi_top(bis[j]):.4f} bottom={_bi_bottom(bis[j]):.4f}")
                        print(f"    temp_zd = max(top{[_bi_top(b) for b in _before_sub]})")
                    zs_lines.append(bis[j]); j += 1
                    sub = zs_lines[1:-1]
                    if sub:
                        zg = min(_bi_top(b) for b in sub)
                        zd = max(_bi_bottom(b) for b in sub)
                    # 终止条件
                    _new_pen = bis[j-1]
                    _start_out = _new_pen.start.val < zd or _new_pen.start.val > zg
                    _end_out = _new_pen.end.val < zd or _new_pen.end.val > zg
                    if _start_out and _end_out:
                        if _new_pen.index in [555, 556]:
                            print(f"    ⛔ 终止条件触发！撤回b[{_new_pen.index}]")
                        zs_lines = zs_lines[:-1]; j -= 1; break
                    
                    # After adding, check extended zd/zg
                    if bis[j-1].index in [555, 556]:
                        sub_after = zs_lines[1:-1]
                        print(f"    添加后sub={[b.index for b in sub_after]}")
                        print(f"    添加后 ZG={zg:.4f} ZD={zd:.4f}")
                else:
                    if bis[j].index in [555, 556]:
                        print(f"   b[{bis[j].index}] 初始范围检查失败: bh({bh:.4f})>={_init_zd}({_init_zd:.4f})={bh>=_init_zd}, bl({bl:.4f})<={_init_zg}({_init_zg:.4f})={bl<=_init_zg}")
                    break
            # ... rest skipped, just return
    return zss

# Override temporarily  
cl2._build_zss_from_bis = debug_build

cd = CD("SH.000001", "daily", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = debug_build(bis, config=cfg)

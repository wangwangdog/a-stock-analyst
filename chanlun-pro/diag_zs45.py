"""诊断 ZS45（精确追踪）"""
import sys, os, math
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
from pathlib import Path
HOME = str(Path.home())
DB = HOME + "/.chanlun_pro/db/chanlun_klines.sqlite"

def fetch_5m():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT dt as date, o as open, h as high, l as low, c as close, v as volume, 0 as amount FROM a_klines_000001 WHERE f = '5m' ORDER BY dt DESC LIMIT 6000").fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config
from chanlun.cl_interface import BI, ZS, FX

df = fetch_5m()
cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()

# 手动调 _build_zss_from_bis 得到zss
zss = _build_zss_from_bis(bis, config=cfg)

print(f"笔{len(bis)}, 中枢{len(zss)}")

# 找ZS45
for zs_idx, zs in enumerate(zss):
    if zs_idx + 1 != 45:
        continue
    
    print(f"\n=== ZS45 (索引{zs_idx}) ===")
    print(f"方向: {zs.type}")
    print(f"笔数: {zs.line_num}, 完成: {zs.done}")
    
    m = zs.lines[1:-1]
    zg = min(b.high for b in m) if m else 0
    zd = max(b.low for b in m) if m else 0
    gg = max(b.end.val for b in m) if m else 0
    dd = min(b.end.val for b in m) if m else 0
    print(f"ZG={zg:.4f} ZD={zd:.4f} GG={gg:.4f} DD={dd:.4f}")
    
    # 找到进入笔索引
    i_pos = next(iter([bi_idx for bi_idx, bi in enumerate(bis) if bi is zs.lines[0]]), None)
    
    for zi, zb in enumerate(zs.lines):
        off_str = ""
        if i_pos is not None:
            for o in range(12):
                if i_pos + o < len(bis) and bis[i_pos + o] is zb:
                    off_str = f"(bis[{i_pos+o}], off={o})"
                    break
        print(f"  笔[{zi}]{off_str} type={zb.type} "
              f"high={zb.high:.4f} low={zb.low:.4f} end={zb.end.val:.4f}")
    
    if zs.line_num >= 5:
        bi5 = zs.lines[4]
        print(f"\n=== 条件检查 ===")
        
        # 条件1: 5笔模式下的突破检查 (第247行)
        exit_high = zs.lines[-1].high
        exit_low = zs.lines[-1].low
        
        print(f"exit_high={exit_high:.4f}, zg={zg:.4f}")
        print(f"exit_low={exit_low:.4f}, zd={zd:.4f}")
        
        # 模拟while循环
        print(f"\n=== 模拟_while_loop (第172行) ===")
        print(f"zs_direction={zs.type}, 5th_pen_end.val={bi5.end.val:.4f}")
        print(f"up direction: exit_end < zg? {zs.type == 'up' and bi5.end.val < zg}")
        print(f"down direction: exit_end > zd? {zs.type == 'down' and bi5.end.val > zd}")
        
        # 显示i_pos周围的笔
        if i_pos is not None:
            print(f"\n=== i_pos={i_pos} 附近12笔 ===")
            for off in range(12):
                idx = i_pos + off
                if idx >= len(bis): break
                b = bis[idx]
                # 标记是否在zss中
                in_zs = any(b is zb for zb in zs.lines)
                mark = " ←★" if in_zs else ""
                print(f"  bis[{idx}] off={off:2d} type={b.type} "
                      f"high={b.high:.4f} low={b.low:.4f} end={b.end.val:.4f}{mark}")
            
            # 模拟while循环的延伸
            print(f"\n=== 模拟延伸检查 ===")
            print(f"while条件: ({zs.type=='up'} and bis[i+4].end.val < zg={zg:.4f}) or ({zs.type=='down'} and bis[i+4].end.val > zd={zd:.4f})")
            
            b5 = bis[i_pos+4]
            if zs.type == 'up':
                print(f"  up: bis[i+4].end.val={b5.end.val:.4f} < zg={zg:.4f} ? {b5.end.val < zg}")
            else:
                print(f"  down: bis[i+4].end.val={b5.end.val:.4f} > zd={zd:.4f} ? {b5.end.val > zd}")
            
            # 检查7/9笔条件
            print(f"\n=== 7/9笔检查 (第247行) ===")
            cond_up = zs.type == 'up' and bi5.high <= zg
            cond_down = zs.type == 'down' and bi5.low >= zd
            print(f"up条件: {zs.type=='up'} and {zs.lines[-1].high:.4f} <= {zg:.4f} ? {cond_up}")
            print(f"down条件: {zs.type=='down'} and {zs.lines[-1].low:.4f} >= {zd:.4f} ? {cond_down}")
            print(f"7/9检查是否进入: {cond_up or cond_down}")
            
            if cond_up or cond_down:
                for off in [6, 8]:
                    idx = i_pos + off
                    if idx < len(bis):
                        bk = bis[idx]
                        type_ok = bk.type == zs.type
                        if zs.type == 'up':
                            brk = bk.high > zg
                            print(f"  偏移{off}(b{idx}): type={bk.type}({'✓' if type_ok else '✗'}), high={bk.high:.4f} > ZG={zg:.4f}?{brk}")
                        else:
                            brk = bk.low < zd
                            print(f"  偏移{off}(b{idx}): type={bk.type}({'✓' if type_ok else '✗'}), low={bk.low:.4f} < ZD={zd:.4f}?{brk}")
                    else:
                        print(f"  偏移{off}: 超出bis范围({len(bis)})")
            else:
                print(f"  7/9检查未进入！原因: exit_high {'>' if zs.type=='up' else '<'} 边界")

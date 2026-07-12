#!/usr/bin/env python3
"""ZS1 深度追踪 — 算法流程逐行分析"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

# ─── 打补丁：临时打开所有DEBUG开关 ───
import chanlun.cl2 as cl2
cl2.SHOW_BIS_OVERLAP_CHECK = 1
cl2.SHOW_BIS_FALLBACK = 1
cl2.SHOW_BIS_EXTEND_BREAK = 1
cl2.SHOW_BIS_EXTEND = 1
cl2.SHOW_BIS_FINAL_RECALC = 1
cl2.SHOW_BIS_MERGE = 1
cl2.SHOW_5_7_9_OPTIMIZE = 1

def fetch_data(period="daily"):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol='SH.000001' AND period=? "
        "ORDER BY trade_date",
        (period,)
    ).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'], format='mixed')
    return df.reset_index(drop=True)

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

df = fetch_data("daily")
print(f"K线数: {len(df)}")

cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({
    "zs_bi_count": 5, "zs_extend": 1,
    "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0
})

cd = CD("SH.000001", "daily", config=cfg)
cd.process_klines(df.iloc[:3000])
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)
print(f"笔: {len(bis)}, 中枢: {len(zss)}")

def bi_top(b):
    return b.end.val if b.type == "up" else b.start.val

def bi_bottom(b):
    return b.end.val if b.type == "down" else b.start.val

# ZS1 深度追踪
print("\n" + "=" * 70)
print("ZS1 深度追踪 — 算法流程")
print("=" * 70)

# 找到组成ZS1的原始笔
zs = zss[0]
print(f"\nZS1: type={zs.type} lines={zs.line_num}")
print(f"  zs.zg={zs.zg:.2f} zs.zd={zs.zd:.2f} (初始/显示值)")
print(f"  zs.gg={zs.gg:.2f} zs.dd={zs.dd:.2f}")
print(f"  ext_zg={getattr(zs,'ext_zg','?'):.2f} ext_zd={getattr(zs,'ext_zd','?'):.2f}")

print(f"\n  ZS1 所有笔:")
for li, b in enumerate(zs.lines):
    tag = "[进]" if li == 0 else "[离]" if li == len(zs.lines)-1 else f"[{li}]"
    print(f"  {tag} b[{b.index}] type={b.type} "
          f"top={bi_top(b):.2f} bottom={bi_bottom(b):.2f} "
          f"high={b.high:.2f} low={b.low:.2f}")

# 模拟算法流程
print(f"\n=== 模拟算法流程 ===")
print(f"进入笔索引: {zs.lines[0].index}")

# 初始3笔
b0 = zs.lines[0]
for step in range(1, min(10, len(zs.lines))):
    if step >= len(zs.lines):
        break
    chunk = [zs.lines[0]] + zs.lines[1:step+1] + ([zs.lines[-1]] if step < len(zs.lines)-1 else [])
    # 至少3笔
    if len(chunk) < 3:
        continue

middle = zs.lines[1:-1]
print(f"\n=== 中间笔 ({len(middle)}笔) 逐笔分析 ===")
for mi, b in enumerate(middle):
    print(f"  m[{mi}] b[{b.index}] type={b.type} top={bi_top(b):.2f} bottom={bi_bottom(b):.2f}")

print(f"\n=== 关键问题: 延伸后 ZD > ZG ===")
print(f"所有中间笔: {len(middle)}笔")
print(f"top值列表: {[f'{bi_top(b):.1f}' for b in middle]}")
print(f"bottom值列表: {[f'{bi_bottom(b):.1f}' for b in middle]}")

# 找出是哪些延伸笔导致 ZD > ZG
# ZG = min(top), ZD = max(bottom)
# 当zd>zg时，至少有一支笔的top低于某支笔的bottom
print(f"\n=== 找到导致ZD>ZG的笔对 ===")
for mi in range(len(middle)):
    for mj in range(len(middle)):
        if mi == mj: continue
        b_i = middle[mi]
        b_j = middle[mj]
        if bi_top(b_i) < bi_bottom(b_j):
            print(f"  m[{mi}].top({bi_top(b_i):.2f}) < m[{mj}].bottom({bi_bottom(b_j):.2f})")
            print(f"    m[{mi}]: b[{b_i.index}] type={b_i.type} top={bi_top(b_i):.2f} bottom={bi_bottom(b_i):.2f}")
            print(f"    m[{mj}]: b[{b_j.index}] type={b_j.type} top={bi_top(b_j):.2f} bottom={bi_bottom(b_j):.2f}")

# 检查扩展流程
print(f"\n=== 初始中间3笔 ===")
init_mid = zs.lines[1:4]
print(f"  笔: [{init_mid[0].index},{init_mid[1].index},{init_mid[2].index}]")
init_top = [bi_top(b) for b in init_mid]
init_bottom = [bi_bottom(b) for b in init_mid]
print(f"  top={init_top} → ZG={min(init_top)}")
print(f"  bottom={init_bottom} → ZD={max(init_bottom)}")
init_ok = min(init_top) > max(init_bottom)
print(f"  初始重叠: ZG({min(init_top):.2f}) > ZD({max(init_bottom):.2f})? {init_ok}")
print(f"  _init_zg={min(init_top):.2f} _init_zd={max(init_bottom):.2f}")

print(f"\n=== ZS_zg={zs.zg:.2f} == _init_zg={min(init_top):.2f}? {abs(zs.zg - min(init_top)) < 0.01}")
print(f"=== ext_zg={getattr(zs,'ext_zg',0):.2f} vs _init_zg={min(init_top):.2f}")

# 遍历所有笔索引，找到哪些笔属于ZS1
b_idx_set = {b.index for b in zs.lines}
print(f"\nZS1 覆盖的笔索引: {sorted(b_idx_set)}")

# 检查ZS1范围内的笔在全部bis中的表现
# 找到ZS1范围内是否有未包含在lines中的笔
start_idx = zs.lines[0].index
end_idx = zs.lines[-1].index
print(f"ZS1 笔范围: [{start_idx}, {end_idx}]")

# 检查merge了哪些子中枢
if hasattr(zs, 'sub_zs_lst') and zs.sub_zs_lst:
    print(f"\n子中枢列表:")
    for sub in zs.sub_zs_lst:
        print(f"  ZS(b{sub.begin_bi.idx}~b{sub.end_bi.idx}) ZG={sub.zg:.2f} ZD={sub.zd:.2f}")
else:
    print(f"\n无子中枢 (非合并产生)")

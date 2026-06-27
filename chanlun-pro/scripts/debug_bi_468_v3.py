"""用AKShare全量数据精准定位BI#467/468问题"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['STOCK_DATA_PATH'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

from src.chanlun.cl2 import CD
from src.chanlun.cl_utils import query_cl_chart_config
import pandas as pd
from datetime import datetime
import akshare as ak

symbol = "SH.000001"
freq = "day"

# ── 1. AKShare全量数据 ──
df = ak.stock_zh_index_daily(symbol="sh000001")
print(f"数据: {len(df)}条, {df['date'].iloc[0]}~{df['date'].iloc[-1]}")

# 和process_klines兼容
df2 = df.copy()
df2['date'] = pd.to_datetime(df2['date'])
df2 = df2.sort_values('date').reset_index(drop=True)
df2['volume'] = df2['volume']
df2['amount'] = df2['volume'] * df2['close']

# ── 2. 跑CD引擎 ──
base_cfg = query_cl_chart_config("a", "000001") or {}
cd = CD(symbol, freq, config=base_cfg)
cd.process_klines(df2)

bis = cd.get_bis()
total = len(bis)
print(f"\n总BI数: {total}")

# ── 找到BI#467, #468, #469 (1-based) ──
for idx in [465, 466, 467, 468, 469, 470]:
    if idx < len(bis):
        b = bis[idx]
        print(f"  BI#{idx+1}(idx={b.index}) | {b.type:>4s} | "
              f"{str(b.start.k.date)[:10]}~{str(b.end.k.date)[:10]} | "
              f"{b.start.val:.2f}->{b.end.val:.2f} | span={abs(b.end.k.index-b.start.k.index)+1}K")

# ── 同向检查 ──
print("\n同向检查:")
same = []
for i in range(1, len(bis)):
    if bis[i-1].type == bis[i].type:
        same.append((i, bis[i-1].type, bis[i].type))
        print(f"  ⚠ BI#{i}({bis[i-1].type})~BI#{i+1}({bis[i].type})")
if not same:
    print("  ✓ 全部交替")

# ── 最后5笔 ──
print("\n最后5笔:")
for i in range(max(0,total-5), total):
    b = bis[i]
    print(f"  BI#{i+1} | {b.type:>4s} | {str(b.start.k.date)[:10]}~{str(b.end.k.date)[:10]}")

# ── 原始CZSC检查 ──
if cd._czsc:
    raw = cd._czsc.bi_list
    print(f"\nCZSC原始: {len(raw)}笔")
    print("原始最后10笔方向:", [("up" if b.direction==1 else "down") for b in raw[-10:]])
    
    # 原始最后3笔
    for i in range(len(raw)-3, len(raw)):
        c = raw[i]
        d = "up" if c.direction==1 else "down"
        print(f"  CZSC#{i} {d} {c.fx_a.elements[1].dt}~{c.fx_b.elements[1].dt} "
              f"fx_a={c.fx_a.fx:.2f} fx_b={c.fx_b.fx:.2f}")

print("\n" + "="*60)
print("BI#467和BI#468: ", end="")
if len(bis) > 467:
    b467 = bis[466]
    b468 = bis[467]
    if b467.type == b468.type:
        print(f"同向! 都是{b467.type}")
    else:
        print(f"反向(正确) — {b467.type}→{b468.type}")

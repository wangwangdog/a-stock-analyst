"""修正后的诊断—正确判断CZSC方向"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['STOCK_DATA_PATH'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

from src.chanlun.cl2 import CD
from src.chanlun.cl_utils import query_cl_chart_config
from czsc.core import Direction as _Direction
import pandas as pd
import akshare as ak

symbol = "SH.000001"
df = ak.stock_zh_index_daily(symbol="sh000001")
df2 = df.copy()
df2['date'] = pd.to_datetime(df2['date'])
df2 = df2.sort_values('date').reset_index(drop=True)
df2['amount'] = df2['volume'] * df2['close']

base_cfg = query_cl_chart_config("a", "000001") or {}
cd = CD(symbol, "day", config=base_cfg)
cd.process_klines(df2)

bis = cd.get_bis()
total = len(bis)
print(f"CL2处理后: {total}个BI")

# ── CZSC 原始方向 ──
if cd._czsc:
    raw = cd._czsc.bi_list
    print(f"\nCZSC原始: {len(raw)}笔")
    print("原始最后10笔方向（正确判断）:")
    for i in range(len(raw)-10, len(raw)):
        c = raw[i]
        dir_str = "up" if c.direction == _Direction.Up else "down"
        print(f"  CZSC#{i} {dir_str} {c.fx_a.elements[1].dt}~{c.fx_b.elements[1].dt} "
              f"| {c.fx_a.fx:.2f}->{c.fx_b.fx:.2f}")
    
    # 正确的同向检查
    same = 0
    for i in range(1, len(raw)):
        d1 = "up" if raw[i-1].direction == _Direction.Up else "down"
        d2 = "up" if raw[i].direction == _Direction.Up else "down"
        if d1 == d2:
            same += 1
    print(f"\nCZSC原始同向数: {same}/{len(raw)-1}")

# ── CL2最后几笔 ──
print("\nCL2最后8笔:")
for i in range(max(0,total-8), total):
    b = bis[i]
    span = abs(b.end.k.index - b.start.k.index) + 1
    print(f"  BI#{i+1}(idx={b.index}) | {b.type:>4s} | "
          f"{str(b.start.k.date)[:10]}~{str(b.end.k.date)[:10]} | "
          f"{b.start.val:.2f}->{b.end.val:.2f} | span={span}K")

# ── 定位最后一笔内部(在CZSC中)包含的笔 ──
if cd._czsc and total >= 1:
    last_bi = bis[-1]  # cl2最后一笔
    last_start_idx = last_bi.start.k.index
    last_end_idx = last_bi.end.k.index
    print(f"\nCL2最后一笔(BY#{total}): span=CLKline[{last_start_idx}~{last_end_idx}]")
    print(f"  {str(last_bi.start.k.date)[:10]}~{str(last_bi.end.k.date)[:10]}")
    print(f"  区间内CZSC笔:")
    count = 0
    for i, c in enumerate(cd._czsc.bi_list):
        a_mid = c.fx_a.elements[1]
        b_mid = c.fx_b.elements[1]
        # 检查是否在最后一笔区间内
        if a_mid.id >= last_start_idx and b_mid.id <= last_end_idx:
            dir_str = "up" if c.direction == _Direction.Up else "down"
            print(f"    CZSC#{i} {dir_str} {a_mid.dt}~{b_mid.dt} | {c.fx_a.fx:.2f}->{c.fx_b.fx:.2f}")
            count += 1
    print(f"  共{count}笔被吞没")

print("\n" + "="*60)

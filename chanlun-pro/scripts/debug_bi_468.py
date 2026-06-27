"""诊断 BI#467 和 BI#468 的方向问题和 BI#468 区间内未画笔问题"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['STOCK_DATA_PATH'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

from src.chanlun.cl2 import CD
from src.chanlun.cl_utils import query_cl_chart_config
import akshare as ak
import pandas as pd
from datetime import datetime

symbol = "SH.000001"
freq = "day"

# ── 1. 获取日线数据 ──
print("=" * 80)
print(f"获取 {symbol} 日线数据...")
df = ak.stock_zh_index_daily(symbol="sh000001")
if df is None or df.empty:
    print("ERROR: 无法获取数据")
    sys.exit(1)

print(f"数据量: {len(df)} 条, 日期范围: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

# 准备DataFrame（和process_klines兼容）
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# ── 2. 运行 CD 引擎（和真实后端一样） ──
print("\n" + "=" * 80)
print("运行 CD 引擎...")
base_cfg = query_cl_chart_config("a", "000001") or {}
cd = CD(symbol, freq, config=base_cfg)
cd.process_klines(df)

# ── 3. 查看BI ──
bis = cd.get_bis()
print(f"\n总BI数: {len(bis)}")

print("\n" + "=" * 80)
print("最后 15 个 BI 详情:")
print("=" * 80)

total = len(bis)
start = max(0, total - 17)
for i in range(start, total):
    b = bis[i]
    bi_num = i + 1
    start_date = str(b.start.k.date)[:10]
    end_date = str(b.end.k.date)[:10]
    start_val = round(b.start.val, 2) if b.start.val else 0
    end_val = round(b.end.val, 2) if b.end.val else 0
    span_klines = abs(b.end.k.index - b.start.k.index) + 1
    print(f"  BI#{bi_num:>4d} | {b.type:>4s} | {start_date} ~ {end_date} "
          f"| {start_val:>8.2f} -> {end_val:>8.2f} "
          f"| high={round(b.high,2):>8.2f} low={round(b.low,2):>8.2f} "
          f"| span={span_klines}K")

# ── 5. 检查最后2笔合并 ──
print("\n" + "=" * 80)
print("最后2笔合并逻辑检查:")
print("=" * 80)
raw_bars_count = len(cd._czsc.bi_list) if cd._czsc else 0
print(f"CZSC 原始BI数: {raw_bars_count}")
print(f"处理后BI数: {len(bis)}")

# 如果超过2笔差异，说明有合并
if len(bis) < raw_bars_count:
    print(f"差异: {raw_bars_count - len(bis)} 笔被合并/删除")

# ── 6. 检查CZSC原始BI输出（跳过merge） ──
print("\n" + "=" * 80)
print("CZSC 原始 BI 输出:")
print("=" * 80)
if cd._czsc:
    from czsc.core import CZSC as _CZSC
    raw_bis = cd._czsc.bi_list
    print(f"原始 CZSC 产出 {len(raw_bis)} 笔")
    raw_total = len(raw_bis)
    for i in range(max(0, raw_total - 17), raw_total):
        c_bi = raw_bis[i]
        fx_a_dt = c_bi.fx_a.elements[1].dt
        fx_b_dt = c_bi.fx_b.elements[1].dt
        dir_str = "up" if c_bi.direction == 1 else "down"
        print(f"  CZSC_BI#{i:>4d} | {dir_str:>4s} | {fx_a_dt} ~ {fx_b_dt} "
              f"| high={c_bi.high:.2f} low={c_bi.low:.2f}")

    # 检查CZSC原始是否交替
    czsc_same = []
    for i in range(1, len(raw_bis)):
        d1 = "up" if raw_bis[i-1].direction == 1 else "down"
        d2 = "up" if raw_bis[i].direction == 1 else "down"
        if d1 == d2:
            czsc_same.append((i, d1, d2))
    if czsc_same:
        print(f"\n警告: CZSC 原始有 {len(czsc_same)} 处同向!")
        for pos, d1, d2 in czsc_same:
            print(f"  ⚠ CZSC_BI#{pos-1}({d1}) 和 CZSC_BI#{pos}({d2}) 同向")
    else:
        print("  ✓ CZSC 原始 BI 全部交替")

    # 显示最后~17笔原始CZSC BI
    print(f"\nCZSC原始最后17笔:")
    raw_total = len(raw_bis)
    for i in range(max(0, raw_total - 17), raw_total):
        c_bi = raw_bis[i]
        dir_str = "up" if c_bi.direction == 1 else "down"
        print(f"  CZSC_BI#{i:>4d} | {dir_str:>4s}")

print("\n" + "=" * 80)
print("诊断完成")

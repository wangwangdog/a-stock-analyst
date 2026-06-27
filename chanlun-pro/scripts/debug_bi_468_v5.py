"""追踪CL2最后一笔区间的BI处理过程"""
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

# 手动跟踪：先跑CZSC，看_bis创建了什么
cd._run_czsc_bars([...])  # 不能这样，需要先有raw_bars

# 改策略：直接跑完整流程，但打印中间状态
# 复制process_klines的逻辑，在中间插入打印

from czsc.core import RawBar, Freq

def _to_dt(val):
    from datetime import datetime
    if isinstance(val, datetime): return val
    if hasattr(val, 'strftime'): return datetime.combine(val, datetime.min.time())
    return datetime.strptime(str(val)[:10], '%Y-%m-%d')

raw_bars = []
for i, (_, row) in enumerate(df2.iterrows()):
    dt = _to_dt(row['date'])
    raw_bars.append(RawBar(symbol=symbol, id=i, dt=dt, freq=Freq.D,
        open=float(row['open']), close=float(row['close']),
        high=float(row['high']), low=float(row['low']),
        vol=float(row.get('volume', 0)),
        amount=float(row.get('amount', row.get('volume', 0) * row.get('close', 0)))))

print(f"RawBars: {len(raw_bars)}")

# 直接调用_run_czsc_bars获取初始BIs
cd._run_czsc_bars(raw_bars)

print(f"\nCL2初始BIs (CZSC转换后): {len(cd._bis)}")
# 找到最后区间的BIs (index > 670)
for b in cd._bis:
    if b.index > 670:
        print(f"  BI(idx={b.index}) | {b.type:>4s} | "
              f"{str(b.start.k.date)[:10]}~{str(b.end.k.date)[:10]} | "
              f"start={b.start.k.index} end={b.end.k.index}")

# 看看CZSC原始的对应信息
if cd._czsc:
    raw = cd._czsc.bi_list
    print(f"\nCZSC最后15笔:")
    for i in range(len(raw)-15, len(raw)):
        c = raw[i]
        dir_str = "up" if c.direction == _Direction.Up else "down"
        a_mid = c.fx_a.elements[1]
        b_mid = c.fx_b.elements[1]
        print(f"  CZSC#{i} {dir_str} | a_mid={a_mid.id} b_mid={b_mid.id} | "
              f"{a_mid.dt}~{b_mid.dt} | {c.fx_a.fx:.2f}->{c.fx_b.fx:.2f}")

# 现在手动运行_validate_and_correct的关键步骤，追踪
print("\n\n手动追踪_validate_and_correct:")
bis_before = list(cd._bis)
print(f"  进入时BI数: {len(bis_before)}")

# step 1: 交替性检查
print("\n  Step1 - 同向丢弃:")
valid = [bis_before[0]]
dropped = []
for b in bis_before[1:]:
    prev = valid[-1]
    if prev.type == b.type:
        dropped.append((b.index, b.type))
        continue
    valid.append(b)
print(f"    保留{len(valid)}, 丢弃{len(dropped)}")
for idx, typ in dropped[-10:]:
    print(f"      丢弃 BI(idx={idx}, {typ})")

# step 2: 不足5根K线检查
print("\n  Step2 - 不足5根K线检查:")
# 先给valid的BI分配CLKline索引
# 需要先构建cl_klines... 但这里已经跑过了
# 直接看cd._validate_and_correct的结果
print("  (实际跑cd._validate_and_correct)")

# 逆向: 看看哪些CZSC笔对应的CL2 BI被丢弃了
print("\n\n被丢弃的CZSC笔（在CL2中无对应BI）:")
if cd._czsc:
    cl2_bi_indices = set(b.index for b in cd._bis)
    for i, c in enumerate(cd._czsc.bi_list):
        # 检查CL2中是否有index=i的BI
        # 但CL2的index是从0递增的，和CZSC位置不一定一一对应
        pass
    
    # 直接检查CL2 index范围
    print(f"CL2 BI index范围: {cd._bis[0].index}~{cd._bis[-1].index}")
    print(f"CL2最后几笔的index: {[b.index for b in cd._bis[-10:]]}")

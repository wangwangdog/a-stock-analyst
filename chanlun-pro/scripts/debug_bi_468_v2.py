"""用真实数据库数据诊断BI#467/468问题"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['STOCK_DATA_PATH'] = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')

from src.chanlun.cl2 import CD
from src.chanlun.cl_utils import query_cl_chart_config
import pandas as pd
from datetime import datetime
import sqlite3

symbol = "SH.000001"
freq = "day"

# ── 1. 从chanlun_klines.sqlite获取数据（和真实后端一致） ──
home = os.path.expanduser("~")
db_path = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
print(f"数据库: {db_path}")

_sym = symbol.split('.')[-1] if '.' in symbol else symbol
conn = sqlite3.connect(db_path)
sql = """SELECT date, open, high, low, close, volume, turnover as amount
         FROM stock_daily WHERE symbol = ? ORDER BY date"""
rows = conn.execute(sql, (_sym,)).fetchall()
conn.close()

if not rows:
    print("数据库无数据")
    sys.exit(1)

print(f"数据量: {len(rows)} 条, 日期: {rows[0][0]} ~ {rows[-1][0]}")

df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)

# ── 2. 运行CD引擎 ──
print("\n运行CD引擎...")
base_cfg = query_cl_chart_config("a", "000001") or {}
cd = CD(symbol, freq, config=base_cfg)
cd.process_klines(df)

bis = cd.get_bis()
print(f"总BI数: {len(bis)}")

# ── 3. 显示最后20笔详情 ──
print("\n" + "=" * 90)
print("最后20个BI详情:")
print("=" * 90)
total = len(bis)
start = max(0, total - 22)
for i in range(start, total):
    b = bis[i]
    bi_num = i + 1
    start_date = str(b.start.k.date)[:10]
    end_date = str(b.end.k.date)[:10]
    start_val = round(b.start.val, 2) if b.start.val else 0
    end_val = round(b.end.val, 2) if b.end.val else 0
    span = abs(b.end.k.index - b.start.k.index) + 1
    print(f"  BI#{bi_num:>4d} | {b.type:>4s} | {start_date} ~ {end_date} "
          f"| {start_val:>8.2f}→{end_val:>8.2f} "
          f"| high={round(b.high,2):>8.2f} low={round(b.low,2):>8.2f} "
          f"| {span:>3d}K")

# ── 4. 检查CZSC原始输出 ──
print("\n" + "=" * 90)
print("CZSC原始BI最后20笔:")
print("=" * 90)
if cd._czsc:
    raw_bis = cd._czsc.bi_list
    raw_total = len(raw_bis)
    print(f"原始CZSC产出: {raw_total}笔")
    for i in range(max(0, raw_total - 22), raw_total):
        c_bi = raw_bis[i]
        dir_str = "up" if c_bi.direction == 1 else "down"
        fx_a_dt = c_bi.fx_a.elements[1].dt
        fx_b_dt = c_bi.fx_b.elements[1].dt
        fx_a_price = c_bi.fx_a.fx
        fx_b_price = c_bi.fx_b.fx
        print(f"  CZSC_BI#{i:>4d} | {dir_str:>4s} | {fx_a_dt}→{fx_b_dt} "
              f"| FX_A={fx_a_price:.2f} FX_B={fx_b_price:.2f} "
              f"| high={c_bi.high:.2f} low={c_bi.low:.2f}")

# ── 5. 检查 validate 中间结果 ──
print("\n" + "=" * 90)
print("最后2笔合并前/后对比:")
print("=" * 90)

# 在 _map_results 之后单独看merge的结果
# 检查 merge 前后的CZSC关系
if cd._czsc:
    raw_bis = cd._czsc.bi_list
    # 找到CZSC中最后几笔的方向
    directions = ["up" if b.direction == 1 else "down" for b in raw_bis[-10:]]
    print(f"CZSC最后10笔方向: {directions}")
    
    # CZSC原始最后几根K线数据
    print(f"\nCZSC最终bar: {len(cd._czsc.bars_raw)}条")
    last_bars = cd._czsc.bars_raw[-5:]
    for b in last_bars:
        print(f"  bar {b.id} | dt={b.dt} | o={b.open:.2f} h={b.high:.2f} l={b.low:.2f} c={b.close:.2f}")

# ── 6. 同向检查 ──
print("\n" + "=" * 90)
print("同向BI检查:")
print("=" * 90)
consecutive = []
for i in range(1, len(bis)):
    if bis[i-1].type == bis[i].type:
        consecutive.append((i, bis[i-1].type, bis[i].type))
        print(f"  ⚠ BI#{i}({bis[i-1].type}) 和 BI#{i+1}({bis[i].type}) 同向")

if not consecutive:
    print("  ✓ 全部交替, 无同向问题")
else:
    print(f"\n  共 {len(consecutive)} 处同向")

# ── 7. 检查最后2笔合并逻辑 ──
print("\n" + "=" * 90)
print("最后2笔合并逻辑验证:")
print("=" * 90)
print(f"处理后BI数量: {len(bis)}")
if cd._czsc:
    print(f"CZSC原始BI数量: {len(cd._czsc.bi_list)}")
    diff = len(cd._czsc.bi_list) - len(bis)
    print(f"差异({diff}): 包含_validate_and_correct删除 + merge合并")

print("\n" + "=" * 90)
print("诊断完成")

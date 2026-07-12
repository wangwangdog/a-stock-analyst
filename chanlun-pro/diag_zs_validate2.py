#!/usr/bin/env python3
"""ZS 验证脚本 — 用数据量充足的股票"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
SYM = "000002"  # SZ.000002 has 5792 5m bars
MARKET = "sz"

def fetch_5m(symbol="000002"):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol=? AND period='5m' "
        "ORDER BY trade_date",
        (f"SZ.{symbol}",)
    ).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    return df.reset_index(drop=True)

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m(SYM)
print(f"K线数: {len(df)}")
print(f"日期范围: {df['date'].min()} ~ {df['date'].max()}")

cfg = query_cl_chart_config(MARKET, SYM) or {}
cfg.update({
    "zs_bi_count": 5, "zs_extend": 1,
    "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0
})

cd = CD(f"SZ.{SYM}", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)
print(f"\n笔: {len(bis)}, 中枢: {len(zss)}")

def bi_top(b):
    return b.end.val if b.type == "up" else b.start.val

def bi_bottom(b):
    return b.end.val if b.type == "down" else b.start.val

def get_zgzd(zs):
    m = zs.lines[1:-1]
    if not m:
        return zs.zg, zs.zd
    return min(bi_top(b) for b in m), max(bi_bottom(b) for b in m)

# ─── 全体有效性检查 ───
print("\n" + "=" * 70)
print("全体中枢有效性检查")
print("=" * 70)

invalid_list = []
for idx, zs in enumerate(zss):
    m = zs.lines[1:-1]
    zg, zd = get_zgzd(zs)
    issues = []
    if zd > zg:
        issues.append(f"中间笔不重叠 ZD>{zg}")
    if m and abs(zs.zg - zg) > 0.001:
        issues.append(f"zs.zg≠计算ZG({zs.zg:.4f}≠{zg:.4f})")
    if m and abs(zs.zd - zd) > 0.001:
        issues.append(f"zs.zd≠计算ZD({zs.zd:.4f}≠{zd:.4f})")
    enter_end = zs.lines[0].end.val
    if zd < enter_end < zg:
        issues.append(f"进入笔终点({enter_end:.2f})在中枢内")
    exit_b = zs.lines[-1]
    if zs.type == "up" and exit_b.high <= zg:
        issues.append(f"离开笔未突破ZG")
    elif zs.type == "down" and exit_b.low >= zd:
        issues.append(f"离开笔未突破ZD")
    
    status = "✅" if not issues else "❌"
    ext = getattr(zs, 'ext_zg', 0)
    print(f"  {status} ZS{idx+1} type={zs.type} lines={zs.line_num} "
          f"ZG={zg:.2f} ZD={zd:.2f} ext_zg={ext:.2f}")
    for iss in issues:
        print(f"       {iss}")
    if issues:
        invalid_list.append(idx)

# ❌中枢详细诊断
print(f"\n{'='*70}")
print(f"❌ 无效中枢详细诊断 ({len(invalid_list)}个)")
print("=" * 70)
for idx in invalid_list:
    zs = zss[idx]
    m = zs.lines[1:-1]
    zg, zd = get_zgzd(zs)
    ext_zg = getattr(zs, 'ext_zg', None)
    
    print(f"\nZS{idx+1} type={zs.type} lines={zs.line_num}")
    print(f"  zs.zg={zs.zg:.4f} zs.zd={zs.zd:.4f} (初始)  "
          f"ext_zg={ext_zg} (延伸)")
    print(f"  计算ZG={zg:.4f} 计算ZD={zd:.4f}")
    for li, b in enumerate(zs.lines):
        tag = "[进]" if li == 0 else "[离]" if li == len(zs.lines)-1 else f"[{li}]"
        print(f"  {tag} b[{b.index}] type={b.type} "
              f"high={b.high:.4f} low={b.low:.4f} "
              f"top={bi_top(b):.4f} bottom={bi_bottom(b):.4f} "
              f"end={b.end.val:.4f} start={b.start.val:.4f}")
    
    # 进出终点检查
    print(f"  进入笔终={zs.lines[0].end.val:.4f} "
          f"离开笔终={zs.lines[-1].end.val:.4f}")
    print(f"  ZG/ZD范围=[{zd:.4f},{zg:.4f}]")
    
    # 判断是否"起点终点的笔都不在中枢范围内"
    enter_out = zs.lines[0].end.val < zd or zs.lines[0].end.val > zg
    exit_out = zs.lines[-1].end.val < zd or zs.lines[-1].end.val > zg
    print(f"  进入笔在中枢外={enter_out} 离开笔在中枢外={exit_out}")


# ─── 合并分析 ───
print(f"\n{'='*70}")
print("合并分析")
print("=" * 70)
merge_count = 0
for k in range(len(zss) - 1):
    a, b = zss[k], zss[k+1]
    a_zg, a_zd = get_zgzd(a)
    b_zg, b_zd = get_zgzd(b)
    shared = bool({x.index for x in a.lines} & {x.index for x in b.lines})
    adj = (a.lines[-1].index + 1 == b.lines[0].index)
    if not (shared or adj):
        continue
    overlap = (a_zg > b_zd and a_zd < b_zg)
    if not overlap:
        continue
    
    _fe = a.lines[-1]
    _fd = "up" if a.lines[0].type == "up" else "down"
    _bg = getattr(a, 'ext_zg', a.zg)
    _bd = getattr(a, 'ext_zd', a.zd)
    
    if _fd == "up":
        broken_init = _fe.high > a_zg
        broken_ext = _fe.high > _bg
    else:
        broken_init = _fe.low < a_zd
        broken_ext = _fe.low < _bd
    
    should_merge = not broken_ext
    if should_merge:
        merge_count += 1
        print(f"\n  ⚠️ ZS{k+1}+ZS{k+2} 会合并 "
              f"(break_init={broken_init} break_ext={broken_ext})")
        print(f"    a: ZG={a_zg:.4f} ZD={a_zd:.4f} "
              f"ext={_bg:.4f}/{_bd:.4f}")
        print(f"    b: ZG={b_zg:.4f} ZD={b_zd:.4f}")
        print(f"    exit b[{_fe.index}] high={_fe.high:.4f}")

print(f"\n会合并的相邻中枢对: {merge_count}")

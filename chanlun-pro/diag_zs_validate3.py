#!/usr/bin/env python3
"""ZS 验证 — 用 SH.000001 日线"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
SYM = "000001"

def fetch_data(period="daily"):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol='SH.000001' AND period=? "
        "ORDER BY trade_date",
        (period,)
    ).fetchall()
    conn.close()
    print(f"Fetched {len(rows)} rows for period={period}")
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'], format='mixed')
    return df.reset_index(drop=True)

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

df = fetch_data("daily")
print(f"K线数: {len(df)}, 日期: {df['date'].min()} ~ {df['date'].max()}")

cfg = query_cl_chart_config("a", SYM) or {}
cfg.update({
    "zs_bi_count": 5, "zs_extend": 1,
    "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0
})

cd = CD("SH.000001", "daily", config=cfg)
cd.process_klines(df.iloc[:3000])  # 先用前3000条
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

# 全体检查
print("\n" + "=" * 70)
print("全体中枢有效性检查")
print("=" * 70)
invalid_list = []
for idx, zs in enumerate(zss):
    m = zs.lines[1:-1]
    zg, zd = get_zgzd(zs)
    issues = []
    if zd > zg:
        issues.append(f"ZD>{zg}")
    if m and abs(zs.zg - zg) > 0.001 and zs.zg is not None:
        pass  # 初始值可以不同于延伸值
    enter_end = zs.lines[0].end.val
    if zd < enter_end < zg:
        issues.append(f"进入笔终({enter_end:.0f})在中枢内")
    exit_b = zs.lines[-1]
    if zs.type == "up" and exit_b.high <= zg:
        issues.append(f"离开high({exit_b.high:.0f})未突破ZG({zg:.0f})")
    elif zs.type == "down" and exit_b.low >= zd:
        issues.append(f"离开low({exit_b.low:.0f})未突破ZD({zd:.0f})")
    
    ext = getattr(zs, 'ext_zg', None)
    status = "✅" if not issues else "❌"
    print(f"  {status} ZS{idx+1} {zs.type} {zs.line_num}笔 "
          f"ZG={zg:.0f} ZD={zd:.0f} "
          f"init_ZG={zs.zg:.0f} init_ZD={zs.zd:.0f} "
          f"ext_ZG={ext}")
    for iss in issues:
        print(f"       {iss}")
    if issues:
        invalid_list.append(idx)

# 合并分析
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
              f"(brk_init={broken_init} brk_ext={broken_ext})")
        print(f"    a_ZG={a_zg:.0f} a_ZD={a_zd:.0f} "
              f"ext={_bg:.0f}/{_bd:.0f} init_zg={a.zg:.0f}")
        print(f"    b_ZG={b_zg:.0f} b_ZD={b_zd:.0f}")
        print(f"    exit b[{_fe.index}] high={_fe.high:.0f}")
        
        # 如果ext判断和init判断不同，说明ext导致了问题
        if broken_init != broken_ext:
            print(f"    ⭐ 差异! init判断={'突破✅' if broken_init else '未突破❌'} "
                  f"ext判断={'突破✅' if broken_ext else '未突破❌'}")
            
            # 展示合并后的结果
            merged_zg = min(a_zg, b_zg)
            merged_zd = max(a_zd, b_zd)
            print(f"    合并后 ZG={merged_zg:.0f} ZD={merged_zd:.0f}")
            
            # 合并后的离开笔突破检查
            merged_exit = b.lines[-1]
            if b.type == "up":
                merged_brk = merged_exit.high > merged_zg
            else:
                merged_brk = merged_exit.low < merged_zd
            print(f"    合并后离开笔 b[{merged_exit.index}] "
                  f"high={merged_exit.high:.0f} → {'突破✅' if merged_brk else '未突破❌'}")

print(f"\n会合并的相邻中枢对: {merge_count}/{len(zss)-1}")

#!/usr/bin/env python3
"""ZS23 验证 + 全体 ZS 有效性检查 + 合并分析"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
from pathlib import Path

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

def fetch_5m():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol='SH.000001' AND period='5m' "
        "ORDER BY trade_date DESC LIMIT 8000"
    ).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m()
print(f"K线数: {len(df)}")
print(f"日期范围: {df['date'].min()} ~ {df['date'].max()}")

cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({
    "zs_bi_count": 5, "zs_extend": 1,
    "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0
})

cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)
print(f"\n笔: {len(bis)}, 中枢: {len(zss)}")

# ─── 辅助方法 ───
def bi_top(b):
    return b.end.val if b.type == "up" else b.start.val

def bi_bottom(b):
    return b.end.val if b.type == "down" else b.start.val

def zs_check(zs, idx):
    """返回 (valid, issues)"""
    issues = []
    m = zs.lines[1:-1]
    if not m:
        return False, ["无中间笔"]
    zg = min(bi_top(b) for b in m)
    zd = max(bi_bottom(b) for b in m)

    # 1. 中间笔重叠
    if zd > zg:
        issues.append(f"❗中间笔不重叠: ZD={zd:.4f} > ZG={zg:.4f}")

    # 2. ZS属性一致性
    if abs(zs.zg - zg) > 0.001:
        issues.append(f"❗ZS.zg({zs.zg:.4f})≠计算ZG({zg:.4f})")
    if abs(zs.zd - zd) > 0.001:
        issues.append(f"❗ZS.zd({zs.zd:.4f})≠计算ZD({zd:.4f})")

    # 3. 进入笔终点在中枢范围外
    enter_end = zs.lines[0].end.val
    if zd < enter_end < zg:
        issues.append(f"❗进入笔终点({enter_end:.4f})在中枢[{zd:.4f},{zg:.4f}]内")

    # 4. 离开笔应突破
    exit_pen = zs.lines[-1]
    if zs.type == "up":
        if exit_pen.high <= zg:
            issues.append(f"❗UP离开笔high({exit_pen.high:.4f})未突破ZG({zg:.4f})")
    else:
        if exit_pen.low >= zd:
            issues.append(f"❗DOWN离开笔low({exit_pen.low:.4f})未突破ZD({zd:.4f})")

    return len(issues) == 0, issues


def get_zgzd(zs):
    """从ZS的中间笔计算ZG/ZD"""
    m = zs.lines[1:-1]
    if not m:
        return zs.zg, zs.zd
    return min(bi_top(b) for b in m), max(bi_bottom(b) for b in m)


# ─── 全体有效性检查 ───
print("\n" + "=" * 70)
print("全体中枢有效性检查")
print("=" * 70)

for idx, zs in enumerate(zss):
    valid, issues = zs_check(zs, idx)
    zg, zd = get_zgzd(zs)
    status = "✅" if valid else "❌"
    print(f"\n{status} ZS{idx+1} ({idx}) type={zs.type} "
          f"lines={zs.line_num} "
          f"ZG={zg:.2f} ZD={zd:.2f} "
          f"ext_zg={getattr(zs,'ext_zg',0):.2f}")
    if not valid:
        for iss in issues:
            print(f"   {iss}")

# ─── ZS23 详细诊断 ───
print("\n" + "=" * 70)
print("ZS23 详细诊断")
print("=" * 70)

for idx, zs in enumerate(zss):
    if idx + 1 != 23:
        continue

    m = zs.lines[1:-1]
    zg = min(bi_top(b) for b in m) if m else 0
    zd = max(bi_bottom(b) for b in m) if m else 0
    ext_zg = getattr(zs, 'ext_zg', None)
    ext_zd = getattr(zs, 'ext_zd', None)

    print(f"\nZS23: type={zs.type} lines={zs.line_num}")
    print(f"  zs.zg={zs.zg:.4f} zs.zd={zs.zd:.4f} (初始/显示)")
    print(f"  计算ZG={zg:.4f} 计算ZD={zd:.4f}")
    print(f"  zs.gg={zs.gg:.4f} zs.dd={zs.dd:.4f}")
    if ext_zg is not None:
        print(f"  ext_zg={ext_zg:.4f} ext_zd={ext_zd:.4f} (延伸后范围)")

    print(f"\n  所有笔 ({len(zs.lines)}笔):")
    for li, b in enumerate(zs.lines):
        tag = "[进]" if li == 0 else "[离]" if li == len(zs.lines)-1 else f"[中{li}]"
        print(f"    {tag} b[{b.index}] type={b.type} "
              f"high={b.high:.4f} low={b.low:.4f} "
              f"top={bi_top(b):.4f} bottom={bi_bottom(b):.4f} "
              f"end={b.end.val:.4f} start={b.start.val:.4f}")

    print(f"\n  中间笔与 ZG/ZD 关系 (ZG={zg:.4f} ZD={zd:.4f}):")
    for li, b in enumerate(m):
        in_range = "∈" if (bi_bottom(b) <= zg and bi_top(b) >= zd) else "∉"
        print(f"    m[{li}] b[{b.index}] range=[{bi_bottom(b):.4f},{bi_top(b):.4f}] "
              f"top={bi_top(b):.4f} bottom={bi_bottom(b):.4f} {in_range}ZS")

    # 进出笔端点检查
    enter_b = zs.lines[0]
    exit_b = zs.lines[-1]
    enter_ok = enter_b.end.val < zd or enter_b.end.val > zg
    exit_ok = exit_b.end.val < zd or exit_b.end.val > zg
    print(f"\n  进入笔终点={enter_b.end.val:.4f} → {'在中枢外✅' if enter_ok else '在中枢内❌'}")
    print(f"  离开笔终点={exit_b.end.val:.4f} → {'在中枢外✅' if exit_ok else '在中枢内❌'}")

    # 离开笔突破检查
    if zs.type == "up":
        brk_init = exit_b.high > zs.zg
        brk_ext = exit_b.high > ext_zg if ext_zg is not None else brk_init
        brk_calc = exit_b.high > zg
        print(f"\n  离开笔突破 (UP): high={exit_b.high:.4f}")
        print(f"    初始ZG={zs.zg:.4f} → {'突破✅' if brk_init else '未突破❌'}")
        if ext_zg is not None:
            print(f"    延伸ZG={ext_zg:.4f} → {'突破✅' if brk_ext else '未突破❌'}")
        print(f"    计算ZG={zg:.4f} → {'突破✅' if brk_calc else '未突破❌'}")
    else:
        brk_init = exit_b.low < zs.zd
        brk_ext = exit_b.low < ext_zd if ext_zd is not None else brk_init
        brk_calc = exit_b.low < zd
        print(f"\n  离开笔突破 (DOWN): low={exit_b.low:.4f}")
        print(f"    初始ZD={zs.zd:.4f} → {'突破✅' if brk_init else '未突破❌'}")
        if ext_zd is not None:
            print(f"    延伸ZD={ext_zd:.4f} → {'突破✅' if brk_ext else '未突破❌'}")
        print(f"    计算ZD={zd:.4f} → {'突破✅' if brk_calc else '未突破❌'}")

    # 检查整个中枢的所有笔是否都覆盖 ZG/ZD 区间
    print(f"\n  所有笔端点覆盖检查:")
    all_endpoints = [(b.index, b.end.val) for b in zs.lines]
    max_end = max(v for _, v in all_endpoints)
    min_end = min(v for _, v in all_endpoints)
    print(f"    端点范围: [{min_end:.4f}, {max_end:.4f}]")
    print(f"    ZG/ZD范围: [{zd:.4f}, {zg:.4f}]")
    if min_end > zg or max_end < zd:
        print(f"    ❌ 所有笔端点都在中枢范围之外！这不可能")
    if enter_b.end.val > zg and exit_b.end.val > zg and zs.type == "up":
        # Both ends above ZG - is this a valid uptrend center?
        print(f"    ⚠️ 进入和离开终点都在ZG之上")

# ─── 合并分析 ───
print("\n" + "=" * 70)
print("合并分析: 相邻中枢 ZG/ZD 重叠 + 出口笔突破检查")
print("=" * 70)

for k in range(len(zss) - 1):
    a, b = zss[k], zss[k+1]
    a_zg, a_zd = get_zgzd(a)
    b_zg, b_zd = get_zgzd(b)

    a_set = {x.index for x in a.lines}
    b_set = {x.index for x in b.lines}
    shared = bool(a_set & b_set)
    adj = (a.lines[-1].index + 1 == b.lines[0].index)
    cond = shared or adj
    overlap = (a_zg > b_zd and a_zd < b_zg)

    if not cond or not overlap:
        continue

    _fe = a.lines[-1]
    _fd = "up" if a.lines[0].type == "up" else "down"
    _bg = getattr(a, 'ext_zg', a.zg)
    _bd = getattr(a, 'ext_zd', a.zd)

    if _fd == "up":
        broken_init = _fe.high > a_zg
        broken_ext  = _fe.high > _bg
    else:
        broken_init = _fe.low < a_zd
        broken_ext  = _fe.low < _bd

    should_merge = not broken_ext

    token = "⚠️ 合并" if should_merge else "→"
    print(f"\n  {token} ZS{k+1}→ZS{k+2}: "
          f"shared={shared} adj={adj} overlap={overlap}")
    print(f"    a.ZG={a_zg:.4f} a.ZD={a_zd:.4f}  "
          f"ext_zg={_bg:.4f} ext_zd={_bd:.4f}")
    print(f"    b.ZG={b_zg:.4f} b.ZD={b_zd:.4f}")
    print(f"    exit b[{_fe.index}] high={_fe.high:.4f} "
          f"brk(init)={broken_init} brk(ext)={broken_ext}")
    if should_merge:
        print(f"    → 离开笔未突破ext→会合并")

# ─── 统计 ───
print("\n" + "=" * 70)
print("统计")
print("=" * 70)
invalid_count = 0
for idx, zs in enumerate(zss):
    valid, issues = zs_check(zs, idx)
    if not valid:
        invalid_count += 1
        print(f"  ZS{idx+1}: {'; '.join(issues)}")
print(f"\n无效中枢: {invalid_count}/{len(zss)}")

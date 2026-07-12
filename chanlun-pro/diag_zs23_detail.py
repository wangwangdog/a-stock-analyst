#!/usr/bin/env python3
"""ZS23 深度诊断"""

import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"

from chanlun.cl2 import CD, _build_zss_from_bis
from chanlun.cl_utils import query_cl_chart_config

def fetch_all():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT trade_date as date, open, high, low, close, volume, amount "
        "FROM kline_cache WHERE symbol='SH.000001' AND period='daily' ORDER BY trade_date"
    ).fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    return df

df = fetch_all()
cfg = query_cl_chart_config("a", "000001") or {}
cfg.update({"zs_bi_count": 5, "zs_extend": 1, "zs_allow_cross": 1, "zs_allow_bi_fx_check": 0})

cd = CD("SH.000001", "daily", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()
zss = _build_zss_from_bis(bis, config=cfg)

def bi_top(b): return b.end.val if b.type == "up" else b.start.val
def bi_bottom(b): return b.end.val if b.type == "down" else b.start.val

# 查找 ZS23
for idx, zs in enumerate(zss):
    if idx + 1 != 23:
        continue
    
    m = zs.lines[1:-1]  # 中间笔
    zg = min(bi_top(b) for b in m) if m else zs.zg
    zd = max(bi_bottom(b) for b in m) if m else zs.zd
    
    print(f"=== ZS23 基础信息 ===")
    print(f"  类型: {zs.type}")
    print(f"  笔数: {zs.line_num}")
    print(f"  初始ZG/ZD: {zs.zg:.2f} / {zs.zd:.2f}")
    print(f"  中间笔计算ZG/ZD: {zg:.2f} / {zd:.2f}")
    print(f"  中枢区间: [{zd:.2f}, {zg:.2f}]")
    
    print(f"\n=== 进入笔 ===")
    enter = zs.lines[0]
    print(f"  b[{enter.index}] type={enter.type}")
    print(f"  start={enter.start.val:.2f} end={enter.end.val:.2f}")
    print(f"  起点在区间外? {enter.start.val < zd or enter.start.val > zg}")
    print(f"  终点在区间外? {enter.end.val < zd or enter.end.val > zg}")
    
    print(f"\n=== 离开笔 ===")
    exit = zs.lines[-1]
    print(f"  b[{exit.index}] type={exit.type}")
    print(f"  start={exit.start.val:.2f} end={exit.end.val:.2f}")
    print(f"  high={exit.high:.2f} low={exit.low:.2f}")
    print(f"  起点在区间外? {exit.start.val < zd or exit.start.val > zg}")
    print(f"  终点在区间外? {exit.end.val < zd or exit.end.val > zg}")
    
    print(f"\n=== 中枢内部笔（中间笔）===")
    print(f"  ZG/ZD区间=[{zd:.2f}, {zg:.2f}]")
    both_outside = []
    inside = []
    for li, b in enumerate(m):
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        tag = ""
        if s_out and e_out:
            tag = " ← ★ 起点和终点都在区间外"
            both_outside.append((li, b))
        elif s_out or e_out:
            inside.append(f"  m[{li}] b[{b.index}] {b.type}: 部分在区间外")
        print(f"  m[{li}] b[{b.index}] type={b.type} "
              f"start={b.start.val:.2f}({'外' if s_out else '内'}) "
              f"end={b.end.val:.2f}({'外' if e_out else '内'})"
              f"{tag}")
    
    if both_outside:
        print(f"\n=== 起点和终点都在中枢区间之外的中间笔 ===")
        for li, b in both_outside:
            print(f"  m[{li}] b[{b.index}] type={b.type} "
                  f"range=[{b.start.val:.2f},{b.end.val:.2f}] "
                  f"区间=[{zd:.2f},{zg:.2f}]")
            print(f"    笔的high={b.high:.2f} low={b.low:.2f}")
            # 为什么这支笔属于这个中枢
            # 检查笔的高点和低点是否与中枢区间有重叠
            overlap = (b.high >= zd and b.low <= zg)
            print(f"    笔range=[{b.low:.2f},{b.high:.2f}] "
                  f"与中枢[{zd:.2f},{zg:.2f}] {'有' if overlap else '无'}重叠")
    
    print(f"\n=== 中枢延续原因分析 ===")
    print(f"  根据缠论，中枢延续不是由笔的端点位置决定的，")
    print(f"  而是看后续笔是否与中枢区间存在重叠。")
    print(f"  中枢区间 = [{zd:.2f}, {zg:.2f}]")
    for li, b in enumerate(zs.lines):
        overlap = (b.high >= zd and b.low <= zg)
        s_out = b.start.val < zd or b.start.val > zg
        e_out = b.end.val < zd or b.end.val > zg
        tag = "[进]" if li == 0 else "[离]" if li == len(zs.lines)-1 else f"[{li}]"
        print(f"  {tag} b[{b.index}] {b.type}: "
              f"range=[{b.low:.2f},{b.high:.2f}] "
              f"{'有' if overlap else '无'}重叠, "
              f"起点{'外' if s_out else '内'} 终点{'外' if e_out else '内'}")
    
    # 关键问题：笔端点在外，但笔的区间与中枢重叠 → 仍算中枢延续
    print(f"\n=== 结论 ===")
    print(f"  中枢延续的核心条件：笔的high-low区间与中枢[ZD,ZG]有重叠")
    print(f"  即使笔的起点和终点都在区间之外，只要笔身（高-低范围）")
    print(f"  穿过了中枢区间，就属于中枢的组成部分。")
    print(f"  这叫做'笔身重叠'原则，而非'端点重叠'原则。")

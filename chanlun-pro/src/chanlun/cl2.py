# -*- coding: utf-8 -*-
"""
cl1.py — CZSC (waditu/czsc) 驱动的缠论分析器
========================================================
使用 CZSC Rust 原生引擎进行包含处理、分型识别、笔识别与中枢构建，
同时保留 chanlun-pro ICL 数据接口不动。

依赖: czsc >= 1.0.0  (底层 rs_czsc Rust 扩展)
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple, Union
import datetime as dt_module
import numpy as np
import pandas as pd

# ── CZSC 核心类型 ──
from czsc.core import CZSC as _CZSC
from czsc.core import RawBar, NewBar, Freq, Direction as _Direction
from rs_czsc import Mark as _Mark

# ── chanlun-pro 接口 ──
from chanlun.cl_interface import (
    ICL, Kline as CL_Kline, CLKline, FX, BI, XD, ZS, MMD, BC,
    LINE, Config, compare_ld_beichi,
)


# ═══════════════════════════════════════════════════════════════════════
# 中枢构建开关变量
# ═══════════════════════════════════════════════════════════════════════
SHOW_BIS_OVERLAP_CHECK = 1        # 1: 连续三笔重叠检查
SHOW_BIS_FALLBACK = 1             # 1: 进入笔起点检查（不能在中枢内）
SHOW_BIS_EXTEND_BREAK = 1         # 1: 延伸前突破确认
SHOW_BIS_EXTEND = 1               # 1: 延伸扩展
SHOW_BIS_FINAL_RECALC = 1         # 1: 最终 ZG/ZD/GG/DD 重算
SHOW_BIS_MERGE = 1                # 1: 中枢合并
SHOW_5_7_9_OPTIMIZE = 1           # 1: 5/7/9突破笔选离开笔时按起点是否站稳选择
SHOW_LAST_BI_MERGE = 0            # 1: 最后2笔合并（吞掉最后一笔，默认关闭）

SHOW_HL_DIR_CHECK = 0             # 1: 高级别方向约束候选形态
SHOW_HL_BOUNDARY_CHECK = 0        # 1: 高级别笔边界检查
SHOW_HL_PRICE_CHECK = 0           # 1: 价格重叠检查
SHOW_HL_FALLBACK = 0              # 1: 无重叠回退分型端点极值
SHOW_HL_EXTEND = 0                # 1: 延伸扩展


# ═══════════════════════════════════════════════════════════════════════
# 常量映射
# ═══════════════════════════════════════════════════════════════════════

_FREQ_MAP = {
    "F1": Freq.F1, "1m": Freq.F1, "1分钟": Freq.F1,
    "F5": Freq.F5, "5m": Freq.F5, "5分钟": Freq.F5,
    "F15": Freq.F15, "15m": Freq.F15, "15分钟": Freq.F15,
    "F30": Freq.F30, "30m": Freq.F30, "30分钟": Freq.F30,
    "F60": Freq.F60, "60m": Freq.F60, "60分钟": Freq.F60,
    "D": Freq.D, "day": Freq.D, "日线": Freq.D,
    "W": Freq.W, "week": Freq.W, "周线": Freq.W,
    "M": Freq.M, "month": Freq.M, "月线": Freq.M,
}


# ═══════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════

def _to_dt(val):
    """统一转换为 datetime"""
    if isinstance(val, dt_module.datetime):
        return val
    if isinstance(val, str):
        try:
            return dt_module.datetime.strptime(str(val)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return dt_module.datetime.strptime(str(val)[:10], "%Y-%m-%d")
    if isinstance(val, (int, float)):
        return dt_module.datetime.fromtimestamp(val / 1000 if val > 1e9 else val)
    return val


def _freq_str_to_czsc(freq: str) -> Freq:
    """将 chanlun-pro 频次字符串映射为 CZSC Freq 枚举"""
    f = _FREQ_MAP.get(freq)
    if f is None:
        for k, v in _FREQ_MAP.items():
            if k in freq or freq in k:
                return v
        return Freq.D
    return f


def _mark_to_type(mark: _Mark) -> str:
    """CZSC Mark → chanlun-pro 分型类型字符串"""
    return "ding" if mark == _Mark.G else "di"


def _type_to_mark(t: str) -> _Mark:
    return _Mark.G if t == "ding" else _Mark.D


def _direction_to_type(d: _Direction) -> str:
    return "up" if d == _Direction.Up else "down"


# ═══════════════════════════════════════════════════════════════════════
# 中枢构建（标准缠论算法）
# ═══════════════════════════════════════════════════════════════════════

def _bi_top(b):
    """笔的顶分型价格"""
    return b.end.val if b.type == "up" else b.start.val


def _bi_bottom(b):
    """笔的底分型价格"""
    return b.start.val if b.type == "up" else b.end.val


def _build_zss_from_bis(bis: List[BI], zs_type: str = "bi", config: dict = None) -> List[ZS]:
    # ═══════════════════════════════════════════════════════════════════════
    # 中枢构建 7 步骤流程 (开关状态: 1=启用, 0=关闭)
    # ═══════════════════════════════════════════════════════════════════════
    #
    # ┌─ 步骤1 ───────────────────────────────────────┐
    # │  连续3笔重叠? (SHOW_BIS_OVERLAP_CHECK=1)       │──NO──→ i++
    # │  3笔顶底分型 ZG > ZD?                          │
    # └───────────────────────┬────────────────────────┘
    #                        │ YES
    # ┌─ 步骤2 ──────────────▼────────────────────────┐
    # │  进入笔起点在中枢内? (SHOW_BIS_FALLBACK=1)      │──YES─→ i++
    # │  bis[i].start 在 [ZD, ZG] 区间内?              │
    # └───────────────────────┬────────────────────────┘
    #                        │ NO
    # ┌─ 步骤3 ──────────────▼────────────────────────┐
    # │  5笔模型: 进入+3中间+离开  (SHOW_BIS_EXTEND_BREAK=1)│
    # │  中间3笔重算 ZG/ZD                              │──NO──→ i++
    # │  中间笔重叠?                                    │
    # │  离开笔突破 ZG(up) / ZD(down)?                  │──NO──→ 步骤4 延伸
    # │  突破 ✓ → 跳步骤5                               │
    # └───────────────────────┬────────────────────────┘
    #                        │ YES
    # ┌─ 步骤4 ──────────────▼────────────────────────┐
    # │  while 延伸扩展 (SHOW_BIS_EXTEND=1)            │
    # │  后续笔与中枢重叠? → 加入 → 重算ZG/ZD → 检查出口│
    # │  不重叠? → break                               │
    # │  偶数笔修正: 去掉末尾不同向笔                    │
    # └───────────────────────┬────────────────────────┘
    #                        │
    # ┌─ 步骤4b ─────────────▼───────────────────────┐
    # │  最终ZG/ZD重算 (SHOW_BIS_FINAL_RECALC=1)      │
    # │  zd > zg? → i++ (扩展过度)                     │
    # └───────────────────────┬────────────────────────┘
    #                        │
    # ┌─ 步骤5 ──────────────▼────────────────────────┐
    # │  5/7/9候选突破笔优选 (SHOW_5_7_9_OPTIMIZE=1)   │
    # │  三笔都突破? + 优化开启?                        │──NO──→ 传统:选最高/低
    # │   YES → 7站稳(起点>ZG且末端>GG)? → 5笔完成     │
    # │         9站稳(起点>ZG且末端>GG)? → 7笔完成     │
    # │         都不稳 → 传统选最高/低                  │
    # │  0笔突破? → i++                                │
    # └───────────────────────┬────────────────────────┘
    #                        │ 找到离开笔
    # ┌─ 步骤6 ──────────────▼────────────────────────┐
    # │  创建 ZS 中枢对象                               │
    # │  start=进入笔终点, end=离开笔起点               │
    # │  ZG/ZD/GG/DD/_type/lines                       │
    # └───────────────────────┬────────────────────────┘
    #                        │
    # ┌─ 步骤7 ──────────────▼────────────────────────┐
    # │  中枢合并 (SHOW_BIS_MERGE=1)                   │
    # │  相邻中枢共用笔 + ZG/ZD重叠 → 合并              │
    # │  出口已突破 → 不合并                            │
    # └────────────────────────────────────────────────┘
    #
    # 关键修复 (2025-06-03):
    #   原 i=j 跳过太多笔 → 改为 i+=1，让每笔都有机会做進入笔
    #   修复位置: step3 中间笔不重叠 / step4b zd>zg / step5 0笔突破
    # 关键修改 (2025-06-XX):
    #   离开笔复用: i=j → i=j-1，允许离开笔作为下一个中枢的进入笔
    #
    # ZG/ZD = 中间笔顶分型/底分型价格 (非K线 high/low)
    # GG/DD = 中间笔 endpoint 极值
    # ═══════════════════════════════════════════════════════════════════════
    """
    从笔列表构建笔中枢列表

    标准缠论中枢定义：连续3笔有重叠区间则构成潜在中枢。
    采用5笔模型：进入笔 + 3笔中间笔 + 离开笔，中间3笔决定ZG/ZD。

    算法流程：
    ─────────────────────────────────────────────────────────────
    步骤1 ─ 连续三笔重叠检查 (SHOW_BIS_OVERLAP_CHECK)
      检查 bis[i]~bis[i+2] 的顶分型/底分型是否有重叠 (ZG>ZD)
      无重叠 → i++ 继续
      有重叠 → 进入步骤2

    步骤2 ─ 进入笔起点检查 (SHOW_BIS_FALLBACK)
      条件: 进入笔起点(zd ≤ start ≤ zg) 不能在中枢区间内
      若起点在中枢内 → 这组笔不构成有效中枢 → i++

    步骤3 ─ 5笔模型高度检查 + 突破确认 (SHOW_BIS_EXTEND_BREAK)
      5笔模型: bis[i]进入, bis[i+1~i+3]中间, bis[i+4]离开
      用中间3笔的顶/底分型重算 ZG/ZD
      中间3笔不重叠 → i++（不跳过，原i=j跳过太多笔）
      出口判断: up方向 exit_end ≥ ZG 即突破, down方向 exit_end ≤ ZD 即突破
      未突破 → 进入延伸(步骤4), 已突破 → 跳至候选笔优选(步骤5)

    步骤4 ─ 延伸扩展 (SHOW_BIS_EXTEND + config:zs_extend)
      while循环: 逐一检查后续笔是否与中枢重叠
      重叠 → 加入中枢线组 → 重算ZG/ZD/GG/DD → 检查新出口是否突破
      不重叠 → break
      偶数笔修正: 同向离开笔已突破后, 去掉末尾不同向笔
      早期3笔+延伸路径(兜底): 当SHOW_BIS_EXTEND_BREAK=0或不够5笔时
        也做类似的延伸检查和while扩展

    步骤4b ─ 最终ZG/ZD重算 (SHOW_BIS_FINAL_RECALC)
      用当前中枢线组所有中间笔重算 ZG/ZD/GG/DD
      若 zd > zg (伸展过度不重叠) → i++（不跳过，原i=j跳过中间笔）

    步骤5 ─ 第5/7/9同向笔候选突破笔优选 (SHOW_5_7_9_OPTIMIZE)
      从5/7/9笔(相对进入笔偏移4/6/8)中找突破ZG/ZD的同向笔
      逻辑 A — 三笔都突破 + 优化开启:
        7站稳(起点>ZG且末端>GG) → 5笔完成中枢
        9站稳(起点>ZG且末端>GG) → 7笔完成中枢
        都不稳 → 传统选最高突破笔 (up) / 最低突破笔 (down)
      逻辑 B — 未全突破或无优化:
        up方向选最高突破, down方向选最低突破
      0笔突破 → i++（不跳过，原i=j跳过中间笔）

    步骤6 ─ 创建中枢对象
      ZS(start=进入笔终点, end=离开笔起点, ZG/ZD/GG/DD/_type/lines)

    步骤7 ─ 中枢合并 (SHOW_BIS_MERGE)
      相邻中枢满足: 共用离开笔 或 相邻索引 + ZG/ZD重叠
      且出口笔未突破ZG/ZD → 合并为一个大中枢

    ─────────────────────────────────────────────────────────────
    参数:
        bis: BI列表（已校验的笔序列）
        zs_type: "bi"(默认) 或 "xd" 或 "zsd"
        config: 配置字典
            zs_extend=1   延伸策略开关
            zs_dir_from_b1=0  方向是否从第一笔决定

    ZG/ZD 使用笔的顶分型/底分型价格（不是 K 线内部最高/最低值）
    GG/DD 使用中间笔的 endpoint 极值
    """
    config = config or {}
    if len(bis) < 3:
        return []

    zss: List[ZS] = []
    zs_idx = 0

    i = 0
    while i < len(bis) - 2:
        # ── 步骤1：连续三笔重叠检查 ──
        # 用顶分型/底分型价格计算 ZG/ZD，检查 bis[i]~bis[i+2] 是否有重叠区间
        h1, l1 = _bi_top(bis[i]), _bi_bottom(bis[i])
        h2, l2 = _bi_top(bis[i + 1]), _bi_bottom(bis[i + 1])
        h3, l3 = _bi_top(bis[i + 2]), _bi_bottom(bis[i + 2])

        zg = min(h1, h2, h3)
        zd = max(l1, l2, l3)

        if zg > zd:
            # ── 步骤2：进入笔起点检查 ──
            # 进入笔起点不能在中枢内（必须在 ZG 之上或 ZD 之下）
            entry_start = bis[i].start.val
            if SHOW_BIS_FALLBACK and zd <= entry_start <= zg:
                i += 1
                continue

            # ── 中间笔重叠区确定 ZG/ZD ──
            zs_direction = "up" if bis[i].type == "up" else "down"

            # ── 步骤3：5笔模型 —— 前5笔能否构成中枢 ──
            #   5笔模型: bis[i]=进入笔, bis[i+1~i+3]=中间笔, bis[i+4]=离开笔
            if i + 4 >= len(bis):
                i += 1
                continue
            zs_lines = [bis[i], bis[i+1], bis[i+2], bis[i+3], bis[i+4]]
            j = i + 5
            middle_pens = zs_lines[1:-1]          # 3笔中间笔
            zg = min(_bi_top(b) for b in middle_pens)
            zd = max(_bi_bottom(b) for b in middle_pens)
            gg = max(b.end.val for b in middle_pens)
            dd = min(b.end.val for b in middle_pens)
            # 初始中间笔不重叠 → 不成立
            if zd > zg:
                i += 1
                continue
            # 进入笔起点不能在中枢内
            if zd <= bis[i].start.val <= zg:
                i += 1
                continue

            # ── 步骤4：第5笔必须突破中枢且与进入笔同向 ──
            zs_direction = "up" if bis[i].type == "up" else "down"
            exit_pen = zs_lines[-1]
            # 进入笔和离开笔必须同向
            if exit_pen.type != bis[i].type:
                i += 1
                continue
            entry_end = zs_lines[0].end.val
            if zs_direction == "up":
                _broken = exit_pen.high > zg and exit_pen.end.val > entry_end
            else:
                _broken = exit_pen.low < zd and exit_pen.end.val < entry_end
            if not _broken:
                i += 1
                continue  # 前5笔不能构成中枢

            # ── 前5笔可构成中枢！保存初始 ZG/ZD ──
            _init_zg, _init_zd = zg, zd

            # ── 步骤5：中枢延伸（笔身与初始区间有重叠则加入）──
            # 终止条件：笔两端完全在中枢同侧（完全在ZG上或完全在ZD下）
            while j < len(bis):
                _p = bis[j]
                _p_both_above = _p.start.val > _init_zg and _p.end.val > _init_zg
                _p_both_below = _p.start.val < _init_zd and _p.end.val < _init_zd
                if _p_both_above or _p_both_below:
                    break  # 独立一笔完全不在中枢区间 → 延伸结束
                bh, bl = _bi_top(_p), _bi_bottom(_p)
                if bh >= _init_zd and bl <= _init_zg:
                    zs_lines.append(_p)
                    j += 1
                else:
                    break

            # ── 延伸后检查：最后笔必须与进入笔同向且终点超越进入笔终点 ──
            entry_end_val = zs_lines[0].end.val
            while len(zs_lines) > 5:
                if zs_lines[-1].type != zs_lines[0].type:
                    zs_lines = zs_lines[:-1]
                    continue
                if zs_direction == "up" and zs_lines[-1].end.val <= entry_end_val:
                    zs_lines = zs_lines[:-1]
                    continue
                if zs_direction == "down" and zs_lines[-1].end.val >= entry_end_val:
                    zs_lines = zs_lines[:-1]
                    continue
                break

            # ── 步骤6：创建中枢对象 ──
            zs = ZS(
                zs_type=zs_type,
                start=zs_lines[0].end,
                end=zs_lines[-1].start,
                zg=_init_zg, zd=_init_zd, gg=gg, dd=dd,
                _type=zs_direction,
                index=zs_idx,
                line_num=len(zs_lines),
            )
            zs.lines = zs_lines
            zss.append(zs)
            zs_idx += 1
            i = j - 1
        else:
            i += 1

    # ── 中枢合并：相邻中枢共用离开笔+ZG/ZD重叠则合并 ──
    if SHOW_BIS_MERGE:
        merged = True
        while merged:
            merged = False
            new_zss = []
            skip_next = False
            for k in range(len(zss)):
                if skip_next:
                    skip_next = False
                    continue
                if k + 1 < len(zss):
                    a_set = {b.index for b in zss[k].lines}
                    b_set = {b.index for b in zss[k + 1].lines}
                    shared = a_set & b_set
                    a_last_idx = zss[k].lines[-1].index
                    b_first_idx = zss[k + 1].lines[0].index
                    adj = (a_last_idx + 1 == b_first_idx)
                    if (shared or adj) and (zss[k].zg > zss[k + 1].zd and zss[k].zd < zss[k + 1].zg):
                        a, b = zss[k], zss[k + 1]
                        # ── 出口笔极值突破检查：已突破则不合并 ──
                        _fe = a.lines[-1]
                        _fd = "up" if a.lines[0].type == "up" else "down"
                        if not ((_fd == "up" and _fe.high > a.zg) or (_fd == "down" and _fe.low < a.zd)):
                            # 去重合并 lines
                            seen = set()
                            merged_lines = [bi for bi in a.lines + b.lines if not (bi.index in seen or seen.add(bi.index))]
                            # 合并后保持奇数笔，确保进出同向
                            if len(merged_lines) % 2 == 0:
                                merged_lines = merged_lines[:-1]
                            if len(merged_lines) < 3:
                                new_zss.append(zss[k])
                                continue
                            zs = ZS(
                                zs_type=a.zs_type,
                                start=a.start,
                                end=b.end,
                                zg=min(a.zg, b.zg),
                                zd=max(a.zd, b.zd),
                                gg=max(a.gg, b.gg),
                                dd=min(a.dd, b.dd),
                                _type=a.type,
                                index=a.index,
                                line_num=len(merged_lines),
                            )
                            zs.lines = merged_lines
                            # 合并后检查离开笔是否突破中枢区间
                            exit_pen = merged_lines[-1]
                            merged_dir = "up" if merged_lines[0].type == "up" else "down"
                            if merged_dir == "up":
                                breaks = exit_pen.high > zs.zg
                            else:
                                breaks = exit_pen.low < zs.zd
                            if not breaks:
                                # 合并后离开笔未突破，不合并，保持原样
                                new_zss.append(zss[k])
                                merged = False
                                continue
                            new_zss.append(zs)
                            skip_next = True
                            merged = True
                            continue
                new_zss.append(zss[k])
            zss = new_zss
        for k, zs in enumerate(zss):
            zs.index = k
    # ── 完成态标记：除最后一个中枢外全部标记为已完成 ──
    for idx in range(len(zss) - 1):
        zss[idx].done = True
    return zss


def _get_bi_time(b, field: str = "start") -> str:
    """从 BI 对象或 dict 中提取规范化时间字符串"""
    if field == "start":
        if hasattr(b, 'start') and hasattr(b.start, 'k') and hasattr(b.start.k, 'date'):
            d = b.start.k.date
            return str(d) if hasattr(d, 'strftime') else str(d)[:19]
        if hasattr(b, '_start_time') and b._start_time:
            return str(b._start_time)
        if isinstance(b, dict):
            return str(b.get('start_time', ''))
    else:
        if hasattr(b, 'end') and hasattr(b.end, 'k') and hasattr(b.end.k, 'date'):
            d = b.end.k.date
            return str(d) if hasattr(d, 'strftime') else str(d)[:19]
        if hasattr(b, '_end_time') and b._end_time:
            return str(b._end_time)
        if isinstance(b, dict):
            return str(b.get('end_time', ''))
    return ''


def _check_zs_boundary(b1, b2, b3, higher_bis: list) -> tuple:
    """
    检查候选三笔是否落在高一级别笔的边界内。
    
    规则（放宽版）：
    - 候选笔的起始和结束只需各自落在某个高级别笔内（允许跨笔）
    - 不提供 higher_bis 时不约束
    
    Returns:
        (bool, obj): (是否通过边界检查, 归属的高级笔或None)
    """
    if not higher_bis:
        return True, None

    c_start = _get_bi_time(b1, "start")
    c_end = _get_bi_time(b3, "end")
    if not c_start or not c_end:
        return True, None

    # 放宽：起始和结束分别找归属的高级别笔
    start_in = False
    end_in = False
    matched_hb = None
    
    for hb in higher_bis:
        if isinstance(hb, dict):
            h_start = str(hb.get('start_time', ''))
            h_end = str(hb.get('end_time', ''))
        else:
            h_start = _get_bi_time(hb, "start")
            h_end = _get_bi_time(hb, "end")
        if not h_start or not h_end:
            continue
        if h_start <= c_start <= h_end:
            start_in = True
        if h_start <= c_end <= h_end:
            end_in = True
            matched_hb = hb
        if start_in and end_in:
            break

    # 严格模式：必须落在同一根高级别笔内（可选）
    # 当前放宽为：起止各自有归属即可
    if start_in or end_in:
        return True, matched_hb
    return False, None


def _build_zss_with_higher_level(bis: List[BI], higher_direction: str, zs_type: str = "bi",
                                 higher_bis: list = None, config: dict = None) -> List[ZS]:
    """
    根据高级别笔方向约束与边界归属规则构建中枢。

    步骤：
    1. 高级别方向约束候选形态 (SHOW_HL_DIR_CHECK=1)
    2. 高级别笔边界检查 (SHOW_HL_BOUNDARY_CHECK=1)
    3. 价格重叠检查 (SHOW_HL_PRICE_CHECK=1)
       - 3a. ZG/ZD 标准重叠 (1)
       - 3b. 无重叠回退分型端点极值 GG/DD (SHOW_HL_FALLBACK=1)
    4. 延伸扩展 (SHOW_HL_EXTEND=1, config:zs_extend)
    5. 创建 ZS 对象 (1)

    约束：
    - 高级别笔 up → 本级别候选三笔形态 下-上-下（回调中枢）
    - 高级别笔 down → 本级别候选三笔形态 上-下-上（反弹中枢）
    - 候选三笔不得跨越高级别笔边界（若提供 higher_bis）
    - 一个本级别中枢只能归属于一个高级别笔
    - 最先满足所有条件的为一组中枢，滑动窗口遍历

    参数（通过 config dict 控制）：
        zs_extend=1   延伸策略：0关闭，1打开
    """
    config = config or {}
    if not higher_direction or len(bis) < 3:
        return []

    zss: List[ZS] = []
    zs_idx = 0
    i = 0

    while i < len(bis) - 2:
        b1, b2, b3 = bis[i], bis[i + 1], bis[i + 2]
        t1, t2, t3 = b1.type, b2.type, b3.type

        if not all([t1, t2, t3]):
            i += 1
            continue

        # 1. 高级别方向约束候选形态
        if SHOW_HL_DIR_CHECK:
            if higher_direction == 'up':
                allowed = (t1 == 'down' and t2 == 'up' and t3 == 'down')
            else:
                allowed = (t1 == 'up' and t2 == 'down' and t3 == 'up')
            if not allowed:
                i += 1
                continue

        # 2. 高级别笔边界检查（不跨笔、不越界）
        if SHOW_HL_BOUNDARY_CHECK:
            ok_boundary, _ = _check_zs_boundary(b1, b2, b3, higher_bis)
            if not ok_boundary:
                i += 1
                continue

        # 3. 价格重叠检查
        h1, l1 = b1.high, b1.low
        h2, l2 = b2.high, b2.low
        h3, l3 = b3.high, b3.low

        zg = min(h1, h2, h3)
        zd = max(l1, l2, l3)

        if zg > zd:
            if SHOW_HL_FALLBACK:
                # ── 无重叠：ZG/ZD 保留原始重叠定义，GG/DD 用3分型端点极值 ──
                fractal_prices = [b1.end.val, b2.end.val, b3.end.val]
                gg = max(fractal_prices)
                dd = min(fractal_prices)
                zs_lines = [b1, b2, b3]
                j = i + 3
                while SHOW_HL_EXTEND and config.get('zs_extend', 1) and j < len(bis):
                    # 扩展笔也必须在高一级别边界内
                    if higher_bis:
                        ok_ext, _ = _check_zs_boundary(bis[j], bis[j], bis[j], higher_bis)
                        if not ok_ext:
                            break
                    bh, bl = bis[j].high, bis[j].low
                    if bh >= zd and bl <= zg:  # 与矩形有交集即可延伸
                        zs_lines.append(bis[j])
                        j += 1
                    else:
                        break

                zs_idx += 1
                zs_type_val = 'up' if higher_direction == 'down' else 'down'
                zs = ZS(
                    zs_type=zs_type,
                    start=zs_lines[0].end,
                    end=zs_lines[-1].start,
                    zg=zg, zd=zd, gg=gg, dd=dd,
                    _type=zs_type_val,
                    index=zs_idx,
                    line_num=len(zs_lines),
                )
                zs.lines = zs_lines
                zss.append(zs)
                i = j
            else:
                i += 1
        else:
            i += 1

    # ── 完成态标记：除最后一个中枢外全部标记为已完成 ──
    for idx in range(len(zss) - 1):
        zss[idx].done = True
    return zss


# ═══════════════════════════════════════════════════════════════════════
# 核心适配类
# ═══════════════════════════════════════════════════════════════════════

class CD(ICL):
    """
    缠论分析器 — CZSC 后端适配 chanlun-pro ICL 接口
    """

    def __init__(self, code: str, frequency: str, config: dict = None, start_datetime=None,
                 higher_level_direction: str = None,
                 higher_level_bis: list = None):
        self._code = code
        self._frequency = frequency
        self._config = config or {}
        self._start_datetime = start_datetime
        self._higher_level_direction = higher_level_direction
        self._higher_level_bis = higher_level_bis or None
        self._czsc_freq = _freq_str_to_czsc(frequency)

        self._src_klines: List[CL_Kline] = []
        self._cl_klines: List[CLKline] = []
        self._fxs: List[FX] = []
        self._bis: List[BI] = []
        self._xds: List[XD] = []
        self._bi_zss: List[ZS] = []
        self._idx: dict = {"macd": {"dif": [], "dea": [], "hist": []}}
        self._czsc: Optional[_CZSC] = None

    # ── 核心数据处理 ──

    def process_klines(self, klines: pd.DataFrame):
        """
        处理 K 线数据。DataFrame 必须包含: date, high, low, open, close [, volume]
        """
        if klines is None or len(klines) == 0:
            return self

        # 防御：如果从 pickle 恢复导致 _czsc_freq 丢失，重新初始化
        if not hasattr(self, '_czsc_freq'):
            self._czsc_freq = _freq_str_to_czsc(self._frequency)
        if not hasattr(self, '_czsc'):
            self._czsc = None

        # 0. 按日期排序（TDX数据可能乱序）
        klines = klines.sort_values("date").reset_index(drop=True)

        # 1. 转换为 CZSC RawBar
        raw_bars: List[RawBar] = []
        for i, (_, row) in enumerate(klines.iterrows()):
            dt = _to_dt(row["date"])
            raw_bars.append(RawBar(
                symbol=self._code,
                id=i,
                dt=dt,
                freq=self._czsc_freq,
                open=float(row["open"]),
                close=float(row["close"]),
                high=float(row["high"]),
                low=float(row["low"]),
                vol=float(row.get("volume", row.get("a", 0))),
                amount=float(row.get("amount", row.get("a", row.get("volume", 0)))),
            ))

        self._src_klines = [
            CL_Kline(index=i, date=b.dt, h=b.high, l=b.low, o=b.open, c=b.close, a=b.vol)
            for i, b in enumerate(raw_bars)
        ]

        # 2. 映射 + 校验 + 修正 + 重建（内部跑 CZSC）
        self._map_results(raw_bars)

        # 3. MACD
        if self._czsc is not None:
            self._calc_macd(raw_bars, self._czsc)
        else:
            self._calc_macd(raw_bars, None)

        return self

    # ── 结果映射 ──

    def _map_results(self, raw_bars: List[RawBar]):
        """
        入口：Function1 → Function2 递归 + 买卖点计算
        """
        self._run_czsc_bars(raw_bars)
        self._validate_and_correct(raw_bars)
        if self._higher_level_direction:
            self._bi_zss = _build_zss_with_higher_level(
                self._bis, self._higher_level_direction, higher_bis=self._higher_level_bis,
                config=self._config,
            )
        else:
            self._bi_zss = _build_zss_from_bis(self._bis, config=self._config)
        self._calc_mmds()

        # ── 最后2笔合并（开关控制，默认关闭）──
        # SHOW_LAST_BI_MERGE=1: 合并最后2笔（取b1方向，吞掉b2）
        # SHOW_LAST_BI_MERGE=0: 不合并，保留最后2笔原样
        if SHOW_LAST_BI_MERGE and len(self._bis) >= 2 and raw_bars:
            b1 = self._bis[-2]
            b2 = self._bis[-1]
            from chanlun.cl_interface import BI as _BI
            new_bi = _BI(start=b1.start, end=b2.end,
                         _type=b1.type, index=b1.index,
                         default_zs_type=self._config.get('zs_type_bz', 'bi'))
            si = min(b1.start.k.index, b2.end.k.index)
            ei = max(b1.start.k.index, b2.end.k.index)
            if si >= 0 and ei < len(self._cl_klines):
                seg = self._cl_klines[si:ei+1]
                new_bi.high = max(ck.h for ck in seg)
                new_bi.low  = min(ck.l for ck in seg)
            else:
                new_bi.high = max(b1.high, b2.high)
                new_bi.low  = min(b1.low, b2.low)
            new_bi.zs_high = max(new_bi.high, new_bi.low)
            new_bi.zs_low  = min(new_bi.high, new_bi.low)
            new_bi.end.val = b2.end.k.c  # 终点用CLKline收盘价
            self._bis = self._bis[:-2] + [new_bi]

    def _run_czsc_bars(self, raw_bars: List[RawBar]) -> bool:
        """
        Function 1: 接收 raw_bars，跑 CZSC，输出 BIs / FX / CLKlines。
        返回 True 表示成功产出 BIs，False 表示数据不足。
        """
        if len(raw_bars) < 10:
            return False

        # max_bi_num 根据K线数量动态计算，避免笔数配额不足无法覆盖全量数据
        max_bi = max(100, len(raw_bars) // 10)
        czsc_obj = _CZSC(raw_bars, max_bi_num=max_bi)
        self._czsc = czsc_obj

        # ── 收集 NewBars 构建 CLKlines ──
        nbs: Dict[int, NewBar] = {}
        for fx in czsc_obj.fx_list:
            for nb in fx.elements:
                nbs[nb.id] = nb
        for bi in czsc_obj.bi_list:
            for nb in bi.bars:
                nbs[nb.id] = nb
            for fx in bi.fxs:
                for nb in fx.elements:
                    nbs[nb.id] = nb
            nbs[bi.fx_a.elements[1].id] = bi.fx_a.elements[1]
            nbs[bi.fx_b.elements[1].id] = bi.fx_b.elements[1]

        sorted_nbs = sorted(nbs.values(), key=lambda x: x.id)
        nb_id_to_clk_idx = {nb.id: i for i, nb in enumerate(sorted_nbs)}

        self._cl_klines = []
        for nb in sorted_nbs:
            subs = [
                CL_Kline(index=eb.id, date=_to_dt(eb.dt),
                         h=eb.high, l=eb.low, o=eb.open, c=eb.close, a=eb.vol)
                for eb in nb.elements
            ]
            self._cl_klines.append(CLKline(
                k_index=nb.id, date=_to_dt(nb.dt),
                h=nb.high, l=nb.low, o=nb.open, c=nb.close, a=nb.vol,
                klines=subs, index=len(self._cl_klines), _n=len(subs), _q=False,
            ))

        # ── FX ──
        self._fxs = []
        for c_fx in czsc_obj.fx_list:
            elements = c_fx.elements
            if len(elements) < 3:
                continue
            mid_idx = nb_id_to_clk_idx.get(elements[1].id)
            if mid_idx is None or mid_idx >= len(self._cl_klines):
                continue
            mid_ck = self._cl_klines[mid_idx]
            left_ck = self._cl_klines[nb_id_to_clk_idx.get(elements[0].id)] if nb_id_to_clk_idx.get(elements[0].id) is not None else None
            right_ck = self._cl_klines[nb_id_to_clk_idx.get(elements[2].id)] if nb_id_to_clk_idx.get(elements[2].id) is not None else None
            self._fxs.append(FX(
                _type=_mark_to_type(c_fx.mark), k=mid_ck,
                klines=[left_ck, mid_ck, right_ck],
                val=c_fx.fx, index=len(self._fxs),
                done=True if right_ck is not None else False,
            ))

        # ── BI ──
        self._bis = []
        for c_bi in czsc_obj.bi_list:
            el_a = list(c_bi.fx_a.elements)
            el_b = list(c_bi.fx_b.elements)
            mid_a_idx = nb_id_to_clk_idx.get(el_a[1].id)
            mid_b_idx = nb_id_to_clk_idx.get(el_b[1].id)
            if mid_a_idx is None or mid_b_idx is None:
                continue
            mid_a_ck = self._cl_klines[mid_a_idx]
            left_a_ck = self._cl_klines[nb_id_to_clk_idx[el_a[0].id]] if nb_id_to_clk_idx.get(el_a[0].id) is not None else None
            right_a_ck = self._cl_klines[nb_id_to_clk_idx[el_a[2].id]] if nb_id_to_clk_idx.get(el_a[2].id) is not None else None
            mid_b_ck = self._cl_klines[mid_b_idx]
            left_b_ck = self._cl_klines[nb_id_to_clk_idx[el_b[0].id]] if nb_id_to_clk_idx.get(el_b[0].id) is not None else None
            right_b_ck = self._cl_klines[nb_id_to_clk_idx[el_b[2].id]] if nb_id_to_clk_idx.get(el_b[2].id) is not None else None

            sf = FX(_type=_mark_to_type(c_bi.fx_a.mark), k=mid_a_ck,
                    klines=[left_a_ck, mid_a_ck, right_a_ck],
                    val=c_bi.fx_a.fx, index=len(self._fxs),
                    done=True if right_a_ck is not None else False)
            ef = FX(_type=_mark_to_type(c_bi.fx_b.mark), k=mid_b_ck,
                    klines=[left_b_ck, mid_b_ck, right_b_ck],
                    val=c_bi.fx_b.fx, index=len(self._fxs) + 1,
                    done=True if right_b_ck is not None else False)
            self._fxs.append(sf)
            self._fxs.append(ef)

            b = BI(start=sf, end=ef, _type=_direction_to_type(c_bi.direction),
                   index=len(self._bis), default_zs_type=Config.ZS_TYPE_BZ.value)
            b.high = c_bi.high
            b.low = c_bi.low
            b.zs_high = max(c_bi.high, c_bi.low)
            b.zs_low = min(c_bi.high, c_bi.low)
            self._bis.append(b)

        # ── 补充末尾未完成分型 ──
        if len(self._cl_klines) >= 2:
            last_done = next((f.type for f in reversed(self._fxs) if f.done), None)
            # 检查最后两根是否存在潜在分型
            left, mid = self._cl_klines[-2], self._cl_klines[-1]
            # 潜力顶分型：mid高 >= left高 且 mid低 >= left低
            if mid.h >= left.h and mid.l >= left.l:
                if last_done != "ding":
                    self._fxs.append(FX(
                        _type="ding", k=mid, klines=[left, mid, None],
                        val=mid.h, index=len(self._fxs), done=False,
                    ))
            # 潜力底分型：mid低 <= left低 且 mid高 <= left高
            elif mid.l <= left.l and mid.h <= left.h:
                if last_done != "di":
                    self._fxs.append(FX(
                        _type="di", k=mid, klines=[left, mid, None],
                        val=mid.l, index=len(self._fxs), done=False,
                    ))

        return len(self._bis) > 0

    def _validate_and_correct(self, raw_bars: List[RawBar]) -> None:
        # 极限递归保护
        if not self._bis:
            return False

        changed = False

        # ── 不能出现两笔连续下或连续上（双重保障）──
        # 缠论要求笔必须交替（上、下、上、下...），
        # CZSC 库可能因数据边界问题产生同向连续笔，
        # 若单次过滤仍残留，则反复清除直到完全交替。
        # 修改 2026-05-11：无条件丢弃同向第二笔 + 循环清除
        max_pass = 5
        for _ in range(max_pass):
            clean = True
            if len(self._bis) > 1:
                valid = [self._bis[0]]
                for b in self._bis[1:]:
                    prev = valid[-1]
                    if prev.type == b.type:
                        clean = False
                        continue  # 同向连续，丢弃第二笔
                    valid.append(b)
                self._bis = valid
            if clean:
                break

        # ── 当前笔内CL K线不足5条：删除下两笔，当前笔终点连到后2笔起点 ──
        # ── 连续性修正 ──
        if len(self._bis) > 1:
            fixed = [self._bis[0]]
            for b in self._bis[1:]:
                p = fixed[-1]
                if b.start.k.index != p.end.k.index:
                    p.end = b.start
                    if p.type == "up":
                        p.low = b.start.val
                    else:
                        p.high = b.start.val
                    p.zs_high, p.zs_low = max(p.high, p.low), min(p.high, p.low)
                fixed.append(b)
            self._bis = fixed

        # ── 极值修正：扫描 cl_klines，更新 high/low 及端点时间 ──
        first_corrected_idx = -1
        for b_idx, b in enumerate(self._bis):
            si = b.start.k.index
            ei = b.end.k.index
            if si < 0 or si >= len(self._cl_klines) or ei < 0 or ei >= len(self._cl_klines):
                continue
            if si > ei:
                si, ei = ei, si
            best_high_val = b.high
            best_high_ck = None
            best_low_val = b.low
            best_low_ck = None
            for ck in self._cl_klines[si: ei + 1]:
                if ck.h > best_high_val:
                    best_high_val = ck.h
                    best_high_ck = ck
                if ck.l < best_low_val:
                    best_low_val = ck.l
                    best_low_ck = ck
            b.high = best_high_val
            b.low = best_low_val

            # 更新价格+时间到极值发生时点
            if b.type == "up":
                if b.low < b.start.val and best_low_ck is not None:
                    b.start.val = b.low
                    b.start.k.date = best_low_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
                if b.high > b.end.val and best_high_ck is not None:
                    b.end.val = b.high
                    b.end.k.date = best_high_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
            else:
                if b.high > b.start.val and best_high_ck is not None:
                    b.start.val = b.high
                    b.start.k.date = best_high_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
                if b.low < b.end.val and best_low_ck is not None:
                    b.end.val = b.low
                    b.end.k.date = best_low_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
            b.zs_high = max(b.high, b.low)
            b.zs_low = min(b.high, b.low)

        # ── 共享端点价格同步（时间靠共享 CLKline 对象自动同步）──
        for i in range(len(self._bis) - 1):
            cur = self._bis[i]
            nxt = self._bis[i + 1]
            if cur.type == "up" and nxt.type == "down":
                shared = max(cur.end.val, nxt.start.val)
                cur.end.val = shared
                nxt.start.val = shared
            elif cur.type == "down" and nxt.type == "up":
                shared = min(cur.end.val, nxt.start.val)
                cur.end.val = shared
                nxt.start.val = shared

        return changed

    def _build_synthetic_clkline(self, nb: NewBar) -> CLKline:
        """从 CZSC NewBar 快速构建一条 CLKline（用于重建笔时）"""
        subs = [
            CL_Kline(
                index=eb.id, date=_to_dt(eb.dt),
                h=eb.high, l=eb.low, o=eb.open, c=eb.close, a=eb.vol,
            )
            for eb in nb.elements
        ]
        return CLKline(
            k_index=nb.id, date=_to_dt(nb.dt),
            h=nb.high, l=nb.low, o=nb.open, c=nb.close, a=nb.vol,
            klines=subs, index=len(self._cl_klines), _n=len(subs), _q=False,
        )

    def _calc_macd(self, raw_bars: List[RawBar], czsc_obj: Optional[_CZSC] = None):
        """
        计算 MACD 指标（优先使用 CZSC 原始序列，否则使用输入数据）
        """
        if czsc_obj is not None and czsc_obj.bars_raw:
            closes = np.array([b.close for b in czsc_obj.bars_raw], dtype=float)
        else:
            closes = np.array([b.close for b in raw_bars], dtype=float)

        if len(closes) < 26:
            closes = np.pad(closes, (26 - len(closes), 0), mode="edge")

        def _ema(d, p):
            r = np.zeros_like(d)
            r[0] = d[0]
            m = 2.0 / (p + 1)
            for i in range(1, len(d)):
                r[i] = (d[i] - r[i - 1]) * m + r[i - 1]
            return r

        dif = _ema(closes, 12) - _ema(closes, 26)
        dea = _ema(dif, 9)
        self._idx = {
            "macd": {
                "dif": dif.tolist(),
                "dea": dea.tolist(),
                "hist": (2 * (dif - dea)).tolist(),
            }
        }

    # ── 买卖点计算（1买/2买/3买/1卖/2卖/3卖）──

    def _calc_mmds(self):
        """
        根据配置计算所有买卖点。
        全自实现，不依赖 cl.py（PyArmor 加密版）。
        """
        calcs = self._config  # cl_mmd_cal_* 键直接放在 config 顶层
        if not calcs:
            return

        zs_type = Config.ZS_TYPE_BZ.value  # "bi"
        bis = self._bis
        zss = self._bi_zss

        # 清空旧买卖点
        for b in bis:
            b.mmds = []
            b.zs_type_mmds = {}
            b.bcs = []
            b.zs_type_bcs = {}

        # 预处理：记录每个BI序号对应的BI对象
        bi_by_idx = {b.index: b for b in bis}

        for i, bi in enumerate(bis):
            if not bi.is_done():
                continue

            is_up = bi.type == "up"
            same_bis = [b for b in bis[:i] if b.type == bi.type]

            # 找到bi之前的所有已完成中枢（bi不在其中）
            prev_zss = []
            for z in zss:
                z_bis = [l for l in z.lines if isinstance(l, BI)]
                if not z_bis:
                    continue
                # bi不能是中线的组成笔
                if bi in z_bis:
                    continue
                # 中枢必须完全在bi之前
                if z_bis[-1].index < bi.index:
                    prev_zss.append(z)

            if not prev_zss:
                continue

            last_zs = prev_zss[-1]

            # ── 3买/3卖：离开中枢后回调不进入 ──
            if not is_up:
                # 下跌笔，结束后不进入中枢 → 三买
                if bi.low >= last_zs.zg:
                    if str(calcs.get("cl_mmd_cal_not_in_zs_3mmd", "0")) == "1":
                        bi.add_mmd("3buy", last_zs, zs_type,
                                   "离开中枢后回调不进入")
                    if str(calcs.get("cl_mmd_cal_not_in_zs_gt_9_3mmd", "0")) == "1":
                        if last_zs.line_num >= 9:
                            bi.add_mmd("3buy", last_zs, zs_type,
                                       f"离开中枢后回调不进入（中枢≥9段）")
            else:
                # 上涨笔，结束后不进入中枢 → 三卖
                if bi.high <= last_zs.zd:
                    if str(calcs.get("cl_mmd_cal_not_in_zs_3mmd", "0")) == "1":
                        bi.add_mmd("3sell", last_zs, zs_type,
                                   "离开中枢后反弹不进入")
                    if str(calcs.get("cl_mmd_cal_not_in_zs_gt_9_3mmd", "0")) == "1":
                        if last_zs.line_num >= 9:
                            bi.add_mmd("3sell", last_zs, zs_type,
                                       f"离开中枢后反弹不进入（中枢≥9段）")

            # ── 趋势判断：查找前序同向中枢 ──
            same_dir_zss = [z for z in prev_zss if z.type == bi.type]
            has_trend = len(same_dir_zss) >= 2 and self.zss_is_qs(
                same_dir_zss[-2], same_dir_zss[-1]
            )[0] is not None

            # ── 1买/1卖（趋势背驰）──
            if has_trend and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                bc_result, _ = self.beichi_qs(bis, zss, bi)
                if bc_result and str(calcs.get("cl_mmd_cal_qs_1mmd", "0")) == "1":
                    name = "1buy" if not is_up else "1sell"
                    bi.add_mmd(name, last_zs, zs_type,
                               f"趋势背驰产生{'一买' if not is_up else '一卖'}")
                    bi.add_bc("qs", last_zs, prev_same,
                              [prev_same, bi], True, zs_type)

            # ── 非趋势 + 三买后 一买/一卖 ──
            if not has_trend:
                _has_3_in_this = any(
                    m.name == ("3buy" if not is_up else "3sell")
                    for m in bi.get_mmds(zs_type)
                )
                if _has_3_in_this and len(same_bis) >= 1:
                    bc_result, _ = self.beichi_pz(last_zs, bi)
                    if bc_result and str(calcs.get("cl_mmd_cal_not_qs_3mmd_1mmd", "0")) == "1":
                        name = "1buy" if not is_up else "1sell"
                        bi.add_mmd(name, last_zs, zs_type,
                                   "三买/卖后新高/新低背驰产生一买/一卖")

            # ── 趋势 + 三买后 一买/一卖 ──
            if has_trend:
                _has_3_in_this = any(
                    m.name == ("3buy" if not is_up else "3sell")
                    for m in bi.get_mmds(zs_type)
                )
                if _has_3_in_this and len(same_bis) >= 1:
                    bc_result, _ = self.beichi_qs(bis, zss, bi)
                    if bc_result and str(calcs.get("cl_mmd_cal_qs_3mmd_1mmd", "0")) == "1":
                        name = "1buy" if not is_up else "1sell"
                        bi.add_mmd(name, last_zs, zs_type,
                                   "趋势三买/卖后新高/新低背驰产生一买/一卖")

            # ── 2买/2卖 ──
            # 检查之前是否有1买/1卖
            _prev_has_1 = any(
                any(m.name == ("1buy" if not is_up else "1sell") for m in b.get_mmds(zs_type))
                for b in same_bis
            )
            _prev_has_3 = any(
                any(m.name == ("3buy" if not is_up else "3sell") for m in b.get_mmds(zs_type))
                for b in same_bis
            )

            if not is_up and _prev_has_1 and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                # 一买后不创新低
                if bi.low >= prev_same.low:
                    if str(calcs.get("cl_mmd_cal_qs_not_lh_2mmd", "0")) == "1":
                        bi.add_mmd("2buy", last_zs, zs_type,
                                   "一买后不创新低产生二买")
                # 一买后创新低但有背驰
                elif bi.low < prev_same.low:
                    bc_result, _ = self.beichi_pz(last_zs, bi)
                    if bc_result:
                        if str(calcs.get("cl_mmd_cal_qs_bc_2mmd", "0")) == "1":
                            bi.add_mmd("2buy", last_zs, zs_type,
                                       "一买后新低背驰产生二买")

            if is_up and _prev_has_1 and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                if bi.high <= prev_same.high:
                    if str(calcs.get("cl_mmd_cal_qs_not_lh_2mmd", "0")) == "1":
                        bi.add_mmd("2sell", last_zs, zs_type,
                                   "一卖后不创新高产生二卖")
                elif bi.high > prev_same.high:
                    bc_result, _ = self.beichi_pz(last_zs, bi)
                    if bc_result:
                        if str(calcs.get("cl_mmd_cal_qs_bc_2mmd", "0")) == "1":
                            bi.add_mmd("2sell", last_zs, zs_type,
                                       "一卖后新高背驰产生二卖")

            # 三买/卖后 → 二买/二卖
            if not is_up and _prev_has_3 and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                if bi.low >= prev_same.low:
                    if str(calcs.get("cl_mmd_cal_3mmd_not_lh_bc_2mmd", "0")) == "1":
                        bi.add_mmd("2buy", last_zs, zs_type,
                                   "三买后不创新低产生二买")
                else:
                    bc_result, _ = self.beichi_pz(last_zs, bi)
                    if bc_result:
                        if str(calcs.get("cl_mmd_cal_3mmd_not_lh_bc_2mmd", "0")) == "1":
                            bi.add_mmd("2buy", last_zs, zs_type,
                                       "三买后背驰产生二买")

            if is_up and _prev_has_3 and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                if bi.high <= prev_same.high:
                    if str(calcs.get("cl_mmd_cal_3mmd_not_lh_bc_2mmd", "0")) == "1":
                        bi.add_mmd("2sell", last_zs, zs_type,
                                   "三卖后不创新高产生二卖")
                else:
                    bc_result, _ = self.beichi_pz(last_zs, bi)
                    if bc_result:
                        if str(calcs.get("cl_mmd_cal_3mmd_not_lh_bc_2mmd", "0")) == "1":
                            bi.add_mmd("2sell", last_zs, zs_type,
                                       "三卖后背驰产生二卖")

            # 一买/一卖后，当前不创新高/低（简单二买/二卖）
            if not is_up and _prev_has_1 and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                if bi.low >= prev_same.low:
                    if str(calcs.get("cl_mmd_cal_1mmd_not_lh_2mmd", "0")) == "1":
                        bi.add_mmd("2buy", last_zs, zs_type,
                                   "一买后不创新低产生二买")
            if is_up and _prev_has_1 and len(same_bis) >= 1:
                prev_same = same_bis[-1]
                if bi.high <= prev_same.high:
                    if str(calcs.get("cl_mmd_cal_1mmd_not_lh_2mmd", "0")) == "1":
                        bi.add_mmd("2sell", last_zs, zs_type,
                                   "一卖后不创新高产生二卖")

    def _get_last_related_zs(self, bi: BI, zss: List[ZS]) -> Optional[ZS]:
        """
        找到当前BI之前最近的已完成中枢（BI不在中枢组成线中）。
        用于外部兼容调用。
        """
        if not zss:
            return None
        cand = []
        for z in zss:
            z_bis = [l for l in z.lines if isinstance(l, BI)]
            if not z_bis:
                continue
            if bi in z_bis:
                continue
            if z_bis[-1].index < bi.index:
                cand.append(z)
        if not cand:
            return None
        return cand[-1]

    # ── ICL 接口 ──

    def get_code(self) -> str:
        return self._code

    def get_frequency(self) -> str:
        return self._frequency

    def get_config(self) -> dict:
        return self._config

    def get_src_klines(self) -> List[CL_Kline]:
        return self._src_klines

    def get_klines(self) -> List[CL_Kline]:
        return self._src_klines

    def get_cl_klines(self) -> List[CLKline]:
        return self._cl_klines

    def get_idx(self) -> dict:
        return self._idx

    def get_fxs(self) -> List[FX]:
        return self._fxs

    def get_bis(self) -> List[BI]:
        return self._bis

    def get_xds(self) -> List[XD]:
        return self._xds

    def get_zsds(self) -> List[XD]:
        return []

    def get_qsds(self) -> List[XD]:
        return []

    def get_bi_zss(self, zs_type: str = None) -> List[ZS]:
        return self._bi_zss

    def get_xd_zss(self, zs_type: str = None) -> List[ZS]:
        return []

    def get_zsd_zss(self) -> List[ZS]:
        return []

    def get_qsd_zss(self) -> List[ZS]:
        return []

    def get_last_bi_zs(self) -> Optional[ZS]:
        return self._bi_zss[-1] if self._bi_zss else None

    def get_last_xd_zs(self) -> Optional[ZS]:
        return None

    # ── Pickle 支持 ──

    def __reduce__(self):
        """
        自定义序列化：排除不可 pickle 的 CZSC 对象和 Freq 枚举
        """
        return (self.__class__._reconstruct, (
            self._code,
            self._frequency,
            self._config,
            self._start_datetime,
            self._src_klines,
            self._cl_klines,
            self._fxs,
            self._bis,
            self._xds,
            self._bi_zss,
            self._idx,
        ))

    @staticmethod
    def _reconstruct(code, frequency, config, start_datetime,
                     src_klines, cl_klines, fxs, bis, xds, bi_zss, idx):
        """反序列化重建"""
        obj = CD.__new__(CD)
        obj._code = code
        obj._frequency = frequency
        obj._config = config or {}
        obj._start_datetime = start_datetime
        obj._higher_level_direction = None
        obj._higher_level_bis = None
        obj._czsc_freq = _freq_str_to_czsc(frequency)
        obj._src_klines = src_klines
        obj._cl_klines = cl_klines
        obj._fxs = fxs
        obj._bis = bis
        obj._xds = xds
        obj._bi_zss = bi_zss
        obj._idx = idx
        obj._czsc = None
        return obj

    def create_dn_zs(
        self, zs_type: str, lines: List[LINE],
        max_line_num: int = 999, zs_include_last_line=True,
    ) -> List[ZS]:
        if not lines:
            return []
        bis_only = [l for l in lines if isinstance(l, BI)]
        if len(bis_only) < 3:
            return []
        return _build_zss_from_bis(bis_only, zs_type, config=None)

    def beichi_pz(self, zs: ZS, now_line: LINE) -> Tuple[bool, Optional[LINE]]:
        """盘整背驰"""
        if not self._bis or len(self._bis) < 3:
            return False, None
        if not isinstance(now_line, BI):
            return False, None

        pre_same_line = None
        for b in self._bis:
            if b.index < now_line.index and b.type == now_line.type:
                pre_same_line = b

        if pre_same_line is None:
            return False, None

        ld1 = pre_same_line.get_ld(self)
        ld2 = now_line.get_ld(self)
        if "macd" not in ld1 or "macd" not in ld2:
            return False, None

        bc = compare_ld_beichi(ld1, ld2, now_line.type)
        return bc, now_line

    def beichi_qs(
        self, lines: List[LINE], zss: List[ZS], now_line: LINE
    ) -> Tuple[bool, List[LINE]]:
        """趋势背驰"""
        if len(zss) < 2:
            return False, []
        if not isinstance(now_line, BI):
            return False, []

        is_up = now_line.type == "up"
        zs1, zs2 = zss[-2], zss[-1]
        if is_up:
            if zs2.zg <= zs1.zg:
                return False, []
        else:
            if zs2.zd >= zs1.zd:
                return False, []

        same_dir_lines = [
            l for l in lines if isinstance(l, BI) and l.type == now_line.type
        ]
        if len(same_dir_lines) < 3:
            return False, []

        comp_line = same_dir_lines[-3]
        ld1 = comp_line.get_ld(self)
        ld2 = now_line.get_ld(self)
        bc = compare_ld_beichi(ld1, ld2, now_line.type)
        if bc:
            return bc, [comp_line, now_line]
        return False, []

    def zss_is_qs(self, one_zs: ZS, two_zs: ZS) -> Tuple[Optional[str], None]:
        """判断两个中枢是否形成趋势"""
        wzgx = self._config.get("zs_wzgx", Config.ZS_WZGX_ZGD.value)

        if wzgx == Config.ZS_WZGX_ZGD.value:
            overlap = one_zs.zg < two_zs.zd or two_zs.zg < one_zs.zd
        elif wzgx == Config.ZS_WZGX_GD.value:
            overlap = one_zs.gg < two_zs.dd or two_zs.gg < one_zs.dd
        else:
            overlap = one_zs.zg < two_zs.zd or two_zs.zg < one_zs.zd

        if overlap:
            return None, None

        if one_zs.gg >= two_zs.gg and one_zs.dd >= two_zs.dd:
            return "down", None
        elif one_zs.gg <= two_zs.gg and one_zs.dd <= two_zs.dd:
            return "up", None
        return None, None


# ═══════════════════════════════════════════════════════════════════════
# 兼容接口（供外部代码直接调用）
# ═══════════════════════════════════════════════════════════════════════

def _merge_klines_to_clk(klines: List[CL_Kline]) -> List[CLKline]:
    """
    原始K线 → 缠论K线（方向性包含合并）
    """
    if not klines:
        return []

    clks: List[CLKline] = []

    first = klines[0]
    if first.c > first.o:
        first_o = first.l
        first_c = first.h
    else:
        first_o = first.h
        first_c = first.l
    cur = CLKline(
        k_index=first.index, date=first.date,
        h=first.h, l=first.l, o=first_o, c=first_c, a=first.a,
        klines=[first], index=0, _n=1, _q=False,
    )
    clks.append(cur)

    for i in range(1, len(klines)):
        k = klines[i]
        prev = clks[-1]

        prev_contains_new = prev.h >= k.h and prev.l <= k.l
        new_contains_prev = prev.h <= k.h and prev.l >= k.l
        is_contained = prev_contains_new or new_contains_prev

        if not is_contained:
            if k.c > k.o:
                nk_o = k.l
                nk_c = k.h
            else:
                nk_o = k.h
                nk_c = k.l
            nk = CLKline(
                k_index=k.index, date=k.date,
                h=k.h, l=k.l, o=nk_o, c=nk_c, a=k.a,
                klines=[k], index=k.index, _n=0, _q=False,
            )
            clks.append(nk)
            continue

        if len(clks) >= 2:
            pprev = clks[-2]
            trend_up = pprev.h < prev.h and pprev.l < prev.l
            trend_down = pprev.h > prev.h and pprev.l > prev.l
        else:
            trend_up = trend_down = False

        if trend_up:
            new_h = max(prev.h, k.h)
            new_l = max(prev.l, k.l)
            up_qs_dir = "up"
        elif trend_down:
            new_h = min(prev.h, k.h)
            new_l = min(prev.l, k.l)
            up_qs_dir = "down"
        else:
            new_h = min(prev.h, k.h)
            new_l = min(prev.l, k.l)
            up_qs_dir = "down"

        if new_h != prev.h or new_l != prev.l:
            prev.h = new_h
            prev.l = new_l
            if up_qs_dir == "up":
                prev.o = new_l
                prev.c = new_h
            else:
                prev.o = new_h
                prev.c = new_l
            if new_contains_prev:
                prev.k_index = k.index
                prev.date = k.date
            prev.a += k.a
            prev.klines.append(k)
            prev.n += 1
            prev.up_qs = up_qs_dir

    for idx, ck in enumerate(clks):
        ck.index = idx
    return clks


def _identify_fxs(clks: List[CLKline]) -> List[FX]:
    """
    分型判定：三根连续缠论K线中
    """
    fxs: List[FX] = []
    fx_idx = 0

    for i in range(1, len(clks) - 1):
        left, mid, right = clks[i - 1], clks[i], clks[i + 1]

        if mid.h >= left.h and mid.h >= right.h and \
           mid.l >= left.l and mid.l >= right.l:
            fx = FX(
                _type="ding", k=mid,
                klines=[left, mid, right],
                val=mid.h, index=fx_idx, done=True,
            )
            fxs.append(fx)
            fx_idx += 1

        elif mid.l <= left.l and mid.l <= right.l and \
             mid.h <= left.h and mid.h <= right.h:
            fx = FX(
                _type="di", k=mid,
                klines=[left, mid, right],
                val=mid.l, index=fx_idx, done=True,
            )
            fxs.append(fx)
            fx_idx += 1

    if len(clks) >= 2:
        left, mid = clks[-2], clks[-1]
        if mid.h >= left.h and mid.l >= left.l:
            fxs.append(FX(
                _type="ding", k=mid,
                klines=[left, mid, None],
                val=mid.h, index=fx_idx, done=False,
            ))
            fx_idx += 1
        elif mid.l <= left.l and mid.h <= left.h:
            fxs.append(FX(
                _type="di", k=mid,
                klines=[left, mid, None],
                val=mid.l, index=fx_idx, done=False,
            ))
            fx_idx += 1

    return fxs


# ── 别名（供 cl2/cl3 等模块引用） ──
from chanlun.cl2 import CD as _CL2_CD
CD = _CL2_CD
CL = CD

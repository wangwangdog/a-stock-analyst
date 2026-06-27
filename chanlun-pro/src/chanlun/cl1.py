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


# ── 全局调试开关 ──
SHOW_ZHONGSHU_CHECK_OVERLAP = True  # True=检查中间笔重叠，False=跳过重叠检查


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
# 中枢构建（5笔中枢 + 保留旧3笔辅助函数）
# ═══════════════════════════════════════════════════════════════════════

def _find_parent_segment_dir(bis: List[BI], start_idx: int) -> str:
    """
    根据当前 bis 的宏观结构推断"高一级别"方向。
    取 start_idx 之前最近一段同向笔簇的方向作为 parent 方向。
    """
    if start_idx < 2:
        return "up"
    nearby = bis[max(0,start_idx-4):start_idx]
    ups = sum(1 for b in nearby if b.type == "up")
    downs = sum(1 for b in nearby if b.type == "down")
    if ups > downs:
        return "up"
    elif downs > ups:
        return "down"
    return bis[min(start_idx,len(bis)-1)].type if start_idx < len(bis) else "up"


def _candidate_pattern(parent_dir: str) -> tuple:
    """
    根据高一级别方向返回候选三笔形态。
    - parent=up → candidate=下-上-下（第1笔下,第2笔上,第3笔下）
    - parent=down → candidate=上-下-上
    返回 (bi1_type, bi2_type, bi3_type)
    """
    if parent_dir == "down":
        return ("up", "down", "up")
    else:
        return ("down", "up", "down")


def _check_within_parent_boundary(
    bi1: BI, bi2: BI, bi3: BI, parent_start: BI, parent_end: BI
) -> bool:
    """
    检查候选三笔是否完全落在同一高一级别笔边界内。
    """
    s_idx = min(bi1.start.k.k_index, bi2.start.k.k_index, bi3.start.k.k_index)
    e_idx = max(bi1.end.k.k_index, bi2.end.k.k_index, bi3.end.k.k_index)
    p_s = parent_start.start.k.k_index
    p_e = parent_end.end.k.k_index
    return s_idx >= p_s and e_idx <= p_e


def _check_middle_overlap(bi1: BI, bi2: BI, bi3: BI) -> tuple:
    """
    检查中间3笔是否存在价格重叠区间。
    返回 (zg, zd, gg, dd) 或 None。
    """
    h1, l1 = bi1.high, bi1.low
    h2, l2 = bi2.high, bi2.low
    h3, l3 = bi3.high, bi3.low
    zg = min(h1, h2, h3)
    zd = max(l1, l2, l3)
    gg = max(h1, h2, h3)
    dd = min(l1, l2, l3)
    return (zg, zd, gg, dd) if zg > zd else None


# ── 频率等级映射（上一级别） ──
FREQ_PARENT = {
    "5m": "30m",
    "15m": "30m",
    "30m": "d",
    "60m": "d",
    "d": "w",
    "w": "m",
}


# ── 全局调试开关 ──
ZS_CANDIDATE_PENS = 5        # 候选笔数（奇数，3或5）
ZS_CHECK_HIGHER_DIR = 0      # 高一级别方向检查（默认关）
ZS_CHECK_HIGHER_BOUNDARY = 0 # 高一级别边界检查（默认关）
ZS_CHECK_OVERLAP = 1         # 重叠检查（默认开）
ZS_CHECK_EXTENSION = 0       # 延伸检查（默认关）
ZS_CHECK_NEW_ZS = 0          # 新生检查（默认关）
ZS_CHECK_ENTRY_EXIT = 1      # 进入离开合理性检查（默认开）


def _build_higher_level_bis(bis: List[BI], config: dict = None) -> List[dict]:
    """生成高一级别笔序列"""
    config = config or {}
    seg_threshold = float(config.get('zs_seg_threshold', 0.9))
    if not bis:
        return []
    segments = []
    cur_start = 0
    cur_dir = bis[0].type
    cur_start_price = bis[0].start.val
    cur_end_price = bis[0].end.val
    for idx, b in enumerate(bis[1:], start=1):
        net_change = b.end.val - cur_start_price
        if cur_dir == "up" and net_change < 0 and abs(net_change) > abs(cur_end_price - cur_start_price) * seg_threshold:
            segments.append({"dir": cur_dir, "start_idx": cur_start, "end_idx": idx})
            cur_start = idx; cur_dir = "down"; cur_start_price = b.start.val
        elif cur_dir == "down" and net_change > 0 and abs(net_change) > abs(cur_end_price - cur_start_price) * seg_threshold:
            segments.append({"dir": cur_dir, "start_idx": cur_start, "end_idx": idx})
            cur_start = idx; cur_dir = "up"; cur_start_price = b.start.val
        cur_end_price = b.end.val
    if cur_start < len(bis):
        segments.append({"dir": cur_dir, "start_idx": cur_start, "end_idx": len(bis) - 1})
    return segments


def _get_hl_dir_at_idx(hl_bis: List[dict], bi_idx: int) -> Optional[str]:
    for seg in hl_bis:
        if seg["start_idx"] <= bi_idx <= seg["end_idx"]:
            return seg["dir"]
    return None


def _check_three_bi_pattern(b1: BI, b2: BI, b3: BI, hl_dir: str = None) -> bool:
    """检查三笔形态"""
    if hl_dir is None:
        return b1.type != b2.type and b2.type != b3.type
    if hl_dir == "up":
        return b1.type == "down" and b2.type == "up" and b3.type == "down"
    if hl_dir == "down":
        return b1.type == "up" and b2.type == "down" and b3.type == "up"
    return False


def _check_five_bi_pattern(entry: BI, b2: BI, b3: BI, b4: BI, exit_bi: BI, hl_dir: str = None) -> bool:
    """检查五笔形态（高一级别方向 + 边界）"""
    if hl_dir is None:
        return (entry.type != b2.type and b2.type != b3.type
                and b3.type != b4.type and b4.type != exit_bi.type)
    # 上涨方向（hl_dir=up）：5笔下-上-下-上-下
    if hl_dir == "up":
        return (entry.type == "down" and b2.type == "up" and b3.type == "down"
                and b4.type == "up" and exit_bi.type == "down")
    # 下跌方向（hl_dir=down）：5笔上-下-上-下-上
    if hl_dir == "down":
        return (entry.type == "up" and b2.type == "down" and b3.type == "up"
                and b4.type == "down" and exit_bi.type == "up")
    return False


def _get_body_pens(entry: BI, middle: List[BI], exit_bi: BI, zs_dir: str) -> List[BI]:
    """返回中枢体笔列表（排除进入/离开笔）"""
    return middle


def _calc_zs_zg_zd(body_pens: List[BI], zs_dir: str) -> Tuple[float, float, float, float]:
    """
    计算 zg/zd/gg/dd。
    上涨中枢：取所有 body_pens 终点的最低值作为 zg
    下跌中枢：取所有 body_pens 终点的最高值作为 zd
    """
    if not body_pens:
        return 0, 0, 0, 0
    ends = [b.end.val for b in body_pens]
    zg = max(ends)  # 中枢上沿 = body 笔终点的最高值
    zd = min(ends)  # 中枢下沿 = body 笔终点的最低值
    gg = max(b.high for b in body_pens)
    dd = min(b.low for b in body_pens)
    return (zg, zd, gg, dd)


def _check_overlap(bis_window: List[BI]) -> Optional[Tuple[float, float, float, float]]:
    """检查一组笔是否有重叠区间（用所有笔的高低价）"""
    if len(bis_window) < 2:
        return None
    zg = min(b.high for b in bis_window)
    zd = max(b.low for b in bis_window)
    if zg > zd:
        return (zg, zd, max(b.high for b in bis_window), min(b.low for b in bis_window))
    return None


def _check_extension_condition(zs: ZS, bi: BI) -> bool:
    """检查 bi 是否与中枢 ZD~ZG 重叠（延伸条件：最高点≥ZD 且 最低点≤ZG）"""
    if bi.high is None or bi.low is None:
        return False
    return bi.high >= zs.zd and bi.low <= zs.zg


def _check_new_zhongshu_3buy(prev_zs: ZS, b1: BI, is_up: bool) -> bool:
    """检查是否满足第三类买卖点"""
    if is_up:
        return b1.low > prev_zs.zg
    else:
        return b1.high < prev_zs.zd


def _check_entry_exit_reasonable(entry_bi: BI, exit_bi: BI, zs_dir: str) -> bool:
    """检查进入笔与离开笔的合理性（上涨/下跌趋势方向验证）"""
    if entry_bi.start is None or exit_bi.end is None:
        return True
    # 上涨中枢：进入笔起点 < 离开笔终点（向上推进）
    if zs_dir == "up":
        return entry_bi.start.val < exit_bi.end.val
    # 下跌中枢：进入笔起点 > 离开笔终点（向下推进）
    return entry_bi.start.val > exit_bi.end.val


def _get_zs_name_v2(zss: List[ZS], zs: ZS) -> str:
    """中枢命名：A/B/C..."""
    same = [z for z in zss if z.type == zs.type]
    order = len(same) + 1
    return chr(64 + order)


def _get_trend_type(zss: List[ZS], zs: ZS) -> str:
    """判断走势类型"""
    same = [z for z in zss if z.type == zs.type]
    if len(same) >= 2:
        return "趋势上涨" if zs.type == "up" else "趋势下跌"
    return "盘整上涨" if zs.type == "up" else "盘整下跌"


def _build_bi_zss(bis: List[BI], config: dict = None) -> List[ZS]:
    """
    笔中枢构建（知识库标准版）。

    流程（开关状态 1=开 0=关）：
    1. 取候选笔（ZS_CANDIDATE_PENS=5）
    2. 方向交替检查（硬性要求）
    3. 高一级方向检查（ZS_CHECK_HIGHER_DIR=0）
    4. 重叠检查（ZS_CHECK_OVERLAP=1）
    5. 高一级边界检查（ZS_CHECK_HIGHER_BOUNDARY=0）
    6. 延伸检查（ZS_CHECK_EXTENSION=0）
    7. 进入离开合理性检查（ZS_CHECK_ENTRY_EXIT=1）
    8. 中枢新生检查（ZS_CHECK_NEW_ZS=0）
    9. 构建中枢对象 → 完成态标记
    """
    n_pens = ZS_CANDIDATE_PENS
    window = n_pens  # 候选笔数
    if len(bis) < window:
        return []

    config = config or {}
    hl_bis = _build_higher_level_bis(bis, config)

    zss: List[ZS] = []
    zs_idx = 0
    used_indices: set = set()

    i = 0
    while i < len(bis) - (window - 1):
        # ── 取出候选笔（包含当前笔 + 后续 n_pens-1 笔） ──
        candidates = [bis[i + k] for k in range(window)]
        entry = candidates[0]
        body = candidates[1:-1]   # 中间笔
        exit_bi = candidates[-1]

        # 跳过已被使用的笔
        if entry.index in used_indices:
            i += 1
            continue

        # 候选笔必须方向交替
        valid_pattern = True
        for k in range(1, window):
            if candidates[k-1].type == candidates[k].type:
                valid_pattern = False
                break
        if not valid_pattern:
            i += 1
            continue

        # ── 步3：高一级别方向检查（ZS_CHECK_HIGHER_DIR=0）──
        if ZS_CHECK_HIGHER_DIR:
            hl_dir = _get_hl_dir_at_idx(hl_bis, entry.index)
            if not _check_five_bi_pattern(entry, candidates[1], candidates[2], candidates[3], exit_bi, hl_dir):
                i += 1
                continue

        # ── 步4：重叠检查（ZS_CHECK_OVERLAP=1）──
        overlap = None
        if ZS_CHECK_OVERLAP:
            overlap = _check_overlap(candidates)  # 所有候选笔重叠
            if overlap is None:
                i += 1
                continue

        # ── 步5：同高一级别边界检查（ZS_CHECK_HIGHER_BOUNDARY=0）──
        if ZS_CHECK_HIGHER_BOUNDARY:
            dir1 = _get_hl_dir_at_idx(hl_bis, entry.index)
            dir3 = _get_hl_dir_at_idx(hl_bis, exit_bi.index)
            if dir1 is not None and dir3 is not None and dir1 != dir3:
                i += 1
                continue
            # 通过边界检查 → 标记上一个同向中枢为已完成
            for z in reversed(zss):
                if z.type == zs_dir and not z.done:
                    z.done = True

        # ── 中枢方向 ──
        zs_dir = "down" if entry.type == "up" else "up"

        # ── 计算 ZG/ZD/GG/DD ──
        if overlap:
            zg, zd, gg, dd = overlap
        else:
            zg = max(b.high for b in body)
            zd = min(b.low for b in body)
            gg = max(b.high for b in candidates[1:-1])
            dd = min(b.low for b in candidates[1:-1])

        # ── 步6：延伸检查（ZS_CHECK_EXTENSION=0）──
        if ZS_CHECK_EXTENSION and zss:
            same_dir = [z for z in zss if z.type == zs_dir]
            if same_dir:
                prev_zs = same_dir[-1]
                # 检查当前候选是否重叠前中枢 → 延伸
                if not (dd > prev_zs.gg or gg < prev_zs.dd):
                    prev_zs.lines.extend(candidates)
                    prev_zs.line_num = len(prev_zs.lines)
                    prev_zs.end = exit_bi.start
                    # 中枢区间不变，不更新 gg/dd
                    for bi in candidates:
                        used_indices.add(bi.index)
                    i += 1
                    continue

        # ── 步7：进入离开合理性检查（ZS_CHECK_ENTRY_EXIT=1）──
        if ZS_CHECK_ENTRY_EXIT:
            if not _check_entry_exit_reasonable(entry, exit_bi, zs_dir):
                i += 1
                continue
            # 通过合理性检查 → 标记上一个同向中枢为已完成
            same_dir_undone = [z for z in reversed(zss) if z.type == zs_dir and not z.done]
            for z in same_dir_undone:
                z.done = True

        # ── 步8：中枢新生检查（ZS_CHECK_NEW_ZS=0）──
        if ZS_CHECK_NEW_ZS and zss:
            same_dir = [z for z in zss if z.type == zs_dir]
            if same_dir:
                prev_zs = same_dir[-1]
                is_up = zs_dir == "up"
                if not _check_new_zhongshu_3buy(prev_zs, entry, is_up):
                    i += 1
                    continue
                # 新中枢不能与前中枢重叠
                if is_up:
                    if dd <= prev_zs.gg:  # 新中枢DD必须>原中枢GG
                        i += 1
                        continue
                else:
                    if gg >= prev_zs.dd:  # 新中枢GG必须<原中枢DD
                        i += 1
                        continue
                # 通过新生检查 → 标记上一个同向中枢为已完成
                for z in reversed(zss):
                    if z.type == zs_dir and not z.done:
                        z.done = True

        # ── 构建中枢对象 ──
        zs = ZS(
            zs_type="bi",
            start=entry.start,
            end=exit_bi.start,
            zg=zg, zd=zd, gg=gg, dd=dd,
            _type=zs_dir,
            index=zs_idx,
            line_num=window,
            level=0,
        )
        zs.lines = candidates
        zs.done = False
        setattr(zs, "trend_type", _get_trend_type(zss, zs))
        setattr(zs, "segment_index", len(zss))
        setattr(zs, "name", _get_zs_name_v2(zss, zs))
        setattr(zs, "entry_bi", entry)
        setattr(zs, "exit_bi", exit_bi)

        for bi in candidates:
            used_indices.add(bi.index)

        zss.append(zs)
        zs_idx += 1

        # 跳至下一组候选
        i += window

    # ── 步9：完成态标记（步5/7/8已标记完成的中枢不重置） ──
    for idx in range(len(zss) - 1):
        zss[idx].done = True
    # 最后中枢的完成态由步5/7/8决定，步9不强制

    return zss

class CD(ICL):
    """
    缠论分析器 — CZSC 后端适配 chanlun-pro ICL 接口
    """

    def __init__(self, code: str, frequency: str, config: dict = None, start_datetime=None):
        self._code = code
        self._frequency = frequency
        self._config = config or {}
        self._start_datetime = start_datetime
        self._czsc_freq = _freq_str_to_czsc(frequency)

        self._src_klines: List[CL_Kline] = []
        self._cl_klines: List[CLKline] = []
        self._fxs: List[FX] = []
        self._bis: List[BI] = []
        self._xds: List[XD] = []
        self._bi_zss: List[ZS] = []
        self._idx: dict = {"macd": {"dif": [], "dea": [], "hist": []}}
        self._trend_infos: List[dict] = []
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
        入口：Function1 → Function2 递归
        """
        self._run_czsc_bars(raw_bars)
        self._validate_and_correct(raw_bars)
        self._bi_zss = _build_bi_zss(self._bis, config=self._config)
        self._calc_mmds()
        self._calc_trend_infos()

    def _run_czsc_bars(self, raw_bars: List[RawBar]) -> bool:
        """
        Function 1: 接收 raw_bars，跑 CZSC，输出 BIs / FX / CLKlines。
        返回 True 表示成功产出 BIs，False 表示数据不足。
        """
        if len(raw_bars) < 10:
            return False

        # max_bi_num 根据K线数量动态计算
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

        # ── 不能出现两笔连续下或连续上 ──
        if len(self._bis) > 1:
            valid = [self._bis[0]]
            for b in self._bis[1:]:
                prev = valid[-1]
                if prev.type == "down" and b.type == "down":
                    if b.end.val <= prev.end.val:
                        continue
                elif prev.type == "up" and b.type == "up":
                    if b.end.val >= prev.end.val:
                        continue
                valid.append(b)
            self._bis = valid

        # ── 当前笔内CL K线不足5条：删除下两笔，当前笔终点连到后2笔起点 ──
        if len(self._bis) >= 3:
            valid = []
            skip = 0
            for idx in range(len(self._bis)):
                if skip > 0:
                    skip -= 1
                    continue
                b = self._bis[idx]
                span = abs(b.end.k.index - b.start.k.index) + 1
                if span < 5 and idx + 2 < len(self._bis):
                    b.end = self._bis[idx + 2].start
                    si = b.start.k.index
                    ei = b.end.k.index
                    if si >= 0 and si < len(self._cl_klines) and ei >= 0 and ei < len(self._cl_klines):
                        if si > ei:
                            si, ei = ei, si
                        segment = self._cl_klines[si:ei+1] if hasattr(self, '_cl_klines') else []
                        if segment:
                            b.high = max(ck.h for ck in segment)
                            b.low = min(ck.l for ck in segment)
                            b.zs_high = max(b.high, b.low)
                            b.zs_low = min(b.high, b.low)
                    valid.append(b)
                    skip = 2
                else:
                    valid.append(b)
            self._bis = valid

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
                # 上涨笔: start 应为最低点
                if b.low < b.start.val:
                    b.start.val = b.low
                    if best_low_ck is not None:
                        b.start.k.date = best_low_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
                # 上涨笔: end 应为最高点
                if b.high > b.end.val:
                    b.end.val = b.high
                    if best_high_ck is not None:
                        b.end.k.date = best_high_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
            else:
                # 下跌笔: start 应为最高点
                if b.high > b.start.val:
                    b.start.val = b.high
                    if best_high_ck is not None:
                        b.start.k.date = best_high_ck.date
                    changed = True
                    if first_corrected_idx < 0:
                        first_corrected_idx = b_idx
                # 下跌笔: end 应为最低点
                if b.low < b.end.val:
                    b.end.val = b.low
                    if best_low_ck is not None:
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

    # ── ICL 接口 ──

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
                if bi in z_bis:
                    continue
                if z_bis[-1].index < bi.index:
                    prev_zss.append(z)

            if not prev_zss:
                continue

            last_zs = prev_zss[-1]

            # ── 3买/3卖：离开中枢后回调不进入 ──
            if not is_up:
                if bi.low >= last_zs.zg:
                    if str(calcs.get("cl_mmd_cal_not_in_zs_3mmd", "0")) == "1":
                        bi.add_mmd("3buy", last_zs, zs_type,
                                   "离开中枢后回调不进入")
                    if str(calcs.get("cl_mmd_cal_not_in_zs_gt_9_3mmd", "0")) == "1":
                        if last_zs.line_num >= 9:
                            bi.add_mmd("3buy", last_zs, zs_type,
                                       f"离开中枢后回调不进入（中枢≥9段）")
            else:
                if bi.high <= last_zs.zd:
                    if str(calcs.get("cl_mmd_cal_not_in_zs_3mmd", "0")) == "1":
                        bi.add_mmd("3sell", last_zs, zs_type,
                                   "离开中枢后反弹不进入")
                    if str(calcs.get("cl_mmd_cal_not_in_zs_gt_9_3mmd", "0")) == "1":
                        if last_zs.line_num >= 9:
                            bi.add_mmd("3sell", last_zs, zs_type,
                                       f"离开中枢后反弹不进入（中枢≥9段）")

            # ── 趋势判断 ──
            same_dir_zss = [z for z in prev_zss if z.type == bi.type]
            has_trend = len(same_dir_zss) >= 2 and self.zss_is_qs(
                same_dir_zss[-2], same_dir_zss[-1]
            )[0] is not None

            # ── 1买/1卖（趋势背驰）──
            if has_trend and len(same_bis) >= 1:
                bc_result, _ = self.beichi_qs(bis, zss, bi)
                if bc_result and str(calcs.get("cl_mmd_cal_qs_1mmd", "0")) == "1":
                    name = "1buy" if not is_up else "1sell"
                    bi.add_mmd(name, last_zs, zs_type,
                               f"趋势背驰产生{'一买' if not is_up else '一卖'}")
                    bi.add_bc("qs", last_zs, same_bis[-1],
                              [same_bis[-1], bi], True, zs_type)

            # ── 三买后的一买/一卖 ──
            _has_3_in_this = any(
                m.name == ("3buy" if not is_up else "3sell")
                for m in bi.get_mmds(zs_type)
            )
            if _has_3_in_this and len(same_bis) >= 1:
                if not has_trend:
                    bc_result, _ = self.beichi_pz(last_zs, bi)
                else:
                    bc_result, _ = self.beichi_qs(bis, zss, bi)
                if bc_result:
                    key = "cl_mmd_cal_not_qs_3mmd_1mmd" if not has_trend else "cl_mmd_cal_qs_3mmd_1mmd"
                    if str(calcs.get(key, "0")) == "1":
                        name = "1buy" if not is_up else "1sell"
                        bi.add_mmd(name, last_zs, zs_type,
                                   "三买/卖后新高/新低背驰产生一买/一卖")

            # ── 2买/2卖 ──
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
                if bi.low >= prev_same.low:
                    if str(calcs.get("cl_mmd_cal_qs_not_lh_2mmd", "0")) == "1":
                        bi.add_mmd("2buy", last_zs, zs_type,
                                   "一买后不创新低产生二买")
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

    def get_trend_infos(self) -> List[dict]:
        """返回走势类型信息列表（用于TradingView中文标识）"""
        return self._trend_infos

    def _calc_trend_infos(self):
        """
        计算走势类型（trend_type）的完整描述。
        规则：
        - 走势类型由连续同向中枢构成
        - 出现反向中枢或反向三买卖点后结束
        - 反向三买卖点终止时，终点取整个走势的极值（上涨=最高点，下跌=最低点）
        - 起始=第一中枢进入段起点，结束=最后中枢离开段终点或三买卖点
        - 中文标识显示在TradingView上
        """
        zss = self._bi_zss
        if not zss:
            self._trend_infos = []
            return

        bis = self._bis
        infos = []
        i = 0
        while i < len(zss):
            cur_dir = zss[i].type
            # 收集连续同向中枢
            group = [zss[i]]
            j = i + 1
            while j < len(zss) and zss[j].type == cur_dir:
                group.append(zss[j])
                j += 1

            # 确定趋势类型
            if len(group) >= 2:
                trend_text = "趋势上涨" if cur_dir == "up" else "趋势下跌"
            else:
                trend_text = "盘整上涨" if cur_dir == "up" else "盘整下跌"

            # 起止点：第一中枢进入段起点 → 最后中枢离开段终点
            first_zs = group[0]
            last_zs = group[-1]

            # 进入段 = 中枢前面的第一笔
            entry_bi = None
            z_lines = [l for l in first_zs.lines if isinstance(l, BI)]
            if z_lines:
                z_bi_indices = {b.index for b in z_lines}
                # 找中枢之前最近的异向笔
                for b in reversed(bis):
                    if b.index < min(z_bi_indices) and b.type != cur_dir:
                        entry_bi = b
                        break

            # 离开段 = 中枢后面的第一笔
            exit_bi = None
            max_bi_idx_in_group = max(
                max(l.index for l in z.lines if isinstance(l, BI))
                for z in group if z.lines
            ) if any(z.lines for z in group) else 0
            for b in bis:
                if b.index > max_bi_idx_in_group and b.type != cur_dir:
                    exit_bi = b
                    break

            # ── 反向第三类买卖点检查：终止走势 ──
            reverse_3rd = None
            for b in bis:
                if b.index <= max_bi_idx_in_group:
                    continue
                # 上涨走势后的三卖：下跌笔完全跌破 ZD
                if cur_dir == "up" and b.type == "down" and b.high < last_zs.zd:
                    reverse_3rd = b
                    break
                # 下跌走势后的三买：上涨笔完全升破 ZG
                elif cur_dir == "down" and b.type == "up" and b.low > last_zs.zg:
                    reverse_3rd = b
                    break

            if entry_bi:
                start_time = entry_bi.start.k.date
                start_price = entry_bi.start.val
            else:
                start_time = first_zs.start.k.date
                start_price = first_zs.start.val

            if reverse_3rd:
                end_time = reverse_3rd.end.k.date
                # 终点是走势的最高/最低点（取整个走势的极值）
                trend_vals = []
                for z in group:
                    for l in z.lines:
                        if isinstance(l, BI):
                            trend_vals.append(l.high if cur_dir == "up" else l.low)
                if entry_bi:
                    trend_vals.append(entry_bi.high if cur_dir == "up" else entry_bi.low)
                if exit_bi:
                    trend_vals.append(exit_bi.high if cur_dir == "up" else exit_bi.low)
                end_price = max(trend_vals) if cur_dir == "up" else min(trend_vals)
            elif exit_bi:
                end_time = exit_bi.end.k.date
                end_price = exit_bi.end.val
            else:
                end_time = last_zs.end.k.date
                all_prices = []
                for z in group:
                    if z.gg and z.dd:
                        all_prices.extend([z.gg, z.dd])
                if all_prices:
                    end_price = max(all_prices) if cur_dir == "up" else min(all_prices)
                else:
                    end_price = last_zs.end.val if last_zs.end else 0

            # 走势类型名称（a->A，b->B，c...）
            name_parts = []
            for zi, z in enumerate(group):
                z_name = getattr(z, "name", chr(65 + zi))
                name_parts.append(z_name)
            zs_names = "→".join(name_parts)

            infos.append({
                "trend_type": trend_text,
                "direction": cur_dir,
                "zs_count": len(group),
                "zs_names": zs_names,
                "start_time": start_time,
                "start_price": start_price,
                "end_time": end_time,
                "end_price": end_price,
                "start_index": first_zs.index,
                "end_index": last_zs.index,
            })

            i = j

        self._trend_infos = infos

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
        return _build_bi_zss(bis_only, config=None)

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
CL = CD

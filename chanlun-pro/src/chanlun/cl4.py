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

def _build_zss_from_bis(bis: List[BI], zs_type: str = "bi") -> List[ZS]:
    """
    从笔列表构建笔中枢列表
    标准中枢定义：至少 3 笔有连续重叠区间
    """
    if len(bis) < 3:
        return []

    zss: List[ZS] = []
    zs_idx = 0

    i = 0
    while i < len(bis) - 2:
        h1, l1 = bis[i].high, bis[i].low
        h2, l2 = bis[i + 1].high, bis[i + 1].low
        h3, l3 = bis[i + 2].high, bis[i + 2].low

        zg = min(h1, h2, h3)
        zd = max(l1, l2, l3)

        if zg > zd:
            zs_lines = [bis[i], bis[i + 1], bis[i + 2]]
            j = i + 3
            while j < len(bis):
                bh, bl = bis[j].high, bis[j].low
                new_zg = min(zg, bh)
                new_zd = max(zd, bl)
                if new_zg >= new_zd:
                    zs_lines.append(bis[j])
                    zg, zd = new_zg, new_zd
                    j += 1
                else:
                    break

            gg = max(l.high for l in zs_lines)
            dd = min(l.low for l in zs_lines)
            zs_direction = "up" if zs_lines[0].type == "up" else "down"

            zss.append(ZS(
                zs_type=zs_type,
                start=zs_lines[0].start,
                end=zs_lines[-1].end,
                zg=zg, zd=zd, gg=gg, dd=dd,
                _type=zs_direction,
                index=zs_idx,
                line_num=len(zs_lines),
            ))
            zs_idx += 1
            i = j
        else:
            i += 1

    return zss


# ═══════════════════════════════════════════════════════════════════════
# 核心适配类
# ═══════════════════════════════════════════════════════════════════════

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
        self._bi_zss = _build_zss_from_bis(self._bis)

    def _run_czsc_bars(self, raw_bars: List[RawBar]) -> bool:
        """
        Function 1: 接收 raw_bars，跑 CZSC，输出 BIs / FX / CLKlines。
        返回 True 表示成功产出 BIs，False 表示数据不足。
        """
        if len(raw_bars) < 10:
            return False

        czsc_obj = _CZSC(raw_bars, max_bi_num=50)
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
                    # 连续下：第二笔终点更低则舍掉
                    if b.end.val <= prev.end.val:
                        continue
                elif prev.type == "up" and b.type == "up":
                    # 连续上：第二笔终点更高则舍掉
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
                    # 不足5根，删除下两笔，当前笔终点连到后2笔起点
                    b.end = self._bis[idx + 2].start
                    # 重新计算笔的高低点
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
                    skip = 2  # 跳过下两笔
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
        return _build_zss_from_bis(bis_only, zs_type)

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

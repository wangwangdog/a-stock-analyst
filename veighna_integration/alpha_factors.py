"""
Alpha158 + Alpha101 因子 → a-stock-analyst 选股 pipeline

从 chanlun_klines.sqlite 读取 stock_daily，用 pandas 计算因子，
输出因子表供 AI 选股和 ML 模型使用。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

DB_PATH = Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")


# ══════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════

def _ts_delay(s: pd.Series, n: int) -> pd.Series:
    return s.shift(n)

def _ts_delta(s: pd.Series, n: int) -> pd.Series:
    return s - s.shift(n)

def _ts_mean(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()

def _ts_std(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).std()

def _ts_max(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).max()

def _ts_min(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).min()

def _ts_sum(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).sum()

def _ts_corr(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    return a.rolling(n).corr(b)

def _ts_rank(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).apply(lambda x: (x.rank().iloc[-1] - 1) / (len(x) - 1) if len(x) > 1 else 0.5, raw=False)

def _ts_quantile(s: pd.Series, n: int, q: float) -> pd.Series:
    return s.rolling(n).quantile(q)

def _ts_slope(s: pd.Series, n: int) -> pd.Series:
    """滚动线性回归斜率"""
    def _slope(x):
        if len(x) < 2:
            return np.nan
        y = x.values if hasattr(x, 'values') else np.array(x)
        t = np.arange(len(y))
        return np.polyfit(t, y, 1)[0]
    return s.rolling(n).apply(_slope, raw=False)

def _ts_rsquare(s: pd.Series, n: int) -> pd.Series:
    """滚动 R²"""
    def _r2(x):
        if len(x) < 2:
            return np.nan
        y = x.values if hasattr(x, 'values') else np.array(x)
        t = np.arange(len(y))
        slope, intercept = np.polyfit(t, y, 1)
        y_pred = slope * t + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = np.sum((y - np.mean(y)) ** 2)
        return 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return s.rolling(n).apply(_r2, raw=False)

def _ts_argmax(s: pd.Series, n: int) -> pd.Series:
    def _amax(x):
        if len(x) == 0:
            return np.nan
        return len(x) - 1 - np.argmax(x)
    return s.rolling(n).apply(_amax, raw=False)

def _ts_argmin(s: pd.Series, n: int) -> pd.Series:
    def _amin(x):
        if len(x) == 0:
            return np.nan
        return len(x) - 1 - np.argmin(x)
    return s.rolling(n).apply(_amin, raw=False)


# ══════════════════════════════════════════════
# Alpha158 因子计算（pandas 实现）
# ══════════════════════════════════════════════

def compute_alpha158(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算 Alpha158 因子集。

    Args:
        df: DataFrame，必须包含列 close, open, high, low, volume
            MultiIndex: (symbol, date) 或普通 index

    Returns:
        添加了 158 个因子列的 DataFrame
    """
    df = df.copy()

    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    vwap = (h + l + c) / 3  # 伪 VWAP

    # ── K线形态 ──
    df["kmid"] = (c - o) / o
    df["klen"] = (h - l) / o
    df["kmid_2"] = (c - o) / (h - l + 1e-12)
    df["kup"] = (h - np.maximum(o, c)) / o
    df["kup_2"] = (h - np.maximum(o, c)) / (h - l + 1e-12)
    df["klow"] = (np.minimum(o, c) - l) / o
    df["klow_2"] = (np.minimum(o, c) - l) / (h - l + 1e-12)
    df["ksft"] = (c * 2 - h - l) / o
    df["ksft_2"] = (c * 2 - h - l) / (h - l + 1e-12)

    for field in ["open", "high", "low"]:
        df[f"{field}_0"] = df[field] / c
    df["vwap_0"] = vwap / c

    windows = [5, 10, 20, 30, 60]

    for w in windows:
        # 收益率
        df[f"roc_{w}"] = _ts_delay(c, w) / c
        # 均线归一化
        df[f"ma_{w}"] = _ts_mean(c, w) / c
        # 波动率
        df[f"std_{w}"] = _ts_std(c, w) / c
        # Beta (斜率)
        df[f"beta_{w}"] = _ts_slope(c, w) / c
        # R²
        df[f"rsqr_{w}"] = _ts_rsquare(c, w)
        # 残差波动
        df[f"resi_{w}"] = (c - _ts_mean(c, w)) / c

        # 极值
        df[f"max_{w}"] = _ts_max(h, w) / c
        df[f"min_{w}"] = _ts_min(l, w) / c
        df[f"qtlu_{w}"] = _ts_quantile(c, w, 0.8) / c
        df[f"qtld_{w}"] = _ts_quantile(c, w, 0.2) / c

        # Rank
        df[f"rank_{w}"] = _ts_rank(c, w)

        # RSV
        min_low = _ts_min(l, w)
        max_high = _ts_max(h, w)
        df[f"rsv_{w}"] = (c - min_low) / (max_high - min_low + 1e-12)

        # ArgMax/ArgMin
        df[f"imax_{w}"] = _ts_argmax(h, w) / w
        df[f"imin_{w}"] = _ts_argmin(l, w) / w
        df[f"imxd_{w}"] = (_ts_argmax(h, w) - _ts_argmin(l, w)) / w

        # 量价相关
        log_v = np.log(v + 1)
        df[f"corr_{w}"] = _ts_corr(c, log_v, w)
        ret_1d = c / _ts_delay(c, 1) - 1
        vol_chg = v / (_ts_delay(v, 1) + 1e-12) - 1
        df[f"cord_{w}"] = _ts_corr(ret_1d, vol_chg, w)

        # 上涨/下跌天数占比
        df[f"cntp_{w}"] = _ts_mean((c > _ts_delay(c, 1)).astype(float), w)
        df[f"cntn_{w}"] = _ts_mean((c < _ts_delay(c, 1)).astype(float), w)
        df[f"cntd_{w}"] = df[f"cntp_{w}"] - df[f"cntn_{w}"]

        # 涨跌幅 sum
        pos_ret = np.maximum(c - _ts_delay(c, 1), 0)
        neg_ret = np.maximum(_ts_delay(c, 1) - c, 0)
        abs_ret = np.abs(c - _ts_delay(c, 1))
        df[f"sump_{w}"] = _ts_sum(pos_ret, w) / (_ts_sum(abs_ret, w) + 1e-12)
        df[f"sumn_{w}"] = _ts_sum(neg_ret, w) / (_ts_sum(abs_ret, w) + 1e-12)
        df[f"sumd_{w}"] = (_ts_sum(pos_ret, w) - _ts_sum(neg_ret, w)) / (_ts_sum(abs_ret, w) + 1e-12)

        # 成交量因子
        df[f"vma_{w}"] = _ts_mean(v, w) / (v + 1e-12)
        df[f"vstd_{w}"] = _ts_std(v, w) / (v + 1e-12)

        # 加权波动
        abs_ret_vol = np.abs(ret_1d) * v
        df[f"wvma_{w}"] = _ts_std(abs_ret_vol, w) / (_ts_mean(abs_ret_vol, w) + 1e-12)

        # 成交量 sum
        pos_vol = np.maximum(v - _ts_delay(v, 1), 0)
        neg_vol = np.maximum(_ts_delay(v, 1) - v, 0)
        abs_vol = np.abs(v - _ts_delay(v, 1))
        df[f"vsump_{w}"] = _ts_sum(pos_vol, w) / (_ts_sum(abs_vol, w) + 1e-12)
        df[f"vsumn_{w}"] = _ts_sum(neg_vol, w) / (_ts_sum(abs_vol, w) + 1e-12)
        df[f"vsumd_{w}"] = (_ts_sum(pos_vol, w) - _ts_sum(neg_vol, w)) / (_ts_sum(abs_vol, w) + 1e-12)

    return df


# ══════════════════════════════════════════════
# Alpha101 因子计算（pandas 实现，精选前20个）
# ══════════════════════════════════════════════

def compute_alpha101(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算 Alpha101 精选因子（前20个 + alpha101）。
    完整101个因子在 VeighNa 中实现，这里提供关键子集。
    """
    df = df.copy()
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    vwap = (h + l + c) / 3
    returns = c / _ts_delay(c, 1) - 1

    # 截面排名（按日分组）
    def _cs_rank(s: pd.Series) -> pd.Series:
        return s.groupby(level="date" if isinstance(s.index, pd.MultiIndex) else s.index).rank(pct=True)

    # Alpha1: 收益反转
    df["alpha001"] = -1 * _ts_corr(_cs_rank(_ts_delta(np.log(v + 1e-12), 2)), _cs_rank((c - o) / o), 6)

    # Alpha2: 开盘量相关
    df["alpha002"] = -1 * _ts_corr(_cs_rank(o), _cs_rank(v), 10)

    # Alpha3: 最低价反轉
    df["alpha003"] = -1 * _ts_rank(_cs_rank(l), 9)

    # Alpha4: 开盘量相关(短)
    df["alpha004"] = -1 * _ts_corr(o, v, 10)

    # Alpha5: VWAP-Close 差
    df["alpha005"] = _cs_rank((o - (_ts_sum(vwap, 10) / 10))) * (-1 * np.abs(_cs_rank((c - vwap))))

    # Alpha6: 量价相关(长)
    df["alpha006"] = -1 * _ts_corr(o, v, 10)

    # Alpha11: VWAP偏离+量变化
    df["alpha011"] = (_cs_rank(_ts_max(vwap - c, 3)) + _cs_rank(_ts_min(vwap - c, 3))) * _cs_rank(_ts_delta(v, 3))

    # Alpha12: 量增价跌
    df["alpha012"] = np.sign(_ts_delta(v, 1)) * (-1 * _ts_delta(c, 1))

    # Alpha20: 开盘区间突破
    df["alpha020"] = (-1 * _cs_rank(o - _ts_delay(h, 1))) * _cs_rank(o - _ts_delay(c, 1)) * _cs_rank(o - _ts_delay(l, 1))

    # Alpha25: 收益*量*VWAP
    df["alpha025"] = _cs_rank((-1 * returns) * _ts_mean(v, 20) * vwap * (h - c))

    # Alpha33: 开盘反转
    df["alpha033"] = _cs_rank((-1) * (o / c * -1 + 1))

    # Alpha38: Close Rank * Close/Open
    df["alpha038"] = (-1 * _cs_rank(_ts_rank(c, 10))) * _cs_rank((c / o))

    # Alpha41: 几何均值-VWAP
    df["alpha041"] = np.power((h * l), 0.5) - vwap

    # Alpha42: VWAP偏离比率
    rank_v_c = _cs_rank((vwap - c))
    rank_v_p_c = _cs_rank((vwap + c))
    df["alpha042"] = rank_v_c / (rank_v_p_c + 1e-12)

    # Alpha44: 高价量负相关
    df["alpha044"] = (-1) * _ts_corr(h, _cs_rank(v), 5)

    # Alpha53: 阴阳转换
    df["alpha053"] = (-1) * _ts_delta(((c - l) - (h - c)) / (c - l + 1e-12), 9)

    # Alpha54: 低开反转
    df["alpha054"] = ((-1) * ((l - c) * np.power(o, 5))) / ((l - h) * np.power(c, 5) + 1e-12)

    # Alpha55: RSV量相关
    rsv_12 = (c - _ts_min(l, 12)) / (_ts_max(h, 12) - _ts_min(l, 12) + 1e-12)
    df["alpha055"] = (-1) * _ts_corr(_cs_rank(rsv_12), _cs_rank(v), 6)

    # Alpha57: VWAP偏离衰减
    df["alpha057"] = -1 * ((c - vwap) / (_ts_sum(_cs_rank(_ts_argmax(c, 30)), 2) + 1e-12))

    # Alpha101: 收盘强度
    df["alpha101"] = ((c - o) / ((h - l) + 0.001))

    return df


# ══════════════════════════════════════════════
# 数据加载 + 因子计算 Pipeline
# ══════════════════════════════════════════════

def load_stock_daily(symbols: Optional[list[str]] = None, days: int = 500) -> pd.DataFrame:
    """从 kline_cache 加载日线数据为 MultiIndex DataFrame（stock_daily 已合并）"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        if symbols:
            placeholders = ",".join(["?"] * len(symbols))
            sql = f"""
                SELECT symbol, trade_date AS date, open, high, low, close, volume, amount AS turnover
                FROM kline_cache
                WHERE symbol IN ({placeholders})
                  AND source='stock_daily' AND period='daily'
                  AND trade_date >= date('now', '-{days} days')
                ORDER BY symbol, trade_date
            """
            df = pd.read_sql(sql, conn, params=symbols)
        else:
            sql = f"""
                SELECT symbol, trade_date AS date, open, high, low, close, volume, amount AS turnover
                FROM kline_cache
                WHERE source='stock_daily' AND period='daily'
                  AND trade_date >= date('now', '-{days} days')
                ORDER BY symbol, trade_date
            """
            df = pd.read_sql(sql, conn)

        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index(["symbol", "date"]).sort_index()

        # 重命名兼容
        df = df.rename(columns={"turnover": "amount"})
        df["amount"] = df["amount"].fillna(0)

        return df
    finally:
        conn.close()


def compute_factors_pipeline(
    symbols: Optional[list[str]] = None,
    days: int = 500,
    include_alpha158: bool = True,
    include_alpha101: bool = True,
) -> pd.DataFrame:
    """
    因子计算 Pipeline。

    Args:
        symbols: 股票列表，None = 全市场
        days: 回溯天数
        include_alpha158: 是否计算 Alpha158
        include_alpha101: 是否计算 Alpha101

    Returns:
        MultiIndex (symbol, date) DataFrame，包含原始数据和因子
    """
    df = load_stock_daily(symbols, days)

    if include_alpha158:
        # 按 symbol 分组计算（避免跨标的滚动）
        result_parts = []
        for sym, group in df.groupby(level="symbol"):
            group = group.reset_index(level="symbol", drop=True)
            group = compute_alpha158(group)
            group["symbol"] = sym
            group = group.set_index("symbol", append=True).swaplevel()
            result_parts.append(group)
        df = pd.concat(result_parts).sort_index()

    if include_alpha101:
        df = compute_alpha101(df)

    return df


def get_latest_factors(symbols: list[str], days: int = 500) -> pd.DataFrame:
    """获取最新一期的因子值（用于选股）"""
    factor_df = compute_factors_pipeline(symbols, days)
    # 每只股票取最新日期
    latest = factor_df.groupby(level="symbol").tail(1)
    latest = latest.reset_index(level="date")
    return latest


# ══════════════════════════════════════════════
# CLI 快捷入口
# ══════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    symbols = sys.argv[1:] if len(sys.argv) > 1 else None

    print(f"计算因子: symbols={symbols or '全市场'}")
    df = compute_factors_pipeline(symbols, days=250)

    factor_cols = [c for c in df.columns if c.startswith(("kmid", "klen", "alpha", "ma_", "std_", "roc_", "rsv_", "corr_"))]
    print(f"因子列数: {len(factor_cols)}")
    print(f"数据形状: {df.shape}")
    print(f"最新因子:\n{df.tail(5).to_string()}")

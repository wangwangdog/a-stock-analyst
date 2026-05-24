"""
Sequoia-X 6大策略 → VeighNa 事件驱动版本

每个策略是纯函数：接收当根 Bar + 历史 Bar 列表 + 上下文，返回信号。
1=buy, -1=sell, 0=nothing
"""
from __future__ import annotations
import numpy as np
from vnpy.trader.object import BarData


# ══════════════════════════════════════════════
# 1. 均线放量策略
# ══════════════════════════════════════════════

def ma_volume(bar: BarData, history: list[BarData], ctx: dict) -> int:
    """5日线上穿20日线 + 放量1.5倍"""
    if len(history) < 20:
        return 0

    closes = [b.close_price for b in history[-20:]] + [bar.close_price]
    volumes = [b.volume for b in history[-20:]] + [bar.volume]
    ma5_now = np.mean(closes[-5:])
    ma20_now = np.mean(closes[-20:])
    ma5_prev = np.mean(closes[-6:-1])
    ma20_prev = np.mean(closes[-21:-1])

    golden_cross = ma5_prev < ma20_prev and ma5_now > ma20_now
    vol_ma20 = np.mean(volumes[-21:-1])
    volume_surge = bar.volume > vol_ma20 * 1.5

    if golden_cross and volume_surge:
        return 1

    # 出场：死叉（5日下穿20日）
    if ma5_prev > ma20_prev and ma5_now < ma20_now:
        return -1

    return 0


# ══════════════════════════════════════════════
# 2. 海龟交易策略
# ══════════════════════════════════════════════

def turtle_trade(bar: BarData, history: list[BarData], ctx: dict) -> int:
    """20日新高突破 + 成交额过亿 + 阳线防诱多"""
    if len(history) < 21:
        return 0

    highs = [b.high_price for b in history[-20:]]
    high_20 = max(highs)
    prev = history[-1]

    breakout = bar.close_price > high_20
    liquid = bar.turnover > 100_000_000
    is_yang = bar.close_price > bar.open_price
    is_up = bar.close_price > prev.close_price

    if breakout and liquid and is_yang and is_up:
        return 1

    # 出场：跌破10日低点
    if ctx.get("shares", 0) > 0:
        low_10 = min(b.low_price for b in history[-10:])
        if bar.close_price < low_10:
            return -1

    return 0


# ══════════════════════════════════════════════
# 3. 高窄旗形策略
# ══════════════════════════════════════════════

def high_tight_flag(bar: BarData, history: list[BarData], ctx: dict) -> int:
    """40天强动量 + 10天极度收敛 + 缩量"""
    if len(history) < 40:
        return 0

    # 40天动量
    highs40 = [b.high_price for b in history[-40:]]
    lows40 = [b.low_price for b in history[-40:]]
    high40 = max(highs40)
    low40 = min(lows40)

    # 10天收敛
    highs10 = [b.high_price for b in history[-10:]]
    lows10 = [b.low_price for b in history[-10:]]
    high10 = max(highs10)
    low10 = min(lows10)

    if low40 == 0 or low10 == 0:
        return 0

    momentum = high40 / low40 > 1.6
    consolidation = high10 / low10 < 1.15
    high_level = low10 >= high40 * 0.8

    volumes = [b.volume for b in history[-21:-1]]
    vol_ma20 = np.mean(volumes) if volumes else 0
    shrink = bar.volume < vol_ma20 * 0.6

    if momentum and consolidation and high_level and shrink:
        return 1

    # 出场：跌破旗形整理最低点
    if ctx.get("shares", 0) > 0:
        if bar.close_price < low10:
            return -1

    return 0


# ══════════════════════════════════════════════
# 4. 涨停洗盘策略
# ══════════════════════════════════════════════

def limit_up_shakeout(bar: BarData, history: list[BarData], ctx: dict) -> int:
    """昨日涨停 + 今日放量收阴但不破昨收"""
    if len(history) < 2:
        return 0

    prev2 = history[-2]   # 前日
    prev1 = history[-1]   # 昨日

    limit_up_yesterday = prev1.close_price >= prev2.close_price * 1.095
    bearish_today = bar.close_price < bar.open_price
    volume_surge = bar.volume > prev1.volume * 2.0
    support_hold = bar.low_price >= prev1.close_price

    if limit_up_yesterday and bearish_today and volume_surge and support_hold:
        return 1  # 买入：洗盘后入场

    # 出场：跌破昨日最低
    if ctx.get("shares", 0) > 0:
        if bar.close_price < prev1.low_price:
            return -1

    return 0


# ══════════════════════════════════════════════
# 5. 跌停反包策略
# ══════════════════════════════════════════════

def uptrend_limit_down(bar: BarData, history: list[BarData], ctx: dict) -> int:
    """上升趋势中放量跌停，捕捉错杀反包"""
    if len(history) < 60:
        return 0

    closes = [b.close_price for b in history[-60:]]
    volumes = [b.volume for b in history[-60:]]
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:])

    prev = history[-1]
    uptrend = ma20 > ma60
    limit_down = bar.close_price <= prev.close_price * 0.905
    vol_ma20 = np.mean(volumes[-20:])
    volume_surge = bar.volume > vol_ma20 * 2.0

    if uptrend and limit_down and volume_surge:
        return 1  # 买入：跌停错杀

    # 出场：止损5% 或 止盈10%
    if ctx.get("shares", 0) > 0:
        entry_price = ctx.get("entry_price", 0)
        if entry_price > 0:
            pnl_pct = (bar.close_price - entry_price) / entry_price
            if pnl_pct < -0.05 or pnl_pct > 0.10:
                return -1

    return 0


# ══════════════════════════════════════════════
# 6. RPS突破策略
# ══════════════════════════════════════════════

def rps_breakout(bar: BarData, history: list[BarData], ctx: dict) -> int:
    """120日RPS > 90 + 接近120日高点"""
    if len(history) < 120:
        return 0

    close_120d_ago = history[-120].close_price
    if close_120d_ago == 0:
        return 0

    pct_change = (bar.close_price - close_120d_ago) / close_120d_ago
    # RPS 需要横向对比，这里简化为涨幅阈值
    rps_strong = pct_change > 0.50  # 120日涨超50%视为RPS>90

    highs = [b.high_price for b in history[-120:]]
    roll_high = max(highs)
    near_high = bar.close_price >= roll_high * 0.90

    if rps_strong and near_high:
        return 1

    # 出场：跌破20日低点
    if ctx.get("shares", 0) > 0:
        low_20 = min(b.low_price for b in history[-20:])
        if bar.close_price < low_20:
            return -1

    return 0


# ══════════════════════════════════════════════
# 策略注册表
# ══════════════════════════════════════════════

STRATEGIES = {
    "ma_volume":          ("均线放量", ma_volume),
    "turtle_trade":       ("海龟交易", turtle_trade),
    "high_tight_flag":    ("高窄旗形", high_tight_flag),
    "limit_up_shakeout":  ("涨停洗盘", limit_up_shakeout),
    "uptrend_limit_down": ("跌停反包", uptrend_limit_down),
    "rps_breakout":       ("RPS突破", rps_breakout),
}

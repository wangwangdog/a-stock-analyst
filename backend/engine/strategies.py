"""
A-Stock 回测策略库

支持策略：
- MaCross: 双均线交叉
- Turtle: 海龟交易法则
- MacdSignal: MACD 金叉死叉
- BollBreak: 布林带突破
- RsiMean: RSI 均值回归
- VolBreak: 量价突破
"""
from dataclasses import dataclass
from typing import ClassVar
import numpy as np


@dataclass
class Strategy:
    """策略基类"""
    name: ClassVar[str] = "Base"

    def generate(self, bars: list) -> list[int]:
        """生成信号: 1=做多, -1=做空, 0=无信号"""
        return [0] * len(bars)


@dataclass
class MaCrossStrategy(Strategy):
    """双均线交叉策略

    金叉做多，死叉做空
    """
    name: ClassVar[str] = "双均线交叉"
    fast: int = 5
    slow: int = 20

    def generate(self, bars):
        closes = np.array([b.close for b in bars])
        if len(closes) < self.slow + 1:
            return [0] * len(bars)

        ma_fast = np.convolve(closes, np.ones(self.fast) / self.fast, mode='valid')
        ma_slow = np.convolve(closes, np.ones(self.slow) / self.slow, mode='valid')
        offset = self.slow - self.fast

        signals = [0] * self.slow
        for i in range(len(ma_slow) - 1):
            idx = i + self.slow
            f_curr = ma_fast[i + offset]
            s_curr = ma_slow[i]
            f_prev = ma_fast[i + offset - 1] if i + offset > 0 else f_curr
            s_prev = ma_slow[i - 1] if i > 0 else s_curr

            if f_prev <= s_prev and f_curr > s_curr:
                signals.append(1)   # 金叉做多
            elif f_prev >= s_prev and f_curr < s_curr:
                signals.append(-1)  # 死叉做空
            else:
                signals.append(0)
        return signals


@dataclass
class TurtleStrategy(Strategy):
    """海龟交易法则

    突破N日高点做多，跌破N日低点做空。
    加ATR止损。
    """
    name: ClassVar[str] = "海龟交易"
    entry_period: int = 20
    exit_period: int = 10

    def generate(self, bars):
        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        n = len(bars)

        signals = [0] * n
        position = 0  # 0=空仓, 1=持多

        for i in range(self.entry_period, n):
            hh = max(highs[i - self.entry_period:i])
            ll = min(lows[i - self.entry_period:i])

            if position == 0:
                if closes[i] > hh:
                    signals[i] = 1
                    position = 1
                elif closes[i] < ll:
                    signals[i] = -1
            else:
                # 出场：跌破 exit_period 低点
                exit_ll = min(lows[max(0, i - self.exit_period):i])
                if closes[i] < exit_ll:
                    signals[i] = -1 if position == 1 else 1
                    position = 0
        return signals


@dataclass
class MacdSignalStrategy(Strategy):
    """MACD 金叉死叉策略"""
    name: ClassVar[str] = "MACD信号"
    fast: int = 12
    slow: int = 26
    signal: int = 9

    def _ema(self, data, period):
        result = np.zeros_like(data)
        result[0] = data[0]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]
        return result

    def generate(self, bars):
        closes = np.array([b.close for b in bars])
        n = len(closes)
        if n < self.slow + self.signal:
            return [0] * n

        ema_fast = self._ema(closes, self.fast)
        ema_slow = self._ema(closes, self.slow)
        dif = ema_fast - ema_slow
        dea = self._ema(dif, self.signal)
        macd = 2 * (dif - dea)

        signals = [0] * n
        for i in range(self.slow + self.signal, n):
            if dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
                signals[i] = 1    # 金叉
            elif dif[i-1] >= dea[i-1] and dif[i] < dea[i]:
                signals[i] = -1   # 死叉
        return signals


@dataclass
class BollBreakStrategy(Strategy):
    """布林带突破策略

    价格突破上轨做多，跌破下轨做空
    """
    name: ClassVar[str] = "布林突破"
    period: int = 20
    std_mult: float = 2.0

    def generate(self, bars):
        closes = np.array([b.close for b in bars])
        n = len(closes)
        if n < self.period + 1:
            return [0] * n

        signals = [0] * n
        for i in range(self.period, n):
            window = closes[i - self.period:i]
            ma = np.mean(window)
            std = np.std(window)
            upper = ma + self.std_mult * std
            lower = ma - self.std_mult * std

            if closes[i] > upper and closes[i-1] <= upper:
                signals[i] = 1
            elif closes[i] < lower and closes[i-1] >= lower:
                signals[i] = -1
        return signals


@dataclass
class RsiMeanStrategy(Strategy):
    """RSI 均值回归策略

    RSI超卖做多，超买做空
    """
    name: ClassVar[str] = "RSI回归"
    period: int = 14
    oversold: int = 30
    overbought: int = 70

    def generate(self, bars):
        closes = np.array([b.close for b in bars])
        n = len(closes)
        if n < self.period + 1:
            return [0] * n

        # 计算 RSI
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.zeros(n)
        avg_loss = np.zeros(n)
        avg_gain[self.period] = np.mean(gains[:self.period])
        avg_loss[self.period] = np.mean(losses[:self.period])

        for i in range(self.period + 1, n):
            avg_gain[i] = (avg_gain[i-1] * (self.period - 1) + gains[i-1]) / self.period
            avg_loss[i] = (avg_loss[i-1] * (self.period - 1) + losses[i-1]) / self.period

        rsi = np.zeros(n)
        for i in range(self.period, n):
            if avg_loss[i] == 0:
                rsi[i] = 100
            else:
                rsi[i] = 100 - (100 / (1 + avg_gain[i] / avg_loss[i]))

        signals = [0] * n
        for i in range(self.period + 1, n):
            if rsi[i-1] < self.oversold and rsi[i] >= self.oversold:
                signals[i] = 1    # 超卖反弹
            elif rsi[i-1] > self.overbought and rsi[i] <= self.overbought:
                signals[i] = -1   # 超买回落
        return signals


@dataclass
class VolBreakStrategy(Strategy):
    """量价突破策略

    放量+突破N日高点做多，缩量+跌破N日低点做空
    """
    name: ClassVar[str] = "量价突破"
    period: int = 20
    vol_mult: float = 1.5

    def generate(self, bars):
        closes = np.array([b.close for b in bars])
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        volumes = np.array([b.volume for b in bars])
        n = len(bars)

        signals = [0] * n
        for i in range(self.period, n):
            hh = max(highs[i - self.period:i])
            ll = min(lows[i - self.period:i])
            avg_vol = np.mean(volumes[i - self.period:i])

            if closes[i] > hh and volumes[i] > avg_vol * self.vol_mult:
                signals[i] = 1
            elif closes[i] < ll and volumes[i] > avg_vol * self.vol_mult:
                signals[i] = -1
        return signals


# ─── 策略注册表 ───
STRATEGIES = {
    "ma_cross": MaCrossStrategy,
    "turtle": TurtleStrategy,
    "macd": MacdSignalStrategy,
    "boll": BollBreakStrategy,
    "rsi": RsiMeanStrategy,
    "vol_break": VolBreakStrategy,
}

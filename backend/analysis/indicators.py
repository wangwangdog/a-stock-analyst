"""技术指标计算"""
import numpy as np
import pandas as pd


def calc_ma(df: pd.DataFrame, periods: list = [5, 10, 20, 60]) -> dict:
    """计算 MA 均线"""
    result = {}
    for p in periods:
        if "close" in df.columns:
            result[f"MA{p}"] = df["close"].rolling(window=p).mean().round(2).tolist()
        else:
            result[f"MA{p}"] = []
    return result


def calc_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> dict:
    """计算 MACD"""
    if "close" not in df.columns or len(df) < slow:
        return {"DIF": [], "DEA": [], "MACD": []}

    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = 2 * (dif - dea)

    return {
        "DIF": dif.round(4).tolist(),
        "DEA": dea.round(4).tolist(),
        "MACD": macd.round(4).tolist(),
    }


def calc_rsi(df: pd.DataFrame, periods: list = [6, 12, 24]) -> dict:
    """计算 RSI，支持多个周期"""
    if "close" not in df.columns or len(df) < min(periods) + 1:
        return {f"RSI{p}": [] for p in periods}

    close = df["close"]
    delta = close.diff()

    result = {}
    for period in periods:
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        result[f"RSI{period}"] = rsi.round(2).tolist()

    return result


def calc_bollinger(df: pd.DataFrame, period=20, std_dev=2) -> dict:
    """计算布林带"""
    if "close" not in df.columns or len(df) < period:
        return {"BOLL_UP": [], "BOLL_MID": [], "BOLL_DN": []}

    mid = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std

    return {
        "BOLL_UP": upper.round(2).tolist(),
        "BOLL_MID": mid.round(2).tolist(),
        "BOLL_DN": lower.round(2).tolist(),
    }


def calc_kdj(df: pd.DataFrame, period=9) -> dict:
    """计算 KDJ"""
    if "high" not in df.columns or "low" not in df.columns or "close" not in df.columns:
        return {"K": [], "D": [], "J": []}

    low = df["low"].rolling(window=period).min()
    high = df["high"].rolling(window=period).max()
    rsv = ((df["close"] - low) / (high - low).replace(0, np.nan)) * 100

    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d

    return {
        "K": k.round(2).tolist(),
        "D": d.round(2).tolist(),
        "J": j.round(2).tolist(),
    }


def calc_all_indicators(df: pd.DataFrame, ma_periods: list = None) -> dict:
    """计算所有常用技术指标"""
    return {
        "ma": calc_ma(df, periods=ma_periods if ma_periods else [5, 10, 20, 60]),
        "macd": calc_macd(df),
        "rsi": calc_rsi(df),
        "bollinger": calc_bollinger(df),
        "kdj": calc_kdj(df),
    }

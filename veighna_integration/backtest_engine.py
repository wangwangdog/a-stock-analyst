"""
Sequoia-X → VeighNa 轻量回测引擎

基于 vnpy_chanlun 适配器 + BarData 事件流，逐日模拟交易。
支持多策略并行回测，输出收益曲线、夏普比、最大回撤。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

# ── 确保 vnpy 和 vnpy_chanlun 在 path 中 ──
sys.path.insert(0, "/home/dogzi/.openclaw/workspace/veighna")
sys.path.insert(0, "/home/dogzi/.openclaw/workspace/chanlun-pro")

from vnpy.trader.constant import Exchange, Interval, Direction, Offset
from vnpy.trader.object import BarData, TradeData, OrderData
from vnpy_chanlun import Database, _symbol_to_exchange


# ══════════════════════════════════════════════
# 数据结构
# ══════════════════════════════════════════════

@dataclass
class DailyResult:
    date: str
    nav: float = 1.0
    cash: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    trades: list[dict] = field(default_factory=list)


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    start: str
    end: str
    initial_capital: float
    final_nav: float
    total_return: float
    annual_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    daily_results: list[DailyResult] = field(default_factory=list)


# ══════════════════════════════════════════════
# 轻量回测引擎
# ══════════════════════════════════════════════

class LightweightBacktestEngine:
    """
    逐日事件驱动回测引擎。

    用法:
        def my_strategy(bar: BarData, history: list[BarData], ctx: dict) -> int:
            # 返回: 1=买入, -1=卖出, 0=无操作
            ...

        engine = LightweightBacktestEngine(capital=100_000)
        result = engine.run("000001", my_strategy, "2024-01-01", "2025-12-31")
    """

    def __init__(self, capital: float = 100_000, commission: float = 0.0003):
        self.capital = capital
        self.commission = commission
        self.db = Database()

    def run(
        self,
        symbol: str,
        strategy_fn: Callable,
        start: str,
        end: str,
        strategy_name: str = "strategy",
    ) -> BacktestResult:
        """运行回测"""
        exchange = _symbol_to_exchange(symbol)
        bars = self.db.load_bar_data(
            symbol, exchange, Interval.DAILY,
            datetime.strptime(start, "%Y-%m-%d"),
            datetime.strptime(end, "%Y-%m-%d"),
        )

        if len(bars) < 20:
            raise ValueError(f"{symbol} 历史数据不足 ({len(bars)} 条)")

        cash = self.capital
        shares = 0
        history: list[BarData] = []  # 滚动窗口
        daily_results: list[DailyResult] = []
        trades: list[dict] = []
        navs: list[float] = []
        wins = 0
        losses = 0
        entry_price = 0.0

        for i, bar in enumerate(bars):
            history.append(bar)
            if len(history) > 120:  # 保留120天历史
                history = history[-120:]

            ctx = {
                "symbol": symbol,
                "date": bar.datetime.strftime("%Y-%m-%d"),
                "cash": cash,
                "shares": shares,
                "trade_count": len(trades),
            }

            signal = strategy_fn(bar, history[:-1], ctx)  # history 不含当日

            # 执行交易
            if signal == 1 and shares == 0 and cash > bar.close_price * 100:
                # 买入
                shares = int(cash * 0.95 / bar.close_price) // 100 * 100
                cost = shares * bar.close_price * (1 + self.commission)
                cash -= cost
                entry_price = bar.close_price
                trades.append({
                    "date": bar.datetime.strftime("%Y-%m-%d"),
                    "action": "BUY",
                    "price": bar.close_price,
                    "shares": shares,
                    "cost": round(cost, 2),
                })

            elif signal == -1 and shares > 0:
                # 卖出
                proceeds = shares * bar.close_price * (1 - self.commission)
                cash += proceeds
                pnl = proceeds - shares * entry_price
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades.append({
                    "date": bar.datetime.strftime("%Y-%m-%d"),
                    "action": "SELL",
                    "price": bar.close_price,
                    "shares": shares,
                    "proceeds": round(proceeds, 2),
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl / (shares * entry_price) * 100, 2),
                })
                shares = 0

            # 日终净值
            nav = cash + shares * bar.close_price
            navs.append(nav / self.capital)

            daily_results.append(DailyResult(
                date=bar.datetime.strftime("%Y-%m-%d"),
                nav=round(nav / self.capital, 4),
                cash=round(cash, 2),
                positions={symbol: shares} if shares else {},
            ))

        # 强制平仓
        if shares > 0:
            last = bars[-1]
            proceeds = shares * last.close_price * (1 - self.commission)
            cash += proceeds

        # ── 计算指标 ──
        final_nav = cash / self.capital
        total_return = (final_nav - 1) * 100
        days = len(navs)
        annual_return = (final_nav ** (240 / days) - 1) * 100 if days > 0 else 0

        nav_arr = np.array(navs)
        daily_returns = np.diff(nav_arr) / nav_arr[:-1]
        sharpe = np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(240) if len(daily_returns) > 0 and np.std(daily_returns) > 0 else 0

        # 最大回撤
        peak = np.maximum.accumulate(nav_arr)
        drawdowns = (nav_arr - peak) / peak
        max_dd = float(np.min(drawdowns) * 100)

        total_trades = wins + losses
        win_rate = wins / total_trades * 100 if total_trades > 0 else 0

        return BacktestResult(
            symbol=symbol,
            strategy=strategy_name,
            start=start,
            end=end,
            initial_capital=self.capital,
            final_nav=round(final_nav, 4),
            total_return=round(total_return, 2),
            annual_return=round(annual_return, 2),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown=round(max_dd, 2),
            win_rate=round(win_rate, 1),
            trade_count=total_trades,
            daily_results=daily_results,
        )

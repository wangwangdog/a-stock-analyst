"""
A-Stock 回测引擎 — 轻量级 CTA 回测

特性：
- 直接读取 chanlun-pro 数据库（无需额外数据源）
- 支持多策略并行回测
- 模拟滑点+手续费
- 输出完整绩效报告

用法：
    engine = BacktestEngine(db_path=DB_PATH)
    engine.set_strategy(MaCrossStrategy, fast=5, slow=20)
    result = engine.run(symbol="000001", start="2023-01-01", end="2024-12-31")
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Any, Callable, Optional, Type

import numpy as np

# ─── 默认数据库路径 ───
DB_PATH = Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite")


# ══════════════════════════════════════════════
#  数据结构
# ══════════════════════════════════════════════

@dataclass
class Bar:
    """K线数据"""
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0


@dataclass
class Trade:
    """成交记录"""
    date: str
    direction: str  # "long" / "short"
    offset: str     # "open" / "close"
    price: float
    volume: int
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class Position:
    """持仓"""
    direction: str = ""  # "long" / "short" / ""
    volume: int = 0
    entry_price: float = 0.0
    entry_date: str = ""


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    strategy_name: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return: float         # 总收益率 (%)
    annual_return: float        # 年化收益率 (%)
    max_drawdown: float         # 最大回撤 (%)
    sharpe_ratio: float         # 夏普比率
    win_rate: float             # 胜率 (%)
    total_trades: int           # 总交易次数
    profit_trades: int          # 盈利次数
    loss_trades: int            # 亏损次数
    avg_profit: float           # 平均盈利 (%)
    avg_loss: float             # 平均亏损 (%)
    profit_factor: float        # 盈亏比
    daily_returns: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)


# ══════════════════════════════════════════════
#  数据加载
# ══════════════════════════════════════════════

def load_bars(symbol: str, start: str, end: str, db_path: Path = DB_PATH) -> list[Bar]:
    """从 chanlun-pro 数据库加载日线数据"""
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 优先从 kline_cache 读取日线
        rows = conn.execute(
            "SELECT trade_date AS date, open, high, low, close, volume, amount "
            "FROM kline_cache WHERE symbol=? AND source='stock_daily' AND period='daily' "
            "AND trade_date>=? AND trade_date<=? "
            "ORDER BY trade_date",
            (symbol, start, end),
        ).fetchall()

        if not rows:
            # 回退到 stock_daily
            rows = conn.execute(
                "SELECT trade_date AS date, open, high, low, close, volume, "
                "COALESCE(amount, 0) AS amount "
                "FROM kline_cache WHERE symbol=? AND period='daily' "
                "AND trade_date>=? AND trade_date<=? ORDER BY trade_date",
                (symbol, start, end),
            ).fetchall()

        return [
            Bar(
                symbol=symbol,
                date=r["date"],
                open=float(r["open"] or 0),
                high=float(r["high"] or 0),
                low=float(r["low"] or 0),
                close=float(r["close"] or 0),
                volume=float(r["volume"] or 0),
                amount=float(r["amount"] or 0),
            )
            for r in rows
        ]
    finally:
        conn.close()


# ══════════════════════════════════════════════
#  回测引擎
# ══════════════════════════════════════════════

class BacktestEngine:
    """轻量级 CTA 回测引擎"""

    def __init__(
        self,
        db_path: Path = DB_PATH,
        initial_capital: float = 100000,
        commission_rate: float = 0.0003,  # 万三
        slippage: float = 0.001,           # 千一
        min_commission: float = 5.0,       # 最低5元
        stamp_duty: float = 0.001,         # 印花税（卖出时）
    ):
        self.db_path = db_path
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.min_commission = min_commission
        self.stamp_duty = stamp_duty

        self.capital = initial_capital
        self.position = Position()
        self.trades: list[Trade] = []
        self.equity: list[float] = []
        self.daily_values: dict[str, float] = {}
        self._bars: list[Bar] = []
        self._strategy = None

    def set_strategy(self, strategy_cls: Type, **params):
        """设置策略"""
        self._strategy = strategy_cls(**params)

    def run(self, symbol: str, start: str, end: str) -> BacktestResult:
        """执行回测"""
        bars = load_bars(symbol, start, end, self.db_path)
        if len(bars) < 50:
            raise ValueError(f"数据不足: 仅 {len(bars)} 根K线")

        self._reset()
        self._bars = bars
        signals = self._strategy.generate(bars)

        for i, bar in enumerate(bars):
            signal = signals[i] if i < len(signals) else 0

            if signal != 0 and self.position.direction == "":
                self._open_position(bar, signal > 0)
            elif (
                (signal <= 0 and self.position.direction == "long")
                or (signal >= 0 and self.position.direction == "short")
            ) and signal != 0:
                self._close_position(bar)

            # 记录每日权益
            value = self.capital
            if self.position.direction == "long":
                value += self.position.volume * bar.close
            self.equity.append(value)
            self.daily_values[bar.date] = value

        # 强平
        if self.position.direction:
            self._close_position(bars[-1])

        return self._build_result(symbol, start, end)

    def _reset(self):
        self.capital = self.initial_capital
        self.position = Position()
        self.trades = []
        self.equity = []
        self.daily_values = {}

    def _open_position(self, bar: Bar, is_long: bool):
        price = bar.close * (1 + self.slippage) if is_long else bar.close * (1 - self.slippage)
        # 全仓买入
        cost_per_lot = price * 100  # A股100股一手
        available = self.capital * 0.95  # 留5%现金
        lots = max(1, int(available / cost_per_lot))
        volume = lots * 100
        cost = cost_per_lot * lots
        commission = max(self.min_commission, cost * self.commission_rate)
        total_cost = cost + commission

        if total_cost > self.capital:
            return

        self.capital -= total_cost
        self.position = Position(
            direction="long" if is_long else "short",
            volume=volume,
            entry_price=price,
            entry_date=bar.date,
        )

    def _close_position(self, bar: Bar):
        if not self.position.direction:
            return

        is_long = self.position.direction == "long"
        price = bar.close * (1 - self.slippage) if not is_long else bar.close * (1 + self.slippage)
        revenue = price * self.position.volume
        commission = max(self.min_commission, revenue * self.commission_rate)
        stamp = revenue * self.stamp_duty if is_long else 0  # A股仅卖出收印花税
        total = revenue - commission - stamp

        pnl = total - (self.position.entry_price * self.position.volume)
        pnl_pct = (pnl / (self.position.entry_price * self.position.volume)) * 100

        trade = Trade(
            date=bar.date,
            direction=self.position.direction,
            offset="close",
            price=price,
            volume=self.position.volume,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )
        self.trades.append(trade)
        self.capital += total
        self.position = Position()

    def _build_result(self, symbol: str, start: str, end: str) -> BacktestResult:
        final_capital = self.equity[-1] if self.equity else self.initial_capital
        total_return = ((final_capital - self.initial_capital) / self.initial_capital) * 100

        # 年化收益
        days = len(self.equity)
        if days > 1 and self.initial_capital > 0:
            annual_return = ((final_capital / self.initial_capital) ** (252 / days) - 1) * 100
        else:
            annual_return = 0

        # 最大回撤
        eq = np.array(self.equity)
        peak = np.maximum.accumulate(eq)
        drawdowns = (eq - peak) / peak * 100
        max_dd = abs(float(np.min(drawdowns)))

        # 日收益
        dates = sorted(self.daily_values.keys())
        daily_returns = []
        prev = self.initial_capital
        for d in dates:
            cur = self.daily_values[d]
            ret = (cur - prev) / prev * 100 if prev > 0 else 0
            daily_returns.append(float(ret))
            prev = cur

        # 夏普比率
        if daily_returns and np.std(daily_returns) > 0:
            sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(252))
        else:
            sharpe = 0.0

        # 胜率
        profit_trades = [t for t in self.trades if t.pnl > 0]
        loss_trades = [t for t in self.trades if t.pnl <= 0]
        win_rate = len(profit_trades) / len(self.trades) * 100 if self.trades else 0

        # 盈亏比
        avg_profit = np.mean([t.pnl_pct for t in profit_trades]) if profit_trades else 0
        avg_loss = abs(np.mean([t.pnl_pct for t in loss_trades])) if loss_trades else 0
        profit_factor = avg_profit / avg_loss if avg_loss > 0 else (999 if avg_profit > 0 else 0)

        return BacktestResult(
            symbol=symbol,
            strategy_name=self._strategy.name if self._strategy else "Unknown",
            start_date=start,
            end_date=end,
            initial_capital=self.initial_capital,
            final_capital=round(final_capital, 2),
            total_return=round(total_return, 2),
            annual_return=round(annual_return, 2),
            max_drawdown=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            win_rate=round(win_rate, 1),
            total_trades=len(self.trades),
            profit_trades=len(profit_trades),
            loss_trades=len(loss_trades),
            avg_profit=round(avg_profit, 2),
            avg_loss=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2),
            daily_returns=daily_returns[-252:],  # 最近一年
            equity_curve=[float(x) for x in self.equity],
            trades=self.trades,
        )

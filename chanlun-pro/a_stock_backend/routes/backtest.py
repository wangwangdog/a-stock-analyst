"""
回测 API 路由
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from engine.backtest import BacktestEngine, BacktestResult
from engine.strategies import STRATEGIES

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


class RunRequest(BaseModel):
    symbol: str
    strategy: str = "ma_cross"
    start: str = "2024-01-01"
    end: str = "2025-05-17"
    capital: float = 100000
    params: dict = {}


@router.get("/strategies")
async def list_strategies():
    """列出所有可用策略及参数"""
    result = []
    import dataclasses
    for key, cls in STRATEGIES.items():
        fields = dataclasses.fields(cls)
        params = {}
        for f in fields:
            if f.name != 'name':
                params[f.name] = f.default
        result.append({
            "key": key,
            "name": cls.name,
            "params": params,
        })
    return {"status": "ok", "strategies": result}


@router.post("/run")
async def run_backtest(req: RunRequest):
    """执行回测"""
    if req.strategy not in STRATEGIES:
        return {"status": "error", "message": f"未知策略: {req.strategy}"}

    strategy_cls = STRATEGIES[req.strategy]
    import dataclasses
    strategy_kwargs = {}
    for f in dataclasses.fields(strategy_cls):
        if f.name != 'name':
            strategy_kwargs[f.name] = req.params.get(f.name, f.default)

    try:
        engine = BacktestEngine(initial_capital=req.capital)
        engine.set_strategy(strategy_cls, **strategy_kwargs)
        result = engine.run(symbol=req.symbol, start=req.start, end=req.end)
        return {"status": "ok", "data": _result_to_dict(result)}
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    except Exception as e:
        return {"status": "error", "message": f"回测异常: {str(e)}"}


@router.get("/quick/{symbol}")
async def quick_backtest(
    symbol: str,
    strategy: str = Query("ma_cross"),
    period: str = Query("1y", description="1y/2y/3y/all"),
):
    """快速回测（简化参数）"""
    from datetime import date, timedelta

    end = date.today().strftime("%Y-%m-%d")
    if period == "1y":
        start = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
    elif period == "2y":
        start = (date.today() - timedelta(days=730)).strftime("%Y-%m-%d")
    elif period == "3y":
        start = (date.today() - timedelta(days=1095)).strftime("%Y-%m-%d")
    else:
        start = "2015-01-01"

    req = RunRequest(symbol=symbol, strategy=strategy, start=start, end=end)
    return await run_backtest(req)


def _result_to_dict(r: BacktestResult) -> dict:
    from datetime import datetime

    def _to_ts(date_str: str) -> int:
        """日期字符串 → Unix秒时间戳"""
        return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())

    return {
        "symbol": r.symbol,
        "strategy_name": r.strategy_name,
        "start_date": r.start_date,
        "end_date": r.end_date,
        "initial_capital": r.initial_capital,
        "final_capital": r.final_capital,
        "total_return": r.total_return,
        "annual_return": r.annual_return,
        "max_drawdown": r.max_drawdown,
        "sharpe_ratio": r.sharpe_ratio,
        "win_rate": r.win_rate,
        "total_trades": r.total_trades,
        "profit_trades": r.profit_trades,
        "loss_trades": r.loss_trades,
        "avg_profit": r.avg_profit,
        "avg_loss": r.avg_loss,
        "profit_factor": r.profit_factor,
        "equity_curve": r.equity_curve[:500],
        "bars": [dict(b, time=_to_ts(b["time"])) for b in r.bars[:500]],
        "markers": [
            {
                "time": _to_ts(t.date),
                "position": "belowBar" if t.direction == "long" else "aboveBar",
                "color": "#ee0a24" if t.direction == "long" else "#07c160",
                "shape": "arrowUp" if t.direction == "long" else "arrowDown",
                "text": f"{'买入' if t.direction == 'long' else '卖出'} ¥{t.price:.2f}",
            }
            for t in r.trades
        ],
        "trades": [
            {
                "date": t.date,
                "direction": t.direction,
                "offset": t.offset,
                "price": round(t.price, 2),
                "volume": t.volume,
                "pnl": round(t.pnl, 2),
                "pnl_pct": round(t.pnl_pct, 2),
            }
            for t in r.trades[-50:]
        ],
    }

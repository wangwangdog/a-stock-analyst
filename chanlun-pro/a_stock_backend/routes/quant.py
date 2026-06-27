"""
/quant 快捷路由 — 量化选股快捷入口

封装 Sequoia-X 策略引擎，提供简洁的量化选股 API。
"""
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from data.sequoia_engine import (
    STRATEGY_META, STRATEGY_CLASSES, DB_PATH,
    _get_engine, _get_settings, _init_picks_table,
    get_strategy_signals,
)
from sequoia_x.strategy.base import BaseStrategy

logger = logging.getLogger('quant_route')
router = APIRouter(prefix="/api/v1/quant", tags=["量化选股"])


# ── 策略元数据映射 ──
_STRATEGY_NAME_MAP = dict((k, n) for k, n, _ in STRATEGY_META)


@router.get("/strategies")
async def list_strategies():
    """返回所有策略列表及其说明"""
    strategies = []
    for key, name, desc in STRATEGY_META:
        strategies.append({
            "key": key,
            "name": name,
            "desc": desc,
        })
    return {
        "total": len(strategies),
        "strategies": strategies,
    }


@router.post("/run/{strategy_name}")
async def run_strategy(strategy_name: str, codes: Optional[List[str]] = Query(None)):
    """对指定股票列表运行单一策略

    如果 codes 为空，则运行全市场扫描。
    """
    if strategy_name not in STRATEGY_CLASSES:
        raise HTTPException(status_code=404, detail=f"未找到策略: {strategy_name}")

    engine = _get_engine()
    settings = _get_settings()
    strategy_cls = STRATEGY_CLASSES[strategy_name]
    strategy = strategy_cls(engine, settings)

    if codes:
        # 限制扫描范围到指定列表，然后调用策略的 run()
        original_get_local = engine.get_local_symbols
        engine.get_local_symbols = lambda: codes
        try:
            selected = strategy.run()
        finally:
            engine.get_local_symbols = original_get_local
    else:
        selected = strategy.run()

    return {
        "strategy": strategy_name,
        "strategy_name": _STRATEGY_NAME_MAP.get(strategy_name, strategy_name),
        "total": len(selected),
        "picks": selected,
    }


@router.post("/scan")
async def scan_all(codes: Optional[List[str]] = Query(None)):
    """全市场扫描，返回所有符合策略条件的标的

    如果 codes 不为空，则只扫描指定列表。
    """
    engine = _get_engine()
    settings = _get_settings()

    results = {}
    for key, cls in STRATEGY_CLASSES.items():
        try:
            strategy = cls(engine, settings)
            if codes:
                original_get_local = engine.get_local_symbols
                engine.get_local_symbols = lambda: codes
                try:
                    selected = strategy.run()
                finally:
                    engine.get_local_symbols = original_get_local
            else:
                selected = strategy.run()

            results[key] = {
                "name": _STRATEGY_NAME_MAP.get(key, key),
                "total": len(selected),
                "picks": selected,
            }
        except Exception as e:
            logger.warning(f"[{key}] 扫描失败: {e}", exc_info=True)
            results[key] = {
                "name": _STRATEGY_NAME_MAP.get(key, key),
                "total": 0,
                "picks": [],
                "error": str(e),
            }

    # 汇总所有被选中的唯一个股
    all_picked = set()
    strategy_counts = {}
    for key, data in results.items():
        for sym in data["picks"]:
            all_picked.add(sym)
            strategy_counts.setdefault(sym, []).append(key)

    return {
        "total_strategies": len(STRATEGY_CLASSES),
        "total_unique_stocks": len(all_picked),
        "strategies": results,
        "multi_strategy": [
            {"symbol": sym, "count": len(strats), "strategies": strats}
            for sym, strats in sorted(strategy_counts.items(), key=lambda x: -len(x[1]))
            if len(strats) > 1
        ],
    }


@router.get("/signals/{symbol}")
async def get_signals(symbol: str):
    """查询个股的所有量化策略信号

    从 strategy_picks 表查询最近 N 天该股被哪些策略选中。
    """
    from data.sequoia_engine import query_stock_strategies

    try:
        result = query_stock_strategies(symbol, max_days=14)
    except Exception as e:
        logger.warning(f"查询 {symbol} 策略信号失败: {e}")
        return {
            "symbol": symbol,
            "date": None,
            "strategy_count": 0,
            "strategies": [],
            "error": str(e),
        }
    return {
        "symbol": symbol,
        "date": result["date"],
        "strategy_count": result["strategy_count"],
        "strategies": result["strategies"],
    }

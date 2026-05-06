"""
API 路由 - 量化选股（Sequoia-X 策略）
"""
import logging
from fastapi import APIRouter, Query
from pydantic import BaseModel

from data.sequoia_engine import (
    check_status, daily_sync, get_todays_picks,
    get_picks_history, get_strategy_signals,
    get_multi_strategy_picks,
    refresh_vol20day, query_vol20day, get_vol20day_total,
    stock_has_strategy_picks,
    STRATEGY_META,
)

logger = logging.getLogger('strategy_route')
router = APIRouter(prefix="/api/v1/strategy", tags=["量化选股"])


class SyncResponse(BaseModel):
    status: str
    sync_count: int = 0
    total_symbols: int = 0
    total_picks: int = 0
    picks: dict = {}
    date: str = ""
    error: str = ""


@router.get("/status")
async def strategy_status():
    """Sequoia-X 数据引擎状态"""
    return check_status()


@router.get("/list")
async def strategy_list():
    """策略列表"""
    return {
        "strategies": [
            {"key": k, "name": n, "desc": d} for k, n, d in STRATEGY_META
        ],
        "total": len(STRATEGY_META),
    }


@router.post("/sync")
async def trigger_sync():
    """触发每日同步（拉数据 + 跑策略 + 写选股结果）"""
    logger.info("🎯 Sequoia-X 日常同步启动")
    result = daily_sync()
    return result


@router.get("/picks")
async def get_picks(
    strategy: str = Query(None, description="按策略筛选"),
    today_only: bool = Query(True, description="仅今日"),
    days: int = Query(1, description="回溯天数"),
):
    """获取选股结果"""
    if today_only or days <= 1:
        rows = get_todays_picks(strategy=strategy)
    else:
        rows = get_picks_history(days=days, strategy=strategy)

    # 按策略聚合
    by_strategy = {}
    for r in rows:
        by_strategy.setdefault(r["strategy"], []).append(r["symbol"])

    return {
        "date": rows[0]["date"] if rows else None,
        "total": len(rows),
        "picks": by_strategy,
        "flat": rows,
    }


@router.get("/check/{symbol}")
async def stock_strategy_check(symbol: str):
    """检查个股是否在策略数据库中（任意日期有记录即可）"""
    return {
        "symbol": symbol,
        "has_picks": stock_has_strategy_picks(symbol),
    }


@router.get("/signals/{symbol}")
async def stock_strategy_signals(symbol: str):
    """个股当日被哪些策略选中"""
    text = get_strategy_signals(symbol)
    return {
        "symbol": symbol,
        "signals": text,
        "has_signals": bool(text),
    }


@router.post("/vol20day/refresh")
async def refresh_vol20day_endpoint():
    """刷新 vol20day 表（计算20日涨幅排名）"""
    result = refresh_vol20day()
    return result


@router.get("/vol20day")
async def get_vol20day(
    min_rank: int = Query(1, ge=1, description="起始排名"),
    max_rank: int = Query(100, ge=1, description="截止排名"),
):
    """查询 vol20day 表中指定排名的股票"""
    data = query_vol20day(min_rank=min_rank, max_rank=max_rank)
    total = get_vol20day_total()
    return {
        "status": "ok",
        "total": total,
        "min_rank": min_rank,
        "max_rank": max_rank,
        "returned": len(data),
        "data": data,
    }


@router.get("/multi-picks")
async def multi_strategy_picks(
    min_count: int = Query(2, ge=1, le=6, description="最少满足策略数"),
    max_count: int = Query(None, ge=1, le=6, description="最多满足策略数"),
    days: int = Query(1, ge=1, le=30, description="回溯天数"),
):
    """获取同时被多个策略选中的股票"""
    results = get_multi_strategy_picks(
        min_count=min_count, max_count=max_count, days=days
    )
    return {
        "status": "ok",
        "total": len(results),
        "min_count": min_count,
        "max_count": max_count if max_count else "unlimited",
        "data": results,
    }


@router.get("/history")
async def picks_history(
    days: int = Query(30, ge=1, le=365),
    strategy: str = Query(None),
    symbol: str = Query(None),
):
    """历史选股记录"""
    rows = get_picks_history(days=days, strategy=strategy, symbol=symbol)
    return {
        "total": len(rows),
        "records": rows,
    }

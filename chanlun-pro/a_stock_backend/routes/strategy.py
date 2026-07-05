"""
API 路由 - 量化选股（Sequoia-X 策略）
"""
import logging
import asyncio
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from fastapi import APIRouter, Query
from pydantic import BaseModel

from data.sequoia_engine import (
    check_status, daily_sync, get_todays_picks,
    get_picks_history, get_strategy_signals,
    get_multi_strategy_picks,
    refresh_vol20day, query_vol20day, get_vol20day_total,
    stock_has_strategy_picks, query_stock_strategies,
    STRATEGY_META,
)
from strategies.pre_market import run_pre_market
from strategies.intraday import run_intraday
from strategies.market_anomaly_collector import collect_anomaly
from strategies.fund_flow_collector import collect_symbol

logger = logging.getLogger('strategy_route')
router = APIRouter(prefix="/api/v1/strategy", tags=["量化选股"])

# 全局同步锁 + 状态跟踪
_sync_in_progress = False
_sync_result = None
_sync_progress = {}  # 策略级进度
_sync_executor = ThreadPoolExecutor(max_workers=1)


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


@router.get("/sync/status")
async def get_sync_status():
    """获取同步状态（含策略级进度）"""
    global _sync_in_progress, _sync_result, _sync_progress
    return {
        "in_progress": _sync_in_progress,
        "result": _sync_result,
        "progress": _sync_progress,
    }


@router.post("/sync")
async def trigger_sync():
    """触发每日同步（后台异步，不阻塞事件循环）"""
    global _sync_in_progress, _sync_result, _sync_progress
    if _sync_in_progress:
        return {"status": "in_progress", "message": "同步正在进行中..."}

    _sync_in_progress = True
    _sync_result = None
    _sync_progress = {}
    logger.info("🎯 Sequoia-X 日常同步启动（后台线程）")

    def _progress_cb(info):
        global _sync_progress
        _sync_progress = {
            "strategies": info,
            "phase": "strategy",
        }
        logger.info(f"  [{info['strategy']}] 完成 ({info['completed']}/{info['total']}), 选股 {info['picks']} 只")

    def _run_sync():
        global _sync_in_progress, _sync_result, _sync_progress
        try:
            _sync_progress = {"phase": "data_sync", "strategies": None}
            # 数据同步加 120 秒超时，超时则只跑策略
            result = None
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(daily_sync, progress_callback=_progress_cb)
                try:
                    result = fut.result(timeout=120)
                except concurrent.futures.TimeoutError:
                    logger.warning("数据同步超时（120s），跳过数据同步直接跑策略")
                    _sync_progress = {"phase": "strategy_only", "strategies": None}
                    # 直接跑策略
                    from data.sequoia_engine import _get_engine, _get_settings, STRATEGY_CLASSES, _init_picks_table, DB_PATH
                    from datetime import date
                    _init_picks_table()
                    engine = _get_engine()
                    settings = _get_settings()
                    today = date.today().strftime("%Y-%m-%d")
                    strategies = [(key, cls(engine, settings)) for key, cls in STRATEGY_CLASSES.items()]
                    import sqlite3
                    DB = DB_PATH
                    conn = sqlite3.connect(DB)
                    conn.execute("DELETE FROM strategy_picks WHERE date=?", (today,))
                    all_picks = []
                    for key, strategy in strategies:
                        try:
                            selected = strategy.run()
                            for rank, symbol in enumerate(selected):
                                conn.execute(
                                    "INSERT INTO strategy_picks (date, strategy, symbol, rank) VALUES (?, ?, ?, ?)",
                                    (today, key, symbol, rank),
                                )
                                all_picks.append((key, symbol))
                            _progress_cb({"strategy": key, "ok": True, "picks": len(selected),
                                          "completed": len(all_picks), "total": len(strategies)})
                        except Exception as e2:
                            _progress_cb({"strategy": key, "ok": False, "picks": 0,
                                          "completed": len(all_picks), "total": len(strategies)})
                            logger.warning(f"[{key}] 策略运行失败: {e2}")
                    conn.commit()
                    conn.close()
                    picks_by_strategy = {}
                    for k, s in all_picks:
                        picks_by_strategy.setdefault(k, []).append(s)
                    result = {
                        "status": "ok",
                        "sync_count": 0,
                        "total_symbols": 0,
                        "picks": {k: len(v) for k, v in picks_by_strategy.items()},
                        "total_picks": len(all_picks),
                        "date": today,
                    }

            _sync_result = result
            _sync_progress = {"phase": "done", "strategies": None}
            logger.info(f"✅ Sequoia-X 同步完成: {result.get('total_picks',0)}只")
        except Exception as e:
            _sync_result = {"status": "error", "error": str(e)}
            _sync_progress = {"phase": "error", "strategies": None}
            logger.error(f"❌ Sequoia-X 同步失败: {e}")
            logger.error(f"❌ Sequoia-X 同步失败: {e}")
        finally:
            _sync_in_progress = False

    loop = asyncio.get_event_loop()
    loop.run_in_executor(_sync_executor, _run_sync)

    return {"status": "started", "message": "同步已启动，后台执行中..."}


@router.get("/picks")
async def get_picks(
    strategy: str = Query(None, description="按策略筛选"),
    today_only: bool = Query(True, description="仅今日"),
    days: int = Query(1, description="回溯天数"),
):
    """获取选股结果
    
    非交易日自动回退到最近有数据的交易日。
    """
    if today_only or days <= 1:
        rows = get_todays_picks(strategy=strategy)
        # 非交易日没有当日数据时，回退到最近交易日
        if not rows:
            rows = get_picks_history(days=14, strategy=strategy)
            if rows:
                # 只保留最近一个交易日的
                latest_date = rows[0]["date"]
                rows = [r for r in rows if r["date"] == latest_date]
    else:
        rows = get_picks_history(days=days, strategy=strategy)

    # 按策略聚合
    by_strategy = {}
    for r in rows:
        by_strategy.setdefault(r["strategy"], []).append(r["symbol"])

    # ── 富化：查询股票详情构建 picks_detail ──
    picks_detail = {}
    if rows:
        db = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")
        # 收集所有涉及到的 symbol
        all_symbols = sorted(set(r["symbol"] for r in rows))
        detail_map = {}
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            placeholders = ','.join('?' * len(all_symbols))
            # 从 vol20day 获取量价数据
            vol_rows = conn.execute(
                f"""SELECT v.symbol, v.latest_close, v.return_20d, v.close_20d, v.rank_20d,
                          CASE WHEN v.name != '' THEN v.name ELSE a.name END as name
                   FROM (SELECT * FROM vol20day WHERE symbol IN ({placeholders})) v
                   LEFT JOIN all_stock_info a ON v.symbol = a.symbol""",
                all_symbols
            ).fetchall()
            for vr in vol_rows:
                detail_map[vr["symbol"]] = {
                    "symbol": vr["symbol"],
                    "name": vr["name"] or "",
                    "latest_close": vr["latest_close"],
                    "return_20d": round(vr["return_20d"], 2) if vr["return_20d"] is not None else None,
                    "close_20d": vr["close_20d"],
                    "rank_20d": vr["rank_20d"],
                }
            # 补漏：vol20day 中没有的 symbol，从 all_stock_info 补名
            missing = [s for s in all_symbols if s not in detail_map]
            if missing:
                placeholders2 = ','.join('?' * len(missing))
                name_rows = conn.execute(
                    f"SELECT symbol, name FROM all_stock_info WHERE symbol IN ({placeholders2})",
                    missing
                ).fetchall()
                for nr in name_rows:
                    detail_map[nr["symbol"]] = {
                        "symbol": nr["symbol"],
                        "name": nr["name"] or "",
                        "latest_close": None,
                        "return_20d": None,
                        "close_20d": None,
                        "rank_20d": None,
                    }
            conn.close()
        except Exception as e:
            logger.warning(f"富化 picks_detail 失败: {e}")
            # 保底：至少给出 symbol 和空 name
            for sym in all_symbols:
                if sym not in detail_map:
                    detail_map[sym] = {
                        "symbol": sym, "name": "",
                        "latest_close": None, "return_20d": None,
                        "close_20d": None, "rank_20d": None,
                    }

        # 按策略组装 picks_detail
        for r in rows:
            k = r["strategy"]
            picks_detail.setdefault(k, []).append(
                detail_map.get(r["symbol"], {
                    "symbol": r["symbol"], "name": "",
                    "latest_close": None, "return_20d": None,
                    "close_20d": None, "rank_20d": None,
                })
            )

    return {
        "date": rows[0]["date"] if rows else None,
        "total": len(rows),
        "picks": by_strategy,
        "picks_detail": picks_detail,
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
    """个股当日被哪些策略选中（文本）"""
    text = get_strategy_signals(symbol)
    return {
        "symbol": symbol,
        "signals": text,
        "has_signals": bool(text),
    }


@router.get("/query-stock/{symbol}")
async def stock_strategy_query(symbol: str):
    """个股策略查询（结构化）
    
    检查最近 N 天内该股票被哪些策略选中，返回策略列表及排名。
    """
    result = query_stock_strategies(symbol)
    return {
        "status": "ok",
        **result,
    }


@router.post("/vol20day/refresh")
async def refresh_vol20day_endpoint():
    """刷新 vol20day 表（后台异步，不阻塞事件循环）"""
    global _sync_in_progress
    if _sync_in_progress:
        return {"status": "in_progress", "message": "数据同步正在进行中，请稍后再试"}

    logger.info("📊 vol20day 刷新启动（后台线程）")

    def _run_refresh():
        try:
            result = refresh_vol20day()
            logger.info(f"✅ vol20day 刷新完成: {result}")
        except Exception as e:
            logger.error(f"❌ vol20day 刷新失败: {e}")

    loop = asyncio.get_event_loop()
    loop.run_in_executor(_sync_executor, _run_refresh)

    return {"status": "started", "message": "vol20day 刷新已启动，后台执行中..."}


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
    """获取同时被多个策略选中的股票

    非交易日自动回退到最近有数据的交易日。
    """
    results = get_multi_strategy_picks(
        min_count=min_count, max_count=max_count, days=days
    )
    # 非交易日无数据时回退到最近交易日
    if not results:
        results = get_multi_strategy_picks(
            min_count=min_count, max_count=max_count, days=14
        )
        if results:
            # 只保留最近一个交易日的
            from itertools import groupby
            results.sort(key=lambda r: r.get("date", ""), reverse=True)
            latest = results[0].get("date", "")
            results = [r for r in results if r.get("date") == latest]
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


@router.post("/pre-market")
async def pre_market_strategy():
    """🌅 盘前策略：盘前批量分析，输出今日关注池"""
    return run_pre_market()


@router.post("/intraday")
async def intraday_strategy():
    """⚡ 盘中策略：实时行情扫描，输出交易信号"""
    return run_intraday()


@router.get("/anomaly")
async def get_anomaly(symbol: str = None, limit: int = 50):
    """📡 盘口异动查询"""
    conn = sqlite3.connect("/home/dogzi/sqlite-data/chanlun_klines.sqlite")
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        if symbol:
            rows = conn.execute(
                """SELECT symbol, anomaly_type, occur_time, price, volume, created_at
                   FROM market_anomaly
                   WHERE created_at >= ? AND symbol=?
                   ORDER BY occur_time DESC LIMIT ?""",
                (today, symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT symbol, anomaly_type, occur_time, price, volume, created_at
                   FROM market_anomaly
                   WHERE created_at >= ?
                   ORDER BY occur_time DESC LIMIT ?""",
                (today, limit),
            ).fetchall()
        return {
            "status": "ok",
            "total": len(rows),
            "data": [
                {"symbol": r[0], "anomaly_type": r[1],
                 "occur_time": r[2], "price": r[3],
                 "volume": r[4], "created_at": r[5]}
                for r in rows
            ],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


@router.post("/anomaly/collect")
async def trigger_anomaly_collect(watch_only: bool = Query(False)):
    """📡 触发盘口异动采集"""
    return collect_anomaly(watch_only=watch_only)


@router.get("/fund-flow")
async def get_fund_flow(symbol: str = Query(...), limit: int = 200):
    """💰 查询个股资金流向"""
    conn = sqlite3.connect("/home/dogzi/sqlite-data/chanlun_klines.sqlite")
    try:
        rows = conn.execute(
            """SELECT trade_date, close, pct_change,
                      main_inflow, main_pct,
                      big_inflow, big_pct,
                      large_inflow, large_pct,
                      medium_inflow, medium_pct,
                      small_inflow, small_pct, turnover
               FROM stock_fund_flow
               WHERE symbol=?
               ORDER BY trade_date DESC LIMIT ?""",
            (symbol, limit),
        ).fetchall()
        return {
            "status": "ok",
            "total": len(rows),
            "data": [
                {"trade_date": r[0], "close": r[1], "pct_change": r[2],
                 "main_inflow": r[3], "main_pct": r[4],
                 "big_inflow": r[5], "big_pct": r[6],
                 "large_inflow": r[7], "large_pct": r[8],
                 "medium_inflow": r[9], "medium_pct": r[10],
                 "small_inflow": r[11], "small_pct": r[12],
                 "turnover": r[13]} for r in rows
            ],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


@router.post("/fund-flow/collect")
async def trigger_fund_flow_collect(
    symbol: str = Query(...),
    start: str = Query(None),
    end: str = Query(None),
):
    """💰 触发资金流向采集"""
    from datetime import date, timedelta
    if not start:
        start = (date.today() - timedelta(days=200)).strftime("%Y-%m-%d")
    if not end:
        end = date.today().strftime("%Y-%m-%d")
    cnt = collect_symbol(symbol, start, end)
    return {"status": "ok", "symbol": symbol, "records": cnt}

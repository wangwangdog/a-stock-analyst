"""多数据源交叉校验器"""
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from config import VALIDATION_TOLERANCE
from . import akshare_fetcher, baostock_fetcher
from .cache import save_kline, get_kline, log_check, is_cache_fresh


def fetch_kline_cross_checked(symbol: str, start_date: str = None, end_date: str = None) -> dict:
    """
    双源交叉校验获取 K 线数据

    返回:
    {
        "primary": DataFrame | None,   # 主要数据（AKShare）
        "backup": DataFrame | None,    # 备份数据（Baostock）
        "validation": [
            { "trade_date": str, "diff_pct": float, "passed": bool, "akshare": val, "baostock": val }
        ],
        "source": "akshare" | "baostock" | "cache",
        "status": "ok" | "partial" | "fallback" | "failed",
        "message": str
    }
    """
    result = {"primary": None, "backup": None, "validation": [], "source": "", "status": "ok", "message": ""}

    # 1. 优先本地缓存（立即返回，不等待网络）
    cache_ak = get_kline(symbol, "akshare", start_date, end_date)
    cache_bs = get_kline(symbol, "baostock", start_date, end_date)

    # 有任一缓存即返回，网络数据源失败时缓存是主数据源
    if not cache_ak.empty:
        result["primary"] = cache_ak
        result["source"] = "cache"
        if not cache_bs.empty:
            result["backup"] = cache_bs
            result["validation"] = _validate_dfs(cache_ak, cache_bs, symbol)
        result["status"] = "ok"
        result["message"] = "使用缓存数据"
        return result

    # 2. 无缓存时尝试网络（AKShare）
    df_ak = akshare_fetcher.get_daily_kline(symbol, start_date, end_date)
    if df_ak is not None and not df_ak.empty:
        save_kline(symbol, "akshare", df_ak)
        result["primary"] = df_ak
        result["source"] = "akshare"
        result["status"] = "ok"
        result["message"] = "AKShare 实时数据"
        return result

    # 3. 无缓存时尝试网络（Baostock）
    df_bs = baostock_fetcher.get_daily_kline(symbol, start_date, end_date)
    if df_bs is not None and not df_bs.empty:
        save_kline(symbol, "baostock", df_bs)
        result["primary"] = df_bs
        result["source"] = "baostock"
        result["status"] = "fallback"
        result["message"] = "Baostock 实时数据"
        return result

    # 4. 所有数据源均不可用
    result["status"] = "failed"
    result["message"] = "所有数据源均不可用"
    return result


def _validate_dfs(df_ak: pd.DataFrame, df_bs: pd.DataFrame, symbol: str) -> list:
    """比较两个源的数据，返回校验记录"""
    validation_records = []

    # 统一列名和类型
    ak = df_ak.copy()
    bs = df_bs.copy()

    for df in [ak, bs]:
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")

    # 检查列是否存在
    for col in ["open", "close", "high", "low"]:
        if col not in ak.columns:
            ak[col] = 0.0
        if col not in bs.columns:
            bs[col] = 0.0

    failed_count = 0
    total_count = 0

    # 以 AKShare 的日期为准进行匹配
    for _, arow in ak.iterrows():
        td = arow["trade_date"]
        brow = bs[bs["trade_date"] == td]

        if brow.empty:
            continue

        brow = brow.iloc[0]
        total_count += 1
        record = {"trade_date": td, "passed": True, "akshare": {}, "baostock": {}, "diff_pct": 0}

        max_diff = 0
        for field, tolerance in VALIDATION_TOLERANCE.items():
            if field not in arow.index or field not in brow.index:
                continue
            try:
                av = float(arow[field]) if arow[field] else 0
                bv = float(brow[field]) if brow[field] else 0
                if av == 0 and bv == 0:
                    diff = 0
                elif av == 0:
                    diff = 1.0
                else:
                    diff = abs(av - bv) / av

                record["akshare"][field] = av
                record["baostock"][field] = bv
                max_diff = max(max_diff, diff)

                if diff > tolerance:
                    record["passed"] = False
            except (ValueError, TypeError):
                continue

        record["diff_pct"] = round(max_diff * 100, 2)
        passed = int(record["passed"])
        akshare_open = record["akshare"].get("open", 0)
        baostock_open = record["baostock"].get("open", 0)

        # 写入校验日志
        log_check(symbol, td, akshare_open, baostock_open, record["diff_pct"], record["passed"])

        if not record["passed"]:
            failed_count += 1

        validation_records.append(record)

    if total_count > 0 and failed_count > 0 and failed_count > total_count * 0.5:
        logger.warning(f"[校验] {symbol}: {failed_count}/{total_count} 天数据不一致(>50%)")
    elif failed_count > 0:
        logger.debug(f"[校验] {symbol}: {failed_count}/{total_count} 天数据不一致")

    return validation_records


def check_data_health(symbol: str = None) -> dict:
    """检查数据源健康状态"""
    status = {
        "akshare": {"available": akshare_fetcher.available(), "cached_days": 0},
        "baostock": {"available": baostock_fetcher.available(), "cached_days": 0},
        "last_check": None,
        "failed_dates": [],
    }

    from .cache import _get_conn
    conn = _get_conn()
    try:
        # 最近校验记录
        cursor = conn.execute(
            "SELECT checked_at FROM kline_check_log ORDER BY checked_at DESC LIMIT 1"
        )
        row = cursor.fetchone()

        if row:
            status["last_check"] = row[0]

        # 未通过校验的天数
        cursor = conn.execute(
            "SELECT DISTINCT trade_date FROM kline_check_log WHERE passed=0 ORDER BY trade_date DESC LIMIT 20"
        )
        failures = cursor.fetchall()
        status["failed_dates"] = [r[0] for r in failures]

        # 缓存天数
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM kline_cache WHERE source='akshare'"
        )
        row = cursor.fetchone()
        if row:
            status["akshare"]["cached_days"] = row[0]

        cursor = conn.execute(
            "SELECT COUNT(DISTINCT trade_date) FROM kline_cache WHERE source='baostock'"
        )
        row = cursor.fetchone()
        if row:
            status["baostock"]["cached_days"] = row[0]

    finally:
        conn.close()

    return status

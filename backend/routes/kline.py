"""API 路由 - K线数据"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from data.validator import fetch_kline_cross_checked, check_data_health
from data import akshare_fetcher
from analysis.indicators import calc_all_indicators
from analysis.fundamentals import get_fundamental_summary
from analysis.tushare_analysis import get_tushare_analysis

router = APIRouter(prefix="/api/v1", tags=["K线数据"])


class KlineResponse(BaseModel):
    symbol: str
    name: str = ""
    period: str
    data: list
    indicators: dict = {}
    validation: list = []
    source: str = ""
    status: str = ""
    message: str = ""


class HealthResponse(BaseModel):
    status: str = "ok"
    data_sources: dict = {}
    last_check: Optional[str] = None
    failed_dates: list = []


@router.get("/kline/{symbol}")
async def get_kline(
    symbol: str,
    period: str = Query("daily", pattern="^(daily|weekly|monthly|15min|30min|60min)$"),
    start_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    indicators: bool = Query(True),
):
    """获取K线数据

    支持周期: daily, weekly, monthly, 15min, 30min, 60min
    日/周/月使用双源校验，分钟级直接从 AKShare 获取。
    """
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        if period in ("15min", "30min", "60min"):
            # 分钟级默认取最近30天
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    # 分钟级K线直接从 AKShare 获取（Baostock 不支持分钟级）
    if period in ("15min", "30min", "60min"):
        period_map = {"15min": "15", "30min": "30", "60min": "60"}
        minute_period = period_map[period]
        df = akshare_fetcher.get_minute_kline(symbol, minute_period, start_date, end_date)

        if df is None or df.empty:
            return KlineResponse(
                symbol=symbol, period=period, data=[], source="akshare",
                status="failed", message="获取分钟级数据失败"
            )

        # 缓存分钟级数据
        from data.cache import save_kline
        save_kline(symbol, "akshare", df, period=period)

        # 准备返回数据
        data_list = []
        for _, row in df.iterrows():
            td = str(row.get("trade_date", ""))
            item = {
                "date": td,
                "open": round(float(row.get("open", 0)), 2),
                "close": round(float(row.get("close", 0)), 2),
                "high": round(float(row.get("high", 0)), 2),
                "low": round(float(row.get("low", 0)), 2),
            }
            if "volume" in row:
                item["volume"] = float(row["volume"])
            if "amount" in row:
                item["amount"] = float(row["amount"])
            data_list.append(item)

        # 分钟级不计算技术指标
        # 获取股票名称
        name = ""
        try:
            fund = get_fundamental_summary(symbol)
            if fund:
                name = fund.get("name", "")
        except Exception:
            pass

        return KlineResponse(
            symbol=symbol, period=period, data=data_list,
            indicators={},
            validation=[],
            source="akshare",
            status="ok",
            name=name,
            message=f"AKShare 分钟级K线 (period={minute_period})，共 {len(data_list)} 条",
        )

    # 日/周/月 - 优先从 sequoia.db 读取日线
    kline_data = None
    if period == "daily":
        try:
            from data.sequoia_engine import get_daily_kline
            sq_data = get_daily_kline(symbol, start_date, end_date)
            if sq_data:
                kline_data = sq_data
        except Exception:
            pass

    if kline_data:
        # 转换为 DataFrame 以便技术指标计算
        import pandas as pd
        df = pd.DataFrame(kline_data)
        if "date" in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        
        data_list = []
        for _, row in df.iterrows():
            entry = {
                "date": str(row.get("trade_date", ""))[:10],
                "open": round(float(row.get("open", 0)), 2),
                "close": round(float(row.get("close", 0)), 2),
                "high": round(float(row.get("high", 0)), 2),
                "low": round(float(row.get("low", 0)), 2),
            }
            if "volume" in df.columns and row.get("volume") is not None:
                entry["volume"] = float(row["volume"])
            if "amount" in df.columns and row.get("amount") is not None:
                entry["amount"] = float(row["amount"])
            data_list.append(entry)
        result = {"primary": df, "status": "ok", "source": "sequoia",
                  "message": f"Sequoia 日线，共 {len(data_list)} 条", "validation": []}
    else:
        # fallback: 双源校验
        result = fetch_kline_cross_checked(symbol, start_date, end_date)

        if result["status"] == "failed":
            return KlineResponse(
                symbol=symbol, period=period, data=[], source="",
                status="failed", message=result["message"]
            )

        df = result["primary"]
        if df is None or df.empty:
            return KlineResponse(
                symbol=symbol, period=period, data=[], source=result["source"],
                status="failed", message="无可用数据"
            )

        # 准备返回数据
        data_list = []
        for _, row in df.iterrows():
            item = {
                "date": str(row.get("trade_date", ""))[:10],
                "open": round(float(row.get("open", 0)), 2),
                "close": round(float(row.get("close", 0)), 2),
                "high": round(float(row.get("high", 0)), 2),
                "low": round(float(row.get("low", 0)), 2),
            }
            if "volume" in row:
                item["volume"] = float(row["volume"])
            if "amount" in row:
                item["amount"] = float(row["amount"])
            data_list.append(item)

    # 计算技术指标
    ind_dict = {}
    if indicators and len(data_list) > 20 and df is not None and not df.empty:
        ind_dict = calc_all_indicators(df)

    # 获取股票名称
    name = ""
    try:
        fund = get_fundamental_summary(symbol)
        if fund:
            name = fund.get("name", "")
    except Exception:
        pass

    # 后台预缓存所有其他周期的K线数据
    try:
        from data.cache import save_kline, get_kline
        import asyncio, threading
        async def _do_precache():
            others = [p for p in ["daily","weekly","monthly","15min","30min","60min"] if p != period]
            for op in others:
                try:
                    existing = get_kline(symbol, "akshare", period=op)
                    if existing is not None and not existing.empty:
                        continue
                    if op in ("15min","30min","60min"):
                        pm = {"15min":"15","30min":"30","60min":"60"}
                        df2 = akshare_fetcher.get_minute_kline(symbol, pm[op])
                    else:
                        df2 = akshare_fetcher.get_daily_kline(symbol, period=op)
                    if df2 is not None and not df2.empty:
                        save_kline(symbol, "akshare", df2, period=op)
                except:
                    pass
        threading.Thread(target=lambda: asyncio.run(_do_precache()), daemon=True).start()
    except:
        pass

    return KlineResponse(
        symbol=symbol, period=period, data=data_list,
        indicators=ind_dict,
        validation=result.get("validation", []),
        source=result["source"],
        status=result["status"],
        name=name,
        message=result["message"],
    )


@router.get("/big-buy-summary/{symbol}")
async def get_big_buy_summary(symbol: str, limit: int = 60):
    """获取某只股票的有大买单历史数据（按日汇总）"""
    from data.cache import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT trade_date, COUNT(*) as cnt, SUM(qty) as total_qty, SUM(amount) as total_amount
           FROM big_buy_summary
           WHERE symbol=?
           GROUP BY trade_date
           ORDER BY trade_date DESC
           LIMIT ?""",
        (symbol, limit)
    ).fetchall()
    conn.close()
    return {
        "symbol": symbol,
        "data": [
            {
                "date": r[0],
                "count": r[1],
                "qty": r[2],
                "amount": r[3],
            }
            for r in rows
        ]
    }


@router.get("/big-deal-summary/{symbol}")
async def get_big_deal_summary(symbol: str, limit: int = 60):
    """获取某只股票的大笔买入历史数据"""
    from data.cache import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT trade_date, big_buy_count, big_buy_lots, big_buy_amount, total_lots, total_amount
           FROM big_deal_summary
           WHERE symbol=?
           ORDER BY trade_date DESC
           LIMIT ?""",
        (symbol, limit)
    ).fetchall()
    conn.close()
    return {
        "symbol": symbol,
        "data": [
            {
                "date": r[0],
                "count": r[1],
                "lots": r[2],
                "amount": r[3],
                "total_lots": r[4],
                "total_amount": r[5],
            }
            for r in rows
        ]
    }


@router.get("/stocks")
async def get_stock_list():
    """获取A股股票列表"""
    df = akshare_fetcher.get_stock_list()
    if df.empty:
        return {"status": "failed", "data": [], "message": "获取失败"}
    stocks = df.to_dict(orient="records")
    return {"status": "ok", "data": stocks, "total": len(stocks)}


@router.get("/fundamentals/{symbol}")
async def get_fundamentals(symbol: str):
    """获取基本面数据"""
    summary = get_fundamental_summary(symbol)
    if summary is None:
        return {"status": "failed", "data": {}, "message": "获取基本面失败"}
    return {"status": "ok", "data": summary}


@router.get("/health")
@router.get("/tushare-fundamentals/{symbol}")
async def get_tushare_fundamentals(symbol: str):
    """获取 tushare 财报 & 资金流分析"""
    result = get_tushare_analysis(symbol)
    return {"status": "ok", "data": result}


async def get_health():
    """数据源健康检查"""
    health = check_data_health()
    return HealthResponse(
        status="ok",
        data_sources=health,
        last_check=health.get("last_check"),
        failed_dates=health.get("failed_dates", []),
    )


@router.get("/bigbuy/{symbol}")
async def get_bigbuy(symbol: str, days: int = Query(60, description="回溯天数")):
    """获取大单买入量数据（来自 hzeveryday 表）"""
    from data.cache import _get_conn
    conn = _get_conn()
    try:
        # 代码匹配：前端传 000001，数据库可能存为 1 或 000001
        # 生成多个匹配模式
        code_clean = symbol.lstrip("0")  # "000001" -> "1"
        code_patterns = [symbol, code_clean]
        if code_clean and code_clean != symbol:
            code_patterns.append(f"%{code_clean}")

        placeholders = ",".join(["?"] * len(code_patterns))
        cursor = conn.execute(f"""
            SELECT 买入日期, 大笔买数, 合计金额, 合计手数
            FROM hzeveryday
            WHERE 股票代码 IN ({placeholders})
            ORDER BY 买入日期 DESC
            LIMIT ?
        """, (*code_patterns, days))
        rows = cursor.fetchall()
        if not rows:
            return {"status": "ok", "data": [], "message": "无大单买入数据"}
        data = []
        for row in rows:
            data.append({
                "date": row[0],
                "count": row[1],
                "amount": row[2],
                "volume": row[3],
            })
        data.sort(key=lambda x: x["date"])
        return {"status": "ok", "data": data, "total": len(data)}
    except Exception as e:
        return {"status": "failed", "data": [], "message": str(e)}
    finally:
        conn.close()


@router.get("/bigbuy-rank")
async def get_bigbuy_rank():
    """大笔买入天数排名（按出现天数倒序）"""
    from data.cache import _get_conn
    conn = _get_conn()
    rows = conn.execute("""
        SELECT 股票代码, 股票名称, COUNT(DISTINCT 买入日期) as 天数, SUM(大笔买数) as 总笔数
        FROM hzeveryday
        WHERE 股票代码 NOT LIKE '9%'
          AND 股票名称 NOT LIKE '%ST%'
          AND 股票名称 NOT LIKE '%退%'
        GROUP BY 股票代码
        ORDER BY 天数 DESC, 总笔数 DESC
        LIMIT 200
    """).fetchall()
    conn.close()
    return [
        {"symbol": r[0], "name": r[1] or "", "days": r[2], "total_buys": r[3]}
        for r in rows
    ]


@router.get("/screener")
async def screen_stocks(
    market_cap_min: Optional[float] = Query(None, description="最小总市值(亿元)"),
    market_cap_max: Optional[float] = Query(None, description="最大总市值(亿元)"),
    industry: Optional[str] = Query(None, description="行业名称"),
):
    """
    选股筛选
    获取全部A股实时行情进行过滤（数据量较大，耗时较长）
    """
    try:
        # 从实时行情获取数据
        df = akshare_fetcher.get_all_spot()
        if df.empty:
            return {"status": "failed", "data": [], "message": "获取行情数据失败"}

        # 过滤
        if industry:
            df = df[df.get("行业", "").str.contains(industry, na=False)]
        if market_cap_min is not None:
            df = df[df.get("总市值", 0) >= market_cap_min * 1e8]
        if market_cap_max is not None:
            df = df[df.get("总市值", 0) <= market_cap_max * 1e8]

        return {"status": "ok", "data": df.to_dict(orient="records"), "total": len(df)}
    except Exception as e:
        return {"status": "failed", "data": [], "message": f"筛选出错: {e}"}

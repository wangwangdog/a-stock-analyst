"""API 路由 - K线数据"""
from datetime import datetime, timedelta
from typing import Optional
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from data.validator import fetch_kline_cross_checked, check_data_health
from data import akshare_fetcher
from analysis.indicators import calc_all_indicators
from analysis.fundamentals import get_fundamental_summary
from analysis.tushare_analysis import get_tushare_analysis

logger = logging.getLogger('kline_route')

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
    period: str = Query("daily", pattern="^(daily|weekly|monthly|5min|15min|30min|60min)$"),
    start_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    indicators: bool = Query(True),
    ma_periods: str = Query("5,10,20,60", description="均线周期，逗号分隔"),
):
    """获取K线数据

    支持周期: daily, weekly, monthly, 5min, 15min, 30min, 60min
    日/周/月使用双源校验，分钟级优先从 TDX 缓存读取，备用 AKShare。
    """
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        if period in ("5min", "15min", "30min", "60min"):
            # 分钟级默认取最近30天
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        else:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    # 分钟级K线：优先从 TDX 缓存读取，备用 AKShare
    if period in ("5min", "15min", "30min", "60min"):
        period_map = {"5min": "5m", "15min": "15m", "30min": "30m", "60min": "60m"}
        tdx_period = period_map[period]

        # 尝试从 TDX 缓存读取
        from data.cache import get_kline, save_kline
        df = get_kline(symbol, "tdx", start_date=start_date, end_date=end_date, period=tdx_period)

        source = "tdx"
        if df is None or df.empty:
            # TDX 无数据，降级到 AKShare
            source = "akshare"
            minute_num = tdx_period.replace("m", "")  # "5m" -> "5", "15m" -> "15"
            df = akshare_fetcher.get_minute_kline(symbol, minute_num, start_date, end_date)

        if df is None or df.empty:
            return KlineResponse(
                symbol=symbol, period=period, data=[], source=source,
                status="failed", message="获取分钟级数据失败"
            )

        # 缓存分钟级数据（如果是 AKShare 拉取的）
        if source == "akshare":
            save_kline(symbol, "akshare", df, period=period)

        # 准备返回数据
        data_list = []
        for _, row in df.iterrows():
            # kline_cache 字段名是小写，AKShare 也是
            td = str(row.get("trade_date", ""))
            if not td:
                continue
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
            source=source,
            status="ok",
            name=name,
            message=f"分钟级K线 (source={source}, period={tdx_period})，共 {len(data_list)} 条",
        )

    # 日/周/月 - 优先从 sequoia.db 读取日线
    kline_data = None
    sequoia_stale = False
    if period == "daily":
        try:
            from data.sequoia_engine import get_daily_kline
            sq_data = get_daily_kline(symbol, start_date, end_date)
            if sq_data:
                # 检查 sequoia 数据是否缺少最新交易日
                latest_sq = max(r["date"] for r in sq_data)
                expected = datetime.now().date()
                if expected.weekday() >= 5:  # 周六/日 → 回退到上周五
                    expected = expected - timedelta(days=expected.weekday() - 4)
                if latest_sq < expected.strftime("%Y-%m-%d"):
                    sequoia_stale = True
                    logger.info(f"[Kline] {symbol}: sequoia 最新 {latest_sq}, 缺 {expected}, 走 baostock fallback")
                else:
                    kline_data = sq_data
        except Exception:
            pass

    # sequoia 旧了也 fallback 到双源校验，但保留 sequoia 数据作为历史补充
    _sequoia_backup = None
    if sequoia_stale:
        try:
            from data.sequoia_engine import get_daily_kline
            _sequoia_backup = get_daily_kline(symbol, start_date, end_date)
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

        # 如果 sequoia 有历史数据但缺最新日，合并补充历史部分
        if _sequoia_backup:
            try:
                backup_dates = set(str(d)[:10] for d in df["trade_date"])
                extra_rows = [r for r in _sequoia_backup if r["date"] not in backup_dates]
                if extra_rows:
                    import pandas as pd
                    extra_df = pd.DataFrame(extra_rows)
                    if "date" in extra_df.columns:
                        extra_df = extra_df.rename(columns={"date": "trade_date"})
                    extra_df["trade_date"] = pd.to_datetime(extra_df["trade_date"])
                    # 金额列名兼容
                    if "turnover" in extra_df.columns and "amount" not in extra_df.columns:
                        extra_df = extra_df.rename(columns={"turnover": "amount"})
                    df = pd.concat([df, extra_df], ignore_index=True)
                    df = df.sort_values("trade_date").drop_duplicates(subset=["trade_date"])
            except Exception as e:
                logger.warning(f"[Kline] 合并 sequoia 历史数据失败: {e}")

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
        # 解析自定义 MA 参数
        ma_list = [int(p.strip()) for p in ma_periods.split(",") if p.strip().isdigit()]
        ind_dict = calc_all_indicators(df, ma_periods=ma_list if ma_list else None)

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


@router.get("/cr-indicator/{symbol}")
async def get_cr_indicator(symbol: str, limit: int = 60):
    """获取某只股票的 CR 指标日线数据"""
    from data.cache import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """SELECT trade_date, cr, cr_ma1, cr_ma2, cr_ma3
           FROM stock_cr_indicator
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
                "cr": r[1],
                "ma1": r[2],
                "ma2": r[3],
                "ma3": r[4],
            }
            for r in rows
        ]
    }


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

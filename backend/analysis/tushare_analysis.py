"""Tushare 数据分析模块 - 适配当前积分权限

当前可用接口 (基础积分):
  - stock_basic, stock_company: 公司基本信息
  - daily, pro_bar: 日行情 + 均线

不可用 (需要更高积分):
  - income, balancesheet, cashflow: 财报
  - fina_indicator: 财务指标
  - moneyflow, moneyflow_hsgt: 资金流
  - daily_basic: 每日基本面
  - express, forecast: 业绩快报/预告
"""
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from analysis.fundamentals import get_fundamental_summary

import os

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    ts = None
    TUSHARE_AVAILABLE = False

TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN")
_pro = None


def _get_pro():
    global _pro
    if _pro is None:
        if not TUSHARE_AVAILABLE:
            logger.warning("Tushare 未安装，跳过")
            return None
        if not TUSHARE_TOKEN:
            logger.warning("TUSHARE_TOKEN 未设置")
            return None
        ts.set_token(TUSHARE_TOKEN)
        _pro = ts.pro_api()
    return _pro


def _safe_float(val, default=None):
    if val is None:
        return default
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return default


def _api_available(name: str) -> bool:
    """尝试探测接口是否可用"""
    # 已知可用接口白名单
    available = {"stock_basic", "stock_company", "daily"}
    return name in available


def get_tushare_analysis(symbol: str) -> dict:
    """综合获取 tushare 可提供的分析数据"""
    pro = _get_pro()
    result = {
        "financial_report": {"error": None, "note": None},
        "moneyflow": {"error": None, "note": None},
        "price_analysis": None,
        "company_info": None,
    }

    # 1. 公司基本信息 (stock_basic + stock_company, 降级到本地缓存)
    ci = _get_company_info(pro, symbol)
    if ci is None or ci.get("name") == "":
        # 降级到本地缓存
        summary = get_fundamental_summary(symbol)
        if summary:
            ci = {
                "name": summary.get("name", ""),
                "industry": summary.get("industry", ""),
                "area": "",
                "list_date": summary.get("listing_date", ""),
                "market": "",
            }
    result["company_info"] = ci

    # 2. 行情趋势分析 (daily / pro_bar)
    result["price_analysis"] = _get_price_analysis(pro, symbol)

    # 3. 财报 (不可用，提示升级)
    result["financial_report"]["note"] = (
        "当前 Tushare Token 积分不足以获取财报数据，需要更高积分。\n"
        "可访问 https://tushare.pro 查看积分方案和接口权限。"
    )
    result["financial_report"]["error"] = "积分不足"

    # 4. 资金流 (不可用，提示升级)
    result["moneyflow"]["note"] = (
        "当前 Tushare Token 积分不足以获取资金流数据，需要更高积分。\n"
        "可访问 https://tushare.pro 查看积分方案和接口权限。"
    )
    result["moneyflow"]["error"] = "积分不足"

    return result


def _get_company_info(pro, symbol: str) -> Optional[dict]:
    """获取公司基本信息"""
    try:
        # stock_basic
        basic = pro.stock_basic(ts_code=symbol)
        company_info = {}
        if basic is not None and not basic.empty:
            row = basic.iloc[0]
            company_info = {
                "name": str(row.get("name", "")),
                "industry": str(row.get("industry", "")),
                "area": str(row.get("area", "")),
                "list_date": str(row.get("list_date", "")),
                "market": str(row.get("market", "")),
            }

        # stock_company - 补充信息
        comp = pro.stock_company(ts_code=symbol)
        if comp is not None and not comp.empty:
            row = comp.iloc[0]
            company_info.update({
                "reg_capital": str(row.get("reg_capital", "")),
                "employees": _safe_float(row.get("employees")),
                "main_business": str(row.get("main_business", ""))[:200],
            })

        return company_info if company_info else None
    except Exception as e:
        logger.warning(f"公司信息获取失败 [{symbol}]: {e}")
        return None


def _get_price_analysis(pro, symbol: str) -> Optional[dict]:
    """基于日线数据的行情分析"""
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")

        # 用 pro_bar 获取含均线的日线
        df = ts.pro_bar(
            ts_code=symbol,
            start_date=start,
            end_date=end,
            ma=[5, 10, 20, 60],
        )
        if df is None or df.empty:
            df = pro.daily(ts_code=symbol, start_date=start, end_date=end)
        if df is None or df.empty:
            return None

        df = df.sort_values("trade_date", ascending=True).reset_index(drop=True)

        # 近期表现
        recent = df.tail(20)
        if len(recent) < 2:
            return None

        first_close = recent.iloc[0]["close"]
        last_close = recent.iloc[-1]["close"]
        period_return = (last_close - first_close) / first_close * 100

        # 波动率
        returns = recent["close"].pct_change().dropna()
        volatility = float(returns.std() * 100)

        # 均线多头/空头排列判断
        last_row = df.iloc[-1]
        ma5 = _safe_float(last_row.get("ma5"))
        ma10 = _safe_float(last_row.get("ma10"))
        ma20 = _safe_float(last_row.get("ma20"))

        trend = "震荡"
        if ma5 and ma10 and ma20:
            if ma5 > ma10 > ma20:
                trend = "多头排列 ↑"
            elif ma5 < ma10 < ma20:
                trend = "空头排列 ↓"
            elif ma5 > ma10 and last_close > ma5:
                trend = "短线偏多 ↗"
            elif ma5 < ma10 and last_close < ma5:
                trend = "短线偏弱 ↘"

        # 成交量分析
        avg_vol = recent["vol"].mean()
        latest_vol = recent.iloc[-1]["vol"]
        vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1

        # 区间统计
        high_20 = float(recent["high"].max())
        low_20 = float(recent["low"].min())

        return {
            "close": float(last_close),
            "period_return_20d": round(period_return, 2),
            "volatility_20d": round(volatility, 2),
            "trend": trend,
            "volume_ratio": round(vol_ratio, 2),
            "high_20d": round(high_20, 2),
            "low_20d": round(low_20, 2),
            "avg_volume_20d": round(float(avg_vol), 2),
            "latest_volume": round(float(latest_vol), 2),
            "ma5": round(float(ma5), 2) if ma5 else None,
            "ma10": round(float(ma10), 2) if ma10 else None,
            "ma20": round(float(ma20), 2) if ma20 else None,
            "data_points": len(df),
        }

    except Exception as e:
        logger.error(f"行情分析失败 [{symbol}]: {e}")
        return None

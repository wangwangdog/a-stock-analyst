"""基本面数据分析"""
from datetime import datetime
from typing import Optional

from loguru import logger

from data import akshare_fetcher
from data.cache import save_fundamentals, get_fundamentals


def get_fundamental_summary(symbol: str, use_cache: bool = True) -> Optional[dict]:
    """
    获取基本面摘要信息

    stock_individual_info_em 返回格式:
      item          value
      最新           11.49
      股票代码        000001
      股票简称         平安银行
      总股本     19405918198.0
      流通股     19405600653.0
      总市值    2.22974e+11
      流通市值  2.22970e+11
      行业            银行Ⅱ
      上市时间       19910403
    """
    if use_cache:
        cached = get_fundamentals(symbol, "summary")
        if cached:
            return cached["data"]

    info = akshare_fetcher.get_individual_info(symbol)
    if not info:
        return None

    summary = {
        "symbol": symbol,
        "name": str(info.get("股票简称", info.get("name", ""))),
        "market_cap": _parse_float(info.get("总市值", "")),
        "circulating_market_cap": _parse_float(info.get("流通市值", "")),
        "industry": str(info.get("行业", info.get("industry", ""))),
        "listing_date": str(info.get("上市时间", "")),
        "total_shares": _parse_float(info.get("总股本", "")),
        "circulating_shares": _parse_float(info.get("流通股", "")),
    }

    save_fundamentals(symbol, "summary", summary)
    return summary


def _parse_float(val) -> Optional[float]:
    """安全的 float 转换"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").replace("%", "").replace(" ", ""))
    except (ValueError, TypeError):
        return None

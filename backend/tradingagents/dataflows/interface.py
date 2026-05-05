"""
Simplified data interface for a-stock-analyst integration.
Uses the project's existing AKShare functions + direct AKShare calls.
"""

import pandas as pd
import logging
import os
import sys
from datetime import datetime, timedelta
import json

logger = logging.getLogger('agents')

# Add backend dir to path for project imports
_backend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..')
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

_CONFIG = {}

def set_config(config: dict):
    _CONFIG.update(config)


def get_china_stock_data_unified(
    ticker: str,
    start_date: str = None,
    end_date: str = None,
    period: str = "daily"
) -> str:
    """Get Chinese A-share stock data as formatted string.
    Automatically expands single-day queries to return recent data.
    """
    now = datetime.now()
    if end_date is None:
        end_date = now.strftime("%Y-%m-%d")
    
    # If only a single/very narrow date range is requested, expand to show
    # the last 120 trading days of cached data
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d") if start_date else now
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        if (d2 - d1).days < 60:
            # Expand: go back 120 trading days from end_date
            start_date = (d2 - timedelta(days=180)).strftime("%Y-%m-%d")
    except:
        if start_date is None:
            start_date = (now - timedelta(days=180)).strftime("%Y-%m-%d")

    # Try project's SQLite-cached get_daily_kline first
    try:
        import data.akshare_fetcher as akf
        df = akf.get_daily_kline(ticker, start_date, end_date)
        if df is not None and not df.empty:
            return _format_stock_data(df, ticker, max_rows=120)
    except Exception as e:
        logger.debug(f"akshare_fetcher.get_daily_kline failed for {ticker}: {e}")

    # Fallback: AKShare directly into a wider range
    try:
        import akshare as ak
        p_map = {"daily": "daily", "weekly": "weekly", "monthly": "monthly"}
        p = p_map.get(period, "daily")
        sd = start_date.replace('-', '') if start_date else None
        ed = end_date.replace('-', '') if end_date else None
        adf = ak.stock_zh_a_hist(symbol=ticker, period=p,
                                  start_date=sd, end_date=ed,
                                  adjust="qfq")
        if adf is not None and not adf.empty:
            return _format_stock_data(adf, ticker, max_rows=120)
    except Exception as e:
        logger.error(f"Failed to get stock data for {ticker}: {e}")

    # Last resort: any data we have
    try:
        import data.akshare_fetcher as akf
        df = akf.get_daily_kline(ticker)
        if df is not None and not df.empty:
            return _format_stock_data(df, ticker, max_rows=60)
    except Exception as e2:
        logger.error(f"Last resort also failed for {ticker}: {e2}")

    return f"无法获取股票 {ticker} 的数据"


def get_china_stock_info_unified(ticker: str) -> str:
    """Get Chinese stock basic info."""
    try:
        import akshare as ak
        df = ak.stock_individual_info_em(symbol=ticker)
        if df is not None and not df.empty:
            info = {}
            for _, row in df.iterrows():
                info[str(row['item']).strip()] = str(row['value']).strip()
            name = info.get('股票简称', info.get('name', '未知'))
            industry = info.get('行业', info.get('industry', '未知'))
            return f"股票名称: {name}\n股票代码: {ticker}\n行业: {industry}\n市场: A股"
    except Exception as e:
        logger.error(f"Failed to get stock info for {ticker}: {e}")
    return f"股票名称: 未知\n股票代码: {ticker}\n市场: A股"


def get_china_market_overview() -> str:
    """Get China A-share market overview."""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            up = len(df[df['涨跌幅'] > 0]) if '涨跌幅' in df.columns else 0
            down = len(df[df['涨跌幅'] < 0]) if '涨跌幅' in df.columns else 0
            total = len(df)
            return (
                f"A股市场概况：\n"
                f"总股票数: {total}\n"
                f"上涨: {up}\n"
                f"下跌: {down}\n"
                f"日期: {datetime.now().strftime('%Y-%m-%d')}"
            )
    except Exception:
        pass
    return "无法获取A股市场概况数据"


def get_chinese_social_sentiment(ticker: str) -> str:
    return f"股票 {ticker} 暂无实时社交媒体情绪数据"


def get_google_news(ticker: str, company_name: str = None) -> str:
    name = company_name or ticker
    return f"未找到关于 {name} 的最新新闻数据"


def get_realtime_stock_news(ticker: str) -> str:
    return f"未找到 {ticker} 的实时新闻"


def get_china_fundamentals(ticker: str) -> str:
    """Get China A-share fundamentals."""
    try:
        import data.akshare_fetcher as akf
        result = akf.get_financial_report(ticker)
        if result and isinstance(result, dict):
            lines = [f"基本面数据: {ticker}"]
            for k, v in result.items():
                lines.append(f"  {k}: {v}")
            return "\n".join(lines)
    except Exception:
        pass
    try:
        import akshare as ak
        df = ak.stock_financial_abstract_ths(symbol=ticker)
        if df is not None and not df.empty:
            return df.to_string(index=False)
    except Exception:
        pass
    return f"无法获取 {ticker} 的基本面数据"


def get_stockstats_indicators_report(ticker: str) -> str:
    try:
        from analysis.indicators import calc_all_indicators
        result = calc_all_indicators(ticker)
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed to get indicators for {ticker}: {e}")
    return f"无法计算 {ticker} 的技术指标"


def _format_stock_data(df: pd.DataFrame, ticker: str, max_rows: int = 60) -> str:
    """Format stock dataframe to string."""
    try:
        date_col = 'date' if 'date' in df.columns else 'trade_date'
        if date_col not in df.columns:
            date_col = '日期' if '日期' in df.columns else df.columns[0]

        df = df.sort_values(date_col, ascending=False).head(max_rows)

        lines = [f"股票代码: {ticker}"]
        for _, row in df.iterrows():
            d = row.get(date_col, '')
            close = row.get('close', row.get('收盘', row.get('Close', '')))
            high = row.get('high', row.get('最高', row.get('High', '')))
            low = row.get('low', row.get('最低', row.get('Low', '')))
            vol = row.get('volume', row.get('成交量', row.get('Volume', '')))
            open_ = row.get('open', row.get('开盘', row.get('Open', '')))
            pct = row.get('pct_change', row.get('涨跌幅', ''))
            lines.append(f"日期:{d} 开盘:{open_} 收盘:{close} 最高:{high} 最低:{low} 成交量:{vol} 涨跌幅:{pct}")

        return "\n".join(lines)
    except Exception as e:
        return f"股票 {ticker} 数据格式错误: {e}"

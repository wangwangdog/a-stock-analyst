"""AKShare 数据获取"""
import time
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from config import REQUEST_INTERVAL

# 兼容 akshare 不同版本的导入方式
try:
    import akshare as ak
except ImportError:
    ak = None


def available() -> bool:
    return ak is not None


def _rate_limit():
    time.sleep(REQUEST_INTERVAL)


def get_stock_list() -> pd.DataFrame:
    """获取A股股票列表"""
    if not available():
        return pd.DataFrame()
    try:
        _rate_limit()
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            df.columns = [c.lower() for c in df.columns]
            return df
    except Exception as e:
        logger.warning(f"[AKShare] 获取股票列表失败: {e}")
    return pd.DataFrame()


def get_daily_kline(symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """获取日K线，默认最近200个自然日(约140交易日)"""
    if not available():
        return None
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=200)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    _start = start_date.replace("-", "") if start_date else None
    _end = end_date.replace("-", "") if end_date else None
    try:
        _rate_limit()
        df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                start_date=_start, end_date=_end,
                                adjust="qfq", timeout=10)  # 前复权
        if df is not None and not df.empty:
            # 统一列名
            df = df.rename(columns={
                "日期": "trade_date",
                "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
                "振幅": "amplitude", "涨跌幅": "pct_change",
                "涨跌额": "change", "换手率": "turnover",
            })
            return df
    except Exception as e:
        logger.warning(f"[AKShare] 获取 {symbol} K线失败: {e}")
    return None


def _fix_date_params(start_date, end_date):
    """统一日期格式处理"""
    # 如果用户传入了带横线的日期格式(如2026-04-01)，转换为AKShare兼容格式
    _start = start_date.replace("-", "") if start_date else None
    _end = end_date.replace("-", "") if end_date else None
    return _start, _end


def get_weekly_kline(symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """获取周K线，默认最近140个自然日(约20周)"""
    if not available():
        return None
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=140)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    _start, _end = _fix_date_params(start_date, end_date)
    try:
        _rate_limit()
        df = ak.stock_zh_a_hist(symbol=symbol, period="weekly",
                                start_date=_start, end_date=_end,
                                adjust="qfq", timeout=10)
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "trade_date",
                "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
            })
            return df
    except Exception as e:
        logger.warning(f"[AKShare] 获取 {symbol} 周K失败: {e}")
    return None


def get_monthly_kline(symbol: str, start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """获取月K线，默认最近365天"""
    if not available():
        return None
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    _start, _end = _fix_date_params(start_date, end_date)
    try:
        _rate_limit()
        df = ak.stock_zh_a_hist(symbol=symbol, period="monthly",
                                start_date=_start, end_date=_end,
                                adjust="qfq", timeout=10)
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "trade_date",
                "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
            })
            return df
    except Exception as e:
        logger.warning(f"[AKShare] 获取 {symbol} 月K失败: {e}")
    return None


def get_financial_report(symbol: str) -> Optional[dict]:
    """获取财务数据"""
    if not available():
        return None
    try:
        result = {}

        # 利润表
        _rate_limit()
        try:
            df = ak.stock_lrb_em(symbol=symbol)
            if df is not None and not df.empty:
                result["income"] = df.to_dict(orient="records")
        except Exception:
            pass

        # 资产负债表
        _rate_limit()
        try:
            df = ak.stock_zcfz_em(symbol=symbol)
            if df is not None and not df.empty:
                result["balance"] = df.to_dict(orient="records")
        except Exception:
            pass

        # 现金流量
        _rate_limit()
        try:
            df = ak.stock_xjll_em(symbol=symbol)
            if df is not None and not df.empty:
                result["cashflow"] = df.to_dict(orient="records")
        except Exception:
            pass

        return result if result else None
    except Exception as e:
        logger.warning(f"[AKShare] 获取 {symbol} 财报失败: {e}")
    return None


def get_individual_info(symbol: str) -> Optional[dict]:
    """获取个股基本信息（市值、行业等）"""
    if not available():
        return None
    try:
        _rate_limit()
        df = ak.stock_individual_info_em(symbol=symbol, timeout=10)
        if df is not None and not df.empty:
            info = {}
            for _, row in df.iterrows():
                key = str(row.iloc[0]).strip()
                val = row.iloc[1]
                info[key] = val
            return info
    except Exception as e:
        logger.warning(f"[AKShare] 获取 {symbol} 个股信息失败: {e}")
    return None


def get_minute_kline(symbol: str, period: str = "15", start_date: str = None, end_date: str = None) -> Optional[pd.DataFrame]:
    """获取分钟级K线数据 (15/30/60分钟)，默认最近30天

    Args:
        symbol: 股票代码，如 "000001"
        period: 分钟级别 "15", "30", "60"
        start_date: 起始日期
        end_date: 结束日期
    """
    if not available():
        return None
    if period not in ("15", "30", "60"):
        logger.warning(f"[AKShare] 不支持的分钟级别: {period}")
        return None
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    _start = start_date.replace("-", "") if start_date else None
    _end = end_date.replace("-", "") if end_date else None
    try:
        _rate_limit()
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol, period=period,
            start_date=_start, end_date=_end
        )
        if df is not None and not df.empty:
            # 统一列名: 时间, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅
            df = df.rename(columns={
                "时间": "trade_date",
                "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
                "振幅": "amplitude", "涨跌幅": "pct_change",
            })
            # 确保 trade_date 是字符串
            df["trade_date"] = df["trade_date"].astype(str)
            return df
    except Exception as e:
        logger.warning(f"[AKShare] 获取 {symbol} 分钟K线(period={period})失败: {e}")
    return None


def get_all_spot() -> pd.DataFrame:
    """获取全部A股实时行情（用于筛选）"""
    if not available():
        return pd.DataFrame()
    try:
        _rate_limit()
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            # 统一列名
            col_map = {
                "代码": "symbol", "名称": "name",
                "最新价": "price", "涨跌幅": "pct_change",
                "涨跌额": "change", "成交量": "volume",
                "成交额": "amount", "振幅": "amplitude",
                "最高": "high", "最低": "low",
                "今开": "open", "昨收": "prev_close",
                "量比": "volume_ratio", "换手率": "turnover",
                "市盈率-动态": "pe", "市净率": "pb",
                "总市值": "market_cap", "流通市值": "circulating_market_cap",
                "60日涨跌幅": "pct_60d", "年初至今涨跌幅": "pct_ytd",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            return df
    except Exception as e:
        logger.warning(f"[AKShare] 获取全部行情失败: {e}")
    return pd.DataFrame()

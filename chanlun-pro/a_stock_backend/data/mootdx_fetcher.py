"""mootdx TCP 行情 — K线 + 五档盘口 + 逐笔成交 + 财务F10

来源：a-stock-data Layer 1.1 + Layer 4
TCP 二进制协议，连通达信服务器(7709)，不封IP。
安装: pip install mootdx
"""
from typing import Optional
from datetime import datetime
import pandas as pd

try:
    from mootdx.quotes import Quotes
    _client = None
    _HAS_MOOTDX = True
except ImportError:
    _client = None
    _HAS_MOOTDX = False


def _get_client():
    global _client
    if not _HAS_MOOTDX:
        return None
    if _client is None:
        try:
            _client = Quotes.factory(market='std')
        except Exception as e:
            # mootdx 连接通达信服务器失败（非交易时段或 IP 过期）
            return None
    return _client


def _market(code: str) -> int:
    """6位代码 → 市场编号: 0=深圳, 1=上海"""
    return 0 if code.startswith(("0", "3", "8")) else 1


def get_klines(symbol: str, category: int = 4, offset: int = 10) -> Optional[list]:
    """
    获取K线数据。
    category: 4=日线, 5=周线, 6=月线, 7=1分钟, 8=5分钟, 9=15分钟, 10=30分钟, 11=60分钟
    offset: 拉取多少条
    返回: [{open, close, high, low, vol, amount, datetime}, ...]
    """
    client = _get_client()
    if not client:
        return None
    try:
        df = client.bars(symbol=symbol, category=category, offset=offset)
        if df is None or df.empty:
            return None
        return df.to_dict('records')
    except Exception:
        return None


def get_klines_df(symbol: str, category: int = 4, offset: int = 10) -> Optional[pd.DataFrame]:
    """获取K线数据，返回 DataFrame"""
    client = _get_client()
    if not client:
        return None
    try:
        df = client.bars(symbol=symbol, category=category, offset=offset)
        return df
    except Exception:
        return None


def get_quotes(symbols: list[str]) -> Optional[list]:
    """
    获取实时报价（五档盘口）。
    symbols: ["688017", "300476"]
    返回列表，每个元素含 price, open, high, low, last_close,
             bid1~bid5, ask1~ask5, bid_vol1~bid_vol5, ask_vol1~ask_vol5,
             vol, amount, servertime
    """
    client = _get_client()
    if not client:
        return None
    try:
        return client.quotes(symbol=symbols)
    except Exception:
        return None


def get_transactions(symbol: str, date: str = None) -> Optional[list]:
    """
    获取逐笔成交数据。
    date: 格式 YYYYMMDD，默认当天
    返回: [{time, price, vol, num, buyorsell(0买/1卖/2中性)}, ...]
    非交易时间返回空。
    """
    client = _get_client()
    if not client:
        return None
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    try:
        df = client.transaction(symbol=symbol, date=date)
        if df is None or df.empty:
            return None
        return df.to_dict('records')
    except Exception:
        return None


def get_finance(symbol: str) -> Optional[dict]:
    """
    获取财务快照（37字段季报数据）。
    返回: {liutongguben, zongguben, eps, bvps, roe, profit, income, ...}
    """
    client = _get_client()
    if not client:
        return None
    try:
        fin = client.finance(symbol=symbol)
        if fin is None or fin.empty:
            return None
        return fin.iloc[0].to_dict()
    except Exception:
        return None


def get_f10(symbol: str, category: str = "公司概况") -> Optional[str]:
    """
    获取F10文本资料。
    category: 最新提示, 公司概况, 财务分析, 股东研究, 股本结构,
              资本运作, 业内点评, 行业分析, 公司大事
    """
    client = _get_client()
    if not client:
        return None
    try:
        return client.F10(symbol=symbol, name=category)
    except Exception:
        return None


def available() -> bool:
    return _HAS_MOOTDX

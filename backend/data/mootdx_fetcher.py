"""mootdx TCP 行情 — K 线 + 五档盘口 + 逐笔成交 + 财务 F10

来源：a-stock-data Layer 1.1 + Layer 4
TCP 二进制协议，连通达信服务器 (7709)，不封 IP。
安装：pip install mootdx

注意：mootdx 需要通达信服务器 IP，默认使用自动发现。如果自动发现失败，
需要手动配置 MOOTDX_SERVER 环境变量或更新此文件。
"""
from typing import Optional
from datetime import datetime
import pandas as pd
import os

try:
    from mootdx.quotes import StdQuotes
    _client = None
    _HAS_MOOTDX = True
except ImportError:
    _client = None
    _HAS_MOOTDX = False

# 默认服务器配置（通达信标准端口 7709）
# 如果自动发现失败，可以尝试以下地址之一：
MOOTDX_SERVER = os.environ.get('MOOTDX_SERVER', None)


def _get_client():
    global _client
    if not _HAS_MOOTDX:
        return None
    if _client is None:
        try:
            if MOOTDX_SERVER:
                # 从环境变量解析 server:port
                host, port = MOOTDX_SERVER.split(':')
                _client = StdQuotes(server=(host, int(port)), timeout=10)
            else:
                # 尝试自动发现
                _client = StdQuotes(bestip=True, timeout=10)
        except Exception as e:
            # mootdx 连接通达信服务器失败（非交易时段或 IP 过期）
            return None
    return _client


def _market(code: str) -> int:
    """6 位代码 → 市场编号：0=深圳，1=上海"""
    return 0 if code.startswith(("0", "3", "8")) else 1


def get_klines(symbol: str, category: int = 4, offset: int = 10) -> Optional[list]:
    """
    获取 K 线数据。
    category: 4=日线，5=周线，6=月线，7=1 分钟，8=5 分钟，9=15 分钟，10=30 分钟，11=60 分钟
    offset: 拉取多少条
    返回：[{open, close, high, low, vol, amount, datetime}, ...]
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
    """获取 K 线数据，返回 DataFrame"""
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
    返回：[{time, price, vol, num, buyorsell(0 买/1 卖/2 中性)}, ...]
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
    获取财务快照（37 字段季报数据）。
    返回：{liutongguben, zongguben, eps, bvps, roe, profit, income, ...}
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
    获取 F10 文本资料。
    category: 最新提示，公司概况，财务分析，股东研究，股本结构，
              资本运作，业内点评，行业分析，公司大事
    """
    client = _get_client()
    if not client:
        return None
    try:
        return client.F10(symbol=symbol, name=category)
    except Exception:
        return None


def available() -> bool:
    """检查 mootdx 是否可用（已安装 + 能连接）"""
    if not _HAS_MOOTDX:
        return False
    try:
        client = _get_client()
        return client is not None
    except:
        return False

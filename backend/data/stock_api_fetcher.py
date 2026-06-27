"""
stock-api 风格 HTTP 数据获取器
直接调用腾讯/东方财富/新浪 HTTP 行情接口（纯 Python，无需 Node.js）
参考: https://github.com/zhangxiangliang/stock-api
"""
import time
from typing import Optional
from datetime import datetime, timedelta

import pandas as pd
import requests
from loguru import logger

# 请求超时
_REQUEST_TIMEOUT = 10

# 代码前缀
_CODE_MAP = {
    "6": "sh", "9": "sh",  # 上海
    "0": "sz", "3": "sz",  # 深圳
    "8": "bj", "4": "bj",  # 北交所
}


def _normalize_code(symbol: str) -> str:
    """标准化为腾讯/新浪格式: '600519' → 'sh600519'"""
    symbol = symbol.strip().upper()
    for prefix in ("SH", "SZ", "BJ", "SH.", "SZ.", "BJ."):
        symbol = symbol.replace(prefix, "")
    if symbol.startswith(("6", "9")):
        return f"sh{symbol}"
    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    if symbol.startswith(("8", "4")):
        return f"bj{symbol}"
    return symbol


def _http_get(url: str, headers: dict = None, encoding: str = "utf-8") -> Optional[str]:
    """公共 HTTP GET 请求"""
    try:
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if headers:
            default_headers.update(headers)
        resp = requests.get(url, headers=default_headers, timeout=_REQUEST_TIMEOUT)
        resp.encoding = encoding
        return resp.text
    except Exception as e:
        logger.debug(f"[stock-api] HTTP GET 失败 {url[:60]}: {e}")
        return None


# ══════════════════════════════════════════════
# 腾讯行情 (qt.gtimg.cn)
# ══════════════════════════════════════════════

def _fetch_tencent(symbol: str) -> Optional[dict]:
    """腾讯实时行情: https://qt.gtimg.cn/q=sh600519"""
    code = _normalize_code(symbol)
    url = f"https://qt.gtimg.cn/q={code}"
    text = _http_get(url, encoding="gbk")
    if not text or "=" not in text:
        return None
    try:
        row = text.split("=", 1)[1].strip(' "\n;')
        parts = row.split("~")
        if len(parts) < 40:
            return None
        return {
            "name": parts[1],
            "code": code,
            "price": _f(parts[3]),
            "prev_close": _f(parts[4]),
            "open": _f(parts[5]),
            "volume": _f(parts[6]),
            "high": _f(parts[33]),
            "low": _f(parts[34]),
            "amount": _f(parts[37]),
        }
    except Exception as e:
        logger.debug(f"[stock-api] 腾讯解析失败 {symbol}: {e}")
        return None


def _fetch_tencent_kline(symbol: str, count: int = 320) -> Optional[pd.DataFrame]:
    """腾讯历史K线: https://web.ifzq.gtimg.cn/appstock/app/kline/kline"""
    code = _normalize_code(symbol)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},day,,,{count}"
    resp = _http_get(url)
    if not resp:
        return None
    try:
        import json
        data = json.loads(resp)
        api_code = list(data.get("data", {}).keys())[0] if data.get("data") else None
        if not api_code:
            return None
        rows = data["data"][api_code].get("qfqday", []) or data["data"][api_code].get("day", [])
        if not rows:
            return None
        records = []
        for r in rows:
            records.append({
                "trade_date": r[0],
                "open": float(r[1]), "close": float(r[2]),
                "high": float(r[3]), "low": float(r[4]),
                "volume": float(r[5]) if len(r) > 5 else 0,
            })
        df = pd.DataFrame(records)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    except Exception as e:
        logger.debug(f"[stock-api] 腾讯K线解析失败 {symbol}: {e}")
        return None


# ══════════════════════════════════════════════
# 新浪行情 (hq.sinajs.cn)
# ══════════════════════════════════════════════

def _fetch_sina(symbol: str) -> Optional[dict]:
    """新浪实时行情: https://hq.sinajs.cn/list=sh600519"""
    code = _normalize_code(symbol)
    url = f"https://hq.sinajs.cn/list={code}"
    text = _http_get(url, headers={"Referer": "https://finance.sina.com.cn"}, encoding="gbk")
    if not text or "=" not in text:
        return None
    try:
        row = text.split("=", 1)[1].strip(' "\n;')
        parts = row.split(",")
        if len(parts) < 30:
            return None
        return {
            "name": parts[0],
            "code": code,
            "open": _f(parts[1]),
            "prev_close": _f(parts[2]),
            "price": _f(parts[3]),
            "high": _f(parts[4]),
            "low": _f(parts[5]),
            "volume": _f(parts[8]),
            "amount": _f(parts[9]),
        }
    except Exception as e:
        logger.debug(f"[stock-api] 新浪解析失败 {symbol}: {e}")
        return None


# ══════════════════════════════════════════════
# 东方财富行情 (push2.eastmoney.com)
# ══════════════════════════════════════════════

def _em_secid(symbol: str) -> str:
    """东方财富 secid 格式"""
    code = symbol.strip()
    if code.startswith(("6", "9")):
        return f"1.{code}"
    return f"0.{code}"


def _fetch_eastmoney(symbol: str) -> Optional[dict]:
    """东方财富实时行情"""
    secid = _em_secid(symbol)
    url = (f"https://push2.eastmoney.com/api/qt/stock/get"
           f"?secid={secid}&fields=f43,f44,f45,f57,f58,f60,f170,f46,f47,f48,f50,f168")
    resp = _http_get(url, headers={"Referer": "https://quote.eastmoney.com/"})
    if not resp:
        return None
    try:
        import json
        data = json.loads(resp).get("data")
        if not data or not data.get("f57"):
            return None
        return {
            "name": data.get("f58", ""),
            "code": symbol,
            "price": _f(data.get("f43")),
            "high": _f(data.get("f44")),
            "low": _f(data.get("f45")),
            "prev_close": _f(data.get("f60")),
            "open": _f(data.get("f46")),
            "volume": _f(data.get("f47")),
            "amount": _f(data.get("f48")),
            "turnover": _f(data.get("f168")),
        }
    except Exception as e:
        logger.debug(f"[stock-api] 东方财富行情解析失败 {symbol}: {e}")
        return None


def _fetch_eastmoney_kline(symbol: str, count: int = 320, fqt: str = "1") -> Optional[pd.DataFrame]:
    """东方财富历史K线"""
    secid = _em_secid(symbol)
    url = (f"https://push2his.eastmoney.com/api/qt/stock/kline/get"
           f"?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
           f"&ut=7eea3edcaed734bea9cbfc24409ed989"
           f"&klt=101&fqt={fqt}&secid={secid}&beg=19700101&end=20500101&lmt={count}")
    resp = _http_get(url, headers={"Referer": "https://quote.eastmoney.com/"})
    if not resp:
        return None
    try:
        import json
        data = json.loads(resp).get("data")
        if not data or not data.get("klines"):
            return None
        records = []
        for line in data["klines"]:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            records.append({
                "trade_date": parts[0],
                "open": float(parts[1]), "close": float(parts[2]),
                "high": float(parts[3]), "low": float(parts[4]),
                "volume": float(parts[5]),
            })
        df = pd.DataFrame(records)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    except Exception as e:
        logger.debug(f"[stock-api] 东方财富K线解析失败 {symbol}: {e}")
        return None


# ══════════════════════════════════════════════
# 公开接口（与 akshare_fetcher / baostock_fetcher 一致）
# ══════════════════════════════════════════════

_STOCK_SOURCES = [
    ("tencent", _fetch_tencent),
    ("eastmoney", _fetch_eastmoney),
    ("sina", _fetch_sina),
]


def available() -> bool:
    """永远是 True（HTTP 接口无需安装）"""
    return True


def get_realtime_quote(symbol: str) -> Optional[dict]:
    """获取实时行情，自动兜底 tencent → eastmoney → sina"""
    for name, fn in _STOCK_SOURCES:
        try:
            result = fn(symbol)
            if result:
                result["source"] = name
                return result
        except Exception as e:
            logger.debug(f"[stock-api] {name} 失败: {e}")
    return None


def get_daily_kline(symbol: str, start_date: str = None, end_date: str = None,
                    count: int = 365) -> Optional[pd.DataFrame]:
    """获取日K线，自动兜底十档 → 东方财富"""
    # 先尝试腾讯
    df = _fetch_tencent_kline(symbol, count)
    # 腾讯不行就东方财富
    if df is None or df.empty:
        df = _fetch_eastmoney_kline(symbol, count)

    if df is None or df.empty:
        return None

    # 按日期筛选
    if start_date:
        df = df[df["trade_date"] >= start_date]
    if end_date:
        df = df[df["trade_date"] <= end_date]

    return df if not df.empty else None


def get_stock_list() -> pd.DataFrame:
    """暂不支持通过 stock-api 获取股票列表（返回空）"""
    return pd.DataFrame()


def search_stocks(keyword: str) -> list:
    """搜索股票（东方财富搜索API）"""
    url = (f"https://searchapi.eastmoney.com/api/suggest/get"
           f"?input={keyword}&type=14&token=D43BF722C8E33BDC906FB84D85E326E8")
    resp = _http_get(url)
    if not resp:
        return []
    try:
        import json
        data = json.loads(resp)
        items = data.get("QuotationCodeTable", {}).get("Data", [])
        results = []
        for item in items:
            mkt = item.get("MktNum", "")
            code = item.get("Code", "")
            if not code:
                continue
            prefix = "SH" if mkt == "1" else "SZ" if mkt == "0" else ""
            if prefix:
                results.append({
                    "symbol": f"{prefix}{code}",
                    "code": code,
                    "name": item.get("Name", ""),
                })
        return results
    except Exception:
        return []


def _f(val) -> float:
    """安全转float"""
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0

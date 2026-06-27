"""
个股补充数据端点 — 整合 a-stock-data 能力
Layer 1: 腾讯实时行情（PE/PB/市值/换手率，不封IP）
Layer 3+: 东财/同花顺/巨潮（按需）

路由: /api/v1/stock-supplement/{symbol}
"""
import urllib.request
import json
import re
from typing import Optional
from datetime import datetime

from fastapi import APIRouter
from loguru import logger
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1", tags=["supplement"])


class SupplementResponse(BaseModel):
    symbol: str
    name: str
    timestamp: str
    # Layer 1 - 腾讯实时行情
    price: Optional[float] = None
    last_close: Optional[float] = None
    change_pct: Optional[float] = None
    change_amt: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    pe_ttm: Optional[float] = None
    pe_static: Optional[float] = None
    pb: Optional[float] = None
    mcap_yi: Optional[float] = None          # 总市值(亿)
    float_mcap_yi: Optional[float] = None    # 流通市值(亿)
    turnover_pct: Optional[float] = None     # 换手率%
    amplitude_pct: Optional[float] = None    # 振幅%
    limit_up: Optional[float] = None         # 涨停价
    limit_down: Optional[float] = None       # 跌停价
    vol_ratio: Optional[float] = None        # 量比
    amount_wan: Optional[float] = None       # 成交额(万)
    # Layer 6 - 东财个股基本面
    industry: Optional[str] = None
    total_shares: Optional[float] = None     # 总股本
    float_shares: Optional[float] = None     # 流通股
    listing_date: Optional[str] = None       # 上市日期
    # 状态
    status: str = "ok"
    message: str = ""


def _tencent_prefixed(symbol: str) -> str:
    """归一化腾讯前缀"""
    if "." not in symbol:
        return symbol
    mkt, code = symbol.split(".")
    prefix_map = {"SH": "sh", "SZ": "sz", "BJ": "bj"}
    pref = prefix_map.get(mkt, mkt.lower())
    return f"{pref}{code}"


def fetch_tencent_quote(codes: list[str]) -> dict[str, dict]:
    """从腾讯财经拉实时行情（PE/PB/市值，不封IP）
    
    参考 a-stock-data Layer 1.2
    """
    prefixed = [_tencent_prefixed(c) for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    req.add_header("Referer", "https://qt.gtimg.cn/")
    
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception as e:
        logger.warning(f"[TencentQuote] 请求失败: {e}")
        return {}
    
    result = {}
    for line in data.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line or '"' not in line:
            continue
        try:
            key = line.split("=")[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
        except (IndexError, ValueError):
            continue
        if len(vals) < 53:
            continue
        
        # key is like 'sz000001', strip 2-char prefix 'sz'/'sh'/'bj'
        bare_key = key[2:] if len(key) > 2 else key
        
        def _f(i):
            try:
                v = vals[i]
                return float(v) if v else 0.0
            except (IndexError, ValueError, TypeError):
                return None
        
        result[bare_key] = {
            "name": vals[1] if len(vals) > 1 else "",
            "price": _f(3),
            "last_close": _f(4),
            "open": _f(5),
            "high": _f(33),
            "low": _f(34),
            "change_amt": _f(31),
            "change_pct": _f(32),
            "amount_wan": _f(37),
            "turnover_pct": _f(38),
            "pe_ttm": _f(39),
            "amplitude_pct": _f(43),
            "mcap_yi": _f(44),
            "float_mcap_yi": _f(45),
            "pb": _f(46),
            "limit_up": _f(47),
            "limit_down": _f(48),
            "vol_ratio": _f(49),
            "pe_static": _f(52),
        }
    return result


def _bare_code(symbol: str) -> str:
    """SZ.000001 → 000001"""
    if "." in symbol:
        return symbol.split(".")[1]
    return symbol


def fetch_eastmoney_basic(code: str) -> dict:
    """东财个股基本面（行业/股本/上市日期）
    
    参考 a-stock-data Layer 6.3
    """
    url = (
        "https://push2.eastmoney.com/api/qt/stock/get?"
        f"secid={code}&fields=f57,f58,f84,f85,f100,f116,f117,f162,f167,f168"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://quote.eastmoney.com/",
            },
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))
        d = data.get("data", {}) or {}
        # f57=代码, f58=名称, f84=总股本, f85=流通股
        # f100=行业, f116=总市值, f117=流通市值
        # f162=f167=流通市值, f168=上市日期
        result = {
            "industry": d.get("f100", ""),
            "total_shares": d.get("f84"),
            "float_shares": d.get("f85"),
            "listing_date": str(d.get("f168", "")) if d.get("f168") else None,
        }
        return result
    except Exception:
        return {}


@router.get("/stock-supplement/{symbol}", response_model=SupplementResponse)
async def get_stock_supplement(symbol: str):
    """个股补充数据 — 腾讯实时行情 + 东财基本面"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. 腾讯实时行情
    quotes = fetch_tencent_quote([symbol])
    q = quotes.get(_bare_code(symbol), {})
    
    name = q.get("name", "")
    if not name:
        # 尝试从 kline_cache 拿名称
        try:
            import sqlite3
            conn = sqlite3.connect("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")
            cur = conn.execute(
                "SELECT name FROM kline_cache WHERE symbol=? LIMIT 1",
                (symbol,),
            )
            row = cur.fetchone()
            if row:
                name = row[0]
            conn.close()
        except Exception:
            pass
    
    # 2. 东财基本面
    code = _bare_code(symbol)
    em_basic = {}
    if not q:
        # 腾讯没数据时才走东财
        em_basic = fetch_eastmoney_basic(code)
    
    return SupplementResponse(
        symbol=symbol,
        name=name,
        timestamp=now,
        price=q.get("price"),
        last_close=q.get("last_close"),
        change_pct=q.get("change_pct"),
        change_amt=q.get("change_amt"),
        open=q.get("open"),
        high=q.get("high"),
        low=q.get("low"),
        pe_ttm=q.get("pe_ttm"),
        pe_static=q.get("pe_static"),
        pb=q.get("pb"),
        mcap_yi=q.get("mcap_yi"),
        float_mcap_yi=q.get("float_mcap_yi"),
        turnover_pct=q.get("turnover_pct"),
        amplitude_pct=q.get("amplitude_pct"),
        limit_up=q.get("limit_up"),
        limit_down=q.get("limit_down"),
        vol_ratio=q.get("vol_ratio"),
        amount_wan=q.get("amount_wan"),
        industry=em_basic.get("industry", q.get("name", "")),
        total_shares=em_basic.get("total_shares"),
        float_shares=em_basic.get("float_shares"),
        listing_date=em_basic.get("listing_date"),
        status="ok" if q else "partial",
        message="" if q else "腾讯实时行情未获取到数据，尝试使用缓存",
    )

"""行业横向对比 — 同花顺90行业涨跌排名

来源：a-stock-data Layer 6.7
akshare + 东财 datacenter，零鉴权。
"""
import requests
import akshare as ak
from typing import Optional
from datetime import datetime

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def get_industry_ranking(source: str = "ths") -> list[dict]:
    """
    获取行业板块涨跌排名。
    source: "ths"(同花顺90行业) / "em"(东财行业) / "sina"(新浪行业)
    返回: [{industry_name, change_pct, stock_count, top_stock, ...}, ...]
    """
    if source == "ths":
        return _ths_industry()
    elif source == "em":
        return _em_industry()
    elif source == "sina":
        return _sina_industry()
    return _ths_industry()


def _ths_industry() -> list[dict]:
    """同花顺90行业"""
    try:
        df = ak.stock_board_industry_name_ths()
        if df is None or df.empty:
            return _fallback_industry()
        results = []
        for _, row in df.head(90).iterrows():
            results.append({
                "industry_name": row.get("板块名称", row.get("name", "")),
                "code": row.get("板块代码", row.get("code", "")),
                "change_pct": float(row.get("涨跌幅", row.get("change", 0)) or 0),
                "stock_count": int(row.get("股票数量", row.get("num", 0)) or 0),
                "top_stock": row.get("龙头股", row.get("top", "")),
            })
        return results
    except Exception:
        return _fallback_industry()


def _em_industry() -> list[dict]:
    """东财行业"""
    try:
        df = ak.stock_board_industry_name_em()
        if df is None or df.empty:
            return _fallback_industry()
        results = []
        for _, row in df.head(90).iterrows():
            results.append({
                "industry_name": row.get("板块名称", ""),
                "code": row.get("板块代码", ""),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "stock_count": int(row.get("股票数量", 0) or 0),
                "top_stock": row.get("龙头股", ""),
            })
        return results
    except Exception:
        return _fallback_industry()


def _sina_industry() -> list[dict]:
    """新浪行业"""
    try:
        df = ak.stock_board_industry_name_em()
        return _em_industry()
    except Exception:
        return _fallback_industry()


def _fallback_industry() -> list[dict]:
    """fallback: 东财 datacenter"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f3", "po": 1, "pz": 90, "np": 1,
        "fltt": 2, "invt": 2,
        "fs": "m:90+t:2",
        "fields": "f12,f14,f2,f3,f4,f8,f15,f16,f17,f18,f20",
        "_": int(datetime.now().timestamp() * 1000),
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        }, timeout=15)
        data = r.json()
        items = data.get("data", {}).get("diff", [])
        results = []
        for item in items:
            results.append({
                "industry_name": item.get("f14", ""),
                "code": item.get("f12", ""),
                "change_pct": float(item.get("f3", 0) or 0),
                "price": float(item.get("f2", 0) or 0),
                "amount": float(item.get("f8", 0) or 0),
                "stock_count": 0,
                "top_stock": "",
            })
        return results
    except Exception:
        return []


def get_industry_concept(code: str) -> list[dict]:
    """
    查询个股所属行业/概念板块。
    返回: [{type, name, ...}, ...]
    """
    try:
        df = ak.stock_board_industry_cons_em(symbol=code)
        results = []
        if df is not None and not df.empty:
            for _, row in df.head(30).iterrows():
                results.append({
                    "type": "industry",
                    "name": row.get("板块名称", row.get("name", "")),
                    "code": row.get("板块代码", row.get("code", "")),
                })
        return results
    except Exception:
        return []

"""龙虎榜席位 + 全市场龙虎榜

来源：a-stock-data Layer 6.4 + 6.5
东财 datacenter API，免费无key。
"""
import requests
from typing import Optional
from datetime import datetime, timedelta

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_BILLBOARD_API = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
_ALL_BILLBOARD_API = "https://push2.eastmoney.com/api/qt/clist/get"


def get_stock_billboard(code: str, start_date: str = None, end_date: str = None,
                        page: int = 1, page_size: int = 20) -> dict:
    """
    查询个股龙虎榜上榜记录。
    code: 6位股票代码
    start_date/end_date: YYYY-MM-DD, 默认近30天
    返回: {total, pages, items: [{date, code, name, reason, buy_amount, sell_amount, net_amount, ...}]}
    """
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    # 东财新API格式
    # 龙虎榜买卖汇总
    url = f"https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_LHB_MAIN_TRAIT_DETAIL",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,PURCHASE_AMOUNT,SELL_AMOUNT,NET_BUY_AMOUNT",
        "filter": f'(SECURITY_CODE="{code}")(TRADE_DATE>="{start_date}")(TRADE_DATE<="{end_date}")',
        "pageNumber": page,
        "pageSize": page_size,
        "sortTypes": -1,
        "sortColumns": "TRADE_DATE",
        "source": "HSFZ",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"}, timeout=15)
        data = r.json()
        items = data.get("result", {}).get("data", [])
        total = data.get("result", {}).get("total", 0) or 0
        results = []
        for item in items:
            results.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "trade_date": item.get("TRADE_DATE", ""),
                "buy_amount": float(item.get("PURCHASE_AMOUNT", 0) or 0),
                "sell_amount": float(item.get("SELL_AMOUNT", 0) or 0),
                "net_amount": float(item.get("NET_BUY_AMOUNT", 0) or 0),
            })
        return {"total": total, "items": results}
    except Exception as e:
        raise RuntimeError(f"查询龙虎榜失败: {e}")


def get_billboard_seats(code: str, date: str = None) -> dict:
    """
    查询龙虎榜买卖席位 TOP5。
    code: 6位股票代码
    date: YYYY-MM-DD, 默认最近一日
    返回: {buy_seats: [{rank, dept_name, buy_amount, ...}], sell_seats: [...], total_buy, total_sell, net}
    """
    if date is None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "reportName": "RPT_LHB_DETAIL",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE",
        "filter": f'(TRADE_DATE>="{date}")',
        "pageNumber": 1,
        "pageSize": 500,
        "sortTypes": -1,
        "sortColumns": "TRADE_DATE",
        "source": "HSFZ",
        "client": "WEB",
    }
    try:
        r = requests.get(_BILLBOARD_API, params=params, headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"}, timeout=15)
        data = r.json()
        all_items = data.get("result", {}).get("data", [])
        stock_items = [i for i in all_items if i.get("SECURITY_CODE", "") == code]
        return {
            "code": code,
            "items": stock_items,
            "count": len(stock_items),
        }
    except Exception as e:
        raise RuntimeError(f"查询龙虎榜席位失败: {e}")


def get_all_billboard(date: str = None, limit: int = 50) -> list[dict]:
    """
    获取全市场龙虎榜（每日全部上榜股票 + 净买额排名）。
    date: YYYY-MM-DD, 默认最近一日
    """
    if date is None:
        date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "fid": "f3",
        "po": 1,
        "pz": limit,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fs": "m:0+t:6+f:!50,m:0+t:80+f:!50,m:1+t:6+f:!50,m:1+t:80+f:!50,m:0+t:81+f:!50,m:1+t:81+f:!50",
        "fields": "f12,f14,f2,f3,f4,f8,f18,f20,f15,f16,f17",
        "_": int(datetime.now().timestamp() * 1000),
    }
    try:
        r = requests.get(_ALL_BILLBOARD_API, params=params, headers={
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/stock/tradedetail.html",
        }, timeout=15)
        data = r.json()
        inner = data.get("data") if isinstance(data, dict) else None
        items = inner.get("diff", []) if isinstance(inner, dict) else []
        results = []
        for item in items:
            results.append({
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "price": float(item.get("f2", 0) or 0),
                "change_pct": float(item.get("f3", 0) or 0),
                "amount": float(item.get("f8", 0) or 0),
                "amount_yi": round(float(item.get("f18", 0) or 0) / 1e8, 2),
                "buy_amount": float(item.get("f15", 0) or 0),
                "sell_amount": float(item.get("f16", 0) or 0),
                "net_amount": float(item.get("f17", 0) or 0),
            })
        results.sort(key=lambda x: x["net_amount"], reverse=True)
        return results
    except Exception as e:
        raise RuntimeError(f"获取全市场龙虎榜失败: {e}")

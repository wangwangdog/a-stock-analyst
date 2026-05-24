"""限售解禁日历 — 历史解禁 + 未来90天待解禁

来源：a-stock-data Layer 6.6
akshare + 东财数据，免费无key。
"""
import akshare as ak
import pandas as pd
from typing import Optional
from datetime import datetime, timedelta

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def get_upcoming_lockups(days: int = 90) -> list[dict]:
    """
    获取未来 N 天内限售解禁股票列表。
    days: 未来天数，默认90
    返回: [{code, name, release_date, count, ratio, market, ...}, ...]
    """
    try:
        df = ak.stock_lockup_reason_upcoming_em()
        if df is None or df.empty:
            return _fallback_upcoming(days)

        # 统一列名
        col_map = {
            "股票代码": "code", "股票简称": "name",
            "解禁日期": "release_date", "解禁数量(股)": "count",
            "解禁股数/总股本": "ratio",
            "解禁股数/流通A股": "ratio_to_a",
            "解禁类型": "type",
            "市场板块": "market",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

        # 筛选未来days天
        cutoff = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        if "release_date" in df.columns:
            df = df[df["release_date"] <= cutoff]

        return df.head(200).to_dict('records')
    except Exception as e:
        # fallback
        return _fallback_upcoming(days)


def _fallback_upcoming(days: int = 90) -> list:
    """akshare 不可用时的 fallback（走东财接口）"""
    import requests
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "reportName": "RPT_LOCKUP_UPCOMING",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,RELEASE_DATE,ACTUAL_COUNT,RATIO_SHARES_OUTSTANDING,LOCKUP_TYPE",
        "filter": f'(RELEASE_DATE>="{today}")(RELEASE_DATE<="{future}")',
        "pageNumber": 1,
        "pageSize": 200,
        "sortTypes": 1,
        "sortColumns": "RELEASE_DATE",
        "source": "HSFZ",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"}, timeout=15)
        data = r.json()
        items = data.get("result", {}).get("data", [])
        results = []
        for item in items:
            results.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "release_date": item.get("RELEASE_DATE", ""),
                "count": float(item.get("ACTUAL_COUNT", 0) or 0),
                "ratio": item.get("RATIO_SHARES_OUTSTANDING", ""),
                "type": item.get("LOCKUP_TYPE", ""),
            })
        return results
    except Exception:
        return []


def get_stock_lockups(code: str) -> list[dict]:
    """查询个股解禁记录"""
    try:
        df = ak.stock_lockup_reason_upcoming_em()
        if df is not None and not df.empty and "股票代码" in df.columns:
            df = df[df["股票代码"] == code]
            return df.head(50).to_dict('records')
    except Exception:
        pass
    return []


def get_historical_lockups(date: str = None) -> list[dict]:
    """
    获取某日的解禁记录。
    date: YYYY-MM-DD, 默认今天
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    import requests
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    params = {
        "reportName": "RPT_LOCKUP_HISTORY",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,RELEASE_DATE,ACTUAL_COUNT,RATIO_SHARES_OUTSTANDING,LOCKUP_TYPE",
        "filter": f'(RELEASE_DATE="{date}")',
        "pageNumber": 1,
        "pageSize": 200,
        "sortTypes": -1,
        "sortColumns": "RELEASE_DATE",
        "source": "HSFZ",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA, "Referer": "https://data.eastmoney.com/"}, timeout=15)
        data = r.json()
        items = data.get("result", {}).get("data", [])
        results = []
        for item in items:
            results.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "release_date": item.get("RELEASE_DATE", ""),
                "count": float(item.get("ACTUAL_COUNT", 0) or 0),
                "ratio": item.get("RATIO_SHARES_OUTSTANDING", ""),
                "type": item.get("LOCKUP_TYPE", ""),
            })
        return results
    except Exception:
        return []

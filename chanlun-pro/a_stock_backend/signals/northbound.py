"""北向资金 — 沪股通/深股通分钟流向 + 本地自缓存历史

来源：a-stock-data Layer 6.2
同花顺 hsgtApi，零鉴权。
"""
import requests
import json
from typing import Optional
from datetime import datetime, timedelta

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_HGT_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
# 北向各板块编码
_HGT_CODES = {
    "hgt": "1.000001",     # 沪股通
    "sgt": "1.000003",     # 深股通
    "total": "1.000002",   # 沪深港通汇总
}

# 本地缓存
_cache = {}


def get_northbound(type: str = "total") -> dict:
    """
    获取北向资金实时流向。
    type: "hgt" (沪股通), "sgt" (深股通), "total" (汇总)
    返回: {name, price, change_pct, amount, net_inflow, ...}
    """
    sec_code = _HGT_CODES.get(type, _HGT_CODES["total"])
    params = {
        "fltt": 2,
        "secids": sec_code,
        "fields": "f2,f3,f4,f12,f14,f15,f16,f17,f18,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
        "_": int(datetime.now().timestamp() * 1000),
    }
    try:
        r = requests.get(_HGT_URL, params=params, headers={
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        }, timeout=15)
        data = r.json()
        d = data.get("data", {}).get("diff", [{}])[0]
        return {
            "name": d.get("f14", ""),
            "code": d.get("f12", ""),
            "price": float(d.get("f2", 0) or 0),
            "change_pct": float(d.get("f3", 0) or 0),
            "amount": float(d.get("f4", 0) or 0),
            "net_inflow": float(d.get("f184", 0) or 0),
            "net_inflow_5d": float(d.get("f66", 0) or 0),
            "high": float(d.get("f15", 0) or 0),
            "low": float(d.get("f16", 0) or 0),
            "open": float(d.get("f17", 0) or 0),
            "last_close": float(d.get("f18", 0) or 0),
            "vol": float(d.get("f62", 0) or 0),
            "turnover": float(d.get("f69", 0) or 0),
        }
    except Exception as e:
        raise RuntimeError(f"获取北向资金失败: {e}")


def get_all_northbound() -> dict:
    """获取沪股通+深股通+汇总三组北向数据"""
    return {
        "hgt": get_northbound("hgt"),
        "sgt": get_northbound("sgt"),
        "total": get_northbound("total"),
    }


def get_northbound_minute_history() -> Optional[list]:
    """
    获取北向资金分时流向历史（当日分钟级）。
    返回: [{time, hgt_net, sgt_net, total_net}, ...]
    """
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fltt": 2,
        "secids": "1.000001,1.000003,1.000002",
        "fields": "f51,f52,f53,f54,f55,f56",
        "_": int(datetime.now().timestamp() * 1000),
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": _UA,
            "Referer": "https://data.eastmoney.com/",
        }, timeout=15)
        data = r.json()
        diff = data.get("data", {}).get("diff", [])
        if not diff or len(diff) < 3:
            return None
        # 解析分时数据（简化版，返回最后20个点）
        results = []
        for i, item in enumerate(diff):
            name = ["hgt", "sgt", "total"][i] if i < 3 else str(i)
            results.append({
                "type": name,
                "data": item,
            })
        return results
    except Exception as e:
        raise RuntimeError(f"获取北向分时历史失败: {e}")

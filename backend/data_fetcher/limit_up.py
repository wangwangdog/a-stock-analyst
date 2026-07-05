"""
打板层数据采集 — 涨停/炸板/跌停/昨涨停 + 同花顺涨停揭秘
"""
import re, json
from datetime import datetime, timedelta
import requests
from .base import em_get, UA, today_str, today_ymd


def _fmt_zt_time(t):
    if not t:
        return ""
    s = str(int(t))
    return f"{s[:2]}:{s[2:4]}:{s[4:6]}" if len(s) >= 6 else s


def _em_zt_api(endpoint: str, sort: str, date: str) -> list[dict]:
    """东财涨停板行情中心通用请求"""
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
              "Pageindex": 0, "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception as e:
        print(f"[WARN] 涨停板 {endpoint}: {e}")
        return []


def em_zt_pool(date: str = None) -> list[dict]:
    """涨停池"""
    date = date or today_ymd()
    out = []
    for p in _em_zt_api("getTopicZTPool", "fbt:asc", date):
        out.append({
            "code": p.get("c", ""), "name": p.get("n", ""),
            "price": (p.get("p", 0) or 0) / 1000,
            "pct": round(p.get("zdp", 0), 2),
            "amount": p.get("amount", 0),
            "turnover": round(p.get("hs", 0), 2),
            "limit_days": p.get("lbc", 0),
            "first_seal": _fmt_zt_time(p.get("fbt")),
            "last_seal": _fmt_zt_time(p.get("lbt")),
            "seal_fund": p.get("fund", 0),
            "break_times": p.get("zbc", 0),
            "industry": p.get("hybk", ""),
            "zt_stat": f'{(p.get("zttj") or {}).get("days","?")}天{(p.get("zttj") or {}).get("ct","?")}板',
        })
    return out


def em_zb_pool(date: str = None) -> list[dict]:
    """炸板池"""
    date = date or today_ymd()
    out = []
    for p in _em_zt_api("getTopicZBPool", "fbt:asc", date):
        out.append({
            "code": p.get("c", ""), "name": p.get("n", ""),
            "price": (p.get("p", 0) or 0) / 1000,
            "limit_price": (p.get("ztp", 0) or 0) / 1000,
            "pct": round(p.get("zdp", 0), 2),
            "turnover": round(p.get("hs", 0), 2),
            "first_seal": _fmt_zt_time(p.get("fbt")),
            "break_times": p.get("zbc", 0),
            "amplitude": round(p.get("zf", 0), 2),
            "speed": round(p.get("zs", 0), 2),
            "industry": p.get("hybk", ""),
            "zt_stat": f'{(p.get("zttj") or {}).get("days","?")}天{(p.get("zttj") or {}).get("ct","?")}板',
        })
    return out


def em_dt_pool(date: str = None) -> list[dict]:
    """跌停池"""
    date = date or today_ymd()
    out = []
    for p in _em_zt_api("getTopicDTPool", "fund:asc", date):
        out.append({
            "code": p.get("c", ""), "name": p.get("n", ""),
            "price": (p.get("p", 0) or 0) / 1000,
            "pct": round(p.get("zdp", 0), 2),
            "turnover": round(p.get("hs", 0), 2),
            "seal_fund": p.get("fund", 0),
            "last_seal": _fmt_zt_time(p.get("lbt")),
            "board_amount": p.get("fba", 0),
            "dt_days": p.get("days", 0),
            "open_times": p.get("oc", 0),
            "industry": p.get("hybk", ""),
        })
    return out


def em_yzt_pool(date: str = None) -> list[dict]:
    """昨日涨停今表现"""
    date = date or today_ymd()
    out = []
    for p in _em_zt_api("getYesterdayZTPool", "zs:desc", date):
        out.append({
            "code": p.get("c", ""), "name": p.get("n", ""),
            "price": (p.get("p", 0) or 0) / 1000,
            "pct": round(p.get("zdp", 0), 2),
            "turnover": round(p.get("hs", 0), 2),
            "amplitude": round(p.get("zf", 0), 2),
            "speed": round(p.get("zs", 0), 2),
            "y_first_seal": _fmt_zt_time(p.get("yfbt")),
            "y_limit_days": p.get("ylbc", 0),
            "industry": p.get("hybk", ""),
            "zt_stat": f'{(p.get("zttj") or {}).get("days","?")}天{(p.get("zttj") or {}).get("ct","?")}板',
        })
    return out


def ths_limit_up_pool(date: str = None) -> list[dict]:
    """同花顺涨停揭秘（涨停原因 + 封板质量）"""
    date = date or today_ymd()
    url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
    params = {"limit": 5, "date": date, "field": ""}
    headers = {"User-Agent": UA, "Referer": "https://data.10jqka.com.cn/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        stocks = (data.get("data") or {}).get("list") or []
        out = []
        for s in stocks:
            out.append({
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "price": (s.get("price") or 0),
                "pct": round(float(s.get("change_rate") or 0), 2),
                "reason": s.get("reason", ""),
                "board_type": s.get("board_form", ""),
                "seal_rate": (s.get("seal_success_rate") or 0),
                "break_times": s.get("break_times", 0),
                "seal_amount": (s.get("seal_amount") or 0),
                "board_stat": s.get("board_stat", ""),
                "first_time": s.get("first_limit_time", ""),
                "is_again": s.get("is_again", 0),
            })
        return out
    except Exception as e:
        print(f"[WARN] ths_limit_up_pool: {e}")
        return []


def limit_up_sentiment(date: str = None) -> dict:
    """打板情绪速算"""
    zt = em_zt_pool(date)
    zb = em_zb_pool(date)
    yzt = em_yzt_pool(date)
    dt_count = len(em_dt_pool(date))

    total_zt = len(zt)
    total_zb = len(zb)
    break_rate = round(total_zb / (total_zt + total_zb) * 100, 1) if (total_zt + total_zb) > 0 else 0

    # 连板梯队
    board_ladder = {}
    for s in zt:
        days = s.get("limit_days", 0)
        board_ladder[days] = board_ladder.get(days, 0) + 1

    # 晋级率
    promotion_rate = 0
    if yzt:
        today_up = sum(1 for s in yzt if s.get("pct", 0) > 0)
        today_zt_again = sum(1 for s in yzt if s.get("pct", 0) >= 9.8)
        promotion_rate = round(today_zt_again / len(yzt) * 100, 1) if yzt else 0

    return {
        "date": date or today_ymd(),
        "zt_count": total_zt,
        "zb_count": total_zb,
        "dt_count": dt_count,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "board_ladder": dict(sorted(board_ladder.items(), reverse=True)),
        "max_boards": max(board_ladder.keys()) if board_ladder else 0,
    }

"""
ETF期权数据采集 — 新浪期权数据
"""
from .base import em_get, UA

def _opt_f(x):
    try: return float(x)
    except: return 0.0

def _sina_opt_list(param: str) -> list:
    url = f"https://hq.sinajs.cn/list={param}"
    headers = {"User-Agent": UA, "Referer": "https://stock.finance.sina.com.cn/"}
    try:
        r = em_get(url, headers=headers, timeout=10)
        txt = r.text.strip()
        v = txt.split("=")[-1].strip('"').split(",") if "=" in txt else []
        return [x.strip() for x in v]
    except Exception:
        return []


def sina_option_codes(underlying: str = "510050", call: bool = True) -> dict:
    """获取期权合约列表。underlying=510050(50ETF)/510300(300ETF)/588000/510500"""
    t = "o" if call else "p"
    param = f"OP_UP_{underlying}"
    v = _sina_opt_list(param)
    if not v:
        return {}
    result = {}
    month = ""
    for item in v:
        if item.startswith("{"):
            continue
        if item.startswith("\""):
            month = item.strip('"')
            result[month] = []
        elif item.strip():
            result[month].append(item.strip())
    return {k: v for k, v in result.items() if v}


def sina_option_tquote(code: str) -> dict:
    """期权T型报价"""
    v = _sina_opt_list(f"CON_OP_{code}")
    if len(v) < 43:
        return {}
    return {
        "contract_code": code,
        "bid_vol": _opt_f(v[0]), "bid_price": _opt_f(v[1]),
        "last_price": _opt_f(v[2]), "ask_price": _opt_f(v[3]),
        "ask_vol": _opt_f(v[4]), "open_interest": _opt_f(v[5]),
        "pct": _opt_f(v[6]), "strike": _opt_f(v[7]),
        "prev_close": _opt_f(v[8]), "open": _opt_f(v[9]),
        "limit_up": _opt_f(v[10]), "limit_down": _opt_f(v[11]),
        "name": v[37], "amplitude": _opt_f(v[38]),
        "high": _opt_f(v[39]), "low": _opt_f(v[40]),
        "volume": _opt_f(v[41]), "amount": _opt_f(v[42]),
    }


def sina_option_greeks(code: str) -> dict:
    """期权希腊字母 + 隐含波动率"""
    raw = _sina_opt_list(f"CON_SO_{code}")
    if len(raw) < 16:
        return {}
    v = [raw[0]] + raw[4:]
    return {
        "contract_code": code,
        "name": v[0], "volume": _opt_f(v[1]),
        "delta": _opt_f(v[2]), "gamma": _opt_f(v[3]),
        "theta": _opt_f(v[4]), "vega": _opt_f(v[5]),
        "iv": _opt_f(v[6]),
        "high": _opt_f(v[7]), "low": _opt_f(v[8]),
        "trade_code": v[9], "strike": _opt_f(v[10]),
        "last_price": _opt_f(v[11]), "theory_price": _opt_f(v[12]),
    }

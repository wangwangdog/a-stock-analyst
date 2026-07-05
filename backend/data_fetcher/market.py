"""
行情层数据采集 — mootdx K线/报价、腾讯实时价、百度K线
"""
from .base import tdx_client, em_get, UA, today_str

def mootdx_klines(code: str, frequency: str = "5m", start: str = None, end: str = None, limit: int = 800):
    """mootdx K线（不复权原始价）
    frequency: 5m/15m/30m/60m/d/w/m
    返回 list[dict] 或 []
    """
    freq_map = {"1m": 8, "5m": 0, "15m": 1, "30m": 2, "60m": 3,
                "d": 9, "w": 5, "m": 6}
    freq = freq_map.get(frequency, 9)
    pure = code.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")
    market_code = 0 if pure.startswith("0") or pure.startswith("3") or pure.startswith("2") else 1
    try:
        client = tdx_client()
        df = client.bars(freq, int(pure), start=start or 0, count=limit)
        client.close()
        if df is None or df.empty:
            return []
        result = []
        for _, r in df.iterrows():
            result.append({
                "code": code,
                "date": str(r.get("datetime", "")),
                "open": float(r.get("open", 0)),
                "high": float(r.get("high", 0)),
                "low": float(r.get("low", 0)),
                "close": float(r.get("close", 0)),
                "volume": float(r.get("vol", 0)) * 100,  # 手→股
                "amount": float(r.get("amount", 0)),
            })
        return result
    except Exception as e:
        print(f"[WARN] mootdx_klines {code}: {e}")
        return []


def mootdx_quote(codes: list) -> dict:
    """mootdx 实时报价 46字段"""
    client = tdx_client()
    try:
        df = client.quotes(codes)
        client.close()
        if df is None or df.empty:
            return {}
        result = {}
        for _, r in df.iterrows():
            result[str(r.get("code", ""))] = {
                "price": float(r.get("price", 0)),
                "open": float(r.get("open", 0)),
                "high": float(r.get("high", 0)),
                "low": float(r.get("low", 0)),
                "last_close": float(r.get("last_close", 0)),
                "volume": float(r.get("vol", 0)) * 100,
                "amount": float(r.get("amount", 0)),
                "bid1": float(r.get("bid1", 0)), "ask1": float(r.get("ask1", 0)),
            }
        return result
    except Exception:
        return {}


def tencent_quote(codes: list) -> dict:
    """腾讯财经实时报价"""
    if not codes:
        return {}
    code_str = ",".join(
        c.replace("SH.", "sh").replace("SZ.", "sz").replace("BJ.", "bj")
        for c in codes
    )
    url = f"http://qt.gtimg.cn/q={code_str}"
    headers = {"User-Agent": UA}
    try:
        r = em_get(url, headers=headers, timeout=10, max_retries=1)
        result = {}
        for line in r.text.strip().split("\n"):
            if "=" not in line:
                continue
            raw = line.split("=")[-1].strip('"\n; ')
            v = raw.split("~")
            if len(v) < 46:
                continue
            # 腾讯字段: name(1), code(2), price(3), open(5), high(33), low(34),
            #           volume(6), amount(37), last_close(4), pe(39), pb(46),
            #           market_cap(44), turnover(38), limit_up(47), limit_down(48)
            code = v[2]
            result[code] = {
                "code": code,
                "name": v[1],
                "price": float(v[3]) if v[3] else 0,
                "last_close": float(v[4]) if v[4] else 0,
                "open": float(v[5]) if v[5] else 0,
                "volume": float(v[6]) if v[6] else 0,
                "high": float(v[33]) if len(v) > 33 and v[33] else 0,
                "low": float(v[34]) if len(v) > 34 and v[34] else 0,
                "turnover": float(v[38]) if len(v) > 38 and v[38] else 0,
                "pe": float(v[39]) if len(v) > 39 and v[39] else 0,
                "amount": float(v[37]) if len(v) > 37 and v[37] else 0,
                "market_cap": float(v[44]) if len(v) > 44 and v[44] else 0,
                "pb": float(v[46]) if len(v) > 46 and v[46] else 0,
                "limit_up": float(v[47]) if len(v) > 47 and v[47] else 0,
                "limit_down": float(v[48]) if len(v) > 48 and v[48] else 0,
            }
        return result
    except Exception as e:
        print(f"[WARN] tencent_quote: {e}")
        return {}

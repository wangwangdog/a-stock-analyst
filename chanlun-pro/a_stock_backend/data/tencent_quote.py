"""腾讯财经实时行情 — PE/PB/市值/换手率/涨跌停价

来源：a-stock-data Layer 1.2
HTTP GET，GBK 编码，`~` 分隔 88 个字段，不封IP。
"""
import urllib.request
import json
from typing import Optional

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_URL = "https://qt.gtimg.cn/q="


def _prefix(code: str) -> str:
    """6位代码 → 市场前缀"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    elif code.startswith("8"):
        return f"bj{code}"
    else:
        return f"sz{code}"


def fetch(codes: list[str]) -> dict[str, dict]:
    """
    批量拉取腾讯财经实时行情。
    codes: ["688017", "300476", "002463"]
    返回: {code: {name, price, pe_ttm, pb, mcap, ...}}
    """
    prefixed = ",".join(_prefix(c) for c in codes)
    url = _URL + prefixed
    req = urllib.request.Request(url)
    req.add_header("User-Agent", _UA)
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name":           vals[1],
            "price":          float(vals[3]) if vals[3] else 0,
            "last_close":     float(vals[4]) if vals[4] else 0,
            "open":           float(vals[5]) if vals[5] else 0,
            "change_amt":     float(vals[31]) if vals[31] else 0,
            "change_pct":     float(vals[32]) if vals[32] else 0,
            "high":           float(vals[33]) if vals[33] else 0,
            "low":            float(vals[34]) if vals[34] else 0,
            "amount_wan":     float(vals[37]) if vals[37] else 0,
            "turnover_pct":   float(vals[38]) if vals[38] else 0,
            "pe_ttm":         float(vals[39]) if vals[39] else 0,
            "amplitude_pct":  float(vals[43]) if vals[43] else 0,
            "mcap_yi":        float(vals[44]) if vals[44] else 0,
            "float_mcap_yi":  float(vals[45]) if vals[45] else 0,
            "pb":             float(vals[46]) if vals[46] else 0,
            "limit_up":       float(vals[47]) if vals[47] else 0,
            "limit_down":     float(vals[48]) if vals[48] else 0,
            "vol_ratio":      float(vals[49]) if vals[49] else 0,
            "pe_static":      float(vals[52]) if vals[52] else 0,
        }
    return result


def fetch_one(code: str) -> Optional[dict]:
    """拉取单只股票实时行情"""
    result = fetch([code])
    return result.get(code)

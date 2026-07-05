"""
资金面数据采集 — 龙虎榜、融资融券、大宗交易、股东户数、分红、资金流、北向、解禁
"""
import re, json
from datetime import datetime, timedelta
from .base import em_get, eastmoney_datacenter, UA, today_str, today_ymd


# ─── 龙虎榜（个股席位） ───

def dragon_tiger_board(code: str, trade_date: str = None, look_back: int = 30) -> dict:
    """龙虎榜数据聚合：上榜记录 + 买卖席位 + 机构动向"""
    if trade_date is None:
        trade_date = today_str()
    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50, sort_columns="TRADE_DATE", sort_types="-1",
    )
    for row in data:
        records.append({
            "code": code,
            "name": row.get("SECURITY_NAME", ""),
            "trade_date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy": (row.get("BILLBOARD_NET_AMT") or 0),
            "total_buy": (row.get("BILLBOARD_BUY_AMT") or 0),
            "total_sell": (row.get("BILLBOARD_SELL_AMT") or 0),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
        })

    seats = {"buy": [], "sell": []}
    inst = {"buy": 0, "sell": 0}
    if records:
        latest = records[0]["trade_date"]
        for src_type, seat_key in [("RPT_BILLBOARD_DAILYDETAILSBUY", "buy"),
                                    ("RPT_BILLBOARD_DAILYDETAILSSELL", "sell")]:
            seat_data = eastmoney_datacenter(
                src_type,
                filter_str=f"(TRADE_DATE='{latest}')(SECURITY_CODE=\"{code}\")",
                page_size=10, sort_columns="BUY" if seat_key == "buy" else "SELL", sort_types="-1",
            )
            for row in seat_data[:5]:
                seats[seat_key].append({
                    "name": row.get("OPERATEDEPT_NAME", ""),
                    "buy_amt": (row.get("BUY") or 0),
                    "sell_amt": (row.get("SELL") or 0),
                    "net": (row.get("NET") or 0),
                })
            # 机构
            inst[seat_key] = sum(
                (r.get("BUY") or 0) for r in seat_data if "机构" in (r.get("OPERATEDEPT_NAME") or "")
            ) if seat_key == "buy" else sum(
                (r.get("SELL") or 0) for r in seat_data if "机构" in (r.get("OPERATEDEPT_NAME") or "")
            )
    return {"records": records, "seats": seats, "institution": inst}


# ─── 全市场龙虎榜 ───

def daily_dragon_tiger(trade_date: str = None, min_net_buy: float = None) -> dict:
    """每日全市场龙虎榜"""
    if trade_date is None:
        trade_date = today_str()
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE='{trade_date}')",
        page_size=500, sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    result = {"date": trade_date, "stocks": [], "total": len(data)}
    for row in data:
        net = (row.get("BILLBOARD_NET_AMT") or 0)
        if min_net_buy and abs(net) < min_net_buy:
            continue
        result["stocks"].append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME", ""),
            "net_buy": net,
            "reason": row.get("EXPLANATION", ""),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
            "total_buy": (row.get("BILLBOARD_BUY_AMT") or 0),
        })
    return result


# ─── 融资融券 ───

def margin_trading(code: str, page_size: int = 30) -> list[dict]:
    """融资融券明细"""
    data = eastmoney_datacenter(
        "RPT_MARGIN_TRADING_DETAILS",
        columns="SECURITY_CODE,SECURITY_NAME,TRADE_DATE,ZYE,(RZYE),(RZME),(RQYE),(RQME)",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1",
    )
    result = []
    for row in data:
        result.append({
            "code": code,
            "name": row.get("SECURITY_NAME", ""),
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "margin_balance": (row.get("RZYE") or 0),
            "margin_buy": (row.get("RZME") or 0),
            "margin_repay": 0,
            "short_sell_balance": (row.get("RQYE") or 0),
            "short_sell_sell": (row.get("RQME") or 0),
            "short_sell_repay": 0,
        })
    return result


# ─── 大宗交易 ───

def block_trade(code: str, page_size: int = 20) -> list[dict]:
    data = eastmoney_datacenter(
        "RPT_BLOCK_TRADE_DETAILS",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=page_size, sort_columns="TRADE_DATE", sort_types="-1",
    )
    result = []
    for row in data:
        amount = (row.get("TRADE_AMOUNT") or 0)
        volume = (row.get("TRADE_VOLUME") or 0)
        price = (row.get("TRADE_PRICE") or 0)
        cl = (row.get("CLOSE_PRICE") or 1)
        premium = round(((price / cl) - 1) * 100, 2) if cl else 0
        result.append({
            "code": code,
            "name": row.get("SECURITY_NAME", ""),
            "trade_date": str(row.get("TRADE_DATE", ""))[:10],
            "price": price,
            "volume": volume,
            "amount": amount,
            "premium_rate": premium,
            "buyer": row.get("BUYER_NAME", ""),
            "seller": row.get("SELLER_NAME", ""),
        })
    return result


# ─── 股东户数 ───

def holder_num_change(code: str, page_size: int = 10) -> list[dict]:
    data = eastmoney_datacenter(
        "RPT_HOLDER_NUM",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=page_size, sort_columns="END_DATE", sort_types="-1",
    )
    result = []
    for row in data:
        result.append({
            "code": code,
            "name": row.get("SECURITY_NAME", ""),
            "report_date": str(row.get("END_DATE", ""))[:10],
            "holder_count": (row.get("HOLDER_NUM") or 0),
            "change_pct": round(float(row.get("CHANGE_PCT") or 0), 2),
            "avg_shares": (row.get("AVG_SHARES") or 0),
        })
    return result


# ─── 分红送转 ───

def dividend_history(code: str, page_size: int = 20) -> list[dict]:
    data = eastmoney_datacenter(
        "RPT_DIVIDEND_HISTORY",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=page_size, sort_columns="ANNOUNCE_DATE", sort_types="-1",
    )
    result = []
    for row in data:
        result.append({
            "code": code,
            "name": row.get("SECURITY_NAME", ""),
            "announce_date": str(row.get("ANNOUNCE_DATE", ""))[:10],
            "plan": row.get("DIVIDEND_PLAN", ""),
            "cash_dividend": (row.get("CASH_DIVIDEND") or 0),
            "bonus_shares": (row.get("BONUS_SHARES") or 0),
            "transfer_shares": (row.get("TRANSFER_SHARES") or 0),
            "progress": row.get("PROGRESS", ""),
        })
    return result


# ─── 北向资金 ───

def northbound_flow(date: str = None) -> dict:
    """北向资金实时流向"""
    if date is None:
        date = today_str()
    url = "https://push2.eastmoney.com/api/qt/kamt.kline/get"
    params = {"fields1": "f1,f2,f3,f4", "fields2": "f51,f52,f53,f54,f55,f56",
              "klt": 1, "lmt": 262, "secid": "1.000001"}
    try:
        r = em_get(url, params=params)
        data = r.json()
        lines = (data.get("data") or {}).get("klines") or []
        result = {"date": date, "hgt_net": 0, "sgt_net": 0, "total_net": 0, "minute_data": []}
        for line in lines[-262:]:
            parts = line.split(",")
            if len(parts) >= 6:
                result["minute_data"].append({
                    "time": parts[0], "hgt_net": float(parts[1]),
                    "sgt_net": float(parts[2]), "total_net": float(parts[5]),
                })
        if result["minute_data"]:
            last = result["minute_data"][-1]
            result["hgt_net"] = last["hgt_net"]
            result["sgt_net"] = last["sgt_net"]
            result["total_net"] = last["total_net"]
        return result
    except Exception as e:
        print(f"[WARN] northbound_flow: {e}")
        return {"date": date, "hgt_net": 0, "sgt_net": 0, "total_net": 0, "minute_data": []}


# ─── 个股资金流向（分钟级） ───

def eastmoney_fund_flow_minute(code: str) -> list[dict]:
    """个股资金流向 分钟级"""
    secid = f"0.{code}" if code.startswith("SZ.") or code.startswith("0") else f"1.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
              "fields2": "f51,f52,f53,f54,f55", "klt": 1, "lmt": 120}
    try:
        r = em_get(url, params=params)
        data = r.json()
        lines = (data.get("data") or {}).get("klines") or []
        result = []
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 5:
                result.append({
                    "code": code,
                    "time": parts[0],
                    "main_net": float(parts[1]),
                    "super_large_net": float(parts[2]),
                    "large_net": float(parts[3]),
                    "medium_net": float(parts[4]),
                })
        return result
    except Exception:
        return []


# ─── 个股资金流 120 日 ───

def stock_fund_flow_120d(code: str) -> list[dict]:
    """120日主力/大单/中单/小单日级净流入"""
    secid = f"0.{code}" if code.startswith("SZ.") or code.startswith("0") else f"1.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
              "fields2": "f51,f52,f53,f54,f55,f56,f57,f58", "lmt": 120}
    try:
        r = em_get(url, params=params)
        data = r.json()
        lines = (data.get("data") or {}).get("klines") or []
        result = []
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 8:
                result.append({
                    "code": code,
                    "date": parts[0],
                    "main_net": float(parts[1]),
                    "super_large_net": float(parts[2]),
                    "large_net": float(parts[3]),
                    "medium_net": float(parts[4]),
                    "small_net": float(parts[5]),
                })
        return result
    except Exception:
        return []


# ─── 限售解禁 ───

def lockup_expiry(code: str, trade_date: str = None, forward_days: int = 90) -> dict:
    if trade_date is None:
        trade_date = today_str()
    data = eastmoney_datacenter(
        "RPT_LOCKUP_EXPIRY",
        columns="SECURITY_CODE,SECURITY_NAME,LOCKUP_DATE,UNLOCK_DATE,UNLOCK_SHARES,UNLOCK_RATIO,UNLOCK_AMOUNT",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=100, sort_columns="UNLOCK_DATE", sort_types="1",
    )
    result = {"code": code, "records": []}
    for row in data:
        result["records"].append({
            "code": code,
            "name": row.get("SECURITY_NAME", ""),
            "unlock_date": str(row.get("UNLOCK_DATE", ""))[:10],
            "shares": (row.get("UNLOCK_SHARES") or 0),
            "ratio": round(float(row.get("UNLOCK_RATIO") or 0), 4),
            "amount": (row.get("UNLOCK_AMOUNT") or 0),
        })
    return result


# ─── 行业板块排名 ───

def industry_comparison(top_n: int = 20) -> dict:
    """东财行业涨跌排名"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {"pn": 1, "pz": top_n, "po": 1, "np": 1,
              "fltt": 2, "invt": 2, "fid": "f3",
              "fs": "m:90+t:2", "fields": "f2,f3,f4,f12,f14,f104,f105,f106"}
    try:
        r = em_get(url, params=params)
        data = r.json()
        rows = (data.get("data") or {}).get("diff") or []
        result = []
        for row in rows:
            result.append({
                "industry_code": str(row.get("f12", "")),
                "industry_name": row.get("f14", ""),
                "change_pct": round(float(row.get("f3", 0)), 2),
                "up_count": (row.get("f104") or 0),
                "down_count": (row.get("f105") or 0),
                "total_stocks": (row.get("f106") or 0),
            })
        return {"date": today_str(), "industries": result}
    except Exception:
        return {"date": today_str(), "industries": []}


# ─── 概念板块归属 ───

def eastmoney_concept_blocks(code: str) -> dict:
    """个股所属板块（行业/概念/地域）"""
    secid = f"0.{code}" if code.startswith("SZ.") or code.startswith("0") else f"1.{code}"
    url = "https://push2.eastmoney.com/api/qt/slist/get"
    params = {"spt": 3, "fltt": 2, "secids": secid}
    try:
        r = em_get(url, params=params)
        data = r.json()
        rows = (data.get("data") or {}).get("diff") or []
        result = {"code": code, "blocks": []}
        for row in rows:
            result["blocks"].append({
                "code": code,
                "name": row.get("f14", ""),
                "bk_code": str(row.get("f12", "")),
                "change_pct": round(float(row.get("f3", 0)), 2),
                "category": row.get("f9", ""),
            })
        return result
    except Exception:
        return {"code": code, "blocks": []}


if __name__ == "__main__":
    # 测试
    print("龙虎榜:", json.dumps(dragon_tiger_board("SZ.002475", "2026-06-30"), ensure_ascii=False)[:200])
    print("行业排名:", json.dumps(industry_comparison(5), ensure_ascii=False)[:200])

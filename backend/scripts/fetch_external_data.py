"""
A股扩展数据定时采集 — 全量定时任务脚本
数据统一标准：volume=股, amount=元, price=元, date=YYYY-MM-DD

用法：
  python fetch_external_data.py              # 全量采集
  python fetch_external_data.py --mode daily  # 仅日频任务
  python fetch_external_data.py --mode intraday # 仅盘中任务
  python fetch_external_data.py --mode backfill --days 30 # 回填30天
"""
import sys, os, json, time
from datetime import datetime, timedelta

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_fetcher.db import (
    get_db_path, get_conn,
    upsert_dragon_tiger, upsert_margin_trading, upsert_block_trade,
    upsert_holder_count, upsert_dividend, upsert_northbound_flow,
    upsert_fund_flow_daily, upsert_lockup_calendar, upsert_industry_ranking,
    upsert_limit_up_pool, upsert_etf_option_quote, upsert_investor_qa,
    upsert_ths_hot_list, upsert_stock_concept, upsert_stock_industry,
)

# ── 数据采集函数 ──
# 这些函数从 a-stock-data 借用的 HTTP API 直接采集

def fetch_all_daily():
    """收市后采集（每日盘后 ~17:00 运行）"""
    results = {}
    today = datetime.now().strftime("%Y-%m-%d")
    today_ymd = datetime.now().strftime("%Y%m%d")
    
    # 1. 北向资金
    print(f"[{today}] 🌊 采集北向资金...")
    results['northbound'] = _fetch_northbound(today)
    
    # 2. 行业板块排名
    print(f"[{today}] 🏭 采集行业板块排名...")
    results['industry'] = _fetch_industry_ranking(today)
    
    # 3. 龙虎榜全市场
    print(f"[{today}] 🐉 采集龙虎榜...")
    results['dragon_tiger'] = _fetch_daily_dragon_tiger(today)
    
    # 4. 涨停板四池
    print(f"[{today}] 📈 采集涨停板情绪...")
    results['limit_up'] = _fetch_limit_up_pools(today_ymd)
    
    # 5. 同花顺热榜
    print(f"[{today}] 🔥 采集热榜...")
    results['hot_list'] = _fetch_ths_hot_list(today)
    
    # 6. ETF 期权（收盘后快照）
    print(f"[{today}] 💹 采集ETF期权...")
    results['options'] = _fetch_etf_options(today)
    
    print(f"[{today}] ✅ 日频采集完成")
    return results


def fetch_all_intraday():
    """盘中采集（每30分钟运行）"""
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    date = now.strftime("%Y-%m-%d")
    ymd = now.strftime("%Y%m%d")
    
    r = {}
    
    # 1. 北向资金（盘中实时）
    print(f"[{ts}] 🌊 采集北向资金(盘中)...")
    r['northbound'] = _fetch_northbound(date)
    
    # 2. 涨停板池（盘中变化）
    print(f"[{ts}] 📈 采集涨停板池(盘中)...")
    if 930 <= int(now.strftime("%H%M")) <= 1500:
        r['limit_up'] = _fetch_limit_up_pools(ymd)
    
    # 3. 行业板块（盘中实时）
    print(f"[{ts}] 🏭 采集行业板块(盘中)...")
    r['industry'] = _fetch_industry_ranking(date)
    
    # 4. 同花顺热榜
    print(f"[{ts}] 🔥 采集热榜(盘中)...")
    r['hot_list'] = _fetch_ths_hot_list(date)
    
    # 5. ETF 期权（盘中快照）
    print(f"[{ts}] 💹 采集ETF期权(盘中)...")
    r['options'] = _fetch_etf_options(date)
    
    return r


def fetch_stock_fundamentals(code: str):
    """单只股票全维度数据采集"""
    r = {}
    r['margin'] = _fetch_margin_trading(code)
    r['block'] = _fetch_block_trade(code)
    r['holders'] = _fetch_holder_count(code)
    r['dividend'] = _fetch_dividend(code)
    r['lockup'] = _fetch_lockup(code)
    r['fund_flow'] = _fetch_fund_flow(code)
    r['dragon'] = _fetch_stock_dragon_tiger(code)
    r['qa'] = _fetch_investor_qa(code)
    r['concept'] = _fetch_concept_blocks(code)
    return r


# ══════════════════════════════════════════════
# 各数据源采集实现（复用 base 工具）
# ══════════════════════════════════════════════

def _em_get(url, params=None, headers=None, timeout=15):
    """东财统一限流请求"""
    import requests
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
    import time, random
    
    UA = "Mozilla/5.0 Windows NT 10.0; Win64; x64 AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    
    # 限流
    _last_call = getattr(_em_get, '_last_call', 0)
    now = time.time()
    sleep_time = 1.2 + random.uniform(0, 0.3) - (now - _last_call)
    if sleep_time > 0:
        time.sleep(sleep_time)
    
    sess = getattr(_em_get, '_session', None)
    if sess is None:
        sess = requests.Session()
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        sess.mount("https://", HTTPAdapter(max_retries=retry))
        _em_get._session = sess
    
    if headers is None:
        headers = {"User-Agent": UA, "Referer": "https://data.eastmoney.com/"}
    else:
        headers.setdefault("User-Agent", UA)
    
    resp = sess.get(url, params=params, headers=headers, timeout=timeout)
    _em_get._last_call = time.time()
    return resp


def _eastmoney_datacenter(report_name, filter_str="", page_size=100, sort_columns="", sort_types=""):
    """东财数据中心查询"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": report_name, "columns": "ALL", "pageNumber": 1,
              "pageSize": min(page_size, 500), "sortTypes": sort_types,
              "sortColumns": sort_columns, "source": "WEB", "client": "WEB"}
    if filter_str:
        params["filter"] = filter_str
    try:
        r = _em_get(url, params=params)
        data = r.json()
        if data.get("success") and data.get("result", {}).get("data"):
            return data["result"]["data"]
    except Exception as e:
        print(f"  [WARN] datacenter {report_name}: {e}")
    return []


def _get_stock_list():
    """获取全市场股票列表（kline_cache 中有的股票）"""
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND symbol LIKE '%.%' ORDER BY symbol").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ── 北向资金 ──
def _fetch_northbound(date):
    url = "https://push2.eastmoney.com/api/qt/kamt.kline/get"
    params = {"fields1": "f1,f2,f3,f4", "fields2": "f51,f52,f53,f54,f55,f56",
              "klt": 1, "lmt": 262, "secid": "1.000001"}
    try:
        r = _em_get(url, params=params)
        data = r.json()
        lines = (data.get("data") or {}).get("klines") or []
        if lines:
            last = lines[-1].split(",")
            if len(last) >= 6:
                row = {
                    "date": date,
                    "hgt_net": float(last[1]),
                    "sgt_net": float(last[2]),
                    "total_net": float(last[5]),
                }
                upsert_northbound_flow(row)
                print(f"  北向: 沪{row['hgt_net']/1e8:.1f}亿 深{row['sgt_net']/1e8:.1f}亿 合计{row['total_net']/1e8:.1f}亿")
                return row
    except Exception as e:
        print(f"  [WARN] northbound: {e}")
    return None


# ── 行业板块排名 ──
def _fetch_industry_ranking(date):
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {"pn": 1, "pz": 80, "po": 1, "np": 1, "fltt": 2, "invt": 2,
              "fid": "f3", "fs": "m:90+t:2", "fields": "f2,f3,f4,f12,f14,f104,f105,f106"}
    try:
        r = _em_get(url, params=params)
        data = r.json()
        rows = (data.get("data") or {}).get("diff") or []
        count = 0
        for row in rows:
            item = {
                "industry_code": str(row.get("f12", "")),
                "industry_name": row.get("f14", ""),
                "date": date,
                "change_pct": round(float(row.get("f3", 0)), 2),
                "up_count": (row.get("f104") or 0),
                "down_count": (row.get("f105") or 0),
                "total_stocks": (row.get("f106") or 0),
            }
            upsert_industry_ranking(item)
            count += 1
        print(f"  行业板块: {count} 行")
        return count
    except Exception as e:
        print(f"  [WARN] industry_ranking: {e}")
    return 0


# ── 龙虎榜 ──
def _fetch_daily_dragon_tiger(date):
    data = _eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE='{date}')",
        page_size=500, sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    count = 0
    for row in data:
        item = {
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME", ""),
            "trade_date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy": (row.get("BILLBOARD_NET_AMT") or 0),
            "total_buy": (row.get("BILLBOARD_BUY_AMT") or 0),
            "total_sell": (row.get("BILLBOARD_SELL_AMT") or 0),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
            "buy_seats": "{}", "sell_seats": "{}",
            "inst_buy": 0, "inst_sell": 0,
        }
        try:
            upsert_dragon_tiger(item)
            count += 1
        except:
            pass
    print(f"  龙虎榜: {count} 只股票上榜")
    return count


# ── 涨停板 ──
def _fetch_limit_up_pools(ymd):
    """涨停板情绪数据"""
    def _em_zt_api(endpoint, sort):
        url = f"https://push2ex.eastmoney.com/{endpoint}"
        params = {"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
                  "Pageindex": 0, "pagesize": 10000, "sort": sort, "date": ymd}
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
        try:
            r = _em_get(url, params=params, headers=headers, timeout=10)
            return (r.json().get("data") or {}).get("pool") or []
        except:
            return []
    
    pools = [
        ("zt", "getTopicZTPool", "fbt:asc"),
        ("zb", "getTopicZBPool", "fbt:asc"),
        ("dt", "getTopicDTPool", "fund:asc"),
        ("yzt", "getYesterdayZTPool", "zs:desc"),
    ]
    total = 0
    for ptype, endpoint, sort in pools:
        items = _em_zt_api(endpoint, sort)
        for p in items:
            try:
                row = {
                    "code": p.get("c", ""),
                    "name": p.get("n", ""),
                    "trade_date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
                    "pool_type": ptype,
                    "price": (p.get("p", 0) or 0) / 1000,
                    "pct": round(p.get("zdp", 0), 2),
                    "amount": p.get("amount", 0),
                    "turnover": round(p.get("hs", 0), 2),
                    "seal_fund": p.get("fund", 0),
                    "limit_days": p.get("lbc", 0),
                    "first_seal": str(int(p.get("fbt", 0))).zfill(6) if p.get("fbt") else "",
                    "last_seal": str(int(p.get("lbt", 0))).zfill(6) if p.get("lbt") else "",
                    "break_times": p.get("zbc", 0),
                    "industry": p.get("hybk", ""),
                    "zt_stat": f'{(p.get("zttj") or {}).get("days","?")}天{(p.get("zttj") or {}).get("ct","?")}板',
                    "board_amount": p.get("fba", 0),
                    "amplitude": round(p.get("zf", 0), 2) if p.get("zf") else 0,
                    "speed": round(p.get("zs", 0), 2) if p.get("zs") else 0,
                    "seal_rate": 0, "reason": "", "board_type": "",
                }
                upsert_limit_up_pool(row)
                total += 1
            except Exception:
                pass
    print(f"  涨停板: {total} 条记录")
    return total


# ── 同花顺热榜 ──
def _fetch_ths_hot_list(date):
    for period in ["hour", "day", "week"]:
        period_map = {"hour": "1", "day": "2", "week": "3"}
        url = "https://data.10jqka.com.cn/dataapi/hot_rank/hot_rank_list"
        params = {"type": period_map[period], "limit": 100,
                  "field": "code,name,rank,rank_change,popularity,concept_tags"}
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.10jqka.com.cn/"}
        try:
            r = _em_get(url, params=params, headers=headers, timeout=10)
            data = r.json()
            items = (data.get("data") or {}).get("list") or []
            for item in items:
                row = {
                    "code": item.get("code", ""),
                    "name": item.get("name", ""),
                    "rank": item.get("rank", 0),
                    "rank_change": item.get("rank_change", 0),
                    "popularity": (item.get("popularity") or 0),
                    "concept_tags": json.dumps(item.get("concept_tags", []), ensure_ascii=False),
                    "period": period,
                    "snapshot_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                try:
                    upsert_ths_hot_list(row)
                except:
                    pass
        except:
            pass
    print(f"  热榜: {period} 周期已采集")
    return True


# ── ETF 期权 ──
def _fetch_etf_options(snapshot_date):
    underlying_list = [
        ("510050", "上证50ETF"), ("510300", "沪深300ETF"),
        ("588000", "科创50ETF"), ("510500", "中证500ETF"),
    ]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = 0
    for und_code, und_name in underlying_list:
        # 获取近月平值合约
        url = f"https://hq.sinajs.cn/list=OP_UP_{und_code}"
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://stock.finance.sina.com.cn/"}
        try:
            r = _em_get(url, headers=headers, timeout=10)
            txt = r.text.strip()
            if "=" not in txt:
                continue
            v = txt.split("=")[-1].strip('"').split(",")
            contracts = []
            month = ""
            for item in v:
                item = item.strip()
                if item.startswith("\""):
                    month = item.strip('"')
                elif item:
                    contracts.append((month, item))
            
            # 只取近月平值附近 3 个合约
            mid = max(0, len(contracts) // 2 - 1)
            for month, ccode in contracts[mid:mid+6]:
                if not ccode:
                    continue
                # T型报价
                url2 = f"https://hq.sinajs.cn/list=CON_OP_{ccode}"
                try:
                    r2 = _em_get(url2, headers=headers, timeout=10)
                    txt2 = r2.text.strip()
                    vv = txt2.split("=")[-1].strip('"').split(",") if "=" in txt2 else []
                    if len(vv) < 43:
                        continue
                    # 希腊字母
                    url3 = f"https://hq.sinajs.cn/list=CON_SO_{ccode}"
                    greeks = {}
                    try:
                        r3 = _em_get(url3, headers=headers, timeout=10)
                        txt3 = r3.text.strip()
                        gv = txt3.split("=")[-1].strip('"').split(",") if "=" in txt3 else []
                        if len(gv) >= 16:
                            gv2 = [gv[0]] + gv[4:]
                            greeks = {"delta": _f(gv2[2]), "gamma": _f(gv2[3]),
                                      "theta": _f(gv2[4]), "vega": _f(gv2[5]),
                                      "iv": _f(gv2[6]), "theory": _f(gv2[12])}
                    except:
                        pass
                    
                    row = {
                        "underlying": und_code,
                        "contract_code": ccode,
                        "name": vv[37] if len(vv) > 37 else "",
                        "call_put": "CALL" if "购" in (vv[37] if len(vv) > 37 else "") else "PUT",
                        "strike": _f(vv[7]) if len(vv) > 7 else 0,
                        "expiry": month,
                        "last_price": _f(vv[2]) if len(vv) > 2 else 0,
                        "bid_price": _f(vv[1]) if len(vv) > 1 else 0,
                        "ask_price": _f(vv[3]) if len(vv) > 3 else 0,
                        "bid_vol": _f(vv[0]), "ask_vol": _f(vv[4]),
                        "open_interest": _f(vv[5]), "volume": _f(vv[41]) if len(vv) > 41 else 0,
                        "amount": _f(vv[42]) if len(vv) > 42 else 0,
                        "pct": _f(vv[6]), "snapshot_time": ts,
                        "delta": greeks.get("delta", 0), "gamma": greeks.get("gamma", 0),
                        "theta": greeks.get("theta", 0), "vega": greeks.get("vega", 0),
                        "iv": greeks.get("iv", 0), "theory_price": greeks.get("theory", 0),
                    }
                    try:
                        upsert_etf_option_quote(row)
                        total += 1
                    except:
                        pass
                except:
                    continue
        except:
            continue
    print(f"  ETF期权: {total} 条")
    return total


def _f(v):
    try: return float(v) if v else 0.0
    except: return 0.0


# ── 单只股票数据 ──

def _fetch_margin_trading(code):
    data = _eastmoney_datacenter("RPT_MARGIN_TRADING_DETAILS",
        filter_str=f"(SECURITY_CODE=\"{code}\")", page_size=30,
        sort_columns="TRADE_DATE", sort_types="-1")
    count = 0
    for row in data:
        upsert_margin_trading({
            "code": code, "name": row.get("SECURITY_NAME",""),
            "date": str(row.get("TRADE_DATE",""))[:10],
            "margin_balance": (row.get("RZYE") or 0),
            "margin_buy": (row.get("RZME") or 0),
            "margin_repay": 0,
            "short_sell_balance": (row.get("RQYE") or 0),
            "short_sell_sell": (row.get("RQME") or 0),
            "short_sell_repay": 0,
        })
        count += 1
    return count


def _fetch_block_trade(code):
    data = _eastmoney_datacenter("RPT_BLOCK_TRADE_DETAILS",
        filter_str=f"(SECURITY_CODE=\"{code}\")", page_size=20,
        sort_columns="TRADE_DATE", sort_types="-1")
    count = 0
    for row in data:
        price = (row.get("TRADE_PRICE") or 0)
        cl = (row.get("CLOSE_PRICE") or 1)
        premium = round(((price / cl) - 1) * 100, 2) if cl else 0
        upsert_block_trade({
            "code": code, "name": row.get("SECURITY_NAME",""),
            "trade_date": str(row.get("TRADE_DATE",""))[:10],
            "price": price, "volume": (row.get("TRADE_VOLUME") or 0),
            "amount": (row.get("TRADE_AMOUNT") or 0),
            "premium_rate": premium,
            "buyer": row.get("BUYER_NAME",""), "seller": row.get("SELLER_NAME",""),
        })
        count += 1
    return count


def _fetch_holder_count(code):
    data = _eastmoney_datacenter("RPT_HOLDER_NUM",
        filter_str=f"(SECURITY_CODE=\"{code}\")", page_size=10,
        sort_columns="END_DATE", sort_types="-1")
    count = 0
    for row in data:
        upsert_holder_count({
            "code": code, "name": row.get("SECURITY_NAME",""),
            "report_date": str(row.get("END_DATE",""))[:10],
            "holder_count": (row.get("HOLDER_NUM") or 0),
            "change_pct": round(float(row.get("CHANGE_PCT") or 0), 2),
            "avg_shares": (row.get("AVG_SHARES") or 0),
        })
        count += 1
    return count


def _fetch_dividend(code):
    data = _eastmoney_datacenter("RPT_DIVIDEND_HISTORY",
        filter_str=f"(SECURITY_CODE=\"{code}\")", page_size=20,
        sort_columns="ANNOUNCE_DATE", sort_types="-1")
    count = 0
    for row in data:
        upsert_dividend({
            "code": code, "name": row.get("SECURITY_NAME",""),
            "announce_date": str(row.get("ANNOUNCE_DATE",""))[:10],
            "plan": row.get("DIVIDEND_PLAN",""),
            "cash_dividend": (row.get("CASH_DIVIDEND") or 0),
            "bonus_shares": (row.get("BONUS_SHARES") or 0),
            "transfer_shares": (row.get("TRANSFER_SHARES") or 0),
            "progress": row.get("PROGRESS",""),
        })
        count += 1
    return count


def _fetch_lockup(code):
    data = _eastmoney_datacenter("RPT_LOCKUP_EXPIRY",
        columns="SECURITY_CODE,SECURITY_NAME,LOCKUP_DATE,UNLOCK_DATE,UNLOCK_SHARES,UNLOCK_RATIO,UNLOCK_AMOUNT",
        filter_str=f"(SECURITY_CODE=\"{code}\")", page_size=100,
        sort_columns="UNLOCK_DATE", sort_types="1")
    count = 0
    for row in data:
        upsert_lockup_calendar({
            "code": code, "name": row.get("SECURITY_NAME",""),
            "unlock_date": str(row.get("UNLOCK_DATE",""))[:10],
            "shares": (row.get("UNLOCK_SHARES") or 0),
            "ratio": round(float(row.get("UNLOCK_RATIO") or 0), 4),
            "amount": (row.get("UNLOCK_AMOUNT") or 0),
        })
        count += 1
    return count


def _fetch_fund_flow(code):
    secid = f"0.{code}" if code.startswith("SZ.") or code.startswith("0") else f"1.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {"secid": secid, "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
              "fields2": "f51,f52,f53,f54,f55,f56,f57,f58", "lmt": 120}
    try:
        r = _em_get(url, params=params)
        lines = (r.json().get("data") or {}).get("klines") or []
        count = 0
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 8:
                upsert_fund_flow_daily({
                    "code": code, "name": "",
                    "date": parts[0],
                    "main_net": float(parts[1]),
                    "super_large_net": float(parts[2]),
                    "large_net": float(parts[3]),
                    "medium_net": float(parts[4]),
                    "small_net": float(parts[5]),
                })
                count += 1
        return count
    except:
        return 0


def _fetch_stock_dragon_tiger(code):
    data = _eastmoney_datacenter("RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(SECURITY_CODE=\"{code}\")", page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1")
    count = 0
    for row in data:
        try:
            upsert_dragon_tiger({
                "code": code, "name": row.get("SECURITY_NAME",""),
                "trade_date": str(row.get("TRADE_DATE",""))[:10],
                "reason": row.get("EXPLANATION",""),
                "net_buy": (row.get("BILLBOARD_NET_AMT") or 0),
                "total_buy": (row.get("BILLBOARD_BUY_AMT") or 0),
                "total_sell": (row.get("BILLBOARD_SELL_AMT") or 0),
                "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
                "buy_seats": "{}", "sell_seats": "{}",
                "inst_buy": 0, "inst_sell": 0,
            })
            count += 1
        except:
            pass
    return count


def _fetch_investor_qa(code):
    # 获取 orgId
    pure = code.replace("SH.","").replace("SZ.","").replace("BJ.","")
    org_url = "https://www.cninfo.com.cn/new/data/szse_stock.json"
    org_id = ""
    try:
        r = _em_get(org_url, timeout=10)
        stocks = r.json()
        for s in stocks.get("stockList", []):
            if s.get("code") == pure:
                org_id = s.get("orgId", f"gssz0{pure}")
                break
    except:
        pass
    if not org_id:
        org_id = f"gssz0{pure}" if pure.startswith("0") or pure.startswith("3") else f"gssh0{pure}"
    
    url = "http://irm.cninfo.com.cn/ircs/api/searchByCode"
    params = {"stockCode": pure, "orgId": org_id, "pageNum": 1, "pageSize": 30, "keyWord": ""}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "http://irm.cninfo.com.cn/"}
    try:
        r = _em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        items = (data.get("result") or []) if isinstance(data, dict) else data
        count = 0
        for item in items:
            upsert_investor_qa({
                "code": code, "name": "",
                "question_date": (item.get("questionTime") or "")[:10],
                "question": item.get("question",""),
                "answer_date": (item.get("answerTime") or "")[:10],
                "answer": item.get("answer",""),
                "qa_id": str(item.get("questionId","")),
            })
            count += 1
        return count
    except:
        return 0


def _fetch_concept_blocks(code):
    secid = f"0.{code}" if code.startswith("SZ.") else f"1.{code}"
    url = "https://push2.eastmoney.com/api/qt/slist/get"
    params = {"spt": 3, "fltt": 2, "secids": secid}
    try:
        r = _em_get(url, params=params)
        data = r.json()
        rows = (data.get("data") or {}).get("diff") or []
        count = 0
        today = datetime.now().strftime("%Y-%m-%d")
        for row in rows:
            # 存入 stock_industry
            cat_map = {"1": "HY", "2": "GN", "3": "DQ"}
            category = cat_map.get(str(row.get("f9", "")), "GN")
            upsert_stock_industry({
                "code": code, "name": "",
                "industry_name": row.get("f14",""),
                "industry_code": str(row.get("f12","")),
                "category": category,
            })
            # 存入 stock_concept
            upsert_stock_concept({
                "code": code, "name": "",
                "concept_name": row.get("f14",""),
                "concept_code": str(row.get("f12","")),
                "category": category,
                "date": today,
            })
            count += 1
        return count
    except:
        return 0


# ══════════════════════════════════════════════
# 主函数
# ══════════════════════════════════════════════

def backfill_missing_days(days: int = 30):
    """回填历史数据"""
    print(f"🔄 开始回填过去 {days} 天数据...")
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        dy = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
        print(f"\n[{d}] 回填...")
        _fetch_daily_dragon_tiger(d)
        _fetch_industry_ranking(d)
        _fetch_limit_up_pools(dy)
        time.sleep(2)
    print("✅ 回填完成")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    
    if mode == "--mode" and len(sys.argv) > 2:
        mode = sys.argv[2]
    
    if mode == "daily":
        print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} 盘后全量采集开始")
        fetch_all_daily()
    elif mode == "intraday":
        print(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} 盘中采集开始")
        fetch_all_intraday()
    elif mode == "backfill":
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        backfill_missing_days(days)
    elif mode == "stock":
        code = sys.argv[3] if len(sys.argv) > 3 else ""
        if code:
            print(f"🕐 采集 {code} 全维度数据...")
            r = fetch_stock_fundamentals(code)
            for k, v in r.items():
                print(f"  {k}: {v}")
    elif mode == "all_stocks":
        stocks = _get_stock_list()
        print(f"🕐 批量采集 {len(stocks)} 只股票数据...")
        for i, code in enumerate(stocks):
            if i % 100 == 0:
                print(f"  [{i}/{len(stocks)}] {code}...")
            r = fetch_stock_fundamentals(code)
            if i % 10 == 9:
                time.sleep(1)  # 东财防封
        print(f"✅ 批量采集完成，共 {len(stocks)} 只")
    else:
        print("用法:")
        print("  python fetch_external_data.py daily     # 盘后全量")
        print("  python fetch_external_data.py intraday  # 盘中")
        print("  python fetch_external_data.py backfill --days 30  # 回填")
        print("  python fetch_external_data.py stock SZ.000001  # 单只")
        print("  python fetch_external_data.py all_stocks  # 全市场批量")

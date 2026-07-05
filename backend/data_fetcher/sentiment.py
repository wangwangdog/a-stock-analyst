"""
舆情互动层 — 互动易问答、同花顺热榜、东财人气榜
"""
import json
from .base import em_get, UA, today_str


def cninfo_irm(code: str, page_size: int = 30, page_num: int = 1) -> list[dict]:
    """互动易问答（巨潮）"""
    # 先获取 orgId
    org_id = _cninfo_orgid(code)
    url = "http://irm.cninfo.com.cn/ircs/api/searchByCode"
    params = {"stockCode": code, "orgId": org_id, "pageNum": page_num,
              "pageSize": page_size, "keyWord": ""}
    headers = {"User-Agent": UA, "Referer": "http://irm.cninfo.com.cn/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        items = (data.get("result") or []) if isinstance(data, dict) else data
        out = []
        for item in items:
            out.append({
                "code": code,
                "name": "",
                "question_date": (item.get("questionTime") or "")[:10],
                "question": item.get("question", ""),
                "answer_date": (item.get("answerTime") or "")[:10],
                "answer": item.get("answer", ""),
                "qa_id": str(item.get("questionId", "")),
            })
        return out
    except Exception as e:
        print(f"[WARN] cninfo_irm {code}: {e}")
        return []


def _cninfo_orgid(code: str) -> str:
    """获取巨潮 orgId"""
    pure = code.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")
    url = "https://www.cninfo.com.cn/new/data/szse_stock.json"
    try:
        r = em_get(url, timeout=10)
        stocks = r.json()
        for s in stocks.get("stockList", []):
            if s.get("code") == pure:
                return s.get("orgId", f"gssz0{pure}")
        for s in stocks.get("stockBList", []):
            if s.get("code") == pure:
                return s.get("orgId", f"gssz0{pure}")
    except Exception:
        pass
    # fallback
    prefix = code.split(".")[0] if "." in code else "sh"
    return {"SH": f"gssh0{pure}", "SZ": f"gssz0{pure}", "BJ": f"gsbz0{pure}"}.get(prefix, f"gssz0{pure}")


def ths_hot_list(period: str = "hour") -> list[dict]:
    """同花顺热榜。period: hour/day/week"""
    period_map = {"hour": "1", "day": "2", "week": "3"}
    url = "https://data.10jqka.com.cn/dataapi/hot_rank/hot_rank_list"
    params = {"type": period_map.get(period, "1"), "limit": 100,
              "field": "code,name,rank,rank_change,popularity,concept_tags"}
    headers = {"User-Agent": UA, "Referer": "https://data.10jqka.com.cn/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        items = (data.get("data") or {}).get("list") or []
        out = []
        for item in items:
            out.append({
                "code": item.get("code", ""),
                "name": item.get("name", ""),
                "rank": item.get("rank", 0),
                "rank_change": item.get("rank_change", 0),
                "popularity": (item.get("popularity") or 0),
                "concept_tags": json.dumps(item.get("concept_tags", []), ensure_ascii=False),
            })
        return out
    except Exception as e:
        print(f"[WARN] ths_hot_list: {e}")
        return []


def em_hot_rank(top: int = 50) -> list[dict]:
    """东财人气榜"""
    url = "https://emappdata.eastmoney.com/StockRanking/GetStockRankingData"
    params = {"pageIndex": 1, "pageSize": top,
              "market": "A", "sortField": "HotScore", "sortDirection": "Desc"}
    headers = {"User-Agent": UA, "Referer": "https://emappdata.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        items = (data.get("Data") or []) if isinstance(data, dict) else []
        out = []
        for item in items:
            out.append({
                "code": item.get("SCode", ""),
                "name": item.get("SName", ""),
                "rank": item.get("Rank", 0),
                "rank_change": item.get("RankChange", 0),
            })
        return out
    except Exception as e:
        print(f"[WARN] em_hot_rank: {e}")
        return []


def em_hot_concept(code: str) -> list[dict]:
    """个股概念命中"""
    pure = code.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")
    url = "https://emappdata.eastmoney.com/StockRanking/GetStockConcepts"
    params = {"code": pure}
    headers = {"User-Agent": UA, "Referer": "https://emappdata.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        items = (data.get("Data") or []) if isinstance(data, dict) else []
        out = []
        for item in items:
            out.append({
                "code": code,
                "concept_name": item.get("ConceptName", ""),
                "heat": item.get("Heat", 0),
            })
        return out
    except Exception as e:
        print(f"[WARN] em_hot_concept: {e}")
        return []

"""
新闻数据采集 — 东财个股新闻 + 全球资讯
"""
import json
import re
from .base import em_get, UA


def eastmoney_stock_news(code: str, page_size: int = 20) -> list[dict]:
    """东财个股新闻"""
    pure = code.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")
    url = "https://search-api-web.eastmoney.com/search/jsonp"
    params = {"param": f'{{"uid":"","keyword":{pure},"type":["cmsArticleWebOld"],"client":"web","clientType":"web"}}',
              "cb": "jQuery", "_": "1"}
    headers = {"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10, max_retries=1)
        import re
        text = r.text
        m = re.search(r'jQuery\((.*)\)', text)
        if not m:
            return []
        data = json.loads(m.group(1))
        articles = (data.get("result") or {}).get("cmsArticleWebOld") or []
        out = []
        for a in articles[:page_size]:
            out.append({
                "code": code,
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "date": str(a.get("date", ""))[:19],
                "source": a.get("source", ""),
            })
        return out
    except Exception as e:
        print(f"[WARN] eastmoney_stock_news {code}: {e}")
        return []


def eastmoney_global_news(page_size: int = 50) -> list[dict]:
    """东财全球财经资讯"""
    url = "https://np-weblist.eastmoney.com/comm/web/list"
    params = {"client": "webclient", "sr": -1, "page_size": page_size,
              "page_index": 1, "type": "live"}
    headers = {"User-Agent": UA, "Referer": "https://live.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        items = (data.get("data") or {}).get("list") or []
        out = []
        for item in items:
            out.append({
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "time": item.get("show_time", ""),
                "url": item.get("url", ""),
            })
        return out
    except Exception as e:
        print(f"[WARN] eastmoney_global_news: {e}")
        return []




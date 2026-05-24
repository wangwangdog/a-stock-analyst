"""个股新闻 + 财联社快讯 + 全球资讯

来源：a-stock-data Layer 3
akshare，免费无key。
"""
import akshare as ak
import requests
from typing import Optional
from datetime import datetime, timedelta

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def get_stock_news(code: str, limit: int = 20) -> list[dict]:
    """
    获取个股新闻（东财源）。
    code: 6位股票代码
    返回: [{title, content, date, source, url}, ...]
    """
    # 优先: akshare
    try:
        df = ak.stock_news_em(symbol=code)
        if df is not None and not df.empty:
            col_map = {
                "新闻标题": "title",
                "新闻内容": "content",
                "发布时间": "date",
                "文章来源": "source",
                "新闻链接": "url",
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            return df.head(limit).to_dict('records')
    except Exception:
        pass

    # Fallback: 直接请求东财新闻 API
    try:
        import requests
        url = f"https://push2.eastmoney.com/api/qt/slist/get"
        params = {
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fields": "f12,f14,f2,f3",
            "np": 1,
            "pz": limit,
            "secids": f"1.{code}",
            "_": 0,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://guba.eastmoney.com/",
        }
        # 新闻搜索 end point
        from urllib.parse import quote
        nurl = f"https://search-api-web.eastmoney.com/search/jsonp"
        nparams = {
            "param": f"{{\"uid\":\"\",\"keyword\":\"{code}\",\"type\":[\"cmsArticleWebOld\"],\"client\":\"web\",\"clientType\":\"web\",\"clientVersion\":\"curr\",\"param\":{{\"cmsArticleWebOld\":{{\"searchScope\":\"default\",\"sort\":\"default\",\"pageIndex\":1,\"pageSize\":{limit},\"preTag\":\"\",\"searchToken\":\"\"}}}}}}",
            "pageSize": limit,
        }
        r = requests.get(nurl, params=nparams, headers=headers, timeout=15)
        data = r.json()
        articles = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", data.get("list", []))
        results = []
        for a in articles[:limit]:
            results.append({
                "title": a.get("articleTitle", a.get("title", "")),
                "content": a.get("articleContent", a.get("summary", "")),
                "date": a.get("date", a.get("showTime", a.get("createDate", ""))),
                "source": a.get("source", ""),
                "url": a.get("articleUrl", a.get("url", "")),
            })
        if results:
            return results
    except Exception:
        pass

    return []


def get_cailianshe(limit: int = 30) -> list[dict]:
    """
    获取财联社快讯（分钟级）。
    返回: [{title, content, date}, ...]
    """
    try:
        df = ak.stock_info_global_cls()
        if df is None or df.empty:
            return []
        col_map = {
            "标题": "title",
            "内容": "content",
            "发布时间": "date",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df.head(limit).to_dict('records')
    except Exception:
        # fallback: 直接拉财联社
        return _fallback_cailianshe(limit)


def _fallback_cailianshe(limit: int = 30) -> list[dict]:
    """直接拉财联社电报"""
    url = "https://www.cls.cn/telegraph"
    params = {
        "category": "all",
        "_": int(datetime.now().timestamp() * 1000),
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": _UA,
            "Referer": "https://www.cls.cn/",
        }, timeout=15)
        data = r.json()
        items = data.get("data", {}).get("roll_data", [])
        results = []
        for item in items[:limit]:
            results.append({
                "title": item.get("title", ""),
                "content": item.get("content", "") or item.get("brief", ""),
                "date": item.get("ctime", ""),
            })
        return results
    except Exception:
        return []


def get_global_news(limit: int = 30) -> list[dict]:
    """
    获取东财全球资讯。
    返回: [{title, summary, date, url}, ...]
    """
    try:
        df = ak.stock_info_global_em()
        if df is None or df.empty:
            return []
        col_map = {
            "标题": "title",
            "摘要": "summary",
            "发布时间": "date",
            "链接": "url",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df.head(limit).to_dict('records')
    except Exception as e:
        # fallback: akshare 另一入口
        try:
            df = ak.stock_info_global_em()
            return df.head(limit).to_dict('records')
        except Exception:
            return []

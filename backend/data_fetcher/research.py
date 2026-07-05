"""
研报数据采集 — 东财研报、同花顺一致预期、行业研报
"""
import json
from .base import em_get, UA


def eastmoney_reports(code: str, max_pages: int = 5) -> list[dict]:
    """东财个股研报列表"""
    pure = code.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")
    out = []
    for page in range(1, max_pages + 1):
        data = _em_report_api(pure, page)
        if not data:
            break
        for row in data:
            out.append({
                "code": code,
                "title": row.get("infoCode", ""),
                "org_name": row.get("orgName", ""),
                "rating": row.get("emRatingName", ""),
                "report_date": str(row.get("publishDate", ""))[:10],
                "eps_2025": _safe_float(row.get("yem2025")),
                "eps_2026": _safe_float(row.get("yem2026")),
                "eps_2027": _safe_float(row.get("yem2027")),
                "pdf_url": row.get("pdfUrl", ""),
                "stock_code": code,
            })
    return out


def _em_report_api(stock_code: str, page: int = 1) -> list[dict]:
    url = "https://reportapi.eastmoney.com/report/list"
    params = {"stockCode": stock_code, "pageSize": 50, "pageNo": page,
              "industryCode": "*", "industry": "*", "rating": "*", "ratingChange": "*",
              "beginTime": "", "endTime": "", "qType": "0", "fields": "",
              "sortCol": "publishDate", "sortType": "1"}
    try:
        r = em_get(url, params=params, timeout=10)
        data = r.json()
        return (data.get("data") or []) if isinstance(data, dict) else []
    except Exception:
        return []


def eastmoney_industry_reports(industry_code: str = "*", max_pages: int = 5) -> list[dict]:
    """东财行业研报"""
    out = []
    for page in range(1, max_pages + 1):
        url = "https://reportapi.eastmoney.com/report/list"
        params = {"stockCode": "", "pageSize": 50, "pageNo": page,
                  "industryCode": industry_code, "industry": "*",
                  "rating": "*", "ratingChange": "*",
                  "beginTime": "", "endTime": "", "qType": "1",
                  "fields": "", "sortCol": "publishDate", "sortType": "1"}
        try:
            r = em_get(url, params=params, timeout=10)
            data = r.json()
            rows = (data.get("data") or []) if isinstance(data, dict) else []
            if not rows:
                break
            for row in rows:
                out.append({
                    "industry_code": industry_code,
                    "industry_name": row.get("industryName", row.get("stockName", "")),
                    "title": row.get("title", ""),
                    "org_name": row.get("orgName", ""),
                    "rating": row.get("emRatingName", ""),
                    "report_date": str(row.get("publishDate", ""))[:10],
                    "pdf_url": row.get("pdfUrl", ""),
                })
        except Exception:
            break
    return out


def download_pdf(record: dict, target_dir: str = "./reports") -> str:
    """下载研报PDF"""
    import os, re
    os.makedirs(target_dir, exist_ok=True)
    pdf_url = record.get("pdf_url", "")
    if not pdf_url:
        return ""
    if not pdf_url.startswith("http"):
        pdf_url = f"https://reportapi.eastmoney.com{pdf_url}"
    title = re.sub(r'[\\/:*?"<>|]', "_", (record.get("title", "report") or "")[:60]).strip()
    fname = f"{title}.pdf"
    fpath = os.path.join(target_dir, fname)
    headers = {"User-Agent": UA,
               "Referer": "https://data.eastmoney.com/report/"}
    try:
        r = em_get(pdf_url, headers=headers, timeout=30, max_retries=2)
        with open(fpath, "wb") as f:
            f.write(r.content)
        return fpath
    except Exception as e:
        print(f"[WARN] download_pdf: {e}")
        return ""


def ths_eps_forecast(code: str) -> list[dict]:
    """同花顺一致预期EPS"""
    pure = code.replace("SH.", "").replace("SZ.", "").replace("BJ.", "")
    url = "https://basic.10jqka.com.cn/api/stock/forecast_eps/"
    params = {"stockCode": pure, "limit": 5}
    headers = {"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        rows = (data.get("data") or []) if isinstance(data, dict) else []
        out = []
        for row in rows:
            out.append({
                "code": code,
                "year": row.get("year", ""),
                "forecast_count": row.get("预测机构数", 0),
                "mean_eps": _safe_float(row.get("均值")),
                "min_eps": _safe_float(row.get("最小值")),
                "max_eps": _safe_float(row.get("最大值")),
            })
        return out
    except Exception:
        return []


def _safe_float(v):
    try:
        return float(v) if v is not None else None
    except:
        return None

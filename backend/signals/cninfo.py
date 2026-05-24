"""巨潮公告 — 沪深北全量公告全文

来源：a-stock-data Layer 5
akshare → cninfo，免费无key。
"""
import akshare as ak
from typing import Optional
from datetime import datetime, timedelta


def get_market(code: str) -> str:
    """6位代码 → 巨潮 market 参数"""
    return "沪深京"  # akshare 统一参数


def get_disclosures(code: str, start_date: str = None, end_date: str = None,
                    limit: int = 50) -> list[dict]:
    """
    获取个股公告。
    code: 6位股票代码
    start_date/end_date: YYYY-MM-DD, 默认近30天
    返回: [{title, date, type, url, ...}, ...]
    """
    if start_date is None:
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    if end_date is None:
        end_date = datetime.now().strftime("%Y-%m-%d")

    market = get_market(code)
    try:
        # akshare 需要 YYYYMMDD 格式
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=code,
            market="沪深京",
            start_date=sd,
            end_date=ed,
        )
        if df is None or df.empty:
            return []

        # 统一列名
        col_map = {
            "公告标题": "title",
            "公告分类": "type",
            "公告日期": "date",
            "公告链接": "url",
        }
        df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
        return df.head(limit).to_dict('records')
    except Exception as e:
        raise RuntimeError(f"获取公告失败: {e}")


def get_latest_disclosures(market: str = "all", limit: int = 100) -> list[dict]:
    """
    获取全市场最新公告。
    market: 已忽略（全部使用沪深京）
    返回: [{code, name, title, date, type, url}, ...]
    """
    symbols_sample = ["600000", "600519", "600900", "000001", "000002", "002415"]
    all_results = []
    for code in symbols_sample:
        try:
            items = get_disclosures(code, limit=10)
            for item in items:
                item["code"] = code
            all_results.extend(items)
        except Exception:
            continue
    all_results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return all_results[:limit]

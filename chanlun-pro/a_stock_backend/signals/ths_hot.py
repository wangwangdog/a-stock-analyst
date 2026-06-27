"""当日强势股 + 概念题材

来源：a-stock-data Layer 6.1（原同花顺热点 API 已下线，改用 akshare 东财源替代）
"""
import akshare as ak
import pandas as pd
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def get_hot_stocks(limit: int = 60) -> list[dict]:
    """
    获取当日强势股/热门排名。
    limit: 返回条数
    返回: [{code, name, rank, change_pct, price, rank_change, ...}, ...]
    """
    # 优先: stock_hot_up_em（排名上升最快）
    for fn, rank_field, extra_fields in [
        ("stock_hot_up_em", "排名较昨日变动", True),
        ("stock_hot_rank_em", None, False),
    ]:
        try:
            df = getattr(ak, fn)()
            if df is not None and not df.empty:
                results = []
                for _, row in df.head(min(limit, len(df))).iterrows():
                    raw = str(row.get("代码", ""))
                    code = raw.replace("SH", "").replace("SZ", "").replace("BJ", "")
                    item = {
                        "code": code,
                        "name": row.get("股票名称", ""),
                        "rank": int(row.get("当前排名", 0) or 0),
                        "change_pct": float(row.get("涨跌幅", 0) or 0),
                        "price": float(row.get("最新价", 0) or 0),
                    }
                    if extra_fields and rank_field:
                        item["rank_change"] = int(row.get(rank_field, 0) or 0)
                    results.append(item)
                return results
        except Exception:
            continue

    return []


def get_hot_rank_detail(limit: int = 100) -> list[dict]:
    """东财热搜详细排名"""
    try:
        df = ak.stock_hot_rank_detail_em()
        if df is not None and not df.empty:
            return df.head(limit).to_dict('records')
    except Exception:
        pass
    return []


def get_reason_tags(date: str = None) -> list[dict]:
    """
    获取概念题材板块（替代原同花顺题材归因）。
    date: 忽略（概念板块无历史回溯）
    返回: [{name, index, change_pct, stock_count, ...}, ...]
    """
    # 使用同花顺概念板块
    try:
        df = ak.stock_board_concept_name_ths()
        if df is not None and not df.empty:
            results = []
            for _, row in df.head(100).iterrows():
                results.append({
                    "name": row.get("板块名称", ""),
                    "code": row.get("板块代码", ""),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "stock_count": int(row.get("股票数量", 0) or 0),
                    "top_stock": row.get("龙头股", ""),
                })
            return results
    except Exception:
        pass

    # Fallback: 东财概念板块
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and not df.empty:
            results = []
            for _, row in df.head(100).iterrows():
                results.append({
                    "name": row.get("板块名称", ""),
                    "code": row.get("板块代码", ""),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "stock_count": int(row.get("股票数量", 0) or 0),
                    "top_stock": row.get("龙头股", ""),
                })
            return results
    except Exception:
        pass

    return []


def get_stock_concept_tags(code: str) -> list[str]:
    """查询个股所属概念板块标签"""
    try:
        df = ak.stock_board_concept_cons_em(symbol=code)
        if df is not None and not df.empty:
            return df["板块名称"].tolist() if "板块名称" in df.columns else []
    except Exception:
        pass
    return []

"""信号层 + 新数据源 API 路由

整合自 a-stock-data 的 A 级数据源：
- 腾讯财经实时估值
- 同花顺热点+题材归因
- 龙虎榜+全市场龙虎榜
- 北向资金
- 限售解禁
- 行业对比
- 个股新闻+财联社
- 巨潮公告
- mootdx 行情
"""
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/api/signals", tags=["signals"])

# ========== 腾讯财经估值 ==========
@router.get("/tencent/quote")
async def tencent_quote(code: str = Query(..., description="股票代码，多个用逗号分隔")):
    """腾讯实时行情 — PE/PB/市值/换手率/涨跌停价"""
    from data.tencent_quote import fetch
    codes = [c.strip() for c in code.split(",") if c.strip()]
    try:
        result = fetch(codes)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 同花顺热点 ==========
@router.get("/ths/hot-stocks")
async def ths_hot_stocks(limit: int = Query(60, ge=1, le=60)):
    """当日强势股列表"""
    from signals.ths_hot import get_hot_stocks
    try:
        result = get_hot_stocks(limit=limit)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/ths/reason-tags")
async def ths_reason_tags(date: Optional[str] = None):
    """题材归因列表"""
    from signals.ths_hot import get_reason_tags
    try:
        result = get_reason_tags(date=date)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 龙虎榜 ==========
@router.get("/dragon-tiger/stock")
async def dragon_tiger_stock(
    code: str = Query(..., description="6位股票代码"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """个股龙虎榜记录"""
    from signals.dragon_tiger import get_stock_billboard
    try:
        result = get_stock_billboard(code, start_date, end_date)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/dragon-tiger/all")
async def dragon_tiger_all(date: Optional[str] = None, limit: int = Query(50, le=100)):
    """全市场龙虎榜"""
    from signals.dragon_tiger import get_all_billboard
    try:
        result = get_all_billboard(date=date, limit=limit)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 北向资金 ==========
@router.get("/northbound")
async def northbound():
    """北向资金实时（沪+深+汇总）"""
    from signals.northbound import get_all_northbound
    try:
        result = get_all_northbound()
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 限售解禁 ==========
@router.get("/lockup/upcoming")
async def lockup_upcoming(days: int = Query(90, ge=1, le=365)):
    """未来解禁股票"""
    from signals.lockup_expiry import get_upcoming_lockups
    try:
        result = get_upcoming_lockups(days=days)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/lockup/stock")
async def lockup_stock(code: str = Query(..., description="6位股票代码")):
    """个股解禁记录"""
    from signals.lockup_expiry import get_stock_lockups
    try:
        result = get_stock_lockups(code)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 行业对比 ==========
@router.get("/industry/ranking")
async def industry_ranking(source: str = Query("ths", pattern="^(ths|em|sina)$")):
    """行业板块涨跌排名"""
    from signals.industry_compare import get_industry_ranking
    try:
        result = get_industry_ranking(source=source)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/industry/concept")
async def industry_concept(code: str = Query(..., description="6位股票代码")):
    """个股所属行业/概念"""
    from signals.industry_compare import get_industry_concept
    try:
        result = get_industry_concept(code)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 新闻 ==========
@router.get("/news/stock")
async def news_stock(code: str = Query(..., description="6位股票代码"), limit: int = Query(20, le=50)):
    """个股新闻"""
    from signals.news import get_stock_news
    try:
        result = get_stock_news(code, limit=limit)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/news/cailianshe")
async def news_cailianshe(limit: int = Query(30, le=50)):
    """财联社快讯"""
    from signals.news import get_cailianshe
    try:
        result = get_cailianshe(limit=limit)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/news/global")
async def news_global(limit: int = Query(30, le=50)):
    """东财全球资讯"""
    from signals.news import get_global_news
    try:
        result = get_global_news(limit=limit)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== 巨潮公告 ==========
@router.get("/cninfo/disclosures")
async def cninfo_disclosures(
    code: str = Query(..., description="6位股票代码"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(50, le=100),
):
    """个股公告"""
    from signals.cninfo import get_disclosures
    try:
        result = get_disclosures(code, start_date, end_date, limit=limit)
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ========== mootdx 行情 ==========
@router.get("/mootdx/klines")
async def mootdx_klines(
    symbol: str = Query(..., description="6位股票代码"),
    category: int = Query(4, description="4=日线,5=周线,6=月线"),
    offset: int = Query(10, ge=1, le=1000),
):
    """mootdx K线数据"""
    try:
        from data.mootdx_fetcher import get_klines
        result = get_klines(symbol, category=category, offset=offset)
        if result is None:
            return {"status": "error", "message": "mootdx 不可用或无数据"}
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mootdx/quote")
async def mootdx_quote(symbols: str = Query(..., description="股票代码，多个用逗号分隔")):
    """mootdx 五档盘口"""
    try:
        from data.mootdx_fetcher import get_quotes
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
        result = get_quotes(sym_list)
        if result is None:
            return {"status": "error", "message": "mootdx 不可用（非交易时段或连接失败）"}
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mootdx/finance")
async def mootdx_finance(symbol: str = Query(..., description="6位股票代码")):
    """mootdx 财务快照"""
    try:
        from data.mootdx_fetcher import get_finance
        result = get_finance(symbol)
        if result is None:
            return {"status": "error", "message": "mootdx 不可用（非交易时段或连接失败）"}
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/mootdx/f10")
async def mootdx_f10(
    symbol: str = Query(..., description="6位股票代码"),
    category: str = Query("公司概况", description="F10分类"),
):
    """mootdx F10资料"""
    try:
        from data.mootdx_fetcher import get_f10
        result = get_f10(symbol, category=category)
        if result is None:
            return {"status": "error", "message": "mootdx 不可用（非交易时段或连接失败）"}
        return {"status": "ok", "data": result}
    except Exception as e:
        return {"status": "error", "message": str(e)}

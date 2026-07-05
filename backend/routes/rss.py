"""RSS 新闻 API 路由（对接 chanlun-pro 三去重 RSS 引擎）"""
import logging
import re
import os
import time
import sqlite3
from pathlib import Path
from fastapi import APIRouter, Query, BackgroundTasks
from fastapi.responses import JSONResponse

logger = logging.getLogger("rss_route")
router = APIRouter(prefix="/rss-api", tags=["RSS新闻"])

# chanlun-pro RSS 数据在 ~/.chanlun_pro/db/chanlun_klines.sqlite 的 rss_news_dedup 表
RSS_DB = str(Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite"))
CL_RSS_FETCHER = str(Path(__file__).resolve().parent.parent.parent / "chanlun-pro" / "web" / "chanlun_chart" / "cl_app" / "rss_fetcher.py")

# 源名映射
SOURCE_NAMES = {
    "trendradar": "TrendRadar",
    "buzzing_hn": "Buzzing HN",
    "buzzing_ph": "Buzzing PH",
    "tavily": "Tavily 财经",
}


def _get_conn():
    conn = sqlite3.connect(RSS_DB)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/list")
async def rss_list(
    source_id: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        conn = _get_conn()
        if source_id:
            rows = conn.execute(
                "SELECT id, source, source_name, title, link, summary, published, fetched_at "
                "FROM rss_news_dedup WHERE source=? ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
                (source_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, source, source_name, title, link, summary, published, fetched_at "
                "FROM rss_news_dedup ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"RSS query failed: {e}")
        rows = []

    return JSONResponse(
        content={
            "news": [
                {
                    "id": r["id"],
                    "source": r["source"],
                    "source_name": r["source_name"] or SOURCE_NAMES.get(r["source"], r["source"]),
                    "source_color": "#333",
                    "title": re.sub(r"<[^>]+>", "", r["title"]),
                    "link": r["link"],
                    "summary": r["summary"] or "",
                    "published": r["published"] or "",
                    "fetched_at": _fmt_ts(r["fetched_at"]),
                }
                for r in rows
            ],
            "count": len(rows),
            "offset": offset,
        },
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _fmt_ts(ts):
    """Unix秒级时间戳 → ISO日期字符串（含时区）"""
    if not ts:
        return ""
    try:
        import datetime
        dt = datetime.datetime.fromtimestamp(float(ts))
        # 加时区偏移 +08:00
        tz = datetime.timezone(datetime.timedelta(hours=8))
        dt = dt.replace(tzinfo=tz)
        return dt.isoformat()
    except:
        return str(ts)


@router.get("/sources")
async def rss_sources():
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT DISTINCT source, source_name FROM rss_news_dedup ORDER BY source"
        ).fetchall()
        conn.close()
        sources = [
            {"key": r["source"], "name": r["source_name"] or SOURCE_NAMES.get(r["source"], r["source"])}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"RSS sources query failed: {e}")
        sources = []
    return {"sources": sources}


@router.get("/stats")
async def rss_stats():
    try:
        conn = _get_conn()
        total = conn.execute("SELECT COUNT(*) as c FROM rss_news_dedup").fetchone()["c"]
        conn.close()
    except Exception as e:
        logger.error(f"RSS stats failed: {e}")
        total = 0
    return {"total": total}


@router.post("/fetch")
async def rss_fetch(background_tasks: BackgroundTasks):
    """后台触发 chanlun-pro RSS 抓取 + 三去重"""
    def _run():
        try:
            os.system(f"cd /home/dogzi/.openclaw/workspace/a-stock-analyst && "
                      f"{Path.home() / '.openclaw' / 'workspace' / 'a-stock-analyst' / 'chanlun-pro' / '.venv' / 'bin' / 'python3'} "
                      f"{CL_RSS_FETCHER} 2>&1 | logger -t rss-fetch")
        except Exception as e:
            logger.error(f"RSS fetch failed: {e}")

    background_tasks.add_task(_run)
    return {"status": "started"}

"""RSS 新闻 API 路由"""
import logging
import re
from fastapi import APIRouter, Query, BackgroundTasks

from rss_fetcher import get_items, get_sources, get_stats, fetch_all

logger = logging.getLogger("rss_route")
router = APIRouter(prefix="/rss-api", tags=["RSS新闻"])

# 源名/颜色缓存
_source_map = {}


def _load_source_map():
    if not _source_map:
        for s in get_sources():
            _source_map[s["id"]] = {"name": s["name"], "color": s.get("color", "#333")}
    return _source_map


def _clean_html(text):
    return re.sub(r"<[^>]+>", "", text)


def _run_fetch():
    try:
        return fetch_all()
    except Exception as e:
        logger.error(f"RSS fetch failed: {e}")
        return 0


@router.get("/sources")
async def rss_sources():
    return {"sources": get_sources()}


@router.get("/list")
async def rss_list(
    source_id: str = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    news = get_items(source_id=source_id, limit=limit, offset=offset)
    sources = _load_source_map()

    return {
        "news": [
            {
                "id": n["id"],
                "source": n["source_id"],
                "source_name": sources.get(n["source_id"], {}).get("name", n["source_id"]),
                "source_color": sources.get(n["source_id"], {}).get("color", "#333"),
                "title": _clean_html(n["title"]),
                "link": n["link"],
                "summary": n["summary"],
                "published": n["published"],
                "fetched_at": n["fetched_at"],
            }
            for n in news
        ],
        "count": len(news),
        "offset": offset,
    }


@router.get("/stats")
async def rss_stats():
    return get_stats()


@router.post("/fetch")
async def rss_fetch(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_fetch)
    return {"status": "started"}

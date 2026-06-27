"""
RSS 新闻聚合模块
使用 feedparser 从多个财经/科技源抓取新闻，存入 SQLite
"""
import logging
import re
import sqlite3
import time
from pathlib import Path

import feedparser

logger = logging.getLogger("rss_fetcher")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rss.db"

RSS_SOURCES = [
    {
        "id": "hackernews",
        "name": "HN",
        "url": "https://hnrss.org/frontpage",
        "color": "#FF6600",
        "enabled": True,
    },
    {
        "id": "eastmoney",
        "name": "东方财富",
        "url": "https://rsshub.rssforever.com/eastmoney/search/热门",
        "color": "#E4393C",
        "enabled": True,
    },
    {
        "id": "cls",
        "name": "财联社",
        "url": "https://www.cls.cn/rss",
        "color": "#C4161C",
        "enabled": False,
    },
    {
        "id": "36kr",
        "name": "36氪",
        "url": "https://36kr.com/feed",
        "color": "#07C160",
        "enabled": False,
    },
]


def _get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            summary TEXT DEFAULT '',
            published TEXT DEFAULT '',
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(source_id, link)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            color TEXT DEFAULT '#333',
            enabled INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    return conn


def _init_sources():
    conn = _get_conn()
    for src in RSS_SOURCES:
        conn.execute("""
            INSERT OR REPLACE INTO rss_sources (id, name, url, color, enabled)
            VALUES (?, ?, ?, ?, ?)
        """, (src["id"], src["name"], src["url"], src["color"], int(src["enabled"])))
    conn.commit()
    conn.close()


def fetch_source(source):
    conn = _get_conn()
    new_count = 0
    try:
        logger.info(f"Fetching RSS: {source['name']} ({source['url']})")
        # feedparser 默认超时 20s，适当放宽
        feed = feedparser.parse(source["url"], agent="a-stock-rss/1.0")
        # 二次校验：如果解析异常且无条目，走超时逻辑
        if feed.bozo and not feed.entries:
            ex = getattr(feed, "bozo_exception", None)
            if ex and "timed out" in str(ex).lower():
                logger.warning(f"RSS timeout for {source['id']}")
            else:
                logger.warning(f"RSS parse error for {source['id']}: {ex}")
            conn.close()
            return 0
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            raw_summary = entry.get("summary", "") or entry.get("description", "")
            summary = re.sub(r"<[^>]+>", "", raw_summary)[:200] if raw_summary else ""
            published = entry.get("published", "") or entry.get("updated", "")
            before = conn.execute(
                "SELECT COUNT(*) FROM rss_items WHERE source_id=? AND link=?",
                (source["id"], link),
            ).fetchone()[0]
            if before == 0:
                conn.execute(
                    "INSERT INTO rss_items (source_id, title, link, summary, published) VALUES (?, ?, ?, ?, ?)",
                    (source["id"], title, link, summary.strip(), published),
                )
                new_count += 1
        conn.commit()
    except Exception as e:
        logger.error(f"Error fetching {source['id']}: {e}")
    finally:
        conn.close()
    return new_count


def fetch_all():
    _init_sources()
    total = 0
    for src in RSS_SOURCES:
        if not src.get("enabled", True):
            continue
        n = fetch_source(src)
        total += n
        logger.info(f"  {src['name']}: +{n} new")
        time.sleep(0.5)
    logger.info(f"RSS fetch done: {total} new items total")
    return total


def get_items(source_id=None, limit=50, offset=0):
    conn = _get_conn()
    if source_id:
        rows = conn.execute(
            "SELECT * FROM rss_items WHERE source_id=? ORDER BY COALESCE(published, fetched_at) DESC LIMIT ? OFFSET ?",
            (source_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rss_items ORDER BY COALESCE(published, fetched_at) DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"], "source_id": r["source_id"],
            "title": r["title"], "link": r["link"],
            "summary": r["summary"], "published": r["published"],
            "fetched_at": r["fetched_at"],
        }
        for r in rows
    ]


def get_sources():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM rss_sources WHERE enabled=1 ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = _get_conn()
    total = conn.execute("SELECT COUNT(*) FROM rss_items").fetchone()[0]
    recent = conn.execute(
        "SELECT COUNT(*) FROM rss_items WHERE fetched_at > datetime('now','-24 hours')"
    ).fetchone()[0]
    conn.close()
    return {"total": total, "recent_24h": recent}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = fetch_all()
    s = get_stats()
    print(f"\nNew items: {n}, Total: {s['total']}, Recent 24h: {s['recent_24h']}")

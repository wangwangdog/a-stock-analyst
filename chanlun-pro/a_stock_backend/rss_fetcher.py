"""
RSS 新闻聚合模块
- 从多个 RSS 源抓取新闻，存入 SQLite
- 提供 API 接口供前端调用
- 支持定时刷新（配合 cron）
"""

import sqlite3
import os
import hashlib
import time
import logging
import feedparser

logger = logging.getLogger('rss-fetcher')

DB_PATH = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

# RSS 订阅源配置
RSS_SOURCES = {
    "trendradar": {
        "url": "https://trendradar.techleaf.xyz/rss.xml",
        "name": "TrendRadar 热点",
        "enabled": True,
    },
    "buzzing_hn": {
        "url": "https://hn.buzzing.cc/rss.xml",
        "name": "Buzzing HN",
        "enabled": True,
    },
    "buzzing_ph": {
        "url": "https://ph.buzzing.cc/rss.xml",
        "name": "Buzzing ProductHunt",
        "enabled": True,
    },
}


def get_conn():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_table():
    """初始化 rss_news 表"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_news (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            summary TEXT,
            published TEXT,
            fetched_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rss_news_fetched 
        ON rss_news(fetched_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rss_news_source 
        ON rss_news(source, fetched_at DESC)
    """)
    conn.commit()
    conn.close()
    logger.info("rss_news table ready")


def fetch_feed(source_key, source_cfg):
    """抓取单个 RSS 源"""
    url = source_cfg["url"]
    name = source_cfg["name"]
    logger.info(f"Fetching {name}: {url}")

    try:
        feed = feedparser.parse(url)
    except Exception as e:
        logger.error(f"Failed to fetch {name}: {e}")
        return 0

    if feed.bozo and not feed.entries:
        logger.error(f"Parse error for {name}: {feed.bozo_exception}")
        return 0

    count = 0
    conn = get_conn()
    now = time.time()

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        if not title or not link:
            continue

        # 生成唯一 ID
        content_id = hashlib.md5(f"{source_key}:{link}".encode()).hexdigest()

        summary = entry.get("summary", "")
        # 截断 summary 防止存太多 HTML
        if summary and len(summary) > 500:
            summary = summary[:500]

        published = entry.get("published", "")

        try:
            conn.execute(
                "INSERT OR IGNORE INTO rss_news (id, source, source_name, title, link, summary, published, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (content_id, source_key, name, title, link, summary, published, now),
            )
            if conn.total_changes > 0:
                count += 1
        except Exception as e:
            logger.error(f"DB insert error: {e}")

    conn.commit()
    conn.close()
    logger.info(f"{name}: +{count} new articles")
    return count


def fetch_all():
    """抓取所有启用的 RSS 源"""
    init_table()
    total = 0
    for key, cfg in RSS_SOURCES.items():
        if cfg.get("enabled", True):
            total += fetch_feed(key, cfg)
    logger.info(f"Total new articles: {total}")
    return total


def get_news(limit=50, offset=0, source=None):
    """获取新闻列表"""
    conn = get_conn()
    if source:
        rows = conn.execute(
            "SELECT id, source, source_name, title, link, published, fetched_at "
            "FROM rss_news WHERE source=? ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (source, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, source, source_name, title, link, published, fetched_at "
            "FROM rss_news ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_news_count(source=None):
    """获取新闻总数"""
    conn = get_conn()
    if source:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM rss_news WHERE source=?", (source,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) as cnt FROM rss_news").fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_sources():
    """获取源状态"""
    sources = []
    for key, cfg in RSS_SOURCES.items():
        sources.append({
            "key": key,
            "name": cfg["name"],
            "enabled": cfg.get("enabled", True),
        })
    return sources


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    init_table()
    c = fetch_all()
    print(f"Fetched {c} new articles")
    news = get_news(limit=5)
    for n in news:
        print(f"  [{n['published']}] {n['title']}")

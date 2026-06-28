"""
RSS 新闻聚合模块（三去重版）
- 从多个 RSS 源抓取新闻，存入 SQLite 原始表
- 三去重：URL去重 → 标题精确去重 → 标题相似去重
- 入库到 rss_news_dedup 干净表
- 支持按时间段增量抓取
"""

import sqlite3
import os
import hashlib
import time
import re
import logging
from difflib import SequenceMatcher

import feedparser

logger = logging.getLogger('rss-fetcher')

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

# 标题相似度阈值（0~1，1=完全一致）
TITLE_SIM_THRESHOLD = 0.85

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


# ── 数据库操作 ──

def get_conn():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    """初始化所有相关表"""
    conn = get_conn()

    # raw 原始抓取表（保留原始数据）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_news (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            summary TEXT,
            published TEXT,
            fetched_at REAL NOT NULL,
            dedup_checked INTEGER DEFAULT 0
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

    # dedup 干净表（三去重后）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_news_dedup (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            summary TEXT,
            published TEXT,
            fetched_at REAL NOT NULL,
            UNIQUE(link),
            UNIQUE(title)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rss_news_dedup_fetched
        ON rss_news_dedup(fetched_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_rss_news_dedup_source
        ON rss_news_dedup(source, fetched_at DESC)
    """)

    # 抓取状态表（记录每次抓取时间）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rss_fetch_state (
            source TEXT PRIMARY KEY,
            last_fetched_at REAL NOT NULL DEFAULT 0,
            last_article_time TEXT DEFAULT ''
        )
    """)

    conn.commit()
    conn.close()
    logger.info("RSS tables ready")


# ── 工具函数 ──

def _normalize_title(title):
    """规范化标题，用于去重比较"""
    if not title:
        return ""
    # 转小写
    t = title.lower().strip()
    # 去标点符号
    t = re.sub(r'[^\w\u4e00-\u9fff\s]', '', t)
    # 去多余空格
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def _title_similarity(t1, t2):
    """计算两个规范化标题的相似度"""
    n1 = _normalize_title(t1)
    n2 = _normalize_title(t2)
    if not n1 or not n2:
        return 0.0
    return SequenceMatcher(None, n1, n2).ratio()


def _get_content_id(source_key, link, title=""):
    """生成唯一内容ID"""
    raw = f"{source_key}:{link}:{title}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_fetch_state(source_key):
    """获取上次抓取时间"""
    conn = get_conn()
    row = conn.execute(
        "SELECT last_fetched_at FROM rss_fetch_state WHERE source=?",
        (source_key,),
    ).fetchone()
    conn.close()
    return row["last_fetched_at"] if row else 0


def _update_fetch_state(source_key, now, last_published=""):
    """更新抓取时间"""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO rss_fetch_state (source, last_fetched_at, last_article_time) VALUES (?, ?, ?)",
        (source_key, now, last_published),
    )
    conn.commit()
    conn.close()


# ── TrendRadar 特殊解析 ──

def _extract_trendradar_items(entry, source_key, source_name, now):
    """从 TrendRadar 每日汇总的 description HTML 中提取单条新闻"""
    items = []
    summary = entry.get("summary", "")
    published = entry.get("published", "")
    if not summary:
        return items

    li_pattern = re.compile(r"<li>(.*?)</li>", re.DOTALL | re.IGNORECASE)
    a_pattern = re.compile(r'<a\s+href="([^"]+)"[^>]*>([^<]+)</a>')

    for li in li_pattern.findall(summary):
        a_match = a_pattern.search(li)
        if not a_match:
            continue
        link = a_match.group(1).strip()
        title = a_match.group(2).strip()
        if not title or not link:
            continue

        src_match = re.search(r"\[([^\]]+)\]", li.split("</a>")[-1] if "</a>" in li else li)
        source_tag = src_match.group(1) if src_match else ""

        content_id = _get_content_id(source_key, link, title)

        items.append({
            "id": content_id,
            "source": source_key,
            "source_name": source_name,
            "title": title,
            "link": link,
            "summary": f"[{source_tag}] {published}" if source_tag else published,
            "published": published,
            "fetched_at": now,
        })

    return items


# ── 三去重 ──

def _dedup_url(conn, link):
    """Layer 1: URL 精确去重"""
    return conn.execute("SELECT 1 FROM rss_news_dedup WHERE link=?", (link,)).fetchone()


def _dedup_title_exact(conn, title):
    """Layer 2: 标题精确去重"""
    return conn.execute("SELECT 1 FROM rss_news_dedup WHERE title=?", (title,)).fetchone()


def _dedup_title_similar(conn, title):
    """Layer 3: 标题相似去重（字符级模糊匹配）"""
    rows = conn.execute(
        "SELECT title FROM rss_news_dedup ORDER BY fetched_at DESC LIMIT 1000"
    ).fetchall()
    for row in rows:
        if _title_similarity(title, row["title"]) >= TITLE_SIM_THRESHOLD:
            return True
    return False


def _dedup_item(conn, item):
    """三层去重：URL → 标题精确 → 标题相似，通过则 None，被去重则返回原因"""
    if _dedup_url(conn, item["link"]):
        return f"url dup: {item['link'][:60]}"
    if _dedup_title_exact(conn, item["title"]):
        return f"title exact dup: {item['title'][:40]}"
    if _dedup_title_similar(conn, item["title"]):
        return f"title similar dup: {item['title'][:40]}"
    return None


def _run_dedup_pipeline(raw_table="rss_news", dedup_table="rss_news_dedup"):
    """
    将 raw 表中未去重的数据通过三层去重写入 dedup 表
    返回：{deduped: N, skipped_url: N, skipped_title_exact: N, skipped_title_sim: N}
    """
    stats = {"deduped": 0, "skipped_url": 0, "skipped_title_exact": 0, "skipped_title_sim": 0}

    conn = get_conn()

    # 只处理未检查过的条目（避免重复检查被跳过的）
    rows = conn.execute(
        f"SELECT r.* FROM {raw_table} r "
        f"LEFT JOIN {dedup_table} d ON r.id = d.id "
        f"WHERE d.id IS NULL AND r.dedup_checked = 0 "
        f"ORDER BY r.fetched_at ASC"
    ).fetchall()

    if not rows:
        conn.close()
        return stats

    logger.info(f"Dedup pipeline: processing {len(rows)} raw items")

    for row in rows:
        item = dict(row)
        reason = _dedup_item(conn, item)
        if reason:
            # 标记已检查（被跳过的下次不用再跑一遍）
            conn.execute(f"UPDATE {raw_table} SET dedup_checked=1 WHERE id=?", (item["id"],))
            if reason.startswith("url dup"):
                stats["skipped_url"] += 1
            elif reason.startswith("title exact dup"):
                stats["skipped_title_exact"] += 1
            else:
                stats["skipped_title_sim"] += 1
            logger.debug(f"SKIP: {reason}")
            continue

        # 通过去重，写入 dedup 表
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO {dedup_table} "
                f"(id, source, source_name, title, link, summary, published, fetched_at) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (item["id"], item["source"], item["source_name"],
                 item["title"], item["link"], item.get("summary", ""),
                 item["published"], item["fetched_at"]),
            )
            if conn.total_changes > 0:
                stats["deduped"] += 1
            conn.execute(f"UPDATE {raw_table} SET dedup_checked=1 WHERE id=?", (item["id"],))
        except Exception as e:
            logger.error(f"Dedup insert error: {e}")

    conn.commit()
    conn.close()

    logger.info(
        f"Dedup done: +{stats['deduped']} new | "
        f"url dup {stats['skipped_url']} | "
        f"title exact {stats['skipped_title_exact']} | "
        f"title sim {stats['skipped_title_sim']}"
    )
    return stats


# ── 抓取逻辑（按时间段增量）──

def fetch_feed(source_key, source_cfg):
    """抓取单个 RSS 源，仅获取新内容"""
    url = source_cfg["url"]
    name = source_cfg["name"]
    last_fetched = _get_fetch_state(source_key)
    logger.info(f"Fetching {name}: {url} (last_fetched={last_fetched:.0f})")

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
    max_article_time = ""

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        published = entry.get("published", "")

        # TrendRadar 特殊处理
        if source_key == "trendradar":
            sub_items = _extract_trendradar_items(entry, source_key, name, now)
            if not sub_items:
                continue

            # 取子项中最晚的发布时间
            for si in sub_items:
                if si["published"] > max_article_time:
                    max_article_time = si["published"]

            # 全部插入 raw 表（去重在管道里做）
            for item in sub_items:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO rss_news "
                        "(id, source, source_name, title, link, summary, published, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (item["id"], item["source"], item["source_name"],
                         item["title"], item["link"], item["summary"],
                         item["published"], item["fetched_at"]),
                    )
                    if conn.total_changes > 0:
                        count += 1
                except Exception as e:
                    logger.error(f"DB insert error: {e}")
            continue

        # 常规处理
        if not title or not link:
            continue

        if published > max_article_time:
            max_article_time = published

        content_id = _get_content_id(source_key, link, title)
        summary = entry.get("summary", "")
        if summary and len(summary) > 500:
            summary = summary[:500]

        try:
            conn.execute(
                "INSERT OR IGNORE INTO rss_news "
                "(id, source, source_name, title, link, summary, published, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (content_id, source_key, name, title, link, summary, published, now),
            )
            if conn.total_changes > 0:
                count += 1
        except Exception as e:
            logger.error(f"DB insert error: {e}")

    conn.commit()
    conn.close()

    _update_fetch_state(source_key, now, max_article_time)
    logger.info(f"{name}: +{count} raw items")
    return count


def fetch_all():
    """抓取所有启用的 RSS 源，然后运行三去重"""
    init_tables()
    total_raw = 0
    for key, cfg in RSS_SOURCES.items():
        if cfg.get("enabled", True):
            total_raw += fetch_feed(key, cfg)

    # 运行三去重管道
    stats = _run_dedup_pipeline()

    logger.info(
        f"Fetch round complete: +{total_raw} raw → +{stats['deduped']} deduped "
        f"(dedup skipped: url={stats['skipped_url']} title_exact={stats['skipped_title_exact']} title_sim={stats['skipped_title_sim']})"
    )
    return total_raw, stats


# ── 全量重新去重（用于修复已有数据）──

def re_dedup_all():
    """对所有 raw 数据重新跑三去重"""
    conn = get_conn()
    conn.execute("DELETE FROM rss_news_dedup")
    conn.commit()
    conn.close()
    return _run_dedup_pipeline()


# ── API 查询 ──

def get_news(limit=50, offset=0, source=None):
    """从 dedup 表获取新闻列表"""
    conn = get_conn()
    if source:
        rows = conn.execute(
            "SELECT id, source, source_name, title, link, published, fetched_at "
            "FROM rss_news_dedup WHERE source=? ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (source, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, source, source_name, title, link, published, fetched_at "
            "FROM rss_news_dedup ORDER BY fetched_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_news_count(source=None):
    """获取新闻总数（从 dedup 表）"""
    conn = get_conn()
    if source:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM rss_news_dedup WHERE source=?", (source,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) as cnt FROM rss_news_dedup").fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_raw_news_count(source=None):
    """获取 raw 表总数"""
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
    conn = get_conn()
    sources = []
    for key, cfg in RSS_SOURCES.items():
        row = conn.execute(
            "SELECT last_fetched_at FROM rss_fetch_state WHERE source=?",
            (key,),
        ).fetchone()
        sources.append({
            "key": key,
            "name": cfg["name"],
            "enabled": cfg.get("enabled", True),
            "last_fetched_at": row["last_fetched_at"] if row else 0,
        })
    conn.close()
    return sources


def get_dedup_stats():
    """获取去重统计"""
    conn = get_conn()
    raw = conn.execute("SELECT COUNT(*) as c FROM rss_news").fetchone()["c"]
    deduped = conn.execute("SELECT COUNT(*) as c FROM rss_news_dedup").fetchone()["c"]
    conn.close()
    return {
        "raw": raw,
        "deduped": deduped,
        "skipped": raw - deduped,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    init_tables()
    total_raw, stats = fetch_all()
    print(f"\n结果: raw +{total_raw} → deduped +{stats['deduped']}")
    print(f"去重明细: url={stats['skipped_url']} title_exact={stats['skipped_title_exact']} title_sim={stats['skipped_title_sim']}")

    dedup_info = get_dedup_stats()
    print(f"总数: raw={dedup_info['raw']} deduped={dedup_info['deduped']} skipped={dedup_info['skipped']}")

    news = get_news(limit=5)
    for n in news:
        print(f"  [{n['published']}] [{n['source']}] {n['title'][:60]}")

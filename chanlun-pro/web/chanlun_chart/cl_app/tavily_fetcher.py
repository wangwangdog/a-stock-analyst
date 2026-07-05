"""Tavily 新闻抓取模块
从 Tavily API 获取财经/科技新闻，写入 rss_news + rss_news_dedup 表
与 chanlun-pro RSS 抓取共享同一套去重管道
"""
import hashlib
import json
import logging
import os
import sys
import time

# 添加上级目录到路径，复用 rss_fetcher 的 DB 工具
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rss_fetcher import get_conn, _get_content_id, _run_dedup_pipeline

logger = logging.getLogger("tavily-fetcher")

DB_PATH = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
TAVILY_API_KEY = "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"

# Tavily 搜索主题列表（覆盖 A 股财经/科技/行业热点）
SEARCH_TOPICS = [
    "A股 市场 热点 新闻",
    "行业 龙头 上市公司 最新 动态",
    "科技 产业 人工智能 半导体 新能源",
    "汽车 消费 医药 金融 板块",
]

SOURCE_KEY = "tavily"
SOURCE_NAME = "Tavily 财经"


def _init_tavily_table():
    """确保 rss_news 和 rss_news_dedup 表存在（复用 rss_fetcher 的初始化）"""
    from rss_fetcher import init_tables
    init_tables()


def fetch_tavily_news():
    """用 Tavily API 搜索各主题，结果写入 rss_news 表"""
    from tavily import TavilyClient
    client = TavilyClient(TAVILY_API_KEY)

    conn = get_conn()
    now = time.time()
    total_new = 0

    for query in SEARCH_TOPICS:
        logger.info(f"Tavily search: {query}")
        try:
            resp = client.search(
                query=query,
                search_depth="advanced",
                max_results=10,
            )
        except Exception as e:
            logger.error(f"Tavily search failed for '{query}': {e}")
            continue

        results = resp.get("results", []) if isinstance(resp, dict) else []
        for item in results:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "")[:500]

            if not title or not url:
                continue

            content_id = _get_content_id(SOURCE_KEY, url, title)

            try:
                conn.execute(
                    "INSERT OR IGNORE INTO rss_news "
                    "(id, source, source_name, title, link, summary, published, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (content_id, SOURCE_KEY, SOURCE_NAME,
                     title, url, content, "", now),
                )
                if conn.total_changes > 0:
                    total_new += 1
            except Exception as e:
                logger.error(f"DB insert error: {e}")

        time.sleep(0.5)  # Tavily API 限流保护

    conn.commit()
    conn.close()

    logger.info(f"Tavily fetch: +{total_new} raw items")
    return total_new


def fetch_and_dedup():
    """抓取 + 三去重，返回统计"""
    _init_tavily_table()
    raw_count = fetch_tavily_news()
    stats = _run_dedup_pipeline()
    logger.info(
        f"Tavily round: +{raw_count} raw → +{stats['deduped']} deduped "
        f"(skipped: url={stats['skipped_url']} title_exact={stats['skipped_title_exact']} title_sim={stats['skipped_title_sim']})"
    )
    return raw_count, stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    raw, stats = fetch_and_dedup()
    print(f"TAVILY DONE: +{raw} raw, +{stats['deduped']} deduped")

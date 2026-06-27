#!/usr/bin/env bash
# 每15分钟执行：chanlun-pro RSS 新闻抓取 + 三去重
set -e
cd /home/dogzi/.openclaw/workspace/a-stock-analyst
CHANLUN_VENV="/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/.venv/bin/python3"
RSS_FETCHER="/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/web/chanlun_chart/cl_app/rss_fetcher.py"
exec "$CHANLUN_VENV" "$RSS_FETCHER"

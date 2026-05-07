#!/usr/bin/env bash
# 每日收盘后（17:00）补齐当日 K 线数据
# 1. sequoia 增量同步 + 策略
# 2. kline_cache 增量同步
set -euo pipefail

LOGFILE="/tmp/daily_update_$(date +%Y%m%d).log"
cd /home/dogzi/.openclaw/workspace/a-stock-analyst

echo "=== $(date) 开始每日更新 ===" > "$LOGFILE"

echo "--- sequoia 同步 ---" >> "$LOGFILE"
python3 -c "
import sys
sys.path.insert(0, 'backend')
from data.sequoia_engine import daily_sync
result = daily_sync()
print(f'sync_count={result[\"sync_count\"]}, stocks={result[\"total_symbols\"]}, picks={result[\"total_picks\"]}')
" >> "$LOGFILE" 2>&1

echo "--- kline_cache 增量 ---" >> "$LOGFILE"
python3 backend/scripts/data_update.py >> "$LOGFILE" 2>&1

echo "=== $(date) 完成 ===" >> "$LOGFILE"

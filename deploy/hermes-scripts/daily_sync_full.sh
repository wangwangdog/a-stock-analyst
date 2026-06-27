#!/bin/bash
set -e
cd /home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro

PYTHON=/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/.venv/bin/python
DB_PATH=/mnt/disk990g/sqlite-data/chanlun_klines.sqlite
TODAY=$(date +%Y-%m-%d)

echo "=== 日线数据全量同步 $TODAY ==="
echo ""

# === 第1步：补齐今日日线数据（腾讯API → stock_daily）===
echo "【Step 1/3】补齐今日日线数据..."
$PYTHON sync_daily_today.py || echo "  [warn] sync_daily_today.py 返回非0"
echo ""

# === 第2步：stock_daily → kline_cache ===
echo "【Step 2/3】stock_daily → kline_cache..."
$PYTHON /home/dogzi/.hermes/scripts/sync_stock_daily_to_cache.py || echo "  [warn] sync_stock_daily_to_cache.py 返回非0"
echo ""

# === 第3步：上证指数 SH.000001 增量补充 ===
echo "【Step 3/4】上证指数 SH.000001 增量补充..."
$PYTHON /home/dogzi/.hermes/scripts/sync_sh_index.py || echo "  [warn] sync_sh_index.py 返回非0"
echo ""

# === 第4步：CR 指标增量更新 ===
echo "【Step 4/4】CR 指标增量更新..."
CR_SCRIPT="/home/dogzi/.openclaw/workspace/a-stock-analyst/backend/scripts/calc_cr_indicator.py"
if [ -f "$CR_SCRIPT" ]; then
    $PYTHON "$CR_SCRIPT" || echo "  [warn] calc_cr_indicator.py 返回非0"
else
    echo "  [warn] calc_cr_indicator.py 不存在，跳过"
fi
echo ""

echo "=== 全部完成 $(date '+%H:%M:%S') ==="

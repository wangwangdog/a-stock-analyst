#!/usr/bin/env bash
# ================================================================
# 每日七流水线统一执行脚本
# 交易日 15:05 由 cron 触发，顺序执行全部任务
# ================================================================
set -o pipefail  # 不设 -e，单个任务失败不影响后续

export TZ=Asia/Shanghai
DIR="/home/dogzi/.openclaw/workspace/a-stock-analyst"
CL_DIR="/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro"
LOG="/tmp/daily_all_$(date +%Y%m%d).log"
TODAY="$(date +%Y-%m-%d)"
START_TS=$(date +%s)

cd "$DIR" || { echo "❌ 无法进入 $DIR"; exit 1; }
echo -e "\n========== 📊 每日七流水线  $(date) ==========" | tee -a "$LOG"
echo "交易日: $TODAY" | tee -a "$LOG"

# ---------- 交易日判断 ----------
IS_TRADING=$(python3 -c "
import sqlite3
from pathlib import Path
DB = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))
try:
    conn = sqlite3.connect(DB)
    r = conn.execute('SELECT is_trading_day FROM trade_calendar WHERE calendar_date=?', ('$TODAY',)).fetchone()
    conn.close()
    print(r[0] if r and r[0]==1 else 0)
except:
    print(0)
" 2>/dev/null)

if [ "$IS_TRADING" != "1" ]; then
    echo "⏭️ 非交易日，跳过" | tee -a "$LOG"
    exit 0
fi

echo "✅ 交易日，开始执行七流水线" | tee -a "$LOG"
echo "---" | tee -a "$LOG"

# ---- 12-Factor 线程管理：启动 ----
THREAD_ID="daily_pipeline_$TODAY"
PYTHON_THREAD_CMD="python3 -c \"import sys; sys.path.insert(0, '$DIR/backend'); from data.thread_manager import start; print(start('$THREAD_ID', 'daily_pipeline', {'date': '$TODAY', 'tasks': 7}))\" 2>&1"
eval "$PYTHON_THREAD_CMD" >> "$LOG" 2>&1 || true

TOTAL_OK=0
TOTAL_FAIL=0

run_task() {
    local num=$1
    local name=$2
    local cmd=$3
    local timeout=$4
    local step_name="task_${num}_${name// /_}"
    echo "" >> "$LOG"
    echo "━━━ [${num}/7] ${name}  $(date) ━━━" | tee -a "$LOG"

    # 检查点：任务开始
    PYTHON_CP="python3 -c \"import sys; sys.path.insert(0, '$DIR/backend'); from data.thread_manager import checkpoint; print(checkpoint('$THREAD_ID', '$step_name', 'started'))\" 2>&1"
    eval "$PYTHON_CP" >> "$LOG" 2>&1 || true

    local t0=$(date +%s)
    if timeout "$timeout" bash -c "$cmd" >> "$LOG" 2>&1; then
        local t1=$(date +%s)
        local elapsed=$((t1 - t0))
        echo "✅ [${num}/7] ${name} 完成 (${elapsed}s)" | tee -a "$LOG"
        # 检查点：任务完成
        PYTHON_CP_OK="python3 -c \"import sys; sys.path.insert(0, '$DIR/backend'); from data.thread_manager import checkpoint; print(checkpoint('$THREAD_ID', '$step_name', 'done', {'elapsed_s': $elapsed}))\" 2>&1"
        eval "$PYTHON_CP_OK" >> "$LOG" 2>&1 || true
        TOTAL_OK=$((TOTAL_OK + 1))
    else
        local t1=$(date +%s)
        local elapsed=$((t1 - t0))
        echo "❌ [${num}/7] ${name} 失败 (${elapsed}s)" | tee -a "$LOG"
        # 结构化错误记录
        PYTHON_ERR="python3 -c \"import sys; sys.path.insert(0, '$DIR/backend'); from data.thread_manager import record_error; print(record_error('$THREAD_ID', '$step_name', 'timeout', '任务超时或失败，耗时${elapsed}s'))\" 2>&1"
        eval "$PYTHON_ERR" >> "$LOG" 2>&1 || true
        TOTAL_FAIL=$((TOTAL_FAIL + 1))
    fi
}

# ========== 任务 1：stock_daily + kline_cache 日线 ==========
run_task 1 "stock_daily日线增量" "
cd '$DIR'
# daily_update.sh 的主要逻辑：stock_daily 日线 baostock 增量
python3 -c \"
import sys, sqlite3, time
sys.path.insert(0, 'backend')
from pathlib import Path
import baostock as bs
DB = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))
today='$TODAY'

# 先检查 baostock 数据是否就绪
lg = bs.login()
if lg.error_code != '0':
    print('⚠ baostock 登录失败')
    exit(0)

rs = bs.query_history_k_data_plus('sh.600000', 'date,open,close', start_date=today, end_date=today, frequency='d', adjustflag='2')
ok = 0
while rs.next():
    r = rs.get_row_data()
    if r[0] and r[1] != '': ok = 1
bs.logout()

if ok != 1:
    print('⏸ baostock 今日数据未就绪，跳过 stock_daily 增量')
    exit(0)

# 数据就绪，开始增量
bs.login()
conn = sqlite3.connect(DB)
stocks = [r[0] for r in conn.execute('SELECT DISTINCT symbol FROM stock_daily').fetchall()]
conn.close()
print(f'处理 {len(stocks)} 只股票')
batch = []
total_ok = total_fail = total_data = 0
for idx, code in enumerate(stocks):
    prefix = 'sh' if code.startswith('6') or code.startswith('68') else 'sz'
    try:
        rs = bs.query_history_k_data_plus(f'{prefix}.{code}', 'date,open,high,low,close,volume,amount', start_date=today, end_date=today, frequency='d', adjustflag='2')
        while rs.next():
            r = rs.get_row_data()
            if r[0] and r[1] != '':
                batch.append({'symbol': code, 'date': r[0], 'open': float(r[1]), 'high': float(r[2]), 'low': float(r[3]), 'close': float(r[4]), 'volume': float(r[5] or 0), 'turnover': float(r[6] or 0)})
                total_data += 1
        total_ok += 1
    except:
        total_fail += 1
    if (idx+1) % 200 == 0:
        print(f'进度: {idx+1}/{len(stocks)} (OK:{total_ok} Fail:{total_fail} Data:{total_data})')
    time.sleep(0.005)

if batch:
    import pandas as pd
    df = pd.DataFrame(batch)
    conn = sqlite3.connect(DB)
    # 写入 kline_cache（source='stock_daily', period='daily'）
    rows_kc = []
    for _, r in df.iterrows():
        rows_kc.append((r['symbol'], 'stock_daily', 'daily', r['date'],
                        r['open'], r['close'], r['high'], r['low'],
                        r['volume'] or 0, r['turnover'] or 0))
    conn.executemany(
        'INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)',
        rows_kc
    )
    # 同时保留写入 stock_daily（过渡期兼容）
    conn.executemany(
        'INSERT OR REPLACE INTO stock_daily (symbol,date,open,high,low,close,volume,turnover) VALUES (?,?,?,?,?,?,?,?)',
        [(r['symbol'],r['date'],r['open'],r['high'],r['low'],r['close'],r['volume'],r['turnover']) for _, r in df.iterrows()]
    )
    conn.commit(); conn.close()
    print(f'stock_daily+kline_cache 写入: {len(batch)} 条')
print(f'完成 (OK:{total_ok} Fail:{total_fail} Data:{total_data})')
\" 2>&1

# kline_cache 日线增量
python3 backend/scripts/data_update.py --mode daily 2>&1
" 3600

# ========== 任务 2：盘口异动（pkyd → big_buy_summary + hzeveryday） ==========
run_task 2 "盘口异动 pkyd" "
cd '$DIR/backend'
# pkyd.py 会调用 hzeveryday.py 和 wsqllite.py
python3 scripts/pkyd.py 2>&1
" 600

# ========== 任务 3：大单统计（big_deal_collect） ==========
run_task 3 "大单统计 big_deal" "
cd '$DIR/backend'
python3 scripts/big_deal_collect.py 2>&1
" 7200

# ========== 任务 4：TDX 日线补全（增量更新） ==========
run_task 4 "TDX日线补全" "
cd '$DIR'
$CL_DIR/.venv/bin/python3 backend/scripts/tdx_daily_sync.py 2>&1
" 3600

# ========== 任务 5：TDX 分钟线盘后增强 ==========
# 分钟线数据通常 16:00 后才完整，15:05 跑的话先等一等
run_task 5 "TDX分钟线" "
cd '$DIR'
# 计算需要等待到 16:00 的秒数
NOW_HM=\$(date +%H%M)
if [ \"\$NOW_HM\" -lt 1600 ]; then
    WAIT_SEC=\$(( 1600 - 10#\$NOW_HM ))
    WAIT_MIN=\$(( WAIT_SEC / 60 ))
    echo \"距 16:00 还有 ~\${WAIT_MIN} 分钟，等待中...\"
    sleep \$(( WAIT_SEC > 0 ? WAIT_SEC : 0 ))
fi
$CL_DIR/.venv/bin/python3 backend/scripts/tdx_minute_sync.py --mode afterhours 2>&1
" 3600

# ========== 任务 6：重试失败（TDX 日线补漏） ==========
run_task 6 "日线补漏重试" "
cd '$DIR'
$CL_DIR/.venv/bin/python3 backend/scripts/tdx_daily_sync.py 2>&1
" 3600

# ========== 任务 7：策略选股 ==========
run_task 7 "策略选股" "
cd '$DIR/backend'
$DIR/.venv/bin/python3 scripts/strategy_sync.py 2>&1
" 600

# ========== 汇总 ==========
END_TS=$(date +%s)
TOTAL_TIME=$((END_TS - START_TS))
echo -e "\n---" | tee -a "$LOG"
echo "========== 📊 七流水线汇总  $(date) ==========" | tee -a "$LOG"
echo "  总耗时: ${TOTAL_TIME}s" | tee -a "$LOG"
echo "  成功: ${TOTAL_OK} / 7" | tee -a "$LOG"
echo "  失败: ${TOTAL_FAIL} / 7" | tee -a "$LOG"

# 12-Factor 线程结束
python3 -c "
import sys
sys.path.insert(0, '$DIR/backend')
from data.thread_manager import finish, record_error
status = 'done' if $TOTAL_FAIL -eq 0 else 'partial_failure'
finish('$THREAD_ID', status)
if $TOTAL_FAIL -gt 0:
    record_error('$THREAD_ID', 'pipeline_summary', 'partial_failure', f'7 tasks: {$TOTAL_OK} ok, {$TOTAL_FAIL} failed')
print(f'Thread {status}: {THREAD_ID}')
" 2>&1 | tee -a "$LOG" || true

# 简单数据验证
python3 -c "
import sqlite3
from pathlib import Path
DB = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))
conn = sqlite3.connect(DB)
today='$TODAY'
checks = [
    ('stock_daily', 'SELECT COUNT(*) FROM stock_daily WHERE date=?'),
    ('kline_cache(stock_daily)', "SELECT COUNT(*) FROM kline_cache WHERE source='stock_daily' AND trade_date=?"),
    ('big_buy_summary', 'SELECT COUNT(*) FROM big_buy_summary WHERE trade_date=?'),
    ('hzeveryday', 'SELECT COUNT(*) FROM hzeveryday WHERE 买入日期=?'),
    ('strategy_picks', 'SELECT COUNT(*) FROM strategy_picks WHERE date=?'),
]
for name, sql in checks:
    r = conn.execute(sql, (today,)).fetchone()
    print(f'  {name}: {r[0]} 条')
conn.close()
" 2>&1 | tee -a "$LOG"

echo "========== 日志: $LOG ==========" | tee -a "$LOG"

#!/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/.venv/bin/python3
"""
从5m数据聚合生成15m/30m/60m K线，增量写入kline_cache。
定时任务建议：15:45 每日（5m同步之后15分钟）

用法:
  python3 cron_aggregate_5m.py                # 增量聚合
  python3 cron_aggregate_5m.py --backfill      # 全量重建（慎用）
  python3 cron_aggregate_5m.py --check         # 查看状态
"""
import os, sys, time
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import sqlite3

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

# period -> 需要几根5m
TARGET_PERIODS = {"15m": 3, "30m": 6, "60m": 12}
# 允许的前缀（与5m同步一致）
KEEP_PREFIXES = ("0", "3", "6", "9", "S", "H")


def now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_conn():
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_stocks(conn):
    """获取允许前缀的5m股票列表"""
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m'"
    ).fetchall()
    return [r[0] for r in rows if r[0] and r[0][0] in KEEP_PREFIXES]


def get_max_dates(conn, symbol):
    """获取某股票各周期最大日期"""
    result = {}
    for p in TARGET_PERIODS:
        r = conn.execute(
            "SELECT MAX(trade_date) FROM kline_cache WHERE symbol=? AND period=?",
            (symbol, p)
        ).fetchone()[0]
        result[p] = r
    return result


def get_5m_since(conn, symbol, since):
    """获取5m数据（since之后的，strictly greater）"""
    if since:
        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
            "WHERE symbol=? AND period='5m' AND trade_date>? ORDER BY trade_date",
            (symbol, since)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
            "WHERE symbol=? AND period='5m' ORDER BY trade_date",
            (symbol,)
        ).fetchall()
    return rows


def aggregate(rows, n):
    """
    将5m rows聚合成n根一组的K线。
    返回 [(trade_date, open, close, high, low, volume, amount), ...]
    """
    result = []
    for i in range(0, len(rows), n):
        chunk = rows[i:i + n]
        if len(chunk) < n:
            break  # 不完整K线不写
        trade_date = chunk[-1][0]
        open_ = chunk[0][1]
        close = chunk[-1][2]
        high = max(r[3] for r in chunk)
        low = min(r[4] for r in chunk)
        volume = sum(r[5] for r in chunk)
        amount = sum(r[6] for r in chunk)
        result.append((trade_date, open_, close, high, low, volume, amount))
    return result


def process_stock(symbol):
    """处理单只股票，返回 (symbol, {period: n_inserted})"""
    conn = get_conn()
    try:
        max_dates = get_max_dates(conn, symbol)
        inserted = {}
        for period, n in TARGET_PERIODS.items():
            since = max_dates.get(period)
            rows = get_5m_since(conn, symbol, since)
            if len(rows) < n:
                inserted[period] = 0
                continue
            agg = aggregate(rows, n)
            if not agg:
                inserted[period] = 0
                continue
            data = [(symbol, "tdx", period, r[0], r[1], r[2], r[3], r[4], r[5], r[6])
                    for r in agg]
            conn.executemany(
                "INSERT OR IGNORE INTO kline_cache "
                "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                data
            )
            conn.commit()
            inserted[period] = len(data)
        return (symbol, inserted)
    except Exception as e:
        return (symbol, {"error": str(e)})
    finally:
        conn.close()


def main():
    from datetime import datetime
    action = "incremental"
    if "--backfill" in sys.argv:
        action = "backfill"
    elif "--check" in sys.argv:
        action = "check"
    t0 = time.time()
    conn = get_conn()

    if action == "check":
        print(f"[{now_s()}] 高级周期数据状态")
        rows = conn.execute(
            "SELECT period, COUNT(*), COUNT(DISTINCT symbol), MAX(trade_date) "
            "FROM kline_cache WHERE period IN ('15m','30m','60m') "
            "GROUP BY period ORDER BY period"
        ).fetchall()
        for r in rows:
            print(f"  {r[0]}: {r[1]}行, {r[2]}只, 最新{r[3]}")
        conn.close()
        return

    stocks = get_stocks(conn)
    conn.close()
    print(f"[{now_s()}] 开始{action}聚合: {len(stocks)}只股票", flush=True)

    # 多线程处理
    n_workers = 4
    total_inserted = {p: 0 for p in TARGET_PERIODS}
    done = 0
    errors = []

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {pool.submit(process_stock, s): s for s in stocks}
        for fut in as_completed(futs):
            done += 1
            symbol, result = fut.result()
            if "error" in result:
                errors.append((symbol, result["error"]))
            else:
                for p, n in result.items():
                    total_inserted[p] += n
            if done % 500 == 0:
                el = time.time() - t0
                rate = done / el if el > 0 else 0
                eta = (len(stocks) - done) / rate if rate > 0 else 0
                ins_str = " ".join(f"{p}+{total_inserted[p]}" for p in TARGET_PERIODS)
                print(f"  [{done}/{len(stocks)}] {ins_str} {el:.0f}s ETA:{eta:.0f}s", flush=True)

    el = time.time() - t0
    ins_str = " ".join(f"{p}:+{total_inserted[p]}行" for p in TARGET_PERIODS)
    print(f"[{now_s()}] 完成! {el:.0f}s {ins_str}", flush=True)
    if errors:
        print(f"  失败{len(errors)}只, 示例: {errors[:5]}", flush=True)


if __name__ == "__main__":
    main()

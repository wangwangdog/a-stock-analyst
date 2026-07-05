#!/usr/bin/env python3
"""
日线增量补齐 + 报告
- 查找 stock_daily 中缺失的交易日
- 用 AKShare 拉取补齐
- 输出报告（回传给用户）
"""
import sys, sqlite3, time, os, json
from pathlib import Path
from datetime import datetime, date
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = "/home/dogzi/.openclaw/workspace/a-stock-analyst/chanlun-pro/db/chanlun_klines.sqlite"
MAX_WORKERS = 6  # akshare 并发数
BATCH_SIZE = 200  # 每批次写入行数

REPORT = {"start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_all_symbols():
    conn = get_conn()
    symbols = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol"
    ).fetchall()]
    conn.close()
    return symbols


def get_missing_dates(symbols):
    """找出缺失或不完整的交易日"""
    today_str = date.today().strftime("%Y-%m-%d")
    total_stocks = len(symbols)
    conn = get_conn()

    # 收集最近 90 天每个交易日的数据完整度
    cursor = conn.cursor()
    cursor.execute(
        "SELECT calendar_date FROM trade_calendar "
        "WHERE is_trading_day=1 AND calendar_date <= ? "
        "ORDER BY calendar_date DESC LIMIT 90",
        (today_str,)
    )
    recent_trading_days = [r[0] for r in cursor.fetchall()]

    if not recent_trading_days:
        conn.close()
        return []

    placeholders = ",".join("?" for _ in recent_trading_days)
    cursor.execute(
        f"SELECT date, COUNT(DISTINCT symbol) AS cnt FROM stock_daily "
        f"WHERE date IN ({placeholders}) GROUP BY date",
        recent_trading_days
    )
    coverage = {r[0]: r[1] for r in cursor.fetchall()}
    conn.close()

    # 标记完整度低于 80% 的日期为"缺失"
    missing = []
    threshold = max(4000, int(total_stocks * 0.8))
    for d in recent_trading_days:
        cnt = coverage.get(d, 0)
        if cnt < threshold:
            missing.append(d)

    # 按时间升序
    missing.sort()
    return missing


def get_stocks_with_data_for_dates(dates):
    """返回在指定日期已有全部数据的股票集合，用于断点续传跳过"""
    if not dates:
        return set()
    conn = get_conn()
    placeholders = ",".join("?" for _ in dates)
    # 某只股票在 missing_dates 中有数据的日期数
    rows = conn.execute(
        f"SELECT symbol, COUNT(DISTINCT date) AS cnt FROM stock_daily "
        f"WHERE date IN ({placeholders}) GROUP BY symbol",
        dates
    ).fetchall()
    conn.close()
    target = len(dates)
    return {r[0] for r in rows if r[1] >= target}


def fetch_stock_range(symbol):
    """拉取单只股票在缺失日期范围内的日线"""
    import akshare as ak
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=START_DATE,
            end_date=END_DATE,
            adjust="qfq",
            timeout=25
        )
        if df is not None and not df.empty:
            rows = []
            for _, r in df.iterrows():
                d = str(r["日期"])
                if d[:4] not in ("2024", "2025", "2026"):
                    continue
                # stock_zh_a_hist 返回日期格式 YYYY-MM-DD
                if d in MISSING_SET:
                    rows.append((
                        symbol, d,
                        float(r["开盘"]), float(r["最高"]), float(r["最低"]), float(r["收盘"]),
                        float(r["成交量"]), float(r["成交额"])
                    ))
            return rows
    except Exception:
        pass
    return []


def write_batch(conn, rows):
    conn.executemany(
        "INSERT OR REPLACE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) "
        "VALUES (?,?,?,?,?,?,?,?)",
        rows
    )
    conn.commit()


def generate_report(status, stats):
    REPORT["status"] = status
    REPORT["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    REPORT["stats"] = stats

    lines = []
    lines.append("=" * 50)
    lines.append("📊 日线数据补齐报告")
    lines.append("=" * 50)
    lines.append(f"运行时间: {REPORT['start_time']} → {REPORT['end_time']}")
    lines.append(f"状态: {status}")
    lines.append("")

    st = stats
    lines.append(f"补齐交易日: {st.get('target_days', 0)} 天")
    if st.get('missing_dates'):
        lines.append(f"缺失日期: {', '.join(st['missing_dates'][:10])}{'...' if len(st['missing_dates']) > 10 else ''}")
    lines.append(f"总股票数: {st.get('total_stocks', '?')} 只")
    lines.append(f"成功行数: {st.get('success_rows', 0)}")
    lines.append(f"失败股票: {st.get('failed_stocks', 0)} 只")
    if st.get('success_rate'):
        lines.append(f"成功率: {st['success_rate']}")
    lines.append("")

    lines.append("📈 数据库概览:")
    lines.append(f"  stock_daily 总行数: {st.get('total_rows', '?'):,}")
    lines.append(f"  总股票数: {st.get('unique_symbols', '?'):,}")
    lines.append(f"  最新日期: {st.get('latest_date', '?')}")
    lines.append(f"  最早日期: {st.get('earliest_date', '?')}")
    lines.append("")

    if st.get('day_counts'):
        lines.append("📅 各日数据量:")
        for d, cnt in st['day_counts']:
            lines.append(f"  {d}: {cnt:,} 只股票")

    lines.append("=" * 50)
    return "\n".join(lines)


def run_backfill(missing_dates):
    """补齐缺失日期"""
    import akshare as ak

    global START_DATE, END_DATE, MISSING_SET
    START_DATE = missing_dates[0].replace("-", "")
    END_DATE = missing_dates[-1].replace("-", "")
    MISSING_SET = set(missing_dates)

    symbols = get_all_symbols()
    total = len(symbols)
    print(f"股票总数: {total:,}")
    print(f"缺失交易日: {len(missing_dates)} 天 ({missing_dates[0]} ~ {missing_dates[-1]})")
    print(f"查询范围: {START_DATE} ~ {END_DATE}")
    print(f"并发: {MAX_WORKERS} workers")
    print()

    # 断点续传：跳过已有数据的股票
    stocks_with_data = get_stocks_with_data_for_dates(missing_dates)
    pending = [s for s in symbols if s not in stocks_with_data]
    skip_count = len(stocks_with_data)
    pending_count = len(pending)
    print(f"已完整: {skip_count} 只 (跳过)")
    print(f"待补齐: {pending_count} 只")
    print()

    if not pending:
        print("✅ 所有股票已有缺失日期的数据，无需补齐")
        return get_final_stats()

    success_rows = 0
    failed_stocks = 0
    batch_buffer = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for i, sym in enumerate(pending):
            futures[pool.submit(fetch_stock_range, sym)] = sym
            if (i + 1) % 200 == 0:
                print(f"  已提交 {i+1}/{total}...")

        conn = get_conn()
        for idx, future in enumerate(as_completed(futures)):
            sym = futures[future]
            rows = future.result()
            if rows:
                success_rows += len(rows)
                batch_buffer.extend(rows)
            else:
                failed_stocks += 1

            # 批量写入
            if len(batch_buffer) >= BATCH_SIZE:
                write_batch(conn, batch_buffer)
                batch_buffer = []
                elapsed = time.time() - t0
                pct = (idx + 1) / pending_count * 100
                rate = success_rows / (success_rows + failed_stocks) * 100 if (success_rows + failed_stocks) > 0 else 0
                print(f"  [{idx+1}/{pending_count}] {pct:.0f}% | 成功{success_rows}行 | 失败{failed_stocks}只 | {rate:.0f}% | {elapsed:.0f}s")

        if batch_buffer:
            write_batch(conn, batch_buffer)

        conn.close()

    elapsed = time.time() - t0
    print(f"\n✅ 补齐完成! 耗时 {elapsed:.0f}s")

    final_stats = get_final_stats(missing_dates)
    final_stats.update({
        "target_days": len(missing_dates),
        "missing_dates": missing_dates,
        "total_stocks": len(symbols),
        "success_rows": success_rows,
        "failed_stocks": failed_stocks,
        "success_rate": f"{success_rows/(success_rows+failed_stocks)*100:.1f}%" if (success_rows + failed_stocks) > 0 else "N/A",
        "pending_count": pending_count,
        "elapsed_seconds": elapsed,
    })
    return final_stats


def get_final_stats(missing_dates=None):
    """查询最终统计"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM stock_daily")
    total_rows = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily")
    uniq_syms = cursor.fetchone()[0]
    cursor.execute("SELECT MIN(date), MAX(date) FROM stock_daily")
    earliest, latest = cursor.fetchone()

    day_counts = []
    if missing_dates:
        for d in missing_dates:
            cursor.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily WHERE date=?", (d,))
            cnt = cursor.fetchone()[0]
            if cnt > 0:
                day_counts.append((d, cnt))

    conn.close()

    stats = {
        "total_rows": total_rows,
        "unique_symbols": uniq_syms,
        "earliest_date": earliest,
        "latest_date": latest,
        "day_counts": day_counts,
    }
    return stats


def main():
    t0 = time.time()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 日线增量补齐开始")

    symbols = get_all_symbols()
    if not symbols:
        print("❌ stock_daily 为空，无法补齐")
        stats = get_final_stats()
        stats.update({"target_days": 0, "missing_dates": [], "total_stocks": 0, "success_rows": 0, "failed_stocks": 0, "success_rate": "N/A"})
        report = generate_report("ERROR (空库)", stats)
        print(report)
        return report

    missing_dates = get_missing_dates(symbols)
    if not missing_dates:
        print("✅ 数据已完整，无需补齐")
        stats = get_final_stats()
        stats.update({"target_days": 0, "missing_dates": [], "total_stocks": len(symbols), "success_rows": 0, "failed_stocks": 0, "success_rate": "100%"})
        report = generate_report("OK (无需补齐)", stats)
        print(report)
        return report

    print(f"📅 缺失 {len(missing_dates)} 个交易日:")
    for d in missing_dates:
        print(f"   {d}")
    print()

    stats = run_backfill(missing_dates)
    report = generate_report("OK (已补齐)", stats)
    print(report)
    return report


if __name__ == "__main__":
    report = main()
    # 保存报告到文件供 cron 取用
    out_dir = Path(__file__).resolve().parent / ".." / ".." / "data"
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "sync_report_latest.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\n📝 报告已保存: {report_path}")

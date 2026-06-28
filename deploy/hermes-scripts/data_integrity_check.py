#!/usr/bin/env python3
"""每日18:00数据完整性检查（仅报告，不做补齐——补齐由定时任务负责）"""
import sqlite3
from datetime import datetime

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
report = []

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    report.append(msg)

def check_and_report():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")

    # 1. 最新交易日
    cur = conn.execute("SELECT MAX(trade_date) FROM kline_cache WHERE source='stock_daily' AND period='daily'")
    latest = cur.fetchone()[0]
    if not latest:
        log("❌ kline_cache(stock_daily) 无数据")
        conn.close()
        return
    log(f"📅 最新交易日: {latest}")

    # 2. stock_daily 覆盖
    cur = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE source='stock_daily' AND period='daily' WHERE date=?", (latest,))
    daily_cnt = cur.fetchone()[0]
    log(f"  kline_cache(stock_daily): {daily_cnt}只")

    # 3. kline_cache 各周期覆盖
    coverage = {}
    for p in ["5m", "15m", "60m", "daily"]:
        cur = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period=? AND trade_date LIKE ?||'%'",
            (p, latest)
        )
        cnt = cur.fetchone()[0]
        pct = cnt / daily_cnt * 100 if daily_cnt > 0 else 0
        status = "✅" if pct >= 99 else ("⚠️" if pct >= 50 else "❌")
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        log(f"  {status} {p:6s}: {cnt:>5}/{daily_cnt} ({pct:5.1f}%) {bar}")
        coverage[p] = {"count": cnt, "pct": pct}

    # 4. SH.000001
    cur = conn.execute(
        "SELECT trade_date, close FROM kline_cache WHERE symbol='SH.000001' AND period='daily' ORDER BY trade_date DESC LIMIT 1"
    )
    r = cur.fetchone()
    if r:
        log(f"  SH.000001: {r[0][:10]} close={r[1]:.3f}")
    else:
        log("  SH.000001: 无数据 ❌")

    conn.close()

    # 总体判定
    ok = all(v["pct"] >= 99 for v in coverage.values())
    if ok:
        log("\n✅ 全部正常")
    else:
        warnings = [f"{k}只有{v['pct']:.1f}%" for k, v in coverage.items() if v["pct"] < 99]
        log(f"\n⚠️ 需关注: {', '.join(warnings)}")

if __name__ == "__main__":
    check_and_report()
    print("\n--- 报告 ---")
    for line in report:
        print(line)

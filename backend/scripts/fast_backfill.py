#!/usr/bin/env python3
"""
快速全市场历史回填 - 使用 AKShare + 多线程

AKShare 实测 7 只股票 0.68s (~10只/秒)，
5200 只预计 8-10 分钟完成。

用法：
    python scripts/fast_backfill.py
"""

import sys
import time
import sqlite3
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
DB_PATH = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")
START_DATE = "20240101"  # AKShare 格式：YYYYMMDD


def get_all_akshare_symbols() -> list[str]:
    """通过 AKShare 获取全市场 A 股代码"""
    import akshare as ak
    df = ak.stock_info_a_code_name()
    symbols = []
    for _, row in df.iterrows():
        code = str(row.get("code", ""))
        if code:
            symbols.append(code)
    return symbols


def fetch_one(symbol: str) -> tuple:
    """
    拉取单只股票的全量日线数据。
    返回 (symbol, [(date, open, high, low, close, volume, turnover), ...])
    失败返回 (symbol, None, error_msg)
    """
    import akshare as ak
    try:
        today = date.today().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=START_DATE, end_date=today,
            adjust="qfq",
        )
        if df is None or df.empty:
            return (symbol, None, "empty")

        rows = []
        for _, r in df.iterrows():
            rows.append((
                str(r["日期"]),
                float(r["开盘"]),
                float(r["最高"]),
                float(r["最低"]),
                float(r["收盘"]),
                float(r["成交量"]),
                float(r["成交额"]) if "成交额" in r else 0.0,
            ))
        return (symbol, rows, None)
    except Exception as e:
        return (symbol, None, str(e))


def main():
    print("🚀 快速全市场历史回填（AKShare + 多线程）")
    print(f"   数据库: {DB_PATH}")
    print(f"   起始日: {START_DATE}")
    print()

    # 确保 stock_daily 表存在
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol   TEXT    NOT NULL,
            date     TEXT    NOT NULL,
            open     REAL,
            high     REAL,
            low      REAL,
            close    REAL,
            volume   REAL,
            turnover REAL,
            UNIQUE (symbol, date)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_symbol_date ON stock_daily (symbol, date)
    """)
    conn.commit()
    conn.close()

    # 获取全市场股票列表
    print("📡 获取 A 股列表...")
    all_symbols = get_all_akshare_symbols()
    print(f"✅ 共 {len(all_symbols)} 只 A 股")

    # 过滤已有数据
    conn = sqlite3.connect(DB_PATH)
    existing = set(r[0] for r in conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall())
    conn.close()
    print(f"   已有: {len(existing)} 只")
    print()

    symbols_to_fetch = [s for s in all_symbols if s not in existing]
    if not symbols_to_fetch:
        # 但可能还有 Baostock 后复权的旧数据，需要清理
        print("✅ 全部股票已有数据")
        print("   清理 Baostock 旧数据（替换为 AKShare 前复权）...")
        symbols_to_fetch = all_symbols  # 全部重拉
        # 先清空
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM stock_daily")
        conn.commit()
        conn.close()
        print(f"   已清空，准备重新拉取 {len(symbols_to_fetch)} 只")
    else:
        print(f"   待拉取: {len(symbols_to_fetch)} 只")

    N_THREADS = 8
    print(f"\n📦 启动 {N_THREADS} 线程并行拉取...")
    print()

    start_time = time.time()
    total_rows = 0
    success_count = 0
    fail_count = 0

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA synchronous=OFF")  # 加速写入
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        with ThreadPoolExecutor(max_workers=N_THREADS) as executor:
            futs = {executor.submit(fetch_one, sym): sym for sym in symbols_to_fetch}

            for i, f in enumerate(as_completed(futs)):
                symbol = futs[f]
                try:
                    sym, rows, error = f.result()
                    if error:
                        fail_count += 1
                        if fail_count <= 3:
                            print(f"  ⚠ [{symbol}] 失败: {error}")
                        continue

                    if not rows:
                        continue

                    # 批量写入
                    conn.executemany(
                        "INSERT OR IGNORE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?,?,?,?,?,?,?,?)",
                        [(symbol, r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]
                    )

                    total_rows += len(rows)
                    success_count += 1

                    # 每 100 只打印进度
                    if (i + 1) % 100 == 0:
                        elapsed = time.time() - start_time
                        rate = (i + 1) / elapsed if elapsed > 0 else 0
                        conn.commit()  # 定期提交
                        print(f"  [{i+1}/{len(symbols_to_fetch)}] 成功 {success_count} 失败 {fail_count} | {rate:.0f}只/秒 | {total_rows} 条")

                except Exception as e:
                    fail_count += 1
                    if fail_count <= 3:
                        print(f"  ⚠ [{symbol}] 异常: {e}")

            conn.commit()  # 最终提交

    finally:
        conn.close()

    elapsed = time.time() - start_time

    # 最终统计
    conn = sqlite3.connect(DB_PATH)
    final_stocks = conn.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()[0]
    final_rows = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
    final_dates = conn.execute("SELECT COUNT(DISTINCT date) FROM stock_daily").fetchone()[0]
    latest_date = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()[0]
    conn.close()

    print()
    print("✅ 回填完成!")
    print(f"   耗时: {elapsed/60:.1f} 分钟")
    print(f"   成功: {success_count} 只 | 失败: {fail_count} 只")
    print(f"   写入: {total_rows} 条")
    print(f"   总计: {final_stocks} 只股票, {final_rows} 条记录, {final_dates} 个交易日")
    print(f"   最新日: {latest_date}")
    print()
    print("现在可以运行日常同步: python scripts/daily_sync.py")


if __name__ == "__main__":
    main()

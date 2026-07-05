#!/usr/bin/env python3
"""
强制补全 stock_daily 日线数据（独立进程，避免 baostock 连接冲突）。
补充缺失交易日期的数据到 stock_daily 表。
"""
import sys
import socket
import time
from pathlib import Path
from datetime import date, timedelta

socket.setdefaulttimeout(20)

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import baostock as bs
import pandas as pd
import sqlite3

DB_PATH = Path("/home/dogzi/sqlite-data/chanlun_klines.sqlite")

BATCH_SIZE = 300   # 每批 300 只
INTER_BATCH = 5    # 批间休息 5秒


def get_stocks(conn):
    """获取所有股票代码（去重）"""
    rows = conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()
    return [r[0] for r in rows]


def get_missing_dates(conn):
    """确定需要补充的交易日"""
    today = date.today()
    last_row = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    last_date = date.fromisoformat(last_row[0]) if last_row[0] else today - timedelta(days=60)

    # 从最后日期之后到昨天的所有工作日
    missing = []
    d = last_date + timedelta(days=1)
    while d < today:
        if d.weekday() < 5:  # 周一到周五
            missing.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return missing, last_date


def main():
    conn = sqlite3.connect(str(DB_PATH))
    stocks = get_stocks(conn)
    missing_dates, last_date = get_missing_dates(conn)
    conn.close()

    print(f"股票总数: {len(stocks)}")
    print(f"本地最新日: {last_date}")
    print(f"需要补充: {len(missing_dates)} 个交易日")
    if not missing_dates:
        print("✅ 数据已是最新")
        return

    total = len(stocks)
    updated = 0
    failed = 0
    logged_in = False

    def ensure_login():
        nonlocal logged_in
        try:
            bs.logout()
        except:
            pass
        lg = bs.login()
        if lg.error_code == "0":
            logged_in = True
            return True
        logged_in = False
        return False

    if not ensure_login():
        print("❌ Baostock 首次登录失败")
        return
    print("✅ Baostock 登录成功")

    for i in range(0, total, BATCH_SIZE):
        chunk = stocks[i:i+BATCH_SIZE]
        batch_rows = []

        # 每批重新登录，避免 session 过期
        if i > 0:
            ensure_login()
            time.sleep(1)

        for idx, symbol in enumerate(chunk):
            bs_code = f"sh.{symbol}" if symbol.startswith(("6", "688")) else f"sz.{symbol}"
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume,amount",
                    start_date=missing_dates[0],
                    end_date=missing_dates[-1],
                    frequency="d", adjustflag="2",
                )
                if rs.error_code != "0":
                    failed += 1
                    continue

                has_data = False
                while rs.next():
                    row = rs.get_row_data()
                    if row[1] == "":
                        continue
                    date_val = row[0]
                    close = float(row[4] or 0)
                    if close > 0:
                        batch_rows.append([
                            symbol, date_val,
                            float(row[1] or 0), float(row[2] or 0),
                            float(row[3] or 0), close,
                            float(row[5] or 0), float(row[6] or 0),
                        ])
                        has_data = True

                if has_data:
                    updated += 1
            except Exception as e:
                failed += 1

            if (idx + 1) % 100 == 0:
                print(f"  [{i+idx+1}/{total}] {symbol} ... updated={updated} failed={failed}")

        # 写批次
        if batch_rows:
            df = pd.DataFrame(batch_rows, columns=[
                "symbol", "date", "open", "high", "low", "close", "volume", "turnover"
            ])
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            df = df[df["volume"] > 0]

            c = sqlite3.connect(str(DB_PATH))
            for d in df["date"].unique():
                c.execute("DELETE FROM stock_daily WHERE date = ?", (d,))
            df.to_sql("stock_daily", c, if_exists="append", index=False, method="multi")
            c.commit()
            c.close()
            print(f"  💾 写入批次 {i//BATCH_SIZE + 1}: {len(df)} 行")

        # 批间休息
        if i + BATCH_SIZE < total:
            print(f"  😴 休息 {INTER_BATCH}s ...")
            time.sleep(INTER_BATCH)

    bs.logout()
    print(f"\n✅ 完成！更新: {updated}, 失败: {failed}")

    # 验证
    c = sqlite3.connect(str(DB_PATH))
    latest = c.execute("SELECT MAX(date) FROM stock_daily").fetchone()
    rows = c.execute("SELECT date, COUNT(*) FROM stock_daily GROUP BY date ORDER BY date DESC LIMIT 5").fetchall()
    c.close()
    print(f"最新日期: {latest[0]}")
    for d, cnt in rows:
        print(f"  {d}: {cnt} 只股票")


if __name__ == "__main__":
    main()

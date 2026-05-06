#!/usr/bin/env python3
"""
从 stock_records 表汇总大单数据到 hzeveryday 表，并清理已处理记录。
"""

import sys
import sqlite3
from pathlib import Path
from datetime import date


def _is_trading_day() -> bool:
    """通过 baostock 判断今天是不是交易日，非交易日直接退出。"""
    try:
        import baostock as bs
        today = date.today().strftime("%Y-%m-%d")
        lg = bs.login()
        if lg.error_code != "0":
            print(f"⚠ baostock 登录失败，默认按交易日处理: {lg.error_msg}")
            return True
        try:
            rs = bs.query_trade_dates(start_date=today, end_date=today)
            while rs.next():
                row = rs.get_row_data()
                if row[0] == today:
                    return row[1] == "1"
            return False
        finally:
            bs.logout()
    except ImportError:
        print("⚠ baostock 未安装，跳过交易日判断")
        return True


SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = str(SCRIPT_DIR.parent.parent / "backend" / "data" / "stock_cache.db")


def migrate_and_cleanup():
    """
    从 stock_records 表按日期和股票代码汇总数据到 hzeveryday 表，
    并删除已处理的原始记录。
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN TRANSACTION;")

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS hzeveryday (
            股票代码 TEXT,
            股票名称 TEXT,
            大笔买数 INTEGER,
            合计金额 REAL,
            合计手数 REAL,
            买入日期 TEXT
        )
        """)

        cursor.execute("SELECT DISTINCT 买入日期, 股票代码 FROM stock_records;")
        groups = cursor.fetchall()

        if not groups:
            print("stock_records 表中没有数据，无需处理。")
            conn.commit()
            return

        print(f"找到 {len(groups)} 个待处理的日期+股票代码组合。")

        # 先清除当天的旧数据，避免定时任务重复执行导致重复
        today_str = date.today().strftime("%Y-%m-%d")
        cursor.execute("DELETE FROM hzeveryday WHERE 买入日期=?", (today_str,))
        deleted = cursor.rowcount
        if deleted > 0:
            print(f"🧹 已清除当日旧数据: {deleted} 行\n")

        for buy_date, stock_code in groups:
            raw_code = stock_code.strip()
            padded_code = raw_code.zfill(6)

            if padded_code.startswith('9'):
                print(f"跳过9开头股票：日期 {buy_date}，代码 {padded_code}")
                cursor.execute("""
                DELETE FROM stock_records
                WHERE 买入日期 = ? AND 股票代码 = ?
                """, (buy_date, stock_code))
                continue

            cursor.execute("""
            SELECT
                SUM(买入数量) AS 合计手数,
                SUM(金额) AS 合计金额,
                COUNT(*) AS 大笔买数,
                MIN(股票名称) AS 股票_name
            FROM stock_records
            WHERE 买入日期 = ? AND 股票代码 = ?
            """, (buy_date, stock_code))
            row = cursor.fetchone()
            if row is None or row[0] is None:
                continue

            sum_shou, sum_amount, big_count, stock_name = row

            cursor.execute("""
            INSERT INTO hzeveryday (股票代码, 股票名称, 大笔买数, 合计金额, 合计手数, 买入日期)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (padded_code, stock_name, big_count, sum_amount, sum_shou, buy_date))

            cursor.execute("""
            DELETE FROM stock_records
            WHERE 买入日期 = ? AND 股票代码 = ?
            """, (buy_date, stock_code))

            print(f"已处理：日期 {buy_date}，股票代码 {padded_code}，共 {big_count} 条记录，"
                  f"合计手数 {sum_shou}，合计金额 {sum_amount}")

        conn.commit()
        print("所有数据处理完成并已提交。")

    except Exception as e:
        conn.rollback()
        print(f"处理过程中出现错误，已回滚事务：{e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    # ── 交易日判断 ──
    if not _is_trading_day():
        print(f"📅 {date.today()} 非交易日，跳过 hzeveryday 汇总")
        sys.exit(0)
    migrate_and_cleanup()

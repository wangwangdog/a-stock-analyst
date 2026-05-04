import sqlite3
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = str(SCRIPT_DIR.parent.parent / "backend" / "data" / "stock_cache.db")  # 统一使用 stock_cache.db


def migrate_and_cleanup():
    """
    从 stock_records 表按日期和股票代码汇总数据到 hzeveryday 表，
    并删除已处理的原始记录。
    """
    db_path = DB_PATH
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("BEGIN TRANSACTION;")

        # 1. 创建目标表 hzeveryday（如果不存在）
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

        # 2. 查询所有需要汇总的 (买入日期, 股票代码) 组合
        cursor.execute("SELECT DISTINCT 买入日期, 股票代码 FROM stock_records;")
        groups = cursor.fetchall()

        if not groups:
            print("stock_records 表中没有数据，无需处理。")
            conn.commit()
            return

        print(f"找到 {len(groups)} 个待处理的日期+股票代码组合。")

        # 3. 逐组处理：汇总 -> 插入 -> 删除
        for buy_date, stock_code in groups:
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
                print(f"警告：日期 {buy_date} 代码 {stock_code} 无有效数据，跳过")
                continue

            sum_shou, sum_amount, big_count, stock_name = row

            cursor.execute("""
            INSERT INTO hzeveryday (股票代码, 股票名称, 大笔买数, 合计金额, 合计手数, 买入日期)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (stock_code, stock_name, big_count, sum_amount, sum_shou, buy_date))

            cursor.execute("""
            DELETE FROM stock_records
            WHERE 买入日期 = ? AND 股票代码 = ?
            """, (buy_date, stock_code))

            print(f"已处理：日期 {buy_date}，股票代码 {stock_code}，共 {big_count} 条记录，"
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
    migrate_and_cleanup()

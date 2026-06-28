#!/usr/bin/env python3
"""
将 Excel 中的盘口异动数据写入 stock_records 表。
"""
import os
import re
import sys
import sqlite3
import pandas as pd
from pathlib import Path
from datetime import date

# ── 交易日判断（被 pkyd.py 或定时任务调度时生效）──
def _is_trading_day() -> bool:
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

if not _is_trading_day():
    print(f"📅 {date.today()} 非交易日，跳过 wsqllite 入库")
    sys.exit(0)

# ==================== 配置 ====================
SCRIPT_DIR = Path(__file__).resolve().parent
EXCEL_DIR = str(SCRIPT_DIR / "excel_files")  # Excel 文件目录
DB_PATH = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))  # chanlun-pro 统一数据库
TABLE_NAME = "stock_records"

# 文件名中日期提取的正则表达式
DATE_PATTERN = r"(\d{4}[-_]?\d{2}[-_]?\d{2})"


def create_table(conn):
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        股票代码 TEXT,
        股票名称 TEXT,
        买入数量 REAL,
        单价 REAL,
        涨跌幅 REAL,
        金额 REAL,
        买入时间 TEXT,
        买入日期 TEXT
    );
    """
    conn.execute(create_sql)
    conn.commit()
    print(f"表 '{TABLE_NAME}' 已准备就绪")


def extract_date_from_filename(filename: str) -> str:
    match = re.search(DATE_PATTERN, filename)
    if not match:
        return None

    date_str = match.group(1)
    for sep in ['_', '-']:
        if sep in date_str:
            date_str = date_str.replace(sep, '-')
            break

    if len(date_str) == 8 and date_str.isdigit():
        date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    try:
        pd.to_datetime(date_str)
        return date_str
    except:
        return None


def process_excel_file(file_path: str, buy_date: str) -> pd.DataFrame:
    df = pd.read_excel(file_path)
    required_cols = ['股票代码', '股票名称', '买入数量', '单价', '涨跌幅', '买入时间']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"缺少必需列：{missing_cols}")

    df['金额'] = df['单价'] * df['买入数量']
    df['买入日期'] = buy_date
    result_df = df[['股票代码', '股票名称', '买入数量', '单价', '涨跌幅', '金额', '买入时间', '买入日期']]
    return result_df


def main():
    os.makedirs(EXCEL_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    create_table(conn)

    exts = ('.xlsx', '.xls')
    excel_files = [f for f in os.listdir(EXCEL_DIR) if f.lower().endswith(exts)]
    if not excel_files:
        print(f"目录 '{EXCEL_DIR}' 中没有找到 Excel 文件。")
        conn.close()
        return

    total_rows = 0
    for filename in excel_files:
        file_path = os.path.join(EXCEL_DIR, filename)
        print(f"正在处理: {filename}")

        buy_date = extract_date_from_filename(filename)
        if buy_date is None:
            print(f"  警告：无法从文件名提取合法日期，跳过文件 '{filename}'")
            continue

        try:
            df = process_excel_file(file_path, buy_date)
            # 删除该日期旧数据，避免重复
            c = conn.cursor()
            c.execute(f"DELETE FROM {TABLE_NAME} WHERE 买入日期=?", (buy_date,))
            if c.rowcount > 0:
                print(f"  🧹 已删除 {c.rowcount} 条旧数据（买入日期: {buy_date}）")
            df.to_sql(TABLE_NAME, conn, if_exists='append', index=False)
            rows = len(df)
            total_rows += rows
            print(f"  成功写入 {rows} 行数据（买入日期: {buy_date}）")
        except Exception as e:
            print(f"  处理失败：{e}")
            continue

    conn.close()
    print(f"\n全部完成！共写入 {total_rows} 行数据到数据库文件: {DB_PATH}")


if __name__ == "__main__":
    main()

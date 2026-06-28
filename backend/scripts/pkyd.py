#!/usr/bin/env python3
"""
盘口异动数据获取与解析

从 AKShare 获取当日盘口异动分类数据，解析后生成 Excel 文件，
并自动调用 wsqllite.py 写入 stock_records 表、调用 hzeveryday.py 汇总到 hzeveryday 表。
"""

import akshare as ak
import pandas as pd
import os
import re
import sys
import shutil
import subprocess
from datetime import datetime


def _is_trading_day() -> bool:
    """通过 baostock 判断今天是不是交易日，非交易日直接退出。"""
    try:
        import baostock as bs
        from datetime import date
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


def main():
    # ── 交易日判断（定时任务入口）──
    if not _is_trading_day():
        from datetime import date
        print(f"📅 {date.today()} 非交易日，跳过盘口异动数据获取")
        sys.exit(0)

    # ---------- 1. 所有异动分类 ----------
    symbols = [
        '火箭发射', '快速反弹', '大笔买入', '封涨停板',
        '有大买盘', '竞价上涨', '高开5日线', '向上缺口', '60日新高',
        '60日大幅上涨', '加速下跌', '高台跳水', '大笔卖出', '封跌停板',
        '有大卖盘', '竞价下跌', '低开5日线', '向下缺口',
        '60日新低', '60日大幅下跌'
    ]

    # ---------- 2. 输出文件夹 ----------
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(SCRIPT_DIR, '盘口异动_分类解析')
    excel_dir = os.path.join(SCRIPT_DIR, 'excel_files')
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(excel_dir, exist_ok=True)
    date_tag = datetime.now().strftime('%Y%m%d')

    print(f"输出目录: {output_dir}")
    print(f"共 {len(symbols)} 个分类\n")

    # ---------- 3. 逐类获取并解析 ----------
    for sym in symbols:
        print(f'处理: {sym} ...', end=' ')
        try:
            df = ak.stock_changes_em(symbol=sym)
        except Exception as e:
            print(f'请求失败 ({e})')
            continue

        if df is None or df.empty:
            print('无数据')
            continue

        if '相关信息' not in df.columns or '时间' not in df.columns:
            print('缺少必要列，跳过')
            continue

        # 解析每一行的"相关信息"
        parsed_rows = []
        for _, row in df.iterrows():
            info = str(row['相关信息']).strip()
            if not info or info == 'nan':
                continue

            parts = [p.strip() for p in info.split(',')]
            if len(parts) < 3:
                continue

            def extract_num(s):
                return float(re.sub(r'[^\d.\-]', '', s))

            try:
                qty = extract_num(parts[0])
                price = extract_num(parts[1])
                change = extract_num(parts[2])
            except ValueError:
                continue

            amount = qty * price

            parsed_rows.append({
                '股票代码': row.get('代码', ''),
                '股票名称': row.get('名称', ''),
                '买入数量': qty,
                '单价': price,
                '涨跌幅': change,
                '金额(单价*数量)': amount,
                '买入时间': row['时间']
            })

        # 保存该类别的解析结果
        if parsed_rows:
            result_df = pd.DataFrame(parsed_rows).sort_values('买入时间')
            safe_name = sym.replace('/', '_')
            filename = f'盘口异动解析_{date_tag}_{safe_name}.xlsx'
            filepath = os.path.join(output_dir, filename)
            result_df.to_excel(filepath, index=False, engine='openpyxl')
            print(f'已生成 {len(parsed_rows)} 条明细')
        else:
            print('无有效解析数据')

    print(f'\n✅ 完成！所有解析文件保存在：{output_dir}')

    # ---------- 4. 复制"大笔买入"文件到 excel_files 并入库 ----------
    print('\n--- 筛选大笔买入文件 ---')
    buy_files = [f for f in os.listdir(output_dir)
                 if f.endswith('.xlsx') and '大笔买入' in f and date_tag in f]

    for f in buy_files:
        src = os.path.join(output_dir, f)
        dst = os.path.join(excel_dir, f)
        shutil.copy2(src, dst)
        print(f'复制: {f}')

    if buy_files:
        print(f'\n--- 调用 wsqllite.py 写入数据库 ---')
        wsqllite_path = os.path.join(SCRIPT_DIR, 'wsqllite.py')
        result = subprocess.run(['python3', wsqllite_path], capture_output=True, text=True, cwd=SCRIPT_DIR)
        print(result.stdout)
        if result.returncode != 0:
            print(f'wsqllite.py 错误: {result.stderr}')
        else:
            print('wsqllite.py 执行成功 ✅')

        print(f'\n--- 调用 hzeveryday.py 汇总数据 ---')
        hz_path = os.path.join(SCRIPT_DIR, 'hzeveryday.py')
        result2 = subprocess.run(['python3', hz_path], capture_output=True, text=True, cwd=SCRIPT_DIR)
        print(result2.stdout)
        if result2.returncode != 0:
            print(f'hzeveryday.py 错误: {result2.stderr}')
        else:
            print('hzeveryday.py 执行成功 ✅')

        # 将 excel_files 中的文件移回原目录
        print(f'\n--- 清理：将 excel_files 中的文件移回原目录 ---')
        for f in buy_files:
            src = os.path.join(excel_dir, f)
            dst = os.path.join(output_dir, f)
            os.replace(src, dst)
            print(f'移回: {f}')
    else:
        print('今日无大笔买入数据，跳过入库')


    # ---------- 5. 有大买盘 → big_buy_summary 表 ----------
    print('\n--- 提取有大买盘数据 → big_buy_summary ---')
    try:
        df_big = ak.stock_changes_em(symbol='有大买盘')
    except Exception as e:
        print(f'❌ 获取有大买盘失败: {e}')
        df_big = None

    if df_big is not None and not df_big.empty:
        import sqlite3
        from pathlib import Path
        DB = str(Path('/mnt/disk990g/sqlite-data/chanlun_klines.sqlite'))
        conn = sqlite3.connect(DB)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS big_buy_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT,
                symbol TEXT,
                name TEXT,
                time TEXT,
                qty REAL,
                price REAL,
                change REAL,
                amount REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bbs_date ON big_buy_summary(trade_date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bbs_symbol ON big_buy_summary(symbol)")

        today_str = datetime.now().strftime('%Y-%m-%d')
        inserted = 0
        for _, row in df_big.iterrows():
            try:
                info = str(row['相关信息']).strip()
                parts = [p.strip() for p in info.split(',')]
                if len(parts) < 4:
                    continue
                conn.execute(
                    "INSERT INTO big_buy_summary (trade_date, symbol, name, time, qty, price, change, amount) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (today_str, str(row['代码']), str(row['名称']), str(row['时间']),
                     float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
                )
                inserted += 1
            except (ValueError, KeyError):
                continue
        conn.commit()
        conn.close()
        print(f'✅ big_buy_summary: 写入 {inserted} 条有大买盘记录')
    else:
        print('今日无有大买盘数据')


if __name__ == "__main__":
    main()

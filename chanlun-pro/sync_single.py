#!/usr/bin/env python3
"""单股票测试同步"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from chanlun.utils.trading_calendar import get_calendar
import sqlite3

DB_PATH = './db/chanlun_klines.sqlite'
cal = get_calendar()

def test_baostock():
    print("测试 Baostock...")
    try:
        import baostock as bs
        lg = bs.login()
        print(f"  登录：{lg.error_code}")
        if lg.error_code == '0':
            rs = bs.query_history_k_data_plus(
                "sh.600000", 
                "date,open,high,low,close,volume,amount",
                start_date="2026-05-11", end_date="2026-05-12",
                frequency="d", adjustflag="2"
            )
            print(f"  查询：{rs.error_code}")
            if rs.error_code == '0':
                data = rs.get_result()['data']
                print(f"  数据：{len(data)}条")
                bs.logout()
                return data
            bs.logout()
        return None
    except Exception as e:
        print(f"  错误：{e}")
        return None

def test_akshare():
    print("测试 AKShare...")
    try:
        import akshare as ak
        df = ak.stock_zh_a_hist(
            symbol="600000", period="daily",
            start_date="20260511", end_date="20260512",
            adjust="qfq", timeout=10
        )
        print(f"  数据：{len(df)}条")
        return df.values.tolist()
    except Exception as e:
        print(f"  错误：{e}")
        return None

if __name__ == "__main__":
    bs_data = test_baostock()
    if not bs_data:
        ak_data = test_akshare()
        if ak_data:
            print("✅ AKShare 可用，将使用 AKShare 同步")
        else:
            print("❌ 两个源都不可用")
    else:
        print("✅ Baostock 可用，将使用 Baostock 同步")
#!/usr/bin/env python3
"""
补齐 stock_fund_flow 资金流入数据表
数据源: 东方财富 (push2his.eastmoney.com)
覆盖: 全部 A 股（来自 all_stock_info），最近 60 个交易日
"""
import sqlite3
import requests
import time
import sys
from pathlib import Path
from datetime import datetime

DB_PATH = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))

def get_stock_list():
    """从 chanlun DB 的 all_stock_info 获取全部 A 股代码"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT symbol, name FROM all_stock_info WHERE symbol NOT LIKE '%ST%' AND name NOT LIKE '%退%' ORDER BY symbol").fetchall()
    conn.close()
    stocks = []
    for code, name in rows:
        code = code.strip()
        # 推断市场
        if code.startswith(('60', '68', '90')):
            mkt = 'sh'
            market_id = 1
        elif code.startswith(('00', '30')):
            mkt = 'sz'
            market_id = 0
        elif code.startswith(('83', '87', '43')):
            mkt = 'bj'
            market_id = 0  # 北交所也用 0
        else:
            continue
        stocks.append((code, mkt, market_id, name))
    return stocks


def get_fund_flow(code: str, market_id: int) -> list:
    """获取单只股票资金流数据（最近 60 天）
    
    东方财富 API 字段 (fields2=f51..f63):
      f51=日期, f52=主力净流入, f53=超大单净流入, f54=大单净流入,
      f55=中单净流入, f56=小单净流入,
      f57=主力净占比, f58=超大单占比, f59=大单占比,
      f60=中单占比, f61=小单占比, f62=收盘价, f63=涨跌幅
    """
    secid = f"{market_id}.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "lmt": "60",
        "klt": "101",
        "secid": secid,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}
    
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        data = r.json()
        if data.get('rc') != 0 or not data.get('data'):
            return []
        
        klines = data['data'].get('klines', [])
        if not klines:
            return []
        
        records = []
        for line in klines:
            parts = line.split(',')
            if len(parts) < 13:
                continue
            try:
                records.append({
                    'symbol': code,
                    'trade_date': parts[0],
                    'main_inflow': float(parts[1]) if parts[1] and parts[1] != '-' else 0,
                    'big_inflow': float(parts[2]) if parts[2] and parts[2] != '-' else 0,
                    'large_inflow': float(parts[3]) if parts[3] and parts[3] != '-' else 0,
                    'medium_inflow': float(parts[4]) if parts[4] and parts[4] != '-' else 0,
                    'small_inflow': float(parts[5]) if parts[5] and parts[5] != '-' else 0,
                    'main_pct': float(parts[6]) if parts[6] and parts[6] != '-' else 0,
                    'big_pct': float(parts[7]) if parts[7] and parts[7] != '-' else 0,
                    'large_pct': float(parts[8]) if parts[8] and parts[8] != '-' else 0,
                    'medium_pct': float(parts[9]) if parts[9] and parts[9] != '-' else 0,
                    'small_pct': float(parts[10]) if parts[10] and parts[10] != '-' else 0,
                    'close': float(parts[11]) if parts[11] and parts[11] != '-' else 0,
                    'pct_change': float(parts[12]) if parts[12] and parts[12] != '-' else 0,
                    'turnover': 0,
                })
            except (ValueError, IndexError):
                continue
        return records
    except Exception as e:
        return []


def upsert_records(conn, records: list):
    sql = """
        INSERT OR REPLACE INTO stock_fund_flow 
        (symbol, trade_date, close, pct_change, main_inflow, main_pct,
         big_inflow, big_pct, large_inflow, large_pct, 
         medium_inflow, medium_pct, small_inflow, small_pct, turnover)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    values = [(r['symbol'], r['trade_date'], r['close'], r['pct_change'],
               r['main_inflow'], r['main_pct'], r['big_inflow'], r['big_pct'],
               r['large_inflow'], r['large_pct'], r['medium_inflow'], r['medium_pct'],
               r['small_inflow'], r['small_pct'], r['turnover']) for r in records]
    conn.executemany(sql, values)


def main():
    stocks = get_stock_list()
    total = len(stocks)
    print(f"📋 待抓取: {total} 只股票", flush=True)
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    
    # 确保表存在
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stock_fund_flow (
            symbol TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            close REAL DEFAULT 0,
            pct_change REAL DEFAULT 0,
            main_inflow REAL DEFAULT 0,
            main_pct REAL DEFAULT 0,
            big_inflow REAL DEFAULT 0,
            big_pct REAL DEFAULT 0,
            large_inflow REAL DEFAULT 0,
            large_pct REAL DEFAULT 0,
            medium_inflow REAL DEFAULT 0,
            medium_pct REAL DEFAULT 0,
            small_inflow REAL DEFAULT 0,
            small_pct REAL DEFAULT 0,
            turnover REAL DEFAULT 0,
            PRIMARY KEY (symbol, trade_date)
        )
    """)
    
    success = 0; empty = 0; batch = []
    batch_size = 5000
    t0 = time.time()
    
    for i, (code, mkt, market_id, name) in enumerate(stocks):
        records = get_fund_flow(code, market_id)
        if records:
            success += 1
            batch.extend(records)
        else:
            empty += 1
        
        if len(batch) >= batch_size:
            upsert_records(conn, batch)
            conn.commit()
            batch = []
        
        if (i + 1) % 200 == 0 or (i + 1) == total:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            print(f"  [{i+1}/{total}] {(i+1)/total*100:.0f}% ✓{success} ✗{empty} "
                  f"| {rate:.1f}只/s | ETA {eta:.0f}s", flush=True)
        
        time.sleep(0.12)
    
    if batch:
        upsert_records(conn, batch)
        conn.commit()
    
    total_rows = conn.execute("SELECT COUNT(*) FROM stock_fund_flow").fetchone()[0]
    symbols = conn.execute("SELECT COUNT(DISTINCT symbol) FROM stock_fund_flow").fetchone()[0]
    latest = conn.execute("SELECT MAX(trade_date) FROM stock_fund_flow").fetchone()[0]
    
    print(f"\n✅ 完成:", flush=True)
    print(f"   成功: {success} 只 ({success/total*100:.1f}%)", flush=True)
    print(f"   无数据: {empty} 只", flush=True)
    print(f"   总行数: {total_rows:,}", flush=True)
    print(f"   覆盖股票: {symbols} 只", flush=True)
    print(f"   最新日期: {latest}", flush=True)
    
    conn.close()


if __name__ == "__main__":
    main()

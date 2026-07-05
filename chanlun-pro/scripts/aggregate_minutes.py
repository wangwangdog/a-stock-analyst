#!/usr/bin/env python3
"""从已有的5m数据聚合 15m/30m/60m（补齐06-04/06-05）"""
import os, sqlite3, time
from datetime import datetime

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
TARGETS = {"15m": 3, "30m": 6, "60m": 12}
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"

def now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def main():
    c = sqlite3.connect(DB, timeout=120)
    c.execute("PRAGMA busy_timeout=60000")
    
    # 取有06-04 5m数据的股票
    stocks = [r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' AND trade_date LIKE '2026-06-04%'"
    ).fetchall()]
    print(f"[{now_s()}] {len(stocks)} 只股票待聚合", flush=True)
    
    total_agg = 0
    t0 = time.time()
    
    for idx, sym in enumerate(stocks):
        for period, n in TARGETS.items():
            # 检查该周期是否有06-04/06-05数据
            has_new = c.execute(
                "SELECT 1 FROM kline_cache WHERE symbol=? AND period=? AND trade_date>=? LIMIT 1",
                (sym, period, "2026-06-04")
            ).fetchone()
            if has_new:
                continue  # 已有数据跳过
            
            # 取最新的n倍5m数据来聚合
            rows = c.execute(
                "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache "
                "WHERE symbol=? AND period='5m' AND trade_date>='2026-06-04' ORDER BY trade_date",
                (sym,)
            ).fetchall()
            
            if len(rows) < n:
                continue
            
            # 聚合
            ag = []
            for i in range(0, len(rows), n):
                chunk = rows[i:i+n]
                if len(chunk) < n:
                    continue
                # 取最后一根的日期时间
                last_ts = chunk[-1][0]
                ag.append((
                    sym, 'tencent', period, last_ts,
                    chunk[0][1],    # open = 第一根的开盘
                    chunk[-1][2],   # close = 最后一根的收盘
                    max(r[3] for r in chunk),   # high
                    min(r[4] for r in chunk),   # low
                    sum(r[5] for r in chunk),   # volume
                    sum(r[6] for r in chunk),   # amount
                ))
            
            if ag:
                c.executemany(INS, ag)
                c.commit()
                total_agg += len(ag)
        
        if (idx + 1) % 500 == 0:
            el = time.time() - t0
            print(f"  [{idx+1}/{len(stocks)}] +{total_agg}行 {el:.0f}s", flush=True)
    
    c.close()
    el = time.time() - t0
    print(f"[{now_s()}] 聚合完成: +{total_agg}行 {el:.0f}s", flush=True)

if __name__ == '__main__':
    main()

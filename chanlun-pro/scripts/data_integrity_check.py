#!/usr/bin/env python3
"""每日18:00检查并补齐各类数据最后一个交易日的数据"""
import sqlite3
import os
import sys
import subprocess
from datetime import datetime, timedelta

DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
WORK_DIR = "/home/dogzi/.openclaw/workspace/cl-vendors/chanlun-pro"
VENV_PYTHON = f"{WORK_DIR}/.venv/bin/python3"

report = []

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    report.append(msg)

def get_latest_trade_date(conn):
    """从 stock_daily 获取最新交易日"""
    cur = conn.execute("SELECT MAX(date) FROM stock_daily")
    return cur.fetchone()[0]

def get_trade_dates_from_table(conn):
    """从 trade_calendar 取交易日"""
    cur = conn.execute("SELECT cal_date FROM trade_calendar WHERE is_open=1 ORDER BY cal_date DESC LIMIT 5")
    return [r[0] for r in cur.fetchall()]

def check_and_fill():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA busy_timeout=60000")
    
    # 1. 确定最新交易日
    latest_date = get_latest_trade_date(conn)
    if not latest_date:
        log("❌ stock_daily 表无数据")
        conn.close()
        return
    
    log(f"最新交易日: {latest_date}")
    
    # 2. 检查 stock_daily 覆盖
    cur = conn.execute("SELECT COUNT(*) FROM stock_daily WHERE date=?", (latest_date,))
    daily_count = cur.fetchone()[0]
    
    # 3. 检查 kline_cache 各周期覆盖
    checks = {}
    for period in ['5m', '15m', '60m', 'd']:
        cur = conn.execute("""
            SELECT COUNT(DISTINCT symbol) FROM kline_cache 
            WHERE period=? AND trade_date LIKE ?||'%'
        """, (period, latest_date))
        checks[period] = cur.fetchone()[0]
    
    log(f"  daily(stock_daily): {daily_count}只")
    for p in ['5m', '15m', '60m', 'd']:
        log(f"  {p}(kline_cache): {checks[p]}只")
    
    # 4. stock_daily → kline_cache daily同步（如有缺漏）
    if daily_count > 0 and checks['d'] < daily_count:
        log(f"⚠️ kline_cache daily 缺 {daily_count - checks['d']} 只，同步中...")
        conn.execute("""
            INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)
            SELECT symbol, 'tdx', 'd', date, open, close, high, low, volume, turnover
            FROM stock_daily WHERE date=? AND symbol NOT IN (
                SELECT DISTINCT k.symbol FROM kline_cache k WHERE k.period='d' AND k.trade_date=?
            )
        """, (latest_date, latest_date))
        affected = conn.rowcount
        conn.commit()
        log(f"  → daily同步完成: +{affected}条")
    
    # 5. 检查 5m 是否完备（对比 stock_daily 的股票数）
    cur = conn.execute("""
        SELECT COUNT(*) FROM stock_daily s
        WHERE s.date=? AND s.symbol NOT LIKE '%.%'
        AND s.symbol NOT IN (
            SELECT DISTINCT k.symbol FROM kline_cache k 
            WHERE k.period='5m' AND k.trade_date LIKE ?||'%'
        )
    """, (latest_date, latest_date))
    missing_5m = cur.fetchone()[0]
    
    if missing_5m > 0 and missing_5m < 200:  # 少量缺失才用TDX补
        log(f"⚠️ 5m 缺 {missing_5m} 只，用 TDX 补齐...")
        cur = conn.execute("""
            SELECT s.symbol FROM stock_daily s
            WHERE s.date=? AND s.symbol NOT LIKE '%.%'
            AND s.symbol NOT IN (
                SELECT DISTINCT k.symbol FROM kline_cache k 
                WHERE k.period='5m' AND k.trade_date LIKE ?||'%'
            )
        """, (latest_date, latest_date))
        missing_codes = [r[0] for r in cur.fetchall()]
        
        from pytdx.hq import TdxHq_API
        total_ins = 0
        for sym in missing_codes:
            m = 1 if sym.startswith(('6', '68', '688')) else 0
            try:
                client = TdxHq_API(raise_exception=True, auto_retry=True)
                client.connect('180.153.18.170', 7709, time_out=8)
                bars = client.get_security_bars(0, m, sym, 0, 700)
                client.disconnect()
            except:
                try: client.disconnect()
                except: pass
                continue
            if not bars: continue
            ins = 0
            for bar in bars:
                dt = __import__('pandas').to_datetime(bar['datetime']).strftime('%Y-%m-%d %H:%M:%S')
                if not dt.startswith(latest_date):  # 只补当天的
                    continue
                try:
                    conn.execute('INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,0,0)',
                                 (sym, 'tdx', '5m', dt, float(bar['open']), float(bar['close']), float(bar['high']), float(bar['low'])))
                    ins += 1
                except: pass
            if ins:
                conn.commit()
                total_ins += ins
        log(f"  → 5m补齐: +{total_ins}条")
    elif missing_5m >= 200:
        log(f"⚠️ 5m 缺 {missing_5m} 只（过多），跳过TDX逐个补齐，改由系统日间同步覆盖")
    
    # 6. 从5m聚合15m/60m（仅补当天）
    for period, slot_fn in [
        ('15m', lambda dt: f"{dt[:10]} {int(dt[11:13]):02d}:{(int(dt[14:16])//15)*15:02d}:00"),
        ('60m', lambda dt: f"{dt[:10]} {int(dt[11:13]):02d}:00:00")
    ]:
        cur = conn.execute("""
            SELECT COUNT(DISTINCT a.symbol) FROM kline_cache a
            WHERE a.period='5m' AND a.trade_date LIKE ?||'%'
            AND NOT EXISTS (
                SELECT 1 FROM kline_cache b
                WHERE b.period=? AND b.trade_date LIKE ?||'%' AND b.symbol=a.symbol
            )
        """, (latest_date, period, latest_date))
        missing = cur.fetchone()[0]
        if missing == 0:
            log(f"  {period}: 已完整 ✅")
            continue
        
        log(f"⚠️ {period} 缺 {missing} 只，从5m聚合...")
        cur = conn.execute("""
            SELECT DISTINCT a.symbol FROM kline_cache a
            WHERE a.period='5m' AND a.trade_date LIKE ?||'%'
            AND NOT EXISTS (
                SELECT 1 FROM kline_cache b
                WHERE b.period=? AND b.trade_date LIKE ?||'%' AND b.symbol=a.symbol
            )
        """, (latest_date, period, latest_date))
        symbols = [r[0] for r in cur.fetchall()]
        
        done = 0
        for sym in symbols:
            cur = conn.execute("""
                SELECT trade_date, open, close, high, low, volume, amount 
                FROM kline_cache WHERE symbol=? AND period='5m' AND trade_date LIKE ?||'%'
                ORDER BY trade_date
            """, (sym, latest_date))
            rows = cur.fetchall()
            if not rows: continue
            
            agg = {}
            for r in rows:
                key = slot_fn(r[0])
                if key not in agg:
                    agg[key] = {'open': r[1], 'high': r[3], 'low': r[4], 'close': r[2], 'volume': r[5], 'amount': r[6]}
                else:
                    if r[3] > agg[key]['high']: agg[key]['high'] = r[3]
                    if r[4] < agg[key]['low']: agg[key]['low'] = r[4]
                    agg[key]['close'] = r[2]
                    agg[key]['volume'] += r[5]
                    agg[key]['amount'] += r[6]
            
            conn.executemany(
                "INSERT OR REPLACE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(sym, 'py', period, k, v['open'], v['close'], v['high'], v['low'], v['volume'], v['amount']) for k, v in sorted(agg.items())]
            )
            done += 1
            if done % 500 == 0:
                conn.commit()
        conn.commit()
        log(f"  → {period}聚合完成: {done}只")
    
    conn.close()
    log("✅ 数据完整性检查完成")

if __name__ == '__main__':
    check_and_fill()
    print("\n--- 报告 ---")
    for line in report:
        print(line)

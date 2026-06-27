#!/usr/bin/env python3
"""
Baostock 分钟线慢速同步（15/30/60 分钟）
策略：
- 1 并发，随机延迟 2-5 秒
- 每 100 只股票休息 30 秒
- 优先补齐 30 分钟（狗哥要求），再 15/60 分钟
"""
import sys
import sqlite3
import time
import random
import baostock as bs
from pathlib import Path
from datetime import date, timedelta
from loguru import logger

DB_PATH = Path.home() / '.chanlun_pro' / 'db' / 'chanlun_klines.sqlite'

# 交易日历（手动指定，或从 trade_calendar 表读取）
TRADING_DAYS = ['2026-05-28', '2026-05-29', '2026-05-30', '2026-05-31', '2026-06-01']

# 分钟线配置
MINUTE_CONFIG = {
    '30': {'freq': '30', 'bars_per_day': 8},  # 优先级最高
    '15': {'freq': '15', 'bars_per_day': 16},
    '60': {'freq': '60', 'bars_per_day': 4},
}

def get_stock_list():
    """获取股票列表"""
    conn = sqlite3.connect(str(DB_PATH))
    stocks = [r[0] for r in conn.execute("SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol").fetchall()]
    conn.close()
    logger.info(f"股票总数：{len(stocks)}")
    return stocks

def get_missing_dates(period, stock_list):
    """获取缺失的日期"""
    conn = sqlite3.connect(str(DB_PATH))
    missing_dates = {}
    
    for symbol in stock_list:
        cursor = conn.execute(
            "SELECT DISTINCT trade_date FROM kline_cache WHERE symbol=? AND period=? ORDER BY trade_date",
            (symbol, period)
        )
        existing = set(row[0][:10] for row in cursor.fetchall())
        missing = [d for d in TRADING_DAYS if d not in existing]
        if missing:
            missing_dates[symbol] = missing
    
    conn.close()
    return missing_dates

def fetch_minute_data(symbol, trade_date, freq):
    """从 Baostock 获取单只股票单日分钟线"""
    rs = bs.query_history_k_data_plus(
        s_code=f"sh.{symbol}" if symbol.startswith('6') else f"sz.{symbol}",
        start_date=trade_date,
        end_date=trade_date,
        frequency=freq,
        adjustflag="2",  # 前复权
        fields="date,time,open,high,low,close,volume,amount"
    )
    
    if rs.error_msg != "":
        return None
    
    data = []
    while rs.next():
        row = {
            'trade_date': trade_date,
            'open': float(rs.get_fields('open')),
            'high': float(rs.get_fields('high')),
            'low': float(rs.get_fields('low')),
            'close': float(rs.get_fields('close')),
            'volume': float(rs.get_fields('volume')),
            'amount': float(rs.get_fields('amount'))
        }
        data.append(row)
    
    return data

def insert_data(symbol, period, data):
    """插入数据到数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    
    inserted = 0
    for row in data:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO kline_cache 
                (symbol, source, period, trade_date, open, high, low, close, volume, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, 'baostock', period, row['trade_date'],
                row['open'], row['high'], row['low'], row['close'],
                row['volume'], row['amount']
            ))
            if cursor.rowcount > 0:
                inserted += 1
        except Exception as e:
            logger.warning(f"插入失败 {symbol} {period}: {e}")
    
    conn.commit()
    conn.close()
    return inserted

def sync_period(period, stock_list, missing_dates, batch_size=100, delay_range=(2, 5)):
    """
    同步指定周期分钟线
    - 1 并发，慢速
    - 每 batch_size 只股票休息 30 秒
    """
    freq = MINUTE_CONFIG[period]['freq']
    total_stocks = len(missing_dates)
    success_count = 0
    total_bars = 0
    
    logger.info(f"开始同步 {period}分钟线：{total_stocks} 只股票需要补齐")
    
    processed = 0
    for symbol, dates in missing_dates.items():
        # 慢速策略：每只股票前随机延迟
        time.sleep(random.uniform(*delay_range))
        
        success = False
        for trade_date in dates:
            # 获取数据
            data = fetch_minute_data(symbol, trade_date, freq)
            if data:
                inserted = insert_data(symbol, period, data)
                total_bars += inserted
                success = True
                logger.debug(f"✅ {symbol} {trade_date} {period}min: +{inserted}条")
            else:
                logger.warning(f"❌ {symbol} {trade_date} {period}min: 空数据")
        
        if success:
            success_count += 1
        
        processed += 1
        
        # 每 batch_size 只股票休息 30 秒
        if processed % batch_size == 0:
            logger.info(f"进度：{processed}/{total_stocks} ({processed*100//total_stocks}%)，休息 30 秒...")
            time.sleep(30)
    
    return {
        'period': period,
        'total_stocks': total_stocks,
        'success_stocks': success_count,
        'total_bars': total_bars
    }

def main():
    # 登录 Baostock
    lg = bs.login()
    if lg.error_msg != "":
        logger.error(f"Baostock 登录失败：{lg.error_msg}")
        return
    logger.info("✅ Baostock 登录成功")
    
    stock_list = get_stock_list()
    
    # 按优先级同步：30 分钟 → 15 分钟 → 60 分钟
    results = []
    for period in ['30', '15', '60']:
        logger.info(f"\n{'='*50}")
        logger.info(f"开始同步 {period}分钟线...")
        
        missing_dates = get_missing_dates(period, stock_list)
        if not missing_dates:
            logger.info(f"{period}分钟线：无缺失数据，跳过")
            continue
        
        result = sync_period(period, stock_list, missing_dates)
        results.append(result)
        
        bs.logout()
        # 换周期前休息 1 分钟
        if period != '60':
            time.sleep(60)
        bs.login()
    
    # 汇总报告
    logger.info("\n" + "="*60)
    logger.info("同步完成！")
    for r in results:
        logger.info(f"{r['period']}分钟线：{r['success_stocks']}/{r['total_stocks']} 只成功，+{r['total_bars']} 条数据")
    
    bs.logout()

if __name__ == "__main__":
    main()

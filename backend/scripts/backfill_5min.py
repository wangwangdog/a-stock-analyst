#!/usr/bin/env python3
"""
使用 pytdx (TDX 协议) 补齐历史 5 分钟 K 线数据
解决 mootdx 仅返回日线数据的问题
支持批量回补历史数据（不包括今天）
"""
import sys
import os
from pathlib import Path
from datetime import date, datetime, timedelta
import sqlite3
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pytdx.hq import TdxHq_API

DB_PATH = Path('/home/dogzi/sqlite-data/chanlun_klines.sqlite')

# 可用 TDX 服务器列表（从 chanlun 库获取的最佳 IP）
TDX_SERVERS = [
    ('180.153.18.170', 7709),
    ('218.75.126.9', 7709),
    ('60.12.136.250', 7709),
    ('shtdx.gtjas.com', 7709),
    ('sztdx.gtjas.com', 7709),
]

# 当前服务器索引
current_server_idx = 0

def get_tdx_server():
    """获取当前 TDX 服务器配置"""
    global current_server_idx
    return TDX_SERVERS[current_server_idx % len(TDX_SERVERS)]

def rotate_server():
    """轮询到下一个服务器"""
    global current_server_idx
    current_server_idx += 1


def log(msg: str):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_stocks():
    """获取股票列表"""
    conn = sqlite3.connect(DB_PATH)
    stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol"
    ).fetchall()]
    conn.close()
    return stocks


def get_date_range() -> Tuple[str, str]:
    """获取需要补全的日期范围（昨天往前推，不包括今天）"""
    today = date.today()
    # 默认补全昨天及之前的数据，不包括今天
    end_date = today - timedelta(days=1)
    # 默认补全最近 60 个交易日的历史数据
    start_date = end_date - timedelta(days=60)
    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def get_missing_period_stocks(start_date: str, end_date: str) -> List[str]:
    """
    获取缺少历史 5 分钟数据的股票列表
    检查指定日期范围内是否有数据，没有则加入缺失列表
    """
    conn = sqlite3.connect(DB_PATH)
    
    # 获取所有股票
    all_stocks = conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()
    
    # 检查哪些股票在指定日期范围内缺少 5 分钟数据
    missing_stocks = []
    for stock in all_stocks:
        symbol = stock[0]
        # 检查该股票在日期范围内是否有任何 5 分钟数据
        count = conn.execute(
            f"""SELECT COUNT(*) FROM kline_cache 
                WHERE symbol=? AND period='5min' AND source='tdx' 
                AND trade_date BETWEEN ? AND ?""",
            (symbol, start_date, end_date)
        ).fetchone()[0]
        if count == 0:
            missing_stocks.append(symbol)
    
    conn.close()
    return missing_stocks


def get_tdx_market(code: str) -> int:
    """返回 TDX 市场代码: 0=深圳，1=上海，2=北京"""
    code = str(code).strip()
    if code.startswith('6') or code.startswith('9'):
        return 1  # 上海
    if code.startswith('8') or code.startswith('4'):
        return 2  # 北京
    return 0  # 深圳 (0xxx, 3xxx)


def fetch_historical_5min(symbol: str, start_date: str, end_date: str) -> list:
    """
    使用 pytdx 获取历史 5 分钟 K 线（指定日期范围内）
    通过分页获取，每页 800 根，直到覆盖整个日期范围
    返回：[(trade_date, open, close, high, low, volume, amount), ...]
    """
    api = TdxHq_API()
    market = get_tdx_market(symbol)
    all_bars = []
    
    # Try all servers until one works
    for attempt in range(len(TDX_SERVERS)):
        server = get_tdx_server()
        try:
            if not api.connect(server[0], server[1], time_out=10):
                rotate_server()
                continue
            
            log(f"{symbol} 连接 {server[0]}:{server[1]} 成功，开始分页获取 5 分钟线...")
            
            # 目标日期
            target_date = datetime.strptime(start_date, "%Y-%m-%d")
            pos = 0
            max_pages = 20  # 最多 20 页，防止无限循环
            
            for page in range(max_pages):
                # 获取 800 根 K 线
                klines = api.get_security_bars(2, market, symbol, pos, 800)
                
                if not klines or len(klines) == 0:
                    break
                
                # 解析 datetime 并筛选
                page_bars = []
                oldest_dt = None
                for k in klines:
                    dt_str = str(k['datetime'])
                    try:
                        bar_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                        # 只保留目标日期范围内的数据
                        if bar_dt >= target_date:
                            page_bars.append((
                                dt_str,
                                float(k['open']),
                                float(k['close']),
                                float(k['high']),
                                float(k['low']),
                                int(k['vol']),
                                float(k['amount'])
                            ))
                            if oldest_dt is None or bar_dt < oldest_dt:
                                oldest_dt = bar_dt
                        else:
                            # 已经到达目标日期之前，可以提前结束
                            break
                    except (ValueError, TypeError):
                        continue
                
                all_bars.extend(page_bars)
                
                # 检查是否已经获取到足够早的数据
                if oldest_dt and oldest_dt <= target_date:
                    log(f"{symbol} 已获取 {len(all_bars)} 条数据，覆盖到 {oldest_dt.strftime('%Y-%m-%d')}")
                    break
                
                # 移动到下一页
                pos += 800
                
                # 如果这一页数据很少，说明已经到底了
                if len(klines) < 800:
                    break
            
            api.disconnect()
            return all_bars
            
            # Filter by date range and convert to list of tuples
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            
            bars = []
            for k in klines:
                dt_str = str(k['datetime'])
                try:
                    bar_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    # Only include bars within date range (exclude today)
                    if start_dt <= bar_dt <= end_dt:
                        bars.append((
                            dt_str,
                            float(k['open']),
                            float(k['close']),
                            float(k['high']),
                            float(k['low']),
                            int(k['vol']),
                            float(k['amount'])
                        ))
                except (ValueError, TypeError):
                    continue
            
            api.disconnect()
            return bars
            
        except Exception as e:
            log(f"Error fetching {symbol} from {server}: {e}")
            try:
                api.disconnect()
            except:
                pass
            rotate_server()
            continue
    
    log(f"Error fetching {symbol}: All servers failed")
    return None


def save_historical_5min(symbol: str, bars: list):
    """
    保存历史 5 分钟数据到 kline_cache
    """
    if not bars:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Insert with REPLACE to handle unique constraint
        count = 0
        for bar in bars:
            cursor.execute(
                "INSERT OR REPLACE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'tdx', '5min', ?, ?, ?, ?, ?, ?, ?)",
                (symbol, bar[0], bar[1], bar[2], bar[3], bar[4], bar[5], bar[6])
            )
            count += 1
        
        conn.commit()
        return count
        
    except Exception as e:
        log(f"Error saving {symbol}: {e}")
        return 0
    finally:
        conn.close()


def process_stock(symbol: str):
    """处理单只股票"""
    bars = fetch_5min(symbol)
    if bars:
        count = save_5min(symbol, bars)
        if count > 0:
            return symbol, count
        else:
            return symbol, 0
    return symbol, -1


def process_historical_stock(symbol: str, start_date: str, end_date: str):
    """处理单只股票的历史数据"""
    bars = fetch_historical_5min(symbol, start_date, end_date)
    if bars:
        count = save_historical_5min(symbol, bars)
        if count > 0:
            return symbol, count
        else:
            return symbol, 0
    return symbol, -1


def main():
    parser = argparse.ArgumentParser(description="使用 TDX 协议批量补齐历史 5 分钟 K 线数据（不包括今天）")
    parser.add_argument("--limit", type=int, default=0, help="最多处理的股票数（0=全部）")
    parser.add_argument("--symbol", type=str, action="append", default=None, help="指定股票（可多次使用）")
    parser.add_argument("--workers", type=int, default=20, help="并发 worker 数")
    parser.add_argument("--days", type=int, default=60, help="回补天数（默认 60 天）")
    parser.add_argument("--start-date", type=str, default=None, help="开始日期 YYYY-MM-DD（覆盖--days）")
    parser.add_argument("--end-date", type=str, default=None, help="结束日期 YYYY-MM-DD（默认昨天）")
    args = parser.parse_args()
    
    # Calculate date range
    if args.start_date:
        start_date = args.start_date
    else:
        end_date_obj = (date.today() - timedelta(days=1)) if not args.end_date else datetime.strptime(args.end_date, "%Y-%m-%d").date()
        start_date = (end_date_obj - timedelta(days=args.days)).strftime("%Y-%m-%d")
    
    if args.end_date:
        end_date = args.end_date
    else:
        end_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    log(f"日期范围：{start_date} 至 {end_date}（不包括今天：{date.today()}）")
    
    if args.symbol:
        symbols = args.symbol
    else:
        symbols = get_missing_period_stocks(start_date, end_date)
        if args.limit and 0 < args.limit < len(symbols):
            symbols = symbols[:args.limit]
        log(f"需要补全历史 5 分钟数据的股票：{len(symbols)} 只")
    
    if not symbols:
        log("✅ 所有股票历史 5 分钟数据已齐全")
        return
    
    # Process with thread pool
    success = 0
    failed = 0
    total_bars = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_historical_stock, sym, start_date, end_date): sym for sym in symbols}
        
        for future in as_completed(futures):
            symbol, count = future.result()
            if count > 0:
                log(f"✅ {symbol}: 写入 {count} 条 5 分钟数据")
                success += 1
                total_bars += count
            elif count == 0:
                log(f"⚠️  {symbol}: 无数据")
                failed += 1
            else:
                log(f"❌ {symbol}: 获取失败")
                failed += 1
            
            if success % 100 == 0:
                log(f"进度：成功{success} 失败{failed}")
    
    # Verify
    conn = sqlite3.connect(DB_PATH)
    total_historical = conn.execute(
        f"""SELECT COUNT(*) FROM kline_cache 
            WHERE period='5min' AND source='tdx' 
            AND trade_date BETWEEN ? AND ?""",
        (start_date, end_date)
    ).fetchone()[0]
    conn.close()
    
    log(f"\n{'='*50}")
    log(f"✅ 完成：成功{success} 失败{failed}")
    log(f"📊 历史 5 分钟数据总量 ({start_date}~{end_date}): {total_historical} 条")
    log(f"{'='*50}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
使用 pytdx (TDX 协议) 批量回补历史 5 分钟 K 线数据
- 支持分页获取，覆盖任意历史日期
- 自动过滤节假日（无数据时跳过）
- 并发下载，速度极快
"""
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
import sqlite3
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from pytdx.hq import TdxHq_API

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 配置
DB_PATH = Path('/mnt/disk990g/sqlite-data/chanlun_klines.sqlite')
TDX_SERVER = ('180.153.18.170', 7709)  # 已验证可用


def log(msg: str):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def get_tdx_market(code: str) -> int:
    """返回 TDX 市场代码：0=深圳，1=上海，2=北京"""
    code = str(code).strip()
    if code.startswith('6') or code.startswith('9'):
        return 1  # 上海
    if code.startswith('8') or code.startswith('4'):
        return 2  # 北京
    return 0  # 深圳


def fetch_5min_bars(symbol: str, start_date: str, end_date: str) -> List[Tuple]:
    """
    使用 pytdx 分页获取历史 5 分钟 K 线
    返回：[(trade_date_str, open, close, high, low, volume, amount), ...]
    """
    api = TdxHq_API()
    market = get_tdx_market(symbol)
    all_bars = []
    
    try:
        if not api.connect(TDX_SERVER[0], TDX_SERVER[1], time_out=10):
            log(f"{symbol} 连接 TDX 服务器失败")
            return []
        
        target_start = datetime.strptime(start_date, "%Y-%m-%d")
        target_end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        
        # TDX 返回的数据可能不是按时间排序的，需要获取后过滤
        pos = 0
        max_pages = 100  # 获取足够多的数据覆盖目标范围
        
        for page in range(max_pages):
            klines = api.get_security_bars(2, market, symbol, pos, 800)
            
            if not klines or len(klines) == 0:
                break
            
            # 解析所有数据
            for k in klines:
                dt_str = str(k['datetime'])
                try:
                    # 尝试不同格式
                    bar_dt = None
                    for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]:
                        try:
                            bar_dt = datetime.strptime(dt_str, fmt)
                            break
                        except:
                            continue
                    
                    if bar_dt and target_start <= bar_dt < target_end:
                        all_bars.append((
                            dt_str,
                            float(k['open']),
                            float(k['close']),
                            float(k['high']),
                            float(k['low']),
                            int(k['vol']),
                            float(k['amount'])
                        ))
                except Exception as e:
                    continue
            
            # 如果这一页数据很少，说明已经到底了
            if len(klines) < 800:
                break
            
            pos += 800
        
        api.disconnect()
        return all_bars
        
    except Exception as e:
        log(f"{symbol} 异常：{e}")
        try:
            api.disconnect()
        except:
            pass
        return []


def save_bars(symbol: str, bars: List[Tuple]):
    """保存数据到数据库"""
    if not bars:
        return 0
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        count = 0
        for bar in bars:
            cursor.execute(
                "INSERT OR REPLACE INTO kline_cache "
                "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'tdx', '5min', ?, ?, ?, ?, ?, ?, ?)",
                (symbol, bar[0], bar[1], bar[2], bar[3], bar[4], bar[5], bar[6])
            )
            count += 1
        
        conn.commit()
        return count
        
    except Exception as e:
        log(f"{symbol} 保存失败：{e}")
        return 0
    finally:
        conn.close()


def get_stocks_to_fetch(start_date: str, end_date: str, limit: int = 0) -> List[str]:
    """获取需要补全的股票列表"""
    conn = sqlite3.connect(DB_PATH)
    
    # 获取所有股票
    all_stocks = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol"
    ).fetchall()]
    
    if limit and 0 < limit < len(all_stocks):
        all_stocks = all_stocks[:limit]
    
    conn.close()
    return all_stocks


def process_stock(symbol: str, start_date: str, end_date: str):
    """处理单只股票"""
    bars = fetch_5min_bars(symbol, start_date, end_date)
    if bars:
        count = save_bars(symbol, bars)
        if count > 0:
            return symbol, count
    return symbol, 0


def main():
    parser = argparse.ArgumentParser(description="批量回补历史 5 分钟 K 线数据")
    parser.add_argument("--start-date", type=str, required=True, help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, required=True, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=0, help="最多处理的股票数（0=全部）")
    parser.add_argument("--workers", type=int, default=10, help="并发 worker 数（默认 10）")
    args = parser.parse_args()
    
    log(f"开始回补 5 分钟数据：{args.start_date} 至 {args.end_date}")
    log(f"TDX 服务器：{TDX_SERVER[0]}:{TDX_SERVER[1]}")
    
    # 获取股票列表
    stocks = get_stocks_to_fetch(args.start_date, args.end_date, args.limit)
    log(f"共 {len(stocks)} 只股票待处理")
    
    if not stocks:
        log("没有股票需要处理")
        return
    
    # 并发处理
    success = 0
    total_bars = 0
    failed = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_stock, sym, args.start_date, args.end_date): sym 
            for sym in stocks
        }
        
        for future in as_completed(futures):
            symbol, count = future.result()
            if count > 0:
                log(f"✅ {symbol}: 写入 {count} 条")
                success += 1
                total_bars += count
            else:
                log(f"❌ {symbol}: 无数据或失败")
                failed += 1
            
            if success > 0 and success % 50 == 0:
                log(f"进度：成功{success} 失败{failed} 总数据量{total_bars}")
    
    # 验证
    conn = sqlite3.connect(DB_PATH)
    total_in_db = conn.execute(
        f"""SELECT COUNT(*) FROM kline_cache 
            WHERE period='5min' AND source='tdx' 
            AND trade_date BETWEEN ? AND ?""",
        (args.start_date, args.end_date)
    ).fetchone()[0]
    conn.close()
    
    log("="*60)
    log(f"✅ 完成")
    log(f"  成功：{success} 只股票")
    log(f"  失败：{failed} 只股票")
    log(f"  本次写入：{total_bars} 条")
    log(f"  数据库中总量：{total_in_db} 条")
    log("="*60)


if __name__ == "__main__":
    main()

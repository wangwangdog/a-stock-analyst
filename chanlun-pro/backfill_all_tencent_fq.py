#!/usr/bin/env python3
"""
全市场 tencent_fq 日线数据补齐
从腾讯 API 拉全量历史 → 写入 kline_cache（INSERT OR IGNORE，不覆盖）
并发请求加速
"""
import sys, os, json, urllib.request, sqlite3, time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
MAX_WORKERS = 8

TENCENT_CACHE = {}

def tencent_code(symbol):
    mkt, code = symbol.split(".")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt, mkt.lower())
    return f"{prefix}{code}"

def fetch_tencent_daily(tc_str):
    """从腾讯 API 拉日线数据（前复权），带缓存"""
    if tc_str in TENCENT_CACHE:
        return TENCENT_CACHE[tc_str]
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc_str},day,,,800,qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        stock_data = data.get("data", {}).get(tc_str, {})
        days = stock_data.get("qfqday", stock_data.get("day", stock_data.get("hfqday", [])))
        if not days:
            TENCENT_CACHE[tc_str] = None
            return None
        result = {}
        for item in days:
            if len(item) < 6:
                continue
            date_str = item[0]
            if len(date_str) != 10:
                continue
            try:
                # 丢弃 item[6] 如果是 dict（分红信息）
                vol = float(item[5]) if isinstance(item[5], (str, int, float)) else 0
                amount = float(item[6]) if len(item) > 6 and isinstance(item[6], (str, int, float)) else 0
                result[date_str] = {
                    "open": float(item[1]), "close": float(item[2]),
                    "high": float(item[3]), "low": float(item[4]),
                    "volume": vol, "amount": amount,
                }
            except (ValueError, IndexError):
                continue
        TENCENT_CACHE[tc_str] = result if result else None
        return TENCENT_CACHE[tc_str]
    except Exception as e:
        TENCENT_CACHE[tc_str] = None
        return None

def backfill_one(symbol):
    """补齐单只股票，返回 (symbol, new_count, api_count, error)"""
    tc = tencent_code(symbol)
    bars = fetch_tencent_daily(tc)
    if not bars:
        return (symbol, 0, 0, None)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA busy_timeout=30000")
        
        # 查已有的日期
        existing = set()
        for row in conn.execute(
            "SELECT trade_date FROM kline_cache WHERE symbol=? AND source='tencent_fq' AND period='daily'",
            (symbol,)
        ):
            existing.add(row[0])
        
        new_count = 0
        for date_str, b in bars.items():
            if date_str not in existing:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO kline_cache 
                           (symbol, source, period, trade_date, open, close, high, low, volume, amount)
                           VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)""",
                        (symbol, date_str, b["open"], b["close"], b["high"], b["low"], b["volume"], b["amount"])
                    )
                    new_count += 1
                except Exception:
                    pass
        
        conn.commit()
        conn.close()
        return (symbol, new_count, len(bars), None)
    except Exception as e:
        return (symbol, 0, len(bars), str(e))

def main():
    print(f"=== 全市场 tencent_fq 补齐 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    
    # 获取所有需要补齐的股票
    conn = sqlite3.connect(DB_PATH)
    all_symbols = set()
    for row in conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND source='tencent_fq'"
    ):
        all_symbols.add(row[0])
    conn.close()
    
    # 排除指数
    symbols = sorted(s for s in all_symbols if '.' in s and not s.startswith('SH.000') and not s.startswith('SZ.399') and not s.startswith('SH.688'))
    
    print(f"待处理: {len(symbols)} 只股票\n")
    
    total_new = 0
    total_stocks = 0
    errors = []
    
    start = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(backfill_one, s): s for s in symbols}
        done = 0
        for f in as_completed(futures):
            done += 1
            sym, new_cnt, api_cnt, err = f.result()
            total_new += new_cnt
            if api_cnt > 0:
                total_stocks += 1
            if err:
                errors.append((sym, err))
            
            if done % 200 == 0 or done == len(symbols):
                elapsed = time.time() - start
                rate = done / elapsed if elapsed > 0 else 0
                print(f"  [{done}/{len(symbols)}] 新增{total_new}条, {rate:.1f}只/秒, {elapsed:.0f}s", flush=True)
    
    elapsed = time.time() - start
    print(f"\n=== 完成 {elapsed:.0f}s ===")
    print(f"处理: {done} 只股票")
    print(f"有API数据: {total_stocks} 只")
    print(f"新增: {total_new} 条")
    if errors:
        print(f"错误: {len(errors)} 只")
        for sym, err in errors[:5]:
            print(f"  {sym}: {err}")
        if len(errors) > 5:
            print(f"  ... 共 {len(errors)} 个错误")

if __name__ == "__main__":
    main()

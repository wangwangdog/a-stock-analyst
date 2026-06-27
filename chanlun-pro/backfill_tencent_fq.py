#!/usr/bin/env python3
"""
补齐 tencent_fq 日线数据：从腾讯 API 拉全量历史 → 写入 kline_cache
不覆盖现有数据（INSERT OR IGNORE），只补缺的
"""
import sys, os, json, urllib.request, sqlite3, time
from datetime import datetime

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

def tencent_code(symbol):
    """SH.000001 → sh000001, SZ.301563 → sz301563"""
    mkt, code = symbol.split(".")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt, mkt.lower())
    return f"{prefix}{code}"

def fetch_tencent_daily(tencent_code_str):
    """从腾讯 API 拉日线数据（前复权）"""
    url = f"http://ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code_str},day,,,800,qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        stock_data = data.get("data", {}).get(tencent_code_str, {})
        days = stock_data.get("qfqday", stock_data.get("day", stock_data.get("hfqday", [])))
        if not days:
            return None
        result = []
        for item in days:
            date_str = item[0]
            if len(date_str) != 10:
                continue
            try:
                result.append({
                    "trade_date": date_str,
                    "open": float(item[1]),
                    "close": float(item[2]),
                    "high": float(item[3]),
                    "low": float(item[4]),
                    "volume": float(item[5]) if len(item) > 5 and isinstance(item[5], (str, int, float)) else 0,
                    "amount": float(item[6]) if len(item) > 6 and isinstance(item[6], (str, int, float)) else 0,
                })
            except (ValueError, IndexError):
                continue
        return result
    except Exception as e:
        print(f"  [ERR] 腾讯API请求失败: {e}", flush=True)
        return None

def backfill_one(conn, symbol):
    """补齐单只股票的 tencent_fq 数据"""
    tc = tencent_code(symbol)
    print(f"  {symbol} → 腾讯API...", end=" ", flush=True)
    
    bars = fetch_tencent_daily(tc)
    if not bars:
        print("❌ 无数据")
        return 0
    
    print(f"{len(bars)}条", end=" ", flush=True)
    
    # 检查已有
    existing = set()
    for row in conn.execute(
        "SELECT trade_date FROM kline_cache WHERE symbol=? AND source='tencent_fq' AND period='daily'",
        (symbol,)
    ):
        existing.add(row[0])
    
    new_bars = [b for b in bars if b["trade_date"] not in existing]
    if not new_bars:
        print("✅ 已全")
        return 0
    
    print(f"新{len(new_bars)}条", end=" ", flush=True)
    
    # 批量写入
    count = 0
    for b in new_bars:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO kline_cache 
                   (symbol, source, period, trade_date, open, close, high, low, volume, amount)
                   VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, b["trade_date"], b["open"], b["close"], b["high"], b["low"], b["volume"], b["amount"])
            )
            count += 1
        except Exception as e:
            pass
    
    conn.commit()
    print(f"→ 写入{count}条 ✅")
    return count

def main():
    stocks = [
        "SZ.000001",  # 平安银行
        "SH.603968",  # 醋化股份
        "SZ.301563",  # 爱尔创
    ]
    
    # 再加全市场 top 30 大市值股票
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=30000")
    
    print(f"=== tencent_fq 补齐 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    
    total_new = 0
    for sym in stocks:
        try:
            n = backfill_one(conn, sym)
            total_new += n
        except Exception as e:
            print(f"  [ERR] {sym}: {e}", flush=True)
        time.sleep(0.3)  # 请求间隔
    
    print(f"\n总计新增: {total_new} 条")
    
    # 校验结果
    print(f"\n=== 补齐后校验 ===")
    for sym in stocks:
        row = conn.execute(
            "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM kline_cache WHERE symbol=? AND source='tencent_fq' AND period='daily'",
            (sym,)
        ).fetchone()
        print(f"  {sym}: {row[0]} 条 ({row[1]} ~ {row[2]})")
    
    conn.close()

if __name__ == "__main__":
    main()

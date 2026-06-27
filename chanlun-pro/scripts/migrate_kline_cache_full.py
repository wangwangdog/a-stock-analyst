#!/usr/bin/env python3
"""
全量迁移 kline_cache + 补齐指数分钟数据

1. 所有裸码加前缀: 6xxxx→SH., 0/3xxxx→SZ., 8/4xxxx→BJ.
2. 补充 SH.000001/SZ.399001 的 5m/15m/30m 数据
"""
import sys, os, sqlite3, re, time
from pathlib import Path

sys.path.insert(0, str(Path(os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))))
DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")

def prefix_for(code):
    """根据代码前缀判断市场"""
    if code.startswith(('6', '688', '900')):
        return 'SH.'
    if code.startswith(('0', '3', '002', '200', '300', '301')):
        return 'SZ.'
    if code.startswith(('8', '4', '920')):
        return 'BJ.'
    return None

def migrate_kline_cache():
    """给 kline_cache 所有裸码加前缀"""
    conn = sqlite3.connect(DB)
    # 获取所有裸码（不含 . 的）
    rows = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE symbol NOT LIKE '%.%'"
    ).fetchall()
    
    total = 0
    for (symbol,) in rows:
        pref = prefix_for(symbol)
        if pref is None:
            continue
        full = f"{pref}{symbol}"
        # 检查是否已有带前缀的数据
        has = conn.execute(
            "SELECT 1 FROM kline_cache WHERE symbol=? LIMIT 1", (full,)
        ).fetchone()
        if has:
            continue  # 已存在
        # 插入带前缀的数据（去重）
        conn.execute("""
            INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)
            SELECT ?, source, period, trade_date, open, close, high, low, volume, amount
            FROM kline_cache WHERE symbol=?
        """, (full, symbol))
        conn.commit()
        cnt = conn.execute(
            "SELECT COUNT(*) FROM kline_cache WHERE symbol=?", (full,)
        ).fetchone()[0]
        total += cnt
        print(f"  {symbol} → {full}: {cnt}条")
    
    conn.close()
    print(f"\n总计迁移 {total} 条记录")

def sync_index_minute(index_symbol, periods):
    """从TDX拉取指数分钟数据存入kline_cache"""
    from chanlun.exchange.exchange_tdx import ExchangeTDX
    ex = ExchangeTDX()
    
    conn = sqlite3.connect(DB)
    period_map = {"5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m"}
    total = 0
    for freq in periods:
        p = period_map[freq]
        # 检查是否已有数据
        exist = conn.execute(
            "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period=?", (index_symbol, p)
        ).fetchone()[0]
        if exist > 0:
            print(f"  {index_symbol} {freq}: 已有 {exist}条，跳过")
            total += exist
            continue
        
        klines = ex.klines(index_symbol, freq)
        if klines is None or len(klines) == 0:
            print(f"  {index_symbol} {freq}: 无数据")
            continue
        
        rows = []
        for _, r in klines.iterrows():
            d = r['date']
            if hasattr(d, 'strftime'):
                d = d.strftime('%Y-%m-%d %H:%M:%S')
            rows.append((index_symbol, 'tdx', p, str(d),
                         float(r['open']), float(r['close']),
                         float(r['high']), float(r['low']),
                         float(r.get('volume', 0)), float(r.get('amount', 0))))
        conn.executemany(
            "INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.commit()
        print(f"  {index_symbol} {freq}: 插入 {len(rows)} 条")
        total += len(rows)
    conn.close()
    return total

if __name__ == '__main__':
    t0 = time.time()
    
    # 1. 全量迁移裸码 → 带前缀
    print("=" * 50)
    print("步骤1: 全量迁移 kline_cache 裸码加前缀")
    print("=" * 50)
    migrate_kline_cache()
    
    # 2. 补充指数分钟数据
    print("\n" + "=" * 50)
    print("步骤2: 补充指数分钟数据")
    print("=" * 50)
    t = sync_index_minute("SH.000001", ["5m", "15m", "30m", "60m"])
    t += sync_index_minute("SZ.399001", ["5m", "15m", "30m", "60m"])
    print(f"  指数分钟数据: {t}条")
    
    # 3. 验证
    print("\n" + "=" * 50)
    print("步骤3: 验证")
    print("=" * 50)
    conn = sqlite3.connect(DB)
    for sym in ["SH.000001", "SZ.399001", "SZ.000001", "SH.600000"]:
        for p in ["daily", "5m", "15m", "30m"]:
            cnt = conn.execute(
                "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period=?",
                (sym, p)
            ).fetchone()[0]
            if cnt:
                print(f"  {sym} {p}: {cnt}条")
    conn.close()
    
    print(f"\n总耗时: {time.time()-t0:.0f}秒")

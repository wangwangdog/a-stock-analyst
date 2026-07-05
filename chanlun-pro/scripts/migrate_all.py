#!/usr/bin/env python3
"""
全量 kline_cache 数据迁移：裸码 → 带前缀
同时补齐指数(SH.000001/SZ.399001)分钟数据

分两阶段：
  阶段1(快): 迁移 daily 数据（190K条）
  阶段2(慢): 迁移分钟数据（42M条）+ 补齐指数分钟数据
  
运行: nohup python3 scripts/migrate_all.py > /tmp/migrate.log 2>&1 &
"""
import sys, os, sqlite3, re, time, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
LOG = "/tmp/migrate_all.log"

def log(msg):
    t = datetime.now().strftime("%H:%M:%S")
    line = f"[{t}] {msg}"
    print(line, flush=True)

def prefix_for(code):
    if code.startswith(('6', '688', '900')): return 'SH.'
    if code.startswith(('0', '3', '002', '200', '300', '301')): return 'SZ.'
    if code.startswith(('8', '4', '920')): return 'BJ.'
    return None

def phase1_migrate_daily():
    """阶段1：迁移 daily 数据到前缀"""
    log("=== 阶段1: 迁移 daily 数据 ===")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    
    symbols = conn.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND symbol NOT LIKE '%.%'"
    ).fetchall()
    log(f"待迁移 daily symbol: {len(symbols)} 个")
    
    total = 0
    for (symbol,) in symbols:
        pref = prefix_for(symbol)
        if pref is None: continue
        full = f"{pref}{symbol}"
        # 检查是否已有
        has = conn.execute("SELECT 1 FROM kline_cache WHERE symbol=? AND period='daily' LIMIT 1", (full,)).fetchone()
        if has: continue
        conn.execute("""
            INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)
            SELECT ?, source, period, trade_date, open, close, high, low, volume, amount
            FROM kline_cache WHERE symbol=? AND period='daily'
        """, (full, symbol))
        conn.commit()
        cnt = conn.execute("SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period='daily'", (full,)).fetchone()[0]
        total += cnt
        if total % 50000 == 0:
            log(f"  daily 已迁移 {total} 条")
    
    conn.close()
    log(f"阶段1完成: 迁移 daily {total} 条")

def populate_index_minutes():
    """补齐指数分钟数据"""
    log("=== 补齐指数分钟数据 ===")
    from chanlun.exchange.exchange_tdx import ExchangeTDX
    ex = ExchangeTDX()
    
    conn = sqlite3.connect(DB)
    period_map = {"5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m"}
    
    for idx_sym in ["SH.000001", "SZ.399001"]:
        for freq, period in period_map.items():
            has = conn.execute(
                "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period=?", (idx_sym, period)
            ).fetchone()[0]
            if has > 100:
                log(f"  {idx_sym} {freq}: 已有 {has}条，跳过")
                continue
            klines = ex.klines(idx_sym, freq)
            if klines is None or len(klines) == 0:
                log(f"  {idx_sym} {freq}: TDX无数据")
                continue
            rows = []
            for _, r in klines.iterrows():
                d = r['date']
                if hasattr(d, 'strftime'):
                    d = d.strftime('%Y-%m-%d %H:%M:%S')
                rows.append((idx_sym, 'tdx', period, str(d),
                             float(r['open']), float(r['close']),
                             float(r['high']), float(r['low']),
                             float(r.get('volume', 0)), float(r.get('amount', 0))))
            conn.executemany(
                "INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows)
            conn.commit()
            log(f"  {idx_sym} {freq}: 插入 {len(rows)} 条")
    conn.close()

def phase2_migrate_minutes():
    """阶段2：全量迁移分钟数据到前缀"""
    log("=== 阶段2: 迁移分钟数据 ===")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    
    for period in ["5m", "15m", "30m", "60m"]:
        symbols = conn.execute(
            "SELECT DISTINCT symbol FROM kline_cache WHERE period=? AND symbol NOT LIKE '%.%'",
            (period,)
        ).fetchall()
        log(f"{period}: {len(symbols)} 个裸码")
        
        batch_total = 0
        for (symbol,) in symbols:
            pref = prefix_for(symbol)
            if pref is None: continue
            full = f"{pref}{symbol}"
            has = conn.execute(
                "SELECT 1 FROM kline_cache WHERE symbol=? AND period=? LIMIT 1", (full, period)
            ).fetchone()
            if has: continue
            conn.execute("""
                INSERT OR IGNORE INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)
                SELECT ?, source, period, trade_date, open, close, high, low, volume, amount
                FROM kline_cache WHERE symbol=? AND period=?
            """, (full, symbol, period))
            conn.commit()
            cnt = conn.execute(
                "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period=?", (full, period)
            ).fetchone()[0]
            batch_total += cnt
            if batch_total % 500000 == 0:
                log(f"  {period} 已迁移 {batch_total} 条, 当前 {symbol}→{full}")
        
        log(f"  {period}完成: 迁移 {batch_total} 条")
    
    conn.close()
    log("阶段2完成")

def verify():
    log("=== 验证 ===")
    conn = sqlite3.connect(DB)
    checks = [
        ("SH.000001", "daily"), ("SH.000001", "5m"), ("SH.000001", "15m"),
        ("SZ.399001", "daily"), ("SZ.399001", "5m"), ("SZ.399001", "15m"),
        ("SZ.000001", "daily"),
        ("SH.600000", "daily"),
    ]
    for sym, period in checks:
        cnt = conn.execute(
            "SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period=?", (sym, period)
        ).fetchone()[0]
        latest = conn.execute(
            "SELECT trade_date, close FROM kline_cache WHERE symbol=? AND period=? ORDER BY trade_date DESC LIMIT 1",
            (sym, period)
        ).fetchone()
        if cnt:
            log(f"  {sym} {period}: {cnt}条, 最新={latest[0]} {latest[1]}")
        else:
            log(f"  {sym} {period}: 无数据!")
    
    bare_cnt = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE symbol NOT LIKE '%.%'"
    ).fetchone()[0]
    pref_cnt = conn.execute(
        "SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE symbol LIKE '%.%'"
    ).fetchone()[0]
    log(f"\n  裸码: {bare_cnt} 个, 已前缀: {pref_cnt} 个")
    conn.close()

if __name__ == '__main__':
    t0 = time.time()
    phase1_migrate_daily()
    populate_index_minutes()
    phase2_migrate_minutes()
    verify()
    log(f"\n总耗时: {(time.time()-t0)/60:.1f} 分钟")

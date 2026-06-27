#!/usr/bin/env python3
"""补齐今天日线数据（增量模式）"""
import json, sqlite3, subprocess, sys, time
from pathlib import Path

DB_PATH = Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"
TODAY = "2026-06-10"

def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn

def code_prefix(bare):
    if bare.startswith(("6","9","68")): return "SH"
    if bare.startswith(("0","3","002","200","300","301")): return "SZ"
    if bare.startswith(("8","4","920")): return "BJ"
    return ""

conn = get_db()
# 从 kline_cache 拿已有股票的裸码
stocks = conn.execute(
    "SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND source='tencent_fq' "
    "AND LENGTH(symbol)<=6 AND symbol GLOB '[0-9]*'"
).fetchall()
stocks = [r[0] for r in stocks]
conn.close()

total = len(stocks)
print(f"📋 需补齐 {total} 只股票今天({TODAY})的数据...")

success = failed = 0
for i, bare in enumerate(stocks):
    prefix = code_prefix(bare)
    if not prefix:
        failed += 1
        continue
    market = prefix.lower()
    tc = f"{market}{bare}"
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc},day,,,5,qfq"
    try:
        ret = subprocess.run(["curl","-s",url], capture_output=True, text=True, timeout=15)
        d = json.loads(ret.stdout)
        sd = d.get("data",{}).get(tc,{})
        klines = sd.get("qfqday",[]) or sd.get("day",[])
        if not klines:
            failed += 1
            continue
        # 找今天数据
        today_k = None
        for k in klines:
            if k[0] == TODAY:
                today_k = k
                break
        if not today_k:
            failed += 1
            continue
        o, c, h, l = float(today_k[1]), float(today_k[2]), float(today_k[3]), float(today_k[4])
        vh = float(today_k[5])
        vol_shares = int(vh * 100)

        # 从 qt 取成交额
        qt = sd.get("qt",{}).get(tc,[])
        amt = 0
        for item in qt:
            if isinstance(item, str) and "/" in item and item.count("/") == 2:
                parts = item.split("/")
                try:
                    p, v, a = float(parts[0]), float(parts[1]), float(parts[2])
                    if abs(p - c) / max(c, 0.01) < 0.001:
                        amt = int(a)
                        break
                except: pass
        if amt == 0:
            amt = int(vh * 100 * ((o + c) / 2))

        # 写入 DB（删除旧数据，插入新数据）
        conn2 = get_db()
        for sym in (bare, f"{prefix}.{bare}"):
            conn2.execute("DELETE FROM kline_cache WHERE symbol=? AND trade_date=? AND period='daily'", (sym, TODAY))
            conn2.execute(
                "INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                "VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)",
                (sym, TODAY, o, c, h, l, vol_shares, amt)
            )
        conn2.commit()
        conn2.close()
        success += 1
    except Exception as e:
        failed += 1

    if (i+1) % 500 == 0:
        print(f"  [{i+1}/{total}] ✅{success} ❌{failed}")

print(f"✅ 完成! 成功: {success}  失败: {failed}")

# 验证
conn = get_db()
r = conn.execute("SELECT COUNT(*) FROM kline_cache WHERE trade_date=? AND period='daily'", (TODAY,)).fetchone()
print(f"验证: 今天({TODAY}) 共 {r[0]} 条记录")
r = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE trade_date=? AND period='daily'", (TODAY,)).fetchone()
print(f"       {r[0]} 只股票")
conn.close()

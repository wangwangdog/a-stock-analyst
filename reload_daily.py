"""
全量重载 stock_daily 日线数据
- 清空原表
- 从 baostock 用 前复权 (adjustflag=2) 逐只重拉
- 保持 4900 只股票
"""
import sys, sqlite3, time, os
from pathlib import Path
from datetime import datetime

os.chdir(Path(__file__).resolve().parent)
sys.path.insert(0, "backend")

import baostock as bs
import pandas as pd

DB = "backend/data/stock_cache.db"
ADJUST = "2"  # 前复权
FETCH_START = "2024-01-01"
FETCH_END = datetime.now().strftime("%Y-%m-%d")
BATCH_SAVE = 500  # 每 N 只写入一次

# 获取所有股票（从 AKShare 股票列表，避免从已清空的 stock_daily 读）
import akshare as ak
stk_df = ak.stock_info_a_code_name()
all_codes = stk_df['code'].astype(str).tolist()
# 过滤：主板(6,0)、创业板(3)、科创板(68)，排除 ST
symbols = []
stk_map = {}
for _, r in stk_df.iterrows():
    c = str(r['code'])
    n = str(r['name'])
    stk_map[c] = n
    if c.startswith(('6','3','0')) and 'ST' not in n.upper() and '退' not in n:
        symbols.append(c)
symbols.sort()
print(f"待重载股票: {len(symbols)} 只（来源: AKShare 全量列表）")

all_data = []
bs.login()

for i, symbol in enumerate(symbols):
    prefix = "sh" if symbol.startswith("6") or symbol.startswith("68") else "sz"
    try:
        rs = bs.query_history_k_data_plus(
            f"{prefix}.{symbol}",
            "date,open,high,low,close,volume,amount",
            start_date=FETCH_START, end_date=FETCH_END,
            frequency="d", adjustflag=ADJUST
        )
        rows = []
        while rs.next():
            r = rs.get_row_data()
            if r[0] and r[1] != "":
                rows.append({
                    "symbol": symbol,
                    "date": r[0],
                    "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]),
                    "volume": float(r[5] or 0), "turnover": float(r[6] or 0),
                })
        if rows:
            all_data.extend(rows)
    except Exception as e:
        print(f"  ❌ {symbol}: {e}")
    
    time.sleep(0.05)
    
    # 批量写入
    if len(all_data) >= BATCH_SAVE * 100 or (i + 1) % BATCH_SAVE == 0:
        pct = (i + 1) / len(symbols) * 100
        print(f"  {pct:.1f}% ({i+1}/{len(symbols)}), 已获取 {len(all_data)} 条")
    
    # 每 500 只写入一次
    if (i + 1) % BATCH_SAVE == 0:
        batch_syms = symbols[max(0, i - BATCH_SAVE + 1):i + 1]
        conn = sqlite3.connect(DB)
        placeholders = ",".join("?" * len(batch_syms))
        conn.execute(f"DELETE FROM stock_daily WHERE symbol IN ({placeholders})", batch_syms)
        # 分批写入，每批最多 100 行，避免 SQLite 变量数超限
        CHUNK = 100
        for start in range(0, len(all_data), CHUNK):
            chunk = all_data[start:start + CHUNK]
            rows = [(d["symbol"], d["date"], d["open"], d["high"], d["low"], d["close"], d["volume"], d["turnover"]) for d in chunk]
            conn.executemany(
                "INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?,?,?,?,?,?,?,?)",
                rows
            )
        conn.commit()
        conn.close()
        print(f"    ✅ 写入 {len(all_data)} 条")
        all_data = []

# 写入最后一批
if all_data:
    conn = sqlite3.connect(DB)
    CHUNK = 100
    for start in range(0, len(all_data), CHUNK):
        chunk = all_data[start:start + CHUNK]
        rows = [(d["symbol"], d["date"], d["open"], d["high"], d["low"], d["close"], d["volume"], d["turnover"]) for d in chunk]
        conn.executemany(
            "INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?,?,?,?,?,?,?,?)",
            rows
        )
    conn.commit()
    conn.close()
    print(f"  ✅ 最终写入 {len(all_data)} 条")

bs.logout()

# 验证
conn = sqlite3.connect(DB)
total = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
stocks = conn.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()[0]
dates = conn.execute("SELECT MIN(date), MAX(date) FROM stock_daily").fetchone()
conn.close()
print(f"\n✅ 重载完成: {total} 条, {stocks} 只, {dates[0]} ~ {dates[1]}")

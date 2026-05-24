"""
修复 stock_daily 中 volume 异常的股票（复权方式不一致导致）
只处理环比变化 > 3 倍的股票，重新用后复权 (adjustflag=1) 拉取覆盖
"""
import sys, sqlite3, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import baostock as bs

DB = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")
ADJUST_FLAG = "1"  # 后复权

conn = sqlite3.connect(DB)

# 找到所有有前一日数据的 05-06 记录，计算 volume 环比
anomalies = conn.execute("""
    SELECT a.symbol, a.volume, b.volume as prev_vol
    FROM stock_daily a
    JOIN stock_daily b ON a.symbol = b.symbol
        AND b.date = (SELECT MAX(date) FROM stock_daily WHERE symbol = a.symbol AND date < a.date)
    WHERE a.date = '2026-05-06' AND b.volume > 0
      AND 1.0 * a.volume / b.volume > 3
""").fetchall()

print(f"volume 环比 > 3x 需修复的股票: {len(anomalies)} 只")

# 也检查 04-29 和 04-30（可能之前的日期也不一致）
for chk_date in ['2026-04-29', '2026-04-30', '2026-04-27', '2026-04-28']:
    extra = conn.execute("""
        SELECT a.symbol, a.volume, b.volume as prev_vol
        FROM stock_daily a
        JOIN stock_daily b ON a.symbol = b.symbol
            AND b.date = (SELECT MAX(date) FROM stock_daily WHERE symbol = a.symbol AND date < a.date)
        WHERE a.date = ? AND b.volume > 0
          AND 1.0 * a.volume / b.volume > 3
    """, (chk_date,)).fetchall()
    if extra:
        print(f"  {chk_date}: {len(extra)} 只异常")
        anomalies.extend(extra)

# 去重
seen = set()
unique_symbols = []
for r in anomalies:
    if r[0] not in seen:
        seen.add(r[0])
        unique_symbols.append(r[0])

print(f"\n去重后需修复: {len(unique_symbols)} 只股票")

bs.login()
fixed = 0
BATCH = 50

for i in range(0, len(unique_symbols), BATCH):
    batch = unique_symbols[i:i+BATCH]
    batch_fixed = 0
    
    for code in batch:
        prefix = "sh" if code.startswith("6") or code.startswith("68") else "sz"
        try:
            rs = bs.query_history_k_data_plus(
                f"{prefix}.{code}",
                "date,open,high,low,close,volume,amount",
                start_date="2026-04-27", end_date="2026-05-06",
                frequency="d", adjustflag=ADJUST_FLAG
            )
            rows = []
            while rs.next():
                row = rs.get_row_data()
                if row[0] and row[1] != "":
                    rows.append(row)
            
            if rows:
                conn2 = sqlite3.connect(DB)
                for r in rows:
                    conn2.execute(
                        "UPDATE stock_daily SET open=?, high=?, low=?, close=?, volume=?, turnover=? WHERE symbol=? AND date=?",
                        (float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                         float(r[5] or 0), float(r[6] or 0), code, r[0])
                    )
                conn2.commit()
                conn2.close()
                batch_fixed += 1
        except Exception as e:
            pass
        time.sleep(0.02)
    
    fixed += batch_fixed
    pct = min(100, (i + BATCH) / len(unique_symbols) * 100)
    print(f"  {pct:.0f}%: 已修复 {fixed}/{len(unique_symbols)}")

bs.logout()
conn.close()
print(f"\n✅ 完成: 修复 {fixed}/{len(unique_symbols)} 只股票")

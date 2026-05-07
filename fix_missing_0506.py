"""补齐 sequoia stock_daily 表中缺失的 2026-05-06 数据"""
import sqlite3, time, sys, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, "backend")

import baostock as bs

DB = "backend/data/stock_cache.db"

conn = sqlite3.connect(DB)
missing = [
    r[0]
    for r in conn.execute(
        "SELECT symbol FROM stock_daily GROUP BY symbol HAVING MAX(date) < '2026-05-06'"
    ).fetchall()
]
conn.close()

print(f"需要补充 05-06 数据的股票: {len(missing)} 只")

bs.login()
inserted = 0
failed = 0
BATCH = 200

for i in range(0, len(missing), BATCH):
    batch = missing[i : i + BATCH]
    batch_ok = 0
    batch_fail = 0
    conn = sqlite3.connect(DB)

    for code in batch:
        prefix = "sh" if code.startswith("6") or code.startswith("68") else "sz"
        try:
            rs = bs.query_history_k_data_plus(
                f"{prefix}.{code}",
                "date,open,high,low,close,volume,amount",
                start_date="2026-05-06",
                end_date="2026-05-06",
                frequency="d",
                adjustflag="2",
            )
            row_data = []
            while rs.next():
                row = rs.get_row_data()
                if row[0] and row[1] != "":
                    row_data.append(row)

            if row_data:
                r = row_data[0]
                conn.execute(
                    "INSERT INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        code,
                        r[0],
                        float(r[1]),
                        float(r[2]),
                        float(r[3]),
                        float(r[4]),
                        float(r[5] or 0),
                        float(r[6] or 0),
                    ),
                )
                batch_ok += 1
            else:
                batch_fail += 1
        except Exception as e:
            batch_fail += 1
        time.sleep(0.02)

    conn.commit()
    conn.close()
    inserted += batch_ok
    failed += batch_fail
    pct = min(100, (i + BATCH) / len(missing) * 100)
    print(f"  {pct:.0f}%: +{batch_ok} OK, {batch_fail} skip (累计 {inserted} OK / {failed} skip)")
    if i > 0 and i % (BATCH * 5) == 0:
        time.sleep(1)

bs.logout()
print(f"\n✅ 完成: 新增 {inserted}, 跳过(无交易) {failed}")

"""临时脚本：用 ak 初始化 stock_daily 表（股票列表）"""
import sqlite3
import akshare as ak

DB_PATH = "/home/dogzi/.chanlun_pro/db/chanlun_klines.sqlite"
conn = sqlite3.connect(DB_PATH)

# 创建 stock_daily 表（只要 symbol 列）
conn.execute("""
    CREATE TABLE IF NOT EXISTS stock_daily (
        symbol TEXT NOT NULL,
        date TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume REAL,
        turnover REAL,
        PRIMARY KEY (symbol, date)
    )
""")

# 获取 A 股列表
try:
    df = ak.stock_info_a_code_name()
except Exception:
    df = ak.stock_zh_a_spot_em()

symbols = []
for _, r in df.iterrows():
    code = str(r["code"]).strip().zfill(6) if "code" in df.columns else str(r["symbol"]).strip().zfill(6)
    name = r.get("name", "")
    symbols.append((code, "2000-01-01", 0, 0, 0, 0, 0, 0))

# 仅插入 symbol（去重，最小数据）
for sym, *_ in symbols:
    conn.execute(
        "INSERT OR IGNORE INTO stock_daily (symbol, date, open, high, low, close, volume, turnover) VALUES (?, ?, 0, 0, 0, 0, 0, 0)",
        (sym, "2000-01-01")
    )

conn.commit()
cnt = conn.execute("SELECT COUNT(*) FROM stock_daily").fetchone()[0]
conn.close()
print(f"✅ stock_daily 初始化完成，共 {cnt} 只股票")

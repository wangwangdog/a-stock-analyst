"""补齐 all_stock_info 的财务数据（市值、每股收益、市盈率）"""
import sys, time, sqlite3
from pathlib import Path
sys.path.insert(0, "backend")
import akshare as ak
import baostock as bs

DB = str(Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"))
INTERVAL = 0.15

conn = sqlite3.connect(DB)
missing = [r[0] for r in conn.execute(
    "SELECT symbol FROM all_stock_info WHERE market_cap IS NULL OR eps IS NULL"
).fetchall()]
conn.close()
print(f"待补齐: {len(missing)} 只")

bs.login()
ok = 0
fail = 0
for i, symbol in enumerate(missing):
    prefix = "sh" if symbol.startswith("6") or symbol.startswith("68") else "sz"
    market_cap = None
    eps = None
    
    # 1. 市值
    try:
        info = ak.stock_individual_info_em(symbol)
        for _, r in info.iterrows():
            if "总市值" in str(r.iloc[0]):
                market_cap = float(r.iloc[1])
    except:
        pass
    
    # 2. 每股收益
    try:
        rs = bs.query_operation_data(f"{prefix}.{symbol}", year="2026", quarter="1")
        while rs.next():
            row = rs.get_row_data()
            if row[3]:
                eps = float(row[3])
    except:
        pass
    
    # 3. 写入
    if market_cap is not None or eps is not None:
        conn = sqlite3.connect(DB)
        if market_cap is not None:
            conn.execute("UPDATE all_stock_info SET market_cap=? WHERE symbol=?", (market_cap, symbol))
        if eps is not None and eps > 0:
            pe = market_cap / (eps * 1261147883) if market_cap else None  # approximate
            conn.execute("UPDATE all_stock_info SET eps=?, pe_ratio=? WHERE symbol=?", (eps, pe, symbol))
        conn.commit()
        conn.close()
        ok += 1
    else:
        fail += 1
    
    if (i + 1) % 200 == 0:
        print(f"  {i+1}/{len(missing)}: OK={ok}, 失败={fail}")
    
    time.sleep(INTERVAL)

bs.logout()
print(f"\n✅ 完成: 成功 {ok}, 失败 {fail}")

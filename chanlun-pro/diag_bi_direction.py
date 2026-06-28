"""检查最近两笔是否同向"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
sys.path.insert(0, SRC)

import sqlite3, pandas as pd
from pathlib import Path
HOME = str(Path.home())
DB = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"

def fetch_5m():
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT dt as date, o as open, h as high, l as low, c as close, v as volume, 0 as amount FROM a_klines_000001 WHERE f = '5m' ORDER BY dt DESC LIMIT 5000").fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount'])
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values('date').reset_index(drop=True)

from chanlun.cl2 import CD
from chanlun.cl_utils import query_cl_chart_config

df = fetch_5m()
cfg = query_cl_chart_config("a", "000001") or {}
cd = CD("SZ.000001", "5m", config=cfg)
cd.process_klines(df)
bis = cd.get_bis()

print(f"总笔数: {len(bis)}")
print("最近15笔:")
for bi in bis[-15:]:
    print(f"  idx={bi.index} type={bi.type} high={bi.high:.2f} low={bi.low:.2f} "
          f"start={bi.start.val:.2f} end={bi.end.val:.2f} "
          f"start_time={bi.start.k.date} end_time={bi.end.k.date}")

# 检查是否有连续同向
print("\n连续同向检查:")
for i in range(1, len(bis)):
    if bis[i].type == bis[i-1].type:
        print(f"  ❌ bis[{bis[i-1].index}]({bis[i-1].type}) → bis[{bis[i].index}]({bis[i].type})")
    elif i <= 5 or i >= len(bis) - 5:
        print(f"  ✓ bis[{bis[i-1].index}]({bis[i-1].type}) → bis[{bis[i].index}]({bis[i].type})")

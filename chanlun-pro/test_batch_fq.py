import json
import sqlite3
import subprocess
import time
from pathlib import Path

HOME = Path.home()
DB_PATH = HOME / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"

# 测试5只股票
test_codes = ['600000', '000002', '300750', '688111', '002415']
conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()

for code in test_codes:
    prefix = 'sh' if code.startswith(('6','9')) else 'sz'
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{code},day,,,300,qfq"
    
    try:
        r = subprocess.run(['curl','-s',url,'-H','User-Agent: Mozilla/5.0'], 
                         capture_output=True, text=True, timeout=25)
        d = json.loads(r.stdout)
        sd = d.get('data',{}).get(f'{prefix}{code}',{})
        klines = sd.get('qfqday', [])
        qt = sd.get('qt',{}).get(f'{prefix}{code}',[])
        
        if not klines:
            print(f'{code}: 无前复权数据')
            continue
        
        # 解析成交额
        amounts = {}
        for item in qt:
            if isinstance(item, str) and '/' in item and item.count('/') == 2:
                parts = item.split('/')
                try:
                    amt = float(parts[2])
                    price = float(parts[0])
                    if amt > 1000000:
                        for k in reversed(klines):
                            if abs(float(k[2]) - price) / max(float(k[2]), 0.01) < 0.001:
                                amounts[k[0]] = int(amt)
                                break
                except:
                    pass
        
        # 清理并写入
        for sym in [code, f'SH.{code}', f'SZ.{code}']:
            if cur.execute('SELECT COUNT(*) FROM kline_cache WHERE symbol=? AND period="daily"', (sym,)).fetchone()[0] > 0:
                # 删除旧数据
                cur.execute("DELETE FROM kline_cache WHERE symbol=? AND period='daily'", (sym,))
                
                # 写入新数据
                rows = []
                for k in klines:
                    date = k[0]
                    o,c,h,l = float(k[1]),float(k[2]),float(k[3]),float(k[4])
                    vh = float(k[5])
                    amt = amounts.get(date, int(vh * 100 * ((o + c) / 2)))
                    rows.append((sym,"tencent_fq","daily",date,o,c,h,l,amt,amt))
                
                cur.executemany(
                    "INSERT INTO kline_cache VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
                print(f'{code}->{sym}: {len(rows)}条 成交额样本={amt}')
        
        conn.commit()
        
    except Exception as e:
        print(f'{code}: 错误 {e}')

conn.close()

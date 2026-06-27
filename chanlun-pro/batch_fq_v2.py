#!/usr/bin/env python3
"""
全量A股前复权 + 成交额批量替换脚本 v2
遍历kline_cache所有daily标的 → 腾讯前复权 → volume=成交额
"""
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HOME = Path.home()
DB_PATH = HOME / ".chanlun_pro" / "db" / "chanlun_klines.sqlite"

MAX_WORKERS = 20
API_TIMEOUT = 25
TOTAL_LIMIT = 300
PROGRESS_INTERVAL = 100  # 每100只报一次进度


def get_symbol_mapping(conn):
    """获取bare_code → [(symbol, market)] 映射"""
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT symbol FROM kline_cache WHERE period="daily"')
    all_symbols = [r[0] for r in cur.fetchall()]

    mapping = {}
    for s in all_symbols:
        if '.' in s:
            prefix, code = s.split('.', 1)
            market = prefix.lower()
        else:
            code = s
            if code.startswith(('6', '9')):       market = 'sh'
            elif code.startswith(('0', '3')):     market = 'sz'
            elif code.startswith('8'):            market = 'bj'
            else:                                 market = 'sz'
        mapping.setdefault(code, []).append((s, market))
    return mapping


def process_one(bare_code, symbols):
    """处理一只股票，返回结果字典"""
    # 失败重试
    for attempt in range(2):
        try:
            # 市场判定
            markets = {m for _, m in symbols}
            market = next(iter(markets)) if len(markets) == 1 else \
                     ('sh' if bare_code.startswith(('6', '9')) else 'sz')
            
            tencent_code = f"{market}{bare_code}"
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tencent_code},day,,,{TOTAL_LIMIT},qfq"
            
            result = subprocess.run(
                ["curl", "-s", url, "-H", "User-Agent: Mozilla/5.0"],
                capture_output=True, text=True, timeout=API_TIMEOUT
            )
            d = json.loads(result.stdout)
            sd = d.get("data", {}).get(tencent_code, {})
            klines = sd.get("qfqday", [])
            if not klines:
                return {"bare": bare_code, "ok": False, "err": "no_qfq_data"}
            
            # 成交额提取
            qt = sd.get("qt", {}).get(tencent_code, [])
            amounts = {}
            for item in qt:
                if isinstance(item, str) and '/' in item and item.count('/') == 2:
                    parts = item.split('/')
                    try:
                        price, vol, amt = float(parts[0]), float(parts[1]), float(parts[2])
                        if amt > 1000000:
                            for k in reversed(klines):
                                if abs(float(k[2]) - price) / max(float(k[2]), 0.01) < 0.001:
                                    amounts[k[0]] = int(amt)
                                    break
                    except: pass
            
            # 每条K线准备
            rows_by_symbol = {}
            for sym, _ in symbols:
                rows = []
                for k in klines:
                    date = k[0]
                    o, c, h, l = float(k[1]), float(k[2]), float(k[3]), float(k[4])
                    vh = float(k[5])
                    amt = amounts.get(date, int(vh * 100 * ((o + c) / 2)))
                    rows.append((sym, "tencent_fq", "daily", date, o, c, h, l, int(vh * 100), amt))
                rows_by_symbol[sym] = rows
            
            return {"bare": bare_code, "ok": True, "rows": rows_by_symbol}
            
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
                continue
            return {"bare": bare_code, "ok": False, "err": str(e)}
    
    return {"bare": bare_code, "ok": False, "err": "max_retry"}


def write_results(conn, results_batch):
    """批量写入一批结果到数据库"""
    cur = conn.cursor()
    total = 0
    for r in results_batch:
        if not r["ok"]:
            continue
        for sym, rows in r["rows"].items():
            cur.execute("DELETE FROM kline_cache WHERE symbol=? AND period='daily'", (sym,))
            cur.executemany(
                "INSERT INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows
            )
            total += len(rows)
    conn.commit()
    return total


def main():
    print("=" * 60)
    print("全量A股 前复权+成交额 批量替换 v2")
    print(f"并发: {MAX_WORKERS}, 超时: {API_TIMEOUT}s, 单次: {TOTAL_LIMIT}条")
    print()

    conn = sqlite3.connect(str(DB_PATH))
    mapping = get_symbol_mapping(conn)
    items = list(mapping.items())
    total = len(items)
    
    # 排除指数 (代码以399/159/880开头的)
    items = [(c, s) for c, s in items 
             if not any(sym.startswith(('SH.', 'SZ.')) and (
                 sym.split('.')[1].startswith(('399', '159', '880')) or
                 sym.split('.')[1].startswith(('0', '1')) and len(sym.split('.')[1]) == 6 and sym not in ('SH.000001',)
             ) for sym, _ in s)]
    
    total = len(items)
    print(f"待处理: {total} 只股票")
    
    success = failed = skipped = 0
    total_rows = 0
    start_time = time.time()
    
    # 用固定连接写入，子进程只拉数据
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_one, code, syms): code 
                   for code, syms in items}
        
        write_buffer = []
        done = 0
        
        for future in as_completed(futures):
            result = future.result()
            done += 1
            
            if result["ok"]:
                write_buffer.append(result)
                success += 1
            else:
                # 检查是否是指数(无前复权)
                if "no_qfq" in result.get("err", ""):
                    skipped += 1
                else:
                    failed += 1
            
            # 每批写入
            if len(write_buffer) >= 20 or done == total:
                if write_buffer:
                    rows = write_results(conn, write_buffer)
                    total_rows += rows
                    write_buffer = []
            
            # 进度
            if done % PROGRESS_INTERVAL == 0 or done == total:
                elapsed = time.time() - start_time
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  [{done}/{total}] ✓{success} ✗{failed} -{skipped} 行:{total_rows:,} "
                      f"速率:{rate:.1f}/s ETA:{eta:.0f}s")
    
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"✅ 完成! 耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"   成功: {success}  跳过(指数): {skipped}  失败: {failed}")
    print(f"   写入: {total_rows:,} 条K线")
    
    # 验证
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*), COUNT(DISTINCT symbol) FROM kline_cache WHERE period="daily" AND source="tencent_fq"')
    fq_rows, fq_stocks = cur.fetchone()
    cur.execute('SELECT COUNT(*), COUNT(DISTINCT symbol) FROM kline_cache WHERE period="daily"')
    total_daily, total_stocks = cur.fetchone()
    print(f"\n最终状态:")
    print(f"   前复权: {fq_rows:,} 条 / {fq_stocks} 只")
    print(f"   总计: {total_daily:,} 条 / {total_stocks} 只")
    
    # 随机验证
    cur.execute('''
        SELECT symbol, trade_date, open, close, volume, amount 
        FROM kline_cache WHERE period="daily" AND source="tencent_fq"
        ORDER BY RANDOM() LIMIT 5
    ''')
    print("\n随机验证:")
    for r in cur.fetchall():
        print(f"  {r[0]} {r[1]} O:{r[2]:.2f} C:{r[3]:.2f} Vol(成交额):{r[4]:>15,}")
    
    conn.close()


if __name__ == "__main__":
    main()

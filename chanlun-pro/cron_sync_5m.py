#!/usr/bin/env python3
"""
5分钟数据定时任务
- 交易日收盘后(15:30)运行
- 同步当天5分钟数据
- 删除最老交易日数据，保持数据库大小

用法:
  python3 cron_sync_5m.py                    # 正常日终同步
  python3 cron_sync_5m.py --backfill          # 补历史缺失
  python3 cron_sync_5m.py --check             # 查看状态
"""
import os, sys, time, sqlite3, json, urllib.request
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
INS = "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)"
DEL = "DELETE FROM kline_cache WHERE period='5m' AND trade_date < ? AND trade_date >= ?"
N_WORKERS = 3
CUTOFF = "2026-05-26"  # 只处理 >= 此日

def now_s():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_all_symbols(c):
    return [r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m'"
    ).fetchall()]

def fetch_tencent(symbol):
    """腾讯API拉5m"""
    # 处理 SH./SZ. 前缀
    raw_code = symbol.split(".")[-1]
    if symbol.startswith(("SH.", "sh.")):
        pref = "sh"
    elif symbol.startswith(("SZ.", "sz.")):
        pref = "sz"
    elif symbol.startswith(("BJ.", "bj.")):
        pref = "sz"  # 北交所走sz通道
    else:
        pref = "sh" if raw_code.startswith(("6","688","900","7")) else "sz"
    url = f"http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pref}{raw_code},m5,,480"
    try:
        r = urllib.request.urlopen(url, timeout=10)
        data = json.loads(r.read())
    except:
        return (symbol, [])
    try:
        klines = data.get("data", {}).get(f"{pref}{symbol}", {}).get("m5", [])
    except AttributeError:
        return (symbol, [])
    if not isinstance(klines, list) or not klines:
        return (symbol, [])
    rows = []
    for item in klines:
        dt_str = str(item[0])
        td = f"{dt_str[:4]}-{dt_str[4:6]}-{dt_str[6:8]} {dt_str[8:10]}:{dt_str[10:12]}:00"
        if td < CUTOFF:
            continue
        vol_val = float(item[7]) * 100_000_000 if len(item) > 7 else 0.0  # item[7]是成交额(亿), 转元
        rows.append((symbol, "tencent", "5m", td,
                     float(item[1]), float(item[2]),
                     float(item[3]), float(item[4]),
                     vol_val, vol_val))  # volume和amount都存成交额(元)
    return (symbol, rows)

def sync_all(c, symbols, today_str):
    """同步所有股票5m数据"""
    n = len(symbols)
    print(f"[{now_s()}] 开始同步 {n}只", flush=True)
    all_rows = []
    done = total_rows = 0
    t0 = time.time()
    fail_syms = []

    with ThreadPoolExecutor(max_workers=N_WORKERS) as pool:
        futures = {pool.submit(fetch_tencent, s): s for s in symbols}
        for fut in as_completed(futures):
            done += 1
            symbol, rows = fut.result()
            if rows:
                all_rows.extend(rows)
                total_rows += len(rows)
            else:
                if done > n - 2000:  # 只记最后失败的
                    fail_syms.append(symbol)

            if len(all_rows) >= 30000:
                c2 = sqlite3.connect(DB, timeout=60)
                c2.execute("PRAGMA busy_timeout=60000")
                c2.executemany(INS, all_rows)
                c2.commit()
                c2.close()
                all_rows = []

            if done % 200 == 0:
                el = time.time() - t0
                rate = done / el
                eta = (n - done) / rate if rate > 0 else 0
                print(f"  [{done}/{n}] +{total_rows}行 {el:.0f}s ETA:{eta:.0f}s", flush=True)

    if all_rows:
        c2 = sqlite3.connect(DB, timeout=60)
        c2.execute("PRAGMA busy_timeout=60000")
        c2.executemany(INS, all_rows)
        c2.commit()
        c2.close()

    el = time.time() - t0
    print(f"[{now_s()}] 同步完成: +{total_rows}行 {el:.0f}s", flush=True)
    return fail_syms

def purge_oldest(c):
    """删最老交易日5m数据，保持数据库大小"""
    rows = c.execute(
        "SELECT DISTINCT SUBSTR(trade_date,1,10) as day FROM kline_cache "
        "WHERE period='5m' ORDER BY day LIMIT 1"
    ).fetchone()
    if not rows:
        return
    oldest_day = rows[0]
    next_day = (datetime.strptime(oldest_day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    c.execute(DEL, (next_day, oldest_day))
    deleted = c.rowcount
    print(f"[{now_s()}] 删除最老交易日 {oldest_day}: {deleted}行", flush=True)
    c.commit()

def cmd_check(c):
    """查看状态"""
    total = c.execute("SELECT COUNT(*) FROM kline_cache WHERE period='5m'").fetchone()[0]
    oldest = c.execute("SELECT MIN(trade_date) FROM kline_cache WHERE period='5m'").fetchone()[0]
    newest = c.execute("SELECT MAX(trade_date) FROM kline_cache WHERE period='5m'").fetchone()[0]
    symb = c.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period='5m'").fetchone()[0]
    today_cnt = c.execute(
        "SELECT COUNT(DISTINCT symbol) FROM kline_cache "
        "WHERE period='5m' AND trade_date LIKE '2026-06-02%'"
    ).fetchone()[0]
    print(f"5m数据: {total}行, {symb}只股票")
    print(f"范围: {oldest} ~ {newest}")
    print(f"今天(06-02)已有数据: {today_cnt}只")
    print(f"窗口内交易日: ~245天")

def cmd_backfill(c):
    """补历史缺失（一次性）"""
    symbols = get_all_symbols(c)
    stale = [s for s in symbols if c.execute(
        "SELECT 1 FROM kline_cache WHERE period='5m' AND symbol=? AND trade_date>='2026-05-28' LIMIT 1",
        (s,)
    ).fetchone() is None]
    print(f"[{now_s()}] 需补历史: {len(stale)}只", flush=True)
    if stale:
        fail = sync_all(c, stale, "backfill")
        if fail:
            print(f"失败({len(fail)}只), 尝试TDX回退...", flush=True)
            # TDX回退逻辑可加在这里

def main():
    action = "daily"
    if "--backfill" in sys.argv:
        action = "backfill"
    elif "--check" in sys.argv:
        action = "check"

    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA busy_timeout=60000")

    if action == "check":
        cmd_check(c)
    elif action == "backfill":
        cmd_backfill(c)
    elif action == "daily":
        symbols = get_all_symbols(c)
        today_str = datetime.now().strftime("%Y-%m-%d")
        print(f"[{now_s()}] 日终5m同步 {today_str}", flush=True)
        sync_all(c, symbols, today_str)
        purge_oldest(c)

    c.close()

if __name__ == "__main__":
    main()

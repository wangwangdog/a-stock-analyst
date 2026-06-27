#!/usr/bin/env python3
"""
全市场 tencent_fq 日线数据补齐（后台版）
从腾讯 API 拉全量历史 → 写入 kline_cache（INSERT OR IGNORE，不覆盖）
写日志到 /tmp/backfill_tencent_fq.log
"""
import sys, os, json, urllib.request, sqlite3, time, logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler("/tmp/backfill_tencent_fq.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
MAX_WORKERS = 8

def tencent_code(symbol):
    mkt, code = symbol.split(".")
    prefix = {"SH": "sh", "SZ": "sz", "BJ": "bj"}.get(mkt, mkt.lower())
    return f"{prefix}{code}"

def fetch_tencent_daily(tc_str):
    url = f"http://ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc_str},day,,,800,qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode("utf-8"))
        sd = data.get("data", {}).get(tc_str, {})
        days = sd.get("qfqday", sd.get("day", sd.get("hfqday", [])))
        if not days:
            return None
        result = {}
        for item in days:
            if len(item) < 6:
                continue
            ds = item[0]
            if len(ds) != 10:
                continue
            try:
                vol = float(item[5]) if isinstance(item[5], (str, int, float)) else 0
                amt = float(item[6]) if len(item) > 6 and isinstance(item[6], (str, int, float)) else 0
                result[ds] = {
                    "open": float(item[1]), "close": float(item[2]),
                    "high": float(item[3]), "low": float(item[4]),
                    "volume": vol, "amount": amt,
                }
            except (ValueError, IndexError):
                continue
        return result if result else None
    except Exception as e:
        return None

def process_one(symbol):
    tc = tencent_code(symbol)
    bars = fetch_tencent_daily(tc)
    if not bars:
        return (symbol, 0, 0)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA busy_timeout=30000")
        existing = set()
        for r in conn.execute(
            "SELECT trade_date FROM kline_cache WHERE symbol=? AND source='tencent_fq' AND period='daily'",
            (symbol,),
        ):
            existing.add(r[0])
        new = 0
        for ds, b in bars.items():
            if ds not in existing:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO kline_cache "
                        "(symbol, source, period, trade_date, open, close, high, low, volume, amount) "
                        "VALUES (?, 'tencent_fq', 'daily', ?, ?, ?, ?, ?, ?, ?)",
                        (symbol, ds, b["open"], b["close"], b["high"], b["low"], b["volume"], b["amount"]),
                    )
                    new += 1
                except Exception:
                    pass
        conn.commit()
        conn.close()
        return (symbol, new, len(bars))
    except Exception as e:
        return (symbol, 0, len(bars))

def main():
    t0 = time.time()
    conn = sqlite3.connect(DB_PATH)
    syms = set()
    for r in conn.execute("SELECT DISTINCT symbol FROM kline_cache WHERE period='daily' AND source='tencent_fq'"):
        syms.add(r[0])
    conn.close()

    # Filter A-stocks only
    stocks = sorted(
        s for s in syms
        if "." in s
        and not s.startswith("SH.000")
        and not s.startswith("SZ.399")
        and not s.startswith("BJ.")
    )
    log.info("待处理: %d 只", len(stocks))

    total_new = 0
    total_api = 0
    errors = 0
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process_one, s): s for s in stocks}
        for f in as_completed(futures):
            done += 1
            sym, new, api_cnt = f.result()
            total_new += new
            if api_cnt:
                total_api += 1
            if new == 0 and api_cnt == 0:
                errors += 1

            if done % 500 == 0 or done == len(stocks):
                elapsed = time.time() - t0
                log.info(
                    "[%d/%d] 新增%d条, 有数据%d只, 无数据%d只, %.0fs",
                    done, len(stocks), total_new, total_api, errors, elapsed,
                )

    log.info("完成! %.0fs 处理%d只, 有数据%d只, 新增%d条", time.time() - t0, done, total_api, total_new)

if __name__ == "__main__":
    main()

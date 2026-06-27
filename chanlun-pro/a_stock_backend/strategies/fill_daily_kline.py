"""
日线补齐（2025-10-01起）：保留下所有股票的最新日线数据

步骤：
1. 扫描所有 stock_daily 中的股票
2. 检查每只股票的最新日期
3. 如果最新日期 < 今天，用新浪API补齐缺失数据
4. 只保留 2025-10-01 之后的数据
"""
import sys, os, time, random, sqlite3, logging
from datetime import datetime, date, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', stream=sys.stdout)
logger = logging.getLogger('fill_daily')

DB_PATH = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
CUTOFF = "2025-10-01"


def get_conn():
    return sqlite3.connect(DB_PATH)


def get_all_symbols() -> list:
    """获取所有股票代码"""
    conn = get_conn()
    syms = [r[0] for r in conn.execute(
        "SELECT DISTINCT symbol FROM stock_daily WHERE symbol NOT LIKE 'SH.0%' AND symbol NOT LIKE 'SZ.399%' AND symbol NOT LIKE 'SH.880%' ORDER BY symbol"
    ).fetchall()]
    conn.close()
    return syms


def get_missing_symbols(symbols: list) -> list:
    """找出需要补充数据的股票"""
    conn = get_conn()
    today = date.today().isoformat()
    missing = []
    for sym in symbols:
        r = conn.execute(
            "SELECT MAX(date), COUNT(*) FROM stock_daily WHERE symbol=?", (sym,)
        ).fetchone()
        latest = r[0]
        cnt = r[1]
        # 交易需求：需要至少3个月的交易日（约60天）
        if latest is None or latest < today or cnt < 60:
            missing.append((sym, latest or "无", cnt))
    conn.close()
    logger.info(f"总{symbols}只, 需补充{len(missing)}只")
    return missing


def fetch_sina(symbol: str) -> list:
    """新浪日线（600条，覆盖2.5年）"""
    code = symbol.replace("SH.", "sh").replace("SZ.", "sz")
    if "." not in symbol:
        code = f"sh{symbol}" if symbol.startswith(("6", "9")) else f"sz{symbol}"
    try:
        import requests
        url = f"https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale=240&ma=no&datalen=600"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        records = []
        for item in data:
            try:
                dt = item["day"]
                if dt < CUTOFF:
                    continue  # 只保留 2025-10-01 之后
                records.append({
                    "date": dt,
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item["volume"]),
                    "turnover": float(item["close"]) * float(item["volume"]),
                })
            except (KeyError, ValueError):
                continue
        return records
    except Exception as e:
        return []


def write_batch(symbol: str, records: list) -> int:
    """批量写入（先删后插，保证>2025-10-01）"""
    if not records:
        return 0
    conn = get_conn()
    written = 0
    try:
        # 删掉该股所有旧数据（只保留2025-10-01后）
        conn.execute("DELETE FROM stock_daily WHERE symbol=? AND date < ?", (symbol, CUTOFF))
        for rec in records:
            conn.execute("""
                INSERT OR REPLACE INTO stock_daily
                (symbol, date, open, high, low, close, volume, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (symbol, rec["date"], rec["open"], rec["high"], rec["low"],
                  rec["close"], rec["volume"], rec["turnover"]))
            written += 1
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.warning(f"  写入失败: {e}")
        written = 0
    finally:
        conn.close()
    return written


def main():
    all_syms = get_all_symbols()
    total = len(all_syms)
    logger.info(f"总 {total} 只股票，扫描中...")

    missing = get_missing_symbols(all_syms)
    if not missing:
        logger.info("✅ 所有股票数据完整（2025-10-01后）")
        return

    ok, skip = 0, 0
    for idx, (sym, latest, cnt) in enumerate(missing, 1):
        logger.info(f"  [{idx}/{len(missing)}] {sym}: 最新={latest} 条数={cnt}")
        records = fetch_sina(sym)
        if not records:
            logger.warning(f"  ⏭ {sym}: 新浪无数据")
            skip += 1
            continue

        written = write_batch(sym, records)
        date_range = f"{records[0]['date']}~{records[-1]['date']}"
        logger.info(f"  ✅ {sym}: 写入{written}条 ({date_range})")
        ok += 1

        if idx % 50 == 0:
            logger.info(f"  --- {idx}/{len(missing)} OK={ok} SKIP={skip} 休息5秒 ---")
            time.sleep(5)
        else:
            time.sleep(random.uniform(0.5, 1.5))

    logger.info(f"\n✅ 完成! OK={ok} SKIP={skip}")


if __name__ == "__main__":
    main()

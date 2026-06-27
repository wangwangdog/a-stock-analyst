"""
合并 stock_daily 日线数据到 kline_cache 表
- stock_daily 是 bare code (000001)
- kline_cache 存 bare + prefixed (SH.000001 / SZ.301563 / BJ.8xxxxx)
- 以后增量日线只写 kline_cache
"""
import sqlite3
from pathlib import Path

DB = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")

PREFIX_MAP: dict[str, str] = {}
# 沪深300/科创50等指数特殊处理
SPECIAL_PREFIX = {
    "000001": "SH", "000002": "SH", "000003": "SH", "000016": "SH",
    "000300": "SH", "000688": "SH", "000905": "SH",
    "399001": "SZ", "399006": "SZ", "399016": "SZ", "399300": "SZ",
}


def code_prefix(bare: str) -> str:
    if bare in SPECIAL_PREFIX:
        return SPECIAL_PREFIX[bare]
    if bare.startswith("6") or bare.startswith("9"):
        return "SH"
    if bare.startswith("0") or bare.startswith("3"):
        return "SZ"
    if bare.startswith("8") or bare.startswith("4"):
        return "BJ"
    return ""


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    # 读取 stock_daily 全部数据
    rows = cur.execute(
        "SELECT symbol, date, open, high, low, close, volume, turnover "
        "FROM stock_daily ORDER BY symbol, date"
    ).fetchall()

    print(f"stock_daily 总行数: {len(rows)}")

    insert_sql = """INSERT OR IGNORE INTO kline_cache
        (symbol, source, period, trade_date, open, close, high, low, volume, amount)
        VALUES (?, ?, 'daily', ?, ?, ?, ?, ?, ?, ?)"""

    total = 0
    prefixed_total = 0
    errors = 0
    seen_symbols: set[str] = set()

    for sym, dt, op, hi, lo, cl, vol, amt in rows:
        try:
            # 裸码
            cur.execute(insert_sql, (sym, "stock_daily", dt, op, cl, hi, lo, vol or 0, amt or 0))
            total += 1

            # 前缀码（防止重复插入同一前缀）
            pref = code_prefix(sym)
            if pref:
                psym = f"{pref}.{sym}"
                cur.execute(insert_sql, (psym, "stock_daily", dt, op, cl, hi, lo, vol or 0, amt or 0))
                prefixed_total += 1
                seen_symbols.add(psym)
            else:
                seen_symbols.add(sym)
        except Exception as e:
            print(f"ERROR: {sym} {dt}: {e}")
            errors += 1

    conn.commit()
    conn.close()

    print(f"裸码插入: {total} 行")
    print(f"前缀码插入: {prefixed_total} 行")
    print(f"涉及去重股票: {len(seen_symbols)} 只")
    print(f"错误: {errors}")

    # 校验
    verify()


def verify():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    for sym in ["301563", "SZ.301563", "000001", "SH.000001"]:
        r = cur.execute(
            "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM kline_cache "
            "WHERE symbol=? AND period='daily'", (sym,)
        ).fetchone()
        print(f"kline_cache {sym:15s} daily: {r[0]:>5}条, {r[1]} ~ {r[2]}")

    # stock_daily 原始数量
    r = cur.execute(
        "SELECT COUNT(*), MIN(date), MAX(date) FROM stock_daily WHERE symbol='301563'"
    ).fetchone()
    print(f"stock_daily  301563:              {r[0]:>5}条, {r[1]} ~ {r[2]}")

    conn.close()


if __name__ == "__main__":
    main()

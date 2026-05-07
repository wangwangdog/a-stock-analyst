"""
Volume 数据校验 & 修复脚本
- 建立交易日历表 (trade_calendar)
- 双源校验最近交易日 volume
- 统一使用后复权 (adjustflag=1) 写入 stock_daily
"""
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import baostock as bs
from loguru import logger

DB = Path(__file__).resolve().parent.parent / "data" / "stock_cache.db"
ADJUST_FLAG = "1"  # 后复权，与 sequoia 引擎一致


# ────────────────────────────────
# 1. 建交易日历表
# ────────────────────────────────
def init_trade_calendar():
    """从 baostock 同步交易日历到本地"""
    conn = sqlite3.connect(str(DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_calendar (
            calendar_date TEXT PRIMARY KEY,
            is_trading_day INTEGER NOT NULL
        )
    """)
    # 检查最近数据是否已有
    last = conn.execute("SELECT MAX(calendar_date) FROM trade_calendar WHERE is_trading_day=1").fetchone()[0]
    if last and last >= datetime.now().strftime("%Y-%m-%d"):
        conn.close()
        logger.info("交易日历已最新")
        return

    logger.info("同步交易日历...")
    bs.login()
    rs = bs.query_trade_dates(start_date="2024-01-01", end_date="2027-12-31")
    rows = []
    while rs.next():
        row = rs.get_row_data()
        rows.append(row)
    bs.logout()

    conn.executemany(
        "INSERT OR REPLACE INTO trade_calendar (calendar_date, is_trading_day) VALUES (?, ?)",
        [(r[0], int(r[1])) for r in rows]
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM trade_calendar").fetchone()[0]
    conn.close()
    logger.info(f"交易日历已同步: {count} 天")


# ────────────────────────────────
# 2. 获取最近 N 个交易日
# ────────────────────────────────
def get_recent_trading_days(n: int = 5) -> list[str]:
    conn = sqlite3.connect(str(DB))
    rows = conn.execute(
        "SELECT calendar_date FROM trade_calendar WHERE is_trading_day=1 ORDER BY calendar_date DESC LIMIT ?",
        (n,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ────────────────────────────────
# 3. 从 baostock 获取单只股票日线（后复权）
# ────────────────────────────────
def fetch_baostock(symbol: str, start_date: str, end_date: str):
    prefix = "sh" if symbol.startswith("6") or symbol.startswith("68") else "sz"
    try:
        rs = bs.query_history_k_data_plus(
            f"{prefix}.{symbol}",
            "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag=ADJUST_FLAG
        )
        rows = []
        while rs.next():
            row = rs.get_row_data()
            if row[0] and row[1] != "":
                rows.append({
                    "date": row[0],
                    "open": float(row[1]), "high": float(row[2]),
                    "low": float(row[3]), "close": float(row[4]),
                    "volume": float(row[5] or 0), "turnover": float(row[6] or 0),
                })
        return rows
    except Exception as e:
        logger.debug(f"[baostock] {symbol} 获取失败: {e}")
        return []


# ────────────────────────────────
# 4. 校验并修复 volume
# ────────────────────────────────
def validate_and_fix(trade_dates: list[str]):
    """
    对每个交易日，对 stock_daily 中有该日数据的股票进行 volume 校验。
    用 baostock 重新获取后复权数据对比，不一致则覆盖。
    """
    if not trade_dates:
        logger.warning("无交易日可供校验")
        return

    logger.info(f"校验交易日: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)}天)")

    bs.login()
    try:
        for trade_date in trade_dates:
            logger.info(f"--- {trade_date} ---")
            conn = sqlite3.connect(str(DB))
            # 获取该日所有有数据的股票
            stocks = conn.execute(
                "SELECT symbol, open, high, low, close, volume, turnover FROM stock_daily WHERE date=?",
                (trade_date,)
            ).fetchall()
            conn.close()

            if not stocks:
                logger.info(f"  {trade_date} 无数据，跳过")
                continue

            fixed_count = 0
            for stock in stocks:
                symbol = stock[0]
                db_volume = stock[5]

                # 从 baostock 重新拉取
                fetched = fetch_baostock(symbol, trade_date, trade_date)
                if not fetched:
                    continue

                bs_row = fetched[0]
                bs_volume = bs_row["volume"]

                # 校验：volume 差异 > 1%（含复权不一致的情况）
                if bs_volume > 0 and db_volume > 0:
                    ratio = abs(bs_volume - db_volume) / max(bs_volume, db_volume)
                    if ratio > 0.01:
                        conn = sqlite3.connect(str(DB))
                        conn.execute(
                            "UPDATE stock_daily SET open=?, high=?, low=?, close=?, volume=?, turnover=? WHERE symbol=? AND date=?",
                            (bs_row["open"], bs_row["high"], bs_row["low"],
                             bs_row["close"], bs_row["volume"], bs_row["turnover"],
                             symbol, trade_date)
                        )
                        conn.commit()
                        conn.close()
                        fixed_count += 1
                        if fixed_count <= 5 or ratio > 100:
                            logger.info(f"  🔧 {symbol}: volume {db_volume:.0f} → {bs_volume:.0f} (差异 {ratio*100:.1f}%)")

            logger.info(f"  {trade_date}: 总 {len(stocks)} 只, 修正 {fixed_count} 只")

    finally:
        bs.logout()


# ────────────────────────────────
# main
# ────────────────────────────────
def main():
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}")

    init_trade_calendar()

    # 获取 stock_daily 中实际有数据的最近交易日
    conn = sqlite3.connect(str(DB))
    actual_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM stock_daily ORDER BY date DESC"
    ).fetchall()]
    conn.close()

    # 过滤出真正的交易日并取最近 5 个
    conn = sqlite3.connect(str(DB))
    trade_dates = [r[0] for r in conn.execute(
        "SELECT calendar_date FROM trade_calendar "
        "WHERE calendar_date IN ({}) AND is_trading_day=1 "
        "ORDER BY calendar_date DESC LIMIT 5".format(
            ",".join("?" * len(actual_dates))
        ),
        actual_dates
    ).fetchall()]
    conn.close()

    if not trade_dates:
        logger.info("无可校验的交易日")
        return

    logger.info(f"共 {len(trade_dates)} 个交易日待校验: {trade_dates[0]} ~ {trade_dates[-1]}")
    validate_and_fix(trade_dates)


if __name__ == "__main__":
    main()

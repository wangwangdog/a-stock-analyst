"""
大笔买入统计（big_deal_summary）
触发：交易日 15:05
- 扫描全市场逐笔成交（买盘）
- 连续最多3笔买入合并，手数达价格分档阈值即为1次"大笔买入"
- 开盘 09:30 前（集合竞价）及尾盘 15:00 后的成交不计入
- 仅统计 09:30~15:00 连续竞价时段
- 按股票每日汇总
"""
import sys
import time
from pathlib import Path
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import sqlite3
import akshare as ak
from loguru import logger

DB = "/home/dogzi/sqlite-data/chanlun_klines.sqlite"
INTERVAL = 0.15  # 每只股票间隔（秒）
OPEN_START = "09:30"  # 开盘后第一笔才算（剔除集合竞价）
TAIL_CUT = "15:00"    # 尾盘截止时间（含，之后不计入）

# 价格分档大单手数阈值（成交量单位：手）
PRICE_TIERS = [
    (5, 50000),          # 5元以下  ≥ 50000手
    (10, 25000),         # 5~10元   ≥ 25000手
    (50, 15000),         # 10~50元  ≥ 15000手
    (100, 6000),         # 50~100元 ≥ 6000手
    (500, 3000),         # 100~500元≥ 3000手
    (float("inf"), 1000),# 500元以上 ≥ 1000手
]

# 小单排除阈值（低于此值的不记入 all_stcok_daydeal）
SMALL_TIERS = [
    (5, 5000),           # 5元以下  < 5000手 → 小单排除
    (10, 3000),          # 5~10元   < 3000手
    (50, 2000),          # 10~50元  < 2000手
    (100, 500),          # 50~100元 < 500手
    (500, 200),          # 100~500元< 200手
    (float("inf"), 50), # 500元以上 < 50手
]


def get_threshold_lots(price: float) -> int:
    for max_price, lots in PRICE_TIERS:
        if price < max_price:
            return lots
    return 1000


def get_small_threshold(price: float) -> int:
    """小单阈值：低于此手数的为小单，不记入 all_stcok_daydeal"""
    for max_price, lots in SMALL_TIERS:
        if price < max_price:
            return lots
    return 50


def init_table():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS big_deal_summary (
            trade_date TEXT,
            symbol TEXT,
            name TEXT,
            big_buy_count INTEGER DEFAULT 0,
            big_buy_lots REAL DEFAULT 0,
            big_buy_amount REAL DEFAULT 0,
            total_lots REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS all_stcok_daydeal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT,
            symbol TEXT,
            time TEXT,
            price REAL,
            qty REAL,
            amount REAL,
            direction TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_asd_date ON all_stcok_daydeal(trade_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_asd_symbol ON all_stcok_daydeal(symbol)")
    conn.commit()
    conn.close()


def get_stock_list() -> list[tuple[str, str]]:
    try:
        df = ak.stock_info_a_code_name()
        stocks = []
        for _, r in df.iterrows():
            c, n = str(r["code"]), str(r["name"])
            if c.startswith(("6", "3", "0")) and "ST" not in n.upper() and "退" not in n:
                stocks.append((c, n))
        return stocks
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return []


def _prefix(code: str) -> str:
    return "sh" if code.startswith(("6", "68")) else "sz"


def fetch_tick(symbol: str) -> pd.DataFrame | None:
    """获取当日逐笔成交"""
    try:
        df = ak.stock_zh_a_tick_tx_js(f"{_prefix(symbol)}{symbol}")
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.debug(f"[{symbol}] tick 失败: {e}")
    return None


def calc_big_buys(df: pd.DataFrame) -> dict:
    """
    从逐笔成交中提取大笔买入。
    规则：尾盘15:00后不计入；买盘中连续最多3笔合并，手数达阈值即为1次大笔买入。
    """
    if "成交金额" not in df.columns or df.empty:
        return {"big_buy_count": 0, "big_buy_lots": 0, "big_buy_amount": 0,
                "total_lots": 0, "total_amount": 0}

    # 过滤开盘前（含集合竞价）和尾盘后
    day_df = df[(df["成交时间"] >= OPEN_START) & (df["成交时间"] < TAIL_CUT)].copy()
    if day_df.empty:
        return {"big_buy_count": 0, "big_buy_lots": 0, "big_buy_amount": 0,
                "total_lots": 0, "total_amount": 0}

    total_lots = day_df["成交量"].sum()
    total_amount = day_df["成交金额"].sum()

    # 只取买盘
    buys = day_df[day_df["性质"].str.contains("买盘", na=False)].copy()
    if buys.empty:
        return {"big_buy_count": 0, "big_buy_lots": 0, "big_buy_amount": 0,
                "total_lots": total_lots, "total_amount": total_amount}

    buys = buys.reset_index(drop=True)
    big_count = 0
    big_lots = 0
    big_amount = 0
    i = 0

    while i < len(buys):
        # 尝试合并 i ~ i+1 和 i ~ i+2
        merged_lots_1 = buys.loc[i, "成交量"]
        merged_amount_1 = buys.loc[i, "成交金额"]
        price = buys.loc[i, "成交价格"]
        threshold = get_threshold_lots(price)

        # 单笔已达阈值
        if merged_lots_1 >= threshold:
            big_count += 1
            big_lots += merged_lots_1
            big_amount += merged_amount_1
            i += 1
            continue

        # 尝试合并后1笔（共2笔）
        if i + 1 < len(buys):
            merged_lots_2 = merged_lots_1 + buys.loc[i + 1, "成交量"]
            merged_amount_2 = merged_amount_1 + buys.loc[i + 1, "成交金额"]
            if merged_lots_2 >= threshold:
                big_count += 1
                big_lots += merged_lots_2
                big_amount += merged_amount_2
                i += 2
                continue

        # 尝试合并后2笔（共3笔）
        if i + 2 < len(buys):
            merged_lots_3 = merged_lots_2 + buys.loc[i + 2, "成交量"]
            merged_amount_3 = merged_amount_2 + buys.loc[i + 2, "成交金额"]
            if merged_lots_3 >= threshold:
                big_count += 1
                big_lots += merged_lots_3
                big_amount += merged_amount_3
                i += 3
                continue

        # 达不到阈值，跳过当前笔
        i += 1

    return {
        "big_buy_count": big_count,
        "big_buy_lots": big_lots,
        "big_buy_amount": big_amount,
        "total_lots": total_lots,
        "total_amount": total_amount,
    }


_db_lock = threading.Lock()


def _to_num(v):
    """确保值存为 Python 原生数字（避免 numpy.float64 被 sqlite3 存成 blob）"""
    if v is None:
        return 0
    if isinstance(v, bytes):
        try:
            import struct
            return struct.unpack('d', v)[0] if len(v) == 8 else 0.0
        except:
            return 0.0
    return float(v)


def _process_stock(symbol: str, name: str, today: str) -> dict:
    """处理单只股票：拉取 tick → 计算大笔买入 + 提取非小单交易"""
    try:
        df = fetch_tick(symbol)
        if df is None or df.empty:
            return {"symbol": symbol, "name": name, "ok": False, "daydeal": []}
        result = calc_big_buys(df)

        # 提取非小单交易（写入 all_stcok_daydeal）
        daydeal = []
        if "成交金额" in df.columns:
            for _, row in df.iterrows():
                price = float(row.get("成交价格", 0))
                qty = float(row.get("成交量", 0))
                threshold = get_small_threshold(price)
                if qty >= threshold:
                    daydeal.append({
                        "trade_date": today,
                        "symbol": symbol,
                        "time": str(row.get("成交时间", "")),
                        "price": price,
                        "qty": qty,
                        "amount": float(row.get("成交金额", 0)),
                        "direction": str(row.get("性质", "")),
                    })

        return {
            "symbol": symbol, "name": name,
            "ok": True,
            "big_buy_count": int(result["big_buy_count"]),
            "big_buy_lots": _to_num(result["big_buy_lots"]),
            "big_buy_amount": _to_num(result["big_buy_amount"]),
            "total_lots": _to_num(result["total_lots"]),
            "total_amount": _to_num(result["total_amount"]),
            "has_big": result["big_buy_count"] > 0,
            "daydeal": daydeal,
        }
    except Exception as e:
        logger.debug(f"[{symbol}] 处理异常: {e}")
        return {"symbol": symbol, "name": name, "ok": False}


def _batch_write(rows: list[dict], today: str):
    """批量写入 big_deal_summary 和 all_stcok_daydeal"""
    with _db_lock:
        conn = sqlite3.connect(DB)
        try:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO big_deal_summary
                       (trade_date, symbol, name,
                        big_buy_count, big_buy_lots, big_buy_amount,
                        total_lots, total_amount)
                       VALUES (?,?,?, ?,?,?, ?,?)""",
                    (today, r["symbol"], r["name"],
                     r["big_buy_count"], r["big_buy_lots"], r["big_buy_amount"],
                     r["total_lots"], r["total_amount"])
                )
                # 同时写入 all_stcok_daydeal（非小单交易）
                for d in r.get("daydeal", []):
                    conn.execute(
                        "INSERT INTO all_stcok_daydeal (trade_date, symbol, time, price, qty, amount, direction) VALUES (?,?,?,?,?,?,?)",
                        (d["trade_date"], d["symbol"], d["time"], d["price"], d["qty"], d["amount"], d["direction"])
                    )
            conn.commit()
        finally:
            conn.close()


def main():
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}")

    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"🚀 big_deal_summary: {today}")
    logger.info(f"  规则: {OPEN_START}~{TAIL_CUT} 连续竞价时段 | 买盘连续≤3笔合并达阈值")

    init_table()

    stocks = get_stock_list()
    if not stocks:
        logger.error("无法获取股票列表，终止")
        return

    # 过滤已处理的股票
    conn = sqlite3.connect(DB)
    existing_set = set(
        r[0] for r in conn.execute(
            "SELECT symbol FROM big_deal_summary WHERE trade_date=?", (today,)
        ).fetchall()
    )
    conn.close()
    stocks = [(s, n) for s, n in stocks if s not in existing_set]

    logger.info(f"  待扫描: {len(stocks)} 只（已跳过 {len(existing_set)} 只已处理）")

    if not stocks:
        logger.info("全部已处理，跳过")
        return

    MAX_WORKERS = 8
    BATCH_WRITE = 100  # 每 N 条批量写入一次
    ok = 0
    failed = 0
    has_big = 0
    batch = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_process_stock, symbol, name, today): (symbol, name)
            for symbol, name in stocks
        }

        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            if result.get("ok"):
                ok += 1
                batch.append(result)
                if result.get("has_big"):
                    has_big += 1
            else:
                failed += 1
                # 写入空记录标记已扫描
                batch.append({
                    "symbol": result["symbol"],
                    "name": result["name"],
                    "big_buy_count": 0, "big_buy_lots": 0, "big_buy_amount": 0,
                    "total_lots": 0, "total_amount": 0,
                })

            # 批量写入
            if len(batch) >= BATCH_WRITE:
                _batch_write(batch, today)
                batch = []

            if (i + 1) % 200 == 0:
                pct = (i + 1) / len(stocks) * 100
                logger.info(f"  {pct:.0f}% ({i+1}/{len(stocks)}): OK={ok}, 有大笔={has_big}, 失败={failed}")

        # 写入剩余
        if batch:
            _batch_write(batch, today)

    # 汇总
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT SUM(big_buy_count), SUM(big_buy_lots), SUM(big_buy_amount) FROM big_deal_summary WHERE trade_date=?",
        (today,)
    ).fetchone()
    conn.close()

    total = ok + failed + len(existing_set)
    logger.info(f"✅ big_deal_summary 完成:")
    logger.info(f"  扫描 {total} 只, 成功 {ok}, 无成交 {failed}, 已跳过 {len(existing_set)}")
    logger.info(f"  有大笔买入股票: {has_big}")
    if row and row[0]:
        logger.info(f"  大笔买入总次数: {row[0]:.0f}")
        logger.info(f"  大笔买入总手数: {row[1]:.0f}")
        logger.info(f"  大笔买入总金额: {row[2] / 1e8:.2f} 亿")


if __name__ == "__main__":
    main()

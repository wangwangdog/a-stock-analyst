"""
大笔买入统计（big_deal_summary）
触发：交易日 15:05
- 扫描全市场逐笔成交（买盘）
- 连续最多3笔买入合并，手数达价格分档阈值即为1次"大笔买入"
- 尾盘 15:00 及之后的成交不计入
- 按股票每日汇总
"""
import sys
import time
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import sqlite3
import akshare as ak
from loguru import logger

DB = str(Path(__file__).resolve().parent.parent / "data" / "stock_cache.db")
INTERVAL = 0.15  # 每只股票间隔（秒）
TAIL_CUT = "15:00"  # 尾盘截止时间（含，之后不计入）

# 价格分档大单手数阈值（成交量单位：手）
PRICE_TIERS = [
    (5, 50000),          # 5元以下  ≥ 50000手
    (10, 25000),         # 5~10元   ≥ 25000手
    (50, 15000),         # 10~50元  ≥ 15000手
    (100, 6000),         # 50~100元 ≥ 6000手
    (500, 3000),         # 100~500元≥ 3000手
    (float("inf"), 1000),# 500元以上 ≥ 1000手
]


def get_threshold_lots(price: float) -> int:
    for max_price, lots in PRICE_TIERS:
        if price < max_price:
            return lots
    return 1000


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

    # 过滤尾盘 15:00 后的交易
    day_df = df[df["成交时间"] < TAIL_CUT].copy()
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


def main():
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}")

    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"🚀 big_deal_summary: {today}")
    logger.info(f"  规则: 买盘连续≤3笔合并达阈值 | 尾盘 {TAIL_CUT} 后不计入")

    init_table()

    stocks = get_stock_list()
    if not stocks:
        logger.error("无法获取股票列表，终止")
        return

    logger.info(f"  待扫描: {len(stocks)} 只")

    conn = sqlite3.connect(DB)
    ok = 0
    failed = 0
    skipped = 0
    has_big = 0

    for i, (symbol, name) in enumerate(stocks):
        # 跳过已有记录的股票
        existing = conn.execute(
            "SELECT 1 FROM big_deal_summary WHERE trade_date=? AND symbol=?",
            (today, symbol)
        ).fetchone()
        if existing:
            skipped += 1
            if (i + 1) % 500 == 0:
                logger.info(f"  {i+1}/{len(stocks)}: OK={ok}, 有大笔={has_big}, 跳过={skipped}, 失败={failed}")
            continue

        df = fetch_tick(symbol)
        if df is None or df.empty:
            conn.execute(
                "INSERT OR REPLACE INTO big_deal_summary (trade_date, symbol, name) VALUES (?,?,?)",
                (today, symbol, name)
            )
            conn.commit()
            failed += 1
            time.sleep(INTERVAL)
            continue

        result = calc_big_buys(df)

        conn.execute(
            """INSERT OR REPLACE INTO big_deal_summary
               (trade_date, symbol, name,
                big_buy_count, big_buy_lots, big_buy_amount,
                total_lots, total_amount)
               VALUES (?,?,?, ?,?,?, ?,?)""",
            (today, symbol, name,
             result["big_buy_count"], result["big_buy_lots"], result["big_buy_amount"],
             result["total_lots"], result["total_amount"])
        )
        conn.commit()
        ok += 1
        if result["big_buy_count"] > 0:
            has_big += 1

        if (i + 1) % 200 == 0:
            pct = (i + 1) / len(stocks) * 100
            logger.info(f"  {pct:.0f}% ({i+1}/{len(stocks)}): OK={ok}, 有大笔={has_big}, 跳过={skipped}, 失败={failed}")

        time.sleep(INTERVAL)

    conn.close()

    # 汇总
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT SUM(big_buy_count), SUM(big_buy_lots), SUM(big_buy_amount) FROM big_deal_summary WHERE trade_date=?",
        (today,)
    ).fetchone()
    conn.close()

    logger.info(f"✅ big_deal_summary 完成:")
    logger.info(f"  扫描 {ok + skipped + failed} 只, 成功 {ok}, 无成交 {failed}, 跳过 {skipped}")
    logger.info(f"  有大笔买入股票: {has_big}")
    if row and row[0]:
        logger.info(f"  大笔买入总次数: {row[0]:.0f}")
        logger.info(f"  大笔买入总手数: {row[1]:.0f}")
        logger.info(f"  大笔买入总金额: {row[2] / 1e8:.2f} 亿")


if __name__ == "__main__":
    main()

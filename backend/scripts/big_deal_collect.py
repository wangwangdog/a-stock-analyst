"""
大单采集：收盘后逐只扫描全市场逐笔成交，提取大单汇总
触发时间：17:30（确保当日成交数据完整）
写入 big_deal_summary 表
"""
import sys
import time
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import sqlite3
import akshare as ak
from loguru import logger

DB = str(Path(__file__).resolve().parent.parent / "data" / "stock_cache.db")
INTERVAL = 0.15  # 每只股票间隔（秒）

# 交易所前缀映射
def _prefix(code: str) -> str:
    if code.startswith(("6", "68")):
        return "sh"
    return "sz"


def init_table():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS big_deal_summary (
            trade_date TEXT,
            symbol TEXT,
            name TEXT,
            big_deal_count INTEGER DEFAULT 0,
            big_deal_amount REAL DEFAULT 0,
            buy_count INTEGER DEFAULT 0,
            buy_amount REAL DEFAULT 0,
            sell_count INTEGER DEFAULT 0,
            sell_amount REAL DEFAULT 0,
            neutral_count INTEGER DEFAULT 0,
            neutral_amount REAL DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            total_amount REAL DEFAULT 0,
            PRIMARY KEY (trade_date, symbol)
        )
    """)
    conn.commit()
    conn.close()


def get_stock_list() -> list[tuple[str, str]]:
    """从 AKShare 获取股票列表（code, name）"""
    try:
        df = ak.stock_info_a_code_name()
        stocks = []
        for _, r in df.iterrows():
            code = str(r["code"])
            name = str(r["name"])
            if code.startswith(("6", "3", "0")) and "ST" not in name.upper() and "退" not in name:
                stocks.append((code, name))
        return stocks
    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return []


# 价格分档大单手数阈值
# 成交量单位：手（akshare tick 数据默认单位为手）
PRICE_TIERS = [
    (5, 50000),      # 5元以下 ≥ 50000手
    (10, 25000),     # 5~10元 ≥ 25000手
    (50, 15000),     # 10~50元 ≥ 15000手
    (100, 6000),     # 50~100元 ≥ 6000手
    (500, 3000),     # 100~500元 ≥ 3000手
    (float("inf"), 1000),  # 500元以上 ≥ 1000手
]


def get_threshold_lots(price: float) -> int:
    """按成交价格返回大单阈值（手数）"""
    for max_price, lots in PRICE_TIERS:
        if price < max_price:
            return lots
    return 1000


def fetch_tick(symbol: str) -> pd.DataFrame | None:
    """获取当日逐笔成交（单位：手）"""
    try:
        df = ak.stock_zh_a_tick_tx_js(f"{_prefix(symbol)}{symbol}")
        if df is not None and not df.empty:
            return df
    except Exception as e:
        logger.debug(f"[{symbol}] tick 失败: {e}")
    return None


def extract_big_deals(df: pd.DataFrame) -> dict:
    """从逐笔成交中按价格分档阈值提取大单汇总"""
    if "成交金额" not in df.columns:
        return None

    total_count = len(df)
    total_amount = df["成交金额"].sum()

    # 逐笔判断是否达到该价格档位的大单手数阈值
    def _is_big(row):
        return row["成交量"] >= get_threshold_lots(row["成交价格"])

    big = df[df.apply(_is_big, axis=1)]
    if big.empty:
        return {
            "big_deal_count": 0, "big_deal_amount": 0,
            "buy_count": 0, "buy_amount": 0,
            "sell_count": 0, "sell_amount": 0,
            "neutral_count": 0, "neutral_amount": 0,
            "total_count": total_count,
            "total_amount": total_amount,
        }

    # 按买卖方向分组
    buy = big[big["性质"].str.contains("买盘", na=False)]
    sell = big[big["性质"].str.contains("卖盘", na=False)]
    neutral = big[big["性质"].str.contains("中性", na=False)]

    return {
        "big_deal_count": len(big),
        "big_deal_amount": big["成交金额"].sum(),
        "buy_count": len(buy),
        "buy_amount": buy["成交金额"].sum() if not buy.empty else 0,
        "sell_count": len(sell),
        "sell_amount": sell["成交金额"].sum() if not sell.empty else 0,
        "neutral_count": len(neutral),
        "neutral_amount": neutral["成交金额"].sum() if not neutral.empty else 0,
        "total_count": total_count,
        "total_amount": total_amount,
    }


def main():
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}")

    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"🚀 开始大单采集: {today}")
    logger.info(f"  大单阈值: 按价格分6档（5↓/5~10/10~50/50~100/100~500/500↑ → 50000/25000/15000/6000/3000/1000手）")

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
    big_found = 0

    for i, (symbol, name) in enumerate(stocks):
        # 跳过已有记录的股票
        existing = conn.execute(
            "SELECT 1 FROM big_deal_summary WHERE trade_date=? AND symbol=?",
            (today, symbol)
        ).fetchone()
        if existing:
            skipped += 1
            if (i + 1) % 500 == 0:
                logger.info(f"  {i+1}/{len(stocks)}: OK={ok}, 大单={big_found}, 跳过={skipped}, 失败={failed}")
            continue

        df = fetch_tick(symbol)
        if df is None or df.empty:
            # 无成交（停牌等），写入空记录标记已扫描
            conn.execute(
                "INSERT OR REPLACE INTO big_deal_summary "
                "(trade_date, symbol, name, total_count) VALUES (?,?,?,0)",
                (today, symbol, name)
            )
            conn.commit()
            skipped += 1
            failed += 1
            time.sleep(INTERVAL)
            continue

        result = extract_big_deals(df)
        if result is None:
            failed += 1
            time.sleep(INTERVAL)
            continue

        conn.execute(
            """INSERT OR REPLACE INTO big_deal_summary
               (trade_date, symbol, name,
                big_deal_count, big_deal_amount,
                buy_count, buy_amount,
                sell_count, sell_amount,
                neutral_count, neutral_amount,
                total_count, total_amount)
               VALUES (?,?,?, ?,?, ?,?, ?,?, ?,?, ?,?)""",
            (today, symbol, name,
             result["big_deal_count"], result["big_deal_amount"],
             result["buy_count"], result["buy_amount"],
             result["sell_count"], result["sell_amount"],
             result["neutral_count"], result["neutral_amount"],
             result["total_count"], result["total_amount"])
        )
        conn.commit()
        ok += 1
        if result["big_deal_count"] > 0:
            big_found += 1

        if (i + 1) % 200 == 0:
            pct = (i + 1) / len(stocks) * 100
            logger.info(f"  {pct:.0f}% ({i+1}/{len(stocks)}): OK={ok}, 大单={big_found}, 跳过={skipped}, 失败={failed}")

        time.sleep(INTERVAL)

    conn.close()

    # 汇总统计
    conn = sqlite3.connect(DB)
    total_big = conn.execute(
        "SELECT SUM(big_deal_count), SUM(big_deal_amount) FROM big_deal_summary WHERE trade_date=?",
        (today,)
    ).fetchone()
    conn.close()

    logger.info(f"✅ 大单采集完成:")
    logger.info(f"  扫描 {ok + skipped + failed} 只, 成功 {ok}, 无成交 {failed}, 已跳过 {skipped}")
    logger.info(f"  有大单股票: {big_found}")
    if total_big and total_big[0]:
        logger.info(f"  大单总笔数: {total_big[0]:.0f}")
        logger.info(f"  大单总金额: {total_big[1] / 1e8:.2f} 亿")


if __name__ == "__main__":
    main()

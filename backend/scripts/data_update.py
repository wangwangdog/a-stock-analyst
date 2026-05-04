"""
增量数据更新脚本
- 由 cron 定时调用（每周日晚 10 点）
- 只更新上周（最近 5 个交易日）的数据
- 支持全市场更新
"""
import sys
import time
import warnings
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from data.cache import _get_conn, save_kline
from config import REQUEST_INTERVAL

try:
    import akshare as ak
except ImportError:
    logger.error("AKShare 未安装")
    sys.exit(1)


BATCH_SIZE = 50
INTER_STOCK = 0.5
INTER_BATCH = 5
MINUTE_START_DATE = "20260201"  # 分钟级数据起始日


def get_all_stocks() -> pd.DataFrame:
    """获取所有 A 股代码"""
    df = ak.stock_info_a_code_name()
    if df is None or df.empty:
        return pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
    mask = df["code"].str.startswith(("6", "3", "0")) & ~df["name"].str.contains(r"ST|\*", na=False)
    return df[mask]


def get_last_trading_dates(days: int = 7) -> str:
    """获取最近 days 天的日期作为起始日期"""
    return (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")


def update_stock(symbol: str, start_date: str, end_date: str) -> bool:
    """更新单只股票的日线数据"""
    try:
        time.sleep(INTER_STOCK)
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=start_date, end_date=end_date,
            adjust="qfq"
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "日期": "trade_date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
            })
            df["trade_date"] = df["trade_date"].astype(str).str[:10]
            save_kline(symbol, "akshare", df, period="daily")
        return True
    except Exception as e:
        logger.warning(f"[{symbol}] 更新失败: {e}")
        return False


def update_minute_stock(symbol: str, period: str, start_date: str, end_date: str) -> bool:
    """更新单只股票的分钟级数据"""
    try:
        time.sleep(INTER_STOCK)
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol, period=period,
            start_date=start_date, end_date=end_date
        )
        if df is not None and not df.empty:
            df = df.rename(columns={
                "时间": "trade_date", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low",
                "成交量": "volume", "成交额": "amount",
            })
            df["trade_date"] = df["trade_date"].astype(str)
            save_kline(symbol, "akshare", df, period=f"{period}min")
        return True
    except Exception as e:
        logger.warning(f"[{symbol}] {period}min 更新失败: {e}")
        return False


def main():
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | {message}")

    logger.info("🚀 开始增量数据更新...")

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = get_last_trading_dates(7)

    logger.info(f"时间范围: {start_date} ~ {end_date}")

    stocks = get_all_stocks()
    if stocks.empty:
        logger.error("无法获取股票列表")
        return

    logger.info(f"共 {len(stocks)} 只股票需更新日线")

    # --- 更新日线 ---
    total = len(stocks)
    success = 0
    failed = 0
    for idx, (_, row) in enumerate(stocks.iterrows()):
        code = row["code"]
        name = row["name"]
        ok = update_stock(code, start_date, end_date)
        if ok:
            success += 1
        else:
            failed += 1
        if (idx + 1) % BATCH_SIZE == 0:
            logger.info(f"日线: {idx+1}/{total} (成功{success}, 失败{failed}), 休息 {INTER_BATCH}s...")
            time.sleep(INTER_BATCH)
    logger.info(f"日线更新: 成功{success}, 失败{failed}/{total}")

    # --- 更新分钟级 ---
    for minute_period in ("15", "30", "60"):
        logger.info(f"更新 {minute_period}min 分钟级数据...")
        ms = 0
        mf = 0
        for idx, (_, row) in enumerate(stocks.iterrows()):
            code = row["code"]
            ok = update_minute_stock(code, minute_period, MINUTE_START_DATE, end_date)
            if ok:
                ms += 1
            else:
                mf += 1
            if (idx + 1) % BATCH_SIZE == 0:
                logger.info(f"{minute_period}min: {idx+1}/{total} (成功{ms}, 失败{mf}), 休息 {INTER_BATCH}s...")
                time.sleep(INTER_BATCH)
        logger.info(f"{minute_period}min 更新: 成功{ms}, 失败{mf}/{total}")

    logger.info(f"✅ 所有数据更新完成")


if __name__ == "__main__":
    main()

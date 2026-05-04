"""
批量下载全A股历史数据
- 获取所有以 6/3/0 开头且非ST的股票
- 日线数据: 最近 3 年
- 周线数据: 最近 5 年
- 使用 AKShare, 支持断点续传
"""
import sys
import time
import warnings
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

warnings.filterwarnings("ignore")

# 确保后端模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger
from data.cache import _get_conn, save_kline, init_db
from config import REQUEST_INTERVAL

try:
    import akshare as ak
except ImportError:
    logger.error("AKShare 未安装")
    sys.exit(1)


# === 配置 ===
BATCH_SIZE = 50          # 每批数量
INTER_STOCK = 0.5        # 每只股票间隔（秒）
INTER_BATCH = 5          # 每批间隔（秒）
DAILY_YEARS = 3          # 日线年数
WEEKLY_YEARS = 5         # 周线年数
MINUTE_START_DATE = "20260201"  # 分钟级数据从 2026年2月起

# 进度记录表
PROGRESS_TABLE = "download_progress"


def init_progress_table():
    """初始化进度表"""
    conn = _get_conn()
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {PROGRESS_TABLE} (
                symbol TEXT PRIMARY KEY,
                period TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                downloaded_at TEXT DEFAULT (datetime('now','localtime')),
                error TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_progress(symbol: str, period: str) -> str:
    """获取股票下载状态: pending/done/error"""
    conn = _get_conn()
    try:
        cursor = conn.execute(
            f"SELECT status FROM {PROGRESS_TABLE} WHERE symbol=? AND period=?",
            (symbol, period)
        )
        row = cursor.fetchone()
        return row[0] if row else "pending"
    finally:
        conn.close()


def set_progress(symbol: str, period: str, status: str, error: str = ""):
    """记录下载进度"""
    conn = _get_conn()
    try:
        conn.execute(f"""
            INSERT OR REPLACE INTO {PROGRESS_TABLE}
            (symbol, period, status, downloaded_at, error)
            VALUES (?, ?, ?, datetime('now','localtime'), ?)
        """, (symbol, period, status, error))
        conn.commit()
    finally:
        conn.close()


def get_stock_list() -> pd.DataFrame:
    """获取过滤后的股票列表"""
    logger.info("获取 A 股列表...")
    df = ak.stock_info_a_code_name()
    if df is None or df.empty:
        logger.error("无法获取股票列表")
        return pd.DataFrame()

    df.columns = [c.lower() for c in df.columns]
    # 过滤：6/3/0 开头，非 ST
    mask = (
        df["code"].str.startswith(("6", "3", "0")) &
        ~df["name"].str.contains(r"ST|\*", na=False)
    )
    filtered = df[mask].copy()
    logger.info(f"过滤后共 {len(filtered)} 只股票 (原始 {len(df)} 只)")
    return filtered


def fetch_and_save(symbol: str, period: str, start_date: str, end_date: str) -> bool:
    """获取并缓存单只股票数据"""
    try:
        time.sleep(INTER_STOCK)

        if period == "daily":
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
                for c in ["trade_date", "open", "close", "high", "low"]:
                    if c not in df.columns:
                        return False
                df["trade_date"] = df["trade_date"].astype(str).str[:10]
                save_kline(symbol, "akshare", df, period="daily")
                return True

        elif period == "weekly":
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="weekly",
                start_date=start_date, end_date=end_date,
                adjust="qfq"
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "trade_date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low",
                    "成交量": "volume", "成交额": "amount",
                })
                for c in ["trade_date", "open", "close", "high", "low"]:
                    if c not in df.columns:
                        return False
                df["trade_date"] = df["trade_date"].astype(str).str[:10]
                save_kline(symbol, "akshare", df, period="weekly")
                return True

        elif period in ("15", "30", "60"):
            # 分钟级数据，start_date 格式无横线
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
                for c in ["trade_date", "open", "close", "high", "low"]:
                    if c not in df.columns:
                        return False
                df["trade_date"] = df["trade_date"].astype(str)
                period_key = f"{period}min"
                save_kline(symbol, "akshare", df, period=period_key)
                return True

        # 无数据返回但仍标记成功（有的新股数据少）
        return True

    except Exception as e:
        logger.warning(f"[{symbol}] {period} 获取失败: {e}")
        return False


def download_period(stocks: pd.DataFrame, period: str):
    """下载指定周期的所有数据"""
    years = DAILY_YEARS if period == "daily" else WEEKLY_YEARS
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=365 * years)).strftime("%Y%m%d")

    logger.info(f"=== 开始下载 {period} 数据 ({years}年) ===")
    logger.info(f"时间范围: {start_date} ~ {end_date}")

    total = len(stocks)
    downloaded = 0
    skipped = 0
    failed = 0

    for idx, row in stocks.iterrows():
        code = row["code"]
        name = row["name"]

        # 检查是否已存在
        status = get_progress(code, period)
        if status == "done":
            skipped += 1
            if (skipped + downloaded + failed) % 100 == 0:
                logger.info(f"  进度: {skipped + downloaded + failed}/{total} (已跳过{skipped}, 成功{downloaded}, 失败{failed})")
            continue

        logger.debug(f"[{code} {name}] 下载 {period}...")
        ok = fetch_and_save(code, period, start_date, end_date)

        if ok:
            set_progress(code, period, "done")
            downloaded += 1
        else:
            set_progress(code, period, "error", "fetch failed")
            failed += 1

        # 每 N 只休息一次
        if (downloaded + failed) % BATCH_SIZE == 0:
            paused_s = (skipped + downloaded + failed) / total * 100
            logger.info(f"  进度: {skipped + downloaded + failed}/{total} "
                        f"({paused_s:.1f}%), "
                        f"成功{downloaded}, 失败{failed}, 跳过{skipped}, 休息 {INTER_BATCH}s...")
            time.sleep(INTER_BATCH)

    logger.info(f"=== {period} 完成: 成功{downloaded}, 失败{failed}, 跳过{skipped} ===")


def download_minute_period(stocks: pd.DataFrame, period: str):
    """下载分钟级数据（从 MINUTE_START_DATE 起）"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = MINUTE_START_DATE
    period_label = f"{period}min"

    logger.info(f"=== 开始下载 {period_label} 数据 ({start_date} ~ {end_date}) ===")

    total = len(stocks)
    downloaded = 0
    skipped = 0
    failed = 0

    for idx, row in stocks.iterrows():
        code = row["code"]
        name = row["name"]

        status = get_progress(code, period_label)
        if status == "done":
            skipped += 1
            if (skipped + downloaded + failed) % 500 == 0:
                logger.info(f"  进度: {skipped + downloaded + failed}/{total} (跳过{skipped}, 成功{downloaded}, 失败{failed})")
            continue

        logger.debug(f"[{code} {name}] 下载 {period_label}...")
        ok = fetch_and_save(code, period, start_date, end_date)

        if ok:
            set_progress(code, period_label, "done")
            downloaded += 1
        else:
            set_progress(code, period_label, "error", "fetch failed")
            failed += 1

        if (downloaded + failed) % BATCH_SIZE == 0:
            logger.info(f"  进度: {skipped + downloaded + failed}/{total} "
                        f"({((skipped+downloaded+failed)/total*100):.1f}%), "
                        f"成功{downloaded}, 失败{failed}, 跳过{skipped}")
            time.sleep(INTER_BATCH)

    logger.info(f"=== {period_label} 完成: 成功{downloaded}, 失败{failed}, 跳过{skipped} ===")


def main():
    init_db()
    init_progress_table()
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:HH:mm:ss}</green> | <level>{level:7}</level> | <level>{message}</level>")
    logger.add(Path(__file__).parent / "batch_download.log", rotation="10 MB")

    start_time = time.time()

    # 1. 获取股票列表
    stocks = get_stock_list()
    if stocks.empty:
        return

    # 2. 先下载日线
    download_period(stocks, "daily")

    # 3. 再下载周线
    download_period(stocks, "weekly")

    # 4. 分钟级数据（2026年2月起）
    for minute_period in ("15", "30", "60"):
        download_minute_period(stocks, minute_period)

    elapsed = time.time() - start_time
    hours = int(elapsed // 3600)
    mins = int((elapsed % 3600) // 60)
    secs = int(elapsed % 60)
    logger.info(f"\n🎉 全部完成！耗时 {hours}h{mins}m{secs}s")


if __name__ == "__main__":
    main()

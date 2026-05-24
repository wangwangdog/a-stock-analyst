#!/usr/bin/env python3
"""
CR指标计算 & 入库脚本

计算逻辑（基于 stockstats 库）：
1. 从 stock_daily 表读取所有股票的日K线数据
2. 使用 stockstats 计算 CR 值及三条均线 (MA5/MA10/MA20)
3. 写入 stock_cr_indicator 表

CR 含义：中间价（(2*C+H+L)/4）的动量指标，衡量买卖力道
  - CR > 100: 买方力道偏强
  - CR < 100: 卖方力道偏强
  - MA1(5日)/MA2(10日)/MA3(20日) 为 CR 的移动平均线

用法：
    python calc_cr_indicator.py                   # 全市场增量更新
    python calc_cr_indicator.py 000001             # 单只股票
    python calc_cr_indicator.py --full             # 全市场全量重算
"""
import sys
import warnings
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd
import stockstats
from loguru import logger
from data.cache import _get_conn
from config import DB_PATH


def get_all_symbols(conn) -> list:
    """从 stock_daily 获取所有股票代码"""
    rows = conn.execute("SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def get_stock_kline(conn, symbol: str, min_rows: int = 60) -> pd.DataFrame:
    """读取某只股票的日 K 线（升序）"""
    df = pd.read_sql(
        "SELECT date, open, high, low, close, volume, turnover FROM stock_daily WHERE symbol=? ORDER BY date ASC",
        conn, params=(symbol,)
    )
    if len(df) < min_rows:
        return pd.DataFrame()
    for c in ['open','high','low','close','volume','turnover']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['date'] = pd.to_datetime(df['date'], format='mixed')
    df.set_index('date', inplace=True)
    return df


def calc_cr(symbol: str, conn) -> list:
    """计算某只股票的 CR 指标，返回要写入的行"""
    df = get_stock_kline(conn, symbol)
    if df.empty:
        return []

    try:
        sf = stockstats.StockDataFrame.retype(df)
        cr_values = sf['cr'].values
        cr_ma1 = sf['cr-ma1'].values
        cr_ma2 = sf['cr-ma2'].values
        cr_ma3 = sf['cr-ma3'].values

        dates = [d.strftime('%Y-%m-%d') for d in df.index]
        rows = []
        for i in range(len(dates)):
            if pd.isna(cr_values[i]):
                continue
            rows.append((
                symbol,
                dates[i],
                round(float(cr_values[i]), 4),
                round(float(cr_ma1[i]), 4) if not pd.isna(cr_ma1[i]) else None,
                round(float(cr_ma2[i]), 4) if not pd.isna(cr_ma2[i]) else None,
                round(float(cr_ma3[i]), 4) if not pd.isna(cr_ma3[i]) else None,
            ))
        return rows
    except Exception as e:
        logger.warning(f"[{symbol}] CR 计算失败: {e}")
        return []


def get_existing_dates(conn, symbol: str) -> set:
    """获取已存在的 CR 日期集合"""
    rows = conn.execute(
        "SELECT trade_date FROM stock_cr_indicator WHERE symbol=?", (symbol,)
    ).fetchall()
    return {r[0] for r in rows}


def save_cr(conn, rows: list, symbol: str):
    """批量写入 CR 数据"""
    if not rows:
        return 0

    existing = get_existing_dates(conn, symbol)
    new_rows = [r for r in rows if r[1] not in existing]

    if not new_rows:
        return 0

    conn.executemany(
        "INSERT OR IGNORE INTO stock_cr_indicator (symbol, trade_date, cr, cr_ma1, cr_ma2, cr_ma3) VALUES (?, ?, ?, ?, ?, ?)",
        new_rows
    )
    conn.commit()
    return len(new_rows)


def calc_and_save(symbol: str, conn, force_full: bool = False) -> int:
    """计算并保存单只股票的 CR 值，返回新增行数"""
    if not force_full:
        existing = get_existing_dates(conn, symbol)
        # 查看 stock_daily 最新日期
        latest = conn.execute(
            "SELECT MAX(date) FROM stock_daily WHERE symbol=?", (symbol,)
        ).fetchone()[0]
        if latest and latest in existing:
            return 0  # 已是最新，跳过

    rows = calc_cr(symbol, conn)
    return save_cr(conn, rows, symbol)


def run_all(force_full: bool = False, symbols: list = None):
    """全市场增量/全量重算"""
    conn = _get_conn()
    try:
        all_symbols = symbols if symbols else get_all_symbols(conn)
        total = len(all_symbols)
        inserted = 0
        skipped = 0

        logger.info(f"🚀 CR指标计算开始: {'全量' if force_full else '增量'} 共 {total} 只")

        for idx, symbol in enumerate(all_symbols, 1):
            n = calc_and_save(symbol, conn, force_full)
            inserted += n
            if n == 0:
                skipped += 1
            if idx % 500 == 0 or idx == total:
                logger.info(f"  进度 {idx}/{total} ({idx*100//total}%) | 已写入 {inserted} 条 | 跳过 {skipped} 只")

        logger.info(f"✅ CR指标计算完成: 共写入 {inserted} 条, 跳过 {skipped} 只")
    finally:
        conn.close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CR指标计算")
    parser.add_argument("symbol", nargs="?", default=None, help="股票代码（可选，默认全市场）")
    parser.add_argument("--full", action="store_true", help="全量重算")
    args = parser.parse_args()

    if args.symbol:
        conn = _get_conn()
        try:
            n = calc_and_save(args.symbol, conn, force_full=args.full)
            logger.info(f"[{args.symbol}] 写入 {n} 条 CR 数据")
        finally:
            conn.close()
    else:
        run_all(force_full=args.full)


if __name__ == "__main__":
    main()

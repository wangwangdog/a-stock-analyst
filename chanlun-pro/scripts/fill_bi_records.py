#!/usr/bin/env python3
"""
填充 stock_bi_records 表 — 多级别笔数据（日线/60分钟/30分钟/15分钟/5分钟）
支持自动清理旧数据，保留策略按级别配置。
同步提取买卖点写入 stock_mmd_records。

用法:
    python fill_bi_records.py                         # 全部级别
    python fill_bi_records.py --level 60min           # 只跑60分钟
    python fill_bi_records.py --symbol 000001         # 只跑指定股票
    python fill_bi_records.py --dry-run               # 仅打印不写入
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd
from chanlun.cl2 import CD
from chanlun.cl_utils import query_cl_chart_config
from chanlun.cl_interface import BI
from chanlun.utils.trading_calendar import get_calendar

# ── 配置 ──
DB = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")
TODAY = datetime.now().strftime("%Y-%m-%d")

# 级别 → (表名, kline_cache period, akshare period, 保留交易日数, 回溯天数)
LEVELS = {
    "day":   ("stock_bi_records",        "daily",  None,    None, 365),
    "60min": ("stock_bi_records_60min",  "60min",  "60",    100, 120),
    "30min": ("stock_bi_records_30min",  "30min",  "30",     50,  60),
    "15min": ("stock_bi_records_15min",  "15min",  "15",     30,  40),
    "5min":  ("stock_bi_records_5min",   "5min",  "5",      20,  30),
}

SYMBOLS_CACHE = None


def get_all_symbols() -> list:
    """获取全部 A 股代码"""
    global SYMBOLS_CACHE
    if SYMBOLS_CACHE is not None:
        return SYMBOLS_CACHE
    import sqlite3
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM stock_daily ORDER BY symbol"
        ).fetchall()
        SYMBOLS_CACHE = [r[0] for r in rows if len(r[0]) == 6]
    except Exception:
        try:
            rows = conn.execute(
                "SELECT symbol FROM all_stock_info ORDER BY symbol"
            ).fetchall()
            SYMBOLS_CACHE = [r[0] for r in rows if len(r[0]) == 6]
        except Exception:
            SYMBOLS_CACHE = []
    conn.close()
    return SYMBOLS_CACHE


def get_klines(symbol: str, level: str, lookback_days: int) -> pd.DataFrame:
    """从 kline_cache 或 stock_daily 读取对应级别的 K 线数据。"""
    import sqlite3
    conn = sqlite3.connect(DB)
    try:
        if level == "day":
            rows = conn.execute(
                "SELECT date, open, high, low, close, volume, turnover FROM stock_daily "
                "WHERE symbol=? ORDER BY date", (symbol,)
            ).fetchall()
            if rows:
                df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "turnover"])
                df["date"] = pd.to_datetime(df["date"])
                return df

        # 分钟级别
        period = LEVELS[level][1]
        if period is None:
            conn.close()
            return None

        end = TODAY
        cal = get_calendar()
        dates = cal.get_trading_days_between(
            (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y-%m-%d"), end
        )
        start = dates[0] if dates else (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y-%m-%d")

        rows = conn.execute(
            "SELECT trade_date, open, close, high, low, volume, amount "
            "FROM kline_cache WHERE symbol=? AND period=? AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date ASC",
            (symbol, period, start, end)
        ).fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["trade_date", "open", "close", "high", "low", "volume", "amount"])
            df.rename(columns={"trade_date": "date"}, inplace=True)
            df["date"] = pd.to_datetime(df["date"])
            return df
    except Exception as e:
        print(f"  ⚠ kline_cache 读取失败 {symbol}/{level}: {e}", file=sys.stderr)
    finally:
        conn.close()
    return None


def fetch_and_save_klines(symbol: str, level: str, lookback_days: int) -> pd.DataFrame:
    """从 AKShare 拉取分钟级数据并存入 kline_cache。"""
    if level == "day":
        return None
    ak_period = LEVELS[level][2]
    if ak_period is None:
        return None

    cal = get_calendar()
    end_date = TODAY
    dates = cal.get_trading_days_between(
        (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y-%m-%d"), end_date
    )
    start_date = dates[0] if dates else (datetime.now() - timedelta(days=lookback_days * 2)).strftime("%Y-%m-%d")

    try:
        from a_stock_backend.data.akshare_fetcher import get_minute_kline
        df = get_minute_kline(symbol, ak_period, start_date, end_date)
        if df is not None and not df.empty:
            period_str = LEVELS[level][1]
            _save_to_kline_cache(symbol, period_str, df)
            df.rename(columns={"trade_date": "date"}, inplace=True)
            df["date"] = pd.to_datetime(df["date"])
            return df
    except ImportError:
        pass
    except Exception as e:
        print(f"  ⚠ AKShare 获取失败 {symbol}/{level}: {e}", file=sys.stderr)
    return None


def _save_to_kline_cache(symbol: str, period: str, df: pd.DataFrame):
    """将 AKShare 返回的分钟级数据存入 kline_cache"""
    import sqlite3
    conn = sqlite3.connect(DB)
    try:
        td_col = "trade_date"
        if td_col not in df.columns:
            for alt in ["时间", "date"]:
                if alt in df.columns:
                    df[td_col] = df[alt].astype(str)
                    break
            else:
                return
        for _, row in df.iterrows():
            conn.execute(
                """INSERT OR REPLACE INTO kline_cache
                   (symbol, source, period, trade_date, open, close, high, low, volume, amount)
                   VALUES (?, 'akshare', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, period, str(row[td_col]),
                 float(row.get("open", 0)), float(row.get("close", 0)),
                 float(row.get("high", 0)), float(row.get("low", 0)),
                 float(row.get("volume", 0) or 0), float(row.get("amount", 0) or 0))
            )
        conn.commit()
    except Exception as e:
        print(f"  ⚠ 写入 kline_cache 失败: {e}", file=sys.stderr)
    finally:
        conn.close()


def purge_old_data(table: str, keep_days: int):
    """删除指定表中超过 keep_days 个交易日的数据。"""
    if keep_days is None:
        return
    cal = get_calendar()
    today = TODAY
    trading_days = cal.get_trading_days_between(
        (datetime.now() - timedelta(days=keep_days * 3)).strftime("%Y-%m-%d"), today
    )
    keep_dates = set(trading_days[-keep_days:]) if len(trading_days) > keep_days else set(trading_days)
    if not keep_dates:
        return

    import sqlite3
    conn = sqlite3.connect(DB)
    try:
        cursor = conn.execute(f"SELECT DISTINCT analysis_date FROM {table} ORDER BY analysis_date")
        all_dates = [r[0] for r in cursor.fetchall()]
        to_purge = [d for d in all_dates if d not in keep_dates]
        if to_purge:
            batch_size = 50
            for i in range(0, len(to_purge), batch_size):
                batch = to_purge[i:i + batch_size]
                placeholders = ",".join(["?"] * len(batch))
                conn.execute(f"DELETE FROM {table} WHERE analysis_date IN ({placeholders})", batch)
            conn.commit()
            print(f"  🗑 清理 {table}: 删除 {len(to_purge)} 个交易日数据 ({len(all_dates)}→{len(keep_dates)})")
    except Exception as e:
        print(f"  ⚠ 清理 {table} 失败: {e}", file=sys.stderr)
    finally:
        conn.close()


def purge_mmd_old_data(keep_days: int = 120):
    """删除 stock_mmd_records 中超过 keep_days 个交易日的数据"""
    cal = get_calendar()
    today = TODAY
    trading_days = cal.get_trading_days_between(
        (datetime.now() - timedelta(days=keep_days * 2)).strftime("%Y-%m-%d"), today
    )
    keep_dates = set(trading_days[-keep_days:]) if len(trading_days) > keep_days else set(trading_days)
    if not keep_dates:
        return
    import sqlite3
    conn = sqlite3.connect(DB)
    try:
        cursor = conn.execute("SELECT DISTINCT analysis_date FROM stock_mmd_records ORDER BY analysis_date")
        all_dates = [r[0] for r in cursor.fetchall()]
        to_purge = [d for d in all_dates if d not in keep_dates]
        if to_purge:
            batch_size = 50
            for i in range(0, len(to_purge), batch_size):
                batch = to_purge[i:i + batch_size]
                placeholders = ",".join(["?"] * len(batch))
                conn.execute(f"DELETE FROM stock_mmd_records WHERE analysis_date IN ({placeholders})", batch)
            conn.commit()
            print(f"  🗑 清理 stock_mmd_records: 删除 {len(to_purge)} 个交易日数据")
    except Exception as e:
        print(f"  ⚠ 清理 stock_mmd_records 失败: {e}", file=sys.stderr)
    finally:
        conn.close()


def _save_mmds(symbol: str, mmds: list):
    """批量写入买卖点记录到 stock_mmd_records"""
    import sqlite3
    conn = sqlite3.connect(DB)
    try:
        conn.execute(
            "DELETE FROM stock_mmd_records WHERE symbol=? AND analysis_date=?",
            (symbol, TODAY)
        )
        for m in mmds:
            conn.execute(
                """INSERT OR REPLACE INTO stock_mmd_records
                (symbol, market, mmd_name, source_level,
                 point_time, point_price,
                 bi_index, bi_direction, bi_start_time,
                 zs_index, zs_zg, zs_zd,
                 msg, analysis_date)
                VALUES (?,?,?,?, ?,?, ?,?,?, ?,?,?, ?,?)""",
                (
                    symbol, "a", m['mmd_name'], m['source_level'],
                    m['point_time'], m['point_price'],
                    m['bi_index'], m['bi_direction'], m['bi_start_time'],
                    m['zs_index'], m['zs_zg'], m['zs_zd'],
                    m['msg'], m['analysis_date'],
                )
            )
        conn.commit()
    except Exception as e:
        print(f"  ⚠ 写入 MMD 失败 {symbol}: {e}", file=sys.stderr)
    finally:
        conn.close()


def fill_one_stock(symbol: str, level: str, dry_run: bool = False):
    """
    计算一只股票一个级别的笔，写入对应表。
    同时提取买卖点写入 stock_mmd_records。
    """
    table_name, period, ak_period, keep_days, lookback_days = LEVELS[level]

    # 1. 获取K线
    df = get_klines(symbol, level, lookback_days)
    if df is None or df.empty:
        if level != "day":
            print(f"  📥 {symbol} {level}: 拉取 AKShare 分钟数据...")
            df = fetch_and_save_klines(symbol, level, lookback_days)
        if df is None or df.empty:
            print(f"  ⏭ {symbol} {level}: 无数据")
            return

    # 2. 检查数据量
    min_bars = {"day": 50, "60min": 100, "30min": 100, "15min": 100, "5min": 50}
    if len(df) < min_bars.get(level, 50):
        print(f"  ⏭ {symbol} {level}: 数据不足 ({len(df)} < {min_bars.get(level, 50)})")
        return

    # 3. 缠论计算
    config = query_cl_chart_config("a", symbol)
    cd = CD(symbol, level, config)
    cd.process_klines(df)

    bis = cd.get_bis()
    zss = cd.get_bi_zss()
    idx = cd.get_idx()
    macd = idx.get("macd", {})
    zs_by_idx = {z.index: z for z in zss}

    if not bis:
        print(f"  ⏭ {symbol} {level}: 无笔数据")
        return

    # 4. 写入 BI 表 + 收集 MMD
    import sqlite3
    conn = sqlite3.connect(DB)
    if not dry_run:
        conn.execute(f"DELETE FROM {table_name} WHERE symbol=? AND analysis_date=?", (symbol, TODAY))

    bi_inserted = 0
    all_mmds = []

    for b in bis:
        rel_zs_ids = []
        for z in zss:
            if b in z.lines:
                rel_zs_ids.append(z.index)

        change_pct = ((b.end.val - b.start.val) / b.start.val) * 100 if b.start.val else 0

        si = b.start.k.k_index
        ei = b.end.k.k_index
        if si >= 0 and ei >= 0 and si < len(df) and ei < len(df):
            if si > ei:
                si, ei = ei, si
            vol_range = df.iloc[si: ei + 1]
            vol_total = vol_range.get("volume", pd.Series([0])).sum() if "volume" in vol_range else 0
        else:
            vol_total = 0

        macd_idx = min(ei, len(macd.get("hist", [])) - 1) if ei >= 0 else -1
        macd_hist = macd["hist"][macd_idx] if macd_idx >= 0 and macd.get("hist") else None
        macd_dif = macd["dif"][macd_idx] if macd_idx >= 0 and macd.get("dif") else None
        macd_dea = macd["dea"][macd_idx] if macd_idx >= 0 and macd.get("dea") else None

        trend_type = None
        if rel_zs_ids:
            first_zs = zs_by_idx.get(rel_zs_ids[0])
            if first_zs:
                trend_type = getattr(first_zs, "trend_type", None)

        mmds = b.line_mmds("|") if hasattr(b, "line_mmds") else None
        bcs = b.line_bcs("|") if hasattr(b, "line_bcs") else None
        jiaodu = b.jiaodu() if hasattr(b, "jiaodu") else None
        is_done = 1 if b.is_done() else 0
        start_time = str(b.start.k.date) if hasattr(b.start.k, 'date') else str(b.start.k)
        end_time = str(b.end.k.date) if hasattr(b.end.k, 'date') else str(b.end.k)

        if not dry_run:
            conn.execute(
                f"""INSERT OR REPLACE INTO {table_name}
                (symbol, market, bi_index, direction,
                 start_time, end_time, start_price, end_price,
                 high, low, change_pct,
                 macd_dif, macd_dea, macd_hist, volume_total, jiaodu,
                 is_done, line_mmds, line_bcs,
                 zs_ids, trend_type, analysis_date)
                VALUES (?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?,?,?, ?,?,?, ?,?,?)""",
                (symbol, "a", b.index, b.type,
                 start_time, end_time, b.start.val, b.end.val,
                 b.high, b.low, change_pct,
                 macd_dif, macd_dea, macd_hist, vol_total, jiaodu,
                 is_done,
                 json.dumps(mmds, ensure_ascii=False) if mmds else None,
                 json.dumps(bcs, ensure_ascii=False) if bcs else None,
                 json.dumps(rel_zs_ids) if rel_zs_ids else None,
                 trend_type, TODAY),
            )
        bi_inserted += 1

        # 提取笔上附着的买卖点对象
        if hasattr(b, 'get_mmds'):
            bi_mmd_objects = b.get_mmds("|")
            for m_obj in bi_mmd_objects:
                if not hasattr(m_obj, 'name') or not m_obj.name:
                    continue
                m_zs = getattr(m_obj, 'zs', None)
                zs_idx = getattr(m_zs, 'index', None) if m_zs else None
                zs_zg = getattr(m_zs, 'zg', None) if m_zs else None
                zs_zd = getattr(m_zs, 'zd', None) if m_zs else None
                msg = getattr(m_obj, 'msg', '')

                all_mmds.append({
                    'mmd_name': m_obj.name,
                    'source_level': level,
                    'point_time': end_time,        # 笔结束时刻，精确到秒
                    'point_price': b.end.val,      # 笔结束价格
                    'bi_index': b.index,
                    'bi_direction': b.type,
                    'bi_start_time': start_time,
                    'zs_index': zs_idx,
                    'zs_zg': zs_zg,
                    'zs_zd': zs_zd,
                    'msg': msg,
                    'analysis_date': TODAY,
                })

    if not dry_run:
        conn.commit()
    conn.close()

    # 5. 写入买卖点表
    if all_mmds:
        if not dry_run:
            _save_mmds(symbol, all_mmds)
        mmd_types = sorted(set(m['mmd_name'] for m in all_mmds))
        print(f"  {'🔍' if dry_run else '✅'} {symbol} {level}: {bi_inserted} 笔, {len(zss)} 中枢, {len(all_mmds)} 买卖点 [{', '.join(mmd_types)}]")
    else:
        print(f"  {'🔍' if dry_run else '✅'} {symbol} {level}: {bi_inserted} 笔, {len(zss)} 中枢, 无买卖点")

    # 6. 后清理
    if keep_days and not dry_run:
        purge_old_data(table_name, keep_days)


def run_level(level: str, symbols: list = None, dry_run: bool = False):
    """运行一个级别的填充"""
    if level not in LEVELS:
        print(f"❌ 不支持的级别: {level}，可选: {list(LEVELS.keys())}")
        return

    if symbols is None:
        symbols = get_all_symbols()

    table_name = LEVELS[level][0]
    print(f"\n{'='*60}")
    print(f"📊 {level} → {table_name} (目标 {len(symbols)} 只)")
    print(f"{'='*60}")

    count = 0
    errors = []
    for i, sym in enumerate(symbols):
        if not sym or len(sym) != 6:
            continue
        try:
            fill_one_stock(sym, level, dry_run)
            count += 1
            if count % 200 == 0:
                print(f"  [{datetime.now().strftime('%H:%M:%S')}] 进度: {count}/{len(symbols)}")
        except Exception as e:
            errors.append((sym, str(e)))
            print(f"  ❌ {sym} {level}: {e}", file=sys.stderr)

    keep_days = LEVELS[level][3]
    if keep_days and not dry_run and level != "day":
        purge_old_data(table_name, keep_days)

    if errors:
        print(f"\n⚠ 错误汇总 ({len(errors)}):")
        for sym, err in errors[:10]:
            print(f"  {sym}: {err}")
        if len(errors) > 10:
            print(f"  ... 还有 {len(errors) - 10} 个错误")

    return count


def main():
    parser = argparse.ArgumentParser(description="填充多级别笔+买卖点数据")
    parser.add_argument("--level", choices=list(LEVELS.keys()), help="只跑指定级别")
    parser.add_argument("--symbol", help="只跑指定股票代码")
    parser.add_argument("--dry-run", action="store_true", help="仅打印不写入")
    parser.add_argument("--sample", type=int, default=0, help="测试模式：只跑前 N 只")
    parser.add_argument("--purge-only", action="store_true", help="只做数据清理")
    args = parser.parse_args()

    if args.purge_only:
        print("🧹 数据清理模式")
        for lv, (tbl, *_) in LEVELS.items():
            kd = LEVELS[lv][3]
            if kd:
                purge_old_data(tbl, kd)
        purge_mmd_old_data()
        print("🧹 清理完成")
        return

    symbols = None
    if args.symbol:
        symbols = [args.symbol]
    else:
        all_syms = get_all_symbols()
        if args.sample > 0:
            symbols = all_syms[:args.sample]

    levels = [args.level] if args.level else list(LEVELS.keys())

    print(f"🚀 多级别笔+买卖点填充 {TODAY}")
    if args.dry_run:
        print("🔍 DRY RUN 模式：不会写入数据库")
    if args.sample:
        print(f"🧪 测试模式：每级别只跑前 {args.sample} 只")

    total_ops = 0
    for lv in levels:
        n = run_level(lv, symbols, args.dry_run)
        if n:
            total_ops += n

    # 跑完所有级别后清理 MMD 旧数据
    if not args.dry_run:
        purge_mmd_old_data()

    print(f"\n{'='*60}")
    print(f"🏁 完成! 共处理 {total_ops} 次操作")


if __name__ == "__main__":
    main()

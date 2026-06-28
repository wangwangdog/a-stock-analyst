"""数据采集器 — 补齐缺失的4类数据

用法:
    python data_collector.py --min-kline           # 采集关注池前5日1分钟K线
    python data_collector.py --concepts            # 采集概念板块 + 个股映射
    python data_collector.py --zt-pool             # 采集昨日涨停/跌停池
    data_collector.py --realtime          # 采集一次实时快照
    python data_collector.py --init-db             # 初始化缺失的表
    python data_collector.py --all                 # 执行全部（盘前任务）

依赖:
    pip install akshare -U
"""

import argparse
import logging
import sqlite3
import os
import sys
import time
import socket as _socket
from datetime import datetime, timedelta, date
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('data_collector')

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"


def _get_conn():
    return sqlite3.connect(DB_PATH)


def _force_ipv4():
    """强制 socket 走 IPv4（避免 AKShare IPv6 被封）"""
    orig = _socket.getaddrinfo
    def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig(host, port, _socket.AF_INET, type, proto, flags)
    _socket.getaddrinfo = _ipv4


# ============================================================
# 0. 初始化缺失的表
# ============================================================

INIT_SQL = """
-- 5分钟K线
CREATE TABLE IF NOT EXISTS stock_kline_5min (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    amount REAL,
    PRIMARY KEY (symbol, date)
);

-- 实时快照（盘中写入）
CREATE TABLE IF NOT EXISTS realtime_snapshot (
    snap_time TEXT NOT NULL,
    snap_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    price REAL,
    pre_close REAL,
    pct REAL,
    volume INTEGER,
    turnover REAL,
    bid1 REAL,
    bid1_vol INTEGER,
    ask1 REAL,
    ask1_vol INTEGER,
    zt_price REAL,
    dt_price REAL,
    is_limit_up INTEGER DEFAULT 0,
    is_limit_down INTEGER DEFAULT 0,
    PRIMARY KEY (snap_date, snap_time, symbol)
);

-- 盘中情绪快照（每5分钟）
CREATE TABLE IF NOT EXISTS sentiment_snapshot (
    snap_date TEXT NOT NULL,
    snap_time TEXT NOT NULL,
    zt_count INTEGER,
    dt_count INTEGER,
    zb_count INTEGER,
    up_5_count INTEGER,
    down_5_count INTEGER,
    total_watch INTEGER,
    max_lb_height INTEGER DEFAULT 0,
    sentiment_score REAL DEFAULT 0,
    sentiment_phase TEXT DEFAULT '',
    PRIMARY KEY (snap_date, snap_time)
);
"""


def init_missing_tables():
    """初始化所有缺失的表"""
    conn = _get_conn()
    try:
        for stmt in INIT_SQL.split(';'):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()
        logger.info("✅ 缺失表初始化完成")
    except Exception as e:
        logger.error(f"❌ 表初始化失败: {e}")
    finally:
        conn.close()


# ============================================================
# 1. 采集关注池1分钟K线
# ============================================================

def get_watch_list() -> list:
    """从数据库获取关注池列表"""
    conn = _get_conn()
    try:
        symbols = set()
        # 从 cl_zixuan_watchlist
        rows = conn.execute(
            "SELECT DISTINCT stock_code FROM cl_zixuan_watchlist WHERE stock_code != ''"
        ).fetchall()
        for (sym,) in rows:
            sym = sym.strip()
            if sym.startswith(('SH.', 'SZ.')):
                sym = sym[3:]
            if sym.isdigit() and len(sym) == 6:
                symbols.add(sym)

        # 从 favorites
        favs = conn.execute(
            "SELECT symbol FROM favorites LIMIT 50"
        ).fetchall()
        for (sym,) in favs:
            if sym and sym.isdigit() and len(sym) == 6:
                symbols.add(sym)

        return sorted(symbols)
    except Exception as e:
        logger.warning(f"获取关注池失败: {e}")
        return ['000001', '000002', '000858', '002415', '300750']
    finally:
        conn.close()


def download_1min_klines(symbols: list, days: int = 5):
    """下载关注池前 N 日的1分钟K线"""
    import akshare as ak

    _force_ipv4()
    today = date.today()
    end_date = today.strftime("%Y-%m-%d")
    start_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")

    conn = _get_conn()
    inserted = 0
    failed = 0

    try:
        for code in symbols:
            for retry in range(3):
                try:
                    df = ak.stock_zh_a_hist_min_em(
                        symbol=code,
                        period="1",
                        start_date=start_date,
                        end_date=end_date,
                        adjust=""
                    )
                    if df is None or df.empty:
                        logger.warning(f"  ⚠️ {code}: 无1分钟K线数据")
                        failed += 1
                        break

                    # 写入 stock_kline_1min
                    for _, row in df.iterrows():
                        time_str = str(row['时间'])
                        o = float(row['开盘'])
                        h = float(row['最高'])
                        l = float(row['最低'])
                        c = float(row['收盘'])
                        v = int(row['成交量'])
                        a = float(row['成交额'])

                        conn.execute(
                            """INSERT OR REPLACE INTO stock_kline_1min
                               (symbol, date, open, high, low, close, volume, amount)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (code, time_str, o, h, l, c, v, a)
                        )
                    conn.commit()
                    inserted += len(df)
                    logger.info(f"  ✅ {code}: 写入 {len(df)} 条1分钟K线")
                    break
                except Exception as e:
                    if retry < 2:
                        logger.warning(f"  ⚠️ {code} 重试 {retry+1}: {e}")
                        time.sleep(2)
                    else:
                        logger.error(f"  ❌ {code}: {e}")
                        failed += 1
            time.sleep(1.5)  # 防反爬
    except Exception as e:
        logger.error(f"采集1分钟K线失败: {e}")
    finally:
        conn.close()

    logger.info(f"📊 1分钟K线采集完成: 成功 {inserted} 条, 失败 {failed} 只")
    return {"inserted": inserted, "failed": failed}


# ============================================================
# 2. 采集概念板块 + 个股映射
# ============================================================

def collect_concepts():
    """采集全市场概念板块及其成分股"""
    import akshare as ak

    _force_ipv4()

    conn = _get_conn()
    boards_collected = 0
    maps_collected = 0

    try:
        # 2.1 获取所有概念板块列表
        logger.info("📦 获取概念板块列表...")
        df_board = ak.stock_board_concept_name_em()
        if df_board is None or df_board.empty:
            logger.error("❌ 无法获取概念板块列表")
            return {"boards": 0, "maps": 0}

        # 写入 stock_concepts
        for _, row in df_board.iterrows():
            code = row.get('概念代码', '') or str(row.get('代码', ''))
            name = row.get('概念名称', '') or str(row.get('名称', ''))
            conn.execute(
                "INSERT OR REPLACE INTO stock_concepts (code, name, category) VALUES (?, ?, '概念')",
                (code, name)
            )
        conn.commit()
        boards_collected = len(df_board)
        logger.info(f"  ✅ 写入 {boards_collected} 个概念板块")

        # 2.2 遍历板块获取成分股（最多100个，防止请求过多）
        concept_codes = df_board['概念代码'].tolist() if '概念代码' in df_board.columns else df_board.iloc[:, 0].tolist()
        for idx, code in enumerate(concept_codes[:100]):
            name = ""
            try:
                row = conn.execute(
                    "SELECT name FROM stock_concepts WHERE code=? LIMIT 1", (code,)
                ).fetchone()
                if row:
                    name = row[0]
            except Exception:
                pass

            for retry in range(3):
                try:
                    df_cons = ak.stock_board_concept_cons_em(symbol=code)
                    if df_cons is not None and not df_cons.empty:
                        for _, row2 in df_cons.iterrows():
                            symbol = str(row2.get('代码', ''))
                            cons_name = row2.get('名称', '')
                            conn.execute(
                                """INSERT OR REPLACE INTO stock_concept_map
                                   (symbol, name, concept_code, concept_name)
                                   VALUES (?, ?, ?, ?)""",
                                (symbol, cons_name, code, name)
                            )
                            maps_collected += 1
                    conn.commit()
                    logger.info(f"  ✅ [{idx+1}/{len(concept_codes)}] {code} {name}: {maps_collected if maps_collected else 0} 条")
                    break
                except Exception as e:
                    if retry < 2:
                        time.sleep(2)
                    else:
                        logger.warning(f"  ⚠️ {code}: {e}")
            time.sleep(1.5)

        logger.info(f"📊 概念采集完成: {boards_collected} 板块, {maps_collected} 个股映射")
    except Exception as e:
        logger.error(f"❌ 概念采集失败: {e}")
    finally:
        conn.close()

    return {"boards": boards_collected, "maps": maps_collected}


# ============================================================
# 3. 采集涨停/跌停池
# ============================================================

def collect_zt_pools(trade_date: str = None):
    """采集指定日期的涨停/跌停池"""
    import akshare as ak

    _force_ipv4()

    if not trade_date:
        trade_date = (date.today() - timedelta(days=1)).strftime("%Y%m%d")

    conn = _get_conn()
    result = {"zt": 0, "dt": 0}

    try:
        # 3.1 涨停池
        logger.info(f"📈 采集涨停池: {trade_date}")
        df_zt = ak.stock_zt_pool_em(date=trade_date)
        if df_zt is not None and not df_zt.empty:
            for _, row in df_zt.iterrows():
                code = str(row.get('代码', ''))
                name = row.get('名称', '')
                price = float(row.get('最新价', 0))
                zt_price = float(row.get('涨停价', 0))
                fd = float(row.get('封板资金', 0))
                lb = int(row.get('连板数', 0))
                concept = row.get('所属概念', '')
                is_zb = 1 if row.get('最后封板时间', '') == '09:25:00' else 0

                conn.execute(
                    """INSERT OR REPLACE INTO zt_pool
                       (date, symbol, name, close_price, zt_price, fd_amount, lb_count, concept, is_zb)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (trade_date, code, name, price, zt_price, fd, lb, concept, is_zb)
                )
            conn.commit()
            result["zt"] = len(df_zt)
            logger.info(f"  ✅ 涨停 {len(df_zt)} 只")

        # 3.2 跌停池
        logger.info(f"📉 采集跌停池: {trade_date}")
        try:
            df_dt = ak.stock_zt_pool_dtgc_em(date=trade_date)
            if df_dt is not None and not df_dt.empty:
                for _, row in df_dt.iterrows():
                    code = str(row.get('代码', ''))
                    name = row.get('名称', '')
                    price = float(row.get('最新价', 0))
                    dt_price = float(row.get('跌停价', price * 0.9))

                    conn.execute(
                        """INSERT OR REPLACE INTO zt_pool_dt
                           (date, symbol, name, close_price, dt_price)
                           VALUES (?, ?, ?, ?, ?)""",
                        (trade_date, code, name, price, dt_price)
                    )
                conn.commit()
                result["dt"] = len(df_dt)
                logger.info(f"  ✅ 跌停 {len(df_dt)} 只")
            else:
                logger.info("  ⚠️ 跌停池为空（无跌停或非交易日）")
        except Exception as e:
            logger.warning(f"  ⚠️ 跌停池采集失败: {e}")

    except Exception as e:
        logger.error(f"❌ 涨停池采集失败: {e}")
    finally:
        conn.close()

    return result


# ============================================================
# 4. 采集盘中实时快照
# ============================================================

def collect_realtime_snapshot(codes: list = None):
    """采集一次实时快照（腾讯接口）写入 realtime_snapshot 表"""
    import urllib.request

    now = datetime.now()
    snap_time = now.strftime("%H:%M:%S")
    snap_date = now.strftime("%Y-%m-%d")

    if not codes:
        codes = get_watch_list()[:50]  # 最多50只

    # 加前缀
    prefixed = []
    for c in codes:
        c = c.strip()
        if c.startswith(('6', '9')):
            prefixed.append(f"sh{c}")
        else:
            prefixed.append(f"sz{c}")

    if not prefixed:
        logger.warning("⚠️ 无关注池数据，使用默认股票")
        prefixed = ["sh600000", "sz000001", "sz300750"]

    url = "http://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})

    conn = _get_conn()
    written = 0

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk")

        for line in raw.strip().split(";"):
            if not line or "=" not in line:
                continue
            parts = line.split("=")
            if len(parts) < 2:
                continue
            fields = parts[1].strip('"').split("~")
            if len(fields) < 35:
                continue
            try:
                code = fields[2]
                name = fields[1]
                price = float(fields[3]) if fields[3] else 0
                pre_close = float(fields[4]) if fields[4] else 0
                open_p = float(fields[5]) if fields[5] else 0
                volume = int(fields[6]) if fields[6] else 0
                turnover = float(fields[37]) if fields[37] else 0
                high = float(fields[33]) if fields[33] else 0
                low = float(fields[34]) if fields[34] else 0
                # 腾讯字段：买一=fields[9],买一量=fields[10],卖一=fields[19],卖一量=fields[20]
                bid1 = float(fields[9]) if fields[9] else 0
                bid1_vol = int(fields[10]) if fields[10] else 0
                ask1 = float(fields[19]) if fields[19] else 0
                ask1_vol = int(fields[20]) if fields[20] else 0

                pct = round((price / pre_close - 1) * 100, 2) if pre_close else 0
                zt_price = round(pre_close * 1.1, 2)
                dt_price = round(pre_close * 0.9, 2)
                is_limit_up = 1 if price >= zt_price else 0
                is_limit_down = 1 if price <= dt_price else 0

                conn.execute(
                    """INSERT OR REPLACE INTO realtime_snapshot
                       (snap_time, snap_date, symbol, name, price, pre_close, pct,
                        volume, turnover, bid1, bid1_vol, ask1, ask1_vol,
                        zt_price, dt_price, is_limit_up, is_limit_down)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (snap_time, snap_date, code, name, price, pre_close, pct,
                     volume, turnover, bid1, bid1_vol, ask1, ask1_vol,
                     zt_price, dt_price, is_limit_up, is_limit_down)
                )
                written += 1
            except (ValueError, IndexError) as e:
                continue

        conn.commit()
        logger.info(f"✅ 实时快照写入: {written} 只 (时间: {snap_time})")
    except Exception as e:
        logger.error(f"❌ 实时快照采集失败: {e}")
    finally:
        conn.close()

    return {"written": written, "time": snap_time}


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="数据采集器 — 补齐4类缺失数据")
    parser.add_argument("--init-db", action="store_true", help="初始化缺失的表")
    parser.add_argument("--min-kline", action="store_true", help="采集关注池1分钟K线")
    parser.add_argument("--concepts", action="store_true", help="采集概念板块+个股映射")
    parser.add_argument("--zt-pool", action="store_true", help="采集涨停/跌停池")
    parser.add_argument("--realtime", action="store_true", help="采集一次实时快照")
    parser.add_argument("--all", action="store_true", help="执行全部（盘前任务）")
    parser.add_argument("--date", type=str, default=None, help="指定交易日期 YYYYMMDD")

    args = parser.parse_args()

    if args.init_db or args.all:
        init_missing_tables()

    if args.zt_pool or args.all:
        logger.info("=" * 50)
        logger.info("📈 采集涨停/跌停池...")
        collect_zt_pools(args.date)

    if args.concepts or args.all:
        logger.info("=" * 50)
        logger.info("📦 采集概念板块...")
        collect_concepts()

    if args.min_kline or args.all:
        logger.info("=" * 50)
        logger.info("📊 采集1分钟K线...")
        symbols = get_watch_list()
        logger.info(f"   关注池: {len(symbols)} 只")
        download_1min_klines(symbols)

    if args.realtime:
        logger.info("=" * 50)
        logger.info("📡 采集实时快照...")
        collect_realtime_snapshot()

    if not any([args.init_db, args.zt_pool, args.concepts, args.min_kline, args.realtime, args.all]):
        parser.print_help()

    logger.info("=" * 50)
    logger.info("✅ 全部任务完成")


if __name__ == "__main__":
    main()

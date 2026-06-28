"""
数据准备模块 — 采集缺失数据并建立新表

缺失数据清单：
1. 涨停池 (zt_pool / zt_pool_dt) — AKShare stock_zt_pool_em / stock_zt_pool_dt_em
2. 概念板块 (stock_concepts) — AKShare stock_board_concept_name_em + 个股概念映射
3. 盘中实时行情快照 (realtime_snapshot) — 腾讯接口 qt.gtimg.cn 轮询写入
4. 个股概念映射 (stock_concept_map) — AKShare stock_board_concept_cons_em

用法:
    python data_prepare.py --zt-pool           # 采集昨日涨停池
    python data_prepare.py --concepts          # 采集全市场概念板块
    python data_prepare.py --realtime          # 采集一次盘中实时快照
    python data_prepare.py --init-db           # 初始化新表
"""
import argparse
import sys
import logging
import sqlite3
import os
import json
import urllib.request
import time
from datetime import datetime, timedelta, date

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('data_prepare')

DB_PATH = "/mnt/disk990g/sqlite-data/chanlun_klines.sqlite"
AKSHARE_TIMEOUT = 30


def _get_conn():
    return sqlite3.connect(DB_PATH)


def _force_ipv4():
    """强制 socket 走 IPv4（避免 AKShare/Tencent IPv6 被拒）"""
    import socket
    orig = socket.getaddrinfo
    def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return orig(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _ipv4


# ============================================================
# 1. 初始化新表
# ============================================================

INIT_SQL = """
-- 涨停池（盘前采集）
CREATE TABLE IF NOT EXISTS zt_pool (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    close_price REAL,
    zt_price REAL,
    fd_amount REAL,          -- 封单额（元）
    lb_count INTEGER,        -- 连板数
    concept TEXT,            -- 所属概念（逗号分隔）
    is_zb INTEGER DEFAULT 0, -- 是否炸板
    PRIMARY KEY (date, symbol)
);

-- 跌停池
CREATE TABLE IF NOT EXISTS zt_pool_dt (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT,
    close_price REAL,
    dt_price REAL,
    PRIMARY KEY (date, symbol)
);

-- 概念板块
CREATE TABLE IF NOT EXISTS stock_concepts (
    code TEXT PRIMARY KEY,      -- 概念代码（如 BK0999）
    name TEXT NOT NULL,         -- 概念名称
    category TEXT DEFAULT ''     -- 分类（行业/概念/地域）
);

-- 个股概念映射
CREATE TABLE IF NOT EXISTS stock_concept_map (
    symbol TEXT NOT NULL,        -- 股票代码（000001）
    name TEXT,
    concept_code TEXT NOT NULL,  -- 概念代码
    concept_name TEXT,           -- 概念名称
    PRIMARY KEY (symbol, concept_code)
);

-- 盘中实时快照（腾讯接口写入）
CREATE TABLE IF NOT EXISTS realtime_snapshot (
    snap_time TEXT NOT NULL,     -- HH:MM:SS
    snap_date TEXT NOT NULL,     -- YYYY-MM-DD
    symbol TEXT NOT NULL,
    name TEXT,
    price REAL,
    pre_close REAL,
    pct REAL,
    volume INTEGER,
    high REAL,
    low REAL,
    bid1 REAL,
    bid1_vol INTEGER,
    ask1 REAL,
    ask1_vol INTEGER,
    zt_price REAL,
    dt_price REAL,
    PRIMARY KEY (snap_date, snap_time, symbol)
);
"""


def init_db():
    conn = _get_conn()
    conn.executescript(INIT_SQL)
    conn.commit()
    conn.close()
    logger.info("✅ 新表初始化完成：zt_pool, zt_pool_dt, stock_concepts, stock_concept_map, realtime_snapshot")


# ============================================================
# 2. 涨停池采集（AKShare）
# ============================================================

def collect_zt_pool(target_date: str = None):
    """采集指定日期的涨停/跌停池"""
    if target_date is None:
        target_date = (date.today() - timedelta(1)).strftime("%Y%m%d")  # 默认为昨日

    _force_ipv4()
    try:
        import akshare as ak
        logger.info(f"📡 采集涨停池: {target_date}")

        # 涨停池
        try:
            df = ak.stock_zt_pool_em(date=target_date)
            conn = _get_conn()
            count = 0
            for _, row in df.iterrows():
                symbol = str(row.get("代码", "")).strip().zfill(6)
                if not symbol:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO zt_pool
                       (date, symbol, name, close_price, zt_price, fd_amount, lb_count, concept, is_zb)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
                        symbol,
                        row.get("名称", ""),
                        float(row.get("最新价", 0)),
                        float(row.get("涨停价", 0)),
                        float(row.get("封单额", 0)),
                        int(row.get("连板数", 0)) if "连板数" in row else 0,
                        row.get("所属概念", ""),
                        1 if row.get("炸板", "") == "炸板" else 0,
                    ),
                )
                count += 1
            conn.commit()
            logger.info(f"✅ 涨停池写入 {count} 条")
        except Exception as e:
            logger.warning(f"涨停池采集失败: {e}")

        # 跌停池
        try:
            df2 = ak.stock_zt_pool_dt_em(date=target_date)
            count2 = 0
            for _, row in df2.iterrows():
                symbol = str(row.get("代码", "")).strip().zfill(6)
                if not symbol:
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO zt_pool_dt
                       (date, symbol, name, close_price, dt_price)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
                        symbol,
                        row.get("名称", ""),
                        float(row.get("最新价", 0)),
                        float(row.get("跌停价", 0)),
                    ),
                )
                count2 += 1
            conn.commit()
            logger.info(f"✅ 跌停池写入 {count2} 条")
        except Exception as e:
            logger.warning(f"跌停池采集失败: {e}")

        conn.close()
    except ImportError:
        logger.warning("akshare 未安装，跳过涨停池采集")
    except Exception as e:
        logger.error(f"涨停池采集异常: {e}")


# ============================================================
# 3. 概念板块采集（AKShare）
# ============================================================

def collect_concepts():
    """采集全市场概念板块"""
    _force_ipv4()
    try:
        import akshare as ak

        conn = _get_conn()
        total_concepts = 0
        total_maps = 0

        # 行业板块
        try:
            df_ind = ak.stock_board_industry_name_em()
            for _, row in df_ind.iterrows():
                code = row.get("板块代码", "")
                name = row.get("板块名称", "")
                if code and name:
                    conn.execute(
                        "INSERT OR REPLACE INTO stock_concepts (code, name, category) VALUES (?, ?, 'industry')",
                        (code, name),
                    )
                    total_concepts += 1
                    # 取该板块个股
                    try:
                        cons = ak.stock_board_industry_cons_em(symbol=name)
                        for _, c in cons.iterrows():
                            sym = str(c.get("代码", "")).zfill(6)
                            cname = c.get("名称", "")
                            if sym:
                                conn.execute(
                                    "INSERT OR REPLACE INTO stock_concept_map (symbol, name, concept_code, concept_name) VALUES (?, ?, ?, ?)",
                                    (sym, cname, code, name),
                                )
                                total_maps += 1
                    except Exception:
                        pass
            logger.info(f"✅ 行业板块: {total_concepts} 个")
            conn.commit()
        except Exception as e:
            logger.warning(f"行业板块采集失败: {e}")

        # 概念板块
        try:
            df_con = ak.stock_board_concept_name_em()
            con_count = 0
            for _, row in df_con.iterrows():
                code = row.get("板块代码", "")
                name = row.get("板块名称", "")
                if code and name:
                    conn.execute(
                        "INSERT OR REPLACE INTO stock_concepts (code, name, category) VALUES (?, ?, 'concept')",
                        (code, name),
                    )
                    con_count += 1
                    try:
                        cons = ak.stock_board_concept_cons_em(symbol=name)
                        for _, c in cons.iterrows():
                            sym = str(c.get("代码", "")).zfill(6)
                            cname = c.get("名称", "")
                            if sym:
                                conn.execute(
                                    "INSERT OR REPLACE INTO stock_concept_map (symbol, name, concept_code, concept_name) VALUES (?, ?, ?, ?)",
                                    (sym, cname, code, name),
                                )
                                total_maps += 1
                    except Exception:
                        pass
            logger.info(f"✅ 概念板块: {con_count} 个, 共计映射 {total_maps} 条")
            conn.commit()
        except Exception as e:
            logger.warning(f"概念板块采集失败: {e}")

        conn.close()
    except ImportError:
        logger.warning("akshare 未安装，跳过概念采集")
    except Exception as e:
        logger.error(f"概念采集异常: {e}")


# ============================================================
# 4. 盘中实时快照（腾讯接口）
# ============================================================

def collect_realtime(watch_codes: list = None):
    """采集一次盘中实时行情，写入 realtime_snapshot 表"""
    if watch_codes is None:
        # 默认取 zt_pool 中的股票 + 自选股
        conn = _get_conn()
        codes = set()
        try:
            for (sym,) in conn.execute("SELECT symbol FROM zt_pool WHERE date=(SELECT MAX(date) FROM zt_pool) LIMIT 50"):
                codes.add(sym[0])
        except Exception:
            pass
        try:
            for (sym,) in conn.execute("SELECT symbol FROM favorites LIMIT 50"):
                codes.add(sym[0])
        except Exception:
            pass
        conn.close()
        if not codes:
            logger.warning("没有关注股，使用默认代码")
            codes = {"000001", "600519", "000858", "002415"}
        watch_codes = list(codes)[:50]

    now = datetime.now()
    snap_date = now.strftime("%Y-%m-%d")
    snap_time = now.strftime("%H:%M:%S")

    # 加前缀：6开头=sh, 其余=sz
    prefixed = []
    code_map = {}
    for c in watch_codes:
        c = c.strip()
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        else:
            prefixed.append(f"sz{c}")
        code_map[prefixed[-1]] = c

    if not prefixed:
        return

    url = "http://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gbk")
    except Exception as e:
        logger.error(f"腾讯接口失败: {e}")
        return

    rows = []
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
            raw_code = parts[0].split("_")[-1]
            symbol = code_map.get(raw_code, fields[2])
            rows.append((
                snap_time, snap_date, symbol,
                fields[1],  # name
                float(fields[3]) if fields[3] else 0,  # price
                float(fields[4]) if fields[4] else 0,  # pre_close
                round((float(fields[3]) / float(fields[4]) - 1) * 100, 2) if fields[3] and fields[4] else 0,
                int(fields[6]) if fields[6] else 0,  # volume
                float(fields[33]) if fields[33] else 0,  # high
                float(fields[34]) if fields[34] else 0,  # low
                float(fields[27]) if fields[27] else 0,  # bid1
                int(fields[28]) if fields[28] else 0,  # bid1_vol
                float(fields[29]) if fields[29] else 0,  # ask1
                int(fields[30]) if fields[30] else 0,  # ask1_vol
                round(float(fields[4]) * 1.1, 2) if fields[4] else 0,  # zt_price
                round(float(fields[4]) * 0.9, 2) if fields[4] else 0,  # dt_price
            ))
        except (ValueError, IndexError) as e:
            continue

    conn = _get_conn()
    conn.execute("BEGIN")
    for r in rows:
        conn.execute(
            """INSERT OR REPLACE INTO realtime_snapshot
               (snap_time, snap_date, symbol, name, price, pre_close, pct,
                volume, high, low, bid1, bid1_vol, ask1, ask1_vol, zt_price, dt_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            r,
        )
    conn.commit()
    conn.close()
    logger.info(f"✅ 实时快照: {len(rows)} 只, {snap_date} {snap_time}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据准备模块")
    parser.add_argument("--init-db", action="store_true", help="初始化新表")
    parser.add_argument("--zt-pool", action="store_true", help="采集昨日涨停/跌停池")
    parser.add_argument("--zt-pool-date", type=str, help="指定涨停池日期 YYYYMMDD")
    parser.add_argument("--concepts", action="store_true", help="采集全市场概念板块")
    parser.add_argument("--realtime", action="store_true", help="采集一次盘中实时行情")
    parser.add_argument("--anomaly", action="store_true", help="采集盘口异动数据")
    parser.add_argument("--anomaly-watch", action="store_true", help="仅采关注池盘口异动")
    parser.add_argument("--all", action="store_true", help="全量采集（init-db + zt-pool + concepts + anomaly）")

    args = parser.parse_args()

    if args.init_db or args.all:
        init_db()

    if args.zt_pool or args.all:
        collect_zt_pool(args.zt_pool_date)

    if args.concepts or args.all:
        collect_concepts()

    if args.realtime:
        collect_realtime()

    if args.anomaly or args.anomaly_watch or args.all:
        try:
            from market_anomaly_collector import collect_anomaly
            result = collect_anomaly(watch_only=args.anomaly_watch)
            logger.info(f"盘口异动: {result['records_written']} 条写入")
        except ImportError as e:
            logger.warning(f"盘口异动采集模块不可用: {e}")
        except Exception as e:
            logger.error(f"盘口异动采集失败: {e}")

    if not any([args.init_db, args.zt_pool, args.concepts, args.realtime, args.anomaly, args.anomaly_watch, args.all]):
        parser.print_help()
        print()
        print("提示: 首次使用请执行 python data_prepare.py --all")

"""
Sequoia-X 数据引擎（已集成到 a-stock-analyst 项目内）

提供：
1. 每日数据同步（baostock → stock_cache.db）
2. 日线数据读取接口
3. 策略运行 + 结果写入 strategy_picks 表
"""

import json
import sqlite3
from pathlib import Path
from datetime import date, datetime
from typing import Optional

from sequoia_x.core.config import Settings
from sequoia_x.data.engine import DataEngine
from sequoia_x.strategy.ma_volume import MaVolumeStrategy
from sequoia_x.strategy.turtle_trade import TurtleTradeStrategy
from sequoia_x.strategy.high_tight_flag import HighTightFlagStrategy
from sequoia_x.strategy.limit_up_shakeout import LimitUpShakeoutStrategy
from sequoia_x.strategy.uptrend_limit_down import UptrendLimitDownStrategy
from sequoia_x.strategy.rps_breakout import RpsBreakoutStrategy

# ── 数据库路径：指向合并后的统一数据库 ──
DB_PATH = str(Path.home() / ".chanlun_pro" / "db" / "chanlun_klines.sqlite")


# ── 策略注册 ──
STRATEGY_META = [
    ("ma_volume",          "均线放量",   "5日线上穿20日线 + 放量1.5倍"),
    ("turtle_trade",       "海龟交易",   "唐奇安通道突破"),
    ("high_tight_flag",    "高窄旗形",   "高窄旗形整理突破"),
    ("limit_up_shakeout",  "涨停洗盘",   "涨停后洗盘再拉升"),
    ("uptrend_limit_down", "跌停反包",   "上升趋势跌停反包"),
    ("rps_breakout",       "RPS突破",   "120日RPS极强动量突破"),
]

STRATEGY_CLASSES = {
    "ma_volume":          MaVolumeStrategy,
    "turtle_trade":       TurtleTradeStrategy,
    "high_tight_flag":    HighTightFlagStrategy,
    "limit_up_shakeout":  LimitUpShakeoutStrategy,
    "uptrend_limit_down": UptrendLimitDownStrategy,
    "rps_breakout":       RpsBreakoutStrategy,
}


def _get_settings():
    """获取 Sequoia-X Settings，数据库指向 Sequoia-X 的 sequoia_v2.db"""
    return Settings(
        db_path=DB_PATH,
        start_date="2024-01-01",
        feishu_webhook_url="http://localhost/unused",
    )


def _get_engine():
    """获取 DataEngine 实例"""
    return DataEngine(_get_settings())


def _init_picks_table():
    """创建 strategy_picks 表（在 DB_PATH 库中）"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_picks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                strategy TEXT NOT NULL,
                symbol TEXT NOT NULL,
                rank INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sp_date ON strategy_picks(date, strategy)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sp_symbol ON strategy_picks(symbol, date)
        """)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════

def check_status() -> dict:
    """检查数据引擎状态"""
    status = {
        "db_exists": Path(DB_PATH).exists(),
        "stock_count": 0,
        "latest_date": None,
        "picks_today": 0,
    }
    if not status["db_exists"]:
        return status
    try:
        conn = sqlite3.connect(DB_PATH)
        # 查 kline_cache 日线数据（统一数据源）
        r = conn.execute("SELECT COUNT(DISTINCT symbol) FROM kline_cache WHERE period='daily' AND source='tencent_fq' AND symbol NOT LIKE '%.%' AND substr(symbol,1,1) IN ('0','3','6','9')").fetchone()
        status["stock_count"] = r[0] if r else 0
        r = conn.execute("SELECT MAX(trade_date) FROM kline_cache WHERE period='daily'").fetchone()
        status["latest_date"] = r[0] if r else None
        # 选股数据最新日期（优先展示 strategy_picks 的最新日期）
        r2 = conn.execute("SELECT MAX(date) FROM strategy_picks").fetchone()
        if r2 and r2[0] and r2[0] > (status["latest_date"] or ""):
            status["latest_date"] = r2[0]
        # 今日选股（非交易日回退最近交易日）
        today = date.today().strftime("%Y-%m-%d")
        r = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM strategy_picks WHERE date=?", (today,)
        ).fetchone()
        picks_count = r[0] if r else 0
        if not picks_count:
            r = conn.execute(
                "SELECT COUNT(DISTINCT symbol) FROM strategy_picks "
                "WHERE date=(SELECT MAX(date) FROM strategy_picks)"
            ).fetchone()
            picks_count = r[0] if r else 0
        status["picks_today"] = picks_count
        conn.close()
    except Exception:
        pass
    return status


def get_daily_kline(symbol: str, start: str = None, end: str = None) -> Optional[list]:
    """从 kline_cache 表读取日线K线（统一数据源，含 amount 成交额）
    兼容 bare code (000001) 和 prefixed code (SH.000001 / SZ.301563)。"""
    if not Path(DB_PATH).exists():
        return None

    # 尝试多种 symbol 格式，优先匹配正确的交易所前缀
    # 裸码→全码转换（库内只有 SH./SZ./BJ. 前缀）
    if "." not in symbol:
        if symbol.startswith("6"):
            symbol = f"SH.{symbol}"
        elif symbol.startswith(("0", "3")):
            symbol = f"SZ.{symbol}"
        elif symbol.startswith(("4", "8")):
            symbol = f"BJ.{symbol}"

    conn = sqlite3.connect(DB_PATH)
    try:
        sql = "SELECT trade_date, open, close, high, low, volume, amount FROM kline_cache WHERE symbol=? AND period='daily'"
        params = [symbol]
        if start:
            sql += " AND trade_date>=?"
            params.append(start)
        if end:
            sql += " AND trade_date<=?"
            params.append(end)
        sql += " ORDER BY trade_date ASC"
        rows = conn.execute(sql, params).fetchall()

        if not rows:
            return None
        return [
            {
                "date": r[0], "open": r[1], "close": r[2], "high": r[3], "low": r[4],
                "volume": r[5], "amount": r[6] if r[6] else 0,
            }
            for r in rows
        ]
    finally:
        conn.close()


def daily_sync(progress_callback=None) -> dict:
    """
    日常同步：增量拉 baostock 数据 + 跑策略 + 写 strategy_picks。

    多线程并行跑策略，每完成一个通过 progress_callback 通知。
    """
    _init_picks_table()
    settings = _get_settings()
    engine = _get_engine()

    # 增量数据同步
    count = engine.sync_today_bulk()
    total_symbols = len(engine.get_local_symbols())

    # 跑全部策略（并行）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    strategies = [
        (key, cls(engine, settings)) for key, cls in STRATEGY_CLASSES.items()
    ]
    all_picks = []
    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM strategy_picks WHERE date=?", (today,))
    conn.commit()
    conn.close()

    total_strategies = len(strategies)
    completed = 0
    _picks_lock = __import__('threading').Lock()

    def _run_one(key, cls_instance):
        try:
            selected = cls_instance.run()
            # 在各线程中创建独立连接写入
            _c = sqlite3.connect(DB_PATH)
            for rank, symbol in enumerate(selected):
                _c.execute(
                    "INSERT INTO strategy_picks (date, strategy, symbol, rank) VALUES (?, ?, ?, ?)",
                    (today, key, symbol, rank),
                )
            _c.commit()
            _c.close()
            with _picks_lock:
                for s in selected:
                    all_picks.append((key, s))
            return {"key": key, "ok": True, "picks": len(selected), "error": None}
        except Exception as e:
            return {"key": key, "ok": False, "picks": 0, "error": str(e)}

    with ThreadPoolExecutor(max_workers=min(total_strategies, 6)) as executor:
        futures = {executor.submit(_run_one, key, cls): key for key, cls in strategies}
        for future in as_completed(futures):
            result = future.result()
            completed += 1
            if progress_callback:
                progress_callback({
                    "strategy": result["key"],
                    "ok": result["ok"],
                    "picks": result["picks"],
                    "completed": completed,
                    "total": total_strategies,
                })
            if not result["ok"]:
                import logging
                logging.getLogger("sequoia_engine").warning(
                    f"[{result['key']}] 策略运行失败: {result['error']}"
                )

    picks_by_strategy = {}
    for key, sym in all_picks:
        picks_by_strategy.setdefault(key, []).append(sym)

    return {
        "status": "ok",
        "sync_count": count,
        "total_symbols": total_symbols,
        "picks": {k: len(v) for k, v in picks_by_strategy.items()},
        "total_picks": len(all_picks),
        "date": today,
    }


def get_todays_picks(strategy: str = None) -> list[dict]:
    """获取当日选股结果"""
    if not Path(DB_PATH).exists():
        return []
    today = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        if strategy:
            rows = conn.execute(
                "SELECT strategy, symbol, rank FROM strategy_picks WHERE date=? AND strategy=? ORDER BY rank",
                (today, strategy)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT strategy, symbol, rank FROM strategy_picks WHERE date=? ORDER BY strategy, rank",
                (today,)
            ).fetchall()
        return [{"strategy": r[0], "symbol": r[1], "rank": r[2], "date": today} for r in rows]
    finally:
        conn.close()


def get_picks_history(days: int = 30, strategy: str = None, symbol: str = None) -> list[dict]:
    """历史选股记录"""
    if not Path(DB_PATH).exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        from datetime import timedelta
        start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        sql = "SELECT date, strategy, symbol, rank FROM strategy_picks WHERE date>=?"
        params = [start]
        if strategy:
            sql += " AND strategy=?"
            params.append(strategy)
        if symbol:
            sql += " AND symbol=?"
            params.append(symbol)
        sql += " ORDER BY date DESC, strategy, rank"
        rows = conn.execute(sql, params).fetchall()
        return [{"date": r[0], "strategy": r[1], "symbol": r[2], "rank": r[3]} for r in rows]
    finally:
        conn.close()


def stock_has_strategy_picks(symbol: str) -> bool:
    """检查个股是否在 strategy_picks 表中有记录（任意日期）"""
    if not Path(DB_PATH).exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        r = conn.execute(
            "SELECT 1 FROM strategy_picks WHERE symbol=? LIMIT 1",
            (symbol,)
        ).fetchone()
        return r is not None
    finally:
        conn.close()


def get_strategy_signals(ticker: str) -> str:
    """个股今日被哪些策略选中（供 AI Agent 使用，返回文本）"""
    data = query_stock_strategies(ticker)
    if not data["strategies"]:
        return ""
    parts = [f"{s['name']} ✓" for s in data["strategies"]]
    return " | ".join(parts)


def query_stock_strategies(symbol: str, max_days: int = 7) -> dict:
    """查询个股在策略数据库中最近被哪些策略选中（结构化结果）

    Args:
        symbol: 股票代码
        max_days: 向前回溯天数

    Returns:
        {
            "symbol": str,
            "name": str,           # 股票名称（可能为空）
            "date": str,           # 最近有数据的日期
            "strategy_count": int,  # 满足的策略数
            "strategies": [         # 策略详情
                {"key": str, "name": str, "rank": int},
            ]
        }
    """
    result = {
        "symbol": symbol,
        "name": _get_stock_name(symbol),
        "date": None,
        "strategy_count": 0,
        "strategies": [],
    }

    if not Path(DB_PATH).exists():
        return result

    from datetime import timedelta
    start = (date.today() - timedelta(days=max_days)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    try:
        # 找到最近有数据的日期
        date_row = conn.execute(
            "SELECT MAX(date) FROM strategy_picks WHERE symbol=? AND date BETWEEN ? AND ?",
            (symbol, start, today)
        ).fetchone()
        latest_date = date_row[0] if date_row and date_row[0] else None
        if not latest_date:
            return result

        result["date"] = latest_date

        # 按策略查 rank
        rows = conn.execute(
            "SELECT strategy, MIN(rank) as best_rank FROM strategy_picks "
            "WHERE symbol=? AND date=? "
            "GROUP BY strategy ORDER BY best_rank ASC",
            (symbol, latest_date)
        ).fetchall()

        name_map = dict((k, n) for k, n, _ in STRATEGY_META)
        strategies = []
        for r in rows:
            strategies.append({
                "key": r[0],
                "name": name_map.get(r[0], r[0]),
                "rank": r[1],
            })

        result["strategies"] = strategies
        result["strategy_count"] = len(strategies)
        return result
    finally:
        conn.close()


def get_multi_strategy_picks(min_count: int = 2, max_count: int = None, days: int = 1) -> list[dict]:
    """获取同时被多个策略选中的股票

    Args:
        min_count: 最少策略数
        max_count: 最多策略数（None 表示不限制上限）
        days: 回溯天数

    Returns:
        [{"symbol": "000001.SZ", "count": 3, "strategies": ["ma_volume", ...],
          "name": ..., "latest_close": ..., "return_20d": ..., "close_20d": ...}, ...]
    """
    if not Path(DB_PATH).exists():
        return []

    from datetime import timedelta
    today = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        # 尝试当日数据，若没有则回退到最近有数据的交易日
        target_date = today
        if days > 1:
            from datetime import timedelta
            start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
            has_data = conn.execute(
                "SELECT 1 FROM strategy_picks WHERE date=? LIMIT 1", (today,)
            ).fetchone()
            if not has_data:
                r = conn.execute(
                    "SELECT MAX(date) FROM strategy_picks WHERE date >= ?", (start,)
                ).fetchone()
                if r and r[0]:
                    target_date = r[0]

        # 按 symbol 分组统计当日命中的策略数
        sql = """
            SELECT symbol, COUNT(DISTINCT strategy) as strategy_count,
                   GROUP_CONCAT(DISTINCT strategy) as strategies
            FROM strategy_picks
            WHERE date=?
            GROUP BY symbol
            HAVING strategy_count >= ?
        """
        params = [target_date, min_count]

        if max_count is not None:
            sql += " AND strategy_count <= ?"
            params.append(max_count)

        sql += " ORDER BY strategy_count DESC, symbol"
        rows = conn.execute(sql, params).fetchall()

        name_map = dict((k, n) for k, n, _ in STRATEGY_META)
        result = []

        # 批量获取股票名称和行情数据
        symbols = [r[0] for r in rows]
        detail_map = {}
        if symbols:
            placeholders = ','.join('?' * len(symbols))
            # 名称
            try:
                name_rows = conn.execute(
                    f"SELECT symbol, name FROM all_stock_info WHERE symbol IN ({placeholders})",
                    symbols
                ).fetchall()
                for nr in name_rows:
                    detail_map.setdefault(nr[0], {})["name"] = nr[1] or ""
            except:
                pass
            # vol20day 量价数据
            try:
                vol_rows = conn.execute(
                    f"""SELECT symbol, latest_close, return_20d, close_20d
                       FROM vol20day WHERE symbol IN ({placeholders})""",
                    symbols
                ).fetchall()
                for vr in vol_rows:
                    d = detail_map.setdefault(vr[0], {})
                    d["latest_close"] = vr[1]
                    d["return_20d"] = round(vr[2], 2) if vr[2] is not None else None
                    d["close_20d"] = vr[3]
            except:
                pass

        for r in rows:
            strat_keys = r[2].split(",") if r[2] else []
            sym = r[0]
            dd = detail_map.get(sym, {})
            result.append({
                "symbol": sym,
                "count": r[1],
                "strategies": strat_keys,
                "strategy_names": [name_map.get(s, s) for s in strat_keys],
                "name": dd.get("name", ""),
                "latest_close": dd.get("latest_close"),
                "return_20d": dd.get("return_20d"),
                "close_20d": dd.get("close_20d"),
                "date": target_date,
            })
        return result
    finally:
        conn.close()


# ── vol20day 表：20日涨幅排序 ──

VOL20DAY_TABLE = "vol20day"


def _init_vol20day_table():
    """创建 vol20day 表（存于 stock_cache.db）"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {VOL20DAY_TABLE} (
                symbol TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                latest_date TEXT,
                latest_close REAL,
                date_20d TEXT,
                close_20d REAL,
                return_20d REAL,
                rank_20d INTEGER,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        # 兼容旧表：如果 name 列不存在则添加
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info({VOL20DAY_TABLE})').fetchall()]
        if 'name' not in cols:
            conn.execute(f'ALTER TABLE {VOL20DAY_TABLE} ADD COLUMN name TEXT DEFAULT ""')
        conn.commit()
    finally:
        conn.close()


def _get_stock_name(code: str) -> str:
    """通过代码获取股票名称

    优先级：
    1. kline_cache 表（如果 stock_daily 有代码直接返回代码）
    2. 尝试从 stock_daily 表获取
    """
    conn = sqlite3.connect(DB_PATH)
    try:
        # 从 kline_cache 获取（如果有股票名称字段）
        try:
            r = conn.execute(
                "SELECT symbol FROM kline_cache WHERE symbol=? AND source='baostock' LIMIT 1",
                (code,)
            ).fetchone()
            if r:
                return r[0]
        except Exception:
            pass
        # 从 stock_daily 提取代码（用代码本身作为临时名称）
        return ""
    finally:
        conn.close()


def refresh_vol20day() -> dict:
    """计算并更新 vol20day 表

    筛选规则：
    - 代码以 0 或 6 开头（stock_daily 中暂无 1 开头数据）
    - 不含 ST（stock_daily 无 ST 标记，此处靠前缀过滤）
    - 有完整 20 个交易日的收盘价数据
    - 涨幅 = (最新收盘 - 20日前收盘) / 20日前收盘
    """
    today_str = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(f"DELETE FROM {VOL20DAY_TABLE}")

        rows = conn.execute("""
            WITH ranked AS (
                SELECT symbol, trade_date as date, close,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) as rn
                FROM kline_cache
                WHERE period='daily' AND source='tencent_fq'
                  AND symbol NOT LIKE '%.%'
                  AND SUBSTR(symbol, 1, 1) IN ('0', '3', '6')
            ),
            latest AS (
                SELECT symbol, close as latest_close, date as latest_date
                FROM ranked WHERE rn = 1
                AND close > 0
            ),
            ago20 AS (
                SELECT symbol, close as close_20d, date as date_20d
                FROM ranked WHERE rn = 21
                AND close > 0
            )
            SELECT l.symbol, l.latest_date, l.latest_close,
                   a.date_20d, a.close_20d,
                   (l.latest_close - a.close_20d) / a.close_20d * 100.0 as return_20d
            FROM latest l
            INNER JOIN ago20 a ON l.symbol = a.symbol
            ORDER BY return_20d DESC
        """).fetchall()

        count = 0
        for rank_idx, row in enumerate(rows):
            symbol, latest_date, latest_close, date_20d, close_20d, ret_20d = row
            name = _get_stock_name(symbol)
            conn.execute(
                f"""INSERT OR REPLACE INTO {VOL20DAY_TABLE}
                   (symbol, name, latest_date, latest_close, date_20d, close_20d, return_20d, rank_20d)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, name, latest_date, latest_close, date_20d, close_20d, round(ret_20d, 4), rank_idx + 1)
            )
            count += 1

        conn.commit()
        return {"status": "ok", "total": count, "updated_at": today_str}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
    finally:
        conn.close()


def query_vol20day(min_rank: int = 1, max_rank: int = 100) -> list[dict]:
    """查询20日涨幅排名，从 vol20day 表读取（已预计算）"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        rows = conn.execute("""
            SELECT symbol, latest_date, latest_close,
                   date_20d, close_20d, return_20d, rank_20d
            FROM vol20day
            WHERE rank_20d >= ? AND rank_20d <= ?
            ORDER BY rank_20d
        """, (min_rank, max_rank)).fetchall()

        symbols = [r[0] for r in rows]
        name_map = {}
        if symbols:
            placeholders = ','.join('?' * len(symbols))
            name_rows = conn.execute(
                f"SELECT 股票代码, 股票名称 FROM hzeveryday WHERE 股票代码 IN ({placeholders})",
                symbols
            ).fetchall()
            for code, name in name_rows:
                name_map[code] = name
            # 补漏
            for sym in symbols:
                if sym not in name_map:
                    name_map[sym] = ""

        result = []
        for r in rows:
            symbol, latest_date, latest_close, date_20d, close_20d, ret_20d, rnk = r
            result.append({
                "symbol": symbol,
                "name": name_map.get(symbol, ""),
                "latest_date": latest_date,
                "latest_close": latest_close,
                "date_20d": date_20d,
                "close_20d": close_20d,
                "return_20d": round(ret_20d, 2),
                "rank": rnk,
            })

        return result
    finally:
        conn.close()


def get_vol20day_total() -> int:
    """获取 vol20day 表中已排名的股票总数"""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    try:
        r = conn.execute("SELECT COUNT(*) FROM vol20day").fetchone()
        return r[0] if r else 0
    finally:
        conn.close()


# 启动时初始化 tables
_init_picks_table()
_init_vol20day_table()

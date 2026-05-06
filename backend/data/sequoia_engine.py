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

# ── 数据库路径：统一用 stock_cache.db ──
BASE_DIR = Path(__file__).resolve().parent.parent          # backend/
DB_PATH = str(BASE_DIR / "data" / "stock_cache.db")


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
        # 查 stock_daily 表（Sequoia-X 建的）
        r = conn.execute("SELECT COUNT(DISTINCT symbol) FROM stock_daily").fetchone()
        status["stock_count"] = r[0] if r else 0
        r = conn.execute("SELECT MAX(date) FROM stock_daily").fetchone()
        status["latest_date"] = r[0] if r else None
        # 今日选股
        today = date.today().strftime("%Y-%m-%d")
        r = conn.execute(
            "SELECT COUNT(DISTINCT symbol) FROM strategy_picks WHERE date=?", (today,)
        ).fetchone()
        status["picks_today"] = r[0] if r else 0
        conn.close()
    except Exception:
        pass
    return status


def get_daily_kline(symbol: str, start: str = None, end: str = None) -> Optional[list]:
    """从 stock_daily 表读取日线K线（含 amount 成交额）"""
    if not Path(DB_PATH).exists():
        return None
    conn = sqlite3.connect(DB_PATH)
    try:
        sql = "SELECT date, open, high, low, close, volume, turnover FROM stock_daily WHERE symbol=?"
        params = [symbol]
        if start:
            sql += " AND date>=?"
            params.append(start)
        if end:
            sql += " AND date<=?"
            params.append(end)
        sql += " ORDER BY date ASC"
        rows = conn.execute(sql, params).fetchall()
        if not rows:
            return None
        return [
            {
                "date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4],
                "volume": r[5], "amount": r[6] if r[6] else 0,
            }
            for r in rows
        ]
    finally:
        conn.close()


def daily_sync() -> dict:
    """
    日常同步：增量拉 baostock 数据 + 跑策略 + 写 strategy_picks。
    """
    _init_picks_table()
    settings = _get_settings()
    engine = _get_engine()

    # 增量数据同步
    count = engine.sync_today_bulk()
    total_symbols = len(engine.get_local_symbols())

    # 跑全部策略
    strategies = [
        (key, cls(engine, settings)) for key, cls in STRATEGY_CLASSES.items()
    ]
    all_picks = []
    today = date.today().strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM strategy_picks WHERE date=?", (today,))

    for key, strategy in strategies:
        try:
            selected = strategy.run()
            for rank, symbol in enumerate(selected):
                conn.execute(
                    "INSERT INTO strategy_picks (date, strategy, symbol, rank) VALUES (?, ?, ?, ?)",
                    (today, key, symbol, rank),
                )
                all_picks.append((key, symbol))
        except Exception as e:
            import logging
            logging.getLogger("sequoia_engine").warning(f"[{key}] 策略运行失败: {e}")

    conn.commit()
    conn.close()

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
    """个股今日被哪些策略选中（供 AI Agent 使用）"""
    if not Path(DB_PATH).exists():
        return ""
    today = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT DISTINCT strategy FROM strategy_picks WHERE symbol=? AND date=?",
            (ticker, today)
        ).fetchall()
        if not rows:
            return ""
        name_map = dict((k, n) for k, n, _ in STRATEGY_META)
        parts = [f"{name_map.get(r[0], r[0])} ✓" for r in rows]
        return " | ".join(parts)
    finally:
        conn.close()


def get_multi_strategy_picks(min_count: int = 2, max_count: int = None, days: int = 1) -> list[dict]:
    """获取同时被多个策略选中的股票

    Args:
        min_count: 最少策略数
        max_count: 最多策略数（None 表示不限制上限）
        days: 回溯天数

    Returns:
        [{"symbol": "000001.SZ", "count": 3, "strategies": ["ma_volume", ...]}, ...]
    """
    if not Path(DB_PATH).exists():
        return []

    from datetime import timedelta
    start = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    today = date.today().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    try:
        # 按 symbol 分组统计当日命中的策略数
        sql = """
            SELECT symbol, COUNT(DISTINCT strategy) as strategy_count,
                   GROUP_CONCAT(DISTINCT strategy) as strategies
            FROM strategy_picks
            WHERE date=?
            GROUP BY symbol
            HAVING strategy_count >= ?
        """
        params = [today, min_count]

        if max_count is not None:
            sql += " AND strategy_count <= ?"
            params.append(max_count)

        sql += " ORDER BY strategy_count DESC, symbol"
        rows = conn.execute(sql, params).fetchall()

        name_map = dict((k, n) for k, n, _ in STRATEGY_META)
        result = []
        for r in rows:
            strat_keys = r[2].split(",") if r[2] else []
            result.append({
                "symbol": r[0],
                "count": r[1],
                "strategies": strat_keys,
                "strategy_names": [name_map.get(s, s) for s in strat_keys],
                "date": today,
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
                latest_date TEXT,
                latest_close REAL,
                date_20d TEXT,
                close_20d REAL,
                return_20d REAL,
                rank_20d INTEGER,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()
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

        # 使用窗口函数获取每只股票的最新日期和第21行（20日前的数据）
        # SQL 先得到每只股票按日期降序的排位
        rows = conn.execute("""
            WITH ranked AS (
                SELECT symbol, date, close,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                FROM stock_daily
                WHERE SUBSTR(symbol, 1, 1) IN ('0', '6')
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
            conn.execute(
                f"""INSERT OR REPLACE INTO {VOL20DAY_TABLE}
                   (symbol, latest_date, latest_close, date_20d, close_20d, return_20d, rank_20d)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (symbol, latest_date, latest_close, date_20d, close_20d, round(ret_20d, 4), rank_idx + 1)
            )
            count += 1

        conn.commit()
        return {"status": "ok", "total": count, "updated_at": today_str}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
    finally:
        conn.close()


def query_vol20day(min_rank: int = 1, max_rank: int = 100) -> list[dict]:
    """查询 vol20day 表中指定排名的股票"""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            f"""SELECT symbol, latest_date, latest_close, date_20d, close_20d,
                      return_20d, rank_20d
               FROM {VOL20DAY_TABLE}
               WHERE rank_20d >= ? AND rank_20d <= ?
               ORDER BY rank_20d""",
            (min_rank, max_rank)
        ).fetchall()
        result = []
        for r in rows:
            result.append({
                "symbol": r[0],
                "latest_date": r[1],
                "latest_close": r[2],
                "date_20d": r[3],
                "close_20d": r[4],
                "return_20d": r[5],
                "rank": r[6],
            })
        return result
    finally:
        conn.close()


def get_vol20day_total() -> int:
    """获取 vol20day 表中的总记录数"""
    conn = sqlite3.connect(DB_PATH)
    try:
        r = conn.execute(f"SELECT COUNT(*) FROM {VOL20DAY_TABLE}").fetchone()
        return r[0] if r else 0
    finally:
        conn.close()


# 启动时初始化 tables
_init_picks_table()
_init_vol20day_table()

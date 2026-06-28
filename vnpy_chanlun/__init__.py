"""
vnpy_chanlun — VeighNa 数据库适配器

让 VeighNa 直接读写 chanlun-pro 的 chanlun_klines.sqlite。
用法：在 VeighNa 配置中设置 database.name = "chanlun"，并将此包加入 PYTHONPATH。
"""
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData, TickData
from vnpy.trader.database import BaseDatabase, BarOverview, TickOverview


# ── chanlun-pro 数据库路径 ──
DB_PATH = Path("/mnt/disk990g/sqlite-data/chanlun_klines.sqlite")


# ── 交易所推导 ──
def _symbol_to_exchange(symbol: str) -> Exchange:
    """A股代码 → VeighNa Exchange 枚举"""
    s = symbol.lstrip("sh").lstrip("sz").lstrip("bj")
    if s.startswith(("60", "68")):
        return Exchange.SSE
    elif s.startswith(("00", "30", "002")):
        return Exchange.SZSE
    elif s.startswith(("8", "4")):
        return Exchange.BSE
    return Exchange.SSE  # fallback


# ── Interval 映射：chanlun-pro → VeighNa ──
_PERIOD_TO_INTERVAL: dict[str, Interval] = {
    "daily": Interval.DAILY,
    "weekly": Interval.WEEKLY,
    "monthly": Interval.WEEKLY,  # VeighNa 无 monthly，归到 WEEKLY
    "15min": Interval.MINUTE,
    "30min": Interval.MINUTE,
    "60min": Interval.HOUR,
}

# 反向映射（Interval → kline_cache period，仅用于分钟级）
_INTERVAL_TO_PERIOD: dict[Interval, str] = {
    Interval.MINUTE: "15min",   # 默认用 15min
    Interval.HOUR: "60min",
    Interval.DAILY: "daily",
    Interval.WEEKLY: "weekly",
}


# ── 通用 DB 连接（只读查询用） ──
def _get_conn(readonly: bool = True) -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(f"chanlun-pro 数据库不存在: {DB_PATH}")
    if readonly:
        uri = f"file:{DB_PATH}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── 数据行 → BarData ──
def _row_to_bar(row: sqlite3.Row, symbol: str, exchange: Exchange, interval: Interval) -> BarData:
    """将 SQLite 行转为 VeighNa BarData"""
    # 处理日期字段
    dt_str = row["date"]
    if isinstance(dt_str, str):
        dt = datetime.strptime(dt_str, "%Y-%m-%d")
    else:
        dt = dt_str  # 已是 datetime

    return BarData(
        symbol=symbol,
        exchange=exchange,
        datetime=dt,
        interval=interval,
        open_price=float(row["open"] or 0),
        high_price=float(row["high"] or 0),
        low_price=float(row["low"] or 0),
        close_price=float(row["close"] or 0),
        volume=float(row["volume"] or 0),
        turnover=float(row["turnover"] if "turnover" in row.keys() else (row["amount"] if "amount" in row.keys() else 0)),
        open_interest=0,
        gateway_name="VN",
    )


# ══════════════════════════════════════════════
#  Database 适配器
# ══════════════════════════════════════════════

class Database(BaseDatabase):
    """
    VeighNa → chanlun-pro 数据库适配器。

    读取：
     - 日线/周线 → stock_daily / stock_kline_weekly
     - 分钟线 → kline_cache

    写入：
     - 日线/周线 → stock_daily（upsert 模式）
     - 分钟线 → kline_cache（upsert 模式）
    """

    name = "chanlun"

    # ── 查询 ──────────────────────────────────

    def load_bar_data(
        self,
        symbol: str,
        exchange: Exchange,
        interval: Interval,
        start: datetime,
        end: datetime,
    ) -> list[BarData]:
        conn = _get_conn(readonly=True)
        try:
            rows = self._query_bars(conn, symbol, interval, start, end)
            return [_row_to_bar(r, symbol, exchange, interval) for r in rows]
        finally:
            conn.close()

    def _query_bars(self, conn, symbol: str, interval: Interval, start: datetime, end: datetime):
        """根据 interval 选择正确的表和 SQL"""
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        if interval == Interval.DAILY:
            sql = """
                SELECT date, open, high, low, close, volume, turnover
                FROM stock_daily
                WHERE symbol = ? AND date >= ? AND date <= ?
                ORDER BY date ASC
            """
            return conn.execute(sql, (symbol, start_str, end_str)).fetchall()

        elif interval == Interval.WEEKLY:
            # 优先用 stock_kline_weekly，回退到 stock_daily 聚合
            try:
                sql = """
                    SELECT date, open, high, low, close, volume, turnover
                    FROM stock_kline_weekly
                    WHERE symbol = ? AND date >= ? AND date <= ?
                    ORDER BY date ASC
                """
                rows = conn.execute(sql, (symbol, start_str, end_str)).fetchall()
                if rows:
                    return rows
            except sqlite3.OperationalError:
                pass  # 表不存在，跳过

            # 回退：从 stock_daily 做周聚合
            sql = """
                SELECT 
                    MIN(date) AS date,
                    FIRST_VALUE(open) OVER win AS open,
                    MAX(high) AS high,
                    MIN(low) AS low,
                    LAST_VALUE(close) OVER win AS close,
                    SUM(volume) AS volume,
                    SUM(turnover) AS turnover
                FROM stock_daily
                WHERE symbol = ? AND date >= ? AND date <= ?
                GROUP BY strftime('%Y-%W', date)
                WINDOW win AS (PARTITION BY strftime('%Y-%W', date) ORDER BY date 
                               RANGE BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
                ORDER BY date ASC
            """
            return conn.execute(sql, (symbol, start_str, end_str)).fetchall()

        elif interval in (Interval.MINUTE, Interval.HOUR):
            period = _INTERVAL_TO_PERIOD.get(interval, "60min")
            sql = """
                SELECT trade_date AS date, open, close, high, low, volume, 
                       COALESCE(amount, 0) AS turnover
                FROM kline_cache
                WHERE symbol = ? AND period = ? AND trade_date >= ? AND trade_date <= ?
                ORDER BY trade_date ASC
            """
            return conn.execute(sql, (symbol, period, start_str, end_str)).fetchall()

        return []

    def load_tick_data(
        self, symbol: str, exchange: Exchange, start: datetime, end: datetime
    ) -> list[TickData]:
        # chanlun-pro 没有 tick 数据
        return []

    # ── 写入 ──────────────────────────────────

    def save_bar_data(self, bars: list[BarData], stream: bool = False) -> bool:
        if not bars:
            return True

        conn = _get_conn(readonly=False)
        try:
            for bar in bars:
                self._upsert_bar(conn, bar)
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _upsert_bar(self, conn, bar: BarData):
        date_str = bar.datetime.strftime("%Y-%m-%d")
        if bar.interval in (Interval.DAILY, Interval.WEEKLY):
            table = "stock_daily" if bar.interval == Interval.DAILY else "stock_kline_weekly"
            sql = f"""
                INSERT INTO {table} (symbol, date, open, high, low, close, volume, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, date) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume, turnover=excluded.turnover
            """
            conn.execute(sql, (
                bar.symbol, date_str,
                bar.open_price, bar.high_price, bar.low_price, bar.close_price,
                bar.volume, bar.turnover,
            ))
        else:
            period = _INTERVAL_TO_PERIOD.get(bar.interval, "60min")
            sql = """
                INSERT INTO kline_cache (symbol, source, period, trade_date, open, close, high, low, volume, amount)
                VALUES (?, 'vnpy', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, source, period, trade_date) DO UPDATE SET
                    open=excluded.open, close=excluded.close, high=excluded.high,
                    low=excluded.low, volume=excluded.volume, amount=excluded.amount
            """
            conn.execute(sql, (
                bar.symbol, period, date_str,
                bar.open_price, bar.close_price, bar.high_price, bar.low_price,
                bar.volume, bar.turnover,
            ))

    def save_tick_data(self, ticks: list[TickData], stream: bool = False) -> bool:
        # tick 数据暂不支持
        return True

    # ── 删除 ──────────────────────────────────

    def delete_bar_data(self, symbol: str, exchange: Exchange, interval: Interval) -> int:
        conn = _get_conn(readonly=False)
        try:
            if interval == Interval.DAILY:
                cur = conn.execute("DELETE FROM stock_daily WHERE symbol = ?", (symbol,))
            elif interval == Interval.WEEKLY:
                cur = conn.execute("DELETE FROM stock_kline_weekly WHERE symbol = ?", (symbol,))
            else:
                period = _INTERVAL_TO_PERIOD.get(interval, "60min")
                cur = conn.execute(
                    "DELETE FROM kline_cache WHERE symbol = ? AND source = 'vnpy' AND period = ?",
                    (symbol, period),
                )
            conn.commit()
            return cur.rowcount
        except Exception:
            conn.rollback()
            return 0
        finally:
            conn.close()

    def delete_tick_data(self, symbol: str, exchange: Exchange) -> int:
        return 0

    # ── 概览 ──────────────────────────────────

    def get_bar_overview(self) -> list[BarOverview]:
        conn = _get_conn(readonly=True)
        try:
            results = []

            # 日线
            sql = """
                SELECT symbol, COUNT(*) as cnt, MIN(date) as start, MAX(date) as end
                FROM stock_daily GROUP BY symbol
            """
            for row in conn.execute(sql).fetchall():
                results.append(BarOverview(
                    symbol=row["symbol"],
                    exchange=_symbol_to_exchange(row["symbol"]),
                    interval=Interval.DAILY,
                    count=row["cnt"],
                    start=datetime.strptime(row["start"], "%Y-%m-%d"),
                    end=datetime.strptime(row["end"], "%Y-%m-%d"),
                ))

            # 分钟线
            sql = """
                SELECT symbol, period, COUNT(*) as cnt, MIN(trade_date) as start, MAX(trade_date) as end
                FROM kline_cache WHERE period IN ('15min','30min','60min')
                GROUP BY symbol, period
            """
            for row in conn.execute(sql).fetchall():
                interval = Interval.HOUR if row["period"] == "60min" else Interval.MINUTE
                results.append(BarOverview(
                    symbol=row["symbol"],
                    exchange=_symbol_to_exchange(row["symbol"]),
                    interval=interval,
                    count=row["cnt"],
                    start=datetime.strptime(row["start"], "%Y-%m-%d"),
                    end=datetime.strptime(row["end"], "%Y-%m-%d"),
                ))

            return results
        finally:
            conn.close()

    def get_tick_overview(self) -> list[TickOverview]:
        return []


# ── 便捷函数：直接获取 A 股日线 ──
def get_daily_bars(symbol: str, start: str = "2020-01-01", end: str | None = None) -> list[BarData]:
    """快捷接口：获取 A 股日线 BarData 列表"""
    if end is None:
        end = date.today().strftime("%Y-%m-%d")
    db = Database()
    return db.load_bar_data(
        symbol=symbol,
        exchange=_symbol_to_exchange(symbol),
        interval=Interval.DAILY,
        start=datetime.strptime(start, "%Y-%m-%d"),
        end=datetime.strptime(end, "%Y-%m-%d"),
    )
